"""Understander (UnderstandingPort): raw text or one key in, Understanding out (docs/SPEC.md §3, §8.7-§8.8).

One turn: normalize -> redact digits -> keyword intents -> rule parser -> fast path? -> at most ONE model call within
the turn deadline -> merge and grounding. A keypad turn never calls the model. The model is skipped in closed mode,
when no client exists (no key: closed mode for the whole app), over the daily turn cap, and on the fast path (an
utterance of three words or fewer that the parser maps confidently to the pending question, with no keyword intent).

The deadline is an absolute value on the injected clock's monotonic scale (the dialogue computes it from the turn
budget); the model gets min(GP_LLM_TIMEOUT_S, deadline - now - 0.15 s), and the turn returns within the deadline
plus a few milliseconds even when the provider hangs. Nothing here is persisted or logged with content.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gatorplate.contracts.common import Lang, SlotSource
from gatorplate.contracts.extraction import ExtractOutcome, Intent, PendingQuestion, Understanding
from gatorplate.contracts.slots import SlotName
from gatorplate.extract.bank import Bank
from gatorplate.extract.conversion import Conversion
from gatorplate.extract.guards import load_guards
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.llm.anthropic_client import AnthropicClient
from gatorplate.extract.llm.base import DailyCounter, LLMClient, MemoryCounter, UsageMetrics
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.merge import Merger
from gatorplate.extract.parser import Parsed, Parser
from gatorplate.extract.prompt import SYSTEM_PROMPT, output_schema, user_message
from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import guess_lang, normalize, word_count

log = logging.getLogger("gatorplate.extract")
_SLOT_NAMES = frozenset(SlotName.__members__) | frozenset(SlotName)
DEADLINE_MARGIN_S = 0.15  # the model must answer this long before the turn deadline
HARD_CAP_S = 0.02  # extra time the port waits for a client that ignores its own timeout
FAST_PATH_WORDS = 3
DAILY_KEY = "llm_turns"  # the platform's counters table: one row per Pacific day
_CLOSED_KINDS = ("yes_no", "confirm", "choice")


class _LocalClock:
    """Used only when no Clock is injected (the app injects its own, so the deadline and "now" share one scale)."""

    def __init__(self, tz: str) -> None:
        self._tz = ZoneInfo(tz)

    def monotonic(self) -> float:
        return time.monotonic()

    def today(self) -> date:
        return datetime.now(UTC).astimezone(self._tz).date()


class Understander:
    def __init__(self, *, settings: Any, guards_path: Path | None = None, llm: LLMClient | None = None,
                 counters: DailyCounter | None = None, clock: Any = None) -> None:
        self.settings = settings
        guards = load_guards(guards_path or settings.guards_path)
        self.redactor = Redactor(guards)
        self.keywords = KeywordMatcher(guards)
        self.conversion = Conversion.load(settings.rules_table_path)
        self.bank = Bank.load(Path(settings.content_dir) / "sentences.en.json")
        self.parser = Parser(self.bank, self.conversion)
        self.merger = Merger(self.conversion)
        self.clock = clock or _LocalClock(getattr(settings, "tz", "America/Los_Angeles"))
        self.counters: DailyCounter = counters or MemoryCounter()
        self.daily_cap = int(settings.llm_daily_turn_cap)
        self._capped_on: date | None = None
        self.metrics = UsageMetrics(provider=str(settings.llm_provider))
        self.schema = output_schema()
        if llm is not None:
            self._client: LLMClient | None = llm
            self.metrics = getattr(llm, "metrics", None) or self.metrics
        else:
            self._client = self._build_llm()

    @classmethod
    def from_settings(cls, settings: Any, *, counters: DailyCounter | None = None, clock: Any = None
                      ) -> Understander:
        return cls(settings=settings, guards_path=settings.guards_path, counters=counters, clock=clock)

    def _build_llm(self) -> LLMClient | None:
        s = self.settings
        if s.llm_provider == "fake":
            return FakeLLM(redactor=self.redactor, parser=self.parser, keywords=self.keywords, metrics=self.metrics)
        key = s.llm_api_key.get_secret_value()
        if not key:
            self.metrics.status = "no_key"
            return None  # no client without a key: closed mode
        return AnthropicClient(api_key=key, base_url=s.llm_base_url, model=s.llm_model,
                               fallback_model=s.llm_fallback_model, hedge_ms=s.llm_hedge_ms, metrics=self.metrics)

    @property
    def llm(self) -> LLMClient | None:
        """The model client, or None when there is none (no key) or when today's turn cap is used up; the dialogue
        then starts new calls in closed mode."""
        if self._client is None or self.daily_cap <= 0:
            return None
        if self._capped_on is not None and self._capped_on == self.clock.today():
            return None
        return self._client

    def _take_turn(self) -> bool:
        """Count one model turn for today (Pacific date); False once GP_LLM_DAILY_TURN_CAP is passed."""
        today = self.clock.today()
        if self.counters.incr(DAILY_KEY, today) > self.daily_cap:
            self._capped_on = today
            return False
        return True

    # ------------------------------------------------------------------------------------------ health
    def llm_health(self) -> dict[str, Any]:
        """`/healthz` llm part: {provider, status (no_key | ready | ok | error), last_ok_at, usage}."""
        snap = self.metrics.snapshot()
        snap["provider"] = str(self.settings.llm_provider)
        if self._client is None:
            snap["status"] = "no_key"
        return snap

    # ------------------------------------------------------------------------------------------ port
    async def understand(self, *, text: str, masked: bool, confidence: float | None, dtmf: str | None,
                         pending: PendingQuestion | None, known: dict[SlotName, str], recent: list[str],
                         last_prompt: str | None, lang: Lang, deadline: float, closed_mode: bool) -> Understanding:
        session_lang = Lang(lang).value if lang else "en"
        known = {SlotName(k): str(v) for k, v in (known or {}).items() if k in _SLOT_NAMES and v is not None}
        if dtmf is not None and not (text or "").strip():
            return self._keypad(dtmf, pending, known, session_lang)

        redaction = self.redactor.redact(normalize(text), masked=masked)
        utterance = redaction.text
        keyword_intents = self.keywords.match(utterance)
        try:
            parsed = self.parser.parse(utterance, pending, known, session_lang)
        except Exception as exc:  # noqa: BLE001 - a parser bug must never break a turn; the model still listens
            log.warning(json.dumps({"event": "parser_error", "error": type(exc).__name__}))
            parsed = Parsed()
        result = ExtractOutcome(status="skipped")
        if utterance and self.llm is not None and not closed_mode \
                and not self._fast(utterance, parsed, keyword_intents, pending, session_lang) and self._take_turn():
            memory = [self.redactor.redact(normalize(r)).text for r in (recent or [])[-2:]]
            prompt = user_message(utterance=utterance, pending=pending, known=known, recent=memory,
                                  last_prompt=last_prompt)
            result = await self._call(self._timeout(deadline), prompt)
        merged = self.merger.merge(utterance=utterance, llm=result, parsed=parsed, keyword_intents=keyword_intents,
                                   pending=pending, known=known, session_lang=session_lang)
        return Understanding(
            redacted_text=utterance, observations=merged.observations, intents=merged.intents,
            lang=merged.lang if utterance else Lang(session_lang),
            answered_pending=merged.answered_pending,  # type: ignore[arg-type]
            side_question=merged.side_question, requested_language=merged.requested_language, llm=result,
            sources=merged.sources, redactions=list(redaction.kinds), keyword_intents=keyword_intents,
            teen_ty=merged.teen_ty)

    # ------------------------------------------------------------------------------------------ internals
    def _keypad(self, key: str, pending: PendingQuestion | None, known: dict[SlotName, str],
                session_lang: str) -> Understanding:
        parsed = self.parser.parse_key(key, pending, known)
        answered = "yes" if not parsed.invalid_key and (
            parsed.observations or parsed.intents or parsed.answer or (pending is not None and not pending.slots)
        ) else "no"
        return Understanding(redacted_text="", observations=parsed.observations, intents=parsed.intents,
                             lang=Lang(session_lang), answered_pending=answered,  # type: ignore[arg-type]
                             llm=ExtractOutcome(status="skipped"),
                             sources={o.slot: SlotSource.keypad for o in parsed.observations})

    @staticmethod
    def _fast(utterance: str, parsed: Parsed, keyword_intents: list[Intent], pending: PendingQuestion | None,
              session_lang: str) -> bool:
        """No model call for a short, confident answer to the pending question. A Spanish answer still goes to the
        model, which writes the English gloss the console shows next to the quote."""
        if pending is None or keyword_intents or not parsed.confident or parsed.intents:
            return False
        if word_count(utterance) > FAST_PATH_WORDS or guess_lang(utterance, default=session_lang) == "es":
            return False
        return pending.kind in _CLOSED_KINDS or pending.closed or (pending.kind == "number" and len(pending.slots) == 1)

    def _timeout(self, deadline: float) -> float:
        budget = float(self.settings.turn_budget_s)
        remaining = deadline - self.clock.monotonic()
        if remaining > budget + 1.0 or remaining < -5.0:
            remaining = budget  # a deadline on another clock's scale: fall back to the configured turn budget
        return max(0.0, min(float(self.settings.llm_timeout_s), remaining - DEADLINE_MARGIN_S))

    async def _call(self, timeout_s: float, prompt: str) -> ExtractOutcome:
        client = self._client
        assert client is not None
        model = getattr(client, "model", None)
        if timeout_s <= 0:
            return ExtractOutcome(status="timeout", model=model)
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout_s + HARD_CAP_S):
                return await client.complete(SYSTEM_PROMPT, prompt, self.schema, timeout_s)
        except TimeoutError:
            result = ExtractOutcome(status="timeout", model=model, latency_ms=int((time.monotonic() - started) * 1000))
        except Exception:  # noqa: BLE001 - a provider bug must never break a turn; the parser takes over
            result = ExtractOutcome(status="error", model=model, latency_ms=int((time.monotonic() - started) * 1000))
        self.metrics.record(result)
        return result

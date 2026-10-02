"""The fake provider: deterministic, no network. Tests, local runs and the emergency switch use it.

It answers from an exact-utterance table built from data/tests/utterances.jsonl (keyed by the redacted, normalized
utterance, so the contract examples and the end-to-end scripts replay the same extraction). An entry recorded for a
different question is used only when its facts do not depend on that question (a "No." recorded for the rent flip is
not reused for the consent question). Any other utterance gets the rule parser plus the keyword lists. A delay and
failures can be injected for tests: `delay_s`, and `fail` = a list of "timeout" | "error" | "invalid" | "refused"
consumed one per call.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome, Intent, PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.llm.base import UsageMetrics, outcome
from gatorplate.extract.parser import Parser, fmt
from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import guess_lang, normalize

DEFAULT_TABLE = Path(__file__).resolve().parents[3] / "data" / "tests" / "utterances.jsonl"
_RESULT_KEYS = ("observations", "intents", "answered_pending", "lang", "side_question", "requested_language")


@dataclass(frozen=True)
class _Entry:
    pending_key: str | None
    pending_slots: tuple[str, ...]
    known: dict[str, str]
    result: ExtractionResult


class FakeLLM:
    provider = "fake"

    def __init__(self, *, table_path: Path | None = None, redactor: Redactor | None = None,
                 parser: Parser | None = None, keywords: KeywordMatcher | None = None, delay_s: float = 0.0,
                 fail: list[str] | None = None, metrics: UsageMetrics | None = None) -> None:
        self.model = "fake"
        self.redactor = redactor or Redactor()
        self.parser = parser or Parser()
        self.keywords = keywords or KeywordMatcher()
        self.delay_s = delay_s
        self.fail = list(fail or [])
        self.metrics = metrics or UsageMetrics(provider=self.provider)
        self.metrics.provider = self.provider
        self.table = self._load(table_path or DEFAULT_TABLE)
        self.calls = 0

    def _load(self, path: Path) -> dict[str, list[_Entry]]:
        table: dict[str, list[_Entry]] = {}
        if not path.exists():
            return table
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            expect = row["expect"]
            result = ExtractionResult.model_validate({k: expect[k] for k in _RESULT_KEYS})
            pending = row.get("pending") or {}
            key = self.redactor.redact(normalize(row["utterance"]), masked=bool(row.get("masked"))).text
            table.setdefault(key, []).append(_Entry(pending.get("key"), tuple(pending.get("slots") or ()),
                                                    dict(row.get("known") or {}), result))
        return table

    # ------------------------------------------------------------------------------------------ port
    async def complete(self, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                       ) -> ExtractOutcome:
        started = time.monotonic()
        self.calls += 1
        mode = self.fail.pop(0) if self.fail else None
        delay = self.delay_s if mode != "timeout" else max(self.delay_s, timeout_s + 1.0)
        if delay > 0:
            if delay >= timeout_s:
                await asyncio.sleep(max(0.0, timeout_s))
                return self._done(outcome("timeout", model=self.model), started)
            await asyncio.sleep(delay)
        if mode in ("error", "invalid", "refused"):
            return self._done(outcome(mode, model=self.model), started)  # type: ignore[arg-type]
        data = json.loads(user_json)
        result = self.lookup(data) or self.from_rules(data)
        return self._done(outcome("ok", model=self.model, result=result, input_tokens=0, output_tokens=0), started)

    def _done(self, result: ExtractOutcome, started: float) -> ExtractOutcome:
        result = result.model_copy(update={"latency_ms": int((time.monotonic() - started) * 1000)})
        self.metrics.record(result)
        return result

    # ------------------------------------------------------------------------------------------ table
    def lookup(self, data: dict[str, Any]) -> ExtractionResult | None:
        entries = self.table.get(normalize(data.get("utterance") or ""))
        if not entries:
            return None
        req = data.get("pending") or None
        known = data.get("known") or {}
        chosen: _Entry | None = None
        if req is None:
            chosen = entries[0]
        else:
            req_slots = tuple(req.get("slots") or ())
            for test in (lambda e: e.pending_key == req.get("key"),
                         lambda e: set(e.pending_slots) == set(req_slots),
                         lambda e: not {o.slot.value for o in e.result.observations} & set(e.pending_slots)):
                chosen = next((e for e in entries if test(e)), None)
                if chosen is not None:
                    break
        if chosen is None:
            return None
        result = chosen.result
        # A value recorded as "all of it" follows the rent share known in this call.
        old_rent, new_rent = chosen.known.get("rent_share"), known.get("rent_share")
        if old_rent and new_rent and old_rent != new_rent:
            obs = []
            for o in result.observations:
                if o.slot == SlotName.rent_paid_by_others_to_landlord and _same_amount(o.value, old_rent):
                    o = o.model_copy(update={"value": _plain(new_rent)})
                obs.append(o)
            result = result.model_copy(update={"observations": obs})
        return result

    def from_rules(self, data: dict[str, Any]) -> ExtractionResult:
        """No table entry: the rule parser and the keyword lists answer, as in closed mode."""
        text = normalize(data.get("utterance") or "")
        raw_pending = data.get("pending")
        pending = PendingQuestion.model_validate(raw_pending) if raw_pending else None
        known = {SlotName(k): v for k, v in (data.get("known") or {}).items() if k in SlotName.__members__}
        lang = guess_lang(text)
        parsed = self.parser.parse(text, pending, known, lang)
        intents = list(self.keywords.match(text))
        for intent in parsed.intents + ([Intent.off_topic] if parsed.injection else []):
            if intent not in intents:
                intents.append(intent)
        requested = None
        if Intent.language_request in intents:
            if re.search(r"spanish|espa[nñ]ol", text, re.IGNORECASE):
                requested = "es"
            elif re.search(r"english|ingl[eé]s", text, re.IGNORECASE):
                requested = "en"
        pslots = set(pending.slots) if pending else set()
        got = {o.slot for o in parsed.observations}
        if pslots and pslots <= got:
            answered = "yes"
        elif got or (pslots & got):
            answered = "partial"
        else:
            answered = "yes" if (parsed.answer and pending is not None) else "no"
        return ExtractionResult(observations=parsed.observations, intents=intents, answered_pending=answered,
                                lang=lang, side_question=None, requested_language=requested)  # type: ignore[arg-type]


def _same_amount(a: str, b: str) -> bool:
    try:
        return Decimal(a) == Decimal(b)
    except ArithmeticError:
        return False


def _plain(raw: str) -> str:
    try:
        return fmt(Decimal(raw))
    except ArithmeticError:
        return raw

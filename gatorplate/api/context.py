"""The app context: Deps plus what only the HTTP layer needs (web tokens, counters, rate limits, demo cases, the
janitor, per-call locks), and the shared builders of CaseSummary and CaseDetail.

Programs (docs/SPEC.md §5.10): with today = the Pacific date, CaseDetail.programs = evaluate(case), every CaseSummary
the API sends (list, detail, events) carries found_display of a full-mode result, and nothing at all with
GP_PROGRAMS=0. The programs engine is pure; a failure there never breaks a console or card answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import CaseStatus, Lang
from gatorplate.contracts.console_api import CaseDetail, CaseSummary
from gatorplate.contracts.programs import ProgramsMeta, ProgramsResult, UnlockedView
from gatorplate.contracts.rules_io import RulesMeta
from gatorplate.contracts.summary import case_summary
from gatorplate.deps import Deps

log = logging.getLogger("gatorplate.api")

# Coordinator status transitions (docs/UI_SPEC.md A3.7), enforced by the server.
TRANSITIONS: dict[CaseStatus, list[CaseStatus]] = {
    CaseStatus.new: [CaseStatus.reviewed, CaseStatus.follow_up],
    CaseStatus.reviewed: [CaseStatus.applied, CaseStatus.follow_up],
    CaseStatus.applied: [CaseStatus.interview_scheduled, CaseStatus.approved, CaseStatus.follow_up],
    CaseStatus.interview_scheduled: [CaseStatus.approved, CaseStatus.follow_up],
    CaseStatus.follow_up: [CaseStatus.reviewed, CaseStatus.applied, CaseStatus.interview_scheduled],
    CaseStatus.approved: [CaseStatus.follow_up],
}


def _quiet(what: str, exc: Exception) -> None:
    log.warning(json.dumps({"event": f"{what}_failed", "kind": exc.__class__.__name__}))


@dataclass
class AppContext:
    deps: Deps
    db: Any
    webtokens: Any
    counters: Any
    limits: Any
    demo: Any
    janitor: Any
    web_dir: Path
    sse_ping_s: float = 15.0
    _locks: weakref.WeakValueDictionary = field(default_factory=weakref.WeakValueDictionary)

    # ------------------------------------------------------------------------------------------ basics

    @property
    def settings(self) -> Any:
        return self.deps.settings

    def now(self) -> datetime:
        return self.deps.clock.now()

    def call_lock(self, call_id: str) -> asyncio.Lock:
        """One lock per call: requests for the same call_id run one after another, in arrival order."""
        lock = self._locks.get(call_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[call_id] = lock
        return lock

    def rules_meta(self) -> RulesMeta:
        return self.deps.rules.meta()

    # ------------------------------------------------------------------------------------------ programs

    def programs_result(self, case: Case) -> ProgramsResult | None:
        if not self.settings.programs:
            return None
        try:
            return self.deps.programs.evaluate(case, today=self.deps.clock.today())
        except Exception as exc:  # noqa: BLE001 - the console works without the programs section
            _quiet("programs_evaluate", exc)
            return None

    def programs_view(self, case: Case, lang: Lang) -> UnlockedView | None:
        if not self.settings.programs:
            return None
        return self.deps.programs.view(case, lang=lang, today=self.deps.clock.today())

    def programs_meta(self) -> ProgramsMeta | None:
        if not self.settings.programs:
            return None
        try:
            return self.deps.programs.meta()
        except Exception as exc:  # noqa: BLE001
            _quiet("programs_meta", exc)
            return None

    # ------------------------------------------------------------------------------------------ console models

    def summarize(self, case: Case) -> CaseSummary:
        summary = case_summary(case, tz=self.settings.tz, today=self.deps.clock.today())
        result = self.programs_result(case)
        found = result.found_display if result is not None and result.mode == "full" else None
        return summary.model_copy(update={"found_display": found})

    def short_code(self, case: Case) -> str | None:
        card = case.card
        if card is None or card.short_code is None or card.short_code_expires_at is None:
            return None
        return card.short_code if card.short_code_expires_at > self.now() else None

    def detail(self, case: Case) -> CaseDetail:
        open_lines = sum(1 for line in case.yellow_lines if line.resolved is None)
        card = case.card
        return CaseDetail(
            case=case, summary=self.summarize(case),
            card_url=f"/c/{card.token}" if card else None,
            qr_svg_url=f"/api/cases/{case.id}/qr.svg" if card else None,
            short_code=self.short_code(case),
            can_review=not case.live and open_lines == 0,
            allowed_status=[] if case.live else list(TRANSITIONS[case.status]),
            rules=self.rules_meta(),
            programs=self.programs_result(case),
        )

    # ------------------------------------------------------------------------------------------ health

    def llm_health(self) -> dict[str, Any]:
        """{provider, status, last_ok_at, usage: {calls, input_tokens, output_tokens, cache_read_input_tokens,
        cache_creation_input_tokens}} read from the understanding
        component: a `llm_health()` mapping when it offers one, else the attributes of its language-model client."""
        settings = self.settings
        out: dict[str, Any] = {"provider": settings.llm_provider, "status": None, "last_ok_at": None,
                               "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
        source: Any = self.deps.understanding
        try:
            reader = getattr(source, "llm_health", None)
            info: Any = reader() if callable(reader) else None
            if not isinstance(info, dict):
                client = getattr(source, "llm", None)
                info = {name: getattr(client, name, None) for name in ("status", "last_ok_at", "usage")}
                metrics = getattr(client, "metrics", None)
                if metrics is not None and info["usage"] is None:
                    info["usage"] = metrics
            out["status"] = info.get("status")
            last_ok = info.get("last_ok_at")
            out["last_ok_at"] = last_ok.isoformat() if isinstance(last_ok, datetime) else last_ok
            usage = info.get("usage")
            if callable(usage):
                usage = usage()
            if usage is not None:
                for key in ("calls", "input_tokens", "output_tokens", "cache_read_input_tokens",
                            "cache_creation_input_tokens"):
                    value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
                    if isinstance(value, int):
                        out["usage"][key] = value
        except Exception as exc:  # noqa: BLE001 - health never fails on a reporting detail
            _quiet("llm_health", exc)
        if out["status"] not in ("no_key", "ready", "ok", "error"):
            no_key = settings.llm_provider == "anthropic" and not settings.llm_api_key.get_secret_value()
            out["status"] = "no_key" if no_key else "ready"
        return out

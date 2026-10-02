"""Demo cases: seed, reset and inject (docs/UI_SPEC.md A2.5; the files in data/demo_cases/).

The console's "Seed samples", "Reset demo" (reset, then seed) and the janitor's daily demo reset all call these same
functions. Every time and date is relative to the seed time in America/Los_Angeles and never falls before the file's
`not_before` (the first morning of the rules table) nor before the rules table's first effective day; nothing is later
than the seed time, and the order created_at <= tracking dates <= reviewed_at <= now is kept.

Callers publish the events (one `demo.reset` for a reset or a seed, `case.created` for an inject).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gatorplate.contracts.case import AskedQuestion, CardRef, Case, Consent, ProgramAnswer, TimelinePoint, Tracking
from gatorplate.contracts.common import CaseStatus, Channel, Lang, Phase, SlotSource, SlotState, YellowResolution
from gatorplate.contracts.errors import NotFound
from gatorplate.contracts.slots import ROUTING_ONLY, Slot, SlotName, format_display
from gatorplate.contracts.summary import summary_line

DEMO_ID = re.compile(r"^[a-z0-9_]{1,64}$")
SEED_NOTE = "Checked in the demo seed"
CONSENT_AFTER = timedelta(seconds=12)  # the opening and the consent answer take a few seconds


@dataclass(frozen=True)
class SeedResult:
    seeded: int
    replaced: int


@dataclass(frozen=True)
class ResetResult:
    deleted: int
    kept: int
    deleted_ids: tuple[str, ...] = ()


class DemoCases:
    def __init__(self, *, demo_dir: Path, rules: Any, cases: Any, ids: Any, live: Any = None,
                 tz: str = "America/Los_Angeles", card_ttl_days: int = 7) -> None:
        self.demo_dir = Path(demo_dir)
        self.rules = rules
        self.cases = cases
        self.ids = ids
        self.live = live
        self.tz = ZoneInfo(tz)
        self.card_ttl = timedelta(days=card_ttl_days)

    # ------------------------------------------------------------------------------------------ files

    def available(self) -> list[str]:
        return sorted(p.stem for p in self.demo_dir.glob("*.json") if DEMO_ID.match(p.stem))

    def load(self, demo_id: str) -> dict:
        if not DEMO_ID.match(demo_id) or demo_id not in self.available():
            raise NotFound("No such demo case.")
        return json.loads((self.demo_dir / f"{demo_id}.json").read_text(encoding="utf-8"))

    def seed_files(self) -> list[dict]:
        files = [self.load(name) for name in self.available()]
        return [f for f in files if f.get("seed") is True]

    # ------------------------------------------------------------------------------------------ times

    def _floor(self, demo: dict) -> datetime:
        floor = datetime.fromisoformat(demo["not_before"])
        try:
            effective = self.rules.meta().effective_from
        except Exception:  # noqa: BLE001 - a rules engine that cannot answer leaves the file's floor
            return floor
        return max(floor, datetime.combine(effective, time(0), tzinfo=self.tz))

    def _clamp(self, value: datetime, *, low: datetime, now: datetime) -> datetime:
        """`value` raised to `low` and capped at `now`, in UTC (every stored timestamp is UTC)."""
        return min(now, max(value, low)).astimezone(UTC)

    # ------------------------------------------------------------------------------------------ building

    def build(self, demo: dict, now: datetime) -> Case:
        """The Case a demo file describes, with rules applied, a card, status and tracking dates."""
        floor = self._floor(demo)
        created = self._clamp(now - timedelta(minutes=int(demo["minutes_ago"])), low=floor, now=now)
        ended = min(created + timedelta(seconds=int(demo["call_seconds"])), now)
        turns: dict[str, int] = demo.get("turns", {})
        max_turn = max(turns.values(), default=1)

        def turn_at(turn: int) -> datetime:
            seconds = int(demo["call_seconds"]) * turn // (max_turn + 1)
            return min(created + timedelta(seconds=seconds), now)

        slots: dict[SlotName, Slot] = {}
        for name, raw in demo.get("slots", {}).items():
            slot = SlotName(name)
            if slot in ROUTING_ONLY:
                continue  # never stored (the store would refuse the case)
            slots[slot] = Slot(value=raw, display=format_display(slot, raw), state=SlotState.clear,
                               source=SlotSource.seed, heard=demo.get("heard", {}).get(name),
                               heard_en=demo.get("heard_en", {}).get(name), turn=turns.get(name),
                               confirmed=name in demo.get("confirmed", []), updated_at=ended)
        asked = [AskedQuestion.model_validate(a) for a in demo.get("asked", [])]
        consent_given = demo.get("slots", {}).get("consent") == "true"
        answers_at = min(created + timedelta(seconds=int(demo["call_seconds"])), now)
        case = Case(
            id=self.ids.case_id(), code=demo["code"], created_at=created, updated_at=ended,
            lang=Lang(demo["lang"]), channel=Channel(demo["channel"]), test=False, live=False,
            status=CaseStatus.new, seeded=bool(demo.get("seed")), persona=demo.get("persona"), phase=Phase.end,
            turn_count=max_turn + 1, ended_reason=demo.get("ended_reason"), ended_early=False, slots=slots,
            asked=asked,
            consent=Consent(given=consent_given if "consent" in demo.get("slots", {}) else None,
                            at=min(created + CONSENT_AFTER, now) if consent_given else None,
                            disclosure_key="consent.ask" if consent_given else None),
            program_answers={q: ProgramAnswer(value=v, at=answers_at, source="seed")
                             for q, v in (demo.get("program_answers") or {}).items()},
        )
        case = self._apply_rules(case, turns=turns, turn_at=turn_at, ended=ended, max_turn=max_turn, file_asked=asked)
        case.card = CardRef(token=self.ids.card_token(), short_code=None, short_code_expires_at=None,
                            created_at=ended, expires_at=ended + self.card_ttl)
        reviewed_at = self._status(case, demo, now=now, floor=floor, ended=ended)
        self._tracking(case, demo, now=now, created=created, reviewed_at=reviewed_at)
        if not case.summary:
            case.summary = summary_line(case)
        case.updated_at = ended
        return case

    def _apply_rules(self, case: Case, *, turns: dict[str, int], turn_at: Any, ended: datetime, max_turn: int,
                     file_asked: list[AskedQuestion]) -> Case:
        """Runs the rules once per student turn on the slots known by then (only the timeline point of each run
        is kept: the console's range bar and replay), then once on the whole case."""
        points: list[TimelinePoint] = []
        for turn in sorted(set(turns.values())):
            known = {n: s for n, s in case.slots.items() if s.turn is not None and s.turn <= turn}
            changed = [n for n, s in case.slots.items() if s.turn == turn]
            partial = case.model_copy(update={"slots": known, "timeline": list(points), "asked": [],
                                              "skipped": [], "yellow_lines": []}, deep=True)
            lo = hi = None
            try:
                result = self.rules.apply(partial, now=turn_at(turn), turn=turn)
                if result.estimate_range is not None:
                    lo, hi = result.estimate_range.lo, result.estimate_range.hi
            except Exception:  # noqa: BLE001 - a partial case the engine cannot place keeps an empty range
                pass
            points.append(TimelinePoint(turn=turn, at=turn_at(turn), slots=changed, lo=lo, hi=hi))
        final = self.rules.apply(case.model_copy(deep=True), now=ended, turn=max_turn)
        if points:
            final.timeline = points
        keys = {a.key for a in file_asked}
        final.asked = list(file_asked) + [a for a in final.asked if a.key not in keys]
        return final

    def _status(self, case: Case, demo: dict, *, now: datetime, floor: datetime, ended: datetime) -> datetime | None:
        status = CaseStatus(demo.get("status", "new"))
        reviewed_at = None
        if status is CaseStatus.reviewed:
            minutes = int(demo.get("reviewed_minutes_ago", 0))
            reviewed_at = self._clamp(now - timedelta(minutes=minutes), low=max(floor, ended), now=now)
            if demo.get("confirm_open_yellow_lines"):
                for line in case.yellow_lines:
                    if line.resolved is None:
                        line.resolved = YellowResolution.confirm
                        line.resolved_at = reviewed_at
                        line.resolved_note = SEED_NOTE
            case.reviewed_at = reviewed_at
        case.status = status
        return reviewed_at

    def _tracking(self, case: Case, demo: dict, *, now: datetime, created: datetime,
                  reviewed_at: datetime | None) -> None:
        spec = demo.get("tracking")
        if not spec:
            return
        seed_day = now.astimezone(self.tz).date()
        floor_day: date = max(datetime.fromisoformat(demo["not_before"]).astimezone(self.tz).date(),
                              created.astimezone(self.tz).date())
        tracking = Tracking()
        applied_on = None
        if "applied_days_ago" in spec:
            applied_on = max(seed_day - timedelta(days=int(spec["applied_days_ago"])), floor_day)
            tracking.applied_at = applied_on
        if "interview_days_ago" in spec:
            day = max(seed_day - timedelta(days=int(spec["interview_days_ago"])), applied_on or floor_day)
            hour, minute = (int(x) for x in str(spec.get("interview_local_time", "10:00")).split(":"))
            at = datetime.combine(day, time(hour, minute), tzinfo=self.tz)
            tracking.interview_at = self._clamp(at, low=created, now=reviewed_at or now)
            tracking.interview_missed = bool(spec.get("interview_missed", False))
        try:
            tracking = self.rules.compute_tracking(tracking)
        except Exception:  # noqa: BLE001 - the stated dates stay; the deadlines come with the rules engine
            pass
        case.tracking = tracking

    # ------------------------------------------------------------------------------------------ operations

    def _wipe_live(self, ids: list[str]) -> None:
        if self.live is not None:
            for case_id in ids:
                self.live.wipe(case_id)

    def _remove_code(self, code: str) -> str | None:
        existing = self.cases.get_by_code(code)
        if existing is not None and self.cases.delete(existing.id):
            return existing.id
        return None

    def seed(self, now: datetime) -> SeedResult:
        """Creates every demo case with "seed": true, replacing the samples already there (and any case that holds
        a sample's code)."""
        files = self.seed_files()
        built = [self.build(f, now) for f in files]  # build first: a failure leaves the old samples in place
        removed: list[str] = []
        for case_id in self.cases.ids(seeded=True):
            if self.cases.delete(case_id):
                removed.append(case_id)
        for case in built:
            gone = self._remove_code(case.code)
            if gone:
                removed.append(gone)
            self.cases.create(case)
        self._wipe_live(removed)
        return SeedResult(seeded=len(built), replaced=len(removed))

    def reset(self) -> ResetResult:
        """Removes every case that is not a demo sample, with its card and its saved call state."""
        ids = self.cases.ids(seeded=False)
        deleted = self.cases.delete_all(keep_seeded=True)
        self._wipe_live(ids)
        return ResetResult(deleted=deleted, kept=self.cases.count(), deleted_ids=tuple(ids))

    def inject(self, demo_id: str, now: datetime) -> Case:
        """Creates the case one demo file describes (any file; replaces a case with the same code)."""
        case = self.build(self.load(demo_id), now)
        gone = self._remove_code(case.code)
        if gone:
            self._wipe_live([gone])
        return self.cases.create(case)

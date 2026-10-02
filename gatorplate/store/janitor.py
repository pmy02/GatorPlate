"""The janitor: one tick every 60 seconds (docs/SPEC.md §8.4).

- Idle calls (no request for 10 minutes) are closed as if /end had arrived with reason `timeout`; a case still marked
  live without an open call is closed with an `incomplete` yellow line when it never reached a result.
- Expired web tokens and spoken card codes are purged (expired cards themselves answer 410 at read time), and so is
  the call state a deleted case left behind once its call has been quiet for 10 minutes.
- Daily demo reset (only with GP_DEMO_MODE=1 and GP_DAILY_RESET=1): the first tick at or after 23:30 Pacific on a
  Pacific date with no recorded run does the same reset, then seed as the console's "Reset demo", publishes one
  `demo.reset`, records the date in the counters (key `demo_daily_reset`) and writes one content-free log line. While
  any case is live the run waits for the next tick. It runs at most once per Pacific date.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from gatorplate.contracts.brain_api import EndRequest
from gatorplate.contracts.case import YellowLine
from gatorplate.contracts.common import YellowKind
from gatorplate.contracts.console_text import INCOMPLETE
from gatorplate.store.counters import DEMO_DAILY_RESET

log = logging.getLogger("gatorplate.janitor")

IDLE_AFTER = timedelta(minutes=10)
DAILY_RESET_AT = time(23, 30)
TICK_SECONDS = 60


class Janitor:
    def __init__(self, *, settings: Any, clock: Any, cases: Any, sessions: Any, webtokens: Any, counters: Any,
                 live: Any, events: Any, brain: Any, demo: Any) -> None:
        self.settings = settings
        self.clock = clock
        self.cases = cases
        self.sessions = sessions
        self.webtokens = webtokens
        self.counters = counters
        self.live = live
        self.events = events
        self.brain = brain
        self.demo = demo
        self.tz = ZoneInfo(getattr(settings, "tz", "America/Los_Angeles"))

    async def tick(self) -> dict[str, int]:
        """One janitor pass; returns content-free counts (for tests and the log)."""
        closed = await self.close_idle_calls()
        purged = self.purge()
        reset = self.daily_reset()
        return {"closed": closed, "purged": purged, "daily_reset": 1 if reset else 0}

    # ------------------------------------------------------------------------------------------ idle calls

    async def close_idle_calls(self) -> int:
        now = self.clock.now()
        closed = 0
        for state in self.sessions.idle(before=now - IDLE_AFTER):
            try:
                await self.brain.end(state.call_id, EndRequest(v=1, reason="timeout"))
            except Exception:  # noqa: BLE001 - the call is closed here instead (content-free log below)
                log.warning(json.dumps({"event": "janitor.end_failed"}))
                state.ended = True
                self.sessions.put(state)
                self._close_case(state.case_id)
            else:
                fresh = self.sessions.get(state.call_id)
                if fresh is not None and not fresh.ended:
                    fresh.ended = True
                    self.sessions.put(fresh)
                self._close_case(state.case_id)
            self.live.wipe(state.case_id)
            closed += 1
        # Cases still marked live with no open call that has been active recently.
        for case_id in self.cases.ids(live=True):
            case = self.cases.get(case_id)
            if case is None or case.updated_at > now - IDLE_AFTER:
                continue
            open_calls = [s for s in self.sessions.for_case(case_id)
                          if not s.ended and s.last_activity_at > now - IDLE_AFTER]
            if not open_calls:
                self._close_case(case_id)
                self.live.wipe(case_id)
                closed += 1
        return closed

    def _close_case(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        if case is None or not case.live:
            return
        now = self.clock.now()
        case.live = False
        case.ended_reason = case.ended_reason or "timeout"
        if case.tier is None:
            case.ended_early = True
            if not any(y.kind == YellowKind.incomplete for y in case.yellow_lines):
                case.yellow_lines.append(YellowLine(id=f"y{len(case.yellow_lines) + 1}", kind=YellowKind.incomplete,
                                                    code="incomplete", reason=INCOMPLETE, created_at=now))
        saved = self.cases.save(case)
        self.events.publish("live.ended", case_id=case_id)
        self.events.publish("case.updated", case=saved)

    # ------------------------------------------------------------------------------------------ purge

    def purge(self) -> int:
        now = self.clock.now()
        purged = self.webtokens.purge() + self.cases.purge_short_codes(now=now)
        purge_orphans = getattr(self.sessions, "purge_orphans", None)
        if callable(purge_orphans):
            purged += purge_orphans(before=now - IDLE_AFTER)
        return purged

    # ------------------------------------------------------------------------------------------ daily reset

    def daily_reset_due(self, now: datetime) -> bool:
        if not (self.settings.demo_mode and self.settings.daily_reset):
            return False
        local = now.astimezone(self.tz)
        if local.time() < DAILY_RESET_AT:
            return False
        return self.counters.recorded_day(DEMO_DAILY_RESET) != local.date().isoformat()

    def daily_reset(self) -> bool:
        now = self.clock.now()
        if not self.daily_reset_due(now):
            return False
        if self.cases.any_live():
            return False  # a call in progress is never cut; the next tick checks again
        reset = self.demo.reset()
        seeded = self.demo.seed(now)
        self.events.publish("demo.reset")
        self.counters.record(DEMO_DAILY_RESET, day=now.astimezone(self.tz).date(), n=1)
        log.info(json.dumps({"event": "demo.daily_reset", "deleted": reset.deleted, "seeded": seeded.seeded}))
        return True

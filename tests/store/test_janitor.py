"""The janitor: idle calls closed as a timeout, expired tokens and spoken codes purged, and the daily demo reset at
23:30 Pacific (once per Pacific date, never during a live call, only with GP_DEMO_MODE=1 and GP_DAILY_RESET=1)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gatorplate.clock import FixedClock
from gatorplate.config import REPO_ROOT
from gatorplate.contracts.case import CardRef, Case
from gatorplate.contracts.common import Channel, Lang, YellowKind, YellowResolution
from gatorplate.contracts.session import SessionState
from gatorplate.ids import FixedIds
from gatorplate.store import Counters, DemoCases, Janitor, WebTokens
from gatorplate.store.counters import DEMO_DAILY_RESET
from tests.api.fakes import make_deps, make_settings

PT = ZoneInfo("America/Los_Angeles")


class Rig:
    def __init__(self, tmp_db, clock: FixedClock, **settings) -> None:
        self.clock = clock
        self.settings = make_settings(tmp_db, **settings)
        self.deps = make_deps(self.settings, clock=clock, ids=FixedIds())
        db = self.deps.cases.db
        self.webtokens = WebTokens(db, clock=clock)
        self.counters = Counters(db, clock=clock)
        self.demo = DemoCases(demo_dir=REPO_ROOT / "data" / "demo_cases", rules=self.deps.rules, cases=self.deps.cases,
                              ids=self.deps.ids, live=self.deps.live)
        self.janitor = self.new_janitor()

    def new_janitor(self) -> Janitor:
        d = self.deps
        return Janitor(settings=self.settings, clock=self.clock, cases=d.cases, sessions=d.sessions,
                       webtokens=self.webtokens, counters=self.counters, live=d.live, events=d.events,
                       brain=d.brain, demo=self.demo)

    def judge_case(self, *, live: bool = False) -> Case:
        now = self.clock.now()
        case = Case(id=self.deps.ids.case_id(), code="K7Q-2FM", created_at=now, updated_at=now, lang=Lang.en,
                    channel=Channel.phone, live=live,
                    card=CardRef(token="judgecard000000000000001", created_at=now, expires_at=now + timedelta(days=7)))
        case = self.deps.cases.create(case)
        self.deps.sessions.put(SessionState(call_id="f" * 32, case_id=case.id, channel=Channel.phone, lang=Lang.en,
                                            started_at=now, last_activity_at=now, ended=not live))
        return case

    async def at(self, hour: int, minute: int, *, day: int = 2) -> dict:
        self.clock.set(datetime(2026, 10, day, hour, minute, tzinfo=PT))
        return await self.janitor.tick()

    def resets(self) -> list:
        return [e for e in self.deps.events.buffered() if e.type == "demo.reset"]


@pytest.fixture
def rig(clean_gp_env, tmp_db) -> Rig:
    r = Rig(tmp_db, FixedClock.pacific(2026, 10, 2, 22, 0), daily_reset=True)
    r.demo.seed(r.clock.now())
    sofia = r.deps.cases.get_by_code("R8W-3ND")
    sofia.yellow_lines[0].resolved = YellowResolution.confirm
    r.deps.cases.save(sofia)
    return r


async def test_daily_reset_runs_once_at_2330_pacific(rig: Rig, caplog) -> None:
    judge = rig.judge_case()
    assert (await rig.at(23, 29))["daily_reset"] == 0 and rig.deps.cases.get(judge.id) is not None
    with caplog.at_level(logging.INFO, logger="gatorplate"):
        assert (await rig.at(23, 30))["daily_reset"] == 1  # UTC is already Oct 3
    assert rig.deps.cases.get(judge.id) is None and rig.deps.cases.get_by_card_token("judgecard000000000000001") is None
    assert rig.deps.sessions.get("f" * 32) is None
    sofia = rig.deps.cases.get_by_code("R8W-3ND")
    assert [y.resolved for y in sofia.yellow_lines] == [None]
    assert len(rig.resets()) == 1
    assert rig.counters.recorded_day(DEMO_DAILY_RESET) == "2026-10-02"
    lines = [json.loads(r.getMessage()) for r in caplog.records if "demo.daily_reset" in r.getMessage()]
    assert lines == [{"event": "demo.daily_reset", "deleted": 1, "seeded": 5}]
    assert (await rig.at(23, 31))["daily_reset"] == 0
    rig.janitor = rig.new_janitor()  # a restart on the same database
    assert (await rig.at(23, 45))["daily_reset"] == 0
    assert len(rig.resets()) == 1


async def test_missed_run_happens_at_the_first_tick_after(rig: Rig) -> None:
    assert (await rig.at(23, 50))["daily_reset"] == 1
    assert rig.counters.recorded_day(DEMO_DAILY_RESET) == "2026-10-02"


async def test_no_catch_up_after_midnight(rig: Rig) -> None:
    assert (await rig.at(0, 10, day=3))["daily_reset"] == 0
    assert (await rig.at(23, 29, day=3))["daily_reset"] == 0
    assert (await rig.at(23, 30, day=3))["daily_reset"] == 1
    assert rig.counters.recorded_day(DEMO_DAILY_RESET) == "2026-10-03"


async def test_a_live_call_is_never_cut(rig: Rig) -> None:
    rig.clock.set(datetime(2026, 10, 2, 23, 25, tzinfo=PT))  # the call is active (not idle) at 23:30
    judge = rig.judge_case(live=True)
    assert (await rig.at(23, 30))["daily_reset"] == 0 and rig.deps.cases.get(judge.id) is not None
    case = rig.deps.cases.get(judge.id)
    case.live = False
    rig.deps.cases.save(case)
    assert (await rig.at(23, 31))["daily_reset"] == 1
    assert rig.deps.cases.get(judge.id) is None


@pytest.mark.parametrize("settings", [{"daily_reset": False}, {"demo_mode": False, "daily_reset": True}, {}])
async def test_never_runs_when_switched_off(clean_gp_env, tmp_db, settings) -> None:
    r = Rig(tmp_db, FixedClock.pacific(2026, 10, 2, 23, 30), **settings)
    assert (await r.janitor.tick())["daily_reset"] == 0
    assert r.counters.recorded_day(DEMO_DAILY_RESET) is None


async def test_idle_call_closed_as_timeout(clean_gp_env, tmp_db) -> None:
    r = Rig(tmp_db, FixedClock.pacific(2026, 10, 2, 10, 0))
    case = r.judge_case(live=True)
    r.clock.advance(minutes=9)
    assert (await r.janitor.tick())["closed"] == 0
    r.clock.advance(minutes=2)
    assert (await r.janitor.tick())["closed"] == 1
    assert r.deps.brain.ended == ["timeout"]
    assert r.deps.sessions.get("f" * 32).ended and not r.deps.cases.get(case.id).live


async def test_idle_call_closed_even_when_the_brain_fails(clean_gp_env, tmp_db) -> None:
    r = Rig(tmp_db, FixedClock.pacific(2026, 10, 2, 10, 0))

    async def broken(call_id, req):
        raise RuntimeError("boom")

    r.deps.brain.end = broken  # type: ignore[method-assign]
    case = r.judge_case(live=True)
    r.clock.advance(minutes=11)
    assert (await r.janitor.tick())["closed"] == 1
    closed = r.deps.cases.get(case.id)
    assert not closed.live and closed.ended_early
    assert [y.kind for y in closed.yellow_lines] == [YellowKind.incomplete]
    assert closed.yellow_lines[0].reason == "Call ended before the result."


async def test_purges_expired_tokens_and_codes(clean_gp_env, tmp_db) -> None:
    r = Rig(tmp_db, FixedClock.pacific(2026, 10, 2, 10, 0))
    now = r.clock.now()
    case = Case(id="c_codecase01", code="AAA-BBB", created_at=now, updated_at=now, lang=Lang.en, channel=Channel.phone,
                live=False, card=CardRef(token="codecard0000000000000001", short_code="481206",
                                         short_code_expires_at=now + timedelta(hours=24), created_at=now,
                                         expires_at=now + timedelta(days=7)))
    stored = r.deps.cases.create(case)
    r.webtokens.issue("webtoken-to-expire-0000000000000000000", "a" * 32)
    r.clock.advance(hours=23)
    assert (await r.janitor.tick())["purged"] == 1  # the web token (30 minutes); the spoken code lives 24 h
    assert r.deps.cases.get(case.id).card.short_code == "481206"
    r.clock.advance(hours=2)
    assert (await r.janitor.tick())["purged"] == 1
    after = r.deps.cases.get(case.id)
    assert r.webtokens.count() == 0 and after.card.short_code is None and after.card.short_code_expires_at is None
    assert after.version == stored.version  # housekeeping: no version bump, so no console edit turns stale
    assert r.deps.cases.db.query("SELECT short_code FROM cases")[0]["short_code"] is None

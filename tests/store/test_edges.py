"""Store edges: call state left behind by a deleted case is purged once the call is quiet; every timestamp a demo case
stores is UTC; deletes leave no session row or web token behind; the event bus resyncs a number from an earlier
run; the live store is never read from disk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gatorplate.clock import FixedClock
from gatorplate.config import REPO_ROOT
from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.session import SessionState
from gatorplate.ids import FixedIds
from gatorplate.store import Counters, DemoCases, EventBus, Janitor, WebTokens
from tests.api.fakes import make_deps, make_settings


def _rig(tmp_db, clock):
    settings = make_settings(tmp_db)
    deps = make_deps(settings, clock=clock, ids=FixedIds())
    db = deps.cases.db
    webtokens = WebTokens(db, clock=clock)
    demo = DemoCases(demo_dir=REPO_ROOT / "data" / "demo_cases", rules=deps.rules, cases=deps.cases, ids=deps.ids,
                     live=deps.live)
    janitor = Janitor(settings=settings, clock=clock, cases=deps.cases, sessions=deps.sessions, webtokens=webtokens,
                      counters=Counters(db, clock=clock), live=deps.live, events=deps.events, brain=deps.brain,
                      demo=demo)
    return deps, webtokens, demo, janitor


async def test_orphaned_call_state_is_purged_after_the_call_goes_quiet(clean_gp_env, tmp_db) -> None:
    """A voice "delete my data" deletes the case during the call; the brain then writes the call's last state, which
    names a case that no longer exists. Ten quiet minutes later nothing of that call is left."""
    clock = FixedClock.pacific(2026, 10, 2, 10, 0)
    deps, webtokens, _, janitor = _rig(tmp_db, clock)
    now = clock.now()
    kept = deps.cases.create(Case(id="c_keep000001", code="AAA-AAA", created_at=now, updated_at=now, lang=Lang.en,
                                  channel=Channel.web))
    for call_id, case_id in (("a" * 32, "c_gone000001"), ("b" * 32, kept.id)):
        deps.sessions.put(SessionState(call_id=call_id, case_id=case_id, channel=Channel.web, lang=Lang.en,
                                       started_at=now, last_activity_at=now, ended=True))
        webtokens.issue(f"token-{call_id}", call_id, expires_at=now + timedelta(hours=1))
    clock.advance(minutes=9)
    assert (await janitor.tick())["purged"] == 0 and deps.sessions.count() == 2  # the call may still send /end
    clock.advance(minutes=2)
    assert (await janitor.tick())["purged"] == 1
    assert deps.sessions.get("a" * 32) is None and not webtokens.check("token-" + "a" * 32, "a" * 32)
    assert deps.sessions.get("b" * 32) is not None  # a case that still exists keeps its call state


def test_every_demo_timestamp_is_utc(clean_gp_env, tmp_db) -> None:
    """Timestamps are stored in UTC (docs/SPEC.md §5.7), also the ones raised to the table's first morning, which is
    a Pacific time."""
    clock = FixedClock.pacific(2026, 10, 2, 10, 0)
    deps, _, demo, _ = _rig(tmp_db, clock)
    demo.seed(clock.now())
    demo.inject("maria_g1", clock.now())
    rows = deps.cases.db.query("SELECT doc FROM cases")
    assert len(rows) == 6
    for row in rows:
        stamps = _datetimes(row["doc"])
        assert stamps, "a case has timestamps"
        offenders = [s for s in stamps if not s.endswith("Z")]
        assert offenders == [], offenders[:3]
    jamal = deps.cases.get_by_code("P2X-6TC")
    assert jamal.created_at == datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # 08:00 PT, the floor
    assert jamal.tracking.interview_at == datetime(2026, 10, 1, 17, 0, tzinfo=UTC)  # 10:00 PT


def _datetimes(doc: str) -> list[str]:
    import json
    import re

    out: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})",
                                                    value):
            out.append(value)

    walk(json.loads(doc))
    return out


def test_resync_for_a_number_from_an_earlier_run(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock)
    bus.publish("case.deleted", case_id="c_1")
    assert bus.changed_since(57) is None  # a number this process never issued: refetch everything
    assert bus.changed_since(0) == {"c_1"}


def test_timestamp_columns_sort_and_compare_as_text() -> None:
    from gatorplate.store.db import parse_ts, ts

    whole = datetime(2026, 10, 2, 17, 0, 0, tzinfo=UTC)
    later = whole + timedelta(microseconds=500_000)
    assert ts(whole) == "2026-10-02T17:00:00.000000Z" and ts(whole) < ts(later)
    assert parse_ts(ts(later)) == later and len(ts(whole)) == len(ts(later))


def test_a_web_token_expires_at_the_exact_instant(clean_gp_env, tmp_db) -> None:
    """Expiry on a whole second, checked half a second later: expired, and purged (text comparison included)."""
    clock = FixedClock(datetime(2026, 10, 2, 16, 59, 0, tzinfo=UTC))
    deps, webtokens, _, _ = _rig(tmp_db, clock)
    webtokens.issue("tok", "c" * 32, expires_at=datetime(2026, 10, 2, 17, 0, 0, tzinfo=UTC))
    clock.set(datetime(2026, 10, 2, 16, 59, 59, 900_000, tzinfo=UTC))
    assert webtokens.check("tok", "c" * 32) and webtokens.purge() == 0
    clock.set(datetime(2026, 10, 2, 17, 0, 0, 500_000, tzinfo=UTC))
    assert not webtokens.check("tok", "c" * 32) and webtokens.purge() == 1

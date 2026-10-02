"""Demo cases: seed, reset and inject from data/demo_cases/ (dates relative to the seed time in Pacific time and never
before the rules table's first day; asked entries copied as given; Jamal's card answers and tracking; Sofia's open
yellow line comes back after reset then seed)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gatorplate.clock import FixedClock
from gatorplate.config import REPO_ROOT
from gatorplate.contracts.case import Case
from gatorplate.contracts.common import CaseStatus, Channel, Lang, YellowResolution
from gatorplate.contracts.console_text import PARENT_HOUSEHOLD_TEXT
from gatorplate.contracts.errors import NotFound
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import ROUTING_ONLY
from gatorplate.ids import FixedIds
from gatorplate.store import DemoCases
from tests.api.fakes import make_deps, make_settings

PT = ZoneInfo("America/Los_Angeles")
FLOOR = datetime(2026, 10, 1, 8, 0, tzinfo=PT)
SAMPLE_CODES = {"R8W-3ND", "P2X-6TC", "H5V-9KB", "Z4M-7QE", "D7L-8RW"}


def build(tmp_db, clock):
    deps = make_deps(make_settings(tmp_db), clock=clock, ids=FixedIds())
    demo = DemoCases(demo_dir=REPO_ROOT / "data" / "demo_cases", rules=deps.rules, cases=deps.cases, ids=deps.ids,
                     live=deps.live)
    return deps, demo


def by_code(deps) -> dict[str, Case]:
    return {c.code: c for c in deps.cases.list()}


def test_seed_creates_the_samples_and_replaces_them(clean_gp_env, tmp_db, fixed_clock) -> None:
    deps, demo = build(tmp_db, fixed_clock)
    first = demo.seed(fixed_clock.now())
    assert (first.seeded, first.replaced) == (5, 0)
    cases = by_code(deps)
    assert set(cases) == SAMPLE_CODES and all(c.seeded and not c.live for c in cases.values())
    again = demo.seed(fixed_clock.now())
    assert (again.seeded, again.replaced) == (5, 5)
    assert set(by_code(deps)) == SAMPLE_CODES


def test_sofia_jamal_and_fillers(clean_gp_env, tmp_db, fixed_clock) -> None:
    deps, demo = build(tmp_db, fixed_clock)
    demo.seed(fixed_clock.now())
    cases = by_code(deps)
    sofia = cases["R8W-3ND"]
    open_lines = [y for y in sofia.yellow_lines if y.resolved is None]
    assert len(open_lines) == 1 and open_lines[0].reason == PARENT_HOUSEHOLD_TEXT
    assert sofia.lang == Lang.es and sofia.channel == Channel.web and sofia.persona == "Sofia (demo persona)"
    assert sofia.slots["age"].heard == "Tengo diecinueve años" and sofia.slots["age"].heard_en == "I'm nineteen"
    assert [a.key for a in sofia.asked] == ["ask.level_units", "ask.age_parent"]
    assert sofia.program_answers == {}
    jamal = cases["P2X-6TC"]
    assert jamal.status == CaseStatus.follow_up
    assert [a.key for a in jamal.asked][-1] == "expedited.intro_cash" and jamal.asked[-1].turn == 5
    assert len(jamal.asked) == len({a.key for a in jamal.asked}) == 5
    assert {q: a.value for q, a in jamal.program_answers.items()} == {"tax_dependent": "no",
                                                                     "break_transit": "two_days"}
    assert all(a.source == "seed" and a.at == jamal.created_at + timedelta(seconds=109)
               for a in jamal.program_answers.values())
    assert jamal.tracking.applied_at == date(2026, 10, 1)
    assert jamal.tracking.interview_at == datetime(2026, 10, 1, 10, 0, tzinfo=PT)
    assert jamal.tracking.interview_missed is True and jamal.tracking.deadline_30d == date(2026, 10, 31)
    grad = cases["H5V-9KB"]
    assert grad.status == CaseStatus.reviewed and grad.reviewed_at is not None
    assert grad.created_at <= grad.reviewed_at <= fixed_clock.now()
    assert all(y.resolved == YellowResolution.confirm for y in grad.yellow_lines)
    for case in cases.values():
        assert case.card is not None and case.card.expires_at == case.card.created_at + timedelta(days=7)
        assert case.phase is not None and case.consent.given is True
        assert not (set(case.slots) & ROUTING_ONLY)
        assert all(s.source == "seed" and s.display for s in case.slots.values())


@pytest.mark.parametrize("now", [datetime(2026, 10, 1, 8, 0, 30, tzinfo=PT), datetime(2026, 10, 2, 10, 0, tzinfo=PT),
                                 datetime(2026, 10, 2, 23, 30, tzinfo=PT), datetime(2026, 10, 9, 1, 0, tzinfo=PT)])
def test_seed_dates_never_before_the_table_and_never_after_now(clean_gp_env, tmp_db, now) -> None:
    clock = FixedClock(now)
    deps, demo = build(tmp_db, clock)
    demo.seed(clock.now())
    for case in deps.cases.list():
        stamps = [case.created_at, case.updated_at, case.card.created_at, *(a.at for a in case.program_answers.values()),
                  *(y.created_at for y in case.yellow_lines), *(p.at for p in case.timeline)]
        if case.reviewed_at:
            stamps.append(case.reviewed_at)
        if case.tracking.interview_at:
            stamps.append(case.tracking.interview_at)
        assert all(FLOOR <= s <= clock.now() for s in stamps), case.code
        assert case.created_at <= case.updated_at
        if case.tracking.applied_at:
            assert date(2026, 10, 1) <= case.tracking.applied_at <= now.astimezone(PT).date()
            assert case.created_at.astimezone(PT).date() <= case.tracking.applied_at
        if case.reviewed_at and case.tracking.interview_at:
            assert case.tracking.interview_at <= case.reviewed_at


@pytest.mark.parametrize("seed_at,applied,interview", [
    (datetime(2026, 10, 2, 10, 0, tzinfo=PT), date(2026, 10, 1), datetime(2026, 10, 1, 10, 0, tzinfo=PT)),
    (datetime(2026, 10, 7, 10, 0, tzinfo=PT), date(2026, 10, 4), datetime(2026, 10, 6, 10, 0, tzinfo=PT)),
    (datetime(2026, 10, 8, 10, 0, tzinfo=PT), date(2026, 10, 5), datetime(2026, 10, 7, 10, 0, tzinfo=PT)),
])
def test_jamal_tracking_examples(clean_gp_env, tmp_db, seed_at, applied, interview) -> None:
    clock = FixedClock(seed_at)
    deps, demo = build(tmp_db, clock)
    demo.seed(clock.now())
    jamal = by_code(deps)["P2X-6TC"]
    assert (jamal.tracking.applied_at, jamal.tracking.interview_at) == (applied, interview)


def test_inject_maria_and_reset(clean_gp_env, tmp_db, fixed_clock) -> None:
    deps, demo = build(tmp_db, fixed_clock)
    demo.seed(fixed_clock.now())
    maria = demo.inject("maria_g1", fixed_clock.now())
    assert maria.code == "K7Q-2FM" and not maria.seeded and maria.persona == "Maria (demo persona)"
    flip = next(a for a in maria.asked if a.key == "flip.rent_paid_by_others")
    assert flip.reason == "could change the estimate by $151: $155 or $306" and flip.delta_usd == 151
    assert len({a.key for a in maria.asked}) == len(maria.asked) == 7
    assert maria.slots["roommates_count"].value == "2"
    ranges = {p.turn: (p.lo, p.hi) for p in maria.timeline}
    assert ranges[6] == (155, 306) and ranges[7] == (306, 306) and ranges[1] == (None, None)
    assert maria.summary == "Undergrad · 1 person · work $900 · rent $1,100"
    now = fixed_clock.now()
    deps.sessions.put(SessionState(call_id="a" * 32, case_id=maria.id, channel=Channel.phone, lang=Lang.en,
                                   started_at=now, last_activity_at=now))
    again = demo.inject("maria_g1", fixed_clock.now())  # the same code is replaced
    assert deps.cases.get(maria.id) is None and deps.cases.get(again.id) is not None
    result = demo.reset()
    assert (result.deleted, result.kept) == (1, 5)
    assert deps.cases.get_by_code("K7Q-2FM") is None and deps.sessions.count() == 0


def test_reset_then_seed_reopens_sofias_line(clean_gp_env, tmp_db, fixed_clock) -> None:
    deps, demo = build(tmp_db, fixed_clock)
    demo.seed(fixed_clock.now())
    sofia = deps.cases.get_by_code("R8W-3ND")
    sofia.yellow_lines[0].resolved = YellowResolution.confirm
    deps.cases.save(sofia)
    demo.reset()
    demo.seed(fixed_clock.now())
    sofia = deps.cases.get_by_code("R8W-3ND")
    assert [y.resolved for y in sofia.yellow_lines] == [None] and sofia.status == CaseStatus.new


def test_unknown_demo_ids(clean_gp_env, tmp_db, fixed_clock) -> None:
    _, demo = build(tmp_db, fixed_clock)
    for bad in ("nope", "../maria_g1", "maria_g1.json", ""):
        with pytest.raises(NotFound):
            demo.inject(bad, fixed_clock.now())
    assert "maria_g1" in demo.available() and len(demo.seed_files()) == 5

"""ProgramFacts from a Case (docs/SPEC.md §5.10 "Facts"): the demo cases give the golden facts, the defaults hold, and
nothing in the case changes."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gatorplate.programs.facts import FACT_NAMES, ProgramFacts, facts_from_case

GOLDEN = json.loads((Path(__file__).resolve().parent.parent.parent / "data" / "golden" / "programs_golden.json")
                    .read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in GOLDEN["cases"]}


def facts(engine, case) -> ProgramFacts:
    return facts_from_case(case, horizon_months=engine.table.money.horizon_months,
                           assumed_roommates=engine.table.facts_defaults.roommates_count_when_unsaid)


def test_fields_are_exactly_the_golden_facts_keys() -> None:
    for case in GOLDEN["cases"]:
        assert set(case["facts"]) == set(FACT_NAMES), case["id"]


@pytest.mark.parametrize(("demo_name", "golden_id"), [("maria_g1", "PG2"), ("jamal_g4", "PG4"), ("sofia_g3", "PG5")])
def test_demo_cases_give_the_golden_facts(engine, make_case, demo_name: str, golden_id: str) -> None:
    built = facts(engine, make_case(demo_name)).model_dump()
    want = ProgramFacts.model_validate(CASES[golden_id]["facts"]).model_dump()
    built.pop("half_time")  # the demo calls never set half_time; the golden facts carry the CalFresh value
    want.pop("half_time")
    assert built == want


def test_seeded_jamal_is_pg4(engine, make_case) -> None:
    jamal = make_case("jamal_g4")
    assert {q: a.source for q, a in jamal.program_answers.items()} == {"tax_dependent": "seed", "break_transit": "seed"}
    r = engine.evaluate(jamal, today=date.fromisoformat(CASES["PG4"]["today"]))
    assert r is not None
    assert (r.found_yearly, r.found_display, r.share_display) == (3998, 3980, 3900)


def test_half_time_is_the_slot_or_null(engine, make_case) -> None:
    assert facts(engine, make_case("maria_g1")).half_time is None
    slots = dict(json.loads((Path(__file__).resolve().parents[2] / "data" / "demo_cases" / "maria_g1.json")
                            .read_text(encoding="utf-8"))["slots"], half_time="true")
    assert facts(engine, make_case("maria_g1", slots=slots)).half_time is True


def test_defaults_for_slots_the_call_never_set(engine, make_case) -> None:
    f = facts(engine, make_case("sofia_g3"))
    assert (f.dorm_on_campus, f.homeless, f.roommates, f.roommates_count, f.children_count) == (False, False, False,
                                                                                                0, 0)
    assert (f.heat_cool, f.other_utils, f.youngest_child_age) == (False, "none", None)
    assert f.earned_monthly is None and f.magi_monthly is None and f.earned_annual is None
    assert f.work_study_monthly == Decimal(0) and f.unearned_monthly == Decimal(0)


def test_roommates_count_assumed_when_not_said(engine, make_case) -> None:
    base = dict(json.loads((Path(__file__).resolve().parents[2] / "data" / "demo_cases" / "maria_g1.json")
                           .read_text(encoding="utf-8"))["slots"])
    unsaid = {k: v for k, v in base.items() if k != "roommates_count"}
    f = facts(engine, make_case("maria_g1", slots=unsaid))
    assert (f.roommates_count, f.bill_split, f.people_in_home) == (2, 3, 3)
    four = facts(engine, make_case("maria_g1", slots={**base, "roommates_count": "4"}))
    assert (four.roommates_count, four.bill_split, four.people_in_home) == (4, 5, 5)
    alone = facts(engine, make_case("maria_g1", slots={**unsaid, "roommates": "false"}))
    assert (alone.roommates_count, alone.bill_split, alone.people_in_home) == (0, 1, 1)


def test_household_and_income_sums(engine, make_case) -> None:
    slots = {"age": "26", "lives_with_parent": "false", "spouse": "true", "children_count": "2",
             "youngest_child_age": "3", "earned_monthly": "1169.10", "work_study_monthly": "200.00",
             "unearned_monthly": "50.00", "other_cash_monthly": "300.00", "roommates": "true"}
    f = facts(engine, make_case("maria_g1", slots=slots, reason_code="likely", estimate=500))
    assert f.household_size == 4  # 1 + spouse + 2 children
    assert f.magi_monthly == Decimal("1419.10")  # family cash is not counted
    assert f.earned_annual == Decimal("16429.20")  # 12 x (earned + work-study)
    assert (f.roommates_count, f.bill_split, f.people_in_home) == (2, 3, 6)
    assert f.calfresh_monthly == 500 and f.route == "likely"


def test_money_facts_are_never_floats() -> None:
    good = dict(CASES["PG1"]["facts"])
    with pytest.raises(ValueError):
        ProgramFacts.model_validate({**good, "earned_monthly": 900.0})
    assert ProgramFacts.model_validate(good).earned_monthly == Decimal("900")


def test_building_facts_does_not_touch_the_case(engine, make_case) -> None:
    case = make_case("maria_g1")
    before = case.model_dump()
    facts(engine, case)
    assert case.model_dump() == before

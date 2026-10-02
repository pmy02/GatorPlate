"""Edge cases found in review: routes that wait for the student's answer, leftovers that can change the tier, the turn
cap, the work-rule line's inputs, the table's dates in Pacific time, idempotency, trace sources, wording and
privacy."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from gatorplate.contracts.case import AskedQuestion
from gatorplate.contracts.common import Phase, SlotState, YellowKind
from gatorplate.contracts.rules_io import Facts
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.rules import Rules

from .conftest import MARIA, NOW, ROOT, TODAY, demo_case, make_case

N = SlotName
GRAD = {"consent": "true", "level": "grad", "units": "9"}
GOLDEN = json.loads((ROOT / "data" / "golden" / "golden_cases.json").read_text(encoding="utf-8"))["cases"]
REJECTION = re.compile(r"not eligible|ineligible|don't qualify|do not qualify|denied|no califica|no eres elegible",
                       re.IGNORECASE)


def _flip(slot: str, turn: int = 6) -> AskedQuestion:
    return AskedQuestion(turn=turn, key="flip.x", slots=[N(slot)], kind="flip")


# ---------------------------------------------------------------------------------------------- routes wait


def test_grad_route_waits_for_the_exemption_answer(rules: Rules) -> None:
    """A missing exemption is not an answer of "none": no route (and no coordinator line) before the question."""
    early = rules.apply(make_case(GRAD, phase=Phase.student), now=NOW)
    assert (early.tier, early.reason_code) == (None, None)
    assert early.yellow_lines == []
    none = rules.apply(make_case({**GRAD, "grad_exemption": "none"}, phase=Phase.student), now=NOW)
    assert (none.tier.value, none.reason_code) == ("coordinator", "coordinator.grad_no_exemption")
    assert [y.code for y in none.yellow_lines] == ["coordinator.grad_no_exemption"]
    unclear = rules.apply(make_case({**GRAD, "grad_exemption": (None, SlotState.unclear)}, phase=Phase.student),
                          now=NOW)
    assert unclear.reason_code == "coordinator.grad_no_exemption"  # an unclear answer: the coordinator checks


@pytest.mark.parametrize("fields", [{"live": False, "phase": Phase.end}, {"phase": Phase.result},
                                    {"flags": ["turn_cap"]}])
def test_grad_route_stands_once_the_call_cannot_ask(rules: Rules, fields: dict) -> None:
    done = rules.apply(make_case(GRAD, **{"phase": Phase.student, **fields}), now=NOW)
    assert done.reason_code == "coordinator.grad_no_exemption"


def test_grad_with_an_exemption_continues(rules: Rules) -> None:
    slots = {**GRAD, "grad_exemption": "campus_job", "age": "26", "lives_with_parent": "false",
             "household_food": "alone", "earned_monthly": "900.00", "other_cash_monthly": "0.00",
             "rent_share": "1100.00", "rent_paid_by_others_to_landlord": "0.00"}
    assert rules.apply(make_case({k: v for k, v in slots.items() if k in {*GRAD, "grad_exemption"}},
                                 phase=Phase.student), now=NOW).tier is None
    done = rules.apply(make_case(slots, phase=Phase.result), now=NOW)
    assert (done.reason_code, done.estimate_monthly) == ("likely", 306)


def test_a_cleared_grad_route_leaves_no_open_line(rules: Rules) -> None:
    routed = rules.apply(make_case({**GRAD, "grad_exemption": "none"}, phase=Phase.student), now=NOW)
    edited = routed.model_copy(deep=True)
    edited.slots[N.grad_exemption] = Slot(value="ta_ra", state=SlotState.clear, changed_from="none")
    assert rules.apply(edited, now=NOW).yellow_lines == []


# ---------------------------------------------------------------------------------------------- leftovers


def test_food_asked_and_still_unclear_goes_to_a_person(rules: Rules) -> None:
    """The food flip was asked and the answer stayed unclear: a tier-changing leftover is coordinator.unresolved,
    exactly as when the question limit leaves it open — never a guessed "likely"."""
    slots = {**MARIA, "household_food": (None, SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00"}
    case = make_case(slots, asked=[_flip("household_food", 4), _flip("rent_paid_by_others_to_landlord", 6)])
    plan = rules.flip_plan(case, today=TODAY, budget=0)
    food = next(c for c in plan.not_asked if c.slot == N.household_food)
    assert food.tier_changes and food.decision == "coordinator"
    done = rules.apply(case, now=NOW)
    assert (done.tier.value, done.reason_code, done.estimate_monthly) == ("coordinator", "coordinator.unresolved",
                                                                           None)
    line = next(y for y in done.yellow_lines if y.code == "coordinator.unresolved")
    assert line.slot == N.household_food and line.effect.kind == "tier"
    assert not [s for s in done.skipped if s.slot == N.household_food]  # it was asked, so it is not "not asked"


def test_food_asked_once_waits_while_other_questions_remain(rules: Rules) -> None:
    """While the rent flip is still to be asked the estimate stays provisional (no unresolved route yet)."""
    slots = {**MARIA, "household_food": (None, SlotState.unclear)}
    case = make_case(slots, asked=[_flip("household_food", 4)])
    plan = rules.flip_plan(case, today=TODAY, budget=1)
    assert [c.slot for c in plan.ask] == [N.rent_paid_by_others_to_landlord]
    assert rules.apply(case, now=NOW).reason_code == "likely"


def test_amount_slot_asked_and_still_unclear_keeps_the_conservative_value(rules: Rules) -> None:
    """Rent paid by someone else: "yes" with an unclear amount after the flip → the lower estimate ($155), no
    unresolved route (it cannot change the tier)."""
    slots = {**MARIA, "rent_paid_by_others_to_landlord": (None, SlotState.unclear), "heat_cool": "false"}
    case = make_case(slots, asked=[_flip("rent_paid_by_others_to_landlord"), _flip("heat_cool", 7)],
                     phase=Phase.result)
    done = rules.apply(case, now=NOW)
    assert (done.reason_code, done.estimate_monthly) == ("likely", 155)
    assert not [y for y in done.yellow_lines if y.code.startswith(("assumed.", "coordinator."))]


def test_turn_cap_makes_the_leftovers_final(rules: Rules) -> None:
    """At the turn cap no flip is asked any more: an askable slot is reported as a leftover with its yellow line."""
    done = rules.apply(make_case(MARIA, phase=Phase.flip, flags=["turn_cap"]), now=NOW)
    assert done.estimate_monthly == 306
    assert [(s.slot.value, s.reason) for s in done.skipped] == [("rent_paid_by_others_to_landlord", "max_questions"),
                                                               ("heat_cool", "no_effect"), ("other_utils", "no_effect")]
    assert [y.code for y in done.yellow_lines] == ["assumed.rent_paid_by_others_to_landlord"]


# ---------------------------------------------------------------------------------------------- work rule


@pytest.mark.parametrize("youngest,line", [(None, True), ("4", False), ("13", False), ("14", True)])
def test_work_rule_line_with_a_child(rules: Rules, youngest: str | None, line: bool) -> None:
    """Only a stated age under 14 turns the work-rule line off; an unknown age leaves it for the coordinator."""
    slots = {**MARIA, "units": "4", "children_count": "1", "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    if youngest is not None:
        slots["youngest_child_age"] = youngest
    facts = rules.facts_from_case(make_case(slots), today=TODAY)
    assert facts.child_under14_in_hh is (not line)
    done = rules.apply(make_case(slots, phase=Phase.result), now=NOW)
    assert ("abawd_possible" in [y.code for y in done.yellow_lines]) is line


def test_work_rule_from_weekly_pay_with_hours(rules: Rules) -> None:
    from decimal import Decimal

    from gatorplate.contracts.slots import MoneyBasis

    case = make_case({**MARIA, "units": "4"})
    case.slots[N.earned_monthly] = Slot(value="1299.00", state=SlotState.clear,
                                        basis=MoneyBasis(amount=Decimal("300"), period="week",
                                                         hours_per_week=Decimal("18.5")))
    assert rules.facts_from_case(case, today=TODAY).works_80h_month  # 18.5 × 4.33 = 80.105


# ---------------------------------------------------------------------------------------------- dates


@pytest.mark.parametrize("now,valid", [
    (datetime(2026, 10, 1, 5, 0, tzinfo=UTC), False),    # Sep 30, 10 PM Pacific: before the table
    (datetime(2026, 10, 1, 7, 0, tzinfo=UTC), True),     # Oct 1, midnight Pacific
    (datetime(2027, 10, 1, 6, 0, tzinfo=UTC), True),     # Sep 30, 11 PM Pacific: still inside
    (datetime(2027, 10, 1, 7, 30, tzinfo=UTC), False),   # Oct 1, 12:30 AM Pacific: outside
])
def test_table_dates_use_the_pacific_day(rules: Rules, now: datetime, valid: bool) -> None:
    slots = {**MARIA, "rent_paid_by_others_to_landlord": "0.00"}
    done = rules.apply(make_case(slots, phase=Phase.result), now=now)
    if valid:
        assert (done.reason_code, done.estimate_monthly) == ("likely", 306)
        assert "rules_not_valid" not in [y.code for y in done.yellow_lines]
    else:
        assert (done.reason_code, done.estimate_monthly) == ("coordinator.unresolved", None)
        assert [y.code for y in done.yellow_lines] == ["rules_not_valid"]


# ---------------------------------------------------------------------------------------------- idempotency


@pytest.mark.parametrize("name", ["maria_g1", "jamal_g4", "grad_ta_g6b", "boundary_g8", "sofia_g3", "dorm_g9"])
def test_apply_twice_changes_nothing(rules: Rules, name: str) -> None:
    once = rules.apply(demo_case(name), now=NOW, turn=9)
    assert rules.apply(once, now=NOW, turn=9) == once


def test_g10_leftover_line_is_idempotent(rules: Rules) -> None:
    slots = {"consent": "true", "level": "undergrad", "units": "12", "age": "21", "lives_with_parent": "false",
             "household_food": "alone", "earned_monthly": "1200.00", "other_cash_monthly": "300.00",
             "rent_share": "900.00", "heat_cool": "false", "rent_paid_by_others_to_landlord": "0.00"}
    case = make_case(slots, phase=Phase.result, asked=[_flip("heat_cool"), _flip("rent_paid_by_others_to_landlord", 7)])
    once = rules.apply(case, now=NOW)
    twice = rules.apply(once, now=NOW)
    assert twice.yellow_lines == once.yellow_lines and twice.skipped == once.skipped
    assert [y.code for y in once.yellow_lines] == ["assumed.other_utils"]
    assert once.estimate_is_floor and once.estimate_monthly == 106
    edited = once.model_copy(deep=True)
    edited.slots[N.other_utils] = Slot(value="two_plus", state=SlotState.clear, source="coordinator")
    edited.yellow_lines[0].resolved = "edit"
    edited.yellow_lines[0].resolved_at = NOW
    redone = rules.apply(edited, now=NOW)
    assert redone.estimate_monthly == 159 and not redone.estimate_is_floor
    assert [(y.code, y.resolved) for y in redone.yellow_lines] == [("assumed.other_utils", "edit")]


# ---------------------------------------------------------------------------------------------- trace and wording


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_every_trace_step_names_a_table_source(rules: Rules, case: dict) -> None:
    from datetime import date

    facts = Facts.model_validate(case["facts"])
    today = date.fromisoformat(case["today"]) if "today" in case else TODAY
    ev = rules.evaluate(facts, today=today)
    ids = {s.id for s in rules.table.sources}
    assert all(step.source in ids for step in ev.trace), [(s.step, s.source) for s in ev.trace]
    assert not [s.result for s in ev.trace if REJECTION.search(s.result)]


def test_every_value_source_names_a_value_in_the_table(table_raw: dict) -> None:
    """Each value_sources key is a (dotted) path to a value of the table: the source map documents values, it does
    not add its own."""
    missing = []
    for key in table_raw["value_sources"]:
        node = table_raw
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                missing.append(key)
                break
            node = node[part]
    assert missing == []


def test_lines_and_trace_never_reject_and_hold_no_student_words(rules: Rules) -> None:
    words = "my landlord is my uncle and I make nine hundred"
    cases = [make_case({**MARIA, "units": "4", "income_changing_soon": "true"}, phase=Phase.result),
             make_case({**MARIA, "earned_monthly": "3500.00"}, phase=Phase.result),
             make_case({**MARIA, "household_food": "shared"}, phase=Phase.result),
             make_case({**GRAD, "grad_exemption": "none"}, phase=Phase.result),
             make_case({**MARIA, "dorm_on_campus": "true", "meals_per_week": "14"}, phase=Phase.result)]
    for case in cases:
        for slot in case.slots.values():
            slot.heard = words
        done = rules.apply(case, now=NOW)
        texts = [s.result for s in done.rule_trace] + [y.reason for y in done.yellow_lines]
        assert not [t for t in texts if REJECTION.search(t)]
        assert not [t for t in texts if words in t]
        assert all(not s.detail or words not in s.detail for s in done.skipped)


def test_yellow_kinds_and_ids(rules: Rules) -> None:
    done = rules.apply(make_case({**MARIA, "units": "4"}, phase=Phase.result), now=NOW)
    assert [(y.id, y.code, y.kind) for y in done.yellow_lines] == [
        ("y1", "assumed.rent_paid_by_others_to_landlord", YellowKind.assumed),
        ("y2", "abawd_possible", YellowKind.policy)]


# ---------------------------------------------------------------------------------------------- income split


@pytest.mark.parametrize("extra,crossing,x", [
    ({}, 1577, 1600),
    ({"rent_share": "600.00"}, 1275, 1300),            # half-up at the $25 midpoint
    ({"heat_cool": "true"}, 1616, 1600),               # nearest $50, not the next step up
])
def test_earned_split_point_is_the_halfway_income_rounded_to_the_step(rules: Rules, extra: dict, crossing: int,
                                                                       x: int) -> None:
    """docs/SPEC.md §5.6: X = the income where the estimate is halfway between the band ends' amounts, rounded to
    $50. `crossing` is the first whole dollar at or below the halfway amount (checked by a scan here)."""
    from decimal import Decimal

    slots = {**MARIA, "earned_monthly": ("2000.00", SlotState.assumed), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none", **extra}
    case = make_case(slots)

    def amount(income: int) -> int:
        world = {**slots, "earned_monthly": f"{income}.00"}
        facts = rules.facts_from_case(make_case(world), today=TODAY)
        ev = rules.evaluate(facts, today=TODAY)
        return ev.monthly if ev.reason_code == "likely" else 0

    half = Decimal(amount(1000) + amount(2000)) / 2
    assert amount(crossing) <= half < amount(crossing - 1)
    assert rules.earned_split_point(case, today=TODAY) == x


def test_earned_split_point_asks_at_the_limit_first(rules: Rules) -> None:
    slots = {**MARIA, "earned_monthly": ("3000.00", SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    assert rules.earned_split_point(make_case(slots), today=TODAY) == 2660


# ---------------------------------------------------------------------------------------------- the port


def test_rules_satisfy_the_port(rules: Rules) -> None:
    import inspect

    from gatorplate.contracts.ports import RulesPort

    assert isinstance(rules, RulesPort)
    for name in ("meta", "valid_on", "normalize_money", "facts_from_case", "evaluate", "flip_plan", "apply",
                 "filing_date", "compute_tracking"):
        want = inspect.signature(getattr(RulesPort, name))
        got = inspect.signature(getattr(Rules, name))
        assert [(p.name, p.kind, p.default) for p in got.parameters.values()] == \
            [(p.name, p.kind, p.default) for p in want.parameters.values()], name


def test_from_settings_reads_the_settings_path_and_time_zone(settings_test) -> None:
    rules = Rules.from_settings(settings_test)
    assert rules.table_path == settings_test.rules_table_path and rules.tz == settings_test.tz
    assert rules.valid_on(TODAY) and rules.meta().table_id == "CA-CalFresh-FFY2027"


# ---------------------------------------------------------------------------------------------- trace wording


def _trace(rules: Rules, cid: str) -> dict[str, tuple[str, str | None]]:
    case = next(c for c in GOLDEN if c["id"] == cid)
    ev = rules.evaluate(Facts.model_validate(case["facts"]), today=TODAY)
    return {s.step: (s.result, s.source) for s in ev.trace}


def test_trace_wording_for_allowances_negatives_and_the_minimum(rules: Rules) -> None:
    n1 = _trace(rules, "N1")["shelter"][0]
    assert n1 == ("Shelter: $900 + SUA (standard utility allowance) $686 − 50% of $1,463 ($731.50) = $854.50 → "
                  "capped at $769")
    n15 = _trace(rules, "N15")["benefit"][0]
    assert "= −$207" in n15 and "$-" not in n15
    g8 = _trace(rules, "G8")["benefit"]
    assert g8 == ("Estimate: $306 − 30% × $1,767 ($531) is below the minimum → $25 (1 person)", "ACIN-I-40-26")
    assert _trace(rules, "G1")["benefit"][1] == "7-CFR-273"


@pytest.mark.parametrize("y,m,d,hh,mm,filed,label,amount", [
    (2026, 10, 30, 17, 30, (2026, 11, 2), "November", 295),   # Friday after 5 PM → Monday in the next month
    (2026, 10, 31, 9, 0, (2026, 11, 2), "November", 295),     # Saturday → Monday
    (2026, 11, 1, 1, 30, (2026, 11, 2), "November", 295),     # the night the clocks fall back (Sunday)
    (2026, 11, 2, 16, 30, (2026, 11, 2), "November", 295),    # Monday before 5 PM (PST, UTC-8)
])
def test_first_month_across_months_and_the_clock_change(rules: Rules, y: int, m: int, d: int, hh: int, mm: int,
                                                       filed: tuple[int, int, int], label: str, amount: int) -> None:
    from datetime import date

    from gatorplate.clock import FixedClock

    clock = FixedClock.pacific(y, m, d, hh, mm)
    case = rules.apply(demo_case("maria_g1", now=clock.now()), now=clock.now())
    assert case.first_month.filed_on == date(*filed)
    assert (case.first_month.month_label, case.first_month.amount) == (label, amount)
    assert case.first_month.apply_date == clock.today()

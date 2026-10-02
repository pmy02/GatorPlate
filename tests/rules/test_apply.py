"""RulesPort.apply: the case-level results, the yellow lines it owns (idempotent by code), the not-asked entries, the
timeline and the first month; plus the demo cases' `expect` blocks."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from gatorplate.clock import FixedClock
from gatorplate.contracts import console_text
from gatorplate.contracts.common import Phase, SlotState, YellowKind, YellowResolution
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.rules import Rules

from .conftest import MARIA, NOW, demo_case, demo_expect, make_case

N = SlotName
SOFIA = {"consent": "true", "level": "undergrad", "units": "12", "age": "19", "lives_with_parent": "true"}


@pytest.mark.parametrize("name", ["maria_g1", "sofia_g3", "jamal_g4", "grad_ta_g6b", "boundary_g8", "dorm_g9"])
def test_demo_case_expect(rules: Rules, name: str) -> None:
    case = rules.apply(demo_case(name), now=NOW)
    expect = demo_expect(name)
    assert case.tier.value == expect["tier"]
    assert case.reason_code == expect["reason_code"]
    assert case.estimate_monthly == expect["estimate_monthly"]
    for key in ("estimate_is_floor", "expedited_possible", "summary"):
        if key in expect:
            assert getattr(case, key) == expect[key], key
    if "estimate_range" in expect:
        assert case.estimate_range.model_dump() == expect["estimate_range"]
    if "irt_applies" in expect:
        facts = rules.facts_from_case(case, today=date(2026, 10, 2))
        assert rules.evaluate(facts, today=date(2026, 10, 2)).irt_applies == expect["irt_applies"]
    if "skipped" in expect:
        got = [(s.slot.value, s.reason) for s in case.skipped]
        assert got == [(s["slot"], s["reason"]) for s in expect["skipped"]]
    for line in expect.get("yellow", []):
        found = next(y for y in case.yellow_lines if y.code == line["code"])
        assert found.kind.value == line["kind"]
        if "slot" in line:
            assert found.slot.value == line["slot"]
        if "reason" in line:
            assert found.reason == line["reason"]
    if "yellow_total" in expect:
        assert len(case.yellow_lines) == expect["yellow_total"]
    elif "yellow_open" in expect and name != "grad_ta_g6b":
        assert len([y for y in case.yellow_lines if y.resolved is None]) == expect["yellow_open"]
    assert case.rule_trace and case.table_id == "CA-CalFresh-FFY2027"


def test_maria_after_the_call(rules: Rules) -> None:
    case = rules.apply(demo_case("maria_g1"), now=NOW)
    assert case.first_month is not None
    assert (case.first_month.apply_date, case.first_month.filed_on) == (date(2026, 10, 2), date(2026, 10, 2))
    assert (case.first_month.amount, case.first_month.days_counted, case.first_month.month_label) == (296, 30,
                                                                                                    "October")
    assert case.first_month.estimate is True
    assert [s.detail for s in case.skipped] == [
        "Not asked — heating or cooling bill, same estimate either way",
        "Not asked — other utility bills, same estimate either way",
    ]
    assert [s.values for s in case.skipped] == [[306, 306], [306, 306, 306]]
    assert case.yellow_lines == []


def test_sofia_line_is_the_fixed_text(rules: Rules) -> None:
    case = rules.apply(make_case(SOFIA, phase=Phase.age_home, turn=3), now=NOW, turn=3)
    assert (case.tier.value, case.reason_code, case.estimate_monthly) == ("coordinator",
                                                                          "coordinator.parent_household", None)
    assert len(case.yellow_lines) == 1
    line = case.yellow_lines[0]
    assert (line.id, line.kind, line.code, line.slot) == ("y1", YellowKind.policy, "coordinator.parent_household",
                                                          N.lives_with_parent)
    assert line.reason == rules.table.parent_household_console_text == console_text.PARENT_HOUSEHOLD_TEXT
    assert line.reason == ("Under 22 and living with a parent — the parent's household is counted together. "
                           "Confirm, then help with a household application.")
    assert case.skipped == [] and case.estimate_range is None and case.first_month is None


def test_apply_is_idempotent_and_keeps_resolutions(rules: Rules) -> None:
    once = rules.apply(make_case(SOFIA), now=NOW)
    twice = rules.apply(once, now=NOW)
    assert twice.yellow_lines == once.yellow_lines
    confirmed = once.model_copy(deep=True)
    confirmed.yellow_lines[0].resolved = YellowResolution.confirm
    confirmed.yellow_lines[0].resolved_at = NOW
    again = rules.apply(confirmed, now=NOW)
    assert again.yellow_lines == confirmed.yellow_lines


def test_apply_does_not_mutate_its_input(rules: Rules) -> None:
    case = make_case(MARIA)
    before = case.model_dump()
    rules.apply(case, now=NOW, turn=6)
    assert case.model_dump() == before


def test_open_line_removed_when_the_route_changes(rules: Rules) -> None:
    routed = rules.apply(make_case(SOFIA), now=NOW)
    edited = routed.model_copy(deep=True)
    edited.slots[N.lives_with_parent] = Slot(value="false", state=SlotState.clear, changed_from="true")
    edited.slots.update({N(k): Slot(value=v, state=SlotState.clear) for k, v in MARIA.items()
                         if k not in SOFIA})
    redone = rules.apply(edited, now=NOW)
    assert redone.reason_code == "likely" and redone.yellow_lines == []


def test_dialogue_lines_are_untouched(rules: Rules) -> None:
    case = make_case(SOFIA)
    from gatorplate.contracts.case import YellowLine

    case.yellow_lines.append(YellowLine(id="y1", kind=YellowKind.student_question, code="student_question",
                                        reason=console_text.student_question("Do I need a bank account?"),
                                        created_at=NOW))
    done = rules.apply(case, now=NOW)
    assert [(y.id, y.code) for y in done.yellow_lines] == [("y1", "student_question"),
                                                           ("y2", "coordinator.parent_household")]


def test_maria_turn_by_turn(rules: Rules) -> None:
    """The golden dialogue's case checks: the range after the rent answer, then $306 settled."""
    before_rent = {k: v for k, v in MARIA.items() if k != "rent_share"}
    t5 = rules.apply(make_case(before_rent, phase=Phase.income, turn=5), now=NOW, turn=5)
    assert t5.tier is None and t5.estimate_range is None and t5.estimate_monthly is None
    rent = make_case(MARIA, phase=Phase.housing, turn=5)
    rent.slots[N.rent_share].turn = 6
    t6 = rules.apply(rent, now=NOW, turn=6)
    assert t6.estimate_range.model_dump() == {"lo": 155, "hi": 306, "settled": False}
    assert t6.skipped == []  # the flip question is still to be asked
    assert t6.timeline[-1].model_dump(include={"turn", "slots", "lo", "hi"}) == {
        "turn": 6, "slots": [N.rent_share], "lo": 155, "hi": 306}
    answered = t6.model_copy(deep=True)
    answered.asked.append(_flip("rent_paid_by_others_to_landlord", 6))
    answered.slots[N.rent_paid_by_others_to_landlord] = Slot(value="0.00", state=SlotState.clear, turn=7)
    t7 = rules.apply(answered, now=NOW, turn=7)
    assert (t7.tier.value, t7.estimate_monthly) == ("likely", 306)
    assert t7.estimate_range.model_dump() == {"lo": 306, "hi": 306, "settled": True}
    assert [(s.slot.value, s.reason) for s in t7.skipped] == [("heat_cool", "no_effect"), ("other_utils", "no_effect")]
    assert [p.turn for p in t7.timeline] == [6, 7]
    cash = t7.model_copy(deep=True)
    cash.slots[N.cash_on_hand] = Slot(value="1000.00", state=SlotState.clear, turn=8)
    t8 = rules.apply(cash, now=NOW, turn=8)
    assert t8.expedited_possible == "no"
    assert t8.summary == "Undergrad · 1 person · work $900 · rent $1,100"


def _flip(slot: str, turn: int):
    from gatorplate.contracts.case import AskedQuestion

    return AskedQuestion(turn=turn, key="flip.x", slots=[N(slot)], kind="flip")


def test_jamal_expedited_yes(rules: Rules) -> None:
    case = rules.apply(demo_case("jamal_g4"), now=NOW)
    assert (case.estimate_monthly, case.expedited_possible) == (306, "yes")
    assert case.skipped == [] and case.yellow_lines == []


def test_rules_not_valid_outside_the_dates(rules: Rules) -> None:
    later = datetime(2027, 10, 1, 17, tzinfo=UTC)
    case = rules.apply(make_case({**MARIA, "rent_paid_by_others_to_landlord": "0.00"}, phase=Phase.result),
                       now=later)
    assert (case.tier.value, case.reason_code, case.estimate_monthly) == ("coordinator", "coordinator.unresolved",
                                                                          None)
    assert [(y.code, y.reason) for y in case.yellow_lines] == [("rules_not_valid", console_text.RULES_NOT_VALID)]
    assert case.estimate_range is None and case.first_month is None
    assert not rules.valid_on(later.date()) and rules.valid_on(date(2027, 9, 30))


def test_work_rule_line(rules: Rules) -> None:
    g11 = {**MARIA, "units": "4", "rent_paid_by_others_to_landlord": "0.00"}
    case = rules.apply(make_case(g11, phase=Phase.result), now=NOW)
    assert case.estimate_monthly == 306
    line = next(y for y in case.yellow_lines if y.code == "abawd_possible")
    assert line.reason == ("Fewer than 8 units: the county may apply the 3-month work rule unless the student works "
                           "80 hours a month.")
    assert line.kind == YellowKind.policy and line.slot == N.units


def test_work_rule_line_for_a_graduate_student(rules: Rules) -> None:
    """A graduate student below half-time (golden N5-b): half-time depends on the program, not on 8 units."""
    grad = {**MARIA, "level": "grad", "half_time": "false", "age": "27", "earned_monthly": "400.00",
            "rent_paid_by_others_to_landlord": "0.00"}
    grad.pop("units", None)
    case = rules.apply(make_case(grad, phase=Phase.result), now=NOW)
    line = next(y for y in case.yellow_lines if y.code == "abawd_possible")
    assert line.reason == ("Less than half-time: the county may apply the 3-month work rule unless the student works "
                           "80 hours a month.")


def test_income_changing_soon_line(rules: Rules) -> None:
    slots = {**MARIA, "income_changing_soon": "true", "rent_paid_by_others_to_landlord": "0.00"}
    case = rules.apply(make_case(slots, phase=Phase.result), now=NOW)
    assert [y.code for y in case.yellow_lines] == ["income_changing_soon"]


def test_past_the_flip_phase_an_askable_slot_is_a_leftover(rules: Rules) -> None:
    """The dialogue moved on without the rent question: the default stands with a yellow line (spread $151)."""
    case = rules.apply(make_case(MARIA, phase=Phase.result), now=NOW)
    assert case.estimate_monthly == 306 and not case.estimate_is_floor  # the default gives the highest amount
    line = next(y for y in case.yellow_lines if y.code == "assumed.rent_paid_by_others_to_landlord")
    assert line.reason == "Rent paid by someone else: assumed $0 (could be as low as $155)"
    assert (line.kind, line.assumed, line.effect.delta_usd) == (YellowKind.assumed, "$0", 151)


def test_ta_ra_line(rules: Rules) -> None:
    case = rules.apply(demo_case("grad_ta_g6b"), now=NOW)
    assert [(y.code, y.reason) for y in case.yellow_lines] == [("ta_ra_income_type", console_text.TA_RA_INCOME_TYPE)]


def test_ended_early_keeps_no_result(rules: Rules) -> None:
    case = make_case(MARIA, phase=Phase.end, live=False, ended_early=True)
    done = rules.apply(case, now=NOW)
    assert done.tier is None and done.reason_code is None and done.estimate_monthly is None
    assert done.first_month is None
    assert done.estimate_range is not None  # the range bar is kept


@pytest.mark.parametrize("slot,code", [("already_receiving", "info.already_receiving"),
                                       ("applied_waiting_interview", "info.interview_waiting")])
def test_info_routes(rules: Rules, slot: str, code: str) -> None:
    case = rules.apply(make_case({"consent": "true", slot: "true"}, phase=Phase.result), now=NOW)
    assert (case.reason_code, case.estimate_monthly) == (code, None)
    assert case.yellow_lines == []
    status = rules.apply(make_case({"consent": "true", slot: "true"}, route_override="other_help.status"), now=NOW)
    assert status.reason_code == "other_help.status"


@pytest.mark.parametrize("override,code", [("other_help.status", "other_help.status"),
                                           ("coordinator.status_complex", "coordinator.status_complex"),
                                           ("coordinator.elderly_disabled", "coordinator.elderly_disabled")])
def test_route_overrides(rules: Rules, override: str, code: str) -> None:
    case = rules.apply(make_case(MARIA, route_override=override), now=NOW)
    assert case.reason_code == code
    lines = [y for y in case.yellow_lines]
    if code.startswith("coordinator."):
        assert len(lines) == 1 and lines[0].slot is None
        assert "not stored" in lines[0].reason
    else:
        assert lines == []
    assert all("F-1" not in s.result and "LPR" not in s.result for s in case.rule_trace)


@pytest.mark.parametrize("clock,filed,amount", [
    (FixedClock.pacific(2026, 10, 1, 23, 30), date(2026, 10, 2), 296),
    (FixedClock.pacific(2026, 10, 2, 16, 59), date(2026, 10, 2), 296),
    (FixedClock.pacific(2026, 10, 2, 17, 1), date(2026, 10, 5), 266),
    (FixedClock.pacific(2026, 10, 3, 10, 0), date(2026, 10, 5), 266),
    (FixedClock.pacific(2026, 10, 2, 23, 30), date(2026, 10, 5), 266),
])
def test_first_month_uses_the_filing_estimate(rules: Rules, clock: FixedClock, filed: date, amount: int) -> None:
    case = rules.apply(demo_case("maria_g1", now=clock.now()), now=clock.now())
    assert case.first_month.filed_on == filed and case.first_month.amount == amount
    assert case.first_month.apply_date == clock.today()


def test_yellow_ids_continue(rules: Rules) -> None:
    case = make_case({**MARIA, "units": "4", "income_changing_soon": "true",
                      "rent_paid_by_others_to_landlord": "0.00"}, phase=Phase.result)
    done = rules.apply(case, now=NOW)
    assert [(y.id, y.code) for y in done.yellow_lines] == [("y1", "abawd_possible"), ("y2", "income_changing_soon")]


def test_capped_call_with_no_income_answer_is_unresolved(rules: Rules) -> None:
    """At the brain's turn or time cap the result uses the current defaults, but a work income the student never
    answered is never read as $0 (that would state the highest amount): coordinator.unresolved with its line."""
    slots = {k: v for k, v in MARIA.items() if k not in ("earned_monthly", "other_cash_monthly", "rent_share")}
    case = rules.apply(make_case(slots, phase=Phase.result, flags=["turn_cap"]), now=NOW)
    assert case.reason_code == "coordinator.unresolved" and case.estimate_monthly is None
    line = next(y for y in case.yellow_lines if y.code == "coordinator.unresolved")
    assert line.slot == SlotName.earned_monthly and "Still open and could change the result" in line.reason


def test_capped_call_with_income_answered_keeps_its_estimate(rules: Rules) -> None:
    """A missing rent only lowers the estimate, so a capped call with the income answered keeps its amount."""
    slots = {k: v for k, v in MARIA.items() if k != "rent_share"}
    case = rules.apply(make_case(slots, phase=Phase.result, flags=["turn_cap"]), now=NOW)
    assert case.reason_code == "likely" and case.estimate_monthly is not None



def test_under_22_with_the_living_situation_unknown_is_unresolved(rules: Rules) -> None:
    """A closed-mode call asks only the age band: under 22 with lives_with_parent unknown never gets an amount that
    could belong to the parents' household."""
    slots = {k: v for k, v in MARIA.items() if k != "lives_with_parent"}
    case = rules.apply(make_case({**slots, "rent_paid_by_others_to_landlord": "0.00"}, phase=Phase.result), now=NOW)
    assert case.reason_code == "coordinator.unresolved" and case.estimate_monthly is None
    line = next(y for y in case.yellow_lines if y.code == "coordinator.unresolved")
    assert line.slot == SlotName.lives_with_parent


def test_22_or_older_with_the_living_situation_unknown_keeps_its_estimate(rules: Rules) -> None:
    slots = {k: v for k, v in MARIA.items() if k != "lives_with_parent"}
    case = rules.apply(make_case({**slots, "age": "22", "rent_paid_by_others_to_landlord": "0.00"},
                                 phase=Phase.result), now=NOW)
    assert case.reason_code == "likely" and case.estimate_monthly == 306

"""Value of information (docs/SPEC.md §5.6): the required results, the switch, the food question, leftovers and the
expedited outlook over the remaining worlds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gatorplate.contracts.case import AskedQuestion, Case
from gatorplate.contracts.common import Phase, SlotSource, SlotState
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.rules import Rules

from .conftest import MARIA, NOW, TABLE, TODAY, make_case

N = SlotName
NATURAL_ANSWER = {"rent_paid_by_others_to_landlord": "0.00", "heat_cool": "false", "other_utils": "none"}

# The cases of the table's voi.required_results, before the question picker runs.
BASE = {
    "G1": MARIA,
    "G1-b": MARIA,
    "G1-c": MARIA,
    "G6-b": {"consent": "true", "level": "grad", "half_time": "true", "grad_exemption": "ta_ra", "ta_ra": "true",
             "age": "26", "lives_with_parent": "false", "household_food": "alone", "earned_monthly": "1800.00",
             "other_cash_monthly": "0.00", "rent_share": "1000.00"},
    "G10": {"consent": "true", "level": "undergrad", "units": "12", "age": "21", "lives_with_parent": "false",
            "household_food": "alone", "earned_monthly": "1200.00", "other_cash_monthly": "300.00",
            "rent_share": "900.00"},
}


def ask_loop(rules: Rules, case: Case, answers: dict[str, str]) -> tuple[Case, list[str]]:
    """Plays the flip phase: ask what the plan says, answer from `answers` (else the natural default), re-plan."""
    asked: list[str] = []
    turn = 10
    while True:
        budget = rules.table.voi.max_questions - len(asked)
        plan = rules.flip_plan(case, today=TODAY, budget=budget)
        assert len(plan.ask) <= max(budget, 0)
        if not plan.ask:
            return case, asked
        top = plan.ask[0]
        name = top.slot.value
        asked.append(name)
        raw = answers.get(name, NATURAL_ANSWER.get(name))
        if raw == "rent_share":
            raw = case.slots[N.rent_share].value
        case = case.model_copy(deep=True)
        case.asked.append(AskedQuestion(turn=turn, key=rules.table.voi.slots[name].ask_key, slots=[top.slot],
                                        kind="flip", reason=top.reason, delta_usd=top.spread_usd,
                                        outcomes=[o.label for o in top.outcomes]))
        turn += 1
        case.slots[top.slot] = Slot(value=raw, state=SlotState.clear, source=SlotSource.llm, turn=turn)


@pytest.mark.parametrize("cid", ["G1", "G1-b", "G1-c", "G6-b", "G10"])
def test_required_results(rules: Rules, cid: str) -> None:
    req = next(r for r in rules.table.voi.required_results if r.case == cid)
    case, asked = ask_loop(rules, make_case(BASE[cid]), req.answers)
    assert asked == req.asked
    done = rules.apply(case.model_copy(update={"phase": Phase.result}), now=NOW)
    assert done.tier.value == "likely" and done.estimate_monthly == req.amount
    skipped = {s.slot.value: s.reason for s in done.skipped}
    for name in req.no_effect:
        assert skipped.get(name) == "no_effect", name
    for name in req.below_threshold:
        assert skipped.get(name) == "below_threshold", name
    assumed = [y for y in done.yellow_lines if y.code.startswith("assumed.")]
    assert [y.slot.value for y in assumed] == req.yellow
    if req.yellow_could_be_up_to is not None:
        assert assumed[0].reason == ("Other utility bills: assumed none (could be up to "
                                     f"${req.yellow_could_be_up_to:,})")
        assert done.estimate_is_floor
        assert skipped["other_utils"] == "max_questions"


def test_g1_flip_reason_and_outcomes(rules: Rules) -> None:
    plan = rules.flip_plan(make_case(MARIA), today=TODAY, budget=2)
    assert [c.slot.value for c in plan.ask] == ["rent_paid_by_others_to_landlord"]
    top = plan.ask[0]
    assert top.reason == "could change the estimate by $151: $155 or $306"
    assert top.spread_usd == 151 and not top.tier_changes and top.decision == "ask"
    assert [o.label for o in top.outcomes] == ["No → $306/mo", "Yes → $155/mo"]
    assert {c.slot.value: c.decision for c in plan.not_asked} == {"heat_cool": "no_effect", "other_utils": "no_effect"}
    heat = next(c for c in plan.not_asked if c.slot == N.heat_cool)
    assert heat.reason == "Not asked — heating or cooling bill, same estimate either way"
    assert plan.estimate_range.model_dump() == {"lo": 155, "hi": 306, "settled": False}
    assert plan.expedited_outlook is None  # cash not known yet


def test_g6b_and_g10_ask_order(rules: Rules) -> None:
    g6b = rules.flip_plan(make_case(BASE["G6-b"]), today=TODAY, budget=2)
    assert [c.slot.value for c in g6b.ask] == ["heat_cool", "other_utils"]
    assert [c.spread_usd for c in g6b.ask] == [114, 53]
    g10 = rules.flip_plan(make_case(BASE["G10"]), today=TODAY, budget=2)
    assert [c.slot.value for c in g10.ask] == ["heat_cool", "rent_paid_by_others_to_landlord"]
    assert [c.spread_usd for c in g10.ask] == [117, 81]


def test_budget_limits_the_plan(rules: Rules) -> None:
    plan = rules.flip_plan(make_case(BASE["G6-b"]), today=TODAY, budget=1)
    assert [c.slot.value for c in plan.ask] == ["heat_cool"]
    plan0 = rules.flip_plan(make_case(BASE["G6-b"]), today=TODAY, budget=0)
    assert plan0.ask == []
    assert {c.slot.value: c.decision for c in plan0.not_asked}["heat_cool"] == "assume_default"


@pytest.mark.parametrize("earned", ["800.00", "1000.00"])
def test_n25_asks_nothing(rules: Rules, earned: str) -> None:
    """Flat region: rent $1,100 and work $800 or $1,000 give $306 in every utility world."""
    slots = {**MARIA, "earned_monthly": earned, "rent_paid_by_others_to_landlord": "0.00"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    assert plan.ask == []
    assert plan.estimate_range.model_dump() == {"lo": 306, "hi": 306, "settled": True}


def test_n25_band_needs_no_split_question(rules: Rules) -> None:
    """An unclear work income in the lowest band ($0 to $1,000) changes nothing here: no earned_split question."""
    slots = {**MARIA, "earned_monthly": ("1000.00", SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    assert plan.ask == []
    assert rules.income_band_edges(1) == rules.table.voi.income_band.edges_1_person == [1000, 2000]


def test_unclear_food_answer_plans_the_food_flip(rules: Rules) -> None:
    before_income = {k: v for k, v in MARIA.items() if k not in ("earned_monthly", "other_cash_monthly", "rent_share")}
    case = make_case({**before_income, "household_food": (None, SlotState.unclear)}, phase=Phase.household)
    plan = rules.flip_plan(case, today=TODAY, budget=2)
    assert [c.slot.value for c in plan.ask] == ["household_food"]
    top = plan.ask[0]
    assert top.tier_changes and top.reason == "could change the result: likely or coordinator check"
    assert rules.table.voi.slots["household_food"].ask_key == "flip.household_food"
    together = case.model_copy(deep=True)
    together.slots[N.household_food] = Slot(value="shared", state=SlotState.clear, turn=4)
    done = rules.apply(together, now=NOW)
    assert (done.tier.value, done.reason_code) == ("coordinator", "coordinator.shared_household")
    assert [y.code for y in done.yellow_lines] == ["coordinator.shared_household"]
    apart = case.model_copy(deep=True)
    apart.slots[N.household_food] = Slot(value="separate", state=SlotState.clear, turn=4)
    assert rules.apply(apart, now=NOW).tier is None  # no result before income and housing


def test_leftover_tier_change_gives_unresolved(rules: Rules) -> None:
    """The food answer stays open while the question limit is used up: coordinator.unresolved."""
    slots = {**MARIA, "household_food": (None, SlotState.unclear)}
    asked = [AskedQuestion(turn=6, key="flip.rent_paid_by_others", slots=[N.rent_paid_by_others_to_landlord],
                           kind="flip"),
             AskedQuestion(turn=7, key="flip.heat_cool", slots=[N.heat_cool], kind="flip")]
    case = make_case({**slots, "rent_paid_by_others_to_landlord": "0.00", "heat_cool": "false"}, asked=asked)
    plan = rules.flip_plan(case, today=TODAY, budget=0)
    food = next(c for c in plan.not_asked if c.slot == N.household_food)
    assert food.decision == "coordinator" and food.tier_changes
    done = rules.apply(case, now=NOW)
    assert (done.tier.value, done.reason_code, done.estimate_monthly) == ("coordinator", "coordinator.unresolved",
                                                                           None)
    line = next(y for y in done.yellow_lines if y.code == "coordinator.unresolved")
    assert line.reason == "Still open and could change the result: Buys and cooks food. Confirm it with the student."
    assert line.slot == N.household_food and line.effect.kind == "tier"
    assert any(s.slot == N.household_food and s.reason == "max_questions" for s in done.skipped)


def test_conservative_switch_turns_g6b_into_25(rules: Rules, tmp_path: Path) -> None:
    copy = tmp_path / "ca_conservative.json"
    shutil.copy(TABLE, copy)
    raw = json.loads(copy.read_text(encoding="utf-8"))
    raw["voi"]["default_mode"] = "conservative"
    copy.write_text(json.dumps(raw), encoding="utf-8")
    switched = Rules(copy)
    answered = {**BASE["G6-b"], "heat_cool": "false", "other_utils": "none"}
    natural = rules.apply(make_case(answered, phase=Phase.result), now=NOW)
    conservative = switched.apply(make_case(answered, phase=Phase.result), now=NOW)
    assert natural.estimate_monthly == 55
    assert conservative.estimate_monthly == 25
    assert rules.facts_from_case(make_case(answered), today=TODAY).rent_paid_by_others_to_landlord == 0
    assert switched.facts_from_case(make_case(answered), today=TODAY).rent_paid_by_others_to_landlord == 1000


@pytest.mark.parametrize("utility,outlook", [(None, "maybe"), ("none", "no"), ("heat", "yes")])
def test_n6_outlook_over_utility_worlds(rules: Rules, utility: str | None, outlook: str) -> None:
    """N6-b/N6-c facts (work $600, rent $1,000, cash $450): never mentioned utilities → maybe, with no question."""
    slots = {"consent": "true", "level": "undergrad", "units": "12", "age": "22", "lives_with_parent": "false",
             "household_food": "alone", "earned_monthly": "600.00", "other_cash_monthly": "0.00",
             "rent_share": "1000.00", "rent_paid_by_others_to_landlord": "0.00", "cash_on_hand": "450.00"}
    if utility == "none":
        slots |= {"heat_cool": "false", "other_utils": "none"}
    elif utility == "heat":
        slots |= {"heat_cool": "true"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    assert plan.ask == []
    assert plan.expedited_outlook == outlook
    done = rules.apply(make_case(slots, phase=Phase.card), now=NOW)
    assert done.expedited_possible == outlook and done.estimate_monthly == 306


def test_maria_outlook_counts_the_unasked_heating_bill(rules: Rules) -> None:
    slots = {**MARIA, "rent_paid_by_others_to_landlord": "0.00"}
    assert rules.expedited_screen(make_case(slots), today=TODAY)
    assert rules.flip_plan(make_case({**slots, "cash_on_hand": "1000.00"}), today=TODAY, budget=1)\
        .expedited_outlook == "no"
    assert rules.flip_plan(make_case({**slots, "cash_on_hand": "800.00"}), today=TODAY, budget=1)\
        .expedited_outlook == "maybe"


def test_expedited_screen_any_world(rules: Rules) -> None:
    """Work $1,050, rent $1,000: no screen in the no-bills world, but the heating world ($1,686) is above gross."""
    slots = {**MARIA, "earned_monthly": "1050.00", "rent_share": "1000.00", "rent_paid_by_others_to_landlord": "0.00"}
    assert rules.evaluate(rules.facts_from_case(make_case(slots), today=TODAY), today=TODAY).expedited_screen is False
    assert rules.expedited_screen(make_case(slots), today=TODAY) is True
    answered = {**slots, "heat_cool": "false", "other_utils": "none"}
    assert rules.expedited_screen(make_case(answered), today=TODAY) is False


def test_expedited_never_flips(rules: Rules) -> None:
    assert rules.table.voi.expedited_never_flips and not rules.table.expedited.is_flip_question
    assert "cash_on_hand" not in rules.table.voi.slots


def test_answered_before_asked_needs_no_question(rules: Rules) -> None:
    slots = {**MARIA, "rent_paid_by_others_to_landlord": "0.00", "heat_cool": "true"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    assert plan.ask == [] and plan.not_asked == []
    assert plan.estimate_range.model_dump() == {"lo": 306, "hi": 306, "settled": True}


def test_homeless_has_no_rent_or_utility_questions(rules: Rules) -> None:
    jamal = {"consent": "true", "level": "undergrad", "units": "12", "age": "24", "lives_with_parent": "false",
             "homeless": "true", "household_food": "separate", "earned_monthly": "0.00", "other_cash_monthly": "0.00",
             "homeless_shelter_cost_monthly": "0.00"}
    plan = rules.flip_plan(make_case(jamal), today=TODAY, budget=2)
    assert plan.ask == [] and plan.not_asked == []
    assert plan.estimate_range.model_dump() == {"lo": 306, "hi": 306, "settled": True}


def test_no_plan_before_income_and_housing(rules: Rules) -> None:
    early = {k: v for k, v in MARIA.items() if k != "rent_share"}
    plan = rules.flip_plan(make_case(early, phase=Phase.income), today=TODAY, budget=2)
    assert plan.ask == [] and plan.estimate_range is None and plan.expedited_outlook is None


def test_unclear_cash_from_family_band(rules: Rules) -> None:
    """'Sometimes' (an unclear cash answer, no amount): candidates $0 and the band top; conservative = the top."""
    slots = {**MARIA, "earned_monthly": "1200.00", "rent_share": "900.00",
             "other_cash_monthly": (None, SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    cash = next(c for c in [*plan.ask, *plan.not_asked] if c.slot == N.other_cash_monthly)
    assert [o.value for o in cash.outcomes] == ["0.00", "300.00"]
    assert cash.default_value == "300.00"
    facts = rules.facts_from_case(make_case(slots), today=TODAY)
    assert sum(i.amount for i in facts.incomes if i.kind == "unearned") == 300


def test_earned_band_split_point(rules: Rules) -> None:
    """Work income 'between $1,000 and $2,000' (stored at the conservative top): the split X sits where the
    estimate is halfway between the band ends' amounts, on a $50 step."""
    slots = {**MARIA, "earned_monthly": ("2000.00", SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    case = make_case(slots)
    plan = rules.flip_plan(case, today=TODAY, budget=2)
    earned = next(c for c in plan.ask if c.slot == N.earned_monthly)
    assert [o.value for o in earned.outcomes] == ["1000.00", "2000.00"]
    assert earned.default_value == "2000.00"
    x = rules.earned_split_point(case, today=TODAY)
    assert x is not None and 1000 <= x <= 2000 and x % rules.table.voi.income_band.round_to_usd == 0
    assert rules.earned_split_point(make_case(MARIA), today=TODAY) is None


def test_band_answer_stored_as_assumed_is_measured(rules: Rules) -> None:
    """The dialogue stores a band answer at its conservative end with state assumed: still a range for the picker."""
    slots = {**MARIA, "earned_monthly": ("2000.00", SlotState.assumed), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    assert [c.slot for c in plan.ask] == [N.earned_monthly]
    asked = [AskedQuestion(turn=6, key="flip.earned_split", slots=[N.earned_monthly], kind="flip")]
    again = rules.flip_plan(make_case(slots, asked=asked), today=TODAY, budget=1)
    assert again.ask == []  # one flip per slot
    done = rules.apply(make_case(slots, asked=asked, phase=Phase.result), now=NOW)
    assert not [y for y in done.yellow_lines if y.code.startswith("assumed.")]  # the dialogue's unclear line


def test_unknown_income_spans_up_to_the_limit(rules: Rules) -> None:
    slots = {**MARIA, "earned_monthly": (None, SlotState.unclear), "rent_paid_by_others_to_landlord": "0.00",
             "heat_cool": "false", "other_utils": "none"}
    plan = rules.flip_plan(make_case(slots), today=TODAY, budget=2)
    earned = next(c for c in plan.ask if c.slot == N.earned_monthly)
    assert [o.value for o in earned.outcomes] == ["0.00", "2660.00"] and earned.default_value == "2660.00"
    assert rules.facts_from_case(make_case(slots), today=TODAY).incomes[0].amount == 2660

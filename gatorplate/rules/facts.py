"""From a case's slots to the engine's Facts (docs/SPEC.md §5.2 and §5.6).

Slot values are canonical strings (money is already monthly). Missing facts take neutral values that never route a
case on their own: a route needs the student's actual answer. The question-picker slots (`voi.slots`) are filled from
a `world` mapping chosen by the value-of-information module (natural defaults, conservative values or one candidate).
`roommates_count` is never read here: the CalFresh rules do not use it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import SlotState
from gatorplate.contracts.rules_io import Facts, IncomeItem, RulesTable
from gatorplate.contracts.slots import SLOT_SPECS, SlotName, decode_value
from gatorplate.contracts.summary import household_size
from gatorplate.rules.money import ZERO

N = SlotName
# Words in the student's own quote (English or Spanish) that say the other income is unemployment benefits.
UNEMPLOYMENT_WORDS = ("unemployment", "desempleo")


def value(case: Case, name: SlotName, world: Mapping[SlotName, str] | None = None):
    """The decoded value of a slot (the world's value first), or None when the student has not given one."""
    raw = world.get(name) if world is not None and name in world else None
    if raw is None:
        slot = case.slots.get(name)
        raw = slot.value if slot is not None else None
    if raw is None:
        return None
    try:
        return decode_value(name, raw)
    except (TypeError, ValueError):
        return None


def state(case: Case, name: SlotName) -> SlotState:
    slot = case.slots.get(name)
    if slot is None:
        return SlotState.missing
    if slot.state == SlotState.missing and slot.value is not None:
        return SlotState.clear
    return slot.state


def answered(case: Case, name: SlotName) -> bool:
    """The student answered (a value, or an unclear answer the question picker resolves)."""
    return value(case, name) is not None or state(case, name) == SlotState.unclear


def _money(case: Case, name: SlotName, world: Mapping[SlotName, str] | None = None) -> Decimal:
    found = value(case, name, world)
    return found if isinstance(found, Decimal) else ZERO


def _bool(case: Case, name: SlotName, world: Mapping[SlotName, str] | None = None) -> bool:
    return value(case, name, world) is True


def works_80h_month(table: RulesTable, case: Case) -> bool:
    """True when the student's work reaches the work rule's monthly hours: a stated hourly basis
    (hours a week × the weekly factor), or the graduate exemption for 20 hours a week of paid work."""
    if value(case, N.grad_exemption) == "work20h":
        return True
    slot = case.slots.get(N.earned_monthly)
    basis = slot.basis if slot is not None else None
    if basis is None or basis.hours_per_week is None:
        return False
    monthly_hours = basis.hours_per_week * table.conversion.multipliers.week
    return monthly_hours >= table.abawd.work_requirement_hours_month


def receives_unemployment(case: Case) -> bool:
    """True when the student's words for their other income name unemployment benefits."""
    slot = case.slots.get(N.unearned_monthly)
    if slot is None or not isinstance(value(case, N.unearned_monthly), Decimal) or value(case, N.unearned_monthly) <= 0:
        return False
    words = " ".join(t for t in (slot.heard, slot.heard_en) if t).lower()
    return any(w in words for w in UNEMPLOYMENT_WORDS)


def utility(case: Case, world: Mapping[SlotName, str] | None = None) -> str:
    """heat_cool true gives heat_cool; otherwise other_utils two_plus / phone_only / none (table utility_rules)."""
    if _bool(case, N.heat_cool, world):
        return "heat_cool"
    other = value(case, N.other_utils, world)
    return {"two_plus": "two_other", "phone_only": "phone_only"}.get(other, "none")


def _incomes(case: Case, world: Mapping[SlotName, str] | None) -> list[IncomeItem]:
    items: list[IncomeItem] = []
    kinds = (
        (N.earned_monthly, "earned", False),
        (N.work_study_monthly, "earned", True),
        (N.gig_monthly, "self_employment", False),
        (N.unearned_monthly, "unearned", False),
        (N.other_cash_monthly, "unearned", False),
    )
    for name, kind, excluded in kinds:
        amount = _money(case, name, world)
        if amount > ZERO:
            items.append(IncomeItem(amount=amount, freq="monthly", kind=kind, excluded=excluded,
                                    label=SLOT_SPECS[name].label))
    return items


def build_facts(table: RulesTable, case: Case, world: Mapping[SlotName, str] | None = None, *,
                apply_date: date | None = None) -> Facts:
    """Facts for one world: the case's answers, with the question-picker slots taken from `world`."""
    age_value = value(case, N.age)
    age = age_value if isinstance(age_value, int) else table.student_rule_age[0]
    level = value(case, N.level) or "undergrad"
    units = value(case, N.units)
    exemption = value(case, N.grad_exemption)
    exemption = exemption if exemption in table.grad.exemptions else None
    stated_half_time = value(case, N.half_time)
    if isinstance(stated_half_time, bool):
        half_time = stated_half_time
    elif level == "grad":
        half_time = exemption != "under_half_time"
    elif isinstance(units, int):
        half_time = units >= table.half_time.undergrad_units_at_least
    else:
        half_time = True
    children = value(case, N.children_count)
    youngest = value(case, N.youngest_child_age)
    # Only a stated age counts: an unknown age leaves the work-rule line on, so a coordinator checks it (the
    # line's other inputs default the same way).
    child_under14 = (isinstance(children, int) and children > 0
                     and isinstance(youngest, int) and youngest < table.abawd.child_exempt_under)
    with_parent = _bool(case, N.lives_with_parent)
    food = value(case, N.household_food, world)
    if food is None:
        food = "separate" if _bool(case, N.roommates) else "alone"
    rent = _money(case, N.rent_share)
    paid_by_others = min(_money(case, N.rent_paid_by_others_to_landlord, world), rent)
    status = value(case, N.volunteered_status)
    route = case.route_override
    status_route = {"other_help.status": "other_help", "coordinator.status_complex": "coordinator"}.get(route or "")
    cash = value(case, N.cash_on_hand)
    return Facts(
        lang=case.lang,
        volunteered_status=status if isinstance(status, str) else None,
        elderly_or_disabled=route == "coordinator.elderly_disabled" or _bool(case, N.elderly_or_disabled),
        age=age,
        level=level,
        public_ca_degree_program=level != "not_degree",
        half_time=half_time,
        units=units if isinstance(units, int) else None,
        grad_exemption=exemption,
        child_under14_in_hh=child_under14,
        under22_with_parent=with_parent and isinstance(age_value, int) and age < table.parent_household_age_under,
        dorm_on_campus=_bool(case, N.dorm_on_campus),
        meals_per_week=value(case, N.meals_per_week) or 0,
        dorm_meals_over_10=value(case, N.dorm_meals_over_10),
        household_food=food,
        household_size=household_size(case),
        spouse_student=_bool(case, N.spouse_student),
        boarder=_bool(case, N.boarder),
        homeless=_bool(case, N.homeless),
        homeless_shelter_cost=_money(case, N.homeless_shelter_cost_monthly),
        incomes=_incomes(case, world),
        rent_share=rent,
        rent_paid_by_others_to_landlord=paid_by_others,
        utility=utility(case, world),
        dependent_care=_money(case, N.dependent_care_monthly),
        cash_on_hand=cash if isinstance(cash, Decimal) else None,
        apply_date=apply_date,
        income_changing_soon=_bool(case, N.income_changing_soon),
        works_80h_month=works_80h_month(table, case),
        receives_unemployment=receives_unemployment(case),
        status_route=status_route,
    )

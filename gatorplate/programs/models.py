"""The value models of the programs table (`value_models`), with Decimal and the table's rounding.

Every value is floored to the dollar; a display value is floored to `money.display_round_down_to`; the share amount to
`money.share_round_down_to`. No float, no round(), and every number comes from the table (docs/SPEC.md §5.10 "Value
models"). Each model also returns English trace lines with its numbers for the console ("How" column).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from gatorplate.contracts.slots import CENT
from gatorplate.programs.facts import ProgramFacts
from gatorplate.programs.table import (
    BreaksRow,
    CalEitcRow,
    CareRow,
    EitcParams,
    FaresRow,
    FederalEitcRow,
    FlatRow,
    YctcRow,
)

# The table's transit_breaks model prices this choice with the BART average fare; every other ride choice is Muni.
BART_CHOICE = "weekdays_bart"
ZERO = Decimal(0)


def floor_dollar(value: Decimal | int) -> int:
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def floor_to(value: int, step: int) -> int:
    """Floor a whole-dollar amount to a multiple of `step` ($10 display, $100 share)."""
    return (value // step) * step


def usd(value: Decimal | int) -> str:
    """Console money: "$3,672", "$19.85" (cents only when there are cents)."""
    number = Decimal(value)
    if number == number.to_integral_value():
        return f"${int(number):,}"
    return f"${number.quantize(CENT, rounding=ROUND_HALF_UP):,}"


@dataclass
class Valued:
    value: int
    basis: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------- CalFresh

def calfresh_annual(months: int, monthly: int) -> Valued:
    value = months * monthly
    return Valued(value, [f"{months} × {usd(monthly)} a month = {usd(value)}"])


# ---------------------------------------------------------------------------------------------- Clipper START

def _weekly_cap(pass_month: int, fares: FaresRow) -> Decimal:
    return Decimal(pass_month) * fares.months_per_year / fares.weeks_per_year


def transit_breaks(fares: FaresRow, breaks: BreaksRow, choice: str, explain: bool = True) -> Valued:
    rides = breaks.rides_per_week[choice]
    weeks = breaks.break_weeks
    if choice == BART_CHOICE:
        raw = rides * fares.bart_average_fare * fares.start_discount * weeks
        value = floor_dollar(raw)
        if not explain:
            return Valued(value)
        return Valued(value, [f"{rides} rides a week with BART: {rides} × {usd(fares.bart_average_fare)} × "
                              f"{fares.start_discount} × {weeks} break weeks = {usd(raw)} → {usd(value)}"])
    full = min(rides * fares.muni_adult, _weekly_cap(fares.muni_pass_month, fares))
    start = min(rides * fares.muni_start, _weekly_cap(fares.lifeline_pass_month, fares))
    raw = (full - start) * weeks
    value = floor_dollar(raw)
    if not explain:
        return Valued(value)
    return Valued(value, [
        f"{rides} rides a week on Muni: full fare min({rides} × {usd(fares.muni_adult)}, "
        f"{usd(fares.muni_pass_month)} × {fares.months_per_year} ÷ {fares.weeks_per_year}) = {usd(full)} a week; "
        f"START fare min({rides} × {usd(fares.muni_start)}, {usd(fares.lifeline_pass_month)} × "
        f"{fares.months_per_year} ÷ {fares.weeks_per_year}) = {usd(start)} a week",
        f"({usd(full)} − {usd(start)}) × {weeks} break weeks = {usd(raw)} → {usd(value)}",
    ])


def before_next_break(breaks: BreaksRow, today: date) -> date | None:
    """The first break whose start minus the card's mail time is today or later: apply by that day."""
    for gap in sorted(breaks.gaps, key=lambda g: g.from_):
        apply_by = gap.from_ - timedelta(days=breaks.mail_days)
        if apply_by >= today:
            return apply_by
    return None


# ---------------------------------------------------------------------------------------------- PG&E CARE

@dataclass
class CareValue(Valued):
    household: int = 0
    bill: int = 0


def utility_share(care: CareRow, facts: ProgramFacts, explain: bool = True) -> CareValue:
    bill = care.default_bill_two_plus if facts.people_in_home > 1 else care.default_bill_alone
    share = care.electric_discount * care.electric_share_of_bill + \
        care.gas_discount * (1 - care.electric_share_of_bill)
    household = care.months * share * bill
    value = floor_dollar(household / facts.bill_split)
    if not explain:
        return CareValue(value, household=floor_dollar(household), bill=bill)
    basis = [f"{care.months} × ({care.electric_discount} × {care.electric_share_of_bill} + {care.gas_discount} × "
             f"{1 - care.electric_share_of_bill}) × {usd(bill)} assumed bill = {usd(household)} for the home"]
    if facts.bill_split > 1:
        basis.append(f"{usd(household)} ÷ {facts.bill_split} people on the bill = "
                     f"{usd(household / facts.bill_split)} → {usd(value)}")
    else:
        basis.append(f"one person on the bill → {usd(value)}")
    return CareValue(value, basis, household=floor_dollar(household), bill=bill)


# ---------------------------------------------------------------------------------------------- California LifeLine

def flat_monthly(row: FlatRow, months: int, explain: bool = True) -> Valued:
    raw = months * row.monthly
    value = floor_dollar(raw)
    if not explain:
        return Valued(value)
    ceiling = " (a ceiling: a cheaper plan saves less)" if row.ceiling else ""
    return Valued(value, [f"{months} × {usd(row.monthly)} a month = {usd(raw)} → {usd(value)}{ceiling}"])


# ---------------------------------------------------------------------------------------------- tax credits

@dataclass
class TaxValue(Valued):
    caleitc: int = 0
    federal: int = 0
    yctc: int = 0


def caleitc_anchor(row: CalEitcRow, earned: Decimal, age: int | None) -> int:
    """The tax-year-2025 CalEITC table as a proxy: the credit at the smallest anchor at or above E, only for E within
    the anchors (a floor, because the credit falls as E rises); otherwise no counted state value."""
    if age is None or age < row.min_age or earned > row.earned_limit:
        return 0
    anchors = sorted(row.anchors_annual_earned_to_credit)
    if not anchors or earned < anchors[0][0] or earned > anchors[-1][0]:
        return 0
    for anchor_earned, credit in anchors:
        if anchor_earned >= earned:
            return credit
    return 0


def federal_eitc(params: EitcParams, earned: Decimal) -> int:
    """floor(max(0, min(rate × E, max) − phase-out rate × max(0, E − phase-out start))); AGI = E."""
    credit = min(params.rate * earned, Decimal(params.max))
    phaseout = params.phaseout_rate * max(ZERO, earned - params.phaseout_start)
    return floor_dollar(max(ZERO, credit - phaseout))


def yctc(row: YctcRow, earned: Decimal) -> int:
    """Young Child Tax Credit (2025 amount): the maximum up to `full_up_to`, then down to 0 at `zero_at`."""
    if earned <= row.full_up_to:
        return row.max
    return max(0, floor_dollar(row.max * (row.zero_at - earned) / (row.zero_at - row.full_up_to)))


def tax_credits(cal: CalEitcRow, fed: FederalEitcRow, young: YctcRow, facts: ProgramFacts,
                variant: str, months: int, explain: bool = True) -> TaxValue:
    earned = facts.earned_annual if facts.earned_annual is not None else ZERO
    age = facts.age
    basis = [f"E = {months} × the monthly pay = {usd(earned)} (the same pay all year)"] if explain else []
    if variant == "parent":
        top = max(int(k) for k in fed.params)
        kids = min(facts.children_count, top)
        federal = federal_eitc(fed.params[str(kids)], earned)
        young_child = facts.youngest_child_age is not None and facts.youngest_child_age < young.child_under
        young_value = yctc(young, earned) if young_child and earned > 0 else 0
        value = federal + young_value
        if explain:
            basis.append(f"federal EITC with {kids} child(ren) {usd(federal)} + Young Child Tax Credit "
                         f"{usd(young_value)} = {usd(value)} (CalEITC with children not counted)")
        return TaxValue(value, basis, federal=federal, yctc=young_value)
    state = caleitc_anchor(cal, earned, age)
    adult_age = age is not None and fed.min_age_no_child <= age <= fed.max_age_no_child
    federal = federal_eitc(fed.params["0"], earned) if adult_age else 0
    value = state + federal
    if not explain:
        return TaxValue(value, basis, caleitc=state, federal=federal)
    age_text = "" if adult_age else f" (no-child federal EITC only at ages {fed.min_age_no_child}–" \
                                    f"{fed.max_age_no_child})"
    basis.append(f"CalEITC ({cal.tax_year} table) {usd(state)} + federal EITC {usd(federal)}{age_text} = "
                 f"{usd(value)}")
    return TaxValue(value, basis, caleitc=state, federal=federal)

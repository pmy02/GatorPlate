"""The CalFresh decision order (docs/SPEC.md §5.2) as a pure function of the facts and the rules table.

The steps run in the table's `decision_order`. A step either passes, adds a policy flag, or routes the case (a
reason code); the trace records each step in English with its numbers and source id ("Computed by the rules table —
not by AI"). Money is Decimal; the only rounding is the table's: income to the cent once, net income to the dollar
half-up, the benefit reduction up to the dollar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from gatorplate.contracts.case import FirstMonth, RuleStep
from gatorplate.contracts.common import Tier
from gatorplate.contracts.rules_io import Evaluation, Facts, RulesTable
from gatorplate.rules import dates
from gatorplate.rules.money import ZERO, freq_period, pct, rounder, to_monthly, usd
from gatorplate.rules.table import by_size, min_benefit_max_size, source_id, valid_on, zero_benefit_min_size

LIKELY = "likely"
TIER_OF_PREFIX = {"likely": Tier.likely, "coordinator": Tier.coordinator, "other_help": Tier.other_help,
                  "info": Tier.coordinator}
FOOD_TEXT = {"alone": "Buys and cooks food alone", "separate": "Buys and cooks food separately from others",
             "shared": "Buys and cooks food with others"}


def tier_of(reason_code: str) -> Tier:
    """The tier of a reason code. The info routes have no estimate; a person (the county or the coordinator)
    handles them, so they carry the coordinator tier and their own card column."""
    return TIER_OF_PREFIX[reason_code.split(".")[0]]


def people(size: int) -> str:
    return f"{size} person" if size == 1 else f"{size} people"


@dataclass
class _Run:
    facts: Facts
    table: RulesTable
    today: date
    with_trace: bool
    trace: list[RuleStep] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    earned: Decimal = ZERO
    unearned: Decimal = ZERO
    excluded: Decimal = ZERO
    self_employment: Decimal = ZERO
    gross: Decimal = ZERO
    adjusted: Decimal = ZERO
    deduction: Decimal = ZERO
    net: int | None = None
    monthly: int | None = None
    min_applied: bool = False
    first_month: FirstMonth | None = None
    expedited: bool | None = None

    @property
    def size(self) -> int:
        return self.facts.household_size

    def step(self, step: str, result: str, *source_keys: str, value: str | None = None,
             source: str | None = None) -> None:
        """Adds a trace row; the source is the first named `value_sources` key that exists (or `source`)."""
        if self.with_trace:
            self.trace.append(RuleStep(step=step, result=result, source=source or source_id(self.table, *source_keys),
                                       value=value))

    def shelter_cost(self) -> Decimal:
        return shelter_cost(self.facts)

    def utility_allowance(self) -> int:
        return utility_allowance(self.table, self.facts)


def shelter_cost(facts: Facts) -> Decimal:
    """Own shelter cost: rent share minus what someone else pays to the landlord (not below 0); for a homeless
    household, what it pays to stay."""
    if facts.homeless:
        return facts.homeless_shelter_cost
    return max(ZERO, facts.rent_share - facts.rent_paid_by_others_to_landlord)


def utility_allowance(table: RulesTable, facts: Facts) -> int:
    return getattr(table.utility_allowance, facts.utility)


def housing_cost(table: RulesTable, facts: Facts) -> Decimal:
    """Own shelter cost + utility allowance (the expedited tests)."""
    return shelter_cost(facts) + utility_allowance(table, facts)


def _incomes(run: _Run) -> None:
    for item in run.facts.incomes:
        monthly = to_monthly(run.table, item.amount, freq_period(run.table, item.freq))
        if item.excluded:
            run.excluded += monthly
        elif item.kind == "earned":
            run.earned += monthly
        elif item.kind == "unearned":
            run.unearned += monthly
        else:
            run.self_employment += monthly
    # each item is already in cents; the total keeps the cent scale ("0.00" when there is no income)
    run.gross = rounder(run.table, "income_conversion")(run.earned + run.unearned)


# ---------------------------------------------------------------------------------------------- steps
# Each step returns a reason code to route the case, or None to continue.


def _table_dates(run: _Run) -> str | None:
    if valid_on(run.table, run.today):
        return None
    start, end = run.table.effective
    run.step("table_dates", f"The rules table covers {start.isoformat()} to {end.isoformat()}; "
                            f"{run.today.isoformat()} is outside it — no estimate", "decision_order")
    return run.table.routes.unresolved_tier


def _volunteered_status(run: _Run) -> str | None:
    f, status = run.facts, run.table.status
    route = None
    if f.volunteered_status in status.other_help or f.status_route == "other_help":
        route = run.table.routes.volunteered_status_other_help
    elif f.volunteered_status in status.coordinator or f.status_route == "coordinator":
        route = run.table.routes.volunteered_status_coordinator
    if route:
        run.step("volunteered_status", "Immigration status mentioned (not stored) — "
                 + ("other help" if route.startswith("other_help") else "a person checks"), "status")
    return route


def _elderly_or_disabled(run: _Run) -> str | None:
    rule = run.table.elderly_disabled
    if run.facts.elderly_or_disabled or run.facts.age >= rule.age_at_or_over:
        run.step("elderly_or_disabled", f"Disability benefits or age {rule.age_at_or_over}+ (details not stored) — "
                 "different income tests apply; a person checks", "elderly_disabled")
        return run.table.routes.elderly_or_disabled
    return None


def _school(run: _Run) -> str | None:
    if run.facts.level == "not_sfsu":
        run.step("school", "Not an SF State student — other help", "routes")
        return run.table.routes.not_sfsu
    return None


def _parent_household(run: _Run) -> str | None:
    if run.facts.under22_with_parent:
        run.step("parent_household", f"Under {run.table.parent_household_age_under} and living with a parent — the "
                 "parent's household is counted together, no exceptions", "parent_household_age_under")
        return run.table.routes.under_22_with_parent
    return None


def _student_age(run: _Run) -> str | None:
    ages = run.table.age_coordinator
    if run.facts.age < ages.under or run.facts.age >= ages.at_or_over:
        lo, hi = run.table.student_rule_age
        run.step("student_age", f"Age {run.facts.age}: outside the student rule's ages {lo}–{hi} — a person checks "
                 "which rules apply", "student_rule_age")
        return run.table.routes.age_outside_student_rule
    return None


def _degree_program(run: _Run) -> str | None:
    if run.facts.level == "not_degree" or not run.facts.public_ca_degree_program:
        run.step("degree_program", "Not in a degree program (credential, certificate or extension) — a person "
                 "checks the student rule", "half_time")
        return run.table.routes.not_degree
    return None


def _grad_exemption(run: _Run) -> str | None:
    f, grad = run.facts, run.table.grad
    exemption = f.grad_exemption if f.grad_exemption in grad.exemptions else None
    if f.level == "grad":
        if f.half_time and exemption is None:
            run.step("grad_exemption", "Graduate student, half-time or more, no student-rule exemption named — a "
                     "person goes through the exemption list", "grad.rule")
            return run.table.routes.grad_no_exemption
        if f.half_time:
            run.step("student_rule", f"Graduate student, half-time or more, exemption: "
                     f"{grad.exemption_labels[exemption]} → student rule met", "grad.exemptions",
                     source=grad.exemption_sources.get(exemption))
        else:
            run.step("student_rule", "Graduate student below half-time → the student rule does not apply",
                     "half_time")
    elif f.half_time:
        run.step("student_rule", "SF State undergrad, at least half-time, bachelor's program → student rule met",
                 "half_time")
    else:
        units = f"{f.units} units, " if f.units is not None else ""
        run.step("student_rule", f"SF State undergrad below half-time ({units}fewer than "
                 f"{run.table.half_time.undergrad_units_at_least}) → the student rule does not apply", "half_time")
    return None


def _work_rule(run: _Run) -> str | None:
    f, rule = run.facts, run.table.abawd
    lo, hi = rule.age
    child_exempt = f.child_under14_in_hh
    if (not f.half_time and lo <= f.age <= hi and not child_exempt and run.earned < rule.earnings_exempt_monthly
            and not f.works_80h_month and not f.receives_unemployment):
        run.flags.append(rule.yellow_code)
        run.step("work_rule", f"Below half-time, age {f.age}, no child under {rule.child_exempt_under}, earnings "
                 f"{usd(run.earned)} < {usd(rule.earnings_exempt_monthly)} — the county may apply the work rule "
                 "(yellow line)", "abawd.earnings_exempt_monthly")
    return None


def _household(run: _Run) -> str | None:
    f, routes = run.facts, run.table.routes
    if f.household_food == "shared":
        run.step("household", f"{FOOD_TEXT['shared']} — they may count as one household; a person checks", "routes")
        return routes.shared_food
    if f.boarder:
        run.step("household", "Pays for room and meals together — may be a boarder; a person checks", "routes")
        return routes.boarder
    if f.spouse_student:
        run.step("household", "Spouse is also a student — both students' situations count; a person checks",
                 "routes")
        return routes.spouse_student
    limit = run.table.dorm_meals_per_week_max_eligible
    if f.dorm_on_campus and (f.meals_per_week > limit or f.dorm_meals_over_10):
        run.step("household", f"Campus meal plan with more than {limit} meals a week — other help",
                 "dorm_meals_per_week_max_eligible")
        return routes.dorm_meal_plan
    run.step("household", f"{FOOD_TEXT[f.household_food]} → {people(run.size)}", "routes", value=str(run.size))
    return None


def _income(run: _Run) -> str | None:
    if run.self_employment > ZERO:
        run.step("income", f"Self-employment income {usd(run.self_employment)} a month — business costs change the "
                 "count; a person checks", "income_rules.self_employment")
        return run.table.routes.self_employment_income
    parts = [f"work {usd(run.earned)}"]
    if run.unearned:
        parts.append(f"other income {usd(run.unearned)}")
    text = "Monthly income: " + " + ".join(parts) + f" = gross {usd(run.gross)}"
    if run.excluded:
        text += f" (not counted: {usd(run.excluded)} work-study or school aid)"
    run.step("income", text, "income_rules.counted_family_cash", value=str(run.gross))
    return None


def _gross_income_test(run: _Run) -> str | None:
    limit = by_size(run.table.gross_limit_200, run.size)
    if run.gross > limit:
        run.step("gross_income_test", f"Gross {usd(run.gross)} > {usd(limit)} (gross income limit, "
                 f"{people(run.size)}) — other help", "gross_limit_200")
        return run.table.routes.over_gross_limit
    run.step("gross_income_test", f"Gross {usd(run.gross)} ≤ {usd(limit)} (gross income limit, {people(run.size)})",
             "gross_limit_200")
    return None


def _adjusted_income(run: _Run) -> str | None:
    rates = run.table.rates
    earned_deduction = rates.earned_income_deduction * run.earned
    standard = by_size(run.table.standard_deduction, run.size)
    raw = run.gross - earned_deduction - standard - run.facts.dependent_care
    run.adjusted = max(ZERO, raw)
    text = (f"Earned-income deduction {pct(rates.earned_income_deduction)}: −{usd(earned_deduction)} · standard "
            f"deduction −{usd(standard)}")
    if run.facts.dependent_care:
        text += f" · dependent care −{usd(run.facts.dependent_care)}"
    run.step("adjusted_income", f"{text} → {usd(run.adjusted)}", "rates.earned_income_deduction",
             value=str(run.adjusted))
    return None


def _excess_shelter(run: _Run, cost: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(cost + utility allowance, the share of adjusted income, the capped excess)."""
    share = run.table.rates.shelter_income_share * run.adjusted
    total = cost + run.utility_allowance()
    excess = min(max(ZERO, total - share), Decimal(run.table.excess_shelter_cap_non_elderly_disabled))
    return total, share, excess


def _shelter(run: _Run) -> str | None:
    f, table = run.facts, run.table
    share_rate = pct(table.rates.shelter_income_share)
    if f.homeless:
        cost = f.homeless_shelter_cost
        pays = cost > ZERO or f.utility != "none"
        if not pays:
            run.deduction = ZERO
            run.step("shelter", "No fixed home and pays nothing to stay — no shelter deduction",
                     "homeless_rules.direct_if_cost")
            return None
        hsd = table.homeless_shelter_deduction
        total, share, excess = _excess_shelter(run, cost)
        if table.homeless_deduction_mode == "excess_formula":
            total, share, excess = _excess_shelter(run, hsd)
            run.deduction = excess
            run.step("shelter", f"No fixed home: homeless shelter deduction {usd(hsd)} used as the shelter cost; "
                     f"minus {share_rate} of {usd(run.adjusted)} → {usd(excess)}", "homeless_rules.excess_formula")
            return None
        run.deduction = max(hsd, excess)
        if excess > hsd:
            run.step("shelter", f"No fixed home, pays {usd(cost)}: actual costs give a larger deduction, "
                     f"{usd(total)} − {share_rate} of {usd(run.adjusted)} → {usd(excess)}",
                     "homeless_rules.direct_if_cost")
        else:
            run.step("shelter", f"No fixed home, pays {usd(cost)}: homeless shelter deduction {usd(hsd)} subtracted "
                     "directly", "homeless_rules.direct_if_cost", value=str(hsd))
        return None
    cost = run.shelter_cost()
    total, share, excess = _excess_shelter(run, cost)
    run.deduction = excess
    cap = table.excess_shelter_cap_non_elderly_disabled
    text = f"Shelter: {usd(cost)}"
    if f.rent_paid_by_others_to_landlord:
        text = (f"Shelter: rent {usd(f.rent_share)} − {usd(f.rent_paid_by_others_to_landlord)} paid by someone else "
                f"= {usd(cost)}")
    if run.utility_allowance():
        name = getattr(table.utility_rules.names, f.utility)
        text += f" + {name} {usd(run.utility_allowance())}"
    raw = total - share
    text += f" − {share_rate} of {usd(run.adjusted)} ({usd(share)})"
    if raw <= ZERO:
        text += " → $0"
    elif raw > cap:
        text += f" = {usd(raw)} → capped at {usd(cap)}"
    else:
        text += f" = {usd(raw)}"
    run.step("shelter", text, "excess_shelter_cap_non_elderly_disabled", value=str(excess))
    return None


def _net_income(run: _Run) -> str | None:
    raw = max(ZERO, run.adjusted - run.deduction)
    run.net = int(rounder(run.table, "net_income")(raw))
    run.step("net_income", f"Net income: {usd(run.adjusted)} − {usd(run.deduction)} → {usd(run.net)}", "rounding",
             value=str(run.net))
    return None


def _benefit(run: _Run) -> str | None:
    table = run.table
    assert run.net is not None
    maximum = by_size(table.max_allotment, run.size)
    rate = table.rates.benefit_reduction
    reduction = int(rounder(table, "benefit_reduction")(rate * run.net))
    amount = maximum - reduction
    text = f"Estimate: {usd(maximum)} − {pct(rate)} × {usd(run.net)} ({usd(reduction)}) = {usd(amount)}"
    source_key = "rates.benefit_reduction"
    if run.size <= min_benefit_max_size() and amount < table.min_benefit_1_2_persons:
        source_key = "min_benefit_1_2_persons"
        amount = table.min_benefit_1_2_persons
        run.min_applied = True
        text = (f"Estimate: {usd(maximum)} − {pct(rate)} × {usd(run.net)} ({usd(reduction)}) is below the minimum → "
                f"{usd(amount)} ({people(run.size)})")
    elif run.size >= zero_benefit_min_size() and amount <= 0:
        run.step("benefit", f"{text}: $0 or below for {people(run.size)} — other help", "zero_benefit_rule")
        return table.zero_benefit_3_plus_route
    run.monthly = amount
    run.step("benefit", text, source_key, value=str(amount))
    return None


def _first_month(run: _Run) -> str | None:
    apply_date = run.facts.apply_date
    if apply_date is None or run.monthly is None:
        return None
    fm = dates.first_month(run.table, run.monthly, apply_date=apply_date, filed_on=apply_date)
    run.first_month = fm
    run.step("first_month", f"First month (filed {apply_date.isoformat()}): {usd(run.monthly)} × "
             f"{fm.days_counted}/{dates.days_in_month(apply_date)} days → {usd(fm.amount)} (estimate)", "proration",
             value=str(fm.amount))
    return None


def expedited_test(table: RulesTable, *, gross: Decimal, cash: Decimal, housing: Decimal) -> bool:
    """(gross < income limit and cash <= cash limit) or gross + cash < housing (own shelter cost + utility
    allowance), strictly."""
    rule = table.expedited
    return (gross < rule.income_lt and cash <= rule.liquid_le) or gross + cash < housing


def _expedited(run: _Run) -> str | None:
    cash = run.facts.cash_on_hand
    if cash is None:
        return None
    housing = housing_cost(run.table, run.facts)
    run.expedited = expedited_test(run.table, gross=run.gross, cash=cash, housing=housing)
    run.step("expedited", f"{run.table.expedited.days}-day service check: gross {usd(run.gross)}, cash {usd(cash)}, "
             f"housing {usd(housing)} → {'yes' if run.expedited else 'no'}", "expedited.rule")
    return None


STEPS: dict[str, Callable[[_Run], str | None]] = {
    "table_dates": _table_dates,
    "volunteered_status": _volunteered_status,
    "elderly_or_disabled": _elderly_or_disabled,
    "school": _school,
    "parent_household": _parent_household,
    "student_age": _student_age,
    "degree_program": _degree_program,
    "grad_exemption": _grad_exemption,
    "work_rule": _work_rule,
    "household": _household,
    "income": _income,
    "gross_income_test": _gross_income_test,
    "adjusted_income": _adjusted_income,
    "shelter": _shelter,
    "net_income": _net_income,
    "benefit": _benefit,
    "first_month": _first_month,
    "expedited": _expedited,
}


def evaluate(table: RulesTable, facts: Facts, *, today: date, with_trace: bool = True) -> Evaluation:
    run = _Run(facts=facts, table=table, today=today, with_trace=with_trace)
    _incomes(run)
    route: str | None = None
    reached_income = False
    for entry in table.decision_order:
        route = STEPS[entry.step](run)
        reached_income = reached_income or entry.step == "income"
        if route is not None:
            break
    if facts.income_changing_soon and reached_income:
        run.flags.append("income_changing_soon")
    if route is not None:
        return Evaluation(tier=tier_of(route), reason_code=route, household_size=facts.household_size,
                          gross_monthly=run.gross, hard_stop=True, trace=run.trace, policy_flags=run.flags,
                          table_id=table.id)
    irt = run.gross <= by_size(table.irt_130, run.size)
    housing = housing_cost(table, facts)
    screen = run.gross < table.expedited.income_lt or housing > run.gross
    return Evaluation(tier=Tier.likely, reason_code=LIKELY, monthly=run.monthly, min_benefit_applied=run.min_applied,
                      household_size=facts.household_size, gross_monthly=run.gross, net_monthly=run.net,
                      expedited=run.expedited, expedited_screen=screen, irt_applies=irt,
                      first_month=run.first_month, policy_flags=run.flags, hard_stop=False, trace=run.trace,
                      table_id=table.id)

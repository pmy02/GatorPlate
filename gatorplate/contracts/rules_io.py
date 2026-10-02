"""Rules engine input and output (docs/SPEC.md §5): facts, evaluation, value-of-information plan and the rules table.

`Facts` mirrors the `facts` objects of data/golden/golden_cases.json key for key, so every golden case loads without
an adapter. `RulesTable` mirrors data/rules/ca_fy2027.json key for key (descriptive text fields included); unknown
keys are an error. Money is Decimal (JSON strings); whole dollars are int.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from gatorplate.contracts.case import EstimateRange, FirstMonth, RuleStep
from gatorplate.contracts.common import ExpeditedOutlook, Lang, Model, Period, Tier
from gatorplate.contracts.slots import SlotName


class SourceRef(Model):
    id: str
    title: str
    date: str  # the source's own date, or the day it was read (free text in some tables: "rev 8/13", "2026")
    grade: str | None = None
    url: str | None = None


class RulesMeta(Model):
    table_id: str
    label: str
    effective_from: date
    effective_to: date
    sources: list[SourceRef]


class IncomeItem(Model):
    """One income in the facts. Golden G12 stores "$20 × 15 h/week" as weekly 300; live hourly pay is normalized to
    monthly in the slot before facts_from_case runs."""

    amount: Decimal
    freq: Literal["weekly", "biweekly", "semimonthly", "monthly", "yearly"]
    kind: Literal["earned", "unearned", "self_employment"]
    excluded: bool = False  # work-study, financial aid
    label: str = ""


class Facts(Model):
    """The engine's input: exactly the golden-case `facts` keys, plus `status_route` (a live case routes on a
    volunteered status without storing its value).

    A golden case is {id, source, title, facts, expected, hand_calc} plus optional test-harness keys (normalize, trap,
    today, route_step) that are not Facts fields."""

    lang: Lang
    volunteered_status: str | None
    elderly_or_disabled: bool
    age: int
    level: Literal["undergrad", "grad", "not_degree", "not_sfsu"]
    public_ca_degree_program: bool
    half_time: bool
    units: int | None
    grad_exemption: str | None
    child_under14_in_hh: bool
    under22_with_parent: bool
    dorm_on_campus: bool
    meals_per_week: int
    dorm_meals_over_10: bool | None
    household_food: Literal["alone", "separate", "shared"]
    household_size: int
    spouse_student: bool
    boarder: bool
    homeless: bool
    homeless_shelter_cost: Decimal
    incomes: list[IncomeItem]
    rent_share: Decimal
    rent_paid_by_others_to_landlord: Decimal
    utility: Literal["heat_cool", "two_other", "phone_only", "none"]
    dependent_care: Decimal
    cash_on_hand: Decimal | None
    apply_date: date | None
    income_changing_soon: bool
    works_80h_month: bool = False
    receives_unemployment: bool = False
    status_route: Literal["other_help", "coordinator"] | None = None


REASON_CODES: list[str] = [
    "likely",
    "coordinator.parent_household",
    "coordinator.shared_household",
    "coordinator.grad_no_exemption",
    "coordinator.not_degree",
    "coordinator.age_outside_student_rule",
    "coordinator.gig_income",
    "coordinator.boarder",
    "coordinator.spouse_student",
    "coordinator.status_complex",
    "coordinator.elderly_disabled",
    "coordinator.unresolved",
    "other_help.status",
    "other_help.over_gross_limit",
    "other_help.dorm_meal_plan",
    "other_help.not_sfsu",
    "other_help.zero_benefit",
    "info.already_receiving",
    "info.interview_waiting",
]


class Evaluation(Model):
    tier: Tier
    reason_code: str
    monthly: int | None = None
    min_benefit_applied: bool = False
    household_size: int
    gross_monthly: Decimal
    net_monthly: int | None = None
    expedited: bool | None = None  # None until cash_on_hand is known
    expedited_screen: bool = False  # ask the cash question?
    irt_applies: bool = False  # gross at the estimate <= the 130 % line (card line)
    first_month: FirstMonth | None = None  # when facts.apply_date is set
    policy_flags: list[str] = Field(default_factory=list)  # = golden "yellow_codes"
    hard_stop: bool = False
    trace: list[RuleStep]
    table_id: str


class FlipOutcome(Model):
    value: str
    tier: Tier
    monthly: int | None
    label: str  # "Yes → $155/mo"


class FlipCandidate(Model):
    slot: SlotName
    default_value: str
    outcomes: list[FlipOutcome]
    tier_changes: bool
    spread_usd: int
    decision: Literal["ask", "assume_default", "assume_conservative", "no_effect", "coordinator"]
    reason: str  # console_text.flip_reason(...)


class FlipPlan(Model):
    ask: list[FlipCandidate]  # within the remaining budget, in asking order
    not_asked: list[FlipCandidate]
    expedited_outlook: ExpeditedOutlook | None
    estimate_range: EstimateRange | None


# ---------------------------------------------------------------------------------------------- rules table


class MoneyBasisExample(Model):
    amount: Decimal
    period: Period
    hours_per_week: Decimal | None


class ConversionExample(Model):
    basis: MoneyBasisExample
    monthly: Decimal


class ConversionMultipliers(Model):
    month: Decimal
    week: Decimal
    biweek: Decimal
    semimonth: Decimal


class FreqAlias(Model):
    monthly: str
    weekly: str
    biweekly: str
    semimonthly: str
    yearly: str


class Conversion(Model):
    multipliers: ConversionMultipliers
    hour: str
    year_divisor: Decimal
    freq_alias: FreqAlias
    round: str
    examples: list[ConversionExample]


class HomelessRules(Model):
    definition: str
    direct_if_cost: str
    excess_formula: str


class UtilityAllowance(Model):
    heat_cool: int
    two_other: int
    phone_only: int
    none: int


class UtilityNames(Model):
    heat_cool: str
    two_other: str
    phone_only: str
    none: str


class UtilityRules(Model):
    names: UtilityNames
    from_slots: str
    heat_cool: str
    lua_utilities: str
    one_per_household: str
    shared_bills: str


class Rates(Model):
    earned_income_deduction: Decimal
    shelter_income_share: Decimal
    benefit_reduction: Decimal


class Rounding(Model):
    income_conversion: str
    after_conversion: str
    net_income: str
    benefit_reduction: str
    benefit_reduction_integer_formula: str
    proration: str
    float_allowed: bool
    builtin_round_allowed: bool


class Proration(Model):
    days_counted: str
    amount: str
    below_min_issue: str
    applies_to_minimum_benefit: bool
    note: str


class ExpeditedOutlookText(Model):
    yes: str
    maybe: str
    no: str


class Expedited(Model):
    income_lt: int
    liquid_le: int
    shelter_test: str
    rule: str
    days: int
    ask_cash_when: str
    outlook: ExpeditedOutlookText
    is_flip_question: bool


class AgeCoordinator(Model):
    under: int
    at_or_over: int


class HalfTime(Model):
    undergrad_units_at_least: int
    basis: str
    affects: str
    grad: str
    note: str


class Abawd(Model):
    age: tuple[int, int]
    child_exempt_under: int
    earnings_exempt_monthly: Decimal
    earnings_basis: str
    work_requirement_hours_month: int
    unemployment_exempt: bool
    half_time_student_exempt: bool
    ca_effective: date
    sf_waiver: bool
    yellow_code: str
    yellow_when: str
    yellow_text: str


class Grad(Model):
    work_hours_week: int
    work_hours_month: int
    child_under: int
    child_no_care_under: int
    single_parent_child_under: int
    exemptions: list[str]
    exemption_labels: dict[str, str]
    exemption_sources: dict[str, str]
    rule: str


class StatusRouting(Model):
    other_help: list[str]
    coordinator: list[str]
    asked: bool
    stored: bool
    rule: str


class ElderlyDisabled(Model):
    age_at_or_over: int
    signals: list[str]
    route: str
    asked: bool
    stored: str
    rule: str


class IncomeExcluded(Model):
    work_study: str
    higher_education_aid: str
    vendor_payment: str


class IncomeRules(Model):
    excluded: IncomeExcluded
    counted_family_cash: str
    earned_deduction_applies_to: str
    unearned_examples: list[str]
    self_employment: str


class Routes(Model):
    volunteered_status_other_help: str
    volunteered_status_coordinator: str
    elderly_or_disabled: str
    not_sfsu: str
    age_outside_student_rule: str
    not_degree: str
    grad_no_exemption: str
    under_22_with_parent: str
    shared_food: str
    boarder: str
    spouse_student: str
    dorm_meal_plan: str
    self_employment_income: str
    over_gross_limit: str
    zero_benefit_3_plus: str
    unresolved_tier: str
    already_receiving: str
    interview_waiting: str


class DecisionStep(Model):
    step: str
    rule: str


class Deadlines(Model):
    decision_days: int
    doc_request_days: int
    irt_report_days: int
    sar7_month: int
    sar7_due_day: int
    sar7_late_day: int
    recert_month: int
    note: str


class FilingExample(Model):
    now: str  # local ISO time with offset ("2026-10-01T23:30:00-07:00")
    filed_on: date
    first_month_for_306: int


class FilingDateEstimate(Model):
    cutoff_local: str
    rule: str
    label: str
    examples: list[FilingExample]
    note: str


class VoiDefaultModes(Model):
    natural: str
    conservative: str


class VoiSlot(Model):
    candidates: list[str] | str
    default: str
    only_if: dict[str, bool] | None = None
    ask_key: str
    follow_up_key: str | None = None
    follow_up_when: str | None = None


class VoiNotAskedRule(Model):
    skipped_reason: str | None = None
    line: str
    value: str | None = None
    route: str | None = None
    yellow_text: str | None = None
    yellow_text_when_default_is_highest: str | None = None


class VoiNotAsked(Model):
    spread_zero: VoiNotAskedRule
    spread_up_to_threshold: VoiNotAskedRule
    left_by_cap_spread_over_threshold: VoiNotAskedRule
    left_by_cap_tier_change: VoiNotAskedRule
    unclear_never_resolved: VoiNotAskedRule


class VoiEstimateRange(Model):
    lo_hi: str
    settled: str


class IncomeBand(Model):
    fractions_of_gross_limit: list[Decimal]
    round_to_usd: int
    edges_1_person: list[int]
    split_rule: str
    stop: str


class RequiredResult(Model):
    case: str
    asked: list[str]
    amount: int
    answers: dict[str, str] = Field(default_factory=dict)
    no_effect: list[str] = Field(default_factory=list)
    below_threshold: list[str] = Field(default_factory=list)
    yellow: list[str] = Field(default_factory=list)
    yellow_could_be_up_to: int | None = None


class Voi(Model):
    default_mode: Literal["natural", "conservative"]
    default_mode_values: VoiDefaultModes
    flip_threshold_usd: int
    threshold_rule: str
    max_questions: int
    order: list[str]
    priority: list[str]
    replan_after_each_answer: bool
    measure: str
    conservative_value: str
    unclear_answer_value: str
    unknown_income_value: str
    slots: dict[str, VoiSlot]
    not_asked: VoiNotAsked
    estimate_spoken: str
    estimate_range: VoiEstimateRange
    flip_reason_text: str
    income_band: IncomeBand
    other_cash_band_usd: list[int]
    expedited_never_flips: bool
    required_results: list[RequiredResult]


class RulesTable(Model):
    """data/rules/ca_fy2027.json, key for key. Household-size tables keep their keys as strings ("1".."8",
    "each_over_8", "18_plus", "6_plus")."""

    id: str
    label: str
    fy: str
    version: str
    checked: date
    effective: tuple[date, date]
    timezone: str
    about: str
    sources: list[SourceRef]
    source_notes: dict[str, str]
    value_sources: dict[str, str]
    household_size_lookup: str
    max_allotment: dict[str, int]
    standard_deduction: dict[str, int]
    gross_limit_200: dict[str, int]
    irt_130: dict[str, int]
    min_benefit_1_2_persons: int
    min_benefit_rule: str
    zero_benefit_3_plus_route: str
    zero_benefit_rule: str
    excess_shelter_cap_non_elderly_disabled: int
    homeless_shelter_deduction: Decimal
    homeless_deduction_mode: Literal["direct_if_cost", "excess_formula"]
    homeless_temp_stay_max_days: int
    homeless_rules: HomelessRules
    utility_allowance: UtilityAllowance
    utility_rules: UtilityRules
    rates: Rates
    conversion: Conversion
    rounding: Rounding
    proration_min_issue: int
    proration: Proration
    expedited: Expedited
    irt_card_rule: str
    student_rule_age: tuple[int, int]
    age_coordinator: AgeCoordinator
    parent_household_age_under: int
    parent_household_exceptions: list[str]
    parent_household_console_text: str
    dorm_meals_per_week_max_eligible: int
    sfsu_half_time_units_undergrad: int
    half_time: HalfTime
    abawd: Abawd
    grad: Grad
    status: StatusRouting
    elderly_disabled: ElderlyDisabled
    income_rules: IncomeRules
    routes: Routes
    decision_order: list[DecisionStep]
    deadlines: Deadlines
    filing_date_estimate: FilingDateEstimate
    voi: Voi
    notes: list[str]

    def meta(self) -> RulesMeta:
        return RulesMeta(table_id=self.id, label=self.label, effective_from=self.effective[0],
                         effective_to=self.effective[1], sources=list(self.sources))

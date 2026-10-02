"""The other-programs table (data/rules/programs_2026.json): strict models that mirror it, loaded once.

Every number the programs engine uses lives in this table (docs/SPEC.md §5.10). Rates are exact decimal strings and
become Decimal; whole dollars stay int; a float anywhere in the file is rejected when it is read. Every value row
carries `valid: [from, to]` (inclusive; `null` = open-ended), and `effective` bounds the whole table.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, model_validator

from gatorplate.contracts.programs import ProgramStage, ProgramStatus

Status = ProgramStatus | Literal["hidden"]
FACT_OPS = ("eq", "ne", "lt", "lte", "gt", "gte", "in", "between", "lte_row")
ANSWER_OPS = ("in", "eq", "ne")
UNANSWERED = "unanswered"


class TableError(ValueError):
    """The programs table (or the content that speaks it) does not have the shape the engine needs."""


def _rate(value: object) -> Decimal:
    """A rate or a price: an exact decimal string. Floats (and ints posing as rates) are rejected."""
    if not isinstance(value, str):
        raise ValueError(f"a rate must be a decimal string, not {type(value).__name__}")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{value!r} is not a decimal number") from exc
    if not number.is_finite():
        raise ValueError(f"{value!r} is not finite")
    return number


Rate = Annotated[Decimal, BeforeValidator(_rate)]


class TModel(BaseModel):
    """Every table model: unknown keys are an error, nothing is coerced loosely, nothing changes after loading."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# ---------------------------------------------------------------------------------------------- conditions

class Cond(TModel):
    """The table's condition language. `{}` always holds; `all` / `any` / `not` combine; a fact or an answer is
    compared with `op` (`value`, or `row` for lte_row)."""

    all: list[Cond] | None = None
    any: list[Cond] | None = None
    not_: Cond | None = Field(default=None, alias="not")
    fact: str | None = None
    answer: str | None = None
    op: str | None = None
    value: StrictBool | StrictInt | str | list[StrictInt | str] | None = None
    row: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> Cond:
        forms = [self.all is not None, self.any is not None, self.not_ is not None, self.fact is not None,
                 self.answer is not None]
        if sum(forms) > 1:
            raise ValueError("a condition is exactly one of all / any / not / fact / answer")
        if self.fact is not None:
            if self.op not in FACT_OPS:
                raise ValueError(f"fact op {self.op!r} is not one of {FACT_OPS}")
            if self.op == "lte_row":
                if not self.row or self.value is not None:
                    raise ValueError("lte_row compares with a row, not a value")
            elif self.row is not None:
                raise ValueError("only lte_row names a row")
            if self.op == "between":
                try:
                    low, high = self.value  # type: ignore[misc]
                except (TypeError, ValueError) as exc:
                    raise ValueError("between needs [low, high]") from exc
                if isinstance(low, bool) or isinstance(high, bool) or not isinstance(low, int) \
                        or not isinstance(high, int):
                    raise ValueError("between compares whole numbers")
            if self.op == "in" and not isinstance(self.value, list):
                raise ValueError("in needs a list")
        elif self.answer is not None:
            if self.op not in ANSWER_OPS or self.row is not None:
                raise ValueError(f"answer op {self.op!r} is not one of {ANSWER_OPS}")
            if self.op == "in" and not isinstance(self.value, list):
                raise ValueError("in needs a list")
        elif self.op is not None or self.value is not None or self.row is not None:
            raise ValueError("op, value and row belong to a fact or an answer")
        return self

    def walk(self) -> list[Cond]:
        out: list[Cond] = [self]
        for child in (self.all or []) + (self.any or []) + ([self.not_] if self.not_ else []):
            out.extend(child.walk())
        return out


Validity = tuple[date, date | None]


# ---------------------------------------------------------------------------------------------- value rows

class RowBase(TModel):
    valid: Validity
    sources: list[str]


class LimitRow(RowBase):
    """Monthly income limits by household size (Medi-Cal 138 % and 266 %)."""

    by_household: dict[str, StrictInt]
    rule: str
    unverified: str | None = None


class FaresRow(RowBase):
    muni_adult: Rate
    muni_start: Rate
    muni_pass_month: StrictInt
    lifeline_pass_month: StrictInt
    bart_average_fare: Rate
    start_discount: Rate
    weeks_per_year: StrictInt
    months_per_year: StrictInt
    unverified: str | None = None


class Gap(TModel):
    from_: date = Field(alias="from")
    to: date
    to_assumed: StrictBool = False


class BreaksRow(RowBase):
    age: tuple[StrictInt, StrictInt]
    break_weeks: StrictInt
    mail_days: StrictInt
    gaps: list[Gap]
    rides_per_week: dict[str, StrictInt]
    unverified: str | None = None


class CareRow(RowBase):
    electric_discount: Rate
    gas_discount: Rate
    electric_share_of_bill: Rate
    default_bill_alone: StrictInt
    default_bill_two_plus: StrictInt
    months: StrictInt
    unverified: str | None = None


class FlatRow(RowBase):
    monthly: Rate
    ceiling: StrictBool = False
    display_only: StrictBool = False
    basic_tier_monthly: Rate | None = None
    unverified: str | None = None


class CalEitcRow(RowBase):
    tax_year: StrictInt
    used_for_tax_year: StrictInt
    label: str
    assumes: str
    anchors_annual_earned_to_credit: list[tuple[StrictInt, StrictInt]]
    max: StrictInt
    earned_limit: StrictInt
    min_age: StrictInt
    lookup: str


class EitcParams(TModel):
    rate: Rate
    max: StrictInt
    phaseout_start: StrictInt
    phaseout_rate: Rate


class FederalEitcRow(RowBase):
    tax_year: StrictInt
    min_age_no_child: StrictInt
    max_age_no_child: StrictInt
    params: dict[str, EitcParams]
    formula: str


class YctcRow(RowBase):
    max: StrictInt
    full_up_to: StrictInt
    zero_at: StrictInt
    child_under: StrictInt
    formula: str
    label: str


Row = LimitRow | FaresRow | BreaksRow | CareRow | FlatRow | CalEitcRow | FederalEitcRow | YctcRow


# ---------------------------------------------------------------------------------------------- programs

class CoverageOnly(TModel):
    model: Literal["coverage_only"]


class TransitBreaks(TModel):
    model: Literal["transit_breaks"]
    fares_row: str
    breaks_row: str
    check_range: dict[Literal["lo_choice", "hi_choice"], str]


class FlatMonthly(TModel):
    model: Literal["flat_monthly"]
    row: str
    extra_display_row: str | None = None


class UtilityShare(TModel):
    model: Literal["utility_share"]
    row: str


class TaxCredits(TModel):
    model: Literal["tax_credits_2026"]
    caleitc_row: str
    federal_row: str
    yctc_row: str
    variants: dict[str, str]
    downgrade: str


ValueModel = Annotated[CoverageOnly | TransitBreaks | FlatMonthly | UtilityShare | TaxCredits,
                       Field(discriminator="model")]


class StatusRule(TModel):
    when: Cond
    status: Status
    notes: list[str] = Field(default_factory=list)
    variant: Literal["no_child", "parent"] | None = None


class ApplyBy(TModel):
    model: Literal["before_next_break"]
    row: str


class CalFreshLink(TModel):
    kind: str
    text_key: str
    sources: list[str]


class Apply(TModel):
    url: str
    label_key: str


class Prefill(TModel):
    screen: str
    question_key: str
    answer_key: str | None = None
    answer_from: str | None = None

    @model_validator(mode="after")
    def _one_answer(self) -> Prefill:
        if (self.answer_key is None) == (self.answer_from is None):
            raise ValueError("a prefill row has answer_key or answer_from, not both")
        return self


class Program(TModel):
    id: str
    kind: Literal["coverage", "cash", "tax_credit"]
    priority: StrictInt
    stage: ProgramStage
    status_rules: list[StatusRule]
    note_rules: dict[str, Cond] = Field(default_factory=dict)
    notes_always: list[str] = Field(default_factory=list)
    console_note_rules: dict[str, Cond] = Field(default_factory=dict)
    value: ValueModel
    apply_by: ApplyBy | None = None
    calfresh_link: CalFreshLink
    apply: Apply
    prefill: list[Prefill]
    sources: list[str]
    unverified: list[str] = Field(default_factory=list)
    cost_facts: dict[str, str] | None = None
    card_wording: str | None = None
    counting_rule: str | None = None


# ---------------------------------------------------------------------------------------------- table parts

class MoneyRules(TModel):
    value_rounding: Literal["dollar_floor"]
    display_round_down_to: StrictInt
    share_round_down_to: StrictInt
    found_display_rule: str
    horizon_months: StrictInt
    float_allowed: Literal[False]
    builtin_round_allowed: Literal[False]


class ModeFull(TModel):
    routes: list[str]
    shows: list[str]


class ModeListOnly(TModel):
    routes: list[str]
    shows: list[str]
    status_override: Literal["check"]
    amounts: Literal[False]
    rule: str


class Modes(TModel):
    full: ModeFull
    list_only: ModeListOnly
    none: ModeFull


class FactsDefaults(TModel):
    roommates_count_when_unsaid: StrictInt
    source: str
    text: str


class CalFreshKey(TModel):
    model: Literal["calfresh_annual"]
    months: StrictInt
    counted_when: Cond
    source: str
    text: str


class Question(TModel):
    choices: list[str]
    ask_when: Cond
    affects: list[str]


class AskRule(TModel):
    threshold_usd: StrictInt
    strictly_greater: StrictBool
    max_questions: StrictInt
    one_at_a_time: StrictBool
    order: list[str]
    priority: list[str]
    measure: str
    replan_after_each_answer: StrictBool
    source: str
    note: str


class Plan(TModel):
    stages: list[ProgramStage]
    include: list[ProgramStatus]
    order_within_stage: list[str]
    today_always: Literal["calfresh"]
    tax_time_window: str


class Source(TModel):
    id: str
    title: str
    url: str | None
    date: str
    grade: str


class SourceNotes(TModel):
    grades: str
    dates: str


class Unverified(TModel):
    n: StrictInt
    affects: list[str]
    text: str
    sources: list[str] = Field(default_factory=list)


class ProgramsTable(TModel):
    id: str
    label: str
    version: str
    checked: date
    effective: tuple[date, date]
    timezone: Literal["America/Los_Angeles"]
    about: str
    money: MoneyRules
    statuses: dict[str, str]
    modes: Modes
    evaluation_notes: list[str]
    facts_defaults: FactsDefaults
    calfresh_key: CalFreshKey
    questions: dict[str, Question]
    ask_rule: AskRule
    rows: dict[str, Row]
    programs: list[Program]
    value_models: dict[str, str]
    plan: Plan
    source_notes: SourceNotes
    sources: list[Source]
    unverified: list[Unverified]

    # ------------------------------------------------------------------------------------------ helpers

    def effective_on(self, today: date) -> bool:
        lo, hi = self.effective
        return lo <= today <= hi

    def program(self, program_id: str) -> Program:
        for p in self.programs:
            if p.id == program_id:
                return p
        raise KeyError(program_id)

    def source_ids(self) -> set[str]:
        return {s.id for s in self.sources}


def valid_on(row: RowBase, today: date) -> bool:
    """Inclusive at both ends; an open end (`null`) never expires."""
    start, end = row.valid
    return start <= today and (end is None or today <= end)


ROW_TYPES: dict[str, type[RowBase]] = {
    "fares_row": FaresRow, "breaks_row": BreaksRow, "caleitc_row": CalEitcRow, "federal_row": FederalEitcRow,
    "yctc_row": YctcRow,
}


def value_rows(program: Program) -> list[str]:
    """The rows a program's value needs (a likely, maybe or check line whose row is not valid today has no dollars)."""
    v = program.value
    if isinstance(v, TransitBreaks):
        return [v.fares_row, v.breaks_row]
    if isinstance(v, FlatMonthly | UtilityShare):
        return [v.row]
    if isinstance(v, TaxCredits):
        return [v.caleitc_row, v.federal_row, v.yctc_row]
    return []


def _reject_float(text: str) -> Any:
    raise TableError(f"float {text!r} in the programs table: write a rate as a string, whole dollars as an int")


def _check(table: ProgramsTable, fact_names: set[str]) -> None:
    """Cross-references the models alone cannot see."""
    problems: list[str] = []
    sources = {s.id: s for s in table.sources}
    for s in table.sources:
        if not s.date.strip():
            problems.append(f"source {s.id} has no date")
    rows = table.rows

    def need_row(where: str, name: str, kind: type[RowBase]) -> None:
        if name not in rows:
            problems.append(f"{where}: row {name!r} is missing")
        elif not isinstance(rows[name], kind):
            problems.append(f"{where}: row {name!r} is not a {kind.__name__}")

    def need_source(where: str, sid: str) -> None:
        if sid not in sources:
            problems.append(f"{where}: source {sid!r} is not in sources")

    def check_cond(where: str, cond: Cond, *, rows_allowed: bool) -> None:
        for c in cond.walk():
            if c.fact is not None and c.fact not in fact_names:
                problems.append(f"{where}: unknown fact {c.fact!r}")
            if c.answer is not None:
                q = table.questions.get(c.answer)
                if q is None:
                    problems.append(f"{where}: unknown question {c.answer!r}")
                else:
                    values = c.value if isinstance(c.value, list) else [c.value]
                    for v in values:
                        if v not in q.choices and v != UNANSWERED:
                            problems.append(f"{where}: {v!r} is not a choice of {c.answer}")
            if c.op == "lte_row":
                if not rows_allowed:
                    problems.append(f"{where}: lte_row is allowed only in status rules")
                need_row(where, c.row or "", LimitRow)

    for name, row in rows.items():
        for sid in row.sources:
            need_source(f"row {name}", sid)
    need_source("calfresh_key", table.calfresh_key.source)
    need_source("facts_defaults", table.facts_defaults.source)
    check_cond("calfresh_key", table.calfresh_key.counted_when, rows_allowed=False)
    for qid, q in table.questions.items():
        check_cond(f"question {qid}", q.ask_when, rows_allowed=False)
        if not q.choices or len(set(q.choices)) != len(q.choices) or UNANSWERED in q.choices:
            problems.append(f"question {qid}: choices must be unique and never {UNANSWERED!r}")
    if sorted(table.ask_rule.priority) != sorted(table.questions):
        problems.append("ask_rule.priority must list every question once")
    ids = [p.id for p in table.programs]
    if len(set(ids)) != len(ids) or "calfresh" in ids:
        problems.append("program ids must be unique and never 'calfresh' (the key line)")
    for p in table.programs:
        where = f"program {p.id}"
        for sid in p.sources + p.calfresh_link.sources:
            need_source(where, sid)
        if not p.status_rules or p.status_rules[-1].when != Cond():
            problems.append(f"{where}: the last status rule must be the catch-all {{}}")
        for i, rule in enumerate(p.status_rules):
            check_cond(f"{where} status rule {i}", rule.when, rows_allowed=True)
        for key, cond in {**p.note_rules, **p.console_note_rules}.items():
            check_cond(f"{where} {key}", cond, rows_allowed=False)
        v = p.value
        if isinstance(v, TransitBreaks):
            need_row(where, v.fares_row, FaresRow)
            need_row(where, v.breaks_row, BreaksRow)
            breaks = rows.get(v.breaks_row)
            if isinstance(breaks, BreaksRow):
                for choice in [*breaks.rides_per_week, *v.check_range.values()]:
                    if not any(choice in q.choices for q in table.questions.values()):
                        problems.append(f"{where}: {choice!r} is not a card choice")
        elif isinstance(v, FlatMonthly):
            need_row(where, v.row, FlatRow)
            if v.extra_display_row:
                need_row(where, v.extra_display_row, FlatRow)
        elif isinstance(v, UtilityShare):
            need_row(where, v.row, CareRow)
        elif isinstance(v, TaxCredits):
            for attr, name in (("caleitc_row", v.caleitc_row), ("federal_row", v.federal_row),
                               ("yctc_row", v.yctc_row)):
                need_row(where, name, ROW_TYPES[attr])
        if p.apply_by is not None:
            need_row(where, p.apply_by.row, BreaksRow)
        for rule in p.status_rules:
            if rule.variant is not None and not isinstance(v, TaxCredits):
                problems.append(f"{where}: only tax credits have variants")
    if table.effective[1] < table.effective[0] or table.checked > table.effective[1]:
        problems.append("effective must run forward, and checked must not be after its end")
    if problems:
        raise TableError("programs table: " + "; ".join(problems))


def load_table(path: Path, fact_names: set[str]) -> ProgramsTable:
    """Read, parse (no floats) and validate the programs table."""
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text, parse_float=_reject_float)
    table = ProgramsTable.model_validate(raw)
    _check(table, fact_names)
    return table

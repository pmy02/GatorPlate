"""Loading and checking the CalFresh rules table (data/rules/ca_fy2027.json) and reading it by household size.

Every number the engine uses comes from the table (docs/SPEC.md §5.1). Household-size tables store rows "1".."8"
explicitly; larger households use the last stored row plus `each_over_<n>` per member over that row, and a
`<n>_plus` key (for example "18_plus" or "6_plus") replaces the value for households of that size or more. The sizes
are read from the keys themselves, so the code holds no household-size literal.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from gatorplate.contracts.rules_io import REASON_CODES, RulesTable
from gatorplate.contracts.slots import SLOT_SPECS, SlotName

EACH_OVER = "each_over_"
PLUS = "_plus"
_DIGITS = re.compile(r"\d+")


class RulesTableError(ValueError):
    """The rules table does not pass the engine's checks."""


def load_table(path: Path) -> RulesTable:
    """Read, parse and check the table. Raises RulesTableError on any problem."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=_no_float)
    table = RulesTable.model_validate(raw)
    problems = check_table(table)
    if problems:
        raise RulesTableError("; ".join(problems))
    return table


def _no_float(text: str) -> Decimal:
    raise RulesTableError(f"the rules table holds a float ({text}); money and rates are strings")


def valid_on(table: RulesTable, day: date) -> bool:
    start, end = table.effective
    return start <= day <= end


def by_size(row: dict[str, int], size: int) -> int:
    """The value of a household-size table for `size` people (see the module docstring)."""
    if size < 1:
        raise ValueError(f"household size {size} is below 1")
    plus = sorted((int(key.removesuffix(PLUS)), value) for key, value in row.items() if key.endswith(PLUS))
    for start, value in reversed(plus):
        if size >= start:
            return value
    rows = {int(key): value for key, value in row.items() if key.isdigit()}
    if size in rows:
        return rows[size]
    over = [key for key in row if key.startswith(EACH_OVER)]
    if over:
        base = int(over[0].removeprefix(EACH_OVER))
        return rows[base] + row[over[0]] * (size - base)
    raise ValueError(f"household size {size} has no row")


def sizes_in_name(name: str) -> list[int]:
    """Household sizes written into a table key name ("min_benefit_1_2_persons" -> [1, 2])."""
    return [int(part) for part in _DIGITS.findall(name)]


def min_benefit_max_size() -> int:
    """The largest household that gets the minimum benefit (the sizes are part of the key name)."""
    return max(sizes_in_name("min_benefit_1_2_persons"))


def zero_benefit_min_size() -> int:
    """The smallest household routed to other help when the computed amount is 0 or below."""
    return min(sizes_in_name("zero_benefit_3_plus_route"))


def source_id(table: RulesTable, *keys: str) -> str | None:
    """The source id of the first `value_sources` key that exists (dotted keys for nested values)."""
    for key in keys:
        if key in table.value_sources:
            return table.value_sources[key]
    return None


def check_table(table: RulesTable) -> list[str]:
    """Checks beyond the schema: dates, rows, rates, sources, routes, steps and the question-picker settings."""
    problems: list[str] = []
    start, end = table.effective
    if not start <= end:
        problems.append("effective dates are reversed")
    for name in ("max_allotment", "gross_limit_200", "irt_130"):
        row = getattr(table, name)
        rows = sorted(int(k) for k in row if k.isdigit())
        if not rows or rows != list(range(rows[0], rows[-1] + 1)) or rows[0] != 1:
            problems.append(f"{name}: rows must run from 1 without gaps")
        if not any(k.startswith(EACH_OVER) for k in row):
            problems.append(f"{name}: no per-member increment")
    if "1" not in table.standard_deduction or not any(k.endswith(PLUS) for k in table.standard_deduction):
        problems.append("standard_deduction: needs row 1 and an open-ended row")
    for rate_name, rate in table.rates.model_dump().items():
        if not Decimal(0) < rate < Decimal(1):
            problems.append(f"rates.{rate_name} is not between 0 and 1")
    ids = {s.id for s in table.sources}
    for key, sid in table.value_sources.items():
        if sid not in ids:
            problems.append(f"value_sources.{key} names an unknown source {sid}")
    for key, sid in table.grad.exemption_sources.items():
        if sid not in ids:
            problems.append(f"grad.exemption_sources.{key} names an unknown source {sid}")
    if set(table.grad.exemptions) != set(table.grad.exemption_labels):
        problems.append("grad.exemption_labels do not match grad.exemptions")
    for name, code in table.routes.model_dump().items():
        if code not in REASON_CODES:
            problems.append(f"routes.{name} is not a reason code ({code})")
    if table.zero_benefit_3_plus_route not in REASON_CODES:
        problems.append("zero_benefit_3_plus_route is not a reason code")
    known_steps = {
        "table_dates", "volunteered_status", "elderly_or_disabled", "school", "parent_household", "student_age",
        "degree_program", "grad_exemption", "work_rule", "household", "income", "gross_income_test",
        "adjusted_income", "shelter", "net_income", "benefit", "first_month", "expedited",
    }
    steps = [s.step for s in table.decision_order]
    if set(steps) != known_steps or len(steps) != len(set(steps)):
        problems.append("decision_order must list each engine step exactly once")
    elif steps.index("parent_household") > steps.index("student_age"):
        problems.append("decision_order: the parent-household check must run before the student-age route")
    voi = table.voi
    for name in [*voi.priority, *voi.slots]:
        if name not in SlotName.__members__:
            problems.append(f"voi: {name} is not a slot")
    if set(voi.priority) != set(voi.slots):
        problems.append("voi.priority and voi.slots name different slots")
    for name, spec in voi.slots.items():
        if name in SlotName.__members__ and spec.default != "conservative":
            if isinstance(spec.candidates, str) or spec.default not in spec.candidates:
                problems.append(f"voi.slots.{name}: the natural default is not a candidate")
        if spec.only_if:
            for cond in spec.only_if:
                if cond not in SlotName.__members__ or SLOT_SPECS[SlotName(cond)].type != "bool":
                    problems.append(f"voi.slots.{name}.only_if: {cond} is not a yes/no slot")
    if voi.flip_threshold_usd < 0 or voi.max_questions < 0:
        problems.append("voi: threshold and question limit must not be negative")
    if len(voi.income_band.fractions_of_gross_limit) != len(voi.income_band.edges_1_person):
        problems.append("voi.income_band: fractions and 1-person edges differ in length")
    weekend = {calendar.SATURDAY, calendar.SUNDAY}
    if any(e.filed_on.weekday() in weekend for e in table.filing_date_estimate.examples):
        problems.append("filing_date_estimate: an example files on a weekend")
    return problems

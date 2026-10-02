"""The table's condition language (docs/SPEC.md §5.10 "Facts").

`{}` always holds; `all` / `any` / `not` combine (read left to right, stopping at the first decisive part); a fact is
compared with eq ne lt lte gt gte in between (inclusive) or lte_row (the row value for the household size); a card
answer is compared with in / eq / ne, where a question with no answer reads "unanswered". A fact with no value makes
a comparison false. An lte_row whose row is not valid today (or has no value for the household size) stops the status
rules: the program becomes `check` with no dollars.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from gatorplate.programs.facts import ProgramFacts
from gatorplate.programs.table import UNANSWERED, Cond, LimitRow, RowBase, valid_on


class RowNotValid(Exception):  # noqa: N818 - a signal, not an error
    """An lte_row condition met a row that is not valid today: the status rules stop (-> check, no dollars)."""

    def __init__(self, row: str) -> None:
        super().__init__(row)
        self.row = row


@dataclass
class Comparison:
    """One lte_row comparison that was made (for the console's "How" column)."""

    fact: str
    value: Decimal | int
    row: str
    limit: int
    size: int
    held: bool


@dataclass
class Context:
    facts: ProgramFacts
    answers: Mapping[str, str]
    rows: Mapping[str, RowBase]
    today: date
    trace: list[Comparison] = field(default_factory=list)


def _number(value: object) -> bool:
    return isinstance(value, int | Decimal) and not isinstance(value, bool)


def _eq(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):  # True is never 1 here
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    return left == right


def _compare(op: str, left: object, right: object) -> bool:
    if op == "eq":
        return _eq(left, right)
    if op == "ne":
        return not _eq(left, right)
    if op == "in":
        return isinstance(right, list) and any(_eq(left, item) for item in right)
    if not _number(left):
        return False
    if op == "between":
        if not isinstance(right, list):
            return False
        low, high = right
        return _number(low) and _number(high) and low <= left <= high  # type: ignore[operator]
    if not _number(right):
        return False
    if op == "lt":
        return left < right  # type: ignore[operator]
    if op == "lte":
        return left <= right  # type: ignore[operator]
    if op == "gt":
        return left > right  # type: ignore[operator]
    if op == "gte":
        return left >= right  # type: ignore[operator]
    raise ValueError(f"unknown op {op!r}")


def holds(cond: Cond, ctx: Context) -> bool:
    """Whether a condition holds. Raises RowNotValid for an lte_row against a row that is not valid today."""
    if cond.all is not None:
        return all(holds(c, ctx) for c in cond.all)
    if cond.any is not None:
        return any(holds(c, ctx) for c in cond.any)
    if cond.not_ is not None:
        return not holds(cond.not_, ctx)
    if cond.answer is not None:
        current = ctx.answers.get(cond.answer, UNANSWERED)
        return _compare(cond.op or "", current, cond.value)
    if cond.fact is not None:
        value = getattr(ctx.facts, cond.fact)
        if value is None:
            return False
        if cond.op == "lte_row":
            return _lte_row(cond, value, ctx)
        return _compare(cond.op or "", value, cond.value)
    return True  # {} always holds


def _lte_row(cond: Cond, value: object, ctx: Context) -> bool:
    name = cond.row or ""
    row = ctx.rows[name]
    if not isinstance(row, LimitRow) or not valid_on(row, ctx.today):
        raise RowNotValid(name)
    size = ctx.facts.household_size
    limit = row.by_household.get(str(size))
    if limit is None:  # a household larger than the table's rows: no number to compare with, so no dollars
        raise RowNotValid(name)
    if not _number(value):
        return False
    held = value <= limit  # type: ignore[operator]
    ctx.trace.append(Comparison(fact=cond.fact or "", value=value, row=name, limit=limit, size=size,  # type: ignore[arg-type]
                                held=held))
    return held


def holds_quietly(cond: Cond, ctx: Context) -> bool:
    """For note, console-note and ask conditions: a row that is not valid simply makes the condition false."""
    try:
        return holds(cond, ctx)
    except RowNotValid:
        return False

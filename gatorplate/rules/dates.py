"""Dates in America/Los_Angeles (docs/SPEC.md §5.7): the filing-date estimate, the first-month proration and the
tracking deadlines. Every day count and cutoff comes from the rules table."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from gatorplate.contracts.case import FirstMonth, Tracking
from gatorplate.contracts.rules_io import RulesTable
from gatorplate.rules.money import rounder

ONE_DAY = timedelta(days=1)
WEEKEND = frozenset({calendar.SATURDAY, calendar.SUNDAY})


def local(table: RulesTable, moment: datetime, tz: str | None = None) -> datetime:
    """The moment as wall-clock time in the table's time zone (an aware datetime is required)."""
    if moment.tzinfo is None:
        raise ValueError("an aware datetime is required")
    return moment.astimezone(ZoneInfo(tz or table.timezone))


def next_weekday(day: date) -> date:
    """The day itself when it is a weekday, otherwise the following Monday (holidays are not modeled)."""
    while day.weekday() in WEEKEND:
        day += ONE_DAY
    return day


def filing_date(table: RulesTable, now: datetime, tz: str | None = None) -> date:
    """A weekday before the cutoff (5 PM Pacific) counts that day; otherwise the next weekday. Pacific date only."""
    at = local(table, now, tz)
    cutoff = time.fromisoformat(table.filing_date_estimate.cutoff_local)
    day = at.date()
    if day.weekday() in WEEKEND or at.time() >= cutoff:
        day += ONE_DAY
    return next_weekday(day)


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def first_month(table: RulesTable, amount: int, *, apply_date: date, filed_on: date) -> FirstMonth:
    """Proration: (amount × days counted) // days in the month; below the table's minimum issue it is 0."""
    total = days_in_month(filed_on)
    counted = total - filed_on.day + 1
    # rounding.proration = dollar_floor: the exact quotient floored, equal to (amount × days) // days_in_month
    value = int(rounder(table, "proration")(Decimal(amount * counted) / Decimal(total)))
    if value < table.proration_min_issue:
        value = 0
    return FirstMonth(apply_date=apply_date, filed_on=filed_on, amount=value, days_counted=counted,
                      month_label=calendar.month_name[filed_on.month], estimate=True)


def add_months(day: date, months: int) -> date:
    """The first day of the month `months` after the month of `day`."""
    first = day.replace(day=1)
    for _ in range(months):
        first = first + timedelta(days=days_in_month(first))
    return first


def compute_tracking(table: RulesTable, tracking: Tracking) -> Tracking:
    """Fills the computed tracking dates from the coordinator's inputs (docs/UI_SPEC.md A3.9).

    filed_on = applied_at when it is a weekday, otherwise the next weekday; decision due = filed_on + decision days;
    papers due = request + document days; SAR 7 due about day `sar7_due_day` of certification month `sar7_month` and
    renewal at the end of month `recert_month`, both counted from the first benefit month (the filing month) and
    only once the case is approved. The SAR 7 day is approximate (not verified)."""
    d = table.deadlines
    out = tracking.model_copy(deep=True)
    out.filed_on = next_weekday(tracking.applied_at) if tracking.applied_at else None
    out.deadline_30d = out.filed_on + timedelta(days=d.decision_days) if out.filed_on else None
    out.doc_due = (tracking.doc_request_at + timedelta(days=d.doc_request_days)
                   if tracking.doc_request_at else None)
    start = out.filed_on or tracking.approved_at
    if tracking.approved_at and start:
        sar7_month = add_months(start, d.sar7_month - 1)
        out.sar7_due = sar7_month.replace(day=min(d.sar7_due_day, days_in_month(sar7_month)))
        recert_month = add_months(start, d.recert_month - 1)
        out.recert_due = recert_month.replace(day=days_in_month(recert_month))
    else:
        out.sar7_due = None
        out.recert_due = None
    return out

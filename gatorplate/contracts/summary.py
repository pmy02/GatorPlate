"""The one-line case summary and the console's CaseSummary (never a name: the label is the case code)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from gatorplate.contracts.case import Case
from gatorplate.contracts.console_api import CaseSummary
from gatorplate.contracts.slots import SlotName, decode_value, money_text

LEVEL_TEXT = {"undergrad": "Undergrad", "grad": "Grad", "not_degree": "Not in a degree program",
              "not_sfsu": "Not SF State"}
SEP = " · "


def _value(case: Case, name: SlotName):
    slot = case.slots.get(name)
    if slot is None or slot.value is None:
        return None
    try:
        return decode_value(name, slot.value)
    except (TypeError, ValueError):
        return None


def household_size(case: Case) -> int:
    """The student + a spouse + children (docs/SPEC.md §5.2)."""
    spouse = 1 if _value(case, SlotName.spouse) is True else 0
    children = _value(case, SlotName.children_count)
    return 1 + spouse + (children if isinstance(children, int) else 0)


def summary_line(case: Case) -> str:
    """'Undergrad · 1 person · work $900 · rent $1,100': level · household size · work · other cash · rent or
    'no fixed home'. Parts the call never reached are left out."""
    parts: list[str] = []
    level = _value(case, SlotName.level)
    if isinstance(level, str):
        parts.append(LEVEL_TEXT.get(level, level))
    if parts or case.slots:
        size = household_size(case)
        parts.append(f"{size} person" if size == 1 else f"{size} people")
    earned = _value(case, SlotName.earned_monthly)
    if isinstance(earned, Decimal) and earned > 0:
        parts.append(f"work {money_text(earned)}")
    cash = _value(case, SlotName.other_cash_monthly)
    if isinstance(cash, Decimal) and cash > 0:
        parts.append(f"cash {money_text(cash)}")
    if _value(case, SlotName.homeless) is True:
        parts.append("no fixed home")
    else:
        rent = _value(case, SlotName.rent_share)
        if isinstance(rent, Decimal):
            parts.append(f"rent {money_text(rent)}")
    return SEP.join(parts)


def next_deadline(case: Case, *, today: date | None = None, tz: str = "America/Los_Angeles") -> date | None:
    """The earliest tracking deadline on or after `today` (default: the Pacific date of the case's last update)."""
    reference = today or case.updated_at.astimezone(ZoneInfo(tz)).date()
    t = case.tracking
    dates = [d for d in (t.deadline_30d, t.doc_due, t.sar7_due, t.recert_due) if d is not None and d >= reference]
    return min(dates) if dates else None


def case_summary(case: Case, *, tz: str = "America/Los_Angeles", today: date | None = None) -> CaseSummary:
    """The console list row of a case. `found_display` stays null here (the programs port fills it)."""
    open_lines = [y for y in case.yellow_lines if y.resolved is None]
    return CaseSummary(
        id=case.id, code=case.code, version=case.version, created_at=case.created_at, updated_at=case.updated_at,
        label=case.code, summary=case.summary or summary_line(case), lang=case.lang, channel=case.channel,
        live=case.live, test=case.test, seeded=case.seeded, phase=case.phase, status=case.status,
        ended_early=case.ended_early, tier=case.tier, reason_code=case.reason_code,
        estimate_monthly=case.estimate_monthly, estimate_is_floor=case.estimate_is_floor,
        expedited_possible=case.expedited_possible, yellow_open=len(open_lines),
        yellow_total=len(case.yellow_lines), asked_count=len(case.asked), skipped_count=len(case.skipped),
        next_deadline=next_deadline(case, today=today, tz=tz), found_display=None,
    )

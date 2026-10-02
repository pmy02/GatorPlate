"""Money helpers named after the rules table's rounding modes (docs/SPEC.md §5.5).

Decimal only: no float and no round(). Ceilings and floors use Decimal rounding modes; the cent is the contract's
canonical money step. Income is converted to monthly once (the table's `conversion`), then kept exact.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from gatorplate.contracts.common import Period
from gatorplate.contracts.rules_io import RulesTable
from gatorplate.contracts.slots import CENT, MoneyBasis, money_text

DOLLAR = Decimal(1)
ZERO = Decimal(0)


def cents_half_up(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def exact_decimal(amount: Decimal) -> Decimal:
    return amount


def dollar_half_up(amount: Decimal) -> int:
    return int(amount.quantize(DOLLAR, rounding=ROUND_HALF_UP))


def dollar_ceil(amount: Decimal) -> int:
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def dollar_floor(amount: Decimal) -> int:
    return int(amount.to_integral_value(rounding=ROUND_FLOOR))


ROUNDERS: dict[str, Callable[[Decimal], Decimal | int]] = {
    "cents_half_up": cents_half_up,
    "exact_decimal": exact_decimal,
    "dollar_half_up": dollar_half_up,
    "dollar_ceil": dollar_ceil,
    "dollar_floor": dollar_floor,
}


def rounder(table: RulesTable, step: str) -> Callable[[Decimal], Decimal | int]:
    """The rounding function the table names for a step (`rounding.<step>`)."""
    mode = getattr(table.rounding, step)
    if mode not in ROUNDERS:
        raise ValueError(f"unknown rounding mode {mode!r} for {step}")
    return ROUNDERS[mode]


def as_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("money is never a float")
    return value if isinstance(value, Decimal) else Decimal(value)


def to_monthly(table: RulesTable, amount: Decimal, period: Period, hours_per_week: Decimal | None = None) -> Decimal:
    """Monthly amount, converted once and rounded per `rounding.income_conversion` (cents half-up)."""
    amount = as_decimal(amount)
    mult = table.conversion.multipliers
    if period == "month":
        raw = amount * mult.month
    elif period == "week":
        raw = amount * mult.week
    elif period == "biweek":
        raw = amount * mult.biweek
    elif period == "semimonth":
        raw = amount * mult.semimonth
    elif period == "year":
        raw = amount / table.conversion.year_divisor
    elif period == "hour":
        if hours_per_week is None:
            raise ValueError("hourly pay needs hours_per_week")
        raw = amount * as_decimal(hours_per_week) * mult.week
    elif period == "once":
        raw = amount
    else:
        raise ValueError(f"unknown period {period!r}")
    result = rounder(table, "income_conversion")(raw)
    return result if isinstance(result, Decimal) else Decimal(result)


def normalize(table: RulesTable, basis: MoneyBasis) -> Decimal:
    return to_monthly(table, basis.amount, basis.period, basis.hours_per_week)


def freq_period(table: RulesTable, freq: str) -> Period:
    """The period of a golden-case income frequency ("weekly" -> "week")."""
    return getattr(table.conversion.freq_alias, freq)


# ---------------------------------------------------------------------------------------------- trace wording


MINUS = "\N{MINUS SIGN}"


def usd(amount: Decimal | int) -> str:
    """'$1,100' or, with cents, '$251.50'; a negative amount as '−$207' (the trace's minus sign)."""
    value = as_decimal(amount)
    if value < ZERO:
        return MINUS + money_text(-value, cents=True)
    return money_text(value, cents=True)


def pct(rate: Decimal) -> str:
    """'20%' from the table's rate '0.20'."""
    return format(rate.normalize(), "%")

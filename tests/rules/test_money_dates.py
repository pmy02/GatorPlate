"""Money conversion and rounding (docs/SPEC.md §5.5) and dates in Pacific time (docs/SPEC.md §5.7)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from gatorplate.clock import FixedClock
from gatorplate.contracts.case import Tracking
from gatorplate.contracts.slots import MoneyBasis
from gatorplate.rules import Rules, dates
from gatorplate.rules.money import cents_half_up, dollar_ceil, dollar_floor, dollar_half_up, pct, to_monthly, usd


def test_conversion_examples(rules: Rules) -> None:
    for example in rules.table.conversion.examples:
        basis = MoneyBasis(amount=example.basis.amount, period=example.basis.period,
                           hours_per_week=example.basis.hours_per_week)
        assert rules.normalize_money(basis) == example.monthly
        assert str(rules.normalize_money(basis)) == str(example.monthly)


def test_g12_hourly_and_once(rules: Rules) -> None:
    assert rules.normalize_money(MoneyBasis(amount=Decimal("20"), period="hour", hours_per_week=Decimal("15"))) \
        == Decimal("1299.00")
    assert rules.normalize_money(MoneyBasis(amount=Decimal("40"), period="once")) == Decimal("40.00")
    with pytest.raises(ValueError):
        rules.normalize_money(MoneyBasis(amount=Decimal("20"), period="hour"))


def test_rounding_helpers() -> None:
    assert cents_half_up(Decimal("2660.0056")) == Decimal("2660.01")
    assert cents_half_up(Decimal("699.165")) == Decimal("699.17")
    assert dollar_half_up(Decimal("20.5")) == 21 and dollar_half_up(Decimal("834.5")) == 835
    assert dollar_half_up(Decimal("13.498")) == 13
    assert dollar_ceil(Decimal("150.9")) == 151 and dollar_ceil(Decimal("0")) == 0 and dollar_ceil(Decimal("6")) == 6
    assert dollar_floor(Decimal("296.99")) == 296
    assert pct(Decimal("0.20")) == "20%" and pct(Decimal("0.50")) == "50%"
    assert usd(Decimal("251.50")) == "$251.50" and usd(1100) == "$1,100"


def test_float_is_refused(rules: Rules) -> None:
    with pytest.raises(TypeError):
        to_monthly(rules.table, 900.0, "month")  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", ["0.01", "1", "99.99", "161.47", "614.31", "614.32", "1227.50", "2000"])
@pytest.mark.parametrize("period", ["week", "biweek", "semimonth", "month", "year"])
def test_conversion_grid_is_exact(rules: Rules, amount: str, period: str) -> None:
    """Property: the result has exactly two decimals and equals the exact product rounded half-up once."""
    t = rules.table
    factor = {"week": t.conversion.multipliers.week, "biweek": t.conversion.multipliers.biweek,
              "semimonth": t.conversion.multipliers.semimonth, "month": t.conversion.multipliers.month}
    exact = Decimal(amount) / t.conversion.year_divisor if period == "year" else Decimal(amount) * factor[period]
    got = to_monthly(t, Decimal(amount), period)
    assert got == exact.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    assert got.as_tuple().exponent == -2


@pytest.mark.parametrize("now,filed", [
    ("2026-10-01T23:30:00-07:00", date(2026, 10, 2)),
    ("2026-10-02T16:59:00-07:00", date(2026, 10, 2)),
    ("2026-10-02T17:01:00-07:00", date(2026, 10, 5)),
    ("2026-10-03T10:00:00-07:00", date(2026, 10, 5)),
    ("2026-10-02T23:30:00-07:00", date(2026, 10, 5)),
    ("2026-10-04T08:00:00-07:00", date(2026, 10, 5)),
    ("2026-10-02T17:00:00-07:00", date(2026, 10, 5)),
])
def test_filing_date(rules: Rules, now: str, filed: date) -> None:
    assert rules.filing_date(datetime.fromisoformat(now)) == filed


def test_filing_date_examples_from_the_table(rules: Rules) -> None:
    for example in rules.table.filing_date_estimate.examples:
        moment = datetime.fromisoformat(example.now)
        filed = rules.filing_date(moment)
        assert filed == example.filed_on
        assert dates.first_month(rules.table, 306, apply_date=moment.date(), filed_on=filed).amount \
            == example.first_month_for_306


def test_pacific_date_not_utc(rules: Rules) -> None:
    """16:59 PDT on Friday is already 23:59 UTC; 23:30 PDT is Saturday in UTC — both still Friday in Pacific."""
    friday_late = FixedClock.pacific(2026, 10, 2, 16, 59).now()
    assert friday_late.astimezone(UTC).hour == 23
    assert rules.filing_date(friday_late) == date(2026, 10, 2)
    night = FixedClock.pacific(2026, 10, 2, 23, 30)
    assert night.now().astimezone(UTC).date() == date(2026, 10, 3) and night.today() == date(2026, 10, 2)
    assert rules.filing_date(night.now()) == date(2026, 10, 5)
    with pytest.raises(ValueError):
        rules.filing_date(datetime(2026, 10, 2, 10, 0))


@pytest.mark.parametrize("amount,filed,expected,days", [
    (306, date(2026, 10, 15), 167, 17), (306, date(2026, 10, 1), 306, 31), (306, date(2026, 10, 31), 0, 1),
    (306, date(2026, 10, 30), 19, 2), (25, date(2026, 10, 19), 10, 13), (25, date(2026, 10, 20), 0, 12),
    (55, date(2026, 11, 25), 11, 6), (306, date(2027, 2, 28), 10, 1), (75, date(2026, 11, 9), 55, 22),
])
def test_first_month_proration(rules: Rules, amount: int, filed: date, expected: int, days: int) -> None:
    fm = dates.first_month(rules.table, amount, apply_date=filed, filed_on=filed)
    assert (fm.amount, fm.days_counted) == (expected, days)
    if expected:
        assert fm.amount == (amount * days) // dates.days_in_month(filed)


def test_proration_grid_matches_integer_floor(rules: Rules) -> None:
    for amount in (25, 55, 75, 106, 155, 306, 562):
        for day in range(1, 32):
            filed = date(2026, 10, day)
            fm = dates.first_month(rules.table, amount, apply_date=filed, filed_on=filed)
            reference = (amount * (31 - day + 1)) // 31
            assert fm.amount == (reference if reference >= 10 else 0)


@pytest.mark.parametrize("applied,filed,due", [
    (date(2026, 10, 1), date(2026, 10, 1), date(2026, 10, 31)),
    (date(2026, 10, 4), date(2026, 10, 5), date(2026, 11, 4)),
    (date(2026, 10, 5), date(2026, 10, 5), date(2026, 11, 4)),
])
def test_tracking_jamal_examples(rules: Rules, applied: date, filed: date, due: date) -> None:
    t = rules.compute_tracking(Tracking(applied_at=applied))
    assert (t.filed_on, t.deadline_30d) == (filed, due)
    assert t.sar7_due is None and t.recert_due is None


def test_tracking_papers_sar7_and_renewal(rules: Rules) -> None:
    t = rules.compute_tracking(Tracking(applied_at=date(2026, 10, 1), doc_request_at=date(2026, 10, 9),
                                        approved_at=date(2026, 10, 20)))
    assert t.doc_due == date(2026, 10, 19)
    assert t.sar7_due == date(2027, 3, 5)  # about day 5 of certification month 6 (approximate)
    assert t.recert_due == date(2027, 9, 30)  # end of certification month 12
    cleared = rules.compute_tracking(t.model_copy(update={"approved_at": None, "doc_request_at": None}))
    assert cleared.sar7_due is None and cleared.doc_due is None

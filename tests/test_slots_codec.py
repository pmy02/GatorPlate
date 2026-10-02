"""Slot specs and the canonical value codecs (docs/SPEC.md §3.10)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gatorplate.contracts.slots import (
    ROUTING_ONLY,
    SLOT_SPECS,
    MoneyBasis,
    SlotName,
    decode_value,
    encode_value,
    format_display,
)


def test_every_slot_has_a_spec() -> None:
    assert set(SLOT_SPECS) == set(SlotName)
    assert len(SlotName) == 38


def test_critical_slots_exactly() -> None:
    critical = {name for name, spec in SLOT_SPECS.items() if spec.critical}
    assert critical == {SlotName.earned_monthly, SlotName.other_cash_monthly, SlotName.rent_share,
                        SlotName.rent_paid_by_others_to_landlord}


def test_chip_nouns_and_labels() -> None:
    assert SLOT_SPECS[SlotName.heat_cool].short == "heating or cooling bill"
    assert SLOT_SPECS[SlotName.other_utils].short == "other utility bills"
    assert SLOT_SPECS[SlotName.rent_paid_by_others_to_landlord].short == "rent paid by someone else"
    assert SLOT_SPECS[SlotName.rent_share].label == "Rent share"
    assert SLOT_SPECS[SlotName.earned_monthly].label == "Work income"


def test_roommates_count_spec() -> None:
    spec = SLOT_SPECS[SlotName.roommates_count]
    assert (spec.type, spec.label, spec.min, spec.max) == ("int", "Number of roommates", Decimal(0), Decimal(10))
    assert not spec.critical and not spec.periodic
    assert encode_value(SlotName.roommates_count, 2) == "2"
    assert encode_value("roommates_count", "10") == "10"
    for bad in (11, -1, "two", 2.0, True):
        with pytest.raises((ValueError, TypeError)):
            encode_value(SlotName.roommates_count, bad)


def test_enum_choices() -> None:
    assert SLOT_SPECS[SlotName.other_utils].choices == ["none", "phone_only", "two_plus"]
    assert SLOT_SPECS[SlotName.level].choices == ["undergrad", "grad", "not_degree", "not_sfsu"]
    assert SLOT_SPECS[SlotName.household_food].choices == ["alone", "separate", "shared"]
    assert ROUTING_ONLY == {SlotName.volunteered_status, SlotName.elderly_or_disabled}


@pytest.mark.parametrize("name,value,raw", [
    ("consent", True, "true"), ("homeless", False, "false"), ("homeless", "TRUE", "true"),
    ("age", 20, "20"), ("units", "12", "12"),
    ("earned_monthly", Decimal("900"), "900.00"), ("earned_monthly", 900, "900.00"),
    ("earned_monthly", "1169.1", "1169.10"), ("rent_share", Decimal("1266.525"), "1266.53"),
    ("cash_on_hand", "1000", "1000.00"), ("household_food", "separate", "separate"),
    ("grad_exemption", "none", "none"), ("other_utils", "two_plus", "two_plus"),
])
def test_round_trip(name: str, value, raw: str) -> None:
    assert encode_value(name, value) == raw
    assert encode_value(name, decode_value(name, raw)) == raw


@pytest.mark.parametrize("name,value", [
    ("earned_monthly", 900.0), ("earned_monthly", True), ("earned_monthly", "abc"), ("earned_monthly", "-5"),
    ("earned_monthly", "50000"), ("units", "fifty"), ("units", "50"), ("age", 3), ("consent", "yes"),
    ("household_food", "together"), ("level", "undergraduate"), ("earned_monthly", "NaN"),
])
def test_rejects(name: str, value) -> None:
    with pytest.raises((ValueError, TypeError)):
        encode_value(name, value)


def test_decode_types() -> None:
    assert decode_value("consent", "true") is True
    assert decode_value("age", "20") == 20
    assert decode_value("rent_share", "1100.00") == Decimal("1100.00")
    with pytest.raises(ValueError):
        decode_value("consent", "yes")
    with pytest.raises(TypeError):
        decode_value("consent", True)  # type: ignore[arg-type]


def test_format_display() -> None:
    assert format_display("earned_monthly", "900.00") == "$900/mo"
    basis = MoneyBasis(amount=Decimal("18"), period="hour", hours_per_week=Decimal("15"))
    assert format_display("earned_monthly", "1169.10", basis) == "$1,169/mo ($18/h × 15 h/wk)"
    weekly = MoneyBasis(amount=Decimal("292.50"), period="week")
    assert format_display("earned_monthly", "1266.53", weekly) == "$1,267/mo ($292.50/wk)"
    assert format_display("cash_on_hand", "1000.00") == "$1,000"
    assert format_display("consent", "true") == "Yes"
    assert format_display("household_food", "separate") == "Separately"
    assert format_display("roommates_count", "2") == "2"
    assert format_display("rent_share", None) == "—"

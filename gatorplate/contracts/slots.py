"""Slots: what GatorPlate listens for (docs/SPEC.md §3.10), their specs and the canonical value codecs.

Canonical encodings (Slot.value): bool "true" / "false"; int "20"; money as a monthly amount with two decimals
("1169.10"); enum = the choice id. Money is Decimal, never float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import Field

from gatorplate.contracts.common import Model, Period, SlotSource, SlotState


class SlotName(StrEnum):
    consent = "consent"
    level = "level"
    units = "units"
    half_time = "half_time"
    grad_exemption = "grad_exemption"
    age = "age"
    lives_with_parent = "lives_with_parent"
    roommates = "roommates"
    dorm_on_campus = "dorm_on_campus"
    meals_per_week = "meals_per_week"
    dorm_meals_over_10 = "dorm_meals_over_10"
    household_food = "household_food"
    spouse = "spouse"
    spouse_student = "spouse_student"
    children_count = "children_count"
    youngest_child_age = "youngest_child_age"
    boarder = "boarder"
    homeless = "homeless"
    homeless_shelter_cost_monthly = "homeless_shelter_cost_monthly"
    earned_monthly = "earned_monthly"
    work_study_monthly = "work_study_monthly"
    gig_monthly = "gig_monthly"
    ta_ra = "ta_ra"
    unearned_monthly = "unearned_monthly"
    other_cash_monthly = "other_cash_monthly"
    dependent_care_monthly = "dependent_care_monthly"
    rent_share = "rent_share"
    rent_paid_by_others_to_landlord = "rent_paid_by_others_to_landlord"
    heat_cool = "heat_cool"
    other_utils = "other_utils"
    cash_on_hand = "cash_on_hand"
    volunteered_status = "volunteered_status"  # routing only: never persisted
    elderly_or_disabled = "elderly_or_disabled"  # routing only: never persisted
    already_receiving = "already_receiving"
    applied_waiting_interview = "applied_waiting_interview"
    previously_denied = "previously_denied"
    income_changing_soon = "income_changing_soon"
    roommates_count = "roommates_count"  # extracted when said, never asked (docs/SPEC.md §3.10)


ROUTING_ONLY: frozenset[SlotName] = frozenset({SlotName.volunteered_status, SlotName.elderly_or_disabled})

SlotType = Literal["bool", "int", "money", "enum"]


class SlotSpec(Model):
    type: SlotType
    label: str  # English console label (docs/UI_SPEC.md A3.5)
    short: str  # chip noun ("heating or cooling bill")
    choices: list[str] | None = None
    critical: bool = False  # explicit-confirm rule applies (the four critical money slots only)
    periodic: bool = False  # stated with a period, normalized to monthly
    min: Decimal | None = None  # plausibility, not policy
    max: Decimal | None = None


# Choice lists that live in data/rules/ca_fy2027.json (grad.exemptions plus "none"; status.other_help +
# status.coordinator). tests/test_data_valid.py checks that they equal the table.
GRAD_EXEMPTION_CHOICES: list[str] = [
    "campus_job", "ta_ra", "work_study", "work20h", "child_under_6", "child_6_to_11_no_care",
    "single_parent_full_time_child_under_12", "calworks", "dor_wioa", "final_term", "under_half_time", "none",
]
STATUS_CHOICES: list[str] = [
    "F-1", "J-1", "DACA", "TPS", "undocumented", "LPR", "refugee_asylee", "parolee", "other",
]


def _bool(label: str, short: str) -> SlotSpec:
    return SlotSpec(type="bool", label=label, short=short)


def _int(label: str, short: str, lo: int, hi: int) -> SlotSpec:
    return SlotSpec(type="int", label=label, short=short, min=Decimal(lo), max=Decimal(hi))


def _money(label: str, short: str, hi: int, *, critical: bool = False, periodic: bool = True) -> SlotSpec:
    return SlotSpec(type="money", label=label, short=short, critical=critical, periodic=periodic,
                    min=Decimal(0), max=Decimal(hi))


def _enum(label: str, short: str, choices: list[str]) -> SlotSpec:
    return SlotSpec(type="enum", label=label, short=short, choices=list(choices))


N = SlotName
SLOT_SPECS: dict[SlotName, SlotSpec] = {
    N.consent: _bool("Consent", "consent"),
    N.level: _enum("Student level", "student level", ["undergrad", "grad", "not_degree", "not_sfsu"]),
    N.units: _int("Units this term", "units this term", 0, 30),
    N.half_time: _bool("Half-time or more", "half-time or more"),
    N.grad_exemption: _enum("Grad student exemption", "grad student exemption", GRAD_EXEMPTION_CHOICES),
    N.age: _int("Age", "age", 13, 99),
    N.lives_with_parent: _bool("Lives with a parent", "living with a parent"),
    N.roommates: _bool("Lives with roommates", "roommates"),
    N.dorm_on_campus: _bool("Lives in a campus dorm", "campus dorm"),
    N.meals_per_week: _int("Meal plan, meals a week", "meal plan", 0, 21),
    N.dorm_meals_over_10: _bool("Meal plan over 10 meals a week", "meal plan over 10 meals a week"),
    N.household_food: _enum("Buys and cooks food", "who buys and cooks food", ["alone", "separate", "shared"]),
    N.spouse: _bool("Spouse or partner", "spouse or partner"),
    N.spouse_student: _bool("Spouse is a student", "spouse in school"),
    N.children_count: _int("Children", "children", 0, 10),
    N.youngest_child_age: _int("Youngest child's age", "youngest child's age", 0, 25),
    N.boarder: _bool("Pays for room and meals", "room and meals"),
    N.homeless: _bool("No regular place to stay", "no regular place to stay"),
    N.homeless_shelter_cost_monthly: _money("Pays to stay", "cost to stay", 5000),
    N.earned_monthly: _money("Work income", "work income", 20000, critical=True),
    N.work_study_monthly: _money("Work-study", "work-study pay", 5000),
    N.gig_monthly: _money("Self-employment", "self-employment income", 20000),
    N.ta_ra: _bool("TA or RA job", "TA or RA job"),
    N.unearned_monthly: _money("Other income", "other income", 20000),
    N.other_cash_monthly: _money("Cash from family or friends", "cash from family or friends", 10000, critical=True),
    N.dependent_care_monthly: _money("Child or dependent care", "child or dependent care", 5000),
    N.rent_share: _money("Rent share", "rent share", 10000, critical=True),
    N.rent_paid_by_others_to_landlord: _money("Rent paid by someone else", "rent paid by someone else", 10000,
                                              critical=True),
    N.heat_cool: _bool("Heating or cooling bill", "heating or cooling bill"),
    N.other_utils: _enum("Other utility bills", "other utility bills", ["none", "phone_only", "two_plus"]),
    N.cash_on_hand: _money("Money on hand now", "money on hand", 100000, periodic=False),
    N.volunteered_status: _enum("Status (routing only, never stored)", "status", STATUS_CHOICES),
    N.elderly_or_disabled: _bool("Disability benefits or 60+ (routing only, never stored)",
                                 "disability benefits or age 60+"),
    N.already_receiving: _bool("Already gets CalFresh", "already gets CalFresh"),
    N.applied_waiting_interview: _bool("Applied, waiting for the interview", "waiting for the interview"),
    N.previously_denied: _bool("Applied before", "applied before"),
    N.income_changing_soon: _bool("Income changing soon", "income changing soon"),
    N.roommates_count: _int("Number of roommates", "number of roommates", 0, 10),
}
del N


class MoneyBasis(Model):
    amount: Decimal
    period: Period
    hours_per_week: Decimal | None = None


class Slot(Model):
    value: str | None = None  # canonical encoding (see the module docstring)
    display: str | None = None  # console text, e.g. "$1,169/mo ($18/h × 15 h/wk)"
    state: SlotState = SlotState.missing
    heard: str | None = Field(default=None, max_length=80)  # exact redacted student words
    heard_en: str | None = Field(default=None, max_length=120)  # English gloss of a Spanish quote
    confirmed: bool = False  # explicitly confirmed (a confirm question, or a coordinator confirm)
    changed_from: str | None = None  # previous canonical value after a correction or an edit
    turn: int | None = None
    source: SlotSource | None = None
    basis: MoneyBasis | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------------------------- codecs

CENT = Decimal("0.01")
_TRUE = "true"
_FALSE = "false"


def _spec(name: SlotName | str) -> tuple[SlotName, SlotSpec]:
    slot = SlotName(name)
    return slot, SLOT_SPECS[slot]


def _check_range(slot: SlotName, spec: SlotSpec, number: Decimal) -> None:
    if spec.min is not None and number < spec.min:
        raise ValueError(f"{slot.value}: {number} is below {spec.min}")
    if spec.max is not None and number > spec.max:
        raise ValueError(f"{slot.value}: {number} is above {spec.max}")


def _to_decimal(slot: SlotName, value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{slot.value}: money must be Decimal, int or a numeric string, not {type(value).__name__}")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{slot.value}: {value!r} is not a number") from exc
    else:
        raise TypeError(f"{slot.value}: unsupported value type {type(value).__name__}")
    if not number.is_finite():
        raise ValueError(f"{slot.value}: {value!r} is not a finite number")
    return number


def encode_value(name: SlotName | str, value: bool | int | Decimal | str) -> str:
    """Canonical string for a slot value. Raises ValueError (bad value, out of the plausible range) or TypeError
    (a float, or a type the slot does not take)."""
    slot, spec = _spec(name)
    if spec.type == "bool":
        if isinstance(value, bool):
            return _TRUE if value else _FALSE
        if isinstance(value, str) and value.strip().lower() in (_TRUE, _FALSE):
            return value.strip().lower()
        raise ValueError(f"{slot.value}: {value!r} is not a bool")
    if spec.type == "int":
        if isinstance(value, bool) or isinstance(value, float):
            raise TypeError(f"{slot.value}: {type(value).__name__} is not an int")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
            number = int(value.strip())
        elif isinstance(value, Decimal) and value == value.to_integral_value():
            number = int(value)
        else:
            raise ValueError(f"{slot.value}: {value!r} is not a whole number")
        _check_range(slot, spec, Decimal(number))
        return str(number)
    if spec.type == "money":
        number = _to_decimal(slot, value).quantize(CENT, rounding=ROUND_HALF_UP)
        _check_range(slot, spec, number)
        return f"{number:.2f}"
    # enum
    if not isinstance(value, str) or value not in (spec.choices or []):
        raise ValueError(f"{slot.value}: {value!r} is not one of {spec.choices}")
    return value


def decode_value(name: SlotName | str, raw: str) -> bool | int | Decimal | str:
    """Python value of a canonical string (no range check: stored values are read as they are)."""
    slot, spec = _spec(name)
    if not isinstance(raw, str):
        raise TypeError(f"{slot.value}: canonical values are strings")
    if spec.type == "bool":
        if raw == _TRUE:
            return True
        if raw == _FALSE:
            return False
        raise ValueError(f"{slot.value}: {raw!r} is not 'true' or 'false'")
    if spec.type == "int":
        if not raw.lstrip("-").isdigit():
            raise ValueError(f"{slot.value}: {raw!r} is not a whole number")
        return int(raw)
    if spec.type == "money":
        return _to_decimal(slot, raw)
    if raw not in (spec.choices or []):
        raise ValueError(f"{slot.value}: {raw!r} is not one of {spec.choices}")
    return raw


ENUM_DISPLAY: dict[SlotName, dict[str, str]] = {
    SlotName.level: {"undergrad": "Undergrad", "grad": "Grad student", "not_degree": "Not in a degree program",
                     "not_sfsu": "Not at SF State"},
    SlotName.household_food: {"alone": "Lives alone", "separate": "Separately", "shared": "Together"},
    SlotName.other_utils: {"none": "None", "phone_only": "Phone only", "two_plus": "Two or more"},
}

_PERIOD_TEXT = {"week": "/wk", "biweek": " every 2 weeks", "semimonth": " twice a month", "month": "/mo",
                "year": "/yr", "once": " once"}


def money_text(amount: Decimal | int, *, cents: bool = False) -> str:
    """"$1,169" (whole dollars, half-up) or, with cents=True and a fraction, "$18.50"."""
    number = amount if isinstance(amount, Decimal) else Decimal(amount)
    if cents and number != number.to_integral_value():
        return f"${number.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"
    return f"${number.quantize(Decimal(1), rounding=ROUND_HALF_UP):,.0f}"


def _number_text(number: Decimal) -> str:
    return f"{number.normalize():f}" if number != number.to_integral_value() else f"{int(number)}"


def format_display(name: SlotName | str, raw: str | None, basis: MoneyBasis | None = None) -> str:
    """Console text for a slot value: "Yes", "20", "$1,100/mo", "$1,169/mo ($18/h × 15 h/wk)", "Separately"."""
    slot, spec = _spec(name)
    if raw is None:
        return "—"
    value = decode_value(slot, raw)
    if spec.type == "bool":
        return "Yes" if value else "No"
    if spec.type == "int":
        return str(value)
    if spec.type == "money":
        assert isinstance(value, Decimal)
        text = money_text(value) + ("/mo" if spec.periodic else "")
        if basis is not None and spec.periodic and basis.period != "month":
            if basis.period == "hour":
                hours = _number_text(basis.hours_per_week) if basis.hours_per_week is not None else "?"
                text += f" ({money_text(basis.amount, cents=True)}/h × {hours} h/wk)"
            else:
                text += f" ({money_text(basis.amount, cents=True)}{_PERIOD_TEXT[basis.period]})"
        return text
    return ENUM_DISPLAY.get(slot, {}).get(str(value), str(value))

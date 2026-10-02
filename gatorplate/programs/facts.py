"""ProgramFacts: the programs engine's input, built from a Case (docs/SPEC.md §5.10 "Facts").

The fields are exactly the `facts` keys of data/golden/programs_golden.json. Slots go through the contracts codecs;
the CalFresh result is the one the rules wrote on the case (`reason_code` -> `route`, `estimate_monthly` ->
`calfresh_monthly`). Nothing here writes to the case.

Defaults for slots the call never set (the golden file's `defaults`): dorm_on_campus, homeless and roommates false;
roommates_count 2 when roommates is true and the count was not said (else 0); children_count 0; heat_cool false;
other_utils "none"; work-study and other income 0. An income the call never reached stays null, and so do
magi_monthly and earned_annual. half_time is the slot when the call set it, else null.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictBool, StrictInt

from gatorplate.contracts.case import Case
from gatorplate.contracts.slots import SlotName, decode_value


def _money(value: object) -> Decimal | None:
    """Money facts are exact decimals: Decimal, int or a numeric string. Never a float."""
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("money facts are never floats")
    if isinstance(value, int | str):
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError(f"{value!r} is not finite")
        return number
    raise ValueError(f"unsupported money value {value!r}")


Money = Annotated[Decimal | None, BeforeValidator(_money)]


class ProgramFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: str | None
    age: StrictInt | None
    level: str | None
    half_time: StrictBool | None
    lives_with_parent: StrictBool | None
    roommates: StrictBool
    roommates_count: StrictInt
    dorm_on_campus: StrictBool
    homeless: StrictBool
    household_size: StrictInt
    children_count: StrictInt
    youngest_child_age: StrictInt | None
    earned_monthly: Money
    work_study_monthly: Money
    unearned_monthly: Money
    heat_cool: StrictBool
    other_utils: str
    calfresh_monthly: StrictInt | None
    magi_monthly: Money
    earned_annual: Money
    bill_split: StrictInt
    people_in_home: StrictInt


FACT_NAMES: frozenset[str] = frozenset(ProgramFacts.model_fields)


def _slot(case: Case, name: SlotName) -> bool | int | Decimal | str | None:
    slot = case.slots.get(name)
    if slot is None or slot.value is None:
        return None
    return decode_value(name, slot.value)


def _bool(case: Case, name: SlotName, default: bool | None) -> bool | None:
    value = _slot(case, name)
    return value if isinstance(value, bool) else default


def _int(case: Case, name: SlotName, default: int | None) -> int | None:
    value = _slot(case, name)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _dec(case: Case, name: SlotName, default: Decimal | None) -> Decimal | None:
    value = _slot(case, name)
    return value if isinstance(value, Decimal) else default


def _str(case: Case, name: SlotName, default: str | None) -> str | None:
    value = _slot(case, name)
    return value if isinstance(value, str) else default


def facts_from_case(case: Case, *, horizon_months: int, assumed_roommates: int) -> ProgramFacts:
    """ProgramFacts of one case. `horizon_months` and `assumed_roommates` come from the programs table."""
    zero = Decimal(0)
    roommates = bool(_bool(case, SlotName.roommates, False))
    said_count = _int(case, SlotName.roommates_count, None)
    roommates_count = (said_count if said_count is not None else assumed_roommates) if roommates else 0
    children = _int(case, SlotName.children_count, 0) or 0
    spouse = 1 if _bool(case, SlotName.spouse, False) else 0
    household_size = 1 + spouse + children
    earned = _dec(case, SlotName.earned_monthly, None)
    work_study = _dec(case, SlotName.work_study_monthly, zero)
    unearned = _dec(case, SlotName.unearned_monthly, zero)
    magi = None if earned is None else earned + (work_study or zero) + (unearned or zero)
    earned_annual = None if earned is None else horizon_months * (earned + (work_study or zero))
    return ProgramFacts(
        route=case.reason_code,
        age=_int(case, SlotName.age, None),
        level=_str(case, SlotName.level, None),
        half_time=_bool(case, SlotName.half_time, None),
        lives_with_parent=_bool(case, SlotName.lives_with_parent, None),
        roommates=roommates,
        roommates_count=roommates_count,
        dorm_on_campus=bool(_bool(case, SlotName.dorm_on_campus, False)),
        homeless=bool(_bool(case, SlotName.homeless, False)),
        household_size=household_size,
        children_count=children,
        youngest_child_age=_int(case, SlotName.youngest_child_age, None) if children else None,
        earned_monthly=earned,
        work_study_monthly=work_study,
        unearned_monthly=unearned,
        heat_cool=bool(_bool(case, SlotName.heat_cool, False)),
        other_utils=_str(case, SlotName.other_utils, None) or "none",
        calfresh_monthly=case.estimate_monthly,
        magi_monthly=magi,
        earned_annual=earned_annual,
        bill_split=1 + roommates_count if roommates else 1,
        people_in_home=household_size + roommates_count,
    )

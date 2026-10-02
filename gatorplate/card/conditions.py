"""The `when` conditions of data/content/card.{en,es}.json (its format.when and when_keys sections).

A condition object is an AND of its keys; {} is always true; "not" holds when none of its sub-conditions holds.
Values are the slots' canonical strings ("true", "900.00", "separate"); see gatorplate.contracts.slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

_FALSY = {"", "false", "none", "0"}


def truthy(value: str | None) -> bool:
    """A slot value counts as positive when it is > 0, true, or a choice other than 'none'."""
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in _FALSY:
        return False
    try:
        return Decimal(text) > 0
    except InvalidOperation:
        return True


def zeroish(value: str | None) -> bool:
    """A slot value counts as zero when it is present and 0, false or 'none'."""
    return value is not None and not truthy(value)


@dataclass(frozen=True)
class CardContext:
    """Everything the conditions read about one case (built by the card builder from the Case)."""

    tier: str | None = None
    reason: str | None = None
    expedited: str | None = None
    slots: dict[str, str] = field(default_factory=dict)  # canonical values, derived half_time included
    answered: frozenset[str] = frozenset()  # slots the student gave (not a default, not assumed)
    flags: frozenset[str] = frozenset()  # policy flags and yellow-line codes
    facts: frozenset[str] = frozenset()  # card facts that exist: first_month, case_code
    irt_applies: bool | None = None  # None when there is no estimate: neither IRT line shows
    at_max: bool | None = None


def _names(value: Any) -> list[str]:
    return list(value) if isinstance(value, list) else [value]


def when_true(cond: dict[str, Any], ctx: CardContext) -> bool:
    for key, want in cond.items():
        if not _holds(key, want, ctx):
            return False
    return True


def _holds(key: str, want: Any, ctx: CardContext) -> bool:
    slots = ctx.slots
    if key == "tier":
        return ctx.tier in want
    if key == "reason":
        return ctx.reason in want
    if key == "expedited":
        return ctx.expedited in want
    if key == "level":
        return slots.get("level") in want
    if key == "homeless":
        return truthy(slots.get("homeless")) is bool(want)
    if key == "irt_applies":
        return ctx.irt_applies is want
    if key == "at_max":
        return ctx.at_max is want
    if key == "flag":
        return bool(set(want) & ctx.flags)
    if key == "has":
        return all(slots.get(s) is not None or s in ctx.facts for s in _names(want))
    if key == "answered":
        return all(s in ctx.answered for s in _names(want))
    if key == "positive":
        return all(truthy(slots.get(s)) for s in _names(want))
    if key == "zero":
        return all(zeroish(slots.get(s)) for s in _names(want))
    if key == "slot":
        return all(str(slots.get(s)).lower() in [str(v).lower() for v in values] for s, values in want.items())
    if key == "not":
        return not any(when_true(sub, ctx) for sub in _names(want))
    if key == "lang":
        return True  # ignored by definition (card.*.json when_keys)
    raise ValueError(f"unknown condition key {key!r}")

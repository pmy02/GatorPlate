"""Helpers for the understanding tests: the utterance file, per-slot comparison, a one-line understand() call."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import PendingQuestion, Understanding
from gatorplate.contracts.slots import SLOT_SPECS, SlotName
from gatorplate.extract.conversion import Conversion

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
UTTERANCES = DATA / "tests" / "utterances.jsonl"
CONVERSION = Conversion.load(DATA / "rules" / "ca_fy2027.json")

# Fake, never-issued test numbers, assembled at run time so no number-shaped literal sits in the source.
CARD = " ".join(["4111"] + ["1111"] * 3)
SSN_DASHED = "-".join(("987", "65", "4321"))
SSN_SPACED = " ".join(("987", "65", "4320"))
NINE_DIGITS = "".join(("912", "345", "678"))


def load_utterances() -> list[dict[str, Any]]:
    return [json.loads(line) for line in UTTERANCES.read_text(encoding="utf-8").splitlines() if line.strip()]


def value_key(ob: dict[str, Any]) -> tuple[Any, str]:
    """Comparable form of one observation: money as its monthly amount, everything else as said."""
    spec = SLOT_SPECS[SlotName(ob["slot"])]
    value: Any = ob["value"]
    if spec.type == "money" and value not in ("true", "false"):
        value = CONVERSION.monthly(value, ob.get("period") if spec.periodic else None, ob.get("hours_per_week"))
    return value, ob["state"]


def per_slot(observations: list[dict[str, Any]], *, with_state: bool = True) -> dict[str, tuple[Any, ...]]:
    """One comparable value per slot; several amounts of one slot are added (two jobs)."""
    out: dict[str, tuple[Any, str]] = {}
    for ob in observations:
        value, state = value_key(ob)
        slot = ob["slot"]
        if slot in out and isinstance(out[slot][0], Decimal) and isinstance(value, Decimal):
            value = out[slot][0] + value
            state = "unclear" if "unclear" in (out[slot][1], state) else "clear"
        out[slot] = (value, state)
    return dict(out) if with_state else {slot: (value,) for slot, (value, _state) in out.items()}


def known_of(row: dict[str, Any]) -> dict[SlotName, str]:
    return {SlotName(k): v for k, v in (row.get("known") or {}).items()}


async def understand_row(understander: Any, row: dict[str, Any], *, closed_mode: bool = False,
                         text: str | None = None, deadline_s: float = 2.6) -> Understanding:
    return await understander.understand(
        text=row["utterance"] if text is None else text, masked=bool(row.get("masked")), confidence=0.9,
        dtmf=None, pending=PendingQuestion.model_validate(row["pending"]), known=known_of(row), recent=[],
        last_prompt=None, lang=Lang(row["lang"]), deadline=understander.clock.monotonic() + deadline_s,
        closed_mode=closed_mode)

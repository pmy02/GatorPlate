"""Question metadata read from the sentence bank (data/content/sentences.en.json): what a pending question expects.

The parser needs a question's slots, its keypad entries (single keys '1'-'3', never multi-key amounts), its tap
choices, the fixed band edges of a band choice without {a, b} vars, and what a yes or a no means when the slot is not
a plain boolean (`yes` / `no` entries). The closed form's `expect` overrides the main one when the question was asked
closed. Only metadata is read here; the wording belongs to the dialogue module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_BANK = Path(__file__).resolve().parent.parent.parent / "data" / "content" / "sentences.en.json"


@dataclass(frozen=True)
class QuestionForm:
    expect: str = "open"
    slots: tuple[str, ...] = ()
    keypad: Any = None  # None | "yes_no" | {"1": entry, ...}
    choices: tuple[dict[str, Any], ...] = ()
    band_edges: tuple[Decimal, Decimal] | None = None
    yes: dict[str, Any] = field(default_factory=dict)
    no: dict[str, Any] = field(default_factory=dict)


def _edges(raw: Any) -> tuple[Decimal, Decimal] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Decimal(str(raw["a"])), Decimal(str(raw["b"]))
    except (KeyError, InvalidOperation):
        return None


def _form(expect: dict[str, Any] | None) -> QuestionForm | None:
    if not isinstance(expect, dict):
        return None
    return QuestionForm(
        expect=str(expect.get("expect") or "open"),
        slots=tuple(expect.get("slots") or ()),
        keypad=expect.get("keypad"),
        choices=tuple(c for c in (expect.get("choices") or ()) if isinstance(c, dict)),
        band_edges=_edges(expect.get("band_edges")),
        yes=dict(expect.get("yes") or {}),
        no=dict(expect.get("no") or {}),
    )


class Bank:
    def __init__(self, messages: dict[str, Any]) -> None:
        self._messages = messages

    @classmethod
    def load(cls, path: Path | None = None) -> Bank:
        return _load(str(path or DEFAULT_BANK))

    def form(self, key: str | None, *, closed: bool = False) -> QuestionForm | None:
        """The pending question's metadata (closed form first when it was asked closed), or None if unknown."""
        msg = self._messages.get(key or "")
        if not isinstance(msg, dict):
            return None
        if closed:
            closed_part = msg.get("closed")
            if isinstance(closed_part, dict) and isinstance(closed_part.get("expect"), dict):
                return _form(closed_part["expect"])
        return _form(msg.get("expect"))


@lru_cache(maxsize=4)
def _load(path: str) -> Bank:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        messages = data.get("messages") if isinstance(data, dict) else None
    except (OSError, ValueError):
        messages = None
    return Bank(messages if isinstance(messages, dict) else {})

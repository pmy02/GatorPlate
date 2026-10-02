"""Yellow lines the dialogue creates (docs/SPEC.md §3.4, §3.7; docs/UI_SPEC.md A3.5): `unclear.<slot>`,
`conflict.<slot>`, `student_question` and `incomplete`. Wording comes from gatorplate.contracts.console_text only.

Lines are idempotent by code (a second `incomplete` does nothing), except `student_question`, which keeps one line per
question. Each open line blocks "Mark reviewed" until a coordinator confirms or edits it.
"""

from __future__ import annotations

from datetime import datetime

from gatorplate.contracts import console_text
from gatorplate.contracts.case import Case, YellowEffect, YellowLine
from gatorplate.contracts.common import YellowKind
from gatorplate.contracts.slots import SLOT_SPECS, SlotName

PARAPHRASE_MAX = 120


def _next_id(case: Case) -> str:
    used = {line.id for line in case.yellow_lines}
    n = len(case.yellow_lines) + 1
    while f"y{n}" in used:
        n += 1
    return f"y{n}"


def _has(case: Case, code: str) -> bool:
    return any(line.code == code for line in case.yellow_lines)


def add(case: Case, *, kind: YellowKind, code: str, reason: str, now: datetime, slot: SlotName | None = None,
        heard: str | None = None, assumed: str | None = None, effect: YellowEffect | None = None,
        unique: bool = True) -> YellowLine | None:
    """Append one yellow line; with unique=True a line with the same code is never added twice."""
    if unique and _has(case, code):
        return None
    line = YellowLine(id=_next_id(case), slot=slot, kind=kind, code=code, reason=reason[:240],
                      heard=heard[:80] if heard else None, assumed=assumed, effect=effect, created_at=now)
    case.yellow_lines.append(line)
    return line


def incomplete(case: Case, now: datetime) -> YellowLine | None:
    """The call ended before the result."""
    return add(case, kind=YellowKind.incomplete, code="incomplete", reason=console_text.INCOMPLETE, now=now)


def unclear(case: Case, slot: SlotName, value_display: str, now: datetime, *,
            heard: str | None = None) -> YellowLine | None:
    """Still unclear after the one explicit confirm (or the one closed re-ask): the conservative value is used."""
    label = SLOT_SPECS[slot].label
    return add(case, kind=YellowKind.unclear, code=f"unclear.{slot.value}", slot=slot, now=now, heard=heard,
               reason=console_text.unclear(label, value_display), assumed=value_display)


def conflict(case: Case, slot: SlotName, a: str, b: str, now: datetime, *,
             heard: str | None = None) -> YellowLine | None:
    """The words and the number disagree and the confirm did not settle it."""
    label = SLOT_SPECS[slot].label
    return add(case, kind=YellowKind.conflict, code=f"conflict.{slot.value}", slot=slot, now=now, heard=heard,
               reason=console_text.conflict(label, a, b))


def student_question(case: Case, paraphrase: str, now: datetime) -> YellowLine | None:
    """A side question for the coordinator (a paraphrase of at most 120 characters, never the student's words)."""
    text = " ".join(paraphrase.split())[:PARAPHRASE_MAX]
    return add(case, kind=YellowKind.student_question, code="student_question", now=now,
               reason=console_text.student_question(text), unique=False)

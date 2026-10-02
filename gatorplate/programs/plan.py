"""The plan: stages and order are code (docs/SPEC.md §5.10 "Plan and dates").

Stages in the table's order (today, after approval, tax time). "Today" always starts with CalFresh. Inside a stage the
plan lines (likely, maybe, check, coverage) come first: by apply-by date (earliest first, none last), then value
(largest first; no value counts as 0; a range line uses its high end), then the program's priority. Zero and note
lines follow in their stage by priority (shown muted, without a link or a button).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from gatorplate.contracts.programs import ProgramStage, ProgramStatus

KEY_LINE = "calfresh"


@dataclass
class Draft:
    """One line before it becomes a ProgramLine (the engine fills it; the plan only orders it)."""

    id: str
    status: ProgramStatus
    stage: ProgramStage
    priority: int
    value_yearly: int | None = None
    display_yearly: int | None = None
    counted: bool = False
    range_lo: int | None = None
    range_hi: int | None = None
    apply_by: date | None = None
    vars: dict[str, str] = field(default_factory=dict)
    note_keys: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    applied: bool = False
    variant: str | None = None


def ordered(lines: Sequence[Draft], *, stages: Sequence[str], include: Sequence[str]) -> list[Draft]:
    stage_at = {s: i for i, s in enumerate(stages)}

    def key(line: Draft) -> tuple:
        planned = line.status in include
        size = line.range_hi if line.range_hi is not None else (line.value_yearly or 0)
        return (stage_at[line.stage], line.id != KEY_LINE, not planned, line.apply_by is None,
                line.apply_by or date.max, -size, line.priority)

    return sorted(lines, key=key)


def plan_ids(lines: Sequence[Draft], *, stages: Sequence[str], include: Sequence[str]) -> dict[str, list[str]]:
    """Per stage, the ids of the plan lines in order (the golden cases' `plan`)."""
    return {s: [line.id for line in lines if line.stage == s and line.status in include] for s in stages}

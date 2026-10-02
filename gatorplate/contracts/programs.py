"""Other programs on the student card: "money you may be missing" (docs/SPEC.md §5.10 and §6.6).

Code computes every value from data/rules/programs_2026.json; the language model never produces, estimates or ranks a
program amount. Import order without cycles: common (Model, Lang, CardRow) -> case (ProgramAnswer, ProgramProgress)
-> rules_io (SourceRef) -> programs -> card_api, console_api -> ports.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from gatorplate.contracts.case import ProgramAnswer, ProgramProgress
from gatorplate.contracts.common import CardRow, Lang, Model
from gatorplate.contracts.rules_io import SourceRef

__all__ = [
    "ProgramAnswer",
    "ProgramProgress",
    "ProgramStatus",
    "ProgramMode",
    "ProgramStage",
    "ProgramLine",
    "ProgramsResult",
    "ProgramsMeta",
    "UnlockedChoice",
    "UnlockedQuestion",
    "UnlockedProgram",
    "UnlockedView",
    "ProgramAnswersRequest",
    "ProgramProgressRequest",
]

ProgramStatus = Literal["likely", "maybe", "check", "coverage", "zero", "note"]  # "hidden" lines are never sent
ProgramMode = Literal["full", "list_only"]  # mode "none" is not a result: evaluate() and view() return None
ProgramStage = Literal["today", "after_approval", "tax_time"]


class ProgramLine(Model):
    """Engine output, language-free (console section 6b and the view builder)."""

    id: str  # "calfresh" (the key line, always first in full mode) or a program id
    status: ProgramStatus
    # Floored to the dollar; 0 for zero lines and for coverage; None when the line has no value (note, list_only,
    # an expired row, a check line with a range). data/golden/programs_golden.json is the truth.
    value_yearly: int | None
    display_yearly: int | None  # floored to $10 (null exactly when value_yearly is)
    counted: bool  # True only for likely lines (the calfresh line in full mode is likely)
    range_lo: int | None = None  # check lines with a range
    range_hi: int | None = None
    stage: ProgramStage
    order: int  # plan position; the order is code
    apply_by: date | None = None  # Pacific date (Clipper START: 30 days before the next break)
    vars: dict[str, str] = Field(default_factory=dict)  # raw placeholder values; the view formats them per language
    note_keys: list[str] = Field(default_factory=list)  # programs.*.json keys ("care.roommate_applies")
    basis: list[str] = Field(default_factory=list)  # English trace lines with numbers (console "How" column)
    source_ids: list[str] = Field(default_factory=list)  # ids in the table's sources (each has a date)
    applied: bool = False  # from Case.program_progress


class ProgramsResult(Model):
    table_id: str
    checked: date
    mode: ProgramMode
    calfresh_yearly: int | None  # 12 x the monthly estimate (full mode)
    found_yearly: int | None  # sum of counted value_yearly (full mode)
    found_display: int | None  # sum of counted display_yearly: the headline (full mode)
    share_display: int | None  # found_display floored to $100; None when 0 or not full mode
    claimed_display: int  # sum of counted display_yearly whose line is applied (0 in list_only)
    lines: list[ProgramLine]  # in plan order; hidden programs absent
    open_questions: list[str]  # askable now, highest spread first (empty in list_only)
    next_question: str | None
    question_spreads: dict[str, int]  # spread of found_yearly per open question (the ask rule)
    console_notes: list[str]  # gray notes only ("care.utility_conflict"); never a yellow line


class ProgramsMeta(Model):
    """ProgramsPort.meta() -> ConsoleMeta.programs."""

    table_id: str
    label: str
    checked: date
    effective_from: date
    effective_to: date
    programs: list[str]  # program ids in priority order
    names: dict[str, str]  # English program names ("calfresh" too)
    console_texts: dict[str, str]  # English gray-note texts
    questions: list[str]  # question ids
    sources: list[SourceRef]  # the table's sources (title, date, url, grade)


class UnlockedChoice(Model):
    value: str
    label: str


class UnlockedQuestion(Model):
    id: str
    text: str
    choices: list[UnlockedChoice]
    index: int  # "Question {index} of {total}"; index = answered + 1
    total: int  # card questions already answered (any source) + len(open_questions)


class UnlockedProgram(Model):
    id: str
    name: str
    status: ProgramStatus
    status_label: str
    value_text: str | None
    counted: bool
    line: str
    notes: list[str]
    stage: ProgramStage
    stage_label: str
    apply_by_text: str | None
    apply_url: str  # official page, new tab; CalFresh's is "#today_action" (in-page link)
    apply_label: str
    applied: bool
    can_mark_applied: bool  # True for likely, maybe, check and coverage lines in full mode
    prefill: list[CardRow]  # "Your answers for this form"; never an SSN or an immigration status
    source_text: str  # "Source: {title}, {date}"


class UnlockedView(Model):
    """Everything the card widget shows, in one language; every string passed the output guard."""

    mode: ProgramMode
    title: str
    total_text: str | None  # "About $4,220 a year" (full mode)
    found_display: int | None
    claimed_display: int
    calfresh_display: int | None
    segments: list[tuple[str, int]]  # (line id, display_yearly) of the counted lines in plan order: the bar
    question: UnlockedQuestion | None  # one at a time; None when nothing is left to ask
    chips: list[str]
    programs: list[UnlockedProgram]  # plan order
    share_text: str | None  # full mode with found_display > 0 only; never the card URL, token, code or an answer
    footnote: str
    # The control labels of docs/UI_SPEC.md A4.7 in this language; every known placeholder filled except
    # ui.question_count's {i} / {n}.
    labels: dict[str, str]
    lang: Lang


class ProgramAnswersRequest(Model):
    answers: dict[str, str] = Field(min_length=1, max_length=3)  # question id -> choice id


class ProgramProgressRequest(Model):
    program: str  # "calfresh" or a program id shown on the card
    applied: bool

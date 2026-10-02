"""Shared base model and enums of the internal contracts (docs/SPEC.md §8, docs/UI_SPEC.md A8).

Internal models forbid unknown fields. Money is Decimal in code and a string in JSON; whole-dollar results are int.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base of every internal contract model: unknown fields are an error."""

    model_config = ConfigDict(extra="forbid")


class Lang(StrEnum):
    en = "en"
    es = "es"


class Channel(StrEnum):
    phone = "phone"
    web = "web"


class Tier(StrEnum):
    likely = "likely"
    coordinator = "coordinator"
    other_help = "other_help"


class CaseStatus(StrEnum):
    """Coordinator status of a case (docs/UI_SPEC.md A3.7). "Live", "Ended early" and "Sample" are badges."""

    new = "new"
    reviewed = "reviewed"
    applied = "applied"
    interview_scheduled = "interview_scheduled"
    approved = "approved"
    follow_up = "follow_up"


class Phase(StrEnum):
    """Conversation phases 0-10 plus end (docs/SPEC.md §3.2)."""

    consent = "consent"
    student = "student"
    age_home = "age_home"
    household = "household"
    income = "income"
    housing = "housing"
    flip = "flip"
    result = "result"
    expedited = "expedited"
    card = "card"
    close = "close"
    end = "end"


class SlotState(StrEnum):
    clear = "clear"
    assumed = "assumed"
    unclear = "unclear"
    missing = "missing"


class SlotSource(StrEnum):
    """Where a slot value came from (docs/UI_SPEC.md A3.5 source icons)."""

    llm = "llm"
    parser = "parser"
    keypad = "keypad"
    coordinator = "coordinator"
    default = "default"
    seed = "seed"


class YellowKind(StrEnum):
    unclear = "unclear"
    conflict = "conflict"
    policy = "policy"
    assumed = "assumed"
    student_question = "student_question"
    incomplete = "incomplete"


class YellowResolution(StrEnum):
    """A coordinator resolves a yellow line by confirming it or by editing the value; nothing else."""

    confirm = "confirm"
    edit = "edit"


class CardRow(Model):
    """One row of a form helper table: the official screen name, its question and the student's answer.

    Defined here (and re-exported by card_api) so that programs.py can use it without an import cycle."""

    screen: str
    question: str
    answer: str


Period = Literal["hour", "week", "biweek", "semimonth", "month", "year", "once"]
ExpeditedOutlook = Literal["yes", "maybe", "no"]
EffectKind = Literal["amount", "tier", "expedited"]
RouteOverride = Literal["other_help.status", "coordinator.status_complex", "coordinator.elderly_disabled"]

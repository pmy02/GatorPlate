"""The student card (docs/SPEC.md §6, docs/UI_SPEC.md A4 and A8.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from gatorplate.contracts.case import FirstMonth
from gatorplate.contracts.common import CardRow, CaseStatus, ExpeditedOutlook, Lang, Model, Tier
from gatorplate.contracts.programs import UnlockedView
from gatorplate.contracts.rules_io import SourceRef

__all__ = ["CardRow", "CardBlock", "CardStatus", "CardView", "BLOCK_ORDER"]

# The one block order for every tier and route (docs/SPEC.md §6.2); absent blocks are skipped.
BLOCK_ORDER: list[str] = [
    "today_action", "expedited", "why", "answer_sheet", "documents", "interview", "after_approval", "food_today",
    "contact",
]


class CardBlock(Model):
    id: str  # one of BLOCK_ORDER (ids of data/content/card.*.json)
    title: str
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    rows: list[CardRow] = Field(default_factory=list)
    tone: Literal["default", "accent", "warning", "muted"] = "default"
    collapsed: bool = False


class CardStatus(Model):
    status: CaseStatus
    reviewed: bool
    reviewed_at: datetime | None
    tier: Tier | None
    estimate_monthly: int | None


class CardView(Model):
    lang: Lang
    code: str
    tier: Tier | None
    reason_code: str | None
    headline: str
    subhead: str
    estimate_monthly: int | None
    estimate_is_floor: bool
    expedited: ExpeditedOutlook | None
    first_month: FirstMonth | None
    blocks: list[CardBlock]
    footer: list[str]
    sources: list[SourceRef]
    rules_label: str
    status: CardStatus
    generated_at: datetime
    expires_at: datetime
    reminders_url: str | None
    delete_url: str
    # The fixed part under the hero (not a CardBlock); null in mode none and with GP_PROGRAMS=0.
    unlocked: UnlockedView | None = None

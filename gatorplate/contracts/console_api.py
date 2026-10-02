"""Coordinator console models (docs/UI_SPEC.md A3 and A8)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import (
    CaseStatus,
    Channel,
    ExpeditedOutlook,
    Lang,
    Model,
    Phase,
    Tier,
    YellowResolution,
)
from gatorplate.contracts.programs import ProgramsMeta, ProgramsResult
from gatorplate.contracts.rules_io import RulesMeta
from gatorplate.contracts.slots import SlotName, SlotSpec


class CaseSummary(Model):
    id: str
    code: str
    version: int
    created_at: datetime
    updated_at: datetime
    label: str  # = code; never a name
    summary: str  # one-line summary
    lang: Lang
    channel: Channel
    live: bool
    test: bool
    seeded: bool
    phase: Phase | None
    status: CaseStatus
    ended_early: bool
    tier: Tier | None
    reason_code: str | None
    estimate_monthly: int | None
    estimate_is_floor: bool
    expedited_possible: ExpeditedOutlook | None
    yellow_open: int
    yellow_total: int
    asked_count: int
    skipped_count: int
    next_deadline: date | None
    # "Found about $4,220/yr": ProgramsResult.found_display for a full-mode case, else null; set through the
    # programs port (summary.py leaves it null).
    found_display: int | None = None


class LiveTurn(Model):
    """One live transcript line (memory only)."""

    case_id: str
    turn: int
    who: Literal["student", "assistant"]
    text: str  # already redacted by the brain
    lang: Lang
    at: datetime


class LiveView(Model):
    """GET /api/cases/{id}/live: the lines so far (memory only)."""

    case_id: str
    lines: list[LiveTurn]
    now_asking: str | None = None  # sentence key
    now_asking_text: str | None = None  # English text of the question
    asked_reason: str | None = None  # flip reason text, when the question is a flip


CaseEventType = Literal["case.created", "case.updated", "case.deleted", "demo.reset", "resync", "live.turn",
                        "live.ended"]


class CaseEvent(Model):
    seq: int
    type: CaseEventType
    case_id: str | None = None
    summary: CaseSummary | None = None
    changed_slots: list[SlotName] = Field(default_factory=list)
    now_asking: str | None = None  # sentence key
    now_asking_text: str | None = None
    asked_reason: str | None = None
    line: LiveTurn | None = None  # only for live.turn
    changed_programs: bool = False  # case.updated after a card answer or an "I applied" mark
    at: datetime


class CaseListResponse(Model):
    items: list[CaseSummary]
    seq: int
    server_time: datetime


class CaseDetail(Model):
    case: Case
    summary: CaseSummary
    card_url: str | None
    qr_svg_url: str | None
    short_code: str | None
    can_review: bool
    allowed_status: list[CaseStatus]
    rules: RulesMeta
    programs: ProgramsResult | None = None  # null = mode none or GP_PROGRAMS=0


class ConsoleMeta(Model):
    rules: RulesMeta
    rules_valid_today: bool
    slot_specs: dict[SlotName, SlotSpec]
    demo_mode: bool
    live_transcript: bool
    card_delivery: Literal["screen", "code"]
    app_version: str
    demo_phone_display: str | None
    programs: ProgramsMeta | None = None  # null with GP_PROGRAMS=0


class PublicInfo(Model):
    """GET /api/public/info (no auth): landing and talk page."""

    demo_phone_display: str | None
    rules_label: str
    effective_from: date


class YellowAction(Model):
    action: YellowResolution
    value: str | None = None
    note: str | None = Field(default=None, max_length=200)
    expected_version: int


class SlotEdit(Model):
    value: str
    note: str | None = Field(default=None, max_length=200)
    expected_version: int


class StatusChange(Model):
    status: CaseStatus
    expected_version: int


class TrackingPatch(Model):
    applied_at: date | None = None
    interview_at: datetime | None = None
    interview_missed: bool | None = None
    doc_request_at: date | None = None
    approved_at: date | None = None
    expected_version: int


class LoginRequest(Model):
    passcode: str


class CardLookup(Model):
    code: str = Field(pattern=r"^[0-9]{6}$")


class CardLookupResponse(Model):
    url: str


class DemoInject(Model):
    id: str  # a demo case id from data/demo_cases/ ("maria_g1", "sofia_g3", ...)


class DemoSeedResponse(Model):
    seeded: int
    replaced: int


class DemoResetResponse(Model):
    deleted: int
    kept: int

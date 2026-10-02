"""The case: everything GatorPlate keeps about one conversation (docs/SPEC.md §8.2, docs/UI_SPEC.md A8.1).

Never stored: names, phone numbers or anything derived from them, audio, full transcripts, a volunteered immigration
status, disability-benefit details (docs/SPEC.md §8.3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from gatorplate.contracts.common import (
    CaseStatus,
    Channel,
    EffectKind,
    ExpeditedOutlook,
    Lang,
    Model,
    Phase,
    RouteOverride,
    Tier,
    YellowKind,
    YellowResolution,
)
from gatorplate.contracts.slots import Slot, SlotName

CASE_CODE_PATTERN = r"^[A-Z0-9]{3}-[A-Z0-9]{3}$"


class YellowEffect(Model):
    kind: EffectKind
    delta_usd: int | None = None


class YellowLine(Model):
    id: str  # "y1", "y2", ... unique per case
    slot: SlotName | None = None
    kind: YellowKind
    code: str  # "coordinator.parent_household", "assumed.other_utils", "unclear.rent_share", ...
    reason: str = Field(max_length=240)  # English console text from contracts.console_text
    heard: str | None = Field(default=None, max_length=80)
    assumed: str | None = None  # display of the assumed value
    effect: YellowEffect | None = None
    created_at: datetime
    resolved: YellowResolution | None = None
    resolved_at: datetime | None = None
    resolved_note: str | None = Field(default=None, max_length=200)


class RuleStep(Model):
    step: str  # "gross_income_test", "shelter", ...
    result: str  # English with numbers ("Gross $900 ≤ $2,660 (1 person)")
    source: str | None = None  # source id from the rules table
    value: str | None = None


class AskedQuestion(Model):
    turn: int
    key: str  # sentence key
    slots: list[SlotName]
    kind: Literal["standard", "flip", "confirm", "band", "closed", "reprompt"]
    reason: str | None = None  # flips: "could change the estimate by $151: $155 or $306"
    delta_usd: int | None = None  # flips: the spread
    outcomes: list[str] = Field(default_factory=list)  # ["No → $306/mo", "Yes → $155/mo"]


class SkippedQuestion(Model):
    slot: SlotName
    reason: Literal["no_effect", "below_threshold", "max_questions", "hard_stop", "not_applicable"]
    detail: str | None = None  # "Not asked — heating or cooling bill, same estimate either way"
    values: list[int] = Field(default_factory=list)


class EstimateRange(Model):
    """docs/SPEC.md §5.6: exactly {lo, hi, settled}."""

    lo: int
    hi: int
    settled: bool


class TimelinePoint(Model):
    """One per turn that changed slots; drives the console's range bar and replay."""

    turn: int
    at: datetime
    slots: list[SlotName]
    lo: int | None = None
    hi: int | None = None


class FirstMonth(Model):
    apply_date: date  # the day the student would apply
    filed_on: date  # the day the county counts (weekday before 5 PM Pacific)
    amount: int  # 0 = below the table's proration minimum
    days_counted: int
    month_label: str  # English month name for the console; the card renders the month in its own language
    estimate: bool = True  # screens and the card always say "estimate"


class CardRef(Model):
    token: str
    short_code: str | None = None
    short_code_expires_at: datetime | None = None
    created_at: datetime
    expires_at: datetime


class Tracking(Model):
    applied_at: date | None = None
    filed_on: date | None = None  # computed from applied_at
    deadline_30d: date | None = None  # computed
    interview_at: datetime | None = None
    interview_missed: bool = False
    doc_request_at: date | None = None
    doc_due: date | None = None  # computed
    approved_at: date | None = None
    sar7_due: date | None = None  # computed
    recert_due: date | None = None  # computed


class Consent(Model):
    given: bool | None = None
    at: datetime | None = None
    disclosure_key: str | None = None


class PrivacyEvent(Model):
    """Content-free: only the kind and the time."""

    kind: Literal["ssn_blocked", "card_number_blocked"]
    at: datetime


class LanguageRequest(Model):
    asked: str  # two-letter code
    offered: Literal["web", "switched", "none"]


class ProgramAnswer(Model):
    """A card answer to one of the other-programs questions (docs/SPEC.md §6.6); re-exported by programs.py."""

    value: str  # one choice id of the question in the programs table
    at: datetime
    source: Literal["card", "seed"] = "card"  # seed = a demo case file


class ProgramProgress(Model):
    """The card's "I applied" mark for one program."""

    applied: bool
    at: datetime


class Case(Model):
    id: str
    code: str = Field(pattern=CASE_CODE_PATTERN)  # display code; no names anywhere
    version: int = 0
    created_at: datetime
    updated_at: datetime
    lang: Lang
    channel: Channel
    test: bool = False  # StartRequest.test
    live: bool = True
    status: CaseStatus = CaseStatus.new
    seeded: bool = False  # demo sample
    persona: str | None = None  # seeded cases only, fictional ("Sofia (demo persona)"); never a real name
    phase: Phase | None = Phase.consent
    turn_count: int = 0
    ended_reason: str | None = None
    ended_early: bool = False
    tier: Tier | None = None
    reason_code: str | None = None
    route_override: RouteOverride | None = None  # routing only; the status value is never stored
    estimate_monthly: int | None = None
    estimate_is_floor: bool = False  # "at least about"
    estimate_range: EstimateRange | None = None  # null until income and housing are known
    expedited_possible: ExpeditedOutlook | None = None
    first_month: FirstMonth | None = None
    summary: str = ""  # built by code: "Undergrad · 1 person · work $900 · rent $1,100"
    slots: dict[SlotName, Slot] = Field(default_factory=dict)
    yellow_lines: list[YellowLine] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)  # crisis_resources_given, human_requested, abuse_ended, ...
    asked: list[AskedQuestion] = Field(default_factory=list)
    skipped: list[SkippedQuestion] = Field(default_factory=list)
    timeline: list[TimelinePoint] = Field(default_factory=list)
    rule_trace: list[RuleStep] = Field(default_factory=list)
    privacy_events: list[PrivacyEvent] = Field(default_factory=list)
    language_request: LanguageRequest | None = None
    table_id: str | None = None
    card: CardRef | None = None
    tracking: Tracking = Field(default_factory=Tracking)
    consent: Consent = Field(default_factory=Consent)
    reviewed_at: datetime | None = None
    # Card questions: question id -> answer. Written only by the card answers endpoint and the demo seed; never a
    # CalFresh slot.
    program_answers: dict[str, ProgramAnswer] = Field(default_factory=dict)
    # "I applied" marks: program id ("calfresh" included) -> {applied, at}.
    program_progress: dict[str, ProgramProgress] = Field(default_factory=dict)

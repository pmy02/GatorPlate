"""Understanding: what the language model and the parser may return (docs/SPEC.md §8.8).

The language model only extracts. Its output format (ExtractionResult) has every field required (nullable where
optional) and no string length or pattern constraints: those are checked in code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from gatorplate.contracts.common import Lang, Model, Period, SlotSource
from gatorplate.contracts.slots import SlotName


class Intent(StrEnum):
    correction = "correction"
    dont_know = "dont_know"
    repeat = "repeat"
    is_ai = "is_ai"
    is_recorded = "is_recorded"
    human_request = "human_request"
    stop = "stop"
    delete_data = "delete_data"
    apply_for_me = "apply_for_me"
    immigration_question = "immigration_question"
    language_request = "language_request"
    crisis = "crisis"
    food_today = "food_today"
    already_receiving = "already_receiving"
    interview_waiting = "interview_waiting"
    previously_denied = "previously_denied"
    proxy_caller = "proxy_caller"
    side_question = "side_question"
    mentions_financial_aid = "mentions_financial_aid"
    off_topic = "off_topic"
    ssn_attempt = "ssn_attempt"
    hold = "hold"
    abuse = "abuse"


class SlotObservation(Model):
    """Every field required (structured-output friendly)."""

    slot: SlotName
    value: str  # "true"/"false", "1100", "18.50", an enum value
    period: Period | None
    # Only with period "hour". A JSON number as in data/tests/utterances.jsonl; code converts it with
    # Decimal(str(x)) before any money math (no float math).
    hours_per_week: float | None
    state: Literal["clear", "unclear"]
    quote: str  # exact substring of the utterance, at most 80 characters (checked in code)
    quote_en: str | None  # English gloss, only when the utterance is Spanish


class ExtractionResult(Model):
    """The language model's output format."""

    observations: list[SlotObservation]
    intents: list[Intent]
    answered_pending: Literal["yes", "partial", "no"]
    lang: Literal["en", "es", "other"]
    side_question: str | None  # paraphrase of at most 120 characters, only with intent side_question
    requested_language: str | None  # two-letter code, only with intent language_request


class PendingQuestion(Model):
    key: str
    slots: list[SlotName]
    kind: Literal["yes_no", "confirm", "number", "choice", "open"]
    choices: list[str] | None = None
    closed: bool = False


class ExtractOutcome(Model):
    status: Literal["ok", "timeout", "error", "refused", "invalid", "skipped"]
    result: ExtractionResult | None = None
    latency_ms: int = 0
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Understanding(Model):
    """Never persisted."""

    redacted_text: str  # for short-term memory and the live transcript only
    observations: list[SlotObservation]
    intents: list[Intent]
    lang: Lang | None
    answered_pending: Literal["yes", "partial", "no"]
    side_question: str | None = None
    requested_language: str | None = None
    llm: ExtractOutcome
    sources: dict[SlotName, SlotSource] = Field(default_factory=dict)
    redactions: list[Literal["ssn", "card_number"]] = Field(default_factory=list)
    keyword_intents: list[Intent] = Field(default_factory=list)
    teen_ty: list[SlotName] = Field(default_factory=list)  # the parser flagged a teen/ty number for these slots

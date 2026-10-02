"""Per-call conversation state, persisted every turn (no transcript)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from gatorplate.contracts.brain_api import BrainReply
from gatorplate.contracts.common import Channel, Lang, Model, Phase
from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import SlotName


class SessionState(Model):
    call_id: str
    case_id: str
    channel: Channel
    lang: Lang
    test: bool = False
    phase: Phase = Phase.consent
    pending: PendingQuestion | None = None
    flips_asked: int = 0
    confirms: dict[SlotName, int] = Field(default_factory=dict)
    silence_count: int = 0
    llm_failures: int = 0
    closed_mode: bool = False
    close_loops: int = 0
    abuse_count: int = 0
    consent_reasks: int = 0
    deferred_keys: list[str] = Field(default_factory=list)  # remainder of a reply split for the word budget
    turn_count: int = 0
    last_seq: int = 0
    first_reply: BrainReply | None = None  # repeated /start
    last_reply: BrainReply | None = None  # repeated seq, repeat intent
    last_keys: list[str] = Field(default_factory=list)
    awaiting: Literal["none", "delete_confirm", "continue_or_stop", "consent"] = "none"
    ended_by_brain: Literal["completed", "no_input", "declined"] | None = None
    ended: bool = False  # /end received
    started_at: datetime
    last_activity_at: datetime
    # Short-term memory (the last 2 redacted utterances of a call) lives in process memory only, never here.

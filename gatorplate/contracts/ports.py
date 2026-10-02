"""Ports: the only way modules call each other (injected through gatorplate.deps.Deps; tests use fakes)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from gatorplate.contracts.brain_api import BrainReply, EndRequest, GatewayLines, StartRequest, TurnRequest
from gatorplate.contracts.card_api import CardStatus, CardView
from gatorplate.contracts.case import Case, Tracking
from gatorplate.contracts.common import CaseStatus, Lang
from gatorplate.contracts.console_api import CaseEvent, LiveTurn, LiveView
from gatorplate.contracts.extraction import PendingQuestion, Understanding
from gatorplate.contracts.programs import ProgramsMeta, ProgramsResult, UnlockedView
from gatorplate.contracts.rules_io import Evaluation, Facts, FlipPlan, RulesMeta
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import MoneyBasis, SlotName


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...  # aware UTC

    def today(self) -> date: ...  # America/Los_Angeles

    def monotonic(self) -> float: ...


@runtime_checkable
class Ids(Protocol):
    """All randomness; tests pin values."""

    def case_id(self) -> str: ...

    def case_code(self) -> str: ...

    def call_id(self) -> str: ...

    def web_token(self) -> str: ...

    def card_token(self) -> str: ...

    def short_code(self) -> str: ...


@runtime_checkable
class RulesPort(Protocol):
    def meta(self) -> RulesMeta: ...

    def valid_on(self, day: date) -> bool: ...

    def normalize_money(self, basis: MoneyBasis) -> Decimal: ...  # monthly, cents half-up

    def facts_from_case(self, case: Case, *, today: date) -> Facts: ...  # defaults per docs/SPEC.md §5.6

    def evaluate(self, facts: Facts, *, today: date) -> Evaluation: ...

    def flip_plan(self, case: Case, *, today: date, budget: int) -> FlipPlan: ...

    def apply(self, case: Case, *, now: datetime, turn: int | None = None) -> Case:
        """Writes tier, reason, estimate, range, timeline point, trace, first_month (filing-date estimate), summary,
        case-level yellow lines (idempotent by code), asked/skipped VoI entries."""
        ...

    def filing_date(self, now: datetime) -> date: ...  # weekday before 5 PM Pacific counts that day

    def compute_tracking(self, tracking: Tracking) -> Tracking: ...


@runtime_checkable
class UnderstandingPort(Protocol):
    async def understand(self, *, text: str, masked: bool, confidence: float | None, dtmf: str | None,
                         pending: PendingQuestion | None, known: dict[SlotName, str], recent: list[str],
                         last_prompt: str | None, lang: Lang, deadline: float, closed_mode: bool) -> Understanding: ...


@runtime_checkable
class CaseStorePort(Protocol):
    def create(self, case: Case) -> Case: ...

    def get(self, case_id: str) -> Case | None: ...

    def get_by_card_token(self, token: str) -> Case | None: ...

    def get_by_short_code(self, code: str, *, now: datetime) -> Case | None: ...

    def list(self, *, status: CaseStatus | None = None, since_seq: int | None = None,
             limit: int = 200) -> list[Case]: ...

    def save(self, case: Case, *, expected_version: int | None = None) -> Case: ...  # bumps version; VersionConflict

    def delete(self, case_id: str) -> bool: ...

    def delete_all(self, *, keep_seeded: bool) -> int: ...


@runtime_checkable
class SessionStorePort(Protocol):
    def get(self, call_id: str) -> SessionState | None: ...

    def put(self, state: SessionState) -> None: ...

    def delete(self, call_id: str) -> None: ...


@runtime_checkable
class LivePort(Protocol):
    """Memory only."""

    def append(self, line: LiveTurn) -> None: ...

    def set_now_asking(self, case_id: str, *, key: str | None, text: str | None, reason: str | None) -> None: ...

    def get(self, case_id: str) -> LiveView | None: ...

    def wipe(self, case_id: str) -> None: ...


@runtime_checkable
class EventBusPort(Protocol):
    def publish(self, type: str, *, case: Case | None = None, case_id: str | None = None,
                changed_slots: Sequence[SlotName] = (), now_asking: str | None = None,
                now_asking_text: str | None = None, asked_reason: str | None = None,
                line: LiveTurn | None = None, changed_programs: bool = False) -> CaseEvent: ...

    def subscribe(self, *, last_seq: int | None) -> AsyncIterator[CaseEvent]: ...

    def current_seq(self) -> int: ...


@runtime_checkable
class BrainPort(Protocol):
    async def start(self, call_id: str, req: StartRequest) -> BrainReply: ...

    async def turn(self, call_id: str, req: TurnRequest) -> BrainReply: ...

    async def end(self, call_id: str, req: EndRequest) -> None: ...

    def lines(self, lang: Lang) -> GatewayLines: ...


@runtime_checkable
class CardBuilderPort(Protocol):
    def build(self, case: Case, *, lang: Lang, now: datetime, base_url: str) -> CardView: ...

    def status(self, case: Case) -> CardStatus: ...

    def ics(self, case: Case, *, lang: Lang) -> str: ...  # 3 VEVENTs relative to first_month.filed_on


@runtime_checkable
class ProgramsPort(Protocol):
    """Other programs on the card; pure, no I/O after construction (docs/SPEC.md §5.10)."""

    def evaluate(self, case: Case, *, today: date) -> ProgramsResult | None:
        """None: mode none (other_help.*, incomplete), a day outside the table's effective dates, or GP_PROGRAMS=0."""
        ...

    def view(self, case: Case, *, lang: Lang, today: date) -> UnlockedView | None:
        """None when evaluate is None (or, never expected, on an output-guard hit)."""
        ...

    def validate_answers(self, case: Case, answers: dict[str, str], *, today: date) -> dict[str, str]:
        """Raises errors.InvalidRequest (422 invalid_request) for an unknown question id or choice, or a question that
        is neither open for this case now nor already answered (a re-answer replaces the old one)."""
        ...

    def can_mark(self, case: Case, program: str, *, today: date) -> bool:
        """"calfresh" or a shown program with can_mark_applied (else the API answers 422)."""
        ...

    def meta(self) -> ProgramsMeta | None: ...  # None with GP_PROGRAMS=0

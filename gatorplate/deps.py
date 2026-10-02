"""Deps: every component the app wires together, injected into the API and the brain (tests use fakes)."""

from __future__ import annotations

from dataclasses import dataclass

from gatorplate.config import Settings
from gatorplate.contracts.ports import (
    BrainPort,
    CardBuilderPort,
    CaseStorePort,
    Clock,
    EventBusPort,
    Ids,
    LivePort,
    ProgramsPort,
    RulesPort,
    SessionStorePort,
    UnderstandingPort,
)


@dataclass(frozen=True)
class Deps:
    settings: Settings
    clock: Clock
    ids: Ids
    rules: RulesPort
    understanding: UnderstandingPort
    brain: BrainPort
    cases: CaseStorePort
    sessions: SessionStorePort
    live: LivePort
    events: EventBusPort
    cards: CardBuilderPort
    # Always a ProgramsPort: with GP_PROGRAMS=0 it is the engine built with enabled=False, whose methods return
    # None / False. CardBuilder receives the same instance.
    programs: ProgramsPort

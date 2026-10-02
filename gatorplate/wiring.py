"""Wiring: builds Deps from Settings — the real rules engine, the understanding (language-model provider from
settings), the dialogue brain, the platform stores, the live transcript store, the event bus, the card builder, the
programs engine, the system clock and the system ids.

One clock instance reaches every component, so a turn deadline, "today" and the stored timestamps share one scale.
With `GP_PROGRAMS=0` the programs engine is built with `enabled=False` (every method answers None / False) and the
card builder receives that same instance (docs/SPEC.md §5.10).
"""

from __future__ import annotations

from gatorplate.card import CardBuilder
from gatorplate.clock import SystemClock
from gatorplate.config import Settings
from gatorplate.contracts.ports import Clock, Ids
from gatorplate.deps import Deps
from gatorplate.dialogue import Brain
from gatorplate.extract import Understander
from gatorplate.ids import SystemIds
from gatorplate.programs import Programs
from gatorplate.rules import Rules
from gatorplate.store import CaseStore, Counters, Database, EventBus, LiveStore, SessionStore


def build_deps(settings: Settings) -> Deps:
    """Every component, wired once, on the system clock and the system ids."""
    return compose(settings, clock=SystemClock(settings.tz), ids=SystemIds())


def compose(settings: Settings, *, clock: Clock, ids: Ids) -> Deps:
    """The same wiring on a given clock and ids (tests pin both, so one fixed clock reaches every component)."""
    db = Database(settings.db_file)
    cases = CaseStore(db, clock=clock)
    sessions = SessionStore(db)
    live = LiveStore()
    events = EventBus(clock=clock, tz=settings.tz)

    rules = Rules.from_settings(settings)
    understanding = Understander.from_settings(settings, counters=Counters(db, clock=clock), clock=clock)
    programs = Programs.from_settings(settings)
    cards = CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz,
                        rules_table_path=settings.rules_table_path, card_ttl_days=settings.card_ttl_days)
    brain = Brain(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, cases=cases,
                  sessions=sessions, live=live, events=events, cards=cards)
    return Deps(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, brain=brain,
                cases=cases, sessions=sessions, live=live, events=events, cards=cards, programs=programs)

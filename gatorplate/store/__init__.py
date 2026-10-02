"""Persistence and in-process state: SQLite case and session stores, web tokens, counters, the memory-only live
transcript store, the event bus, the demo cases and the janitor (docs/SPEC.md §8).

Wiring builds one Database and hands it to the stores:

    db = Database(settings.db_file)
    cases = CaseStore(db, clock=clock); sessions = SessionStore(db)
    live = LiveStore(); events = EventBus(clock=clock, tz=settings.tz)
    WebTokens(db, clock=clock) and Counters(db, clock=clock) (the language-model turn cap)
"""

from __future__ import annotations

from gatorplate.store.cases import CaseStore, DuplicateCaseError, RoutingOnlySlotError
from gatorplate.store.counters import Counters
from gatorplate.store.db import Database
from gatorplate.store.demo import DemoCases
from gatorplate.store.events import EventBus, Subscription
from gatorplate.store.janitor import Janitor
from gatorplate.store.live import LiveStore
from gatorplate.store.sessions import SessionStore
from gatorplate.store.webtokens import WebTokens

__all__ = ["Database", "CaseStore", "SessionStore", "LiveStore", "EventBus", "Subscription", "WebTokens", "Counters",
           "DemoCases", "Janitor", "DuplicateCaseError", "RoutingOnlySlotError"]

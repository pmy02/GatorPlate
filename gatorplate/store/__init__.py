"""Persistence and in-process state: SQLite case and session stores, web tokens, counters, the memory-only live
transcript store, the event bus and the janitor.

Stub with the final signatures; built in stage 1 (docs/SPEC.md §8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import CaseStatus
from gatorplate.contracts.console_api import CaseEvent, LiveTurn, LiveView
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import SlotName


class Database:
    """One SQLite file in WAL mode; migrations at construction."""

    def __init__(self, path: Path) -> None:
        self.path = path


class CaseStore:
    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock

    def create(self, case: Case) -> Case:
        raise NotImplementedError

    def get(self, case_id: str) -> Case | None:
        raise NotImplementedError

    def get_by_card_token(self, token: str) -> Case | None:
        raise NotImplementedError

    def get_by_short_code(self, code: str, *, now: datetime) -> Case | None:
        raise NotImplementedError

    def list(self, *, status: CaseStatus | None = None, since_seq: int | None = None, limit: int = 200) -> list[Case]:
        raise NotImplementedError

    def save(self, case: Case, *, expected_version: int | None = None) -> Case:
        raise NotImplementedError

    def delete(self, case_id: str) -> bool:
        raise NotImplementedError

    def delete_all(self, *, keep_seeded: bool) -> int:
        raise NotImplementedError


class SessionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, call_id: str) -> SessionState | None:
        raise NotImplementedError

    def put(self, state: SessionState) -> None:
        raise NotImplementedError

    def delete(self, call_id: str) -> None:
        raise NotImplementedError


class LiveStore:
    """Memory only: never written to disk or logs."""

    def append(self, line: LiveTurn) -> None:
        raise NotImplementedError

    def set_now_asking(self, case_id: str, *, key: str | None, text: str | None, reason: str | None) -> None:
        raise NotImplementedError

    def get(self, case_id: str) -> LiveView | None:
        raise NotImplementedError

    def wipe(self, case_id: str) -> None:
        raise NotImplementedError


class EventBus:
    """In-process bus: a ring buffer of the last 500 case.* and demo.reset events; live.* is never buffered."""

    def __init__(self, *, clock: Any, buffer: int = 500) -> None:
        self.clock = clock
        self.buffer = buffer

    def publish(self, type: str, *, case: Case | None = None, case_id: str | None = None,
                changed_slots: Sequence[SlotName] = (), now_asking: str | None = None,
                now_asking_text: str | None = None, asked_reason: str | None = None,
                line: LiveTurn | None = None, changed_programs: bool = False) -> CaseEvent:
        raise NotImplementedError

    def subscribe(self, *, last_seq: int | None) -> AsyncIterator[CaseEvent]:
        raise NotImplementedError

    def current_seq(self) -> int:
        raise NotImplementedError


class WebTokens:
    """Web session tokens, stored only as SHA-256 hashes."""

    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock


class Counters:
    """Daily counters (the language-model turn cap, the daily demo reset record)."""

    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock

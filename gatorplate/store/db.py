"""The SQLite database: one file in WAL mode, migrations at construction (docs/SPEC.md §8).

One connection per Database, shared by every store and serialized by a re-entrant lock: the app runs one worker, and
route handlers may run in the event loop or in the thread pool. Timestamps are stored as UTC ISO-8601 text with a `Z`.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS cases (
    id                    TEXT PRIMARY KEY,
    code                  TEXT NOT NULL UNIQUE,
    version               INTEGER NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    status                TEXT NOT NULL,
    live                  INTEGER NOT NULL,
    seeded                INTEGER NOT NULL,
    card_token            TEXT UNIQUE,
    short_code            TEXT,
    short_code_expires_at TEXT,
    card_expires_at       TEXT,
    change_seq            INTEGER NOT NULL DEFAULT 0,
    doc                   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_created ON cases (created_at);
CREATE INDEX IF NOT EXISTS cases_short_code ON cases (short_code);
CREATE INDEX IF NOT EXISTS cases_change_seq ON cases (change_seq);
CREATE TABLE IF NOT EXISTS sessions (
    call_id    TEXT PRIMARY KEY,
    case_id    TEXT NOT NULL,
    doc        TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_case ON sessions (case_id);
CREATE TABLE IF NOT EXISTS web_tokens (
    token_hash TEXT PRIMARY KEY,
    call_id    TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS web_tokens_call ON web_tokens (call_id);
CREATE TABLE IF NOT EXISTS counters (
    key TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    n   INTEGER NOT NULL
);
"""


def ts(value: datetime) -> str:
    """UTC ISO-8601 text with a Z and always six fraction digits. SQL compares and sorts these columns as text, so
    the width must never change (`…:00Z` would sort after `…:00.5Z` of the same second)."""
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(text: str | None) -> datetime | None:
    if text is None:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Database:
    """One SQLite file in WAL mode; migrations at construction."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    # ------------------------------------------------------------------------------------------ plumbing

    def _migrate(self) -> None:
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current < 1:
            self._conn.executescript(_SCHEMA_V1)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @property
    def journal_mode(self) -> str:
        with self._lock:
            return str(self._conn.execute("PRAGMA journal_mode").fetchone()[0])

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction (BEGIN IMMEDIATE ... COMMIT, rolled back on any error)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def ping(self) -> bool:
        try:
            with self._lock:
                return self._conn.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

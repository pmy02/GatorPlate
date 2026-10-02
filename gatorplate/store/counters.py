"""Daily counters: the language-model turn cap and the daily demo reset record.

A counter is (key, day, n); `day` is the America/Los_Angeles date. Reading or adding on a new Pacific day starts the
count again from zero.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from gatorplate.store.db import Database

LLM_TURNS = "llm_turns"
DEMO_DAILY_RESET = "demo_daily_reset"


class Counters:
    """Daily counters (the language-model turn cap, the daily demo reset record)."""

    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock

    def _day(self, day: date | None) -> str:
        return (day or self.clock.today()).isoformat()

    def get(self, key: str, *, day: date | None = None) -> int:
        """Today's count (0 when the stored count belongs to another day)."""
        row = self.db.query_one("SELECT day, n FROM counters WHERE key = ?", (key,))
        if row is None or row["day"] != self._day(day):
            return 0
        return int(row["n"])

    def incr(self, key: str, day: date | None = None, *, by: int = 1) -> int:
        """Adds `by` to the count of `day` (default: today, the Pacific date) and returns the new count. The
        signature is the understanding module's daily counter (`incr(key, day)`), so this store can back the
        language-model turn cap directly."""
        if not isinstance(day, date | None) or isinstance(by, bool) or not isinstance(by, int):
            raise TypeError("incr(key, day=None, *, by=1): day is a date, by an int")
        today = self._day(day)
        with self.db.tx() as conn:
            row = conn.execute("SELECT day, n FROM counters WHERE key = ?", (key,)).fetchone()
            n = (int(row["n"]) if row is not None and row["day"] == today else 0) + by
            conn.execute("INSERT INTO counters (key, day, n) VALUES (?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET day = excluded.day, n = excluded.n", (key, today, n))
        return n

    def try_take(self, key: str, cap: int, *, day: date | None = None) -> bool:
        """Adds one unless today's count already reached `cap`; True when it was added."""
        today = self._day(day)
        with self.db.tx() as conn:
            row = conn.execute("SELECT day, n FROM counters WHERE key = ?", (key,)).fetchone()
            n = int(row["n"]) if row is not None and row["day"] == today else 0
            if n >= cap:
                return False
            conn.execute("INSERT INTO counters (key, day, n) VALUES (?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET day = excluded.day, n = excluded.n", (key, today, n + 1))
        return True

    def recorded_day(self, key: str) -> str | None:
        """The day stored for `key` (for example the Pacific date of the last daily demo reset)."""
        row = self.db.query_one("SELECT day FROM counters WHERE key = ?", (key,))
        return str(row["day"]) if row else None

    def record(self, key: str, *, day: date, n: int = 1) -> None:
        with self.db.tx() as conn:
            conn.execute("INSERT INTO counters (key, day, n) VALUES (?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET day = excluded.day, n = excluded.n",
                         (key, day.isoformat(), n))

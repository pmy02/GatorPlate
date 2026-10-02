"""Clocks: timestamps are aware UTC; "today" is the America/Los_Angeles date (docs/SPEC.md §5.7)."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = "America/Los_Angeles"


class SystemClock:
    def __init__(self, tz: str = PACIFIC) -> None:
        self._tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().astimezone(self._tz).date()

    def monotonic(self) -> float:
        return time.monotonic()


class FixedClock:
    """A clock for tests: it stays at the given instant until advanced or set. monotonic() follows advance()."""

    def __init__(self, at: datetime, tz: str = PACIFIC) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._tz = ZoneInfo(tz)
        self._now = at.astimezone(UTC)
        self._mono = 1000.0

    @classmethod
    def pacific(cls, year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> FixedClock:
        """A clock at a wall-clock time in America/Los_Angeles."""
        return cls(datetime(year, month, day, hour, minute, second, tzinfo=ZoneInfo(PACIFIC)))

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(self._tz).date()

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float = 0, **delta: float) -> datetime:
        step = timedelta(seconds=seconds, **delta)
        self._now = self._now + step
        self._mono += step.total_seconds()
        return self._now

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        new = at.astimezone(UTC)
        self._mono += (new - self._now).total_seconds()
        self._now = new


def default_test_clock() -> FixedClock:
    """Fri 2026-10-02 10:00 Pacific: the default test clock everywhere except the time-zone tests."""
    return FixedClock.pacific(2026, 10, 2, 10, 0)

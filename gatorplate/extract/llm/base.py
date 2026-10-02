"""The language-model port: one structured extraction per turn, a daily turn cap and content-free usage metrics.

Two providers sit behind it: `anthropic` (production) and `fake` (deterministic, no network; tests and the emergency
switch). A third fits behind the same protocol without touching callers. Metrics count calls and tokens since
process start; they never hold a prompt, an utterance or an output.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol

from gatorplate.contracts.extraction import ExtractOutcome

LLMStatus = Literal["no_key", "ready", "ok", "error"]


class LLMClient(Protocol):
    provider: str
    model: str

    async def complete(self, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                       ) -> ExtractOutcome: ...


class DailyCounter(Protocol):
    """A per-day counter (the platform keeps it in its `counters` table): returns the count after adding one."""

    def incr(self, key: str, day: date) -> int: ...


class MemoryCounter:
    """In-process daily counter (tests, and the default when no persistent counter is wired)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, date], int] = {}

    def incr(self, key: str, day: date) -> int:
        with self._lock:
            n = self._counts.get((key, day), 0) + 1
            self._counts[(key, day)] = n
            return n


@dataclass
class UsageMetrics:
    """Counts since process start, read by /healthz (`llm.status`, `llm.usage`). No personal data."""

    provider: str = "fake"
    status: LLMStatus = "ready"
    calls: int = 0
    input_tokens: int = 0  # every input token, the prompt-cache reads and writes below included
    output_tokens: int = 0
    cache_read_tokens: int = 0  # input tokens served from the prompt cache (priced lower)
    cache_write_tokens: int = 0  # input tokens written to the prompt cache (priced higher)
    last_ok_at: datetime | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, outcome: ExtractOutcome, *, now: datetime | None = None) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += outcome.input_tokens or 0
            self.output_tokens += outcome.output_tokens or 0
            if outcome.status == "ok":
                self.status = "ok"
                self.last_ok_at = now or datetime.now(UTC)
            elif outcome.status in ("error", "invalid", "refused", "timeout"):
                self.status = "error"

    def record_cache(self, read: int, write: int) -> None:
        with self._lock:
            self.cache_read_tokens += max(0, int(read))
            self.cache_write_tokens += max(0, int(write))

    def count_extra_call(self) -> None:
        with self._lock:
            self.calls += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider,
                "status": self.status,
                "last_ok_at": self.last_ok_at.isoformat().replace("+00:00", "Z") if self.last_ok_at else None,
                "usage": {"calls": self.calls, "input_tokens": self.input_tokens,
                          "output_tokens": self.output_tokens, "cache_read_input_tokens": self.cache_read_tokens,
                          "cache_creation_input_tokens": self.cache_write_tokens},
            }


def outcome(status: Literal["ok", "timeout", "error", "refused", "invalid", "skipped"], *, latency_ms: int = 0,
            model: str | None = None, **extra: Any) -> ExtractOutcome:
    return ExtractOutcome(status=status, latency_ms=max(0, int(latency_ms)), model=model, **extra)

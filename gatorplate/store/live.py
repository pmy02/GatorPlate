"""The live transcript store (LivePort): redacted lines of the current call, in process memory only.

Never written to disk or logs and never put into the event replay buffer; wiped when the call ends and lost on a
restart by design (docs/SPEC.md §8.6).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from gatorplate.contracts.console_api import LiveTurn, LiveView

MAX_LINES = 400  # far more than a call has (about 2 lines per turn, a few dozen turns at most)


@dataclass
class _Live:
    lines: list[LiveTurn] = field(default_factory=list)
    now_asking: str | None = None
    now_asking_text: str | None = None
    asked_reason: str | None = None


class LiveStore:
    """Memory only: never written to disk or logs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, _Live] = {}

    def append(self, line: LiveTurn) -> None:
        with self._lock:
            live = self._calls.setdefault(line.case_id, _Live())
            live.lines.append(line)
            if len(live.lines) > MAX_LINES:
                del live.lines[: len(live.lines) - MAX_LINES]

    def set_now_asking(self, case_id: str, *, key: str | None, text: str | None, reason: str | None) -> None:
        with self._lock:
            live = self._calls.setdefault(case_id, _Live())
            live.now_asking, live.now_asking_text, live.asked_reason = key, text, reason

    def get(self, case_id: str) -> LiveView | None:
        with self._lock:
            live = self._calls.get(case_id)
            if live is None:
                return None
            return LiveView(case_id=case_id, lines=[line.model_copy() for line in live.lines],
                            now_asking=live.now_asking, now_asking_text=live.now_asking_text,
                            asked_reason=live.asked_reason)

    def wipe(self, case_id: str) -> None:
        with self._lock:
            self._calls.pop(case_id, None)

    def wipe_all(self) -> None:
        with self._lock:
            self._calls.clear()

    def case_ids(self) -> list[str]:
        with self._lock:
            return list(self._calls)

"""The in-process event bus (EventBusPort) behind the console's Server-Sent Events (docs/UI_SPEC.md A8.3).

Every event gets the next global sequence number. `case.*` and `demo.reset` events go into a ring buffer (the last
500) and are replayed to a subscriber that resumes after a `Last-Event-ID`; a subscriber that is too far behind (or
holds a number from an earlier run of the server) gets one `resync` event instead and refetches the list. `live.*`
events carry transcript lines: they are never buffered and never replayed.

One process, one worker: the bus, its buffer and its subscribers live in memory. `publish` may be called from the
event loop or from a worker thread; delivery to each subscriber's queue is thread-safe.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.console_api import CaseEvent, CaseSummary, LiveTurn
from gatorplate.contracts.slots import SlotName
from gatorplate.contracts.summary import case_summary

BUFFERED_TYPES = frozenset({"case.created", "case.updated", "case.deleted", "demo.reset"})
LIVE_TYPES = frozenset({"live.turn", "live.ended"})
EVENT_TYPES = BUFFERED_TYPES | LIVE_TYPES | {"resync"}
MAX_QUEUE = 1000  # a subscriber further behind than this gets a resync


class Subscription:
    """One subscriber: the backlog computed at subscription time, then live events from its queue."""

    def __init__(self, bus: EventBus, loop: asyncio.AbstractEventLoop, backlog: list[CaseEvent]) -> None:
        self._bus = bus
        self.loop = loop
        self.queue: asyncio.Queue[CaseEvent | None] = asyncio.Queue()
        self.backlog = backlog
        self.closed = False

    def _deliver(self, event: CaseEvent) -> None:
        if self.closed:
            return
        if self.queue.qsize() >= MAX_QUEUE:
            while not self.queue.empty():
                self.queue.get_nowait()
            event = self._bus.make_resync()
        self.queue.put_nowait(event)

    async def get(self, timeout: float | None = None) -> CaseEvent | None:
        """The next event: the backlog first, then the queue. None on timeout or after close()."""
        if self.backlog:
            return self.backlog.pop(0)
        if self.closed:
            return None
        try:
            if timeout is None:
                return await self.queue.get()
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._bus._remove(self)
            try:
                self.queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - the queue is unbounded
                pass


class EventBus:
    """In-process bus: a ring buffer of the last 500 case.* and demo.reset events; live.* is never buffered."""

    def __init__(self, *, clock: Any, buffer: int = 500, tz: str = "America/Los_Angeles",
                 summarize: Callable[[Case], CaseSummary] | None = None) -> None:
        self.clock = clock
        self.buffer = buffer
        self.tz = tz
        # The app installs a summarizer that also fills found_display through the programs port.
        self.summarize: Callable[[Case], CaseSummary] = summarize or (lambda case: case_summary(case, tz=self.tz))
        self._lock = threading.Lock()
        self._seq = 0
        self._ring: deque[CaseEvent] = deque()
        self._dropped_upto = 0  # highest seq of a buffered event that fell out of the ring
        self._case_seq: dict[str, int] = {}
        self._last_reset_seq = 0
        self._subs: set[Subscription] = set()

    # ------------------------------------------------------------------------------------------ publishing

    def publish(self, type: str, *, case: Case | None = None, case_id: str | None = None,
                changed_slots: Sequence[SlotName] = (), now_asking: str | None = None,
                now_asking_text: str | None = None, asked_reason: str | None = None,
                line: LiveTurn | None = None, changed_programs: bool = False) -> CaseEvent:
        if type not in EVENT_TYPES or type == "resync":
            raise ValueError(f"unknown event type {type!r}")
        cid = case_id or (case.id if case is not None else None) or (line.case_id if line is not None else None)
        summary = None
        if case is not None and type in ("case.created", "case.updated"):
            summary = self.summarize(case)
        with self._lock:
            self._seq += 1
            event = CaseEvent(seq=self._seq, type=type, case_id=cid, summary=summary,  # type: ignore[arg-type]
                              changed_slots=[SlotName(s) for s in changed_slots], now_asking=now_asking,
                              now_asking_text=now_asking_text, asked_reason=asked_reason,
                              line=line if type == "live.turn" else None, changed_programs=changed_programs,
                              at=self.clock.now())
            if type in BUFFERED_TYPES:
                self._ring.append(event)
                while len(self._ring) > self.buffer:
                    self._dropped_upto = self._ring.popleft().seq
                if type == "demo.reset":
                    self._last_reset_seq = event.seq
                elif cid is not None:
                    self._case_seq[cid] = event.seq
            # Scheduled under the lock and always through the loop's queue, so every subscriber sees seq order
            # whichever thread published.
            closed = [sub for sub in self._subs if not self._send(sub, event)]
            for sub in closed:
                self._subs.discard(sub)
        return event

    @staticmethod
    def _send(sub: Subscription, event: CaseEvent) -> bool:
        try:
            sub.loop.call_soon_threadsafe(sub._deliver, event)
        except RuntimeError:  # the subscriber's loop is closed
            return False
        return True

    def make_resync(self) -> CaseEvent:
        with self._lock:
            return CaseEvent(seq=self._seq, type="resync", at=self.clock.now())

    # ------------------------------------------------------------------------------------------ reading

    def current_seq(self) -> int:
        with self._lock:
            return self._seq

    def buffered(self) -> list[CaseEvent]:
        with self._lock:
            return list(self._ring)

    def changed_since(self, seq: int) -> set[str] | None:
        """Case ids with a case.* event after `seq`; None when the caller must refetch everything (a demo reset
        since then, events that left the buffer, or a number this process never issued)."""
        with self._lock:
            if seq > self._seq or seq < self._dropped_upto or self._last_reset_seq > seq:
                return None
            return {cid for cid, s in self._case_seq.items() if s > seq}

    def _backlog(self, last_seq: int | None) -> list[CaseEvent]:
        if last_seq is None:
            return []
        if last_seq > self._seq or last_seq < self._dropped_upto:
            return [CaseEvent(seq=self._seq, type="resync", at=self.clock.now())]
        return [e for e in self._ring if e.seq > last_seq]

    def open(self, *, last_seq: int | None) -> Subscription:
        """A subscription in the running event loop; the replay backlog and the registration are atomic."""
        loop = asyncio.get_running_loop()
        with self._lock:
            sub = Subscription(self, loop, self._backlog(last_seq))
            self._subs.add(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    async def subscribe(self, *, last_seq: int | None) -> AsyncIterator[CaseEvent]:
        sub = self.open(last_seq=last_seq)
        try:
            while True:
                event = await sub.get()
                if event is None:
                    return
                yield event
        finally:
            sub.close()

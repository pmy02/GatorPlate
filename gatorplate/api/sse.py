"""Server-Sent Events for the console (`GET /api/events`, docs/UI_SPEC.md A8.3).

Each event is `id: <seq>`, `event: <type>`, `data: <CaseEvent JSON>`. A `ping` event (data `{}`) goes out after
15 seconds without an event, so the page can tell a quiet stream from a dead one. `Last-Event-ID` resumes: buffered
`case.*` and `demo.reset` events are replayed, `live.*` never; a client too far behind gets one `resync`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from gatorplate.contracts.console_api import CaseEvent
from gatorplate.store.events import Subscription

PING_S = 15.0
RETRY_MS = 3000


def format_event(event: CaseEvent) -> bytes:
    data = event.model_dump_json()
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n".encode()


def parse_last_event_id(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    return int(value) if value.isdigit() and len(value) <= 18 else None


async def event_stream(sub: Subscription, *, ping_s: float = PING_S) -> AsyncIterator[bytes]:
    try:
        yield f"retry: {RETRY_MS}\n\n".encode()
        while True:
            event = await sub.get(timeout=ping_s)
            if event is None:
                if sub.closed:
                    return
                yield b"event: ping\ndata: {}\n\n"
                continue
            yield format_event(event)
    finally:
        sub.close()

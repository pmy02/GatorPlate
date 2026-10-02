"""Server-Sent Events at the ASGI level (the test client buffers whole bodies, so the stream is read chunk by chunk
here): the first chunk is the padding comment, the reconnect delay and an immediate ping; the response asks proxies
not to buffer, cache or transform it; two events arrive in order, a reconnect with Last-Event-ID replays the case
events it missed but never a live.* event, a quiet stream sends ping events, and a disconnect ends the
subscription."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

import gatorplate.api.security as security
from gatorplate.api.sse import PADDING_BYTES, PING, RETRY_MS, event_stream, first_chunk
from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.console_api import LiveTurn


def parse(raw: bytes) -> list[dict]:
    events = []
    for block in raw.decode().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line and not line.startswith(":"):
                key, _, value = line.partition(":")
                fields[key] = value.strip()
        if "event" in fields:
            events.append(fields)
    return events


async def stream(app, cookie: str, *, until: int, last_event_id: str | None = None,
                 during: Callable[[], None] | None = None, bus=None, pings: bool = False,
                 query: str = "") -> dict[str, Any]:
    """Read /api/events until `until` events arrived (pings count only with pings=True), then disconnect.
    `last_event_id` is the Last-Event-ID header; `query` the query string (the page's `?last_event_id=` resume point)."""
    disconnect = asyncio.Event()
    state: dict[str, Any] = {"requested": False, "status": 0, "headers": {}, "chunks": [], "raw": b""}

    def counted(raw: bytes) -> list[dict]:
        return [e for e in parse(raw) if pings or e["event"] != "ping"]

    async def receive() -> dict:
        if not state["requested"]:
            state["requested"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
            for key, value in message.get("headers", []):
                state["headers"].setdefault(key.decode().lower(), []).append(value.decode())
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                state["chunks"].append(body)
            state["raw"] += body
            if len(counted(state["raw"])) >= until or state["status"] != 200:
                disconnect.set()

    headers = [(b"cookie", f"gp_console={cookie}".encode()), (b"accept", b"text/event-stream")]
    if last_event_id is not None:
        headers.append((b"last-event-id", last_event_id.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": "GET", "scheme": "https", "path": "/api/events", "raw_path": b"/api/events",
             "query_string": query.encode(), "headers": headers, "client": ("testclient", 50000),
             "server": ("testserver", 443), "root_path": "", "state": {}}
    task = asyncio.create_task(app(scope, receive, send))
    if during is not None:
        for _ in range(200):
            if bus is not None and bus.subscriber_count() > 0:
                break
            await asyncio.sleep(0.005)
        during()
    await asyncio.wait_for(task, 5)
    state["events"] = counted(state["raw"])
    return state


def _case(clock) -> Case:
    now = clock.now()
    return Case(id="c_ssecase001", code="K7Q-2FM", created_at=now, updated_at=now, lang=Lang.en, channel=Channel.phone)


async def test_first_chunk_is_padding_then_an_immediate_ping(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    h.ctx.sse_ping_s = 30.0  # the timed ping is far away: the first ping must not wait for it
    out = await asyncio.wait_for(stream(h.app, cookie, until=1, pings=True), 2)
    assert out["status"] == 200
    first = out["chunks"][0]
    comment, _, rest = first.partition(b"\n")
    assert comment.startswith(b": ") and comment[2:].strip() == b"", "a comment line, ignored by EventSource"
    assert len(comment) + 1 == PADDING_BYTES >= 2048
    assert rest == f"retry: {RETRY_MS}\n\n".encode() + b"event: ping\ndata: {}\n\n", "a ping in the first chunk"
    assert [e["event"] for e in parse(first)] == ["ping"]


async def test_stream_headers_ask_proxies_not_to_buffer_or_transform(h, monkeypatch: pytest.MonkeyPatch) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    out = await stream(h.app, cookie, until=1, pings=True)
    headers = out["headers"]
    assert headers["content-type"][0].startswith("text/event-stream")
    assert headers["x-accel-buffering"] == ["no"]
    # The security headers stay as strict as on every API answer (no-store is never weakened) ...
    assert any("no-store" in v for v in headers["cache-control"])
    assert headers["cache-control"] == ["no-store, no-transform"], "no-transform also reaches the wire"
    assert "x-content-type-options" in headers and "content-security-policy" in headers
    # ... and the route itself asks for no caching and no transforming.
    monkeypatch.setattr(security, "security_headers", lambda path: [])
    own = (await stream(h.app, cookie, until=1, pings=True))["headers"]
    assert own["cache-control"] == ["no-cache, no-transform"] and own["x-accel-buffering"] == ["no"]


async def test_two_events_then_resume_without_live(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    bus = h.deps.events

    def publish_two() -> None:
        bus.publish("case.created", case=_case(h.clock))
        bus.publish("case.updated", case=_case(h.clock), changed_slots=["age"])

    out = await stream(h.app, cookie, until=2, during=publish_two, bus=bus)
    events = out["events"]
    assert out["status"] == 200 and [e["event"] for e in events] == ["case.created", "case.updated"]
    assert [int(e["id"]) for e in events] == [1, 2]
    data = json.loads(events[1]["data"])
    assert data["summary"]["code"] == "K7Q-2FM" and data["changed_slots"] == ["age"]
    assert bus.subscriber_count() == 0  # the disconnect closed the subscription
    line = LiveTurn(case_id="c_ssecase001", turn=1, who="student", text="redacted", lang=Lang.en, at=h.clock.now())
    bus.publish("live.turn", line=line)
    bus.publish("live.ended", case_id="c_ssecase001")
    bus.publish("case.deleted", case_id="c_ssecase001")
    replay = (await stream(h.app, cookie, until=2, last_event_id="1"))["events"]
    assert [(e["event"], e["id"]) for e in replay] == [("case.updated", "2"), ("case.deleted", "5")]


async def test_resync_and_pings(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    h.ctx.sse_ping_s = 0.02
    events = (await stream(h.app, cookie, until=1, last_event_id="42"))["events"]  # never issued by this process
    assert events[0]["event"] == "resync"
    pings = (await stream(h.app, cookie, until=3, pings=True))["events"]
    assert [e["event"] for e in pings] == ["ping", "ping", "ping"] and pings[1]["data"] == "{}"


async def test_events_need_the_console_cookie(h) -> None:
    out = await stream(h.app, "forged", until=1)
    assert out["status"] == 401 and out["events"] == []


async def test_the_query_resume_point_replays_and_the_header_wins(h) -> None:
    """The page opens each stream with `?last_event_id=<seq>`; on its own reconnect the browser keeps that URL and
    adds the newer Last-Event-ID header, which must win, or the stream would replay what the page already has."""
    h.login()
    cookie = h.client.cookies.get("gp_console")
    bus = h.deps.events
    for _ in range(3):
        bus.publish("case.updated", case=_case(h.clock))
    by_query = (await stream(h.app, cookie, until=2, query="last_event_id=1"))["events"]
    assert [e["id"] for e in by_query] == ["2", "3"]
    newer = await asyncio.wait_for(stream(h.app, cookie, until=1, last_event_id="2", query="last_event_id=1"), 2)
    assert [e["id"] for e in newer["events"]] == ["3"]
    # A broken resume point is ignored (no replay), never a server error.
    bad = await asyncio.wait_for(stream(h.app, cookie, until=1, pings=True, query="last_event_id=-1"), 2)
    assert bad["status"] == 200 and [e["event"] for e in bad["events"]] == ["ping"]


async def test_padding_and_the_first_ping_come_before_a_replay_or_a_resync(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    h.ctx.sse_ping_s = 30.0
    bus = h.deps.events
    bus.publish("case.created", case=_case(h.clock))
    bus.publish("case.deleted", case_id="c_ssecase001")
    replay = await asyncio.wait_for(stream(h.app, cookie, until=3, pings=True, query="last_event_id=0"), 2)
    assert replay["chunks"][0].startswith(b": ")
    assert [(e["event"], e.get("id")) for e in replay["events"]] == [("ping", None), ("case.created", "1"),
                                                                     ("case.deleted", "2")]
    resync = await asyncio.wait_for(stream(h.app, cookie, until=2, pings=True, last_event_id="99"), 2)
    assert resync["chunks"][0].startswith(b": ")
    assert [e["event"] for e in resync["events"]] == ["ping", "resync"]


class _QuietSub:
    """A subscription that never has an event: it records each wait, and closes after `waits` of them."""

    def __init__(self, waits: int) -> None:
        self.timeouts: list[float | None] = []
        self.waits = waits
        self.closed = False

    async def get(self, timeout: float | None = None) -> None:
        self.timeouts.append(timeout)
        if len(self.timeouts) >= self.waits:
            self.closed = True
        return None

    def close(self) -> None:
        self.closed = True


async def test_the_first_ping_does_not_change_the_quiet_interval() -> None:
    sub = _QuietSub(waits=3)
    chunks = [chunk async for chunk in event_stream(sub, ping_s=15.0)]  # type: ignore[arg-type]
    assert chunks == [first_chunk(), PING, PING]  # one ping at once, then one per quiet interval
    assert sub.timeouts == [15.0, 15.0, 15.0] and sub.closed

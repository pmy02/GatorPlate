"""Server-Sent Events at the ASGI level (the test client buffers whole bodies, so the stream is read chunk by chunk
here): two events arrive in order, a reconnect with Last-Event-ID replays the case events it missed but never a
live.* event, a quiet stream sends ping events, and a disconnect ends the subscription."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

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
                 during: Callable[[], None] | None = None, bus=None) -> tuple[int, list[dict]]:
    disconnect = asyncio.Event()
    state = {"requested": False, "status": 0, "raw": b""}

    async def receive() -> dict:
        if not state["requested"]:
            state["requested"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["raw"] += message.get("body", b"")
            if len(parse(state["raw"])) >= until or state["status"] != 200:
                disconnect.set()

    headers = [(b"cookie", f"gp_console={cookie}".encode()), (b"accept", b"text/event-stream")]
    if last_event_id is not None:
        headers.append((b"last-event-id", last_event_id.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": "GET", "scheme": "https", "path": "/api/events", "raw_path": b"/api/events",
             "query_string": b"", "headers": headers, "client": ("testclient", 50000),
             "server": ("testserver", 443), "root_path": "", "state": {}}
    task = asyncio.create_task(app(scope, receive, send))
    if during is not None:
        for _ in range(200):
            if bus is not None and bus.subscriber_count() > 0:
                break
            await asyncio.sleep(0.005)
        during()
    await asyncio.wait_for(task, 5)
    return state["status"], parse(state["raw"])


def _case(clock) -> Case:
    now = clock.now()
    return Case(id="c_ssecase001", code="K7Q-2FM", created_at=now, updated_at=now, lang=Lang.en, channel=Channel.phone)


async def test_two_events_then_resume_without_live(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    bus = h.deps.events

    def publish_two() -> None:
        bus.publish("case.created", case=_case(h.clock))
        bus.publish("case.updated", case=_case(h.clock), changed_slots=["age"])

    status, events = await stream(h.app, cookie, until=2, during=publish_two, bus=bus)
    assert status == 200 and [e["event"] for e in events] == ["case.created", "case.updated"]
    assert [int(e["id"]) for e in events] == [1, 2]
    data = json.loads(events[1]["data"])
    assert data["summary"]["code"] == "K7Q-2FM" and data["changed_slots"] == ["age"]
    assert bus.subscriber_count() == 0  # the disconnect closed the subscription
    line = LiveTurn(case_id="c_ssecase001", turn=1, who="student", text="redacted", lang=Lang.en, at=h.clock.now())
    bus.publish("live.turn", line=line)
    bus.publish("live.ended", case_id="c_ssecase001")
    bus.publish("case.deleted", case_id="c_ssecase001")
    status, replay = await stream(h.app, cookie, until=2, last_event_id="1")
    assert [(e["event"], e["id"]) for e in replay] == [("case.updated", "2"), ("case.deleted", "5")]


async def test_resync_and_pings(h) -> None:
    h.login()
    cookie = h.client.cookies.get("gp_console")
    h.ctx.sse_ping_s = 0.02
    _, events = await stream(h.app, cookie, until=1, last_event_id="42")  # never issued by this process
    assert events[0]["event"] == "resync"
    _, pings = await stream(h.app, cookie, until=2)
    assert [e["event"] for e in pings] == ["ping", "ping"] and pings[0]["data"] == "{}"


async def test_events_need_the_console_cookie(h) -> None:
    status, events = await stream(h.app, "forged", until=1)
    assert status == 401 and events == []

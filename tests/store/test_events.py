"""The event bus: one global sequence, a ring buffer of 500 case.* / demo.reset events, live.* never buffered,
resume after Last-Event-ID, resync for a subscriber that is too far behind, thread-safe delivery."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.console_api import LiveTurn
from gatorplate.contracts.slots import SlotName
from gatorplate.store import EventBus


def _case(clock, cid: str = "c_aaaaaaaaaa") -> Case:
    now = clock.now()
    return Case(id=cid, code="K7Q-2FM", created_at=now, updated_at=now, lang=Lang.en, channel=Channel.phone)


def _line(clock, case_id: str = "c_aaaaaaaaaa") -> LiveTurn:
    return LiveTurn(case_id=case_id, turn=1, who="student", text="redacted words", lang=Lang.en, at=clock.now())


def test_publish_builds_events(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock)
    created = bus.publish("case.created", case=_case(fixed_clock), changed_slots=[SlotName.age])
    assert created.seq == 1 and created.summary is not None and created.summary.label == "K7Q-2FM"
    assert created.changed_slots == [SlotName.age] and created.at == fixed_clock.now()
    live = bus.publish("live.turn", line=_line(fixed_clock))
    assert live.seq == 2 and live.case_id == "c_aaaaaaaaaa" and live.line is not None and live.summary is None
    programs = bus.publish("case.updated", case=_case(fixed_clock), changed_programs=True)
    assert programs.changed_programs is True and bus.current_seq() == 3
    assert [e.type for e in bus.buffered()] == ["case.created", "case.updated"]  # live.* never buffered


def test_ring_buffer_and_changed_since(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock, buffer=500)
    for i in range(501):
        bus.publish("case.updated", case=_case(fixed_clock, f"c_{i:010d}"))
    ring = bus.buffered()
    assert len(ring) == 500 and ring[0].seq == 2
    assert bus.changed_since(0) is None  # seq 1 left the buffer: refetch everything
    assert bus.changed_since(500) == {"c_0000000500"}
    assert bus.changed_since(10_000) is None  # a number this process never issued
    bus.publish("demo.reset")
    assert bus.changed_since(500) is None


async def test_subscribe_replays_after_last_event_id_without_live(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock)
    bus.publish("case.created", case=_case(fixed_clock))
    bus.publish("live.turn", line=_line(fixed_clock))
    bus.publish("case.updated", case=_case(fixed_clock))
    sub = bus.open(last_seq=1)
    first = await sub.get(timeout=0.5)
    assert first is not None and (first.seq, first.type) == (3, "case.updated")  # live.turn (2) not replayed
    bus.publish("live.turn", line=_line(fixed_clock))
    nxt = await sub.get(timeout=0.5)
    assert nxt is not None and nxt.type == "live.turn"  # a connected subscriber does get live events
    assert await sub.get(timeout=0.01) is None
    sub.close()
    assert bus.subscriber_count() == 0


async def test_resync_when_too_far_behind(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock, buffer=3)
    for _ in range(5):
        bus.publish("case.updated", case=_case(fixed_clock))
    sub = bus.open(last_seq=1)
    event = await sub.get(timeout=0.5)
    assert event is not None and event.type == "resync" and event.seq == 5
    sub.close()
    stale = bus.open(last_seq=99)  # from an earlier run of the server
    event = await stale.get(timeout=0.5)
    assert event is not None and event.type == "resync"
    stale.close()


async def test_async_iterator_and_thread_publish(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock)
    seen: list[str] = []

    async def consume() -> None:
        async with contextlib.aclosing(bus.subscribe(last_seq=None)) as events:
            async for event in events:
                seen.append(event.type)
                if len(seen) == 2:
                    return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    worker = threading.Thread(target=lambda: bus.publish("case.created", case=_case(fixed_clock)))
    worker.start()
    worker.join()
    bus.publish("case.deleted", case_id="c_aaaaaaaaaa")
    await asyncio.wait_for(task, 2)
    assert seen == ["case.created", "case.deleted"]
    assert bus.subscriber_count() == 0


def test_summarizer_hook(fixed_clock) -> None:
    bus = EventBus(clock=fixed_clock)
    bus.summarize = lambda case: EventBus(clock=fixed_clock).summarize(case).model_copy(update={"found_display": 4220})
    event = bus.publish("case.updated", case=_case(fixed_clock), changed_programs=True)
    assert event.summary is not None and event.summary.found_display == 4220

"""Fixtures for the dialogue tests: a Brain wired to the in-memory doubles of tests/dialogue/support.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from gatorplate.clock import FixedClock, default_test_clock
from gatorplate.config import Settings
from gatorplate.contracts.brain_api import BrainReply, StartRequest, TurnRequest
from gatorplate.dialogue import Brain
from gatorplate.ids import FixedIds
from tests.dialogue.support import FakeRules, FakeUnderstanding, MemCases, MemEvents, MemLive, MemSessions


@dataclass
class Rig:
    brain: Brain
    settings: Settings
    clock: FixedClock
    ids: FixedIds
    rules: FakeRules
    understanding: FakeUnderstanding
    cases: MemCases
    sessions: MemSessions
    live: MemLive
    events: MemEvents
    call_id: str = "0a000000000000000000000000000001"
    seq: int = 0
    problems: list = field(default_factory=list)

    def _check(self, reply: BrainReply, *, start: bool = False) -> BrainReply:
        """Every phone reply of every test passes the phone text rules and its word budget."""
        from tests.dialogue.replay import phone_reply_problems

        session = self.session()
        if session is not None and session.channel == "phone" and reply.debug is not None:
            found = phone_reply_problems(reply, list(reply.debug.keys), start=start)
            if found:
                self.problems.append((reply.debug.keys, found))
        return reply

    async def start(self, *, channel: str = "phone", lang: str = "en", test: bool = False) -> BrainReply:
        self.seq = 0
        reply = await self.brain.start(self.call_id, StartRequest(v=1, seq=0, channel=channel, lang=lang, test=test))
        return self._check(reply, start=True)

    async def say(self, text: str, **extra: Any) -> BrainReply:
        self.seq += 1
        lang = extra.pop("lang", self.session().lang.value)
        body = {"v": 1, "seq": self.seq, "lang": lang, "event": "utterance", "text": text, "masked": False,
                "confidence": 0.93, "interrupted": False, "typed": False}
        body.update(extra)
        return self._check(await self.brain.turn(self.call_id, TurnRequest.model_validate(body)))

    async def key(self, key: str) -> BrainReply:
        self.seq += 1
        body = {"v": 1, "seq": self.seq, "lang": self.session().lang.value, "event": "dtmf", "dtmf": key}
        return self._check(await self.brain.turn(self.call_id, TurnRequest.model_validate(body)))

    async def silence(self, n: int) -> BrainReply:
        self.seq += 1
        body = {"v": 1, "seq": self.seq, "lang": "en", "event": "silence", "silence_n": n, "silence_ms": 5000 * n}
        return self._check(await self.brain.turn(self.call_id, TurnRequest.model_validate(body)))

    def session(self):
        return self.sessions.get(self.call_id)

    def case(self):
        s = self.session()
        return self.cases.get(s.case_id) if s else None


def make_rig(settings: Settings, *, card_delivery: str = "code", live: bool = False, short_codes=(),
             understanding: FakeUnderstanding | None = None, clock: FixedClock | None = None,
             debug_keys: bool = True) -> Rig:
    settings = settings.model_copy(update={"card_delivery": card_delivery, "live_transcript": live,
                                           "debug_keys": debug_keys})
    clock = clock or default_test_clock()
    ids = FixedIds(short_codes=list(short_codes))
    rules = FakeRules()
    und = understanding or FakeUnderstanding()
    cases, sessions, mem_live, events = MemCases(), MemSessions(), MemLive(), MemEvents()
    brain = Brain(settings=settings, clock=clock, ids=ids, rules=rules, understanding=und, cases=cases,
                  sessions=sessions, live=mem_live, events=events, cards=None)
    return Rig(brain=brain, settings=settings, clock=clock, ids=ids, rules=rules, understanding=und, cases=cases,
               sessions=sessions, live=mem_live, events=events)


@pytest.fixture
def rig(settings_test: Settings):
    built = make_rig(settings_test)
    yield built
    assert built.problems == []


@pytest.fixture
def rig_factory(settings_test: Settings):
    built: list[Rig] = []

    def build(**kwargs: Any) -> Rig:
        built.append(make_rig(settings_test, **kwargs))
        return built[-1]

    yield build
    assert [r.problems for r in built if r.problems] == []

"""Dialogue (BrainPort): global intents, the phase machine, rendering from the sentence bank, word budgets, the
output guard, per-call locks and seq rules.

Stub with the final signatures; built in stage 1 (docs/SPEC.md §3, docs/BRAIN_API.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gatorplate.contracts.brain_api import BrainReply, EndRequest, GatewayLines, StartRequest, TurnRequest
from gatorplate.contracts.common import Lang


class Brain:
    def __init__(self, *, settings: Any, clock: Any, ids: Any, rules: Any, understanding: Any, cases: Any,
                 sessions: Any, live: Any, events: Any, cards: Any, content_dir: Path | None = None) -> None:
        self.settings = settings
        self.clock = clock
        self.ids = ids
        self.rules = rules
        self.understanding = understanding
        self.cases = cases
        self.sessions = sessions
        self.live = live
        self.events = events
        self.cards = cards
        self.content_dir = content_dir

    async def start(self, call_id: str, req: StartRequest) -> BrainReply:
        raise NotImplementedError

    async def turn(self, call_id: str, req: TurnRequest) -> BrainReply:
        raise NotImplementedError

    async def end(self, call_id: str, req: EndRequest) -> None:
        raise NotImplementedError

    def lines(self, lang: Lang) -> GatewayLines:
        raise NotImplementedError

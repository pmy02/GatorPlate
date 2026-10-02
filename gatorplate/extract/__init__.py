"""Understanding (UnderstandingPort): redaction, keyword intents, parser, one language-model call, merge.

Stub with the final signatures; built in stage 1 (docs/SPEC.md §3 and §8.7-§8.8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import PendingQuestion, Understanding
from gatorplate.contracts.slots import SlotName


class Understander:
    def __init__(self, *, settings: Any, guards_path: Path | None = None, llm: Any = None,
                 counters: Any = None) -> None:
        self.settings = settings
        self.guards_path = guards_path
        self.llm = llm
        self.counters = counters

    @classmethod
    def from_settings(cls, settings: Any, *, counters: Any = None) -> Understander:
        return cls(settings=settings, guards_path=settings.guards_path, counters=counters)

    async def understand(self, *, text: str, masked: bool, confidence: float | None, dtmf: str | None,
                         pending: PendingQuestion | None, known: dict[SlotName, str], recent: list[str],
                         last_prompt: str | None, lang: Lang, deadline: float, closed_mode: bool) -> Understanding:
        raise NotImplementedError

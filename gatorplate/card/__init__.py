"""Student card (CardBuilderPort): CardView, CardStatus and the calendar file from a Case and the card content.

Stub with the final signatures; built in stage 1 (docs/SPEC.md §6). The unlocked part comes from the injected
ProgramsPort, never from importing the programs module.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from gatorplate.contracts.card_api import CardStatus, CardView
from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Lang
from gatorplate.contracts.ports import ProgramsPort


class CardBuilder:
    def __init__(self, content_dir: Path | None = None, programs: ProgramsPort | None = None, *,
                 guards_path: Path | None = None, tz: str = "America/Los_Angeles") -> None:
        self.content_dir = content_dir
        self.programs = programs
        self.guards_path = guards_path
        self.tz = tz

    def build(self, case: Case, *, lang: Lang, now: datetime, base_url: str) -> CardView:
        raise NotImplementedError

    def status(self, case: Case) -> CardStatus:
        raise NotImplementedError

    def ics(self, case: Case, *, lang: Lang) -> str:
        raise NotImplementedError

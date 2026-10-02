"""Other programs on the student card (ProgramsPort): "money you may be missing", computed by code from
data/rules/programs_2026.json and spoken by data/content/programs.{en,es}.json (docs/SPEC.md §5.10 and §6.6).

Stub with the final signatures. Every method raises NotImplementedError, except that an engine built with
enabled=False (GP_PROGRAMS=0) answers None / False everywhere, so the app can be wired before the engine exists.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Lang
from gatorplate.contracts.errors import InvalidRequest
from gatorplate.contracts.programs import ProgramsMeta, ProgramsResult, UnlockedView


class Programs:
    def __init__(self, *, enabled: bool = True, table_path: Path | None = None, content_dir: Path | None = None,
                 guards_path: Path | None = None, public_base_url: str = "") -> None:
        self.enabled = enabled
        self.table_path = table_path
        self.content_dir = content_dir
        self.guards_path = guards_path
        self.public_base_url = public_base_url

    @classmethod
    def from_settings(cls, settings: Any) -> Programs:
        """Reads GP_PROGRAMS, GP_PROGRAMS_TABLE and GP_PUBLIC_BASE_URL."""
        return cls(enabled=settings.programs, table_path=settings.programs_table_path,
                   content_dir=settings.content_dir, guards_path=settings.guards_path,
                   public_base_url=settings.public_base_url)

    def evaluate(self, case: Case, *, today: date) -> ProgramsResult | None:
        if not self.enabled:
            return None
        raise NotImplementedError

    def view(self, case: Case, *, lang: Lang, today: date) -> UnlockedView | None:
        if not self.enabled:
            return None
        raise NotImplementedError

    def validate_answers(self, case: Case, answers: dict[str, str], *, today: date) -> dict[str, str]:
        if not self.enabled:
            # Never reached: with GP_PROGRAMS=0 the card endpoints answer 404 first.
            raise InvalidRequest("Other programs are switched off.")
        raise NotImplementedError

    def can_mark(self, case: Case, program: str, *, today: date) -> bool:
        if not self.enabled:
            return False
        raise NotImplementedError

    def meta(self) -> ProgramsMeta | None:
        if not self.enabled:
            return None
        raise NotImplementedError

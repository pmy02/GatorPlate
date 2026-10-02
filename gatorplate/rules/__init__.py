"""Rules engine (RulesPort): CalFresh tier, estimate, value of information and dates from the rules table.

Stub with the final signatures; the engine is built in stage 1 (docs/SPEC.md §5).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from gatorplate.contracts.case import Case, Tracking
from gatorplate.contracts.rules_io import Evaluation, Facts, FlipPlan, RulesMeta
from gatorplate.contracts.slots import MoneyBasis


class Rules:
    """Pure: no I/O except loading the table at construction."""

    def __init__(self, table_path: Path, *, tz: str = "America/Los_Angeles") -> None:
        self.table_path = table_path
        self.tz = tz

    @classmethod
    def from_settings(cls, settings) -> Rules:
        return cls(settings.rules_table_path, tz=settings.tz)

    def meta(self) -> RulesMeta:
        raise NotImplementedError

    def valid_on(self, day: date) -> bool:
        raise NotImplementedError

    def normalize_money(self, basis: MoneyBasis) -> Decimal:
        raise NotImplementedError

    def facts_from_case(self, case: Case, *, today: date) -> Facts:
        raise NotImplementedError

    def evaluate(self, facts: Facts, *, today: date) -> Evaluation:
        raise NotImplementedError

    def flip_plan(self, case: Case, *, today: date, budget: int) -> FlipPlan:
        raise NotImplementedError

    def apply(self, case: Case, *, now: datetime, turn: int | None = None) -> Case:
        raise NotImplementedError

    def filing_date(self, now: datetime) -> date:
        raise NotImplementedError

    def compute_tracking(self, tracking: Tracking) -> Tracking:
        raise NotImplementedError

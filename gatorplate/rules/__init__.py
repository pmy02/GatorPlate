"""Rules engine (RulesPort): CalFresh tier, estimate, value of information and dates from the rules table
(docs/SPEC.md §5).

Pure: the only I/O is loading the table at construction. Every number comes from the table; money is Decimal;
dates are America/Los_Angeles. The language model never computes anything here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from gatorplate.contracts.case import Case, Tracking
from gatorplate.contracts.rules_io import Evaluation, Facts, FlipPlan, RulesMeta, RulesTable
from gatorplate.contracts.slots import MoneyBasis
from gatorplate.rules import apply as _apply
from gatorplate.rules import dates, engine, money, voi
from gatorplate.rules.table import load_table
from gatorplate.rules.table import valid_on as _valid_on


class Rules:
    """Pure: no I/O except loading the table at construction."""

    def __init__(self, table_path: Path, *, tz: str = "America/Los_Angeles") -> None:
        self.table_path = table_path
        self.tz = tz
        self.table: RulesTable = load_table(Path(table_path))

    @classmethod
    def from_settings(cls, settings) -> Rules:
        return cls(settings.rules_table_path, tz=settings.tz)

    def meta(self) -> RulesMeta:
        return self.table.meta()

    def valid_on(self, day: date) -> bool:
        return _valid_on(self.table, day)

    def normalize_money(self, basis: MoneyBasis) -> Decimal:
        """Monthly amount of a stated pay basis, converted once (cents half-up)."""
        return money.normalize(self.table, basis)

    def facts_from_case(self, case: Case, *, today: date) -> Facts:
        """The all-defaults world: open question-picker slots at their natural or conservative defaults."""
        a = voi.analyze(self.table, case, today=today)
        return a.default_world.facts

    def evaluate(self, facts: Facts, *, today: date) -> Evaluation:
        return engine.evaluate(self.table, facts, today=today)

    def flip_plan(self, case: Case, *, today: date, budget: int) -> FlipPlan:
        """The flip questions to ask now (at most `budget`, in asking order) and the slots that are not asked."""
        a = voi.analyze(self.table, case, today=today, budget=budget, final=False)
        assert a.plan is not None
        return a.plan

    def apply(self, case: Case, *, now: datetime, turn: int | None = None) -> Case:
        return _apply.apply(self.table, case, now=now, tz=self.tz, turn=turn)

    def filing_date(self, now: datetime) -> date:
        return dates.filing_date(self.table, now, self.tz)

    def compute_tracking(self, tracking: Tracking) -> Tracking:
        return dates.compute_tracking(self.table, tracking)

    # ------------------------------------------------------------------------------------------ helpers
    # Not part of RulesPort; the dialogue may use them for the expedited screen and the income-band questions.

    def expedited_screen(self, case: Case, *, today: date) -> bool:
        """Ask the cash question? Gross under the income limit, or own housing cost + utility allowance above gross,
        in any remaining world (the unanswered utility and rent questions included)."""
        a = voi.analyze(self.table, case, today=today)
        return voi.expedited_screen(self.table, a.worlds or [a.default_world])

    def income_band_edges(self, household_size: int) -> list[int]:
        """The `ask.income_band` edges {a, b} for a household size (one person: 1,000 and 2,000)."""
        return voi.income_band_edges(self.table, household_size)

    def earned_split_point(self, case: Case, *, today: date) -> int | None:
        """The `flip.earned_split` amount {x}, or None unless the work income is an unclear answer or a band."""
        return voi.split_point(self.table, case, today=today)

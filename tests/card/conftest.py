"""Card test factories: cases shaped like the golden personas (docs/SPEC.md §5.8) and a fake ProgramsPort."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gatorplate.card import CardBuilder
from gatorplate.contracts.case import CardRef, Case, FirstMonth, Tracking, YellowLine
from gatorplate.contracts.common import Lang
from gatorplate.contracts.programs import UnlockedView
from gatorplate.contracts.slots import Slot

ROOT = Path(__file__).resolve().parents[2]
# Fri 2026-10-02 10:00 Pacific (the default test clock) as UTC.
NOW = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)
TOKEN = "tok_Card_0123456789abc"
CREATED = datetime(2026, 10, 2, 16, 58, 58, tzinfo=UTC)


def slot(value: str, *, source: str = "llm", state: str = "clear") -> Slot:
    return Slot(value=value, state=state, source=source)


def make_case(*, reason: str | None, tier: str | None = None, estimate: int | None = None, floor: bool = False,
              expedited: str | None = None, first_month: FirstMonth | None = None,
              slots: dict[str, str | Slot] | None = None, flags: list[str] | None = None,
              yellow: list[YellowLine] | None = None, reviewed_at: datetime | None = None, status: str = "new",
              lang: str = "en", code: str = "K7Q-2FM", card: bool = True, tracking: Tracking | None = None,
              **extra: Any) -> Case:
    if tier is None and reason is not None and not reason.startswith("info."):
        tier = reason.split(".")[0]
    built = {k: (v if isinstance(v, Slot) else slot(v)) for k, v in (slots or {}).items()}
    return Case(
        id="c_card000001", code=code, created_at=CREATED, updated_at=CREATED, lang=lang, channel="phone", live=False,
        status=status, tier=tier, reason_code=reason, estimate_monthly=estimate, estimate_is_floor=floor,
        expedited_possible=expedited, first_month=first_month, slots=built, flags=flags or [],
        yellow_lines=yellow or [], reviewed_at=reviewed_at, tracking=tracking or Tracking(),
        card=CardRef(token=TOKEN, created_at=CREATED, expires_at=CREATED + timedelta(days=7)) if card else None,
        **extra,
    )


def first_month(amount: int, filed: date = date(2026, 10, 2), days: int = 30) -> FirstMonth:
    return FirstMonth(apply_date=filed, filed_on=filed, amount=amount, days_counted=days, month_label="October")


MARIA_SLOTS = {
    "consent": "true", "level": "undergrad", "units": "12", "age": "20", "lives_with_parent": "false",
    "roommates": "true", "roommates_count": "2", "household_food": "separate", "earned_monthly": "900.00",
    "other_cash_monthly": "0.00", "rent_share": "1100.00", "rent_paid_by_others_to_landlord": "0.00",
    "cash_on_hand": "1000.00",
}


def maria(**over: Any) -> Case:
    """G1: likely $306, expedited no, first month $296 on Fri 2026-10-02."""
    args: dict[str, Any] = dict(reason="likely", estimate=306, expedited="no", first_month=first_month(296),
                                slots=dict(MARIA_SLOTS))
    args.update(over)
    return make_case(**args)


def sofia(**over: Any) -> Case:
    """G3: 19, lives with her parents (Spanish, web) -> coordinator.parent_household."""
    args: dict[str, Any] = dict(reason="coordinator.parent_household", lang="es", code="S4F-9Q2",
                                slots={"consent": "true", "level": "undergrad", "units": "12", "age": "19",
                                       "lives_with_parent": "true"})
    args.update(over)
    return make_case(**args)


def jamal(**over: Any) -> Case:
    """G4: 24, couch-surfing, pays nothing, no income, cash $40 -> likely $306, expedited yes."""
    args: dict[str, Any] = dict(reason="likely", estimate=306, expedited="yes", first_month=first_month(296),
                                code="P2X-6TC",
                                slots={"consent": "true", "level": "undergrad", "units": "12", "age": "24",
                                       "lives_with_parent": "false", "homeless": "true", "household_food": "separate",
                                       "earned_monthly": "0.00", "other_cash_monthly": "0.00",
                                       "homeless_shelter_cost_monthly": "0.00", "cash_on_hand": "40.00"})
    args.update(over)
    return make_case(**args)


def boundary(**over: Any) -> Case:
    """G8: earned $2,660 (= the limit), rent $1,100 -> likely $25 (minimum), above the 130% line."""
    args: dict[str, Any] = dict(reason="likely", estimate=25, expedited="no", first_month=first_month(24),
                                slots={"consent": "true", "level": "undergrad", "units": "12", "age": "21",
                                       "household_food": "alone", "earned_monthly": "2660.00",
                                       "other_cash_monthly": "0.00", "rent_share": "1100.00"})
    args.update(over)
    return make_case(**args)


class FakePrograms:
    """A ProgramsPort fake: view() answers the given view (or raises the given error) and records its calls."""

    def __init__(self, view: UnlockedView | None = None, error: Exception | None = None) -> None:
        self._view = view
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def view(self, case: Case, *, lang: Lang, today: date) -> UnlockedView | None:
        self.calls.append({"case": case.id, "lang": Lang(lang), "today": today})
        if self._error is not None:
            raise self._error
        return self._view

    def evaluate(self, case: Case, *, today: date) -> None:
        return None

    def validate_answers(self, case: Case, answers: dict[str, str], *, today: date) -> dict[str, str]:
        return answers

    def can_mark(self, case: Case, program: str, *, today: date) -> bool:
        return False

    def meta(self) -> None:
        return None


def fixture_unlocked(lang: str = "en") -> UnlockedView:
    """The hand-built UnlockedView of Maria's card fixture (no answers yet)."""
    data = json.loads((ROOT / "web" / "fixtures" / f"card_maria_{lang}.json").read_text(encoding="utf-8"))
    return UnlockedView.model_validate(data["unlocked"])


@pytest.fixture(scope="session")
def builder() -> CardBuilder:
    return CardBuilder()


@pytest.fixture(scope="session")
def card_content() -> dict[str, dict[str, Any]]:
    return {lang: json.loads((ROOT / "data" / "content" / f"card.{lang}.json").read_text(encoding="utf-8"))
            for lang in ("en", "es")}


@pytest.fixture(scope="session")
def kit() -> SimpleNamespace:
    """The factories above, for test modules (with --import-mode=importlib a conftest is not importable)."""
    return SimpleNamespace(NOW=NOW, TOKEN=TOKEN, CREATED=CREATED, ROOT=ROOT, slot=slot, make_case=make_case,
                           first_month=first_month, maria=maria, sofia=sofia, jamal=jamal, boundary=boundary,
                           FakePrograms=FakePrograms, fixture_unlocked=fixture_unlocked, MARIA_SLOTS=MARIA_SLOTS)

"""Fixtures for the rules tests: the engine on the real table, a case builder and the demo cases."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from gatorplate.clock import default_test_clock
from gatorplate.contracts.case import AskedQuestion, Case
from gatorplate.contracts.common import Channel, Lang, Phase, SlotSource, SlotState
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.rules import Rules

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "data" / "rules" / "ca_fy2027.json"
DEMO = ROOT / "data" / "demo_cases"
TODAY = date(2026, 10, 2)  # the test clock's day (Fri 2026-10-02 10:00 Pacific)
NOW = default_test_clock().now()


@pytest.fixture(scope="session")
def rules() -> Rules:
    return Rules(TABLE)


@pytest.fixture(scope="session")
def table_raw() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def make_case(slots: dict[str, str | tuple[str | None, SlotState]], *, live: bool = True,
              phase: Phase | None = Phase.flip, lang: Lang = Lang.en, turn: int = 1,
              asked: list[AskedQuestion] | None = None, **fields) -> Case:
    """A case with the given slots (canonical values; a (value, state) pair for an unclear answer)."""
    built: dict[SlotName, Slot] = {}
    for name, raw in slots.items():
        value, state = raw if isinstance(raw, tuple) else (raw, SlotState.clear)
        built[SlotName(name)] = Slot(value=value, state=state, source=SlotSource.parser, turn=turn)
    created = datetime(2026, 10, 2, 16, 55, tzinfo=UTC)
    return Case(id="c_aaaaaaaaaa", code="K7Q-2FM", created_at=created, updated_at=created, lang=lang,
                channel=Channel.phone, live=live, phase=phase, slots=built, asked=list(asked or []), **fields)


def demo_case(name: str, now: datetime = NOW) -> Case:
    """A case built from a demo case file the way the files' `about` says (slots clear, source seed), before the
    rules run; not-live, with its asked entries."""
    demo = json.loads((DEMO / f"{name}.json").read_text(encoding="utf-8"))
    not_before = datetime.fromisoformat(demo["not_before"])
    created = min(now, max(now - timedelta(minutes=demo["minutes_ago"]), not_before))
    slots = {SlotName(k): Slot(value=v, state=SlotState.clear, source=SlotSource.seed,
                               heard=demo.get("heard", {}).get(k), heard_en=demo.get("heard_en", {}).get(k),
                               turn=demo.get("turns", {}).get(k), confirmed=k in demo.get("confirmed", []))
             for k, v in demo["slots"].items()}
    return Case(id="c_demoaaaaaa", code=demo["code"], created_at=created, updated_at=created,
                lang=Lang(demo["lang"]), channel=Channel(demo["channel"]), live=False, seeded=bool(demo.get("seed")),
                persona=demo.get("persona"), phase=None, ended_reason=demo.get("ended_reason"), slots=slots,
                asked=[AskedQuestion.model_validate(a) for a in demo.get("asked", [])])


def demo_expect(name: str) -> dict:
    return json.loads((DEMO / f"{name}.json").read_text(encoding="utf-8"))["expect"]


# Maria (G1) before the question picker runs: everything the call asked up to the rent answer.
MARIA = {"consent": "true", "level": "undergrad", "units": "12", "age": "20", "lives_with_parent": "false",
         "roommates": "true", "roommates_count": "2", "household_food": "separate", "earned_monthly": "900.00",
         "other_cash_monthly": "0.00", "rent_share": "1100.00"}

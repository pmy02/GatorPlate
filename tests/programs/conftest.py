"""Fixtures for the programs engine tests (docs/SPEC.md §5.10 and §6.6)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from gatorplate.contracts.case import CardRef, Case, ProgramAnswer, ProgramProgress
from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.programs import Computed, ProgramFacts, Programs

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
SITE = "https://gatorplate.fly.dev"
NOW = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)  # Fri 2026-10-02 10:00 Pacific
TODAY = date(2026, 10, 2)


@pytest.fixture(scope="session")
def engine() -> Programs:
    return Programs(public_base_url=SITE)


@pytest.fixture(scope="session")
def golden_doc() -> dict:
    return json.loads((DATA / "golden" / "programs_golden.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def content() -> dict[str, dict]:
    return {lang: json.loads((DATA / "content" / f"programs.{lang}.json").read_text(encoding="utf-8"))
            for lang in ("en", "es")}


@pytest.fixture(scope="session")
def run_golden(engine: Programs) -> Callable[..., Computed | None]:
    """Evaluate one golden case (or its facts with other answers) exactly as the golden file says."""

    def run(case: dict, *, answers: dict[str, str] | None = None, today: date | None = None) -> Computed | None:
        facts = ProgramFacts.model_validate(case["facts"])
        progress = {k: bool(v["applied"]) for k, v in case.get("progress", {}).items()}
        return engine.compute(facts, answers=case["answers"] if answers is None else answers, progress=progress,
                              today=today or date.fromisoformat(case["today"]))

    return run


def demo(name: str) -> dict:
    return json.loads((DATA / "demo_cases" / f"{name}.json").read_text(encoding="utf-8"))


def build_case(name: str, *, answers: dict[str, str] | None = None, progress: dict[str, bool] | None = None,
               reason_code: str | None = None, estimate: int | None = None, slots: dict[str, str] | None = None,
               token: str = "fixtureToken0123456789", code: str | None = None) -> Case:
    """A finished case built from a demo case file (the CalFresh result as its `expect` says, unless given)."""
    d = demo(name)
    expect = d.get("expect", {})
    file_answers = d.get("program_answers") or {}
    chosen = file_answers if answers is None else answers
    source = "seed" if answers is None and file_answers else "card"
    raw_slots = dict(d["slots"]) if slots is None else slots
    return Case(
        id="c_" + name.replace("_", "")[:10].ljust(10, "x"), code=code or d["code"], created_at=NOW, updated_at=NOW,
        lang=Lang(d.get("lang", "en")), channel=Channel(d.get("channel", "phone")), live=False,
        tier=expect.get("tier"), reason_code=reason_code if reason_code is not None else expect.get("reason_code"),
        estimate_monthly=estimate if estimate is not None else expect.get("estimate_monthly"),
        slots={SlotName(k): Slot(value=v) for k, v in raw_slots.items()},
        card=CardRef(token=token, created_at=NOW, expires_at=NOW),
        program_answers={q: ProgramAnswer(value=v, at=NOW, source=source) for q, v in chosen.items()},
        program_progress={k: ProgramProgress(applied=v, at=NOW) for k, v in (progress or {}).items()},
    )


@pytest.fixture(scope="session")
def make_case() -> Callable[..., Case]:
    return build_case


@pytest.fixture(scope="session")
def langs() -> tuple[Lang, Lang]:
    return (Lang.en, Lang.es)

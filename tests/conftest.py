"""Shared test fixtures. Tests use the fake language model, the fixed clock (Fri 2026-10-02 10:00 Pacific) and
settings built explicitly with every GP_* variable cleared, so nothing from the shell reaches the app."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from gatorplate.clock import FixedClock, default_test_clock
from gatorplate.config import Settings
from gatorplate.contracts.rules_io import RulesTable
from gatorplate.ids import FixedIds

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--update-snapshots", action="store_true", default=False,
                     help="rewrite tests/snapshots/*.json from the contract models (integrator only)")


@pytest.fixture
def update_snapshots(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--update-snapshots"))


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def clean_gp_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every GP_* variable from the process environment for this test."""
    for name in list(os.environ):
        if name.upper().startswith("GP_"):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A fresh database path per test (the file does not exist yet)."""
    return tmp_path / "gatorplate.db"


@pytest.fixture
def settings_test(clean_gp_env: pytest.MonkeyPatch, tmp_db: Path) -> Settings:
    """Test settings, built explicitly: GP_* cleared, fake language model, code card delivery, debug keys on."""
    return Settings(env="test", llm_provider="fake", llm_api_key=SecretStr(""), debug_keys=True, demo_mode=True,
                    live_transcript=False, card_delivery="code", daily_reset=False, db_path=tmp_db,
                    public_base_url="http://127.0.0.1:8000", programs=True)


@pytest.fixture
def fixed_clock() -> FixedClock:
    return default_test_clock()


@pytest.fixture
def fixed_ids() -> FixedIds:
    return FixedIds()


@pytest.fixture(scope="session")
def rules_table() -> RulesTable:
    return RulesTable.model_validate(json.loads((DATA / "rules" / "ca_fy2027.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def golden() -> dict[str, dict]:
    """The CalFresh golden cases by id (data/golden/golden_cases.json)."""
    data = json.loads((DATA / "golden" / "golden_cases.json").read_text(encoding="utf-8"))
    return {case["id"]: case for case in data["cases"]}


@pytest.fixture(scope="session")
def programs_table() -> dict:
    return json.loads((DATA / "rules" / "programs_2026.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def programs_golden() -> dict[str, dict]:
    data = json.loads((DATA / "golden" / "programs_golden.json").read_text(encoding="utf-8"))
    return {case["id"]: case for case in data["cases"]}

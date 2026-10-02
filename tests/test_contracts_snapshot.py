"""Every contract model's JSON Schema equals its snapshot in tests/snapshots/<Model>.json.

Drift fails the suite. Only the integrator runs `pytest --update-snapshots`, after accepting a CONTRACT_REQUESTS.md
entry."""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

import pytest
from pydantic import BaseModel

import gatorplate.contracts as contracts_pkg

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"


def contract_models() -> dict[str, type[BaseModel]]:
    models: dict[str, type[BaseModel]] = {}
    for info in pkgutil.iter_modules(contracts_pkg.__path__):
        module = importlib.import_module(f"gatorplate.contracts.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                assert obj.__name__ not in models or models[obj.__name__] is obj, f"duplicate model name {obj.__name__}"
                models[obj.__name__] = obj
    return dict(sorted(models.items()))


MODELS = contract_models()


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", list(MODELS))
def test_snapshot(name: str, update_snapshots: bool) -> None:
    path = SNAPSHOTS / f"{name}.json"
    current = schema_text(MODELS[name])
    if update_snapshots:
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(current, encoding="utf-8")
        return
    assert path.exists(), f"no snapshot for {name}: run pytest --update-snapshots (integrator only)"
    assert path.read_text(encoding="utf-8") == current, f"{name} drifted from tests/snapshots/{name}.json"


def test_no_stale_snapshots() -> None:
    stale = sorted(p.stem for p in SNAPSHOTS.glob("*.json") if p.stem not in MODELS)
    assert not stale, f"snapshots without a model: {stale}"


def test_upgrade_models_present() -> None:
    for name in ("ProgramLine", "ProgramsResult", "ProgramsMeta", "UnlockedChoice", "UnlockedQuestion",
                 "UnlockedProgram", "UnlockedView", "ProgramAnswersRequest", "ProgramProgressRequest",
                 "ProgramAnswer", "ProgramProgress", "CardRow"):
        assert name in MODELS, name

"""Live accuracy of the real language model (marker `live`).

These run only through `make test-live`, with the owner's key, in the verification stage; `make test-extract`
deselects them. Settings come from the environment that target passes (GP_LLM_PROVIDER=anthropic and
GP_LLM_API_KEY by reference), never from the cleared test settings. Without a key they skip. They report slot
accuracy on data/tests/utterances.jsonl (English and Spanish too), check that pay every two weeks is never read as
monthly (golden case G13), and write var/live_accuracy.json with the measured tokens and their cost.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from gatorplate.config import Settings
from gatorplate.extract import Understander
from tests.extract.support import ROOT, load_utterances, per_slot, understand_row

pytestmark = pytest.mark.live

# USD per million tokens (input, output), list prices; input counted at the full rate (an upper bound).
PRICES = {"claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00"))}
MIN_ACCURACY = Decimal("0.95")
CONCURRENCY = 6
_REPORT: dict[str, Any] = {}


@pytest.fixture
def live() -> Understander:
    """A fresh client per test: each test runs its own event loop."""
    settings = Settings()  # the GP_* environment of make test-live
    if settings.llm_provider != "anthropic" or not settings.llm_api_key.get_secret_value():
        pytest.skip("no language-model key: run make test-live with GP_LLM_API_KEY set")
    return Understander.from_settings(settings)


def _score(row: dict[str, Any], got: list[dict[str, Any]]) -> tuple[int, int]:
    want = per_slot(row["expect"]["observations"], with_state=False)
    allow = set(row.get("allow_extra") or [])
    have = {k: v for k, v in per_slot(got, with_state=False).items() if k in want or k not in allow}
    items = set(want) | set(have)
    correct = sum(1 for slot in want if have.get(slot) == want[slot])
    return correct, len(items)


async def _run_all(understander: Understander, rows: list[dict[str, Any]]) -> list[Any]:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(row: dict[str, Any]) -> Any:
        async with gate:
            return await understand_row(understander, row)

    return await asyncio.gather(*(one(row) for row in rows))


def test_live_slot_accuracy(live: Understander) -> None:
    rows = load_utterances()
    results = asyncio.run(_run_all(live, rows))
    totals: dict[str, list[int]] = {"all": [0, 0], "en": [0, 0], "es": [0, 0]}
    statuses: dict[str, int] = {}
    for row, result in zip(rows, results, strict=True):
        correct, items = _score(row, [o.model_dump() for o in result.observations])
        for key in ("all", row["lang"]):
            totals[key][0] += correct
            totals[key][1] += items
        statuses[result.llm.status] = statuses.get(result.llm.status, 0) + 1

    def ratio(key: str) -> Decimal:
        correct, items = totals[key]
        return (Decimal(correct) / Decimal(items)).quantize(Decimal("0.0001")) if items else Decimal(1)

    usage = live.llm_health()["usage"]
    model = live.settings.llm_model
    price = PRICES.get(model)
    cost = None
    if price is not None:
        cost = (Decimal(usage["input_tokens"]) * price[0] + Decimal(usage["output_tokens"]) * price[1]) / Decimal(
            1_000_000)
    _REPORT.update({
        "measured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "model": model, "n": len(rows),
        "accuracy": str(ratio("all")), "accuracy_en": str(ratio("en")), "accuracy_es": str(ratio("es")),
        "statuses": statuses, "calls": usage["calls"], "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_usd": str(cost.quantize(Decimal("0.0001"))) if cost is not None else None,
        "cost_per_call_usd": str((cost / usage["calls"]).quantize(Decimal("0.000001")))
        if cost is not None and usage["calls"] else None,
    })
    _write_report()
    assert ratio("all") >= MIN_ACCURACY, _REPORT


def test_live_biweekly_never_monthly(live: Understander) -> None:
    """Golden case G13: pay every two weeks must keep its period (misread as monthly it would give $306)."""
    rows = [r for r in load_utterances() if any(o["period"] == "biweek" for o in r["expect"]["observations"])]
    assert rows
    results = asyncio.run(_run_all(live, rows))
    misses = []
    for row, result in zip(rows, results, strict=True):
        periods = {o.period for o in result.observations if o.slot.value.endswith("_monthly")}
        if "biweek" not in periods:
            misses.append(row["id"])
    _REPORT["g13"] = {"lines": [r["id"] for r in rows], "misread": misses, "ok": not misses}
    _write_report()
    assert not misses


def _write_report() -> None:
    out = ROOT / "var" / "live_accuracy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_REPORT, indent=2) + "\n", encoding="utf-8")

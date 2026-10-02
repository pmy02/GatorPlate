"""Live bench of the extraction call: latency, structured-output validity, tokens and measured cost.

Run only through `make bench` (it passes GP_LLM_PROVIDER=anthropic and GP_LLM_API_KEY by reference), and only when
the owner has set the key; every call is billed. It sends N lines of data/tests/utterances.jsonl, one at a time,
through the production client with the real prompt and schema, and reports p50 / p95 latency (the brain targets
p50 <= 0.8 s and p95 <= 1.5 s per turn, with a 2.3 s model timeout), how many replies were valid structured output,
token counts and the cost computed from the measured tokens. Nothing personal is printed or stored: the report holds
counts and timings only (var/bench_llm.json).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from gatorplate.config import Settings
from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract.llm.anthropic_client import AnthropicClient
from gatorplate.extract.llm.base import UsageMetrics
from gatorplate.extract.prompt import SYSTEM_PROMPT, output_schema, user_message
from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import normalize

ROOT = Path(__file__).resolve().parent.parent
UTTERANCES = ROOT / "data" / "tests" / "utterances.jsonl"
# USD per million tokens (input, output), list prices. Prompt-cache reads cost 0.1x the input price; cache writes cost
# 1.25x for the five-minute lifetime and 2x for the one-hour lifetime the client asks for; the other input tokens are
# counted at the full rate.
PRICES = {"claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00"))}
CACHE_READ = Decimal("0.1")
CACHE_WRITE = {"5m": Decimal("1.25"), "1h": Decimal("2")}
BENCH_TIMEOUT_S = 10.0  # long enough to see the whole latency distribution; the brain cuts at GP_LLM_TIMEOUT_S


def pick(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """An even spread over the file (English and Spanish, every kind of question), deterministic."""
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def percentile(values: list[int], pct: int) -> int:
    """Nearest-rank percentile with integer math only (no float, no round())."""
    ordered = sorted(values)
    rank = -(-pct * len(ordered) // 100)  # ceil(pct * n / 100)
    return ordered[min(len(ordered), max(1, rank)) - 1]


async def bench(settings: Settings, rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = UsageMetrics(provider="anthropic")
    client = AnthropicClient(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url,
                             model=settings.llm_model, metrics=metrics)
    redactor = Redactor()
    schema = output_schema()
    latencies: list[int] = []
    statuses: dict[str, int] = {}
    for row in rows:
        text = redactor.redact(normalize(row["utterance"]), masked=bool(row.get("masked"))).text
        known = {SlotName(k): v for k, v in (row.get("known") or {}).items()}
        prompt = user_message(utterance=text, pending=PendingQuestion.model_validate(row["pending"]), known=known,
                              recent=[], last_prompt=None)
        started = time.monotonic()
        result = await client.complete(SYSTEM_PROMPT, prompt, schema, BENCH_TIMEOUT_S)
        latencies.append(int((time.monotonic() - started) * 1000))
        statuses[result.status] = statuses.get(result.status, 0) + 1
    usage = metrics.snapshot()["usage"]
    cached, written = client.cache_read_tokens, client.cache_write_tokens
    plain = max(0, usage["input_tokens"] - cached - written)
    price = PRICES.get(settings.llm_model)
    cost = None
    if price is not None:
        write = CACHE_WRITE["1h" if client.cache_ttl == "1h" else "5m"]
        cost = ((Decimal(plain) + Decimal(cached) * CACHE_READ + Decimal(written) * write) * price[0]
                + Decimal(usage["output_tokens"]) * price[1]) / Decimal(1_000_000)
    timeout_ms = int(settings.llm_timeout_s * 1000)
    calls = max(1, usage["calls"])
    return {
        "measured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model": settings.llm_model,
        "n": len(rows),
        "statuses": statuses,
        "structured_output_ok": statuses.get("ok", 0),
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95), "max": max(latencies)},
        "over_model_timeout": sum(1 for ms in latencies if ms > timeout_ms),
        "tokens": {"input": usage["input_tokens"], "output": usage["output_tokens"],
                   "input_per_call": usage["input_tokens"] // calls,
                   "output_per_call": usage["output_tokens"] // calls,
                   "cache_read": cached, "cache_write": written,
                   "cache_read_per_call": cached // calls},
        "cost_usd": str(cost.quantize(Decimal("0.0001"))) if cost is not None else None,
        "cost_per_call_usd": str((cost / calls).quantize(Decimal("0.000001"))) if cost is not None else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=30, help="number of utterances to send (each one is a billed call)")
    ap.add_argument("--out", default=str(ROOT / "var" / "bench_llm.json"), help="where to write the report")
    args = ap.parse_args()
    settings = Settings()
    if settings.llm_provider != "anthropic" or not settings.llm_api_key.get_secret_value():
        print("bench: no language-model key (run make bench after the owner sets GP_LLM_API_KEY)", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in UTTERANCES.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = asyncio.run(bench(settings, pick(rows, max(1, args.n))))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    p95 = report["latency_ms"]["p95"]
    if p95 > 1200:
        print(f"bench: model p95 {p95} ms is over 1.2 s; the owner may turn on GP_LLM_HEDGE_MS", file=sys.stderr)
    return 0 if report["structured_output_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

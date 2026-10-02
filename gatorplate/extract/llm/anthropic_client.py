"""The production provider: one structured-output Messages API call per turn through the official SDK.

- The key and the base URL are always passed explicitly from GP_* settings; no client is built without a key (the
  brain then runs in closed mode). Headers the SDK would merge from the process environment are dropped, so only
  GP_* settings configure the client (every process also starts with a clean environment).
- `max_retries=0`: the turn budget has no room for SDK retries. A provider error (not a timeout) may be retried once
  on GP_LLM_FALLBACK_MODEL when time is left.
- Structured output (`output_config.format` with the ExtractionResult schema); the reply is validated again here.
  A refusal, a cut-off reply or invalid JSON is a failed extraction, never a guess.
- At most 8 calls at a time (the daily turn cap is the Understander's); an optional hedge
  (GP_LLM_HEDGE_MS > 0 sends one identical second request when the first is slow, and takes the first answer).
- Logs are content-free: model, latency, token counts and status only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import anthropic
from pydantic import ValidationError

from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome
from gatorplate.extract.llm.base import UsageMetrics, outcome

log = logging.getLogger("gatorplate.llm")

MAX_TOKENS = 1024
CONCURRENCY = 8
FALLBACK_MIN_S = 0.3  # time a fallback attempt needs to be worth sending
# Models that still accept a sampling temperature; the SDK no longer has the argument, so it goes in the body.
_DETERMINISTIC_MODELS = frozenset({"claude-haiku-4-5"})


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, *, api_key: str, base_url: str, model: str, fallback_model: str = "", hedge_ms: int = 0,
                 metrics: UsageMetrics | None = None, sdk: Any = None) -> None:
        if not api_key:
            raise ValueError("no language-model key: run in closed mode instead of building a client")
        self.model = model
        self.fallback_model = fallback_model
        self.hedge_ms = max(0, int(hedge_ms))
        self.metrics = metrics or UsageMetrics(provider=self.provider)
        self.metrics.provider = self.provider
        self._sems: dict[int, asyncio.Semaphore] = {}
        if sdk is None:
            sdk = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=0)
            # Only GP_* settings configure the client: drop any header merged from the process environment.
            sdk._custom_headers = {}
        self.sdk = sdk

    # ------------------------------------------------------------------------------------------ public
    async def complete(self, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                       ) -> ExtractOutcome:
        if timeout_s <= 0:
            return outcome("timeout", model=self.model)
        started = time.monotonic()
        result = await self._attempt(self.model, system, user_json, schema, timeout_s)
        if result.status == "error" and self.fallback_model:
            left = timeout_s - (time.monotonic() - started)
            if left >= FALLBACK_MIN_S:
                result = await self._attempt(self.fallback_model, system, user_json, schema, left)
        result = result.model_copy(update={"latency_ms": int((time.monotonic() - started) * 1000)})
        self.metrics.record(result)
        log.info(json.dumps({"event": "llm", "model": result.model, "status": result.status,
                             "latency_ms": result.latency_ms, "input_tokens": result.input_tokens,
                             "output_tokens": result.output_tokens}))
        return result

    # ------------------------------------------------------------------------------------------ internals
    async def _attempt(self, model: str, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                       ) -> ExtractOutcome:
        try:
            async with asyncio.timeout(timeout_s):
                async with self._semaphore():
                    message = await self._hedged(model, system, user_json, schema, timeout_s)
        except (TimeoutError, anthropic.APITimeoutError):
            return outcome("timeout", model=model)
        except (anthropic.APIConnectionError, anthropic.APIStatusError):
            return outcome("error", model=model)
        return self._read(message, model)

    def _semaphore(self) -> asyncio.Semaphore:
        """At most CONCURRENCY calls at a time, per event loop (the app runs one loop; tests may run several)."""
        loop_id = id(asyncio.get_running_loop())
        sem = self._sems.get(loop_id)
        if sem is None:
            sem = self._sems[loop_id] = asyncio.Semaphore(CONCURRENCY)
        return sem

    def _params(self, model: str, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_json}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
            "timeout": timeout_s,
        }
        if model in _DETERMINISTIC_MODELS:
            params["extra_body"] = {"temperature": 0}
        return params

    async def _create(self, params: dict[str, Any]) -> Any:
        return await self.sdk.messages.create(**params)

    async def _hedged(self, model: str, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                      ) -> Any:
        params = self._params(model, system, user_json, schema, timeout_s)
        if self.hedge_ms <= 0:
            return await self._create(params)
        first = asyncio.ensure_future(self._create(params))
        done, _ = await asyncio.wait({first}, timeout=self.hedge_ms / 1000)
        if done:
            return first.result()
        self.metrics.count_extra_call()  # the hedge is a second billed request
        second = asyncio.ensure_future(self._create(params))
        tasks = {first, second}
        try:
            while tasks:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task.exception() is None:
                        return task.result()
                if not tasks:
                    raise next(iter(done)).exception()  # type: ignore[misc]
        finally:
            for task in (first, second):
                if not task.done():
                    task.cancel()
        raise RuntimeError("unreachable")  # pragma: no cover

    def _read(self, message: Any, model: str) -> ExtractOutcome:
        usage = getattr(message, "usage", None)
        tokens_in = None
        tokens_out = None
        if usage is not None:
            tokens_in = int(getattr(usage, "input_tokens", 0) or 0) + int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0) + int(
                getattr(usage, "cache_read_input_tokens", 0) or 0)
            tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        common = {"model": getattr(message, "model", None) or model, "input_tokens": tokens_in,
                  "output_tokens": tokens_out}
        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            return outcome("refused", **common)
        if stop == "max_tokens":
            return outcome("invalid", **common)
        text = "".join(getattr(block, "text", "") for block in getattr(message, "content", [])
                       if getattr(block, "type", None) == "text")
        try:
            result = ExtractionResult.model_validate_json(text)
        except (ValidationError, ValueError):
            return outcome("invalid", **common)
        return outcome("ok", result=result, **common)

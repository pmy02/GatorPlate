"""The production provider: one structured-output Messages API call per turn through the official SDK.

- The key and the base URL are always passed explicitly from GP_* settings; no client is built without a key (the
  brain then runs in closed mode). Headers the SDK would merge from the process environment are dropped, so only
  GP_* settings configure the client (every process also starts with a clean environment).
- `max_retries=0`: the turn budget has no room for SDK retries. A provider error (not a timeout) may be retried once
  on GP_LLM_FALLBACK_MODEL when time is left.
- Structured output (`output_config.format` with the ExtractionResult schema); the reply is validated again here.
  A refusal, a cut-off reply or invalid JSON is a failed extraction, never a guess.
- At most 8 calls at a time (the daily turn cap is the Understander's); an optional hedge
  (GP_LLM_HEDGE_MS > 0 sends one identical second request when the first is slow, takes the first answer and cancels
  the other; the second request is billed and counted as a call).
- One pooled HTTP client that keeps idle TLS connections for five minutes (the HTTP library's default is five
  seconds, shorter than the gap between two phone turns, so nearly every turn paid for a new handshake). `prewarm()`
  opens or refreshes those connections with a plain HEAD request to the configured base URL: no model call, no key,
  no body, at most once a minute; the brain schedules it when a call starts and never waits on it.
- The fixed system text carries the cache marker. The model caches only a prefix of at least its minimum length
  (4,096 tokens for claude-haiku-4-5), so the prompt is kept above it (tests/extract/test_prompt.py); cache reads and
  writes are counted and logged apart from the other input tokens, so a live run shows whether the cache is used.
  The marker asks for the one-hour lifetime: calls come in bursts (a demo table, a class visit) with gaps longer than
  the default five minutes, and a cold prefix makes the first model turn of the next call the slowest one. A provider
  that rejects the lifetime (HTTP 400) gets the plain marker from then on, and that turn is retried once without it.
- Logs are content-free: model, latency, token counts (cache reads and writes included) and status; a hedged turn
  adds one line saying which request answered ("first", "second" or "none").
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import anthropic
import httpx2
from pydantic import ValidationError

from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome
from gatorplate.extract.llm.base import UsageMetrics, outcome

log = logging.getLogger("gatorplate.llm")

MAX_TOKENS = 1024
CONCURRENCY = 8
FALLBACK_MIN_S = 0.3  # time a fallback attempt (or a hedge request) needs to be worth sending
CACHE_TTL = "1h"  # prompt-cache lifetime asked for on the system prompt (the provider's default is five minutes)
# Models that still accept a sampling temperature; the SDK no longer has the argument, so it goes in the body.
_DETERMINISTIC_MODELS = frozenset({"claude-haiku-4-5"})
# Connection pool: idle connections live five minutes (turns of one call are seconds apart; a call lasts about two
# minutes). Up to two requests per call slot (the hedge), plus room for a pre-connect.
KEEPALIVE_EXPIRY_S = 300.0
POOL_LIMITS = httpx2.Limits(max_connections=2 * CONCURRENCY + 4, max_keepalive_connections=2 * CONCURRENCY,
                            keepalive_expiry=KEEPALIVE_EXPIRY_S)
PREWARM_EVERY_S = 60.0  # at most one pre-connect a minute, however many calls start
PREWARM_TIMEOUT_S = 5.0


def build_http_client() -> httpx2.AsyncClient:
    """The SDK's own default HTTP client (its timeouts, TCP keep-alive and proxy handling) with the long-lived pool."""
    return anthropic.DefaultAsyncHttpxClient(limits=POOL_LIMITS)


def _quiet(task: asyncio.Future[Any]) -> None:
    """Done callback of a request nobody waits for any more: its late error is retrieved and dropped."""
    if not task.cancelled():
        task.exception()


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, *, api_key: str, base_url: str, model: str, fallback_model: str = "", hedge_ms: int = 0,
                 metrics: UsageMetrics | None = None, sdk: Any = None,
                 http_client: httpx2.AsyncClient | None = None) -> None:
        if not api_key:
            raise ValueError("no language-model key: run in closed mode instead of building a client")
        self.model = model
        self.fallback_model = fallback_model
        self.hedge_ms = max(0, int(hedge_ms))
        self.metrics = metrics or UsageMetrics(provider=self.provider)
        self.metrics.provider = self.provider
        self._sems: dict[int, asyncio.Semaphore] = {}
        self.cache_ttl: str | None = CACHE_TTL  # None after the provider rejected it: the plain five-minute marker
        self._rejected = False  # the last attempt was refused as a bad request (HTTP 400)
        # Since process start, content-free: input tokens served from the prompt cache and written to it (both are
        # also inside the outcome's input_tokens, which counts every input token).
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.http: httpx2.AsyncClient | None = None  # the pooled client, when this class built the SDK client
        self._prewarmed_at: float | None = None
        if sdk is None:
            self.http = http_client or build_http_client()
            sdk = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=0, http_client=self.http)
            # Only GP_* settings configure the client: drop any header merged from the process environment.
            sdk._custom_headers = {}
        self.sdk = sdk

    async def prewarm(self) -> bool:
        """Open (or refresh) pooled TLS connections to the API host without a model call: a HEAD request to the
        configured base URL, sent with no key, no body and no redirect. One connection, or two with the hedge on (a
        hedged turn sends two requests at once). At most once per PREWARM_EVERY_S; every error is swallowed. True when
        a pre-connect was attempted."""
        http = self.http
        if http is None:
            return False
        now = time.monotonic()
        if self._prewarmed_at is not None and now - self._prewarmed_at < PREWARM_EVERY_S:
            return False
        self._prewarmed_at = now
        url = str(self.sdk.base_url)
        wanted = 2 if self.hedge_ms > 0 else 1
        results = await asyncio.gather(*(self._touch(http, url) for _ in range(wanted)), return_exceptions=True)
        log.info(json.dumps({"event": "llm_preconnect", "connections": wanted,
                             "ok": sum(1 for r in results if r is True),
                             "ms": int((time.monotonic() - now) * 1000)}))
        return True

    @staticmethod
    async def _touch(http: httpx2.AsyncClient, url: str) -> bool:
        try:
            response = await http.head(url, follow_redirects=False, timeout=httpx2.Timeout(PREWARM_TIMEOUT_S))
        except Exception:  # noqa: BLE001 - a failed pre-connect only means the next turn connects on its own
            return False
        return response.status_code < 500

    # ------------------------------------------------------------------------------------------ public
    async def complete(self, system: str, user_json: str, schema: dict[str, Any], timeout_s: float
                       ) -> ExtractOutcome:
        if timeout_s <= 0:
            return outcome("timeout", model=self.model)
        started = time.monotonic()
        hedge: list[str] = []  # "first" | "second" per hedged request: which of the two answered ("none": neither)
        result, cache = await self._attempt(self.model, system, user_json, schema, timeout_s, hedge)
        if result.status == "error" and self._rejected and self.cache_ttl is not None:
            self.cache_ttl = None  # the cache lifetime may be what the provider refused: never ask for it again
            left = timeout_s - (time.monotonic() - started)
            if left >= FALLBACK_MIN_S:
                result, cache = await self._attempt(self.model, system, user_json, schema, left, hedge)
        if result.status == "error" and self.fallback_model:
            left = timeout_s - (time.monotonic() - started)
            if left >= FALLBACK_MIN_S:
                result, cache = await self._attempt(self.fallback_model, system, user_json, schema, left, hedge)
        result = result.model_copy(update={"latency_ms": int((time.monotonic() - started) * 1000)})
        self.metrics.record(result)
        self.cache_read_tokens += cache[0]
        self.cache_write_tokens += cache[1]
        self.metrics.record_cache(cache[0], cache[1])  # /healthz llm.usage prices them apart
        log.info(json.dumps({"event": "llm", "model": result.model, "status": result.status,
                             "latency_ms": result.latency_ms, "input_tokens": result.input_tokens,
                             "cache_read_input_tokens": cache[0], "cache_creation_input_tokens": cache[1],
                             "output_tokens": result.output_tokens}))
        if hedge:  # a hedged turn: which of the two requests answered, so the hedge's worth can be read from logs
            log.info(json.dumps({"event": "llm_hedge", "answered": hedge[-1], "status": result.status}))
        return result

    # ------------------------------------------------------------------------------------------ internals
    async def _attempt(self, model: str, system: str, user_json: str, schema: dict[str, Any], timeout_s: float,
                       hedge: list[str]) -> tuple[ExtractOutcome, tuple[int, int]]:
        """The outcome and the (cache read, cache write) input tokens of one request (two when hedged)."""
        self._rejected = False
        params = self._params(model, system, user_json, schema, timeout_s)
        try:
            async with asyncio.timeout(timeout_s):
                async with self._semaphore():
                    message = await self._hedged(params, time.monotonic() + timeout_s, hedge)
        except (TimeoutError, anthropic.APITimeoutError):
            return outcome("timeout", model=model), (0, 0)
        except anthropic.APIStatusError as exc:
            self._rejected = getattr(exc, "status_code", None) == 400
            return outcome("error", model=model), (0, 0)
        except anthropic.APIConnectionError:
            return outcome("error", model=model), (0, 0)
        usage = getattr(message, "usage", None)
        cache = (int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                 int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
        return self._read(message, model), cache

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
            "system": [{"type": "text", "text": system, "cache_control": self._cache_control()}],
            "messages": [{"role": "user", "content": user_json}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
            "timeout": timeout_s,
        }
        if model in _DETERMINISTIC_MODELS:
            params["extra_body"] = {"temperature": 0}
        return params

    def _cache_control(self) -> dict[str, str]:
        marker = {"type": "ephemeral"}
        if self.cache_ttl is not None:
            marker["ttl"] = self.cache_ttl
        return marker

    async def _create(self, params: dict[str, Any]) -> Any:
        return await self.sdk.messages.create(**params)

    async def _hedged(self, params: dict[str, Any], deadline: float, hedge: list[str]) -> Any:
        """One request; with the hedge on, a second identical request when the first has not answered after
        GP_LLM_HEDGE_MS (and enough time is left for it to answer). The first successful answer wins. A request still
        running is cancelled on every way out (an answer, an error, the attempt's deadline), and its late error is
        swallowed. Both fail: the first request's error is raised. The second request is counted as a billed call."""
        if self.hedge_ms <= 0:
            return await self._create(params)
        first = asyncio.ensure_future(self._create(params))
        tasks = [first]
        try:
            done, _ = await asyncio.wait(tasks, timeout=self.hedge_ms / 1000)
            if not done and deadline - time.monotonic() >= FALLBACK_MIN_S:
                self.metrics.count_extra_call()
                tasks.append(asyncio.ensure_future(self._create(params)))
                hedge.append("none")  # sent; replaced by the request that answers, if one does
            pending = set(tasks)
            errors: dict[int, BaseException] = {}
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(done, key=tasks.index):
                    error = task.exception()
                    if error is None:
                        if len(tasks) > 1:
                            hedge[-1] = "first" if task is first else "second"
                        return task.result()
                    errors[tasks.index(task)] = error
            raise errors[min(errors)]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
                task.add_done_callback(_quiet)

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

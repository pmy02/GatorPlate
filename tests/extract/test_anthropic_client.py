"""The production client against a stub of the SDK (no network): request shape, reply handling, deadlines,
fallback model, hedge, daily cap and usage counters."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from gatorplate.extract.llm.anthropic_client import AnthropicClient
from gatorplate.extract.prompt import SYSTEM_PROMPT, output_schema

GOOD = {"observations": [{"slot": "rent_share", "value": "1100", "period": "month", "hours_per_week": None,
                          "state": "clear", "quote": "Eleven hundred", "quote_en": None}],
        "intents": [], "answered_pending": "yes", "lang": "en", "side_question": None, "requested_language": None}


def message(text: str = json.dumps(GOOD), stop: str = "end_turn", model: str = "claude-haiku-4-5") -> Any:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, model=model,
                           usage=SimpleNamespace(input_tokens=1800, output_tokens=60, cache_creation_input_tokens=0,
                                                 cache_read_input_tokens=200))


class StubSDK:
    def __init__(self, replies: list[Any], delay: float = 0.0) -> None:
        self.replies = list(replies)
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **params: Any) -> Any:
        self.calls.append(params)
        if self.delay:
            await asyncio.sleep(self.delay)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def client(sdk: StubSDK, **kw: Any) -> AnthropicClient:
    params = {"api_key": "fake-key", "base_url": "https://example.invalid", "model": "claude-haiku-4-5"}
    params.update(kw)
    return AnthropicClient(sdk=sdk, **params)


def status_error(code: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    response = httpx2.Response(code, request=request)
    return anthropic.APIStatusError("provider error", response=response, body=None)


def test_never_built_without_a_key() -> None:
    with pytest.raises(ValueError):
        AnthropicClient(api_key="", base_url="https://example.invalid", model="claude-haiku-4-5")


async def test_request_shape_and_ok_reply() -> None:
    sdk = StubSDK([message()])
    c = client(sdk)
    out = await c.complete(SYSTEM_PROMPT, '{"utterance":"Eleven hundred."}', output_schema(), 2.3)
    assert out.status == "ok" and out.result is not None and out.result.observations[0].value == "1100"
    assert out.input_tokens == 2000 and out.output_tokens == 60 and out.model == "claude-haiku-4-5"
    (params,) = sdk.calls
    assert params["model"] == "claude-haiku-4-5" and params["timeout"] == 2.3
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["output_config"]["format"]["schema"] == output_schema()
    assert params["messages"] == [{"role": "user", "content": '{"utterance":"Eleven hundred."}'}]
    assert params["system"][0]["text"] == SYSTEM_PROMPT and params["system"][0]["cache_control"]["type"] == "ephemeral"
    assert params["extra_body"] == {"temperature": 0}  # deterministic sampling on the configured model
    assert "temperature" not in params and "thinking" not in params
    snap = c.metrics.snapshot()
    assert snap["status"] == "ok" and snap["usage"] == {"calls": 1, "input_tokens": 2000, "output_tokens": 60}


async def test_other_models_get_no_temperature() -> None:
    sdk = StubSDK([message()])
    await client(sdk, model="other-model").complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert "extra_body" not in sdk.calls[0]


@pytest.mark.parametrize("reply,status", [
    (message(stop="refusal"), "refused"),
    (message(stop="max_tokens"), "invalid"),
    (message(text="not json"), "invalid"),
    (message(text=json.dumps({**GOOD, "extra": 1})), "invalid"),
    (message(text=json.dumps({**GOOD, "intents": ["approve_me"]})), "invalid"),
])
async def test_bad_replies(reply: Any, status: str) -> None:
    c = client(StubSDK([reply]))
    out = await c.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == status and out.result is None
    assert c.metrics.snapshot()["status"] == "error"


async def test_timeout_within_budget() -> None:
    c = client(StubSDK([message()], delay=5.0))
    started = time.monotonic()
    out = await c.complete(SYSTEM_PROMPT, "{}", {}, 0.2)
    assert out.status == "timeout" and time.monotonic() - started < 0.25


async def test_sdk_timeout_error_is_a_timeout() -> None:
    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    c = client(StubSDK([anthropic.APITimeoutError(request=request)]), fallback_model="fallback-model")
    out = await c.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "timeout"  # never retried on the fallback model


async def test_provider_error_uses_the_fallback_model_once() -> None:
    sdk = StubSDK([status_error(529), message(model="fallback-model")])
    out = await client(sdk, fallback_model="fallback-model").complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "ok" and [c["model"] for c in sdk.calls] == ["claude-haiku-4-5", "fallback-model"]
    sdk = StubSDK([status_error(500)])
    out = await client(sdk).complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "error" and len(sdk.calls) == 1
    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    sdk = StubSDK([anthropic.APIConnectionError(request=request)])
    assert (await client(sdk).complete(SYSTEM_PROMPT, "{}", {}, 2.3)).status == "error"


async def test_no_time_left() -> None:
    sdk = StubSDK([message()])
    assert (await client(sdk).complete(SYSTEM_PROMPT, "{}", {}, 0.0)).status == "timeout"
    assert sdk.calls == []


async def test_hedge_takes_the_first_answer() -> None:
    class SlowThenFast(StubSDK):
        async def create(self, **params: Any) -> Any:
            self.calls.append(params)
            await asyncio.sleep(1.0 if len(self.calls) == 1 else 0.01)
            return message()

    sdk = SlowThenFast([message()])
    c = client(sdk, hedge_ms=50)
    started = time.monotonic()
    out = await c.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "ok" and len(sdk.calls) == 2 and time.monotonic() - started < 0.5
    assert c.metrics.snapshot()["usage"]["calls"] == 2


async def test_hedge_off_by_default() -> None:
    sdk = StubSDK([message()], delay=0.05)
    await client(sdk).complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert len(sdk.calls) == 1


async def test_concurrency_is_capped() -> None:
    active = 0
    peak = 0

    class Counting(StubSDK):
        async def create(self, **params: Any) -> Any:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return message()

    c = client(Counting([message()]))
    await asyncio.gather(*(c.complete(SYSTEM_PROMPT, "{}", {}, 2.3) for _ in range(20)))
    assert peak <= 8

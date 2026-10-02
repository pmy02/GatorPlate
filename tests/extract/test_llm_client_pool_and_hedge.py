"""The production client's connection pool, pre-connect and hedge (no network: a mock transport and fake create
functions).

- The SDK client is built on one pooled HTTP client that keeps idle connections for five minutes, with the explicit
  key and base URL and no SDK retries.
- `prewarm()` sends one HEAD request to the base URL (two with the hedge on): no key, no body, no redirect, at most
  once a minute, errors swallowed. The Understander passes it through, and does nothing with the fake provider,
  without a key or over the daily cap.
- The hedge: the first answer wins and the other request is cancelled; the second request is counted as a call; the
  attempt's deadline cancels both; a loser's late error is swallowed; both failing raises the first request's error;
  no second request when too little time is left.
"""

from __future__ import annotations

import asyncio
import gc
import json
import time
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from gatorplate.config import Settings
from gatorplate.extract import Understander
from gatorplate.extract.llm import anthropic_client as ac
from gatorplate.extract.llm.anthropic_client import AnthropicClient
from gatorplate.extract.prompt import SYSTEM_PROMPT

BASE = "https://llm.example.invalid"
GOOD = {"observations": [], "intents": [], "answered_pending": "no", "lang": "en", "side_question": None,
        "requested_language": None}


def message() -> Any:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(GOOD))], stop_reason="end_turn",
                           model="claude-haiku-4-5",
                           usage=SimpleNamespace(input_tokens=500, output_tokens=40, cache_creation_input_tokens=0,
                                                 cache_read_input_tokens=4000))


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx2.Request("POST", f"{BASE}/v1/messages"))


class Recorder:
    """A mock transport handler: records every request it sees and answers with `status` (or raises `fail`)."""

    def __init__(self, status: int = 404, fail: Exception | None = None, location: str | None = None) -> None:
        self.status, self.fail, self.location = status, fail, location
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        headers = {"location": self.location} if self.location else {}
        return httpx2.Response(self.status, headers=headers)


def pooled(recorder: Recorder, **kw: Any) -> AnthropicClient:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(recorder))
    return AnthropicClient(api_key="fake-key", base_url=BASE, model="claude-haiku-4-5", http_client=http, **kw)


class Scripted:
    """Fake create functions: request n (from 1) waits `delays[n-1]` seconds, then returns a message or raises
    `errors[n-1]`. Records which requests were cancelled and which ran to the end."""

    def __init__(self, delays: list[float], errors: list[BaseException | None] | None = None,
                 cancel_error: BaseException | None = None) -> None:
        self.delays, self.errors = delays, errors or [None] * len(delays)
        self.cancel_error = cancel_error  # raised instead of the cancellation, as a misbehaving loser would
        self.started = 0
        self.cancelled: list[int] = []
        self.finished: list[int] = []

    async def create(self, params: dict[str, Any]) -> Any:
        self.started += 1
        n = self.started
        try:
            await asyncio.sleep(self.delays[n - 1])
        except asyncio.CancelledError:
            self.cancelled.append(n)
            if self.cancel_error is not None:
                raise self.cancel_error from None
            raise
        self.finished.append(n)
        error = self.errors[n - 1]
        if error is not None:
            raise error
        return message()


def hedged(script: Scripted, hedge_ms: int = 50) -> AnthropicClient:
    client = AnthropicClient(api_key="k", base_url=BASE, model="claude-haiku-4-5", hedge_ms=hedge_ms,
                             sdk=SimpleNamespace(base_url=BASE))
    client._create = script.create  # type: ignore[method-assign]
    return client


def hedge_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "gatorplate.llm"]
    return [x for x in lines if x.get("event") == "llm_hedge"]


# ---------------------------------------------------------------------------------------------- the pool


def test_the_sdk_client_runs_on_one_pool_with_a_five_minute_keep_alive() -> None:
    client = AnthropicClient(api_key="gp-key", base_url=BASE, model="claude-haiku-4-5")
    assert client.http is not None and client.sdk._client is client.http
    pool = client.http._transport._pool
    assert pool._keepalive_expiry == ac.KEEPALIVE_EXPIRY_S == 300.0  # the HTTP library's default is 5 s
    assert pool._max_connections == 2 * ac.CONCURRENCY + 4
    assert pool._max_keepalive_connections == 2 * ac.CONCURRENCY
    # Everything else as before: explicit key and base URL, no SDK retries, the SDK's own default timeouts.
    assert client.sdk.api_key == "gp-key" and str(client.sdk.base_url).rstrip("/") == BASE
    assert client.sdk.max_retries == 0
    assert client.sdk.timeout == anthropic.DEFAULT_TIMEOUT
    assert isinstance(client.http, anthropic.DefaultAsyncHttpxClient)


def test_the_understander_builds_its_client_on_the_pool(clean_gp_env, tmp_path) -> None:
    settings = Settings(env="test", db_path=tmp_path / "x.db", llm_provider="anthropic",
                        llm_api_key=SecretStr("gp-key"), llm_base_url=BASE)
    client = Understander(settings=settings).llm
    assert isinstance(client, AnthropicClient) and client.sdk._client is client.http
    assert client.http._transport._pool._keepalive_expiry == 300.0


# ---------------------------------------------------------------------------------------------- pre-connect


async def test_prewarm_sends_one_keyless_head_to_the_base_url() -> None:
    recorder = Recorder()
    client = pooled(recorder)
    assert await client.prewarm() is True
    [request] = recorder.requests
    assert request.method == "HEAD" and str(request.url).rstrip("/") == BASE
    names = {name.lower() for name in request.headers}
    assert not names & {"x-api-key", "authorization", "anthropic-version"}
    assert "fake-key" not in json.dumps(dict(request.headers))
    assert request.content == b""


async def test_prewarm_runs_at_most_once_a_minute(monkeypatch) -> None:
    recorder = Recorder()
    client = pooled(recorder)
    now = [1000.0]
    monkeypatch.setattr(ac.time, "monotonic", lambda: now[0])
    assert await client.prewarm() is True
    now[0] += ac.PREWARM_EVERY_S - 1
    assert await client.prewarm() is False
    now[0] += 2
    assert await client.prewarm() is True
    assert len(recorder.requests) == 2


async def test_prewarm_opens_two_connections_when_the_hedge_is_on() -> None:
    recorder = Recorder()
    assert await pooled(recorder, hedge_ms=1400).prewarm() is True
    assert [r.method for r in recorder.requests] == ["HEAD", "HEAD"]


async def test_prewarm_swallows_errors_and_never_follows_a_redirect(caplog) -> None:
    failing = pooled(Recorder(fail=httpx2.ConnectError("refused")))
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        assert await failing.prewarm() is True  # attempted; the failure stays inside
    [line] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "gatorplate.llm"]
    assert line == {"event": "llm_preconnect", "connections": 1, "ok": 0, "ms": line["ms"]}
    redirect = Recorder(status=301, location="https://elsewhere.example.invalid/")
    assert await pooled(redirect).prewarm() is True
    assert [str(r.url.host) for r in redirect.requests] == ["llm.example.invalid"]


async def test_prewarm_never_follows_a_redirect_on_the_production_client_either() -> None:
    """The production client follows redirects for model calls (the SDK's default): the pre-connect still never does,
    so the key-less HEAD never goes to another host."""
    redirect = Recorder(status=307, location="https://elsewhere.example.invalid/")
    http = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(redirect))
    assert http.follow_redirects is True
    client = AnthropicClient(api_key="fake-key", base_url=BASE, model="claude-haiku-4-5", http_client=http)
    assert await client.prewarm() is True
    assert [(r.method, str(r.url.host)) for r in redirect.requests] == [("HEAD", "llm.example.invalid")]
    await http.aclose()


async def test_no_prewarm_without_the_pooled_client() -> None:
    client = AnthropicClient(api_key="k", base_url=BASE, model="claude-haiku-4-5", sdk=SimpleNamespace())
    assert await client.prewarm() is False


async def test_the_understander_passes_the_prewarm_through(settings_test) -> None:
    recorder = Recorder()
    understander = Understander(settings=settings_test, llm=pooled(recorder))
    assert await understander.prewarm_llm() is True
    assert [r.method for r in recorder.requests] == ["HEAD"]


async def test_no_prewarm_with_the_fake_provider_without_a_key_or_over_the_cap(settings_test, tmp_path) -> None:
    fake = Understander(settings=settings_test)
    assert fake.llm is not None and fake.llm.provider == "fake"
    assert await fake.prewarm_llm() is False
    no_key = Understander(settings=settings_test.model_copy(update={"llm_provider": "anthropic"}))
    assert no_key.llm is None and await no_key.prewarm_llm() is False
    recorder = Recorder()
    capped = Understander(settings=settings_test.model_copy(update={"llm_daily_turn_cap": 0}),
                          llm=pooled(recorder))
    assert await capped.prewarm_llm() is False and recorder.requests == []


async def test_a_failing_prewarm_never_raises_from_the_understander(settings_test) -> None:
    class Broken:
        provider, model = "anthropic", "claude-haiku-4-5"

        async def prewarm(self) -> bool:
            raise RuntimeError("boom")

        async def complete(self, *args: Any) -> Any:  # pragma: no cover - never called here
            raise NotImplementedError

    assert await Understander(settings=settings_test, llm=Broken()).prewarm_llm() is False


# ---------------------------------------------------------------------------------------------- hedge


async def test_the_second_request_wins_and_the_slow_first_is_cancelled(caplog) -> None:
    script = Scripted([1.0, 0.02])
    client = hedged(script)
    started = time.monotonic()
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        out = await client.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "ok" and time.monotonic() - started < 0.5
    await asyncio.sleep(0)  # let the cancellation land
    assert script.started == 2 and script.cancelled == [1] and script.finished == [2]
    assert client.metrics.snapshot()["usage"]["calls"] == 2  # the extra request is counted
    assert hedge_lines(caplog) == [{"event": "llm_hedge", "answered": "second", "status": "ok"}]


async def test_the_first_request_wins_after_the_hedge_and_the_second_is_cancelled(caplog) -> None:
    script = Scripted([0.1, 1.0])
    client = hedged(script)
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        out = await client.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    await asyncio.sleep(0)
    assert out.status == "ok" and script.finished == [1] and script.cancelled == [2]
    assert hedge_lines(caplog) == [{"event": "llm_hedge", "answered": "first", "status": "ok"}]


async def test_a_fast_answer_sends_no_second_request(caplog) -> None:
    script = Scripted([0.01])
    client = hedged(script, hedge_ms=200)
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        assert (await client.complete(SYSTEM_PROMPT, "{}", {}, 2.3)).status == "ok"
    assert script.started == 1 and client.metrics.snapshot()["usage"]["calls"] == 1
    assert hedge_lines(caplog) == []


async def test_a_first_request_that_fails_after_the_hedge_leaves_the_second_to_answer() -> None:
    script = Scripted([0.1, 0.15], errors=[connection_error(), None])
    out = await hedged(script).complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "ok" and script.finished == [1, 2]


async def test_a_fast_failure_is_not_hedged() -> None:
    script = Scripted([0.01], errors=[connection_error()])
    out = await hedged(script, hedge_ms=200).complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "error" and script.started == 1


async def test_both_failing_raise_the_first_requests_error(caplog) -> None:
    def status(code: int) -> anthropic.APIStatusError:
        request = httpx2.Request("POST", f"{BASE}/v1/messages")
        return anthropic.APIStatusError("provider error", response=httpx2.Response(code, request=request), body=None)

    script = Scripted([0.1, 0.12], errors=[status(529), connection_error()])
    client = hedged(script)
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        out = await client.complete(SYSTEM_PROMPT, "{}", {}, 2.3)
    assert out.status == "error" and client._rejected is False  # the first error (529) was raised, not a 400
    assert hedge_lines(caplog) == [{"event": "llm_hedge", "answered": "none", "status": "error"}]


async def test_the_deadline_cancels_both_requests(caplog) -> None:
    script = Scripted([5.0, 5.0])
    client = hedged(script, hedge_ms=100)
    started = time.monotonic()
    with caplog.at_level("INFO", logger="gatorplate.llm"):
        out = await client.complete(SYSTEM_PROMPT, "{}", {}, 0.5)
    assert out.status == "timeout" and time.monotonic() - started < 0.6
    await asyncio.sleep(0)
    assert script.started == 2 and sorted(script.cancelled) == [1, 2] and script.finished == []
    assert hedge_lines(caplog) == [{"event": "llm_hedge", "answered": "none", "status": "timeout"}]


async def test_a_deadline_before_the_hedge_cancels_the_first_request() -> None:
    """The hedge timer longer than the time left: the deadline cancels the only request (it used to keep running)."""
    script = Scripted([5.0])
    out = await hedged(script, hedge_ms=2000).complete(SYSTEM_PROMPT, "{}", {}, 0.2)
    await asyncio.sleep(0)
    assert out.status == "timeout" and script.started == 1 and script.cancelled == [1]


async def test_no_second_request_when_too_little_time_is_left() -> None:
    script = Scripted([5.0, 5.0])
    out = await hedged(script, hedge_ms=100).complete(SYSTEM_PROMPT, "{}", {}, 0.35)
    assert out.status == "timeout" and script.started == 1  # 0.25 s left after the timer: never worth a request


async def test_a_losers_late_error_is_swallowed() -> None:
    """A loser that raises instead of ending quietly when cancelled: its error is retrieved, never reported as an
    unhandled task exception, and the winner's answer stands."""
    loop = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        script = Scripted([1.0, 0.02], cancel_error=RuntimeError("late loser error"))
        out = await hedged(script).complete(SYSTEM_PROMPT, "{}", {}, 2.3)
        await asyncio.sleep(0.01)
        assert out.status == "ok" and script.cancelled == [1]
        del script
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)
    assert reported == []

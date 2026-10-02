"""The request-body reader and the request-log middleware, unit by unit (no app): the body cap at its exact edge, a
declared length refused before anything is read, reading that stops at the first piece past the cap, a header that is
not plain digits, scopes other than HTTP passing through untouched, Server-Timing only on Brain API routes, and one
content-free log line per request, also when the app fails."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from gatorplate.api.errors import MAX_BODY_BYTES, ApiProblem, declared_length, read_body
from gatorplate.api.timing import RequestLogMiddleware

CALL = "0d000000000000000000000000000001"


def make_request(pieces: list[bytes], *, content_length: str | None = None) -> tuple[Request, list[int]]:
    """A request whose body arrives in `pieces`; the returned list counts how often the body stream was read."""
    queue = list(pieces)
    reads: list[int] = []

    async def receive() -> dict:
        reads.append(1)
        piece = queue.pop(0) if queue else b""
        return {"type": "http.request", "body": piece, "more_body": bool(queue)}

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode("latin-1")))
    scope = {"type": "http", "method": "POST", "path": "/api/web/sessions", "query_string": b"", "headers": headers}
    return Request(scope, receive), reads


def assert_too_large(info: pytest.ExceptionInfo[ApiProblem]) -> None:
    assert info.value.code == "invalid_request" and info.value.message == "Request body too large."


# ---------------------------------------------------------------------------------------------- body reader


async def test_a_body_exactly_at_the_cap_is_kept_whole_for_later_readers() -> None:
    request, _ = make_request([b"12345", b"67890"])
    assert await read_body(request, limit=10) == b"1234567890"
    assert await request.body() == b"1234567890"


async def test_one_byte_past_the_cap_is_refused() -> None:
    request, _ = make_request([b"12345", b"678901"])
    with pytest.raises(ApiProblem) as info:
        await read_body(request, limit=10)
    assert_too_large(info)


async def test_reading_stops_at_the_first_piece_past_the_cap() -> None:
    request, reads = make_request([b"abc", b"def", b"ghi", b"jkl"])
    with pytest.raises(ApiProblem) as info:
        await read_body(request, limit=4)
    assert_too_large(info)
    assert len(reads) == 2  # the rest of the stream is never pulled into memory


async def test_a_declared_length_past_the_cap_is_refused_before_reading() -> None:
    request, reads = make_request([b"{}"], content_length=str(MAX_BODY_BYTES + 1))
    with pytest.raises(ApiProblem) as info:
        await read_body(request)
    assert_too_large(info)
    assert reads == []
    huge, reads = make_request([b"{}"], content_length="9" * 40)
    with pytest.raises(ApiProblem):
        await read_body(huge)
    assert reads == []


@pytest.mark.parametrize("header, expected", [
    ("", None), ("12", 12), ("0", 0), ("12a", None), ("-1", None), (" 12", None), ("²", None),
    ("1" * 20, 111111111111),
])
def test_declared_length_reads_only_plain_ascii_digits(header, expected) -> None:
    request, _ = make_request([], content_length=header or None)
    assert declared_length(request) == expected


async def test_a_length_header_that_is_not_ascii_digits_falls_back_to_reading() -> None:
    # "²" (superscript two) counts as a digit for str.isdigit() but int() refuses it: never a 500.
    request, _ = make_request([b'{"lang": "en"}'], content_length="²")
    assert await read_body(request) == b'{"lang": "en"}'


# ---------------------------------------------------------------------------------------------- request log


class Recorder:
    """An inner ASGI app: records what it was called with, then sends `messages` (or raises `fail`)."""

    def __init__(self, *, messages: list[dict] | None = None, route: str | None = None,
                 fail: Exception | None = None) -> None:
        self.messages, self.route, self.fail = messages or [], route, fail
        self.calls: list[tuple[dict, Any, Any]] = []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.calls.append((scope, receive, send))
        if self.route is not None:  # the router writes the matched route into the shared scope
            scope["route"] = SimpleNamespace(path=self.route)
        if self.fail is not None:
            raise self.fail
        for message in self.messages:
            await send(message)


def response(status: int = 200) -> list[dict]:
    return [{"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]},
            {"type": "http.response.body", "body": b"{}"}]


def http_scope(path: str) -> dict:
    return {"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""}


def log_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [json.loads(rec.getMessage()) for rec in caplog.records if rec.name == "gatorplate.requests"]


async def test_scopes_other_than_http_pass_through_untouched_and_unlogged(caplog) -> None:
    inner = Recorder()
    middleware = RequestLogMiddleware(inner)

    async def receive() -> dict:  # pragma: no cover - never called
        return {}

    async def send(message: dict) -> None:  # pragma: no cover - never called
        return None

    scope = {"type": "lifespan"}
    with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
        await middleware(scope, receive, send)
    assert inner.calls == [(scope, receive, send)]  # the very same callables, not wrappers
    assert log_lines(caplog) == []


async def test_brain_routes_get_server_timing_and_one_content_free_log_line(caplog) -> None:
    inner = Recorder(messages=response(), route="/v1/calls/{call_id}/turn")
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
        await RequestLogMiddleware(inner)(http_scope(f"/v1/calls/{CALL}/turn"), None, send)
    start, body = sent
    names = [name for name, _ in start["headers"]]
    assert names == [b"content-type", b"server-timing"]
    timing = dict(start["headers"])[b"server-timing"].decode()
    assert timing.startswith("brain;dur=") and float(timing.removeprefix("brain;dur=")) >= 0
    assert body == {"type": "http.response.body", "body": b"{}"}
    [line] = log_lines(caplog)
    # A /turn line always carries the model step's fields; both are null when no understanding step ran.
    assert set(line) == {"method", "route", "status", "server_ms", "llm_ms", "llm_status"}
    assert (line["llm_ms"], line["llm_status"]) == (None, None)
    assert (line["method"], line["route"], line["status"]) == ("POST", "/v1/calls/{call_id}/turn", 200)
    assert line["server_ms"] >= 0 and CALL not in json.dumps(line)


async def test_other_routes_get_no_server_timing(caplog) -> None:
    inner = Recorder(messages=response(201), route="/api/web/sessions")
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
        await RequestLogMiddleware(inner)(http_scope("/api/web/sessions"), None, send)
    assert sent == response(201)
    [line] = log_lines(caplog)
    assert (line["route"], line["status"]) == ("/api/web/sessions", 201)


async def test_a_failing_app_is_logged_as_500_and_the_error_still_propagates(caplog) -> None:
    inner = Recorder(fail=RuntimeError("detail that must stay out of the log"))

    async def send(message: dict) -> None:  # pragma: no cover - never called
        return None

    with caplog.at_level(logging.INFO, logger="gatorplate.requests"), pytest.raises(RuntimeError):
        await RequestLogMiddleware(inner)(http_scope("/api/cases/c_aaaaaaaaaa"), None, send)
    [line] = log_lines(caplog)
    assert (line["route"], line["status"]) == ("unmatched", 500)
    assert "detail" not in json.dumps(line) and "c_aaaaaaaaaa" not in json.dumps(line)

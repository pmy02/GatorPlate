"""The error envelope: every non-200 answer is {"error": {"code", "message", "retryable"}} with one of the schema's
codes (docs/BRAIN_API.md §12); no other code exists. Messages are short and generic: never request text, never a
stack trace."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gatorplate.contracts.brain_api import ERROR_STATUS, error_envelope
from gatorplate.contracts.errors import GatorPlateError

log = logging.getLogger("gatorplate.api")

DEFAULT_MESSAGES: dict[str, str] = {
    "unknown_call": "No such call.",
    "bad_signature": "Signature check failed.",
    "stale_timestamp": "Timestamp outside the allowed window.",
    "unauthorized": "Not allowed.",
    "rate_limited": "Too many requests. Try again later.",
    "invalid_request": "Request body does not match the schema.",
    "stale_seq": "seq is older than the last accepted turn.",
    "conflict": "The request conflicts with the current state.",
    "locked": "Check every yellow line first.",
    "not_found": "Not found.",
    "gone": "This link has expired.",
    "internal": "Something went wrong on our side.",
}


class ApiProblem(Exception):
    """An error answer with one of the schema's codes."""

    def __init__(self, code: str, message: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f"unknown error code {code}")
        super().__init__(code)
        self.code = code
        self.message = message or DEFAULT_MESSAGES[code]
        self.headers = headers or {}


def error_response(code: str, message: str | None = None, *, headers: dict[str, str] | None = None) -> JSONResponse:
    status, _ = ERROR_STATUS[code]
    text = (message or DEFAULT_MESSAGES[code])[:200] or DEFAULT_MESSAGES[code]
    body = error_envelope(code, text).model_dump(mode="json")
    return JSONResponse(body, status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def _problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return error_response(exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(GatorPlateError)
    async def _domain(request: Request, exc: GatorPlateError) -> JSONResponse:
        code = exc.code if exc.code in ERROR_STATUS else "internal"
        # Domain messages are written by GatorPlate's own code (never request text); the class name is the fallback.
        message = exc.message if exc.message and exc.message != exc.__class__.__name__ else None
        return error_response(code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response("invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 401:
            return error_response("unauthorized")
        if exc.status_code == 422 or exc.status_code == 400:
            return error_response("invalid_request")
        if exc.status_code == 429:
            return error_response("rate_limited")
        # 404, 405 and anything else a page or the static mount raises: the schema has no other code.
        return error_response("not_found")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error(json.dumps({"event": "internal_error", "kind": exc.__class__.__name__}))
        return error_response("internal")


MAX_BODY_BYTES = 64 * 1024  # every request body GatorPlate accepts is small (a turn's text is at most 1000 chars)


async def read_body(request: Request, *, limit: int = MAX_BODY_BYTES) -> bytes:
    """The raw body, refused with 422 invalid_request when it is larger than any valid request could be."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared[:12]) > limit:
        raise ApiProblem("invalid_request", "Request body too large.")
    # Read in chunks and stop past the limit: a chunked body has no Content-Length to check first.
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiProblem("invalid_request", "Request body too large.")
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body  # later readers of request.body() get the same bytes
    return body

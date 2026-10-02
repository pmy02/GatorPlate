"""Brain API v1 routes (docs/BRAIN_API.md): lines, start, turn, end. The HTTP layer authenticates, validates the
exact body bytes against the frozen schema, serializes requests per call and maps domain errors; the brain decides
every word, the seq rules and the stored replies.

A request rejected with 401 or 422 never reaches the brain, so it never uses up its seq.

After a successful `/start`, the platform asks the understanding to open its pooled connection to the language-model
host (no model call: `/start` never calls the language model, docs/BRAIN_API.md §9). The pre-connect runs as a
background task while the opening is spoken; `/start` never waits for it and never sees its result or failure.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from gatorplate.api.auth import Credentials, authenticate_call, signed_path, verify_gateway
from gatorplate.api.context import AppContext
from gatorplate.api.errors import ApiProblem, read_body
from gatorplate.contracts.brain_api import CALL_ID, EndRequest, StartRequest, TurnRequest
from gatorplate.contracts.common import Lang

router = APIRouter()
CALL_ID_RE = re.compile(CALL_ID)
_PRECONNECTS: set[asyncio.Task[Any]] = set()  # strong references until each pre-connect finishes


def _preconnect(ctx: AppContext) -> None:
    """Fire and forget: schedule the understanding's pre-connect, if it has one (the fake provider and a missing key
    make it a no-op). Nothing here can delay or fail `/start`."""
    hook = getattr(ctx.deps.understanding, "prewarm_llm", None)
    if not callable(hook):
        return
    try:
        task = asyncio.get_running_loop().create_task(hook())
    except Exception:  # noqa: BLE001 - not a coroutine function, or no loop: no pre-connect
        return
    _PRECONNECTS.add(task)
    task.add_done_callback(_preconnect_done)


def _preconnect_done(task: asyncio.Task[Any]) -> None:
    _PRECONNECTS.discard(task)
    if not task.cancelled():
        task.exception()  # retrieved and dropped: a failed pre-connect is never reported as an error


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _parse(model: type[BaseModel], body: bytes) -> Any:
    try:
        return model.model_validate_json(body)
    except (ValidationError, ValueError, UnicodeDecodeError) as exc:
        raise ApiProblem("invalid_request") from exc


async def _authenticate(request: Request, call_id: str, body: bytes) -> Credentials:
    ctx = _ctx(request)
    creds = authenticate_call(request, call_id=call_id, body=body,
                              secret=ctx.settings.gateway_secret.get_secret_value(),
                              now_s=int(ctx.now().timestamp()), webtokens=ctx.webtokens)
    if not CALL_ID_RE.fullmatch(call_id):
        raise ApiProblem("invalid_request", "Malformed call_id.")
    return creds


def _check_channel(ctx: AppContext, call_id: str, creds: Credentials) -> Any:
    """The saved call state, if any; credentials for the other channel get 401 unauthorized."""
    state = ctx.deps.sessions.get(call_id)
    if state is not None and state.channel.value != creds.channel:
        raise ApiProblem("unauthorized")
    return state


def _reply(model: BaseModel) -> JSONResponse:
    # Replies always carry every field (never exclude_none).
    return JSONResponse(model.model_dump(mode="json"))


@router.get("/v1/lines")
async def lines(request: Request, lang: str = "en") -> JSONResponse:
    ctx = _ctx(request)
    if request.headers.get("authorization", "").lower().startswith("bearer"):
        raise ApiProblem("unauthorized")  # gateway credentials only
    verify_gateway(secret=ctx.settings.gateway_secret.get_secret_value(),
                   timestamp=request.headers.get("x-gp-timestamp"), sig=request.headers.get("x-gp-signature"),
                   method=request.method, path=signed_path(request), body=await read_body(request),
                   now_s=int(ctx.now().timestamp()))
    try:
        language = Lang(lang)
    except ValueError as exc:
        raise ApiProblem("invalid_request", "Unsupported lang.") from exc
    return _reply(ctx.deps.brain.lines(language))


@router.post("/v1/calls/{call_id}/start")
async def start(call_id: str, request: Request) -> JSONResponse:
    ctx = _ctx(request)
    body = await read_body(request)
    creds = await _authenticate(request, call_id, body)
    req: StartRequest = _parse(StartRequest, body)
    if req.channel.value != creds.channel:
        raise ApiProblem("unauthorized")
    async with ctx.call_lock(call_id):
        _check_channel(ctx, call_id, creds)
        reply = await ctx.deps.brain.start(call_id, req)
    _preconnect(ctx)
    return _reply(reply)


@router.post("/v1/calls/{call_id}/turn")
async def turn(call_id: str, request: Request) -> JSONResponse:
    ctx = _ctx(request)
    body = await read_body(request)
    creds = await _authenticate(request, call_id, body)
    req: TurnRequest = _parse(TurnRequest, body)
    async with ctx.call_lock(call_id):
        _check_channel(ctx, call_id, creds)
        reply = await ctx.deps.brain.turn(call_id, req)
    return _reply(reply)


@router.post("/v1/calls/{call_id}/end")
async def end(call_id: str, request: Request) -> JSONResponse:
    ctx = _ctx(request)
    body = await read_body(request)
    creds = await _authenticate(request, call_id, body)
    req: EndRequest = _parse(EndRequest, body)
    async with ctx.call_lock(call_id):
        state = _check_channel(ctx, call_id, creds)
        await ctx.deps.brain.end(call_id, req)
        if state is not None:
            ctx.deps.live.wipe(state.case_id)  # the live transcript never outlives the call
    return JSONResponse({})

"""Web sessions for the talk page (docs/BRAIN_API.md §3.2): a call id and a bearer token bound to it, valid for
30 minutes, 20 an hour per IP address."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from gatorplate.api.context import AppContext
from gatorplate.api.errors import ApiProblem, read_body
from gatorplate.contracts.brain_api import WebSessionRequest, WebSessionResponse

router = APIRouter()
SESSION_LIMIT_MESSAGE = "Too many sessions from this network. Try again later."


@router.post("/api/web/sessions")
async def create_session(request: Request) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    if not ctx.limits.by_ip(ctx.limits.web_sessions, request):
        raise ApiProblem("rate_limited", SESSION_LIMIT_MESSAGE, headers={"Retry-After": "180"})
    body = await read_body(request)
    try:
        WebSessionRequest.model_validate_json(body if body.strip() else b"{}")
    except (ValidationError, ValueError) as exc:
        raise ApiProblem("invalid_request") from exc
    call_id = ctx.deps.ids.call_id()
    token = ctx.deps.ids.web_token()
    expires_at = ctx.webtokens.issue(token, call_id)
    reply = WebSessionResponse(call_id=call_id, token=token, expires_at=expires_at)
    return JSONResponse(reply.model_dump(mode="json"))

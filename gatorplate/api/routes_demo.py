"""Demo routes (console demo menu; only with GP_DEMO_MODE=1, else 404): seed the samples, reset (remove every case
that is not a sample) and inject one demo case. The console's "Reset demo" sends reset, then seed (docs/UI_SPEC.md
A2.5); the janitor's daily reset calls the same functions."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from gatorplate.api.auth import require_console
from gatorplate.api.context import AppContext
from gatorplate.api.errors import ApiProblem, read_body
from gatorplate.contracts.console_api import DemoInject, DemoResetResponse, DemoSeedResponse

router = APIRouter()


def _demo_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    if not ctx.settings.demo_mode:
        raise ApiProblem("not_found")
    require_console(request)
    return ctx


@router.post("/api/demo/seed")
async def seed(request: Request) -> JSONResponse:
    ctx = _demo_ctx(request)
    result = ctx.demo.seed(ctx.now())
    ctx.deps.events.publish("demo.reset")
    return JSONResponse(DemoSeedResponse(seeded=result.seeded, replaced=result.replaced).model_dump(mode="json"))


@router.post("/api/demo/reset")
async def reset(request: Request) -> JSONResponse:
    ctx = _demo_ctx(request)
    result = ctx.demo.reset()
    ctx.deps.events.publish("demo.reset")
    return JSONResponse(DemoResetResponse(deleted=result.deleted, kept=result.kept).model_dump(mode="json"))


@router.post("/api/demo/inject")
async def inject(request: Request) -> JSONResponse:
    ctx = _demo_ctx(request)
    try:
        req = DemoInject.model_validate_json(await read_body(request))
    except (ValidationError, ValueError) as exc:
        raise ApiProblem("invalid_request") from exc
    code = ctx.demo.load(req.id)["code"]  # 404 for an unknown id
    find = getattr(ctx.deps.cases, "get_by_code", None)
    replaced = find(code) if callable(find) else None
    case = ctx.demo.inject(req.id, ctx.now())
    if replaced is not None:  # the file's fixed code was taken: that case is gone, and open consoles hear it
        ctx.deps.events.publish("case.deleted", case_id=replaced.id)
    ctx.deps.events.publish("case.created", case=case)
    return JSONResponse(ctx.detail(case).model_dump(mode="json"))

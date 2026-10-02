"""`GET /api/public/info` (no login): the landing and talk pages read the demo number and the rules label."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gatorplate.api.context import AppContext
from gatorplate.contracts.console_api import PublicInfo

router = APIRouter()


@router.get("/api/public/info")
async def public_info(request: Request) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    meta = ctx.rules_meta()
    info = PublicInfo(demo_phone_display=ctx.settings.demo_phone_display or None, rules_label=meta.label,
                      effective_from=meta.effective_from)
    return JSONResponse(info.model_dump(mode="json"))

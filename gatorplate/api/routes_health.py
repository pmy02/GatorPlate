"""Health: `GET /v1/health` for the gateway (no auth, no data) and `GET /healthz` for the team (settings that
matter for a run, the rules and programs tables, the language-model status and usage counts; no personal data)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import gatorplate
from gatorplate.api.context import AppContext

router = APIRouter()


@router.get("/v1/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    ctx: AppContext = request.app.state.ctx
    settings = ctx.settings
    today = ctx.deps.clock.today()
    table_id: str | None = None
    rules_valid = False
    try:
        table_id = ctx.rules_meta().table_id
        rules_valid = bool(ctx.deps.rules.valid_on(today))
    except Exception:  # noqa: BLE001 - reported as not valid
        pass
    programs: dict[str, Any] = {"enabled": bool(settings.programs), "table_id": None, "valid_today": False}
    meta = ctx.programs_meta()
    if meta is not None:
        programs["table_id"] = meta.table_id
        programs["valid_today"] = meta.effective_from <= today <= meta.effective_to
    body = {
        "ok": bool(ctx.db.ping()),
        "version": gatorplate.__version__,
        "table_id": table_id,
        "rules_valid_today": rules_valid,
        "demo_mode": bool(settings.demo_mode),
        "card_delivery": settings.card_delivery,
        "debug_keys": bool(settings.debug_keys),
        "live_transcript": bool(settings.live_transcript),
        "programs": programs,
        "llm": ctx.llm_health(),
    }
    return JSONResponse(body)

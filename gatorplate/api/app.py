"""The FastAPI app factory: every route of docs/BRAIN_API.md and docs/UI_SPEC.md A8.3, the pages and the static
mount, security headers, content-free request logs, the console session cookie and the janitor loop.

`create_app(deps)` takes everything it needs from Deps; the web tokens, counters, rate limits, demo cases and janitor
are built here on the case store's database.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

import gatorplate
from gatorplate.api import (
    errors,
    routes_brain,
    routes_card,
    routes_console,
    routes_demo,
    routes_health,
    routes_public,
    routes_web,
)
from gatorplate.api.context import AppContext
from gatorplate.api.errors import error_response
from gatorplate.api.ratelimit import Limits
from gatorplate.api.routes_pages import build_router, mount_static
from gatorplate.api.security import SecurityHeadersMiddleware
from gatorplate.api.timing import RequestLogMiddleware
from gatorplate.config import REPO_ROOT
from gatorplate.deps import Deps
from gatorplate.store import Counters, Database, DemoCases, EventBus, Janitor, WebTokens
from gatorplate.store.janitor import TICK_SECONDS

log = logging.getLogger("gatorplate.api")
SESSION_COOKIE = "gp_console"
SESSION_MAX_AGE_S = 12 * 3600


def _configure_logging() -> None:
    """JSON lines on stderr for the gatorplate loggers (content-free by construction)."""
    root = logging.getLogger("gatorplate")
    if not any(getattr(h, "_gatorplate", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._gatorplate = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(logging.INFO)


class _InternalErrorGuard:
    """Outermost-but-one layer: an unexpected exception becomes the 500 `internal` envelope inside the security
    headers layer (so even that answer carries them), with a content-free log line."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = {"value": False}

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start":
                started["value"] = True
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        except Exception as exc:  # noqa: BLE001
            if started["value"]:
                raise
            log.error(json.dumps({"event": "internal_error", "kind": exc.__class__.__name__}))
            response = error_response("internal")
            await response(scope, receive, send)


async def _janitor_loop(janitor: Janitor, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await janitor.tick()
        except Exception as exc:  # noqa: BLE001 - the loop keeps going; the log line is content-free
            log.error(json.dumps({"event": "janitor_failed", "kind": exc.__class__.__name__}))


def build_context(deps: Deps, *, web_dir: Path | None = None) -> AppContext:
    settings = deps.settings
    db = getattr(deps.cases, "db", None)
    if not isinstance(db, Database):
        db = Database(settings.db_file)
    webtokens = WebTokens(db, clock=deps.clock)
    counters = Counters(db, clock=deps.clock)
    limits = Limits(clock=deps.clock, exempt_loopback=not settings.is_prod)
    demo = DemoCases(demo_dir=REPO_ROOT / "data" / "demo_cases", rules=deps.rules, cases=deps.cases, ids=deps.ids,
                     live=deps.live, tz=settings.tz, card_ttl_days=settings.card_ttl_days)
    janitor = Janitor(settings=settings, clock=deps.clock, cases=deps.cases, sessions=deps.sessions,
                      webtokens=webtokens, counters=counters, live=deps.live, events=deps.events, brain=deps.brain,
                      demo=demo)
    ctx = AppContext(deps=deps, db=db, webtokens=webtokens, counters=counters, limits=limits, demo=demo,
                     janitor=janitor, web_dir=web_dir or REPO_ROOT / "web")
    if isinstance(deps.events, EventBus) or hasattr(deps.events, "summarize"):
        deps.events.summarize = ctx.summarize  # every event summary carries found_display (docs/SPEC.md §5.10)
    return ctx


def create_app(deps: Deps) -> Any:
    _configure_logging()
    settings = deps.settings
    ctx = build_context(deps)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_janitor_loop(ctx.janitor, TICK_SECONDS))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="GatorPlate", version=gatorplate.__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.ctx = ctx
    errors.install(app)
    for module in (routes_health, routes_brain, routes_web, routes_public, routes_console, routes_card, routes_demo):
        app.include_router(module.router)
    app.include_router(build_router(prod=settings.is_prod))
    mount_static(app, ctx.web_dir, prod=settings.is_prod)

    # Innermost first: the console cookie, then the error guard, the security headers and the request log.
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret.get_secret_value(),
                       session_cookie=SESSION_COOKIE, max_age=SESSION_MAX_AGE_S, path="/", same_site="lax",
                       https_only=settings.is_prod)
    app.add_middleware(_InternalErrorGuard)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app

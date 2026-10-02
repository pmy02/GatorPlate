"""Pages: explicit routes for the page entry points, then the static mount of `web/` (added last by the app).

`/c/{token}` → the card page, `/go` → the code page, `/talk`, `/console`, `/about`. The fixture files and the
widget's fixture-only harness (`/unlocked/`, `/unlocked/index.html`, `harness.js`, `harness.css`) are served only
outside prod; the widget's three files (`unlocked.js`, `unlocked-lib.mjs`, `unlocked.css`) are served everywhere (the
card page loads them).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse

from gatorplate.api.context import AppContext
from gatorplate.api.errors import ApiProblem

# Slim images ship without a system MIME table, so the font type is registered here (else application/octet-stream).
mimetypes.add_type("font/woff2", ".woff2")

PAGES: dict[str, str] = {
    "/talk": "talk/index.html",
    "/console": "console/index.html",
    "/go": "go/index.html",
    "/about": "about/index.html",
}


def _page(request: Request, relative: str) -> FileResponse:
    ctx: AppContext = request.app.state.ctx
    path = (ctx.web_dir / relative).resolve()
    if not path.is_file() or ctx.web_dir.resolve() not in path.parents:
        raise ApiProblem("not_found")
    return FileResponse(path, media_type="text/html; charset=utf-8")


def build_router(*, prod: bool) -> APIRouter:
    router = APIRouter()

    def page_route(relative: str):  # noqa: ANN202 - FastAPI endpoint factory
        async def endpoint(request: Request) -> FileResponse:
            return _page(request, relative)
        return endpoint

    for path, relative in PAGES.items():
        router.add_api_route(path, page_route(relative), methods=["GET"], include_in_schema=False)
        router.add_api_route(path + "/", page_route(relative), methods=["GET"], include_in_schema=False)

    @router.get("/c/{token}", include_in_schema=False)
    async def card_page(token: str, request: Request) -> FileResponse:
        return _page(request, "card/index.html")

    if prod:
        @router.get("/fixtures", include_in_schema=False)
        @router.get("/fixtures/{rest:path}", include_in_schema=False)
        async def no_fixtures(rest: str = "") -> None:
            raise ApiProblem("not_found")

        @router.get("/unlocked", include_in_schema=False)
        @router.get("/unlocked/", include_in_schema=False)
        @router.get("/unlocked/index.html", include_in_schema=False)
        async def no_harness() -> None:
            raise ApiProblem("not_found")

    return router


def dev_only(path: str) -> bool:
    """True for the files served only outside prod: the fixtures and the widget's harness page with its own script
    and stylesheet (the widget's unlocked.js, unlocked-lib.mjs and unlocked.css stay public). `path` is the
    static mount's normalized relative path; compared without case (a case-insensitive file system would serve
    `Fixtures/`)."""
    parts = [p for p in path.replace("\\", "/").lower().split("/") if p not in ("", ".")]
    if not parts:
        return False
    if parts[0] == "fixtures":
        return True
    harness = (["index.html"], ["harness.js"], ["harness.css"])
    return parts[0] == "unlocked" and (len(parts) == 1 or parts[1:] in harness)


def mount_static(app: FastAPI, web_dir: Path, *, prod: bool = False) -> None:
    from starlette.exceptions import HTTPException
    from starlette.staticfiles import StaticFiles

    class WebFiles(StaticFiles):
        """The web folder. In prod the dev-only files answer 404 for every method and path spelling (HEAD,
        `//fixtures/…`, `/unlocked/./`), not only for the GET routes above."""

        async def get_response(self, path: str, scope: dict):  # type: ignore[override]
            if prod and dev_only(path):
                raise HTTPException(status_code=404)
            return await super().get_response(path, scope)

    if web_dir.is_dir():
        app.mount("/", WebFiles(directory=str(web_dir), html=True, follow_symlink=False), name="web")

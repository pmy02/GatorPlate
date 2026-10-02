"""Content-free request logs and the Server-Timing header (docs/SPEC.md §8.9).

One JSON line per request: method, route template (never the raw path: card tokens and call ids are in paths), status
and server milliseconds. Brain API routes also return `Server-Timing: brain;dur=<ms>`. Never a body, a query, a
header value, an utterance, a reply, a token or a code.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger("gatorplate.requests")


def route_template(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    raw = scope.get("path", "")
    return "static" if not raw.startswith(("/api/", "/v1/")) else "unmatched"


class RequestLogMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": 500}
        brain = scope.get("path", "").startswith("/v1/")

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message.get("status", 500)
                if brain:
                    ms = (time.perf_counter() - started) * 1000
                    headers = list(message.get("headers", []))
                    headers.append((b"server-timing", f"brain;dur={ms:.1f}".encode()))
                    message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            ms = (time.perf_counter() - started) * 1000
            log.info(json.dumps({"method": scope.get("method"), "route": route_template(scope),
                                 "status": status["code"], "server_ms": int(ms * 10) / 10}))

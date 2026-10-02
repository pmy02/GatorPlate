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


class _Exchange:
    """What the middleware learns about one HTTP request while the app answers it."""

    __slots__ = ("brain", "started", "status")

    def __init__(self, scope: dict) -> None:
        self.brain = scope.get("path", "").startswith("/v1/")
        self.status = 500  # kept when the app fails before it starts a response
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    def stamp(self, message: dict) -> dict:
        """Note the status of the response start; on a Brain API route, add the Server-Timing header to it."""
        if message["type"] != "http.response.start":
            return message
        self.status = message.get("status", 500)
        if not self.brain:
            return message
        timing = (b"server-timing", f"brain;dur={self.elapsed_ms():.1f}".encode())
        return {**message, "headers": [*message.get("headers", []), timing]}

    def log_line(self, scope: dict) -> str:
        return json.dumps({"method": scope.get("method"), "route": route_template(scope), "status": self.status,
                           "server_ms": int(self.elapsed_ms() * 10) / 10})


class RequestLogMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            await self._observe(scope, receive, send)
        else:  # lifespan and any other scope type pass through untouched and are never logged
            await self.app(scope, receive, send)

    async def _observe(self, scope: dict, receive: Any, send: Any) -> None:
        exchange = _Exchange(scope)

        async def send_stamped(message: dict) -> None:
            await send(exchange.stamp(message))

        try:
            await self.app(scope, receive, send_stamped)
        finally:
            log.info(exchange.log_line(scope))

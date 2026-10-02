"""Security headers on every response (docs/SPEC.md §8.9): a same-origin Content Security Policy with no inline
script or style, no referrer, no MIME sniffing, the microphone only on the talk page, `no-store` on every API answer
and `noindex` on the card, console and code pages."""

from __future__ import annotations

from typing import Any

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; font-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
NOINDEX_PREFIXES = ("/c/", "/console", "/go", "/api/", "/v1/", "/unlocked", "/fixtures")


def security_headers(path: str) -> list[tuple[bytes, bytes]]:
    talk = path == "/talk" or path.startswith("/talk/")
    headers = [
        (b"content-security-policy", CSP.encode()),
        (b"referrer-policy", b"no-referrer"),
        (b"x-content-type-options", b"nosniff"),
        (b"permissions-policy", b"microphone=(self)" if talk else b"microphone=()"),
    ]
    if path.startswith("/api/") or path.startswith("/v1/") or path == "/healthz":
        headers.append((b"cache-control", b"no-store"))
    if path.startswith(NOINDEX_PREFIXES):
        headers.append((b"x-robots-tag", b"noindex"))
    return headers


class SecurityHeadersMiddleware:
    """Pure ASGI middleware (streaming-safe): sets the headers above, replacing any value a route set itself."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(scope.get("path", ""))
        names = {name for name, _ in extra}

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message = {**message, "headers": headers + extra}
            await send(message)

        await self.app(scope, receive, wrapped)

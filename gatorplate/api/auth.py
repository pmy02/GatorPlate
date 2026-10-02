"""Authentication (docs/BRAIN_API.md §3): signed gateway requests (phone), bearer tokens (web talk page) and the
console's signed session cookie.

Gateway check order (the schema's x-auth.check_order):
1. no bearer token and a signature header missing -> 401 unauthorized
2. timestamp not digits, or signature not "v1=" + 64 lowercase hex -> 401 bad_signature
3. HMAC-SHA256 over "{ts}.{METHOD}.{path}.{sha256_hex(body)}" (path without the query, the exact body bytes),
   constant-time compare -> 401 bad_signature
4. more than 120 s between the timestamp and the server clock -> 401 stale_timestamp
5. a start body whose channel is not phone -> 401 unauthorized (checked by the route after parsing the body)
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request

from gatorplate.api.errors import ApiProblem

WINDOW_S = 120
TS_PATTERN = re.compile(r"[0-9]{1,15}")  # whole seconds; longer is never a real clock value
SIG_PATTERN = re.compile(r"v1=[0-9a-f]{64}")
BEARER = re.compile(r"bearer ([A-Za-z0-9_-]{1,256})", re.IGNORECASE)  # the scheme name is case-insensitive
CONSOLE_KEY = "console"


@dataclass(frozen=True)
class Credentials:
    channel: Literal["phone", "web"]


def signature(secret: str, ts: str, method: str, path: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    message = f"{ts}.{method.upper()}.{path}.{digest}".encode()
    return "v1=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_path(request: Request) -> str:
    """The URL path exactly as sent, without the query string."""
    raw = request.scope.get("raw_path")
    if isinstance(raw, bytes | bytearray) and raw:
        return bytes(raw).split(b"?", 1)[0].decode("latin-1")
    return request.url.path


def verify_gateway(*, secret: str, timestamp: str | None, sig: str | None, method: str, path: str, body: bytes,
                   now_s: int) -> None:
    """Raises ApiProblem in the schema's check order; returns None when the request is signed correctly."""
    if not timestamp or not sig:
        raise ApiProblem("unauthorized")
    if not TS_PATTERN.fullmatch(timestamp) or not SIG_PATTERN.fullmatch(sig):
        raise ApiProblem("bad_signature")
    expected = signature(secret, timestamp, method, path, body)
    if not hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii")):
        raise ApiProblem("bad_signature")
    if abs(now_s - int(timestamp)) > WINDOW_S:
        raise ApiProblem("stale_timestamp")


def bearer_token(request: Request) -> str | None:
    """The bearer token, or None when the request carries no Authorization: Bearer header. A bearer header that is
    present but malformed counts as a bad token (401), never as "no credentials"."""
    header = request.headers.get("authorization")
    if header is None or not header.lower().startswith("bearer"):
        return None
    match = BEARER.fullmatch(header.strip())
    return match.group(1) if match else ""


def authenticate_call(request: Request, *, call_id: str, body: bytes, secret: str, now_s: int,
                      webtokens: object, allow_bearer: bool = True) -> Credentials:
    """Credentials for a Brain API request: bearer (web) when an Authorization: Bearer header is present, else the
    gateway signature (phone)."""
    token = bearer_token(request)
    if token is not None:
        if not allow_bearer or not token or not webtokens.check(token, call_id):  # type: ignore[attr-defined]
            raise ApiProblem("unauthorized")
        return Credentials(channel="web")
    verify_gateway(secret=secret, timestamp=request.headers.get("x-gp-timestamp"),
                   sig=request.headers.get("x-gp-signature"), method=request.method, path=signed_path(request),
                   body=body, now_s=now_s)
    return Credentials(channel="phone")


def require_console(request: Request) -> None:
    """The console's signed session cookie (set by POST /api/console/login)."""
    if request.session.get(CONSOLE_KEY) is not True:
        raise ApiProblem("unauthorized")

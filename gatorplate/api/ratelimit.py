"""In-memory token buckets (docs/SPEC.md §8.9). Client addresses are hashed with a per-boot salt and never stored
or logged; a restart clears every bucket.

Limits: web sessions 20 an hour per IP; card code lookups 5 a minute per IP; console login 5 a minute per IP; the two
card programs endpoints share 30 a minute per card token (no address exemption). Outside prod, loopback clients
(127.0.0.1, ::1) are exempt from the per-IP limits so local end-to-end runs work.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_BUCKETS = 20_000


@dataclass
class _Bucket:
    tokens: float
    at: float


class RateLimiter:
    """capacity requests per `period_s`, refilled continuously; keys are salted hashes."""

    def __init__(self, *, capacity: int, period_s: float, clock: Any, salt: bytes) -> None:
        self.capacity = capacity
        self.rate = capacity / period_s
        self.clock = clock
        self._salt = salt
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def _key(self, raw: str) -> str:
        return hashlib.sha256(self._salt + raw.encode("utf-8")).hexdigest()

    def allow(self, raw_key: str) -> bool:
        key = self._key(raw_key)
        now = self.clock.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= MAX_BUCKETS:
                    self._prune(now)
                bucket = self._buckets[key] = _Bucket(tokens=float(self.capacity), at=now)
            bucket.tokens = min(float(self.capacity), bucket.tokens + max(0.0, now - bucket.at) * self.rate)
            bucket.at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def _prune(self, now: float) -> None:
        full = [k for k, b in self._buckets.items()
                if b.tokens + max(0.0, now - b.at) * self.rate >= self.capacity]
        for k in full:
            del self._buckets[k]

    def size(self) -> int:
        with self._lock:
            return len(self._buckets)


def client_ip(request: Request) -> str:
    """The address a rate limit counts. Behind the hosting proxy every request carries X-Forwarded-For, and the proxy
    appends the address it saw as the last entry; the entries before it are whatever the client sent. The server
    trusts the forwarded header for its own client address, which is the first entry, so a client could pick a fresh
    one per request — the limits therefore count the last entry. Without the header: the connection's address."""
    entries = [part.strip() for value in request.headers.getlist("x-forwarded-for") for part in value.split(",")]
    entries = [e for e in entries if e]
    if entries:
        return entries[-1][:64]
    return request.client.host if request.client else "unknown"


class Limits:
    def __init__(self, *, clock: Any, exempt_loopback: bool) -> None:
        salt = secrets.token_bytes(16)
        self.exempt_loopback = exempt_loopback
        self.web_sessions = RateLimiter(capacity=20, period_s=3600, clock=clock, salt=salt)
        self.card_lookup = RateLimiter(capacity=5, period_s=60, clock=clock, salt=salt)
        self.console_login = RateLimiter(capacity=5, period_s=60, clock=clock, salt=salt)
        self.card_programs = RateLimiter(capacity=30, period_s=60, clock=clock, salt=salt)

    def by_ip(self, limiter: RateLimiter, request: Request) -> bool:
        ip = client_ip(request)
        peer = request.client.host if request.client else None
        if self.exempt_loopback and ip in LOOPBACK and (peer is None or peer in LOOPBACK):
            return True
        return limiter.allow(ip)

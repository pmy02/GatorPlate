"""Web session tokens for the talk page, stored only as SHA-256 hashes and bound to one call (docs/BRAIN_API.md
§3.2). A token lives 30 minutes."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any

from gatorplate.store.db import Database, parse_ts, ts

WEB_TOKEN_TTL = timedelta(minutes=30)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class WebTokens:
    """Web session tokens, stored only as SHA-256 hashes."""

    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock

    def issue(self, token: str, call_id: str, *, expires_at: datetime | None = None) -> datetime:
        """Stores the hash of a new token for `call_id`; returns its expiry (30 minutes from now by default)."""
        expiry = expires_at or (self.clock.now() + WEB_TOKEN_TTL)
        with self.db.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO web_tokens (token_hash, call_id, expires_at) VALUES (?, ?, ?)",
                         (token_hash(token), call_id, ts(expiry)))
        return expiry

    def check(self, token: str, call_id: str) -> bool:
        """True when the token exists, is not expired and was issued for this call."""
        row = self.db.query_one("SELECT call_id, expires_at FROM web_tokens WHERE token_hash = ?",
                                (token_hash(token),))
        if row is None:
            return False
        expires = parse_ts(row["expires_at"])
        if expires is None or expires <= self.clock.now():
            return False
        return hmac.compare_digest(str(row["call_id"]), call_id)

    def purge(self) -> int:
        """Deletes expired tokens; returns how many."""
        with self.db.tx() as conn:
            return conn.execute("DELETE FROM web_tokens WHERE expires_at <= ?", (ts(self.clock.now()),)).rowcount

    def delete_for_call(self, call_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM web_tokens WHERE call_id = ?", (call_id,))

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM web_tokens")
        return int(row["n"]) if row else 0

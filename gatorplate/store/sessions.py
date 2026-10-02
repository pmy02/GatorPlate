"""Per-call conversation state (SessionStorePort), persisted every turn so a call survives a restart. No
transcript is ever stored here; short-term memory lives in process memory only."""

from __future__ import annotations

from datetime import datetime

from gatorplate.contracts.session import SessionState
from gatorplate.store.db import Database, ts


class SessionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, call_id: str) -> SessionState | None:
        row = self.db.query_one("SELECT doc FROM sessions WHERE call_id = ?", (call_id,))
        return SessionState.model_validate_json(row["doc"]) if row else None

    def put(self, state: SessionState) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO sessions (call_id, case_id, doc, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(call_id) DO UPDATE SET case_id = excluded.case_id, doc = excluded.doc, "
                "updated_at = excluded.updated_at",
                (state.call_id, state.case_id, state.model_dump_json(), ts(state.last_activity_at)))

    def delete(self, call_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE call_id = ?", (call_id,))

    def for_case(self, case_id: str) -> list[SessionState]:
        rows = self.db.query("SELECT doc FROM sessions WHERE case_id = ?", (case_id,))
        return [SessionState.model_validate_json(r["doc"]) for r in rows]

    def idle(self, *, before: datetime) -> list[SessionState]:
        """Calls that are still open (no /end received) and had no request since `before`."""
        rows = self.db.query("SELECT doc FROM sessions WHERE updated_at < ?", (ts(before),))
        states = [SessionState.model_validate_json(r["doc"]) for r in rows]
        return [s for s in states if not s.ended]

    def purge_orphans(self, *, before: datetime) -> int:
        """Deletes the call state (and the web tokens) of calls whose case no longer exists and that had no request
        since `before`. A voice "delete my data" removes the case while its call is still open, and the call's last
        state is written after that; once the call has gone quiet nothing of it stays behind."""
        with self.db.tx() as conn:
            rows = conn.execute("SELECT call_id FROM sessions WHERE updated_at < ? AND case_id NOT IN "
                                "(SELECT id FROM cases)", (ts(before),)).fetchall()
            for row in rows:
                conn.execute("DELETE FROM web_tokens WHERE call_id = ?", (row["call_id"],))
                conn.execute("DELETE FROM sessions WHERE call_id = ?", (row["call_id"],))
        return len(rows)

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM sessions")
        return int(row["n"]) if row else 0

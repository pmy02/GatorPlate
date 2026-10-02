"""The case store (CaseStorePort): one row per case, the whole Case as JSON in `doc`, versioned saves.

Routing-only slots (a volunteered immigration status, disability details) are never stored: a case that carries one
is rejected. Deleting a case also deletes its saved call state (`sessions` rows) and the web tokens of those calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import CaseStatus
from gatorplate.contracts.errors import NotFound, VersionConflict
from gatorplate.contracts.slots import ROUTING_ONLY
from gatorplate.store.db import Database, ts


class RoutingOnlySlotError(ValueError):
    """A case carried a routing-only slot; those are never persisted (docs/SPEC.md §8.3)."""


class DuplicateCaseError(ValueError):
    """A case id, code or card token that already exists."""


def _check_storable(case: Case) -> None:
    bad = sorted(name.value for name in case.slots if name in ROUTING_ONLY)
    if bad:
        raise RoutingOnlySlotError(f"routing-only slots are never stored: {', '.join(bad)}")


def _row_values(case: Case) -> dict[str, Any]:
    card = case.card
    return {
        "id": case.id,
        "code": case.code,
        "version": case.version,
        "created_at": ts(case.created_at),
        "updated_at": ts(case.updated_at),
        "status": case.status.value,
        "live": 1 if case.live else 0,
        "seeded": 1 if case.seeded else 0,
        "card_token": card.token if card else None,
        "short_code": card.short_code if card else None,
        "short_code_expires_at": ts(card.short_code_expires_at) if card and card.short_code_expires_at else None,
        "card_expires_at": ts(card.expires_at) if card else None,
        "doc": case.model_dump_json(),
    }


class CaseStore:
    def __init__(self, db: Database, *, clock: Any) -> None:
        self.db = db
        self.clock = clock

    # ------------------------------------------------------------------------------------------ reads

    @staticmethod
    def _load(row: Any) -> Case:
        return Case.model_validate_json(row["doc"])

    def get(self, case_id: str) -> Case | None:
        row = self.db.query_one("SELECT doc FROM cases WHERE id = ?", (case_id,))
        return self._load(row) if row else None

    def get_by_code(self, code: str) -> Case | None:
        row = self.db.query_one("SELECT doc FROM cases WHERE code = ?", (code,))
        return self._load(row) if row else None

    def get_by_card_token(self, token: str) -> Case | None:
        row = self.db.query_one("SELECT doc FROM cases WHERE card_token = ?", (token,))
        return self._load(row) if row else None

    def get_by_short_code(self, code: str, *, now: datetime) -> Case | None:
        """The case whose spoken card code is `code` and still active at `now` (the newest when, against the rule,
        two active cases share it)."""
        row = self.db.query_one(
            "SELECT doc FROM cases WHERE short_code = ? AND short_code_expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1", (code, ts(now)))
        return self._load(row) if row else None

    def short_code_active(self, code: str, *, now: datetime) -> bool:
        """True when an active card already uses this spoken code (codes are unique among active codes)."""
        return self.get_by_short_code(code, now=now) is not None

    def list(self, *, status: CaseStatus | None = None, since_seq: int | None = None,
             limit: int = 200) -> list[Case]:
        """Newest first. `since_seq` keeps the cases written after this store's change counter `since_seq`
        (`current_change_seq()`); the console's polling uses the event bus sequence instead."""
        where: list[str] = []
        params: list[Any] = []
        if status is not None:
            where.append("status = ?")
            params.append(CaseStatus(status).value)
        if since_seq is not None:
            where.append("change_seq > ?")
            params.append(int(since_seq))
        sql = "SELECT doc FROM cases"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(0, int(limit)))
        return [self._load(row) for row in self.db.query(sql, params)]

    def ids(self, *, seeded: bool | None = None, live: bool | None = None) -> list[str]:
        where: list[str] = []
        params: list[Any] = []
        if seeded is not None:
            where.append("seeded = ?")
            params.append(1 if seeded else 0)
        if live is not None:
            where.append("live = ?")
            params.append(1 if live else 0)
        sql = "SELECT id FROM cases" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at"
        return [row["id"] for row in self.db.query(sql, params)]

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM cases")
        return int(row["n"]) if row else 0

    def any_live(self) -> bool:
        return self.db.query_one("SELECT 1 FROM cases WHERE live = 1 LIMIT 1") is not None

    def current_change_seq(self) -> int:
        row = self.db.query_one("SELECT COALESCE(MAX(change_seq), 0) AS n FROM cases")
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------------------------------ writes

    def create(self, case: Case) -> Case:
        """Stores a new case. The stored copy has version = the given version + 1 (a fresh case: 1)."""
        _check_storable(case)
        stored = case.model_copy(update={"version": case.version + 1}, deep=True)
        values = _row_values(stored)
        with self.db.tx() as conn:
            exists = conn.execute(
                "SELECT 1 FROM cases WHERE id = ? OR code = ? OR (card_token IS NOT NULL AND card_token = ?)",
                (values["id"], values["code"], values["card_token"])).fetchone()
            if exists:
                raise DuplicateCaseError("a case with this id, code or card token already exists")
            seq = conn.execute("SELECT COALESCE(MAX(change_seq), 0) + 1 FROM cases").fetchone()[0]
            conn.execute(
                "INSERT INTO cases (id, code, version, created_at, updated_at, status, live, seeded, card_token, "
                "short_code, short_code_expires_at, card_expires_at, change_seq, doc) VALUES "
                "(:id, :code, :version, :created_at, :updated_at, :status, :live, :seeded, :card_token, :short_code, "
                ":short_code_expires_at, :card_expires_at, :change_seq, :doc)", {**values, "change_seq": seq})
        return stored

    def save(self, case: Case, *, expected_version: int | None = None) -> Case:
        """Writes the case and bumps its version (stored version + 1); `updated_at` becomes now. With
        `expected_version`, a stored version that differs raises VersionConflict (409 conflict)."""
        _check_storable(case)
        with self.db.tx() as conn:
            row = conn.execute("SELECT version FROM cases WHERE id = ?", (case.id,)).fetchone()
            if row is None:
                raise NotFound("The case no longer exists.")
            current = int(row["version"])
            if expected_version is not None and current != expected_version:
                raise VersionConflict("The case was changed by someone else.")
            stored = case.model_copy(update={"version": current + 1, "updated_at": self.clock.now()}, deep=True)
            values = _row_values(stored)
            if values["card_token"] is not None:
                clash = conn.execute("SELECT 1 FROM cases WHERE card_token = ? AND id != ?",
                                     (values["card_token"], case.id)).fetchone()
                if clash:
                    raise DuplicateCaseError("card token already in use")
            seq = conn.execute("SELECT COALESCE(MAX(change_seq), 0) + 1 FROM cases").fetchone()[0]
            conn.execute(
                "UPDATE cases SET code = :code, version = :version, created_at = :created_at, "
                "updated_at = :updated_at, status = :status, live = :live, seeded = :seeded, "
                "card_token = :card_token, short_code = :short_code, short_code_expires_at = :short_code_expires_at, "
                "card_expires_at = :card_expires_at, change_seq = :change_seq, doc = :doc WHERE id = :id",
                {**values, "change_seq": seq})
        return stored

    def purge_short_codes(self, *, now: datetime) -> int:
        """Removes spoken card codes that expired (housekeeping: the case's version and updated_at stay, because
        nothing a person sees changes — an expired code is never shown or accepted anyway)."""
        purged = 0
        with self.db.tx() as conn:
            rows = conn.execute("SELECT id, doc FROM cases WHERE short_code IS NOT NULL AND short_code_expires_at <= ?",
                                (ts(now),)).fetchall()
            for row in rows:
                case = Case.model_validate_json(row["doc"])
                if case.card is not None:
                    case.card.short_code = None
                    case.card.short_code_expires_at = None
                conn.execute("UPDATE cases SET short_code = NULL, short_code_expires_at = NULL, doc = ? WHERE id = ?",
                             (case.model_dump_json(), row["id"]))
                purged += 1
        return purged

    def _delete_ids(self, conn: Any, ids: list[str]) -> int:
        deleted = 0
        for case_id in ids:
            calls = [r["call_id"] for r in conn.execute("SELECT call_id FROM sessions WHERE case_id = ?",
                                                        (case_id,)).fetchall()]
            for call_id in calls:
                conn.execute("DELETE FROM web_tokens WHERE call_id = ?", (call_id,))
            conn.execute("DELETE FROM sessions WHERE case_id = ?", (case_id,))
            deleted += conn.execute("DELETE FROM cases WHERE id = ?", (case_id,)).rowcount
        return deleted

    def delete(self, case_id: str) -> bool:
        """Removes the case, its card (same row), its saved call state and the web tokens of its calls."""
        with self.db.tx() as conn:
            return self._delete_ids(conn, [case_id]) > 0

    def delete_all(self, *, keep_seeded: bool) -> int:
        """Removes every case (or every case that is not a demo sample) with its call state; returns the count."""
        with self.db.tx() as conn:
            sql = "SELECT id FROM cases" + (" WHERE seeded = 0" if keep_seeded else "")
            ids = [r["id"] for r in conn.execute(sql).fetchall()]
            return self._delete_ids(conn, ids)

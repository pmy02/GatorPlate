"""The SQLite stores: WAL, versioned saves, lookups by code, card token and spoken code, routing-only slots refused,
deletes that take the call state along; sessions, hashed web tokens, daily counters and the memory-only live store."""

from __future__ import annotations

from datetime import timedelta

import pytest

from gatorplate.contracts.case import CardRef, Case
from gatorplate.contracts.common import CaseStatus, Channel, Lang
from gatorplate.contracts.console_api import LiveTurn
from gatorplate.contracts.errors import NotFound, VersionConflict
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import Slot, SlotName
from gatorplate.store import (
    CaseStore,
    Counters,
    Database,
    DuplicateCaseError,
    LiveStore,
    RoutingOnlySlotError,
    SessionStore,
    WebTokens,
)
from gatorplate.store.webtokens import token_hash


@pytest.fixture
def db(tmp_db):
    database = Database(tmp_db)
    yield database
    database.close()


@pytest.fixture
def cases(db, fixed_clock) -> CaseStore:
    return CaseStore(db, clock=fixed_clock)


def make_case(clock, *, cid="c_aaaaaaaaaa", code="K7Q-2FM", token=None, short=None, seeded=False, live=False,
              short_hours=24) -> Case:
    now = clock.now()
    card = None
    if token:
        card = CardRef(token=token, short_code=short,
                       short_code_expires_at=now + timedelta(hours=short_hours) if short else None,
                       created_at=now, expires_at=now + timedelta(days=7))
    return Case(id=cid, code=code, created_at=now, updated_at=now, lang=Lang.en, channel=Channel.phone,
                seeded=seeded, live=live, card=card)


def test_database_is_wal_and_migrated(db, tmp_db) -> None:
    assert db.journal_mode.lower() == "wal"
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"cases", "sessions", "web_tokens", "counters"} <= tables
    again = Database(tmp_db)  # migrations are idempotent
    assert again.ping()
    again.close()


def test_every_connection_setting_is_in_force(db, tmp_db) -> None:
    from gatorplate.store.db import CONNECTION_SETTINGS

    assert dict(CONNECTION_SETTINGS) == {"journal_mode": "WAL", "synchronous": "NORMAL", "foreign_keys": "ON"}
    # SQLite answers synchronous as a number (NORMAL = 1) and foreign_keys as 0 or 1.
    assert db.query_one("PRAGMA synchronous")[0] == 1
    assert db.query_one("PRAGMA foreign_keys")[0] == 1
    assert db.journal_mode.lower() == "wal"
    # The settings belong to each connection, not to the file: a second Database on the same file gets them too.
    again = Database(tmp_db)
    assert again.query_one("PRAGMA synchronous")[0] == 1 and again.query_one("PRAGMA foreign_keys")[0] == 1
    again.close()
    # Rows come back addressable by column name; the connection is autocommit, so tx() owns BEGIN and COMMIT.
    assert db.query_one("SELECT 1 AS one")["one"] == 1
    assert db._conn.isolation_level is None and not db._conn.in_transaction


def test_create_get_save_versions(cases, fixed_clock) -> None:
    created = cases.create(make_case(fixed_clock))
    assert created.version == 1
    assert cases.get(created.id) == created
    fixed_clock.advance(5)
    saved = cases.save(created, expected_version=1)
    assert saved.version == 2 and saved.updated_at == fixed_clock.now()
    assert cases.get(created.id).version == 2
    with pytest.raises(VersionConflict):
        cases.save(created, expected_version=1)
    assert cases.save(created).version == 3  # no expected version: last writer wins, the version still goes up
    with pytest.raises(NotFound):
        cases.save(make_case(fixed_clock, cid="c_bbbbbbbbbb", code="AAA-BBB"))


def test_duplicates_refused(cases, fixed_clock) -> None:
    cases.create(make_case(fixed_clock, token="tok_aaaaaaaaaaaaaaaaaaaa"))
    for other in (make_case(fixed_clock, cid="c_bbbbbbbbbb"),  # same code
                  make_case(fixed_clock, code="AAA-BBB"),  # same id
                  make_case(fixed_clock, cid="c_cccccccccc", code="CCC-DDD", token="tok_aaaaaaaaaaaaaaaaaaaa")):
        with pytest.raises(DuplicateCaseError):
            cases.create(other)


def test_routing_only_slots_are_never_stored(cases, fixed_clock) -> None:
    case = make_case(fixed_clock)
    case.slots[SlotName.volunteered_status] = Slot(value="F-1")
    with pytest.raises(RoutingOnlySlotError):
        cases.create(case)
    clean = cases.create(make_case(fixed_clock))
    clean.slots[SlotName.elderly_or_disabled] = Slot(value="true")
    with pytest.raises(RoutingOnlySlotError):
        cases.save(clean)
    assert SlotName.elderly_or_disabled not in cases.get(clean.id).slots


def test_lookups(cases, fixed_clock) -> None:
    cases.create(make_case(fixed_clock, token="tok_aaaaaaaaaaaaaaaaaaaa", short="481206"))
    now = fixed_clock.now()
    assert cases.get_by_card_token("tok_aaaaaaaaaaaaaaaaaaaa").code == "K7Q-2FM"
    assert cases.get_by_card_token("tok_unknown") is None
    assert cases.get_by_code("K7Q-2FM").id == "c_aaaaaaaaaa"
    assert cases.get_by_short_code("481206", now=now).code == "K7Q-2FM"
    assert cases.short_code_active("481206", now=now)
    assert cases.get_by_short_code("481206", now=now + timedelta(hours=24)) is None  # 24 h, then gone
    assert cases.get_by_short_code("000000", now=now) is None


def test_list_order_status_and_change_seq(cases, fixed_clock) -> None:
    first = cases.create(make_case(fixed_clock))
    fixed_clock.advance(60)
    second = make_case(fixed_clock, cid="c_bbbbbbbbbb", code="AAA-BBB")
    second.status = CaseStatus.reviewed
    cases.create(second)
    assert [c.id for c in cases.list()] == ["c_bbbbbbbbbb", "c_aaaaaaaaaa"]
    assert [c.id for c in cases.list(status=CaseStatus.reviewed)] == ["c_bbbbbbbbbb"]
    assert len(cases.list(limit=1)) == 1
    mark = cases.current_change_seq()
    cases.save(first)
    assert [c.id for c in cases.list(since_seq=mark)] == ["c_aaaaaaaaaa"]


def test_delete_takes_sessions_and_tokens(db, cases, fixed_clock) -> None:
    sessions = SessionStore(db)
    tokens = WebTokens(db, clock=fixed_clock)
    case = cases.create(make_case(fixed_clock))
    now = fixed_clock.now()
    sessions.put(SessionState(call_id="a" * 32, case_id=case.id, channel=Channel.web, lang=Lang.en, started_at=now,
                              last_activity_at=now))
    tokens.issue("tok-web-0000000000000000000000", "a" * 32)
    assert cases.delete(case.id) is True
    assert cases.get(case.id) is None and sessions.get("a" * 32) is None
    assert not tokens.check("tok-web-0000000000000000000000", "a" * 32)
    assert cases.delete(case.id) is False


def test_delete_all_keeps_samples(db, cases, fixed_clock) -> None:
    sessions = SessionStore(db)
    cases.create(make_case(fixed_clock, cid="c_seeded0001", code="R8W-3ND", seeded=True))
    judge = cases.create(make_case(fixed_clock, cid="c_judge00001", code="K7Q-2FM"))
    now = fixed_clock.now()
    sessions.put(SessionState(call_id="b" * 32, case_id=judge.id, channel=Channel.phone, lang=Lang.en,
                              started_at=now, last_activity_at=now))
    assert cases.delete_all(keep_seeded=True) == 1
    assert cases.ids() == ["c_seeded0001"] and sessions.count() == 0
    assert cases.delete_all(keep_seeded=False) == 1 and cases.count() == 0


def test_sessions_round_trip_and_idle(db, fixed_clock) -> None:
    sessions = SessionStore(db)
    now = fixed_clock.now()
    state = SessionState(call_id="c" * 32, case_id="c_x", channel=Channel.phone, lang=Lang.en, started_at=now,
                         last_activity_at=now - timedelta(minutes=11))
    sessions.put(state)
    assert sessions.get("c" * 32) == state
    assert [s.call_id for s in sessions.idle(before=now - timedelta(minutes=10))] == ["c" * 32]
    state.ended = True
    sessions.put(state)
    assert sessions.idle(before=now) == []
    sessions.delete("c" * 32)
    assert sessions.get("c" * 32) is None


def test_web_tokens_are_hashed_bound_and_expire(db, fixed_clock) -> None:
    tokens = WebTokens(db, clock=fixed_clock)
    token = "webtoken-plain-value-000000000000000000"
    expires = tokens.issue(token, "d" * 32)
    assert expires == fixed_clock.now() + timedelta(minutes=30)
    stored = [r["token_hash"] for r in db.query("SELECT token_hash FROM web_tokens")]
    assert stored == [token_hash(token)] and token not in stored
    assert tokens.check(token, "d" * 32)
    assert not tokens.check(token, "e" * 32)  # bound to its call
    assert not tokens.check("other-token", "d" * 32)
    fixed_clock.advance(minutes=30)
    assert not tokens.check(token, "d" * 32)
    assert tokens.purge() == 1 and tokens.count() == 0


def test_counters_are_daily_in_pacific_time(db, fixed_clock) -> None:
    counters = Counters(db, clock=fixed_clock)
    assert counters.get("llm_turns") == 0
    assert counters.incr("llm_turns") == 1 and counters.incr("llm_turns", by=2) == 3
    assert counters.try_take("cap", 2) and counters.try_take("cap", 2) and not counters.try_take("cap", 2)
    fixed_clock.advance(hours=14)  # Sat 2026-10-03 00:00 PT
    assert counters.get("llm_turns") == 0 and counters.incr("llm_turns") == 1
    assert counters.recorded_day("llm_turns") == "2026-10-03"


def test_counters_fit_the_understanding_daily_counter(db, fixed_clock) -> None:
    """The understanding module counts language-model turns with `incr(key, day)` (day positional, a date); this
    store backs that cap, so the call shape must work and count per Pacific day."""
    from datetime import date

    from gatorplate.extract.llm.base import DailyCounter, MemoryCounter

    counters = Counters(db, clock=fixed_clock)
    reference = MemoryCounter()
    for day in (date(2026, 10, 2), date(2026, 10, 2), date(2026, 10, 3)):
        assert counters.incr("llm_turns", day) == reference.incr("llm_turns", day)
    assert counters.get("llm_turns", day=date(2026, 10, 3)) == 1
    port: DailyCounter = counters  # structural fit
    assert port.incr("llm_turns", date(2026, 10, 3)) == 2
    with pytest.raises(TypeError):
        counters.incr("llm_turns", 2)  # type: ignore[arg-type]  # the old by-position call is refused, not misread


def test_live_store_is_memory_only(db, fixed_clock) -> None:
    live = LiveStore()
    line = LiveTurn(case_id="c_live", turn=1, who="student", text="about 900 a month", lang=Lang.en,
                    at=fixed_clock.now())
    live.append(line)
    live.set_now_asking("c_live", key="ask.rent", text="How much is your rent?", reason=None)
    view = live.get("c_live")
    assert view is not None and view.lines == [line] and view.now_asking == "ask.rent"
    live.wipe("c_live")
    assert live.get("c_live") is None
    dump = "".join(str(r[0]) for r in db.query("SELECT doc FROM cases UNION ALL SELECT doc FROM sessions"))
    assert "900 a month" not in dump

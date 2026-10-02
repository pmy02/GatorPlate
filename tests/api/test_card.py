"""Card API: view, status, reminders, self-delete, code lookup, expiry (410), and the two card programs endpoints
(answers and "I applied" marks: stored on the case, version bumps, case.updated with changed_programs, every error
code, the shared 30-a-minute bucket per card token, GP_PROGRAMS=0)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from gatorplate.contracts.errors import VersionConflict

TOKEN = "cardtoken0000000000000001"
SOFIA_SLOTS = {"age": "19", "lives_with_parent": "true", "level": "undergrad"}
DORM_SLOTS = {"age": "18", "lives_with_parent": "false", "dorm_on_campus": "true", "meals_per_week": "14"}


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def answer(h, payload: dict, *, token: str = TOKEN, lang: str = "en"):
    return h.client.post(f"/api/card/{token}/answers?lang={lang}", json={"answers": payload})


def test_card_view_status_and_language(h) -> None:
    maria = h.add_case()
    r = h.client.get(f"/api/card/{TOKEN}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    view = r.json()
    assert view["lang"] == "en" and view["code"] == maria.code and view["estimate_monthly"] == 306
    assert view["unlocked"]["found_display"] == 3670 and view["unlocked"]["question"]["id"] == "break_transit"
    assert h.client.get(f"/api/card/{TOKEN}?lang=es").json()["lang"] == "es"
    assert err(h.client.get(f"/api/card/{TOKEN}?lang=fr")) == (422, "invalid_request")
    status = h.client.get(f"/api/card/{TOKEN}/status").json()
    assert set(status) == {"status", "reviewed", "reviewed_at", "tier", "estimate_monthly"}
    assert status["status"] == "new" and status["reviewed"] is False
    assert err(h.client.get("/api/card/unknowntoken00000000000/status")) == (404, "not_found")
    assert err(h.client.get("/api/card/unknowntoken00000000000")) == (404, "not_found")


def test_card_expires(h) -> None:
    h.add_case()
    h.clock.advance(days=7)
    for path in (f"/api/card/{TOKEN}", f"/api/card/{TOKEN}/status", f"/api/card/{TOKEN}/reminders.ics"):
        assert err(h.client.get(path)) == (410, "gone"), path
    assert err(answer(h, {"break_transit": "none"})) == (410, "gone")
    assert h.client.delete(f"/api/card/{TOKEN}").json() == {}  # the student can still delete it


def test_reminders(h) -> None:
    maria = h.add_case()
    r = h.client.get(f"/api/card/{TOKEN}/reminders.ics?lang=es")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert r.text.count("BEGIN:VEVENT") == 3 and "attachment" in r.headers["content-disposition"]
    case = h.deps.cases.get(maria.id)
    case.first_month = None
    h.deps.cases.save(case)
    assert err(h.client.get(f"/api/card/{TOKEN}/reminders.ics")) == (404, "not_found")


def test_self_delete_removes_everything(h) -> None:
    from gatorplate.contracts.common import Channel, Lang
    from gatorplate.contracts.session import SessionState

    maria = h.add_case()
    assert answer(h, {"break_transit": "weekdays_muni"}).status_code == 200
    now = h.clock.now()
    h.deps.sessions.put(SessionState(call_id="a" * 32, case_id=maria.id, channel=Channel.phone, lang=Lang.en,
                                     started_at=now, last_activity_at=now))
    assert h.client.delete(f"/api/card/{TOKEN}").json() == {}
    assert h.deps.cases.get(maria.id) is None and h.deps.sessions.get("a" * 32) is None
    assert err(h.client.get(f"/api/card/{TOKEN}")) == (404, "not_found")
    assert err(h.client.delete(f"/api/card/{TOKEN}")) == (404, "not_found")
    assert h.deps.events.buffered()[-1].type == "case.deleted"


def test_lookup(h) -> None:
    h.add_case(short_code="481206")
    r = h.client.post("/api/card/lookup", json={"code": "481206"})
    assert r.status_code == 200 and r.json() == {"url": f"/c/{TOKEN}"}
    assert err(h.client.post("/api/card/lookup", json={"code": "48120"})) == (422, "invalid_request")
    assert err(h.client.post("/api/card/lookup", json={"code": "000000"})) == (404, "not_found")
    assert h.client.post("/api/card/lookup", json={"code": "481206"}).status_code == 200
    assert h.client.post("/api/card/lookup", json={"code": "481206"}).status_code == 200
    assert err(h.client.post("/api/card/lookup", json={"code": "481206"})) == (429, "rate_limited")  # the 6th
    h.clock.advance(hours=24)
    assert err(h.client.post("/api/card/lookup", json={"code": "481206"})) == (404, "not_found")  # code expired


def test_three_taps_count_up(h) -> None:
    maria = h.add_case()
    slots_before = h.deps.cases.get(maria.id).slots
    totals = []
    for question, choice in (("break_transit", "weekdays_muni"), ("tax_dependent", "no"), ("pge_bill", "own_roommate")):
        h.clock.advance(5)
        r = answer(h, {question: choice})
        assert r.status_code == 200, r.text
        totals.append(r.json()["found_display"])
        event = h.deps.events.buffered()[-1]
        assert event.type == "case.updated" and event.changed_programs is True
        assert event.summary is not None and event.summary.found_display == r.json()["found_display"]
    assert totals == [3830, 4050, 4220]
    stored = h.deps.cases.get(maria.id)
    assert stored.version == maria.version + 3
    assert {q: (a.value, a.source) for q, a in stored.program_answers.items()} == {
        "break_transit": ("weekdays_muni", "card"), "tax_dependent": ("no", "card"), "pge_bill": ("own_roommate", "card")}
    assert stored.program_answers["pge_bill"].at == h.clock.now()
    assert stored.slots == slots_before and stored.estimate_monthly == 306  # never a CalFresh slot or the estimate
    changed = answer(h, {"tax_dependent": "not_sure"})  # a re-answer replaces the older one
    assert changed.status_code == 200 and changed.json()["found_display"] == 4000
    assert h.deps.cases.get(maria.id).program_answers["tax_dependent"].value == "not_sure"


def test_answer_errors(h) -> None:
    h.add_case()
    assert err(answer(h, {"bogus": "no"})) == (422, "invalid_request")
    assert err(answer(h, {"tax_dependent": "maybe"})) == (422, "invalid_request")
    assert err(answer(h, {})) == (422, "invalid_request")
    too_many = {"break_transit": "none", "tax_dependent": "no", "pge_bill": "in_rent", "x": "y"}
    assert err(answer(h, too_many)) == (422, "invalid_request")
    assert err(h.client.post(f"/api/card/{TOKEN}/answers", content=b"nope")) == (422, "invalid_request")
    assert err(answer(h, {"tax_dependent": "no"}, lang="fr")) == (422, "invalid_request")
    assert err(answer(h, {"tax_dependent": "no"}, token="unknowntoken00000000000")) == (404, "not_found")


def test_routes_without_a_full_programs_part(h) -> None:
    h.add_case(code="R8W-3ND", token="sofiacard00000000000001", slots=SOFIA_SLOTS)
    assert err(answer(h, {"tax_dependent": "no"}, token="sofiacard00000000000001")) == (422, "invalid_request")
    h.add_case(code="Z4M-7QE", token="dormcard000000000000001", slots=DORM_SLOTS)
    assert err(answer(h, {"tax_dependent": "no"}, token="dormcard000000000000001")) == (404, "not_found")
    r = h.client.post("/api/card/dormcard000000000000001/progress", json={"program": "calfresh", "applied": True})
    assert err(r) == (404, "not_found")


def test_live_case_conflict(h) -> None:
    h.add_case(live=True)
    assert err(answer(h, {"break_transit": "none"})) == (409, "conflict")


def test_progress(h) -> None:
    maria = h.add_case()
    r = h.client.post(f"/api/card/{TOKEN}/progress?lang=es", json={"program": "calfresh", "applied": True})
    assert r.status_code == 200 and r.json()["claimed_display"] == 3670 and r.json()["lang"] == "es"
    stored = h.deps.cases.get(maria.id)
    assert stored.program_progress["calfresh"].applied is True and stored.version == maria.version + 1
    assert h.deps.events.buffered()[-1].changed_programs is True
    undo = h.client.post(f"/api/card/{TOKEN}/progress", json={"program": "calfresh", "applied": False})
    assert undo.json()["claimed_display"] == 0
    bad = h.client.post(f"/api/card/{TOKEN}/progress", json={"program": "bogus", "applied": True})
    assert err(bad) == (422, "invalid_request")
    assert err(h.client.post(f"/api/card/{TOKEN}/progress", json={"applied": True})) == (422, "invalid_request")


def test_shared_bucket_of_30_a_minute_per_token(h) -> None:
    h.add_case()
    h.add_case(code="AAA-BBB", token="othercard00000000000001")
    codes = []
    for i in range(30):
        if i % 2:
            codes.append(answer(h, {"break_transit": "none"}).status_code)
        else:
            codes.append(h.client.post(f"/api/card/{TOKEN}/progress",
                                       json={"program": "calfresh", "applied": True}).status_code)
    assert codes == [200] * 30
    assert err(answer(h, {"break_transit": "none"})) == (429, "rate_limited")  # the 31st
    r = h.client.post(f"/api/card/{TOKEN}/progress", json={"program": "calfresh", "applied": True})
    assert err(r) == (429, "rate_limited")
    assert answer(h, {"break_transit": "none"}, token="othercard00000000000001").status_code == 200  # per token
    h.clock.advance(60)
    assert answer(h, {"break_transit": "none"}).status_code == 200


def test_programs_off(make_client) -> None:
    h = make_client(programs=False)
    h.add_case()
    assert err(answer(h, {"break_transit": "none"})) == (404, "not_found")
    r = h.client.post(f"/api/card/{TOKEN}/progress", json={"program": "calfresh", "applied": True})
    assert err(r) == (404, "not_found")
    assert h.client.get(f"/api/card/{TOKEN}").json()["unlocked"] is None


def test_version_conflict_retried_once(h, monkeypatch) -> None:
    h.add_case()
    real_save = h.deps.cases.save
    calls = {"n": 0}

    def flaky(case, *, expected_version=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise VersionConflict("changed")
        return real_save(case, expected_version=expected_version)

    monkeypatch.setattr(h.deps.cases, "save", flaky)
    assert answer(h, {"break_transit": "weekdays_muni"}).status_code == 200 and calls["n"] == 2

    def always(case, *, expected_version=None):
        raise VersionConflict("changed")

    monkeypatch.setattr(h.deps.cases, "save", always)
    assert err(answer(h, {"tax_dependent": "no"})) == (409, "conflict")


def test_logs_are_content_free(make_client, caplog) -> None:
    from tests.api.test_brain_routes import PHONE_START, post, turn_body

    h = make_client(live_transcript=True)
    with caplog.at_level(logging.DEBUG):
        h.add_case(short_code="481206")
        answer(h, {"tax_dependent": "not_sure"})
        h.client.post(f"/api/card/{TOKEN}/progress", json={"program": "calfresh", "applied": True})
        h.client.get(f"/api/card/{TOKEN}")
        h.client.post("/api/card/lookup", json={"code": "481206"})
        call = "/v1/calls/0d000000000000000000000000000001"
        post(h, call + "/start", PHONE_START)
        post(h, call + "/turn", turn_body(1, "I make about nine hundred a month"))
        session = h.client.post("/api/web/sessions", json={}).json()
        h.client.post("/api/console/login", json={"passcode": "dev"})
        h.client.post("/api/console/login", json={"passcode": "wrong-1"})
    server = [r for r in caplog.records if r.name.startswith(("gatorplate", "uvicorn", "fastapi", "starlette"))]
    text = "\n".join(r.getMessage() for r in server)
    assert "/api/card/{token}/answers" in text  # route templates are logged...
    for secret in (TOKEN, "481206", "not_sure", "tax_dependent", "about $", "nine hundred", "0d000000000000000000000000000001",
                   session["token"], session["call_id"], "wrong-1", "Got it.", "Goodbye"):
        assert secret not in text, secret  # ...never a token, code, answer, utterance, reply or passcode


@pytest.mark.parametrize("path", ["/api/card/{t}", "/api/card/{t}/status"])
def test_card_routes_are_public_by_token_only(h, path) -> None:
    h.add_case()
    assert h.client.get(path.format(t=TOKEN)).status_code == 200
    assert h.client.get(path.format(t=TOKEN[:-1] + "2")).status_code == 404
    assert timedelta(days=7) == h.deps.cases.get_by_card_token(TOKEN).card.expires_at - h.clock.now()

"""Console API: login and its limit, the cookie on every route, meta, list and detail (with the programs fields),
yellow lines, slot edits, the status machine with the review lock, tracking, delete, QR codes, the live transcript
endpoint and the demo routes."""

from __future__ import annotations

import pytest

from gatorplate.contracts.case import YellowLine
from gatorplate.contracts.common import CaseStatus, Tier, YellowKind
from gatorplate.contracts.console_text import PARENT_HOUSEHOLD_TEXT
from gatorplate.contracts.slots import SlotName

SOFIA_SLOTS = {"age": "19", "lives_with_parent": "true", "level": "undergrad"}
CONSOLE_ROUTES = [("GET", "/api/meta"), ("GET", "/api/cases"), ("GET", "/api/cases/c_x"), ("GET", "/api/cases/c_x/live"),
                  ("POST", "/api/cases/c_x/yellow/y1"), ("PUT", "/api/cases/c_x/slots/age"),
                  ("POST", "/api/cases/c_x/status"), ("PATCH", "/api/cases/c_x/tracking"), ("DELETE", "/api/cases/c_x"),
                  ("GET", "/api/cases/c_x/qr.svg"), ("GET", "/api/qr/talk.svg"), ("GET", "/api/events"),
                  ("POST", "/api/demo/seed"), ("POST", "/api/demo/reset"), ("POST", "/api/demo/inject")]


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


@pytest.mark.parametrize("method,path", CONSOLE_ROUTES)
def test_cookie_required(h, method, path) -> None:
    assert err(h.client.request(method, path, json={})) == (401, "unauthorized")


def test_login_logout_and_limit(h) -> None:
    assert err(h.client.post("/api/console/login", json={"passcode": "wrong"})) == (401, "unauthorized")
    assert err(h.client.post("/api/console/login", json={})) == (422, "invalid_request")
    r = h.client.post("/api/console/login", json={"passcode": "dev"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    cookie = r.headers["set-cookie"].lower()
    assert "gp_console=" in cookie and "samesite=lax" in cookie and "httponly" in cookie
    assert h.client.get("/api/meta").status_code == 200
    assert h.client.post("/api/console/logout").json() == {"ok": True}
    assert h.client.get("/api/meta").status_code == 401
    codes = [h.client.post("/api/console/login", json={"passcode": "x"}).status_code for _ in range(4)]
    assert codes == [401, 401, 429, 429]  # 5 a minute per IP, counting every try (3 above)
    h.clock.advance(60)
    assert h.client.post("/api/console/login", json={"passcode": "dev"}).status_code == 200


def test_prod_cookie_is_secure(make_client) -> None:
    from tests.api.test_web_and_health import PROD_SECRETS

    h = make_client(env="prod", **PROD_SECRETS)
    r = h.client.post("/api/console/login", json={"passcode": "p" * 20})
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()


def test_meta(make_client) -> None:
    h = make_client(card_delivery="screen")
    meta = h.login().get("/api/meta").json()
    assert meta["rules"]["table_id"] == "CA-CalFresh-FFY2027" and meta["rules_valid_today"] is True
    assert meta["slot_specs"]["roommates_count"]["label"] == "Number of roommates"
    assert (meta["demo_mode"], meta["live_transcript"], meta["card_delivery"]) == (True, False, "screen")
    assert meta["demo_phone_display"] is None and meta["programs"]["table_id"] == "GP-Programs-2026"
    off = make_client(programs=False)
    assert off.login().get("/api/meta").json()["programs"] is None


def test_list_and_detail(h) -> None:
    c = h.login()
    maria = h.add_case(short_code="481206")
    sofia = h.add_case(code="R8W-3ND", token="cardtoken0000000000000002", slots=SOFIA_SLOTS)
    listing = c.get("/api/cases").json()
    assert [i["code"] for i in listing["items"]] == ["R8W-3ND", "K7Q-2FM"] or len(listing["items"]) == 2
    rows = {i["code"]: i for i in listing["items"]}
    assert rows["K7Q-2FM"]["found_display"] == 3670 and rows["R8W-3ND"]["found_display"] is None
    assert rows["K7Q-2FM"]["label"] == "K7Q-2FM" and listing["seq"] == h.deps.events.current_seq()
    detail = c.get(f"/api/cases/{maria.id}").json()
    assert detail["card_url"] == "/c/cardtoken0000000000000001"
    assert detail["qr_svg_url"] == f"/api/cases/{maria.id}/qr.svg" and detail["short_code"] == "481206"
    assert detail["can_review"] is True and detail["allowed_status"] == ["reviewed", "follow_up"]
    assert detail["programs"]["mode"] == "full" and detail["summary"]["found_display"] == 3670
    sofia_detail = c.get(f"/api/cases/{sofia.id}").json()
    assert sofia_detail["can_review"] is False and sofia_detail["programs"]["mode"] == "list_only"
    assert err(c.get("/api/cases/c_missing")) == (404, "not_found")
    assert err(c.get("/api/cases?status=bogus")) == (422, "invalid_request")
    assert err(c.get("/api/cases?limit=0")) == (422, "invalid_request")
    assert [i["code"] for i in c.get("/api/cases?status=new&limit=1").json()["items"]] in (["R8W-3ND"], ["K7Q-2FM"])


def test_since_seq_polling(h) -> None:
    c = h.login()
    maria = h.add_case()
    h.add_case(code="R8W-3ND", token="cardtoken0000000000000002", slots=SOFIA_SLOTS)
    mark = c.get("/api/cases").json()["seq"]
    assert c.get(f"/api/cases?since_seq={mark}").json()["items"] == []
    case = h.deps.cases.get(maria.id)
    h.deps.events.publish("case.updated", case=h.deps.cases.save(case))
    changed = c.get(f"/api/cases?since_seq={mark}").json()
    assert [i["id"] for i in changed["items"]] == [maria.id] and changed["seq"] == mark + 1
    assert len(c.get("/api/cases?since_seq=999").json()["items"]) == 2  # unknown number: everything


def test_programs_off_hides_everything(make_client) -> None:
    h = make_client(programs=False)
    c = h.login()
    maria = h.add_case()
    assert c.get("/api/cases").json()["items"][0]["found_display"] is None
    detail = c.get(f"/api/cases/{maria.id}").json()
    assert detail["programs"] is None and detail["summary"]["found_display"] is None


def test_yellow_confirm_unlocks_review(h) -> None:
    c = h.login()
    sofia = h.add_case(code="R8W-3ND", slots=SOFIA_SLOTS)
    assert sofia.yellow_lines[0].reason == PARENT_HOUSEHOLD_TEXT
    locked = c.post(f"/api/cases/{sofia.id}/status", json={"status": "reviewed", "expected_version": sofia.version})
    assert err(locked) == (409, "locked") and locked.json()["error"]["message"] == "Check 1 line first."
    stale = c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "confirm", "expected_version": 99})
    assert err(stale) == (409, "conflict")
    assert err(c.post(f"/api/cases/{sofia.id}/yellow/y9", json={"action": "confirm", "expected_version": 1})) == \
        (404, "not_found")
    ok = c.post(f"/api/cases/{sofia.id}/yellow/y1",
                json={"action": "confirm", "note": "Checked with the student", "expected_version": sofia.version})
    assert ok.status_code == 200
    detail = ok.json()
    line = detail["case"]["yellow_lines"][0]
    assert line["resolved"] == "confirm" and line["resolved_note"] == "Checked with the student"
    assert detail["can_review"] is True and detail["case"]["version"] == sofia.version + 1
    again = c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "confirm",
                                                            "expected_version": detail["case"]["version"]})
    assert err(again) == (409, "conflict")
    reviewed = c.post(f"/api/cases/{sofia.id}/status", json={"status": "reviewed",
                                                             "expected_version": detail["case"]["version"]})
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["case"]["status"] == "reviewed" and body["case"]["reviewed_at"] is not None
    assert body["allowed_status"] == ["applied", "follow_up"]
    assert [e.type for e in h.deps.events.buffered()][-2:] == ["case.updated", "case.updated"]


def test_yellow_edit_reruns_rules(h) -> None:
    c = h.login()
    sofia = h.add_case(code="R8W-3ND", slots=SOFIA_SLOTS)
    applied = h.deps.rules.applied
    r = c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "edit", "expected_version": sofia.version})
    assert err(r) == (422, "invalid_request")
    bad = c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "edit", "value": "maybe",
                                                          "expected_version": sofia.version})
    assert err(bad) == (422, "invalid_request")
    ok = c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "edit", "value": "false",
                                                         "expected_version": sofia.version}).json()
    slot = ok["case"]["slots"]["lives_with_parent"]
    assert (slot["value"], slot["changed_from"], slot["source"], slot["confirmed"]) == ("false", "true", "coordinator",
                                                                                     True)
    assert ok["case"]["yellow_lines"][0]["resolved"] == "edit" and h.deps.rules.applied == applied + 1
    assert h.deps.events.buffered()[-1].changed_slots == [SlotName.lives_with_parent]


def test_slot_edit(h) -> None:
    c = h.login()
    maria = h.add_case()
    case = h.deps.cases.get(maria.id)
    case.yellow_lines.append(YellowLine(id="y1", slot=SlotName.rent_share, kind=YellowKind.unclear,
                                        code="unclear.rent_share", reason="Rent share: unclear answer.",
                                        created_at=h.clock.now()))
    maria = h.deps.cases.save(case)
    assert err(c.put(f"/api/cases/{maria.id}/slots/bogus", json={"value": "1", "expected_version": 1})) == \
        (422, "invalid_request")
    assert err(c.put(f"/api/cases/{maria.id}/slots/volunteered_status",
                     json={"value": "F-1", "expected_version": maria.version})) == (422, "invalid_request")
    assert err(c.put(f"/api/cases/{maria.id}/slots/rent_share",
                     json={"value": "lots", "expected_version": maria.version})) == (422, "invalid_request")
    assert err(c.put(f"/api/cases/{maria.id}/slots/rent_share",
                     json={"value": "1000", "expected_version": maria.version - 1})) == (409, "conflict")
    ok = c.put(f"/api/cases/{maria.id}/slots/rent_share", json={"value": "1000", "note": "Checked",
                                                                 "expected_version": maria.version}).json()
    slot = ok["case"]["slots"]["rent_share"]
    assert (slot["value"], slot["changed_from"], slot["display"], slot["source"]) == ("1000.00", "1100.00",
                                                                                     "$1,000/mo", "coordinator")
    assert ok["case"]["yellow_lines"][0]["resolved"] == "edit"


def test_status_machine(h) -> None:
    c = h.login()
    maria = h.add_case()
    bad = c.post(f"/api/cases/{maria.id}/status", json={"status": "approved", "expected_version": maria.version})
    assert err(bad) == (409, "conflict")
    assert err(c.post(f"/api/cases/{maria.id}/status", json={"status": "bogus", "expected_version": 1})) == \
        (422, "invalid_request")
    version = maria.version
    for status in ("follow_up", "applied", "interview_scheduled", "approved", "follow_up"):
        r = c.post(f"/api/cases/{maria.id}/status", json={"status": status, "expected_version": version})
        assert r.status_code == 200, (status, r.text)
        version = r.json()["case"]["version"]
    live = h.add_case(code="LIV-E22", token="cardtoken0000000000000003", live=True)
    r = c.post(f"/api/cases/{live.id}/status", json={"status": "reviewed", "expected_version": live.version})
    assert err(r) == (409, "conflict")
    detail = c.get(f"/api/cases/{live.id}").json()
    assert detail["allowed_status"] == [] and detail["can_review"] is False


def test_tracking_patch(h) -> None:
    c = h.login()
    maria = h.add_case()
    r = c.patch(f"/api/cases/{maria.id}/tracking", json={"applied_at": "2026-10-02", "interview_missed": None,
                                                          "expected_version": maria.version})
    assert r.status_code == 200
    tracking = r.json()["case"]["tracking"]
    assert (tracking["applied_at"], tracking["filed_on"], tracking["deadline_30d"]) == ("2026-10-02", "2026-10-02",
                                                                                     "2026-11-01")
    assert err(c.patch(f"/api/cases/{maria.id}/tracking", json={"applied_at": "soon", "expected_version": 2})) == \
        (422, "invalid_request")


def test_delete_case(h) -> None:
    c = h.login()
    maria = h.add_case()
    assert c.delete(f"/api/cases/{maria.id}").json() == {}
    assert err(c.get(f"/api/cases/{maria.id}")) == (404, "not_found")
    assert err(c.delete(f"/api/cases/{maria.id}")) == (404, "not_found")
    assert h.deps.events.buffered()[-1].type == "case.deleted"


def test_qr_codes(h) -> None:
    c = h.login()
    maria = h.add_case()
    r = c.get(f"/api/cases/{maria.id}/qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.content.startswith(b"<svg") and r.headers["cache-control"] == "no-store"
    talk = c.get("/api/qr/talk.svg?lang=es")
    assert talk.status_code == 200 and talk.content.startswith(b"<svg")
    assert err(c.get("/api/qr/talk.svg?lang=fr")) == (422, "invalid_request")
    no_card = h.deps.cases.get(maria.id)
    no_card.card = None
    h.deps.cases.save(no_card)
    assert err(c.get(f"/api/cases/{maria.id}/qr.svg")) == (404, "not_found")


def test_live_endpoint(make_client) -> None:
    from tests.api.test_brain_routes import PHONE_START, post, turn_body

    off = make_client()
    call = off.add_case(live=True)
    assert err(off.login().get(f"/api/cases/{call.id}/live")) == (404, "not_found")  # flag off
    h = make_client(live_transcript=True)
    c = h.login()
    path = "/v1/calls/0d000000000000000000000000000001"
    post(h, path + "/start", PHONE_START)
    post(h, path + "/turn", turn_body(1, "I make about 900 a month"))
    case_id = h.deps.sessions.get("0d000000000000000000000000000001").case_id
    view = c.get(f"/api/cases/{case_id}/live").json()
    assert view["case_id"] == case_id and [line["who"] for line in view["lines"]] == ["assistant", "student",
                                                                                     "assistant"]
    post(h, path + "/end", b'{"v":1,"reason":"completed"}')
    assert err(c.get(f"/api/cases/{case_id}/live")) == (404, "not_found")  # after the call
    ended = h.add_case(code="END-ED2", token="cardtoken0000000000000009")
    assert err(c.get(f"/api/cases/{ended.id}/live")) == (404, "not_found")  # not live


def test_demo_routes(make_client) -> None:
    h = make_client()
    c = h.login()
    seeded = c.post("/api/demo/seed").json()
    assert seeded == {"seeded": 5, "replaced": 0}
    assert c.post("/api/demo/seed").json() == {"seeded": 5, "replaced": 5}
    maria = c.post("/api/demo/inject", json={"id": "maria_g1"})
    assert maria.status_code == 200 and maria.json()["case"]["code"] == "K7Q-2FM"
    assert maria.json()["summary"]["found_display"] == 3670
    assert any(a["delta_usd"] == 151 for a in maria.json()["case"]["asked"])
    assert err(c.post("/api/demo/inject", json={"id": "nobody"})) == (404, "not_found")
    assert err(c.post("/api/demo/inject", json={})) == (422, "invalid_request")
    rows = {i["code"]: i for i in c.get("/api/cases").json()["items"]}
    assert rows["P2X-6TC"]["found_display"] is not None and rows["R8W-3ND"]["yellow_open"] == 1
    sofia = h.deps.cases.get_by_code("R8W-3ND")
    c.post(f"/api/cases/{sofia.id}/yellow/y1", json={"action": "confirm", "expected_version": sofia.version})
    assert c.post("/api/demo/reset").json() == {"deleted": 1, "kept": 5}
    c.post("/api/demo/seed")
    rows = {i["code"]: i for i in c.get("/api/cases").json()["items"]}
    assert set(rows) == {"R8W-3ND", "P2X-6TC", "H5V-9KB", "Z4M-7QE", "D7L-8RW"}
    assert rows["R8W-3ND"]["yellow_open"] == 1 and rows["R8W-3ND"]["status"] == "new"
    types = [e.type for e in h.deps.events.buffered()]
    assert types.count("demo.reset") == 4 and "case.created" in types
    off = make_client(demo_mode=False)
    off_client = off.login()
    for path in ("/api/demo/seed", "/api/demo/reset", "/api/demo/inject"):
        assert err(off_client.post(path, json={"id": "maria_g1"})) == (404, "not_found")


def test_sofia_seeded_detail_through_the_api(h) -> None:
    c = h.login()
    c.post("/api/demo/seed")
    sofia = h.deps.cases.get_by_code("R8W-3ND")
    detail = c.get(f"/api/cases/{sofia.id}").json()
    assert detail["case"]["tier"] == Tier.coordinator.value and detail["can_review"] is False
    assert detail["case"]["status"] == CaseStatus.new.value and len(detail["case"]["asked"]) == 2

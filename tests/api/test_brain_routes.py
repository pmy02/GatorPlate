"""Brain API routes: every HMAC vector and check of contracts/examples/hmac_vectors.json, bearer tokens bound to
their call, channel and credential mismatches, the seq rules of docs/BRAIN_API.md §4 (through the fake brain), schema
errors that do not use up a seq, lines, and the Server-Timing header."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gatorplate.api.auth import signature
from gatorplate.config import DEV_GATEWAY_SECRET
from tests.api.fakes import LINES_EN, ROOT

VECTORS = json.loads((ROOT / "contracts" / "examples" / "hmac_vectors.json").read_text(encoding="utf-8"))
CALL = "0d000000000000000000000000000001"
PHONE_START = b'{"v":1,"seq":0,"channel":"phone","lang":"en","test":false}'


def signed(h, method: str, path: str, body: bytes = b"", *, ts: int | None = None, secret: str = DEV_GATEWAY_SECRET):
    stamp = str(int(h.clock.now().timestamp()) if ts is None else ts)
    return {"X-GP-Timestamp": stamp, "X-GP-Signature": signature(secret, stamp, method, path, body),
            "Content-Type": "application/json"}


def post(h, path: str, body: bytes, headers: dict | None = None):
    return h.client.post(path, content=body, headers=headers if headers is not None else signed(h, "POST", path, body))


def turn_body(seq: int, text: str = "Yes.", **extra) -> bytes:
    return json.dumps({"v": 1, "seq": seq, "lang": "en", "event": "utterance", "text": text, **extra}).encode()


def code(response) -> str | None:
    try:
        return response.json()["error"]["code"]
    except (KeyError, TypeError, ValueError):
        return None


def at(h, unix: int) -> None:
    h.clock.set(datetime.fromtimestamp(unix, UTC))


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=[v["name"] for v in VECTORS["vectors"]])
def test_hmac_vectors_are_accepted(h, vector) -> None:
    assert VECTORS["secret"] == DEV_GATEWAY_SECRET
    at(h, int(vector["timestamp"]))
    body = vector["body"].encode("utf-8")
    url = vector["path"] + (f"?{vector['query']}" if vector.get("query") else "")
    headers = {**vector["headers"], "Content-Type": "application/json"}
    r = h.client.request(vector["method"], url, content=body, headers=headers)
    assert r.status_code != 401, (vector["name"], r.text)
    assert signature(DEV_GATEWAY_SECRET, vector["timestamp"], vector["method"], vector["path"], body) == \
        vector["headers"]["X-GP-Signature"]


@pytest.mark.parametrize("check", VECTORS["checks"], ids=[c["name"] for c in VECTORS["checks"]])
def test_hmac_checks(h, check) -> None:
    at(h, check["server_now"])
    if check["path"].endswith("/turn"):  # a started call, so an accepted request reaches the turn logic
        start_path = check["path"].replace("/turn", "/start")
        assert post(h, start_path, PHONE_START).status_code == 200
    r = h.client.request(check["method"], check["path"], content=check["body"].encode("utf-8"),
                         headers={**check["headers"], "Content-Type": "application/json"})
    if check["expect"] == "ok":
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 401 and code(r) == check["expect"], (check["name"], r.text)


def test_check_order_and_messages(h) -> None:
    path = f"/v1/calls/{CALL}/start"
    r = post(h, path, PHONE_START, headers={"X-GP-Timestamp": "1"})
    assert (r.status_code, code(r)) == (401, "unauthorized")
    assert r.json()["error"] == {"code": "unauthorized", "message": "Not allowed.", "retryable": False}
    bad = {"X-GP-Timestamp": "abc", "X-GP-Signature": "v1=" + "0" * 64}
    assert code(post(h, path, PHONE_START, headers=bad)) == "bad_signature"
    old = signed(h, "POST", path, PHONE_START, ts=int(h.clock.now().timestamp()) - 121)
    r = post(h, path, PHONE_START, headers=old)
    assert code(r) == "stale_timestamp" and r.json()["error"]["message"] == "Timestamp outside the allowed window."
    wrong_and_old = signed(h, "POST", path, PHONE_START, ts=1, secret="other")
    assert code(post(h, path, PHONE_START, headers=wrong_and_old)) == "bad_signature"  # signature before time
    web_body = b'{"v":1,"seq":0,"channel":"web","lang":"en","test":false}'
    assert code(post(h, path, web_body)) == "unauthorized"  # gateway credentials are for the phone only


def test_seq_rules_through_the_api(h) -> None:
    path = f"/v1/calls/{CALL}"
    first = post(h, path + "/start", PHONE_START)
    assert first.status_code == 200 and first.json()["interruptible"] is False
    assert post(h, path + "/start", PHONE_START).json() == first.json()  # repeated start: the first reply
    t1 = post(h, path + "/turn", turn_body(1))
    assert t1.status_code == 200 and set(t1.json()) == {"say", "ask", "end", "end_reason", "lang", "listen",
                                                        "expect", "interruptible", "hold_s", "display", "choices",
                                                        "card_url", "debug"}
    again = post(h, path + "/turn", turn_body(1, "something else"))
    assert again.json() == t1.json() and h.deps.brain.processed == [1]  # same seq: stored reply, not reprocessed
    assert post(h, path + "/turn", turn_body(3)).status_code == 200  # a gap is accepted
    stale = post(h, path + "/turn", turn_body(2))
    assert (stale.status_code, code(stale)) == (409, "stale_seq")
    assert stale.json()["error"]["message"] == "seq is older than the last accepted turn."
    for bad in (b'{"v":1,"seq":4,"lang":"en","event":"utterance"}', b'{"v":2,"seq":4,"event":"silence","silence_n":1}',
                b'{"v":1,"seq":4,"lang":"fr","event":"utterance","text":"Oui."}', b"not json",
                b'{"v":1,"seq":4,"event":"dtmf","dtmf":"9x"}', b'{"v":true,"seq":4,"event":"silence","silence_n":1}'):
        r = post(h, path + "/turn", bad)
        assert (r.status_code, code(r)) == (422, "invalid_request"), bad
    unsigned = h.client.post(path + "/turn", content=turn_body(4))
    assert unsigned.status_code == 401
    assert h.deps.brain.processed == [1, 3]  # 401 and 422 never used up a seq
    assert post(h, path + "/turn", turn_body(4)).status_code == 200
    bye = post(h, path + "/turn", turn_body(5, "bye")).json()
    assert bye["end"] is True and bye["end_reason"] == "completed" and bye["ask"] is None
    after = post(h, path + "/turn", turn_body(6)).json()
    assert (after["say"], after["end"], after["end_reason"]) == ("", True, "completed")
    end = b'{"v":1,"reason":"completed","turns":6,"duration_ms":120000}'
    assert post(h, path + "/end", end).json() == {}
    assert post(h, path + "/end", end).json() == {}  # idempotent
    late = post(h, path + "/turn", turn_body(7))
    assert (late.status_code, code(late)) == (409, "conflict")


def test_unknown_call_and_malformed_ids(h) -> None:
    other = "0e000000000000000000000000000007"
    r = post(h, f"/v1/calls/{other}/turn", turn_body(1))
    assert (r.status_code, code(r)) == (404, "unknown_call") and r.json()["error"]["message"] == "No such call."
    end = b'{"v":1,"reason":"caller_hangup","turns":1,"duration_ms":4000}'
    assert code(post(h, f"/v1/calls/{other}/end", end)) == "unknown_call"
    bad = post(h, "/v1/calls/NOT-A-CALL-ID/start", PHONE_START)
    assert (bad.status_code, code(bad)) == (422, "invalid_request")
    assert code(post(h, f"/v1/calls/{other}/end", b'{"v":1,"reason":"later"}')) == "invalid_request"


def test_web_bearer_tokens(h) -> None:
    session = h.client.post("/api/web/sessions", json={"lang": "es"})
    assert session.status_code == 200
    call_id, token = session.json()["call_id"], session.json()["token"]
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    web_start = b'{"v":1,"seq":0,"channel":"web","lang":"es","test":false}'
    assert post(h, f"/v1/calls/{call_id}/start", PHONE_START, auth).status_code == 401  # a bearer starts web only
    started = post(h, f"/v1/calls/{call_id}/start", web_start, auth)
    assert started.status_code == 200 and started.json()["lang"] == "es" and started.json()["display"]
    assert post(h, f"/v1/calls/{call_id}/turn", turn_body(1), auth).status_code == 200
    other = h.client.post("/api/web/sessions", json={}).json()
    other_auth = {"Authorization": f"Bearer {other['token']}", "Content-Type": "application/json"}
    r = post(h, f"/v1/calls/{call_id}/turn", turn_body(2), other_auth)  # bound to another call
    assert (r.status_code, code(r)) == (401, "unauthorized")
    for header in ("Bearer nope", "Bearer ", "Bearer a b"):
        assert post(h, f"/v1/calls/{call_id}/turn", turn_body(2), {"Authorization": header}).status_code == 401
    phone_creds = post(h, f"/v1/calls/{call_id}/turn", turn_body(2))  # gateway signature on a web call
    assert (phone_creds.status_code, code(phone_creds)) == (401, "unauthorized")
    lines = h.client.get("/v1/lines", headers={"Authorization": f"Bearer {token}"})
    assert lines.status_code == 401
    h.clock.advance(minutes=30)
    assert post(h, f"/v1/calls/{call_id}/turn", turn_body(2), auth).status_code == 401  # 30 minutes, then expired


def test_lines(h) -> None:
    r = h.client.get("/v1/lines?lang=en", headers=signed(h, "GET", "/v1/lines"))
    assert r.status_code == 200 and r.json() == LINES_EN
    es = h.client.get("/v1/lines?lang=es", headers=signed(h, "GET", "/v1/lines"))
    assert es.status_code == 200 and es.json()["lang"] == "es"
    bad = h.client.get("/v1/lines?lang=fr", headers=signed(h, "GET", "/v1/lines"))
    assert (bad.status_code, code(bad)) == (422, "invalid_request")
    assert h.client.get("/v1/lines?lang=fr").status_code == 401  # auth comes first


def test_server_timing_and_health(h) -> None:
    r = post(h, f"/v1/calls/{CALL}/start", PHONE_START)
    assert r.headers["server-timing"].startswith("brain;dur=")
    health = h.client.get("/v1/health")
    assert health.status_code == 200 and health.json() == {"ok": True}
    assert health.headers["cache-control"] == "no-store"


def test_end_wipes_the_live_transcript(make_client) -> None:
    h = make_client(live_transcript=True)
    path = f"/v1/calls/{CALL}"
    post(h, path + "/start", PHONE_START)
    post(h, path + "/turn", turn_body(1, "about 900 a month"))
    case_id = h.deps.sessions.get(CALL).case_id
    assert h.deps.live.get(case_id) is not None
    post(h, path + "/end", b'{"v":1,"reason":"caller_hangup"}')
    assert h.deps.live.get(case_id) is None

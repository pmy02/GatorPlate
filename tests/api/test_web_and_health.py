"""Web sessions (20 an hour per IP; loopback exempt outside prod only), the public info, /healthz and the security
headers and pages."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from gatorplate.api.security import CSP
from gatorplate.config import REPO_ROOT

PROD_SECRETS = dict(gateway_secret="g" * 64, console_passcode="p" * 20, session_secret="s" * 48)


def test_web_session_shape_and_limit(h) -> None:
    for i in range(20):
        r = h.client.post("/api/web/sessions", json={"lang": "en"} if i % 2 else {})
        assert r.status_code == 200, i
        body = r.json()
        assert re.fullmatch(r"[a-f0-9]{32}", body["call_id"]) and len(body["token"]) >= 22
        assert body["expires_at"].endswith("Z") or "+00:00" in body["expires_at"]
    limited = h.client.post("/api/web/sessions", json={})
    assert limited.status_code == 429
    assert limited.json()["error"] == {"code": "rate_limited", "retryable": True,
                                       "message": "Too many sessions from this network. Try again later."}
    h.clock.advance(minutes=10)  # the bucket refills over the hour
    assert h.client.post("/api/web/sessions", json={}).status_code == 200


def test_web_session_body_and_token_storage(h) -> None:
    assert h.client.post("/api/web/sessions", content=b"").status_code == 200  # may be empty
    bad = h.client.post("/api/web/sessions", json={"lang": "fr"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    token = h.client.post("/api/web/sessions", json={}).json()["token"]
    stored = [r["token_hash"] for r in h.ctx.db.query("SELECT token_hash FROM web_tokens")]
    assert token not in stored and len(stored) == 2


def test_loopback_exemption_only_outside_prod(make_client) -> None:
    h = make_client()
    local = TestClient(h.app, base_url="https://testserver", client=("127.0.0.1", 50000))
    assert all(local.post("/api/web/sessions", json={}).status_code == 200 for _ in range(25))
    prod = make_client(env="prod", **PROD_SECRETS)
    local_prod = TestClient(prod.app, base_url="https://testserver", client=("127.0.0.1", 50000))
    codes = [local_prod.post("/api/web/sessions", json={}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


def test_public_info(make_client) -> None:
    h = make_client(demo_phone_display="(415) 338-1203")
    body = h.client.get("/api/public/info").json()
    assert body == {"demo_phone_display": "(415) 338-1203", "rules_label": "Rules FY2027",
                    "effective_from": "2026-10-01"}
    assert make_client().client.get("/api/public/info").json()["demo_phone_display"] is None


def test_healthz(make_client) -> None:
    h = make_client(card_delivery="screen", live_transcript=True)
    body = h.client.get("/healthz").json()
    assert body["ok"] is True and body["version"] and body["table_id"] == "CA-CalFresh-FFY2027"
    assert body["rules_valid_today"] is True and body["demo_mode"] is True
    assert (body["card_delivery"], body["debug_keys"], body["live_transcript"]) == ("screen", True, True)
    assert body["programs"] == {"enabled": True, "table_id": "GP-Programs-2026", "valid_today": True}
    assert body["llm"] == {"provider": "fake", "status": "ready", "last_ok_at": None,
                           "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                     "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
    off = make_client(programs=False).client.get("/healthz").json()
    assert off["programs"] == {"enabled": False, "table_id": None, "valid_today": False}


def test_healthz_reads_llm_usage(make_client) -> None:
    from tests.api.fakes import FakeUnderstanding

    health = {"status": "ok", "last_ok_at": "2026-10-02T17:00:00Z",
              "usage": {"calls": 3, "input_tokens": 6000, "output_tokens": 300, "cache_read_input_tokens": 4000,
                        "cache_creation_input_tokens": 1000}}
    h = make_client(understanding=FakeUnderstanding(health))
    assert h.client.get("/healthz").json()["llm"] == {"provider": "fake", **health}
    keyless = make_client(llm_provider="anthropic")
    assert keyless.client.get("/healthz").json()["llm"]["status"] == "no_key"


def test_security_headers_everywhere(h) -> None:
    for path in ("/v1/health", "/api/public/info", "/", "/nope", "/api/cases"):
        r = h.client.get(path)
        assert r.headers["content-security-policy"] == CSP, path
        assert r.headers["referrer-policy"] == "no-referrer" and r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["permissions-policy"] == "microphone=()"
    assert h.client.get("/api/public/info").headers["cache-control"] == "no-store"
    assert "'unsafe-inline'" not in CSP and "frame-ancestors 'none'" in CSP


def test_pages(h) -> None:
    web = REPO_ROOT / "web"
    for path, rel in (("/talk", "talk/index.html"), ("/console", "console/index.html"), ("/go", "go/index.html"),
                      ("/about", "about/index.html"), ("/c/cardtoken0000000000000001", "card/index.html"),
                      ("/", "index.html")):
        r = h.client.get(path)
        if (web / rel).is_file():
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), path
        else:
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path
        expected = "microphone=(self)" if path == "/talk" else "microphone=()"
        assert r.headers["permissions-policy"] == expected
    for path in ("/c/x", "/console", "/go"):
        assert h.client.get(path).headers["x-robots-tag"] == "noindex"
    css = h.client.get("/shared/tokens.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    font = h.client.get("/shared/fonts/Archivo-Variable.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    assert h.client.get("/shared/api.js").headers["content-type"].startswith("text/javascript")
    assert h.client.post("/").json()["error"]["code"] == "not_found"  # no other status codes exist


def test_fixtures_and_harness_only_outside_prod(make_client) -> None:
    dev = make_client()
    assert dev.client.get("/fixtures/index.json").status_code == 200
    prod = make_client(env="prod", **PROD_SECRETS)
    for path in ("/fixtures/index.json", "/fixtures/", "/fixtures", "/unlocked/", "/unlocked/index.html", "/unlocked"):
        r = prod.client.get(path, follow_redirects=False)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path
    for asset in ("unlocked.js", "unlocked.css"):
        if (REPO_ROOT / "web" / "unlocked" / asset).is_file():
            assert prod.client.get(f"/unlocked/{asset}").status_code == 200


def test_unexpected_errors_become_the_internal_envelope(make_client, caplog) -> None:
    from tests.api.test_brain_routes import PHONE_START, post

    class Broken:
        async def start(self, call_id, req):
            raise RuntimeError("secret detail about I make 900")

        def lines(self, lang):
            raise RuntimeError("boom")

    h = make_client(brain=Broken())
    with caplog.at_level("INFO", logger="gatorplate"):
        r = post(h, "/v1/calls/0d000000000000000000000000000001/start", PHONE_START)
    assert r.status_code == 500 and r.json() == {"error": {"code": "internal", "retryable": True,
                                                           "message": "Something went wrong on our side."}}
    assert r.headers["content-security-policy"] == CSP and r.headers["cache-control"] == "no-store"
    logged = "\n".join(rec.getMessage() for rec in caplog.records if rec.name.startswith("gatorplate"))
    assert "RuntimeError" in logged and "900" not in logged and "secret" not in logged


def test_programs_off_keeps_event_summaries_null(make_client) -> None:
    h = make_client(programs=False)
    case = h.add_case()
    event = h.deps.events.publish("case.updated", case=case)
    assert event.summary is not None and event.summary.found_display is None
    on = make_client()
    case = on.add_case(code="AAA-BBB", token="cardtoken0000000000000002")
    assert on.deps.events.publish("case.updated", case=case).summary.found_display == 3670


def test_oversized_bodies_are_refused(h) -> None:
    big = b'{"lang": "en", "pad": "' + b"x" * 70_000 + b'"}'
    r = h.client.post("/api/web/sessions", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["message"] == "Request body too large."
    turn = h.client.post("/v1/calls/0d000000000000000000000000000001/turn", content=big)
    assert turn.status_code == 422


def test_static_cache_headers(h) -> None:
    """Pages and their assets revalidate on every load; fonts are cached for a day; API answers are never stored."""
    for path in ("/", "/landing.css", "/landing.js", "/shared/tokens.css", "/shared/icons.svg", "/talk", "/console"):
        r = h.client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path
    font = h.client.get("/shared/fonts/Archivo-Variable.woff2")
    assert font.status_code == 200 and font.headers["cache-control"] == "public, max-age=86400"
    assert font.headers["content-type"] == "font/woff2"
    assert h.client.get("/healthz").headers["cache-control"] == "no-store"
    assert h.client.get("/api/public/info").headers["cache-control"] == "no-store"

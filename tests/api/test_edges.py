"""Edges of the HTTP layer: dev-only files in prod for every method and path spelling, the calendar file when only an
application date is known, polling with since_seq for an old case, rate-limit addresses behind the hosting proxy,
chunked bodies, Pacific wall-clock interview times, and one request at a time per call while different calls run
side by side."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from gatorplate.api.routes_pages import dev_only
from tests.api.test_brain_routes import PHONE_START, post, signed, turn_body

PROD_SECRETS = dict(gateway_secret="g" * 64, console_passcode="p" * 20, session_secret="s" * 48)
TOKEN = "cardtoken0000000000000001"
PT = ZoneInfo("America/Los_Angeles")


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


# ---------------------------------------------------------------------------------------------- dev-only files


@pytest.mark.parametrize("path, hidden", [
    ("fixtures/index.json", True), ("fixtures", True), ("Fixtures/meta.json", True), ("unlocked", True),
    ("unlocked/index.html", True), ("./unlocked/./index.html", True), ("unlocked/unlocked.js", False),
    ("unlocked/unlocked.css", False), ("card/index.html", False), (".", False), ("shared/tokens.css", False),
])
def test_dev_only_paths(path, hidden) -> None:
    assert dev_only(path) is hidden


def test_prod_hides_fixtures_and_harness_for_every_spelling(make_client) -> None:
    prod = make_client(env="prod", **PROD_SECRETS)
    # Absolute URLs keep a raw path such as "//unlocked/…" (a relative "//x" would name a host).
    for method, path in (("HEAD", "/fixtures/index.json"), ("GET", "//fixtures/index.json"),
                         ("GET", "//unlocked/index.html"), ("GET", "//unlocked/"), ("HEAD", "/unlocked/index.html"),
                         ("GET", "/unlocked//index.html"), ("GET", "/Fixtures/index.json"),
                         ("GET", "/fixtures/../fixtures/index.json")):
        r = prod.client.request(method, "https://testserver" + path, follow_redirects=False)
        assert r.status_code == 404, (method, path)
    if (prod.ctx.web_dir / "unlocked" / "unlocked.js").is_file():
        assert prod.client.get("/unlocked/unlocked.js").status_code == 200  # the card page loads it
    dev = make_client()
    assert dev.client.head("/fixtures/index.json").status_code == 200


# ---------------------------------------------------------------------------------------------- calendar file


def test_reminders_follow_the_card_builder(h) -> None:
    """The route asks the card builder; a recorded application date is enough for the three dates, and with no filing
    day at all the answer is 404 (never a 500)."""
    case = h.add_case(tier=None, slots={"age": "20"})  # no result yet, so no filing-date estimate
    stored = h.deps.cases.get(case.id)
    assert stored.first_month is None
    assert err(h.client.get(f"/api/card/{TOKEN}/reminders.ics")) == (404, "not_found")
    stored.tracking.applied_at = stored.tracking.filed_on = date(2026, 10, 5)
    h.deps.cases.save(stored)
    r = h.client.get(f"/api/card/{TOKEN}/reminders.ics")
    assert r.status_code == 200 and r.text.count("BEGIN:VEVENT") == 3 and "20261012" in r.text


def test_reminders_pass_now_to_a_builder_that_takes_it(h) -> None:
    seen = {}

    def ics(case, *, lang, now=None):
        seen["now"] = now
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    h.add_case()
    h.deps.cards.ics = ics
    assert h.client.get(f"/api/card/{TOKEN}/reminders.ics").status_code == 200
    assert seen["now"] == h.clock.now()


# ---------------------------------------------------------------------------------------------- polling


def test_since_seq_finds_an_old_case_past_the_list_limit(h) -> None:
    c = h.login()
    old = h.add_case(code="AAA-AAA", token="oldcard00000000000000001")
    h.clock.advance(minutes=5)
    for i in range(3):
        h.add_case(code=f"BBB-BB{i + 2}", token=f"newcard0000000000000000{i + 2}")
    mark = c.get("/api/cases").json()["seq"]
    h.client.post(f"/api/card/{old.card.token}/answers", json={"answers": {"break_transit": "none"}})
    r = c.get(f"/api/cases?since_seq={mark}&limit=2").json()
    assert [i["code"] for i in r["items"]] == ["AAA-AAA"] and r["seq"] > mark
    assert c.get(f"/api/cases?since_seq={r['seq']}").json()["items"] == []
    assert len(c.get("/api/cases?limit=2").json()["items"]) == 2  # without since_seq: the newest
    assert err(c.get("/api/cases?since_seq=-1")) == (422, "invalid_request")
    assert err(c.get("/api/cases?limit=0")) == (422, "invalid_request")
    assert err(c.get("/api/cases?status=bogus")) == (422, "invalid_request")


# ---------------------------------------------------------------------------------------------- client addresses


def _behind_proxy(app):
    """The app as production runs it: uvicorn trusts every forwarded header (the hosting proxy is the peer)."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    return ProxyHeadersMiddleware(app, trusted_hosts="*")


def test_rate_limits_count_the_address_the_proxy_saw(make_client) -> None:
    prod = make_client(env="prod", **PROD_SECRETS)
    client = TestClient(_behind_proxy(prod.app), base_url="https://testserver", client=("10.0.0.1", 40000))
    codes = [client.post("/api/web/sessions", json={},
                         headers={"X-Forwarded-For": f"203.0.113.{i}, 198.51.100.7"}).status_code for i in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429  # a fresh first entry per request does not escape
    other = client.post("/api/web/sessions", json={}, headers={"X-Forwarded-For": "198.51.100.8"})
    assert other.status_code == 200  # another real address has its own bucket
    for _ in range(5):
        client.post("/api/card/lookup", json={"code": "123456"}, headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.9"})
    sixth = client.post("/api/card/lookup", json={"code": "123456"}, headers={"X-Forwarded-For": "2.2.2.2, 198.51.100.9"})
    assert err(sixth) == (429, "rate_limited")


def test_a_forwarded_loopback_address_is_not_exempt(make_client) -> None:
    dev = make_client()
    remote = TestClient(dev.app, base_url="https://testserver", client=("192.0.2.10", 40000))
    codes = [remote.post("/api/web/sessions", json={}, headers={"X-Forwarded-For": "127.0.0.1"}).status_code
             for _ in range(21)]
    assert codes[20] == 429
    local = TestClient(dev.app, base_url="https://testserver", client=("127.0.0.1", 40000))
    assert all(local.post("/api/web/sessions", json={}).status_code == 200 for _ in range(25))


# ---------------------------------------------------------------------------------------------- bodies


def test_chunked_bodies_are_capped_while_reading(h) -> None:
    def chunks():
        yield b'{"lang": "en", "pad": "'
        for _ in range(80):
            yield b"x" * 1024
        yield b'"}'

    r = h.client.post("/api/web/sessions", content=chunks(), headers={"Content-Type": "application/json"})
    assert err(r) == (422, "invalid_request") and r.json()["error"]["message"] == "Request body too large."
    small = h.client.post("/api/web/sessions", content=iter([b'{"lang":', b' "es"}']))
    assert small.status_code == 200


def test_a_signed_body_sent_in_chunks_still_verifies(h) -> None:
    path = "/v1/calls/0d000000000000000000000000000001/start"
    headers = signed(h, "POST", path, PHONE_START)
    r = h.client.post(path, content=iter([PHONE_START[:10], PHONE_START[10:]]), headers=headers)
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------------------------- tracking times


def test_interview_time_without_offset_is_pacific_and_stored_in_utc(h) -> None:
    c = h.login()
    case = h.add_case()
    r = c.patch(f"/api/cases/{case.id}/tracking",
                json={"interview_at": "2026-10-05T10:00:00", "expected_version": case.version})
    assert r.status_code == 200, r.text
    stored = h.deps.cases.get(case.id).tracking.interview_at
    assert stored == datetime(2026, 10, 5, 10, 0, tzinfo=PT) and stored.utcoffset().total_seconds() == 0
    assert r.json()["case"]["tracking"]["interview_at"].startswith("2026-10-05T17:00:00")
    r = c.patch(f"/api/cases/{case.id}/tracking",
                json={"interview_at": "2026-10-06T09:30:00-07:00", "expected_version": r.json()["case"]["version"]})
    assert h.deps.cases.get(case.id).tracking.interview_at == datetime(2026, 10, 6, 16, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------------------------- per-call order


class SlowBrain:
    """Records the order of starts and ends and how many requests of one call overlap."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.active: dict[str, int] = {}
        self.max_same_call = 0
        self.running = 0
        self.max_running = 0

    async def _work(self, call_id: str, what: str) -> None:
        self.active[call_id] = self.active.get(call_id, 0) + 1
        self.running += 1
        self.max_same_call = max(self.max_same_call, self.active[call_id])
        self.max_running = max(self.max_running, self.running)
        self.events.append((call_id, what + ".begin"))
        await asyncio.sleep(0.05)
        self.events.append((call_id, what + ".done"))
        self.active[call_id] -= 1
        self.running -= 1

    async def start(self, call_id, req):
        from tests.api.fakes import _reply

        await self._work(call_id, "start")
        return _reply("Hi.", "Okay to start?", lang=req.lang, web=False, interruptible=False)

    async def turn(self, call_id, req):  # pragma: no cover - not used here
        raise NotImplementedError

    async def end(self, call_id, req):
        await self._work(call_id, "end")

    def lines(self, lang):  # pragma: no cover - not used here
        raise NotImplementedError


async def test_one_request_at_a_time_per_call_and_calls_side_by_side(make_client) -> None:
    brain = SlowBrain()
    h = make_client(brain=brain)
    end_body = b'{"v":1,"reason":"caller_hangup"}'
    calls = [f"0c00000000000000000000000000000{i}" for i in (1, 2, 3)]
    transport = httpx.ASGITransport(app=h.app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        async def send(call_id: str, step: str, body: bytes) -> int:
            path = f"/v1/calls/{call_id}/{step}"
            r = await client.post(path, content=body, headers=signed(h, "POST", path, body))
            return r.status_code

        jobs = []
        for call_id in calls:
            jobs.append(send(call_id, "start", PHONE_START))
            jobs.append(send(call_id, "end", end_body))  # an /end that arrives while /start runs waits for it
        assert await asyncio.gather(*jobs) == [200] * 6
    assert brain.max_same_call == 1 and brain.max_running > 1
    for call_id in calls:
        mine = [what for cid, what in brain.events if cid == call_id]
        assert mine == ["start.begin", "start.done", "end.begin", "end.done"]


def test_a_bad_turn_after_a_good_one_keeps_the_stored_reply(h) -> None:
    """Retries are safe: a body the schema refuses (422) between two sends of the same seq changes nothing."""
    path = "/v1/calls/0d000000000000000000000000000001"
    post(h, path + "/start", PHONE_START)
    first = post(h, path + "/turn", turn_body(1, "Yes."))
    assert err(post(h, path + "/turn", b'{"v":1,"seq":2,"event":"utterance","text":' + json.dumps("x" * 1001).encode()
                    + b"}")) == (422, "invalid_request")
    assert post(h, path + "/turn", turn_body(1, "Yes.")).json() == first.json()


# ---------------------------------------------------------------------------------------------- demo events


def test_an_inject_that_replaces_a_case_tells_the_consoles(h) -> None:
    c = h.login()
    first = c.post("/api/demo/inject", json={"id": "maria_g1"}).json()["case"]
    mark = h.deps.events.current_seq()
    second = c.post("/api/demo/inject", json={"id": "maria_g1"}).json()["case"]
    after = [(e.type, e.case_id) for e in h.deps.events.buffered() if e.seq > mark]
    assert after == [("case.deleted", first["id"]), ("case.created", second["id"])]
    assert c.get(f"/api/cases?since_seq={mark}").json()["items"][0]["id"] == second["id"]


def test_demo_routes_need_the_console_cookie(make_client) -> None:
    h = make_client()
    for path in ("/api/demo/seed", "/api/demo/reset", "/api/demo/inject"):
        assert err(h.client.post(path, json={"id": "maria_g1"})) == (401, "unauthorized")
    assert h.deps.cases.count() == 0


def test_made_up_card_tokens_get_no_bucket(h) -> None:
    for i in range(40):
        r = h.client.post(f"/api/card/madeuptoken{i:014d}/answers", json={"answers": {"break_transit": "none"}})
        assert err(r) == (404, "not_found")
    assert h.ctx.limits.card_programs.size() == 0


def test_calendar_file_name_never_says_reminders(h) -> None:
    """docs/SPEC.md §6.3: the student sees "dates", never "reminders", after the download."""
    h.add_case()
    r = h.client.get(f"/api/card/{TOKEN}/reminders.ics")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="gatorplate-dates.ics"'


def test_widget_files_public_and_harness_dev_only() -> None:
    """The card widget's three files are served in prod; its fixture harness (page, script, stylesheet) is not."""
    from gatorplate.api.routes_pages import dev_only

    for public in ("unlocked/unlocked.js", "unlocked/unlocked-lib.mjs", "unlocked/unlocked.css"):
        assert dev_only(public) is False, public
    for private in ("unlocked", "unlocked/index.html", "unlocked/harness.js", "Unlocked/Harness.css",
                    "fixtures/index.json"):
        assert dev_only(private) is True, private

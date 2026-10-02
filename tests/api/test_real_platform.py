"""The platform with every real module behind it — rules engine, understanding (fake language model), dialogue brain,
card builder and programs engine — on the platform's own stores, driven over HTTP the way the gateway and the talk
page drive it: every contract example scenario (docs/BRAIN_API.md §14) replays with its status codes, error codes and
sentence keys; Maria's phone call fills the console with the W1 data and her card answers count up (W4); a voice
"delete my data" leaves no call state behind once the janitor has run. Each test skips while a module it needs is
still a stub (the integrator runs the same wiring at G2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gatorplate.api.app import create_app
from gatorplate.config import DEV_CONSOLE_PASSCODE, DEV_GATEWAY_SECRET, REPO_ROOT
from gatorplate.deps import Deps
from gatorplate.ids import FixedIds
from gatorplate.store import CaseStore, Counters, Database, EventBus, LiveStore, SessionStore
from tests.api.fakes import make_settings

EXAMPLES = REPO_ROOT / "contracts" / "examples"
SCENARIO_FILES = ["maria_phone.json", "sofia_web_es.json", "jamal_phone_expedited.json", "edge_cases.json"]


def real_deps(settings: Any, clock: Any) -> Deps:
    """The real modules on the platform's stores (what the integrator's wiring builds)."""
    try:
        from gatorplate.card import CardBuilder
        from gatorplate.dialogue import Brain
        from gatorplate.extract.service import Understander
        from gatorplate.programs import Programs
        from gatorplate.rules import Rules

        db = Database(settings.db_file)
        cases, sessions = CaseStore(db, clock=clock), SessionStore(db)
        live, events = LiveStore(), EventBus(clock=clock, tz=settings.tz)
        ids = FixedIds(short_codes=["481206"])
        rules = Rules(settings.rules_table_path, tz=settings.tz)
        understanding = Understander.from_settings(settings, counters=Counters(db, clock=clock), clock=clock)
        programs = Programs.from_settings(settings)
        cards = CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz)
        brain = Brain(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, cases=cases,
                      sessions=sessions, live=live, events=events, cards=cards)
        rules.valid_on(clock.today())
        programs.meta()
    except NotImplementedError as exc:  # pragma: no cover - only while a module is still a stub
        pytest.skip(f"a module is not built yet: {exc}")
    return Deps(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, brain=brain,
                cases=cases, sessions=sessions, live=live, events=events, cards=cards, programs=programs)


class Platform:
    def __init__(self, tmp_db: Any, clock: Any, **overrides: Any) -> None:
        self.settings = make_settings(tmp_db, **overrides)
        self.clock = clock
        self.deps = real_deps(self.settings, clock)
        self.app = create_app(self.deps)
        self.client = TestClient(self.app, base_url="https://testserver")

    @property
    def ctx(self) -> Any:
        return self.app.state.ctx

    def target(self) -> Any:
        from tools import e2e_run as runner

        target = runner.Target(client=self.client, base="https://testserver", secret=DEV_GATEWAY_SECRET,
                               passcode=DEV_CONSOLE_PASSCODE, debug_keys=True,
                               card_delivery=self.settings.card_delivery)
        target.clock = lambda: self.clock.now().timestamp()
        return target

    def phone(self, call_id: str, step: str, body: dict) -> Any:
        from tools import e2e_run as runner

        path = f"/v1/calls/{call_id}/{step}"
        raw = json.dumps(body).encode()
        headers = {**runner.sign(DEV_GATEWAY_SECRET, "POST", path, raw, ts=int(self.clock.now().timestamp())),
                   "Content-Type": "application/json"}
        return self.client.post(path, content=raw, headers=headers)

    def login(self) -> None:
        assert self.client.post("/api/console/login", json={"passcode": DEV_CONSOLE_PASSCODE}).status_code == 200


@pytest.fixture
def platform(clean_gp_env, tmp_db, fixed_clock):
    made: list[Platform] = []

    def build(**overrides: Any) -> Platform:
        p = Platform(tmp_db, fixed_clock, **overrides)
        made.append(p)
        return p

    yield build
    for p in made:
        p.client.close()


def scenarios() -> list[Any]:
    out = []
    for name in SCENARIO_FILES:
        for sc in json.loads((EXAMPLES / name).read_text(encoding="utf-8"))["scenarios"]:
            out.append(pytest.param(sc, id=sc["id"]))
    return out


async def _prime(p: Platform, scenario: dict) -> None:
    """The call state a scenario's `given` block describes, built with the dialogue tests' helper on the platform's
    stores (the example's own call_id), plus a web token for every bearer token the scenario names."""
    from types import SimpleNamespace

    from tests.dialogue.replay import prime

    call_id = scenario.get("call_id")
    rig = SimpleNamespace(brain=p.deps.brain, call_id=call_id, sessions=p.deps.sessions, cases=p.deps.cases, seq=0)
    await prime(rig, scenario)
    for ex in scenario["exchanges"]:
        header = (ex["request"].get("headers") or {}).get("Authorization", "")
        if header.startswith("Bearer "):
            token = header.removeprefix("Bearer ")
            p.ctx.webtokens.issue(token, "f" * 32 if "other" in token else call_id)


def _send(p: Platform, ex: dict) -> Any:
    from tools import e2e_run as runner

    req = ex["request"]
    raw = req["body_raw"].encode("utf-8") if "body_raw" in req else (
        json.dumps(req["body"]).encode("utf-8") if req.get("body") is not None else b"")
    headers = dict(req.get("headers") or {})
    if not headers and req.get("auth") == "gateway":
        headers = runner.sign(DEV_GATEWAY_SECRET, req["method"], req["path"], raw, ts=int(p.clock.now().timestamp()))
    headers.setdefault("Content-Type", "application/json")
    return p.client.request(req["method"], req["path"], params=req.get("query"), content=raw, headers=headers)


@pytest.mark.parametrize("scenario", scenarios())
async def test_contract_examples_over_http(platform, scenario) -> None:
    """Every scenario, in-process: scenarios with a `given` call state are primed on the stores, `server_now` sets
    the clock, the rate-limit scenario first uses up its address's 20 sessions. Statuses, error codes and the
    sentence keys (debug keys on) must match; a web scenario without `given` takes its token from its own
    web_session exchange."""
    from tools import e2e_run as runner

    env = runner.scenario_env(scenario)
    p = platform(card_delivery=env["GP_CARD_DELIVERY"])
    if scenario.get("server_now") is not None:
        p.clock.set(datetime.fromtimestamp(int(scenario["server_now"]), UTC))
    if not scenario.get("given") and not scenario.get("server_now") and scenario["id"] != "web_session_rate_limited":
        result = runner.Replayer(scenario, p.target(), runner.OutputGuard()).run()
        assert result.failures == [], result.failures
        return
    if scenario["id"] == "web_session_rate_limited":
        for _ in range(20):
            assert p.client.post("/api/web/sessions", json={}).status_code == 200
    await _prime(p, scenario)
    for n, ex in enumerate(scenario["exchanges"]):
        r = _send(p, ex)
        want = ex["response"]
        assert r.status_code == want["status"], (n, ex.get("note"), r.text)
        expected_error = ((want.get("body") or {}).get("error") or {}).get("code")
        if expected_error:
            assert r.json()["error"]["code"] == expected_error, (n, r.text)
        if r.status_code == 200 and "keys" in ex:
            assert r.json()["debug"]["keys"] == ex["keys"], (n, r.json()["debug"])


def maria_call(p: Platform, call_id: str = "0a000000000000000000000000000001") -> list[dict]:
    """Maria's phone call as in contracts/examples/maria_phone.json; returns every reply (the last is /end's {})."""
    sc = json.loads((EXAMPLES / "maria_phone.json").read_text(encoding="utf-8"))["scenarios"][0]
    replies: list[dict] = []
    for ex in sc["exchanges"]:
        req = ex["request"]
        step = req["path"].rsplit("/", 1)[-1]
        r = p.phone(call_id, step, req["body"])
        assert r.status_code == ex["response"]["status"], (step, r.text)
        replies.append(r.json())
    return replies


def test_maria_call_fills_the_console_and_her_card_counts_up(platform) -> None:
    p = platform(card_delivery="screen")
    p.login()
    maria_call(p)
    items = p.client.get("/api/cases").json()["items"]
    assert len(items) == 1 and items[0]["live"] is False and items[0]["estimate_monthly"] == 306
    detail = p.client.get(f"/api/cases/{items[0]['id']}").json()
    case = detail["case"]
    assert (case["tier"], case["reason_code"], case["expedited_possible"]) == ("likely", "likely", "no")
    flip = next(a for a in case["asked"] if a["key"] == "flip.rent_paid_by_others")
    assert flip["reason"] == "could change the estimate by $151: $155 or $306"
    assert {s["slot"] for s in case["skipped"]} >= {"heat_cool", "other_utils"}
    assert detail["summary"]["yellow_open"] == 0 and detail["summary"]["found_display"] == 3670
    assert detail["programs"]["mode"] == "full"
    token = detail["card_url"].removeprefix("/c/")
    totals = []
    for question, choice in (("break_transit", "weekdays_muni"), ("tax_dependent", "no"),
                             ("pge_bill", "own_roommate")):
        r = p.client.post(f"/api/card/{token}/answers?lang=en", json={"answers": {question: choice}})
        assert r.status_code == 200, r.text
        totals.append(r.json()["found_display"])
    assert totals == [3830, 4050, 4220]
    after = p.client.get(f"/api/cases/{case['id']}").json()
    assert after["case"]["version"] == case["version"] + 3  # every card answer is a save
    assert after["summary"]["found_display"] == 4220 and after["case"]["slots"] == case["slots"]
    assert after["case"]["estimate_monthly"] == 306  # a card answer never touches CalFresh
    ics = p.client.get(f"/api/card/{token}/reminders.ics")
    assert ics.status_code == 200 and ics.text.count("BEGIN:VEVENT") == 3


def test_three_calls_and_a_restart_mid_call(platform, tmp_db) -> None:
    """Three calls interleaved turn by turn each get their own case; a new app on the same database (a restart)
    continues a call where it stopped (docs/SPEC.md §4.12 items 12.8 and 12.9)."""
    p = platform(card_delivery="code")
    sc = json.loads((EXAMPLES / "maria_phone.json").read_text(encoding="utf-8"))["scenarios"][0]
    calls = [f"0a00000000000000000000000000000{i}" for i in (1, 2, 3)]
    exchanges = sc["exchanges"]
    for ex in exchanges[:5]:
        for call_id in calls:
            req = ex["request"]
            r = p.phone(call_id, req["path"].rsplit("/", 1)[-1], req["body"])
            assert r.status_code == 200, r.text
    restarted = Platform(tmp_db, p.clock, card_delivery="code")
    try:
        for ex in exchanges[5:]:
            for call_id in calls:
                req = ex["request"]
                r = restarted.phone(call_id, req["path"].rsplit("/", 1)[-1], req["body"])
                assert r.status_code == ex["response"]["status"], r.text
        restarted.login()
        items = restarted.client.get("/api/cases").json()["items"]
        assert len(items) == 3 and {i["estimate_monthly"] for i in items} == {306}
        assert {i["live"] for i in items} == {False}
    finally:
        restarted.client.close()


async def test_voice_delete_leaves_no_call_state(platform) -> None:
    p = platform()
    call_id = "0b000000000000000000000000000002"
    assert p.phone(call_id, "start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en"}).status_code == 200
    replies = [p.phone(call_id, "turn", {"v": 1, "seq": seq, "lang": "en", "event": "utterance", "text": text}).json()
               for seq, text in ((1, "Yes."), (2, "Please delete my data."), (3, "Yes, delete it."))]
    assert replies[-1]["end"] is True
    assert p.deps.cases.count() == 0
    assert p.phone(call_id, "end", {"v": 1, "reason": "completed"}).status_code == 200
    p.clock.advance(minutes=11)
    await p.ctx.janitor.tick()
    assert p.deps.sessions.get(call_id) is None and p.deps.sessions.count() == 0


def test_healthz_reads_the_real_understanding(platform) -> None:
    body = platform().client.get("/healthz").json()
    assert body["llm"]["provider"] == "fake" and body["llm"]["status"] in ("ready", "ok")
    assert set(body["llm"]["usage"]) == {"calls", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}
    assert body["programs"] == {"enabled": True, "table_id": "GP-Programs-2026", "valid_today": True}


def test_card_lookup_by_the_spoken_code(platform) -> None:
    """GP_CARD_DELIVERY=code: the code read on the phone opens the card at /go (5 tries a minute per address)."""
    p = platform(card_delivery="code")
    maria_call(p)
    r = p.client.post("/api/card/lookup", json={"code": "481206"})
    assert r.status_code == 200 and r.json()["url"].startswith("/c/")
    p.clock.advance(hours=24)
    assert p.client.post("/api/card/lookup", json={"code": "481206"}).status_code == 404  # 24 hours


def test_live_transcript_with_the_real_brain(platform) -> None:
    """GP_LIVE_TRANSCRIPT=1: lines readable during the call, never in the replay buffer, gone (404) after /end."""
    p = platform(live_transcript=True, card_delivery="screen")
    p.login()
    sc = json.loads((EXAMPLES / "maria_phone.json").read_text(encoding="utf-8"))["scenarios"][0]
    call_id = "0a000000000000000000000000000009"
    for ex in sc["exchanges"][:4]:
        req = ex["request"]
        assert p.phone(call_id, req["path"].rsplit("/", 1)[-1], req["body"]).status_code == 200
    case_id = p.deps.sessions.get(call_id).case_id
    live = p.client.get(f"/api/cases/{case_id}/live")
    assert live.status_code == 200
    lines = live.json()["lines"]
    assert {line["who"] for line in lines} == {"student", "assistant"} and live.json()["now_asking"]
    assert all(e.type.startswith(("case.", "demo.")) for e in p.deps.events.buffered())
    assert p.phone(call_id, "end", {"v": 1, "reason": "caller_hangup"}).status_code == 200
    assert p.client.get(f"/api/cases/{case_id}/live").status_code == 404
    assert p.deps.live.get(case_id) is None
    detail = p.client.get(f"/api/cases/{case_id}").json()
    assert detail["case"]["live"] is False and detail["case"]["ended_early"] is True
    assert [y["kind"] for y in detail["case"]["yellow_lines"] if y["resolved"] is None] == ["incomplete"]
    assert detail["programs"] is None and detail["summary"]["found_display"] is None  # no result: no programs part


def test_console_meta_and_card_errors_with_the_real_engines(platform) -> None:
    p = platform()
    p.login()
    meta = p.client.get("/api/meta").json()
    assert meta["programs"]["table_id"] == "GP-Programs-2026" and meta["rules_valid_today"] is True
    assert "roommates_count" in meta["slot_specs"]
    p.client.post("/api/demo/seed")
    rows = {i["code"]: i for i in p.client.get("/api/cases").json()["items"]}
    sofia = p.client.get(f"/api/cases/{rows['R8W-3ND']['id']}").json()
    jamal = p.client.get(f"/api/cases/{rows['P2X-6TC']['id']}").json()
    assert sofia["programs"]["mode"] == "list_only" and sofia["summary"]["found_display"] is None
    sofia_token = sofia["card_url"].removeprefix("/c/")
    jamal_token = jamal["card_url"].removeprefix("/c/")
    assert p.client.get(f"/api/card/{sofia_token}").json()["unlocked"]["mode"] == "list_only"

    def code(r: Any) -> tuple[int, str]:
        return r.status_code, r.json()["error"]["code"]

    answers = f"/api/card/{sofia_token}/answers"
    assert code(p.client.post(answers, json={"answers": {"tax_dependent": "no"}})) == (422, "invalid_request")
    answers = f"/api/card/{jamal_token}/answers"
    assert code(p.client.post(answers, json={"answers": {"pge_bill": "own_mine"}})) == (422, "invalid_request")
    assert code(p.client.post(answers, json={"answers": {"tax_dependent": "maybe"}})) == (422, "invalid_request")
    assert code(p.client.post(answers, json={"answers": {"ssn": "123"}})) == (422, "invalid_request")
    assert code(p.client.post(answers, json={"answers": {}})) == (422, "invalid_request")
    again = p.client.post(answers, json={"answers": {"break_transit": "weekdays_muni"}})  # a re-answer replaces
    assert again.status_code == 200 and again.json()["found_display"] > 3980
    progress = f"/api/card/{jamal_token}/progress"
    assert code(p.client.post(progress, json={"program": "care", "applied": True})) == (422, "invalid_request")
    marked = p.client.post(progress, json={"program": "calfresh", "applied": True})
    assert marked.status_code == 200 and marked.json()["claimed_display"] == 3670
    case = p.deps.cases.get(jamal["case"]["id"])
    assert case.program_answers["break_transit"].source == "card" and case.program_progress["calfresh"].applied
    assert p.client.delete(f"/api/card/{jamal_token}").json() == {}
    assert p.deps.cases.get(jamal["case"]["id"]) is None  # the answers and marks went with the case


async def test_janitor_with_the_real_brain(platform) -> None:
    """An idle call is closed as a timeout (incomplete, its yellow line); at 23:30 Pacific the daily demo reset
    removes the judge's case and brings back the samples with Sofia's open line and Jamal's card answers."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from gatorplate.contracts.common import YellowResolution

    p = platform(daily_reset=True)
    p.login()
    p.client.post("/api/demo/seed")
    call_id = "0b000000000000000000000000000003"
    assert p.phone(call_id, "start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en"}).status_code == 200
    assert p.phone(call_id, "turn", {"v": 1, "seq": 1, "lang": "en", "event": "utterance",
                                     "text": "Yes."}).status_code == 200
    case_id = p.deps.sessions.get(call_id).case_id
    p.clock.advance(minutes=11)
    assert (await p.ctx.janitor.tick())["closed"] == 1
    closed = p.deps.cases.get(case_id)
    assert not closed.live and closed.ended_early and [y.code for y in closed.yellow_lines] == ["incomplete"]
    late = p.phone(call_id, "turn", {"v": 1, "seq": 2, "lang": "en", "event": "utterance", "text": "Hello?"})
    assert (late.status_code, late.json()["error"]["code"]) == (409, "conflict")
    sofia = p.deps.cases.get_by_code("R8W-3ND")
    sofia.yellow_lines[0].resolved = YellowResolution.confirm
    p.deps.cases.save(sofia)
    p.clock.set(dt(2026, 10, 2, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles")))
    assert (await p.ctx.janitor.tick())["daily_reset"] == 1
    assert p.deps.cases.get(case_id) is None and p.deps.sessions.get(call_id) is None
    rows = {i["code"]: i for i in p.client.get("/api/cases").json()["items"]}
    assert set(rows) == {"R8W-3ND", "P2X-6TC", "H5V-9KB", "Z4M-7QE", "D7L-8RW"}
    assert rows["R8W-3ND"]["yellow_open"] == 1 and rows["P2X-6TC"]["found_display"] == 3980


def test_no_utterance_reply_token_or_answer_in_any_log(platform, caplog) -> None:
    """Every logger of the running platform (all modules, any level) stays content-free during a full call, the
    card taps and a code lookup (docs/SPEC.md §8.9)."""
    import logging

    p = platform(card_delivery="code", live_transcript=True)
    with caplog.at_level(logging.DEBUG):
        replies = maria_call(p, "0a00000000000000000000000000000a")
        p.login()
        detail = p.client.get("/api/cases").json()["items"][0]
        token = p.client.get(f"/api/cases/{detail['id']}").json()["card_url"].removeprefix("/c/")
        p.client.post(f"/api/card/{token}/answers", json={"answers": {"tax_dependent": "not_sure"}})
        p.client.post("/api/card/lookup", json={"code": "481206"})
    client_side = ("httpx", "httpx2", "httpcore", "asyncio")  # the test's own HTTP client logs its URLs
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.split(".")[0] not in client_side)
    assert '"route": "/api/card/{token}/answers"' in text  # the server did log those requests, by template
    sc = json.loads((EXAMPLES / "maria_phone.json").read_text(encoding="utf-8"))["scenarios"][0]
    said = [ex["request"]["body"].get("text") for ex in sc["exchanges"] if ex["request"]["body"].get("text")]
    spoken = [part for r in replies for part in (r.get("say"), r.get("ask")) if part]
    assert len(spoken) > 10
    for secret in [*said, *spoken, token, "481206", "not_sure", "0a00000000000000000000000000000a",
                   "library", "eleven hundred"]:
        if secret and len(secret) > 3:
            assert secret not in text, secret

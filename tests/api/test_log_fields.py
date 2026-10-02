"""The language model's part of the request log, and the pre-connect at /start.

- A turn's log line carries `llm_ms` and `llm_status` from that request's own understanding outcome (null when the
  turn had none), and still no utterance, reply text, token or id; other routes keep their four fields.
- Two concurrent turns never swap their values: each request has its own note, also when the understanding runs in a
  task of its own (as the dialogue runs it) and the requests interleave.
- /start schedules the understanding's pre-connect without waiting for it; a slow or failing pre-connect never delays
  or fails /start; a rejected /start schedules none; the fake provider sends nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx2
import pytest
from fastapi.testclient import TestClient

from gatorplate.api import routes_brain
from gatorplate.api.app import create_app
from gatorplate.api.timing import TURN_ROUTE, RequestLogMiddleware
from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome
from gatorplate.deps import Deps
from gatorplate.extract import Understander
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.ids import FixedIds
from gatorplate.store import CaseStore, Counters, Database, EventBus, LiveStore, SessionStore
from tests.api.fakes import make_settings

EMPTY = ExtractionResult(observations=[], intents=[], answered_pending="no", lang="en", side_question=None,
                         requested_language=None)
WEB_START = {"v": 1, "seq": 0, "channel": "web", "lang": "en", "test": False}


def request_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "gatorplate.requests"]


def all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("gatorplate"))


# ---------------------------------------------------------------------------------------------- concurrency


class ByUtterance:
    """A model client whose outcome depends on the utterance: "alpha" answers ok in 1234 ms, "beta" is invalid in
    77 ms (fixed values, so a swap is visible)."""

    provider, model = "scripted", "scripted"

    async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
        if "alpha" in json.loads(user_json)["utterance"]:
            return ExtractOutcome(status="ok", result=EMPTY, latency_ms=1234, model=self.model)
        return ExtractOutcome(status="invalid", latency_ms=77, model=self.model)


async def test_two_interleaved_turns_never_swap_their_values(settings_test, caplog) -> None:
    """Request A gets its outcome first, then B gets its outcome, then A logs: a shared (global) note would give A's
    line B's values. The understanding runs in a task of its own, as the dialogue runs it."""
    understander = Understander(settings=settings_test, llm=ByUtterance())
    a_noted, b_noted = asyncio.Event(), asyncio.Event()

    async def understand(text: str) -> None:
        await asyncio.wait_for(understander.understand(
            text=text, masked=False, confidence=0.9, dtmf=None, pending=None, known={}, recent=[], last_prompt=None,
            lang=Lang.en, deadline=understander.clock.monotonic() + 2.6, closed_mode=False), timeout=2.6)

    async def app(scope: dict, receive: Any, send: Any) -> None:
        scope["route"] = SimpleNamespace(path=TURN_ROUTE)
        if scope["path"].endswith("a/turn"):
            await understand("alpha says something long enough for the model")
            a_noted.set()
            await b_noted.wait()
        else:
            await a_noted.wait()
            await understand("beta says something long enough for the model")
            b_noted.set()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def send(message: dict) -> None:
        return None

    middleware = RequestLogMiddleware(app)
    scope = {"type": "http", "method": "POST", "headers": [], "query_string": b""}
    with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
        await asyncio.gather(middleware({**scope, "path": "/v1/calls/a/turn"}, None, send),
                             middleware({**scope, "path": "/v1/calls/b/turn"}, None, send))
    lines = request_lines(caplog)
    assert len(lines) == 2
    assert {(x["llm_ms"], x["llm_status"]) for x in lines} == {(1234, "ok"), (77, "invalid")}
    assert [x["llm_status"] for x in lines] == ["invalid", "ok"]  # B finished first, then A


async def test_a_turn_given_up_by_its_caller_still_notes_the_models_part(settings_test) -> None:
    """The dialogue cancels the understanding at its hard turn budget: the note says timeout, with the time spent."""
    from gatorplate.extract.llm.base import llm_note

    class Hanging:
        provider, model = "scripted", "scripted"

        async def complete(self, *args: Any) -> ExtractOutcome:
            await asyncio.sleep(10)
            raise AssertionError("never reached")  # pragma: no cover

    understander = Understander(settings=settings_test, llm=Hanging())
    with llm_note() as note:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(understander.understand(
                text="a long enough answer for the model to read", masked=False, confidence=0.9, dtmf=None,
                pending=None, known={}, recent=[], last_prompt=None, lang=Lang.en,
                deadline=understander.clock.monotonic() + 2.6, closed_mode=False), timeout=0.1)
    assert note.status == "timeout" and note.ms is not None and 90 <= note.ms < 1000


async def test_a_turn_without_understanding_logs_nulls_and_other_routes_no_llm_fields(caplog) -> None:
    async def app(scope: dict, receive: Any, send: Any) -> None:
        scope["route"] = SimpleNamespace(path=TURN_ROUTE if scope["path"].endswith("/turn") else "/api/web/sessions")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def send(message: dict) -> None:
        return None

    scope = {"type": "http", "method": "POST", "headers": [], "query_string": b""}
    with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
        await RequestLogMiddleware(app)({**scope, "path": "/v1/calls/c/turn"}, None, send)
        await RequestLogMiddleware(app)({**scope, "path": "/api/web/sessions"}, None, send)
    turn, other = request_lines(caplog)
    assert (turn["llm_ms"], turn["llm_status"]) == (None, None)
    assert set(other) == {"method", "route", "status", "server_ms"}


# ---------------------------------------------------------------------------------------------- the real platform


def real_app(settings: Any, clock: Any, llm: Any, kind: type[Understander] = Understander) -> tuple[Any, Deps]:
    """Every real module (the dialogue runs the understanding in a task of its own), with the given model client."""
    from gatorplate.card import CardBuilder
    from gatorplate.dialogue import Brain
    from gatorplate.programs import Programs
    from gatorplate.rules import Rules

    db = Database(settings.db_file)
    cases, sessions = CaseStore(db, clock=clock), SessionStore(db)
    live, events = LiveStore(), EventBus(clock=clock, tz=settings.tz)
    ids = FixedIds(short_codes=["481206"])
    rules = Rules(settings.rules_table_path, tz=settings.tz)
    understanding = kind(settings=settings, llm=llm, counters=Counters(db, clock=clock), clock=clock)
    programs = Programs.from_settings(settings)
    cards = CardBuilder(settings.content_dir, programs, guards_path=settings.guards_path, tz=settings.tz)
    brain = Brain(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, cases=cases,
                  sessions=sessions, live=live, events=events, cards=cards)
    deps = Deps(settings=settings, clock=clock, ids=ids, rules=rules, understanding=understanding, brain=brain,
                cases=cases, sessions=sessions, live=live, events=events, cards=cards, programs=programs)
    return create_app(deps), deps


def test_turn_lines_carry_the_turns_own_model_outcome_and_no_content(clean_gp_env, tmp_db, fixed_clock,
                                                                      caplog) -> None:
    settings = make_settings(tmp_db)
    llm = FakeLLM(delay_s=0.03, fail=["", "invalid"])  # the first model turn answers, the second is invalid
    app, _ = real_app(settings, fixed_clock, llm)
    client = TestClient(app, base_url="https://testserver")
    utterances = ["Yes.", "I'm a junior at SF State and I take twelve units this term.",
                  "I am twenty years old and I live with two roommates in the city."]
    replies: list[dict] = []
    with caplog.at_level(logging.INFO):
        session = client.post("/api/web/sessions", json={}).json()
        call, token = session["call_id"], session["token"]
        auth = {"Authorization": f"Bearer {token}"}
        start = client.post(f"/v1/calls/{call}/start", json=WEB_START, headers=auth)
        assert start.status_code == 200, start.text
        replies.append(start.json())
        for seq, text in enumerate(utterances, start=1):
            r = client.post(f"/v1/calls/{call}/turn", headers=auth,
                            json={"v": 1, "seq": seq, "lang": "en", "event": "utterance", "text": text})
            assert r.status_code == 200, r.text
            replies.append(r.json())
        r = client.post(f"/v1/calls/{call}/turn", headers=auth,
                        json={"v": 1, "seq": 4, "lang": "en", "event": "silence", "silence_n": 1, "silence_ms": 5000})
        assert r.status_code == 200, r.text
        replies.append(r.json())
    client.close()
    lines = request_lines(caplog)
    starts = [x for x in lines if x["route"] == "/v1/calls/{call_id}/start"]
    turns = [x for x in lines if x["route"] == TURN_ROUTE]
    assert [set(x) for x in starts] == [{"method", "route", "status", "server_ms"}]
    assert len(turns) == 4 and all(set(x) == {"method", "route", "status", "server_ms", "llm_ms", "llm_status"}
                                   for x in turns)
    consent, first, second, silence = turns
    assert (consent["llm_ms"], consent["llm_status"]) == (None, "skipped")  # a short yes: no model call
    assert first["llm_status"] == "ok" and isinstance(first["llm_ms"], int) and first["llm_ms"] >= 30
    assert second["llm_status"] == "invalid" and isinstance(second["llm_ms"], int)
    assert (silence["llm_ms"], silence["llm_status"]) == (None, None)  # no understanding step at all
    assert llm.calls == 2
    text = all_log_text(caplog)
    secrets = [call, token, *utterances[1:], "SF State and I take", "two roommates"]
    for reply in replies:
        secrets += [reply.get("say") or "", reply.get("ask") or ""]
    for item in (s for s in secrets if s and len(s) > 3):
        assert item not in text


async def test_two_concurrent_calls_over_the_real_platform_keep_their_own_values(clean_gp_env, tmp_db, fixed_clock,
                                                                                 caplog) -> None:
    """Two web calls whose model turns overlap through the whole HTTP stack: call A's model outcome is noted first,
    then call B's, then A's request ends and logs. A shared note would give A's line B's values."""
    a_noted, b_noted = asyncio.Event(), asyncio.Event()

    class Interleaved:
        provider, model = "scripted", "scripted"

        async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
            if "alpha" in json.loads(user_json)["utterance"]:
                return ExtractOutcome(status="ok", result=EMPTY, latency_ms=1234, model=self.model)
            await a_noted.wait()
            return ExtractOutcome(status="invalid", latency_ms=77, model=self.model)

    class Held(Understander):
        """A's understanding returns only after B's model outcome is noted (A's note is already written)."""

        async def understand(self, **kwargs: Any) -> Any:
            out = await super().understand(**kwargs)
            if "alpha" in kwargs["text"]:
                a_noted.set()
                await asyncio.wait_for(b_noted.wait(), timeout=2)
            elif "beta" in kwargs["text"]:
                b_noted.set()
            return out

    app, _ = real_app(make_settings(tmp_db), fixed_clock, Interleaved(), kind=Held)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://testserver") as web:
        calls = []
        for _ in range(2):
            session = (await web.post("/api/web/sessions", json={})).json()
            auth = {"Authorization": f"Bearer {session['token']}"}
            url = f"/v1/calls/{session['call_id']}"
            assert (await web.post(f"{url}/start", json=WEB_START, headers=auth)).status_code == 200
            yes = {"v": 1, "seq": 1, "lang": "en", "event": "utterance", "text": "Yes."}
            assert (await web.post(f"{url}/turn", json=yes, headers=auth)).status_code == 200
            calls.append((url, auth))

        async def turn(index: int, text: str) -> int:
            url, auth = calls[index]
            body = {"v": 1, "seq": 2, "lang": "en", "event": "utterance", "text": text}
            return (await web.post(f"{url}/turn", json=body, headers=auth)).status_code

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="gatorplate.requests"):
            codes = await asyncio.gather(turn(0, "alpha is what I want to say about my classes this term"),
                                         turn(1, "beta is what I want to say about my classes this term"))
    assert codes == [200, 200]
    turns = [x for x in request_lines(caplog) if x["route"] == TURN_ROUTE]
    assert [(x["llm_status"], x["llm_ms"]) for x in turns] == [("invalid", 77), ("ok", 1234)]  # B ends first


# ---------------------------------------------------------------------------------------------- /start


class Spy:
    """An understanding whose pre-connect is slow (or fails): records when it ran."""

    def __init__(self, *, sleep_s: float = 0.0, fail: bool = False) -> None:
        self.sleep_s, self.fail = sleep_s, fail
        self.started = 0
        self.finished = 0

    def llm_health(self) -> dict | None:
        return None

    async def understand(self, **kwargs: Any) -> Any:  # pragma: no cover - the fake brain never calls it
        raise NotImplementedError

    async def prewarm_llm(self) -> bool:
        self.started += 1
        await asyncio.sleep(self.sleep_s)
        if self.fail:
            raise RuntimeError("pre-connect failed")
        self.finished += 1
        return True


async def web_start(app: Any) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://testserver") as client:
        session = (await client.post("/api/web/sessions", json={})).json()
        return await client.post(f"/v1/calls/{session['call_id']}/start", json=WEB_START,
                                 headers={"Authorization": f"Bearer {session['token']}"})


def server_ms(response: httpx2.Response) -> float:
    return float(response.headers["server-timing"].removeprefix("brain;dur="))


async def test_start_schedules_the_preconnect_and_never_waits_for_it(make_client) -> None:
    spy = Spy(sleep_s=2.0)
    h = make_client(understanding=spy)
    loop = asyncio.get_running_loop()
    before = set(routes_brain._PRECONNECTS)  # anything another test left behind is not ours
    await web_start(h.app)  # warm-up call (first request of the app)
    began = loop.time()
    r = await web_start(h.app)
    assert r.status_code == 200
    assert loop.time() - began < 0.5 and server_ms(r) < 50  # /start answers while the pre-connect still sleeps
    await asyncio.sleep(0)
    assert spy.started == 2 and spy.finished == 0
    pending = list(routes_brain._PRECONNECTS - before)
    assert len(pending) == 2
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)
    assert routes_brain._PRECONNECTS - before == set()


async def test_start_preconnects_the_real_client_in_the_background_without_the_key(make_client, settings_test,
                                                                                    caplog) -> None:
    """The whole chain with the real understanding and the real model client: /start answers while the host has not
    answered the HEAD yet; the HEAD carries no key and no body; nothing reaches the model's endpoint; the /start line
    keeps its four fields and the pre-connect line is content-free."""
    from gatorplate.extract.llm.anthropic_client import AnthropicClient

    seen: list[httpx2.Request] = []
    host_answers = asyncio.Event()

    async def slow_host(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        await host_answers.wait()
        return httpx2.Response(404)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(slow_host))
    client = AnthropicClient(api_key="probe-key", base_url="https://llm.example.invalid", model="claude-haiku-4-5",
                             http_client=http)
    h = make_client(understanding=Understander(settings=settings_test, llm=client))
    before = set(routes_brain._PRECONNECTS)
    with caplog.at_level(logging.INFO):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=h.app), base_url="https://testserver") as web:
            assert (await web.get("/v1/health")).status_code == 200  # warm-up request
            session = (await web.post("/api/web/sessions", json={})).json()
            r = await web.post(f"/v1/calls/{session['call_id']}/start", json=WEB_START,
                               headers={"Authorization": f"Bearer {session['token']}"})
        assert r.status_code == 200 and server_ms(r) < 50
        for _ in range(5):
            await asyncio.sleep(0)
        [task] = routes_brain._PRECONNECTS - before
        assert not task.done()  # /start answered while the pre-connect still waits for the host
        host_answers.set()
        assert await task is True
    await http.aclose()
    assert [(x.method, x.url.host, x.url.path) for x in seen] == [("HEAD", "llm.example.invalid", "/")]
    assert not {name.lower() for name in seen[0].headers} & {"x-api-key", "authorization", "anthropic-version"}
    assert "probe-key" not in json.dumps(dict(seen[0].headers)) and seen[0].content == b""
    assert client.metrics.snapshot()["usage"]["calls"] == 0  # no model call at /start
    starts = [x for x in request_lines(caplog) if x["route"] == "/v1/calls/{call_id}/start"]
    assert [set(x) for x in starts] == [{"method", "route", "status", "server_ms"}]
    [pre] = [json.loads(x.getMessage()) for x in caplog.records
             if x.name == "gatorplate.llm" and "llm_preconnect" in x.getMessage()]
    assert set(pre) == {"event", "connections", "ok", "ms"} and (pre["connections"], pre["ok"]) == (1, 1)
    assert session["token"] not in all_log_text(caplog) and session["call_id"] not in all_log_text(caplog)


async def test_a_failing_preconnect_never_affects_start(make_client) -> None:
    loop = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        spy = Spy(fail=True)
        h = make_client(understanding=spy)
        before = set(routes_brain._PRECONNECTS)
        r = await web_start(h.app)
        assert r.status_code == 200 and r.json()["ask"]
        for _ in range(3):
            await asyncio.sleep(0)
        assert spy.started == 1 and routes_brain._PRECONNECTS - before == set()
    finally:
        loop.set_exception_handler(previous)
    assert reported == []


async def test_a_rejected_start_schedules_no_preconnect(make_client) -> None:
    spy = Spy()
    h = make_client(understanding=spy)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=h.app), base_url="https://testserver") as client:
        session = (await client.post("/api/web/sessions", json={})).json()
        r = await client.post(f"/v1/calls/{session['call_id']}/start", json=WEB_START,
                              headers={"Authorization": "Bearer wrong-token"})
    await asyncio.sleep(0)
    assert r.status_code == 401 and spy.started == 0


async def test_an_understanding_without_a_preconnect_is_left_alone(make_client) -> None:
    h = make_client()  # the platform's fake understanding has no pre-connect at all
    before = set(routes_brain._PRECONNECTS)
    assert (await web_start(h.app)).status_code == 200
    assert routes_brain._PRECONNECTS - before == set()


async def test_the_fake_provider_preconnects_nothing(make_client, settings_test) -> None:
    class Watched(Understander):
        results: ClassVar[list[bool]] = []

        async def prewarm_llm(self) -> bool:
            result = await super().prewarm_llm()
            self.results.append(result)
            return result

    understanding = Watched(settings=settings_test)
    assert understanding.llm is not None and not hasattr(understanding.llm, "prewarm")  # the fake: no network
    h = make_client(understanding=understanding)
    assert (await web_start(h.app)).status_code == 200
    for _ in range(3):
        await asyncio.sleep(0)
    assert Watched.results == [False]

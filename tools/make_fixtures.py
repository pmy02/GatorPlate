#!/usr/bin/env python3
"""Regenerates web/fixtures/ from real engine runs (`make fixtures`).

Everything the pages read in fixture mode (`?fixtures=1`) comes from the real wiring — rules, understanding with the
fake language model, the dialogue brain, the stores, the card builder and the programs engine — driven over HTTP the
way the gateway, the talk page, the card page and the console drive it, on a fixed clock (Fri 2026-10-02, 9:57 AM
Pacific) and pinned ids, so the files are the same on every run:

- the console: the seeded samples, Maria's phone call (golden dialogue `maria_g1`, card delivery `screen`, live
  transcript on) with every event it published and the case detail after each turn, her live view, Sofia's confirm
  and review, Maria's review, the list, the meta, and the real error bodies;
- the card: Maria's CardView in English and Spanish, its status polls, W4's three answers and the "I applied" mark in
  both languages, and a short-code lookup (from the same call under card delivery `code`);
- the talk page: Maria's dialogue as web replies (English) and the Spanish web example's replies.

Each database lives under var/fixtures/ and is recreated on every run. Nothing here reads the environment.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import deque
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gatorplate.api.app import create_app  # noqa: E402
from gatorplate.clock import FixedClock  # noqa: E402
from gatorplate.config import DEV_CONSOLE_PASSCODE, DEV_GATEWAY_SECRET, Settings  # noqa: E402
from gatorplate.ids import FixedIds  # noqa: E402
from gatorplate.wiring import compose  # noqa: E402
from tools import e2e_run as runner  # noqa: E402

OUT = ROOT / "web" / "fixtures"
WORK = ROOT / "var" / "fixtures"
SITE = "https://gatorplate.fly.dev"

MARIA_ID, MARIA_CODE, MARIA_CARD = "c_maria2demo", "K7Q-2FM", "fixtureMariaCard000001"
MARIA_CALL = "0a000000000000000000000000000001"
LIVE_CALL = "0a000000000000000000000000000002"
SAMPLE_IDS = {"R8W-3ND": "c_sofia2demo", "P2X-6TC": "c_jamal2demo", "H5V-9KB": "c_gradta2dem",
              "Z4M-7QE": "c_dorm22demo", "D7L-8RW": "c_bound2demo"}
WEB = {"en": ("0a00000000000000000000000000f001", "fixture-web-token-maria-000001"),
       "es": ("0b000000000000000000000000000001", "fixture-web-token-sofia-000001")}
W4_TAPS = [{"break_transit": "weekdays_muni"}, {"tax_dependent": "no"}, {"pge_bill": "own_roommate"}]
TURN_SECONDS = 14  # about 2:00 for the golden dialogue's nine student turns

# Pacing of the console's event replay (each entry waits delay_ms before it plays): a student line comes after the
# previous reply was spoken, the assistant's line shortly after the student's; the call's end closes the replay.
DELAY_MS = {"case.created": 600, "student": 2200, "assistant": 400, "case.updated": 500, "live.ended": 1500,
            "after_end": 1200}


class FixtureIds(FixedIds):
    """Pinned ids; case ids can be queued right before the step that creates the cases."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.case_queue: deque[str] = deque()

    def case_id(self) -> str:
        if self.case_queue:
            return self.case_queue.popleft()
        return super().case_id()


class Run:
    """One app on its own database, fixed clock and pinned ids, with a TestClient and an event recorder."""

    def __init__(self, name: str, *, card_delivery: str, ids: FixtureIds) -> None:
        db = WORK / f"{name}.db"
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db}{suffix}").unlink(missing_ok=True)
        self.settings = Settings(env="dev", llm_provider="fake", llm_api_key=SecretStr(""), debug_keys=True,
                                 demo_mode=True, daily_reset=False, live_transcript=True,
                                 card_delivery=card_delivery, db_path=db, public_base_url=SITE, programs=True)
        self.clock = FixedClock.pacific(2026, 10, 2, 9, 56)
        self.ids = ids
        self.deps = compose(self.settings, clock=self.clock, ids=ids)
        self.app = create_app(self.deps)
        self.client = TestClient(self.app, base_url="http://testserver")
        self.events: list[Any] = []
        bus = self.deps.events
        publish = bus.publish

        def recording(type: str, **kwargs: Any) -> Any:  # noqa: A002 - the port's parameter name
            event = publish(type, **kwargs)
            self.events.append(event)
            return event

        bus.publish = recording  # the brain and the API hold this same bus instance

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------------------------------ requests
    def ok(self, response: Any) -> Any:
        if response.status_code != 200:
            raise SystemExit(f"make_fixtures: {response.request.method} {response.request.url.path} answered "
                             f"{response.status_code}")
        return response.json()

    def login(self) -> dict:
        return self.ok(self.client.post("/api/console/login", json={"passcode": DEV_CONSOLE_PASSCODE}))

    def phone(self, call_id: str, step: str, body: dict) -> Any:
        path = f"/v1/calls/{call_id}/{step}"
        raw = json.dumps(body).encode("utf-8")
        headers = {**runner.sign(DEV_GATEWAY_SECRET, "POST", path, raw, ts=int(self.clock.now().timestamp())),
                   "Content-Type": "application/json"}
        return self.client.post(path, content=raw, headers=headers)

    def web(self, call_id: str, token: str, step: str, body: dict) -> Any:
        return self.client.post(f"/v1/calls/{call_id}/{step}", json=body,
                                headers={"Authorization": f"Bearer {token}"})

    def detail(self, case_id: str) -> dict:
        return self.ok(self.client.get(f"/api/cases/{case_id}"))

    def seed(self) -> dict:
        order = [demo["code"] for demo in self.app.state.ctx.demo.seed_files()]
        self.ids.case_queue.extend(SAMPLE_IDS[code] for code in order)
        return self.ok(self.client.post("/api/demo/seed"))

    def error(self, response: Any) -> dict:
        body = response.json()
        if response.status_code < 400 or "error" not in body:
            raise SystemExit(f"make_fixtures: expected an error from {response.request.url.path}")
        return {"__status": response.status_code, **body}


def strip_debug(reply: dict) -> dict:
    """Fixture replies look like production replies: no debug keys."""
    return {**reply, "debug": None}


def utterance(seq: int, turn: runner.Turn, lang: str) -> dict:
    body: dict[str, Any] = {"v": 1, "seq": seq, "lang": lang}
    if turn.user is not None:
        body.update(event="utterance", text=turn.user, masked=turn.masked, confidence=turn.confidence,
                    interrupted=turn.interrupted, typed=turn.typed)
    elif turn.dtmf is not None:
        body.update(event="dtmf", dtmf=turn.dtmf)
    else:
        raise SystemExit("make_fixtures: the golden dialogue holds only utterance and keypad turns")
    return body


def maria_script() -> runner.Script:
    return runner.load_script(ROOT / "tests" / "e2e" / "scripts" / "maria_g1.json")


def event_entry(event: Any, detail: dict | None, *, after_end: bool = False) -> dict:
    data = event.model_dump(mode="json")
    if event.type == "live.turn":
        delay = DELAY_MS["student" if event.line is not None and event.line.who == "student" else "assistant"]
    elif after_end and event.type == "case.updated":
        delay = DELAY_MS["after_end"]
    else:
        delay = DELAY_MS.get(event.type, 500)
    entry: dict[str, Any] = {"delay_ms": delay, "event": data}
    if event.type in ("case.created", "case.updated") and detail is not None:
        entry["detail"] = detail
    return entry


# ---------------------------------------------------------------------------------------------- the console run

def console_and_card(files: dict[str, Any]) -> None:
    ids = FixtureIds(case_ids=[], case_codes=[], card_tokens=[], short_codes=[])
    run = Run("screen", card_delivery="screen", ids=ids)
    try:
        files["ok.json"] = run.login()
        run.seed()
        files["demo_seed.json"] = run.seed()  # "Reset demo" re-seeds: the samples are replaced
        run.clock.advance(minutes=1)

        # Maria's phone call (golden dialogue maria_g1), every event recorded with the detail after its turn.
        script = maria_script()
        ids.case_queue.append(MARIA_ID)
        ids._given["case_code"] = iter([MARIA_CODE])
        ids._given["card_token"] = iter([MARIA_CARD])
        replay: list[dict] = []
        mark = len(run.events)
        seq = 0
        for turn in script.turns:
            if turn.start:
                reply = run.ok(run.phone(MARIA_CALL, "start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en",
                                                               "test": False}))
            else:
                run.clock.advance(seconds=TURN_SECONDS)
                seq += 1
                reply = run.ok(run.phone(MARIA_CALL, "turn", utterance(seq, turn, "en")))
            want = turn.expect_keys
            got = (reply.get("debug") or {}).get("keys")
            if want is not None and got != want:
                raise SystemExit(f"make_fixtures: maria_g1 turn {seq}: keys {got} != {want}")
            if got and "flip.rent_paid_by_others" in got:  # the W1 moment: the console opens mid-call here
                files["live_maria.json"] = run.ok(run.client.get(f"/api/cases/{MARIA_ID}/live"))
            detail = run.detail(MARIA_ID)
            replay += [event_entry(e, detail) for e in run.events[mark:]]
            mark = len(run.events)
        run.clock.advance(seconds=4)
        end = script.end
        assert end is not None
        run.ok(run.phone(MARIA_CALL, "end", {"v": 1, "reason": end.reason, "turns": end.turns,
                                             "duration_ms": end.duration_ms}))
        detail = run.detail(MARIA_ID)
        replay += [event_entry(e, detail, after_end=True) for e in run.events[mark:]]
        files["maria_live_events.json"] = replay
        files["case_maria.json"] = detail
        run.clock.advance(seconds=30)

        # The console's other reads, before anyone acts on a case.
        files["cases.json"] = run.ok(run.client.get("/api/cases"))
        files["meta.json"] = run.ok(run.client.get("/api/meta"))
        files["public_info.json"] = run.ok(run.client.get("/api/public/info"))
        for name, case_id in (("case_sofia.json", "c_sofia2demo"), ("case_jamal.json", "c_jamal2demo"),
                              ("case_grad_ta.json", "c_gradta2dem"), ("case_dorm.json", "c_dorm22demo"),
                              ("case_boundary.json", "c_bound2demo")):
            files[name] = run.detail(case_id)

        # The card (W2) and its status polls.
        for lang in ("en", "es"):
            files[f"card_maria_{lang}.json"] = run.ok(run.client.get(f"/api/card/{MARIA_CARD}",
                                                                      params={"lang": lang}))
        status = [run.ok(run.client.get(f"/api/card/{MARIA_CARD}/status")) for _ in range(3)]

        # W4: the three taps and the "I applied" mark, in English and in Spanish (the answers are cleared between).
        for lang, suffix in (("en", ""), ("es", "_es")):
            run.clock.advance(seconds=20)
            steps = []
            for tap in W4_TAPS:
                run.clock.advance(seconds=5)
                steps.append(run.ok(run.client.post(f"/api/card/{MARIA_CARD}/answers", params={"lang": lang},
                                                    json={"answers": tap})))
            files[f"unlocked_maria_steps{suffix}.json"] = steps
            run.clock.advance(seconds=5)
            files[f"unlocked_maria_progress{suffix}.json"] = run.ok(run.client.post(
                f"/api/card/{MARIA_CARD}/progress", params={"lang": lang},
                json={"program": "calfresh", "applied": True}))
            case = run.deps.cases.get(MARIA_ID)
            assert case is not None
            case.program_answers = {}
            case.program_progress = {}
            run.deps.cases.save(case)

        # Real error bodies the pages show.
        files["error_not_found.json"] = run.error(run.client.get("/api/cases/c_nosuchcase"))
        sofia = run.detail("c_sofia2demo")
        files["error_locked.json"] = run.error(run.client.post(
            "/api/cases/c_sofia2demo/status",
            json={"status": "reviewed", "expected_version": sofia["case"]["version"]}))
        run.ok(run.phone(LIVE_CALL, "start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en", "test": True}))
        live_id = next(item["id"] for item in run.ok(run.client.get("/api/cases"))["items"] if item["live"])
        live = run.detail(live_id)
        files["error_conflict_live.json"] = run.error(run.client.post(
            f"/api/cases/{live_id}/status", json={"status": "follow_up", "expected_version": live["case"]["version"]}))
        run.ok(run.phone(LIVE_CALL, "end", {"v": 1, "reason": "caller_hangup", "turns": 0, "duration_ms": 3000}))
        files["empty.json"] = run.ok(run.client.delete(f"/api/cases/{live_id}"))

        # W3: Sofia's yellow line confirmed, then reviewed; then Maria reviewed and her card shows it.
        run.clock.advance(minutes=2)
        line = next(y for y in sofia["case"]["yellow_lines"] if not y.get("resolved"))
        confirmed = run.ok(run.client.post(f"/api/cases/c_sofia2demo/yellow/{line['id']}",
                                           json={"action": "confirm", "expected_version": sofia["case"]["version"]}))
        files["case_sofia_confirmed.json"] = confirmed
        files["case_sofia_reviewed.json"] = run.ok(run.client.post(
            "/api/cases/c_sofia2demo/status",
            json={"status": "reviewed", "expected_version": confirmed["case"]["version"]}))
        maria = run.detail(MARIA_ID)
        files["case_maria_reviewed.json"] = run.ok(run.client.post(
            f"/api/cases/{MARIA_ID}/status", json={"status": "reviewed", "expected_version": maria["case"]["version"]}))
        status.append(run.ok(run.client.get(f"/api/card/{MARIA_CARD}/status")))
        files["card_status_maria.json"] = status

        # Reset demo (reset, then seed): the reset removes Maria's call.
        files["demo_reset.json"] = run.ok(run.client.post("/api/demo/reset"))
    finally:
        run.close()


# ---------------------------------------------------------------------------------------------- code delivery

def card_lookup(files: dict[str, Any]) -> None:
    """Maria's call again under card delivery `code`: the six-digit code opens her card."""
    ids = FixtureIds(case_codes=[MARIA_CODE], card_tokens=[MARIA_CARD], short_codes=["481206"])
    ids.case_queue.append(MARIA_ID)
    run = Run("code", card_delivery="code", ids=ids)
    try:
        seq = 0
        for turn in maria_script().turns:
            if turn.start:
                run.ok(run.phone(MARIA_CALL, "start", {"v": 1, "seq": 0, "channel": "phone", "lang": "en",
                                                       "test": False}))
                continue
            run.clock.advance(seconds=TURN_SECONDS)
            seq += 1
            run.ok(run.phone(MARIA_CALL, "turn", utterance(seq, turn, "en")))
        run.ok(run.phone(MARIA_CALL, "end", {"v": 1, "reason": "completed"}))
        files["card_lookup.json"] = run.ok(run.client.post("/api/card/lookup", json={"code": "481206"}))
    finally:
        run.close()


# ---------------------------------------------------------------------------------------------- the talk page

def talk(files: dict[str, Any]) -> None:
    """The talk page's replies: Maria's golden dialogue typed in English, and the Spanish web example."""
    ids = FixtureIds(call_ids=[WEB["en"][0], WEB["es"][0]], web_tokens=[WEB["en"][1], WEB["es"][1]],
                     card_tokens=[MARIA_CARD, "example-card-token-sofia-0001"])
    run = Run("web", card_delivery="screen", ids=ids)
    try:
        session = run.ok(run.client.post("/api/web/sessions", json={"lang": "en"}))
        files["web_session_en.json"] = session
        call_id, token = session["call_id"], session["token"]
        replies = [run.ok(run.web(call_id, token, "start", {"v": 1, "seq": 0, "channel": "web", "lang": "en",
                                                            "test": False}))]
        seq = 0
        for turn in maria_script().turns:
            if turn.start:
                continue
            run.clock.advance(seconds=TURN_SECONDS)
            seq += 1
            replies.append(run.ok(run.web(call_id, token, "turn", utterance(seq, turn, "en"))))
            if replies[-1]["end"]:
                break
        run.ok(run.web(call_id, token, "end", {"v": 1, "reason": "completed"}))
        files["talk_maria_en.json"] = [strip_debug(r) for r in replies]

        example = json.loads((ROOT / "contracts" / "examples" / "sofia_web_es.json").read_text(encoding="utf-8"))
        scenario = example["scenarios"][0]
        session = run.ok(run.client.post("/api/web/sessions", json={"lang": "es"}))
        files["web_session_es.json"] = session
        call_id, token = session["call_id"], session["token"]
        replies = []
        for ex in scenario["exchanges"]:
            req = ex["request"]
            step = req["path"].rsplit("/", 1)[-1]
            if req["path"] == "/api/web/sessions" or step == "end":
                continue
            run.clock.advance(seconds=TURN_SECONDS)
            replies.append(run.ok(run.web(call_id, token, step, req["body"])))
        run.ok(run.web(call_id, token, "end", {"v": 1, "reason": "completed"}))
        files["talk_sofia_es.json"] = [strip_debug(r) for r in replies]
    finally:
        run.close()


# ---------------------------------------------------------------------------------------------- index and output

INDEX_ABOUT = ("Fixture mode (?fixtures=1): web/shared/api.js answers each request from the file mapped here. Keys are "
               "'METHOD /path' with {name} matching one path segment; a literal segment wins over {name}; a key with a "
               "query part matches only that exact query. A value is a file name, or {en, es} chosen by the "
               "request's lang query, else the page's language. A file holding a JSON array is served one element "
               "per request, in order, with one counter per file (the last element repeats). A file "
               "{\"__status\": n, \"error\": {...}} answers as that error. The live replay is maria_live_events.json "
               "({delay_ms, event, detail?}). Every file is regenerated from real engine runs by "
               "tools/make_fixtures.py (make fixtures).")

ROUTES: dict[str, Any] = {
    "POST /api/console/login": "ok.json",
    "POST /api/console/logout": "ok.json",
    "GET /api/meta": "meta.json",
    "GET /api/cases": "cases.json",
    "GET /api/cases/c_maria2demo": "case_maria.json",
    "GET /api/cases/c_sofia2demo": "case_sofia.json",
    "GET /api/cases/c_jamal2demo": "case_jamal.json",
    "GET /api/cases/c_gradta2dem": "case_grad_ta.json",
    "GET /api/cases/c_dorm22demo": "case_dorm.json",
    "GET /api/cases/c_bound2demo": "case_boundary.json",
    "GET /api/cases/{id}": "error_not_found.json",
    "GET /api/cases/c_maria2demo/live": "live_maria.json",
    "GET /api/cases/{id}/live": "error_not_found.json",
    "POST /api/cases/c_sofia2demo/yellow/{yid}": "case_sofia_confirmed.json",
    "POST /api/cases/c_sofia2demo/status": "case_sofia_reviewed.json",
    "POST /api/cases/c_maria2demo/status": "case_maria_reviewed.json",
    "POST /api/cases/{id}/status": "error_locked.json",
    "PUT /api/cases/c_sofia2demo/slots/{slot}": "case_sofia_confirmed.json",
    "PATCH /api/cases/c_jamal2demo/tracking": "case_jamal.json",
    "DELETE /api/cases/{id}": "empty.json",
    "POST /api/demo/seed": "demo_seed.json",
    "POST /api/demo/reset": "demo_reset.json",
    "POST /api/demo/inject": "case_maria.json",
    "GET /api/public/info": "public_info.json",
    "GET /api/card/{token}": {"en": "card_maria_en.json", "es": "card_maria_es.json"},
    "GET /api/card/{token}?lang=en": "card_maria_en.json",
    "GET /api/card/{token}?lang=es": "card_maria_es.json",
    "GET /api/card/{token}/status": "card_status_maria.json",
    "DELETE /api/card/{token}": "empty.json",
    "POST /api/card/{token}/answers": {"en": "unlocked_maria_steps.json", "es": "unlocked_maria_steps_es.json"},
    "POST /api/card/{token}/progress": {"en": "unlocked_maria_progress.json", "es": "unlocked_maria_progress_es.json"},
    "POST /api/card/lookup": "card_lookup.json",
    "POST /api/web/sessions": {"en": "web_session_en.json", "es": "web_session_es.json"},
    "POST /v1/calls/{call_id}/start": {"en": "talk_maria_en.json", "es": "talk_sofia_es.json"},
    "POST /v1/calls/{call_id}/turn": {"en": "talk_maria_en.json", "es": "talk_sofia_es.json"},
    "POST /v1/calls/{call_id}/end": "empty.json",
}


def write(files: dict[str, Any]) -> None:
    referenced = {v for value in ROUTES.values() for v in (value.values() if isinstance(value, dict) else [value])}
    missing = sorted(referenced - set(files))
    if missing:
        raise SystemExit(f"make_fixtures: no file built for {missing}")
    staged = WORK / "out"
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    files = {**files, "index.json": {"about": INDEX_ABOUT, "routes": ROUTES}}
    for name, data in sorted(files.items()):
        (staged / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for old in OUT.glob("*.json"):
        old.unlink()
    for new in sorted(staged.glob("*.json")):
        shutil.copyfile(new, OUT / new.name)
    shutil.rmtree(staged, ignore_errors=True)
    print(f"make_fixtures: wrote {len(files)} files to web/fixtures/ (fixed clock Fri 2026-10-02 PT)")


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    console_and_card(files)
    card_lookup(files)
    talk(files)
    write(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

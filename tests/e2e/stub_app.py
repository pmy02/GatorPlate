"""A stub Brain API for the E2E runner's self-test (tests/e2e/test_static.py) — not GatorPlate's brain.

It speaks the contract (docs/BRAIN_API.md: signed phone requests, web bearer sessions, seq rules, error envelopes)
and answers each call by finding the script whose student turns match the call so far, then replying with exactly
the keys and reply fields that script expects. The console routes return a case built from the script's own
expectations. So the self-test proves the runner's plumbing — grouping, servers, auth, seq handling, assertions,
skips and reports — independently of the real brain.

Served by uvicorn as ``tests.e2e.stub_app:app``; the environment picks the card-delivery mode and debug keys
(``GP_CARD_DELIVERY``, ``GP_DEBUG_KEYS``), like the real app.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIRS = [ROOT / "tests" / "e2e" / "scripts", ROOT / "tests" / "adversarial" / "scripts"]
DEV_SECRET = "test-secret-do-not-use"  # the public HMAC test-vector secret (contracts/examples/hmac_vectors.json)
DEV_PASSCODE = "dev"
ERRORS = {"unknown_call": 404, "bad_signature": 401, "stale_timestamp": 401, "unauthorized": 401,
          "invalid_request": 422, "stale_seq": 409, "conflict": 409, "not_found": 404}


def _error(code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": "stub error", "retryable": False}},
                        status_code=ERRORS[code], headers={"Server-Timing": "brain;dur=1"})


def _load_scripts(dirs: list[Path]) -> list[dict]:
    out = []
    for folder in dirs:
        for path in sorted(folder.glob("*.json")):
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _event_of(turn: dict) -> tuple | None:
    """The request event a script turn produces (None: no matchable event)."""
    if turn.get("expect_status", 200) != 200 or turn.get("call", "this") != "this" \
            or turn.get("auth", "normal") != "normal" or turn.get("repeat_previous") or turn.get("end_call"):
        return None
    if "user" in turn:
        return ("utterance", turn["user"], turn.get("confidence"))
    if "dtmf" in turn:
        return ("dtmf", turn["dtmf"])
    if "silence" in turn:
        return ("silence", turn["silence"]["n"])
    return None


class Call:
    def __init__(self, channel: str, lang: str, case_id: str) -> None:
        self.channel, self.lang, self.case_id = channel, lang, case_id
        self.events: list[tuple] = []
        self.last_seq = 0
        self.replies: dict[int, dict] = {}
        self.ended = False
        self.script: dict | None = None


def create_stub_app(*, card_delivery: str = "code", debug_keys: bool = True, script_dirs: list[Path] | None = None,
                    secret: str = DEV_SECRET, passcode: str = DEV_PASSCODE, report_mode: bool = True) -> FastAPI:
    scripts = _load_scripts(script_dirs or SCRIPT_DIRS)
    app = FastAPI()
    lock = threading.Lock()
    calls: dict[str, Call] = {}
    tokens: dict[str, str] = {}
    cases: dict[str, dict] = {}

    def candidates(call: Call) -> list[dict]:
        out = []
        for s in scripts:
            if s["channel"] != call.channel or s["lang"] != call.lang:
                continue
            if s["channel"] == "phone" and s["env"]["GP_CARD_DELIVERY"] != card_delivery \
                    and any(k.startswith("card.phone") for t in s["turns"] for k in t.get("expect_keys") or []):
                continue
            out.append(s)
        return out

    def walk(script: dict, events: list[tuple]) -> tuple[int | None, bool]:
        """(the turn answering the last event, whether every later event turn is conditional): events must match
        the script's event turns in order, where a conditional turn (when_pending) may be absent."""
        j, found, rest_optional = 0, None, True
        for i, turn in enumerate(script["turns"][1:], start=1):
            ev = _event_of(turn)
            if ev is None:
                continue
            if found is not None:
                rest_optional = rest_optional and bool(turn.get("when_pending"))
                continue
            if j < len(events) and ev == events[j]:
                j += 1
                if j == len(events):
                    found = i
            elif not turn.get("when_pending"):
                return None, False
        return found, rest_optional

    def matching_turns(call: Call) -> list[tuple[dict, int]]:
        """Every script that matches the call so far, with the turn answering the last event; a turn with exact keys
        comes first (an include list is then satisfied too), then script order."""
        found = []
        for s in candidates(call):
            index, _ = walk(s, call.events)
            if index is not None:
                found.append((s, index))
        found.sort(key=lambda f: f[0]["turns"][f[1]].get("expect_keys") is None)
        return found

    def final_script(call: Call) -> dict | None:
        complete = [s for s in candidates(call) if walk(s, call.events)[0] is not None and walk(s, call.events)[1]]
        return complete[0] if complete else call.script

    def build_reply(call: Call, turn: dict) -> dict:
        spec = turn.get("reply") or {}
        keys = turn.get("expect_keys") or turn.get("expect_keys_include") or []
        end = spec.get("end", bool(turn.get("expect_end")))
        has_ask = spec.get("ask", "null" if end else "present") == "present"
        hold = spec.get("hold_s", 0)
        say = "Okay."
        if any(k in ("result.likely", "result.likely_floor") for k in keys):
            say = "Okay. The county decides." if call.lang == "en" else "Bien. El condado decide."
        elif turn.get("budget") == "result" and call.channel == "phone":
            # a result turn whose keys name no result line gives contact details (docs/BRAIN_API.md §7)
            say = "Okay. Call four one five, three three eight, one two zero three."
        ask = None if (end or hold or not has_ask) else ("Next?" if call.lang == "en" else "¿Siguiente?")
        if ask and turn.get("text_includes"):
            ask = " ".join([*turn["text_includes"], ask])
        web = call.channel == "web"
        token = cases[call.case_id].setdefault("_card_token", secrets.token_urlsafe(16))
        reply = {
            "say": say, "ask": ask, "end": end, "end_reason": spec.get("end_reason") if end else None,
            "lang": spec.get("lang", call.lang), "listen": spec.get("listen", "normal"),
            "expect": spec.get("expect", "open") if ask else "open",
            "interruptible": spec.get("interruptible", not end) if not end else False,
            "hold_s": hold, "display": " ".join(filter(None, [say, ask])) if web else None,
            "choices": (["Yes", "No"] if web and ask and spec.get("choices") == "present" else None),
            "card_url": f"/c/{token}" if web and spec.get("card_url") == "present" else None,
            "debug": {"keys": list(keys), "phase": "stub"} if debug_keys else None,
        }
        if reply["end"] and reply["end_reason"] is None:
            reply["end_reason"] = "completed"
        return reply

    def apply_case(call: Call, expect: dict | None, *, final: bool = False) -> None:
        if not expect:
            return
        case = cases[call.case_id]
        for name, value in (expect.get("slots") or {}).items():
            case["slots"][name] = {"value": value, "heard_en": None, "changed_from": None}
        for name in expect.get("heard_en_present") or []:
            case["slots"].setdefault(name, {"value": None})["heard_en"] = "gloss"
        for name, value in (expect.get("changed_from") or {}).items():
            case["slots"].setdefault(name, {"value": None})["changed_from"] = value
        for name in ("tier", "reason_code", "estimate_monthly", "estimate_is_floor", "estimate_range",
                     "expedited_possible", "summary", "ended_reason", "ended_early", "lang", "language_request"):
            if name in expect:
                case[name] = expect[name]
        if expect.get("asked_last"):
            case["asked"].append(dict(expect["asked_last"]))
        for f in expect.get("asked_flip") or []:
            entry = {"key": f"flip.{f['slot']}", "kind": "flip", "slots": [f["slot"]], "reason": f["reason"]}
            if not any(a.get("kind") == "flip" and a.get("slots") == entry["slots"] and a.get("reason") == f["reason"]
                       for a in case["asked"]):
                case["asked"].append(entry)
        for key in expect.get("asked_keys_include") or []:
            case["asked"].append({"key": key, "kind": "standard", "slots": []})
        case["skipped"] = [dict(s) for s in expect.get("skipped") or case["skipped"]]
        case["skipped"] += [dict(s) for s in expect.get("skipped_include") or [] if s not in case["skipped"]]
        lines = [dict(y, resolved=None) for y in expect.get("yellow") or []]
        lines += [{"kind": "policy", "code": c, "resolved": None} for c in expect.get("yellow_codes_include") or []]
        if "yellow_open" in expect:
            while len(lines) < expect["yellow_open"]:
                lines.append({"kind": "policy", "code": "stub", "resolved": None})
            case["yellow_lines"] = lines[: expect["yellow_open"]] if expect["yellow_open"] else []
        elif lines:
            case["yellow_lines"] = lines
        case["flags"] = sorted(set(case["flags"]) | set(expect.get("flags_include") or []))
        if expect.get("card_created"):
            case["card"] = {"token": case.get("_card_token") or secrets.token_urlsafe(16)}
        if "student_turns" in expect:
            case["turn_count"] = expect["student_turns"]
        if "privacy_events" in expect:
            case["privacy_events"] = [{"kind": k if isinstance(k, str) else k["kind"]}
                                      for k in expect["privacy_events"] or []]
        if final and "live" in expect:
            case["live"] = expect["live"]
        if final and expect.get("deleted"):
            cases.pop(call.case_id, None)

    def verify_phone(request: Request, raw: bytes) -> str | None:
        ts, sig = request.headers.get("x-gp-timestamp"), request.headers.get("x-gp-signature")
        if not ts or not sig:
            return "unauthorized"
        if not ts.isdigit() or not sig.startswith("v1=") or len(sig) != 67:
            return "bad_signature"
        msg = f"{ts}.{request.method}.{request.url.path}.{hashlib.sha256(raw).hexdigest()}".encode()
        want = "v1=" + hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, sig):
            return "bad_signature"
        if abs(int(time.time()) - int(ts)) > 120:
            return "stale_timestamp"
        return None

    def auth(request: Request, raw: bytes, call_id: str) -> tuple[str | None, str | None]:
        bearer = request.headers.get("authorization", "")
        if bearer.startswith("Bearer "):
            return ("web", None) if tokens.get(bearer[7:]) == call_id else (None, "unauthorized")
        problem = verify_phone(request, raw)
        return (None, problem) if problem else ("phone", None)

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/healthz")
    def healthz() -> dict:
        body = {"ok": True, "version": "stub", "card_delivery": card_delivery, "debug_keys": debug_keys,
                "programs": {"enabled": True, "valid_today": True},
                "llm": {"provider": "fake", "status": "ok", "usage": {"calls": 0, "input_tokens": 0,
                                                                     "output_tokens": 0}}}
        if not report_mode:  # a server that does not say which card-delivery mode it runs
            del body["card_delivery"]
        return body

    @app.post("/api/web/sessions")
    async def web_session(request: Request) -> Any:
        call_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        tokens[token] = call_id
        expires = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"call_id": call_id, "token": token, "expires_at": expires}

    @app.post("/v1/calls/{call_id}/{step}")
    async def call_step(call_id: str, step: str, request: Request) -> Any:
        raw = await request.body()
        channel, problem = auth(request, raw, call_id)
        if problem:
            return _error(problem)
        try:
            body = json.loads(raw)
        except ValueError:
            return _error("invalid_request")
        with lock:
            call = calls.get(call_id)
            if step == "start":
                if body.get("channel") != channel:
                    return _error("unauthorized")
                if call is None:
                    case_id = f"c_{uuid.uuid4().hex[:10]}"
                    cases[case_id] = {"id": case_id, "slots": {}, "asked": [], "skipped": [], "yellow_lines": [],
                                      "flags": [], "privacy_events": [], "card": None, "live": True,
                                      "lang": body["lang"], "channel": channel, "turn_count": 0}
                    call = calls[call_id] = Call(channel, body["lang"], case_id)
                    start_turns = [s["turns"][0] for s in candidates(call)]
                    turn = start_turns[0] if start_turns else {"expect_keys": ["consent.ask"]}
                    call.replies[0] = build_reply(call, turn)
                return JSONResponse(call.replies[0], headers={"Server-Timing": "brain;dur=1"})
            if call is None:
                return _error("unknown_call")
            if step == "end":
                script = final_script(call)
                if not call.ended and script:
                    apply_case(call, script.get("final"), final=True)
                call.ended = True
                cases.get(call.case_id, {})["live"] = False
                return JSONResponse({}, headers={"Server-Timing": "brain;dur=1"})
            if call.ended:
                return _error("conflict")
            seq = body.get("seq", 0)
            if seq == call.last_seq and seq in call.replies:
                return JSONResponse(call.replies[seq], headers={"Server-Timing": "brain;dur=1"})
            if seq < call.last_seq:
                return _error("stale_seq")
            ev = {"utterance": ("utterance", body.get("text"), body.get("confidence")),
                  "dtmf": ("dtmf", body.get("dtmf")),
                  "silence": ("silence", body.get("silence_n"))}[body["event"]]
            call.events.append(ev)
            found = matching_turns(call)
            if not found:
                turn = {"expect_keys": ["reprompt.unclear"], "reply": {"expect": "open"}}
            else:
                call.script, index = found[0]
                turn = dict(call.script["turns"][index])
                following = next((t for t in call.script["turns"][index + 1:] if _event_of(t) is not None), None)
                if following is not None and following.get("when_pending") and turn.get("expect_keys") is None:
                    # ask the question the next conditional turn answers, so the runner plays it too
                    turn["expect_keys_include"] = [*(turn.get("expect_keys_include") or []),
                                                   following["when_pending"]]
                elif walk(call.script, call.events)[1] and turn.get("expect_keys") is None:
                    # the last event the script sends: the keys its final block says some reply used
                    turn["expect_keys_include"] = [*(turn.get("expect_keys_include") or []),
                                                   *((call.script.get("final") or {}).get("reply_keys_include") or [])]
                turn["text_includes"] = sorted({w for sc, i in found for w in sc["turns"][i].get("text_includes", [])})
                for script, i in found:  # every matching script's case expectations hold on the stub's case
                    apply_case(call, script["turns"][i].get("case"))
            reply = build_reply(call, turn)
            call.last_seq = seq
            call.replies[seq] = reply
            cases[call.case_id]["turn_count"] = cases[call.case_id].get("turn_count", 0)
            return JSONResponse(reply, headers={"Server-Timing": "brain;dur=2"})

    @app.post("/api/console/login")
    async def login(request: Request) -> Any:
        data = await request.json()
        if data.get("passcode") != passcode:
            return _error("unauthorized")
        resp = JSONResponse({"ok": True})
        resp.set_cookie("stub_console", "1")
        return resp

    def console_ok(request: Request) -> bool:
        return request.cookies.get("stub_console") == "1"

    @app.get("/api/cases")
    def list_cases(request: Request) -> Any:
        if not console_ok(request):
            return _error("unauthorized")
        return {"items": [{"id": cid} for cid in cases], "seq": len(cases),
                "server_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}

    @app.get("/api/cases/{case_id}")
    def case_detail(case_id: str, request: Request) -> Any:
        if not console_ok(request):
            return _error("unauthorized")
        case = cases.get(case_id)
        if case is None:
            return _error("not_found")
        public = {k: v for k, v in case.items() if not k.startswith("_")}
        card = case.get("card") or {}
        return {"case": public, "summary": {"id": case_id},
                "card_url": f"/c/{card['token']}" if card.get("token") else None}

    return app


def __getattr__(name: str) -> Any:
    """`app` for uvicorn, configured from the environment the runner passes (GP_* values only)."""
    if name in ("app", "app_without_mode"):
        application = create_stub_app(card_delivery=os.environ.get("GP_CARD_DELIVERY", "code"),
                                      debug_keys=os.environ.get("GP_DEBUG_KEYS", "1") == "1",
                                      report_mode=name == "app")
        globals()[name] = application
        return application
    raise AttributeError(name)

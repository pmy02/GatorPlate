"""End-to-end runner for the Brain API (docs/BRAIN_API.md): golden dialogues, scripted and adversarial scripts, and
the replay of contracts/examples over HTTP.

Two modes:

* local (``--serve``): the runner groups the scripts (or example scenarios) by the server environment they declare,
  and for each group starts exactly one server with a clean environment (fake language model unless ``--llm
  anthropic``), waits for ``/v1/health``, runs the group and always stops the server. Card-delivery modes are never
  mixed in one server run. Phone requests are signed with the public development secret; the console is reached
  with the development passcode.
* remote (``--base URL``): no server is started. The runner reads ``card_delivery`` and ``debug_keys`` from
  ``/healthz``; a phone script that declares another card-delivery mode is skipped and counted, web scripts always
  run; with debug keys off the sentence keys are not asserted. Against a non-local base, phone scripts need
  ``GP_GATEWAY_SECRET`` and the console checks need ``GP_CONSOLE_PASSCODE`` (both read from this process's own
  environment and never printed); without them they are skipped and counted. A remote run that executes nothing
  exits non-zero.

Every reply is also checked against the contract rules that do not depend on wording: the BrainReply schema, the
output guard lists of data/content/guards.json, the phone text rules and word budgets, and the web display rules.
Reports are content-free (sentence keys, fields and counts; never reply text or utterances) and go to stdout and to
``var/reports/``.

Script format: tests/e2e/scripts/*.json and tests/adversarial/scripts/*.json, validated by ``load_script`` (the
models below) and by tests/e2e/test_static.py.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import hmac
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:  # direct runs (python tools/e2e_run.py) without PYTHONPATH
    sys.path.insert(0, str(REPO))

from gatorplate.config import DEV_CONSOLE_PASSCODE, DEV_GATEWAY_SECRET  # noqa: E402
from gatorplate.contracts.brain_api import CALL_ID, BrainReply, ErrorEnvelope  # noqa: E402
from gatorplate.contracts.extraction import ExtractionResult  # noqa: E402
from gatorplate.contracts.slots import SlotName, encode_value  # noqa: E402

SCRIPTS_DIRS = [REPO / "tests" / "e2e" / "scripts", REPO / "tests" / "adversarial" / "scripts"]
EXAMPLES_DIR = REPO / "contracts" / "examples"
GUARDS_FILE = REPO / "data" / "content" / "guards.json"
BANK_FILE = REPO / "data" / "content" / "sentences.en.json"
DEFAULT_APP = "gatorplate.main:app"
CARD_MODES = ("screen", "code")
# Values a script's env may never carry (secrets come only from the owner's environment).
SECRET_SETTINGS = {"GP_LLM_API_KEY", "GP_GATEWAY_SECRET", "GP_CONSOLE_PASSCODE", "GP_SESSION_SECRET"}
# Settings a remote run can confirm from /healthz; a script that declares any other setting needs a local server.
REMOTE_CONFIRMABLE = {"GP_CARD_DELIVERY", "GP_DEBUG_KEYS"}
# The local server's base environment; each group adds the values its scripts declare.
BASE_SERVER_ENV = {"GP_ENV": "dev", "GP_DEBUG_KEYS": "1", "GP_DEMO_MODE": "1", "GP_LIVE_TRANSCRIPT": "1"}
# Example scenarios the HTTP replay never runs: they need a controlled clock or would trip a real rate limit.
LIVE_REPLAY_SKIP = {"web_session_rate_limited": "needs a real rate limit (in-process replay only)"}

WORD_BUDGETS = {"opening": 40, "question": 25, "result": 45}
PHONE_FORBIDDEN = set("$%/~–") | set("0123456789@#&*+=<>|_\\[]{}`")
CONTACT_WORDS = re.compile(r"\b(four one five|eight five five|eight seven seven|nine eight eight|nine one one)\b",
                           re.IGNORECASE)
RESULT_KEY_PREFIXES = ("result.", "expedited.yes", "expedited.maybe", "first_month.", "card.", "close.anything_else",
                       "close.silence", "consent.declined", "crisis.resources", "human.request", "stop.goodbye",
                       "abuse.end", "error.generic", "food_today")
MONEY_SAID = re.compile(r"\$\s?\d|\bdollars?\b|\bdólares\b", re.IGNORECASE)


# ============================================================================================ script schema

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Presence = Literal["present", "null"]


class ReplyExpect(Strict):
    """BrainReply fields that must match exactly; only the fields a script names are compared."""

    end: bool | None = None
    end_reason: Literal["completed", "no_input", "declined"] | None = None
    lang: Literal["en", "es"] | None = None
    expect: Literal["open", "yes_no", "confirm", "number", "choice"] | None = None
    listen: Literal["normal", "long"] | None = None
    interruptible: bool | None = None
    hold_s: int | None = None
    ask: Presence | None = None
    display: Presence | None = None
    choices: Presence | None = None
    card_url: Presence | None = None


class Silence(Strict):
    n: int = Field(ge=1)
    ms: int = Field(default=5000, ge=0)


class EndBlock(Strict):
    reason: Literal["completed", "caller_hangup", "no_input", "timeout", "max_duration", "declined", "error"]
    turns: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)


class FlipAsked(Strict):
    slot: str
    reason: str


class SkippedEntry(Strict):
    slot: str
    reason: str


class AskedLast(Strict):
    key: str
    kind: str | None = None
    slots: list[str] | None = None
    reason: str | None = None


class YellowExpect(Strict):
    kind: str
    code: str
    slot: str | None = None
    reason: str | None = None


class RangeExpect(Strict):
    lo: int
    hi: int
    settled: bool


class LanguageRequestExpect(Strict):
    asked: str
    offered: str


class CaseExpect(Strict):
    """Checked on the stored case through the console API (after a turn, or after /end for `final`)."""

    golden_case: str | None = None  # informational
    slots: dict[str, str] = Field(default_factory=dict)
    slots_absent: list[str] = Field(default_factory=list)
    changed_from: dict[str, str] = Field(default_factory=dict)
    heard_en_present: list[str] = Field(default_factory=list)
    tier: str | None = None
    reason_code: str | None = None
    estimate_monthly: int | None = None
    estimate_is_floor: bool | None = None
    estimate_range: RangeExpect | None = None
    expedited_possible: Literal["yes", "maybe", "no"] | None = None
    asked_last: AskedLast | None = None
    asked_flip: list[FlipAsked] | None = None
    asked_keys_include: list[str] = Field(default_factory=list)
    skipped: list[SkippedEntry] = Field(default_factory=list)  # these, and no other no_effect/below_threshold
    skipped_include: list[SkippedEntry] = Field(default_factory=list)  # these at least
    yellow_open: int | None = None
    yellow: list[YellowExpect] = Field(default_factory=list)
    yellow_codes_include: list[str] = Field(default_factory=list)
    flags_include: list[str] = Field(default_factory=list)
    card_created: bool | None = None
    summary: str | None = None
    student_turns: int | None = None
    max_student_turns: int | None = None
    privacy_events: list[str] | None = None  # kinds, in order
    ended_reason: str | None = None
    ended_early: bool | None = None
    live: bool | None = None
    lang: Literal["en", "es"] | None = None
    language_request: LanguageRequestExpect | None = None
    amount_said: bool | None = None  # checked on the replies, not on the case
    reply_keys_include: list[str] = Field(default_factory=list)  # some reply of the call used each key (debug keys)
    deleted: bool | None = None  # the case is gone (console 404)
    card_gone: bool | None = None  # the card seen earlier in this call answers 404 or 410
    heard_excludes: list[str] = Field(default_factory=list)  # no stored quote or gloss contains these

    @field_validator("privacy_events", mode="before")
    @classmethod
    def _kinds(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [v["kind"] if isinstance(v, dict) else v for v in value]
        return value


TurnAuth = Literal["normal", "none", "bad_signature", "stale_timestamp", "wrong_token"]


class Turn(Strict):
    # exactly one event
    start: bool = False
    user: str | None = Field(default=None, max_length=1000)
    dtmf: str | None = Field(default=None, pattern=r"^[0-9*#]{1,20}$")
    silence: Silence | None = None
    end_call: EndBlock | None = None  # an /end in the middle of a script (hang-up, then later turns)
    repeat_previous: bool = False  # resend the previous turn request unchanged (same seq): identical reply
    # conditional turn: played only when the previous reply's keys include this question key (needs debug keys);
    # lets a script answer value-of-information questions in whichever order the plan asks them
    when_pending: str | None = None
    # request details
    lang: Literal["en", "es"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    masked: bool = False
    interrupted: bool = False
    typed: bool = False
    seq: int | None = Field(default=None, ge=1)  # explicit seq (a stale seq test); otherwise previous + 1
    auth: TurnAuth = "normal"
    call: Literal["this", "unknown"] = "this"
    # expectations
    expect_status: int = 200
    expect_error: str | None = None
    expect_keys: list[str] | None = None
    expect_keys_include: list[str] | None = None
    expect_keys_exclude: list[str] | None = None
    reply: ReplyExpect | None = None
    expect_end: bool | None = None
    budget: Literal["opening", "question", "result"] | None = None
    same_as: int | None = Field(default=None, ge=0)  # index of an earlier turn whose reply this one equals
    text_excludes: list[str] = Field(default_factory=list)  # case-insensitive, on say + ask + display + choices
    text_includes: list[str] = Field(default_factory=list)  # case-insensitive, on the same text
    expect_nonempty: bool = False  # say or ask carries words (never an empty reply)
    fake_llm: dict[str, Any] | None = None  # the ExtractionResult the fake model returns for this utterance
    case: CaseExpect | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _one_event(self) -> Turn:
        events = [self.start, self.user is not None, self.dtmf is not None, self.silence is not None,
                  self.end_call is not None, self.repeat_previous]
        if sum(bool(e) for e in events) != 1:
            raise ValueError("a turn has exactly one of start, user, dtmf, silence, end_call, repeat_previous")
        if self.expect_status != 200 and self.expect_error is None:
            raise ValueError("a non-200 turn names its expect_error code")
        if self.fake_llm is not None:
            if self.user is None:
                raise ValueError("fake_llm belongs to an utterance turn")
            ExtractionResult.model_validate(self.fake_llm)
        if self.end_call is not None and (self.expect_keys or self.expect_keys_include or self.reply):
            raise ValueError("an end_call turn has no reply to check")
        if self.when_pending is not None and self.kind not in ("utterance", "dtmf", "silence"):
            raise ValueError("when_pending is for utterance, dtmf or silence turns")
        return self

    @property
    def kind(self) -> str:
        if self.start:
            return "start"
        if self.end_call is not None:
            return "end"
        if self.user is not None:
            return "utterance"
        if self.dtmf is not None:
            return "dtmf"
        if self.silence is not None:
            return "silence"
        return "repeat"


class WebSession(Strict):
    lang: Literal["en", "es"] = "en"


class Script(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str
    title: str
    appendix: str | None = Field(default=None, pattern=r"^[SA]\d{2}$")  # the scenario list entry it implements
    golden_case: str | None = None
    demo_case: str | None = None
    contract_example: str | None = None
    channel: Literal["phone", "web"]
    lang: Literal["en", "es"]
    test: bool = False  # StartRequest.test
    fake_llm_ok: bool
    native_review: bool = False
    env: dict[str, str]
    settings: dict[str, str] | None = None  # a leftover copy must equal env
    matching: dict[str, str] | None = None
    web_session: WebSession | None = None
    tags: list[str] = Field(default_factory=list)
    turns: list[Turn] = Field(min_length=1)
    end: EndBlock | None = None
    final: CaseExpect | None = None
    note: str | None = None

    @field_validator("env")
    @classmethod
    def _env(cls, env: dict[str, str]) -> dict[str, str]:
        if env.get("GP_CARD_DELIVERY") not in CARD_MODES:
            raise ValueError("env.GP_CARD_DELIVERY is required: 'screen' or 'code'")
        for name, value in env.items():
            if not re.fullmatch(r"GP_[A-Z0-9_]+", name):
                raise ValueError(f"env names are GP_* settings only: {name!r}")
            if name in SECRET_SETTINGS:
                raise ValueError(f"a script never carries a secret setting: {name}")
            if not isinstance(value, str):
                raise ValueError(f"env values are strings: {name}")
        if env.get("GP_ENV", "dev") not in ("dev", "test"):
            raise ValueError("scripts run against dev or test servers only")
        return env

    @model_validator(mode="after")
    def _shape(self) -> Script:
        if self.settings is not None and self.settings != self.env:
            raise ValueError("a leftover settings block must equal env")
        if not self.turns[0].start or any(t.start for t in self.turns[1:]):
            raise ValueError("the first turn, and only the first, is the start")
        if self.channel == "phone" and self.lang != "en":
            raise ValueError("phone scripts are English (docs/BRAIN_API.md §5.1)")
        if self.channel == "web" and any(t.dtmf is not None or t.masked for t in self.turns):
            raise ValueError("the web page sends utterances only (docs/BRAIN_API.md §10)")
        if self.channel == "phone" and self.web_session is not None:
            raise ValueError("web_session is for web scripts")
        for i, t in enumerate(self.turns):
            if t.same_as is not None and t.same_as >= i:
                raise ValueError(f"turn {i}: same_as must point to an earlier turn")
            if t.repeat_previous and (i == 0 or self.turns[i - 1].kind not in ("utterance", "dtmf", "silence",
                                                                               "repeat")):
                raise ValueError(f"turn {i}: repeat_previous follows a turn request")
            if t.expect_end is not None and t.reply is not None and t.reply.end is not None \
                    and t.reply.end != t.expect_end:
                raise ValueError(f"turn {i}: expect_end and reply.end disagree")
        return self

    @property
    def card_mode(self) -> str:
        return self.env["GP_CARD_DELIVERY"]


def load_script(path: Path) -> Script:
    data = json.loads(path.read_text(encoding="utf-8"))
    script = Script.model_validate(data)
    if script.id != path.stem:
        raise ValueError(f"{path.name}: id {script.id!r} must equal the file name")
    return script


def sentence_keys() -> set[str]:
    return set(json.loads(BANK_FILE.read_text(encoding="utf-8"))["messages"])


def check_script_names(script: Script, keys: set[str] | None = None) -> list[str]:
    """Static checks that need the bank and the slot list (used by test_static and at load time)."""
    keys = sentence_keys() if keys is None else keys
    problems = []
    for i, t in enumerate(script.turns):
        for group in (t.expect_keys, t.expect_keys_include, t.expect_keys_exclude,
                      [t.when_pending] if t.when_pending else None):
            for key in group or []:
                if key not in keys:
                    problems.append(f"turn {i}: unknown sentence key {key!r}")
        for block in (t.case,):
            problems += [f"turn {i}: {p}" for p in _case_expect_problems(block)]
    problems += [f"final: {p}" for p in _case_expect_problems(script.final)]
    problems += _final_key_problems(script, keys)
    return problems


def _case_expect_problems(expect: CaseExpect | None) -> list[str]:
    if expect is None:
        return []
    out = []
    names = {s.value for s in SlotName}
    for name, value in expect.slots.items():
        if name not in names:
            out.append(f"unknown slot {name!r}")
            continue
        try:
            if encode_value(name, value) != value:
                out.append(f"slot {name} value {value!r} is not canonical")
        except (TypeError, ValueError) as exc:
            out.append(f"slot {name}: {exc}")
    for name in [*expect.slots_absent, *expect.heard_en_present, *expect.changed_from]:
        if name not in names:
            out.append(f"unknown slot {name!r}")
    return out


def _final_key_problems(script: Script, keys: set[str]) -> list[str]:
    return [f"final: unknown sentence key {k!r}" for k in (script.final.reply_keys_include if script.final else [])
            if k not in keys]


def load_scripts(dirs: list[Path]) -> list[tuple[Path, Script]]:
    out = []
    for folder in dirs:
        for path in sorted(folder.glob("*.json")):
            out.append((path, load_script(path)))
    return out


# ============================================================================================ reply checks

def count_words(text: str) -> int:
    """docs/BRAIN_API.md §7: a whitespace-separated token with at least one letter or digit."""
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


class OutputGuard:
    """data/content/guards.json output lists, applied as its format section says."""

    def __init__(self, path: Path = GUARDS_FILE) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))["output"]
        patterns = data["forbidden"]
        flat = [p for group in (patterns.values() if isinstance(patterns, dict) else [patterns]) for p in group]
        self.patterns = [re.compile(p, re.IGNORECASE) for p in flat]
        self.phrases = [p.lower() for p in data.get("forbidden_phrases", [])]

    @staticmethod
    def normalize(text: str) -> str:
        text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return " ".join(text.split())

    def hits(self, text: str) -> list[str]:
        norm = self.normalize(text)
        low = norm.lower()
        out = [f"pattern #{i}" for i, rx in enumerate(self.patterns) if rx.search(norm)]
        out += [f"phrase {p!r}" for p in self.phrases if p in low]
        return out


def infer_budget(keys: list[str] | None, spoken: str, is_start: bool) -> str:
    if is_start:
        return "opening"
    if keys and any(k.startswith(RESULT_KEY_PREFIXES) for k in keys):
        return "result"
    if CONTACT_WORDS.search(spoken):
        return "result"
    return "question"


def reply_problems(reply: dict, *, channel: str, keys: list[str] | None, budget: str | None, is_start: bool,
                   guard: OutputGuard | None, state: dict) -> list[str]:
    """Wording-independent contract checks on one BrainReply (docs/BRAIN_API.md §6–§7, §10)."""
    out: list[str] = []
    try:
        BrainReply.model_validate(reply)
    except ValidationError as exc:
        return [f"reply does not match the BrainReply schema ({exc.error_count()} errors)"]
    spoken = " ".join(p for p in (reply["say"], reply["ask"]) if p)
    shown = reply["display"] or ""
    every = " ".join([spoken, shown, *(reply["choices"] or [])])
    if guard is not None:
        out += [f"output guard hit: {h}" for h in guard.hits(every)]
    if reply["choices"] is not None and reply["ask"] is None:
        out.append("choices only together with a question")
    if reply["ask"] is None and reply["expect"] != "open":
        out.append("ask null means expect open")
    if reply["end"] and reply["interruptible"]:
        out.append("end replies are not interruptible")
    if is_start:
        # docs/BRAIN_API.md §6: the /start reply has a non-empty say, a consent question, end false and is never
        # interruptible.
        if reply["interruptible"]:
            out.append("the opening is never interruptible")
        if not reply["say"].strip():
            out.append("the opening say is never empty")
        if reply["ask"] is None:
            out.append("the opening asks for consent")
        if reply["end"]:
            out.append("the opening never ends the call")
    if keys and any(k in ("result.likely", "result.likely_floor") for k in keys):
        hedge = "county" if reply["lang"] == "en" else "condado"
        if hedge not in reply["say"].lower():
            out.append("an estimated amount needs the county-decides sentence in the same reply")
    if channel == "phone":
        for name in ("display", "choices", "card_url"):
            if reply[name] is not None:
                out.append(f"phone replies have {name} null")
        bad = sorted({ch for ch in spoken if ch in PHONE_FORBIDDEN})
        if bad:
            out.append(f"phone text has symbols or digits: {''.join(bad)!r}")
        if re.search(r"https?:|www\.", spoken, re.IGNORECASE):
            out.append("phone text has a written URL")
        if keys is not None:
            want = "es" if "language.offer_web" in keys else "en"
            if reply["lang"] != want:
                out.append(f"phone reply lang must be {want}")
        cls = budget or infer_budget(keys, spoken, is_start)
        words = count_words(spoken)
        if words > WORD_BUDGETS[cls]:
            out.append(f"{words} words > {cls} budget {WORD_BUDGETS[cls]}")
            state["budget_overruns"] = state.get("budget_overruns", 0) + 1
    else:
        if not isinstance(reply["display"], str):
            out.append("web replies always carry display")
        if state.get("card_url") and reply["card_url"] != state["card_url"]:
            out.append("card_url, once set, stays set")
        if reply["card_url"]:
            state["card_url"] = reply["card_url"]
    return out


# ============================================================================================ HTTP helpers

def sign(secret: str, method: str, path: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    """docs/BRAIN_API.md §3.1: headers for one gateway request over the exact body bytes."""
    ts = int(time.time()) if ts is None else ts
    digest = hashlib.sha256(body).hexdigest()
    message = f"{ts}.{method.upper()}.{path}.{digest}".encode()
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"X-GP-Timestamp": str(ts), "X-GP-Signature": f"v1={signature}"}


def body_bytes(body: Any) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def server_ms(headers: Any) -> float | None:
    """Server processing time from `Server-Timing: brain;dur=<ms>` (content-free)."""
    value = headers.get("server-timing") if headers is not None else None
    if not value:
        return None
    m = re.search(r"brain;dur=([0-9.]+)", value)
    return float(m.group(1)) if m else None


def is_local_base(base: str) -> bool:
    host = (urlparse(base).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "testserver") or host.endswith(".localhost")


@dataclass
class Target:
    """Where calls go and with which credentials. `client` is an httpx.Client (or a TestClient)."""

    client: Any
    base: str
    secret: str | None  # gateway secret for phone requests (None: phone scripts are skipped)
    passcode: str | None  # console passcode (None: console checks are skipped)
    debug_keys: bool = True
    card_delivery: str | None = None
    console_lock: threading.Lock = field(default_factory=threading.Lock)
    discovery_lock: threading.Lock = field(default_factory=threading.Lock)
    logged_in: bool = False
    login_failed: bool = False
    clock: Any = None  # optional callable -> unix seconds for signing (an in-process app with a fixed clock)
    remote: bool = False  # a server this run did not start: only card delivery and debug keys can be confirmed

    def post(self, path: str, body: Any = None, *, channel: str | None = None, token: str | None = None,
             auth: str = "normal", raw: bytes | None = None, headers: dict | None = None) -> Any:
        data = raw if raw is not None else (body_bytes(body) if body is not None else b"")
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        elif auth != "none":
            if channel == "phone":
                secret = self.secret or DEV_GATEWAY_SECRET
                now = int(self.clock()) if self.clock else int(time.time())
                if auth == "bad_signature":
                    hdrs.update(sign(secret + "-wrong", "POST", path, data, ts=now))
                elif auth == "stale_timestamp":
                    hdrs.update(sign(secret, "POST", path, data, ts=now - 600))
                else:
                    hdrs.update(sign(secret, "POST", path, data, ts=now))
            elif channel == "web" and token:
                hdrs["Authorization"] = f"Bearer {token if auth != 'wrong_token' else token[::-1]}"
        return self.client.post(path, content=data, headers=hdrs)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(path, **kwargs)

    # ---------------------------------------------------------------- console (lenient JSON reading)
    def console_ready(self) -> bool:
        if self.passcode is None or self.login_failed:
            return False
        with self.console_lock:
            if not self.logged_in:
                r = self.client.post("/api/console/login", json={"passcode": self.passcode})
                self.logged_in = r.status_code == 200
                self.login_failed = not self.logged_in
        return self.logged_in

    def case_ids(self) -> set[str]:
        r = self.client.get("/api/cases", params={"limit": 500})
        if r.status_code != 200:
            return set()
        return {item["id"] for item in r.json().get("items", [])}

    def case_detail(self, case_id: str) -> tuple[int, dict | None]:
        r = self.client.get(f"/api/cases/{case_id}")
        return r.status_code, (r.json() if r.status_code == 200 else None)


# ============================================================================================ script player

@dataclass
class ItemResult:
    id: str
    kind: str  # script | scenario
    channel: str
    lang: str
    group: str = ""
    status: str = "passed"  # passed | failed | skipped
    skip_reason: str | None = None
    failures: list[str] = field(default_factory=list)
    turns: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    keys_asserted: bool = True
    console_checked: bool = True
    budget_overruns: int = 0
    case_id: str | None = None
    call_id: str | None = None
    final_case: dict | None = None
    question_keys: list[str] = field(default_factory=list)

    def fail(self, where: str, message: str) -> None:
        self.status = "failed"
        self.failures.append(f"{where}: {message}")


def keys_problems(turn: Turn, got: list[str] | None) -> list[str]:
    out = []
    if got is None:
        return ["debug.keys missing (GP_DEBUG_KEYS=1 expected)"]
    if turn.expect_keys is not None and got != turn.expect_keys:
        out.append(f"keys {got} != expected {turn.expect_keys}")
    if turn.expect_keys_include:
        it = iter(got)
        if not all(any(k == g for g in it) for k in turn.expect_keys_include):
            out.append(f"keys {got} do not contain {turn.expect_keys_include} in order")
    for k in turn.expect_keys_exclude or []:
        if k in got:
            out.append(f"key {k} must not appear (got {got})")
    return out


def reply_field_problems(expect: ReplyExpect | None, reply: dict) -> list[str]:
    if expect is None:
        return []
    out = []
    for name in expect.model_fields_set:
        want = getattr(expect, name)
        got = reply.get(name)
        if name in ("ask", "display", "choices", "card_url"):
            ok = (got is not None) if want == "present" else (got is None)
            if not ok:
                out.append(f"{name} should be {want}")
        elif got != want:
            out.append(f"{name} {got!r} != {want!r}")
    return out


def _slot_value(case: dict, name: str) -> str | None:
    slot = (case.get("slots") or {}).get(name)
    return slot.get("value") if isinstance(slot, dict) else None


# Machine fields (ids, codes, tokens, timestamps, links) are not student text: digits in a timestamp or a token must
# not count as a stored number.
_MACHINE_KEYS = {"id", "code", "token", "case_id", "call_id", "card_url", "qr_svg_url", "short_code", "at",
                 "reminders_url", "delete_url", "table_id", "version", "key", "source_ids", "url"}


def _stored_texts(obj: Any, path: str = "") -> Any:
    """(path, text) for every string in a console CaseDetail, except machine fields."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            if key in _MACHINE_KEYS or key.endswith(("_at", "_on", "_id", "_url")):
                continue
            yield from _stored_texts(v, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _stored_texts(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def case_problems(expect: CaseExpect, detail: dict | None, status: int, replies: list[dict]) -> list[str]:
    """Compare a CaseDetail (read leniently as JSON) with the expectations."""
    if expect.deleted is not None:
        gone = status == 404
        if gone != expect.deleted:
            return [f"case deleted={gone}, expected {expect.deleted}"]
        if gone:
            return []
    if detail is None:
        return [f"case not readable (HTTP {status})"]
    case = detail.get("case") or {}
    out = []
    for name, value in expect.slots.items():
        got = _slot_value(case, name)
        if got != value:
            out.append(f"slot {name} {got!r} != {value!r}")
    for name in expect.slots_absent:
        if _slot_value(case, name) is not None:
            out.append(f"slot {name} must not be stored")
    for name, value in expect.changed_from.items():
        slot = (case.get("slots") or {}).get(name) or {}
        if slot.get("changed_from") != value:
            out.append(f"slot {name} changed_from {slot.get('changed_from')!r} != {value!r}")
    for name in expect.heard_en_present:
        slot = (case.get("slots") or {}).get(name) or {}
        if not slot.get("heard_en"):
            out.append(f"slot {name} has no heard_en")
    for name in ("tier", "reason_code", "estimate_monthly", "estimate_is_floor", "expedited_possible", "summary",
                 "ended_reason", "ended_early", "live", "lang"):
        want = getattr(expect, name)
        if name in expect.model_fields_set and case.get(name) != want:
            out.append(f"{name} {case.get(name)!r} != {want!r}")
    if expect.estimate_range is not None:
        got = case.get("estimate_range")
        if got != expect.estimate_range.model_dump():
            out.append(f"estimate_range {got} != {expect.estimate_range.model_dump()}")
    asked = case.get("asked") or []
    if expect.asked_last is not None:
        last = asked[-1] if asked else {}
        for name in expect.asked_last.model_fields_set:
            if last.get(name) != getattr(expect.asked_last, name):
                out.append(f"asked_last.{name} {last.get(name)!r} != {getattr(expect.asked_last, name)!r}")
    if expect.asked_flip is not None:
        got = [{"slot": (a.get("slots") or [None])[0], "reason": a.get("reason")} for a in asked
               if a.get("kind") == "flip"]
        want = [f.model_dump() for f in expect.asked_flip]
        if got != want:
            out.append(f"asked flips {got} != {want}")
    asked_keys = [a.get("key") for a in asked]
    for key in expect.asked_keys_include:
        if key not in asked_keys:
            out.append(f"question {key} was not asked")
    skipped = [{"slot": s.get("slot"), "reason": s.get("reason")} for s in case.get("skipped") or []]
    for entry in [*expect.skipped, *expect.skipped_include]:
        if entry.model_dump() not in skipped:
            out.append(f"skipped entry {entry.model_dump()} missing")
    if expect.skipped or "skipped" in expect.model_fields_set:
        listed = [e.model_dump() for e in expect.skipped]
        extra = [s for s in skipped if s not in listed and s["reason"] not in ("hard_stop", "not_applicable")]
        if extra:
            out.append(f"unexpected skipped entries {extra}")
    lines = case.get("yellow_lines") or []
    if expect.yellow_open is not None:
        n_open = sum(1 for y in lines if not y.get("resolved"))
        if n_open != expect.yellow_open:
            out.append(f"open yellow lines {n_open} != {expect.yellow_open}")
    for want in expect.yellow:
        fields = want.model_dump(exclude_none=True)
        if not any(all(y.get(k) == v for k, v in fields.items()) for y in lines):
            out.append(f"yellow line {fields} missing")
    codes = [y.get("code") for y in lines]
    for code in expect.yellow_codes_include:
        if code not in codes:
            out.append(f"yellow line code {code} missing (got {codes})")
    if expect.heard_excludes:
        # Never stored (docs/SPEC.md §8): the words may not survive anywhere in the stored case — slots, yellow
        # lines, the asked list, the summary or any other text field — and not in the detail around it.
        texts = list(_stored_texts({"case": detail.get("case"), "summary": detail.get("summary")}))
        for needle in expect.heard_excludes:
            where = sorted({path for path, text in texts if needle.lower() in text.lower()})
            if where:
                out.append(f"stored text keeps {needle!r} (at {', '.join(where[:4])})")
    flags = case.get("flags") or []
    for flag in expect.flags_include:
        if flag not in flags:
            out.append(f"flag {flag} missing (got {flags})")
    if expect.card_created is not None and (case.get("card") is not None) != expect.card_created:
        out.append(f"card_created {case.get('card') is not None} != {expect.card_created}")
    if expect.student_turns is not None and case.get("turn_count") != expect.student_turns:
        out.append(f"student turns {case.get('turn_count')} != {expect.student_turns}")
    if expect.max_student_turns is not None and (case.get("turn_count") or 0) > expect.max_student_turns:
        out.append(f"student turns {case.get('turn_count')} > {expect.max_student_turns}")
    if expect.privacy_events is not None:
        kinds = [p.get("kind") for p in case.get("privacy_events") or []]
        if kinds != expect.privacy_events:
            out.append(f"privacy events {kinds} != {expect.privacy_events}")
    if expect.language_request is not None and case.get("language_request") != expect.language_request.model_dump():
        out.append(f"language_request {case.get('language_request')} != {expect.language_request.model_dump()}")
    seen = [k for r in replies for k in ((r.get("debug") or {}).get("keys") or [])]
    if any(r.get("debug") for r in replies):
        for key in expect.reply_keys_include:
            if key not in seen:
                out.append(f"no reply used {key}")
    if expect.amount_said is not None:
        said = any(MONEY_SAID.search(" ".join(filter(None, (r.get("say"), r.get("ask"), r.get("display")))))
                   for r in replies)
        if said != expect.amount_said:
            out.append(f"amount said {said} != {expect.amount_said}")
    return out


QUESTION_PREFIXES = ("ask.", "flip.", "expedited.intro_cash", "confirm.", "consent.", "close.anything_else",
                     "crisis.continue_or_stop", "human.request", "delete.confirm_ask")


class Player:
    """Plays one script against a target and records the result (no wording is stored)."""

    def __init__(self, script: Script, target: Target, guard: OutputGuard | None, *, group: str = "") -> None:
        self.s = script
        self.t = target
        self.guard = guard
        self.r = ItemResult(id=script.id, kind="script", channel=script.channel, lang=script.lang, group=group)
        self.call_id = uuid.uuid4().hex
        self.token: str | None = None
        self.seq = 0
        self.last_request: tuple[str, dict] | None = None
        self.replies: dict[int, dict] = {}
        self.all_replies: list[dict] = []
        self.state: dict = {}
        self.case_id: str | None = None
        self.known_ids: set[str] | None = None
        self.locked = False
        self.card_url: str | None = None
        self.last_keys: list[str] | None = None

    # ---------------------------------------------------------------- case discovery
    def _begin_discovery(self) -> None:
        if not self.t.console_ready():
            self.r.console_checked = False
            return
        self.t.discovery_lock.acquire()
        self.locked = True
        self.known_ids = self.t.case_ids()

    def _try_discover(self) -> None:
        if self.case_id is not None or self.known_ids is None:
            return
        new = self.t.case_ids() - self.known_ids
        if len(new) == 1:
            self.case_id = new.pop()
            self.r.case_id = self.case_id
        if self.case_id is not None:
            self._end_discovery()

    def _end_discovery(self) -> None:
        if self.locked:
            self.locked = False
            self.t.discovery_lock.release()

    def _check_case(self, where: str, expect: CaseExpect) -> None:
        if not self.r.console_checked:
            return
        if self.case_id is None:
            self._try_discover()
        if self.case_id is None:
            self.r.fail(where, "no case found for this call through the console API")
            return
        status, detail = self.t.case_detail(self.case_id)
        for p in case_problems(expect, detail, status, self.all_replies):
            self.r.fail(where, p)
        if detail is not None:
            self.r.final_case = detail.get("case")
            if detail.get("card_url"):
                self.card_url = detail["card_url"]
        if expect.card_gone is not None:
            if not self.card_url:
                self.r.fail(where, "card_gone: no card was seen earlier in this call")
            else:
                token = self.card_url.rstrip("/").split("/")[-1]
                gone = self.t.get(f"/api/card/{token}").status_code in (404, 410)
                if gone != expect.card_gone:
                    self.r.fail(where, f"card gone={gone}, expected {expect.card_gone}")

    # ---------------------------------------------------------------- requests
    def _call_path(self, step: str, turn: Turn) -> str:
        cid = uuid.uuid4().hex if turn.call == "unknown" else self.call_id
        return f"/v1/calls/{cid}/{step}"

    def _send(self, step: str, body: dict, turn: Turn) -> Any:
        self.r.call_id = self.call_id
        path = self._call_path(step, turn)
        self.last_request = (path, body)
        return self.t.post(path, body, channel=self.s.channel, token=self.token, auth=turn.auth)

    def run(self) -> ItemResult:
        try:
            self._run()
        except Exception as exc:  # report, never crash the whole run
            self.r.fail("runner", f"{type(exc).__name__}: {str(exc)[:160]}")
        finally:
            self._end_discovery()
        return self.r

    def _run(self) -> None:
        s = self.s
        if not self.t.debug_keys:
            self.r.keys_asserted = False
            if any(t.when_pending for t in s.turns):
                self.r.status, self.r.skip_reason = "skipped", "conditional turns need debug keys"
                return
        if s.channel == "web":
            lang = s.web_session.lang if s.web_session else s.lang
            r = self.t.post("/api/web/sessions", {"lang": lang}, auth="none")
            if r.status_code != 200:
                self.r.fail("web_session", f"HTTP {r.status_code}")
                return
            data = r.json()
            self.call_id, self.token = data["call_id"], data["token"]
            if not re.fullmatch(CALL_ID, self.call_id):
                self.r.fail("web_session", "call_id does not match the contract pattern")
        for i, turn in enumerate(s.turns):
            if turn.when_pending is not None and turn.when_pending not in (self.last_keys or []):
                continue  # the plan did not ask this question here
            self._turn(i, turn)
            if self.r.status == "failed" and turn.start:
                return  # nothing else can be judged without a started call
        if s.end is not None:
            body = {"v": 1, "reason": s.end.reason, **s.end.model_dump(exclude={"reason"}, exclude_none=True)}
            r = self._send("end", body, Turn(start=False, end_call=s.end))
            if r.status_code != 200:
                self.r.fail("end", f"HTTP {r.status_code}")
        self._try_discover()
        if s.final is not None:
            self._check_case("final", s.final)
        elif self.r.console_checked and self.case_id is not None:
            _, detail = self.t.case_detail(self.case_id)
            self.r.final_case = (detail or {}).get("case")

    def _turn(self, i: int, turn: Turn) -> None:
        where = f"turn {i}"
        lang = turn.lang or self.s.lang
        if turn.start:
            self._begin_discovery()
            body = {"v": 1, "seq": 0, "channel": self.s.channel, "lang": lang, "test": self.s.test}
            r = self._send("start", body, turn)
        elif turn.end_call is not None:
            body = {"v": 1, "reason": turn.end_call.reason,
                    **turn.end_call.model_dump(exclude={"reason"}, exclude_none=True)}
            r = self._send("end", body, turn)
        elif turn.repeat_previous:
            assert self.last_request is not None
            path, body = self.last_request
            r = self.t.post(path, body, channel=self.s.channel, token=self.token, auth=turn.auth)
        else:
            seq = turn.seq if turn.seq is not None else self.seq + 1
            body = {"v": 1, "seq": seq, "lang": lang}
            if turn.user is not None:
                body.update(event="utterance", text=turn.user, masked=turn.masked, confidence=turn.confidence,
                            interrupted=turn.interrupted, typed=turn.typed)
            elif turn.dtmf is not None:
                body.update(event="dtmf", dtmf=turn.dtmf)
            else:
                assert turn.silence is not None
                body.update(event="silence", silence_n=turn.silence.n, silence_ms=turn.silence.ms)
            r = self._send("turn", body, turn)
            if r.status_code == 200 and turn.call == "this":
                self.seq = max(self.seq, seq)
        self.r.turns += 1
        if r.status_code != turn.expect_status:
            self.r.fail(where, f"HTTP {r.status_code} != {turn.expect_status}")
            return
        if turn.expect_status != 200:
            try:
                env = ErrorEnvelope.model_validate(r.json())
                if env.error.code != turn.expect_error:
                    self.r.fail(where, f"error code {env.error.code} != {turn.expect_error}")
            except (ValidationError, ValueError):
                self.r.fail(where, "error body is not an ErrorEnvelope")
            return
        if turn.end_call is not None:
            if r.json() != {}:
                self.r.fail(where, "/end answers {}")
            return
        ms = server_ms(r.headers)
        if ms is not None and turn.kind in ("utterance", "dtmf"):
            self.r.latencies_ms.append(ms)
        reply = r.json()
        self.replies[i] = reply
        self.all_replies.append(reply)
        if turn.start:
            self._try_discover()
        debug = reply.get("debug")
        keys = debug.get("keys") if isinstance(debug, dict) else None
        self.last_keys = keys
        if keys:
            self.r.question_keys += [k for k in keys if k.startswith(QUESTION_PREFIXES)]
        if self.t.debug_keys:
            if turn.expect_keys is not None or turn.expect_keys_include or turn.expect_keys_exclude:
                for p in keys_problems(turn, keys):
                    self.r.fail(where, p)
        elif debug is not None:
            self.r.fail(where, "debug must be null when the server runs with debug keys off")
        for p in reply_field_problems(turn.reply, reply):
            self.r.fail(where, p)
        if turn.expect_end is not None and reply.get("end") != turn.expect_end:
            self.r.fail(where, f"end {reply.get('end')} != {turn.expect_end}")
        if turn.same_as is not None:
            if self.replies.get(turn.same_as) != reply:
                self.r.fail(where, f"reply differs from turn {turn.same_as}'s reply")
        problems = reply_problems(reply, channel=self.s.channel, keys=keys if self.t.debug_keys else None,
                                  budget=turn.budget, is_start=turn.start, guard=self.guard, state=self.state)
        for p in problems:
            self.r.fail(where, p)
        if reply.get("card_url"):
            self.card_url = reply["card_url"]
        if turn.budget and self.s.channel == "phone" and self.t.debug_keys and keys:
            # A declared budget is an expectation about the reply class (docs/BRAIN_API.md §7): a reply that turns
            # out to be a result while the script declares a question (or the reverse) is a script or brain error,
            # not a looser or stricter word count.
            spoken = " ".join(p for p in (reply.get("say"), reply.get("ask")) if p)
            inferred = infer_budget(keys, spoken, turn.start)
            if inferred != turn.budget:
                self.r.fail(where, f"the script declares a {turn.budget} turn, the reply is a {inferred} turn "
                                   f"(keys {keys})")
        self.r.budget_overruns = self.state.get("budget_overruns", 0)
        text = " ".join(filter(None, [reply.get("say"), reply.get("ask"), reply.get("display"),
                                      *(reply.get("choices") or [])])).lower()
        for needle in turn.text_excludes:
            if needle.lower() in text:
                self.r.fail(where, f"reply contains the excluded text {needle!r}")
        for needle in turn.text_includes:
            if needle.lower() not in text:
                self.r.fail(where, f"reply lacks the text {needle!r}")
        if turn.expect_nonempty and count_words(" ".join(filter(None, [reply.get("say"), reply.get("ask")]))) == 0:
            self.r.fail(where, "empty reply")
        if turn.case is not None:
            self._check_case(where, turn.case)


# ============================================================================================ example replay

def scenario_skip_reason(sc: dict) -> str | None:
    if sc["id"] in LIVE_REPLAY_SKIP:
        return LIVE_REPLAY_SKIP[sc["id"]]
    if sc.get("given"):
        return "needs a seeded call state (in-process replay only)"
    if sc.get("server_now") is not None:
        return "needs a controlled clock (in-process replay only)"
    return None


def scenario_env(sc: dict) -> dict[str, str]:
    env = dict(sc.get("settings") or {})
    env.setdefault("GP_CARD_DELIVERY", "code")
    return env


def load_scenarios(folder: Path) -> list[dict]:
    out = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for sc in data.get("scenarios", []):
            sc = dict(sc)
            sc["_file"] = path.name
            out.append(sc)
    return out


class Replayer:
    """Replays one contract-example scenario over HTTP: status codes, error codes, reply shape and debug.keys."""

    def __init__(self, sc: dict, target: Target, guard: OutputGuard | None, *, group: str = "") -> None:
        self.sc = sc
        self.t = target
        self.guard = guard
        self.r = ItemResult(id=sc["id"], kind="scenario", channel=sc["channel"], lang=sc["lang"], group=group)
        self.call_id = uuid.uuid4().hex if sc["channel"] == "phone" else None
        self.token: str | None = None
        self.by_id: dict[str, Any] = {}
        self.state: dict = {}

    def run(self) -> ItemResult:
        try:
            for n, ex in enumerate(self.sc["exchanges"]):
                self._exchange(n, ex)
        except Exception as exc:
            self.r.fail("runner", f"{type(exc).__name__}: {str(exc)[:160]}")
        if not self.t.debug_keys:
            self.r.keys_asserted = False
        self.r.console_checked = False
        return self.r

    def _exchange(self, n: int, ex: dict) -> None:
        where = f"exchange {n} ({ex['step']})"
        req, want = ex["request"], ex["response"]
        path = req["path"]
        if self.sc.get("call_id") and self.call_id:
            path = path.replace(self.sc["call_id"], self.call_id)
        raw = req["body_raw"].encode("utf-8") if "body_raw" in req else None
        body = req.get("body")
        if req["method"] == "GET":
            hdrs = {}
            if req.get("auth") == "gateway":
                hdrs = sign(self.t.secret or DEV_GATEWAY_SECRET, "GET", path, b"")
            r = self.t.get(path, params=req.get("query"), headers=hdrs)
        else:
            channel = {"gateway": "phone", "bearer": "web"}.get(req.get("auth", "none"))
            r = self.t.post(path, body, channel=channel, token=self.token, raw=raw,
                            auth="normal" if channel else "none")
        self.r.turns += 1
        if r.status_code != want["status"]:
            self.r.fail(where, f"HTTP {r.status_code} != {want['status']}")
            return
        out = r.json() if r.content else None
        if want["status"] != 200:
            expected = want.get("body") or {}
            try:
                env = ErrorEnvelope.model_validate(out)
                if expected.get("error", {}).get("code") not in (None, env.error.code):
                    self.r.fail(where, f"error code {env.error.code} != {expected['error']['code']}")
            except ValidationError:
                self.r.fail(where, "error body is not an ErrorEnvelope")
            return
        if ex["step"] == "web_session":
            self.call_id, self.token = out["call_id"], out["token"]
            return
        if ex.get("id"):
            self.by_id[ex["id"]] = out
        if ex.get("same_as") and self.by_id.get(ex["same_as"]) != out:
            self.r.fail(where, f"reply differs from exchange {ex['same_as']}")
        if ex["step"] not in ("start", "turn"):
            return
        ms = server_ms(r.headers)
        if ms is not None and ex["step"] == "turn" and (body or {}).get("event") in ("utterance", "dtmf"):
            self.r.latencies_ms.append(ms)
        expected = want.get("body") or {}
        debug = out.get("debug")
        keys = debug.get("keys") if isinstance(debug, dict) else None
        if self.t.debug_keys and "keys" in ex and keys != ex["keys"]:
            self.r.fail(where, f"keys {keys} != expected {ex['keys']}")
        for name in ("end", "end_reason", "lang", "hold_s", "expect", "interruptible"):
            if name in expected and out.get(name) != expected[name]:
                self.r.fail(where, f"{name} {out.get(name)!r} != {expected[name]!r}")
        for name in ("ask", "card_url"):
            if name in expected and (out.get(name) is None) != (expected[name] is None):
                self.r.fail(where, f"{name} should be {'null' if expected[name] is None else 'present'}")
        for p in reply_problems(out, channel=self.sc["channel"], keys=keys if self.t.debug_keys else None,
                                budget=ex.get("budget"), is_start=ex["step"] == "start", guard=self.guard,
                                state=self.state):
            self.r.fail(where, p)
        self.r.budget_overruns = self.state.get("budget_overruns", 0)


# ============================================================================================ local servers

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_in_use(port: int) -> bool:
    """True when something listens on the port (a connection succeeds) or the port cannot be bound. The bind test
    sets SO_REUSEADDR, as the server does, so a port left in TIME_WAIT by a closed connection counts as free."""
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.3):
        return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def env_label(env: dict[str, str]) -> str:
    extra = [f"{k}={v}" for k, v in sorted(env.items()) if k != "GP_CARD_DELIVERY" and BASE_SERVER_ENV.get(k) != v]
    return ",".join([f"card={env['GP_CARD_DELIVERY']}", *extra])


def env_slug(env: dict[str, str]) -> str:
    return re.sub(r"[^a-z0-9]+", "-", env_label(env).lower()).strip("-")


def normalized_env(env: dict[str, str]) -> dict[str, str]:
    """The declared env with the server's base values filled in, so equal servers group together."""
    merged = dict(BASE_SERVER_ENV)
    merged.update(env)
    return merged


class LocalServer:
    """One uvicorn process with an explicit, clean environment; always stopped by `stop()`."""

    def __init__(self, *, app: str, port: int, env: dict[str, str], llm: str, db_dir: Path) -> None:
        self.app, self.port, self.declared, self.llm = app, port, env, llm
        self.db_dir = db_dir
        slug = env_slug(env)
        self.db_path = db_dir / f"e2e-{slug}.db"
        self.log_path = db_dir / f"e2e-{slug}.server.log"
        self.proc: subprocess.Popen | None = None
        self.health: dict | None = None
        self.stopped = False

    def child_env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
               if os.environ.get(k)}
        env.update(PYTHONUTF8="1", PYTHONPATH=str(REPO))
        env.update(BASE_SERVER_ENV)
        env.update(GP_LLM_PROVIDER=self.llm, GP_DB_PATH=str(self.db_path),
                   GP_PUBLIC_BASE_URL=f"http://127.0.0.1:{self.port}")
        # The key is passed through (never printed) only for a live run, and never to a group that declares its own
        # provider: such a script asks for exactly that setup (the anthropic provider without a key = closed mode).
        if self.llm == "anthropic" and os.environ.get("GP_LLM_API_KEY") and "GP_LLM_PROVIDER" not in self.declared:
            env["GP_LLM_API_KEY"] = os.environ["GP_LLM_API_KEY"]
        env.update(self.declared)
        return env

    def start(self, timeout_s: float = 30.0) -> None:
        if port_in_use(self.port):
            raise RuntimeError(f"port {self.port} is in use; nothing else may listen there during a local run")
        self.db_dir.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.db_path}{suffix}").unlink(missing_ok=True)
        cmd = [sys.executable, "-m", "uvicorn", self.app, "--host", "127.0.0.1", "--port", str(self.port),
               "--workers", "1", "--no-access-log"]
        log = self.log_path.open("wb")
        self.proc = subprocess.Popen(cmd, cwd=REPO, env=self.child_env(), stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        log.close()
        import httpx

        deadline = time.monotonic() + timeout_s
        with httpx.Client(base_url=self.base, timeout=2.0) as client:
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"server exited with status {self.proc.returncode} "
                                       f"(see {self.log_path.name} in the database folder)")
                try:
                    r = client.get("/v1/health")
                    if r.status_code == 200 and r.json() == {"ok": True}:
                        hz = client.get("/healthz")
                        self.health = hz.json() if hz.status_code == 200 else None
                        return
                except (httpx.HTTPError, ValueError):  # not up yet, or not JSON yet
                    pass
                time.sleep(0.2)
        raise RuntimeError(f"server did not answer /v1/health within {timeout_s:.0f} s")

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self) -> None:
        if self.proc is None or self.stopped:
            return
        if self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=5)
        self.stopped = True


# ============================================================================================ orchestration

@dataclass
class Item:
    id: str
    channel: str
    env: dict[str, str]
    script: Script | None = None
    scenario: dict | None = None
    skip: str | None = None  # a reason decided before any request


@dataclass
class Run:
    kind: str  # scripts | examples
    mode: str  # local | remote | in-process
    llm: str
    base: str | None = None
    groups: list[dict] = field(default_factory=list)
    results: list[ItemResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    @property
    def executed(self) -> list[ItemResult]:
        return [r for r in self.results if r.status != "skipped"]

    @property
    def ok(self) -> bool:
        return bool(self.executed) and all(r.status == "passed" for r in self.executed)


def build_items(kind: str, *, scripts_dir: list[Path] | None, examples_dir: Path | None, only: list[str] | None,
                live: bool) -> list[Item]:
    items: list[Item] = []
    if kind == "scripts":
        for _, script in load_scripts(scripts_dir or SCRIPTS_DIRS):
            item = Item(id=script.id, channel=script.channel, env=dict(script.env), script=script)
            if not script.fake_llm_ok and not live:
                item.skip = "needs a live language model (fake_llm_ok false)"
            items.append(item)
    else:
        for sc in load_scenarios(examples_dir or EXAMPLES_DIR):
            items.append(Item(id=sc["id"], channel=sc["channel"], env=scenario_env(sc), scenario=sc,
                              skip=scenario_skip_reason(sc)))
    if only:
        known = {i.id for i in items}
        unknown = [o for o in only if o not in known]
        if unknown:
            raise SystemExit(f"--only: no script or scenario with id {', '.join(unknown)}")
        items = [i for i in items if i.id in set(only)]
    return items


def run_items(items: list[Item], target: Target, run: Run, *, group: str, concurrency: int = 1) -> None:
    guard = OutputGuard()
    todo: list[Item] = []
    for item in items:
        if item.skip:
            run.results.append(_skipped(item, item.skip, group))
            continue
        needs_local = sorted(set(item.env) - REMOTE_CONFIRMABLE)
        if target.remote and item.script is not None and needs_local:
            run.results.append(_skipped(item, f"env: declares {', '.join(needs_local)} (local server only)", group))
            continue
        if item.channel == "phone":
            signed = item.script is not None or any(ex["request"].get("auth") == "gateway"
                                                    for ex in (item.scenario or {}).get("exchanges", []))
            if target.secret is None and signed:
                run.results.append(_skipped(item, "phone script needs the gateway secret (not set)", group))
                continue
            declares = item.script is not None or "GP_CARD_DELIVERY" in (item.scenario or {}).get("settings", {})
            if declares and target.card_delivery is None:
                # the mode cannot be confirmed, so a run could mix modes (docs/BRAIN_API.md §14, delivery modes)
                run.results.append(_skipped(item, "env: the server does not report card_delivery on /healthz",
                                            group))
                continue
            if declares and item.env["GP_CARD_DELIVERY"] != target.card_delivery:
                run.results.append(_skipped(item, f"env: declares GP_CARD_DELIVERY={item.env['GP_CARD_DELIVERY']}, "
                                                  f"server runs {target.card_delivery}", group))
                continue
        todo.append(item)

    def play(item: Item) -> ItemResult:
        if item.script is not None:
            return Player(item.script, target, guard, group=group).run()
        assert item.scenario is not None
        return Replayer(item.scenario, target, guard, group=group).run()

    if concurrency <= 1:
        for item in todo:
            run.results.append(play(item))
    else:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
        try:
            run.results.extend(pool.map(play, todo))
        except BaseException:  # an interrupt: queued calls are dropped, so the server can be stopped at once
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)


def _skipped(item: Item, reason: str, group: str) -> ItemResult:
    return ItemResult(id=item.id, kind="script" if item.script else "scenario", channel=item.channel,
                      lang=(item.script.lang if item.script else item.scenario["lang"]), group=group,
                      status="skipped", skip_reason=reason, keys_asserted=False, console_checked=False)


def run_local(items: list[Item], run: Run, *, app: str, port: int, llm: str, db_dir: Path, concurrency: int,
              startup_timeout: float = 30.0) -> None:
    """One server per declared environment, started and stopped in turn; never two card modes in one server."""
    import httpx

    groups: dict[tuple, list[Item]] = {}
    for item in items:
        groups.setdefault(tuple(sorted(normalized_env(item.env).items())), []).append(item)
    for key in sorted(groups, key=lambda k: env_label(dict(k))):
        env = dict(key)
        label = env_label(env)
        group_items = groups[key]
        info = {"label": label, "env": env, "items": [i.id for i in group_items], "server": None}
        run.groups.append(info)
        if all(i.skip for i in group_items):
            for item in group_items:
                run.results.append(_skipped(item, item.skip or "", label))
            info["server"] = {"started": False, "reason": "every item skipped"}
            continue
        server = LocalServer(app=app, port=port, env=env, llm=llm, db_dir=db_dir)
        try:
            server.start(timeout_s=startup_timeout)
            health = server.health or {}
            info["server"] = {"started": True, "port": port, "pid": server.pid,
                              "card_delivery": health.get("card_delivery"), "debug_keys": health.get("debug_keys"),
                              "db": server.db_path.name}
            # The group's mode must be confirmed, never assumed: a server that does not report it, or reports
            # another one, fails the group (never two card-delivery modes in one server run).
            if health.get("card_delivery") != env["GP_CARD_DELIVERY"]:
                raise RuntimeError(f"server reports card_delivery={health.get('card_delivery')!r} on /healthz, "
                                   f"group declares {env['GP_CARD_DELIVERY']}")
            with httpx.Client(base_url=server.base, timeout=30.0) as client:
                target = Target(client=client, base=server.base, secret=DEV_GATEWAY_SECRET,
                                passcode=DEV_CONSOLE_PASSCODE, debug_keys=bool(health.get("debug_keys")),
                                card_delivery=env["GP_CARD_DELIVERY"])
                run_items(group_items, target, run, group=label, concurrency=concurrency)
        except RuntimeError as exc:
            info["error"] = str(exc)
            run.notes.append(f"group {label}: {exc}")
            for item in group_items:
                if not any(r.id == item.id for r in run.results):
                    res = _skipped(item, "server did not start", label)
                    res.status = "failed"
                    res.failures.append(f"server: {exc}")
                    run.results.append(res)
        finally:
            server.stop()
            if info["server"] is not None:
                info["server"]["stopped"] = server.stopped
            else:
                info["server"] = {"started": False, "stopped": server.stopped}


def remote_target(base: str, client: Any, run: Run) -> Target:
    local = is_local_base(base)
    secret = os.environ.get("GP_GATEWAY_SECRET") or (DEV_GATEWAY_SECRET if local else None)
    passcode = os.environ.get("GP_CONSOLE_PASSCODE") or (DEV_CONSOLE_PASSCODE if local else None)
    r = client.get("/healthz")
    health = r.json() if r.status_code == 200 else {}
    debug_keys = bool(health.get("debug_keys"))
    target = Target(client=client, base=base, secret=secret, passcode=passcode, debug_keys=debug_keys,
                    card_delivery=health.get("card_delivery"), remote=True)
    run.groups.append({"label": "remote", "env": {"GP_CARD_DELIVERY": str(target.card_delivery)},
                       "items": [], "server": {"started": False, "card_delivery": target.card_delivery,
                                               "debug_keys": debug_keys}})
    if not debug_keys:
        run.notes.append("debug keys are off on this server: sentence keys are not asserted (everything else is)")
    if secret is None:
        run.notes.append("no gateway secret for a non-local base: phone scripts are skipped and counted")
    if passcode is None:
        run.notes.append("no console passcode for a non-local base: console checks are skipped and counted")
    return target


# ============================================================================================ report

def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(-(-q * len(ordered) // 1)) - 1))
    return ordered[k]


def summarize(run: Run) -> dict:
    lat = [ms for r in run.results for ms in r.latencies_ms]
    skipped = Counter(r.skip_reason.split(":")[0] if r.skip_reason else "" for r in run.results
                      if r.status == "skipped")
    return {
        "kind": run.kind, "mode": run.mode, "llm": run.llm, "base": run.base, "started_at": run.started_at,
        "groups": run.groups, "notes": run.notes,
        "counts": {"total": len(run.results), "executed": len(run.executed),
                   "passed": sum(r.status == "passed" for r in run.results),
                   "failed": sum(r.status == "failed" for r in run.results),
                   "skipped": dict(skipped),
                   "keys_not_asserted": sum(1 for r in run.executed if not r.keys_asserted and r.turns),
                   "console_checks_skipped": sum(1 for r in run.executed if not r.console_checked
                                                 and r.kind == "script" and r.turns)},
        "latency_ms": {"n": len(lat), "p50": percentile(lat, 0.5), "p95": percentile(lat, 0.95)},
        "items": [{"id": r.id, "kind": r.kind, "group": r.group, "channel": r.channel, "lang": r.lang,
                   "status": r.status, "skip_reason": r.skip_reason, "failures": r.failures, "turns": r.turns,
                   "keys_asserted": r.keys_asserted, "console_checked": r.console_checked,
                   "budget_overruns": r.budget_overruns,
                   "p50_ms": percentile(r.latencies_ms, 0.5)} for r in run.results],
        "ok": run.ok,
    }


def format_report(summary: dict) -> str:
    c = summary["counts"]
    title = "contract example replay" if summary["kind"] == "examples" else "scripts"
    mode = summary["mode"] + (f" {summary['base']}" if summary.get("base") else "")
    lines = [f"GatorPlate E2E — {title} ({mode}, {summary['llm']} language model)"]
    for g in summary["groups"]:
        srv = g.get("server") or {}
        if summary["mode"] == "local":
            state = (f"server on port {srv.get('port')} (card_delivery={srv.get('card_delivery')}, "
                     f"stopped={srv.get('stopped')})" if srv.get("started") else "no server started")
            lines.append(f"Group {g['label']}: {len(g['items'])} item(s), {state}")
            if g.get("error"):
                lines.append(f"  error: {g['error']}")
        else:
            lines.append(f"Server: card_delivery={srv.get('card_delivery')}, debug_keys={srv.get('debug_keys')}")
    for item in summary["items"]:
        tag = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[item["status"]]
        extra = f"  [{item['group']}]" if item["group"] else ""
        if item["status"] == "skipped":
            lines.append(f"  {tag} {item['id']}: {item['skip_reason']}{extra}")
            continue
        p50 = f", p50 {item['p50_ms']:.0f} ms" if item["p50_ms"] is not None else ""
        lines.append(f"  {tag} {item['id']} ({item['channel']}, {item['lang']}, {item['turns']} requests{p50}){extra}")
        for f in item["failures"][:12]:
            lines.append(f"       - {f}")
        if len(item["failures"]) > 12:
            lines.append(f"       - … {len(item['failures']) - 12} more")
    skipped = ", ".join(f"{n} ({reason})" for reason, n in sorted(c["skipped"].items())) or "none"
    lines.append(f"Summary: {c['executed']} executed — {c['passed']} passed, {c['failed']} failed; skipped: {skipped}")
    if c["keys_not_asserted"]:
        lines.append(f"Sentence keys not asserted (debug keys off) in {c['keys_not_asserted']} item(s)")
    if c["console_checks_skipped"]:
        lines.append(f"Console checks skipped in {c['console_checks_skipped']} script(s)")
    lat = summary["latency_ms"]
    if lat["n"]:
        lines.append(f"Server processing per turn (Server-Timing): n={lat['n']}, p50 {lat['p50']:.0f} ms, "
                     f"p95 {lat['p95']:.0f} ms")
    for note in summary["notes"]:
        lines.append(f"Note: {note}")
    if not c["executed"]:
        lines.append("Nothing was executed: this run proves nothing and exits non-zero.")
    lines.append("Result: " + ("OK" if summary["ok"] else "FAILED"))
    return "\n".join(lines)


def write_reports(summary: dict, report_json: Path | None) -> list[Path]:
    paths = []
    if report_json is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_json = REPO / "var" / "reports" / f"e2e-{summary['kind']}-{summary['mode']}-{stamp}.json"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md = report_json.with_suffix(".md")
    md.write_text("```text\n" + format_report(summary) + "\n```\n", encoding="utf-8")
    paths += [report_json, md]
    return paths


# ============================================================================================ CLI

_STOPPING = threading.Event()


def _on_stop_signal(signum: int, frame: Any) -> None:
    """SIGTERM, SIGHUP and SIGINT become one KeyboardInterrupt, so the `finally` that stops the local server runs
    (the server lives in its own session and would otherwise outlive the runner). Later signals are ignored while
    the server is being stopped."""
    if _STOPPING.is_set():
        return
    _STOPPING.set()
    raise KeyboardInterrupt(f"stopped by signal {signum}")


def install_stop_signals() -> None:
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):  # not the main thread (tests): leave the defaults
                signal.signal(sig, _on_stop_signal)


def main(argv: list[str] | None = None, *, client: Any = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = p.add_mutually_exclusive_group(required=True)
    what.add_argument("--scripts", action="append", type=Path, help="script folder (repeatable)")
    what.add_argument("--examples", type=Path, help="contract examples folder (replays the scenarios)")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--serve", action="store_true", help="local mode: one server per declared environment")
    where.add_argument("--base", help="remote mode: an existing server, no server started")
    p.add_argument("--port", type=int, default=8000, help="local mode server port (default 8000)")
    p.add_argument("--app", default=DEFAULT_APP, help="ASGI app for the local server (default gatorplate.main:app)")
    p.add_argument("--llm", choices=["fake", "anthropic"], default="fake", help="local mode language model provider")
    p.add_argument("--live", action="store_true", help="also run scripts with fake_llm_ok false")
    p.add_argument("--only", help="comma list of script or scenario ids")
    p.add_argument("--concurrency", type=int, default=1, help="calls at a time within one environment group")
    p.add_argument("--db-dir", type=Path, default=REPO / "var", help="local mode database folder (default var/)")
    p.add_argument("--report-json", type=Path, help="write the JSON report here (default var/reports/)")
    p.add_argument("--startup-timeout", type=float, default=30.0)
    args = p.parse_args(argv)

    kind = "examples" if args.examples else "scripts"
    only = [o.strip() for o in args.only.split(",") if o.strip()] if args.only else None
    try:
        items = build_items(kind, scripts_dir=args.scripts, examples_dir=args.examples, only=only, live=args.live)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValidationError, ValueError) as exc:
        print(f"invalid script: {str(exc)[:400]}", file=sys.stderr)
        return 2
    if args.concurrency < 1:
        print("--concurrency must be 1 or more", file=sys.stderr)
        return 2
    llm = args.llm if args.serve else "server's"
    run = Run(kind=kind, mode="local" if args.serve else "remote", llm=llm, base=args.base)
    install_stop_signals()
    interrupted = False
    try:
        if args.serve:
            run_local(items, run, app=args.app, port=args.port, llm=args.llm, db_dir=args.db_dir,
                      concurrency=args.concurrency, startup_timeout=args.startup_timeout)
        else:
            import httpx

            owned = client is None
            http = client or httpx.Client(base_url=args.base, timeout=30.0)
            try:
                target = remote_target(args.base, http, run)
                run.groups[0]["items"] = [i.id for i in items]
                run_items(items, target, run, group="", concurrency=args.concurrency)
            finally:
                if owned:
                    http.close()
    except KeyboardInterrupt:
        interrupted = True
        run.notes.append("interrupted: the run stopped early (every server it started was stopped)")
    summary = summarize(run)
    if interrupted:
        summary["ok"] = False
    print(format_report(summary))
    paths = write_reports(summary, args.report_json)
    print("Report: " + ", ".join(str(p.relative_to(REPO)) if p.is_relative_to(REPO) else p.name for p in paths))
    if interrupted:
        return 130
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

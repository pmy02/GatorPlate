#!/usr/bin/env python3
"""Check the GatorPlate Brain API v1 contract files.

Standard library only (Python 3.9+). Run from anywhere:

    python3 contracts/check_examples.py          # summary
    python3 contracts/check_examples.py -v       # one line per scenario

What it checks
  1. Schema: only the JSON Schema keywords implemented below are used, every
     $ref resolves, and x-auth / x-errors are complete.
  2. Every request and response body in contracts/examples/*.json validates
     against its $defs entry (routing comes from the schema's x-endpoints);
     error bodies match ErrorEnvelope and the status/retryable table.
  3. HMAC vectors: every signature and every check case is recomputed, and the
     explicit auth headers used in the examples give the documented result.
  4. Call rules: repeated seq returns the identical stored reply, an older seq
     gets 409 stale_seq, a repeated start returns the first reply, /start reply
     rules (consent question; on the phone every opening disclosure element),
     end rules, /end turns = student turns (utterance and dtmf, not silence),
     one key per phone dtmf event, web and phone extras, card_url stays once set.
  5. Phone text: no forbidden symbols ($ % / ~ en dash) and no digits in say or
     ask; word budgets for say + ask (opening 40, question 25, result 45), and
     the result budget only for a result line or a phone number; no rejection
     wording and no promises we never make, in any reply.
  6. Hygiene: no Hangul and no local absolute paths in the contract files,
     the examples or this checker.

Exit status: 0 when everything passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / "brain_api.v1.schema.json"
EXAMPLES_DIR = HERE / "examples"
DOC_FILE = HERE.parent / "docs" / "BRAIN_API.md"

# Canonical SHA-256 of examples/lines_en.json (sorted keys, compact, UTF-8).
# The gateway keeps identical built-in copies of these lines: change the file
# and this pin together, and only when the gateway wording itself changes.
LINES_EN_SHA256 = "ee48e240a904478ba7864c35d9ece199404adfaa94ed7743ca5ca522c1f114b8"

WORD_BUDGETS = {"opening": 40, "question": 25, "result": 45}
PHONE_FORBIDDEN = {"$", "%", "/", "~", "–"}           # from the contract
PHONE_ALSO_FORBIDDEN = set("0123456789@#&*+=<>|_\\[]{}`")  # numbers and symbols are spoken as words
CONTACT_WORDS = re.compile(r"\b(four one five|eight five five|eight seven seven|nine eight eight|nine one one)\b",
                           re.IGNORECASE)
REJECTION = ["not eligible", "ineligible", "don't qualify", "do not qualify", "denied",
             "no califica", "no calificas", "no eres elegible", "no es elegible"]
NEVER_PROMISE = ["text message", "send you a text", "text you", "call you back", "callback", "transfer you",
                 "connect you", "sent to the coordinator", "sent it to the coordinator", "remind you", "reminder",
                 "any language", "relay", "mensaje de texto", "te llamaremos", "te llamamos", "te transfiero",
                 "te comunico con", "enviado a", "lo envié", "recordatorio", "cualquier idioma",
                 # an eligibility decision is the county's, never ours
                 "you qualify", "you are eligible", "you're eligible", "approved", "eres elegible", "aprobad"]
HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff\uffa0-\uffdc]")  # Hangul Jamo, compatibility Jamo, extensions, syllables, half-width
LOCAL_PATH = re.compile(r"(/" + "Users" + r"/|/" + "home" + r"/[a-z]|[A-Z]:\\)")

# ------------------------------------------------------------------ frozen shared names
REASON_CODES = [
    "likely", "coordinator.parent_household", "coordinator.shared_household", "coordinator.grad_no_exemption",
    "coordinator.not_degree", "coordinator.age_outside_student_rule", "coordinator.gig_income",
    "coordinator.boarder", "coordinator.spouse_student", "coordinator.status_complex",
    "coordinator.elderly_disabled", "coordinator.unresolved", "other_help.status", "other_help.over_gross_limit",
    "other_help.dorm_meal_plan", "other_help.not_sfsu", "other_help.zero_benefit", "info.already_receiving",
    "info.interview_waiting",
]
SENTENCE_KEYS = set("""
consent.ask consent.reask consent.declined answer.is_ai answer.is_recorded language.offer_web
language.unsupported proxy.caller hold.ok abuse.warn abuse.end
ask.level_units ask.units ask.grad_exemption ask.age_parent ask.meal_plan ask.household
ask.household_food_roommates ask.income ask.other_cash ask.income_band ask.rent ask.homeless_cost
expedited.intro_cash flip.intro flip.rent_paid_by_others flip.rent_paid_by_others_amount flip.heat_cool
flip.other_utils flip.household_food flip.other_cash_band flip.earned_split
ack.short readback.earned readback.hourly readback.rent readback.other_cash readback.cash confirm.money
reprompt.silence_1 reprompt.silence_2 reprompt.unclear reprompt.after_interrupt
result.likely result.likely_floor result.note.abawd result.coordinator.generic result.other_help.generic
result.info.already_receiving result.info.interview_waiting expedited.yes expedited.maybe
first_month.apply_today card.phone_screen card.phone_code card.web close.anything_else close.goodbye
close.silence
crisis.resources crisis.continue_or_stop ssn.block card_number.block human.request stop.goodbye
delete.confirm_ask delete.done delete.cancelled apply_for_me immigration.question food_today
side_question.noted info.previously_denied error.generic
line.filler line.retry line.fatal line.fatal_start line.no_input_bye line.time_limit line.line_unavailable
""".split())
SENTENCE_KEYS |= {f"result.{code}" for code in REASON_CODES if code.split(".")[0] in ("coordinator", "other_help")}
# Keys that make a reply a "result" reply for the word budget: an outcome, the expedited outlook, the
# apply-today and card lines, or a line that carries a phone number (coordinator, county, crisis).
RESULT_KEY_PREFIXES = ("result.", "expedited.yes", "expedited.maybe", "first_month.", "card.", "close.anything_else",
                       "close.silence", "consent.declined", "crisis.resources", "human.request", "stop.goodbye",
                       "abuse.end", "error.generic")
# The phone opening (decision: /start reply) must say all of these; the consent question offers the keypad.
OPENING_SAY = [r"\bGatorPlate\b", r"\bAI\b", r"\bstudent-built\b", r"\bnot an official SF State service\b",
               r"\binto text\b", r"\bCalFresh\b", r"\baudio isn't recorded\b"]
OPENING_ASK = [r"\byes\b", r"\bpress one\b"]

# ------------------------------------------------------------------ JSON Schema subset (draft 2020-12)
ASSERTION_KEYWORDS = {
    "type", "enum", "const", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
    "minLength", "maxLength", "pattern", "minimum", "maximum", "allOf", "anyOf", "oneOf", "not", "if", "then",
    "else", "$ref", "format",
}
ANNOTATION_KEYWORDS = {"$schema", "$id", "$comment", "title", "description", "default", "examples", "$defs",
                       "deprecated", "readOnly", "writeOnly"}
DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")


class SchemaProblem(Exception):
    """The schema itself uses something this checker does not implement."""


def json_equal(a, b) -> bool:
    """Equality with JSON semantics (true is not 1; 1 equals 1.0)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def type_ok(value, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise SchemaProblem(f"unknown type {name!r}")


def ecma_pattern(pattern: str) -> str:
    """JSON Schema patterns are ECMA-262: a final '$' does not match before a trailing newline."""
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        return pattern[:-1] + r"\Z"
    return pattern


class Validator:
    def __init__(self, root: dict):
        self.root = root

    def resolve(self, ref: str) -> dict:
        if not ref.startswith("#/"):
            raise SchemaProblem(f"only local $ref is supported: {ref!r}")
        node = self.root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise SchemaProblem(f"$ref does not resolve: {ref!r}")
            node = node[part]
        return node

    def audit(self, schema, where: str = "#") -> int:
        """Reject keywords this checker does not implement; return the number of subschemas seen."""
        if isinstance(schema, bool):
            return 1
        if not isinstance(schema, dict):
            raise SchemaProblem(f"{where}: a schema must be an object or a boolean")
        seen = 1
        for key, value in schema.items():
            if key.startswith("x-"):
                continue
            if key not in ASSERTION_KEYWORDS and key not in ANNOTATION_KEYWORDS:
                raise SchemaProblem(f"{where}: unsupported keyword {key!r}")
            if key == "$ref":
                self.resolve(value)
            elif key in ("$defs", "properties"):
                for name, sub in value.items():
                    seen += self.audit(sub, f"{where}/{key}/{name}")
            elif key in ("items", "additionalProperties", "not", "if", "then", "else"):
                seen += self.audit(value, f"{where}/{key}")
            elif key in ("allOf", "anyOf", "oneOf"):
                for i, sub in enumerate(value):
                    seen += self.audit(sub, f"{where}/{key}/{i}")
            elif key == "type":
                for name in value if isinstance(value, list) else [value]:
                    type_ok(None, name)
            elif key == "format" and value != "date-time":
                raise SchemaProblem(f"{where}: unsupported format {value!r}")
        return seen

    def errors(self, value, schema, at: str = "$") -> list:
        if schema is True:
            return []
        if schema is False:
            return [f"{at}: no value is allowed here"]
        out = []
        if "$ref" in schema:
            out += self.errors(value, self.resolve(schema["$ref"]), at)
        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(type_ok(value, n) for n in names):
                return out + [f"{at}: expected {' or '.join(names)}, got {type(value).__name__} {value!r:.60}"]
        if "enum" in schema and not any(json_equal(value, e) for e in schema["enum"]):
            out.append(f"{at}: {value!r:.60} is not one of {schema['enum']}")
        if "const" in schema and not json_equal(value, schema["const"]):
            out.append(f"{at}: must be {schema['const']!r}, got {value!r:.60}")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append(f"{at}: shorter than {schema['minLength']} characters")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                out.append(f"{at}: longer than {schema['maxLength']} characters ({len(value)})")
            if "pattern" in schema and not re.search(ecma_pattern(schema["pattern"]), value):
                out.append(f"{at}: {value!r:.60} does not match {schema['pattern']}")
            if schema.get("format") == "date-time":
                if not DATE_TIME.fullmatch(value):
                    out.append(f"{at}: {value!r} is not an RFC 3339 date-time")
                else:
                    try:
                        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
                    except ValueError:
                        out.append(f"{at}: {value!r} is not a real date-time")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append(f"{at}: {value} is below the minimum {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                out.append(f"{at}: {value} is above the maximum {schema['maximum']}")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append(f"{at}: fewer than {schema['minItems']} items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                out.append(f"{at}: more than {schema['maxItems']} items")
            if "items" in schema:
                for i, item in enumerate(value):
                    out += self.errors(item, schema["items"], f"{at}[{i}]")
        if isinstance(value, dict):
            for name in schema.get("required", []):
                if name not in value:
                    out.append(f"{at}: missing required property {name!r}")
            props = schema.get("properties", {})
            for name, item in value.items():
                if name in props:
                    out += self.errors(item, props[name], f"{at}.{name}")
                elif "additionalProperties" in schema:
                    extra = schema["additionalProperties"]
                    if extra is False:
                        out.append(f"{at}: property {name!r} is not allowed")
                    elif isinstance(extra, dict):
                        out += self.errors(item, extra, f"{at}.{name}")
        for sub in schema.get("allOf", []):
            out += self.errors(value, sub, at)
        if "anyOf" in schema and not any(not self.errors(value, s, at) for s in schema["anyOf"]):
            out.append(f"{at}: matches none of anyOf")
        if "oneOf" in schema:
            hits = sum(1 for s in schema["oneOf"] if not self.errors(value, s, at))
            if hits != 1:
                out.append(f"{at}: matches {hits} of oneOf (exactly 1 required)")
        if "not" in schema and not self.errors(value, schema["not"], at):
            out.append(f"{at}: must not match the 'not' schema")
        if "if" in schema:
            if not self.errors(value, schema["if"], at):
                if "then" in schema:
                    out += self.errors(value, schema["then"], at)
            elif "else" in schema:
                out += self.errors(value, schema["else"], at)
        return out


# ------------------------------------------------------------------ helpers
def count_words(text: str) -> int:
    """A word is a whitespace-separated token with at least one letter or digit."""
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def phone_text_problems(text: str) -> list:
    problems = []
    for ch in sorted(set(text)):
        if ch in PHONE_FORBIDDEN:
            problems.append(f"forbidden symbol {ch!r}")
        elif ch in PHONE_ALSO_FORBIDDEN:
            problems.append(f"{ch!r} must be spoken as words")
    if re.search(r"https?:|www\.", text, re.IGNORECASE):
        problems.append("URLs must be spoken ('gatorplate dot fly dot dev slash go')")
    return problems


def wording_problems(text: str) -> list:
    low = text.lower().replace("’", "'")
    out = [f"rejection wording {p!r}" for p in REJECTION if p in low]
    out += [f"promise or claim we never make {p!r}" for p in NEVER_PROMISE if p in low]
    return out


def canonical_sha256(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def gateway_verify(secret: str, method: str, path: str, body: bytes, headers: dict, now: int, window: int) -> str:
    """The brain's check order: headers present, format, signature, then the time window."""
    h = {k.lower(): v for k, v in headers.items()}
    ts, sig = h.get("x-gp-timestamp"), h.get("x-gp-signature")
    if ts is None or sig is None:
        return "unauthorized"
    if not re.fullmatch(r"[0-9]+", ts) or not re.fullmatch(r"v1=[0-9a-f]{64}", sig):
        return "bad_signature"
    message = f"{ts}.{method.upper()}.{path}.{hashlib.sha256(body).hexdigest()}"
    expected = "v1=" + hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return "bad_signature"
    if abs(now - int(ts)) > window:
        return "stale_timestamp"
    return "ok"


class Report:
    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.problems = []
        self.counts = {"files": 0, "scenarios": 0, "exchanges": 0, "replies": 0, "vectors": 0, "checks": 0}

    def fail(self, where: str, message: str) -> None:
        self.problems.append(f"{where}: {message}")

    def info(self, message: str) -> None:
        if self.verbose:
            print(message)


# ------------------------------------------------------------------ the checker
class Checker:
    def __init__(self, report: Report):
        self.r = report
        self.schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
        self.v = Validator(self.schema)
        self.routes = []
        self.errors_table = self.schema.get("x-errors", {})
        self.auth = self.schema.get("x-auth", {})
        self.secret = None
        self.window = int(self.auth.get("gateway", {}).get("window_s", 0))

    # -- schema
    def check_schema(self) -> None:
        where = SCHEMA_FILE.name
        if self.schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            self.r.fail(where, "$schema must be draft 2020-12")
        try:
            seen = self.v.audit(self.schema)
            self.r.info(f"schema: {seen} subschemas, keywords supported")
        except SchemaProblem as exc:
            self.r.fail(where, str(exc))
            return
        defs = self.schema.get("$defs", {})
        for name in ["StartRequest", "TurnRequest", "EndRequest", "BrainReply", "GatewayLines", "WebSessionRequest",
                     "WebSessionResponse", "HealthResponse", "ErrorEnvelope"]:
            if name not in defs:
                self.r.fail(where, f"$defs.{name} is missing")
        for name in ["StartRequest", "TurnRequest", "EndRequest", "WebSessionRequest"]:
            if defs.get(name, {}).get("additionalProperties") is not True:
                self.r.fail(where, f"{name} must allow unknown properties (tolerant reader)")
        for name in ["BrainReply", "GatewayLines"]:
            d = defs.get(name, {})
            if d.get("additionalProperties") is not False:
                self.r.fail(where, f"{name} must set additionalProperties false")
            if sorted(d.get("required", [])) != sorted(d.get("properties", {})):
                self.r.fail(where, f"{name} must list every property as required")
        gw = self.auth.get("gateway", {})
        if gw.get("headers") != {"timestamp": "X-GP-Timestamp", "signature": "X-GP-Signature"}:
            self.r.fail(where, "x-auth.gateway.headers must name X-GP-Timestamp and X-GP-Signature")
        if gw.get("signing_string") != "{ts}.{METHOD}.{path}.{sha256_hex(body)}":
            self.r.fail(where, "x-auth.gateway.signing_string changed")
        if self.window != 120:
            self.r.fail(where, "x-auth.gateway.window_s must be 120")
        if self.auth.get("call_id_pattern") != defs.get("CallId", {}).get("pattern"):
            self.r.fail(where, "x-auth.call_id_pattern and $defs.CallId.pattern differ")
        codes = defs.get("ErrorCode", {}).get("enum", [])
        if sorted(codes) != sorted(self.errors_table):
            self.r.fail(where, "x-errors and $defs.ErrorCode list different codes")
        for ep in self.schema.get("x-endpoints", []):
            rx = "^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(ep["path"])) + "$"
            self.routes.append((ep["method"], re.compile(rx), ep))
            for key in ("request", "response"):
                if key in ep:
                    try:
                        self.v.resolve(ep[key])
                    except SchemaProblem as exc:
                        self.r.fail(where, f"x-endpoints {ep['path']}: {exc}")

    def route(self, method: str, path: str):
        for m, rx, ep in self.routes:
            match = rx.match(path)
            if m == method and match:
                return ep, match.groupdict()
        return None, {}

    def validate(self, value, ref: str, where: str) -> list:
        return self.v.errors(value, self.v.resolve(ref), "$")

    # -- lines
    def check_lines(self, path: Path) -> None:
        where = path.name
        lines = json.loads(path.read_text(encoding="utf-8"))
        for e in self.validate(lines, "#/$defs/GatewayLines", where):
            self.r.fail(where, e)
        if lines.get("lang") != "en":
            self.r.fail(where, "lang must be en")
        texts = list(lines.get("filler", [])) + [v for k, v in lines.items() if k not in ("lang", "filler")]
        for text in texts:
            for p in phone_text_problems(text) + wording_problems(text):
                self.r.fail(where, f"{p} in {text!r:.70}")
        digest = canonical_sha256(lines)
        if digest != LINES_EN_SHA256:
            self.r.fail(where, f"content changed: canonical sha256 {digest} does not match the pin in "
                               "check_examples.py (the gateway keeps identical copies)")
        self.r.info(f"{where}: GatewayLines ok, {len(texts)} spoken lines")

    # -- hmac
    def check_hmac(self, path: Path) -> None:
        where = path.name
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.secret = doc.get("secret")
        if doc.get("signing_string") != self.auth.get("gateway", {}).get("signing_string"):
            self.r.fail(where, "signing_string differs from the schema's x-auth")
        if doc.get("window_s") != self.window:
            self.r.fail(where, "window_s differs from the schema's x-auth")
        for vec in doc.get("vectors", []):
            name = f"{where}:{vec['name']}"
            body = vec["body"].encode("utf-8")
            digest = hashlib.sha256(body).hexdigest()
            message = f"{vec['timestamp']}.{vec['method']}.{vec['path']}.{digest}"
            signature = "v1=" + hmac.new(self.secret.encode("utf-8"), message.encode("utf-8"),
                                         hashlib.sha256).hexdigest()
            if vec.get("body_sha256") != digest:
                self.r.fail(name, "body_sha256 is wrong")
            if vec.get("signing_string") != message:
                self.r.fail(name, "signing_string is wrong")
            if vec.get("headers", {}).get("X-GP-Signature") != signature:
                self.r.fail(name, f"signature is wrong (expected {signature})")
            if vec.get("headers", {}).get("X-GP-Timestamp") != vec["timestamp"]:
                self.r.fail(name, "X-GP-Timestamp header differs from timestamp")
            result = gateway_verify(self.secret, vec["method"], vec["path"], body, vec.get("headers", {}),
                                    int(vec["timestamp"]), self.window)
            if result != "ok":
                self.r.fail(name, f"verification gives {result}")
            if "?" in vec["path"]:
                self.r.fail(name, "signed path must not contain a query string")
            self.r.counts["vectors"] += 1
        for case in doc.get("checks", []):
            name = f"{where}:check:{case['name']}"
            result = gateway_verify(self.secret, case["method"], case["path"], case["body"].encode("utf-8"),
                                    case.get("headers", {}), int(case["server_now"]), self.window)
            if result != case["expect"]:
                self.r.fail(name, f"expected {case['expect']}, verification gives {result}")
            self.r.counts["checks"] += 1
        self.r.info(f"{where}: {len(doc.get('vectors', []))} vectors, {len(doc.get('checks', []))} checks")

    # -- dialogue files
    def check_dialogue_file(self, path: Path) -> None:
        where = path.name
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("example") != path.stem:
            self.r.fail(where, "'example' must equal the file name")
        if doc.get("api") != "brain_api.v1":
            self.r.fail(where, "'api' must be brain_api.v1")
        if doc.get("illustrative_text") is not True:
            self.r.fail(where, "'illustrative_text' must be true")
        if not isinstance(doc.get("native_review"), bool):
            self.r.fail(where, "'native_review' must be true or false")
        scenarios = doc.get("scenarios") or []
        if not scenarios:
            self.r.fail(where, "no scenarios")
        seen_ids = set()
        has_spanish = False
        for sc in scenarios:
            if sc.get("id") in seen_ids:
                self.r.fail(where, f"duplicate scenario id {sc.get('id')!r}")
            seen_ids.add(sc.get("id"))
            has_spanish |= self.check_scenario(where, sc)
            self.r.counts["scenarios"] += 1
        if has_spanish and doc.get("native_review") is not True:
            self.r.fail(where, "Spanish student text present: native_review must be true")

    def check_scenario(self, file: str, sc: dict) -> bool:
        sid = sc.get("id", "?")
        channel, lang = sc.get("channel"), sc.get("lang")
        settings = sc.get("settings", {})
        given = sc.get("given")
        call_id = sc.get("call_id")
        if channel not in ("phone", "web") or lang not in ("en", "es"):
            self.r.fail(f"{file}:{sid}", "channel must be phone|web and lang en|es")
        if call_id is not None and not re.fullmatch(r"[a-f0-9]{32}", call_id):
            self.r.fail(f"{file}:{sid}", f"call_id {call_id!r} does not match ^[a-f0-9]{{32}}$")
        st = {
            "started": bool(given and given.get("started")),
            "last_seq": (given or {}).get("last_seq"),
            "replies": {},
            "start_reply": None,
            "brain_end": (given or {}).get("ended_by_brain"),
            "ended": False,
            "card_url": None,
            "accepted_seqs": set(),
            "student_turns": (given or {}).get("student_turns", 0),
            "turns_known": not given or "student_turns" in given,
            "token": None,
        }
        if given and "student_turns" in given:
            n, last = given["student_turns"], given.get("last_seq")
            if not isinstance(n, int) or isinstance(n, bool) or n < 0 or (isinstance(last, int) and n > last):
                self.r.fail(f"{file}:{sid}", "given.student_turns must be an integer from 0 to given.last_seq")
        ids = {}
        spanish = False
        for i, ex in enumerate(sc.get("exchanges", [])):
            label = f"{file}:{sid}#{i}:{ex.get('id', ex.get('step'))}"
            spanish |= self.check_exchange(label, sc, ex, st, ids, settings)
            self.r.counts["exchanges"] += 1
        final = sc.get("expect_final")
        if final and not given:
            if "student_turns" in final and final["student_turns"] != st["student_turns"]:
                self.r.fail(f"{file}:{sid}", f"expect_final.student_turns {final['student_turns']} but the "
                                             f"dialogue has {st['student_turns']}")
        self.r.info(f"{file}:{sid}: {len(sc.get('exchanges', []))} exchanges ok so far")
        return spanish or (lang == "es")

    def check_exchange(self, label: str, sc: dict, ex: dict, st: dict, ids: dict, settings: dict) -> bool:
        fail = lambda msg: self.r.fail(label, msg)  # noqa: E731
        req, resp = ex.get("request", {}), ex.get("response", {})
        method, path = req.get("method"), req.get("path", "")
        step = ex.get("step")
        ep, params = self.route(method, path)
        if ep is None:
            fail(f"no endpoint for {method} {path}")
            return False
        expected_step = {"/v1/health": "health", "/v1/lines": "lines", "/api/web/sessions": "web_session"}.get(
            ep["path"], ep["path"].rsplit("/", 1)[-1])
        if step != expected_step:
            fail(f"step {step!r} does not match {method} {ep['path']} (expected {expected_step!r})")
        if "?" in path:
            fail("put the query string in request.query, not in the path")
        # body and raw bytes
        if "body_raw" in req:
            raw = req["body_raw"].encode("utf-8")
            body = json.loads(req["body_raw"]) if req["body_raw"] else None
        else:
            body = req.get("body")
            raw = None
        # call id
        if "call_id" in params:
            if params["call_id"] != sc.get("call_id"):
                fail("path call_id differs from the scenario call_id")
        # auth
        auth = req.get("auth")
        headers = req.get("headers", {})
        expected_auth = ep.get("auth")
        if expected_auth == "none" and auth != "none":
            fail(f"{ep['path']} takes no auth")
        if expected_auth == "gateway" and auth != "gateway":
            fail(f"{ep['path']} needs gateway auth")
        if expected_auth == "gateway or bearer":
            want = "gateway" if sc["channel"] == "phone" else "bearer"
            if auth != want:
                fail(f"{sc['channel']} channel uses {want} auth")
        auth_result = None
        if auth == "bearer":
            value = headers.get("Authorization", "")
            if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{22,128}", value):
                fail("bearer requests need 'Authorization: Bearer <token>'")
            elif st["token"] and value.split(" ", 1)[1] != st["token"] and resp.get("status") == 200:
                fail("bearer token differs from the token issued by /api/web/sessions")
        if auth == "gateway" and headers:
            if self.secret is None or "server_now" not in sc:
                fail("explicit gateway headers need hmac_vectors.json and scenario server_now")
            else:
                auth_result = gateway_verify(self.secret, method, path, raw if raw is not None else b"",
                                             headers, int(sc["server_now"]), self.window)
        # request validation
        if "request" in ep:
            errs = self.validate(body, ep["request"], label)
            if req.get("valid") is False:
                if not errs:
                    fail("request marked invalid but it validates")
                if resp.get("body", {}).get("error", {}).get("code") != "invalid_request":
                    fail("an invalid request must get 422 invalid_request")
            else:
                for e in errs:
                    fail(f"request {e}")
            if isinstance(body, dict) and step in ("start", "turn") and body.get("lang") and sc["channel"] == "phone":
                if body.get("lang") != "en" and req.get("valid") is not False:
                    fail("phone requests always carry lang en")
            if isinstance(body, dict) and step == "turn" and body.get("event") == "dtmf" and req.get("valid") is not False:
                if sc["channel"] == "phone" and len(str(body.get("dtmf", ""))) != 1:
                    fail("the phone gateway sends exactly one key per dtmf event")
            if step == "start" and isinstance(body, dict) and resp.get("status") == 200:
                if body.get("channel") != sc["channel"]:
                    fail("start channel differs from the scenario channel")
        # response
        status = resp.get("status")
        if "body_ref" in resp:
            rbody = json.loads((EXAMPLES_DIR / resp["body_ref"]).read_text(encoding="utf-8"))
        else:
            rbody = resp.get("body")
        if status == 200:
            for e in self.validate(rbody, ep["response"], label):
                fail(f"response {e}")
        else:
            for e in self.validate(rbody, "#/$defs/ErrorEnvelope", label):
                fail(f"error body {e}")
            code = (rbody or {}).get("error", {}).get("code")
            row = self.errors_table.get(code)
            if row is None:
                fail(f"unknown error code {code!r}")
            else:
                if row["status"] != status:
                    fail(f"{code} must use HTTP {row['status']}, not {status}")
                if (rbody or {}).get("error", {}).get("retryable") != row["retryable"]:
                    fail(f"{code} must have retryable {row['retryable']}")
        if auth_result is not None:
            code = (rbody or {}).get("error", {}).get("code") if status != 200 else None
            if auth_result == "ok" and code in ("bad_signature", "stale_timestamp", "unauthorized"):
                fail(f"headers verify, but the response is {code}")
            if auth_result != "ok" and code != auth_result:
                fail(f"headers give {auth_result}, but the response is {code or status}")
        # identical repeats
        if "same_as" in ex:
            if ex["same_as"] not in ids:
                fail(f"same_as {ex['same_as']!r} is not an earlier exchange id")
            elif not json_equal(ids[ex["same_as"]], rbody):
                fail(f"reply must be identical to {ex['same_as']!r}")
        if "id" in ex:
            ids[ex["id"]] = rbody
        # step semantics
        if step == "web_session" and status == 200:
            st["token"] = rbody["token"]
            if sc.get("call_id") and rbody["call_id"] != sc["call_id"]:
                fail("web session call_id differs from the scenario call_id")
        spanish = False
        if step in ("start", "turn") and status == 200:
            spanish = self.check_call_semantics(label, sc, ex, body, rbody, st, settings)
        elif step in ("start", "turn"):
            self.check_call_error(label, ex, body, rbody, st)
        elif step == "end":
            self.check_end(label, sc, body, status, rbody, st)
        return spanish

    def check_call_error(self, label: str, ex: dict, body, rbody: dict, st: dict) -> None:
        fail = lambda msg: self.r.fail(label, msg)  # noqa: E731
        code = rbody.get("error", {}).get("code")
        seq = body.get("seq") if isinstance(body, dict) else None
        if code == "stale_seq":
            if not st["started"] or st["last_seq"] is None or not isinstance(seq, int) or seq >= st["last_seq"]:
                fail("stale_seq only for a seq lower than the last accepted seq")
        elif code == "unknown_call":
            if st["started"]:
                fail("unknown_call only for a call that was never started")
        elif code == "conflict":
            if not st["ended"]:
                fail("conflict is for turns after the call ended")
        elif code == "invalid_request":
            if ex["request"].get("valid") is not False:
                fail("invalid_request needs a request marked valid: false")

    def check_call_semantics(self, label: str, sc: dict, ex: dict, body: dict, rep: dict, st: dict,
                             settings: dict) -> bool:
        fail = lambda msg: self.r.fail(label, msg)  # noqa: E731
        step = ex["step"]
        self.r.counts["replies"] += 1
        if step == "start":
            if st["start_reply"] is not None and not json_equal(st["start_reply"], rep):
                fail("a repeated /start must return the stored first reply")
            if st["start_reply"] is None:
                st["start_reply"] = rep
            st["started"] = True
            if st["last_seq"] is None:
                st["last_seq"] = 0
            if not rep["say"].strip():
                fail("the /start reply needs the opening disclosure in say")
            if rep["end"] or rep["interruptible"] or rep["hold_s"]:
                fail("the /start reply has end false, interruptible false and hold_s 0")
            if not rep["ask"]:
                fail("the /start reply asks for consent in ask")
            if sc["channel"] == "phone":
                say, ask = rep["say"].replace("’", "'"), (rep["ask"] or "").replace("’", "'")
                for rx in OPENING_SAY:
                    if not re.search(rx, say, re.IGNORECASE):
                        fail(f"the phone opening must say {rx.strip(chr(92) + 'b')!r}")
                for rx in OPENING_ASK:
                    if not re.search(rx, ask, re.IGNORECASE):
                        fail(f"the phone consent question must offer {rx.strip(chr(92) + 'b')!r}")
        else:
            seq = body["seq"]
            if st["ended"]:
                fail("no 200 reply after /end: expected 409 conflict")
            if not st["started"]:
                fail("turn before start: expected 404 unknown_call")
            last = st["last_seq"]
            if last is not None and seq < last:
                fail("older seq: expected 409 stale_seq")
            elif last is not None and seq == last:
                stored = st["replies"].get(seq)
                if stored is None:
                    fail("repeated seq without a stored reply in this scenario")
                elif not json_equal(stored, rep):
                    fail("repeated seq must return the identical stored reply")
            else:
                if st["brain_end"]:
                    if not (rep["end"] and rep["say"] == "" and rep["end_reason"] == st["brain_end"]):
                        fail("after an end reply, a new turn gets say '' with end true and the same end_reason")
                st["replies"][seq] = rep
                st["last_seq"] = seq
                if seq not in st["accepted_seqs"]:
                    st["accepted_seqs"].add(seq)
                    if body.get("event") in ("utterance", "dtmf"):
                        st["student_turns"] += 1
            if rep["end"]:
                st["brain_end"] = rep["end_reason"]
        self.check_reply(label, sc, ex, rep, st, settings)
        return rep["lang"] == "es"

    def check_reply(self, label: str, sc: dict, ex: dict, rep: dict, st: dict, settings: dict) -> None:
        fail = lambda msg: self.r.fail(label, msg)  # noqa: E731
        keys = ex.get("keys")
        if keys is None:
            fail("every 200 reply lists its sentence keys in 'keys'")
            keys = []
        for key in keys:
            if key not in SENTENCE_KEYS:
                fail(f"unknown sentence key {key!r}")
        debug_on = settings.get("GP_DEBUG_KEYS") == "1"
        if rep["debug"] is not None:
            if not debug_on:
                fail("debug must be null unless GP_DEBUG_KEYS=1")
            elif rep["debug"].get("keys") != keys:
                fail("debug.keys must equal the exchange keys")
        elif debug_on:
            fail("GP_DEBUG_KEYS=1: debug must be filled")
        if rep["choices"] is not None and rep["ask"] is None:
            fail("choices only together with a question")
        if rep["ask"] is None and rep["expect"] != "open":
            fail("ask null means expect open")
        if rep["hold_s"] and "hold.ok" not in keys:
            fail("hold_s is only set with hold.ok")
        if rep["end"] and rep["interruptible"]:
            fail("end replies are not interruptible")
        spoken = " ".join(p for p in (rep["say"], rep["ask"]) if p)
        shown = rep["display"] or ""
        for p in wording_problems(spoken + " " + shown):
            fail(p)
        if any(k in ("result.likely", "result.likely_floor") for k in keys):
            hedge = "county" if rep["lang"] == "en" else "condado"
            if hedge not in rep["say"].lower():
                fail("an estimated amount needs the county-decides sentence in the same reply")
        heard_in_full = any(k in ("result.likely", "result.likely_floor", "card.phone_code", "crisis.resources")
                            for k in keys) or (sc["channel"] == "phone" and CONTACT_WORDS.search(rep["say"]))
        if heard_in_full and rep["interruptible"]:
            fail("a reply with an amount, a card code, a phone number or crisis resources is not interruptible")
        if sc["channel"] == "phone":
            for field in ("display", "choices", "card_url"):
                if rep[field] is not None:
                    fail(f"phone replies have {field} null")
            want_lang = "es" if "language.offer_web" in keys else "en"
            if rep["lang"] != want_lang:
                fail(f"phone reply lang must be {want_lang}")
            for p in phone_text_problems(spoken):
                fail(f"phone text: {p}")
            budget = ex.get("budget")
            if budget not in WORD_BUDGETS:
                fail("phone replies need budget opening|question|result")
            else:
                if (ex["step"] == "start") != (budget == "opening"):
                    fail("the opening budget is for the /start reply only")
                words = count_words(spoken)
                if words > WORD_BUDGETS[budget]:
                    fail(f"{words} words > {budget} budget {WORD_BUDGETS[budget]}: {spoken!r:.80}")
                if budget == "question" and CONTACT_WORDS.search(spoken):
                    fail("a reply that gives a phone number uses the result budget")
                if budget == "result" and not (any(k.startswith(RESULT_KEY_PREFIXES) for k in keys)
                                               or CONTACT_WORDS.search(spoken)):
                    fail("the result budget is only for a reply with a result line or a phone number")
        else:
            if not isinstance(rep["display"], str):
                fail("web replies always carry display")
            if st["card_url"] and rep["card_url"] != st["card_url"]:
                fail("card_url, once set, stays set")
            if rep["card_url"]:
                st["card_url"] = rep["card_url"]
            if rep["lang"] != sc["lang"]:
                fail("web reply lang differs from the conversation language")
            if "budget" in ex:
                fail("word budgets apply to phone replies only")

    def check_end(self, label: str, sc: dict, body: dict, status: int, rbody: dict, st: dict) -> None:
        fail = lambda msg: self.r.fail(label, msg)  # noqa: E731
        if status == 200:
            if not st["started"]:
                fail("/end for an unknown call: expected 404 unknown_call")
            if st["brain_end"] and body["reason"] != st["brain_end"]:
                fail(f"after end_reason {st['brain_end']!r} the end reason must be the same")
            if st["turns_known"] and "turns" in body and body["turns"] != st["student_turns"]:
                fail(f"turns {body['turns']} but {st['student_turns']} student turns (utterance or dtmf) were "
                     "sent; silence events are not counted")
            st["ended"] = True
        else:
            code = rbody.get("error", {}).get("code")
            if code == "unknown_call" and st["started"]:
                fail("unknown_call only for a call that was never started")

    # -- hygiene for public files
    def check_hygiene(self, paths) -> None:
        for path in paths:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if HANGUL.search(text):
                self.r.fail(path.name, "contains Hangul (public files are English or Spanish)")
            if LOCAL_PATH.search(text):
                self.r.fail(path.name, "contains a local absolute path")

    def run(self) -> None:
        self.check_schema()
        files = sorted(EXAMPLES_DIR.glob("*.json"))
        names = [f.name for f in files]
        for required in ["maria_phone.json", "sofia_web_es.json", "jamal_phone_expedited.json", "edge_cases.json",
                         "lines_en.json", "hmac_vectors.json"]:
            if required not in names:
                self.r.fail("examples", f"{required} is missing")
        order = sorted(files, key=lambda f: (f.name != "hmac_vectors.json", f.name != "lines_en.json", f.name))
        for f in order:
            self.r.counts["files"] += 1
            try:
                if f.name == "hmac_vectors.json":
                    self.check_hmac(f)
                elif f.name == "lines_en.json":
                    self.check_lines(f)
                else:
                    self.check_dialogue_file(f)
            except (KeyError, TypeError, ValueError, SchemaProblem) as exc:
                self.r.fail(f.name, f"could not be checked: {type(exc).__name__}: {exc}")
        self.check_hygiene([SCHEMA_FILE, DOC_FILE, Path(__file__).resolve(), *files])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="print one line per file and scenario")
    args = parser.parse_args(argv)
    report = Report(args.verbose)
    try:
        Checker(report).run()
    except SchemaProblem as exc:
        report.fail(SCHEMA_FILE.name, str(exc))
    c = report.counts
    if report.problems:
        print(f"FAIL: {len(report.problems)} problem(s)")
        for p in report.problems:
            print("  -", p)
        return 1
    print(f"OK: {c['files']} example files, {c['scenarios']} scenarios, {c['exchanges']} exchanges, "
          f"{c['replies']} replies, {c['vectors']} HMAC vectors, {c['checks']} HMAC checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

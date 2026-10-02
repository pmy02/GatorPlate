"""Text-level evaluation with simulated students (docs/SPEC.md §10).

Each persona in data/eval/personas.json talks to the Brain API through the web channel (Spanish personas) or through
both the web channel and the phone channel as signed calls (English personas); every simulated call is a team test
call (`"test": true`), never shown as a student's. A simulated student hangs up when it hits the turn cap or hears
the same question again and again; such calls are counted as not finished. The truth for a
persona is its facts run through the rules engine (the golden expected values); the engine golden cases must pass
100 % first, or the tool refuses to run.

Two modes:

* scripted (default, deterministic): the persona answers each question from its own paraphrases, keyed by the
  question's sentence key (the server must run with debug keys on, as local dev servers do);
* model-played (``--live``, only when the owner has approved and set ``GP_LLM_API_KEY``): a student model plays the
  persona from its `story` (plain words in the persona's language; the model never sees the engine's facts).
  ``--max-usd`` caps the run: a call is not started once the student model's measured spend plus the brain's (the
  change in the server's ``/healthz`` ``llm.usage`` since the run started), plus the measured cost of one more call,
  would pass the cap; prices are the published per-token prices passed with ``--price-in`` / ``--price-out`` (US
  dollars per million tokens).

Call order (``--order``): `coverage` (default) first plays every persona once on its first channel, languages
interleaved (the smaller language first), then the remaining channels — so a run stopped by the cap still covers
as many personas and both languages; `file` keeps the file order with each persona's channels together.

Metrics as docs/SPEC.md §10, overall and English vs Spanish, each with n; silent errors always as k/n with the Wilson
95 % upper bound. A wrong result counts as flagged (not silent) only when an open yellow line names the route or a
slot that made the result wrong, the call ended incomplete, or the truth lies inside the case's estimate range — an
unrelated open line does not count. The expedited truth is the engine's outlook wherever the call asked the cash
question and the persona's cash is known; "maybe" (the designed hedge) is reported on its own line.

Adjudication (``--adjudicate FILE``): a model-played student can depart from its persona. The file lists, per call,
the facts the student actually said; the report then also scores every metric against what was said, and counts the
departures. ``--rescore REPORT.json`` applies an adjudication file to a finished run's JSON report without making any
call (live runs are never repeated for it).

Outputs: the Markdown report (var/reports/eval-<time>.md by default, labeled "Text-level evaluation with simulated
students"), its JSON twin, and the conversation record `<report>.calls.jsonl` next to them: every call's exchanges
(the student's text, the replies with their sentence keys) and final case, each marked failed or not, so a failing
conversation can become a regression script. Replies, utterances and the card are never written to the Markdown or
JSON report; the record stays under var/ (never committed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import httpx  # noqa: E402

try:
    from tools import e2e_run as runner  # noqa: E402
except ImportError:  # pragma: no cover
    import e2e_run as runner  # type: ignore[no-redef]  # noqa: E402

LABEL = "Text-level evaluation with simulated students"
PERSONAS_FILE = REPO / "data" / "eval" / "personas.json"
GOLDEN_FILE = REPO / "data" / "golden" / "golden_cases.json"
DEFAULT_TODAY = date(2026, 10, 2)
MAX_TURNS = 24
STUCK_REPEATS = 4  # the same question asked this many more times in a row: the simulated student hangs up
AMOUNT_TOLERANCE_USD = 50  # docs/SPEC.md §10: an amount more than $50 off is wrong
ORDERS = ("coverage", "file")
FALLBACK = {
    "en": {"confirm.money": "Yes.", "consent.reask": "Yes.", "close.anything_else": "No, thanks.",
           "crisis.continue_or_stop": "Let's keep going.", "human.request": "Yes.", "delete.confirm_ask": "No.",
           "_": "I'm not sure."},
    "es": {"confirm.money": "Sí.", "consent.reask": "Sí.", "close.anything_else": "No, gracias.",
           "crisis.continue_or_stop": "Sigamos.", "human.request": "Sí.", "delete.confirm_ask": "No.",
           "_": "No estoy seguro."},
}
# The case slots that carry each engine fact (docs/SPEC.md §3.10). A yellow line names a fact when its slot (or the
# slot in its code, such as "unclear.rent_share") is one of these.
FACT_SLOTS: dict[str, tuple[str, ...]] = {
    "volunteered_status": ("volunteered_status",),
    "elderly_or_disabled": ("elderly_or_disabled",),
    "age": ("age",),
    "level": ("level",),
    "public_ca_degree_program": ("level",),
    "half_time": ("units", "half_time"),
    "units": ("units", "half_time"),
    "grad_exemption": ("grad_exemption",),
    "child_under14_in_hh": ("children_count", "youngest_child_age"),
    "under22_with_parent": ("lives_with_parent", "age"),
    "dorm_on_campus": ("dorm_on_campus",),
    "meals_per_week": ("meals_per_week", "dorm_meals_over_10"),
    "dorm_meals_over_10": ("dorm_meals_over_10", "meals_per_week"),
    "household_food": ("household_food", "roommates"),
    "household_size": ("spouse", "children_count", "roommates", "household_food"),
    "spouse_student": ("spouse_student", "spouse"),
    "boarder": ("boarder",),
    "homeless": ("homeless",),
    "homeless_shelter_cost": ("homeless_shelter_cost_monthly", "homeless"),
    "incomes": ("earned_monthly", "work_study_monthly", "gig_monthly", "unearned_monthly", "other_cash_monthly",
                "ta_ra"),
    "rent_share": ("rent_share",),
    "rent_paid_by_others_to_landlord": ("rent_paid_by_others_to_landlord",),
    "utility": ("heat_cool", "other_utils"),
    "dependent_care": ("dependent_care_monthly",),
    "cash_on_hand": ("cash_on_hand",),
    "income_changing_soon": ("income_changing_soon",),
    "works_80h_month": ("earned_monthly",),
    "receives_unemployment": ("unearned_monthly",),
}
SLOT_CODE_PREFIXES = ("unclear.", "conflict.", "assumed.")
INCOMPLETE_CODE = "incomplete"


# ============================================================================================ truth

def check_golden(rules: Any) -> list[str]:
    """Every engine golden case must pass before the evaluation runs."""
    from gatorplate.contracts.rules_io import Facts

    data = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    problems = []
    for case in data["cases"]:
        today = date.fromisoformat(case["today"]) if case.get("today") else DEFAULT_TODAY
        ev = rules.evaluate(Facts.model_validate(case["facts"]), today=today)
        exp = case["expected"]
        got = {"tier": _tier(ev.tier), "reason_code": ev.reason_code, "amount": ev.monthly}
        for key in ("tier", "reason_code", "amount"):
            if key in exp and exp[key] != got[key]:
                problems.append(f"{case['id']}: {key} {got[key]!r} != {exp[key]!r}")
        if "expedited" in exp and exp["expedited"] != ev.expedited:
            problems.append(f"{case['id']}: expedited {ev.expedited!r} != {exp['expedited']!r}")
    return problems


def _tier(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def persona_today(persona: dict) -> date:
    return date.fromisoformat(persona.get("today") or DEFAULT_TODAY.isoformat())


def persona_facts(persona: dict, overrides: dict | None = None) -> dict:
    facts = json.loads(json.dumps(persona["facts"]))
    facts.update(json.loads(json.dumps(overrides or {})))
    return facts


def truth_for(rules: Any, persona: dict, overrides: dict | None = None) -> dict:
    """The persona's facts (with any adjudicated overrides) through the rules engine.

    `expedited` is the outlook the call must reach on its own: the screen applies in the true world, so the cash
    question is due (docs/SPEC.md §5.5). `expedited_if_asked` is the engine's outlook once the cash question was asked
    and the persona's cash is known — the call may ask it because the screen applies in a world still open at that
    point (docs/SPEC.md §5.8), and then this is the truth for that call."""
    from gatorplate.contracts.rules_io import Facts

    ev = rules.evaluate(Facts.model_validate(persona_facts(persona, overrides)), today=persona_today(persona))
    screened = bool(getattr(ev, "expedited_screen", ev.expedited is not None))
    outlook = None if ev.expedited is None else ("yes" if ev.expedited else "no")
    return {"tier": _tier(ev.tier), "reason_code": ev.reason_code, "monthly": ev.monthly,
            "expedited": outlook if screened else None, "expedited_if_asked": outlook}


# ============================================================================================ students

class ScriptedStudent:
    """Answers each question from the persona's paraphrases (a list is used in order; its last item repeats)."""

    def __init__(self, persona: dict) -> None:
        self.p = persona
        self.lang = persona["lang"]
        self.used: dict[str, int] = defaultdict(int)
        self.cost_usd = 0.0

    def answer(self, key: str | None, reply: dict) -> str:
        answers = self.p["answers"]
        options = answers.get(key) if key else None
        if options is None and key and key.startswith("reprompt."):
            options = answers.get(self.p.get("_last_key") or "")
        if options is None:
            fb = FALLBACK[self.lang]
            return fb.get(key or "", fb["_"])
        if isinstance(options, str):
            options = [options]
        i = min(self.used[key], len(options) - 1)
        self.used[key] += 1
        self.p["_last_key"] = key
        return options[i]


STUDENT_RULES = (
    "You are role-playing a fictional SF State student in a text test of a CalFresh pre-screen assistant. Answer in "
    "{language}, in one or two short sentences, the way a student would say it out loud. Answer only what is asked, "
    "unless the story tells you to bring something up yourself. Everything you know about yourself is in the story "
    "below: never contradict it, and never add facts or numbers it does not give. Say every amount exactly as the "
    "story says it, with the same period (an hour, a week, every two weeks, a month); never convert an amount to "
    "another period and never add amounts together. If the assistant asks about something the story does not cover, "
    "say you are not sure. Story: ")


def student_system_prompt(persona: dict) -> str:
    """The model-played student's instructions: the persona's story in plain words, never the engine's facts (a
    facts object invites misreadings such as a biweekly amount turned into a monthly one)."""
    story = (persona.get("story") or "").strip()
    if not story:
        raise ValueError(f"{persona.get('id')}: no story for the model-played student")
    language = "Spanish" if persona["lang"] == "es" else "English"
    return STUDENT_RULES.format(language=language) + story


class ModelStudent:
    """A student model plays the persona from its story (live runs only; explicit key and base URL)."""

    def __init__(self, persona: dict, *, model: str, api_key: str, base_url: str, price_in: float,
                 price_out: float) -> None:
        import anthropic

        self.system = student_system_prompt(persona)
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url, max_retries=0)
        self.model, self.price_in, self.price_out = model, price_in, price_out
        self.lang = persona["lang"]
        self.messages: list[dict] = []
        self.cost_usd = 0.0

    def answer(self, key: str | None, reply: dict) -> str:
        said = " ".join(p for p in (reply.get("say"), reply.get("ask")) if p)
        self.messages.append({"role": "user", "content": said or "(the assistant is waiting)"})
        response = self.client.messages.create(model=self.model, max_tokens=200, system=self.system,
                                               messages=self.messages)
        usage = response.usage
        self.cost_usd += (usage.input_tokens * self.price_in + usage.output_tokens * self.price_out) / 1_000_000
        text = " ".join(b.text for b in response.content if b.type == "text").strip() or "Okay."
        self.messages.append({"role": "assistant", "content": text})
        return text[:1000]


# ============================================================================================ conversations

@dataclass
class Outcome:
    persona: str
    lang: str
    channel: str
    truth: dict
    case: dict | None = None
    latencies_ms: list[float] = field(default_factory=list)
    budget_overruns: int = 0
    guard_hits: int = 0
    error: str | None = None
    turns_sent: int = 0
    unfinished: bool = False  # the call hit the turn cap or kept asking the same question
    card_guard_hits: int = 0  # output-guard hits in the student's card (both languages)
    truth_facts: dict | None = None  # the persona's facts (the truth's input)
    heard_facts: dict | None = None  # the engine facts the brain built from the final case (what it understood)
    today: str = DEFAULT_TODAY.isoformat()
    said: dict | None = None  # adjudicated: {"overrides", "note", "facts", "truth"} — what the student actually said
    exchanges: list[dict] = field(default_factory=list)  # the conversation record only, never the report

    def to_row(self) -> dict:
        """Everything the metrics read, for the JSON report and --rescore (no utterance, reply or quote)."""
        return {"persona": self.persona, "lang": self.lang, "channel": self.channel, "truth": self.truth,
                "case": case_view(self.case), "latencies_ms": self.latencies_ms,
                "budget_overruns": self.budget_overruns, "guard_hits": self.guard_hits, "error": self.error,
                "turns_sent": self.turns_sent, "unfinished": self.unfinished, "card_guard_hits": self.card_guard_hits,
                "truth_facts": self.truth_facts, "heard_facts": self.heard_facts, "today": self.today}

    @classmethod
    def from_row(cls, row: dict) -> Outcome:
        names = ("persona", "lang", "channel", "truth", "case", "latencies_ms", "budget_overruns", "guard_hits",
                 "error", "turns_sent", "unfinished", "card_guard_hits", "truth_facts", "heard_facts", "today")
        return cls(**{name: row[name] for name in names if name in row})


def case_view(case: dict | None) -> dict | None:
    """The fields of a console case the metrics read; no student text."""
    if case is None:
        return None
    return {
        "tier": case.get("tier"), "reason_code": case.get("reason_code"),
        "estimate_monthly": case.get("estimate_monthly"), "estimate_is_floor": case.get("estimate_is_floor"),
        "estimate_range": case.get("estimate_range"), "expedited_possible": case.get("expedited_possible"),
        "turn_count": case.get("turn_count"), "flags": list(case.get("flags") or []), "live": case.get("live"),
        "ended_reason": case.get("ended_reason"),
        "yellow_lines": [{"code": y.get("code"), "slot": y.get("slot"), "kind": y.get("kind"),
                          "resolved": y.get("resolved")} for y in case.get("yellow_lines") or []],
        "asked": [{"key": a.get("key"), "kind": a.get("kind"), "slots": list(a.get("slots") or [])}
                  for a in case.get("asked") or []],
        "skipped": [{"slot": s.get("slot"), "reason": s.get("reason")} for s in case.get("skipped") or []],
    }


def question_key(keys: list[str] | None) -> str | None:
    for key in reversed(keys or []):
        if key.startswith(runner.QUESTION_PREFIXES):
            return key
    return None


def _reply_record(reply: dict) -> dict:
    """A reply for the conversation record (the card link and the debug block left out, the keys kept)."""
    keep = ("say", "ask", "end", "end_reason", "lang", "listen", "expect", "interruptible", "hold_s", "display",
            "choices")
    out = {k: reply.get(k) for k in keep}
    out["keys"] = (reply.get("debug") or {}).get("keys")
    return out


def converse(target: runner.Target, persona: dict, channel: str, student: Any, truth: dict) -> Outcome:
    out = Outcome(persona=persona["id"], lang=persona["lang"], channel=channel, truth=truth,
                  truth_facts=persona_facts(persona), today=persona_today(persona).isoformat())
    lang = persona["lang"]
    guard = runner.OutputGuard()
    state: dict = {}
    token = None
    call_id = uuid.uuid4().hex
    known: set[str] | None = None
    locked = False
    if target.console_ready():
        target.discovery_lock.acquire()
        locked = True
        known = target.case_ids()
    try:
        if channel == "web":
            r = target.post("/api/web/sessions", {"lang": lang}, auth="none")
            if r.status_code != 200:
                out.error = f"web session HTTP {r.status_code}"
                return out
            call_id, token = r.json()["call_id"], r.json()["token"]
        start = {"v": 1, "seq": 0, "channel": channel, "lang": lang, "test": True}
        r = target.post(f"/v1/calls/{call_id}/start", start, channel=channel, token=token)
        if r.status_code != 200:
            out.error = f"start HTTP {r.status_code}"
            out.exchanges.append({"seq": 0, "start": start, "status": r.status_code})
            return out
        reply = r.json()
        out.exchanges.append({"seq": 0, "start": start, "status": r.status_code, "reply": _reply_record(reply)})
        case_id = None
        if known is not None:
            new = target.case_ids() - known
            case_id = new.pop() if len(new) == 1 else None
            if case_id:
                target.discovery_lock.release()
                locked = False
        seq, silence_n = 0, 0
        same_question, last_question = 0, None
        while not reply.get("end"):
            keys = (reply.get("debug") or {}).get("keys")
            question = question_key(keys)
            same_question = same_question + 1 if question is not None and question == last_question else 0
            last_question = question
            if out.turns_sent >= MAX_TURNS or seq >= 2 * MAX_TURNS or same_question >= STUCK_REPEATS:
                out.unfinished = True  # the student hangs up: counted, not retried
                break
            if reply.get("ask") is None and not reply.get("hold_s"):
                silence_n += 1
                event = {"event": "silence", "silence_n": silence_n, "silence_ms": 3000 * silence_n}
            else:
                silence_n = 0
                text = student.answer(question_key(keys), reply)
                event = {"event": "utterance", "text": text, "masked": False, "confidence": 0.95,
                         "interrupted": False, "typed": channel == "web"}
                out.turns_sent += 1
            seq += 1
            r = target.post(f"/v1/calls/{call_id}/turn", {"v": 1, "seq": seq, "lang": lang, **event},
                            channel=channel, token=token)
            ms = runner.server_ms(r.headers)
            if r.status_code != 200:
                out.error = f"turn HTTP {r.status_code}"
                out.exchanges.append({"seq": seq, "event": event, "status": r.status_code})
                break
            if ms is not None and event["event"] == "utterance":
                out.latencies_ms.append(ms)
            reply = r.json()
            out.exchanges.append({"seq": seq, "event": event, "status": r.status_code, "reply": _reply_record(reply),
                                  "server_ms": ms})
            keys = (reply.get("debug") or {}).get("keys")
            problems = runner.reply_problems(reply, channel=channel, keys=keys, budget=None, is_start=False,
                                             guard=guard, state=state)
            out.guard_hits += sum(1 for p in problems if p.startswith("output guard"))
        out.budget_overruns = state.get("budget_overruns", 0)
        reason = reply.get("end_reason") or "caller_hangup" if reply.get("end") else "caller_hangup"
        end = {"v": 1, "reason": reason, "turns": out.turns_sent}
        r = target.post(f"/v1/calls/{call_id}/end", end, channel=channel, token=token)
        out.exchanges.append({"end": end, "status": r.status_code})
        if case_id is None and known is not None:
            new = target.case_ids() - known
            case_id = new.pop() if len(new) == 1 else None
        if case_id:
            status, detail = target.case_detail(case_id)
            out.case = (detail or {}).get("case")
            out.card_guard_hits = card_guard_hits(target, (detail or {}).get("card_url"), guard)
        elif target.passcode is not None:
            out.error = out.error or "no case found through the console"
    finally:
        if locked:
            target.discovery_lock.release()
    return out


def card_guard_hits(target: runner.Target, card_url: str | None, guard: runner.OutputGuard) -> int:
    """Output-guard hits over every string of the student's card, in English and Spanish (docs/SPEC.md §10:
    forbidden phrases in replies and cards). Only the hit count is kept."""
    if not card_url:
        return 0
    token = card_url.rstrip("/").split("/")[-1]
    hits = 0
    for lang in ("en", "es"):
        r = target.get(f"/api/card/{token}", params={"lang": lang})
        if r.status_code == 200:
            hits += sum(len(guard.hits(text)) for _, text in runner._stored_texts(r.json()))
    return hits


def heard_facts_of(rules: Any, case: dict | None, today: date) -> dict | None:
    """The engine facts the brain built from its final case (its default world), or None when the case cannot be
    read as a case contract (a stub) or the rules cannot build facts."""
    build = getattr(rules, "facts_from_case", None)
    if build is None or not case:
        return None
    from pydantic import ValidationError

    from gatorplate.contracts.case import Case

    try:
        facts = build(Case.model_validate(case), today=today)
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        return None
    return facts.model_dump(mode="json")


# ============================================================================================ scoring

def is_wrong(tier: Any, monthly: int | None, truth: dict) -> bool:
    """docs/SPEC.md §10: a wrong tier, or an amount more than $50 off."""
    if tier != truth["tier"]:
        return True
    want = truth["monthly"]
    return monthly is not None and want is not None and abs(monthly - want) > AMOUNT_TOLERANCE_USD


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a == b
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return a == b


def _evaluate(rules: Any, facts: dict, today: date) -> Any:
    from pydantic import ValidationError

    from gatorplate.contracts.rules_io import Facts

    try:
        return rules.evaluate(Facts.model_validate(facts), today=today)
    except (ValidationError, ValueError, TypeError):
        return None


def _income_key(facts: dict) -> list[tuple]:
    return sorted((str(Decimal(str(i["amount"]))), i["freq"], i["kind"], bool(i.get("excluded")))
                  for i in facts.get("incomes") or [])


def differing_facts(truth_facts: dict | None, heard_facts: dict | None, rules: Any = None,
                    today: date = DEFAULT_TODAY) -> list[str] | None:
    """The engine facts on which the brain's understanding differs from the truth (None: unknown). A fact the
    truth leaves open (null) is not compared; incomes are compared as the engine's monthly gross."""
    if truth_facts is None or heard_facts is None:
        return None
    out = []
    for name in FACT_SLOTS:
        want, got = truth_facts.get(name), heard_facts.get(name)
        if name == "volunteered_status":
            if bool(want or truth_facts.get("status_route")) != bool(got or heard_facts.get("status_route")):
                out.append(name)
            continue
        if want is None and not (name == "grad_exemption" and truth_facts.get("level") == "grad"):
            continue  # unknown in the truth (for a graduate student, a null exemption is the answer "none")
        if name == "incomes":
            a = _evaluate(rules, truth_facts, today) if rules is not None else None
            b = _evaluate(rules, heard_facts, today) if rules is not None else None
            gross_a, gross_b = getattr(a, "gross_monthly", None), getattr(b, "gross_monthly", None)
            differs = (not _same(gross_a, gross_b)) if gross_a is not None and gross_b is not None \
                else _income_key(truth_facts) != _income_key(heard_facts)
            if differs:
                out.append(name)
            continue
        if not _same(want, got):
            out.append(name)
    return out


def decisive_facts(rules: Any, truth: dict, truth_facts: dict, heard_facts: dict, differing: list[str],
                   today: date) -> list[str]:
    """The differing facts that made the result wrong: those whose true value alone fixes the result; if none does,
    those that move it; if none moves it either (or no rules engine), every differing fact."""
    if rules is None or not differing:
        return list(differing)

    def outcome(facts: dict) -> tuple | None:
        ev = _evaluate(rules, facts, today)
        return None if ev is None else (_tier(ev.tier), ev.monthly)

    base = outcome(heard_facts)
    fixes, moves = [], []
    for name in differing:
        changed = dict(heard_facts)
        changed[name] = truth_facts.get(name)
        if name == "volunteered_status":
            changed["status_route"] = truth_facts.get("status_route")
        got = outcome(changed)
        if got is None:
            continue
        if not is_wrong(got[0], got[1], truth):
            fixes.append(name)
        elif got != base:
            moves.append(name)
    return fixes or moves or list(differing)


def _line_slot(line: dict) -> str | None:
    if line.get("slot"):
        return line["slot"]
    code = line.get("code") or ""
    for prefix in SLOT_CODE_PREFIXES:
        if code.startswith(prefix):
            return code[len(prefix):]
    return None


def open_lines(case: dict) -> list[dict]:
    return [y for y in case.get("yellow_lines") or [] if not y.get("resolved")]


def flagged(case: dict, truth: dict, slots: set[str]) -> bool:
    """A wrong result is flagged for the coordinator when an open yellow line names the route (the case's or the
    true one) or one of `slots`, when the call ended incomplete, or when the truth lies inside the case's estimate
    range. Any other open line is unrelated to the error."""
    routes = {code for code in (truth.get("reason_code"), case.get("reason_code")) if code and code != "likely"}
    for line in open_lines(case):
        code = line.get("code") or ""
        if code == INCOMPLETE_CODE or code in routes or _line_slot(line) in slots:
            return True
    rng = case.get("estimate_range") or {}
    want = truth.get("monthly")
    return want is not None and rng.get("lo") is not None and rng.get("hi") is not None \
        and rng["lo"] <= want <= rng["hi"]


def asked_cash(case: dict) -> bool:
    return any(a.get("key") == "expedited.intro_cash" or "cash_on_hand" in (a.get("slots") or [])
               for a in case.get("asked") or [])


def expected_outlook(truth: dict, case: dict) -> str | None:
    """The expedited outlook the call should reach: the true world's outlook when its screen applies; otherwise the
    engine's outlook if the call asked the cash question (docs/SPEC.md §5.5, §5.8); otherwise none."""
    if truth.get("expedited") is not None:
        return truth["expedited"]
    if truth.get("expedited_if_asked") is not None and asked_cash(case):
        return truth["expedited_if_asked"]
    return None


def score(o: Outcome, *, against: str = "persona", rules: Any = None) -> dict:
    """One call against the persona's facts, or against what the student said (an adjudicated call)."""
    truth, facts = o.truth, o.truth_facts
    if against == "said" and o.said is not None:
        truth, facts = o.said["truth"], o.said["facts"]
    case = o.case or {}
    today = date.fromisoformat(o.today)
    wrong = is_wrong(case.get("tier"), case.get("estimate_monthly"), truth)
    differing = differing_facts(facts, o.heard_facts, rules, today)
    decisive = decisive_facts(rules, truth, facts or {}, o.heard_facts or {}, differing, today) \
        if wrong and differing else []
    slots = {s for name in decisive for s in FACT_SLOTS[name]}
    return {"wrong": wrong, "silent": wrong and not flagged(case, truth, slots),
            "silent_any_line": wrong and not open_lines(case), "differing": differing,
            "decisive_slots": sorted(slots), "expected_outlook": expected_outlook(truth, case)}


# ============================================================================================ metrics

def wilson_upper(k: int, n: int, z: float = 1.959964) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre + margin) / (1 + z * z / n)


def metrics(outcomes: list[Outcome], brain_cost_usd: float | None, *, against: str = "persona", rules: Any = None,
            personas_total: int | None = None) -> dict:
    done = [o for o in outcomes if o.case is not None]
    n = len(done)
    scores = {id(o): score(o, against=against, rules=rules) for o in done}

    def truth(o: Outcome) -> dict:
        return o.said["truth"] if against == "said" and o.said is not None else o.truth

    tier_ok = sum(1 for o in done if o.case.get("tier") == truth(o)["tier"])
    likely = [o for o in done if truth(o)["tier"] == "likely" and o.case.get("tier") == "likely"
              and truth(o)["monthly"] is not None and o.case.get("estimate_monthly") is not None]
    diffs = [abs(o.case["estimate_monthly"] - truth(o)["monthly"]) for o in likely]
    exact = sum(1 for d in diffs if d == 0)
    small = sum(1 for d in diffs if 0 < d <= AMOUNT_TOLERANCE_USD)

    def open_yellow(o: Outcome) -> int:
        return len(open_lines(o.case))

    silent = sum(1 for o in done if scores[id(o)]["silent"])
    silent_any = sum(1 for o in done if scores[id(o)]["silent_any_line"])
    exp_rows = [(o, scores[id(o)]["expected_outlook"]) for o in done
                if scores[id(o)]["expected_outlook"] is not None or o.case.get("expedited_possible") is not None]
    maybe = sum(1 for o, _ in exp_rows if o.case.get("expedited_possible") == "maybe")
    definite = [(o, want) for o, want in exp_rows if o.case.get("expedited_possible") != "maybe"]
    exp_ok = sum(1 for o, want in definite if o.case.get("expedited_possible") == want)
    lat = sorted(ms for o in outcomes for ms in o.latencies_ms)
    closed = sum(1 for o in done for a in o.case.get("asked") or [] if a.get("kind") == "closed")
    calls = len(outcomes)
    return {
        "n_calls": calls, "n_with_case": n,
        "personas_reached": [len({o.persona for o in outcomes}), personas_total if personas_total is not None
                             else len({o.persona for o in outcomes})],
        "student_departures": [sum(1 for o in done if o.said is not None and o.said.get("overrides")), n],
        "tier_agreement": [tier_ok, n],
        "amount_exact": [exact, len(diffs)],
        "amount_within_50_not_exact": [small, len(diffs)],
        "amount_mae": (sum(diffs) / len(diffs)) if diffs else None,
        "silent_errors": [silent, n],
        "silent_errors_wilson95_upper": wilson_upper(silent, n),
        "silent_errors_any_line": [silent_any, n],
        "expedited_agreement": [exp_ok, len(definite)],
        "expedited_maybe": [maybe, len(exp_rows)],
        "yellow_open_per_call": (sum(open_yellow(o) for o in done) / n) if n else None,
        "questions_per_call": (sum(len(o.case.get("asked") or []) for o in done) / n) if n else None,
        "student_turns_per_call": (sum(o.case.get("turn_count") or 0 for o in done) / n) if n else None,
        "server_ms": {"n": len(lat), "p50": runner.percentile(lat, 0.5), "p95": runner.percentile(lat, 0.95)},
        "closed_question_fallbacks": closed,
        "guard_hits": sum(o.guard_hits for o in outcomes)
        + sum(1 for o in done if "guard_hit" in (o.case.get("flags") or [])),
        "card_guard_hits": sum(o.card_guard_hits for o in outcomes),
        "unfinished_calls": [sum(1 for o in outcomes if o.unfinished), calls],
        "phone_budget_overruns": sum(o.budget_overruns for o in outcomes if o.channel == "phone"),
        "no_slot_comparison": sum(1 for o in done if o.heard_facts is None),
        "brain_llm_cost_per_call_usd": (brain_cost_usd / calls) if brain_cost_usd is not None and calls else None,
        "errors": [f"{o.persona}/{o.channel}: {o.error}" for o in outcomes if o.error],
    }


# ============================================================================================ adjudication

def load_adjudications(path: Path, personas: dict[str, dict]) -> list[dict]:
    """[{persona, channel (null = every channel), said: {Facts overrides}, note}] — what a model-played student
    actually said where it departed from its persona. Every override must be an engine fact and give valid facts."""
    from gatorplate.contracts.rules_io import Facts

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("adjudications") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("an adjudication file holds a list under 'adjudications'")
    fields = set(Facts.model_fields)
    out = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("said") or {}, dict):
            raise ValueError(f"adjudication {i}: an object with persona, channel, said and note")
        pid, said = entry.get("persona"), entry.get("said") or {}
        if pid not in personas:
            raise ValueError(f"adjudication {i}: unknown persona {pid!r}")
        if entry.get("channel") not in (None, "web", "phone"):
            raise ValueError(f"adjudication {i}: unknown channel {entry.get('channel')!r}")
        unknown = sorted(set(said) - fields)
        if unknown:
            raise ValueError(f"adjudication {i} ({pid}): not engine facts: {', '.join(unknown)}")
        Facts.model_validate(persona_facts(personas[pid], said))
        out.append({"persona": pid, "channel": entry.get("channel"), "said": said, "note": entry.get("note") or ""})
    return out


def apply_adjudications(outcomes: list[Outcome], adjudications: list[dict], personas: dict[str, dict],
                        rules: Any) -> int:
    """Sets `said` on every adjudicated call (the truth recomputed from what the student said); returns how many
    calls an entry matched."""
    matched = 0
    for o in outcomes:
        entry = next((a for a in adjudications if a["persona"] == o.persona and a["channel"] in (None, o.channel)),
                     None)
        if entry is None:
            o.said = None
            continue
        persona = dict(personas[o.persona], facts=o.truth_facts or personas[o.persona]["facts"])
        o.said = {"overrides": entry["said"], "note": entry["note"],
                  "facts": persona_facts(persona, entry["said"]),
                  "truth": truth_for(rules, persona, entry["said"])}
        matched += 1
    return matched


# ============================================================================================ planning

def plan_calls(personas: list[dict], channels: set[str], order: str = "coverage") -> list[tuple[dict, str]]:
    """(persona, channel) in playing order. `coverage`: every persona once on its first channel, languages
    interleaved with the smaller language first, then each persona's next channel the same way; `file`: file order,
    each persona's channels together."""
    def own(p: dict) -> list[str]:
        return [c for c in p.get("channels", ["web"]) if c in channels]

    if order == "file":
        return [(p, c) for p in personas for c in own(p)]
    if order != "coverage":
        raise ValueError(f"unknown order {order!r}")
    by_lang: dict[str, list[dict]] = {}
    for p in personas:
        by_lang.setdefault(p["lang"], []).append(p)
    queues = [list(by_lang[lang]) for lang in sorted(by_lang, key=lambda lang: (len(by_lang[lang]), lang))]
    interleaved: list[dict] = []
    while any(queues):
        for queue in queues:
            if queue:
                interleaved.append(queue.pop(0))
    rounds = max((len(own(p)) for p in personas), default=0)
    return [(p, own(p)[r]) for r in range(rounds) for p in interleaved if r < len(own(p))]


# ============================================================================================ report

def _frac(pair: list[int]) -> str:
    k, n = pair
    return f"{k}/{n}" + (f" ({100 * k / n:.0f} %)" if n else "")


def _silent(m: dict) -> str:
    k, n = m["silent_errors"]
    upper = m["silent_errors_wilson95_upper"]
    return f"{k}/{n}" + ("" if upper is None else f" (upper bound {100 * upper:.1f} %)")


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.4f}"


def markdown(report: dict) -> str:
    lines = [f"# {LABEL}", "",
             f"Run {report['started_at']} against {report['base']} — mode: {report['mode']}"
             f" ({'model-played students' if report['mode'] == 'live' else 'scripted paraphrases'}); "
             f"{report['personas']} personas, {report['calls']} calls"
             + (f" of {report['planned_calls']} planned" if report.get("planned_calls") is not None else "")
             + f" ({report.get('order', 'file')} order). Not real students, not speech recognition.",
             "",
             f"Brain language model: {report.get('brain_llm') or 'unknown'}."
             + (" With the fake model the brain replays the test-utterance table and falls back to its parser, so "
                "paraphrases outside that table measure the parser path, not real extraction."
                if report.get("brain_llm") == "fake" else ""),
             ""]
    if report.get("rescored_from"):
        lines += [f"Rescored from {report['rescored_from']} with {report.get('adjudicated_calls', 0)} adjudicated "
                  "call(s); no call was made again.", ""]
    if report.get("skipped"):
        lines += ["Not run: " + "; ".join(f"{n} {reason}" for reason, n in sorted(report["skipped"].items())) + ".",
                  ""]
    cost = report.get("cost_usd") or {}
    if report["mode"] == "live":
        lines += [f"Measured cost of this run: student model {_money(cost.get('student'))} + brain "
                  f"{_money(cost.get('brain'))} = {_money(cost.get('total'))} (cap ${report['max_usd']:.2f}).", ""]
    if report.get("stopped_by_cap"):
        per_call = cost.get("per_call")
        lines += [f"The run stopped at the spending cap (${report['max_usd']:.2f}); calls not made are not counted"
                  + (f" (measured {_money(per_call)} per call: the cap allows about "
                     f"{int(report['max_usd'] // per_call)} calls)" if per_call else "") + ".", ""]
    cols = [("all", "Overall"), ("en", "English"), ("es", "Spanish")]

    def table(source: dict, rows: list[tuple[str, Any]]) -> None:
        lines.extend(["| Metric | " + " | ".join(c[1] for c in cols) + " |", "|---|" + "---|" * len(cols)])
        for name, fn in rows:
            lines.append(f"| {name} | " + " | ".join(fn(source[c[0]]) for c in cols) + " |")

    table(report["metrics"], [
        ("Calls (with a case)", lambda m: f"{m['n_calls']} ({m['n_with_case']})"),
        ("Personas reached", lambda m: _frac(m["personas_reached"])),
        ("Tier agreement", lambda m: _frac(m["tier_agreement"])),
        ("Amount exact (likely cases)", lambda m: _frac(m["amount_exact"])),
        ("Amount off by $1–50", lambda m: _frac(m["amount_within_50_not_exact"])),
        ("Amount mean absolute error", lambda m: "—" if m["amount_mae"] is None else f"${m['amount_mae']:.2f}"),
        ("Silent errors (k/n, Wilson 95 % upper bound)", _silent),
        ("Silent errors if any open yellow line counted (docs/SPEC.md §10 wording)",
         lambda m: _frac(m["silent_errors_any_line"])),
        ("Expedited outlook agreement (yes/no)", lambda m: _frac(m["expedited_agreement"])),
        ("Expedited outlook \"maybe\"", lambda m: _frac(m["expedited_maybe"])),
        ("Open yellow lines per call", lambda m: "—" if m["yellow_open_per_call"] is None
         else f"{m['yellow_open_per_call']:.2f}"),
        ("Questions per call", lambda m: "—" if m["questions_per_call"] is None else f"{m['questions_per_call']:.1f}"),
        ("Student turns per call", lambda m: "—" if m["student_turns_per_call"] is None
         else f"{m['student_turns_per_call']:.1f}"),
        ("Server processing per turn p50 / p95 (n)", lambda m: "—" if not m["server_ms"]["n"]
         else f"{m['server_ms']['p50']:.0f} / {m['server_ms']['p95']:.0f} ms ({m['server_ms']['n']})"),
        ("Closed-question fallbacks", lambda m: str(m["closed_question_fallbacks"])),
        ("Output-guard hits (replies / cards)", lambda m: f"{m['guard_hits']} / {m['card_guard_hits']}"),
        ("Calls not finished (turn cap or the same question again and again)",
         lambda m: _frac(m["unfinished_calls"])),
        ("Phone word-budget overruns", lambda m: str(m["phone_budget_overruns"])),
        ("Measured brain LLM cost per call", lambda m: _money(m["brain_llm_cost_per_call_usd"])),
    ])
    if report.get("metrics_said"):
        lines += ["", "Against what the students said (adjudicated departures from the persona; the persona table "
                  "above counts a student model's own mistake as the brain's):", ""]
        table(report["metrics_said"], [
            ("Calls where the student departed from its persona", lambda m: _frac(m["student_departures"])),
            ("Tier agreement", lambda m: _frac(m["tier_agreement"])),
            ("Amount exact (likely cases)", lambda m: _frac(m["amount_exact"])),
            ("Amount mean absolute error", lambda m: "—" if m["amount_mae"] is None else f"${m['amount_mae']:.2f}"),
            ("Silent errors (k/n, Wilson 95 % upper bound)", _silent),
            ("Expedited outlook agreement (yes/no)", lambda m: _frac(m["expedited_agreement"])),
            ("Expedited outlook \"maybe\"", lambda m: _frac(m["expedited_maybe"])),
        ])
    lines += ["", "Silent error = wrong tier, or an amount more than $50 off, with no open yellow line that names the "
              "route or a slot that made the result wrong (a slot whose true value would fix or move the result), "
              "no \"incomplete\" line, and the truth outside the case's estimate range; an unrelated open line does "
              "not count (the row below it counts any open line). Truth = the persona's facts run through the rules "
              "engine (the golden expected values).",
              "Expedited agreement counts definite outlooks: the truth is the engine's outlook when the true world's "
              "screen applies, or when the call asked the cash question and the persona's cash is known; \"maybe\" "
              "is the designed hedge and is counted on its own line.",
              "Latency is the brain's own processing time per utterance turn (Server-Timing); the phone gateway's "
              "time is not included. Cost is the brain's measured LLM tokens at the published price; the phone part "
              "is gateway cost, separate."]
    if report["metrics"]["all"].get("no_slot_comparison"):
        lines += [f"The slot comparison was not available for {report['metrics']['all']['no_slot_comparison']} "
                  "call(s) (case not readable as the case contract): only the route, incomplete and range rules "
                  "applied to them."]
    failing = [c for c in report.get("per_call") or [] if c.get("failed")]
    if failing:
        lines += ["", "Calls that differ from the truth (details in the JSON report and the conversation record):"]
        for c in failing:
            t = c["truth"]
            got = f"{c.get('tier')}" + (f" ${c['estimate_monthly']}" if c.get("estimate_monthly") is not None else "")
            want = f"{t['tier']}" + (f" ${t['monthly']}" if t.get("monthly") is not None else "")
            notes = []
            if c.get("wrong"):
                notes.append("silent" if c.get("silent") else "flagged")
                if c.get("decisive_slots"):
                    notes.append("wrong slot: " + ", ".join(c["decisive_slots"]))
            if c.get("expected_outlook") is not None and c.get("expedited") != c["expected_outlook"]:
                notes.append(f"expedited {c.get('expedited')} vs {c['expected_outlook']}")
            if c.get("unfinished"):
                notes.append("not finished")
            if c.get("said"):
                notes.append("student departed from the persona (adjudicated)"
                             + ("; right against what was said" if not c["said"].get("wrong") else ""))
            lines.append(f"- {c['persona']}/{c['channel']}: {got} vs truth {want}"
                         + (f" — {'; '.join(notes)}" if notes else ""))
    errors = report["metrics"]["all"]["errors"]
    if errors:
        lines += ["", "Calls with a transport or console problem:", *[f"- {e}" for e in errors]]
    return "\n".join(lines) + "\n"


def per_call_rows(outcomes: list[Outcome], rules: Any) -> list[dict]:
    rows = []
    for o in outcomes:
        case = o.case or {}
        sc = score(o, rules=rules) if o.case is not None else None
        row = {"persona": o.persona, "lang": o.lang, "channel": o.channel, "truth": o.truth,
               "tier": case.get("tier"), "reason_code": case.get("reason_code"),
               "estimate_monthly": case.get("estimate_monthly"), "expedited": case.get("expedited_possible"),
               "unfinished": o.unfinished, "error": o.error}
        if sc is not None:
            row.update(wrong=sc["wrong"], silent=sc["silent"], decisive_slots=sc["decisive_slots"],
                       expected_outlook=sc["expected_outlook"], persona_vs_heard=sc["differing"],
                       open_yellow=[y.get("code") for y in open_lines(case)])
        if o.said is not None:
            said = score(o, against="said", rules=rules) if o.case is not None else {}
            row["said"] = {"overrides": o.said["overrides"], "note": o.said["note"], "truth": o.said["truth"],
                           "wrong": said.get("wrong"), "silent": said.get("silent"),
                           "decisive_slots": said.get("decisive_slots")}
        exp_off = sc is not None and sc["expected_outlook"] is not None \
            and case.get("expedited_possible") not in (sc["expected_outlook"], "maybe")
        row["failed"] = bool(o.unfinished or o.error or o.case is None or (sc and sc["wrong"]) or exp_off)
        row["outcome"] = o.to_row()
        rows.append(row)
    return rows


def write_record(path: Path, outcomes: list[Outcome], rows: list[dict]) -> None:
    """The conversation record: every call's exchanges and final case (the card reference left out), marked failed
    or not, so a failing conversation can become a regression script. var/ only; never committed."""
    with path.open("w", encoding="utf-8") as fh:
        for o, row in zip(outcomes, rows, strict=True):
            case = {k: v for k, v in (o.case or {}).items() if k != "card"} if o.case is not None else None
            fh.write(json.dumps({"persona": o.persona, "lang": o.lang, "channel": o.channel, "failed": row["failed"],
                                 "truth": o.truth, "said": row.get("said"), "decisive_slots": row.get("decisive_slots"),
                                 "persona_vs_heard": row.get("persona_vs_heard"), "unfinished": o.unfinished,
                                 "error": o.error, "exchanges": o.exchanges, "case": case,
                                 "heard_facts": o.heard_facts}, ensure_ascii=False) + "\n")


def build_report(meta: dict, outcomes: list[Outcome], rules: Any, personas: list[dict],
                 brain_cost: float | None) -> dict:
    groups = {"all": outcomes, "en": [o for o in outcomes if o.lang == "en"],
              "es": [o for o in outcomes if o.lang == "es"]}
    totals = {"all": len(personas), "en": sum(1 for p in personas if p["lang"] == "en"),
              "es": sum(1 for p in personas if p["lang"] == "es")}
    n_all = len(outcomes) or 1

    def share(group: list[Outcome]) -> float | None:
        return None if brain_cost is None else brain_cost * len(group) / n_all

    report = dict(meta)
    report.update({
        "label": LABEL, "personas": len(personas), "calls": len(outcomes),
        "metrics": {name: metrics(group, share(group), rules=rules, personas_total=totals[name])
                    for name, group in groups.items()},
        "per_call": per_call_rows(outcomes, rules),
    })
    if any(o.said is not None for o in outcomes):
        report["metrics_said"] = {name: metrics(group, share(group), against="said", rules=rules,
                                                personas_total=totals[name])
                                  for name, group in groups.items()}
        report["adjudicated_calls"] = sum(1 for o in outcomes if o.said is not None)
    return report


def write_report(report: dict, md_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown(report), encoding="utf-8")
    md_path.with_suffix(".json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(markdown(report))
    print(f"Report: {_shown(md_path)}")


def _shown(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else path.name


# ============================================================================================ main

def llm_usage(client: Any) -> dict | None:
    r = client.get("/healthz")
    if r.status_code != 200:
        return None
    return ((r.json().get("llm") or {}).get("usage")) or None


def main(argv: list[str] | None = None, *, client: Any = None, rules: Any = None) -> int:
    p = argparse.ArgumentParser(description=LABEL)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--personas", type=Path, default=PERSONAS_FILE)
    p.add_argument("--live", action="store_true", help="model-played students (owner-approved runs only)")
    p.add_argument("--max-usd", type=float, default=3.0, help="spending cap for a live run (student + brain)")
    p.add_argument("--price-in", type=float, default=1.00, help="US$ per million input tokens (published price)")
    p.add_argument("--price-out", type=float, default=5.00, help="US$ per million output tokens (published price)")
    p.add_argument("--only", help="comma list of persona ids")
    p.add_argument("--channels", default="web,phone", help="channels to run (English personas use both)")
    p.add_argument("--order", choices=ORDERS, default="coverage",
                   help="coverage (default): every persona once first, languages interleaved; file: file order")
    p.add_argument("--adjudicate", type=Path, help="JSON list of what model-played students actually said")
    p.add_argument("--rescore", type=Path, help="a finished run's JSON report: apply --adjudicate, make no call")
    p.add_argument("--report", type=Path, help="Markdown report path (default var/reports/eval-<time>.md)")
    args = p.parse_args(argv)

    if rules is None:
        from gatorplate.config import Settings
        from gatorplate.rules import Rules

        rules = Rules.from_settings(Settings())
    try:
        problems = check_golden(rules)
    except NotImplementedError:
        print("refusing to run: the rules engine is not built yet", file=sys.stderr)
        return 2
    if problems:
        print(f"refusing to run: {len(problems)} engine golden case(s) fail, e.g. {problems[0]}", file=sys.stderr)
        return 2

    data = json.loads(args.personas.read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in data["personas"]}
    personas = data["personas"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        unknown = sorted(wanted - set(by_id))
        if unknown:
            print(f"unknown persona id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        personas = [q for q in personas if q["id"] in wanted]
    adjudications: list[dict] = []
    if args.adjudicate:
        try:
            adjudications = load_adjudications(args.adjudicate, by_id)
        except ValueError as exc:
            print(f"refusing to run: {exc}", file=sys.stderr)
            return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if args.rescore:
        return rescore(args, rules, by_id, adjudications, stamp)

    channels = {c.strip() for c in args.channels.split(",")}
    owned = client is None
    http = client or httpx.Client(base_url=args.base, timeout=30.0)
    run = runner.Run(kind="eval", mode="remote", llm="live" if args.live else "scripted", base=args.base)
    skipped: dict[str, int] = defaultdict(int)
    plan = plan_calls(personas, channels, args.order)
    try:
        target = runner.remote_target(args.base, http, run)
        if not target.debug_keys and not args.live:
            print("the scripted mode needs a server with debug keys on (local dev servers have them)", file=sys.stderr)
            return 2
        if not target.console_ready():
            print("refusing to run: every metric reads the case through the console API, which this run cannot "
                  "reach (GP_CONSOLE_PASSCODE for a non-local server)", file=sys.stderr)
            return 2
        settings = None
        if args.live:
            from gatorplate.config import Settings

            settings = Settings()  # GP_* only: the student model gets its key and base URL from here, explicitly
            if not settings.llm_api_key.get_secret_value():
                print("--live needs GP_LLM_API_KEY in the environment (owner-approved runs only)", file=sys.stderr)
                return 2
            missing = sorted({q["id"] for q, _ in plan if not (q.get("story") or "").strip()})
            if missing:
                print(f"refusing to run: no story for the model-played student: {', '.join(missing)}",
                      file=sys.stderr)
                return 2
        hz = http.get("/healthz")
        brain_llm = ((hz.json().get("llm") or {}).get("provider")) if hz.status_code == 200 else None
        usage0 = llm_usage(http)
        outcomes: list[Outcome] = []
        truths: dict[str, dict] = {}
        student_cost = 0.0
        stopped = False
        for persona, channel in plan:
            if channel == "phone" and target.secret is None:
                skipped["phone calls (no gateway secret for a non-local server)"] += 1
                continue
            if args.live:
                spent = student_cost + (_cost(usage0, llm_usage(http), args.price_in, args.price_out) or 0.0)
                next_call = spent / len(outcomes) if outcomes else 0.0
                if spent >= args.max_usd or spent + next_call > args.max_usd:
                    stopped = True
                    break
                assert settings is not None
                student: Any = ModelStudent(dict(persona), model=settings.llm_model,
                                            api_key=settings.llm_api_key.get_secret_value(),
                                            base_url=settings.llm_base_url, price_in=args.price_in,
                                            price_out=args.price_out)
            else:
                student = ScriptedStudent(json.loads(json.dumps(persona)))
            if persona["id"] not in truths:
                truths[persona["id"]] = truth_for(rules, persona)
            out = converse(target, persona, channel, student, truths[persona["id"]])
            out.heard_facts = heard_facts_of(rules, out.case, persona_today(persona))
            outcomes.append(out)
            student_cost += getattr(student, "cost_usd", 0.0)
        brain_cost = _cost(usage0, llm_usage(http), args.price_in, args.price_out)
    finally:
        if owned:
            http.close()

    apply_adjudications(outcomes, adjudications, by_id, rules)
    total = (student_cost if args.live else 0.0) + (brain_cost or 0.0)
    meta = {"started_at": run.started_at, "base": args.base, "mode": "live" if args.live else "scripted",
            "order": args.order, "persona_ids": [q["id"] for q in personas], "planned_calls": len(plan),
            "stopped_by_cap": stopped, "max_usd": args.max_usd,
            "brain_llm": brain_llm, "skipped": dict(skipped),
            "student_cost_usd": student_cost if args.live else 0.0,
            "cost_usd": {"student": student_cost if args.live else 0.0, "brain": brain_cost, "total": total,
                         "per_call": (total / len(outcomes)) if outcomes else None}}
    report = build_report(meta, outcomes, rules, personas, brain_cost)
    md_path = args.report or REPO / "var" / "reports" / f"eval-{stamp}.md"
    write_report(report, md_path)
    record = md_path.with_suffix(".calls.jsonl")
    write_record(record, outcomes, report["per_call"])
    print(f"Conversation record: {_shown(record)}")
    return 0 if outcomes else 1


def rescore(args: argparse.Namespace, rules: Any, by_id: dict[str, dict], adjudications: list[dict],
            stamp: str) -> int:
    """Re-reads a finished run's JSON report, applies the adjudications and writes a new report; no call is made."""
    old = json.loads(args.rescore.read_text(encoding="utf-8"))
    rows = old.get("per_call") or []
    if not rows or any("outcome" not in row for row in rows):
        print("refusing to rescore: the report holds no per-call outcomes (made by an older version of this tool)",
              file=sys.stderr)
        return 2
    outcomes = [Outcome.from_row(row["outcome"]) for row in rows]
    unknown = sorted({o.persona for o in outcomes} - set(by_id))
    if unknown:
        print(f"refusing to rescore: personas not in {args.personas.name}: {', '.join(unknown)}", file=sys.stderr)
        return 2
    matched = apply_adjudications(outcomes, adjudications, by_id, rules)
    keep = ("started_at", "base", "mode", "order", "persona_ids", "planned_calls", "stopped_by_cap", "max_usd",
            "brain_llm", "skipped", "student_cost_usd", "cost_usd")
    meta = {k: old.get(k) for k in keep}
    meta["rescored_from"] = args.rescore.name
    selected = [pid for pid in old.get("persona_ids") or [] if pid in by_id] \
        or list(dict.fromkeys(o.persona for o in outcomes))
    brain_cost = (old.get("cost_usd") or {}).get("brain")
    report = build_report(meta, outcomes, rules, [by_id[pid] for pid in selected], brain_cost)
    report["adjudicated_calls"] = matched
    md_path = args.report or REPO / "var" / "reports" / f"eval-{stamp}-rescored.md"
    write_report(report, md_path)
    return 0


# Prompt-cache prices relative to the input price: reads 0.1x, writes 2x (the one-hour lifetime the brain asks for;
# tools/bench_llm.py uses the same rates). /healthz counts both inside input_tokens and also on their own.
CACHE_READ_RATE = 0.1
CACHE_WRITE_RATE = 2.0


def _cost(before: dict | None, after: dict | None, price_in: float, price_out: float) -> float | None:
    if before is None or after is None:
        return None

    def delta(key: str) -> int:
        return max(0, int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0))

    tin, tout = delta("input_tokens"), delta("output_tokens")
    read, write = delta("cache_read_input_tokens"), delta("cache_creation_input_tokens")
    plain = max(0, tin - read - write)
    return ((plain + read * CACHE_READ_RATE + write * CACHE_WRITE_RATE) * price_in + tout * price_out) / 1_000_000


if __name__ == "__main__":
    sys.exit(main())

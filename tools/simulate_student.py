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
  persona from its facts. ``--max-usd`` caps the run: it stops when the student model's measured spend plus the
  brain's (the change in the server's ``/healthz`` ``llm.usage`` since the run started) reaches the cap, at the
  published per-token price passed with ``--price-in`` / ``--price-out`` (US dollars per million tokens).

Metrics exactly as docs/SPEC.md §10, overall and English vs Spanish, each with n; silent errors always as k/n with
the Wilson 95 % upper bound. The Markdown report goes to var/reports/ and is labeled "Text-level evaluation with
simulated students". Replies, utterances and the card are never written to the report.
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
FALLBACK = {
    "en": {"confirm.money": "Yes.", "consent.reask": "Yes.", "close.anything_else": "No, thanks.",
           "crisis.continue_or_stop": "Let's keep going.", "human.request": "Yes.", "delete.confirm_ask": "No.",
           "_": "I'm not sure."},
    "es": {"confirm.money": "Sí.", "consent.reask": "Sí.", "close.anything_else": "No, gracias.",
           "crisis.continue_or_stop": "Sigamos.", "human.request": "Sí.", "delete.confirm_ask": "No.",
           "_": "No estoy seguro."},
}


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
        got = {"tier": ev.tier.value if hasattr(ev.tier, "value") else ev.tier, "reason_code": ev.reason_code,
               "amount": ev.monthly}
        for key in ("tier", "reason_code", "amount"):
            if key in exp and exp[key] != got[key]:
                problems.append(f"{case['id']}: {key} {got[key]!r} != {exp[key]!r}")
        if "expedited" in exp and exp["expedited"] != ev.expedited:
            problems.append(f"{case['id']}: expedited {ev.expedited!r} != {exp['expedited']!r}")
    return problems


def truth_for(rules: Any, persona: dict) -> dict:
    from gatorplate.contracts.rules_io import Facts

    today = date.fromisoformat(persona.get("today", DEFAULT_TODAY.isoformat()))
    ev = rules.evaluate(Facts.model_validate(persona["facts"]), today=today)
    tier = ev.tier.value if hasattr(ev.tier, "value") else ev.tier
    # The call asks the cash question only when the expedited screen applies (docs/SPEC.md §5.5); otherwise the case
    # has no outlook, and the truth has none either.
    screened = bool(getattr(ev, "expedited_screen", ev.expedited is not None))
    outlook = None if ev.expedited is None or not screened else ("yes" if ev.expedited else "no")
    return {"tier": tier, "reason_code": ev.reason_code, "monthly": ev.monthly, "expedited": outlook}


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


class ModelStudent:
    """A student model plays the persona from its facts (live runs only; explicit key and base URL)."""

    def __init__(self, persona: dict, *, model: str, api_key: str, base_url: str, price_in: float,
                 price_out: float) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url, max_retries=0)
        self.model, self.price_in, self.price_out = model, price_in, price_out
        self.lang = persona["lang"]
        language = "Spanish" if self.lang == "es" else "English"
        self.system = (
            "You are role-playing a fictional SF State student in a text test of a CalFresh pre-screen assistant. "
            f"Answer in {language}, in one or two short sentences, as a student would say it out loud. Answer only "
            "what is asked; use only the facts below and never invent other numbers; if asked something the facts "
            "do not cover, say you are not sure. Facts: " + json.dumps(persona["facts"], ensure_ascii=False)
            + (" Notes: " + persona["notes"] if persona.get("notes") else ""))
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


def question_key(keys: list[str] | None) -> str | None:
    for key in reversed(keys or []):
        if key.startswith(runner.QUESTION_PREFIXES):
            return key
    return None


def converse(target: runner.Target, persona: dict, channel: str, student: Any, truth: dict) -> Outcome:
    out = Outcome(persona=persona["id"], lang=persona["lang"], channel=channel, truth=truth)
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
        r = target.post(f"/v1/calls/{call_id}/start", {"v": 1, "seq": 0, "channel": channel, "lang": lang,
                                                        "test": True}, channel=channel, token=token)
        if r.status_code != 200:
            out.error = f"start HTTP {r.status_code}"
            return out
        reply = r.json()
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
            if r.status_code != 200:
                out.error = f"turn HTTP {r.status_code}"
                break
            ms = runner.server_ms(r.headers)
            if ms is not None and event["event"] == "utterance":
                out.latencies_ms.append(ms)
            reply = r.json()
            keys = (reply.get("debug") or {}).get("keys")
            problems = runner.reply_problems(reply, channel=channel, keys=keys, budget=None, is_start=False,
                                             guard=guard, state=state)
            out.guard_hits += sum(1 for p in problems if p.startswith("output guard"))
        out.budget_overruns = state.get("budget_overruns", 0)
        reason = reply.get("end_reason") or "caller_hangup" if reply.get("end") else "caller_hangup"
        target.post(f"/v1/calls/{call_id}/end", {"v": 1, "reason": reason, "turns": out.turns_sent},
                    channel=channel, token=token)
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


# ============================================================================================ metrics

def wilson_upper(k: int, n: int, z: float = 1.959964) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre + margin) / (1 + z * z / n)


def metrics(outcomes: list[Outcome], brain_cost_usd: float | None) -> dict:
    done = [o for o in outcomes if o.case is not None]
    n = len(done)
    tier_ok = sum(1 for o in done if o.case.get("tier") == o.truth["tier"])
    likely = [o for o in done if o.truth["tier"] == "likely" and o.case.get("tier") == "likely"
              and o.truth["monthly"] is not None and o.case.get("estimate_monthly") is not None]
    diffs = [abs(o.case["estimate_monthly"] - o.truth["monthly"]) for o in likely]
    exact = sum(1 for d in diffs if d == 0)
    small = sum(1 for d in diffs if 0 < d <= 50)

    def open_yellow(o: Outcome) -> int:
        return sum(1 for y in o.case.get("yellow_lines") or [] if not y.get("resolved"))

    def wrong(o: Outcome) -> bool:
        if o.case.get("tier") != o.truth["tier"]:
            return True
        got, want = o.case.get("estimate_monthly"), o.truth["monthly"]
        return got is not None and want is not None and abs(got - want) > 50

    silent = sum(1 for o in done if wrong(o) and open_yellow(o) == 0)
    exp_n = [o for o in done if o.truth["expedited"] is not None or o.case.get("expedited_possible") is not None]
    exp_ok = sum(1 for o in exp_n if o.case.get("expedited_possible") == o.truth["expedited"])
    lat = sorted(ms for o in outcomes for ms in o.latencies_ms)
    closed = sum(1 for o in done for a in o.case.get("asked") or [] if a.get("kind") == "closed")
    calls = len(outcomes)
    upper = wilson_upper(silent, n)
    return {
        "n_calls": calls, "n_with_case": n,
        "tier_agreement": [tier_ok, n],
        "amount_exact": [exact, len(diffs)],
        "amount_within_50_not_exact": [small, len(diffs)],
        "amount_mae": (sum(diffs) / len(diffs)) if diffs else None,
        "silent_errors": [silent, n],
        "silent_errors_wilson95_upper": upper,
        "expedited_agreement": [exp_ok, len(exp_n)],
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
        "brain_llm_cost_per_call_usd": (brain_cost_usd / calls) if brain_cost_usd is not None and calls else None,
        "errors": [f"{o.persona}/{o.channel}: {o.error}" for o in outcomes if o.error],
    }


def _frac(pair: list[int]) -> str:
    k, n = pair
    return f"{k}/{n}" + (f" ({100 * k / n:.0f} %)" if n else "")


def markdown(report: dict) -> str:
    lines = [f"# {LABEL}", "",
             f"Run {report['started_at']} against {report['base']} — mode: {report['mode']}"
             f" ({'model-played students' if report['mode'] == 'live' else 'scripted paraphrases'}); "
             f"{report['personas']} personas, {report['calls']} calls. Not real students, not speech recognition.",
             "",
             f"Brain language model: {report.get('brain_llm') or 'unknown'}."
             + (" With the fake model the brain replays the test-utterance table and falls back to its parser, so "
                "paraphrases outside that table measure the parser path, not real extraction."
                if report.get("brain_llm") == "fake" else ""),
             ""]
    if report.get("skipped"):
        lines += ["Not run: " + "; ".join(f"{n} {reason}" for reason, n in sorted(report["skipped"].items())) + ".",
                  ""]
    if report.get("stopped_by_cap"):
        lines += [f"The run stopped at the spending cap (${report['max_usd']:.2f}); calls not made are not counted.",
                  ""]
    cols = [("all", "Overall"), ("en", "English"), ("es", "Spanish")]
    lines += ["| Metric | " + " | ".join(c[1] for c in cols) + " |", "|---|" + "---|" * len(cols)]

    def row(name: str, fn) -> None:
        lines.append(f"| {name} | " + " | ".join(fn(report["metrics"][c[0]]) for c in cols) + " |")

    row("Calls (with a case)", lambda m: f"{m['n_calls']} ({m['n_with_case']})")
    row("Tier agreement", lambda m: _frac(m["tier_agreement"]))
    row("Amount exact (likely cases)", lambda m: _frac(m["amount_exact"]))
    row("Amount off by $1–50", lambda m: _frac(m["amount_within_50_not_exact"]))
    row("Amount mean absolute error", lambda m: "—" if m["amount_mae"] is None else f"${m['amount_mae']:.2f}")
    def silent(m: dict) -> str:
        k, n = m["silent_errors"]
        upper = m["silent_errors_wilson95_upper"]
        return f"{k}/{n}" + ("" if upper is None else f" (upper bound {100 * upper:.1f} %)")

    row("Silent errors (k/n, Wilson 95 % upper bound)", silent)
    row("Expedited outlook agreement", lambda m: _frac(m["expedited_agreement"]))
    row("Open yellow lines per call", lambda m: "—" if m["yellow_open_per_call"] is None
        else f"{m['yellow_open_per_call']:.2f}")
    row("Questions per call", lambda m: "—" if m["questions_per_call"] is None else f"{m['questions_per_call']:.1f}")
    row("Student turns per call", lambda m: "—" if m["student_turns_per_call"] is None
        else f"{m['student_turns_per_call']:.1f}")
    row("Server processing per turn p50 / p95 (n)", lambda m: "—" if not m["server_ms"]["n"]
        else f"{m['server_ms']['p50']:.0f} / {m['server_ms']['p95']:.0f} ms ({m['server_ms']['n']})")
    row("Closed-question fallbacks", lambda m: str(m["closed_question_fallbacks"]))
    row("Output-guard hits (replies / cards)", lambda m: f"{m['guard_hits']} / {m['card_guard_hits']}")
    row("Calls not finished (turn cap or the same question again and again)",
        lambda m: _frac(m["unfinished_calls"]))
    row("Phone word-budget overruns", lambda m: str(m["phone_budget_overruns"]))
    row("Measured brain LLM cost per call", lambda m: "—" if m["brain_llm_cost_per_call_usd"] is None
        else f"${m['brain_llm_cost_per_call_usd']:.4f}")
    lines += ["", "Silent error = wrong tier, or an amount more than $50 off, with no open yellow line on the case. "
              "Truth = the persona's facts run through the rules engine (the golden expected values).",
              "Latency is the brain's own processing time per utterance turn (Server-Timing); the phone gateway's "
              "time is not included. Cost is the brain's measured LLM tokens at the published price; the phone part "
              "is gateway cost, separate."]
    errors = report["metrics"]["all"]["errors"]
    if errors:
        lines += ["", "Calls with a transport or console problem:", *[f"- {e}" for e in errors]]
    return "\n".join(lines) + "\n"


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
    personas = data["personas"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        personas = [q for q in personas if q["id"] in wanted]
    channels = {c.strip() for c in args.channels.split(",")}

    owned = client is None
    http = client or httpx.Client(base_url=args.base, timeout=30.0)
    run = runner.Run(kind="eval", mode="remote", llm="live" if args.live else "scripted", base=args.base)
    skipped: dict[str, int] = defaultdict(int)
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
        hz = http.get("/healthz")
        brain_llm = ((hz.json().get("llm") or {}).get("provider")) if hz.status_code == 200 else None
        usage0 = llm_usage(http)
        outcomes: list[Outcome] = []
        student_cost = 0.0
        stopped = False
        for persona in personas:
            truth = truth_for(rules, persona)
            for channel in persona.get("channels", ["web"]):
                if channel not in channels:
                    continue
                if channel == "phone" and target.secret is None:
                    skipped["phone calls (no gateway secret for a non-local server)"] += 1
                    continue
                if args.live:
                    usage = llm_usage(http)
                    brain = _cost(usage0, usage, args.price_in, args.price_out) or 0.0
                    if student_cost + brain >= args.max_usd:
                        stopped = True
                        break
                    assert settings is not None
                    student: Any = ModelStudent(dict(persona), model=settings.llm_model,
                                                api_key=settings.llm_api_key.get_secret_value(),
                                                base_url=settings.llm_base_url, price_in=args.price_in,
                                                price_out=args.price_out)
                else:
                    student = ScriptedStudent(json.loads(json.dumps(persona)))
                outcomes.append(converse(target, persona, channel, student, truth))
                student_cost += getattr(student, "cost_usd", 0.0)
            if stopped:
                break
        brain_cost = _cost(usage0, llm_usage(http), args.price_in, args.price_out)
    finally:
        if owned:
            http.close()

    groups = {"all": outcomes, "en": [o for o in outcomes if o.lang == "en"],
              "es": [o for o in outcomes if o.lang == "es"]}
    n_all = len(outcomes) or 1
    report = {
        "label": LABEL, "started_at": run.started_at, "base": args.base, "mode": "live" if args.live else "scripted",
        "personas": len(personas), "calls": len(outcomes), "stopped_by_cap": stopped, "max_usd": args.max_usd,
        "brain_llm": brain_llm, "skipped": dict(skipped),
        "student_cost_usd": student_cost if args.live else 0.0,
        "metrics": {name: metrics(group, None if brain_cost is None else brain_cost * len(group) / n_all)
                    for name, group in groups.items()},
        "per_call": [{"persona": o.persona, "lang": o.lang, "channel": o.channel, "truth": o.truth,
                      "tier": (o.case or {}).get("tier"), "estimate_monthly": (o.case or {}).get("estimate_monthly"),
                      "expedited": (o.case or {}).get("expedited_possible"), "unfinished": o.unfinished,
                      "error": o.error}
                     for o in outcomes],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    md_path = args.report or REPO / "var" / "reports" / f"eval-{stamp}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown(report), encoding="utf-8")
    md_path.with_suffix(".json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(markdown(report))
    print(f"Report: {md_path.relative_to(REPO) if md_path.is_relative_to(REPO) else md_path.name}")
    return 0 if outcomes else 1


def _cost(before: dict | None, after: dict | None, price_in: float, price_out: float) -> float | None:
    if before is None or after is None:
        return None
    tin = max(0, after.get("input_tokens", 0) - before.get("input_tokens", 0))
    tout = max(0, after.get("output_tokens", 0) - before.get("output_tokens", 0))
    return (tin * price_in + tout * price_out) / 1_000_000


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check GatorPlate's content files. Standard library only.

    python3 data/content/check_content.py        # exit 0 = all checks pass, 1 = problems
    python3 data/content/check_content.py -v     # also print word counts and reading levels

Files checked (all in this folder): sentences.en.json, sentences.es.json, card.en.json,
card.es.json, guards.json, contacts.json, programs.en.json, programs.es.json.

Also read when present: ../tests/utterances.jsonl (redaction and keyword vectors),
../../contracts/examples/lines_en.json (gateway lines) and ../rules/programs_2026.json (the
programs table that names the card-side keys).

What it checks
  1. Sentence banks: the frozen key list (the sentence keys of docs/SPEC.md + one result key
     per reason code), identical keys and vars in en and es, every placeholder declared and
     resolved, channel coverage, expect blocks (Brain API enums, slots, web choices), a closed
     and a short form for every question, several variants for frequent keys, exact wording
     where it is fixed (opening, flip question, card lines, gateway lines of
     docs/BRAIN_API.md), the county-decides sentence after every estimate.
  2. Phone text rules on every phone-spoken variant (phone and all lists, both banks):
     no symbols, no digits, no URLs; word budgets per key and for real reply compositions
     (opening 40, question 25, result 45; contract word definition).
     The phone opening: at most 40 words, no digits, the fixed consent question.
     Keypad: single keys only (1 = yes, 2 = no, at most three numbered choices); no typed
     amounts, no "pound", no keypad entry wording; every key a phone question offers is one
     its expect block accepts; money questions close with a band choice or a yes/no.
     Confirm and read-back policy: confirm only for the critical money slots; no confirm and
     no read-back for cash on hand. The crisis follow-up is a two-way choice.
  3. Guards: every regex compiles; redaction kinds (ssn or card_number, masked or spoken),
     keyword and routing vectors (the reply key one utterance gets, with the intent
     precedence and the close phase), output test vectors; the redaction and keyword rules
     against data/tests/utterances.jsonl; zero forbidden hits (regex list + contract phrase
     list) over every sentence variant and every card string, sources and unverified notes
     included.
  4. Card: one block order for every card, the block table per tier and route, block tones,
     en/es parity (same conditions and placeholders), valid `when` conditions, declared
     placeholders, the IRT line rule (docs/SPEC.md), honest wording, source dates, sample
     cards for personas render with no leftover placeholders, reading level (Flesch-Kincaid
     grade 7 or lower for every English block).
  5. Contacts: phone formats, spoken digits that match the number, verified hours with a
     source and date, the coordinator number used by the gateway lines.
  6. Public hygiene for all eight files: no Hangul, no local paths, no e-mail address except
     calfresh@sfsu.edu, no phone numbers except the ones in contacts.json, 988 and 911;
     browser makers named only in the web opening disclosure.
  7. Other programs on the card (programs.en.json, programs.es.json; card-side only, never
     spoken): identical keys and placeholders in en and es, identical structure (programs,
     links, budgets, placeholders, sources), every placeholder declared, the required keys and
     the three card questions with their choices, word budgets (question 18, choice 5, line 30,
     note 25, share 30, footnote 25, plus label, button, name, prefill and console), zero output
     guard hits on every string (as written and filled with the example values), honest wording
     (every estimate says about / up to / maybe; LifeLine says 'up to'; CARE shows its assumed
     bill; Medi-Cal has no dollar amount, no '$0 premium', no dental or vision promise), a share
     text with only {share} and {site}, https apply links (CalFresh's apply.calfresh_steps is the
     one in-page link, #today_action), and every key, url, question, choice
     and source id that data/rules/programs_2026.json names (when present).
"""
import itertools
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINES_EN_EXAMPLE = HERE.parent.parent / "contracts" / "examples" / "lines_en.json"
UTTERANCES = HERE.parent / "tests" / "utterances.jsonl"
VERBOSE = "-v" in sys.argv[1:]

PROBLEMS = []
NOTES = []


def fail(where, msg):
    PROBLEMS.append(f"{where}: {msg}")


def load(name):
    path = HERE / name
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001 - report any load problem as a check failure
        fail(name, f"cannot load: {exc}")
        return None


# ------------------------------------------------------------------ frozen names (docs/SPEC.md: sentence keys, reason codes, slots, intents)
REASON_CODES = [
    "likely", "coordinator.parent_household", "coordinator.shared_household", "coordinator.grad_no_exemption",
    "coordinator.not_degree", "coordinator.age_outside_student_rule", "coordinator.gig_income", "coordinator.boarder",
    "coordinator.spouse_student", "coordinator.status_complex", "coordinator.elderly_disabled", "coordinator.unresolved",
    "other_help.status", "other_help.over_gross_limit", "other_help.dorm_meal_plan", "other_help.not_sfsu",
    "other_help.zero_benefit", "info.already_receiving", "info.interview_waiting",
]
KEY_VARS = {
    # opening
    "consent.ask": [], "consent.reask": [], "consent.declined": ["coordinator_phone"], "answer.is_ai": [],
    "answer.is_recorded": [], "language.offer_web": ["talk_url"], "language.unsupported": [], "proxy.caller": [],
    "hold.ok": [], "abuse.warn": [], "abuse.end": ["coordinator_phone"],
    # questions
    "ask.level_units": [], "ask.units": [], "ask.grad_exemption": [], "ask.age_parent": [], "ask.meal_plan": [],
    "ask.household": [], "ask.household_food_roommates": [], "ask.income": [], "ask.other_cash": [],
    "ask.income_band": ["a", "b"], "ask.rent": [], "ask.homeless_cost": [], "expedited.intro_cash": [], "flip.intro": [],
    "flip.rent_paid_by_others": [], "flip.rent_paid_by_others_amount": [], "flip.heat_cool": [], "flip.other_utils": [],
    "flip.household_food": [], "flip.other_cash_band": ["a", "b"], "flip.earned_split": ["x"],
    # read-back, confirm, re-prompt
    "ack.short": [], "readback.earned": ["amount"], "readback.hourly": ["rate", "hours"], "readback.rent": ["amount"],
    "readback.other_cash": ["amount"], "readback.cash": ["amount"], "confirm.money": ["amount", "period"],
    "reprompt.silence_1": ["question"], "reprompt.silence_2": ["question"], "reprompt.unclear": ["question"],
    "reprompt.after_interrupt": ["question"],
    # results
    "result.likely": ["amount"], "result.likely_floor": ["amount"], "result.note.abawd": [],
    "result.coordinator.generic": [], "result.other_help.generic": [], "result.info.already_receiving": [],
    "result.info.interview_waiting": [], "expedited.yes": [], "expedited.maybe": [], "first_month.apply_today": [],
    "card.phone_screen": [], "card.phone_code": ["short_url", "code"], "card.web": [],
    "close.anything_else": ["coordinator_phone"], "close.goodbye": [], "close.silence": ["coordinator_phone"],
    # global
    "crisis.resources": [], "crisis.continue_or_stop": [], "ssn.block": ["question"], "card_number.block": ["question"],
    "human.request": ["coordinator_phone", "coordinator_hours"], "stop.goodbye": ["coordinator_phone"],
    "delete.confirm_ask": [], "delete.done": [], "delete.cancelled": [], "apply_for_me": [], "immigration.question": [],
    "food_today": [], "side_question.noted": [], "info.previously_denied": [], "error.generic": ["coordinator_phone"],
    # gateway lines
    "line.filler": [], "line.retry": [], "line.fatal": [], "line.fatal_start": [], "line.no_input_bye": [],
    "line.time_limit": [], "line.line_unavailable": [],
}
for _code in REASON_CODES:
    _group, _, _name = _code.partition(".")
    if _group in ("coordinator", "other_help"):
        KEY_VARS[f"result.{_code}"] = ["county_phone"] if _code == "other_help.not_sfsu" else []
VAR_TYPES = {"money", "int", "phone", "url", "code", "date", "text", "hours"}
QUESTION_GROUP = [
    "ask.level_units", "ask.units", "ask.grad_exemption", "ask.age_parent", "ask.meal_plan", "ask.household",
    "ask.household_food_roommates", "ask.income", "ask.other_cash", "ask.income_band", "ask.rent", "ask.homeless_cost",
    "expedited.intro_cash", "flip.intro", "flip.rent_paid_by_others", "flip.rent_paid_by_others_amount",
    "flip.heat_cool", "flip.other_utils", "flip.household_food", "flip.other_cash_band", "flip.earned_split",
]
OTHER_ASK_KEYS = ["consent.ask", "consent.reask", "confirm.money", "close.anything_else", "crisis.continue_or_stop",
                  "human.request", "delete.confirm_ask"]
SLOTS = [
    "consent", "level", "units", "half_time", "grad_exemption", "age", "lives_with_parent", "roommates",
    "dorm_on_campus", "meals_per_week", "dorm_meals_over_10", "household_food", "spouse", "spouse_student",
    "children_count", "youngest_child_age", "boarder", "homeless", "homeless_shelter_cost_monthly", "earned_monthly",
    "work_study_monthly", "gig_monthly", "ta_ra", "unearned_monthly", "other_cash_monthly", "dependent_care_monthly",
    "rent_share", "rent_paid_by_others_to_landlord", "heat_cool", "other_utils", "cash_on_hand", "volunteered_status",
    "elderly_or_disabled", "already_receiving", "applied_waiting_interview", "previously_denied",
    "income_changing_soon",
]
INTENTS = ["correction", "dont_know", "repeat", "is_ai", "is_recorded", "human_request", "stop", "delete_data",
           "apply_for_me", "immigration_question", "language_request", "crisis", "food_today", "already_receiving",
           "interview_waiting", "previously_denied", "proxy_caller", "side_question", "mentions_financial_aid",
           "off_topic", "ssn_attempt", "hold", "abuse"]
EXPECT_ENUM = {"open", "yes_no", "confirm", "number", "choice"}
LISTEN_ENUM = {"normal", "long"}
BANDS = {"below_a", "between", "above_b", "below_x", "above_x"}
FREQUENT_KEYS = [
    "consent.reask", "consent.declined", "answer.is_ai", "answer.is_recorded", "hold.ok", "abuse.warn",
    "ask.level_units", "ask.age_parent", "ask.household", "ask.household_food_roommates", "ask.income", "ask.rent",
    "flip.intro", "ack.short", "readback.earned", "readback.hourly", "readback.rent", "readback.other_cash",
    "readback.cash", "confirm.money", "reprompt.silence_1", "reprompt.silence_2", "reprompt.unclear",
    "reprompt.after_interrupt", "result.likely", "expedited.yes", "first_month.apply_today", "close.anything_else",
    "close.goodbye", "crisis.resources", "ssn.block", "info.previously_denied",
]

# ------------------------------------------------------------------ contract rules (contracts/check_examples.py)
WORD_BUDGETS = {"opening": 40, "question": 25, "result": 45}
PHONE_FORBIDDEN = set("$%/~\u2013")
PHONE_ALSO_FORBIDDEN = set("0123456789@#&*+=<>|_\\[]{}`\"()")
RESULT_KEY_PREFIXES = ("result.", "expedited.yes", "expedited.maybe", "first_month.", "card.", "close.anything_else",
                       "close.silence", "consent.declined", "crisis.resources", "human.request", "stop.goodbye",
                       "abuse.end", "error.generic")
CONTACT_WORDS = re.compile(r"\b(four one five|eight five five|eight seven seven|nine eight eight|nine one one)\b", re.I)
OPENING_SAY = [r"\bGatorPlate\b", r"\bAI\b", r"\bstudent-built\b", r"\bnot an official SF State service\b",
               r"\binto text\b", r"\bCalFresh\b", r"\baudio isn't recorded\b"]
OPENING_ASK = [r"\byes\b", r"\bpress one\b"]
OPENING_ASK_EXACT = "Okay to start? Say yes, or press one."   # 40 words with the disclosure (docs/BRAIN_API.md)

# ------------------------------------------------------------------ keypad, money questions, confirm policy
# The gateway sends one key per dtmf event and never collects digits (docs/BRAIN_API.md, TurnRequest keypad note):
# 1 = yes, 2 = no, at most three numbered choices; no typed amounts, no '#'.
KEYPAD_KEYS = ("1", "2", "3")
KEY_WORDS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
             "9": "nine"}
KEYPAD_ENTRY_WORDING = re.compile(r"\bpound\b|\bhash\b|\bkeypad\b|\btype\b|\bdial\b|\benter (?:the|your|an?) "
                                  r"(?:amount|number|age|units?)\b|\bdigits?\b", re.I)
MONEY_QUESTIONS = ["ask.income", "ask.other_cash", "ask.income_band", "ask.rent", "ask.homeless_cost",
                   "expedited.intro_cash", "flip.rent_paid_by_others_amount", "flip.other_cash_band"]
BAND_TOKENS_AB = {"below_a", "between", "above_b"}
CONFIRM_SLOTS = ["earned_monthly", "other_cash_monthly", "rent_share", "rent_paid_by_others_to_landlord"]
CRISIS_CHOICE = {"1": {"action": "resume"}, "2": {"intent": "stop"}}

# ------------------------------------------------------------------ exact wording that is fixed (docs/SPEC.md, docs/BRAIN_API.md)
LINES_EN = {
    "line.filler": ["One moment.", "Let me check that.", "Okay, one second."],
    "line.retry": ["Sorry, I didn't catch that."],
    "line.fatal": ["Sorry, something went wrong on our side. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye."],
    "line.fatal_start": ["Hi, this is GatorPlate, a student-built AI assistant. Sorry, it isn't working right now. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye."],
    "line.no_input_bye": ["I can't hear you, so I'll hang up now. You can call back anytime. Goodbye."],
    "line.time_limit": ["We've reached the time limit for this call. Your answers so far are saved for the coordinator. Goodbye."],
    "line.line_unavailable": ["Hi, this is GatorPlate, a student-built AI assistant for SF State students. The line isn't available right now. You can reach the SF State CalFresh coordinator at four one five, three three eight, one two zero three. Goodbye."],
}
LINE_FIELDS = {"line.filler": "filler", "line.retry": "retry", "line.fatal": "fatal", "line.fatal_start": "fatal_start",
               "line.no_input_bye": "no_input_bye", "line.time_limit": "time_limit",
               "line.line_unavailable": "line_unavailable"}
EXACT_EN = {
    ("card.phone_screen", "phone"): ["Your card is ready — scan the QR code on the screen."],
    ("card.phone_code", "phone"): ["Go to {short_url} and enter code {code}."],
    ("flip.rent_paid_by_others", "all"): ["Does anyone, like a parent, pay part of your rent straight to your landlord?"],
}
WEB_OPENING_EN = ("Hi, I'm GatorPlate, a student-built AI assistant, not an official SF State service. Your browser turns "
                  "your voice into text (Chrome uses Google's speech service; Safari uses Apple's). GatorPlate only gets "
                  "the text and never stores audio.")
COUNTY_DECIDES = {"en": "The county makes the final decision.", "es": "El condado toma la decisión final."}

# ------------------------------------------------------------------ helpers
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
WORD_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9]")


def count_words(text):
    """Contract word: a whitespace-separated token with at least one letter or digit."""
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def norm(text):
    return re.sub(r"\s+", " ", text.replace("\u2019", "'").replace("\u2018", "'")
                  .replace("\u201c", '"').replace("\u201d", '"')).strip()


def placeholders(text):
    return PLACEHOLDER.findall(text)


def render(text, values):
    def sub(m):
        name = m.group(1)
        return values[name] if name in values else m.group(0)
    return PLACEHOLDER.sub(sub, text)


def variant_text(v):
    if isinstance(v, dict):
        return " ".join(x for x in (v.get("say") or "", v.get("ask") or "") if x)
    return v


def variant_parts(v):
    if isinstance(v, dict):
        return [v.get("say") or "", v.get("ask") or ""]
    return [v]


def phone_problems(text):
    out = []
    for ch in sorted(set(text)):
        if ch in PHONE_FORBIDDEN:
            out.append(f"forbidden symbol {ch!r}")
        elif ch in PHONE_ALSO_FORBIDDEN:
            out.append(f"{ch!r} must be spoken as words")
        elif ord(ch) > 0xFFFF:
            out.append("emoji or symbol outside plain text")
    if re.search(r"https?:|www\.", text, re.I):
        out.append("URLs must be spoken")
    return out


# ------------------------------------------------------------------ load
EN = load("sentences.en.json")
ES = load("sentences.es.json")
CARD_EN = load("card.en.json")
CARD_ES = load("card.es.json")
GUARDS = load("guards.json")
CONTACTS = load("contacts.json")
PROG_EN = load("programs.en.json")
PROG_ES = load("programs.es.json")
if None in (EN, ES, CARD_EN, CARD_ES, GUARDS, CONTACTS, PROG_EN, PROG_ES):
    print("\n".join(PROBLEMS))
    sys.exit(1)

# ------------------------------------------------------------------ guards: compile + output checker
FORBIDDEN_RX = []
for lang in ("en", "es"):
    for pat in GUARDS.get("output", {}).get("forbidden", {}).get(lang, []):
        try:
            FORBIDDEN_RX.append((lang, pat, re.compile(pat, re.I)))
        except re.error as exc:
            fail("guards.json", f"output regex does not compile {pat!r}: {exc}")
FORBIDDEN_PHRASES = [p.lower() for p in GUARDS.get("output", {}).get("forbidden_phrases", [])]


def forbidden_hits(text):
    t = norm(text)
    low = t.lower()
    hits = [f"regex {pat!r}" for _lang, pat, rx in FORBIDDEN_RX if rx.search(t)]
    hits += [f"phrase {p!r}" for p in FORBIDDEN_PHRASES if p in low]
    return hits


# ------------------------------------------------------------------ contacts-derived sample values
def c(path, default=None):
    node = CONTACTS
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            fail("contacts.json", f"missing {path}")
            return default
    return node


SPOKEN = {
    "en": {
        "coordinator_phone": c("coordinator.spoken.en", ""), "county_phone": c("county.spoken.en", ""),
        "coordinator_hours": c("coordinator.hours.spoken.en", ""),
        "talk_url": "gatorplate dot fly dot dev slash talk", "short_url": "gatorplate dot fly dot dev slash go",
        "code": "four eight one, two zero six", "amount": "nineteen hundred seventy-five dollars",
        "a": "one thousand dollars", "b": "two thousand dollars", "x": "fifteen hundred dollars",
        "rate": "eighteen dollars fifty", "hours": "twenty-five", "period": "every two weeks",
    },
    "es": {
        "coordinator_phone": c("coordinator.spoken.es", ""), "county_phone": c("county.spoken.es", ""),
        "coordinator_hours": c("coordinator.hours.spoken.es", ""),
        "talk_url": "gatorplate punto fly punto dev barra talk", "short_url": "gatorplate punto fly punto dev barra go",
        "code": "cuatro ocho uno, dos cero seis", "amount": "mil novecientos setenta y cinco dólares",
        "a": "mil dólares", "b": "dos mil dólares", "x": "mil quinientos dólares",
        "rate": "dieciocho dólares cincuenta", "hours": "veinticinco", "period": "cada dos semanas",
    },
}
DISPLAY = {
    "en": {
        "coordinator_phone": c("coordinator.display", ""), "county_phone": c("county.display", ""),
        "coordinator_hours": c("coordinator.hours.text.en", ""), "talk_url": "gatorplate.fly.dev/talk",
        "short_url": "gatorplate.fly.dev/go", "code": "481 206", "amount": "$1,975", "a": "$1,000", "b": "$2,000",
        "x": "$1,500", "rate": "$18.50", "hours": "25", "period": "every two weeks",
    },
    "es": {
        "coordinator_phone": c("coordinator.display", ""), "county_phone": c("county.display", ""),
        "coordinator_hours": c("coordinator.hours.text.es", ""), "talk_url": "gatorplate.fly.dev/talk",
        "short_url": "gatorplate.fly.dev/go", "code": "481 206", "amount": "$1,975", "a": "$1,000", "b": "$2,000",
        "x": "$1,500", "rate": "$18.50", "hours": "25", "period": "cada dos semanas",
    },
}
for _lang in ("en", "es"):
    SPOKEN[_lang]["question"] = "{question}"
    DISPLAY[_lang]["question"] = "{question}"

# ------------------------------------------------------------------ 1. sentence banks
FORMS = ("main", "closed", "short", "demo")  # demo: the live demo's short phone forms (DEMO_KEYS)


def lists_of(msg, form):
    """{field: [variants]} for one form of a message ('main', 'closed', 'short', 'demo')."""
    node = msg if form == "main" else msg.get(form) or {}
    return {f: node[f] for f in ("phone", "web", "all") if isinstance(node.get(f), list)}


def pick(msg, form, channel):
    lists = lists_of(msg, form)
    return lists.get(channel) or lists.get("all") or []


def check_bank(bank, lang):
    name = f"sentences.{lang}.json"
    if bank.get("lang") != lang:
        fail(name, f"lang must be {lang!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(bank.get("version", ""))):
        fail(name, "version must be a date")
    msgs = bank.get("messages")
    if not isinstance(msgs, dict):
        fail(name, "messages missing")
        return {}
    missing = sorted(set(KEY_VARS) - set(msgs))
    extra = sorted(set(msgs) - set(KEY_VARS))
    if missing:
        fail(name, f"missing keys {missing}")
    if extra:
        fail(name, f"keys not in the frozen list {extra}")
    for key, msg in msgs.items():
        where = f"{name} {key}"
        if not isinstance(msg, dict):
            fail(where, "message must be an object")
            continue
        channels = msg.get("channels")
        if not channels or not set(channels) <= {"phone", "web"}:
            fail(where, "channels must be a non-empty subset of phone, web")
            channels = ["phone", "web"]
        # vars
        declared = []
        for v in msg.get("vars", []):
            vname, _, vtype = v.partition(":")
            if vtype not in VAR_TYPES:
                fail(where, f"var {v!r} has an unknown type")
            declared.append(vname)
        if key in KEY_VARS and declared != KEY_VARS[key]:
            fail(where, f"vars {declared} differ from the frozen list {KEY_VARS[key]}")
        # coverage
        main = lists_of(msg, "main")
        if not main:
            fail(where, "no variants")
        if "phone" in channels and not (main.get("phone") or main.get("all")):
            if lang == "en" or channels == ["phone"]:
                fail(where, "phone channel has no variants")
        if "web" in channels and not (main.get("web") or main.get("all")):
            fail(where, "web channel has no variants")
        if lang == "es" and "phone" in main and channels != ["phone"]:
            fail(where, "es phone variants only for phone-only keys (phone calls are English)")
        # variants
        for form in FORMS:
            for field, variants in lists_of(msg, form).items():
                if not variants:
                    fail(where, f"{form}.{field} is empty")
                for i, v in enumerate(variants):
                    at = f"{where} {form}.{field}[{i}]"
                    if isinstance(v, dict):
                        if set(v) - {"say", "ask"} or not v.get("ask"):
                            fail(at, "a {say, ask} variant needs a non-empty ask and nothing else")
                    elif not isinstance(v, str) or not v.strip():
                        fail(at, "variant must be a non-empty string or {say, ask}")
                        continue
                    text = variant_text(v)
                    used = placeholders(text)
                    for p in used:
                        if p not in declared:
                            fail(at, f"placeholder {{{p}}} is not declared in vars")
                    split_key = any(isinstance(x, dict) for vs in lists_of(msg, "main").values() for x in vs)
                    if (form == "main" or (form == "closed" and not split_key)) and set(declared) - set(used):
                        fail(at, f"does not use declared vars {sorted(set(declared) - set(used))}")
                    if text != text.strip() or "  " in text:
                        fail(at, "extra spaces")
                    if not re.search(r"([.?!]|\{question\})$", text.strip()):
                        fail(at, "must end with . ? or !")
                    # phone rules on phone-spoken text, rendered with spoken values
                    if field in ("phone", "all"):
                        spoken = render(text, SPOKEN[lang])
                        for prob in phone_problems(spoken.replace("{question}", "")):
                            fail(at, f"phone text: {prob}")
                    # placeholders resolve
                    for values in (SPOKEN[lang], DISPLAY[lang]):
                        left = [p for p in placeholders(render(text, values)) if p != "question"]
                        if left:
                            fail(at, f"unresolved placeholders {left}")
                    # forbidden wording, both renderings
                    for values in (SPOKEN[lang], DISPLAY[lang]):
                        for hit in forbidden_hits(render(text, values).replace("{question}", "")):
                            fail(at, f"forbidden wording: {hit}")
        # expect blocks
        is_question = (key in QUESTION_GROUP and key != "flip.intro") or key in OTHER_ASK_KEYS
        if is_question and "expect" not in msg:
            fail(where, "question without an expect block")
        if not is_question and "expect" in msg:
            fail(where, "expect block on a key that is not a question")
        if key in QUESTION_GROUP and not lists_of(msg, "closed"):
            fail(where, "question group key without a closed form")
        if is_question:
            if not lists_of(msg, "closed"):
                fail(where, "question without a closed form")
            if not lists_of(msg, "short"):
                fail(where, "question without a short form")
            check_expect(where, msg["expect"], declared)
            if isinstance(msg.get("closed"), dict) and "expect" in msg["closed"]:
                check_expect(where + " closed", msg["closed"]["expect"], declared)
        if key in FREQUENT_KEYS:
            n = max(len(pick(msg, "main", "phone")), len(pick(msg, "main", "web")))
            if n < 2:
                fail(where, "frequent key needs at least 2 variants")
    return msgs


def check_expect(where, e, declared):
    if not isinstance(e, dict):
        fail(where, "expect must be an object")
        return
    if e.get("expect") not in EXPECT_ENUM:
        fail(where, f"expect.expect {e.get('expect')!r} not in {sorted(EXPECT_ENUM)}")
    if e.get("listen") not in LISTEN_ENUM:
        fail(where, f"expect.listen {e.get('listen')!r} not in {sorted(LISTEN_ENUM)}")
    for s in e.get("slots", []):
        if s not in SLOTS:
            fail(where, f"unknown slot {s!r}")
    unknown = set(e) - {"expect", "listen", "slots", "keypad", "choices", "band_edges", "yes", "no"}
    if unknown:
        fail(where, f"unknown expect fields {sorted(unknown)}")
    keypad = e.get("keypad")
    if keypad == "amount":
        fail(where, "keypad 'amount' is not allowed: the phone takes single keys only, never a typed number")
    elif keypad not in (None, "yes_no"):
        if not isinstance(keypad, dict) or not keypad:
            fail(where, "keypad must be null, 'yes_no' or a non-empty map of single keys")
        else:
            keys = sorted(keypad)
            if keys != list(KEYPAD_KEYS[:len(keys)]):
                fail(where, f"keypad keys {keys} must be single keys from 1, at most 1-3")
            for k, entry in keypad.items():
                check_entry(where + f" keypad {k}", entry)
    if e.get("expect") == "yes_no" and keypad not in ("yes_no", None) and not isinstance(keypad, dict):
        fail(where, "yes_no question needs keypad yes_no")
    # band choices: edges come from the a and b vars, or from band_edges on a key without them
    entries = list((keypad or {}).values()) if isinstance(keypad, dict) else []
    entries += [ch for ch in (e.get("choices") or []) if isinstance(ch, dict)]
    entries += [e[yn] for yn in ("yes", "no") if isinstance(e.get(yn), dict)]
    uses_ab = any(isinstance(x, dict) and x.get("band") in BAND_TOKENS_AB for x in entries)
    edges = e.get("band_edges")
    has_ab_vars = {"a", "b"} <= set(declared)
    if edges is not None:
        if has_ab_vars:
            fail(where, "band_edges on a key that already has the a and b vars")
        elif not isinstance(edges, dict) or set(edges) != {"a", "b"}:
            fail(where, "band_edges must be {a, b}")
        else:
            try:
                if not float(edges["a"]) < float(edges["b"]):
                    fail(where, "band_edges a must be below b")
            except (TypeError, ValueError):
                fail(where, "band_edges values must be numbers as strings")
    if uses_ab and not has_ab_vars and edges is None:
        fail(where, "band tokens below_a/between/above_b need the a and b vars or band_edges")
    choices = e.get("choices")
    if choices is not None:
        if not isinstance(choices, list) or not 1 <= len(choices) <= 6:
            fail(where, "choices must be a list of 1-6 entries or null")
        else:
            for ch in choices:
                label = ch.get("label") if isinstance(ch, dict) else None
                if not isinstance(label, str) or not 1 <= len(label) <= 60:
                    fail(where, f"choice label {label!r} must be 1-60 characters")
                    continue
                for p in placeholders(label):
                    if p not in declared:
                        fail(where, f"choice label uses undeclared {{{p}}}")
                for hit in forbidden_hits(label):
                    fail(where, f"choice label forbidden wording: {hit}")
                check_entry(where + f" choice {label!r}", {k: v for k, v in ch.items() if k != "label"})
    for yn in ("yes", "no"):
        if yn in e:
            check_entry(where + f" {yn}", e[yn], allow_empty=True)


def check_entry(where, entry, allow_empty=False):
    if not isinstance(entry, dict) or (not entry and not allow_empty):
        fail(where, "entry must be a non-empty object")
        return
    allowed = {"set", "band", "intent", "answer", "action", "note"}
    if set(entry) - allowed:
        fail(where, f"unknown entry fields {sorted(set(entry) - allowed)}")
    for s in (entry.get("set") or {}):
        if s not in SLOTS:
            fail(where, f"set uses unknown slot {s!r}")
    if "band" in entry and entry["band"] not in BANDS:
        fail(where, f"unknown band {entry['band']!r}")
    if "intent" in entry and entry["intent"] not in INTENTS:
        fail(where, f"unknown intent {entry['intent']!r}")
    if "answer" in entry and entry["answer"] not in ("yes", "no"):
        fail(where, "answer must be yes or no")


MSG_EN = check_bank(EN, "en")
MSG_ES = check_bank(ES, "es")


def strip_labels(obj):
    if isinstance(obj, dict):
        return {k: strip_labels(v) for k, v in obj.items() if k != "label"}
    if isinstance(obj, list):
        return [strip_labels(v) for v in obj]
    return obj


for key in sorted(set(MSG_EN) & set(MSG_ES)):
    a, b = MSG_EN[key], MSG_ES[key]
    if a.get("vars") != b.get("vars"):
        fail(f"sentences {key}", f"vars differ: en {a.get('vars')} es {b.get('vars')}")
    if a.get("channels") != b.get("channels"):
        fail(f"sentences {key}", "channels differ between en and es")
    for form in ("expect",):
        if strip_labels(a.get(form)) != strip_labels(b.get(form)):
            fail(f"sentences {key}", "expect blocks differ between en and es (apart from labels)")
    ca = (a.get("closed") or {}).get("expect")
    cb = (b.get("closed") or {}).get("expect")
    if strip_labels(ca) != strip_labels(cb):
        fail(f"sentences {key}", "closed expect blocks differ between en and es (apart from labels)")
    for form in ("closed", "short"):
        if bool(lists_of(a, form)) != bool(lists_of(b, form)):
            fail(f"sentences {key}", f"{form} form present in one language only")

# exact wording and fixed facts (en)
for (key, field), want in EXACT_EN.items():
    got = (MSG_EN.get(key) or {}).get(field)
    if got != want:
        fail(f"sentences.en.json {key}", f"must be exactly {want} (fixed wording, docs/SPEC.md)")
for key, want in LINES_EN.items():
    if (MSG_EN.get(key) or {}).get("phone") != want:
        fail(f"sentences.en.json {key}", "gateway line must equal docs/BRAIN_API.md GatewayLines exactly")
if LINES_EN_EXAMPLE.exists():
    try:
        example = json.loads(LINES_EN_EXAMPLE.read_text(encoding="utf-8"))
        for key, field in LINE_FIELDS.items():
            want = example.get(field)
            want = want if isinstance(want, list) else [want]
            if (MSG_EN.get(key) or {}).get("phone") != want:
                fail(f"sentences.en.json {key}", "differs from contracts/examples/lines_en.json")
    except Exception as exc:  # noqa: BLE001
        fail("lines_en.json", f"cannot compare: {exc}")
for key in LINES_EN:
    es_lines = (MSG_ES.get(key) or {}).get("phone")
    if not es_lines or len(es_lines) != len(LINES_EN[key]):
        fail(f"sentences.es.json {key}", "needs the same number of Spanish phone lines")
for key in ("line.fatal", "line.fatal_start", "line.line_unavailable"):
    for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
        spoken = SPOKEN[lang]["coordinator_phone"]
        for v in (msgs.get(key) or {}).get("phone", []):
            if spoken and spoken not in v:
                fail(f"sentences.{lang}.json {key}", "must say the coordinator number exactly as contacts.json spoken")
DEMO_KEYS = ("consent.ask", "readback.earned", "readback.rent")  # the live demo's short phone forms (GP_DEMO_SHORTCUT)
# opening (and the live demo's short phone opening, GP_DEMO_SHORTCUT: the same rules, phone only, shorter)
for _lang, _msgs in (("en", MSG_EN), ("es", MSG_ES)):
    for _key, _msg in _msgs.items():
        if "demo" in _msg and (_key not in DEMO_KEYS or _lang != "en" or set(lists_of(_msg, "demo")) != {"phone"}):
            fail(f"sentences.{_lang}.json {_key}", "a demo form exists only as an English phone line of " + ", ".join(sorted(DEMO_KEYS)))
_demo_open = lists_of(MSG_EN.get("consent.ask") or {}, "demo").get("phone") or []
_open = ((MSG_EN.get("consent.ask") or {}).get("phone") or []) + _demo_open
for v in _demo_open:
    if isinstance(v, dict) and count_words(f"{v.get('say')} {v.get('ask')}") > 34:
        fail("sentences.en.json consent.ask demo", "the short demo opening must stay at most 34 words")
for v in _open:
    if not isinstance(v, dict):
        fail("sentences.en.json consent.ask", "phone opening must be {say, ask}")
        continue
    for pat in OPENING_SAY:
        if not re.search(pat, v["say"]):
            fail("sentences.en.json consent.ask", f"opening say lacks {pat}")
    for pat in OPENING_ASK:
        if not re.search(pat, v["ask"]):
            fail("sentences.en.json consent.ask", f"opening ask lacks {pat}")
    if v["ask"] != OPENING_ASK_EXACT:
        fail("sentences.en.json consent.ask", f"phone opening ask must be exactly {OPENING_ASK_EXACT!r}")
    _n = count_words(f"{v['say']} {v['ask']}")
    if _n > WORD_BUDGETS["opening"]:
        fail("sentences.en.json consent.ask", f"phone opening is {_n} words > 40")
    if re.search(r"\d", v["say"] + v["ask"]):
        fail("sentences.en.json consent.ask", "phone opening must not contain digits ('press one', not 'press 1')")
if not _open:
    fail("sentences.en.json consent.ask", "no phone opening")
_web_open =(MSG_EN.get("consent.ask") or {}).get("web") or []
if not _web_open or not isinstance(_web_open[0], dict) or _web_open[0].get("say") != WEB_OPENING_EN \
        or _web_open[0].get("ask") != "Is that okay?":
    fail("sentences.en.json consent.ask", "web opening must be the fixed disclosure text + 'Is that okay?'")
# amounts are always followed by the county-decides sentence
for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
    for key in ("result.likely", "result.likely_floor"):
        for field, variants in lists_of(msgs.get(key) or {}, "main").items():
            for v in variants:
                t = variant_text(v)
                if COUNTY_DECIDES[lang] not in t or t.index(COUNTY_DECIDES[lang]) < t.index("{amount}"):
                    fail(f"sentences.{lang}.json {key}", "the county-decides sentence must follow the amount")
# the read-back and card-code examples of docs/BRAIN_API.md are reachable
_rb = [render(variant_text(v), {"amount": "nine hundred dollars"}) for v in pick(MSG_EN.get("readback.earned", {}), "main", "phone")]
if "Got it — about nine hundred dollars a month from work." not in _rb:
    fail("sentences.en.json readback.earned", "the read-back example of docs/BRAIN_API.md is not one of the variants")
_code = [render(v, {"short_url": "gatorplate dot fly dot dev slash go", "code": "four eight one, two zero six"})
         for v in pick(MSG_EN.get("card.phone_code", {}), "main", "phone")]
if "Go to gatorplate dot fly dot dev slash go and enter code four eight one, two zero six." not in _code:
    fail("sentences.en.json card.phone_code", "does not render to the docs/BRAIN_API.md card-code sentence")


# keypad: single keys only, and every key a phone question offers is one its expect block accepts
OFFERED_KEY = re.compile(r"(?:\bpress |, |\bor )(one|two|three|four|five|six|seven|eight|nine)\b"
                         r"(?= for\b| to\b|,|\.|\?| or\b|$)", re.I)
WORD_KEYS = {w: k for k, w in KEY_WORDS.items()}
WEB_KEY_WORDING = re.compile(r"\bpress (?:one|two|three|[0-9])\b|\bpound\b|\b(?:pulsa|oprime|presiona|marca) "
                             r"(?:el )?(?:uno|dos|tres|[0-9])\b", re.I)


def effective_expect(msg, form):
    if form == "closed" and isinstance(msg.get("closed"), dict) and "expect" in msg["closed"]:
        return msg["closed"]["expect"]
    return msg.get("expect")


def offered_keys(text):
    at = text.lower().find("press")
    if at < 0:
        return set()
    return {WORD_KEYS[m.group(1).lower()] for m in OFFERED_KEY.finditer(text[at:])}


for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
    name = f"sentences.{lang}.json"
    for key, msg in msgs.items():
        for form in FORMS:
            e = effective_expect(msg, form) or {}
            keypad = e.get("keypad")
            allowed = {"1", "2"} if keypad == "yes_no" else set(keypad) if isinstance(keypad, dict) else set()
            for field, variants in lists_of(msg, form).items():
                for i, v in enumerate(variants):
                    at = f"{name} {key} {form}.{field}[{i}]"
                    text = variant_text(v)
                    if field == "web":
                        if WEB_KEY_WORDING.search(text):
                            fail(at, "web text must not offer keypad keys")
                        continue
                    if KEYPAD_ENTRY_WORDING.search(text):
                        fail(at, "phone text must not ask for a typed entry (no 'pound', 'type', 'keypad', digits)")
                    if lang != "en" and field != "phone":
                        continue   # es 'all' variants are only shown on the web
                    offered = offered_keys(text)
                    if offered - allowed:
                        fail(at, f"offers keys {sorted(offered - allowed)} that the expect block does not accept")
                    if form == "closed" and "expect" in msg and lang == "en" and not allowed:
                        fail(at, "a closed phone question needs a keypad option (yes/no or up to three keys)")
                    if form == "closed" and "expect" in msg and allowed and lang == "en" and field in ("phone", "all"):
                        if not offered:
                            fail(at, "a closed phone question with a keypad must offer it ('press one ...')")
                        elif isinstance(keypad, dict) and offered != allowed:
                            fail(at, f"offers keys {sorted(offered)} but the choice has keys {sorted(allowed)}")
# money questions: answered by voice; the closed form is a spoken band choice or a yes/no
for key in MONEY_QUESTIONS:
    for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
        msg = msgs.get(key) or {}
        e = effective_expect(msg, "closed") or {}
        kind = e.get("expect")
        bands = [x for x in list((e.get("keypad") or {}).values() if isinstance(e.get("keypad"), dict) else [])
                 + list(e.get("choices") or []) if isinstance(x, dict) and "band" in x]
        if kind == "choice" and not bands:
            fail(f"sentences.{lang}.json {key}", "money question: a closed choice must be a band choice")
        elif kind not in ("choice", "yes_no"):
            fail(f"sentences.{lang}.json {key}", f"money question: closed form must be a band choice or yes/no, not {kind!r}")
# confirm and read-back policy
_cp = EN.get("confirm_policy") or {}
if _cp.get("confirm_slots") != CONFIRM_SLOTS:
    fail("sentences.en.json confirm_policy", f"confirm_slots must be exactly {CONFIRM_SLOTS}")
for _f in ("no_confirm", "no_readback"):
    if "cash_on_hand" not in (_cp.get(_f) or []):
        fail("sentences.en.json confirm_policy", f"{_f} must list cash_on_hand")
for _slot, _key in (_cp.get("readback_keys") or {}).items():
    if _key not in MSG_EN or _slot in (_cp.get("no_readback") or []):
        fail("sentences.en.json confirm_policy", f"readback_keys {_slot} -> {_key} is not allowed")
if set(_cp.get("confirm_slots") or []) & set(_cp.get("no_confirm") or []):
    fail("sentences.en.json confirm_policy", "a slot cannot be both confirmed and never confirmed")
# the crisis follow-up is a two-way choice (keep going / stop), as in contracts/examples/edge_cases.json
for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
    e = (msgs.get("crisis.continue_or_stop") or {}).get("expect") or {}
    acts = [{k: v for k, v in ch.items() if k != "label"} for ch in (e.get("choices") or [])]
    if e.get("expect") != "choice" or e.get("keypad") != CRISIS_CHOICE or acts != list(CRISIS_CHOICE.values()):
        fail(f"sentences.{lang}.json crisis.continue_or_stop", "must be expect 'choice' with keep going (1) and stop (2)")
# interview timing is on the verification list (docs/SPEC.md): the waiting-for-interview line gives no day count
for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
    _iw = msgs.get("result.info.interview_waiting") or {}
    for _form in ("main", "closed", "short"):
        for _field, _vs in lists_of(_iw, _form).items():
            for _v in _vs:
                if re.search(r"\d|\b(?:thirty|treinta)\b", variant_text(_v), re.I):
                    fail(f"sentences.{lang}.json result.info.interview_waiting {_field}",
                         "interview timing is unverified: no day count")

# ------------------------------------------------------------------ 2. word budgets
def budget_class(keys, spoken_text):
    if keys and keys[0] == "consent.ask":
        return "opening"
    if any(k.startswith(RESULT_KEY_PREFIXES) for k in keys) or CONTACT_WORDS.search(spoken_text):
        return "result"
    return "question"


def phone_variants(key, form="main"):
    msg = MSG_EN.get(key) or {}
    return pick(msg, form, "phone")


BUDGET_ROWS = []


def check_composition(label, parts, values=None, budget=None):
    """parts: list of (key, form) or (key, form, {var: (qkey, qform)}). Every variant combination must fit."""
    values = dict(SPOKEN["en"], **(values or {}))
    if len(parts) > 1 and any(p[0] == "readback.cash" for p in parts):
        fail(f"budget {label}", "readback.cash is never spoken after the cash answer")
    choices = []
    for part in parts:
        key, form = part[0], part[1]
        qspec = part[2] if len(part) > 2 else None
        variants = phone_variants(key, form)
        if not variants:
            fail(f"budget {label}", f"{key} has no phone {form} variants")
            return
        expanded = []
        for v in variants:
            text = variant_text(v)
            if qspec:
                for qv in phone_variants(*qspec["question"]):
                    qtext = qv.get("ask", "") if isinstance(qv, dict) else qv
                    expanded.append(render(text.replace("{question}", qtext), values))
            else:
                expanded.append(render(text, values))
        choices.append(expanded)
    worst = 0
    worst_text = ""
    keys = [p[0] for p in parts]
    for combo in itertools.product(*choices):
        text = " ".join(combo)
        cls = budget or budget_class(keys, text)
        n = count_words(text)
        if n > WORD_BUDGETS[cls]:
            fail(f"budget {label}", f"{n} words > {cls} {WORD_BUDGETS[cls]}: {text!r}")
            return
        if n > worst:
            worst, worst_text = n, text
    BUDGET_ROWS.append((label, worst, budget or budget_class(keys, worst_text)))


ASK_KEYS = [k for k in MSG_EN if "expect" in MSG_EN[k]]
for key in MSG_EN:
    if key.startswith("line.") or "phone" not in (MSG_EN[key].get("channels") or []):
        continue
    if any("{question}" in variant_text(v) for v in phone_variants(key)):
        continue
    check_composition(key, [(key, "main")])
for q in ASK_KEYS:
    check_composition(f"{q} closed", [(q, "closed")])
    check_composition(f"{q} short", [(q, "short")])
    if q in ("consent.ask",):
        continue
    qclass_result = q.startswith(RESULT_KEY_PREFIXES)
    if not qclass_result:
        check_composition(f"ack + {q}", [("ack.short", "main"), (q, "main")])
    check_composition(f"silence 1 + {q}", [("reprompt.silence_1", "main", {"question": (q, "main")})])
    check_composition(f"silence 2 + {q} closed", [("reprompt.silence_2", "main", {"question": (q, "closed")})])
    check_composition(f"unclear + {q} closed", [("reprompt.unclear", "main", {"question": (q, "closed")})])
    check_composition(f"interrupt + {q}", [("reprompt.after_interrupt", "main", {"question": (q, "main")})])
    for g in ("answer.is_ai", "answer.is_recorded", "language.unsupported", "proxy.caller", "abuse.warn",
              "delete.cancelled", "apply_for_me", "immigration.question", "food_today", "side_question.noted",
              "info.previously_denied", "result.info.already_receiving", "result.info.interview_waiting"):
        check_composition(f"{g} + {q} short", [(g, "main"), (q, "short")])
    for g in ("ssn.block", "card_number.block"):
        check_composition(f"{g} + {q} short", [(g, "main", {"question": (q, "short")})])
for g in ("answer.is_ai", "answer.is_recorded"):
    check_composition(f"{g} + consent.reask", [(g, "main"), ("consent.reask", "main")])
check_composition("silence 1 + consent", [("reprompt.silence_1", "main", {"question": ("consent.ask", "short")})])
check_composition("consent.ask demo", [("consent.ask", "demo")])
# read-backs in phase order (long money values)
for rb, nexts in (("readback.earned", ["ask.other_cash", "ask.rent", "ask.homeless_cost"]),
                  ("readback.hourly", ["ask.other_cash", "ask.rent", "ask.homeless_cost"]),
                  ("readback.other_cash", ["ask.rent", "ask.homeless_cost"]),
                  ("readback.rent", ["flip.rent_paid_by_others", "flip.heat_cool", "flip.other_utils",
                                     "flip.household_food", "flip.other_cash_band", "flip.earned_split"])):
    for nq in nexts:
        check_composition(f"{rb} + {nq}", [(rb, "main"), (nq, "main")])
for fq in ("flip.rent_paid_by_others", "flip.heat_cool", "flip.household_food", "flip.earned_split"):
    check_composition(f"readback.rent + flip.intro + {fq}", [("readback.rent", "main"), ("flip.intro", "main"), (fq, "main")])
for fq in ("flip.rent_paid_by_others", "flip.rent_paid_by_others_amount", "flip.heat_cool", "flip.other_utils",
           "flip.household_food", "flip.other_cash_band", "flip.earned_split"):
    check_composition(f"ack + flip.intro + {fq}", [("ack.short", "main"), ("flip.intro", "main"), (fq, "main")])
# results
check_composition("readback.rent + result + cash question", [("readback.rent", "main"), ("result.likely", "main"), ("expedited.intro_cash", "main")])
check_composition("result + cash question", [("result.likely", "main"), ("expedited.intro_cash", "main")])
check_composition("floor + cash question", [("result.likely_floor", "main"), ("expedited.intro_cash", "main")])
check_composition("result + abawd + cash question", [("result.likely", "main"), ("result.note.abawd", "main"), ("expedited.intro_cash", "main")])
check_composition("apply + screen card + anything else", [("first_month.apply_today", "main"), ("card.phone_screen", "main"), ("close.anything_else", "main")])
check_composition("expedited yes + apply + code card", [("expedited.yes", "main"), ("first_month.apply_today", "main"), ("card.phone_code", "main")])
check_composition("cash answer: expedited yes + apply + screen card", [("expedited.yes", "main"), ("first_month.apply_today", "main"), ("card.phone_screen", "main")])
check_composition("expedited maybe + apply + screen card", [("expedited.maybe", "main"), ("first_month.apply_today", "main"), ("card.phone_screen", "main")])
check_composition("abawd + apply + code card", [("result.note.abawd", "main"), ("first_month.apply_today", "main"), ("card.phone_code", "main")])
for code in REASON_CODES:
    group = code.split(".")[0]
    if code == "coordinator.parent_household":   # no apply-today line: the student applies as the parents' household
        check_composition(f"{code} + screen card", [(f"result.{code}", "main"), ("card.phone_screen", "main")])
        check_composition(f"{code} + code card", [(f"result.{code}", "main"), ("card.phone_code", "main")])
    elif group == "coordinator":
        check_composition(f"{code} + apply + screen card", [(f"result.{code}", "main"), ("first_month.apply_today", "main"), ("card.phone_screen", "main")])
        check_composition(f"{code} + apply", [(f"result.{code}", "main"), ("first_month.apply_today", "main")])
    elif group == "other_help":
        check_composition(f"{code} + screen card", [(f"result.{code}", "main"), ("card.phone_screen", "main")])
check_composition("coordinator generic + apply + screen card", [("result.coordinator.generic", "main"), ("first_month.apply_today", "main"), ("card.phone_screen", "main")])
check_composition("other_help generic + screen card", [("result.other_help.generic", "main"), ("card.phone_screen", "main")])
check_composition("code card + anything else", [("card.phone_code", "main"), ("close.anything_else", "main")])
check_composition("crisis", [("crisis.resources", "main"), ("crisis.continue_or_stop", "main")])
# golden demo dialogue maria_g1 (screen delivery) with its real values
MARIA = {"amount": "nine hundred dollars"}
check_composition("maria opening", [("consent.ask", "main")], budget="opening")
for i, q in enumerate(["ask.level_units", "ask.age_parent", "ask.household_food_roommates", "ask.income"]):
    check_composition(f"maria turn {i + 2}", [("ack.short", "main"), (q, "main")])
check_composition("maria income read-back", [("readback.earned", "main"), ("ask.rent", "main")], MARIA)
check_composition("maria flip reply: readback.rent + flip.intro + flip.rent_paid_by_others", [("readback.rent", "main"), ("flip.intro", "main"), ("flip.rent_paid_by_others", "main")], {"amount": "eleven hundred dollars"})
check_composition("maria result", [("result.likely", "main"), ("expedited.intro_cash", "main")], {"amount": "three hundred six dollars"})
check_composition("maria card", [("first_month.apply_today", "main"), ("card.phone_screen", "main"), ("close.anything_else", "main")])
check_composition("maria goodbye", [("close.goodbye", "main")])
# Spanish phone notice
for v in pick(MSG_ES.get("language.offer_web") or {}, "main", "phone"):
    t = render(variant_text(v), SPOKEN["es"])
    if count_words(t) > WORD_BUDGETS["question"]:
        fail("sentences.es.json language.offer_web", f"{count_words(t)} words > question budget 25")

# ------------------------------------------------------------------ 3. guards
gin = GUARDS.get("input", {})
red = gin.get("redact", {})
RX = {}
for kind in ("card_patterns", "ssn_patterns"):
    RX[kind] = []
    for pat in red.get(kind, []):
        try:
            RX[kind].append(re.compile(pat, re.I))
        except re.error as exc:
            fail("guards.json", f"{kind} regex {pat!r}: {exc}")
SPOKEN_RX = {}
for lang in ("en", "es"):
    SPOKEN_RX[lang] = []
    for pat in red.get("spoken_digit_patterns", {}).get(lang, []):
        try:
            SPOKEN_RX[lang].append(re.compile(pat, re.I))
        except re.error as exc:
            fail("guards.json", f"spoken digit regex {pat!r}: {exc}")
if red.get("spoken_digit_run_min") != 7:
    fail("guards.json", "spoken_digit_run_min must be 7 (docs/BRAIN_API.md, privacy)")
KW = {}
REQUIRED_INTENTS = ["crisis", "human_request", "stop", "delete_data", "language_request", "hold", "abuse"]
for intent, langs in gin.get("keywords", {}).items():
    if intent not in INTENTS:
        fail("guards.json", f"keyword group {intent!r} is not an intent")
    for lang in ("en", "es"):
        pats = langs.get(lang) or []
        if not pats:
            fail("guards.json", f"keywords {intent}.{lang} is empty")
        for pat in pats:
            try:
                KW.setdefault((intent, lang), []).append(re.compile(pat, re.I))
            except re.error as exc:
                fail("guards.json", f"keyword regex {intent}.{lang} {pat!r}: {exc}")
for intent in REQUIRED_INTENTS:
    if intent not in gin.get("keywords", {}):
        fail("guards.json", f"missing keyword group {intent}")


SPOKEN_DIGIT_WORDS = {lang: {w.lower() for w in red.get("spoken_digit_words", {}).get(lang, [])} for lang in ("en", "es")}
CARD_WORDS_RX = {lang: [re.compile(p, re.I) for p in red.get("masked_card_words", {}).get(lang, [])] for lang in ("en", "es")}
_spoken_card = red.get("spoken_card_digits") or [0, 0]
if _spoken_card != [13, 19]:
    fail("guards.json", "spoken_card_digits must be [13, 19] (card-like runs, docs/BRAIN_API.md)")
if not CARD_WORDS_RX["en"] or not CARD_WORDS_RX["es"]:
    fail("guards.json", "masked_card_words needs en and es patterns (a masked run carries no digit count)")


def redact_kind(text, lang, masked=False):
    """'card_number', 'ssn' or None: the kind the input guard records for one utterance."""
    t = norm(text)
    if any(rx.search(t) for rx in RX["card_patterns"]):
        return "card_number"
    if any(rx.search(t) for rx in RX["ssn_patterns"]):
        return "ssn"
    for rx in SPOKEN_RX.get(lang, []):
        m = rx.search(t)
        if m:
            tokens = re.findall(r"[^\W\d_]+|\d", m.group(0).lower())
            n = sum(1 for tok in tokens if tok in SPOKEN_DIGIT_WORDS.get(lang, set()) or tok.isdigit())
            return "card_number" if _spoken_card[0] <= n <= _spoken_card[1] else "ssn"
    if masked:   # the gateway's '#' run carries no digit count: a card or bank word decides the kind
        return "card_number" if any(rx.search(t) for rx in CARD_WORDS_RX.get(lang, [])) else "ssn"
    return None


def keyword_intents(text, lang):
    t = norm(text).lower()
    return sorted({intent for (intent, kl), rxs in KW.items() if kl == lang and any(rx.search(t) for rx in rxs)})


# routing: which reply key one utterance gets (intent precedence, redaction, close phase)
ROUTING = gin.get("routing", {})
PRECEDENCE = ROUTING.get("precedence", [])
ROUTE_REPLY = ROUTING.get("reply", {})
CLOSE = ROUTING.get("close_phase", {})
CLOSE_DONE = {}
for lang in ("en", "es"):
    CLOSE_DONE[lang] = []
    for pat in (CLOSE.get("done") or {}).get(lang, []):
        try:
            CLOSE_DONE[lang].append(re.compile(pat, re.I))
        except re.error as exc:
            fail("guards.json", f"close_phase.done regex {pat!r}: {exc}")
if set(PRECEDENCE) != (set(INTENTS) - {"correction", "dont_know", "mentions_financial_aid", "off_topic", "ssn_attempt"}) | {"redaction"}:
    fail("guards.json routing", "precedence must list every reply-changing intent once, plus 'redaction'")
if len(PRECEDENCE) != len(set(PRECEDENCE)):
    fail("guards.json routing", "precedence lists an intent twice")
_order = {name: i for i, name in enumerate(PRECEDENCE)}
for _a, _b in (("crisis", "redaction"), ("redaction", "delete_data"), ("delete_data", "stop"), ("stop", "human_request"),
               ("human_request", "is_ai"), ("is_ai", "language_request"), ("language_request", "hold"),
               ("hold", "abuse"), ("abuse", "repeat")):
    if _a in _order and _b in _order and _order[_a] > _order[_b]:
        fail("guards.json routing", f"{_a} must come before {_b} (docs/SPEC.md global intents; delete before stop)")
for _name in PRECEDENCE:
    _rep = ROUTE_REPLY.get(_name)
    _keys = list(_rep.values()) if isinstance(_rep, dict) else [_rep]
    for _k in _keys:
        if _k != "repeat" and _k not in MSG_EN:
            fail("guards.json routing", f"reply for {_name} is not a sentence key: {_k!r}")
if CLOSE.get("pending") != "close.anything_else" or CLOSE.get("reply") != "close.goodbye" \
        or CLOSE.get("stop_becomes") != "close.goodbye":
    fail("guards.json routing", "close_phase: at close.anything_else a stop or a done phrase gives close.goodbye")
for _intent in ("stop", "abuse"):
    for _lang in ("en", "es"):
        for _rx in KW.get((_intent, _lang), []):
            if re.search(r"that.?s all|eso es todo", _rx.pattern, re.I):
                fail("guards.json", f"'that's all' must not be a {_intent} keyword")


def route(text, lang, pending=None, masked=False):
    """The reply key the input guard alone would pick, or None (the phase machine and the model decide)."""
    kind = redact_kind(text, lang, masked)
    intents = set(keyword_intents(text, lang))
    at_close = pending is not None and pending == CLOSE.get("pending")
    for name in PRECEDENCE:
        if name == "redaction":
            if kind or "ssn_attempt" in intents:  # a question about a Social Security number gets the same guidance
                return (ROUTE_REPLY.get("redaction") or {}).get(kind or "ssn")
        elif name in intents:
            if name == "stop" and at_close:
                return CLOSE.get("stop_becomes")
            return ROUTE_REPLY.get(name)
    if at_close and any(rx.search(norm(text)) for rx in CLOSE_DONE.get(lang, [])):
        return CLOSE.get("reply")
    return None


tests = GUARDS.get("tests", {})
for case in tests.get("redact", []):
    got = redact_kind(case["text"], case["lang"], case.get("masked", False))
    if got != case["expect"]:
        fail("guards.json tests.redact", f"{case['text']!r}: got {got}, expected {case['expect']}")
for case in tests.get("keywords", []):
    got = keyword_intents(case["text"], case["lang"])
    if got != sorted(case["expect"]):
        fail("guards.json tests.keywords", f"{case['text']!r}: got {got}, expected {sorted(case['expect'])}")
for case in tests.get("routing", []):
    got = route(case["text"], case["lang"], case.get("pending"), case.get("masked", False))
    if got != case["expect"]:
        fail("guards.json tests.routing", f"{case['text']!r} (pending {case.get('pending')}): got {got}, expected {case['expect']}")
# the routing rulings each have a vector
_ROUTING_RULINGS = [
    ("is_ai, not human_request", lambda c: c["expect"] == "answer.is_ai" and "real person" in c["text"].lower()),
    ("hold phrase", lambda c: c["expect"] == "hold.ok" and c["lang"] == "es"),
    ("bare espera is not hold", lambda c: c["expect"] is None and "espera," in c["text"].lower()),
    ("indirect crisis en", lambda c: c["expect"] == "crisis.resources" and "point of living" in c["text"]),
    ("indirect crisis es", lambda c: c["expect"] == "crisis.resources" and "sentido a vivir" in c["text"]),
    ("13-19 digits = card_number", lambda c: c["expect"] == "card_number.block"),
    ("9 digits = ssn", lambda c: c["expect"] == "ssn.block"),
    ("that's all at close", lambda c: c["expect"] == "close.goodbye" and "that's all" in c["text"].lower()),
    ("delete before stop", lambda c: c["expect"] == "delete.confirm_ask" and "hang up" in c["text"]),
]
for _label, _pred in _ROUTING_RULINGS:
    if not any(_pred(c) for c in tests.get("routing", [])):
        fail("guards.json tests.routing", f"no vector for the routing rule: {_label}")
for case in tests.get("output_block", []):
    if not forbidden_hits(case["text"]):
        fail("guards.json tests.output_block", f"not blocked: {case['text']!r}")
for case in tests.get("output_pass", []):
    hits = forbidden_hits(case["text"])
    if hits:
        fail("guards.json tests.output_pass", f"blocked {case['text']!r}: {hits}")
# the redaction and keyword rules against the shared utterance file
UTTERANCE_COUNT = 0
_kw_groups = {i for i, _l in KW}
if UTTERANCES.exists():
    for _n, _line in enumerate(UTTERANCES.read_text(encoding="utf-8").splitlines(), 1):
        if not _line.strip():
            continue
        try:
            _u = json.loads(_line)
            _text, _lang, _exp = _u["utterance"], _u["lang"], _u["expect"]
        except (ValueError, KeyError) as exc:
            fail("utterances.jsonl", f"line {_n} unreadable: {exc}")
            continue
        UTTERANCE_COUNT += 1
        _want = (_exp.get("redactions") or [None])[0]
        _got = redact_kind(_text, _lang, bool(_u.get("masked")))
        if _got != _want:
            fail("guards.json redaction vs utterances.jsonl", f"{_u.get('id')}: got {_got}, expected {_want}")
        _hits = set(keyword_intents(_text, _lang))
        _ok = set(_exp.get("intents") or []) | set(_u.get("allow_extra_intents") or [])
        if _hits - _ok:
            fail("guards.json keywords vs utterances.jsonl", f"{_u.get('id')}: keywords add {sorted(_hits - _ok)} to {_text!r}")
        _missed = (set(_exp.get("intents") or []) & _kw_groups) - _hits
        if "crisis" in _missed:
            fail("guards.json keywords vs utterances.jsonl", f"{_u.get('id')}: crisis keywords miss {_text!r}")
        elif _missed:
            NOTES.append(f"utterances.jsonl {_u.get('id')}: keywords miss {sorted(_missed)} (the model covers it)")
else:
    NOTES.append("data/tests/utterances.jsonl not found: utterance vectors skipped")
# the fixed text of a reply never looks like a number the input guard would redact
for lang, msgs in (("en", MSG_EN), ("es", MSG_ES)):
    for key, msg in msgs.items():
        if key in ("line.fatal", "line.fatal_start", "line.line_unavailable"):
            continue  # these say the coordinator's number in words on purpose
        for form in FORMS:
            for field, variants in lists_of(msg, form).items():
                for v in variants:
                    t = PLACEHOLDER.sub("X", variant_text(v))
                    if redact_kind(t, lang):
                        fail(f"sentences.{lang}.json {key}", "fixed text looks like a redactable number run")

# ------------------------------------------------------------------ 4. card
# One block order for every card, and the blocks each tier or route shows (docs/SPEC.md, student card blocks).
BLOCK_ORDER = ["today_action", "expedited", "why", "answer_sheet", "documents", "interview", "after_approval",
               "food_today", "contact"]
BLOCK_TONES = {"default", "accent", "warning", "muted"}   # CardBlock.tone
# tone and starting state (CardBlock.collapsed) per block, as in docs/SPEC.md (student card blocks)
BLOCK_STYLE = {
    "today_action": ("accent", False), "expedited": ("accent", False), "why": ("default", False),
    "answer_sheet": ("default", False), "documents": ("default", True), "interview": ("default", True),
    "after_approval": ("default", True), "food_today": ("muted", False), "contact": ("default", False),
}
ROUTE_BLOCKS = {
    "likely": BLOCK_ORDER,                                   # expedited only for an outlook of yes or maybe
    "coordinator": ["today_action", "why", "answer_sheet", "documents", "interview", "food_today", "contact"],
    "coordinator.parent_household": ["why", "food_today", "contact"],
    "other_help": ["why", "food_today", "contact"],
    "info.already_receiving": ["why", "after_approval", "contact"],
    "info.interview_waiting": ["why", "interview", "contact"],
    None: ["food_today", "contact"],                          # call ended before a result
}
TIERS = ["likely", "coordinator", "other_help"]
FLAGS = {"abawd_possible", "ta_ra_income_type", "income_changing_soon"}
LEVELS = {"undergrad", "grad", "not_degree", "not_sfsu"}
CARD_FACTS = {"first_month", "case_code"}
SLOT_VALUES = {
    "half_time": {"true", "false"}, "household_food": {"alone", "separate", "shared"},
    "grad_exemption": {"campus_job", "ta_ra", "work_study", "work20h", "child_under_6", "child_6_to_11_no_care",
                       "single_parent_full_time_child_under_12", "dor_wioa", "calworks", "final_term",
                       "under_half_time", "none"},
    "heat_cool": {"true", "false"}, "other_utils": {"none", "phone_only", "two_plus"},
    "already_receiving": {"true", "false"}, "applied_waiting_interview": {"true", "false"},
    "previously_denied": {"true", "false"}, "roommates": {"true", "false"},
}


def check_when(where, w):
    if not isinstance(w, dict):
        fail(where, "when must be an object")
        return
    allowed = set(CARD_EN.get("when_keys", {}))
    for k, v in w.items():
        if k not in allowed:
            fail(where, f"unknown when key {k!r}")
        elif k == "tier" and not set(v) <= set(TIERS):
            fail(where, f"bad tier {v}")
        elif k == "reason" and not set(v) <= set(REASON_CODES):
            fail(where, f"bad reason {v}")
        elif k == "expedited" and not set(v) <= {"yes", "maybe", "no"}:
            fail(where, f"bad expedited {v}")
        elif k == "level" and not set(v) <= LEVELS:
            fail(where, f"bad level {v}")
        elif k == "flag" and not set(v) <= FLAGS:
            fail(where, f"bad flag {v}")
        elif k in ("homeless", "irt_applies", "at_max") and not isinstance(v, bool):
            fail(where, f"{k} must be true or false")
        elif k in ("has", "answered", "positive", "zero"):
            for s in (v if isinstance(v, list) else [v]):
                if s not in SLOTS and not (k == "has" and s in CARD_FACTS):
                    fail(where, f"{k} uses unknown slot {s!r}")
        elif k == "slot":
            for s, vals in v.items():
                if s not in SLOTS:
                    fail(where, f"slot condition on unknown slot {s!r}")
                elif s in SLOT_VALUES and not set(vals) <= SLOT_VALUES[s]:
                    fail(where, f"slot {s} values {vals} not canonical")
        elif k == "not":
            for sub in (v if isinstance(v, list) else [v]):
                check_when(where + " not", sub)


def card_strings(card):
    """(where, text) for every student-facing string of a card file."""
    out = []
    for k, v in card.get("headline", {}).items():
        out.append((f"headline.{k}", v))
    for k, v in card.get("subhead", {}).items():
        out.append((f"subhead.{k}", v))
    for b in card.get("blocks", []):
        bid = b.get("id")
        out.append((f"{bid}.title", b.get("title", "")))
        for t, v in (b.get("title_by_tier") or {}).items():
            out.append((f"{bid}.title_by_tier.{t}", v))
        for t, v in (b.get("title_by_reason") or {}).items():
            out.append((f"{bid}.title_by_reason.{t}", v))
        if b.get("intro"):
            out.append((f"{bid}.intro", b["intro"]))
        for t, v in (b.get("columns") or {}).items():
            out.append((f"{bid}.columns.{t}", v))
        for i, it in enumerate(b.get("items", [])):
            out.append((f"{bid}.items[{i}]", it.get("text", "")))
        for i, r in enumerate(b.get("rows", [])):
            out.append((f"{bid}.rows[{i}].screen", r.get("screen", "")))
            out.append((f"{bid}.rows[{i}].question", r.get("question", "")))
            out.append((f"{bid}.rows[{i}].answer", r.get("answer", "")))
    for i, v in enumerate(card.get("footer", [])):
        out.append((f"footer[{i}]", v))
    ui = card.get("ui", {})
    for k, v in ui.items():
        if isinstance(v, str):
            out.append((f"ui.{k}", v))
        elif isinstance(v, dict):
            for kk, vv in v.items():
                out.append((f"ui.{k}.{kk}", vv))
        elif isinstance(v, list):
            for i, it in enumerate(v):
                for kk in ("title", "label"):
                    if kk in it:
                        out.append((f"ui.{k}[{i}].{kk}", it[kk]))
    # the card footer lists the sources, and the unverified notes travel with the card file
    for i, src in enumerate(card.get("sources", [])):
        for kk in ("title", "used_for"):
            if kk in src:
                out.append((f"sources[{i}].{kk}", src[kk]))
    for i, u in enumerate(card.get("unverified", [])):
        out.append((f"unverified[{i}].what", u.get("what", "")))
    return out


def check_card(card, lang):
    name = f"card.{lang}.json"
    if card.get("lang") != lang:
        fail(name, f"lang must be {lang!r}")
    ids = [b.get("id") for b in card.get("blocks", [])]
    if ids != BLOCK_ORDER:
        fail(name, f"blocks must be exactly {BLOCK_ORDER} in this order, got {ids}")
    for tier in TIERS + ["likely_floor"]:
        if tier not in card.get("headline", {}) or tier not in card.get("subhead", {}):
            fail(name, f"headline and subhead need {tier!r}")
    declared = set(card.get("placeholders", {}))
    src_ids = {s.get("id") for s in card.get("sources", [])}
    for b in card.get("blocks", []):
        where = f"{name} {b.get('id')}"
        check_when(where + " when", b.get("when"))
        if b.get("tone") not in BLOCK_TONES:
            fail(where, f"tone {b.get('tone')!r} must be one of {sorted(BLOCK_TONES)}")
        if b.get("id") in BLOCK_STYLE:
            want_tone, want_collapsed = BLOCK_STYLE[b["id"]]
            if b.get("tone") != want_tone:
                fail(where, f"tone must be {want_tone!r} (docs/SPEC.md, student card blocks)")
            if b.get("collapsed") is not want_collapsed:
                fail(where, f"collapsed must be {want_collapsed} (docs/SPEC.md, student card blocks)")
        for r in (b.get("title_by_reason") or {}):
            if r not in REASON_CODES:
                fail(where, f"title_by_reason uses an unknown reason code {r!r}")
        for sid in b.get("sources", []):
            if sid not in src_ids:
                fail(where, f"unknown source id {sid!r}")
        for i, it in enumerate(b.get("items", [])):
            check_when(f"{where} items[{i}]", it.get("when"))
        for i, r in enumerate(b.get("rows", [])):
            check_when(f"{where} rows[{i}]", r.get("when"))
            if not re.fullmatch(r"[A-Za-z —-]+", r.get("screen", "")):
                fail(f"{where} rows[{i}]", "BenefitsCal screen names stay in English")
    used = set()
    for where, text in card_strings(card):
        if not isinstance(text, str) or not text.strip():
            fail(f"{name} {where}", "empty string")
            continue
        for p in placeholders(text):
            used.add(p)
            if p not in declared:
                fail(f"{name} {where}", f"undeclared placeholder {{{p}}}")
        for hit in forbidden_hits(text):
            fail(f"{name} {where}", f"forbidden wording: {hit}")
    for p in sorted(declared - used):
        NOTES.append(f"{name}: placeholder {{{p}}} is declared but unused")
    # estimates sit next to 'estimate' and 'the county decides'
    est_word, county = ("estimate", "the county decides") if lang == "en" else ("estimación", "el condado decide")
    for tier in ("likely", "likely_floor"):
        h = card.get("headline", {}).get(tier, "")
        s = card.get("subhead", {}).get(tier, "").lower()
        if "{estimate}" not in h or est_word not in s or county not in s:
            fail(f"{name} {tier}", "the amount must sit next to 'estimate' and 'the county decides'")
    # IRT line rule (docs/SPEC.md, student card: after approval)
    after = next((b for b in card.get("blocks", []) if b.get("id") == "after_approval"), {})
    irt_true = [it for it in after.get("items", []) if it.get("when") == {"irt_applies": True}]
    irt_false = [it for it in after.get("items", []) if it.get("when") == {"irt_applies": False}]
    if len(irt_true) != 1 or "{irt}" not in irt_true[0]["text"]:
        fail(name, "after_approval needs one item for irt_applies true that shows {irt}")
    if len(irt_false) != 1 or "SAR 7" not in irt_false[0]["text"]:
        fail(name, "after_approval needs one item for irt_applies false that points to the SAR 7")
    for where, text in card_strings(card):
        if "{irt}" in text and not where.startswith("after_approval"):
            fail(f"{name} {where}", "{irt} may only appear in the IRT item")
    # source dates (ACL 15-42 is dated 2015-04-15) and sources referenced by blocks
    for src in card.get("sources", []):
        if src.get("id") == "ACL-15-42" and src.get("date") != "2015-04-15":
            fail(name, "source ACL-15-42 must be dated 2015-04-15")
        if src.get("date") not in ("current",) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{4}-\d{4}|page as saved \d{4}-\d{2}-\d{2}",
                                                                  str(src.get("date"))):
            fail(name, f"source {src.get('id')} needs a date")
    # SAR 7 days are approximate until verified: a day of the month next to SAR 7 says 'about'
    for where, text in card_strings(card):
        if "SAR" in text and re.search(r"\b(?:day|d[ií]a) \d+\b|\b\d+(?:st|nd|rd|th)\b", text, re.I) and \
                not re.search(r"\babout\b|\baround\b|m[aá]s o menos|aproximadamente", text, re.I):
            fail(f"{name} {where}", "SAR 7 days must be shown as approximate ('about')")
    # documents: 'usually not needed - keep them handy'
    docs = next((b for b in card.get("blocks", []) if b.get("id") == "documents"), {})
    keep = "Usually not needed — keep them handy" if lang == "en" else "Normalmente no hacen falta"
    if not any(keep in it.get("text", "") for it in docs.get("items", [])):
        fail(name, f"documents block must say {keep!r}")
    # interview timing is on the verification list (docs/SPEC.md): no day count for the call; only the
    # rights line keeps its 30-day decision (7 CFR 273.2) and the papers line its 'at least 10 days'
    interview = next((b for b in card.get("blocks", []) if b.get("id") == "interview"), {})
    for i, it in enumerate(interview.get("items", [])):
        t = it.get("text", "")
        if re.match(r"(?:Your rights|Tus derechos)\b", t):
            continue
        if re.search(r"\b\d+\s*(?:to|-|–|y)\s*\d+\s*(?:days?|d[ií]as)\b|\b(?:after|within|en|despu[eé]s de)\s+\d+\s*(?:days?|d[ií]as)\b",
                     t, re.I):
            fail(f"{name} interview items[{i}]", "interview timing is unverified: no day count for the call")


check_card(CARD_EN, "en")
check_card(CARD_ES, "es")


def structure(card):
    """Conditions and placeholders, language-independent."""
    out = []
    for b in card.get("blocks", []):
        out.append(("block", b.get("id"), json.dumps(b.get("when"), sort_keys=True), b.get("tone"), b.get("collapsed"),
                    b.get("verify"), tuple(b.get("sources", [])), tuple(sorted(b.get("title_by_tier") or {})),
                    tuple(sorted(b.get("title_by_reason") or {}))))
        for it in b.get("items", []):
            out.append(("item", json.dumps(it.get("when"), sort_keys=True), tuple(sorted(placeholders(it.get("text", "")))),
                        it.get("verify"), it.get("rule")))
        for r in b.get("rows", []):
            out.append(("row", json.dumps(r.get("when"), sort_keys=True), r.get("screen"),
                        tuple(sorted(placeholders(r.get("answer", ""))))))
    for k in ("headline", "subhead"):
        for t, v in card.get(k, {}).items():
            out.append((k, t, tuple(sorted(placeholders(v)))))
    out.append(("footer", len(card.get("footer", []))))
    out.append(("ui", tuple(sorted(card.get("ui", {})))))
    return out


if structure(CARD_EN) != structure(CARD_ES):
    for a, b in zip(structure(CARD_EN), structure(CARD_ES)):
        if a != b:
            fail("card en/es", f"structure differs: {a} vs {b}")
            break
    else:
        fail("card en/es", "structure differs in length")
if CARD_EN.get("placeholders") != CARD_ES.get("placeholders") or CARD_EN.get("when_keys") != CARD_ES.get("when_keys"):
    fail("card en/es", "placeholders and when_keys must be identical")

# sample cards for personas: evaluate conditions, fill placeholders, check the result
def truthy(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("false", "none", "", "0", "0.00"):
        return False
    try:
        return float(s) > 0
    except ValueError:
        return True


def zeroish(v):
    return v is not None and not truthy(v)


def when_true(w, ctx):
    for k, v in w.items():
        slots = ctx["slots"]
        if k == "tier" and ctx["tier"] not in v:
            return False
        if k == "reason" and ctx.get("reason") not in v:
            return False
        if k == "expedited" and ctx.get("expedited") not in v:
            return False
        if k == "level" and slots.get("level") not in v:
            return False
        if k == "homeless" and truthy(slots.get("homeless")) != v:
            return False
        if k in ("irt_applies", "at_max") and ctx.get(k) is not v:
            return False
        if k == "flag" and not set(v) & set(ctx.get("flags", [])):
            return False
        names = v if isinstance(v, list) else [v]
        if k == "has" and not all((slots.get(s) is not None) or (s in ctx.get("facts", {})) for s in names):
            return False
        if k == "answered" and not all(s in ctx.get("answered", set()) for s in names):
            return False
        if k == "positive" and not all(truthy(slots.get(s)) for s in names):
            return False
        if k == "zero" and not all(zeroish(slots.get(s)) for s in names):
            return False
        if k == "slot" and not all(str(slots.get(s)).lower() in vals for s, vals in v.items()):
            return False
        if k == "not" and any(when_true(sub, ctx) for sub in (v if isinstance(v, list) else [v])):
            return False
    return True


def money(v):
    return "${:,.0f}".format(float(v))


PERSONAS = {
    "maria_g1": dict(tier="likely", reason="likely", expedited="no", irt_applies=True, at_max=True, flags=[],
                     estimate=306, facts={"first_month": 296, "case_code": "K7Q-2FM"},
                     answered={"rent_paid_by_others_to_landlord", "household_food"},
                     slots=dict(level="undergrad", units="12", half_time="true", age="20", household_food="separate",
                                roommates="true", earned_monthly="900.00", other_cash_monthly="0.00", rent_share="1100.00",
                                rent_paid_by_others_to_landlord="0.00", heat_cool="false", other_utils="none",
                                cash_on_hand="1000.00", homeless="false"),
                     expect_in=["$1,729", "$306", "$296"], expect_blocks=["today_action", "answer_sheet", "interview", "after_approval"],
                     expect_out=["Help within 3 days"]),
    "sofia_g3": dict(tier="coordinator", reason="coordinator.parent_household", expedited=None, irt_applies=None,
                     at_max=False, flags=[], estimate=None, facts={"case_code": "S4F-9Q2"}, answered=set(),
                     slots=dict(level="undergrad", units="12", half_time="true", age="19", lives_with_parent="true"),
                     expect_in=["under 22", "Talk to the SF State CalFresh coordinator first"],
                     expect_blocks=["why", "food_today", "contact"],
                     expect_absent_blocks=["today_action", "expedited", "answer_sheet", "documents", "interview",
                                           "after_approval"]),
    "shared_g2": dict(tier="coordinator", reason="coordinator.shared_household", expedited=None, irt_applies=None,
                      at_max=False, flags=[], estimate=None, facts={"case_code": "H2S-4KD"}, answered=set(),
                      slots=dict(level="undergrad", units="12", half_time="true", age="21", roommates="true",
                                 household_food="shared", earned_monthly="1200.00", rent_share="1000.00",
                                 homeless="false"),
                      expect_in=["List everyone you buy and cook food with", "Apply on BenefitsCal"],
                      expect_blocks=["today_action", "why", "answer_sheet", "documents", "interview"],
                      expect_absent_blocks=["expedited", "after_approval"]),
    "already_receiving": dict(tier="likely", reason="info.already_receiving", expedited=None, irt_applies=None,
                              at_max=False, flags=[], estimate=None, facts={}, answered=set(),
                              slots=dict(level="undergrad", already_receiving="true"),
                              expect_in=["You already get CalFresh", "SAR 7", "What to keep up"],
                              expect_blocks=["why", "after_approval", "contact"],
                              expect_absent_blocks=["today_action", "answer_sheet", "documents", "interview",
                                                    "food_today"]),
    "interview_waiting": dict(tier=None, reason="info.interview_waiting", expedited=None, irt_applies=None,
                              at_max=False, flags=[], estimate=None, facts={}, answered=set(),
                              slots=dict(level="undergrad", applied_waiting_interview="true"),
                              expect_in=["Get ready for your phone interview", "Unknown"],
                              expect_blocks=["why", "interview", "contact"],
                              expect_absent_blocks=["today_action", "answer_sheet", "documents", "after_approval",
                                                    "food_today"]),
    "incomplete": dict(tier=None, reason=None, expedited=None, irt_applies=None, at_max=False, flags=[],
                       estimate=None, facts={}, answered=set(), slots=dict(level="undergrad"),
                       expect_in=["We didn't finish your check", "Gator Groceries"],
                       expect_blocks=["food_today", "contact"],
                       expect_absent_blocks=["today_action", "why", "answer_sheet", "documents", "interview",
                                             "after_approval", "expedited"]),
    # the call ended before a result, but the student had already said undergrad and 8+ units: `why` still
    # needs a reason code, so its student-rule item must not pull the block onto the card
    "incomplete_half_time": dict(tier=None, reason=None, expedited=None, irt_applies=None, at_max=False, flags=[],
                                 estimate=None, facts={}, answered=set(),
                                 slots=dict(level="undergrad", half_time="true"),
                                 expect_in=["We didn't finish your check", "Gator Groceries"],
                                 expect_blocks=["food_today", "contact"],
                                 expect_absent_blocks=["today_action", "why", "answer_sheet", "documents",
                                                       "interview", "after_approval", "expedited"]),
    "jamal_g4": dict(tier="likely", reason="likely", expedited="yes", irt_applies=True, at_max=True, flags=[],
                     estimate=306, facts={"first_month": 296, "case_code": "J4M-7RT"},
                     answered={"homeless_shelter_cost_monthly"},
                     slots=dict(level="undergrad", units="12", half_time="true", age="24", homeless="true",
                                homeless_shelter_cost_monthly="0.00", household_food="alone", earned_monthly="0.00",
                                other_cash_monthly="0.00", rent_share="0.00", cash_on_hand="40.00"),
                     expect_in=["within 3 days", "No proof of address"], expect_blocks=["expedited"]),
    "f1_g5": dict(tier="other_help", reason="other_help.status", expedited=None, irt_applies=None, at_max=False,
                  flags=[], estimate=None, facts={}, answered=set(), slots=dict(level="undergrad", age="21"),
                  expect_in=["Gator Groceries"], expect_absent_blocks=["today_action", "answer_sheet", "documents",
                                                                       "interview", "after_approval", "expedited"]),
    "grad_ta_g6b": dict(tier="likely", reason="likely", expedited="no", irt_applies=False, at_max=False,
                        flags=["ta_ra_income_type"], estimate=55, facts={"first_month": 53},
                        answered={"heat_cool", "other_utils"},
                        slots=dict(level="grad", grad_exemption="ta_ra", half_time="true", age="26", household_food="alone",
                                   earned_monthly="1800.00", rent_share="1000.00", heat_cool="false", other_utils="none",
                                   cash_on_hand="2500.00", homeless="false"),
                        expect_in=["TA or RA", "SAR 7"], expect_out=["$1,729"]),
    "boundary_g8": dict(tier="likely", reason="likely", expedited="no", irt_applies=False, at_max=False, flags=[],
                        estimate=25, facts={"first_month": 24},
                        answered=set(), slots=dict(level="undergrad", half_time="true", household_food="alone",
                                                   earned_monthly="2660.00", rent_share="1100.00", homeless="false"),
                        expect_in=["Report all your income on your SAR 7"], expect_out=["$1,729"]),
    "parent_cash_g10": dict(tier="likely", reason="likely", expedited="no", irt_applies=True, at_max=False, flags=[],
                            estimate=106, facts={"first_month": 102}, answered={"heat_cool", "rent_paid_by_others_to_landlord"},
                            slots=dict(level="undergrad", half_time="true", household_food="alone", earned_monthly="1200.00",
                                       other_cash_monthly="300.00", rent_share="900.00", heat_cool="false",
                                       rent_paid_by_others_to_landlord="0.00", homeless="false"),
                            expect_in=["even if it's for school", "$1,729"]),
    "under_half_g11": dict(tier="likely", reason="likely", expedited="no", irt_applies=True, at_max=True,
                           flags=["abawd_possible"], estimate=306, facts={"first_month": 296},
                           answered=set(), slots=dict(level="undergrad", units="4", half_time="false", household_food="separate",
                                                      earned_monthly="900.00", rent_share="1100.00", homeless="false"),
                           expect_in=["A work rule may apply", "fewer than 8 units"]),
}


def card_values(ctx, lang):
    s = ctx["slots"]
    v = {
        "estimate": money(ctx["estimate"]) if ctx.get("estimate") is not None else "",
        "first_month": money(ctx["facts"]["first_month"]) if "first_month" in ctx["facts"] else "",
        "filed_on": "Fri, Oct 2" if lang == "en" else "vie 2 de oct",
        "month_label": "October" if lang == "en" else "octubre",
        "irt": "$1,729", "case_code": ctx["facts"].get("case_code", ""), "reviewed_at": "5:03 PM",
        "coordinator_phone": DISPLAY[lang]["coordinator_phone"], "coordinator_email": c("coordinator.email", ""),
        "coordinator_place": c(f"coordinator.place.{lang}", ""), "coordinator_hours": c(f"coordinator.hours.text.{lang}", ""),
        "county_phone": DISPLAY[lang]["county_phone"], "county_hours": c(f"county.hours.text.{lang}", ""),
        "ebt_phone": c("ebt_lost.display", ""), "pantry_url": "asi.sfsu.edu/gator-groceries",
        "meals_url": "basicneeds.sfsu.edu/emergency-meals",
    }
    for slot in ("earned_monthly", "gig_monthly", "unearned_monthly", "other_cash_monthly", "rent_share",
                 "rent_paid_by_others_to_landlord", "homeless_shelter_cost_monthly", "cash_on_hand"):
        v[slot] = money(s[slot]) if s.get(slot) is not None else ""
    return v


def render_card(card, ctx, lang):
    vals = card_values(ctx, lang)
    tier, reason = ctx["tier"], ctx.get("reason")
    shown, texts = [], []
    if reason in card.get("headline", {}):
        head_key = reason                       # info routes
    elif reason is None:
        head_key = "incomplete"                 # the call ended before a result
    elif ctx.get("floor"):
        head_key = "likely_floor"
    else:
        head_key = tier
    texts.append(card["headline"][head_key])
    texts.append(card["subhead"][head_key])
    for b in card["blocks"]:
        if not when_true(b.get("when", {}), ctx):
            continue
        items = [it["text"] for it in b.get("items", []) if when_true(it.get("when", {}), ctx)]
        rows = [r for r in b.get("rows", []) if when_true(r.get("when", {}), ctx)]
        if not items and not rows:
            continue
        shown.append(b["id"])
        title = (b.get("title_by_reason") or {}).get(reason) or (b.get("title_by_tier") or {}).get(tier) or b.get("title")
        texts.append(title)
        texts += items
        for r in rows:
            texts += [r["screen"], r["question"], r["answer"]]
    texts += card.get("footer", [])
    rendered = [render(t, vals) for t in texts]
    return shown, rendered


for pname, ctx in PERSONAS.items():
    for lang, card in (("en", CARD_EN), ("es", CARD_ES)):
        shown, rendered = render_card(card, ctx, lang)
        where = f"card.{lang}.json persona {pname}"
        for t in rendered:
            left = placeholders(t)
            if left:
                fail(where, f"unfilled placeholders {left} in {t!r}")
            if re.search(r"\$\s|\(\s*\)|\s[,.]", t) or "  " in t:
                fail(where, f"empty value or spacing problem in {t!r}")
            for hit in forbidden_hits(t):
                fail(where, f"forbidden wording: {hit}")
        if lang == "en":
            full = " ".join(rendered)
            for want in ctx.get("expect_in", []):
                if want not in full:
                    fail(where, f"expected text {want!r} not on the card")
            for want in ctx.get("expect_out", []):
                if want in full:
                    fail(where, f"text {want!r} must not be on the card")
            for bid in ctx.get("expect_blocks", []):
                if bid not in shown:
                    fail(where, f"block {bid} should show")
            for bid in ctx.get("expect_absent_blocks", []):
                if bid in shown:
                    fail(where, f"block {bid} should not show")
        if "contact" not in shown:
            fail(where, "contact block must always show")

# the block table per tier and route: which blocks show, in which order, for every reason code
for _reason in REASON_CODES + [None]:
    if _reason in ROUTE_BLOCKS:
        _want_base = ROUTE_BLOCKS[_reason]
    else:
        _want_base = ROUTE_BLOCKS[_reason.split(".")[0]]
    _tiers = [_reason.split(".")[0]] if _reason and _reason.split(".")[0] in TIERS else ["likely", "coordinator",
                                                                                          "other_help", None]
    for _tier in _tiers:
        for _exp in (None, "no", "yes", "maybe"):
            _want = [b for b in _want_base if b != "expedited" or _exp in ("yes", "maybe")]
            _ctx = dict(tier=_tier, reason=_reason, expedited=_exp, irt_applies=None, at_max=False, flags=[],
                        estimate=None, facts={}, answered=set(), slots={})
            for _lang, _card in (("en", CARD_EN), ("es", CARD_ES)):
                _shown, _ = render_card(_card, _ctx, _lang)
                if _shown != _want:
                    fail(f"card.{_lang}.json block table",
                         f"reason {_reason} (tier {_tier}, expedited {_exp}): shows {_shown}, expected {_want}")

# reading level (English): Flesch-Kincaid grade per block, 7 or lower
TERMS_2 = {"calfresh", "benefitscal", "gatorplate", "sf", "ebt", "sar", "as", "ta", "ra", "id", "qr", "pdf", "fy2027",
           "cesar", "chavez", "groceries"}


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if w in TERMS_2:
        return 2 if len(w) > 3 else 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(1, n)


def fk_grade(text):
    words = [w for w in re.split(r"\s+", text) if re.search(r"[A-Za-z]", w) and not re.search(r"\w[./]\w", w)]
    if not words:
        return 0.0
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    syl = sum(syllables(w) for w in words)
    return 0.39 * len(words) / sentences + 11.8 * syl / len(words) - 15.59


READING = []
for b in CARD_EN.get("blocks", []):
    parts = [it.get("text", "") for it in b.get("items", [])]
    parts += [r.get("answer", "") for r in b.get("rows", [])]
    text = " ".join(render(p, card_values(PERSONAS["maria_g1"], "en")) for p in parts)
    grade = fk_grade(text)
    READING.append((b.get("id"), grade))
    if grade > 7.0:
        fail(f"card.en.json {b.get('id')}", f"reading level grade {grade:.1f} > 7")
_all_web = []
for key, msg in MSG_EN.items():
    for v in pick(msg, "main", "web"):
        _all_web.append(render(variant_text(v), DISPLAY["en"]).replace("{question}", ""))
_sent_grade = fk_grade(" ".join(_all_web))
READING.append(("sentences.en web (all keys)", _sent_grade))
if _sent_grade > 7.0:
    fail("sentences.en.json", f"reading level grade {_sent_grade:.1f} > 7")

# ------------------------------------------------------------------ 5. contacts
DIGIT_WORDS = {
    "en": {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
           "eight": "8", "nine": "9"},
    "es": {"cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
           "ocho": "8", "nueve": "9"},
}
KNOWN_NUMBERS = set()
for entry in ("coordinator", "county", "ebt_lost"):
    node = CONTACTS.get(entry, {})
    phone = node.get("phone", "")
    if not re.fullmatch(r"\+1\d{10}", phone):
        fail(f"contacts.json {entry}", "phone must be E.164 (+1 and 10 digits)")
        continue
    digits = phone[2:]
    KNOWN_NUMBERS.add(digits)
    want_display = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if node.get("display") != want_display:
        fail(f"contacts.json {entry}", f"display must be {want_display}")
    for lang in ("en", "es"):
        spoken = (node.get("spoken") or {}).get(lang, "")
        got = "".join(DIGIT_WORDS[lang].get(w, "?") for w in re.findall(r"[a-z]+", spoken))
        if got != digits:
            fail(f"contacts.json {entry}", f"spoken.{lang} does not say {digits}")
        if phone_problems(spoken):
            fail(f"contacts.json {entry}", f"spoken.{lang} is not phone-safe")
for entry in ("coordinator", "county"):
    hours = CONTACTS.get(entry, {}).get("hours", {})
    if hours.get("timezone") != "America/Los_Angeles":
        fail(f"contacts.json {entry}", "hours.timezone must be America/Los_Angeles")
    for slot in hours.get("weekly", []):
        if not set(slot.get("days", [])) <= {"mon", "tue", "wed", "thu", "fri", "sat", "sun"} or \
                not re.fullmatch(r"\d\d:\d\d", slot.get("open", "")) or not re.fullmatch(r"\d\d:\d\d", slot.get("close", "")):
            fail(f"contacts.json {entry}", "hours.weekly entries need days, open HH:MM, close HH:MM")
    for lang in ("en", "es"):
        if not (hours.get("text") or {}).get(lang) or not (hours.get("spoken") or {}).get(lang):
            fail(f"contacts.json {entry}", f"hours.text.{lang} and hours.spoken.{lang} are required")
        elif phone_problems((hours.get("spoken") or {}).get(lang, "")):
            fail(f"contacts.json {entry}", f"hours.spoken.{lang} is not phone-safe")
_coord = CONTACTS.get("coordinator", {})
if _coord.get("email") != "calfresh@sfsu.edu":
    fail("contacts.json coordinator", "email must be calfresh@sfsu.edu")
if (_coord.get("source") or {}).get("checked") != "2026-10-01" or not (_coord.get("source") or {}).get("url"):
    fail("contacts.json coordinator", "hours need a source url and the checked date 2026-10-01")
_w = _coord.get("hours", {}).get("weekly", [])
if [(tuple(x["days"]), x["open"], x["close"]) for x in _w] != [(("mon", "tue", "wed", "thu"), "08:30", "17:00"), (("fri",), "08:30", "16:00")]:
    fail("contacts.json coordinator", "hours must be Mon-Thu 8:30-17:00 and Fri 8:30-16:00 (SF State Basic Needs page)")
for f in CONTACTS.get("food", []):
    if f.get("hours_text") not in (None,) and not (f.get("source") or {}).get("checked"):
        fail("contacts.json food", "hours need a source and date, or null")
    if not str(f.get("url", "")).startswith("https://"):
        fail("contacts.json food", "url must be https")
for crisis, num in (("lifeline", "988"), ("emergency", "911")):
    if (CONTACTS.get("crisis", {}).get(crisis) or {}).get("number") != num:
        fail("contacts.json crisis", f"{crisis} must be {num}")

# ------------------------------------------------------------------ 6. public hygiene (all six files)
HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff\uffa0-\uffdc]")  # Hangul Jamo, compatibility Jamo, extensions, syllables, half-width
LOCAL = re.compile(r"(/" + "Users" + r"/|/" + "home" + r"/[a-z]|[A-Z]:\\|" + "Desk" + "top/)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_LIKE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
for name in ("sentences.en.json", "sentences.es.json", "card.en.json", "card.es.json", "guards.json", "contacts.json",
             "programs.en.json", "programs.es.json", "check_content.py"):
    raw = (HERE / name).read_text(encoding="utf-8")
    if HANGUL.search(raw):
        fail(name, "contains Hangul")
    if LOCAL.search(raw):
        fail(name, "contains a local path")
    if name.endswith(".json"):
        for email in EMAIL.findall(raw):
            if email.lower() != "calfresh@sfsu.edu":
                fail(name, f"e-mail address not allowed: {email}")
        for m in PHONE_LIKE.finditer(raw):
            digits = re.sub(r"\D", "", m.group(0))[-10:]
            if digits not in KNOWN_NUMBERS and name != "guards.json":
                fail(name, f"phone number not in contacts.json: {m.group(0)}")


def walk_strings(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


# company names: the web opening may name the browser makers, because it discloses whose speech service turns the
# student's voice into text; nothing else in the content names them
BROWSER_NAMES = re.compile(r"\b(?:Google|Apple|Chrome|Safari)\b")
HEAT_WORDING = re.compile(r"\bheating\b(?! or (?:cooling|air conditioning|AC)\b)", re.I)
SAR_DAY = re.compile(r"\b(?:day|d[ií]a) \d+\b|\b\d+(?:st|nd|rd|th)\b|\b(?:fifth|eleventh|quinto|once)\b", re.I)
SAR_ABOUT = re.compile(r"\babout\b|\baround\b|m[aá]s o menos|aproximadamente|alrededor", re.I)
for name, data in (("sentences.en.json", EN), ("sentences.es.json", ES), ("card.en.json", CARD_EN),
                   ("card.es.json", CARD_ES), ("guards.json", GUARDS), ("contacts.json", CONTACTS),
                   ("programs.en.json", PROG_EN), ("programs.es.json", PROG_ES)):
    for path, text in walk_strings(data):
        if BROWSER_NAMES.search(text) and not path.startswith("messages.consent.ask.web["):
            fail(name, f"{path}: browser makers may be named only in the web opening disclosure")
        # the heating question and the skipped-question chip say 'heating or cooling', never 'heating bill' alone
        if name.endswith(".en.json") and HEAT_WORDING.search(text):
            fail(name, f"{path}: say 'heating or cooling', not 'heating' alone")
        if re.search(r"\bSAR\b", text) and SAR_DAY.search(text) and not SAR_ABOUT.search(text):
            fail(name, f"{path}: SAR 7 days must be shown as approximate ('about')")

# ------------------------------------------------------------------ 7. other programs on the card (programs.*.json)
# Card-side text of the 'money you may be missing' part (the fixed part `unlocked`). Nothing here is spoken, so the
# phone rules of sections 1-2 do not apply; the output guard, honest wording and en/es parity do.
PROGRAMS_TABLE = HERE.parent / "rules" / "programs_2026.json"
PROGRAM_IDS = ["calfresh", "medi_cal", "clipper_start", "lifeline", "care", "tax_credits"]
PROGRAM_STATUSES = {"likely", "maybe", "check", "coverage", "zero", "note"}
PROGRAM_QUESTIONS = {"break_transit": ["none", "two_days", "weekdays_muni", "weekdays_bart"],
                     "tax_dependent": ["no", "yes", "not_sure"],
                     "pge_bill": ["own_mine", "own_roommate", "in_rent", "not_sure"]}
# card-side word budgets (fixed by the upgrade design; the file may restate them but never loosen them)
PROGRAM_BUDGETS = {"question": 18, "choice": 5, "line": 30, "note": 25, "share": 30, "footnote": 25,
                   "label": 18, "button": 5, "name": 6, "prefill": 18, "console": 30}
PROGRAM_PLACEHOLDER_TYPES = {"money", "money_exact", "int", "date", "text", "url"}
REQUIRED_PROGRAM_KEYS = [
    "ui.title", "ui.total", "ui.calfresh_part", "ui.key_line", "ui.claimed", "ui.question_count", "ui.footnote",
    "ui.coverage_chip", "ui.maybe_chip", "ui.plan_title", "ui.stage.today", "ui.stage.after_approval",
    "ui.stage.tax_time", "ui.apply_by", "ui.mark_applied", "ui.undo", "ui.status.likely", "ui.status.maybe",
    "ui.status.check", "ui.status.coverage", "ui.status.zero", "ui.status.note", "ui.source", "ui.list_only_title",
    "ui.list_only_intro", "ui.share_button", "ui.copied", "share.text",
    "medi_cal.coverage", "medi_cal.family_income", "medi_cal.if_claimed", "medi_cal.child_too", "medi_cal.link",
    "clipper.likely", "clipper.check", "clipper.zero", "clipper.youth_free_muni", "clipper.link", "clipper.two_cards",
    "lifeline.likely", "lifeline.federal_extra", "lifeline.check", "lifeline.dependent", "lifeline.family_plan",
    "lifeline.link",
    "care.likely", "care.check", "care.roommate_applies", "care.you_apply", "care.applicant_not_dependent",
    "care.in_rent", "care.link", "care.utility_conflict",
    "tax.likely_no_child", "tax.likely_parent", "tax.maybe", "tax.small", "tax.id_note", "tax.unfiled_2025", "tax.link",
    "apply.calfresh_steps", "apply.benefitscal", "apply.clipper", "apply.lifeline", "apply.care", "apply.vita",
]
# the one in-page link: CalFresh's plan entry jumps to the card's today_action block (docs/UI_SPEC.md A4.2 row 2b)
PROGRAM_IN_PAGE_LINKS = {"apply.calfresh_steps": "#today_action"}
P_HEDGE = {"en": re.compile(r"\b(?:about|up to|maybe|may|could|roughly)\b", re.I),
           "es": re.compile(r"\b(?:unos|hasta|quizá|podría|podrían|puede|cerca de)\b", re.I)}
P_CEILING = {"en": re.compile(r"\bup to\b", re.I), "es": re.compile(r"\bhasta\b", re.I)}
P_ASSUMED = {"en": re.compile(r"\bAssumed bill\b"), "es": re.compile(r"\bFactura supuesta\b")}
# Medi-Cal is coverage, not cash: never '$0 premium', never free coverage, never dental or vision
P_MEDI_CAL_PROMISE = re.compile(r"\$0 premium|\bno premiums?\b|\bfree (?:health|coverage|medi-cal)\b|\bdental\b|"
                                r"\bvision\b|prima de \$0|\bsin primas?\b|\bcobertura (?:médica )?gratis\b|"
                                r"\bvisi[oó]n\b", re.I)
P_SHARE_LEAK = re.compile(r"/c/|\{(?:token|case_code|code|card_url|url)\}", re.I)


def p_strings(doc):
    s = doc.get("strings")
    return s if isinstance(s, dict) else {}


def p_flat_keys(node):
    """Every content key a programs entry's lines/value_text/chip node names (str, or dict of str/None)."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [k for v in node.values() for k in p_flat_keys(v)]
    return []


P_EN, P_ES = p_strings(PROG_EN), p_strings(PROG_ES)
for _lang, _doc in (("en", PROG_EN), ("es", PROG_ES)):
    if _doc.get("lang") != _lang:
        fail(f"programs.{_lang}.json", f"lang must be {_lang!r}")
    if _doc.get("native_review") is not (_lang == "es"):
        fail(f"programs.{_lang}.json", "native_review must be true for es (marked for native review) and false for en")
    if not _doc.get("version"):
        fail(f"programs.{_lang}.json", "version is required")
# the same structure in both languages (the strings differ, nothing else does)
for _part in ("budgets", "programs", "links", "console_keys"):
    if PROG_EN.get(_part) != PROG_ES.get(_part):
        fail("programs.*.json", f"{_part} must be identical in en and es")
_ph_en, _ph_es = PROG_EN.get("placeholders") or {}, PROG_ES.get("placeholders") or {}
if {k: (v.get("type"), v.get("fill")) for k, v in _ph_en.items()} != {k: (v.get("type"), v.get("fill")) for k, v in _ph_es.items()}:
    fail("programs.*.json", "placeholders must have the same names, types and fill rules in en and es")
_src_en, _src_es = PROG_EN.get("sources") or {}, PROG_ES.get("sources") or {}
if {k: v.get("date") for k, v in _src_en.items()} != {k: v.get("date") for k, v in _src_es.items()}:
    fail("programs.*.json", "sources must have the same ids and dates in en and es")
for _lang, _src in (("en", _src_en), ("es", _src_es)):
    for _sid, _s in _src.items():
        if not (_s.get("name") or "").strip() or not (_s.get("date_text") or "").strip():
            fail(f"programs.{_lang}.json sources.{_sid}", "needs a display name and a date_text")
        if _s.get("date") is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(_s.get("date"))):
            fail(f"programs.{_lang}.json sources.{_sid}", "date must be YYYY-MM-DD or null")
# budgets: the file may restate the fixed budgets, never loosen them
for _cls, _n in (PROG_EN.get("budgets") or {}).items():
    if _cls in PROGRAM_BUDGETS and _n > PROGRAM_BUDGETS[_cls]:
        fail("programs.en.json budgets", f"{_cls} {_n} is above the fixed budget {PROGRAM_BUDGETS[_cls]}")
for _name, _p in _ph_en.items():
    if _p.get("type") not in PROGRAM_PLACEHOLDER_TYPES:
        fail("programs.en.json placeholders", f"{_name}: type must be one of {sorted(PROGRAM_PLACEHOLDER_TYPES)}")
    for _lang, _ph in (("en", _ph_en), ("es", _ph_es)):
        if not str((_ph.get(_name) or {}).get("example", "")).strip():
            fail(f"programs.{_lang}.json placeholders", f"{_name}: needs an example value")

# keys and placeholders: identical in en and es, all declared, all required keys present
if set(P_EN) != set(P_ES):
    fail("programs.*.json", f"keys differ between en and es: {sorted(set(P_EN) ^ set(P_ES))}")
for _key in sorted(set(P_EN) & set(P_ES)):
    if sorted(placeholders(P_EN[_key])) != sorted(placeholders(P_ES[_key])):
        fail("programs.*.json", f"{_key}: placeholders differ ({placeholders(P_EN[_key])} vs {placeholders(P_ES[_key])})")
for _lang, _strs, _ph in (("en", P_EN, _ph_en), ("es", P_ES, _ph_es)):
    for _key, _text in _strs.items():
        if not isinstance(_text, str) or not _text.strip():
            fail(f"programs.{_lang}.json {_key}", "empty or not a string")
            continue
        if _text != _text.strip() or "  " in _text:
            fail(f"programs.{_lang}.json {_key}", "leading, trailing or double spaces")
        for _name in placeholders(_text):
            if _name not in _ph:
                fail(f"programs.{_lang}.json {_key}", f"placeholder {{{_name}}} is not declared")
        if re.search(r"\{(?![a-z_][a-z0-9_]*\})|(?<!\{[a-z_0-9])\}", PLACEHOLDER.sub("", _text)):
            fail(f"programs.{_lang}.json {_key}", "stray brace")
for _key in REQUIRED_PROGRAM_KEYS:
    if _key not in P_EN:
        fail("programs.en.json", f"missing required key {_key}")

# the three card questions: text, then exactly the table's choices; 'not sure' is an answer
for _q, _choices in PROGRAM_QUESTIONS.items():
    for _lang, _strs in (("en", P_EN), ("es", P_ES)):
        _t = _strs.get(f"q.{_q}", "")
        if not _t.rstrip().endswith("?"):
            fail(f"programs.{_lang}.json q.{_q}", "the question must end with '?'")
        for _c in _choices:
            if f"q.{_q}.{_c}" not in _strs:
                fail(f"programs.{_lang}.json", f"missing choice q.{_q}.{_c}")
_q_keys = {k for k in P_EN if k.startswith("q.")}
_q_known = {f"q.{q}" for q in PROGRAM_QUESTIONS} | {f"q.{q}.{c}" for q, cs in PROGRAM_QUESTIONS.items() for c in cs}
for _key in sorted(_q_keys - _q_known):
    fail("programs.en.json", f"{_key}: not a card question or choice")

# programs: names, lines per status, notes, list_only lines, value texts, chips, apply links, sources
_PROGS = PROG_EN.get("programs") or {}
_LINKS = PROG_EN.get("links") or {}
_CONSOLE = set(PROG_EN.get("console_keys") or [])
if list(_PROGS) != PROGRAM_IDS:
    fail("programs.en.json programs", f"must list {PROGRAM_IDS} in plan priority order")
_LINE_KEYS, _NOTE_KEYS, _OTHER_REFS = set(), set(), set()
for _pid, _p in _PROGS.items():
    _where = f"programs.en.json programs.{_pid}"
    if f"program.{_pid}" != _p.get("name"):
        fail(_where, f"name must be program.{_pid}")
    _lines = _p.get("lines") or {}
    if not _lines or not set(_lines) <= PROGRAM_STATUSES:
        fail(_where, f"lines must map statuses {sorted(PROGRAM_STATUSES)} to keys")
    for _status, _node in _lines.items():
        if not isinstance(_node, (str, dict)) or not p_flat_keys(_node):
            fail(_where, f"lines.{_status} must be a key or a {{variant: key}} map")
    _LINE_KEYS |= set(p_flat_keys(_lines))
    if _p.get("list_only"):
        _LINE_KEYS.add(_p["list_only"])
    elif _pid != "calfresh":
        fail(_where, "list_only line missing (list_only mode shows one line per program, no amount)")
    _NOTE_KEYS |= set(_p.get("notes") or [])
    for _status in (_p.get("value_text") or {}):
        if _status not in _lines:
            fail(_where, f"value_text.{_status} has no line for that status")
    for _status in (_p.get("chip") or {}):
        if _status not in _lines:
            fail(_where, f"chip.{_status} has no line for that status")
    _OTHER_REFS |= set(p_flat_keys(_p.get("value_text") or {})) | set(p_flat_keys(_p.get("chip") or {}))
    _OTHER_REFS |= {_p.get("name"), _p.get("apply")}
    if _p.get("apply") not in _LINKS:
        fail(_where, f"apply {_p.get('apply')!r} has no url in links")
    for _sid in _p.get("sources") or []:
        if _sid not in _src_en:
            fail(_where, f"source {_sid!r} has no display name in sources")
    if not _p.get("sources"):
        fail(_where, "needs at least one source (shown with ui.source)")
    for _key in p_flat_keys(_lines) + list(_p.get("notes") or []) + [_p.get("list_only") or "program.calfresh"] + \
            list(p_flat_keys(_p.get("value_text") or {})) + list(p_flat_keys(_p.get("chip") or {})) + [_p.get("name"), _p.get("apply")]:
        if _key not in P_EN:
            fail(_where, f"names a key that is not in strings: {_key!r}")
for _key, _url in _LINKS.items():
    if _key not in P_EN:
        fail("programs.en.json links", f"{_key} has no label in strings")
    if _key in PROGRAM_IN_PAGE_LINKS:
        if _url != PROGRAM_IN_PAGE_LINKS[_key]:
            fail("programs.en.json links", f"{_key} must be the in-page link {PROGRAM_IN_PAGE_LINKS[_key]!r}")
    elif not re.fullmatch(r"https://[A-Za-z0-9.-]+\.[a-z]{2,}(?:/[^\s\"'<>]*)?", str(_url)):
        fail("programs.en.json links", f"{_key}: apply links must be https urls ({_url!r})")
if (_PROGS.get("calfresh") or {}).get("apply") != "apply.calfresh_steps":
    fail("programs.en.json programs.calfresh", "apply must be apply.calfresh_steps (the in-page #today_action link, not an outside site)")
for _key in _CONSOLE:
    if _key not in P_EN:
        fail("programs.en.json console_keys", f"{_key} is not in strings")


def program_class(key):
    """The word-budget class of one programs key (None = a key nothing uses)."""
    if key == "share.text":
        return "share"
    if key == "ui.footnote":
        return "footnote"
    if key.startswith("q."):
        return "choice" if key.count(".") >= 2 else "question"
    if key.startswith("ui."):
        return "label"
    if key.startswith("apply."):
        return "button"
    if key.startswith("program."):
        return "name"
    if key.startswith("pf."):
        return "prefill"
    if key in _CONSOLE:
        return "console"
    if key in _NOTE_KEYS:      # a note that is also the line of a 'note' status keeps the stricter note budget
        return "note"
    if key in _LINE_KEYS:
        return "line"
    return None


_P_ROWS = []
for _lang, _strs, _ph in (("en", P_EN, _ph_en), ("es", P_ES, _ph_es)):
    _examples = {k: str(v.get("example", "")) for k, v in _ph.items()}
    for _key, _text in _strs.items():
        if not isinstance(_text, str):
            continue
        _where = f"programs.{_lang}.json {_key}"
        _cls = program_class(_key)
        if _cls is None:
            fail(_where, "no program, question, console note or ui part uses this key")
            continue
        _n = count_words(_text)
        _P_ROWS.append((_lang, _key, _cls, _n))
        if _n > PROGRAM_BUDGETS[_cls]:
            fail(_where, f"{_n} words > {_cls} budget {PROGRAM_BUDGETS[_cls]}")
        # output guard, as written and filled with the example values
        _filled = render(_text, _examples)
        if PLACEHOLDER.search(_filled):
            fail(_where, f"placeholder left after filling: {_filled!r}")
        for _t in {_text, _filled}:
            _hits = forbidden_hits(_t)
            if _hits:
                fail(_where, f"output guard hits {_hits}")
        # honest wording: every estimate is hedged; ceilings say up to; assumptions are shown
        _money = [n for n in placeholders(_text) if (_ph.get(n) or {}).get("type") == "money"]
        if _money and _key not in ("ui.claimed", "share.text") and not _key.startswith("pf.") and not P_HEDGE[_lang].search(_text):
            fail(_where, "an estimate must say about / up to / maybe (es: unos / hasta / quizá)")
        if P_MEDI_CAL_PROMISE.search(_text):
            fail(_where, "Medi-Cal is coverage: no '$0 premium', no free-coverage, dental or vision promise")
        if _key.startswith("tax.") and re.search(r"\brefund\b|\breembolso\b", _text) and \
                not re.search(r"\bnot (?:a |your )?refund\b|\bno (?:es )?tu reembolso\b", _text):
            fail(_where, "a tax credit amount is not a refund amount")
for _key in ("lifeline.likely", "lifeline.check", "lifeline.federal_extra", "ui.value.ceiling"):
    for _lang, _strs in (("en", P_EN), ("es", P_ES)):
        if _key in _strs and not P_CEILING[_lang].search(_strs[_key]):
            fail(f"programs.{_lang}.json {_key}", "a ceiling must say 'up to' (es: 'hasta')")
for _key in [k for k in P_EN if re.fullmatch(r"care\.(?:likely|maybe)(?:_alone)?", k)]:
    for _lang, _strs in (("en", P_EN), ("es", P_ES)):
        if not P_ASSUMED[_lang].search(_strs.get(_key, "")) or "{bill}" not in _strs.get(_key, ""):
            fail(f"programs.{_lang}.json {_key}", "the CARE line shows its assumed bill ({bill})")
for _key in [k for k in P_EN if k.startswith("medi_cal.") or k in ("list_only.medi_cal", "ui.coverage_chip", "ui.value.coverage")]:
    for _lang, _strs, _ph in (("en", P_EN, _ph_en), ("es", P_ES, _ph_es)):
        if any((_ph.get(n) or {}).get("type") in ("money", "money_exact") for n in placeholders(_strs.get(_key, ""))):
            fail(f"programs.{_lang}.json {_key}", "Medi-Cal has no dollar amount (coverage, $0 cash)")
for _lang, _strs in (("en", P_EN), ("es", P_ES)):
    if not re.search(r"\bmost students\b|\bla mayoría de los estudiantes\b", _strs.get("medi_cal.coverage", "")):
        fail(f"programs.{_lang}.json medi_cal.coverage", "say 'at no cost for most students today', never '$0 premium'")
    _share = _strs.get("share.text", "")
    if set(placeholders(_share)) != {"share", "site"} or P_SHARE_LEAK.search(_share):
        fail(f"programs.{_lang}.json share.text", "share text has exactly {share} and {site}: no card url, token, code or answer")
    if not re.search(r"not promises|no promesas", _share):
        fail(f"programs.{_lang}.json share.text", "share text says the amounts are estimates, not promises")
    if "2025" not in _strs.get("tax.basis", ""):
        fail(f"programs.{_lang}.json tax.basis", "name the 2025 tables used as a proxy")

# the programs table names these keys; every one must exist (checked when the table is present)
PROGRAMS_TABLE_DATA = None
if PROGRAMS_TABLE.exists():
    try:
        PROGRAMS_TABLE_DATA = json.loads(PROGRAMS_TABLE.read_text(encoding="utf-8"))
    except ValueError as exc:
        fail("rules/programs_2026.json", f"cannot load: {exc}")
else:
    NOTES.append("data/rules/programs_2026.json not found: table cross-checks skipped")
if isinstance(PROGRAMS_TABLE_DATA, dict):
    _T = PROGRAMS_TABLE_DATA
    _tq = {q: v.get("choices") for q, v in (_T.get("questions") or {}).items()}
    if _tq != PROGRAM_QUESTIONS:
        fail("programs table vs content", f"questions and choices differ: table {_tq}")
    _t_ids = [p.get("id") for p in _T.get("programs") or []]
    for _pid in _t_ids:
        if _pid not in _PROGS:
            fail("programs table vs content", f"program {_pid!r} has no content entry")
    if set(_PROGS) - set(_t_ids) - {(_T.get("plan") or {}).get("today_always")}:
        fail("programs table vs content", f"content programs not in the table: {sorted(set(_PROGS) - set(_t_ids))}")
    _t_src = {s.get("id") for s in _T.get("sources") or []}
    if _t_src - set(_src_en):
        fail("programs table vs content", f"source ids without a display name: {sorted(_t_src - set(_src_en))}")
    if set(_src_en) - _t_src:
        fail("programs table vs content", f"display names for unknown source ids: {sorted(set(_src_en) - _t_src)}")
    if (_T.get("calfresh_key") or {}).get("source") not in (_PROGS.get("calfresh") or {}).get("sources", []):
        fail("programs table vs content", "calfresh_key.source must be a calfresh display source")
    _ANSWER_FROM = {"fact:earned_monthly": ["pf.answer.earned_monthly"],
                    "fact:household_food": [f"pf.answer.household_food.{v}" for v in ("alone", "separate", "shared")],
                    "fact:people_in_home": ["pf.answer.people_in_home"],
                    "fact:half_time": ["pf.answer.half_time.true", "pf.answer.half_time.false"]}
    for _q, _choices in PROGRAM_QUESTIONS.items():
        _ANSWER_FROM[f"answer:{_q}"] = [f"pf.answer.{_q}.{c}" for c in _choices]
    for _tp in _T.get("programs") or []:
        _pid = _tp.get("id")
        _cp = _PROGS.get(_pid) or {}
        _where = f"programs table {_pid} vs content"
        _named_notes = set()
        for _r in _tp.get("status_rules") or []:
            _st = _r.get("status")
            if _st != "hidden" and _st not in (_cp.get("lines") or {}):
                fail(_where, f"status {_st!r} has no line key")
            _named_notes |= set(_r.get("notes") or [])
            if _r.get("variant") and _st in (_cp.get("lines") or {}) and not isinstance(_cp["lines"][_st], dict):
                fail(_where, f"status {_st!r} has variants in the table but one key in the content")
        _named_notes |= set((_tp.get("note_rules") or {}).keys()) | set(_tp.get("notes_always") or [])
        if (_tp.get("calfresh_link") or {}).get("text_key"):
            _named_notes.add(_tp["calfresh_link"]["text_key"])
        for _nk in sorted(_named_notes):
            if _nk not in P_EN:
                fail(_where, f"note key {_nk!r} is not in strings")
            elif _nk not in (_cp.get("notes") or []):
                fail(_where, f"note key {_nk!r} is missing from programs.{_pid}.notes")
        for _nk in (_tp.get("console_note_rules") or {}):
            if _nk not in _CONSOLE:
                fail(_where, f"console note {_nk!r} is not in console_keys")
        _ap = _tp.get("apply") or {}
        if _ap.get("label_key") != _cp.get("apply"):
            fail(_where, f"apply label {_ap.get('label_key')!r} differs from the content's {_cp.get('apply')!r}")
        elif _LINKS.get(_ap.get("label_key")) != _ap.get("url"):
            fail(_where, f"apply url differs: table {_ap.get('url')!r}, content {_LINKS.get(_ap.get('label_key'))!r}")
        for _row in _tp.get("prefill") or []:
            _keys = [_row.get("question_key")] + ([_row["answer_key"]] if _row.get("answer_key") else [])
            if _row.get("answer_from"):
                if _row["answer_from"] not in _ANSWER_FROM:
                    fail(_where, f"prefill answer_from {_row['answer_from']!r} has no answer keys")
                _keys += _ANSWER_FROM.get(_row["answer_from"], [])
            for _k in _keys:
                if _k not in P_EN:
                    fail(_where, f"prefill key {_k!r} is not in strings")
    # numbers that the wording repeats must match the table
    _rows = _T.get("rows") or {}
    _ll = str((_rows.get("lifeline.state") or {}).get("monthly", ""))
    _ll_text = "$" + (_ll[:-3] if _ll.endswith(".00") else _ll)
    for _lang, _strs in (("en", P_EN), ("es", P_ES)):
        if _ll and _ll_text not in _strs.get("lifeline.likely", ""):
            fail(f"programs.{_lang}.json lifeline.likely", f"the monthly ceiling must be the table's {_ll_text}")
        _age = (_rows.get("clipper.breaks") or {}).get("age") or []
        if len(_age) == 2:
            if not re.search(rf"\b{_age[0]}\b", _strs.get("clipper.youth_free_muni", "")) or \
                    not re.search(rf"\b{_age[0]}\b.*\b{_age[1]}\b", _strs.get("list_only.clipper_start", "")):
                fail(f"programs.{_lang}.json clipper", f"Clipper START ages must be the table's {_age[0]}-{_age[1]}")
        _mail = (_rows.get("clipper.breaks") or {}).get("mail_days")
        if _mail and not re.search(rf"\b{_mail}\b", _strs.get("clipper.link", "")):
            fail(f"programs.{_lang}.json clipper.link", f"mail time must be the table's {_mail} days")

# reading level of the English program lines and notes (as filled for Maria), the same measure as the card blocks
_P_EXAMPLES_EN = {k: str(v.get("example", "")) for k, v in _ph_en.items()}
_p_text = " ".join(render(P_EN[k], _P_EXAMPLES_EN) for k in sorted(P_EN) if program_class(k) in ("line", "note"))
_p_grade = fk_grade(_p_text)
READING.append(("programs.en lines and notes", _p_grade))
if _p_grade > 7.0:
    fail("programs.en.json", f"reading level grade {_p_grade:.1f} > 7 (lines and notes)")

# ------------------------------------------------------------------ report
if VERBOSE:
    print("Word budgets (worst variant combination, phone, en):")
    for label, worst, cls in sorted(BUDGET_ROWS, key=lambda r: (r[2], -r[1])):
        print(f"  {worst:3d}/{WORD_BUDGETS[cls]:<3d} {cls:8s} {label}")
    print("Reading level (Flesch-Kincaid grade, English):")
    for label, grade in READING:
        print(f"  {grade:4.1f}  {label}")
    print("Card-side program strings (words / budget, longest first):")
    for lang, key, cls, n in sorted(_P_ROWS, key=lambda r: (r[3] - PROGRAM_BUDGETS[r[2]], r[3]), reverse=True)[:12]:
        print(f"  {n:3d}/{PROGRAM_BUDGETS[cls]:<3d} {cls:8s} {lang} {key}")
    for n in NOTES:
        print("note:", n)
n_keys = len(MSG_EN)
if PROBLEMS:
    print(f"check_content: {len(PROBLEMS)} problem(s)")
    for p in PROBLEMS:
        print("  -", p)
    sys.exit(1)
print(f"check_content: OK ({n_keys} sentence keys x 2 languages, {len(BUDGET_ROWS)} budget checks, "
      f"{len(PERSONAS)} sample cards x 2 languages, {len(REASON_CODES) + 1} card routes, "
      f"{sum(len(v) for v in GUARDS.get('tests', {}).values())} guard tests, {UTTERANCE_COUNT} utterances, "
      f"{len(P_EN)} program strings x 2 languages)")

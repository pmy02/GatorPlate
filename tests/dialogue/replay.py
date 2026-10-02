"""Shared helpers for the Brain-level replays: phone text rules, word budgets and a primed call state."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from gatorplate.contracts.brain_api import BrainReply, StartRequest
from gatorplate.contracts.common import Channel, Lang, Phase, SlotSource, SlotState
from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import Slot, SlotName, encode_value, format_display
from gatorplate.dialogue.budget import CONTACT_WORDS, RESULT_KEY_PREFIXES, WORD_BUDGETS, count_words

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"
SCRIPTS = ROOT / "tests" / "e2e" / "scripts"
PHONE_FORBIDDEN = set("$%/~–")
PHONE_ALSO_FORBIDDEN = set("0123456789@#&*+=<>|_\\[]{}`\"()")
REJECTION = ["not eligible", "ineligible", "don't qualify", "do not qualify", "denied", "no califica",
             "no eres elegible"]


def phone_text_problems(text: str) -> list[str]:
    out = [f"symbol {ch!r}" for ch in sorted(set(text)) if ch in PHONE_FORBIDDEN or ch in PHONE_ALSO_FORBIDDEN]
    if re.search(r"https?:|www\.", text, re.IGNORECASE):
        out.append("URL")
    low = text.lower()
    out += [f"rejection {p!r}" for p in REJECTION if p in low]
    return out


def spoken(reply: BrainReply) -> str:
    return " ".join(p for p in (reply.say, reply.ask) if p)


def budget_of(keys: list[str], text: str, *, start: bool = False) -> str:
    if start:
        return "opening"
    if any(k.startswith(RESULT_KEY_PREFIXES) for k in keys) or CONTACT_WORDS.search(text):
        return "result"
    return "question"


def phone_reply_problems(reply: BrainReply, keys: list[str], *, start: bool = False) -> list[str]:
    """The checker's phone rules (contracts/check_examples.py): text, budget, web extras null, interruptibility."""
    text = spoken(reply)
    out = phone_text_problems(text)
    cls = budget_of(keys, text, start=start)
    if count_words(text) > WORD_BUDGETS[cls]:
        out.append(f"{count_words(text)} words > {cls} {WORD_BUDGETS[cls]}: {text!r}")
    for field in ("display", "choices", "card_url"):
        if getattr(reply, field) is not None:
            out.append(f"{field} must be null on the phone")
    if reply.lang != (Lang.es if "language.offer_web" in keys else Lang.en):
        out.append("phone lang")
    heard_in_full = any(k in ("result.likely", "result.likely_floor", "card.phone_code", "crisis.resources")
                        for k in keys) or CONTACT_WORDS.search(reply.say)
    if heard_in_full and reply.interruptible:
        out.append("must not be interruptible")
    if reply.ask is None and reply.expect != "open":
        out.append("ask null means expect open")
    if any(k in ("result.likely", "result.likely_floor") for k in keys) and "county" not in reply.say.lower():
        out.append("an estimate needs the county-decides sentence")
    return out


PHASE_FOR_PENDING = {
    "consent.ask": Phase.consent, "ask.level_units": Phase.student, "ask.income": Phase.income,
    "ask.rent": Phase.housing, "flip.rent_paid_by_others": Phase.flip,
}
MARIA = [  # Maria's answers in phase order: (phase that needs them, slot, value)
    (Phase.student, SlotName.consent, "true"),
    (Phase.age_home, SlotName.level, "undergrad"), (Phase.age_home, SlotName.units, "12"),
    (Phase.household, SlotName.age, "20"), (Phase.household, SlotName.lives_with_parent, "false"),
    (Phase.household, SlotName.roommates, "true"),
    (Phase.income, SlotName.household_food, "separate"),
    (Phase.housing, SlotName.earned_monthly, "900"), (Phase.housing, SlotName.other_cash_monthly, "0"),
    (Phase.flip, SlotName.rent_share, "1100"),
]
ORDER = [Phase.consent, Phase.student, Phase.age_home, Phase.household, Phase.income, Phase.housing, Phase.flip]


async def prime(rig, scenario: dict) -> None:
    """Build the call state a scenario's `given` block describes (started, last seq, pending question, ended)."""
    given = scenario.get("given") or {}
    if not given.get("started"):
        return
    channel = scenario["channel"]
    await rig.brain.start(rig.call_id, StartRequest(v=1, seq=0, channel=channel, lang=scenario["lang"]))
    session = rig.sessions.get(rig.call_id)
    case = rig.cases.get(session.case_id)
    pending_key = given.get("pending")
    phase = PHASE_FOR_PENDING.get(pending_key, Phase.housing)
    for need, slot, raw in MARIA:
        if ORDER.index(need) <= ORDER.index(phase):
            canonical = encode_value(slot, Decimal(raw) if slot in (SlotName.earned_monthly,
                                                                    SlotName.other_cash_monthly,
                                                                    SlotName.rent_share) else raw)
            case.slots[slot] = Slot(value=canonical, display=format_display(slot, canonical),
                                    state=SlotState.clear, source=SlotSource.llm, turn=1)
    if phase != Phase.consent:
        case.consent.given = True
    session.phase = phase
    session.awaiting = "consent" if phase == Phase.consent else "none"
    session.last_seq = int(given.get("last_seq", 0))
    session.turn_count = int(given.get("student_turns", session.last_seq))
    session.last_reply = None
    if pending_key:
        expect = rig.brain.bank.expect(pending_key) or {}
        session.pending = PendingQuestion(key=pending_key, slots=[SlotName(s) for s in expect.get("slots", [])],
                                          kind=expect.get("expect", "open"))
    if phase == Phase.flip:
        session.flips_asked = 1
    if given.get("ended_by_brain"):
        session.ended_by_brain = given["ended_by_brain"]
        session.phase = Phase.end
    rig.cases.save(case)
    rig.sessions.put(session)
    rig.seq = session.last_seq


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def channel_of(scenario: dict) -> Channel:
    return Channel(scenario["channel"])

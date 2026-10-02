"""The sentence bank, the output guard, the verbalizer and the word counter (docs/SPEC.md §3.6, §3.8;
docs/BRAIN_API.md §7)."""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from gatorplate.contracts.common import Channel, Lang
from gatorplate.contracts.slots import SLOT_SPECS
from gatorplate.dialogue.budget import budget_class, count_words, fits, split_point
from gatorplate.dialogue.output_guard import OutputGuard
from gatorplate.dialogue.templates import Bank, Step, fill, pick_index
from gatorplate.dialogue.verbalize import (
    PHONE_SPOKEN_NAME,
    code_display,
    digits_spoken,
    int_words,
    money_display,
    money_words,
    name_spoken,
    url_display,
    url_spoken,
)
from tests.dialogue.conftest import make_rig
from tests.dialogue.replay import ROOT, phone_text_problems
from tests.dialogue.test_global_intents import at, keys

CONTENT = ROOT / "data" / "content"
GUARDS = json.loads((CONTENT / "guards.json").read_text(encoding="utf-8"))
BANK = Bank(CONTENT)
SAMPLES = {
    "spoken": {
        Lang.en: {"coordinator_phone": "four one five, three three eight, one two zero three",
                  "county_phone": "eight five five, three five five, five seven five seven",
                  "coordinator_hours": "Monday to Thursday eight thirty to five, Friday eight thirty to four",
                  "talk_url": "gatorplate dot fly dot dev slash talk", "short_url": "gatorplate dot fly dot dev slash go",
                  "code": "four eight one, two zero six", "amount": "three hundred six dollars",
                  "a": "one thousand dollars", "b": "two thousand dollars", "x": "fifteen hundred dollars",
                  "rate": "eighteen dollars fifty", "hours": "fifteen", "period": "a month",
                  "question": "How much is your share of the rent each month?"},
        Lang.es: {"coordinator_phone": "cuatro uno cinco, tres tres ocho, uno dos cero tres",
                  "county_phone": "ocho cinco cinco, tres cinco cinco, cinco siete cinco siete",
                  "coordinator_hours": "de lunes a jueves de ocho y media a cinco",
                  "talk_url": "gatorplate punto fly punto dev barra talk",
                  "short_url": "gatorplate punto fly punto dev barra go", "code": "cuatro ocho uno, dos cero seis",
                  "amount": "trescientos seis dólares", "a": "mil dólares", "b": "dos mil dólares",
                  "x": "mil quinientos dólares", "rate": "dieciocho dólares cincuenta", "hours": "quince",
                  "period": "al mes", "question": "¿Cuánto pagas de renta al mes?"},
    },
    "display": {
        "coordinator_phone": "(415) 338-1203", "county_phone": "(855) 355-5757",
        "coordinator_hours": "Mon–Thu 8:30 AM–5 PM, Fri 8:30 AM–4 PM", "talk_url": "gatorplate.fly.dev/talk",
        "short_url": "gatorplate.fly.dev/go", "code": "481 206", "amount": "$306", "a": "$1,000", "b": "$2,000",
        "x": "$1,500", "rate": "$18.50", "hours": "15", "period": "a month", "question": "What's your rent share?",
    },
}


def all_variants(lang: Lang):
    for key, msg in BANK.messages[lang].items():
        for form in ("main", "closed", "short"):
            node = msg if form == "main" else msg.get(form)
            if not isinstance(node, dict):
                continue
            for field in ("phone", "web", "all"):
                for variant in node.get(field) or []:
                    yield key, form, field, variant
            expect = node.get("expect") if form != "main" else msg.get("expect")
            for choice in (expect or {}).get("choices") or []:
                yield key, form, "choice", choice["label"]


def texts(variant) -> list[str]:
    if isinstance(variant, dict):
        return [variant.get("say") or "", variant.get("ask") or ""]
    return [variant]


def test_check_content_passes() -> None:
    result = subprocess.run([sys.executable, str(CONTENT / "check_content.py")], capture_output=True, text=True,
                            cwd=ROOT, timeout=120)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "check_content: OK" in result.stdout


def test_banks_have_the_same_keys_and_vars() -> None:
    en, es = BANK.messages[Lang.en], BANK.messages[Lang.es]
    assert set(en) == set(es) and len(en) == 97
    for key in en:
        assert sorted(en[key].get("vars") or []) == sorted(es[key].get("vars") or []), key


@pytest.mark.parametrize("lang", [Lang.en, Lang.es])
def test_output_guard_zero_hits_over_every_variant(lang: Lang) -> None:
    guard = OutputGuard(CONTENT / "guards.json")
    hits = []
    for key, form, field, variant in all_variants(lang):
        for mode in ("spoken", "display"):
            values = SAMPLES["spoken"][lang] if mode == "spoken" else SAMPLES["display"]
            for text in texts(variant):
                filled = fill(text, values)
                if guard.hits(filled):
                    hits.append((key, form, field, guard.hits(filled)))
    assert hits == []


def test_output_guard_blocks_and_passes_the_vectors() -> None:
    guard = OutputGuard(CONTENT / "guards.json")
    for vector in GUARDS["tests"]["output_block"]:
        assert guard.hits(vector["text"]), vector
    for vector in GUARDS["tests"]["output_pass"]:
        assert not guard.hits(vector["text"]), vector


@pytest.mark.parametrize("text", ["You will save $200 this year.", "You'll get a refund.", "You're covered.",
                                  "Free money for students!", "Vas a ahorrar $200.", "Estás cubierta."])
def test_output_guard_covers_the_program_money_phrases(text: str) -> None:
    assert OutputGuard(CONTENT / "guards.json").hits(text)


def test_phone_variants_pass_the_phone_text_rules() -> None:
    problems = []
    for key, form, field, variant in all_variants(Lang.en):
        if field not in ("phone", "all"):
            continue
        for text in texts(variant):
            filled = fill(text, SAMPLES["spoken"][Lang.en])
            if phone_text_problems(filled):
                problems.append((key, form, phone_text_problems(filled)))
    assert problems == []


def test_every_key_has_variants_on_its_channels() -> None:
    for lang in (Lang.en, Lang.es):
        for key, msg in BANK.messages[lang].items():
            for channel in msg.get("channels") or []:
                assert BANK.variants(key, lang, Channel(channel)), (key, lang, channel)


def test_confirm_policy_matches_the_critical_slots() -> None:
    policy = BANK.confirm_policy
    assert sorted(policy["confirm_slots"]) == sorted(s.value for s, spec in SLOT_SPECS.items() if spec.critical)
    assert "cash_on_hand" in policy["no_confirm"] and "cash_on_hand" in policy["no_readback"]


def test_variant_choice_is_deterministic() -> None:
    a = pick_index("0a000000000000000000000000000001", "ack.short", 3, 4)
    assert a == pick_index("0a000000000000000000000000000001", "ack.short", 3, 4)
    picks = {pick_index("0a000000000000000000000000000001", "ack.short", t, 4) for t in range(20)}
    assert len(picks) > 1


def test_step_encoding_round_trip() -> None:
    for step in (Step("card.phone_code"), Step("ask.rent", "short"), Step("close.anything_else", "closed")):
        back = Step.decode(step.encode())
        assert (back.key, back.form) == (step.key, step.form)


async def test_guard_hit_replaces_the_reply(settings_test, tmp_path: Path) -> None:
    content = tmp_path / "content"
    shutil.copytree(CONTENT, content)
    bank = json.loads((content / "sentences.en.json").read_text(encoding="utf-8"))
    bank["messages"]["ack.short"]["all"] = ["You're approved!"]
    (content / "sentences.en.json").write_text(json.dumps(bank), encoding="utf-8")
    rig = make_rig(settings_test)
    from gatorplate.dialogue import Brain

    rig.brain = Brain(settings=rig.settings, clock=rig.clock, ids=rig.ids, rules=rig.rules,
                      understanding=rig.understanding, cases=rig.cases, sessions=rig.sessions, live=rig.live,
                      events=rig.events, cards=None, content_dir=content)
    await rig.start()
    reply = await rig.say("Yes, that's fine.")
    assert keys(reply) == ["error.generic"] and reply.ask is None
    assert "approved" not in reply.say.lower()
    assert "guard_hit" in rig.case().flags and rig.brain.metrics["guard_hits"] == 1
    again = await rig.say("I'm an SF State undergrad, a junior, and I'm taking 12 units.")
    assert keys(again) == ["error.generic"]  # every ack variant is poisoned in this test bank


# ------------------------------------------------------------------------------------------ verbalizer

@pytest.mark.parametrize(("amount", "en", "es"), [
    (306, "three hundred six dollars", "trescientos seis dólares"),
    (900, "nine hundred dollars", "novecientos dólares"),
    (1100, "eleven hundred dollars", "mil cien dólares"),
    (1975, "nineteen hundred seventy-five dollars", "mil novecientos setenta y cinco dólares"),
    (2500, "twenty-five hundred dollars", "dos mil quinientos dólares"),
    (2000, "two thousand dollars", "dos mil dólares"),
    (1050, "one thousand fifty dollars", "mil cincuenta dólares"),
    (12197, "twelve thousand one hundred ninety-seven dollars", "doce mil ciento noventa y siete dólares"),
    (1, "one dollar", "un dólar"),
    (21, "twenty-one dollars", "veintiún dólares"),
])
def test_money_words(amount: int, en: str, es: str) -> None:
    assert money_words(amount) == en
    assert money_words(amount, Lang.es) == es


def test_money_cents_codes_urls() -> None:
    assert money_words(Decimal("18.50"), cents=True) == "eighteen dollars fifty"
    assert money_words(Decimal("18.50"), Lang.es, cents=True) == "dieciocho dólares cincuenta"
    assert money_display(Decimal("1100")) == "$1,100" and money_display(Decimal("18.5"), cents=True) == "$18.50"
    assert digits_spoken("481206") == "four eight one, two zero six"
    assert digits_spoken("481206", Lang.es) == "cuatro ocho uno, dos cero seis"
    assert code_display("481206") == "481 206"
    assert url_spoken("https://gatorplate.fly.dev", "/go") == "gatorplate dot fly dot dev slash go"
    assert url_spoken("https://gatorplate.fly.dev", "/talk", Lang.es) == "gatorplate punto fly punto dev barra talk"
    assert url_spoken("http://127.0.0.1:8000", "/go") == "localhost slash go"
    assert url_display("https://gatorplate.fly.dev", "/go") == "gatorplate.fly.dev/go"
    assert int_words(12) == "twelve" and int_words(12, Lang.es) == "doce"
    for n in range(0, 2100, 7):
        assert not phone_text_problems(money_words(n))


def test_phone_says_the_name_as_two_words() -> None:
    """Phone text says the display name as two words (PHONE_SPOKEN_NAME); other words are left alone."""
    assert PHONE_SPOKEN_NAME == "Refri Gator"
    assert name_spoken("Thanks for calling refriGator. Goodbye.") == "Thanks for calling Refri Gator. Goodbye."
    assert name_spoken("refriGator is built for SF State students.") == "Refri Gator is built for SF State students."
    assert name_spoken("refriGator's design") == "Refri Gator's design"
    url = url_spoken("https://gatorplate.fly.dev", "/talk", Lang.es)
    assert name_spoken(f"usa refriGator en la web: {url}.") == f"usa Refri Gator en la web: {url}."
    assert name_spoken("a refrigerator, refriGators, GatorPlate") == "a refrigerator, refriGators, GatorPlate"
    assert not phone_text_problems(name_spoken("Thanks for calling refriGator."))


# ------------------------------------------------------------------------------------------ word budgets

def test_word_counter_follows_the_contract_rule() -> None:
    assert count_words("Hi, this is GatorPlate, a student-built AI — the call audio isn't recorded.") == 12
    assert count_words("— –") == 0


def test_budget_classes() -> None:
    assert budget_class(["consent.ask"], "x") == "opening"
    assert budget_class(["ack.short", "ask.rent"], "Okay. What's your rent?") == "question"
    assert budget_class(["result.likely"], "") == "result"
    assert budget_class(["side_question.noted"], "call four one five, three three eight") == "result"
    assert fits(["ack.short"], "one two three")


def test_split_point_keeps_the_longest_fitting_prefix() -> None:
    words = {1: 14, 2: 27, 3: 44, 4: 62}
    keys = ["expedited.yes", "first_month.apply_today", "card.phone_code", "close.anything_else"]

    def render(k: int):
        return keys[:k], " ".join(["word"] * words[k])

    assert split_point(4, render) == 3
    assert split_point(1, render) == 1


async def test_phone_offer_web_is_spanish_and_within_budget(settings_test) -> None:
    rig = make_rig(settings_test.model_copy(update={"public_base_url": "https://gatorplate.fly.dev"}))
    await at(rig, "ask.level_units")
    reply = await rig.say("Can we do this in Spanish? Español, por favor.")
    assert reply.lang == "es" and "gatorplate punto fly punto dev barra talk" in reply.say
    assert count_words(reply.say) <= 25 and not phone_text_problems(reply.say)
    assert "usa Refri Gator en la web" in reply.say and "refriGator" not in reply.say


def test_sample_combinations_stay_within_budget() -> None:
    """Every two-key combination the policy builds around a question stays within the question budget."""
    questions = [k for k, m in BANK.messages[Lang.en].items() if "expect" in m and not k.startswith(("close.",
                                                                                                     "human.",
                                                                                                     "crisis."))]
    leads = ["ack.short", "answer.is_ai", "answer.is_recorded", "apply_for_me", "immigration.question", "food_today",
             "side_question.noted", "info.previously_denied", "abuse.warn", "delete.cancelled", "proxy.caller"]
    for lead, q in itertools.product(leads, questions):
        if q == "consent.ask":
            continue
        lead_text = BANK.variants(lead, Lang.en, Channel.phone)
        q_text = BANK.variants(q, Lang.en, Channel.phone, "short" if lead != "ack.short" else "main")
        for a, b in itertools.product(lead_text, q_text):
            text = fill(" ".join(texts(a) + texts(b)), SAMPLES["spoken"][Lang.en])
            cls = budget_class([lead, q], text)
            limit = {"question": 25, "result": 45, "opening": 40}[cls]
            assert count_words(text) <= limit, (lead, q, text)

"""Keyword intents: a high-recall backstop for the model, phrase-aware (data/content/guards.json)."""

from __future__ import annotations

import json

import pytest

from gatorplate.contracts.extraction import Intent
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.redact import Redactor
from gatorplate.extract.text import normalize
from tests.extract.support import DATA

GUARDS = json.loads((DATA / "content" / "guards.json").read_text(encoding="utf-8"))


def names(km: KeywordMatcher, text: str) -> list[str]:
    return sorted(i.value for i in km.match(text))


@pytest.mark.parametrize("case", GUARDS["tests"]["keywords"], ids=lambda c: c["text"][:40])
def test_guard_vectors(keywords: KeywordMatcher, case: dict) -> None:
    assert names(keywords, case["text"]) == sorted(case["expect"])


@pytest.mark.parametrize("text,expect", [
    # the rulings on keyword intents
    ("Is this a real person?", ["is_ai"]),
    ("No, espera, son mil doscientos, no mil cien.", []),
    ("I don't really see the point of living anymore.", ["crisis"]),
    ("no le veo sentido a vivir", ["crisis"]),
    ("Can I talk to a real person?", ["human_request"]),
    ("Can you erase my information and then hang up?", ["delete_data", "stop"]),
    ("No, that's all. Thanks.", []),
    # hold, abuse, repeat and language, English and Spanish
    ("Hold on, let me grab my paystub.", ["hold"]),
    ("One sec.", ["hold"]),
    ("Espera un momento.", ["hold"]),
    ("Dame un segundo, por favor.", ["hold"]),
    ("Espera, son mil doscientos.", []),
    ("you're useless", ["abuse"]),
    ("this is so fucking hard", []),
    ("eres un idiota", ["abuse"]),
    ("qué pendejo soy, se me olvidó", []),
    ("Sorry, can you say that again?", ["repeat"]),
    ("¿Me lo repites, por favor?", ["repeat"]),
    ("Do you have this in Spanish?", ["language_request"]),
    ("¿Hablas español?", ["language_request"]),
    ("I'm taking a Spanish class", []),
])
def test_rulings_and_lists(keywords: KeywordMatcher, text: str, expect: list[str]) -> None:
    assert names(keywords, text) == sorted(expect)


def test_spanish_crisis_on_an_english_call(keywords: KeywordMatcher) -> None:
    """Both language lists always run: a Spanish crisis line on an English call is still caught."""
    assert Intent.crisis in keywords.match("a veces quiero morirme", langs=("en", "es"))


def test_utterance_file_no_false_hits(keywords: KeywordMatcher, redactor: Redactor, utterances: list[dict]) -> None:
    """Over every utterance (both lists): no intent beyond the expected or allowed ones; crisis is never missed."""
    for row in utterances:
        text = redactor.redact(normalize(row["utterance"]), masked=bool(row.get("masked"))).text
        hits = {i.value for i in keywords.match(text)}
        allowed = set(row["expect"]["intents"]) | set(row.get("allow_extra_intents") or [])
        assert not hits - allowed, (row["id"], hits - allowed)
        if "crisis" in row["expect"]["intents"]:
            assert "crisis" in hits, row["id"]


def test_routing_uses_the_keyword_intent_names(keywords: KeywordMatcher) -> None:
    """guards.json routing names exactly the intents the keyword lists produce (the dialogue reads the routing)."""
    routing = GUARDS["input"]["routing"]
    groups = set(GUARDS["input"]["keywords"])
    known = {i.value for i in Intent} | {"redaction"}
    assert set(routing["precedence"]) <= known
    assert groups <= set(routing["precedence"])
    assert routing["precedence"].index("delete_data") < routing["precedence"].index("stop")
    # done phrases count only while close.anything_else is pending (the dialogue checks that)
    assert keywords.is_done_phrase("No, that's all. Thanks.") and keywords.is_done_phrase("Eso es todo.")
    assert not keywords.is_done_phrase("No, but I have one more question.")
    stop_patterns = " ".join(rx.pattern for intent, _lang, rx in keywords.g.keywords if intent == "stop")
    assert "that" not in stop_patterns and "eso es todo" not in stop_patterns


def test_output_lists_block_and_pass() -> None:
    """The output-guard lists (used by the dialogue, card and programs modules) keep their test lines green."""
    import re

    out = GUARDS["output"]
    patterns = [re.compile(p, re.IGNORECASE) for lang in ("en", "es") for p in out["forbidden"][lang]]
    phrases = [p.lower() for p in out["forbidden_phrases"]]

    def hits(text: str) -> int:
        t = normalize(text)
        return sum(1 for rx in patterns if rx.search(t)) + sum(1 for p in phrases if p in t.lower())

    for case in GUARDS["tests"]["output_block"]:
        assert hits(case["text"]) > 0, case["text"]
    for case in GUARDS["tests"]["output_pass"]:
        assert hits(case["text"]) == 0, case["text"]

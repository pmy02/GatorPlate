"""Brain-owned global intents (docs/SPEC.md §3.3): which intent of a turn wins the reply.

The order is data: data/content/guards.json `input.routing.precedence` (delete before stop; "redaction" stands for a
masked or redacted number), its `reply` map and its `close_phase` rule (while `close.anything_else` is pending, a stop
or a "done" phrase gives `close.goodbye`). The gateway does none of this.

This module also reads short answers to the conversation's own yes/no questions (consent, confirm, delete, keep going,
anything else) when no slot carries the answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import Intent, Understanding
from gatorplate.dialogue.output_guard import normalize

# Short yes / no answers (English and Spanish). Only used for the conversation's own yes/no questions; slot answers come
# from the understanding.
_YES = {
    "en": r"^\W*(?:yes|yeah|yea|yep|yup|sure|ok|okay|right|correct|that's right|that is right|of course|please|"
          r"go ahead|keep going|continue|let's keep going|let's continue|i guess so|uh huh|absolutely|definitely)\b",
    "es": r"^\W*(?:s[ií]|claro|correcto|as[ií] es|dale|vale|est[aá] bien|de acuerdo|por supuesto|sigamos|"
          r"seguimos|seguir|contin[uú]a|adelante)\b",
}
_NO = {
    "en": r"^\W*(?:no|nope|nah|not really|no thanks|don't|do not|never mind|stop)\b",
    "es": r"^\W*(?:no|nada|para|paremos|mejor no)\b",
}
_YES_RX = {lang: re.compile(p, re.IGNORECASE) for lang, p in _YES.items()}
_ENGLISH = re.compile(r"\b(?:english|ingl[eé]s)\b", re.IGNORECASE)
_NO_RX = {lang: re.compile(p, re.IGNORECASE) for lang, p in _NO.items()}
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
# A goodbye at the end of other talk ("thanks for watching everybody, see you tomorrow, bye bye") is often the room on
# a speakerphone (a TV, other people), and so is a bare end word ("stop", "bye", "adiós") that the recognizer heard
# with low confidence: such a stop is asked about first ("keep going, or stop here?"). A plain "Bye!", an explicit
# request ("I want to stop", "I have to go, bye", "hang up") and a short thanks-bye ("Okay thanks, bye") still end
# the call at once.
_BARE_STOP = re.compile(
    r"^\W*(?:stop|quit|cancel|goodbye|bye|bye bye|i'?m done|para|basta|ya|adi[oó]s|chao|chau|termina|terminar)\W*$",
    re.IGNORECASE)
_TRAILING_BYE = re.compile(r"\b(?:bye|goodbye|bye bye|bye-bye|adi[oó]s|chao|chau)\W*$", re.IGNORECASE)
_TALK_BEFORE_BYE = 3  # words before a trailing goodbye that make it talk with a goodbye, not a goodbye


def yes_no(text: str, lang: Lang) -> str | None:
    """'yes', 'no' or None for a short spoken or typed answer."""
    clean = normalize(text)
    for code in (lang.value, "en" if lang == Lang.es else "es"):
        if _NO_RX[code].search(clean):
            return "no"
        if _YES_RX[code].search(clean):
            return "yes"
    return None


@dataclass(frozen=True)
class Winner:
    name: str  # an intent name from routing.precedence, or "redaction"
    reply: str  # the routing.reply entry (a sentence key, or "repeat")


class Routing:
    def __init__(self, guards_path: Path) -> None:
        data = json.loads(guards_path.read_text(encoding="utf-8"))
        routing = (data.get("input") or {}).get("routing") or {}
        self.precedence: list[str] = list(routing.get("precedence") or [])
        self.reply: dict[str, object] = dict(routing.get("reply") or {})
        close = routing.get("close_phase") or {}
        self.close_pending: str = str(close.get("pending") or "close.anything_else")
        self.close_reply: str = str(close.get("reply") or "close.goodbye")
        self.done: dict[str, list[re.Pattern[str]]] = {
            lang: [re.compile(p, re.IGNORECASE) for p in (close.get("done") or {}).get(lang) or []]
            for lang in ("en", "es")
        }
        words = close.get("closing_words") or {}
        self.closing_words: dict[str, frozenset[str]] = {
            lang: frozenset(str(w).lower() for w in words.get(lang) or []) for lang in ("en", "es")}
        redact = (data.get("input") or {}).get("redact") or {}
        card_words = redact.get("masked_card_words") or {}
        self.card_words: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for lang in ("en", "es") for p in card_words.get(lang) or []
        ]
        stop = ((data.get("input") or {}).get("keywords") or {}).get("stop") or {}
        self.stop: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for lang in ("en", "es")
                                            for p in stop.get(lang) or []]
        spanish = (data.get("input") or {}).get("spanish_request") or {}
        self.spanish: dict[str, list[re.Pattern[str]]] = {
            lang: [re.compile(p, re.IGNORECASE) for p in spanish.get(lang) or []] for lang in ("en", "es")
        }

    def is_done(self, text: str, lang: Lang) -> bool:
        clean = normalize(text)
        return any(rx.search(clean) for code in (lang.value, "en") for rx in self.done.get(code, []))

    def is_only_done(self, text: str, lang: Lang) -> bool:
        """A done phrase that says nothing else ("No, that's all. Thanks!"): every word is a closing word
        (guards.json close_phase.closing_words). "No thanks, my roommate wants to know if she can apply too" is a done
        phrase that says more: what it says is answered first."""
        if not self.is_done(text, lang):
            return False
        vocab = self.closing_words["en"] | (self.closing_words["es"] if lang != Lang.en else frozenset())
        words = _WORD.findall(normalize(text).lower().replace("\u2019", "'"))
        return bool(words) and all(w in vocab for w in words)

    def weak_stop(self, text: str, confidence: float | None = None, *, low: float = 0.75) -> bool:
        """A stop heard only as a goodbye at the end of other talk, or as a bare end word below `low` recognizer
        confidence (see _TRAILING_BYE); False when the rest of the utterance still asks to stop ("I have to go,
        bye")."""
        clean = normalize(text)
        if _BARE_STOP.search(clean):
            return confidence is not None and confidence < low
        hit = _TRAILING_BYE.search(clean)
        if hit is None:
            return False
        rest = clean[:hit.start()]
        if len(_WORD.findall(rest)) < _TALK_BEFORE_BYE:
            return False
        return not any(rx.search(rest) for rx in self.stop)

    def asks_spanish(self, text: str) -> bool:
        clean = normalize(text)
        return any(rx.search(clean) for rxs in self.spanish.values() for rx in rxs)

    @staticmethod
    def asks_english(text: str) -> bool:
        """A language request that names English ("can we speak English?", "en inglés, por favor"): on the web it
        switches the conversation back (docs/SPEC.md §3.5), never the unsupported-language line."""
        return bool(_ENGLISH.search(normalize(text)))

    def present(self, u: Understanding, *, masked: bool) -> list[str]:
        """Every routing name present in this turn, in precedence order."""
        intents = {i.value for i in u.intents} | {i.value for i in u.keyword_intents}
        out: list[str] = []
        for name in self.precedence:
            if name == "redaction":
                if u.redactions or masked or Intent.ssn_attempt.value in intents:
                    out.append(name)
            elif name in intents:
                out.append(name)
        return out

    def winner(self, u: Understanding, *, masked: bool) -> Winner | None:
        names = self.present(u, masked=masked)
        if not names:
            return None
        name = names[0]
        reply = self.reply.get(name)
        if isinstance(reply, dict):
            kind = self.redaction_kind(u, masked=masked)
            reply = reply.get(kind) or reply.get("ssn")
        return Winner(name=name, reply=str(reply))

    def redaction_kind(self, u: Understanding, *, masked: bool) -> str:
        """'card_number' or 'ssn' (docs/SPEC.md §8.7): a card-like run anywhere in the turn wins; a masked run counts
        as a card number when the words name a card or an account; everything else (a question about a Social
        Security number without digits included) gets the Social Security guidance."""
        if "card_number" in u.redactions:
            return "card_number"
        if not u.redactions and masked and any(rx.search(u.redacted_text) for rx in self.card_words):
            return "card_number"
        return "ssn"

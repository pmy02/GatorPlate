"""Keyword intents: a high-recall backstop for the language model (data/content/guards.json, input.keywords).

A hit adds that intent. The English and Spanish lists both run on every utterance (a crisis line said in Spanish on
an English call must still be caught). Patterns that can end a call (stop, abuse) are narrow in the data file, so
negations ("please don't hang up") and frustration not aimed at GatorPlate do not count.
"""

from __future__ import annotations

import re
from pathlib import Path

from gatorplate.contracts.extraction import Intent
from gatorplate.extract.guards import GuardData, load_guards
from gatorplate.extract.text import normalize

_ORDER = [i.value for i in Intent]


class KeywordMatcher:
    def __init__(self, guards: GuardData | None = None, *, guards_path: Path | None = None) -> None:
        self.g = guards or load_guards(guards_path)
        close = self.g.routing.get("close_phase") or {}
        done = close.get("done") or {}
        self.close_pending: str = str(close.get("pending") or "close.anything_else")
        self.done_by_lang = {lang: [re.compile(p, re.IGNORECASE) for p in done.get(lang, [])] for lang in ("en", "es")}
        self.done_patterns = self.done_by_lang["en"] + self.done_by_lang["es"]
        words = close.get("closing_words") or {}
        self.closing_words = {lang: frozenset(w.lower() for w in words.get(lang, [])) for lang in ("en", "es")}

    def match(self, text: str, langs: tuple[str, ...] = ("en", "es")) -> list[Intent]:
        """Intents whose keyword lists hit the (redacted) utterance, in the contract's intent order."""
        t = normalize(text).lower()
        if not t:
            return []
        hits = {intent for intent, lang, rx in self.g.keywords if lang in langs and rx.search(t)}
        return [Intent(name) for name in _ORDER if name in hits]

    def is_done_phrase(self, text: str, lang: str | None = None) -> bool:
        """A close-phase "done" phrase ("no, that's all", "eso es todo"); the dialogue module owns what it means. With
        `lang`, only that language's phrases and the English ones count, as the dialogue reads them."""
        t = normalize(text)
        patterns = self.done_patterns if lang is None else (
            self.done_by_lang.get(lang, []) + (self.done_by_lang["en"] if lang != "en" else []))
        return any(rx.search(t) for rx in patterns)

    def is_only_done(self, text: str, lang: str | None = None) -> bool:
        """A done phrase that says nothing else ("No, that's all. Thanks!"): every word is a closing word. A done
        phrase followed by more ("That's all. Oh, I forgot, I'm a grad student.") is not: the model still listens."""
        if not self.is_done_phrase(text, lang):
            return False
        vocab = self.closing_words["en"] | (self.closing_words["es"] if lang != "en" else frozenset())
        return closing_only(text, vocab)


_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def closing_only(text: str, vocab: frozenset[str]) -> bool:
    """Every word of the text is in the closing vocabulary (apostrophes folded to ')."""
    t = normalize(text).lower().replace("\u2019", "'")
    words = _WORD.findall(t)
    return bool(words) and all(w in vocab for w in words)

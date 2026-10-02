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
        done = (self.g.routing.get("close_phase") or {}).get("done") or {}
        self.done_patterns = [re.compile(p, re.IGNORECASE) for lang in ("en", "es") for p in done.get(lang, [])]

    def match(self, text: str, langs: tuple[str, ...] = ("en", "es")) -> list[Intent]:
        """Intents whose keyword lists hit the (redacted) utterance, in the contract's intent order."""
        t = normalize(text).lower()
        if not t:
            return []
        hits = {intent for intent, lang, rx in self.g.keywords if lang in langs and rx.search(t)}
        return [Intent(name) for name in _ORDER if name in hits]

    def is_done_phrase(self, text: str) -> bool:
        """A close-phase "done" phrase ("no, that's all", "eso es todo"); the dialogue module owns what it means."""
        t = normalize(text)
        return any(rx.search(t) for rx in self.done_patterns)

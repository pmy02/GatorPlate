"""Loads the input side of data/content/guards.json once per path (redaction, keyword intents, routing).

The output lists of the same file are used by the dialogue and card modules; this module only reads the input part.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_GUARDS = Path(__file__).resolve().parent.parent.parent / "data" / "content" / "guards.json"
LANGS = ("en", "es")


@dataclass(frozen=True)
class GuardData:
    raw: dict[str, Any]
    replacement: str
    card_patterns: tuple[re.Pattern[str], ...]
    ssn_patterns: tuple[re.Pattern[str], ...]
    spoken_patterns: tuple[re.Pattern[str], ...]  # en and es, both always run
    spoken_digit_words: frozenset[str]
    spoken_card_digits: tuple[int, int]
    masked_char: str
    masked_card_words: tuple[re.Pattern[str], ...]
    keywords: tuple[tuple[str, str, re.Pattern[str]], ...]  # (intent, lang, pattern)
    routing: dict[str, Any]


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


@lru_cache(maxsize=8)
def load_guards(path: Path | str | None = None) -> GuardData:
    file = Path(path) if path is not None else DEFAULT_GUARDS
    raw = json.loads(file.read_text(encoding="utf-8"))
    inp = raw["input"]
    red = inp["redact"]
    spoken: list[str] = []
    words: set[str] = set()
    cards: list[str] = []
    for lang in LANGS:
        spoken.extend(red["spoken_digit_patterns"].get(lang, []))
        words.update(w.lower() for w in red["spoken_digit_words"].get(lang, []))
        cards.extend(red["masked_card_words"].get(lang, []))
    keywords: list[tuple[str, str, re.Pattern[str]]] = []
    for intent, by_lang in inp["keywords"].items():
        for lang in LANGS:
            for pattern in by_lang.get(lang, []):
                keywords.append((intent, lang, re.compile(pattern, re.IGNORECASE)))
    low, high = red["spoken_card_digits"]
    return GuardData(
        raw=raw,
        replacement=red["replacement"],
        card_patterns=_compile(red["card_patterns"]),
        ssn_patterns=_compile(red["ssn_patterns"]),
        spoken_patterns=_compile(spoken),
        spoken_digit_words=frozenset(words),
        spoken_card_digits=(int(low), int(high)),
        masked_char=red.get("masked_char", "#"),
        masked_card_words=_compile(cards),
        keywords=tuple(keywords),
        routing=inp.get("routing", {}),
    )

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
    spoken_run_min: int
    # grouped number words ("one twenty three, forty five"): patterns, and per language the words that count two
    # digits, the tens words that take a following unit word, and connector words that count nothing ("y")
    group_patterns: tuple[re.Pattern[str], ...]
    group_two_digit: frozenset[str]
    group_tens: frozenset[str]
    group_skip: frozenset[str]
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
    groups: list[str] = []
    two_digit: set[str] = set()
    tens: set[str] = set()
    skip: set[str] = set()
    for lang in LANGS:
        groups.extend((red.get("spoken_group_patterns") or {}).get(lang, []))
        group_words = (red.get("spoken_group_words") or {}).get(lang) or {}
        two_digit.update(w.lower() for w in group_words.get("two_digit", []))
        tens.update(w.lower() for w in group_words.get("tens", []))
        skip.update(w.lower() for w in group_words.get("skip", []))
    return GuardData(
        raw=raw,
        replacement=red["replacement"],
        card_patterns=_compile(red["card_patterns"]),
        ssn_patterns=_compile(red["ssn_patterns"]),
        spoken_patterns=_compile(spoken),
        spoken_digit_words=frozenset(words),
        spoken_card_digits=(int(low), int(high)),
        spoken_run_min=int(red.get("spoken_digit_run_min", 7)),
        group_patterns=_compile(groups),
        group_two_digit=frozenset(two_digit),
        group_tens=frozenset(tens),
        group_skip=frozenset(skip),
        masked_char=red.get("masked_char", "#"),
        masked_card_words=_compile(cards),
        keywords=tuple(keywords),
        routing=inp.get("routing", {}),
    )

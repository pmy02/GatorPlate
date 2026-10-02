"""Output guard: every final reply string must have zero hits in data/content/guards.json `output.forbidden` (regular
expressions, English and Spanish) and `output.forbidden_phrases` (plain lower-case substrings).

A hit replaces the whole reply with `error.generic` (docs/SPEC.md §3.7); the blocked text is never sent. Matching
follows the file's own format: re.search with re.IGNORECASE on text whose curly quotes are made straight and whose
whitespace is collapsed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


class OutputGuard:
    def __init__(self, guards_path: Path) -> None:
        data = json.loads(guards_path.read_text(encoding="utf-8"))
        output = data.get("output") or {}
        self.patterns: list[re.Pattern[str]] = []
        for lang in ("en", "es"):
            for pattern in (output.get("forbidden") or {}).get(lang) or []:
                self.patterns.append(re.compile(pattern, re.IGNORECASE))
        self.phrases: list[str] = [p.lower() for p in output.get("forbidden_phrases") or []]

    def hits(self, text: str) -> list[str]:
        """The rules one string breaks (pattern or phrase), never the matched text."""
        clean = normalize(text)
        low = clean.lower()
        out = [f"pattern {i}" for i, rx in enumerate(self.patterns) if rx.search(clean)]
        out += [f"phrase {p!r}" for p in self.phrases if p in low]
        return out

    def blocked(self, texts: Iterable[str | None]) -> bool:
        return any(self.hits(t) for t in texts if t)

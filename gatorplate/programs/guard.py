"""The programs part's own output check over data/content/guards.json (`output.forbidden` regexes in en and es,
`output.forbidden_phrases` substrings), as the guards file defines it: re.search with re.IGNORECASE on text with
curly quotes made straight and whitespace collapsed; phrases are lower-case substrings. Every UnlockedView string
passes it; a hit at run time drops the part for that request (the card still shows without it)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from gatorplate.contracts.programs import UnlockedView

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


def view_strings(view: UnlockedView) -> list[str]:
    """Every string the card widget can show (or share) from one UnlockedView."""
    out: list[str | None] = [view.title, view.total_text, view.share_text, view.footnote, *view.chips,
                             *view.labels.values()]
    if view.question is not None:
        out.append(view.question.text)
        out.extend(c.label for c in view.question.choices)
    for p in view.programs:
        out.extend([p.name, p.status_label, p.value_text, p.line, *p.notes, p.stage_label, p.apply_by_text,
                    p.apply_label, p.source_text])
        for row in p.prefill:
            out.extend([row.screen, row.question, row.answer])
    return [s for s in out if s]


class OutputGuard:
    def __init__(self, patterns: list[str], phrases: list[str]) -> None:
        self._regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        self._phrases = [p.lower() for p in phrases]
        # one pass first; the per-rule list is built only for a text that hits something
        self._any = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE) if patterns else None

    @classmethod
    def from_file(cls, path: Path) -> OutputGuard:
        data = json.loads(path.read_text(encoding="utf-8"))
        output = data["output"]
        patterns = [p for lang in ("en", "es") for p in output["forbidden"].get(lang, [])]
        return cls(patterns, list(output["forbidden_phrases"]))

    def hits(self, text: str) -> list[str]:
        """The patterns and phrases a text hits (empty = clean). Returns the rule, never the text."""
        clean = normalize(text)
        low = clean.lower()
        if (self._any is None or not self._any.search(clean)) and not any(p in low for p in self._phrases):
            return []
        found = [rx.pattern for rx in self._regexes if rx.search(clean)]
        found += [p for p in self._phrases if p in low]
        return found

    def view_hits(self, view: UnlockedView) -> list[str]:
        return [hit for s in view_strings(view) for hit in self.hits(s)]

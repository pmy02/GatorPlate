"""The output guard for card strings: zero hits in output.forbidden (regex, en and es) and output.forbidden_phrases
(plain lower-case substrings) of data/content/guards.json, on text normalized the same way as for replies: curly
quotes made straight, whitespace collapsed (docs/SPEC.md §6.4)."""

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
        data = json.loads(Path(guards_path).read_text(encoding="utf-8"))
        output = data["output"]
        self._patterns = [re.compile(p, re.IGNORECASE) for lang in ("en", "es") for p in output["forbidden"][lang]]
        self._phrases = [p.lower() for p in output["forbidden_phrases"]]

    def hits(self, text: str) -> list[str]:
        """The pattern or phrase each hit came from (empty when the text is clean)."""
        clean = normalize(text)
        low = clean.lower()
        found = [rx.pattern for rx in self._patterns if rx.search(clean)]
        found += [p for p in self._phrases if p in low]
        return found

    def clean(self, text: str) -> bool:
        return not self.hits(text)

    def all_clean(self, texts: Iterable[str]) -> bool:
        return all(self.clean(t) for t in texts if t)

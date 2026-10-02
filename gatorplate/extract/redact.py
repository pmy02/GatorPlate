"""Redaction: removes long digit runs before anything else sees the utterance (docs/SPEC.md §8.7).

Order (data/content/guards.json, input.redact): card-like written runs (13-19 digits), then any other written run of 9
or more digits (up to three spaces, dots, dashes or parentheses may separate the digits, so "(415) 338-1203" counts),
then spoken digit runs of 7 or more digit words (English and Spanish lists both run, because a student may switch
languages mid-call). Each hit is replaced with the file's replacement text and only its kind is recorded:
`card_number` for a written card run or a spoken run of 13-19 digits, `ssn` for every other run. A phone utterance
with `masked: true` is a hit too: the gateway already replaced the run with '#', the number of '#' means nothing, so
the kind is `card_number` when the utterance names a card or a bank account and `ssn` otherwise; grouped '#' runs
("###-##-####") are one removed number.

On the web this is the only protection; nothing downstream (model, logs, case, live transcript) sees the digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from gatorplate.extract.guards import GuardData, load_guards

Kind = Literal["ssn", "card_number"]
_TOKEN = re.compile(r"[^\W\d_]+|\d")


@dataclass(frozen=True)
class Redaction:
    text: str  # the redacted utterance
    kinds: list[Kind] = field(default_factory=list)  # distinct kinds, card first

    @property
    def hit(self) -> bool:
        return bool(self.kinds)


class Redactor:
    def __init__(self, guards: GuardData | None = None, *, guards_path: Path | None = None) -> None:
        self.g = guards or load_guards(guards_path)
        mask = re.escape(self.g.masked_char)
        # "###-##-####" or "#### #### ####" is one removed number: one replacement, not three.
        self._masked_run = re.compile(mask + r"+(?:[ .()-]{1,3}" + mask + "+)*")

    def _spoken_digits(self, match: str) -> int:
        tokens = _TOKEN.findall(match.lower())
        return sum(1 for tok in tokens if tok.isdigit() or tok in self.g.spoken_digit_words)

    def redact(self, text: str, *, masked: bool = False) -> Redaction:
        """Redact one (already normalized) utterance."""
        kinds: list[Kind] = []

        def note(kind: Kind) -> None:
            if kind not in kinds:
                kinds.append(kind)

        out = text
        rep = self.g.replacement
        for rx in self.g.card_patterns:
            out, n = rx.subn(rep, out)
            if n:
                note("card_number")
        for rx in self.g.ssn_patterns:
            out, n = rx.subn(rep, out)
            if n:
                note("ssn")
        low, high = self.g.spoken_card_digits
        for rx in self.g.spoken_patterns:
            def spoken(m: re.Match[str]) -> str:
                count = self._spoken_digits(m.group(0))
                note("card_number" if low <= count <= high else "ssn")
                return rep
            out = rx.sub(spoken, out)
        if masked:
            out = self._masked_run.sub(rep, out)
            note("card_number" if any(rx.search(text) for rx in self.g.masked_card_words) else "ssn")
        kinds.sort(key=lambda k: 0 if k == "card_number" else 1)
        return Redaction(text=out, kinds=kinds)

"""The sentence bank (data/content/sentences.{en,es}.json) and the public contacts (data/content/contacts.json).

Every spoken or displayed sentence comes from the bank; code fills every {var} and never writes wording of its own
(docs/SPEC.md §3, docs/BRAIN_API.md §6-§7). A message holds variants per channel (`phone`, `web`, `all`) for its main
form and optional `closed` and `short` forms; a variant is a string or `{say, ask}`. A string variant of a key that has
an `expect` block is the question (`ask`); otherwise it is said. The variant is chosen deterministically from
(call_id, key, turn) with SHA-256, never Python's salted hash().
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gatorplate.contracts.common import Channel, Lang

FORMS = ("main", "closed", "short", "demo")  # demo: the short phone opening and two read-backs (GP_DEMO_SHORTCUT)
Variant = str | dict


def pick_index(call_id: str, key: str, turn: int, n: int) -> int:
    """Deterministic variant choice across processes and restarts."""
    if n <= 1:
        return 0
    digest = hashlib.sha256(f"{call_id}|{key}|{turn}".encode()).hexdigest()
    return int(digest, 16) % n


@dataclass
class Step:
    """One sentence key in a planned reply. `question` fills the {question} var of the re-ask wrappers
    (reprompt.*, ssn.block, card_number.block); `vars` overrides the values code would compute."""

    key: str
    form: str = "main"
    vars: dict[str, Any] = field(default_factory=dict)
    question: Step | None = None

    def encode(self) -> str:
        """Compact form kept in SessionState.deferred_keys ("card.phone_code", "ask.rent:short")."""
        return self.key if self.form == "main" else f"{self.key}:{self.form}"

    @classmethod
    def decode(cls, text: str) -> Step:
        key, _, form = text.partition(":")
        return cls(key=key, form=form or "main")


class Bank:
    """Both sentence banks and the contacts file, loaded once."""

    def __init__(self, content_dir: Path) -> None:
        self.content_dir = content_dir
        self.banks: dict[Lang, dict[str, Any]] = {}
        for lang in (Lang.en, Lang.es):
            self.banks[lang] = json.loads((content_dir / f"sentences.{lang.value}.json").read_text(encoding="utf-8"))
        self.contacts: dict[str, Any] = json.loads((content_dir / "contacts.json").read_text(encoding="utf-8"))
        self.messages: dict[Lang, dict[str, dict[str, Any]]] = {lang: b["messages"] for lang, b in self.banks.items()}
        self.confirm_policy: dict[str, Any] = self.banks[Lang.en].get("confirm_policy") or {}

    # ------------------------------------------------------------------------------------------ lookups

    def has(self, key: str) -> bool:
        return key in self.messages[Lang.en]

    def message(self, key: str, lang: Lang = Lang.en) -> dict[str, Any]:
        msgs = self.messages[lang]
        if key in msgs:
            return msgs[key]
        return self.messages[Lang.en][key]

    def group(self, key: str) -> str:
        return str(self.message(key).get("group") or "")

    def var_types(self, key: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for spec in self.message(key).get("vars") or []:
            name, _, kind = str(spec).partition(":")
            out[name] = kind or "text"
        return out

    def is_question(self, key: str) -> bool:
        return "expect" in self.message(key)

    def expect(self, key: str, form: str = "main", lang: Lang = Lang.en) -> dict[str, Any] | None:
        """The expect block of a form: closed.expect overrides the main expect when present."""
        msg = self.message(key, lang)
        if form == "closed":
            closed = msg.get("closed")
            if isinstance(closed, dict) and isinstance(closed.get("expect"), dict):
                return closed["expect"]
        expect = msg.get("expect")
        return expect if isinstance(expect, dict) else None

    def _lists(self, msg: dict[str, Any], form: str) -> dict[str, list[Variant]]:
        node = msg if form == "main" else msg.get(form)
        if not isinstance(node, dict):
            return {}
        return {f: node[f] for f in ("phone", "web", "all") if isinstance(node.get(f), list) and node[f]}

    def variants(self, key: str, lang: Lang, channel: Channel, form: str = "main") -> list[Variant]:
        """Variants of one form for a channel: the channel's own list, else `all`. A form the message lacks falls back
        to the main form; a language without the key (or without the channel) falls back to English, and a channel
        without variants to the other channel's list."""
        for try_lang in (lang, Lang.en) if lang != Lang.en else (Lang.en,):
            msgs = self.messages[try_lang]
            if key not in msgs:
                continue
            msg = msgs[key]
            for try_form in (form, "main") if form != "main" else ("main",):
                lists = self._lists(msg, try_form)
                other = Channel.web if channel == Channel.phone else Channel.phone
                found = lists.get(channel.value) or lists.get("all") or lists.get(other.value)
                if found:
                    return list(found)
        raise KeyError(f"no variants for sentence key {key!r}")

    def pick(self, key: str, lang: Lang, channel: Channel, form: str, *, call_id: str, turn: int) -> Variant:
        variants = self.variants(key, lang, channel, form)
        return variants[pick_index(call_id, key, turn, len(variants))]

    # ------------------------------------------------------------------------------------------ contacts

    def contact(self, path: str) -> Any:
        node: Any = self.contacts
        for part in path.split("."):
            node = node[part]
        return node

    def spoken_period(self, period: str, lang: Lang) -> str:
        table = (self.banks[lang].get("spoken") or {}).get("period") or {}
        return str(table.get(period) or self.banks[Lang.en]["spoken"]["period"].get(period) or "")


# ---------------------------------------------------------------------------------------------- rendering

@dataclass
class Rendered:
    """One planned reply rendered for one audience: `say` and `ask` (spoken forms) and the same text with display
    formats (web `display`), plus the keys used and the question's expect block."""

    keys: list[str]
    say: str
    ask: str | None
    display_say: str
    display_ask: str | None
    question: Step | None
    expect: dict[str, Any] | None


def _join(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def fill(text: str, values: dict[str, str]) -> str:
    """Replace every {var} the values know; an unknown var is a bank or code error (KeyError)."""
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


class Renderer:
    """Turns planned steps into text. `values(step, mode)` returns the formatted vars of a step: mode "spoken" (phone
    text and the web's spoken `say`/`ask`) or "display" (the web `display`)."""

    def __init__(self, bank: Bank, values: Callable[[Step, str, Lang], dict[str, str]]) -> None:
        self.bank = bank
        self.values = values

    def _parts(self, step: Step, lang: Lang, channel: Channel, mode: str, *, call_id: str,
               turn: int) -> tuple[str | None, str | None]:
        variant = self.bank.pick(step.key, lang, channel, step.form, call_id=call_id, turn=turn)
        values = self.values(step, mode, lang)
        if "question" in self.bank.var_types(step.key) or (isinstance(variant, dict) and "{question}" in str(variant)):
            values = dict(values)
            values["question"] = self._question_text(step.question, lang, channel, mode, call_id=call_id, turn=turn)
        if isinstance(variant, dict):
            say = fill(variant.get("say") or "", values) or None
            ask = fill(variant.get("ask") or "", values) or None
            return say, ask
        text = fill(variant, values)
        if self.bank.is_question(step.key):
            return None, text
        return text, None

    def _question_text(self, step: Step | None, lang: Lang, channel: Channel, mode: str, *, call_id: str,
                       turn: int) -> str:
        if step is None:
            return ""
        say, ask = self._parts(step, lang, channel, mode, call_id=call_id, turn=turn)
        return ask or say or ""

    def render(self, steps: list[Step], lang: Lang, channel: Channel, *, call_id: str, turn: int) -> Rendered:
        says: list[str] = []
        shows: list[str] = []
        ask: str | None = None
        show_ask: str | None = None
        question: Step | None = None
        for i, step in enumerate(steps):
            say, q = self._parts(step, lang, channel, "spoken", call_id=call_id, turn=turn)
            dsay, dq = self._parts(step, lang, channel, "display", call_id=call_id, turn=turn)
            last = i == len(steps) - 1
            if say:
                says.append(say)
                shows.append(dsay or "")
            if q is not None:
                if last:
                    ask, show_ask = q, dq
                    question = step.question if step.question is not None else step
                else:  # a question can only come last; an earlier one is said as a statement
                    says.append(q)
                    shows.append(dq or "")
        expect = None
        if question is not None:
            expect = self.bank.expect(question.key, question.form, lang)
        keys = [k for s in steps for k in ([s.key] + ([s.question.key] if s.question is not None else []))]
        return Rendered(keys=keys, say=_join(says), ask=ask or None, display_say=_join(shows),
                        display_ask=show_ask or None, question=question, expect=expect)

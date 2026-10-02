"""UnlockedView: the card's "money you may be missing" part in one language (docs/SPEC.md §6.6, docs/UI_SPEC.md A4.2
row 2b). Every word comes from data/content/programs.{en,es}.json (its `format` section is the rulebook); code
fills each placeholder with a value the engine computed and never writes wording of its own.

Money placeholders get '$' and a thousands comma; display values are floored to the table's display step, exact
ones (the monthly estimate, the assumed bill, a slot value) are shown as they are. A template whose placeholder has
no value is not shown (a line falls back to its amount-free list_only line).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from gatorplate.contracts.common import CardRow, Lang
from gatorplate.contracts.programs import ProgramLine, UnlockedChoice, UnlockedProgram, UnlockedQuestion, UnlockedView
from gatorplate.contracts.slots import CENT
from gatorplate.programs.models import floor_to
from gatorplate.programs.plan import KEY_LINE
from gatorplate.programs.table import Program, ProgramsTable, TableError

if TYPE_CHECKING:
    from gatorplate.programs.engine import Computed

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
VERIFY_MARK = re.compile(r"\s*\[verify\]\s*$")
LABEL_KEYS = ("ui.claimed", "ui.calfresh_part", "ui.key_line", "ui.question_count", "ui.plan_title",
              "ui.answers_title", "ui.new_tab", "ui.mark_applied", "ui.undo", "ui.share_button", "ui.copied",
              "ui.list_only_intro")
RAW_LABELS = ("ui.question_count",)  # the widget fills {i} / {n}


class Content:
    """One language of programs.*.json."""

    def __init__(self, doc: dict, lang: Lang) -> None:
        self.lang = lang
        self.strings: dict[str, str] = doc["strings"]
        self.programs: dict[str, dict] = doc["programs"]
        self.links: dict[str, str] = doc["links"]
        self.sources: dict[str, dict] = doc["sources"]
        self.console_keys: list[str] = list(doc["console_keys"])
        self.money_kinds = {name: spec["type"] for name, spec in doc["placeholders"].items()}
        self.months = self.text("ui.months").split()
        self.months_short = self.text("ui.months_short").split()

    def text(self, key: str) -> str:
        return self.strings[key]

    def has(self, key: str | None) -> bool:
        return bool(key) and key in self.strings


def load_content(path: Path, table: ProgramsTable, lang: Lang) -> Content:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("lang") != lang.value:
        raise TableError(f"{path.name}: lang must be {lang.value}")
    content = Content(doc, lang)
    missing: list[str] = []
    for key in (*LABEL_KEYS, "ui.title", "ui.total", "ui.footnote", "ui.list_only_title", "ui.apply_by",
                "ui.source", "share.text", "ui.date.month_day", "ui.date.full"):
        if key not in content.strings:
            missing.append(key)
    if len(content.months) != len(content.months_short) or not content.months:
        missing.append("ui.months / ui.months_short (one name per month)")
    for p in [KEY_LINE, *(p.id for p in table.programs)]:
        entry = content.programs.get(p)
        if entry is None:
            missing.append(f"programs.{p}")
            continue
        if entry.get("apply") not in content.links or not entry.get("sources"):
            missing.append(f"programs.{p}: apply link or sources")
    for qid, q in table.questions.items():
        missing += [k for k in [f"q.{qid}", *(f"q.{qid}.{c}" for c in q.choices)] if k not in content.strings]
    for prog in table.programs:
        keys = [n for r in prog.status_rules for n in r.notes] + list(prog.note_rules) + list(prog.notes_always)
        keys += [prog.calfresh_link.text_key] + [r.question_key for r in prog.prefill]
        keys += [r.answer_key for r in prog.prefill if r.answer_key]
        missing += [k for k in keys if k not in content.strings]
    if missing:
        raise TableError(f"{path.name}: missing {sorted(set(missing))}")
    return content


@dataclass
class ViewInput:
    computed: Computed
    table: ProgramsTable
    content: Content
    site: str
    household_food: str | None


def site_origin(base_url: str) -> str:
    """The public site's origin (http or https, host and port), never a path, a query or a user name or password
    from the setting: the share text never carries a card link or anything secret."""
    try:
        parts = urlsplit(base_url.strip())
        host, port = parts.hostname, parts.port
    except ValueError:  # a malformed host or port
        return ""
    if parts.scheme.lower() not in ("http", "https") or not host:
        return ""
    if ":" in host:  # an IPv6 address keeps its brackets
        host = f"[{host}]"
    return f"{parts.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def usd_whole(amount: int) -> str:
    return f"${amount:,}"


def usd_exact(amount: Decimal | int) -> str:
    """An exact amount: whole dollars without cents ("$900"), otherwise always two decimals ("$1,169.10")."""
    number = Decimal(amount)
    if number == number.to_integral_value():
        return f"${int(number):,}"
    return f"${number.quantize(CENT, rounding=ROUND_FLOOR):,}"


def fill(template: str, values: dict[str, str]) -> str | None:
    """The template with every placeholder filled, or None when one has no value."""
    names = PLACEHOLDER.findall(template)
    if any(n not in values for n in names):
        return None
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


class _Speaker:
    """Formats one evaluation in one language."""

    def __init__(self, vi: ViewInput) -> None:
        self.vi = vi
        self.c = vi.content
        self.t = vi.table
        self.step = vi.table.money.display_round_down_to

    def money(self, name: str, raw: str) -> str:
        """A raw engine number as the placeholder's display text."""
        kind = self.c.money_kinds.get(name)
        if kind == "money":
            return usd_whole(floor_to(int(raw), self.step))
        if kind == "money_exact":
            return usd_exact(Decimal(raw))
        return raw

    def values(self, line: ProgramLine) -> dict[str, str]:
        return {name: self.money(name, raw) for name, raw in line.vars.items()}

    def month_day(self, day: date) -> str:
        return fill(self.c.text("ui.date.month_day"), {"month": self.c.months[day.month - 1],
                                                       "day": str(day.day)}) or ""

    def full_date(self, day: date) -> str:
        return fill(self.c.text("ui.date.full"), {"month": self.c.months_short[day.month - 1], "day": str(day.day),
                                                  "year": str(day.year)}) or ""

    def program(self, line: ProgramLine) -> Program | None:
        for p in self.t.programs:
            if p.id == line.id:
                return p
        return None

    # -------------------------------------------------------------------------------------------- one program

    def line_key(self, line: ProgramLine) -> str | None:
        node = self.c.programs[line.id]["lines"].get(line.status)
        if isinstance(node, dict):
            variant = self.vi.computed.variants.get(line.id)
            return node.get(variant) if variant else None
        return node

    def line_text(self, line: ProgramLine, values: dict[str, str], full: bool) -> tuple[str, str | None]:
        entry = self.c.programs[line.id]
        if full:
            key = self.line_key(line)
            if self.c.has(key):
                text = fill(self.c.text(key), values)  # type: ignore[arg-type]
                if text is not None:
                    return text, key
        fallback = entry.get("list_only")
        if self.c.has(fallback):
            return self.c.text(fallback), fallback
        return self.c.text(entry["name"]), None

    def notes(self, line: ProgramLine, line_key: str | None, values: dict[str, str], full: bool) -> list[str]:
        if not full:
            return []
        keys = list(line.note_keys)
        if line.status in self.t.plan.include:
            program = self.program(line)
            if program is not None:
                keys.append(program.calfresh_link.text_key)
            keys += [k for k in self.c.programs[line.id].get("notes", []) if k.endswith(".basis")]
        out: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if key == line_key or key in seen or not self.c.has(key):
                continue
            seen.add(key)
            text = fill(self.c.text(key), values)
            if text is not None:
                out.append(text)
        return out

    def value_text(self, line: ProgramLine, values: dict[str, str], full: bool) -> str | None:
        if not full or (line.status in ("likely", "maybe") and not line.display_yearly):
            return None  # never "about $0" (a tax line downgraded to "a small amount" has no number to show)
        key = (self.c.programs[line.id].get("value_text") or {}).get(line.status)
        return fill(self.c.text(key), values) if self.c.has(key) else None

    def prefill(self, line: ProgramLine, full: bool) -> list[CardRow]:
        program = self.program(line)
        if not full or program is None or line.status not in self.t.plan.include:
            return []
        rows: list[CardRow] = []
        for row in program.prefill:
            answer = self.prefill_answer(row.answer_key, row.answer_from)
            if answer is None:
                continue
            rows.append(CardRow(screen=VERIFY_MARK.sub("", row.screen), question=self.c.text(row.question_key),
                                answer=answer))
        return rows

    def prefill_answer(self, answer_key: str | None, answer_from: str | None) -> str | None:
        if answer_key:
            return self.c.text(answer_key)
        kind, _, name = (answer_from or "").partition(":")
        facts = self.vi.computed.facts
        key: str | None = None
        values: dict[str, str] = {}
        if kind == "answer":
            choice = self.vi.computed.answers.get(name)
            key = f"pf.answer.{name}.{choice}" if choice else None
        elif name == "earned_monthly" and facts.earned_monthly is not None:
            key, values = "pf.answer.earned_monthly", {"amount": usd_exact(facts.earned_monthly)}
        elif name == "household_food" and self.vi.household_food:
            key = f"pf.answer.household_food.{self.vi.household_food}"
        elif name == "people_in_home":
            key, values = "pf.answer.people_in_home", {"count": str(facts.people_in_home)}
        elif name == "half_time" and facts.half_time is not None:
            key = f"pf.answer.half_time.{'true' if facts.half_time else 'false'}"
        if not self.c.has(key):
            return None
        return fill(self.c.text(key), values)  # type: ignore[arg-type]

    def source_text(self, line_id: str) -> str:
        sid = self.c.programs[line_id]["sources"][0]
        src = self.c.sources[sid]
        return fill(self.c.text("ui.source"), {"source": src["name"], "date": src["date_text"]}) or ""

    def unlocked_program(self, line: ProgramLine, full: bool) -> UnlockedProgram:
        entry = self.c.programs[line.id]
        values = self.values(line)
        text, key = self.line_text(line, values, full)
        planned = full and line.status in self.t.plan.include
        apply_key = entry["apply"]
        return UnlockedProgram(
            id=line.id, name=self.c.text(entry["name"]), status=line.status,
            status_label=self.c.text(f"ui.status.{line.status}"),
            value_text=self.value_text(line, values, full), counted=line.counted, line=text,
            notes=self.notes(line, key, values, full),
            stage=line.stage, stage_label=self.c.text(f"ui.stage.{line.stage}"),
            apply_by_text=fill(self.c.text("ui.apply_by"), {"date": self.month_day(line.apply_by)})
            if (full and line.apply_by) else None,
            apply_url=self.c.links[apply_key], apply_label=self.c.text(apply_key),
            applied=line.applied, can_mark_applied=planned,
            prefill=self.prefill(line, full), source_text=self.source_text(line.id),
        )

    # -------------------------------------------------------------------------------------------- the part

    def chips(self, lines: list[ProgramLine]) -> list[str]:
        out: list[str] = []
        for line in lines:
            key = (self.c.programs[line.id].get("chip") or {}).get(line.status)
            if not self.c.has(key):
                continue
            if line.status == "maybe" and not line.display_yearly:
                continue  # "maybe +$0" says nothing
            text = fill(self.c.text(key), self.values(line))  # type: ignore[arg-type]
            if text is not None:
                out.append(text)
        return out

    def question(self) -> UnlockedQuestion | None:
        result = self.vi.computed.result
        qid = result.next_question
        if qid is None:
            return None
        q = self.t.questions[qid]
        answered = self.vi.computed.answered
        return UnlockedQuestion(id=qid, text=self.c.text(f"q.{qid}"),
                                choices=[UnlockedChoice(value=c, label=self.c.text(f"q.{qid}.{c}")) for c in q.choices],
                                index=answered + 1, total=answered + len(result.open_questions))

    def labels(self, full: bool) -> dict[str, str]:
        result = self.vi.computed.result
        values: dict[str, str] = {}
        if full:
            calfresh = next((ln for ln in result.lines if ln.id == KEY_LINE), None)
            values = {"found": usd_whole(result.found_display or 0), "claimed": usd_whole(result.claimed_display)}
            if calfresh is not None:
                values["calfresh_year"] = usd_whole(calfresh.display_yearly or 0)
                values["calfresh_month"] = self.money("calfresh_month", calfresh.vars.get("calfresh_month", "0"))
        out: dict[str, str] = {}
        for key in LABEL_KEYS:
            text = self.c.text(key) if key in RAW_LABELS else fill(self.c.text(key), values)
            if text is not None:
                out[key] = text
        return out

    def view(self) -> UnlockedView:
        result = self.vi.computed.result
        full = result.mode == "full"
        lines = result.lines
        calfresh = next((ln for ln in lines if ln.id == KEY_LINE), None)
        share_text = None
        site = site_origin(self.vi.site)
        if full and result.share_display and site:
            share_text = fill(self.c.text("share.text"), {"share": usd_whole(result.share_display), "site": site})
        return UnlockedView(
            mode=result.mode,
            title=self.c.text("ui.title" if full else "ui.list_only_title"),
            total_text=fill(self.c.text("ui.total"), {"found": usd_whole(result.found_display or 0)}) if full else None,
            found_display=result.found_display, claimed_display=result.claimed_display,
            calfresh_display=calfresh.display_yearly if (full and calfresh) else None,
            segments=[(ln.id, ln.display_yearly or 0) for ln in lines if ln.counted] if full else [],
            question=self.question() if full else None,
            chips=self.chips(lines) if full else [],
            programs=[self.unlocked_program(ln, full) for ln in lines],
            share_text=share_text,
            footnote=fill(self.c.text("ui.footnote"), {"checked": self.full_date(self.t.checked)}) or "",
            labels=self.labels(full),
            lang=self.c.lang,
        )


def build_view(vi: ViewInput) -> UnlockedView | None:
    return _Speaker(vi).view()

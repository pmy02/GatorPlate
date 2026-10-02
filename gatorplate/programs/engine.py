"""Programs: the ProgramsPort (docs/SPEC.md §5.10 and §6.6; docs/UI_SPEC.md A4.2 row 2b).

Pure: the programs table, the card content (programs.en.json, programs.es.json) and the output guard lists are loaded
once at construction; nothing is read or written after that. The engine reads a Case (slots, the CalFresh result the
rules wrote, the card answers and "I applied" marks) and never changes it. The core (`compute`) takes ProgramFacts,
answers, progress and today, so the golden cases call it directly.
"""

from __future__ import annotations

import decimal
import fnmatch
import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from gatorplate.contracts.case import Case
from gatorplate.contracts.common import Lang
from gatorplate.contracts.errors import InvalidRequest
from gatorplate.contracts.programs import ProgramLine, ProgramMode, ProgramsMeta, ProgramsResult, UnlockedView
from gatorplate.contracts.rules_io import SourceRef
from gatorplate.contracts.slots import SlotName
from gatorplate.programs import models
from gatorplate.programs.ask import plan_questions
from gatorplate.programs.conditions import Context, RowNotValid, holds, holds_quietly
from gatorplate.programs.facts import FACT_NAMES, ProgramFacts, facts_from_case
from gatorplate.programs.guard import OutputGuard
from gatorplate.programs.plan import KEY_LINE, Draft, ordered
from gatorplate.programs.table import (
    CoverageOnly,
    FlatMonthly,
    FlatRow,
    Program,
    ProgramsTable,
    TaxCredits,
    TransitBreaks,
    UtilityShare,
    load_table,
    valid_on,
    value_rows,
)
from gatorplate.programs.view import Content, ViewInput, build_view, load_content

log = logging.getLogger("gatorplate.programs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TABLE = REPO_ROOT / "data" / "rules" / "programs_2026.json"
DEFAULT_CONTENT = REPO_ROOT / "data" / "content"
LANGS = (Lang.en, Lang.es)


def _exact() -> AbstractContextManager[decimal.Context]:
    """A fresh default Decimal context (28 digits) for every evaluation, whatever the calling thread's context says:
    the values, floors and console trace never depend on a precision or rounding set elsewhere."""
    return decimal.localcontext(decimal.Context())


@dataclass
class Computed:
    """One evaluation: the language-free result, plus what the view needs to speak it."""

    result: ProgramsResult
    facts: ProgramFacts
    answers: dict[str, str]
    variants: dict[str, str]
    answered: int


class Programs:
    """The programs engine. `Programs(enabled=False)` (GP_PROGRAMS=0) needs nothing and answers None / False."""

    def __init__(self, *, enabled: bool = True, table_path: Path | None = None, content_dir: Path | None = None,
                 guards_path: Path | None = None, public_base_url: str = "") -> None:
        self.enabled = enabled
        self.table_path = table_path
        self.content_dir = content_dir
        self.guards_path = guards_path
        self.public_base_url = public_base_url
        if not enabled:
            return
        content_root = Path(content_dir) if content_dir is not None else DEFAULT_CONTENT
        self.table: ProgramsTable = load_table(Path(table_path) if table_path is not None else DEFAULT_TABLE,
                                               set(FACT_NAMES))
        self.content: dict[Lang, Content] = {lang: load_content(content_root / f"programs.{lang.value}.json",
                                                                self.table, lang)
                                             for lang in LANGS}
        self.guard = OutputGuard.from_file(Path(guards_path) if guards_path is not None
                                           else content_root / "guards.json")
        self._rows = self.table.rows
        self._priority = {p.id: p.priority for p in self.table.programs}
        self._ride_question = self._find_ride_question()

    @classmethod
    def from_settings(cls, settings: Any) -> Programs:
        """Reads GP_PROGRAMS, GP_PROGRAMS_TABLE and GP_PUBLIC_BASE_URL."""
        return cls(enabled=settings.programs, table_path=settings.programs_table_path,
                   content_dir=settings.content_dir, guards_path=settings.guards_path,
                   public_base_url=settings.public_base_url)

    # ------------------------------------------------------------------------------------------ ProgramsPort

    def evaluate(self, case: Case, *, today: date) -> ProgramsResult | None:
        if not self.enabled:
            return None
        computed = self._compute_case(case, today)
        return computed.result if computed else None

    def view(self, case: Case, *, lang: Lang, today: date) -> UnlockedView | None:
        if not self.enabled:
            return None
        computed = self._compute_case(case, today)
        if computed is None:
            return None
        language = Lang(lang)
        household_food = case.slots.get(SlotName.household_food)
        with _exact():
            view = build_view(ViewInput(computed=computed, table=self.table, content=self.content[language],
                                        site=self.public_base_url,
                                        household_food=household_food.value if household_food else None))
        if view is None or self.guard.view_hits(view):
            log.warning("programs guard_hit")
            return None
        return view

    def validate_answers(self, case: Case, answers: dict[str, str], *, today: date) -> dict[str, str]:
        if not self.enabled:
            # Never reached: with GP_PROGRAMS=0 the card endpoints answer 404 first.
            raise InvalidRequest("Other programs are switched off.")
        computed = self._compute_case(case, today)
        if computed is None or computed.result.mode != "full":
            raise InvalidRequest("This card has no questions.")
        if not answers:
            raise InvalidRequest("Send at least one answer.")
        open_now = set(computed.result.open_questions)
        out: dict[str, str] = {}
        for qid, choice in answers.items():
            question = self.table.questions.get(qid)
            if question is None:
                raise InvalidRequest("Unknown question.")
            if choice not in question.choices:
                raise InvalidRequest("Unknown choice for this question.")
            if qid not in open_now and qid not in computed.answers:
                raise InvalidRequest("This question is not open for this card.")
            out[qid] = choice
        return out

    def can_mark(self, case: Case, program: str, *, today: date) -> bool:
        if not self.enabled:
            return False
        computed = self._compute_case(case, today)
        if computed is None or computed.result.mode != "full":
            return False
        return any(line.id == program and line.status in self.table.plan.include for line in computed.result.lines)

    def meta(self) -> ProgramsMeta | None:
        if not self.enabled:
            return None
        en = self.content[Lang.en]
        ids = [p.id for p in sorted(self.table.programs, key=lambda p: p.priority)]
        return ProgramsMeta(
            table_id=self.table.id, label=self.table.label, checked=self.table.checked,
            effective_from=self.table.effective[0], effective_to=self.table.effective[1],
            programs=ids,
            names={pid: en.text(f"program.{pid}") for pid in [KEY_LINE, *ids]},
            console_texts={key: en.text(key) for key in en.console_keys},
            questions=list(self.table.questions),
            sources=[SourceRef(id=s.id, title=s.title, date=s.date, grade=s.grade, url=s.url)
                     for s in self.table.sources],
        )

    # ------------------------------------------------------------------------------------------ core

    def compute(self, facts: ProgramFacts, *, answers: Mapping[str, str], progress: Mapping[str, bool],
                today: date) -> Computed | None:
        """The whole evaluation for one set of facts on one Pacific date. None = no programs part."""
        with _exact():
            return self._compute(facts, answers=answers, progress=progress, today=today)

    def _compute(self, facts: ProgramFacts, *, answers: Mapping[str, str], progress: Mapping[str, bool],
                 today: date) -> Computed | None:
        if not self.enabled or not self.table.effective_on(today):
            return None
        mode = self.mode_of(facts.route)
        if mode is None or (mode == "full" and facts.calfresh_monthly is None):
            return None
        valid = self._valid_answers(answers)
        drafts = self._drafts(facts, valid, progress, today, mode)
        lines = ordered(drafts, stages=self.table.plan.stages, include=self.table.plan.include)
        counted = [d for d in lines if d.counted]
        full = mode == "full"
        found_yearly = sum(d.value_yearly or 0 for d in counted) if full else None
        found_display = sum(d.display_yearly or 0 for d in counted) if full else None
        share = models.floor_to(found_display, self.table.money.share_round_down_to) if found_display else None
        claimed = sum(d.display_yearly or 0 for d in counted if d.applied) if full else 0
        calfresh = next((d for d in lines if d.id == KEY_LINE), None)
        spreads: dict[str, int] = {}
        open_ids: list[str] = []
        if full:
            ctx = Context(facts=facts, answers=valid, rows=self._rows, today=today)
            asked = plan_questions(self.table.questions, self.table.ask_rule, valid,
                                   askable=lambda q: holds_quietly(q.ask_when, ctx),
                                   found_yearly=lambda a: self._found_yearly(facts, a, today))
            spreads, open_ids = asked.spreads, asked.open
        result = ProgramsResult(
            table_id=self.table.id, checked=self.table.checked, mode=mode,
            calfresh_yearly=calfresh.value_yearly if (full and calfresh) else None,
            found_yearly=found_yearly, found_display=found_display, share_display=share or None,
            claimed_display=claimed,
            lines=[self._line(d, i) for i, d in enumerate(lines, start=1)],
            open_questions=open_ids, next_question=open_ids[0] if open_ids else None,
            question_spreads=spreads,
            console_notes=self._console_notes(facts, valid, today, {d.id for d in lines}),
        )
        return Computed(result=result, facts=facts, answers=valid,
                        variants={d.id: d.variant for d in lines if d.variant}, answered=len(valid))

    def mode_of(self, route: str | None) -> ProgramMode | None:
        """full on the likely route, list_only on coordinator and info routes, None otherwise (mode none)."""
        if not route:
            return None
        modes = self.table.modes
        if any(fnmatch.fnmatchcase(route, p) for p in modes.full.routes):
            return "full"
        if any(fnmatch.fnmatchcase(route, p) for p in modes.list_only.routes):
            return "list_only"
        return None

    # ------------------------------------------------------------------------------------------ helpers

    def _compute_case(self, case: Case, today: date) -> Computed | None:
        with _exact():  # the facts add money too (earned + work-study + unearned)
            facts = facts_from_case(case, horizon_months=self.table.money.horizon_months,
                                    assumed_roommates=self.table.facts_defaults.roommates_count_when_unsaid)
            answers = {q: a.value for q, a in case.program_answers.items()}
            progress = {p: mark.applied for p, mark in case.program_progress.items()}
            return self._compute(facts, answers=answers, progress=progress, today=today)

    def _valid_answers(self, answers: Mapping[str, str]) -> dict[str, str]:
        """Stored answers the table still knows (an unknown question or choice reads as unanswered)."""
        return {q: c for q, c in answers.items() if q in self.table.questions and c in self.table.questions[q].choices}

    def _find_ride_question(self) -> str | None:
        for p in self.table.programs:
            if isinstance(p.value, TransitBreaks):
                lo = p.value.check_range["lo_choice"]
                for qid, q in self.table.questions.items():
                    if lo in q.choices:
                        return qid
        return None

    def _found_yearly(self, facts: ProgramFacts, answers: Mapping[str, str], today: date) -> int:
        drafts = self._drafts(facts, answers, {}, today, "full", explain=False)
        return sum(d.value_yearly or 0 for d in drafts if d.counted)

    def _drafts(self, facts: ProgramFacts, answers: Mapping[str, str], progress: Mapping[str, bool], today: date,
                mode: ProgramMode, *, explain: bool = True) -> list[Draft]:
        """One draft per shown line. `explain=False` skips the console trace text (the ask rule's what-ifs)."""
        drafts: list[Draft] = []
        if mode == "full":
            drafts.append(self._calfresh(facts, answers, progress, today))
        for program in self.table.programs:
            draft = self._program(program, facts, answers, progress, today, mode, explain)
            if draft is not None:
                drafts.append(draft)
        return drafts

    def _calfresh(self, facts: ProgramFacts, answers: Mapping[str, str], progress: Mapping[str, bool],
                  today: date) -> Draft:
        key = self.table.calfresh_key
        monthly = facts.calfresh_monthly or 0
        valued = models.calfresh_annual(key.months, monthly)
        display = models.floor_to(valued.value, self.table.money.display_round_down_to)
        ctx = Context(facts=facts, answers=answers, rows=self._rows, today=today)
        counted = holds_quietly(key.counted_when, ctx)
        return Draft(id=KEY_LINE, status="likely", stage=self.table.plan.stages[0], priority=0,
                     value_yearly=valued.value, display_yearly=display, counted=counted,
                     vars={"value": str(valued.value), "calfresh_month": str(monthly)},
                     basis=[*valued.basis, f"display {models.usd(display)}"], source_ids=[key.source],
                     applied=bool(progress.get(KEY_LINE, False)))

    def _program(self, p: Program, facts: ProgramFacts, answers: Mapping[str, str], progress: Mapping[str, bool],
                 today: date, mode: ProgramMode, explain: bool = True) -> Draft | None:
        ctx = Context(facts=facts, answers=answers, rows=self._rows, today=today)
        status: str = "check"
        notes: list[str] = []
        variant: str | None = None
        expired: str | None = None
        for rule in p.status_rules:
            try:
                matched = holds(rule.when, ctx)
            except RowNotValid as stop:
                expired = stop.row
                break
            if matched:
                status, notes, variant = rule.status, list(rule.notes), rule.variant
                break
        if status == "hidden":
            return None
        if mode == "full" and expired is None and status in ("likely", "maybe", "check"):
            expired = next((r for r in value_rows(p) if not valid_on(self._rows[r], today)), None)
        if expired is not None:
            status, notes, variant = "check", [], None
        note_keys = notes + [k for k, c in p.note_rules.items() if holds_quietly(c, ctx)] + list(p.notes_always)
        draft = Draft(id=p.id, status=status, stage=p.stage, priority=p.priority,  # type: ignore[arg-type]
                      note_keys=note_keys, source_ids=list(p.sources), applied=bool(progress.get(p.id, False)))
        if mode == "list_only":
            draft.status = self.table.modes.list_only.status_override
            draft.basis = ["list only: no amounts until a person checks"]
            return draft
        if expired is not None:
            draft.basis = [f"row {expired} is not valid on {today.isoformat()}: no dollars"]
        else:
            self._value(p, draft, facts, answers, ctx, variant, explain)
        draft.counted = draft.status == "likely"
        if draft.value_yearly is not None:
            draft.display_yearly = models.floor_to(draft.value_yearly, self.table.money.display_round_down_to)
        if p.apply_by is not None and draft.status in self.table.plan.include:
            breaks = self._rows[p.apply_by.row]
            if valid_on(breaks, today):
                draft.apply_by = models.before_next_break(breaks, today)  # type: ignore[arg-type]
        return draft

    def _value(self, p: Program, d: Draft, facts: ProgramFacts, answers: Mapping[str, str], ctx: Context,
               variant: str | None, explain: bool = True) -> None:
        """Fill the draft's value, range, vars, variant and basis by the program's value model and status."""
        if d.status == "note":
            d.basis = ["information line only"]
            return
        if d.status == "zero":
            d.value_yearly = 0
            d.basis = ["answered: worth $0 for this student"]
            return
        v = p.value
        months = self.table.money.horizon_months
        if isinstance(v, CoverageOnly):
            d.value_yearly = 0
            if explain:
                d.basis = [self._comparison_text(c) for c in ctx.trace] + [f"{d.status}: health coverage, $0 cash"]
        elif isinstance(v, TransitBreaks):
            fares, breaks = self._rows[v.fares_row], self._rows[v.breaks_row]
            choice = answers.get(self._ride_question or "")
            if d.status == "check":
                lo = models.transit_breaks(fares, breaks, v.check_range["lo_choice"], explain)  # type: ignore[arg-type]
                hi = models.transit_breaks(fares, breaks, v.check_range["hi_choice"], explain)  # type: ignore[arg-type]
                d.range_lo, d.range_hi = lo.value, hi.value
                d.vars = {"lo": str(lo.value), "hi": str(hi.value)}
                d.basis = lo.basis + hi.basis
            elif choice in breaks.rides_per_week:  # type: ignore[union-attr]
                valued = models.transit_breaks(fares, breaks, choice, explain)  # type: ignore[arg-type]
                d.value_yearly = valued.value
                d.vars = {"value": str(valued.value)}
                d.basis = valued.basis
        elif isinstance(v, FlatMonthly):
            valued = models.flat_monthly(self._rows[v.row], months, explain)  # type: ignore[arg-type]
            d.value_yearly = valued.value
            d.vars = {"value": str(valued.value)}
            d.basis = valued.basis
            extra = self._rows.get(v.extra_display_row or "")
            if isinstance(extra, FlatRow) and valid_on(extra, ctx.today):
                fed = models.flat_monthly(extra, months, explain)
                d.vars["fed"] = str(fed.value)
                d.basis += [f"shown only, never counted: {line}" for line in fed.basis]
        elif isinstance(v, UtilityShare):
            care = models.utility_share(self._rows[v.row], facts, explain)  # type: ignore[arg-type]
            d.value_yearly = care.value
            d.vars = {"value": str(care.value), "household": str(care.household), "bill": str(care.bill),
                      "n": str(facts.bill_split), "count": str(facts.people_in_home)}
            d.variant = "alone" if facts.bill_split == 1 else "shared"
            d.basis = care.basis
        elif isinstance(v, TaxCredits):
            tax = models.tax_credits(self._rows[v.caleitc_row], self._rows[v.federal_row],  # type: ignore[arg-type]
                                     self._rows[v.yctc_row], facts, variant or "no_child", months,  # type: ignore[arg-type]
                                     explain)
            d.value_yearly = tax.value
            d.vars = {"value": str(tax.value)}
            d.basis = tax.basis
            if tax.value == 0:
                d.status, d.variant = "maybe", "small"  # the table's downgrade: "a small amount"
            elif d.status == "maybe":
                d.variant = "any"
            elif variant == "parent":
                d.variant = "parent" if tax.yctc > 0 else "parent_federal_only"
            elif tax.caleitc > 0 and tax.federal > 0:
                d.variant = "both"
            else:
                d.variant = "state_only" if tax.caleitc > 0 else "federal_only"

    @staticmethod
    def _comparison_text(c: Any) -> str:
        sign = "≤" if c.held else ">"
        people = "person" if c.size == 1 else "people"
        return f"{c.fact} {models.usd(c.value)} a month {sign} {models.usd(c.limit)} ({c.row}, {c.size} {people})"

    def _console_notes(self, facts: ProgramFacts, answers: Mapping[str, str], today: date,
                       shown: set[str]) -> list[str]:
        ctx = Context(facts=facts, answers=answers, rows=self._rows, today=today)
        return [key for p in self.table.programs if p.id in shown
                for key, cond in p.console_note_rules.items() if holds_quietly(cond, ctx)]

    @staticmethod
    def _line(d: Draft, order: int) -> ProgramLine:
        return ProgramLine(id=d.id, status=d.status, value_yearly=d.value_yearly, display_yearly=d.display_yearly,
                           counted=d.counted, range_lo=d.range_lo, range_hi=d.range_hi, stage=d.stage, order=order,
                           apply_by=d.apply_by, vars=dict(d.vars), note_keys=list(d.note_keys), basis=list(d.basis),
                           source_ids=list(d.source_ids), applied=d.applied)

"""CardBuilder: the student card (CardView), its status and its calendar file from a Case and the card content.

docs/SPEC.md §6 is the truth: the fixed parts (header, status banner, hero, unlocked, blocks, footer), the one block
table (order, per-route visibility, tone, starting state), the content rules and the calendar file. The wording lives
in data/content/card.{en,es}.json; every number comes from the case (written by the rules engine) or the rules table
and is formatted here. The `unlocked` part comes from the injected ProgramsPort; this module never imports the
programs engine. No I/O after construction.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gatorplate.card.conditions import CardContext, truthy, when_true
from gatorplate.card.fmt import day_text, money, month_name
from gatorplate.card.guard import OutputGuard
from gatorplate.card.ics import build_calendar
from gatorplate.contracts.card_api import BLOCK_ORDER, CardBlock, CardRow, CardStatus, CardView
from gatorplate.contracts.case import Case, FirstMonth
from gatorplate.contracts.common import Lang, SlotSource, SlotState, Tier, YellowResolution
from gatorplate.contracts.errors import NotFound
from gatorplate.contracts.ports import ProgramsPort
from gatorplate.contracts.programs import UnlockedView
from gatorplate.contracts.rules_io import RulesTable, SourceRef
from gatorplate.contracts.slots import ROUTING_ONLY

log = logging.getLogger("gatorplate.card")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTENT_DIR = REPO_ROOT / "data" / "content"
DEFAULT_RULES_TABLE = REPO_ROOT / "data" / "rules" / "ca_fy2027.json"
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
PLACEHOLDER_DOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}(\.?)")

# Slots whose canonical value is a monthly (or one-time) amount the card may show ("$900").
MONEY_PLACEHOLDERS = ("earned_monthly", "gig_monthly", "unearned_monthly", "other_cash_monthly", "rent_share",
                      "rent_paid_by_others_to_landlord", "homeless_shelter_cost_monthly", "cash_on_hand")
# Counted income for the reporting line (work-study, financial aid and rent paid to a landlord are not income).
INCOME_SLOTS = ("earned_monthly", "unearned_monthly", "other_cash_monthly", "gig_monthly")
WEEKEND = (calendar.SATURDAY, calendar.SUNDAY)


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _size_row(rows: dict[str, int], size: int) -> int:
    """A household-size table value: rows 1-8 as stored, 18_plus where listed, else row 8 + each_over_8 per member
    over 8 (rules table household_size_lookup)."""
    flat = {int(k.removesuffix("_plus")): v for k, v in rows.items() if k.endswith("_plus")}
    if flat and size >= min(flat):
        return flat[min(flat)]
    if str(size) in rows:
        return rows[str(size)]
    top = max(int(k) for k in rows if k.isdigit())
    return rows[str(top)] + rows["each_over_8"] * (size - top)


def unlocked_strings(view: UnlockedView) -> list[str]:
    """Every student-facing string of the unlocked part (URLs and ids excluded)."""
    out = [view.title, view.total_text or "", view.share_text or "", view.footnote, *view.chips, *view.labels.values()]
    if view.question is not None:
        out.append(view.question.text)
        out += [c.label for c in view.question.choices]
    for p in view.programs:
        out += [p.name, p.status_label, p.value_text or "", p.line, *p.notes, p.stage_label, p.apply_by_text or "",
                p.apply_label, p.source_text]
        for row in p.prefill:
            out += [row.screen, row.question, row.answer]
    return [s for s in out if s]


def cardview_strings(view: CardView) -> list[str]:
    """Every student-facing string of a CardView, the unlocked part included. Not included: the URL fields (the
    calendar endpoint keeps its contract name), ids, dates and the coordinator status value, which the page never
    shows."""
    out = [view.headline, view.subhead, view.rules_label, view.code, *view.footer]
    for block in view.blocks:
        out += [block.title, *block.paragraphs, *block.bullets]
        for row in block.rows:
            out += [row.screen, row.question, row.answer]
    for src in view.sources:
        out += [src.title, src.date]
    if view.unlocked is not None:
        out += unlocked_strings(view.unlocked)
    return [s for s in out if s]


class CardBuilder:
    """CardBuilderPort. `programs` is the injected ProgramsPort (built with enabled=False when GP_PROGRAMS=0, whose
    view() answers None); a missing port or a failing view leaves the card without its unlocked part."""

    def __init__(self, content_dir: Path | None = None, programs: ProgramsPort | None = None, *,
                 guards_path: Path | None = None, tz: str = "America/Los_Angeles",
                 rules_table_path: Path | None = None, card_ttl_days: int = 7) -> None:
        self.content_dir = Path(content_dir) if content_dir is not None else DEFAULT_CONTENT_DIR
        self.programs = programs
        self.guards_path = Path(guards_path) if guards_path is not None else self.content_dir / "guards.json"
        self.tz = tz
        self._tz = ZoneInfo(tz)
        self.card_ttl_days = card_ttl_days
        self._content: dict[Lang, dict[str, Any]] = {lang: self._load(f"card.{lang.value}.json") for lang in Lang}
        self._contacts: dict[str, Any] = self._load("contacts.json")
        self._guard = OutputGuard(self.guards_path)
        table_path = Path(rules_table_path) if rules_table_path is not None else DEFAULT_RULES_TABLE
        self._table = RulesTable.model_validate(json.loads(table_path.read_text(encoding="utf-8")))
        self._cutoff = time.fromisoformat(self._table.filing_date_estimate.cutoff_local)
        for lang, content in self._content.items():
            ids = [b["id"] for b in content["blocks"]]
            if ids != BLOCK_ORDER:
                raise ValueError(f"card.{lang.value}.json blocks must be {BLOCK_ORDER}, got {ids}")

    def _load(self, name: str) -> dict[str, Any]:
        return json.loads((self.content_dir / name).read_text(encoding="utf-8"))

    # ------------------------------------------------------------------------------------------ CardBuilderPort

    def build(self, case: Case, *, lang: Lang, now: datetime, base_url: str) -> CardView:
        """The CardView in `lang`. `now` sets generated_at, the filing-date estimate and the programs' "today" (the
        America/Los_Angeles date). URLs are root-relative, so `base_url` is not needed for them."""
        lang = Lang(lang)
        content = self._content[lang]
        token = self._token(case)
        tier, reason = self._tier(case), case.reason_code
        estimate = self._estimate(case)
        first_month = self._first_month(case, now) if estimate is not None else None
        ctx = self._context(case, tier, estimate, first_month)
        values = self._values(case, lang, estimate, first_month, ctx)

        head_key = self._head_key(content, tier, reason, estimate, case.estimate_is_floor)
        headline = self._say(content["headline"][head_key], values)
        subhead = self._say(content["subhead"][head_key], values)
        if headline is None or subhead is None:  # never expected: the content and its values pass the guard
            head_key = "incomplete" if reason is None else "coordinator"
            headline = self._say(content["headline"][head_key], values) or ""
            subhead = self._say(content["subhead"][head_key], values) or ""
            estimate = first_month = None

        blocks, source_ids = self._blocks(content, ctx, values, tier, reason)
        footer = [s for s in (self._say(line, values) for line in content["footer"]) if s]
        sources = [SourceRef(id=s["id"], title=s["title"], date=s["date"], url=s.get("url"))
                   for s in content["sources"] if s["id"] in source_ids]
        rules_label = self._say(content["ui"].get("rules_label", ""), values) or self._table.label
        # The calendar endpoint serves every case with a filing day (docs/UI_SPEC.md A4.3): the day the coordinator
        # recorded, else the first-month estimate; ics() prefers the recorded day.
        has_calendar = case.first_month is not None or case.tracking.filed_on is not None
        return CardView(
            lang=lang, code=case.code, tier=tier, reason_code=reason, headline=headline, subhead=subhead,
            estimate_monthly=estimate, estimate_is_floor=bool(estimate is not None and case.estimate_is_floor),
            expedited=case.expedited_possible if estimate is not None else None, first_month=first_month,
            blocks=blocks, footer=footer, sources=sources, rules_label=rules_label, status=self.status(case),
            generated_at=now,
            expires_at=case.card.expires_at if case.card else now + timedelta(days=self.card_ttl_days),
            reminders_url=f"/api/card/{token}/reminders.ics?lang={lang.value}" if has_calendar else None,
            delete_url=f"/api/card/{token}",
            unlocked=self._unlocked(case, lang, now),
        )

    def status(self, case: Case) -> CardStatus:
        """What the card polls: the review state and the two values the page compares with the card it shows."""
        return CardStatus(status=case.status, reviewed=case.reviewed_at is not None, reviewed_at=case.reviewed_at,
                          tier=self._tier(case), estimate_monthly=self._estimate(case))

    def ics(self, case: Case, *, lang: Lang, now: datetime | None = None) -> str:
        """Three all-day events relative to the filing day (docs/SPEC.md §6.3): the day the coordinator recorded, else
        the card's filing-date estimate (refreshed for `now` when given), else the one written at the call."""
        lang = Lang(lang)
        base = case.tracking.filed_on
        if base is None and case.first_month is not None:
            fresh = self._first_month(case, now) if now is not None else case.first_month
            base = (fresh or case.first_month).filed_on
        if base is None:
            raise NotFound("This card has no filing day for calendar dates.")
        content = self._content[lang]
        values = self._contact_values(lang)
        events = []
        for event in content["ui"]["calendar"]:
            title = self._say(event["title"], values)
            if title:
                events.append((base + timedelta(days=int(event["day"])), title))
        return build_calendar(events, uid_seed=case.id, stamp=case.updated_at, lang=lang.value)

    # ------------------------------------------------------------------------------------------ the case

    @staticmethod
    def _token(case: Case) -> str:
        if case.card is None:
            raise NotFound("This case has no card.")
        return case.card.token

    @staticmethod
    def _tier(case: Case) -> Tier | None:
        if case.tier is not None:
            return case.tier
        prefix = (case.reason_code or "").split(".")[0]
        return Tier(prefix) if prefix in Tier.__members__ else None

    @staticmethod
    def _estimate(case: Case) -> int | None:
        """An amount only on the likely route: coordinator, other-help and info cards show none."""
        return case.estimate_monthly if case.reason_code == Tier.likely.value else None

    def filing_date(self, now: datetime) -> date:
        """The estimated filing day: a weekday before the cutoff (5 PM Pacific) counts that day, otherwise the next
        weekday; holidays are not modeled (rules table filing_date_estimate)."""
        local = now.astimezone(self._tz)
        day = local.date()
        if day.weekday() not in WEEKEND and local.time() < self._cutoff:
            return day
        day += timedelta(days=1)
        while day.weekday() in WEEKEND:
            day += timedelta(days=1)
        return day

    def _first_month(self, case: Case, now: datetime) -> FirstMonth | None:
        """The case's first-month estimate, refreshed when the student opens the card on a later filing day (the
        rules table's proration: (amount x days) // days_in_month, under the minimum issue -> 0)."""
        stored = case.first_month
        if stored is None or case.estimate_monthly is None:
            return stored
        filed = self.filing_date(now)
        if filed <= stored.filed_on:
            return stored
        start, end = self._table.effective
        if not start <= filed <= end:
            return None
        days_in_month = calendar.monthrange(filed.year, filed.month)[1]
        days = days_in_month - filed.day + 1
        amount = (case.estimate_monthly * days) // days_in_month
        if amount < self._table.proration_min_issue:
            amount = 0
        return FirstMonth(apply_date=now.astimezone(self._tz).date(), filed_on=filed, amount=amount,
                          days_counted=days, month_label=month_name(filed, Lang.en), estimate=True)

    def _slot_values(self, case: Case) -> dict[str, str]:
        values = {name.value: slot.value for name, slot in case.slots.items()
                  if slot.value is not None and name not in ROUTING_ONLY}
        if "half_time" not in values and values.get("level") == "undergrad":
            units = _decimal(values.get("units"))
            if units is not None:
                values["half_time"] = "true" if units >= self._table.half_time.undergrad_units_at_least else "false"
        if "half_time" not in values and values.get("grad_exemption") == "under_half_time":
            values["half_time"] = "false"
        return values

    def _household_size(self, slots: dict[str, str]) -> int:
        children = _decimal(slots.get("children_count"))
        return 1 + (1 if truthy(slots.get("spouse")) else 0) + (int(children) if children is not None else 0)

    def _gross(self, case: Case, slots: dict[str, str]) -> Decimal | None:
        """Gross monthly income at the estimate: the rules engine's own figure (its `income` trace step, computed
        for the same answers and defaults as the estimate), else the sum of the income slots."""
        step = next((s for s in case.rule_trace if s.step == "income" and s.value is not None), None)
        gross = _decimal(step.value) if step is not None else None
        if gross is not None:
            return gross
        amounts = [_decimal(slots.get(s)) for s in INCOME_SLOTS if slots.get(s) is not None]
        if amounts:
            return sum((a for a in amounts if a is not None), Decimal(0))
        return None

    def _context(self, case: Case, tier: Tier | None, estimate: int | None,
                 first_month: FirstMonth | None) -> CardContext:
        slots = self._slot_values(case)
        # The student gave it: a value that is neither a default nor assumed (a value on a slot still marked missing
        # counts as clear, as in the rules' facts).
        answered = frozenset(
            name.value for name, slot in case.slots.items()
            if slot.value is not None and slot.state in (SlotState.clear, SlotState.missing)
            and slot.source != SlotSource.default)
        flags = set(case.flags) | {y.code for y in case.yellow_lines if y.resolved != YellowResolution.edit}
        facts = {"case_code"} if case.code else set()
        if first_month is not None:
            facts.add("first_month")
        irt_applies = at_max = None
        if estimate is not None:
            size = self._household_size(slots)
            gross = self._gross(case, slots)
            if gross is not None:
                irt_applies = gross <= _size_row(self._table.irt_130, size)
            at_max = estimate == _size_row(self._table.max_allotment, size)
        return CardContext(tier=tier.value if tier else None, reason=case.reason_code,
                           expedited=case.expedited_possible, slots=slots, answered=answered,
                           flags=frozenset(flags), facts=frozenset(facts), irt_applies=irt_applies, at_max=at_max)

    # ------------------------------------------------------------------------------------------ text

    def _contact_values(self, lang: Lang) -> dict[str, str]:
        c = self._contacts
        code = lang.value
        return {
            "coordinator_phone": c["coordinator"]["display"], "coordinator_email": c["coordinator"]["email"],
            "coordinator_place": c["coordinator"]["place"][code],
            "coordinator_hours": c["coordinator"]["hours"]["text"][code],
            "county_phone": c["county"]["display"], "county_hours": c["county"]["hours"]["text"][code],
            "ebt_phone": c["ebt_lost"]["display"], "pantry_url": c["food"][0]["url"],
            "meals_url": c["emergency_meals"]["url"],
        }

    def _values(self, case: Case, lang: Lang, estimate: int | None, first_month: FirstMonth | None,
                ctx: CardContext) -> dict[str, str]:
        values = self._contact_values(lang)
        if case.code:
            values["case_code"] = case.code
        if estimate is not None:
            values["estimate"] = money(estimate)
            values["irt"] = money(_size_row(self._table.irt_130, self._household_size(ctx.slots)))
        if first_month is not None:
            values["first_month"] = money(first_month.amount)
            values["filed_on"] = day_text(first_month.filed_on, lang)
            values["month_label"] = month_name(first_month.filed_on, lang)
        for name in MONEY_PLACEHOLDERS:
            amount = _decimal(ctx.slots.get(name))
            if amount is not None:
                values[name] = money(amount)
        return values

    def _say(self, template: str, values: dict[str, str]) -> str | None:
        """The template with every placeholder filled, or None when a value is missing or the guard objects (the
        string is then left off the card; the log line names no content)."""
        missing = [p for p in PLACEHOLDER.findall(template) if p not in values]
        if missing:
            log.warning("card.unfilled_placeholder", extra={"placeholders": missing})
            return None
        # A value that ends a sentence with its own period ("5 p. m.") absorbs the template's period.
        text = PLACEHOLDER_DOT.sub(lambda m: values[m.group(1)] + ("" if values[m.group(1)].endswith(".")
                                                                   else m.group(2)), template)
        if not self._guard.clean(text):
            log.warning("card.guard_hit")
            return None
        return text

    @staticmethod
    def _head_key(content: dict[str, Any], tier: Tier | None, reason: str | None, estimate: int | None,
                  floor: bool) -> str:
        if reason is not None and reason.startswith("info.") and reason in content["headline"]:
            return reason  # the info routes have their own hero, whatever the tier
        if reason is None:
            return "incomplete"  # the call ended before a result
        if estimate is not None:
            return "likely_floor" if floor else "likely"
        if tier is Tier.other_help:
            return "other_help"
        return "coordinator"

    def _blocks(self, content: dict[str, Any], ctx: CardContext, values: dict[str, str], tier: Tier | None,
                reason: str | None) -> tuple[list[CardBlock], set[str]]:
        blocks: list[CardBlock] = []
        source_ids: set[str] = set()
        for spec in content["blocks"]:
            if not when_true(spec.get("when", {}), ctx):
                continue
            paragraphs = [s for s in (self._say(it["text"], values) for it in spec.get("items", [])
                                      if when_true(it.get("when", {}), ctx)) if s]
            rows = []
            for row in spec.get("rows", []):
                if not when_true(row.get("when", {}), ctx):
                    continue
                cells = [self._say(row[k], values) for k in ("screen", "question", "answer")]
                if all(cells):
                    rows.append(CardRow(screen=cells[0], question=cells[1], answer=cells[2]))
            if not paragraphs and not rows:
                continue
            intro = self._say(spec["intro"], values) if spec.get("intro") else None
            title = ((spec.get("title_by_reason") or {}).get(reason or "")
                     or (spec.get("title_by_tier") or {}).get(tier.value if tier else "")
                     or spec["title"])
            shown = self._say(title, values) or self._say(spec["title"], values)
            if not shown:  # never expected: a block is never shown under a title that failed the guard
                continue
            blocks.append(CardBlock(id=spec["id"], title=shown,
                                    paragraphs=([intro] if intro else []) + paragraphs, rows=rows,
                                    tone=spec["tone"], collapsed=bool(spec["collapsed"])))
            source_ids.update(spec.get("sources", []))
        return blocks, source_ids

    def _unlocked(self, case: Case, lang: Lang, now: datetime) -> UnlockedView | None:
        """The programs part from the injected port, for the America/Los_Angeles date of `now`. The card never
        depends on it: no port, mode none, a failure or a guard hit leave it null. The card also holds the port to
        docs/SPEC.md §6.2 and §6.6: full mode only on the likely route, list_only on the coordinator and info routes,
        nothing on other-help routes or without a result, and never the card token or the case code in its text."""
        reason = case.reason_code or ""
        if reason == Tier.likely.value:
            expected = "full"
        elif reason.startswith(("coordinator.", "info.")):
            expected = "list_only"
        else:
            return None
        if self.programs is None:
            return None
        today = now.astimezone(self._tz).date()
        try:
            view = self.programs.view(case, lang=lang, today=today)
        except NotImplementedError:
            return None
        except Exception as exc:  # the card must still load (docs/SPEC.md §6.2: the part is optional)
            log.warning("card.unlocked_failed", extra={"error": type(exc).__name__})
            return None
        if view is None:
            return None
        if view.mode != expected or view.lang != lang:
            log.warning("card.unlocked_mismatch")
            return None
        strings = unlocked_strings(view)
        private = [s for s in (case.card.token if case.card else "", case.code) if s]
        if any(p in s for s in strings for p in private) or "/c/" in (view.share_text or ""):
            log.warning("card.unlocked_private_text")
            return None
        if not self._guard.all_clean(strings):
            log.warning("card.unlocked_guard_hit")
            return None
        return view

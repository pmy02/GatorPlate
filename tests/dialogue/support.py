"""Test doubles for the dialogue tests: a small rules engine, a table-driven understanding, in-memory stores.

The brain talks to the rules, the understanding and the stores only through their ports, so these doubles stand in for
the real modules (built in parallel). FakeRules reads every number from data/rules/ca_fy2027.json and follows
docs/SPEC.md §5 closely enough for the golden dialogues (G1, G1-b, G3, G4, G5, G6-b, G10, G11): routes, gross test,
deductions, shelter, net, benefit, the one-to-two-person minimum, expedited, and the VoI question plan with natural
defaults. FakeUnderstanding replays the expected extractions of data/tests/utterances.jsonl and the golden scripts'
`fake_llm` blocks, redacts digits and adds keyword intents with the patterns of data/content/guards.json.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from gatorplate.contracts import console_text
from gatorplate.contracts.case import Case, EstimateRange, TimelinePoint, Tracking, YellowLine
from gatorplate.contracts.common import Lang, SlotSource, SlotState, Tier, YellowKind
from gatorplate.contracts.console_api import CaseEvent, LiveTurn, LiveView
from gatorplate.contracts.extraction import (
    ExtractionResult,
    ExtractOutcome,
    Intent,
    PendingQuestion,
    SlotObservation,
    Understanding,
)
from gatorplate.contracts.rules_io import (
    Evaluation,
    Facts,
    FlipCandidate,
    FlipOutcome,
    FlipPlan,
    IncomeItem,
    RulesMeta,
    SourceRef,
)
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import SLOT_SPECS, MoneyBasis, SlotName, decode_value
from gatorplate.contracts.summary import household_size, summary_line

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TABLE_PATH = DATA / "rules" / "ca_fy2027.json"
S = SlotName
D = Decimal


def _row(table: dict, size: int) -> Decimal:
    if str(size) in table:
        return D(str(table[str(size)]))
    top = max(int(k) for k in table if k.isdigit())
    return D(str(table[str(top)])) + D(str(table.get("each_over_8", 0))) * (size - top)


# ============================================================================================ rules

class FakeRules:
    """A compact CalFresh engine on the real table (test double for RulesPort)."""

    def __init__(self, table_path: Path = TABLE_PATH) -> None:
        self.t = json.loads(table_path.read_text(encoding="utf-8"))
        self.voi = self.t["voi"]
        self.apply_calls = 0

    # ------------------------------------------------------------------------------------------ port
    def meta(self) -> RulesMeta:
        return RulesMeta(table_id=self.t["id"], label=self.t["label"], effective_from=date.fromisoformat(
            self.t["effective"][0]), effective_to=date.fromisoformat(self.t["effective"][1]),
            sources=[SourceRef(**{k: v for k, v in s.items() if k in ("id", "title", "date", "grade", "url")})
                     for s in self.t["sources"]])

    def valid_on(self, day: date) -> bool:
        lo, hi = (date.fromisoformat(x) for x in self.t["effective"])
        return lo <= day <= hi

    def normalize_money(self, basis: MoneyBasis) -> Decimal:
        m = self.t["conversion"]["multipliers"]
        amount = basis.amount
        if basis.period == "hour":
            value = amount * (basis.hours_per_week or D(0)) * D(m["week"])
        elif basis.period == "year":
            value = amount / D(self.t["conversion"]["year_divisor"])
        elif basis.period in m:
            value = amount * D(m[basis.period])
        else:
            value = amount
        return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)

    def facts_from_case(self, case: Case, *, today: date) -> Facts:
        return self._facts(case, {})

    def evaluate(self, facts: Facts, *, today: date) -> Evaluation:
        return self._evaluate(facts, today)

    def flip_plan(self, case: Case, *, today: date, budget: int) -> FlipPlan:
        cands = self._candidates(case, today)
        # One flip per slot (as the rules module): a slot asked once as a flip is never planned again.
        asked = {slot for a in case.asked if a.kind == "flip" for slot in a.slots}
        askable = [c for c in cands if (c.tier_changes or c.spread_usd > int(self.voi["flip_threshold_usd"]))
                   and c.slot not in asked]
        prio = self.voi["priority"]
        askable.sort(key=lambda c: (not c.tier_changes, -c.spread_usd, prio.index(c.slot.value)))
        ask = askable[:budget] if budget > 0 else []
        not_asked = [c for c in cands if c not in ask]
        for c in not_asked:
            if c.decision == "ask":
                c.decision = "coordinator" if c.tier_changes else "assume_default"
        for c in ask:
            c.decision = "ask"
        lo_hi = self._range(case, today)
        outlook = self._outlook(case, today)
        return FlipPlan(ask=ask, not_asked=not_asked, expedited_outlook=outlook, estimate_range=lo_hi)

    def apply(self, case: Case, *, now: datetime, turn: int | None = None) -> Case:
        self.apply_calls += 1
        case = case.model_copy(deep=True)
        today = now.date()
        ev = self._evaluate(self._facts(case, {}), today)
        flips = sum(1 for a in case.asked if a.kind == "flip" and a.key != "flip.rent_paid_by_others_amount")
        case.tier, case.reason_code = ev.tier, ev.reason_code
        case.table_id = self.t["id"]
        case.estimate_monthly = ev.monthly if ev.tier == Tier.likely else None
        rng = self._range(case, today) if self._income_housing_known(case) else None
        case.estimate_range = rng
        case.estimate_is_floor = bool(rng and ev.monthly is not None and ev.monthly == rng.lo and rng.hi - rng.lo > 50
                                      and flips >= int(self.voi["max_questions"]))
        if known(case, S.cash_on_hand):
            case.expedited_possible = self._outlook(case, today)
        if ev.tier == Tier.coordinator and ev.reason_code.startswith("coordinator."):
            if ev.reason_code == "coordinator.unresolved":
                reason = console_text.unresolved("an open answer")
            else:
                reason = console_text.coordinator_reason(ev.reason_code,
                                                         parent_household_text=self.t["parent_household_console_text"])
            slot = S.lives_with_parent if ev.reason_code == "coordinator.parent_household" else None
            self._yellow(case, YellowKind.policy, ev.reason_code, reason, now, slot=slot)
        if "abawd_possible" in ev.policy_flags:
            self._yellow(case, YellowKind.policy, "abawd_possible", console_text.abawd_possible(8, 80), now)
        if flips >= int(self.voi["max_questions"]):
            for c in self._candidates(case, today):
                if c.spread_usd > int(self.voi["flip_threshold_usd"]) and not c.tier_changes:
                    hi = max(o.monthly for o in c.outcomes if o.monthly is not None)
                    self._yellow(case, YellowKind.assumed, f"assumed.{c.slot.value}",
                                 console_text.assumed(SLOT_SPECS[c.slot].label, c.default_value, hi=hi), now,
                                 slot=c.slot)
        case.summary = summary_line(case)
        if turn is not None:
            case.timeline.append(TimelinePoint(turn=turn, at=now, slots=[], lo=rng.lo if rng else None,
                                               hi=rng.hi if rng else None))
        return case

    def filing_date(self, now: datetime) -> date:
        return now.date()

    def compute_tracking(self, tracking: Tracking) -> Tracking:
        return tracking

    # ------------------------------------------------------------------------------------------ engine
    @staticmethod
    def _yellow(case: Case, kind: YellowKind, code: str, reason: str, now: datetime, slot: SlotName | None = None):
        if any(y.code == code for y in case.yellow_lines):
            return
        case.yellow_lines.append(YellowLine(id=f"y{len(case.yellow_lines) + 1}", slot=slot, kind=kind, code=code,
                                            reason=reason, created_at=now))

    def _facts(self, case: Case, over: dict[SlotName, str]) -> Facts:
        def val(slot: SlotName, default: Any = None) -> Any:
            if slot in over:
                raw = over[slot]
                return decode_value(slot, raw) if raw is not None else default
            item = case.slots.get(slot)
            if item is None or item.value is None:
                return default
            return decode_value(slot, item.value)

        def unclear(slot: SlotName) -> bool:
            item = case.slots.get(slot)
            return slot not in over and item is not None and item.state == SlotState.unclear

        age = val(S.age, 20)
        level = val(S.level, "undergrad")
        units = val(S.units)
        half_time = val(S.half_time)
        if half_time is None:
            half_time = True if units is None else units >= int(self.t["half_time"]["undergrad_units_at_least"])
        food = "shared" if unclear(S.household_food) else val(S.household_food, "alone")
        incomes = []
        for slot, kind, excluded in ((S.earned_monthly, "earned", False), (S.other_cash_monthly, "unearned", False),
                                     (S.unearned_monthly, "unearned", False), (S.gig_monthly, "self_employment", False),
                                     (S.work_study_monthly, "earned", True)):
            amount = val(slot)
            if amount:
                incomes.append(IncomeItem(amount=amount, freq="monthly", kind=kind, excluded=excluded))
        heat = val(S.heat_cool, False)
        other = val(S.other_utils, "none")
        utility = "heat_cool" if heat else {"two_plus": "two_other", "phone_only": "phone_only"}.get(other, "none")
        route = case.route_override
        rent = val(S.rent_share, D(0))
        paid = val(S.rent_paid_by_others_to_landlord, D(0))
        return Facts(
            lang=case.lang, volunteered_status=None, elderly_or_disabled=route == "coordinator.elderly_disabled",
            age=age, level=level, public_ca_degree_program=True, half_time=half_time, units=units,
            grad_exemption=val(S.grad_exemption), child_under14_in_hh=(val(S.youngest_child_age, 99) < 14),
            under22_with_parent=bool(age < int(self.t["parent_household_age_under"])
                                     and val(S.lives_with_parent, False)),
            dorm_on_campus=val(S.dorm_on_campus, False), meals_per_week=val(S.meals_per_week, 0),
            dorm_meals_over_10=val(S.dorm_meals_over_10), household_food=food, household_size=household_size(case),
            spouse_student=val(S.spouse_student, False), boarder=val(S.boarder, False), homeless=val(S.homeless, False),
            homeless_shelter_cost=val(S.homeless_shelter_cost_monthly, D(0)), incomes=incomes, rent_share=rent,
            rent_paid_by_others_to_landlord=paid, utility=utility, dependent_care=val(S.dependent_care_monthly, D(0)),
            cash_on_hand=val(S.cash_on_hand), apply_date=None, income_changing_soon=val(S.income_changing_soon, False),
            status_route={"other_help.status": "other_help", "coordinator.status_complex": "coordinator"}.get(
                route or ""))

    def _evaluate(self, f: Facts, today: date) -> Evaluation:
        t = self.t
        size = f.household_size
        flags: list[str] = []

        def route(tier: Tier, code: str) -> Evaluation:
            return Evaluation(tier=tier, reason_code=code, household_size=size, gross_monthly=D(0), trace=[],
                              table_id=t["id"], hard_stop=True, policy_flags=flags)

        if not self.valid_on(today):
            return route(Tier.coordinator, "coordinator.unresolved")
        if f.status_route == "other_help":
            return route(Tier.other_help, "other_help.status")
        if f.status_route == "coordinator":
            return route(Tier.coordinator, "coordinator.status_complex")
        if f.elderly_or_disabled:
            return route(Tier.coordinator, "coordinator.elderly_disabled")
        if f.level == "not_sfsu":
            return route(Tier.other_help, "other_help.not_sfsu")
        if f.under22_with_parent:
            return route(Tier.coordinator, "coordinator.parent_household")
        if f.age < t["age_coordinator"]["under"] or f.age >= t["age_coordinator"]["at_or_over"]:
            return route(Tier.coordinator, "coordinator.age_outside_student_rule")
        if f.level == "not_degree":
            return route(Tier.coordinator, "coordinator.not_degree")
        if f.level == "grad" and f.half_time and f.grad_exemption in (None, "none"):
            return route(Tier.coordinator, "coordinator.grad_no_exemption")
        earned = sum((i.amount for i in f.incomes if i.kind == "earned" and not i.excluded), D(0))
        ab = t["abawd"]
        if not f.half_time and ab["age"][0] <= f.age <= ab["age"][1] and not f.child_under14_in_hh \
                and earned < D(ab["earnings_exempt_monthly"]) and not f.works_80h_month:
            flags.append("abawd_possible")
        if f.household_food == "shared":
            return route(Tier.coordinator, "coordinator.shared_household")
        if f.boarder:
            return route(Tier.coordinator, "coordinator.boarder")
        if f.spouse_student:
            return route(Tier.coordinator, "coordinator.spouse_student")
        if f.dorm_on_campus and (f.meals_per_week > t["dorm_meals_per_week_max_eligible"] or f.dorm_meals_over_10):
            return route(Tier.other_help, "other_help.dorm_meal_plan")
        if any(i.kind == "self_employment" and i.amount > 0 for i in f.incomes):
            return route(Tier.coordinator, "coordinator.gig_income")
        gross = sum((i.amount for i in f.incomes if not i.excluded), D(0))
        if gross > _row(t["gross_limit_200"], size):
            return route(Tier.other_help, "other_help.over_gross_limit")
        rates = t["rates"]
        std = _row({k.replace("_plus", ""): v for k, v in t["standard_deduction"].items()}, size)
        adjusted = max(gross - D(rates["earned_income_deduction"]) * earned - std - f.dependent_care, D(0))
        ua = D(t["utility_allowance"][f.utility])
        own = max(f.rent_share - f.rent_paid_by_others_to_landlord, D(0))
        if f.homeless:
            own = f.homeless_shelter_cost
            net = adjusted - (D(t["homeless_shelter_deduction"]) if own > 0 else D(0))
            shelter_cost = own
        else:
            excess = own + ua - D(rates["shelter_income_share"]) * adjusted
            excess = min(max(excess, D(0)), D(t["excess_shelter_cap_non_elderly_disabled"]))
            net = adjusted - excess
            shelter_cost = own + ua
        net_int = int(max(net, D(0)).quantize(D(1), rounding=ROUND_HALF_UP))
        benefit = int(_row(t["max_allotment"], size)) - int(
            (D(rates["benefit_reduction"]) * net_int).quantize(D(1), rounding=ROUND_CEILING))
        minimum = False
        if size <= 2 and benefit < int(t["min_benefit_1_2_persons"]):
            benefit, minimum = int(t["min_benefit_1_2_persons"]), True
        if size >= 3 and benefit <= 0:
            return route(Tier.other_help, "other_help.zero_benefit")
        exp = t["expedited"]
        screen = gross < exp["income_lt"] or shelter_cost > gross
        expedited = None
        if f.cash_on_hand is not None:
            expedited = (gross < exp["income_lt"] and f.cash_on_hand <= exp["liquid_le"]) or \
                (gross + f.cash_on_hand < shelter_cost)
        return Evaluation(tier=Tier.likely, reason_code="likely", monthly=benefit, min_benefit_applied=minimum,
                          household_size=size, gross_monthly=gross, net_monthly=net_int, expedited=expedited,
                          expedited_screen=screen, policy_flags=flags, trace=[], table_id=t["id"])

    # ------------------------------------------------------------------------------------------ VoI
    def _open_slots(self, case: Case) -> list[SlotName]:
        out = []
        homeless = value(case, S.homeless) is True
        for name, spec in self.voi["slots"].items():
            slot = SlotName(name)
            if name in ("other_cash_monthly", "earned_monthly"):
                continue
            if name == "household_food":
                item = case.slots.get(slot)
                if item is not None and item.state == SlotState.unclear:
                    out.append(slot)
                continue
            if known(case, slot):
                continue
            only = spec.get("only_if") or {}
            if only.get("homeless") is False and homeless:
                continue
            if only.get("heat_cool") is False and value(case, S.heat_cool) is True:
                continue
            out.append(slot)
        return out

    def _cand_values(self, case: Case, slot: SlotName) -> list[str]:
        values = []
        for raw in self.voi["slots"][slot.value]["candidates"]:
            if raw == "rent_share":
                rent = value(case, S.rent_share)
                raw = f"{rent:.2f}" if rent is not None else "0.00"
            values.append(raw)
        return values

    def _default(self, case: Case, slot: SlotName) -> str:
        spec = self.voi["slots"][slot.value]
        if spec["default"] == "conservative":
            return self._cand_values(case, slot)[-1]
        return spec["default"]

    def _candidates(self, case: Case, today: date) -> list[FlipCandidate]:
        open_slots = self._open_slots(case)
        defaults = {s: self._default(case, s) for s in open_slots}
        out = []
        for slot in open_slots:
            outcomes = []
            for v in self._cand_values(case, slot):
                over = dict(defaults)
                over[slot] = v
                ev = self._evaluate(self._facts(case, over), today)
                label = ("Yes" if v not in ("0.00", "false", "none", "separate") else "No") + \
                    (f" → ${ev.monthly}/mo" if ev.tier == Tier.likely else f" → {ev.tier.value}")
                outcomes.append(FlipOutcome(value=v, tier=ev.tier, monthly=ev.monthly if ev.tier == Tier.likely
                                            else None, label=label))
            tiers = {o.tier for o in outcomes}
            amounts = [o.monthly for o in outcomes if o.monthly is not None]
            spread = (max(amounts) - min(amounts)) if amounts else 0
            decision = "ask" if (len(tiers) > 1 or spread > int(self.voi["flip_threshold_usd"])) else \
                ("no_effect" if spread == 0 else "assume_default")
            lo, hi = (min(amounts), max(amounts)) if amounts else (0, 0)
            reason = console_text.flip_reason(spread, lo, hi) if len(tiers) == 1 else console_text.flip_reason_tier(
                "likely", "coordinator")
            out.append(FlipCandidate(slot=slot, default_value=defaults[slot], outcomes=outcomes,
                                     tier_changes=len(tiers) > 1, spread_usd=spread, decision=decision, reason=reason))
        return out

    def _worlds(self, case: Case) -> list[dict[SlotName, str]]:
        open_slots = self._open_slots(case)
        choices = [[(s, v) for v in self._cand_values(case, s)] for s in open_slots]
        return [dict(combo) for combo in itertools.product(*choices)] if choices else [{}]

    def _range(self, case: Case, today: date) -> EstimateRange | None:
        amounts, tiers = [], set()
        for over in self._worlds(case):
            ev = self._evaluate(self._facts(case, over), today)
            tiers.add(ev.tier)
            if ev.monthly is not None:
                amounts.append(ev.monthly)
        if not amounts:
            return None
        lo, hi = min(amounts), max(amounts)
        return EstimateRange(lo=lo, hi=hi, settled=len(tiers) == 1 and hi - lo <= int(self.voi["flip_threshold_usd"]))

    def _outlook(self, case: Case, today: date) -> str | None:
        if not known(case, S.cash_on_hand):
            return None
        flags = []
        for over in self._worlds(case):
            ev = self._evaluate(self._facts(case, over), today)
            if ev.expedited is not None:
                flags.append(ev.expedited)
        if not flags:
            return None
        return "yes" if all(flags) else "maybe" if any(flags) else "no"

    @staticmethod
    def _income_housing_known(case: Case) -> bool:
        income = known(case, S.earned_monthly) and known(case, S.other_cash_monthly)
        housing = known(case, S.rent_share) or (value(case, S.homeless) is True
                                                and known(case, S.homeless_shelter_cost_monthly))
        return income and housing


def known(case: Case, slot: SlotName) -> bool:
    item = case.slots.get(slot)
    return item is not None and item.state != SlotState.missing and item.value is not None


def value(case: Case, slot: SlotName) -> Any:
    item = case.slots.get(slot)
    if item is None or item.value is None:
        return None
    return decode_value(slot, item.value)


# ============================================================================================ understanding

_BARE_YES_NO = re.compile(r"^(yes|yeah|yep|correct|right|s[ií]|no|nope|nah)\W*$", re.IGNORECASE)
_TEEN_TY = re.compile(r"\b(thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|thirty|forty|fifty|sixty|"
                      r"seventy|eighty|ninety|trece|catorce|quince|diecis[eé]is|diecisiete|dieciocho|diecinueve|"
                      r"treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)\b", re.IGNORECASE)


def load_extractions() -> dict[str, dict]:
    """utterance text -> expected extraction (utterances.jsonl, then the golden scripts' fake_llm blocks)."""
    table: dict[str, dict] = {}
    for line in (DATA / "tests" / "utterances.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            table.setdefault(item["utterance"], item["expect"])
    for path in sorted((ROOT / "tests" / "e2e" / "scripts").glob("*.json")):
        script = json.loads(path.read_text(encoding="utf-8"))
        for turn in script.get("turns", []):
            if "user" in turn and "fake_llm" in turn:
                table[turn["user"]] = dict(turn["fake_llm"], redactions=table.get(turn["user"], {}).get(
                    "redactions", []))
    return table


class FakeUnderstanding:
    """Deterministic UnderstandingPort: exact-utterance table + guards.json redaction and keyword intents."""

    def __init__(self, *, extra: dict[str, dict] | None = None, delay_s: float = 0.0, status: str = "ok") -> None:
        guards = json.loads((DATA / "content" / "guards.json").read_text(encoding="utf-8"))
        self.table = load_extractions()
        self.table.update(extra or {})
        red = guards["input"]["redact"]
        self.card = [re.compile(p, re.I) for p in red["card_patterns"]]
        self.ssn = [re.compile(p, re.I) for p in red["ssn_patterns"]]
        self.spoken = {lang: [re.compile(p, re.I) for p in pats] for lang, pats in red["spoken_digit_patterns"].items()}
        self.card_words = [re.compile(p, re.I) for pats in red["masked_card_words"].values() for p in pats]
        self.replacement = red["replacement"]
        self.keywords = {(intent, lang): [re.compile(p, re.I) for p in pats]
                         for intent, langs in guards["input"]["keywords"].items() for lang, pats in langs.items()}
        self.delay_s = delay_s
        self.status = status
        self.calls: list[dict] = []

    def _redact(self, text: str, lang: str, masked: bool) -> tuple[str, list[str]]:
        kinds: list[str] = []
        out = text
        for rx in self.card:
            if rx.search(out):
                kinds.append("card_number")
                out = rx.sub(self.replacement, out)
        for rx in self.ssn:
            if rx.search(out):
                kinds.append("ssn")
                out = rx.sub(self.replacement, out)
        for code in {lang, "en"}:
            for rx in self.spoken.get(code, []):
                m = rx.search(out)
                if m:
                    n = len(re.findall(r"[^\W\d_]+|\d", m.group(0)))
                    kinds.append("card_number" if 13 <= n <= 19 else "ssn")
                    out = rx.sub(self.replacement, out)
        if masked and not kinds:
            kinds.append("card_number" if any(rx.search(text) for rx in self.card_words) else "ssn")
        return out, sorted(set(kinds))

    async def understand(self, *, text: str, masked: bool, confidence: float | None, dtmf: str | None,
                         pending: PendingQuestion | None, known: dict[SlotName, str], recent: list[str],
                         last_prompt: str | None, lang: Lang, deadline: float, closed_mode: bool) -> Understanding:
        self.calls.append({"text": text, "pending": pending.key if pending else None, "recent": list(recent),
                           "closed_mode": closed_mode, "known": dict(known), "deadline": deadline})
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        redacted, kinds = self._redact(text, lang.value, masked)
        low = redacted.lower()
        keyword = sorted({Intent(i) for (i, kl), rxs in self.keywords.items()
                          if kl == lang.value and any(rx.search(low) for rx in rxs)}, key=lambda x: x.value)
        entry = self.table.get(text)
        status = self.status
        if entry is None or status != "ok":
            result = ExtractionResult(observations=[], intents=[], answered_pending="no",
                                      lang=lang.value, side_question=None, requested_language=None)
        else:
            result = ExtractionResult.model_validate({k: v for k, v in entry.items()
                                                      if k not in ("redactions", "normalized")})
        observations = [] if kinds else list(result.observations)
        polar = _BARE_YES_NO.match(redacted.strip())
        if pending is not None and pending.kind == "confirm" and pending.slots and polar and not kinds:
            # The understanding's convention on a confirm question: a bare yes is "true", a bare no "false"
            # (gatorplate/extract/parser.py), on the confirmed slot.
            value = "false" if polar.group(1).lower() in ("no", "nope", "nah") else "true"
            observations = [SlotObservation(slot=pending.slots[0], value=value, period=None, hours_per_week=None,
                                            state="clear", quote=redacted.strip()[:80], quote_en=None)]
        teen = [o.slot for o in observations if _TEEN_TY.search(o.quote or "")]
        return Understanding(
            redacted_text=redacted, observations=observations, intents=list(result.intents), lang=lang,
            answered_pending=result.answered_pending, side_question=result.side_question,
            requested_language=result.requested_language,
            llm=ExtractOutcome(status=status if entry is not None or status != "ok" else "ok", result=result),
            sources={o.slot: SlotSource.llm for o in observations}, redactions=kinds, keyword_intents=keyword,
            teen_ty=teen)


# ============================================================================================ stores

class MemCases:
    def __init__(self) -> None:
        self.rows: dict[str, Case] = {}
        self.deleted: list[str] = []

    def create(self, case: Case) -> Case:
        stored = case.model_copy(deep=True)
        stored.version = 1
        self.rows[case.id] = stored
        return stored.model_copy(deep=True)

    def get(self, case_id: str) -> Case | None:
        row = self.rows.get(case_id)
        return row.model_copy(deep=True) if row else None

    def get_by_card_token(self, token: str) -> Case | None:
        return next((c.model_copy(deep=True) for c in self.rows.values() if c.card and c.card.token == token), None)

    def get_by_short_code(self, code: str, *, now: datetime) -> Case | None:
        return next((c.model_copy(deep=True) for c in self.rows.values() if c.card and c.card.short_code == code), None)

    def list(self, *, status=None, since_seq=None, limit: int = 200) -> list[Case]:
        return [c.model_copy(deep=True) for c in self.rows.values()][:limit]

    def save(self, case: Case, *, expected_version: int | None = None) -> Case:
        stored = case.model_copy(deep=True)
        stored.version = (self.rows[case.id].version if case.id in self.rows else 0) + 1
        Case.model_validate(stored.model_dump())  # the store validates every save
        self.rows[case.id] = stored
        return stored.model_copy(deep=True)

    def delete(self, case_id: str) -> bool:
        self.deleted.append(case_id)
        return self.rows.pop(case_id, None) is not None

    def delete_all(self, *, keep_seeded: bool) -> int:
        n = len(self.rows)
        self.rows.clear()
        return n


class MemSessions:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def get(self, call_id: str) -> SessionState | None:
        raw = self.rows.get(call_id)
        return SessionState.model_validate_json(raw) if raw else None

    def put(self, state: SessionState) -> None:
        self.rows[state.call_id] = state.model_dump_json()

    def delete(self, call_id: str) -> None:
        self.rows.pop(call_id, None)


class MemLive:
    def __init__(self) -> None:
        self.lines: dict[str, list[LiveTurn]] = {}
        self.asking: dict[str, tuple] = {}
        self.wiped: list[str] = []

    def append(self, line: LiveTurn) -> None:
        self.lines.setdefault(line.case_id, []).append(line)

    def set_now_asking(self, case_id: str, *, key, text, reason) -> None:
        self.asking[case_id] = (key, text, reason)

    def get(self, case_id: str) -> LiveView | None:
        if case_id not in self.lines:
            return None
        key, text, reason = self.asking.get(case_id, (None, None, None))
        return LiveView(case_id=case_id, lines=self.lines[case_id], now_asking=key, now_asking_text=text,
                        asked_reason=reason)

    def wipe(self, case_id: str) -> None:
        self.wiped.append(case_id)
        self.lines.pop(case_id, None)
        self.asking.pop(case_id, None)


class MemEvents:
    def __init__(self) -> None:
        self.events: list[CaseEvent] = []

    def publish(self, type: str, *, case: Case | None = None, case_id: str | None = None,
                changed_slots: Sequence[SlotName] = (), now_asking: str | None = None,
                now_asking_text: str | None = None, asked_reason: str | None = None, line: LiveTurn | None = None,
                changed_programs: bool = False) -> CaseEvent:
        event = CaseEvent(seq=len(self.events) + 1, type=type, case_id=case.id if case else case_id,
                          changed_slots=list(changed_slots), now_asking=now_asking, now_asking_text=now_asking_text,
                          asked_reason=asked_reason, line=line, changed_programs=changed_programs,
                          at=datetime.now(UTC))
        self.events.append(event)
        return event

    async def subscribe(self, *, last_seq: int | None) -> AsyncIterator[CaseEvent]:  # pragma: no cover - unused
        for e in self.events:
            yield e

    def current_seq(self) -> int:
        return len(self.events)


def deep(obj: Any) -> Any:
    return copy.deepcopy(obj)

"""Value of information: "only ask what can change the answer" (docs/SPEC.md §5.6).

Every setting comes from the table's `voi` section. A question-picker slot is measured while it is open: missing
with a natural default (nobody pays rent to the landlord, no heating or cooling bill, no other utility bills), or
answered unclearly or with a range (state unclear, or a value assumed from a band answer; then its default is the
conservative value, the candidate with the lowest likely amount). A slot
whose default is "conservative" is measured only after an unclear answer (the phase machine asks it otherwise). The
food question is a household question and is measured as soon as the answer is unclear; the money slots are measured
once income and housing are known.

To measure one slot, every other open slot is held at its default and the rules run once per candidate value. The
slot is askable when the tier changes or the spread of the likely amounts is strictly greater than the threshold;
askable slots are asked in the order tier change, spread, then the table's priority list, within the question budget.
Each slot is asked at most once. A slot that is still open afterwards, or is left over by the question limit, and can
change the tier is resolved by a person (coordinator.unresolved); any other leftover keeps its default.
The spoken estimate is the all-defaults world; the estimate range and the expedited outlook run over every
combination of the open slots' candidates.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import product

from gatorplate.contracts import console_text
from gatorplate.contracts.case import Case, EstimateRange
from gatorplate.contracts.common import ExpeditedOutlook, Phase, SlotState, Tier
from gatorplate.contracts.rules_io import Evaluation, Facts, FlipCandidate, FlipOutcome, FlipPlan, RulesTable, VoiSlot
from gatorplate.contracts.slots import ENUM_DISPLAY, SLOT_SPECS, SlotName, encode_value
from gatorplate.rules import engine
from gatorplate.rules.facts import answered, build_facts, state, value
from gatorplate.rules.money import DOLLAR, ZERO, usd
from gatorplate.rules.table import by_size, valid_on

N = SlotName
CONSERVATIVE = "conservative"
ANYTIME = frozenset({N.household_food})  # measured in the household phase, before income and housing are known
PAST_FLIP = frozenset({Phase.result, Phase.expedited, Phase.card, Phase.close, Phase.end})
TIER_WORDS = {Tier.likely: "likely", Tier.coordinator: "coordinator check", Tier.other_help: "other help"}
TOKEN_RENT_SHARE = "rent_share"
TOKEN_BAND_HI = "band_hi"
TOKEN_BAND = "band"
# An unclear answer, or a value assumed from a band answer (a range): the slot stays open at its conservative value.
UNSURE = frozenset({SlotState.unclear, SlotState.assumed})


@dataclass(frozen=True)
class Open:
    """One open question-picker slot."""

    name: SlotName
    spec: VoiSlot
    conservative: bool  # its default is the conservative value
    asked: bool  # already asked as a flip question (one flip per slot)
    unsure: bool  # answered unclearly or with a range (the dialogue keeps its own yellow line for it)
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class World:
    values: dict[SlotName, str]
    facts: Facts
    evaluation: Evaluation

    @property
    def likely(self) -> bool:
        return self.evaluation.tier == Tier.likely and self.evaluation.monthly is not None


@dataclass
class Measured:
    open: Open
    outcomes: list[tuple[str, World]]
    tier_changes: bool
    spread: int
    lo: int | None
    hi: int | None


@dataclass
class Analysis:
    """Everything the question picker found for a case on a day."""

    ready: bool
    valid_day: bool
    opens: list[Open]
    defaults: dict[SlotName, str]
    default_world: World
    measured: list[Measured] = field(default_factory=list)
    plan: FlipPlan | None = None
    settled: bool = False  # no question left to ask: leftovers are final
    why: dict[SlotName, str] = field(default_factory=dict)  # not-asked slot -> no_effect | below | cap | asked
    worlds: list[World] = field(default_factory=list)  # the remaining worlds (empty until income and housing)


# ---------------------------------------------------------------------------------------------- helpers


def is_ready(case: Case) -> bool:
    """Income and housing are known (or the conversation already moved on to the result)."""
    if "turn_cap" in case.flags or case.phase in PAST_FLIP - {Phase.end}:
        return True
    income = answered(case, N.earned_monthly) and answered(case, N.other_cash_monthly)
    if value(case, N.homeless) is True:
        housing = answered(case, N.homeless_shelter_cost_monthly)
    else:
        housing = answered(case, N.rent_share)
    return income and housing


def is_final(case: Case) -> bool:
    """No more flip questions: the call moved past the flip phase, reached the turn cap, or is over (not live)."""
    return (not case.live) or case.phase in PAST_FLIP or "turn_cap" in case.flags


def flips_asked(table: RulesTable, case: Case) -> set[SlotName]:
    names = {N(name) for name in table.voi.slots}
    return {slot for q in case.asked if q.kind == "flip" for slot in q.slots if slot in names}


def remaining_budget(table: RulesTable, case: Case) -> int:
    return max(0, table.voi.max_questions - len(flips_asked(table, case)))


def income_band_edges(table: RulesTable, size: int) -> list[int]:
    """Band edges = gross limit × the table's fractions, rounded to the nearest `round_to_usd` (half up)."""
    band = table.voi.income_band
    limit = Decimal(by_size(table.gross_limit_200, size))
    step = Decimal(band.round_to_usd)
    return [int((limit * f / step).quantize(DOLLAR, rounding=ROUND_HALF_UP) * step)
            for f in band.fractions_of_gross_limit]


def earned_band(table: RulesTable, case: Case) -> tuple[Decimal, Decimal]:
    """The band an unclear work-income answer stands for, from its (conservative) value: the band whose top it is,
    or the band that holds it (edges from `income_band_edges`; the last band ends at the gross limit). With no value
    at all, the whole range from $0 to the gross limit."""
    size = build_facts(table, case).household_size
    found = value(case, N.earned_monthly)
    limit = Decimal(by_size(table.gross_limit_200, size))
    if not isinstance(found, Decimal):
        return ZERO, limit
    amount = found
    bounds = [ZERO, *(Decimal(e) for e in income_band_edges(table, size)), limit]
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        if amount <= hi:
            return lo, hi
    return bounds[-1], amount


def _money(amount: Decimal) -> str:
    return encode_value(N.rent_share, amount)


def _candidates(table: RulesTable, case: Case, name: SlotName, spec: VoiSlot) -> tuple[str, ...]:
    raw = spec.candidates
    if raw == TOKEN_BAND:
        lo, hi = earned_band(table, case)
        out = [encode_value(name, lo), encode_value(name, hi)]
    else:
        out = []
        for cand in raw:
            if cand == TOKEN_RENT_SHARE:
                rent = value(case, N.rent_share)
                out.append(_money(rent if isinstance(rent, Decimal) else ZERO))
            elif cand == TOKEN_BAND_HI:
                found = value(case, name)
                band_top = Decimal(table.voi.other_cash_band_usd[-1])
                top = found if isinstance(found, Decimal) and found > ZERO else band_top
                out.append(encode_value(name, top))
            else:
                out.append(encode_value(name, cand))
    return tuple(dict.fromkeys(out))


def _only_if_holds(case: Case, spec: VoiSlot, world: dict[SlotName, str]) -> bool:
    for cond, wanted in (spec.only_if or {}).items():
        if (value(case, N(cond), world) is True) != wanted:
            return False
    return True


def open_slots(table: RulesTable, case: Case, *, ready: bool) -> list[Open]:
    """The open question-picker slots in priority order."""
    voi = table.voi
    asked = flips_asked(table, case)
    out: list[Open] = []
    for raw_name in voi.priority:
        name = N(raw_name)
        spec = voi.slots[raw_name]
        unclear = state(case, name) in UNSURE
        missing = value(case, name) is None and not unclear
        natural = spec.default != CONSERVATIVE
        if not (unclear or (missing and natural)):
            continue
        if name not in ANYTIME and not ready:
            continue
        static = {N(k) for k in (spec.only_if or {})} - {N(k) for k in voi.slots}
        if any((value(case, k) is True) != spec.only_if[k.value] for k in static):
            continue
        conservative = unclear or not natural or voi.default_mode == CONSERVATIVE
        out.append(Open(name=name, spec=spec, conservative=conservative, asked=name in asked, unsure=unclear,
                        candidates=_candidates(table, case, name, spec)))
    return out


def world(table: RulesTable, case: Case, values: dict[SlotName, str], today: date) -> World:
    facts = build_facts(table, case, values)
    return World(values=dict(values), facts=facts,
                 evaluation=engine.evaluate(table, facts, today=today, with_trace=False))


def _lowest_likely(table: RulesTable, case: Case, slot: Open, values: dict[SlotName, str], today: date) -> str:
    """The conservative value: the candidate with the lowest likely amount; the first candidate if none is likely."""
    best: tuple[int, str] | None = None
    for cand in slot.candidates:
        w = world(table, case, {**values, slot.name: cand}, today)
        if w.likely and (best is None or w.evaluation.monthly < best[0]):
            best = (w.evaluation.monthly, cand)
    return best[1] if best else slot.candidates[0]


def default_values(table: RulesTable, case: Case, opens: list[Open], today: date) -> dict[SlotName, str]:
    """Every open slot at its default, set in priority order (a conservative value sees the values set before)."""
    values: dict[SlotName, str] = {}
    for slot in opens:
        values[slot.name] = slot.candidates[0] if slot.conservative else encode_value(slot.name, slot.spec.default)
    for slot in opens:
        if slot.conservative:
            values[slot.name] = _lowest_likely(table, case, slot, values, today)
    return values


def _measure(table: RulesTable, case: Case, slot: Open, defaults: dict[SlotName, str], today: date) -> Measured:
    outcomes = [(cand, world(table, case, {**defaults, slot.name: cand}, today)) for cand in slot.candidates]
    tiers = {w.evaluation.tier for _, w in outcomes}
    amounts = [w.evaluation.monthly for _, w in outcomes if w.likely]
    lo, hi = (min(amounts), max(amounts)) if amounts else (None, None)
    spread = hi - lo if amounts else 0
    return Measured(open=slot, outcomes=outcomes, tier_changes=len(tiers) > 1, spread=spread, lo=lo, hi=hi)


# ---------------------------------------------------------------------------------------------- wording


def answer_label(name: SlotName, raw: str) -> str:
    """'No' / 'Yes' for the yes-no questions (rent paid by someone else: $0 is 'No'), the choice label, or '$300'."""
    spec = SLOT_SPECS[name]
    if spec.type == "bool":
        return "Yes" if raw == "true" else "No"
    if spec.type == "enum":
        return ENUM_DISPLAY.get(name, {}).get(raw, raw)
    if name == N.rent_paid_by_others_to_landlord:
        return "No" if Decimal(raw) == ZERO else "Yes"
    return usd(Decimal(raw))


def assumed_text(name: SlotName, raw: str) -> str:
    """The assumed value in console words: '$0', 'no', 'none', 'separately'."""
    spec = SLOT_SPECS[name]
    if spec.type == "money":
        return usd(Decimal(raw))
    return answer_label(name, raw).lower()


def outcome_label(name: SlotName, raw: str, w: World) -> str:
    """'No → $306/mo', or 'Together → coordinator check' when the outcome is not likely."""
    if w.likely:
        return f"{answer_label(name, raw)} → {console_text.money(w.evaluation.monthly)}/mo"
    return f"{answer_label(name, raw)} → {TIER_WORDS[w.evaluation.tier]}"


def _reason_ask(table: RulesTable, m: Measured) -> str:
    if m.tier_changes:
        tiers = list(dict.fromkeys(w.evaluation.tier for _, w in m.outcomes))
        return console_text.flip_reason_tier(TIER_WORDS[tiers[0]], TIER_WORDS[tiers[1]])
    return console_text.flip_reason(m.spread, m.lo or 0, m.hi or 0, template=table.voi.flip_reason_text)


def _candidate(table: RulesTable, m: Measured, decision: str, default: str, why: str) -> FlipCandidate:
    """`why` is how the slot ended up: ask, no_effect, below (spread up to the threshold), cap (askable, left over
    by the question limit) or asked (asked once already and still unclear)."""
    name = m.open.name
    if why in ("ask", "asked"):
        reason = _reason_ask(table, m)
    elif why == "no_effect":
        reason = console_text.skip_detail_no_effect(SLOT_SPECS[name].short)
    elif why == "cap":
        reason = console_text.skip_detail_max_questions()
    else:
        reason = console_text.skip_detail_below_threshold(assumed_text(name, default))
    outcomes = [FlipOutcome(value=raw, tier=w.evaluation.tier, monthly=w.evaluation.monthly if w.likely else None,
                            label=outcome_label(name, raw, w)) for raw, w in m.outcomes]
    return FlipCandidate(slot=name, default_value=default, outcomes=outcomes, tier_changes=m.tier_changes,
                         spread_usd=m.spread, decision=decision, reason=reason)


# ---------------------------------------------------------------------------------------------- analysis


def worlds(table: RulesTable, case: Case, a: Analysis, today: date) -> Iterable[World]:
    """Every combination of the open slots' candidates (the remaining worlds)."""
    if not a.opens:
        yield a.default_world
        return
    names = [o.name for o in a.opens]
    for combo in product(*(o.candidates for o in a.opens)):
        values = {**a.defaults, **dict(zip(names, combo, strict=True))}
        skip = False
        for o in a.opens:  # a slot whose condition fails in this world takes its default (no new world)
            if not _only_if_holds(case, o.spec, values) and values[o.name] != a.defaults[o.name]:
                skip = True
        if not skip:
            yield world(table, case, values, today)


def estimate_range(table: RulesTable, ws: list[World], default: World) -> EstimateRange | None:
    amounts = [w.evaluation.monthly for w in ws if w.likely]
    if not amounts:
        return None
    lo, hi = min(amounts), max(amounts)
    same_tier = all(w.evaluation.tier == default.evaluation.tier for w in ws)
    return EstimateRange(lo=lo, hi=hi, settled=same_tier and hi - lo <= table.voi.flip_threshold_usd)


def expedited_outlook(table: RulesTable, ws: list[World]) -> ExpeditedOutlook | None:
    results = [engine.expedited_test(table, gross=w.evaluation.gross_monthly, cash=w.facts.cash_on_hand,
                                     housing=engine.housing_cost(table, w.facts))
               for w in ws if w.likely and w.facts.cash_on_hand is not None]
    if not results:
        return None
    if all(results):
        return "yes"
    return "maybe" if any(results) else "no"


def expedited_screen(table: RulesTable, ws: list[World]) -> bool:
    """Ask the cash question: gross under the income limit, or own housing cost + utility allowance above gross, in
    any remaining likely world."""
    return any(w.evaluation.gross_monthly < table.expedited.income_lt
               or engine.housing_cost(table, w.facts) > w.evaluation.gross_monthly for w in ws if w.likely)


def analyze(table: RulesTable, case: Case, *, today: date, budget: int | None = None,
            final: bool | None = None) -> Analysis:
    """Measure the open slots and plan the flip questions. `budget` defaults to the table's limit minus the flip
    questions already asked; `final` (default: the call moved past the flip phase or is not live) treats every
    askable slot as left over by the question limit."""
    ready = is_ready(case)
    valid_day = valid_on(table, today)
    opens = open_slots(table, case, ready=ready) if valid_day else []
    defaults = default_values(table, case, opens, today)
    default = world(table, case, defaults, today)
    a = Analysis(ready=ready, valid_day=valid_day, opens=opens, defaults=defaults, default_world=default)
    if budget is None:
        budget = remaining_budget(table, case)
    if final is None:
        final = is_final(case)
    measured = [_measure(table, case, o, defaults, today) for o in opens if _only_if_holds(case, o.spec, defaults)]
    if not default.likely and not any(m.tier_changes for m in measured):
        measured = []  # a route the open slots cannot change: nothing to ask, nothing to report
    a.measured = measured
    threshold = table.voi.flip_threshold_usd
    priority = [N(p) for p in table.voi.priority]
    askable = [m for m in measured if (m.tier_changes or m.spread > threshold) and not m.open.asked]
    askable.sort(key=lambda m: (not m.tier_changes, -m.spread, priority.index(m.open.name)))
    take = 0 if final else max(0, budget)
    ask = askable[:take]
    a.settled = not ask
    ask_cands = [_candidate(table, m, "ask", defaults[m.open.name], "ask") for m in ask]
    not_asked: list[FlipCandidate] = []
    a.why = {}
    for m in measured:
        if m in ask:
            continue
        assume = "assume_conservative" if m.open.conservative else "assume_default"
        if m.open.asked:
            # asked once (one flip per slot) and still open: a slot that can change the tier stays a leftover that a
            # person resolves (coordinator.unresolved), never a guessed "likely"; otherwise the conservative value
            why, decision = "asked", ("coordinator" if m.tier_changes else assume)
        elif m in askable:
            why, decision = "cap", ("coordinator" if m.tier_changes else assume)
        elif m.spread == 0 and not m.tier_changes:
            why, decision = "no_effect", "no_effect"
        else:
            why, decision = "below", assume
        a.why[m.open.name] = why
        not_asked.append(_candidate(table, m, decision, defaults[m.open.name], why))
    a.worlds = list(worlds(table, case, a, today)) if ready and valid_day else []
    a.plan = FlipPlan(ask=ask_cands, not_asked=not_asked,
                      expedited_outlook=expedited_outlook(table, a.worlds) if a.worlds else None,
                      estimate_range=estimate_range(table, a.worlds, default) if a.worlds else None)
    return a


def split_point(table: RulesTable, case: Case, *, today: date) -> int | None:
    """The `flip.earned_split` amount X: where the estimate is halfway between the band ends' amounts, rounded to
    the table's step; the gross limit first when the band crosses it. None unless the work income is unclear."""
    if state(case, N.earned_monthly) not in UNSURE:
        return None
    lo, hi = earned_band(table, case)
    size = build_facts(table, case).household_size
    limit = Decimal(by_size(table.gross_limit_200, size))
    if hi > limit:
        return int(limit)
    a = analyze(table, case, today=today, final=True)
    base = {**a.defaults}

    def amount(x: Decimal) -> int:
        w = world(table, case, {**base, N.earned_monthly: encode_value(N.earned_monthly, x)}, today)
        return w.evaluation.monthly if w.likely else 0

    a_lo, a_hi = amount(lo), amount(hi)
    # the first whole dollar where the estimate is at or below the halfway amount (the estimate never rises with
    # income), found by bisection; then rounded half-up to the table's step and kept inside the band
    low, high = int(lo), int(hi)
    while low < high:
        middle = (low + high) >> 1
        if amount(Decimal(middle)) + amount(Decimal(middle)) > a_lo + a_hi:
            low = middle + 1
        else:
            high = middle
    step = Decimal(table.voi.income_band.round_to_usd)
    x = (Decimal(low) / step).quantize(DOLLAR, rounding=ROUND_HALF_UP) * step
    return int(min(max(x, lo), hi))

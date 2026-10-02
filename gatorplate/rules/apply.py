"""Writing the rules' results onto a case (RulesPort.apply).

apply() is pure: it returns an updated copy. It writes the tier, reason code, spoken estimate ("at least about" when
the range is wide), estimate range, the turn's timeline point, the rule trace, the first-month estimate (filing date
by the 5 PM Pacific weekday rule), the one-line summary, the question picker's not-asked entries, and the case-level
yellow lines it owns (coordinator review, work rule, income changing soon, TA/RA pay, rules table not valid, and
assumed values left over by the question limit). Yellow lines are idempotent by code: an open line is updated in
place, a resolved line is kept as it is, and an open line whose condition no longer holds is removed. Lines owned by
the dialogue (unclear, conflict, student question, incomplete) are never touched.

When a result exists: a route (a reason code that needs no amount) as soon as the rules reach it on the student's
own answer (a graduate student's route waits for the exemption question while the call can still ask it); an amount
only once income and housing are known (or the conversation moved on to the result). A call that ended before its
result keeps no result. The two info routes (already receiving, waiting for the interview) come from the
conversation and rank after the table dates, a volunteered status and the elderly-or-disabled route, as in
docs/SPEC.md §5.2 step 0.
"""

from __future__ import annotations

from datetime import datetime

from gatorplate.contracts import console_text
from gatorplate.contracts.case import Case, SkippedQuestion, TimelinePoint, YellowEffect, YellowLine
from gatorplate.contracts.common import YellowKind
from gatorplate.contracts.rules_io import FlipCandidate, RulesTable
from gatorplate.contracts.slots import SLOT_SPECS, SlotName
from gatorplate.contracts.summary import summary_line
from gatorplate.rules import dates, engine, voi
from gatorplate.rules.engine import LIKELY, tier_of
from gatorplate.rules.facts import answered, value

N = SlotName
ABAWD = "abawd_possible"
INCOME_CHANGING_SOON = "income_changing_soon"
TA_RA = "ta_ra_income_type"
RULES_NOT_VALID = "rules_not_valid"
UNRESOLVED = "coordinator.unresolved"
ASSUMED_PREFIX = "assumed."
OWNED_CODES = frozenset({ABAWD, INCOME_CHANGING_SOON, TA_RA, RULES_NOT_VALID})
VOI_SKIP_REASONS = frozenset({"no_effect", "below_threshold", "max_questions"})
WHY_TO_SKIP = {"no_effect": "no_effect", "below": "below_threshold", "cap": "max_questions"}
# The slot a coordinator-review line points at (status and disability details are never stored: no slot).
ROUTE_SLOT: dict[str, SlotName | None] = {
    "coordinator.parent_household": N.lives_with_parent,
    "coordinator.shared_household": N.household_food,
    "coordinator.grad_no_exemption": N.grad_exemption,
    "coordinator.not_degree": N.level,
    "coordinator.age_outside_student_rule": N.age,
    "coordinator.gig_income": N.gig_monthly,
    "coordinator.boarder": N.boarder,
    "coordinator.spouse_student": N.spouse_student,
    "coordinator.status_complex": None,
    "coordinator.elderly_disabled": None,
}
# Routes decided before the conversation's info routes (docs/SPEC.md §5.2 step 0).
BEFORE_INFO = frozenset({"other_help.status", "coordinator.status_complex", "coordinator.elderly_disabled"})
# Results that count the student's income (the TA/RA pay line applies to them).
INCOME_COUNTED = frozenset({LIKELY, "other_help.over_gross_limit", "other_help.zero_benefit", UNRESOLVED})


# A call that hit the brain's turn or time cap (docs/SPEC.md §3, flag `turn_cap`) reaches the result with the current
# defaults; an income the student never answered would count as $0 and overstate the estimate, so the result is
# coordinator.unresolved instead (docs/SPEC.md §5.6: an unknown income is never read as the highest amount). A missing
# rent only lowers the estimate, so it keeps its default.
CAP_FLAG = "turn_cap"
CAP_INCOME_SLOTS = (N.earned_monthly, N.other_cash_monthly)


def _unanswered_income(case: Case) -> SlotName | None:
    if CAP_FLAG not in case.flags:
        return None
    return next((name for name in CAP_INCOME_SLOTS if not answered(case, name)), None)


def _parent_unknown(table: RulesTable, case: Case) -> SlotName | None:
    """Under the parent-household age with the living situation never answered clearly (for example a closed-mode
    call, which asks only the age band): an amount could belong to the parents' household (docs/SPEC.md §3.2 phase 2,
    no exceptions), so the result waits for the coordinator."""
    age = value(case, N.age)
    if not isinstance(age, int) or age >= table.parent_household_age_under:
        return None
    return N.lives_with_parent if value(case, N.lives_with_parent) is None else None


def _owned(code: str) -> bool:
    return code in OWNED_CODES or code.startswith("coordinator.") or code.startswith(ASSUMED_PREFIX)


def _info_route(table: RulesTable, case: Case) -> str | None:
    if value(case, N.already_receiving) is True:
        return table.routes.already_receiving
    if value(case, N.applied_waiting_interview) is True:
        return table.routes.interview_waiting
    return None


def apply(table: RulesTable, case: Case, *, now: datetime, tz: str | None = None, turn: int | None = None) -> Case:
    out = case.model_copy(deep=True)
    today = dates.local(table, now, tz).date()
    a = voi.analyze(table, out, today=today)
    plan = a.plan
    assert plan is not None
    ev = engine.evaluate(table, a.default_world.facts, today=today, with_trace=True)

    reason: str | None = ev.reason_code
    valid_day = a.valid_day
    if valid_day and reason not in BEFORE_INFO:
        reason = _info_route(table, out) or reason
    is_amount = reason in (LIKELY, table.zero_benefit_3_plus_route)
    decided = (not is_amount) or a.ready
    if decided and not is_amount and _awaits_answer(out, reason):
        decided = False
    leftover_tier = None
    if decided and is_amount and a.settled:
        leftover_tier = next((c for c in plan.not_asked if c.decision == "coordinator"), None)
        if leftover_tier is not None:
            reason = UNRESOLVED
    still_open = _unanswered_income(out) if decided and is_amount and leftover_tier is None else None
    if still_open is None and decided and is_amount and leftover_tier is None:
        still_open = _parent_unknown(table, out)
    if still_open is not None:
        reason = UNRESOLVED
    if out.ended_early:
        decided = False

    # ---- result fields
    out.table_id = table.id
    out.rule_trace = list(ev.trace)
    out.estimate_range = plan.estimate_range if a.ready else None
    if decided and reason is not None:
        out.tier = tier_of(reason)
        out.reason_code = reason
    else:
        out.tier = None
        out.reason_code = None
    likely = decided and reason == LIKELY and ev.monthly is not None
    if likely:
        out.estimate_monthly = ev.monthly
        rng = out.estimate_range
        out.estimate_is_floor = bool(rng and ev.monthly == rng.lo and rng.hi - rng.lo > table.voi.flip_threshold_usd)
        out.expedited_possible = plan.expedited_outlook
        out.first_month = dates.first_month(table, ev.monthly, apply_date=today,
                                            filed_on=dates.filing_date(table, now, tz))
    else:
        out.estimate_monthly = None
        out.estimate_is_floor = False
        out.expedited_possible = None
        out.first_month = None
    out.summary = summary_line(out)

    # ---- question picker: not-asked entries (once nothing is left to ask)
    report = decided and a.ready and a.settled and reason in (LIKELY, UNRESOLVED)
    out.skipped = [s for s in out.skipped if not (s.reason in VOI_SKIP_REASONS and s.slot.value in table.voi.slots)]
    wanted: list[YellowLine] = []
    if report:
        unsure = {o.name for o in a.opens if o.unsure}
        for cand in plan.not_asked:
            why = a.why.get(cand.slot)
            if why not in WHY_TO_SKIP:
                continue
            values = [o.monthly for o in cand.outcomes if o.monthly is not None]
            out.skipped.append(SkippedQuestion(slot=cand.slot, reason=WHY_TO_SKIP[why], detail=cand.reason,
                                               values=values))
            # a natural default left by the question limit; an unclear or band answer has the dialogue's own line
            if why == "cap" and cand.decision != "coordinator" and cand.slot not in unsure:
                wanted.append(_assumed_line(table, cand, now))

    # ---- yellow lines owned by the rules
    if decided and reason is not None:
        if reason == UNRESOLVED and leftover_tier is not None:
            label = SLOT_SPECS[leftover_tier.slot].label
            wanted.append(_line(UNRESOLVED, YellowKind.policy, console_text.unresolved(label), now,
                                slot=leftover_tier.slot, effect=YellowEffect(kind="tier")))
        elif reason == UNRESOLVED and still_open is not None:
            label = SLOT_SPECS[still_open].label
            wanted.append(_line(UNRESOLVED, YellowKind.policy, console_text.unresolved(label), now,
                                slot=still_open, effect=YellowEffect(kind="tier")))
        elif reason == UNRESOLVED and not valid_day:
            wanted.append(_line(RULES_NOT_VALID, YellowKind.policy, console_text.RULES_NOT_VALID, now))
        elif reason.startswith("coordinator.") and reason != UNRESOLVED:
            text = console_text.coordinator_reason(reason, parent_household_text=table.parent_household_console_text)
            wanted.append(_line(reason, YellowKind.policy, text, now, slot=ROUTE_SLOT.get(reason)))
        if ABAWD in ev.policy_flags:
            text = console_text.abawd_possible(table.half_time.undergrad_units_at_least,
                                               table.abawd.work_requirement_hours_month,
                                               graduate=value(out, N.level) == "grad")
            wanted.append(_line(ABAWD, YellowKind.policy, text, now, slot=N.units))
        if INCOME_CHANGING_SOON in ev.policy_flags:
            wanted.append(_line(INCOME_CHANGING_SOON, YellowKind.policy, console_text.INCOME_CHANGING_SOON, now,
                                slot=N.income_changing_soon))
        if reason in INCOME_COUNTED and _ta_ra_pay(out):
            wanted.append(_line(TA_RA, YellowKind.policy, console_text.TA_RA_INCOME_TYPE, now, slot=N.earned_monthly))
    out.yellow_lines = _merge_lines(out.yellow_lines, wanted)

    # ---- timeline point for this turn
    if turn is not None:
        changed = sorted((name for name, slot in out.slots.items() if slot.turn == turn), key=list(N).index)
        existing = [p for p in out.timeline if p.turn != turn]
        if changed or len(existing) != len(out.timeline):
            rng = out.estimate_range
            point = TimelinePoint(turn=turn, at=now, slots=changed, lo=rng.lo if rng else None,
                                  hi=rng.hi if rng else None)
            out.timeline = sorted([*existing, point], key=lambda p: p.turn)
    return out


def _awaits_answer(case: Case, reason: str | None) -> bool:
    """A route that rests on a slot the student has not answered yet, while the call can still ask it (a graduate
    student before the exemption question: a missing exemption is not an answer of "none"). After the call, or at
    the turn cap, the route stands: the coordinator checks it."""
    slot = ROUTE_SLOT.get(reason or "")
    if slot is None or answered(case, slot):
        return False
    return case.live and not voi.is_final(case)


def _ta_ra_pay(case: Case) -> bool:
    earned = value(case, N.earned_monthly)
    is_grad = value(case, N.level) == "grad"
    ta_ra = value(case, N.ta_ra) is True or value(case, N.grad_exemption) == "ta_ra"
    return is_grad and ta_ra and earned is not None and earned > 0


def _assumed_line(table: RulesTable, cand: FlipCandidate, now: datetime) -> YellowLine:
    """'Other utility bills: assumed none (could be up to $159)', or '(could be as low as $X)' when the default
    gives the highest amount (texts from the table's voi.not_asked)."""
    rule = table.voi.not_asked.left_by_cap_spread_over_threshold
    amounts = [o.monthly for o in cand.outcomes if o.monthly is not None]
    default_amount = next((o.monthly for o in cand.outcomes if o.value == cand.default_value), None)
    shown = voi.assumed_text(cand.slot, cand.default_value)
    label = SLOT_SPECS[cand.slot].label
    if default_amount is not None and amounts and default_amount == max(amounts) and min(amounts) < default_amount:
        text = console_text.assumed(label, shown, lo=min(amounts),
                                    template_as_low_as=rule.yellow_text_when_default_is_highest or "")
    else:
        text = console_text.assumed(label, shown, hi=max(amounts) if amounts else 0,
                                    template_up_to=rule.yellow_text or "")
    return _line(ASSUMED_PREFIX + cand.slot.value, YellowKind.assumed, text, now, slot=cand.slot, assumed=shown,
                 effect=YellowEffect(kind="amount", delta_usd=cand.spread_usd))


def _line(code: str, kind: YellowKind, reason: str, now: datetime, *, slot: SlotName | None = None,
          assumed: str | None = None, effect: YellowEffect | None = None) -> YellowLine:
    return YellowLine(id="", slot=slot, kind=kind, code=code, reason=reason, assumed=assumed, effect=effect,
                      created_at=now)


def _merge_lines(current: list[YellowLine], wanted: list[YellowLine]) -> list[YellowLine]:
    """Idempotent by code: keep resolved lines, update open ones in place, add new ones with the next free id,
    drop open owned lines that are no longer wanted. Lines the rules do not own stay untouched."""
    by_code = {w.code: w for w in wanted}
    used = [int(y.id[1:]) for y in current if y.id[1:].isdigit()]
    next_id = max(used, default=0) + 1
    out: list[YellowLine] = []
    seen: set[str] = set()
    for line in current:
        if not _owned(line.code) or line.code in seen:
            out.append(line)
            continue
        want = by_code.get(line.code)
        if line.resolved is not None:
            out.append(line)
        elif want is not None:
            out.append(line.model_copy(update={"slot": want.slot, "kind": want.kind, "reason": want.reason,
                                               "assumed": want.assumed, "effect": want.effect}))
        seen.add(line.code)
    for want in wanted:
        if want.code in seen:
            continue
        out.append(want.model_copy(update={"id": f"y{next_id}"}))
        next_id += 1
        seen.add(want.code)
    return out

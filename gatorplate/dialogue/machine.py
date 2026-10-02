"""The phase machine as data (docs/SPEC.md §3.2, phases 0-10).

Each phase names the sentence keys it asks, its goal slots and the reason codes that end the conversation early (hard
stops). A hard stop is taken only once the phase's own goals are known, so an estimate computed from defaults for a
later phase never stops the call. Routes outside the table (a volunteered status, already receiving, waiting for an
interview) stop at any phase.
"""

from __future__ import annotations

from dataclasses import dataclass

from gatorplate.contracts.common import Phase
from gatorplate.contracts.slots import SlotName

S = SlotName

PHASE_ORDER: list[Phase] = [
    Phase.consent, Phase.student, Phase.age_home, Phase.household, Phase.income, Phase.housing, Phase.flip,
    Phase.result, Phase.expedited, Phase.card, Phase.close, Phase.end,
]
BEFORE_RESULT: frozenset[Phase] = frozenset(PHASE_ORDER[: PHASE_ORDER.index(Phase.result)])


@dataclass(frozen=True)
class PhaseSpec:
    phase: Phase
    goals: tuple[SlotName, ...]
    hard_stops: tuple[str, ...]


PHASES: dict[Phase, PhaseSpec] = {
    Phase.student: PhaseSpec(Phase.student, (S.level, S.units),
                             ("other_help.not_sfsu", "coordinator.not_degree", "coordinator.grad_no_exemption")),
    Phase.age_home: PhaseSpec(Phase.age_home, (S.age, S.lives_with_parent),
                              ("coordinator.parent_household", "coordinator.age_outside_student_rule",
                               "other_help.dorm_meal_plan")),
    Phase.household: PhaseSpec(Phase.household, (S.household_food,),
                               ("coordinator.shared_household", "coordinator.boarder", "coordinator.spouse_student")),
    Phase.income: PhaseSpec(Phase.income, (S.earned_monthly, S.other_cash_monthly),
                            ("coordinator.gig_income", "other_help.over_gross_limit")),
    Phase.housing: PhaseSpec(Phase.housing, (S.rent_share,), ()),
}
QUESTION_PHASES: list[Phase] = [Phase.student, Phase.age_home, Phase.household, Phase.income, Phase.housing]

# Routes that end the conversation at any phase (volunteered, never asked).
ANYTIME_ROUTES: tuple[str, ...] = ("other_help.status", "coordinator.status_complex", "coordinator.elderly_disabled",
                                   "info.already_receiving", "info.interview_waiting")
INFO_ROUTES: dict[SlotName, str] = {S.already_receiving: "info.already_receiving",
                                    S.applied_waiting_interview: "info.interview_waiting"}

# VoI flip questions (data/rules/ca_fy2027.json voi.slots ask_key) and the follow-up of a "yes" without an amount.
FLIP_KEYS: dict[SlotName, str] = {
    S.rent_paid_by_others_to_landlord: "flip.rent_paid_by_others",
    S.heat_cool: "flip.heat_cool",
    S.other_utils: "flip.other_utils",
    S.household_food: "flip.household_food",
    S.other_cash_monthly: "flip.other_cash_band",
    S.earned_monthly: "flip.earned_split",
}
FLIP_FOLLOW_UP: dict[str, str] = {"flip.rent_paid_by_others": "flip.rent_paid_by_others_amount"}

# Questions whose answer is a band (a range, not a value): AskedQuestion kind "band" unless the question is a flip.
BAND_KEYS: frozenset[str] = frozenset({"ask.income_band"})

# Keys that are case questions (recorded in Case.asked) as opposed to conversation questions (consent, crisis,
# delete, human request, close).
CASE_QUESTION_PREFIXES: tuple[str, ...] = ("ask.", "flip.", "expedited.intro_cash", "confirm.money")

# Explicit confirm policy (sentences.en.json confirm_policy holds the same lists): the four critical money slots.
READBACK_KEYS: dict[SlotName, str] = {
    S.earned_monthly: "readback.earned",
    S.other_cash_monthly: "readback.other_cash",
    S.rent_share: "readback.rent",
}

# Result chain keys.
CARD_KEYS = ("card.phone_screen", "card.phone_code", "card.web")


def phase_index(phase: Phase) -> int:
    return PHASE_ORDER.index(phase)


def result_key(reason_code: str | None) -> str:
    """The result sentence key of a non-likely route (result.<reason_code>)."""
    return f"result.{reason_code}"

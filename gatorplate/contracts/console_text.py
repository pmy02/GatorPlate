"""Console wording (English) for yellow lines, flip reasons and not-asked details: the one home of these strings.

Pure functions; numbers are passed in by the caller as whole dollars and formatted here with thousands separators.
Texts that also live in data/rules/ca_fy2027.json (the parent-household line, the VoI not-asked texts and the flip
reason) are passed in by the rules engine from the table; the constants below are equal to the table and are the
fallback. Where docs/UI_SPEC.md words a chip differently, the UI composes it from codes and numbers.
"""

from __future__ import annotations

PARENT_HOUSEHOLD_TEXT = ("Under 22 and living with a parent — the parent's household is counted together. "
                         "Confirm, then help with a household application.")

COORDINATOR_TEXTS: dict[str, str] = {
    "coordinator.parent_household": PARENT_HOUSEHOLD_TEXT,
    "coordinator.shared_household": ("Buys and cooks food with others — they may count as one household. "
                                     "Confirm who shares food, then help with a household application."),
    "coordinator.grad_no_exemption": ("Graduate student with no student-rule exemption named. "
                                      "Go through the exemption list with the student."),
    "coordinator.not_degree": ("Not in a degree program (credential, certificate or extension). "
                               "Check how the student rule applies."),
    "coordinator.age_outside_student_rule": ("Outside the student rule's age range — different rules apply. "
                                             "Check which rules apply with the student."),
    "coordinator.gig_income": ("Has self-employment or gig income — business costs change the count. "
                               "Check the income with the student."),
    "coordinator.boarder": "Pays for room and meals together — may be a boarder. Check the living arrangement.",
    "coordinator.spouse_student": "Spouse is also a student — both students' situations count. Check both.",
    "coordinator.status_complex": ("Immigration status mentioned (not stored) — eligibility depends on details the "
                                   "county checks. Offer the clinic or legal aid."),
    "coordinator.elderly_disabled": ("Mentioned disability benefits or age 60+ (details not stored) — different "
                                     "income tests apply. Check with the student."),
}

UNRESOLVED_TEMPLATE = "Still open and could change the result: {label}. Confirm it with the student."
ABAWD_TEMPLATE = ("Fewer than {units} units: the county may apply the 3-month work rule unless the student works "
                  "{hours} hours a month.")
# Graduate students: half-time depends on the program, not on a unit count (docs/SPEC.md §5.2 step 2).
ABAWD_GRAD_TEMPLATE = ("Less than half-time: the county may apply the 3-month work rule unless the student works "
                       "{hours} hours a month.")
INCOME_CHANGING_SOON = "Student said income will change soon. Check the expected amount."
TA_RA_INCOME_TYPE = "TA/RA pay counted as wages. Confirm it is paid work, not a fellowship or grant."
RULES_NOT_VALID = "Rules table not valid for this date — no estimate. Check the rules table."
UNCLEAR_TEMPLATE = "{label}: unclear answer — used the lower amount, {value}. Confirm with the student."
CONFLICT_TEMPLATE = "{label}: the words and the number disagree ({a} or {b}). Confirm with the student."
STUDENT_QUESTION_TEMPLATE = 'Student asked: "{paraphrase}"'
INCOMPLETE = "Call ended before the result."

# Table texts (data/rules/ca_fy2027.json voi): "$" is a literal dollar sign before the {placeholder}.
ASSUMED_UP_TO_TEMPLATE = "assumed {value} (could be up to ${max})"
ASSUMED_AS_LOW_AS_TEMPLATE = "assumed {value} (could be as low as ${min})"
FLIP_REASON_TEMPLATE = "could change the estimate by ${spread}: ${lo} or ${hi}"
FLIP_REASON_TIER_TEMPLATE = "could change the result: {tier_a} or {tier_b}"

SKIP_NO_EFFECT_TEMPLATE = "Not asked — {short}, same estimate either way"
SKIP_BELOW_THRESHOLD_TEMPLATE = "Not asked — assumed {assumed}; changes the estimate by $50 or less"
SKIP_MAX_QUESTIONS = "Not asked — question limit; see the yellow line"


def dollars(amount: int) -> str:
    """Whole dollars with thousands separators and no sign: 1100 -> "1,100"."""
    return f"{int(amount):,}"


def money(amount: int) -> str:
    """Whole dollars with a dollar sign: 1100 -> "$1,100"."""
    return f"${int(amount):,}"


def coordinator_reason(code: str, *, parent_household_text: str | None = None) -> str:
    """The yellow line of a coordinator-tier result. The parent-household text comes from the rules table."""
    if code == "coordinator.parent_household" and parent_household_text:
        return parent_household_text
    if code == "coordinator.unresolved":
        raise ValueError("use unresolved(label) for coordinator.unresolved")
    return COORDINATOR_TEXTS[code]


def unresolved(label: str) -> str:
    return UNRESOLVED_TEMPLATE.format(label=label)


def abawd_possible(units: int, hours: int, *, graduate: bool = False) -> str:
    if graduate:
        return ABAWD_GRAD_TEMPLATE.format(hours=hours)
    return ABAWD_TEMPLATE.format(units=units, hours=hours)


def assumed(label: str, value: str, *, hi: int | None = None, lo: int | None = None,
            template_up_to: str = ASSUMED_UP_TO_TEMPLATE, template_as_low_as: str = ASSUMED_AS_LOW_AS_TEMPLATE) -> str:
    """'{label}: assumed {value} (could be up to ${hi})', or '(could be as low as ${lo})' when only lo is given
    (the default is the highest value). Templates come from the table's voi.not_asked texts."""
    if hi is not None:
        tail = template_up_to.format(value=value, max=dollars(hi), min=dollars(lo) if lo is not None else "")
    elif lo is not None:
        tail = template_as_low_as.format(value=value, min=dollars(lo), max="")
    else:
        raise ValueError("assumed() needs hi or lo")
    return f"{label}: {tail}"


def unclear(label: str, value: str) -> str:
    return UNCLEAR_TEMPLATE.format(label=label, value=value)


def conflict(label: str, a: str, b: str) -> str:
    return CONFLICT_TEMPLATE.format(label=label, a=a, b=b)


def student_question(paraphrase: str) -> str:
    return STUDENT_QUESTION_TEMPLATE.format(paraphrase=paraphrase)


def flip_reason(spread: int, lo: int, hi: int, *, template: str = FLIP_REASON_TEMPLATE) -> str:
    """'could change the estimate by $151: $155 or $306' (template from the table's voi.flip_reason_text)."""
    return template.format(spread=dollars(spread), lo=dollars(lo), hi=dollars(hi))


def flip_reason_tier(tier_a: str, tier_b: str) -> str:
    return FLIP_REASON_TIER_TEMPLATE.format(tier_a=tier_a, tier_b=tier_b)


def skip_detail_no_effect(short: str) -> str:
    """'Not asked — heating or cooling bill, same estimate either way' (short = SlotSpec.short)."""
    return SKIP_NO_EFFECT_TEMPLATE.format(short=short)


def skip_detail_below_threshold(assumed_value: str) -> str:
    return SKIP_BELOW_THRESHOLD_TEMPLATE.format(assumed=assumed_value)


def skip_detail_max_questions() -> str:
    return SKIP_MAX_QUESTIONS


POLICY_TEXTS: dict[str, str] = {
    "income_changing_soon": INCOME_CHANGING_SOON,
    "ta_ra_income_type": TA_RA_INCOME_TYPE,
    "rules_not_valid": RULES_NOT_VALID,
    "incomplete": INCOMPLETE,
}

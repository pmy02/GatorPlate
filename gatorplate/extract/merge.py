"""Merge: the model's observations, checked against the student's words, combined with the rule parser's.

Grounding (code, not model):
- `quote` must be an exact substring of the redacted utterance (case and spacing are repaired); otherwise the
  observation keeps the first 80 characters as its quote and becomes unclear. A quote that holds a slot identifier
  ("rent_share") is an instruction read aloud, not a fact: dropped.
- A money value must be readable from its quote: one of the numbers said there, a no-answer or zero phrase ("No",
  "Nobody gives me cash") for 0, or an all-of-it phrase ("All of it", "Todo", "My parents pay my rent") equal to the
  known rent share. An invented number is dropped. Counts and ages must be said too.
- Values outside the plausible range of SLOT_SPECS (checked monthly for money) become unclear. Hours a week that are
  not a finite number between 0 and 168 are dropped (unclear), so no impossible value ever reaches the money math.
- `quote_en` is kept only when the utterance is Spanish. A volunteered immigration status and the SSI/SSDI flag only
  route: their quote is blanked, and an SSI/SSDI amount is dropped (on a line that names SSI/SSDI, a benefit or cash
  amount stays only when the rule parser, which skips SSI clauses, read the same amount).
Combination:
- several amounts of the same slot in one utterance (two jobs) are added (as a monthly sum when periods differ); the
  same amount reported twice from the same words counts once;
- model and parser agree (amounts within 1 % as monthly values) -> the model's observation; they disagree -> the
  model's value, state unclear (the dialogue may confirm a critical amount once);
- a parser-only observation is kept when it answers one of the pending question's slots that the model left out,
  whatever the question's kind, open included ("I'm 20, and I live with two roommates": the model often returns the
  age and the roommates but not lives_with_parent) — unless the model said the question was not answered, or already
  put the same spoken amount into another money slot; a slot the model reported (clear, unclear or with another
  value) is never replaced. It is also kept when it is routing-only, when it is the never-asked roommate count, when it
  is "lives alone" (household_food alone, which the model often leaves out of an answer about age) and the model said
  nothing that contradicts it, or when the model gave no result (timeout, error, closed mode, fast path);
- answered_pending: the model's, except that "partial" becomes "yes" once every slot the pending question asks is in
  hand (a slot the model left out may come from the parser); without a model result it is computed from the slots;
- intents = model intents + keyword intents (+ the parser's when the model gave no result).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from gatorplate.contracts.common import Lang, SlotSource
from gatorplate.contracts.extraction import ExtractOutcome, Intent, PendingQuestion, SlotObservation
from gatorplate.contracts.slots import ROUTING_ONLY, SLOT_SPECS, SlotName
from gatorplate.extract.conversion import Conversion, in_range
from gatorplate.extract.numbers import find_numbers
from gatorplate.extract.parser import _SLOT_NAME, MONEY, Parsed, _scale_low, all_of_it, fmt
from gatorplate.extract.text import fold_same, guess_lang

S = SlotName
QUOTE_MAX = 80
GLOSS_MAX = 120
SIDE_QUESTION_MAX = 120
AGREE = Decimal("0.01")  # parser and model within 1 %
HOURS_IN_WEEK = Decimal(168)  # an upper bound for hours_per_week, not a policy number
_ZERO_WORDS = re.compile(r"\b(?:no|not|nope|nah|nothing|none|nobody|no one|zero|never|don'?t|doesn'?t|isn'?t|"
                         r"without|broke|nada|nadie|ninguno|ninguna|cero|sin)\b", re.IGNORECASE)
_ONE_WORDS = re.compile(r"\b(?:a|an|un|una|uno|one)\b", re.IGNORECASE)
_SSI = re.compile(r"\b(?:ssi|ssdi)\b", re.IGNORECASE)
_SSI_SLOTS = frozenset({S.unearned_monthly, S.other_cash_monthly})  # where a model would put an SSI amount
# Slots the model may leave out of an answer although the student said them: kept from the parser unless the model
# contradicts them (see _backstop).
_LIVES_ALONE_CONTRADICTED_BY = {S.roommates: "true", S.lives_with_parent: "true", S.boarder: "true"}
_ORDER = [i for i in Intent]
_BOOL_WORDS = {"yes": "true", "no": "false", "si": "true", "sí": "true"}


@dataclass
class Merged:
    observations: list[SlotObservation]
    intents: list[Intent]
    lang: Lang | None
    answered_pending: str
    side_question: str | None = None
    requested_language: str | None = None
    sources: dict[SlotName, SlotSource] = field(default_factory=dict)
    teen_ty: list[SlotName] = field(default_factory=list)
    conflicts: list[SlotName] = field(default_factory=list)


def _dec(raw: str) -> Decimal | None:
    try:
        value = Decimal(str(raw).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _hours(raw: float) -> Decimal | None:
    """Hours a week from the model: finite, more than 0 and at most the hours in a week; else None."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0 or value > HOURS_IN_WEEK:
        return None
    return value


def _number(raw: str, spanish: bool) -> Decimal | None:
    """A model value as a number: "1100", "$1,100", "1100.00", or words such as "nine hundred"."""
    value = _dec(raw)
    if value is not None:
        return value
    found = find_numbers(raw, spanish=spanish)
    return found[0].value if len(found) == 1 else None


class Merger:
    def __init__(self, conversion: Conversion | None = None) -> None:
        self.conversion = conversion or Conversion.load()

    # ------------------------------------------------------------------------------------------ grounding
    def ground(self, ob: SlotObservation, utterance: str, *, spanish: bool, pending: PendingQuestion | None,
               known: dict[SlotName, str]) -> SlotObservation | None:
        slot = SlotName(ob.slot)
        spec = SLOT_SPECS[slot]
        state = ob.state
        quote = ob.quote or ""
        quote_ok = True
        if quote and quote not in utterance:
            found = _find_loose(quote, utterance)
            if found is None:
                quote, state, quote_ok = utterance[:QUOTE_MAX], "unclear", False
            else:
                quote = found
        if _SLOT_NAME.search(fold_same(quote)) or _SLOT_NAME.search(fold_same(ob.value or "")):
            return None
        evidence = quote if quote and quote_ok else utterance
        if len(quote) > QUOTE_MAX:
            quote = quote[:QUOTE_MAX]
        value = (ob.value or "").strip()
        period = ob.period
        hours = ob.hours_per_week
        if spec.type == "bool":
            value = _BOOL_WORDS.get(value.lower(), value.lower())
            if value not in ("true", "false"):
                return None
            period, hours = None, None
        elif spec.type == "enum":
            choices = {c.lower(): c for c in (spec.choices or [])}
            if value.lower() not in choices:
                return None
            value = choices[value.lower()]
            period, hours = None, None
        elif spec.type == "int":
            number = _number(value, spanish)
            if number is None or number != number.to_integral_value():
                return None
            value = str(int(number))
            if not self._said(number, evidence, spanish) and not (
                    number == 1 and _ONE_WORDS.search(evidence)) and not (
                    number == 0 and _ZERO_WORDS.search(evidence)):
                return None
            period, hours = None, None
        else:  # money
            asked_yes_no = pending is not None and slot in pending.slots and pending.kind in ("yes_no", "confirm")
            word = _BOOL_WORDS.get(value.lower(), value.lower())
            if word in ("true", "false"):
                if not asked_yes_no:
                    return None
                if word == "false" and pending is not None and pending.kind == "yes_no":
                    # a plain "no" to a yes/no money question is the amount 0 (the confirm question keeps "false")
                    value, period, hours = "0", ("month" if spec.periodic else None), None
                else:
                    value, period, hours = word, None, None
            else:
                number = _number(value, spanish)
                if number is None or number < 0:
                    return None
                # "All of it" equals the known rent share (rent paid by others) or the slot's own known value.
                all_of = known.get(S.rent_share) if slot == S.rent_paid_by_others_to_landlord else known.get(slot)
                ok = self._said(number, evidence, spanish) \
                    or (number == 0 and bool(_ZERO_WORDS.search(evidence))) \
                    or (all_of_it(fold_same(evidence)) is not None and all_of is not None
                        and _dec(all_of) == number)
                if not ok:
                    return None
                value = fmt(number)
                if not spec.periodic:
                    period, hours = None, None
                else:
                    period = period or "month"
                    if period != "hour":
                        hours = None
                    elif hours is not None:
                        said_hours = _hours(hours)
                        if said_hours is None:
                            hours, state = None, "unclear"  # not a number of hours a week: never passed on
                        elif not self._said(said_hours, utterance, spanish):
                            state = "unclear"
        if state == "clear" and in_range(slot, value, period, hours, self.conversion) is False:
            state = "unclear"
        quote_en = (ob.quote_en or None) if spanish else None
        if quote_en is not None:
            quote_en = quote_en[:GLOSS_MAX]
        if slot in ROUTING_ONLY:
            quote, quote_en = "", None
        return SlotObservation(slot=slot, value=value, period=period, hours_per_week=hours,
                               state=state, quote=quote, quote_en=quote_en)  # type: ignore[arg-type]

    @staticmethod
    def _said(number: Decimal, text: str, spanish: bool) -> bool:
        nums = find_numbers(text, spanish=spanish)
        values: set[Decimal] = set()
        for i, n in enumerate(nums):
            values.add(n.value)
            if n.alt is not None:
                values.add(n.alt)
            if i + 1 < len(nums):
                values.add(_scale_low(n.value, nums[i + 1]))
        if len(nums) > 1:
            values.add(sum((n.value for n in nums), Decimal(0)))
        return number in values

    # ------------------------------------------------------------------------------------------ combine
    def combine(self, observations: list[SlotObservation]) -> dict[SlotName, SlotObservation]:
        """One observation per slot: amounts of the same slot are added; otherwise the last value wins."""
        out: dict[SlotName, SlotObservation] = {}
        seen: set[tuple[str, str, str | None, float | None, str]] = set()
        for ob in observations:
            slot = SlotName(ob.slot)
            same = (slot.value, ob.value, ob.period, ob.hours_per_week, ob.quote)
            if same in seen:
                continue  # the same amount reported twice from the same words is one amount, not two jobs
            seen.add(same)
            prev = out.get(slot)
            if prev is None:
                out[slot] = ob
                continue
            if slot in MONEY and _dec(prev.value) is not None and _dec(ob.value) is not None:
                out[slot] = self._add(prev, ob) or ob
            else:
                state = "unclear" if (prev.value != ob.value or "unclear" in (prev.state, ob.state)) else "clear"
                out[slot] = ob.model_copy(update={"state": state})
        return out

    def _add(self, a: SlotObservation, b: SlotObservation) -> SlotObservation | None:
        spec = SLOT_SPECS[SlotName(a.slot)]
        state = "unclear" if "unclear" in (a.state, b.state) else "clear"
        quote = _span(a.quote, b.quote)
        if a.period == b.period and a.hours_per_week == b.hours_per_week and a.period != "hour":
            total = (_dec(a.value) or Decimal(0)) + (_dec(b.value) or Decimal(0))
            return a.model_copy(update={"value": fmt(total), "state": state, "quote": quote})
        ma = self.conversion.monthly(a.value, a.period if spec.periodic else None, a.hours_per_week)
        mb = self.conversion.monthly(b.value, b.period if spec.periodic else None, b.hours_per_week)
        if ma is None or mb is None:
            return None
        return a.model_copy(update={"value": fmt(ma + mb), "period": "month" if spec.periodic else None,
                                    "hours_per_week": None, "state": state, "quote": quote})

    def agree(self, a: SlotObservation, b: SlotObservation) -> bool:
        slot = SlotName(a.slot)
        if slot in MONEY:
            spec = SLOT_SPECS[slot]
            if _dec(a.value) is None or _dec(b.value) is None:
                return a.value == b.value
            ma = self.conversion.monthly(a.value, a.period if spec.periodic else None, a.hours_per_week)
            mb = self.conversion.monthly(b.value, b.period if spec.periodic else None, b.hours_per_week)
            if ma is None or mb is None:
                return (_dec(a.value), a.period) == (_dec(b.value), b.period)
            if ma == mb:
                return True
            return abs(ma - mb) <= AGREE * max(abs(ma), abs(mb))
        return a.value == b.value

    def _ssi_amount(self, ob: SlotObservation, from_parser: dict[SlotName, SlotObservation]) -> bool:
        """On a line that names SSI/SSDI: is this model money observation (possibly) the SSI amount?"""
        slot = SlotName(ob.slot)
        if slot not in MONEY:
            return False
        if _SSI.search(ob.quote or ""):
            return True
        if slot not in _SSI_SLOTS:
            return False
        other = from_parser.get(slot)
        return other is None or not self.agree(ob, other)

    # ------------------------------------------------------------------------------------------ merge
    def merge(self, *, utterance: str, llm: ExtractOutcome, parsed: Parsed, keyword_intents: list[Intent],
              pending: PendingQuestion | None, known: dict[SlotName, str], session_lang: str) -> Merged:
        result = llm.result if llm.status == "ok" else None
        lang_raw = result.lang if result is not None else guess_lang(utterance, default=session_lang)
        spanish = lang_raw == "es"
        lang = Lang(lang_raw) if lang_raw in ("en", "es") else None

        model_obs: list[SlotObservation] = []
        if result is not None:
            for ob in result.observations:
                grounded = self.ground(ob, utterance, spanish=spanish, pending=pending, known=known)
                if grounded is not None:
                    model_obs.append(grounded)
        from_parser = self.combine(parsed.observations)
        if result is not None and _SSI.search(utterance):
            # An SSI/SSDI amount only routes and is never stored. The model may quote the amount without the word
            # ("I get SSI, it's 900 a month" -> "900 a month"), so on such a line a benefit or cash amount is kept only
            # when the rule parser (which skips SSI clauses) read the same amount for the same slot.
            model_obs = [o for o in model_obs if not self._ssi_amount(o, from_parser)]
        from_model = self.combine(model_obs)

        final: dict[SlotName, SlotObservation] = {}
        sources: dict[SlotName, SlotSource] = {}
        conflicts: list[SlotName] = []
        for slot, ob in from_model.items():
            other = from_parser.get(slot)
            if other is not None and not self.agree(ob, other):
                ob = ob.model_copy(update={"state": "unclear"})
                conflicts.append(slot)
            final[slot] = ob
            sources[slot] = SlotSource.llm
        keep_all = result is None
        model_says_unanswered = result is not None and result.answered_pending == "no"
        model_spans = [(SlotName(o.slot), _where(o.quote, utterance)) for o in model_obs if SlotName(o.slot) in MONEY]
        for slot, ob in from_parser.items():
            if slot in final:
                continue  # the model reported this slot (clear, unclear or another value): its reading stands
            # Any kind of question: "I'm 20, and I live with two roommates" to the open age question answers
            # lives_with_parent even when the model returns only the age and the roommates.
            answers_pending = pending is not None and slot in pending.slots and not model_says_unanswered
            if answers_pending and slot in MONEY and _claimed(slot, ob.quote, utterance, model_spans, spanish):
                # One spoken amount never feeds two slots: the model already put these words into another money
                # slot ("300 from my mom": other cash, not earnings), so the parser's reading is not added on top.
                continue
            # A routing-only reading (a volunteered status, SSI/SSDI) is a backstop like the keyword lists: kept even
            # when the model missed it, so the dialogue routes the case and drops that utterance from memory.
            if keep_all or answers_pending or slot in ROUTING_ONLY \
                    or (not model_says_unanswered and _backstop(slot, ob, from_model)):
                if slot in ROUTING_ONLY:
                    ob = ob.model_copy(update={"quote": "", "quote_en": None})
                final[slot] = ob
                sources[slot] = SlotSource.parser

        intents = list(result.intents) if result is not None else []
        extra = list(keyword_intents)
        if result is None:
            extra += parsed.intents + ([Intent.off_topic] if parsed.injection else [])
        for intent in extra:
            if intent not in intents:
                intents.append(intent)
        intents = [i for i in _ORDER if i in intents]

        side = None
        requested = None
        if result is not None:
            if Intent.side_question in intents and result.side_question:
                side = result.side_question.strip()[:SIDE_QUESTION_MAX] or None
            if Intent.language_request in intents and result.requested_language:
                code = result.requested_language.strip().lower()
                requested = code if re.fullmatch(r"[a-z]{2}", code) else None
        answered = result.answered_pending if result is not None else _answered(final, pending, parsed)
        if answered == "partial" and pending is not None and pending.slots and set(pending.slots) <= set(final):
            answered = "yes"  # every slot the question asks is in hand (one the model left out came from the parser)

        teen: list[SlotName] = []
        for slot, ob in final.items():
            if SLOT_SPECS[slot].type in ("money", "int") and ob.quote and _teen_ty_value(ob, spanish):
                teen.append(slot)
            elif slot in parsed.teen_ty and slot not in teen:
                teen.append(slot)
        ordered = [s for s in SlotName if s in final]
        return Merged(observations=[final[s] for s in ordered], intents=intents, lang=lang, answered_pending=answered,
                      side_question=side, requested_language=requested, sources={s: sources[s] for s in ordered},
                      teen_ty=[s for s in SlotName if s in teen], conflicts=conflicts)


def _backstop(slot: SlotName, ob: SlotObservation, from_model: dict[SlotName, SlotObservation]) -> bool:
    """A parser fact kept beside a model answer that left it out: the roommate count (said, never asked), unless the
    model says there are no roommates; and "lives alone", unless the model reports roommates, a parent or a boarder
    arrangement."""
    if slot == S.roommates_count:
        mates = from_model.get(S.roommates)
        return mates is None or mates.value != "false"
    if slot == S.household_food and ob.value == "alone" and ob.state == "clear":
        return not any(from_model.get(s) is not None and from_model[s].value == v
                       for s, v in _LIVES_ALONE_CONTRADICTED_BY.items())
    return False


def _teen_ty_value(ob: SlotObservation, spanish: bool) -> bool:
    """True when the value (or the hours of hourly pay) was said with a teen or ty word ("fifteen hundred")."""
    value = _dec(ob.value)
    hours = Decimal(str(ob.hours_per_week)) if ob.hours_per_week is not None else None
    for n in find_numbers(ob.quote, spanish=spanish):
        if n.teen_ty and (n.value in (value, hours) or (n.alt is not None and n.alt == value)):
            return True
    return False


def _answered(final: dict[SlotName, SlotObservation], pending: PendingQuestion | None, parsed: Parsed) -> str:
    if pending is None:
        return "partial" if final else "no"
    pslots = set(pending.slots)
    got = set(final)
    if pslots and pslots <= got:
        return "yes"
    if not pslots and (parsed.answer is not None or parsed.intents):
        return "yes"
    if got:
        return "partial"
    return "no"


def _where(quote: str, utterance: str) -> tuple[int, int] | None:
    """The character span of a quote in the utterance (the first occurrence), or None."""
    if not quote:
        return None
    idx = utterance.find(quote)
    return (idx, idx + len(quote)) if idx >= 0 else None


def _claimed(slot: SlotName, quote: str, utterance: str,
             model_spans: list[tuple[SlotName, tuple[int, int] | None]], spanish: bool) -> bool:
    """True when every number of this quote sits inside a model money quote for another slot: the model already
    attributed those amounts elsewhere. A quote without a number ("Nobody gives me cash") is never claimed."""
    span = _where(quote, utterance)
    if span is None:
        return False
    nums = find_numbers(quote, spanish=spanish)
    if not nums:
        return False
    return all(any(other != slot and where is not None and where[0] <= span[0] + n.start
                   and span[0] + n.end <= where[1] for other, where in model_spans) for n in nums)


def _find_loose(quote: str, utterance: str) -> str | None:
    """The utterance's own substring for a quote that differs only in case, spacing or edge punctuation."""
    q = re.sub(r"\s+", " ", quote).strip().strip(".,!?;:\"'")
    if not q:
        return None
    idx = utterance.lower().find(q.lower())
    if idx < 0:
        return None
    return utterance[idx:idx + len(q)]


def _span(a: str, b: str) -> str:
    return a if b in a else (b if a in b else a)

"""Conversation policy: from what the student said (an Understanding, a key or a silence) to the next reply plan.

"The model listens, rules decide, templates speak" (docs/SPEC.md §2.2): the understanding only extracts; code
normalizes money (through the rules port) and stores slots; the rules port decides tier, estimate and the question plan;
this module picks sentence keys. Order of one turn (docs/SPEC.md §3.2-§3.4):

1. silence, keypad and deferred parts of a split reply are handled first (no language model);
2. the global intents, highest precedence first (data/content/guards.json `input.routing`);
3. the conversation's own questions (consent, delete, keep going, explicit confirm, anything else);
4. observations become slots (read-back, explicit confirm for the four critical money slots, corrections);
5. the phase machine asks the next question or gives the result, card and close lines.

Each reply holds at most one question, and it comes last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from gatorplate.contracts import console_text
from gatorplate.contracts.case import CardRef, Case, Consent, LanguageRequest, SkippedQuestion
from gatorplate.contracts.common import Channel, Lang, Phase, SlotSource, SlotState, Tier
from gatorplate.contracts.extraction import Intent, PendingQuestion, SlotObservation, Understanding
from gatorplate.contracts.rules_io import FlipCandidate
from gatorplate.contracts.session import SessionState
from gatorplate.contracts.slots import (
    ROUTING_ONLY,
    SLOT_SPECS,
    MoneyBasis,
    Slot,
    SlotName,
    decode_value,
    encode_value,
    format_display,
)
from gatorplate.contracts.summary import household_size
from gatorplate.dialogue import machine, yellow
from gatorplate.dialogue.intents import Routing, Winner, yes_no
from gatorplate.dialogue.machine import FLIP_KEYS, PHASES, QUESTION_PHASES
from gatorplate.dialogue.templates import Bank, Step

S = SlotName
CRITICAL: frozenset[SlotName] = frozenset(s for s, spec in SLOT_SPECS.items() if spec.critical)
LOW_CONFIDENCE = 0.75  # docs/BRAIN_API.md §5.2: below it a critical money amount is confirmed explicitly
TURN_CAP = 24  # student turns (docs/SPEC.md §3.6)
TIME_CAP = timedelta(minutes=8)
MAX_CLOSE_LOOPS = 2
HOLD_SECONDS = 30  # docs/SPEC.md §3.3: "take your time" holds the line for 30 seconds
DETOUR_KEYS = frozenset({"crisis.continue_or_stop", "human.request", "delete.confirm_ask"})
CONSENT_KEYS = frozenset({"consent.ask", "consent.reask"})
# A yes without an amount to a money question: the follow-up that asks for it (docs/SPEC.md §4.5 item 5.3; the
# bank's closed forms).
AMOUNT_FOLLOW_UP: dict[str, str] = {
    "flip.rent_paid_by_others": "flip.rent_paid_by_others_amount",
    "ask.income": "ask.income_band",
    "ask.other_cash": "flip.other_cash_band",
}
BAND_QUESTIONS = frozenset({"ask.income_band", "flip.other_cash_band", "flip.earned_split"})
# Lines that answer a side remark and then ask the pending question again (in phase 0: consent.reask).
INFO_LINES = frozenset({"is_ai", "is_recorded", "apply_for_me", "immigration_question", "food_today", "proxy_caller",
                        "side_question", "previously_denied"})
# Global intents of a deferred (split) reply that still win over delivering the rest.
URGENT = frozenset({"crisis", "redaction", "delete_data", "stop", "human_request", "repeat"})
# Phases after the result was said: a correction there runs the rules again and says the result again.
AFTER_RESULT = frozenset({Phase.expedited, Phase.card, Phase.close})
# Slots whose unclear answer needs no review line: consent, and the never-asked roommate count that only the card's
# programs part reads (it assumes a count itself and never blocks the review lock).
NO_UNCLEAR_LINE = frozenset({SlotName.consent, SlotName.roommates_count})
# The understanding's answer to a yes/no about a value (confirm.money): "true" / "false" on the confirmed slot.
POLAR = {"true": "yes", "yes": "yes", "false": "no", "no": "no"}


@dataclass
class Plan:
    """A planned reply: sentence steps plus what the reply does."""

    steps: list[Step]
    end_reason: str | None = None  # completed | no_input | declined
    hold_s: int = 0
    reply_lang: Lang | None = None  # language.offer_web on the phone speaks Spanish
    keep_pending: bool = False  # the pending question stays as it was (hold, the Spanish notice)
    delete_case: bool = False
    repeat: bool = False  # send the last reply again
    record: str | None = None  # AskedQuestion kind for the question, None = not a case question
    flip: FlipCandidate | None = None
    drop_from_memory: bool = False
    noise: bool = False  # a re-ask after nothing usable was heard: no unclear answer, the unclear ladder stays


@dataclass
class Ctx:
    """Everything one request works on. `case` and `session` are mutated in place and saved by the orchestrator."""

    call_id: str
    case: Case
    session: SessionState
    now: datetime
    today: date
    turn: int
    channel: Channel
    settings: Any
    changed: list[SlotName] = field(default_factory=list)
    yes_answer: str | None = None
    outcome_before: tuple[Any, ...] | None = None  # the case's result when the turn began

    @property
    def lang(self) -> Lang:
        return self.session.lang


def outcome(case: Case) -> tuple[Any, ...]:
    """What the student was told: tier, route, amount and whether it is a floor."""
    return case.tier, case.reason_code, case.estimate_monthly, case.estimate_is_floor


def forget_unconsented(case: Case) -> None:
    """A call without consent keeps only that it happened (time, channel) and content-free flags and privacy events:
    no answers, no side-question paraphrase, no language request, no route (docs/SPEC.md §3.1)."""
    case.slots = {}
    case.yellow_lines = []
    case.language_request = None
    case.route_override = None
    case.asked = []
    case.skipped = []
    case.timeline = []
    case.summary = ""


def known(case: Case, slot: SlotName) -> bool:
    item = case.slots.get(slot)
    return item is not None and item.state != SlotState.missing


def value_of(case: Case, slot: SlotName) -> Any:
    item = case.slots.get(slot)
    if item is None or item.value is None:
        return None
    try:
        return decode_value(slot, item.value)
    except (TypeError, ValueError):
        return None


class Dialogue:
    """The policy. Pure decisions over the case and the session, plus calls to the rules port."""

    def __init__(self, *, bank: Bank, routing: Routing, rules: Any, table: dict[str, Any], ids: Any,
                 cases: Any) -> None:
        self.bank = bank
        self.routing = routing
        self.rules = rules
        self.table = table
        self.ids = ids
        self.cases = cases
        voi = table.get("voi") or {}
        self.max_flips: int = int(voi.get("max_questions", 2))
        status = table.get("status") or {}
        self.status_other_help: set[str] = set(status.get("other_help") or [])
        self.status_coordinator: set[str] = set(status.get("coordinator") or [])
        self.rules_errors = 0

    # ======================================================================================== entry points

    def start(self, ctx: Ctx) -> Plan:
        ctx.session.phase = Phase.consent
        ctx.session.awaiting = "consent"
        return Plan([Step("consent.ask")])

    def silence(self, ctx: Ctx, n: int) -> Plan:
        """The silence ladder (docs/SPEC.md §3.7): repeat, then the closed form, then end with no_input."""
        s = ctx.session
        s.silence_count = n
        if s.deferred_keys:
            return self.deliver_deferred(ctx)
        pending_key = s.pending.key if s.pending is not None else None
        if pending_key == self.routing.close_pending or (s.phase == Phase.close and pending_key != "confirm.money"):
            return Plan([Step(self.routing.close_reply)], end_reason="completed")
        if n >= 3:
            self._ended_early(ctx)
            return Plan([Step("close.silence")], end_reason="no_input")
        question = self._pending_step(ctx, "main" if n == 1 else "closed")
        if question is None:
            return self.advance(ctx, [], ack=False)
        if s.pending is not None and s.pending.key in CONSENT_KEYS:
            question = Step("consent.ask", "short" if n == 1 else "closed")
        wrapper = "reprompt.silence_1" if n == 1 else "reprompt.silence_2"
        return Plan([Step(wrapper, question=question)], record=self._reask_kind(ctx, question))

    def keypad(self, ctx: Ctx, key: str) -> Plan:
        """Single keys only (docs/BRAIN_API.md §5.2): 1 = yes, 2 = no, numbered choices 1-3. A key the pending question
        does not offer, or a value longer than one key, is an unclear answer."""
        s = ctx.session
        s.silence_count = 0
        if s.deferred_keys:
            return self.deliver_deferred(ctx)
        pending = s.pending
        if pending is None or len(key) != 1:
            return self.unclear(ctx, give_up=False)
        expect = self.bank.expect(pending.key, "closed" if pending.closed else "main", ctx.lang) or {}
        keypad = expect.get("keypad")
        if keypad is None:  # an open question asked in its main form: the closed form's keys
            keypad = (self.bank.expect(pending.key, "closed", ctx.lang) or {}).get("keypad")
        if keypad == "yes_no":
            if key not in ("1", "2"):
                return self.unclear(ctx, give_up=False)
            return self.answer_yes_no(ctx, "yes" if key == "1" else "no", source=SlotSource.keypad)
        if isinstance(keypad, dict) and key in keypad:
            return self.apply_entry(ctx, keypad[key], source=SlotSource.keypad)
        return self.unclear(ctx, give_up=False)

    def utterance(self, ctx: Ctx, u: Understanding, *, masked: bool, interrupted: bool, confidence: float | None,
                  text: str) -> Plan:
        s = ctx.session
        s.silence_count = 0
        winner = self.routing.winner(u, masked=masked)
        names = self.routing.present(u, masked=masked)
        if s.deferred_keys:
            if winner is None or winner.name not in URGENT:
                if not self._says_more(ctx, u, winner):
                    return self.deliver_deferred(ctx)
                return self._before_rest(ctx, u, masked=masked, interrupted=interrupted, confidence=confidence,
                                         text=text)
            if winner.name != "repeat":
                s.deferred_keys = []
        if s.phase == Phase.consent:
            return self.consent(ctx, u, winner, text, confidence=confidence)
        pending_key = s.pending.key if s.pending else None
        # The close question is open (an explicit confirm asked at the close is answered first, never a goodbye).
        at_close = pending_key == self.routing.close_pending or (s.phase == Phase.close
                                                                 and pending_key != "confirm.money")
        # crisis and privacy first, whatever is pending
        if winner is not None and winner.name in ("crisis", "redaction"):
            return self.global_intent(ctx, winner, u, names)
        if s.awaiting == "delete_confirm":
            if winner is not None and winner.name == "delete_data":
                return self._delete_done(ctx)
            answer = yes_no(text, ctx.lang)
            if answer == "yes":
                return self._delete_done(ctx)
            if answer is None and "reprompt.unclear" not in s.last_keys:
                return self.unclear(ctx)
            s.awaiting = "none"
            return self.resume(ctx, [Step("delete.cancelled")], form="short", skip_pending=True)
        if winner is not None and winner.name == "delete_data":
            return self.global_intent(ctx, winner, u, names)
        if at_close and (self.routing.is_done(text, ctx.lang) or "stop" in names):
            # "Nothing else. Actually my rent is twelve hundred." / "No thanks, I'm on an F-1 visa.": what comes with
            # the done phrase is applied first (corrections apply at any time, a volunteered status routes —
            # docs/SPEC.md §3.2, §3.3); only a plain closing that brings nothing new says goodbye at once. A done phrase
            # that says more and carries another intent ("No thanks, is this call recorded?", a side question the
            # model noted) gets that intent's answer, then the close question again.
            plain = "stop" in names or self.routing.is_only_done(text, ctx.lang)
            if plain or winner is None:
                return self.close_again(ctx, u, [], done=True, plain=plain)
        if s.awaiting == "continue_or_stop":  # another global intent leaves the choice pending
            if "stop" in names or yes_no(text, ctx.lang) == "no":
                return self._stop(ctx)
            if winner is None:
                self.apply_observations(ctx, u, quote=False)
                self.refresh(ctx)
                return self.resume(ctx, [], form="short", skip_pending=True)
        if pending_key == "human.request" and (winner is None or winner.name not in ("stop", "human_request")):
            answer = yes_no(text, ctx.lang)
            if answer == "no":
                return self._stop(ctx)
            if answer == "yes":  # keep going; facts said with the yes are kept
                if u.observations:
                    self.apply_observations(ctx, u, skip={S.consent})
                    self.refresh(ctx)
                return self.resume(ctx, [], form="short", skip_pending=True)
        if winner is not None and winner.name == "stop" and s.awaiting == "none" \
                and self.routing.weak_stop(text, confidence, low=LOW_CONFIDENCE):
            # a bare "stop" / "bye", or a goodbye at the end of other talk (a TV, the room on a speakerphone): asked
            # about first; "stop" or "no" to it ends the call, anything else goes on (the continue_or_stop branch)
            self.apply_observations(ctx, u, quote=False)
            self.refresh(ctx)
            s.awaiting = "continue_or_stop"
            return Plan([Step("crisis.continue_or_stop")])
        if winner is not None and winner.name == "hold" and u.observations and s.awaiting == "none":
            # "One sec... okay, it's eleven hundred": the student came back with an answer in the same breath. It is
            # handled as an answer (read back, confirmed when needed, then the next question); a bare hold.ok would
            # change a value without the student hearing it (docs/SPEC.md §3.4). Nothing new said → hold.ok.
            if at_close:
                return self.close_again(ctx, u, [], hold=True)
            return self.answer(ctx, u, interrupted=interrupted, confidence=confidence, text=text, hold=True)
        if winner is not None:
            return self.global_intent(ctx, winner, u, names)
        if at_close:
            return self.close_again(ctx, u, [])
        return self.answer(ctx, u, interrupted=interrupted, confidence=confidence, text=text)

    def noise(self, ctx: Ctx, heard: str, *, interrupted: bool) -> Plan:
        """Nothing usable heard (extract/noise.py): an empty, filler-only or bracketed transcript, a cut-off fragment,
        background speech that says nothing to us ("noise"), or a line check such as "hello?"
        ("check"), a request to hear it again ("repeat"). Nothing is stored and it is no unclear answer: a repeat or a
        check hears the last reply again, noise gets the pending question again (consent: a line check or noise gets
        consent.reask, its re-ask count unchanged)."""
        s = ctx.session
        pending = s.pending
        at_consent = pending is not None and pending.key in CONSENT_KEYS
        if (heard == "repeat" or (heard == "check" and not at_consent)) and not interrupted:
            return Plan([], repeat=True)
        if at_consent:
            return Plan([Step("consent.reask")], noise=True)
        # the short form keeps "Sorry, I missed that." + the question within the word budget; a question asked in its
        # closed form (or closed mode) is asked closed again
        closed = pending is not None and (pending.closed or s.closed_mode)
        question = self._pending_step(ctx, "main" if closed else "short")
        if question is None:
            return Plan([], repeat=True)
        wrapper = "reprompt.after_interrupt" if interrupted else "reprompt.unclear"
        return Plan([Step(wrapper, question=question)], record=self._reask_kind(ctx, question), noise=True)

    def deliver_deferred(self, ctx: Ctx) -> Plan:
        steps = [Step.decode(k) for k in ctx.session.deferred_keys]
        ctx.session.deferred_keys = []
        plan = Plan(steps)
        last = steps[-1].key if steps else ""
        if last == "close.anything_else":
            ctx.session.phase = Phase.close
        # A question that arrives in the second part is still a case question (Case.asked, docs/UI_SPEC.md A3.10).
        if last == "confirm.money":
            plan.record = "confirm"
        elif last.startswith("flip.") and last != "flip.intro":
            plan.record = "flip"
            plan.flip = self._flip_candidate(ctx, last)
        elif last in machine.BAND_KEYS:
            plan.record = "band"
        elif last.startswith(machine.CASE_QUESTION_PREFIXES):
            plan.record = "standard"
        if last == "flip.earned_split":
            steps[-1].vars["x"] = self._earned_split(ctx)
        return plan

    def _says_more(self, ctx: Ctx, u: Understanding, winner: Winner | None) -> bool:
        """Did the student say something new while the rest of a split reply was waiting: an amount or a fact that
        differs from the case, or a global intent ("Is this a real person?", "Hold on")? A bare "okay" or "yes"
        (a yes/no value on the already-answered question) is not new: the rest is delivered."""
        if winner is not None and winner.name != "repeat":
            return True
        for obs in u.observations:
            if obs.value.strip().lower() in POLAR:
                continue
            item = ctx.case.slots.get(obs.slot)
            if obs.slot in ROUTING_ONLY or item is None or item.value is None:
                return True
            try:
                if obs.slot in SLOT_SPECS and SLOT_SPECS[obs.slot].type == "money":
                    if encode_value(obs.slot, self._money_value(ctx, obs, obs.slot)) != item.value:
                        return True
                elif encode_value(obs.slot, obs.value) != item.value:
                    return True
            except (InvalidOperation, TypeError, ValueError):
                return True
        return False

    def _before_rest(self, ctx: Ctx, u: Understanding, *, masked: bool, interrupted: bool,
                     confidence: float | None, text: str) -> Plan:
        """Something new said before the rest of a split reply arrived (docs/SPEC.md §3.2: every turn applies the new
        observations): it is handled first — a correction is read back, a changed result said again, a question
        answered — and the rest follows in the same reply. The phase machine plans the next question again, so only
        the rest's lines that ask nothing (a card code, the apply-today line) are carried over. A hold keeps the
        rest waiting until the student is back."""
        s = ctx.session
        rest = [Step.decode(k) for k in s.deferred_keys]
        s.deferred_keys = []
        # the question of the first part was already answered: a yes or no now is no new answer to it
        u = u.model_copy(update={"observations": [o for o in u.observations if o.value.strip().lower() not in POLAR]})
        s.pending = None
        plan = self.utterance(ctx, u, masked=masked, interrupted=interrupted, confidence=confidence, text=text)
        if plan.end_reason is not None or plan.repeat or plan.delete_case:
            return plan
        if plan.hold_s:
            s.deferred_keys = [st.encode() for st in rest]  # after the hold, the rest of the reply
            return plan
        said = {st.key for st in plan.steps}
        carry = [st for st in rest if not self._asks(st) and st.key not in said]
        if carry:
            if plan.steps and self._asks(plan.steps[-1]):
                plan.steps[-1:-1] = carry
            else:
                plan.steps.extend(carry)
        return plan

    def _asks(self, step: Step) -> bool:
        return step.question is not None or step.key == self.routing.close_pending or self.bank.is_question(step.key)

    def _flip_candidate(self, ctx: Ctx, key: str) -> FlipCandidate | None:
        """The question plan's candidate for a flip key (its reason and outcomes for the console chip)."""
        try:
            plan = self.rules.flip_plan(ctx.case, today=ctx.today, budget=1)
        except Exception:  # noqa: BLE001 - the chip text never blocks the call
            self.rules_errors += 1
            return None
        return next((c for c in list(plan.ask) + list(plan.not_asked) if FLIP_KEYS.get(c.slot) == key), None)

    # ======================================================================================== consent (phase 0)

    def consent(self, ctx: Ctx, u: Understanding, winner: Winner | None, text: str, *,
                confidence: float | None = None) -> Plan:
        s = ctx.session
        answer: str | None = None
        for obs in u.observations:
            if obs.slot == S.consent:
                answer = "yes" if obs.value.strip().lower() in ("true", "yes") else "no"
        if winner is not None and winner.name in ("crisis", "redaction"):
            return self.global_intent(ctx, winner, u, [winner.name])
        weak = winner is not None and winner.name == "stop" and self.routing.weak_stop(text, confidence,
                                                                                         low=LOW_CONFIDENCE)
        if winner is not None and winner.name in ("stop", "delete_data") and not weak:
            answer = "no"
        if answer is None and winner is not None and winner.name in INFO_LINES:
            if winner.name == "side_question" and u.side_question:
                yellow.student_question(ctx.case, u.side_question, ctx.now)
            return Plan([Step(str(winner.reply)), Step("consent.reask")])
        if answer is None and winner is not None and winner.name == "repeat":
            return Plan([], repeat=True)
        if answer is None and winner is not None and winner.name in ("hold", "language_request", "human_request",
                                                                       "abuse"):
            return self.global_intent(ctx, winner, u, [winner.name])
        if answer is None:
            answer = yes_no(text, ctx.lang)
        if answer == "yes":
            return self.consent_given(ctx, u)
        if answer == "no" or s.consent_reasks >= 1:
            return self.consent_declined(ctx)
        s.consent_reasks += 1
        return Plan([Step("consent.reask")])

    def consent_given(self, ctx: Ctx, u: Understanding | None, *, source: SlotSource | None = None) -> Plan:
        s, case = ctx.session, ctx.case
        s.awaiting = "none"
        s.phase = Phase.student
        case.consent = Consent(given=True, at=ctx.now, disclosure_key="consent.ask")
        self._set(ctx, S.consent, "true", source=source or SlotSource.llm, heard=None)
        if u is not None:  # facts said in the consenting utterance are kept
            self.apply_observations(ctx, u, skip={S.consent})
        self.refresh(ctx)
        return self.advance(ctx, [], ack=True)

    def consent_declined(self, ctx: Ctx) -> Plan:
        case = ctx.case
        forget_unconsented(case)  # nothing from the call is stored except that it was declined
        case.consent = Consent(given=False, at=ctx.now, disclosure_key="consent.ask")
        ctx.session.awaiting = "none"
        ctx.changed = []
        return Plan([Step("consent.declined")], end_reason="declined")

    # ======================================================================================== global intents

    def global_intent(self, ctx: Ctx, winner: Winner, u: Understanding, names: list[str]) -> Plan:
        s, case = ctx.session, ctx.case
        name = winner.name
        if name == "crisis":
            if "crisis_resources_given" not in case.flags:
                case.flags.append("crisis_resources_given")
            self.apply_observations(ctx, u, quote=False)
            s.awaiting = "continue_or_stop"
            return Plan([Step("crisis.resources"), Step("crisis.continue_or_stop")])
        if name == "redaction":
            # nothing is stored from this turn: only a content-free privacy event
            kind = "card_number_blocked" if winner.reply == "card_number.block" else "ssn_blocked"
            from gatorplate.contracts.case import PrivacyEvent

            case.privacy_events.append(PrivacyEvent(kind=kind, at=ctx.now))
            question = self._pending_step(ctx, "short") or self._next_question_step(ctx, "short")
            return Plan([Step(winner.reply, question=question)], keep_pending=question is None)
        if name == "delete_data":
            s.awaiting = "delete_confirm"
            return Plan([Step("delete.confirm_ask")])
        if name == "stop":
            return self._stop(ctx)
        if name == "human_request":
            if "human_requested" not in case.flags:
                case.flags.append("human_requested")
            self.apply_observations(ctx, u)
            self.refresh(ctx)
            return Plan([Step("human.request")])
        if name in ("is_ai", "is_recorded"):
            self.apply_observations(ctx, u)
            self.refresh(ctx)
            return self.resume(ctx, [Step(winner.reply)], form="short")
        if name == "language_request":
            return self.language(ctx, u)
        if name == "hold":
            self.apply_observations(ctx, u)
            self.refresh(ctx)
            return self._hold()
        if name in ("already_receiving", "interview_waiting"):
            slot = S.already_receiving if name == "already_receiving" else S.applied_waiting_interview
            self.apply_observations(ctx, u)
            self._set(ctx, slot, "true", source=SlotSource.llm, heard=None)
            self.refresh(ctx)
            if s.phase in machine.BEFORE_RESULT:
                s.phase = Phase.result
                return self.advance(ctx, [], ack=False)
            return self.resume(ctx, [], form="short")
        if name == "side_question":
            paraphrase = u.side_question or ""
            if paraphrase:
                yellow.student_question(case, paraphrase, ctx.now)
            self.apply_observations(ctx, u)
            self.refresh(ctx)
            return self._after_info(ctx, Step("side_question.noted"))
        if name == "previously_denied":
            self.apply_observations(ctx, u)
            self._set(ctx, S.previously_denied, "true", source=SlotSource.llm, heard=None)
            self.refresh(ctx)
            return self._after_info(ctx, Step("info.previously_denied"))
        if name in ("apply_for_me", "immigration_question", "food_today", "proxy_caller"):
            applied = self.apply_observations(ctx, u)
            self.refresh(ctx)
            if applied.status_route and s.phase in machine.BEFORE_RESULT:  # the volunteered route decides the reply
                s.phase = Phase.result
                return self.advance(ctx, [], ack=False, drop=True)
            return self._after_info(ctx, Step(str(winner.reply)))
        if name == "abuse":
            self.apply_observations(ctx, u, quote=False)
            self.refresh(ctx)
            s.abuse_count += 1
            if s.abuse_count >= 2:
                if "abuse_ended" not in case.flags:
                    case.flags.append("abuse_ended")
                self._ended_early(ctx)
                return Plan([Step("abuse.end")], end_reason="completed")
            return self.resume(ctx, [Step("abuse.warn")], form="short")
        if name == "repeat":
            return Plan([], repeat=True)
        return self.answer(ctx, u, interrupted=False, confidence=None, text="")

    def _after_info(self, ctx: Ctx, line: Step) -> Plan:
        if ctx.session.phase == Phase.close or (ctx.session.pending is not None
                                                and ctx.session.pending.key == self.routing.close_pending):
            return self.close_again(ctx, None, [line])
        return self.resume(ctx, [line], form="short")

    def language(self, ctx: Ctx, u: Understanding) -> Plan:
        s, case = ctx.session, ctx.case
        asked = (u.requested_language or "").lower()[:2]
        if not asked and self.routing.asks_spanish(u.redacted_text):
            asked = "es"
        elif not asked and self.routing.asks_english(u.redacted_text):
            asked = "en"
        if ctx.channel == Channel.phone:
            if asked == "es":
                case.language_request = LanguageRequest(asked="es", offered="web")
                return Plan([Step("language.offer_web")], reply_lang=Lang.es, keep_pending=True)
            if asked == "en":
                return self.resume(ctx, [], form="short")
            # a language other than English or Spanish, also when no model named it ("Can we do this in
            # Vietnamese?" read by the keyword list alone): the unsupported-language line (docs/SPEC.md §3.5)
            asked = asked or "xx"
            case.language_request = LanguageRequest(asked=asked, offered="none")
            return self.resume(ctx, [Step("language.unsupported")], form="short")
        if asked in ("en", "es"):
            case.language_request = LanguageRequest(asked=asked, offered="switched")
            s.lang = Lang(asked)
            case.lang = Lang(asked)
            return self.resume(ctx, [Step("ack.short")], form="main")
        case.language_request = LanguageRequest(asked=asked or "xx", offered="none")
        return self.resume(ctx, [Step("language.unsupported")], form="short")

    @staticmethod
    def _hold() -> Plan:
        """hold.ok: the line waits (hold_s), nothing is asked, the pending question stays (docs/SPEC.md §3.3)."""
        return Plan([Step("hold.ok")], hold_s=HOLD_SECONDS, keep_pending=True)

    def _stop(self, ctx: Ctx) -> Plan:
        ctx.session.awaiting = "none"
        if ctx.session.phase == Phase.close:
            return Plan([Step(self.routing.close_reply)], end_reason="completed")
        self._ended_early(ctx)
        return Plan([Step("stop.goodbye")], end_reason="completed")

    def _delete_done(self, ctx: Ctx) -> Plan:
        ctx.session.awaiting = "none"
        return Plan([Step("delete.done")], end_reason="completed", delete_case=True)

    def _ended_early(self, ctx: Ctx) -> None:
        """Before a result: flag ended_early and the yellow incomplete line (docs/SPEC.md §3.3)."""
        if ctx.session.phase in machine.BEFORE_RESULT and ctx.session.phase != Phase.consent:
            ctx.case.ended_early = True
            yellow.incomplete(ctx.case, ctx.now)

    # ======================================================================================== answers

    def answer(self, ctx: Ctx, u: Understanding, *, interrupted: bool, confidence: float | None, text: str,
               hold: bool = False) -> Plan:
        """An utterance with no global intent: apply what it says, then the next step. With `hold` the utterance also
        held a hold phrase: when it changes nothing (a value said again, no follow-up), the line waits instead."""
        s = ctx.session
        pending = s.pending
        intents = {i.value for i in u.intents} | {i.value for i in u.keyword_intents}
        if pending is not None and self._yes_no_band(ctx, pending):
            # "Is your pay less than $X?": a yes or no picks a part of the band; the understanding reports a bare
            # yes or no on a money slot as "true" / "0", which is never the amount
            answer = yes_no(text, ctx.lang)
            said = [o for o in u.observations if o.slot in pending.slots]
            if answer is not None and all(o.value.strip().lower() in POLAR or o.value.strip() in ("0", "0.00")
                                          for o in said):
                return self.answer_yes_no(ctx, answer, source=SlotSource.parser)
        if pending is not None and pending.key == "confirm.money":
            plan = self._confirm_answer(ctx, u, text)
            if plan is not None:
                return plan
            # a yes or no about the value is never an amount (a "false" must not become $0)
            confirmed = pending.slots[0] if pending.slots else None
            u = u.model_copy(update={"observations": [
                o for o in u.observations if not (o.slot == confirmed and o.value.strip().lower() in POLAR)]})
        result = self.apply_observations(ctx, u, confidence=confidence)
        if hold and not ctx.changed and result.confirm is None and not result.follow_up and not result.status_route:
            self.refresh(ctx)
            return self._hold()
        if result.status_route:
            self.refresh(ctx)
            s.phase = Phase.result
            return self.advance(ctx, [], ack=False, drop=True)
        if result.follow_up and pending is not None and pending.key in AMOUNT_FOLLOW_UP:
            self.refresh(ctx)
            return self._question(ctx, [Step("ack.short")], Step(AMOUNT_FOLLOW_UP[pending.key]),
                                  record="flip" if pending.key.startswith("flip.") else "band")
        if result.confirm is not None:
            slot = result.confirm
            s.confirms[slot] = s.confirms.get(slot, 0) + 1
            self.refresh(ctx)
            return self._question(ctx, [], Step("confirm.money", vars={"slot": slot.value}), record="confirm",
                                  pending_slots=[slot])
        if not ctx.changed:
            if Intent.dont_know.value in intents and pending is not None:
                return self._dont_know(ctx)
            if interrupted:
                question = self._pending_step(ctx, "main")
                if question is not None:
                    return Plan([Step("reprompt.after_interrupt", question=question)],
                                record=self._reask_kind(ctx, question))
            if pending is not None and pending.key in CONSENT_KEYS | DETOUR_KEYS:
                return self.unclear(ctx)
            if pending is not None and self._pending_open(ctx):
                return self.unclear(ctx)
            if pending is None and s.phase in (Phase.close, Phase.card):
                return self.close_again(ctx, u, [])
        self.refresh(ctx)
        lead = self._readback(ctx, result.readback, zero=result.zeroed) + self._result_again(ctx)
        partly = self._partly_answered(ctx, pending)
        if partly:
            # the same question would come again with only part of it answered ("I'm twenty" to "How old are you,
            # and who do you live with?"): one re-ask, then the missing part stays unclear (docs/SPEC.md §3.7)
            if "reprompt.unclear" not in s.last_keys:
                assert pending is not None
                question = Step(pending.key, "short")
                return Plan(lead + [Step("reprompt.unclear", question=question)],
                            record=self._reask_kind(ctx, question))
            for slot in partly:
                ctx.case.slots[slot] = Slot(state=SlotState.unclear, turn=ctx.turn, updated_at=ctx.now)
                ctx.changed.append(slot)
            self.refresh(ctx)
            self.unclear_lines(ctx, partly)
        return self.advance(ctx, lead, ack=not lead and bool(ctx.changed))

    def _partly_answered(self, ctx: Ctx, pending: PendingQuestion | None) -> list[SlotName]:
        """The goal slots still missing when the phase machine would ask the pending question again although part
        of it was answered (a two-part question). Empty when the next question is a different one."""
        s, case = ctx.session, ctx.case
        if pending is None or s.phase not in PHASES or not pending.key.startswith("ask."):
            return []
        if self._hard_stop(ctx, s.phase, earlier=True):
            return []  # an earlier phase's route is settled by this answer: the result comes next
        nxt = self._late_question(ctx, s.phase) or self.question_for(ctx, s.phase)
        if nxt is None or nxt.key != pending.key:
            return []
        if not any(known(case, slot) for slot in pending.slots):
            return []  # nothing of it answered: the unclear-answer rule already handles it
        return [g for g in PHASES[s.phase].goals if g in pending.slots and not known(case, g)]

    def _confirm_answer(self, ctx: Ctx, u: Understanding, text: str) -> Plan | None:
        """The answer to confirm.money: the same value or yes confirms; a new value is a correction; a bare no leaves
        the value unclear with a yellow line (one explicit confirm per slot). The understanding reports a bare yes or
        no about the value as "true" / "false" on the confirmed slot."""
        s, case = ctx.session, ctx.case
        pending = s.pending
        assert pending is not None
        slot = pending.slots[0] if pending.slots else None
        if slot is None:
            return None
        current = case.slots.get(slot)
        same = [o for o in u.observations if o.slot == slot and o.value.strip().lower() not in POLAR]
        polar = [POLAR[o.value.strip().lower()] for o in u.observations
                 if o.slot == slot and o.value.strip().lower() in POLAR]
        others = [o for o in u.observations if o.slot != slot]
        if same and current is not None:
            try:
                heard = self._money_value(ctx, same[0], slot)
            except (InvalidOperation, ValueError):
                heard = None
            agreed = all(o.state == "clear" for o in same)
            if agreed and heard is not None and current.value is not None and \
                    encode_value(slot, heard) == current.value:
                self._confirm_slot(ctx, slot)
                return self._after_confirm(ctx, u, others)
            return None  # a different amount: a correction, applied as heard
        answer = ctx.yes_answer or (polar[0] if polar else None) or yes_no(text, ctx.lang)
        if answer == "yes":
            self._confirm_slot(ctx, slot)
            return self._after_confirm(ctx, u, others)
        if answer == "no" and current is not None:
            current.state = SlotState.unclear
            current.updated_at = ctx.now
            if slot not in ctx.changed:
                ctx.changed.append(slot)
            yellow.unclear(case, slot, current.display or format_display(slot, current.value, current.basis), ctx.now,
                           heard=current.heard)
            return self._after_confirm(ctx, u, others)
        return None

    def _after_confirm(self, ctx: Ctx, u: Understanding, others: list[SlotObservation]) -> Plan:
        """Other facts said with the confirm answer are kept; after the result, the result is said again (the
        confirmed value came from a correction)."""
        if others:
            self.apply_observations(ctx, u.model_copy(update={"observations": others}))
        self.refresh(ctx)
        lead = self._result_again(ctx, force=True)
        return self.advance(ctx, lead, ack=not lead)

    def _result_again(self, ctx: Ctx, *, force: bool = False) -> list[Step]:
        """After the result was said, a correction runs the rules again: when the result changed (or a confirm of a
        corrected value settled), the result line is said again so the student never keeps an outdated amount."""
        if ctx.session.phase not in AFTER_RESULT:
            return []
        if outcome(ctx.case) != ctx.outcome_before or (force and ctx.changed):
            return self.result_steps(ctx)
        return []

    def _confirm_slot(self, ctx: Ctx, slot: SlotName) -> None:
        item = ctx.case.slots.get(slot)
        if item is not None:
            item.state = SlotState.clear
            item.confirmed = True
            item.updated_at = ctx.now
            if slot not in ctx.changed:
                ctx.changed.append(slot)

    def _dont_know(self, ctx: Ctx) -> Plan:
        pending = ctx.session.pending
        assert pending is not None
        if pending.key == "ask.income":
            return self._question(ctx, [], Step("ask.income_band"), record="band")
        if pending.key in ("ask.income_band", "flip.earned_split", "flip.other_cash_band"):
            return self._give_up(ctx)
        if "reprompt.unclear" in ctx.session.last_keys or pending.closed:
            return self._give_up(ctx)
        return self._question(ctx, [], Step(pending.key, "closed"), record="closed")

    def unclear(self, ctx: Ctx, *, give_up: bool = True) -> Plan:
        """Empty or unclear: reprompt.unclear + the closed form once; still unclear, move on (consent: no). A key the
        question does not offer is never an answer: it always gets the closed form again (give_up=False)."""
        s = ctx.session
        pending = s.pending
        if pending is None:
            return self.advance(ctx, [], ack=False)
        if pending.key in CONSENT_KEYS:
            if s.consent_reasks >= 1:
                return self.consent_declined(ctx)
            s.consent_reasks += 1
            return Plan([Step("consent.reask")])
        if give_up and "reprompt.unclear" in s.last_keys:
            if pending.key in DETOUR_KEYS:
                s.awaiting = "none"
                return self.resume(ctx, [], form="short", skip_pending=True)
            if pending.key == self.routing.close_pending:
                return Plan([Step(self.routing.close_reply)], end_reason="completed")
            return self._give_up(ctx)
        question = Step(pending.key, "closed")
        return Plan([Step("reprompt.unclear", question=question)], record=self._reask_kind(ctx, question))

    def _give_up(self, ctx: Ctx) -> Plan:
        """Still unclear after the closed re-ask: the open slots stay unclear (the rules use the conservative value)."""
        pending = ctx.session.pending
        given_up: list[SlotName] = []
        if pending is not None:
            for slot in pending.slots:
                item = ctx.case.slots.get(slot)
                if not known(ctx.case, slot):
                    ctx.case.slots[slot] = Slot(state=SlotState.unclear, turn=ctx.turn, updated_at=ctx.now)
                    ctx.changed.append(slot)
                    given_up.append(slot)
                elif item is not None and item.state in (SlotState.unclear, SlotState.assumed):
                    # an unclear or band answer asked about again (a flip) and still unclear: settled as it is
                    item.turn, item.updated_at = ctx.turn, ctx.now
                    given_up.append(slot)
            if pending.key == "confirm.money" and pending.slots:
                item = ctx.case.slots.get(pending.slots[0])
                if item is not None:
                    yellow.unclear(ctx.case, pending.slots[0], item.display or "—", ctx.now, heard=item.heard)
        ctx.session.pending = None
        self.refresh(ctx)
        self.unclear_lines(ctx, given_up)  # docs/SPEC.md §3.7: still unclear -> conservative value + yellow
        return self.advance(ctx, [], ack=False)

    def unclear_lines(self, ctx: Ctx, slots: list[SlotName] | None = None) -> None:
        """A yellow `unclear.<slot>` line for every answer that stayed unclear (the given-up slots, or at the result
        every unclear slot): the rules use the conservative value and leave the line to the dialogue (docs/SPEC.md
        §5.6, "unclear answer never resolved"). A slot that already has a line (the rules' or the dialogue's) gets no
        second one."""
        case = ctx.case
        names = slots if slots is not None else [n for n, item in case.slots.items()
                                                 if item.state == SlotState.unclear and n not in ROUTING_ONLY]
        for slot in names:
            item = case.slots.get(slot)
            if item is None or item.state != SlotState.unclear or slot in NO_UNCLEAR_LINE:
                continue
            if any(line.slot == slot for line in case.yellow_lines):
                continue
            shown = item.display or self._conservative_display(ctx, slot)
            yellow.unclear(case, slot, shown, ctx.now, heard=item.heard)

    def _conservative_display(self, ctx: Ctx, slot: SlotName) -> str:
        """The value the rules use for an unclear answer without a value: the question plan's conservative default
        for a question-picker slot, $0 for any other amount, else a dash."""
        try:
            plan = self.rules.flip_plan(ctx.case, today=ctx.today, budget=0)
            for cand in list(plan.ask) + list(plan.not_asked):
                if cand.slot == slot:
                    return self._default_display(cand)
        except Exception:  # noqa: BLE001 - the console line never blocks the call
            self.rules_errors += 1
        if SLOT_SPECS[slot].type == "money":
            return format_display(slot, encode_value(slot, Decimal(0))).removesuffix("/mo")
        return "—"

    # ---------------------------------------------------------------------------------------- yes / no and entries

    def answer_yes_no(self, ctx: Ctx, answer: str, *, source: SlotSource) -> Plan:
        """A yes or no (a key, a quick reply or a short answer) to the pending question."""
        s = ctx.session
        pending = s.pending
        assert pending is not None
        ctx.yes_answer = answer
        key = pending.key
        if key in CONSENT_KEYS:
            if answer == "yes":
                return self.consent_given(ctx, None, source=source)
            return self.consent_declined(ctx)
        if key == "delete.confirm_ask":
            if answer == "yes":
                return self._delete_done(ctx)
            s.awaiting = "none"
            return self.resume(ctx, [Step("delete.cancelled")], form="short", skip_pending=True)
        if key == "human.request":
            if answer == "no":
                return self._stop(ctx)
            return self.resume(ctx, [], form="short", skip_pending=True)
        if key == self.routing.close_pending:
            if answer == "no":
                return Plan([Step(self.routing.close_reply)], end_reason="completed")
            return self.close_again(ctx, None, [])
        if key == "confirm.money":
            empty = Understanding(redacted_text="", observations=[], intents=[], lang=ctx.lang,
                                  answered_pending="yes", llm=_skipped())
            plan = self._confirm_answer(ctx, empty, answer)
            return plan if plan is not None else self.unclear(ctx)
        expect = self.bank.expect(key, "closed" if pending.closed else "main", ctx.lang) or {}
        entry = expect.get(answer)
        if entry is None:
            entry = (self.bank.expect(key, "closed", ctx.lang) or {}).get(answer)
        if isinstance(entry, dict):
            return self.apply_entry(ctx, entry, source=source)
        slots = list(pending.slots or (expect.get("slots") or []))
        if len(slots) == 1:
            slot = SlotName(slots[0])
            spec = SLOT_SPECS[slot]
            if spec.type == "bool":
                return self.apply_entry(ctx, {"set": {slot.value: "true" if answer == "yes" else "false"}},
                                        source=source)
            if spec.type == "money":
                if answer == "no":
                    return self.apply_entry(ctx, {"set": {slot.value: "0"}}, source=source)
                return self.apply_entry(ctx, {"note": "amount still needed"}, source=source)
        return self.unclear(ctx)

    def apply_entry(self, ctx: Ctx, entry: dict[str, Any], *, source: SlotSource) -> Plan:
        """A keypad entry or a quick reply: {set} · {band} · {intent} · {answer} · {action} · {note}."""
        s = ctx.session
        pending = s.pending
        if "answer" in entry:
            return self.answer_yes_no(ctx, str(entry["answer"]), source=source)
        if "action" in entry:
            action = entry["action"]
            if action == "resume":
                s.awaiting = "none"
                return self.resume(ctx, [], form="short", skip_pending=True)
            if action == "delete.cancelled":
                s.awaiting = "none"
                return self.resume(ctx, [Step("delete.cancelled")], form="short", skip_pending=True)
            return self.unclear(ctx)
        if "intent" in entry:
            intent = entry["intent"]
            if intent == "stop":
                return self._stop(ctx)
            if intent == "delete_data":
                return self._delete_done(ctx) if s.awaiting == "delete_confirm" else Plan([Step("delete.confirm_ask")])
            if intent == "dont_know" and pending is not None:
                return self._dont_know(ctx)
            return self.unclear(ctx)
        if "note" in entry:
            if pending is not None and pending.key in AMOUNT_FOLLOW_UP:
                follow = AMOUNT_FOLLOW_UP[pending.key]
                return self._question(ctx, [Step("ack.short")], Step(follow),
                                      record="flip" if pending.key.startswith("flip.") else "band")
            if pending is not None and pending.key == "flip.rent_paid_by_others_amount":
                rent = value_of(ctx.case, S.rent_share)
                if rent is not None:
                    self._set(ctx, S.rent_paid_by_others_to_landlord, str(rent), source=source, heard=None,
                              state=SlotState.unclear)
                    yellow.unclear(ctx.case, S.rent_paid_by_others_to_landlord,
                                   format_display(S.rent_paid_by_others_to_landlord, encode_value(
                                       S.rent_paid_by_others_to_landlord, rent)), ctx.now)
                self.refresh(ctx)
                return self.advance(ctx, [], ack=True)
            return self._give_up(ctx)
        if "band" in entry and pending is not None and pending.slots:
            return self._band(ctx, str(entry["band"]), pending, source=source)
        if "set" in entry:
            readback: list[SlotName] = []
            for name, raw in dict(entry["set"]).items():
                slot = SlotName(name)
                if raw == "rent_share":
                    raw = value_of(ctx.case, S.rent_share)
                    if raw is None:
                        continue
                if SLOT_SPECS[slot].type == "money" and slot in machine.READBACK_KEYS:
                    readback.append(slot)
                self._set(ctx, slot, str(raw), source=source, heard=None)
            if pending is not None and pending.key in CONSENT_KEYS:
                return self.consent_given(ctx, None, source=source)
            self.refresh(ctx)
            return self.advance(ctx, self._readback(ctx, readback), ack=True)
        return self.unclear(ctx)

    def _band(self, ctx: Ctx, token: str, pending: PendingQuestion, *, source: SlotSource) -> Plan:
        """A band answer is a range, not a value: its conservative end is used (the end that gives the lower estimate,
        docs/SPEC.md §5.6) and the slot is marked assumed; money bands leave a yellow line for the coordinator."""
        slot = pending.slots[0]
        a, b = self.band_edges(ctx, pending.key)
        x = b
        if token in ("below_x", "above_x"):
            x = a
        income_like = slot in (S.earned_monthly, S.other_cash_monthly, S.cash_on_hand)
        if slot == S.age:
            value = {"below_a": a - 1, "between": a, "above_b": b}.get(token, a)
        elif token == "above_x":  # pay at or above X: the band's top stays the conservative value
            current = value_of(ctx.case, slot)
            value = current if isinstance(current, Decimal) and current > x else x
        elif income_like:
            value = {"below_a": a, "between": b, "above_b": b, "below_x": x}.get(token, b)
        else:  # rent and other costs: the low end is the conservative one
            value = {"below_a": Decimal(0), "between": a, "above_b": b}.get(token, a)
        self._set(ctx, slot, str(value), source=source, heard=None, state=SlotState.assumed)
        if SLOT_SPECS[slot].type == "money":
            item = ctx.case.slots[slot]
            yellow.unclear(ctx.case, slot, item.display or "—", ctx.now)
        self.refresh(ctx)
        return self.advance(ctx, [], ack=True)

    def band_edges(self, ctx: Ctx, key: str) -> tuple[Decimal, Decimal]:
        """Band edges: ask.income_band from the rules table (fractions of the gross limit, rounded),
        flip.other_cash_band from the table's other-cash band, every other band choice from the bank's
        expect.band_edges."""
        voi = self.table.get("voi") or {}
        if key == "ask.income_band":
            band = voi.get("income_band") or {}
            size = household_size(ctx.case)
            limits = self.table.get("gross_limit_200") or {}
            if str(size) in limits:
                limit = Decimal(str(limits[str(size)]))
            else:
                top = max(int(k) for k in limits if k.isdigit())
                limit = Decimal(str(limits[str(top)])) + Decimal(str(limits.get("each_over_8", 0))) * (size - top)
            step = Decimal(str(band.get("round_to_usd", 50)))
            edges = [(Decimal(str(f)) * limit / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
                     for f in band.get("fractions_of_gross_limit") or []]
            if len(edges) == 2:
                return edges[0], edges[1]
            first = band.get("edges_1_person") or [0, 0]
            return Decimal(first[0]), Decimal(first[1])
        if key == "flip.other_cash_band":
            pair = voi.get("other_cash_band_usd") or [0, 0]
            return Decimal(str(pair[0])), Decimal(str(pair[1]))
        if key == "flip.earned_split":
            x = self._earned_split(ctx)
            return x, x
        for form in ("closed", "main"):
            edges = (self.bank.expect(key, form) or {}).get("band_edges")
            if isinstance(edges, dict):
                return Decimal(str(edges["a"])), Decimal(str(edges["b"]))
        return Decimal(0), Decimal(0)

    def _earned_split(self, ctx: Ctx) -> Decimal:
        """The 'less than $X a month?' split for a band of work income: halfway between the band's ends, rounded to
        the table's step (data/rules/ca_fy2027.json voi.income_band split_rule)."""
        hint = getattr(self.rules, "earned_split_point", None)  # the rules module's own split (optional)
        if callable(hint):
            try:
                found = hint(ctx.case, today=ctx.today)
                if found is not None:
                    return Decimal(found)
            except Exception:  # noqa: BLE001 - fall back to the table's halfway rule
                self.rules_errors += 1
        band = (self.table.get("voi") or {}).get("income_band") or {}
        step = Decimal(str(band.get("round_to_usd", 50)))
        a, b = self.band_edges(ctx, "ask.income_band")
        current = value_of(ctx.case, S.earned_monthly)
        lo, hi = (a, b) if current is None or current > a else (Decimal(0), a)
        return ((lo + hi) / 2 / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step

    # ---------------------------------------------------------------------------------------- observations → slots

    @dataclass
    class Applied:
        readback: list[SlotName] = field(default_factory=list)
        confirm: SlotName | None = None
        conflict: tuple[SlotName, Decimal, Decimal] | None = None
        follow_up: bool = False
        status_route: bool = False
        zeroed: set[SlotName] = field(default_factory=set)

    def apply_observations(self, ctx: Ctx, u: Understanding, *, quote: bool = True, confidence: float | None = None,
                           skip: set[SlotName] | None = None) -> Dialogue.Applied:
        """Observations become slots. Money is normalized to monthly by the rules port; several amounts of the same slot
        in one turn are summed; a volunteered status or disability benefit only routes and is never stored."""
        out = Dialogue.Applied()
        case = ctx.case
        if case.consent.given is not True:  # nothing is stored before consent
            return out
        spanish = u.lang == Lang.es or ctx.lang == Lang.es
        grouped: dict[SlotName, list[SlotObservation]] = {}
        for obs in u.observations:
            if skip and obs.slot in skip:
                continue
            grouped.setdefault(obs.slot, []).append(obs)
        for slot, observations in grouped.items():
            obs = observations[0]
            if slot in ROUTING_ONLY:
                if self._route_only(ctx, slot, obs):
                    out.status_route = True
                continue
            spec = SLOT_SPECS[slot]
            state = SlotState.clear if all(o.state == "clear" for o in observations) else SlotState.unclear
            basis: MoneyBasis | None = None
            if spec.type == "money":
                raw = obs.value.strip().lower()
                if raw in ("true", "yes"):
                    out.follow_up = True
                    continue
                try:
                    if len(observations) > 1 and state == SlotState.unclear and slot in CRITICAL:
                        values = [self._money_value(ctx, o, slot) for o in observations]
                        if len(set(values)) > 1:
                            out.conflict = (slot, values[0], values[1])
                        amount = values[0]
                    elif len(observations) > 1:
                        amount = sum((self._money_value(ctx, o, slot) for o in observations), Decimal(0))
                    else:
                        amount = self._money_value(ctx, obs, slot)
                        basis = self._basis(obs, slot)
                except (InvalidOperation, ValueError):
                    continue
                if basis is not None and basis.period == "month" and len(observations) == 1:
                    basis = None if spec.periodic and obs.period in (None, "month") else basis
                value: Any = amount
            else:
                value = obs.value
            try:
                canonical = encode_value(slot, value)
                out_of_range = False
            except (TypeError, ValueError):
                if spec.type != "money":
                    continue
                canonical, out_of_range = None, True
            band = self._band_pending(ctx, slot)
            if band and state == SlotState.unclear:  # a range answer: its conservative end, assumed, never confirmed
                state = SlotState.assumed
            needs_confirm = not band and slot in CRITICAL and (
                state == SlotState.unclear or out_of_range or slot in u.teen_ty
                or (confidence is not None and confidence < LOW_CONFIDENCE))
            current = case.slots.get(slot)
            if needs_confirm and ctx.session.confirms.get(slot, 0) >= 1:
                # the slot's one explicit confirm is used (docs/SPEC.md §3.4)
                needs_confirm = False
                said_again = current is not None and current.confirmed and canonical is not None \
                    and current.value == canonical and all(o.state == "clear" for o in observations)
                # the confirmed amount said again (a teen word again) stays confirmed; anything else stays unclear
                state = SlotState.clear if said_again else SlotState.unclear
            if canonical is None:
                if needs_confirm:  # out of the plausible range and no value to repeat back: ask again instead
                    continue
                continue
            new_value = current is None or current.value != canonical
            # A known critical amount set to $0 by an answer to another question ("No, no rent help from anybody" to
            # the landlord question, "my mom is not working" said about a parent) is never applied silently: it is
            # read back with its $0 and a yellow line asks a person to check it (docs/SPEC.md §3.3 corrections, §3.4).
            zeroed = spec.type == "money" and slot in CRITICAL and new_value and canonical is not None \
                and current is not None and current.value is not None and _is_zero(canonical) \
                and not _is_zero(current.value) and not self._pending_asks(ctx, slot)
            old_display = (current.display or format_display(slot, current.value, current.basis)) if zeroed \
                and current is not None else None
            heard = obs.quote[:80] if quote and obs.quote else None
            heard_en = obs.quote_en[:120] if quote and spanish and obs.quote_en else None
            source = u.sources.get(slot, SlotSource.llm)
            self._set(ctx, slot, canonical, source=source, heard=heard, heard_en=heard_en,
                      state=SlotState.unclear if needs_confirm else state, basis=basis)
            if zeroed and old_display is not None:
                item = case.slots[slot]
                new_display = item.display or format_display(slot, canonical)
                yellow.conflict(case, slot, old_display.removesuffix("/mo"), new_display.removesuffix("/mo"), ctx.now,
                                heard=heard)
                out.zeroed.add(slot)
                if slot in machine.READBACK_KEYS:
                    out.readback.append(slot)
            elif band and state == SlotState.assumed and spec.type == "money":
                item = case.slots[slot]
                yellow.unclear(case, slot, item.display or "—", ctx.now, heard=heard)
            elif needs_confirm and out.confirm is None:
                out.confirm = slot
            elif state == SlotState.unclear and slot in CRITICAL and ctx.session.confirms.get(slot, 0) >= 1:
                item = case.slots[slot]
                if out.conflict is not None and out.conflict[0] == slot:
                    a, b = (format_display(slot, encode_value(slot, v)).removesuffix("/mo") for v in out.conflict[1:])
                    yellow.conflict(case, slot, a, b, ctx.now, heard=heard)
                else:
                    yellow.unclear(case, slot, item.display or "—", ctx.now, heard=heard, update=new_value)
                if new_value and slot in machine.READBACK_KEYS:
                    # a new amount after the slot's one confirm (a teen-word correction of a confirmed amount): no
                    # second confirm, but never applied silently — the new value is read back so the student hears
                    # it and can correct it (docs/SPEC.md §3.3 corrections, §3.4), and the line asks a person to check
                    out.readback.append(slot)
            elif slot in machine.READBACK_KEYS and state == SlotState.clear:
                out.readback.append(slot)
        return out

    def _pending_asks(self, ctx: Ctx, slot: SlotName) -> bool:
        """Does the pending question ask this slot (its own answer, or its confirm)?"""
        pending = ctx.session.pending
        return pending is not None and slot in pending.slots

    def _yes_no_band(self, ctx: Ctx, pending: PendingQuestion) -> bool:
        """A yes/no question whose answers are parts of a band (flip.earned_split)."""
        expect = self.bank.expect(pending.key, "closed" if pending.closed else "main", ctx.lang) or {}
        return any(isinstance(expect.get(k), dict) and "band" in expect[k] for k in ("yes", "no"))

    def _band_pending(self, ctx: Ctx, slot: SlotName) -> bool:
        """Is the pending question a band choice for this slot (ask.income_band, the band flips, or a closed form whose
        answers are bands)?"""
        pending = ctx.session.pending
        if pending is None or slot not in pending.slots:
            return False
        if pending.key in BAND_QUESTIONS:
            return True
        if pending.closed:
            expect = self.bank.expect(pending.key, "closed") or {}
            keypad = expect.get("keypad")
            return isinstance(keypad, dict) and any("band" in entry for entry in keypad.values())
        return False

    def _money_value(self, ctx: Ctx, obs: SlotObservation, slot: SlotName) -> Decimal:
        raw = obs.value.strip().lower()
        if raw in ("false", "no", "none"):
            return Decimal(0)
        if raw == "rent_share":
            rent = value_of(ctx.case, S.rent_share)
            if rent is None:
                raise ValueError("rent share unknown")
            return Decimal(rent)
        amount = Decimal(raw.replace(",", "").replace("$", ""))
        basis = self._basis(obs, slot)
        if basis is None:
            return amount
        return Decimal(self.rules.normalize_money(basis))

    @staticmethod
    def _basis(obs: SlotObservation, slot: SlotName) -> MoneyBasis | None:
        spec = SLOT_SPECS[slot]
        if not spec.periodic:
            return None
        raw = obs.value.strip().lower().replace(",", "").replace("$", "")
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            return None
        period = obs.period or "month"
        if period == "once":
            period = "month"
        hours = Decimal(str(obs.hours_per_week)) if obs.hours_per_week is not None else None
        return MoneyBasis(amount=amount, period=period, hours_per_week=hours if period == "hour" else None)

    def _route_only(self, ctx: Ctx, slot: SlotName, obs: SlotObservation) -> bool:
        """A volunteered status or disability benefit picks a route; the value and the quote are never stored."""
        case = ctx.case
        if slot == S.volunteered_status:
            if obs.value in self.status_other_help:
                case.route_override = "other_help.status"
                return True
            if obs.value in self.status_coordinator:
                if case.route_override != "other_help.status":
                    case.route_override = "coordinator.status_complex"
                return True
            return False
        if slot == S.elderly_or_disabled and obs.value.strip().lower() == "true":
            if case.route_override is None:
                case.route_override = "coordinator.elderly_disabled"
            return True
        return False

    def _set(self, ctx: Ctx, slot: SlotName, raw: str, *, source: SlotSource, heard: str | None,
             heard_en: str | None = None, state: SlotState = SlotState.clear, basis: MoneyBasis | None = None) -> None:
        if slot in ROUTING_ONLY:
            return
        case = ctx.case
        canonical = encode_value(slot, raw) if not _is_canonical(slot, raw) else raw
        old = case.slots.get(slot)
        changed_from = old.changed_from if old is not None else None
        confirmed = False
        if old is not None and old.value is not None:
            if old.value != canonical:
                changed_from = old.value
            else:
                confirmed = old.confirmed
                heard = heard or old.heard
                heard_en = heard_en or old.heard_en
        case.slots[slot] = Slot(value=canonical, display=format_display(slot, canonical, basis), state=state,
                                heard=heard, heard_en=heard_en, confirmed=confirmed, changed_from=changed_from,
                                turn=ctx.turn, source=source, basis=basis, updated_at=ctx.now)
        if old is None or old.value != canonical or old.state != state:
            if slot not in ctx.changed:
                ctx.changed.append(slot)

    def _readback(self, ctx: Ctx, slots: list[SlotName], *, zero: set[SlotName] | None = None) -> list[Step]:
        """One implicit read-back of a money answer (never of cash on hand; a zero only when a known amount was set to
        $0 by an answer to another question, `zero`)."""
        for slot in (S.earned_monthly, S.other_cash_monthly, S.rent_share):
            if slot not in slots:
                continue
            value = value_of(ctx.case, slot)
            if value is None or (value == 0 and slot not in (zero or set())):
                continue
            item = ctx.case.slots[slot]
            if slot == S.earned_monthly and item.basis is not None and item.basis.period == "hour":
                return [Step("readback.hourly")]
            return [Step(machine.READBACK_KEYS[slot])]
        return []

    # ======================================================================================== the rules

    def refresh(self, ctx: Ctx) -> None:
        """Re-run the rules on the case (tier, estimate, range, trace, yellow lines) and keep the routes the
        conversation itself decided (an info route)."""
        case = ctx.case
        if case.consent.given is not True:
            return
        case.phase = ctx.session.phase  # the rules read the phase (an amount is final once the call is past the flips)
        try:
            updated = self.rules.apply(case, now=ctx.now, turn=ctx.turn if ctx.changed else None)
        except Exception:  # noqa: BLE001 - the call goes on with the last result; INT sees the counter
            self.rules_errors += 1
            return
        if updated is not case:
            for name in type(case).model_fields:
                setattr(case, name, getattr(updated, name))
        for slot, code in machine.INFO_ROUTES.items():
            if value_of(case, slot) is True and case.route_override is None:
                case.reason_code = code
                case.estimate_monthly = None
                case.estimate_is_floor = False
                break

    def expedited_screen(self, ctx: Ctx) -> bool:
        """Ask the cash question when the screen applies in any remaining world of the utility bills the student has not
        answered (docs/SPEC.md §5.8): the rules port evaluates each world."""
        try:
            return any(ev.expedited_screen for ev in self._worlds(ctx))
        except Exception:  # noqa: BLE001 - a rules failure never blocks the call; the cash question is skipped
            return False

    def expedited_outlook(self, ctx: Ctx) -> str | None:
        """yes / maybe / no over the remaining worlds (FlipPlan.expedited_outlook when the rules port gives one)."""
        case = ctx.case
        outlook = None
        try:
            plan = self.rules.flip_plan(case, today=ctx.today, budget=0)
            outlook = plan.expedited_outlook
        except Exception:  # noqa: BLE001
            outlook = None
        if outlook is None:
            try:
                flags = [ev.expedited for ev in self._worlds(ctx) if ev.expedited is not None]
            except Exception:  # noqa: BLE001
                flags = []
            if flags:
                outlook = "yes" if all(flags) else "maybe" if any(flags) else "no"
        if outlook is not None:
            case.expedited_possible = outlook
        return outlook

    def _worlds(self, ctx: Ctx) -> list[Any]:
        case = ctx.case
        facts = self.rules.facts_from_case(case, today=ctx.today)
        worlds = [facts]
        if value_of(case, S.homeless) is not True:
            utilities = []
            if not known(case, S.heat_cool):
                utilities.append("heat_cool")
            if not known(case, S.other_utils) and value_of(case, S.heat_cool) is not True:
                utilities += ["two_other", "phone_only"]
            for utility in utilities:
                if utility != facts.utility:
                    worlds.append(facts.model_copy(update={"utility": utility}))
        return [self.rules.evaluate(w, today=ctx.today) for w in worlds]

    # ======================================================================================== the phase machine

    def advance(self, ctx: Ctx, lead: list[Step], *, ack: bool, drop: bool = False, form: str = "main") -> Plan:
        """Walk the phases from the current one: ask the next open question, or give the result, the card and close
        lines (chained when nothing is asked between them)."""
        s, case = ctx.session, ctx.case
        if s.phase in machine.BEFORE_RESULT and s.phase != Phase.consent:
            if case.reason_code in machine.ANYTIME_ROUTES or case.route_override is not None:
                s.phase = Phase.result
            elif s.turn_count >= TURN_CAP or ctx.now - s.started_at >= TIME_CAP:
                if "turn_cap" not in case.flags:
                    case.flags.append("turn_cap")
                s.phase = Phase.result
        steps = list(lead)
        while True:
            phase = s.phase
            if phase in PHASES:
                if self._hard_stop(ctx, phase, earlier=True):  # an earlier phase's route, settled late
                    s.phase = Phase.result
                    continue
                question = self._late_question(ctx, phase) or self.question_for(ctx, phase)
                if question is not None:
                    if ack and not steps:
                        steps.append(Step("ack.short"))
                    question.form = form
                    return self._question(ctx, steps, question, record="standard", drop=drop)
                if self._hard_stop(ctx, phase):
                    s.phase = Phase.result
                else:
                    s.phase = QUESTION_PHASES[QUESTION_PHASES.index(phase) + 1] \
                        if phase != Phase.housing else Phase.flip
                continue
            if phase == Phase.flip:
                again = self._open_flip(ctx)
                if again is not None:  # asked, then a detour or a correction: the same flip again, not a new one
                    if ack and not steps:
                        steps.append(Step("ack.short"))
                    again.form = form
                    return self._question(ctx, steps, again, record="reprompt", drop=drop)
                late = self._late_question(ctx, phase)
                if late is not None:  # a question phase's question that became needed only now (before the result)
                    if ack and not steps:
                        steps.append(Step("ack.short"))
                    late.form = form
                    return self._question(ctx, steps, late, record="standard", drop=drop)
                plan = self._flip(ctx, steps, ack=ack, drop=drop)
                if plan is not None:
                    return plan
                s.phase = Phase.result
                continue
            if phase == Phase.result:
                self.refresh(ctx)  # the result phase: the rules give their final answer (leftovers, floor, routes)
                self.unclear_lines(ctx)
                steps += self.result_steps(ctx)
                if self._cash_question_applies(ctx):
                    s.phase = Phase.expedited
                    if not known(case, S.cash_on_hand):
                        return self._question(ctx, steps, Step("expedited.intro_cash"), record="standard", drop=drop)
                    continue  # cash said earlier: the outlook follows without the question
                s.phase = Phase.card
                continue
            if phase == Phase.expedited:
                if not known(case, S.cash_on_hand) and self._cash_question_applies(ctx):
                    # a correction or a detour came instead of the cash answer: ask it again
                    if ack and not steps:
                        steps.append(Step("ack.short"))
                    return self._question(ctx, steps, Step("expedited.intro_cash", form), record="reprompt",
                                          drop=drop)
                outlook = self.expedited_outlook(ctx) if known(case, S.cash_on_hand) else None
                if outlook == "yes":
                    steps.append(Step("expedited.yes"))
                elif outlook == "maybe":
                    steps.append(Step("expedited.maybe"))
                s.phase = Phase.card
                continue
            if phase == Phase.card:
                steps += self.card_steps(ctx)
                s.phase = Phase.close
                continue
            if phase == Phase.close:
                steps.append(Step("close.anything_else"))
                return Plan(steps, drop_from_memory=drop)
            if phase == Phase.consent:
                ctx.session.awaiting = "consent"
                return Plan(steps + [Step("consent.reask")])
            return Plan(steps, drop_from_memory=drop)  # the end: nothing to ask

    def _cash_question_applies(self, ctx: Ctx) -> bool:
        """docs/SPEC.md §3.2 phase 8: a likely amount and the expedited screen applies in a remaining world."""
        case = ctx.case
        return case.tier == Tier.likely and case.reason_code == "likely" and self.expedited_screen(ctx)

    def _open_flip(self, ctx: Ctx) -> Step | None:
        """The last case question when it is a flip that the student has not answered at all (a detour or another
        answer came instead). Each slot is a flip question only once (docs/SPEC.md §5.6), so it is asked again here
        instead of being planned again or left at its default."""
        case = ctx.case
        if not case.asked:
            return None
        last = case.asked[-1]
        if not last.key.startswith("flip.") or last.key == "flip.intro" or not last.slots:
            return None
        if any(self._answered_since(case, slot, last.turn) for slot in last.slots):
            return None
        vars_: dict[str, Any] = {}
        if last.key == "flip.earned_split":
            vars_["x"] = self._earned_split(ctx)
        return Step(last.key, vars=vars_)

    @staticmethod
    def _answered_since(case: Case, slot: SlotName, turn: int) -> bool:
        """Did an answer reach the slot after the question was asked in `turn`? (A flip may be asked about an
        unclear answer, so an earlier value does not count.)"""
        item = case.slots.get(slot)
        if item is None or (item.value is None and item.state == SlotState.missing):
            return False
        return item.turn is None or item.turn > turn

    def _detoured(self, ctx: Ctx, form: str) -> Step | None:
        """The case question that was open when a detour began (keep going, delete cancelled, crisis): the last entry
        of Case.asked while it is still unanswered. Detour questions are never case questions, so the last entry is
        the question the student had not answered yet."""
        case = ctx.case
        if not case.asked:
            return None
        last = case.asked[-1]
        if last.key.startswith("flip."):
            step = self._open_flip(ctx)
        elif last.key == "confirm.money":
            slot = last.slots[0] if last.slots else None
            item = case.slots.get(slot) if slot is not None else None
            open_ = item is not None and not item.confirmed and item.state == SlotState.unclear \
                and not any(line.slot == slot for line in case.yellow_lines)
            step = Step(last.key, vars={"slot": slot.value}) if open_ and slot is not None else None
        elif last.slots and not any(known(case, slot) for slot in last.slots):
            step = Step(last.key)
        else:
            step = None
        if step is not None:
            step.form = "closed" if last.kind == "closed" and self._has_closed(last.key) else form
            if ctx.session.closed_mode and self._has_closed(last.key):
                step.form = "closed"
        return step

    def question_for(self, ctx: Ctx, phase: Phase) -> Step | None:
        """The next open question of a question phase, or None when its goals are known (said earlier counts)."""
        case = ctx.case
        if phase == Phase.student:
            if not known(case, S.level):
                return Step("ask.level_units")
            level = value_of(case, S.level)
            if level == "undergrad" and not known(case, S.units) and not known(case, S.half_time):
                return Step("ask.units")
            if level == "grad" and not known(case, S.grad_exemption):
                return Step("ask.grad_exemption")
            return None
        if phase == Phase.age_home:
            if not known(case, S.age):
                return Step("ask.age_parent")
            if not known(case, S.lives_with_parent) and not ctx.session.closed_mode:
                return Step("ask.age_parent")  # the closed form asks the age only
            if value_of(case, S.dorm_on_campus) is True and not known(case, S.meals_per_week) \
                    and not known(case, S.dorm_meals_over_10):
                return Step("ask.meal_plan")
            return None
        if phase == Phase.household:
            if not known(case, S.household_food):
                return Step("ask.household_food_roommates" if value_of(case, S.roommates) is True else "ask.household")
            return None
        if phase == Phase.income:
            if not known(case, S.earned_monthly):
                return Step("ask.income")
            if not known(case, S.other_cash_monthly):
                return Step("ask.other_cash")
            return None
        if phase == Phase.housing:
            if value_of(case, S.homeless) is True:
                return None if known(case, S.homeless_shelter_cost_monthly) else Step("ask.homeless_cost")
            return None if known(case, S.rent_share) else Step("ask.rent")
        return None

    def _late_question(self, ctx: Ctx, phase: Phase) -> Step | None:
        """A question of an earlier question phase that became needed only after the call moved past that phase: on-
        campus housing said in a later answer ("I live alone in the dorm" to the household question) still gets
        ask.meal_plan before the result, because more than ten meals a week changes the route (docs/SPEC.md §3.2
        phase 2, §4.3 row 3.12). Phases are passed only once their questions are answered, so only a new fact (on-campus
        housing, a corrected level) opens one again."""
        end = QUESTION_PHASES.index(phase) if phase in QUESTION_PHASES else len(QUESTION_PHASES)
        for earlier in QUESTION_PHASES[:end]:
            question = self.question_for(ctx, earlier)
            if question is not None:
                return question
        return None

    def _hard_stop(self, ctx: Ctx, phase: Phase, *, earlier: bool = False) -> bool:
        """A phase's own routes end the conversation once its goals are known and clear (an unclear goal is decided by
        the question plan later). With `earlier`, only the routes of the phases before `phase` count (a route that
        an answer given later settles: a late meal-plan answer of more than ten meals a week goes straight to the
        result, docs/SPEC.md §3.2)."""
        case = ctx.case

        def unsure(slot: SlotName) -> bool:
            # an unclear answer, or a band answer (a range) for a slot the question plan can still narrow down
            item = case.slots.get(slot)
            return item is not None and (item.state == SlotState.unclear
                                         or (item.state == SlotState.assumed and slot in FLIP_KEYS))

        def settled(p: Phase) -> bool:
            return not any(unsure(g) for g in PHASES[p].goals)

        if not earlier and not settled(phase):
            return False
        codes: set[str] = set()
        for p in QUESTION_PHASES[: QUESTION_PHASES.index(phase) + (0 if earlier else 1)]:
            if settled(p):
                codes |= set(PHASES[p].hard_stops)
        return case.reason_code in codes

    def _flip(self, ctx: Ctx, lead: list[Step], *, ack: bool, drop: bool) -> Plan | None:
        """VoI: ask the rules port's next flip question while the budget allows (docs/SPEC.md §5.6)."""
        s, case = ctx.session, ctx.case
        budget = max(self.max_flips - s.flips_asked, 0)
        try:
            plan = self.rules.flip_plan(case, today=ctx.today, budget=budget)
        except Exception:  # noqa: BLE001 - no plan: give the result with the defaults
            return None
        if plan.estimate_range is not None and case.estimate_range is None:
            case.estimate_range = plan.estimate_range
        candidates = [c for c in plan.ask if c.slot in FLIP_KEYS and self._open_for_flip(case, c.slot)]
        if budget > 0 and candidates:
            cand = candidates[0]
            key = FLIP_KEYS[cand.slot]
            vars_: dict[str, Any] = {}
            if key == "flip.earned_split":
                vars_["x"] = self._earned_split(ctx)
            question = Step(key, vars=vars_)
            steps = list(lead)
            if ack and not steps:
                steps.append(Step("ack.short"))
            if s.flips_asked == 0:
                steps.append(Step("flip.intro"))
            s.flips_asked += 1
            out = self._question(ctx, steps, question, record="flip", drop=drop)
            out.flip = cand
            return out
        self._record_skipped(ctx, plan.not_asked)
        return None

    @staticmethod
    def _open_for_flip(case: Case, slot: SlotName) -> bool:
        """A VoI slot the plan may ask: never answered, or answered unclearly (the plan decides, docs/SPEC.md §5.6)."""
        item = case.slots.get(slot)
        # a band answer (assumed) is a range too: the plan may narrow it (flip.earned_split, flip.other_cash_band)
        return item is None or item.state in (SlotState.missing, SlotState.unclear, SlotState.assumed)

    def _record_skipped(self, ctx: Ctx, not_asked: list[FlipCandidate]) -> None:
        """Not-asked VoI candidates as SkippedQuestion entries, one per slot (docs/UI_SPEC.md A3.10)."""
        case = ctx.case
        for cand in not_asked:
            if known(case, cand.slot) and case.slots[cand.slot].source != SlotSource.default:
                continue
            if any(e.slot == cand.slot for e in case.skipped):  # the rules port wrote it already
                continue
            values = sorted({o.monthly for o in cand.outcomes if o.monthly is not None})
            short = SLOT_SPECS[cand.slot].short
            if cand.decision == "no_effect" or (cand.spread_usd == 0 and not cand.tier_changes):
                entry = SkippedQuestion(slot=cand.slot, reason="no_effect",
                                        detail=console_text.skip_detail_no_effect(short), values=values)
            elif cand.decision in ("assume_default", "assume_conservative") and not cand.tier_changes \
                    and cand.spread_usd <= int((self.table.get("voi") or {}).get("flip_threshold_usd", 50)):
                assumed = self._default_display(cand)
                entry = SkippedQuestion(slot=cand.slot, reason="below_threshold",
                                        detail=console_text.skip_detail_below_threshold(assumed), values=values)
            else:
                entry = SkippedQuestion(slot=cand.slot, reason="max_questions",
                                        detail=console_text.skip_detail_max_questions(), values=values)
            case.skipped = [e for e in case.skipped if e.slot != cand.slot] + [entry]

    @staticmethod
    def _default_display(cand: FlipCandidate) -> str:
        raw = cand.default_value
        spec = SLOT_SPECS[cand.slot]
        try:
            if spec.type == "money":
                return format_display(cand.slot, encode_value(cand.slot, Decimal(raw))).removesuffix("/mo")
            return format_display(cand.slot, encode_value(cand.slot, raw))
        except (TypeError, ValueError, InvalidOperation):
            return raw

    def result_steps(self, ctx: Ctx) -> list[Step]:
        case = ctx.case
        code = case.reason_code
        if case.tier == Tier.likely and code == "likely" and case.estimate_monthly is not None:
            steps = [Step("result.likely_floor" if case.estimate_is_floor else "result.likely")]
            if any(line.code == "abawd_possible" for line in case.yellow_lines):
                steps.append(Step("result.note.abawd"))
            return steps
        if code and self.bank.has(f"result.{code}"):
            return [Step(f"result.{code}")]
        if code and code.startswith("other_help."):
            return [Step("result.other_help.generic")]
        return [Step("result.coordinator.generic")]

    def card_steps(self, ctx: Ctx) -> list[Step]:
        """Apply-today for likely and every coordinator route except parent_household (never for other help or the info
        routes), then the card line (docs/SPEC.md §3.2 phase 9)."""
        case = ctx.case
        code = case.reason_code or ""
        steps: list[Step] = []
        likely = case.tier == Tier.likely and code == "likely"
        if likely or (code.startswith("coordinator.") and code != "coordinator.parent_household"):
            steps.append(Step("first_month.apply_today"))
        self.ensure_card(ctx)
        if ctx.channel == Channel.web:
            steps.append(Step("card.web"))
        elif getattr(ctx.settings, "card_delivery", "code") == "screen":
            steps.append(Step("card.phone_screen"))
        else:
            steps.append(Step("card.phone_code"))
        return steps

    def ensure_card(self, ctx: Ctx) -> CardRef:
        case = ctx.case
        if case.card is not None:
            return case.card
        token = self.ids.card_token()
        code = None
        expires_code = None
        if ctx.channel == Channel.phone:
            for _ in range(20):
                code = self.ids.short_code()
                try:
                    taken = self.cases.get_by_short_code(code, now=ctx.now)
                except Exception:  # noqa: BLE001 - a lookup failure never blocks the card
                    taken = None
                if taken is None or taken.id == case.id:
                    break
            expires_code = ctx.now + timedelta(hours=int(getattr(ctx.settings, "short_code_ttl_h", 24)))
        case.card = CardRef(token=token, short_code=code, short_code_expires_at=expires_code, created_at=ctx.now,
                            expires_at=ctx.now + timedelta(days=int(getattr(ctx.settings, "card_ttl_days", 7))))
        return case.card

    def close_again(self, ctx: Ctx, u: Understanding | None, lead: list[Step], *, hold: bool = False,
                    done: bool = False, plain: bool = True) -> Plan:
        """Something else at the close: answer it, then ask again (at most two loops), then goodbye. With `hold` the
        utterance also held a hold phrase: when it changes nothing, the line waits instead. With `done` the utterance
        was a done phrase ("nothing else", "no thanks"): when it changes nothing, goodbye; when it carried a correction
        or a volunteered status, that is answered (read back, the result again) and the close question comes again,
        so the student hears the new value or route before the call ends. A done phrase that said more than a plain
        closing (`plain` False: "No thanks, so I still need to bring my lease, right") and was not understood is never a
        goodbye at once: the close question comes again (at most two loops), so a question said without a question
        mark does not end the call. A value said again as it is ("No thanks, my rent is eleven hundred like I said")
        was understood and changes nothing: goodbye."""
        s = ctx.session
        news = False
        if u is not None and u.observations:
            # a correction after the result: the rules run again, the value is read back, and a changed result is
            # said again (docs/SPEC.md §3.3: corrections apply at any time)
            applied = self.apply_observations(ctx, u)
            if applied.confirm is not None:  # a risky new amount gets its one explicit confirm first
                slot = applied.confirm
                s.confirms[slot] = s.confirms.get(slot, 0) + 1
                self.refresh(ctx)
                return self._question(ctx, [], Step("confirm.money", vars={"slot": slot.value}), record="confirm",
                                      pending_slots=[slot])
            if ctx.changed or applied.status_route:
                news = True
                self.refresh(ctx)
                lead = lead + self._readback(ctx, applied.readback, zero=applied.zeroed) + self._result_again(ctx)
            elif hold:
                self.refresh(ctx)
                return self._hold()
        understood = u is not None and bool(u.observations)  # what came with it was read: a value said again
        if done and not news and (plain or understood):
            return Plan(lead + [Step(self.routing.close_reply)], end_reason="completed")
        s.close_loops += 1
        if s.close_loops > MAX_CLOSE_LOOPS:
            return Plan(lead + [Step(self.routing.close_reply)], end_reason="completed")
        s.phase = Phase.close
        return Plan(lead + [Step("close.anything_else", "short" if lead else "main")])

    # ======================================================================================== questions

    def _question(self, ctx: Ctx, lead: list[Step], question: Step, *, record: str | None, drop: bool = False,
                  pending_slots: list[SlotName] | None = None) -> Plan:
        """A reply that ends with a question. In closed mode (the language model failed twice) every question that
        has a closed form is asked in it, with its single-key options on the phone."""
        if ctx.session.closed_mode and self._has_closed(question.key):
            question.form = "closed"
        if pending_slots is not None:
            question.vars.setdefault("slot", pending_slots[0].value)
        return Plan(lead + [question], record=record, drop_from_memory=drop)

    def _has_closed(self, key: str) -> bool:
        return isinstance(self.bank.message(key).get("closed"), dict)

    def resume(self, ctx: Ctx, lead: list[Step], *, form: str, skip_pending: bool = False) -> Plan:
        """The pending question again after another line (short form), or the next question when it was answered.
        With skip_pending the detour question (keep going, delete, a person) is over: the case question it
        interrupted is asked again while still unanswered (a flip or the cash question is never left at a default),
        else the next question is planned."""
        if skip_pending:
            ctx.session.awaiting = "none"
            if ctx.session.pending is None or ctx.session.pending.key in DETOUR_KEYS:
                ctx.session.pending = None
                again = self._detoured(ctx, form)  # the question the detour interrupted, never a default
                if again is not None:
                    return Plan(lead + [again], record=self._reask_kind(ctx, again))
        else:
            question = self._pending_step(ctx, form)
            if question is not None:
                return Plan(lead + [question])
        if ctx.session.phase == Phase.close:
            return self.close_again(ctx, None, lead)
        return self.advance(ctx, lead, ack=False, form=form)

    def _pending_open(self, ctx: Ctx) -> bool:
        s, case = ctx.session, ctx.case
        pending = s.pending
        if pending is None:
            return False
        if pending.key in CONSENT_KEYS:
            return s.phase == Phase.consent
        if pending.key in DETOUR_KEYS or pending.key == self.routing.close_pending:
            return True
        if pending.key == "confirm.money":
            return bool(pending.slots) and not (case.slots.get(pending.slots[0]) or Slot()).confirmed
        slots = [SlotName(x) for x in pending.slots]
        if slots and pending.key.startswith("flip."):
            # a flip may be asked about an unclear or band answer: open until an answer arrives after it was asked
            asked = next((a.turn for a in reversed(case.asked) if a.key == pending.key), None)
            if asked is not None:
                return not any(self._answered_since(case, slot, asked) for slot in slots)
        return bool(slots) and all(not known(case, slot) for slot in slots)

    def _pending_step(self, ctx: Ctx, form: str) -> Step | None:
        """The pending question as a step in a form, or None when there is no open pending question."""
        pending = ctx.session.pending
        if pending is None or not self._pending_open(ctx):
            return None
        vars_: dict[str, Any] = {}
        if pending.key == "confirm.money" and pending.slots:
            vars_["slot"] = pending.slots[0].value
        if pending.key == "flip.earned_split":
            vars_["x"] = self._earned_split(ctx)
        if (pending.closed or ctx.session.closed_mode) and form == "main" and self._has_closed(pending.key):
            form = "closed"
        return Step(pending.key, form, vars=vars_)

    def _next_question_step(self, ctx: Ctx, form: str) -> Step | None:
        s = ctx.session
        if s.phase in PHASES:
            question = self.question_for(ctx, s.phase)
            if question is not None:
                question.form = form
            return question
        return None

    def _reask_kind(self, ctx: Ctx, question: Step) -> str | None:
        if not question.key.startswith(machine.CASE_QUESTION_PREFIXES):
            return None
        return "closed" if question.form == "closed" else "reprompt"


def _is_zero(raw: str) -> bool:
    try:
        return Decimal(str(raw).replace(",", "").replace("$", "")) == 0
    except InvalidOperation:
        return False


def _is_canonical(slot: SlotName, raw: str) -> bool:
    try:
        return encode_value(slot, raw) == raw
    except (TypeError, ValueError):
        return False


def _skipped():
    from gatorplate.contracts.extraction import ExtractOutcome

    return ExtractOutcome(status="skipped")

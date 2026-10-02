"""Age and home in one sentence, the answer to "How old are you, and who do you live with?" (docs/SPEC.md §3.2,
phase 2 age_home; §3.9 Maria turn 3).

A live model often returns the age and the roommates of "I'm 20, and I live with two roommates." but leaves out
lives_with_parent. The rules behind these checks:
- The rule parser reads who the student lives with whenever the pending question asks lives_with_parent: roommates,
  friends, other students, a partner, a dorm, a couch or living alone, with no parent, family or guardian named, is
  "not with a parent"; a parent or step-parent is "with a parent".
- Merge fills a pending slot the model left out from the parser's reading (source parser) and then reports the
  question as answered once every slot it asks is in hand; a slot the model reported (another value, or unclear) is
  never replaced, and a disagreement stays unclear.
- A count before people ("two other students", "three other people", "two of us") is never money, and renting a place
  ("I rent a room with two other students") is not a rent amount.
- A parent named at home beside the others ("I live with my wife and my parents") is never "not with a parent"
  (docs/SPEC.md §4.3 item 3.5: no exceptions); asked, a parent said plainly ("20, my parents") is "with a parent".
- Only the home today counts: a negated, past, future, work or school phrase ("I don't live alone", "I used to live in
  the dorms", "I work at the dorms", "trabajo con compañeros") says nothing about it.
Each sentence runs through the parser alone (the path of a model timeout, closed mode and the fake model), through
merge with a model result that omits lives_with_parent, and through merge with a model result that contradicts it.
"""

from __future__ import annotations

from typing import Any

import pytest

from gatorplate.contracts.common import Lang, SlotSource
from gatorplate.contracts.extraction import ExtractionResult, ExtractOutcome, PendingQuestion, SlotObservation
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.llm.fake import FakeLLM
from gatorplate.extract.merge import Merger
from gatorplate.extract.parser import Parsed, Parser
from gatorplate.extract.text import guess_lang, normalize

S = SlotName
AGE = PendingQuestion(key="ask.age_parent", slots=[S.age, S.lives_with_parent], kind="open")
AGE_CLOSED = PendingQuestion(key="ask.age_parent", slots=[S.age], kind="choice", closed=True)
HOUSEHOLD = PendingQuestion(key="ask.household", slots=[S.household_food, S.lives_with_parent, S.roommates,
                                                       S.spouse, S.children_count], kind="open")
RENT = PendingQuestion(key="ask.rent", slots=[S.rent_share], kind="number")
INCOME = PendingQuestion(key="ask.income", slots=[S.earned_monthly, S.other_cash_monthly], kind="number")
MARIA_SO_FAR = {S.consent: "true", S.level: "undergrad", S.units: "12"}

# (sentence, age, lives_with_parent) — the reported failures first, then fresh one-sentence answers.
CASES: list[tuple[str, str, str]] = [
    ("I'm 20, and I live with two roommates.", "20", "false"),
    ("20, two roommates", "20", "false"),
    ("I'm 20 and I rent a room with two other students.", "20", "false"),
    ("I'm 20 and live in an apartment with friends.", "20", "false"),
    ("I'm 21 and I share a house with three other people.", "21", "false"),
    ("Nineteen, and I live with my parents and my little brother.", "19", "true"),
    ("I'm 22, I live with my girlfriend.", "22", "false"),
    ("I'm 20, I'm on my own.", "20", "false"),
    ("Twenty-one. Just me, by myself.", "21", "false"),
    ("I'm 19 and I live in a dorm on campus.", "19", "false"),
    ("I'm 20 and I still live with my mom and stepdad.", "20", "true"),
    ("I'm 20 and I live with a couple of friends from class.", "20", "false"),
    ("Twenty, and I'm living with my boyfriend and his roommate.", "20", "false"),
    ("I'm 22, I rent a room in a house with four other guys.", "22", "false"),
    ("I'm 20 and I live with my dad.", "20", "true"),
    ("I'm 25, I'm couch surfing at a friend's place right now.", "25", "false"),
    ("I'm 22, I'm staying with my partner for now.", "22", "false"),
    ("I'm 21, I live in an apartment with other students.", "21", "false"),
    ("20, with friends.", "20", "false"),
    ("Tengo 20 años y comparto departamento con unas amigas.", "20", "false"),
    ("Tengo 21 y vivo con otras dos estudiantes.", "21", "false"),
    ("Tengo 20 años, vivo con mi papá y su esposa.", "20", "true"),
    ("Tengo 22 años y vivo con mi novio.", "22", "false"),
    ("Tengo 24, duermo en el sofá de un amigo por ahora.", "24", "false"),
    ("Tengo 18 años y vivo sola en un estudio.", "18", "false"),
    ("Tengo 19, vivo con tres compañeros de piso.", "19", "false"),
    ("Tengo diecinueve, estoy en los dormitorios.", "19", "false"),
    # a parent named beside the others is "with a parent" (docs/SPEC.md §4.3 item 3.5: no exceptions)
    ("I'm 20, I live with my wife and my parents.", "20", "true"),
    ("I'm 20 and I live with two roommates and my mom.", "20", "true"),
    ("Tengo 20, vivo con mi novio y mi mamá.", "20", "true"),
    # a parent said plainly, and the negated or past parent
    ("I'm 20, me and my mom.", "20", "true"),
    ("20, my parents.", "20", "true"),
    ("Tengo 20 años, mi mamá y yo.", "20", "true"),
    ("I'm 20, I'm not living with my parents.", "20", "false"),
    ("I'm 20, I used to live with my parents but now I live with friends.", "20", "false"),
    ("Tengo 20, ya no vivo con mis papás, vivo con amigas.", "20", "false"),
    ("I'm 20 and live with 4 other students.", "20", "false"),
]
FLIP = {"true": "false", "false": "true"}


def parse(text: str, pending: PendingQuestion = AGE, known: dict | None = None) -> Parsed:
    return Parser().parse(normalize(text), pending, known if known is not None else MARIA_SO_FAR, guess_lang(text))


def values(parsed: Parsed) -> dict[SlotName, SlotObservation]:
    return {o.slot: o for o in parsed.observations}


def model(observations: list[SlotObservation], answered: str = "partial", lang: str = "en") -> ExtractOutcome:
    result = ExtractionResult(observations=observations, intents=[], answered_pending=answered,  # type: ignore
                              lang=lang, side_question=None, requested_language=None)  # type: ignore[arg-type]
    return ExtractOutcome(status="ok", result=result, model="stub")


def merge(text: str, outcome: ExtractOutcome, parsed: Parsed, pending: PendingQuestion = AGE) -> Any:
    return Merger().merge(utterance=normalize(text), llm=outcome, parsed=parsed, keyword_intents=[], pending=pending,
                          known=MARIA_SO_FAR, session_lang="en")


def by_slot(merged: Any) -> dict[SlotName, SlotObservation]:
    return {o.slot: o for o in merged.observations}


# ------------------------------------------------------------------------------------------ the parser alone
@pytest.mark.parametrize("text,age,lwp", CASES)
def test_parser_reads_age_and_home(text: str, age: str, lwp: str) -> None:
    got = values(parse(text))
    assert got[S.age].value == age and got[S.age].state == "clear", got
    assert got[S.lives_with_parent].value == lwp and got[S.lives_with_parent].state == "clear", got
    assert got[S.lives_with_parent].quote and got[S.lives_with_parent].quote in normalize(text)
    assert not any(slot in got for slot in (S.rent_share, S.earned_monthly, S.other_cash_monthly)), got


@pytest.mark.parametrize("text", [
    "I'm 20, I work with other students at the library.",  # people at work, not at home
    "I'm 20, I don't live with friends, I live with my family.",  # the family may include a parent
    "I'm 21, I live with my guardian.",
    "I'm 20, no roommates.",
    "Tengo 20 y tengo residencia permanente.",  # "residencia" is not a dorm here
    "I'm 20 and I live with my mom and two roommates.",
    "I'm 20, I moved out of the dorms and back home.",  # home with the family
])
def test_parser_does_not_guess_not_with_a_parent(text: str) -> None:
    got = values(parse(text))
    assert got.get(S.lives_with_parent) is None or got[S.lives_with_parent].value == "true", got


def test_friends_answer_lives_with_parent_only_when_it_is_asked() -> None:
    got = values(parse("I make 900 a month and I live in an apartment with friends.", INCOME, {}))
    assert S.lives_with_parent not in got and got[S.earned_monthly].value == "900"
    got = values(parse("We buy food separately, I live in an apartment with friends.", HOUSEHOLD, {}))
    assert got[S.lives_with_parent].value == "false"


# ------------------------------------------------------------------------------------------ merge
def _model_without_lwp(parsed: Parsed) -> list[SlotObservation]:
    """What the live model returned: everything it heard (age, roommates, ...) except lives_with_parent."""
    return [o for o in parsed.observations if o.slot != S.lives_with_parent]


@pytest.mark.parametrize("text,age,lwp", CASES)
def test_merge_fills_lives_with_parent_the_model_left_out(text: str, age: str, lwp: str) -> None:
    parsed = parse(text)
    for kept in (_model_without_lwp(parsed), [o for o in parsed.observations if o.slot == S.age]):
        merged = merge(text, model(kept, lang=guess_lang(text)), parsed)
        got = by_slot(merged)
        assert got[S.age].value == age
        assert got[S.lives_with_parent].value == lwp and got[S.lives_with_parent].state == "clear"
        assert merged.sources[S.lives_with_parent] == SlotSource.parser
        assert merged.answered_pending == "yes", text


@pytest.mark.parametrize("text,age,lwp", CASES)
def test_a_model_that_contradicts_the_parser_stays_unclear(text: str, age: str, lwp: str) -> None:
    parsed = parse(text)
    quote = values(parsed)[S.lives_with_parent].quote
    other = SlotObservation(slot=S.lives_with_parent, value=FLIP[lwp], period=None, hours_per_week=None,
                            state="clear", quote=quote, quote_en=None)
    merged = merge(text, model(_model_without_lwp(parsed) + [other], answered="yes"), parsed)
    got = by_slot(merged)[S.lives_with_parent]
    assert got.value == FLIP[lwp] and got.state == "unclear"
    assert S.lives_with_parent in merged.conflicts and merged.sources[S.lives_with_parent] == SlotSource.llm


@pytest.mark.parametrize("text,age,lwp", CASES[:6])
def test_a_slot_the_model_marked_unclear_is_never_filled(text: str, age: str, lwp: str) -> None:
    parsed = parse(text)
    quote = values(parsed)[S.lives_with_parent].quote
    unsure = SlotObservation(slot=S.lives_with_parent, value=lwp, period=None, hours_per_week=None, state="unclear",
                             quote=quote, quote_en=None)
    merged = merge(text, model(_model_without_lwp(parsed) + [unsure]), parsed)
    got = by_slot(merged)[S.lives_with_parent]
    assert got.state == "unclear" and merged.sources[S.lives_with_parent] == SlotSource.llm
    assert merged.answered_pending == "yes"  # both asked slots are in hand (one of them unclear)


def test_the_model_saying_not_answered_keeps_the_parser_out() -> None:
    text = "I'm 20, and I live with two roommates."
    parsed = parse(text)
    merged = merge(text, model([], answered="no"), parsed)
    assert S.lives_with_parent not in by_slot(merged) and merged.answered_pending == "no"


def test_partial_stays_partial_while_an_asked_slot_is_missing() -> None:
    text = "I'm 20, I work with other students at the library."
    parsed = parse(text)
    merged = merge(text, model([o for o in parsed.observations if o.slot == S.age]), parsed)
    assert S.lives_with_parent not in by_slot(merged) and merged.answered_pending == "partial"


# ------------------------------------------------------------------------------------------ one understanding turn
class _Stub:
    """A model that returns the reported live result: age, roommates and the roommate count, no lives_with_parent."""

    model = "stub"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system: str, user_json: str, schema: dict, timeout_s: float) -> ExtractOutcome:
        self.calls += 1
        ob = [SlotObservation(slot=slot, value=value, period=None, hours_per_week=None, state="clear", quote=quote,
                              quote_en=None)
              for slot, value, quote in ((S.age, "20", "I'm 20"), (S.roommates, "true", "I live with two roommates"),
                                         (S.roommates_count, "2", "two roommates"))]
        return model(ob)


async def _turn(u: Understander, text: str, *, closed_mode: bool = False, deadline_s: float = 2.6) -> Any:
    return await u.understand(text=text, masked=False, confidence=0.9, dtmf=None, pending=AGE, known=MARIA_SO_FAR,
                              recent=[], last_prompt="How old are you, and who do you live with?",
                              lang=Lang(guess_lang(text)), deadline=u.clock.monotonic() + deadline_s,
                              closed_mode=closed_mode)


async def test_the_reported_turn_is_answered(settings_test: Any) -> None:
    stub = _Stub()
    u = Understander(settings=settings_test, llm=stub)
    got = await _turn(u, "I'm 20, and I live with two roommates.")
    obs = {o.slot: o.value for o in got.observations}
    assert stub.calls == 1 and got.llm.status == "ok"
    assert obs[S.age] == "20" and obs[S.lives_with_parent] == "false" and obs[S.roommates_count] == "2"
    assert got.sources[S.lives_with_parent] == SlotSource.parser and got.answered_pending == "yes"


async def test_the_short_answer_needs_no_model(settings_test: Any) -> None:
    stub = _Stub()
    u = Understander(settings=settings_test, llm=stub)
    got = await _turn(u, "20, two roommates")
    assert stub.calls == 0 and got.answered_pending == "yes"
    assert {o.slot: o.value for o in got.observations}[S.lives_with_parent] == "false"


@pytest.mark.parametrize("text,age,lwp", CASES)
async def test_without_the_model_every_sentence_is_answered(settings_test: Any, text: str, age: str,
                                                             lwp: str) -> None:
    # a deadline already spent: the model call times out at once (no waiting in the test)
    for u, closed, deadline_s in ((Understander(settings=settings_test, llm=FakeLLM()), False, 0.05),
                                  (Understander(settings=settings_test, llm=FakeLLM(fail=["error"])), False, 2.6),
                                  (Understander(settings=settings_test), True, 2.6)):
        got = await _turn(u, text, closed_mode=closed, deadline_s=deadline_s)
        obs = {o.slot: o.value for o in got.observations}
        assert got.llm.status in ("timeout", "error", "skipped"), text
        assert obs[S.age] == age and obs[S.lives_with_parent] == lwp, (text, obs)
        assert S.rent_share not in obs and got.answered_pending == "yes", (text, obs)


# ------------------------------------------------------------------------------------------ counts and renting a room
@pytest.mark.parametrize("pending,text,want", [
    (AGE, "I'm 20 and I rent a room with two other students.", {S.rent_share: None}),
    (AGE, "I'm 20 and I rent a room in a house of five.", {S.rent_share: None}),
    (AGE, "I'm 20 and I rent a room, there are three of us.", {S.rent_share: None}),
    (AGE, "I'm 20 and I rent a room for 900 a month with two other students.", {S.rent_share: "900"}),
    (AGE, "I'm 20, my rent is 1100 and I rent a room with two other students.", {S.rent_share: "1100"}),
    (RENT, "I rent a room, 950.", {S.rent_share: "950"}),
    (RENT, "It's 900, I live with two other students.", {S.rent_share: "900"}),
    (RENT, "Nine hundred, and there are two of us.", {S.rent_share: "900"}),
    (INCOME, "I make 900 a month, I work with three other people.", {S.earned_monthly: "900"}),
    (INCOME, "About 600 a month, me and two other guys split the shifts.", {S.earned_monthly: "600"}),
])
def test_counts_and_renting_a_room_are_not_amounts(pending: PendingQuestion, text: str,
                                                   want: dict[SlotName, str | None]) -> None:
    got = values(parse(text, pending, {}))
    for slot, value in want.items():
        if value is None:
            assert slot not in got, got
        else:
            assert got[slot].value == value and got[slot].state == "clear", got


async def test_the_rent_misread_is_not_stored_in_closed_mode(settings_test: Any) -> None:
    u = Understander(settings=settings_test)
    got = await _turn(u, "I'm 20 and I rent a room with two other students.", closed_mode=True)
    obs = {o.slot: o.value for o in got.observations}
    assert S.rent_share not in obs and obs[S.lives_with_parent] == "false"


def test_the_closed_age_question_reads_the_age_only() -> None:
    got = values(parse("I'm 20 and I rent a room with two other students.", AGE_CLOSED))
    assert got[S.age].value == "20" and S.rent_share not in got


# ------------------------------------------------------------------------------------------ the home today, whose parent
@pytest.mark.parametrize("text,want", [
    ("I'm 20, I live with my boyfriend and my mom.", "true"),
    ("Tengo 20 y vivo con dos compañeros y mi mamá.", "true"),
    ("Tengo 20, vivo con amigas y con mi papá.", "true"),
    ("Tengo 20, vivo con mi novio, y mis papás también.", "true"),
    ("I'm 20 and I share an apartment with my mom.", "true"),
    ("I'm 20, just me and my dad.", "true"),
    ("I'm 20, it's my mom and me.", "true"),  # "it's" is no possessive
    ("I'm 20, roommates? No, my parents.", "true"),
    ("20 with my mom", "true"),
    ("I'm 20, I'm moving in with roommates next month, right now with my mom.", "true"),
    ("I'm 20, I live with my partner and parents.", None),  # no "my": not read either way
    ("I'm 20, my parents and I share a house with roommates.", None),
    ("I'm 20 and I live with roommates, my mom too.", None),
    ("I'm 20, I live with my mother-in-law.", None),  # an in-law is not a parent
])
def test_a_parent_at_home_is_never_not_with_a_parent(text: str, want: str | None) -> None:
    got = values(parse(text)).get(S.lives_with_parent)
    if want is None:
        assert got is None or got.value == "true", got
    else:
        assert got is not None and got.value == want and got.state == "clear", got
        assert got.quote and got.quote in normalize(text)


@pytest.mark.parametrize("text", [
    "I'm 20, I live with my boyfriend and his parents.",  # someone else's parents
    "Tengo 20, vivo con mi novio y sus papás.",
    "I'm 20, I live with two roommates, my parents live in LA.",  # a parent who lives elsewhere
    "I'm 20 and my parents pay my rent, I live with roommates.",  # a parent who pays
    "I'm 20, I live alone, my parents help with rent.",
    "I'm 20, I don't live with my parents.",
    "I'm 20, I moved out from my parents' place, now with two roommates.",
    "I'm 20, I left my parents' place, I live with friends now.",
])
def test_a_parent_elsewhere_keeps_not_with_a_parent(text: str) -> None:
    got = values(parse(text))[S.lives_with_parent]
    assert got.value == "false" and got.state == "clear", got


@pytest.mark.parametrize("pending,text", [
    (AGE, "I'm 20, I don't live alone."),
    (AGE, "I'm 20 and I'm not living alone."),
    (AGE, "I'm 20, I used to live alone."),
    (AGE, "I'm 20, I used to live in the dorms."),
    (AGE, "I'm 20, I don't live in the dorms."),
    (AGE, "I'm 20, I'm not in the dorms anymore."),
    (AGE, "I'm 20, I moved out of the dorms."),
    (AGE, "I'm 20 and I work at the dorms."),
    (AGE, "I'm 20, I work in the dorm cafeteria."),
    (AGE, "I'm 20, I'm looking for roommates."),
    (AGE, "I'm 20, I don't live with roommates."),
    (AGE, "20, not with roommates."),
    (AGE, "I'm 20, I used to live with roommates."),
    (AGE, "I'm 20 and I hate living with roommates so I moved home."),
    (AGE, "I'm 20, I don't share a room with other students."),
    (AGE, "Tengo 20 y trabajo con compañeros de la escuela."),
    (AGE, "Tengo 20 y estudio con mis compañeros."),
    (AGE, "Tengo 20, mis compañeros de clase son buenos."),
    (HOUSEHOLD, "I don't live alone, and we buy food separately."),
])
def test_a_phrase_about_another_time_or_place_says_nothing_about_the_home(pending: PendingQuestion,
                                                                          text: str) -> None:
    """Negated, past, future, work or school: no "not with a parent", no "alone", no dorm, no roommates."""
    got = values(parse(text, pending, MARIA_SO_FAR if pending is AGE else {}))
    lwp = got.get(S.lives_with_parent)
    assert lwp is None or lwp.value == "true", got
    assert got.get(S.household_food) is None or got[S.household_food].value != "alone", got
    assert got.get(S.dorm_on_campus) is None or got[S.dorm_on_campus].value != "true", got
    assert got.get(S.roommates) is None or got[S.roommates].value != "true", got


def test_no_roommates_beside_a_parent() -> None:
    got = values(parse("I'm 20 and I live with my parents, no roommates."))
    assert got[S.lives_with_parent].value == "true" and got[S.roommates].value == "false"


@pytest.mark.parametrize("text", ["I'm 20, I live with my spouse and my parents.",
                                  "Tengo 20, vivo con mi esposa y mis padres."])
async def test_a_model_that_misses_the_parent_beside_a_spouse_stays_unclear(settings_test: Any, text: str) -> None:
    """The model reads only the spouse ("false"); the parser hears the parent: unclear, never a clear "false"."""
    parsed = parse(text)
    assert values(parsed)[S.lives_with_parent].value == "true"
    wrong = SlotObservation(slot=S.lives_with_parent, value="false", period=None, hours_per_week=None, state="clear",
                            quote=normalize(text)[:20], quote_en=None)
    merged = merge(text, model([o for o in parsed.observations if o.slot == S.age] + [wrong], answered="yes",
                               lang=guess_lang(text)), parsed)
    got = by_slot(merged)[S.lives_with_parent]
    assert got.state == "unclear" and S.lives_with_parent in merged.conflicts
    # without the model the parser's "with a parent" is kept
    u = Understander(settings=settings_test)
    turn = await _turn(u, text, closed_mode=True)
    assert {o.slot: o.value for o in turn.observations}[S.lives_with_parent] == "true"


def test_other_before_a_time_is_an_amount_and_before_a_thing_a_count() -> None:
    earned = values(parse("I make 900 some weeks and 1200 other weeks.", INCOME, {}))[S.earned_monthly]
    assert "1200" in earned.quote  # "other weeks" is not a count: the 1200 is heard as an amount
    earned = values(parse("I make 600 a month, two other jobs pay 300.", INCOME, {}))[S.earned_monthly]
    assert earned.value == "900"  # "two other jobs" is a count, never two dollars


@pytest.mark.parametrize("text", ["I'm 20 and live with 4 other students.", "I'm 20, I rent a room with 2 others."])
def test_a_count_in_digits_before_people(text: str) -> None:
    got = values(parse(text))
    assert S.rent_share not in got and got[S.lives_with_parent].value == "false", got

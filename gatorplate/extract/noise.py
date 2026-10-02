"""Content-free transcripts and background speech (phone noise, speakerphone, a TV in the room).

`kind(text)` sorts a transcript before anything else looks at it:
- "noise": nothing usable was heard. An empty transcript, only punctuation, only recognizer tags ("[inaudible]",
  "(music)", "<unk>"), only filler sounds ("uh", "mm", "eh", "the"), or a cut-off fragment ("under-", "I'm tw-").
- "check": the student checks the line ("hello?", "can you hear me?", "¿bueno? ¿me escuchas?"), and "repeat": the
  student asks to hear it again ("what?", "sorry what", "say that again", "¿perdón?"). The last reply is said again
  (a line check at the consent question gets the short consent question, as after a silence).
- None: anything else (it goes to the parser and the model as usual).

A noise, check or repeat turn stores nothing, makes no model call and does not count as an unclear answer, so noise
can never end a call, give up a question or put a wrong value in the case. Words that answer a question are never
noise: a yes ("mhm", "uh-huh", "okay"), a no ("uh-uh", "nope"), a number, "I don't know".

`background(text)` is speech that is not addressed to GatorPlate: seven or more words with no first-person word, no
answer lead ("it's", "yes", "no", ...), no hedge ("about", "like"), no pay period ("a month", "al mes"), no word said to
us (see _ADDRESSED: "you", a correction, a Spanish first-person verb, a word of the questions) and not starting with a
number, e.g. "tonight's jackpot is now four hundred million dollars", "el precio de la gasolina
subió a cinco dólares". The parser takes no bare amount or age from it, and a background turn in which the
understanding found nothing is handled like noise.
"""

from __future__ import annotations

import re
from typing import Literal

from gatorplate.extract.text import fold, normalize

Kind = Literal["noise", "check", "repeat"]

_TAG = re.compile(r"[\[(<*♪♫][^\]\)>*♪♫]{0,40}[\])>*♪♫]")
_FILLER = frozenset({
    "uh", "uhh", "uhhh", "uhm", "um", "umm", "ummm", "hm", "hmm", "hmmm", "mm", "mmm", "mmmm", "er", "erm", "ah", "ahh",
    "eh", "ehh", "oh", "ooh", "em", "the", "a", "an", "and", "so", "like", "este", "pues", "y", "o",
})
_LEAD = frozenset({"i", "im", "i'm", "it", "its", "it's", "my", "is", "about", "like", "around", "maybe", "uh", "um"})
# a line check: the student is not sure the line works ("hello?", "can you hear me?", "¿bueno? ¿me escuchas?")
_CHECK = re.compile(
    r"^(?:(?:hello|hi|hey|hola|alo|bueno)(?: (?:hello|hi|hey|hola|alo|bueno))*"
    r"(?: (?:can|do|could) you hear me| are you (?:still )?there| you there| me (?:escuchas|escucha|oyes|oye))?"
    r"|(?:hello )?(?:can|do|could) you hear me"
    r"|(?:sorry |hello )?(?:are you (?:still )?there|you there|still there|anybody there|is anyone there)"
    r"|(?:sorry )?i (?:can'?t|cannot|couldn'?t) hear (?:you|that)"
    r"|me (?:escuchas|escucha|oyes|oye)|no (?:te|le|lo) (?:escucho|oigo)|(?:sigues|estas|esta) ahi"
    r")$"
)
# a request to hear the last reply again ("what?", "sorry what", "say that again", "¿qué?", "¿perdón?")
_REPEAT = re.compile(
    r"^(?:wait what|(?:sorry|what|huh|pardon|excuse me|que|como|perdon|mande)"
    r"(?: (?:sorry|what|huh|pardon|que|como|perdon))*"
    r"|(?:sorry |what )?(?:can|could) you (?:say (?:that|it) again|repeat (?:that|it|the question))(?: please)?"
    r"|(?:sorry )?(?:say (?:that |it )?again|come again|one more time|what did you say|what was that)(?: please)?"
    r"|(?:sorry )?i (?:didn'?t|did not) (?:hear|catch) (?:you|that)"
    r"|que dijiste|otra vez|repite(?:lo)?(?: por favor)?"
    r")$"
)
# "como" and "bueno" alone are words with a meaning ("bueno" = okay): a check only when asked as a question
_NEEDS_QUESTION = frozenset({"como", "bueno"})
_WORD = re.compile(r"[a-z0-9'\-]+")
# "uh huh" / "mm hmm" (yes) and "uh uh" (no), however the recognizer spaces them: answers, never noise
_YES_NO_SOUND = re.compile(r"\b(?:uh|um|m+)[\s-]*(?:huh|h+m+)\b|\buh[\s-]+uh\b|\bmhm+\b")
_CUT = re.compile(r"[-–—]$")

_FIRST_PERSON = re.compile(
    r"\b(?:i|i'?m|im|i'?ve|i'?d|i'?ll|me|my|mine|myself|we|we'?re|us|our|ours|"
    r"yo|mi|mis|me|nos|nosotros|nosotras|nuestr[oa]s?|tengo|gano|pago|vivo|soy|estoy|trabajo|recibo|compro|cocino|"
    r"comparto|estudio|tomo|hago|vivimos|pagamos|compramos|cocinamos|ganamos|tenemos|somos)\b")
_ANSWER_LEAD = re.compile(
    r"^\W*(?:about|around|like|maybe|probably|roughly|just|only|it'?s|it is|that'?s|its|yes|yeah|yep|no|nope|nah|"
    r"none|nothing|zero|nobody|um|uh|well|so|okay|ok|sure|si|claro|unos|como|mas o menos|nada|nadie|ninguno|"
    r"son|es|cerca de)\b")
_PERIOD = re.compile(
    r"\b(?:a|per|each|every|the)\s+(?:month|week|year|hour|paycheck)\b|\bmonthly\b|\bweekly\b|"
    r"\b(?:al|por|cada|el|la)\s+(?:mes|semana|ano|hora|quincena)\b")
# an answer often starts with its number ("600 at the library and 300 at the cafe") or hedges it ("so like 383")
_NUMBER_START = re.compile(
    r"^\W*(?:\d+|\$|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|a hundred|"
    r"a thousand|half|cero|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|"
    r"veinte|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa|cien|mil)\b")
_HEDGE = re.compile(r"\b(?:about|around|like|maybe|roughly|probably|more or less|unos|como|mas o menos)\b")
# said to us: a word to the caller ("you", "usted"), a correction ("wait", "espera", "o sea"), a Spanish first-person
# verb, or a word of the questions themselves ("units", "rent", "roommates", "beca"): never background
_ADDRESSED = re.compile(
    r"\b(?:you|your|yours|you'?re|you'?ve|usted|ustedes|tu|tus|ti|contigo|"
    r"wait|actually|sorry|i mean|espera|perdon|o sea|digo|quise decir|me equivoque|"
    r"quiero|quisiera|voy|puedo|necesito|creo|pienso|siento|veo|tuve|fui|llevo|curso|vengo|prefiero|"
    r"units?|unidades|undergrad\w*|grad|graduate|licenciatura|posgrado|maestria|senior|junior|freshman|sophomore|"
    r"rent|renta|alquiler|room|cuarto|roommates?|housemates?|companer[oa]s|parents?|padres|mom|dad|mama|papa|"
    r"groceries|separately|separad[oa]s?|together|juntos|scholarship|beca|paycheck|financial aid|loans?|prestamos?|"
    r"utilities|dorm|meal plan|calfresh|ebt|savings|ahorros|job|trabajo)\b")
BACKGROUND_MIN_WORDS = 7


def _words(folded: str) -> list[str]:
    return _WORD.findall(folded)


def kind(text: str | None) -> Kind | None:
    """"noise", "check", "repeat" or None for one transcript (see the module docstring)."""
    t = normalize(text)
    if not t:
        return "noise"
    raw = fold(t)
    question = "?" in raw
    stripped = _TAG.sub(" ", raw)
    if any(ch.isdigit() for ch in stripped):
        return None
    words = _words(stripped)
    if not words:
        return "noise"  # punctuation or recognizer tags only
    if "-" in "".join(words[:-1]) or _YES_NO_SOUND.search(" ".join(words)):
        return None  # "uh-huh", "uh huh", "mm hmm" (yes), "uh-uh", "uh uh" (no)
    content = [w for w in words if w not in _FILLER]
    if not content:
        return "noise"
    # a cut-off fragment with nothing complete before it: "under-", "el-", "I'm tw-"
    if _CUT.search(words[-1]) and all(w in _LEAD for w in words[:-1]) and len(words) <= 3:
        return "noise"
    phrase = " ".join(w.strip("-'") for w in content)
    if phrase in _NEEDS_QUESTION and not question:
        return None
    if _CHECK.match(phrase):
        return "check"
    if _REPEAT.match(phrase):
        return "repeat"
    return None


def background(text: str | None) -> bool:
    """Speech that is not addressed to GatorPlate (see the module docstring)."""
    f = fold(normalize(text))
    if len(_words(f)) < BACKGROUND_MIN_WORDS:
        return False
    return not (_FIRST_PERSON.search(f) or _ANSWER_LEAD.search(f) or _PERIOD.search(f) or _NUMBER_START.search(f)
                or _HEDGE.search(f) or _ADDRESSED.search(f))

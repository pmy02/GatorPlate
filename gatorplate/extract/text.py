"""Text helpers shared by the input guard, the parser and the merge step.

Every utterance is normalized once (curly quotes made straight, whitespace collapsed) before anything else looks at
it, so quotes, keyword hits and redaction spans all refer to the same string. Word counting uses the contract rule
(docs/BRAIN_API.md §7): a whitespace-separated token with at least one letter or digit.
"""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})
_SPACE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Curly quotes made straight, whitespace collapsed, ends stripped (the guards.json matching form), NFC."""
    if not text:
        return ""
    return _SPACE.sub(" ", unicodedata.normalize("NFC", text).translate(_QUOTES)).strip()


def fold_same(text: str) -> str:
    """Like fold() but keeps every character position, so spans found in the result index the original text."""
    out = "".join(unicodedata.normalize("NFD", ch)[0] for ch in text).lower()
    return out if len(out) == len(text) else text.lower()


def word_count(text: str) -> int:
    """Contract word count: whitespace tokens with at least one letter or digit."""
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def fold(text: str) -> str:
    """Lower case without accents ("Sí, está" -> "si, esta"), for accent-tolerant cue matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


# Words that mark an utterance as Spanish when the model has not said so (closed mode, keypad, fast path).
_SPANISH_MARKERS = re.compile(
    r"\b(?:si|claro|gracias|tengo|vivo|gano|pago|renta|mis?|tus?|nadie|nada|todo|mama|papa|papas|soy|estoy|"
    r"estudio|trabajo|unidades|anos|al mes|la semana|cada|quiero|puedo|puedes|esta|eso|tambien|pero|porque|"
    r"cuanto|dinero|comida|companer[oa]s?|dueno|semestre|ninguno|ninguna|bueno|vale|dale|adelante|por favor|"
    r"espera|perdon|usted|ella|ellos|nosotros|hijos?|hijas?|esposo|esposa|desempleo|beca)\b"
)
_ENGLISH_MARKERS = re.compile(
    r"\b(?:yes|yeah|the|and|my|i|i'm|im|you|is|are|it's|work|make|pay|rent|month|week|hour|with|live|"
    r"don't|no one|nobody|nothing|thanks|okay|sure|what|that|this|have|get|gives?|sends?)\b"
)


def guess_lang(text: str, default: str = "en") -> str:
    """"en" or "es" by marker words; the session language breaks ties. Used only when the model gave no language."""
    folded = fold(text)
    es = len(_SPANISH_MARKERS.findall(folded))
    en = len(_ENGLISH_MARKERS.findall(folded))
    if es > en:
        return "es"
    if en > es:
        return "en"
    return default if default in ("en", "es") else "en"

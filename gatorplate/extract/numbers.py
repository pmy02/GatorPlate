"""Numbers in English and Spanish speech or typing -> Decimal, with their character spans.

Reads digits ("900", "$1,227.50", "1.2k", "20k"), English words ("eleven hundred", "fifteen hundred", "one thousand two
hundred and fifty", "a thousand", "two grand", "twenty-two") and Spanish words ("mil cien", "dieciocho mil",
"doscientos cincuenta", "treinta y cinco", "diecinueve con cincuenta" = 19.50). A teen or ty word ("fifteen" /
"fifty", "quince" / "cincuenta") sets `teen_ty`: speech recognition confuses them, and the dialogue may confirm a
critical amount. A colloquial pair such as "nineteen fifty", "nine-fifty" or "doce cincuenta" reads as 1950 / 950 /
1250, with the alternative reading 19.50 / 9.50 / 12.50 kept in `alt` for hourly pay. Digits never set `teen_ty`.

No float anywhere: every value is a Decimal built from integers or digit strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from gatorplate.extract.text import fold

EN_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9}
EN_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
            "seventeen": 17, "eighteen": 18, "nineteen": 19}
EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
           "eighty": 80, "ninety": 90}
EN_THOUSAND = {"thousand", "grand"}
_EN_SCALES = {"hundred"} | EN_THOUSAND

ES_UNITS = {"cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
            "nueve": 9}
ES_ONE = {"un", "una"}  # a number only before "mil" (else an article)
ES_TEENS = {"diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
            "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21,
            "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
            "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
ES_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
           "noventa": 90}
ES_HUNDREDS = {"cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
               "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
               "seiscientos": 600, "seiscientas": 600, "setecientos": 700, "setecientas": 700, "ochocientos": 800,
               "ochocientas": 800, "novecientos": 900, "novecientas": 900}

TEEN_TY = frozenset({"thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "thirty",
                     "forty", "fourty", "fifty", "sixty", "seventy", "eighty", "ninety", "trece", "catorce", "quince",
                     "dieciseis", "diecisiete", "dieciocho", "diecinueve", "treinta", "cuarenta", "cincuenta",
                     "sesenta", "setenta", "ochenta", "noventa"})

HUNDRED = Decimal(100)
THOUSAND = Decimal(1000)
_ORDINAL = re.compile(r"(?:st|nd|rd|th)\b", re.IGNORECASE)
_TOKEN = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?k?(?![\w])|\$?\d+(?:\.\d+)?|[^\W\d_]+(?:'[^\W\d_]+)?|\S", re.UNICODE)
_DOLLAR_AFTER = re.compile(r"\s*(?:dollars?|bucks|d[oó]lares|dlls?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Num:
    value: Decimal
    start: int
    end: int
    words: bool = False  # said in words
    teen_ty: bool = False
    alt: Decimal | None = None  # the cents reading of a colloquial pair ("nineteen fifty" -> 19.50)
    dollar: bool = False  # "$" before it or "dollars" / "bucks" after it
    text: str = ""


@dataclass(frozen=True)
class _Tok:
    text: str
    word: str  # folded lower case, accents removed
    start: int
    end: int


def _tokens(text: str) -> list[_Tok]:
    return [_Tok(m.group(0), fold(m.group(0)), m.start(), m.end()) for m in _TOKEN.finditer(text)]


class _Reader:
    def __init__(self, toks: list[_Tok], spanish_once: bool) -> None:
        self.t = toks
        self.spanish_once = spanish_once
        self.used: list[str] = []

    def w(self, i: int) -> str:
        return self.t[i].word if 0 <= i < len(self.t) else ""

    def hy(self, i: int) -> int:
        """Skip a hyphen between number words."""
        return i + 1 if self.w(i) == "-" and self._is_num_word(i + 1) else i

    def _is_num_word(self, i: int) -> bool:
        w = self.w(i)
        if w == "once" and not self.spanish_once:
            return False
        return (w in EN_UNITS or w in EN_TEENS or w in EN_TENS or w in ES_UNITS or w in ES_TEENS or w in ES_TENS
                or w in ES_HUNDREDS or w in ("hundred", "thousand", "mil"))

    def take(self, i: int) -> int:
        self.used.append(self.w(i))
        return i + 1

    # ---------------------------------------------------------------- English
    def en_below100(self, i: int) -> tuple[int, int] | None:
        w = self.w(i)
        if w in EN_TENS:
            v = EN_TENS[w]
            j = self.take(i)
            k = self.hy(j)
            if self.w(k) in EN_UNITS and EN_UNITS[self.w(k)] > 0:
                v += EN_UNITS[self.w(k)]
                j = self.take(k)
            return v, j
        if w in EN_TEENS:
            return EN_TEENS[w], self.take(i)
        if w in EN_UNITS and w != "zero":
            return EN_UNITS[w], self.take(i)
        if w == "zero":
            return 0, self.take(i)
        return None

    def en_below1000(self, i: int) -> tuple[int, int, bool] | None:
        """(value, next index, had 'hundred')."""
        if self.w(i) in ("a", "an") and self.w(i + 1) == "hundred":
            v, j = 100, i + 2
            self.used.append("hundred")
            return self._en_after_hundred(v, j)
        r = self.en_below100(i)
        if r is None:
            return None
        v, j = r
        k = self.hy(j)
        if self.w(k) == "hundred" and 0 < v < 100:
            self.used.append("hundred")
            return self._en_after_hundred(v * 100, k + 1)
        return v, j, False

    def _en_after_hundred(self, v: int, j: int) -> tuple[int, int, bool]:
        k = j + 1 if self.w(j) == "and" and self._en_starts_below100(j + 1) else j
        r = self.en_below100(k) if self._en_starts_below100(k) else None
        if r is not None:
            return v + r[0], r[1], True
        return v, j, True

    def _en_starts_below100(self, i: int) -> bool:
        w = self.w(i)
        return w in EN_TENS or w in EN_TEENS or (w in EN_UNITS and w != "zero")

    def en_number(self, i: int) -> tuple[Decimal, int, Decimal | None] | None:
        """(value, next index, alt) for an English number phrase starting at i."""
        if self.w(i) in ("a", "an") and self.w(i + 1) in EN_THOUSAND:
            self.used.append(self.w(i + 1))
            v, j = self._en_after_thousand(1000, i + 2)
            return Decimal(v), j, None
        r = self.en_below1000(i)
        if r is None:
            return None
        v, j, had_hundred = r
        if self.w(j) in EN_THOUSAND and v > 0:
            self.used.append(self.w(j))
            v, j = self._en_after_thousand(v * 1000, j + 1)
            return Decimal(v), j, None
        # colloquial pair: "nineteen fifty", "nine-fifty", "twelve fifty"
        if not had_hundred and v < 100:
            k = self.hy(j) if self.w(j) == "-" else j
            nxt = self.w(k)
            if nxt in EN_TEENS or nxt in EN_TENS:
                save = list(self.used)
                r2 = self.en_below100(k)
                if r2 is not None and r2[0] >= 10 and self.w(r2[1]) not in _EN_SCALES:
                    b, j2 = r2
                    return Decimal(v * 100 + b), j2, Decimal(v) + Decimal(b) / HUNDRED
                self.used = save
        return Decimal(v), j, None

    def _en_after_thousand(self, v: int, j: int) -> tuple[int, int]:
        k = j + 1 if self.w(j) == "and" else j
        if self._en_starts_below100(k) or (self.w(k) in ("a", "an") and self.w(k + 1) == "hundred"):
            r = self.en_below1000(k)
            if r is not None and r[0] < 1000:
                return v + r[0], r[1]
        return v, j

    # ---------------------------------------------------------------- Spanish
    def es_below100(self, i: int) -> tuple[int, int] | None:
        w = self.w(i)
        if w == "once" and not self.spanish_once:
            return None
        if w in ES_TENS:
            v = ES_TENS[w]
            j = self.take(i)
            if self.w(j) == "y" and self.w(j + 1) in ES_UNITS and ES_UNITS[self.w(j + 1)] > 0:
                v += ES_UNITS[self.w(j + 1)]
                j = self.take(j + 1)
            return v, j
        if w in ES_TEENS:
            return ES_TEENS[w], self.take(i)
        if w in ES_UNITS:
            return ES_UNITS[w], self.take(i)
        return None

    def es_below1000(self, i: int) -> tuple[int, int] | None:
        w = self.w(i)
        if w in ES_HUNDREDS:
            v = ES_HUNDREDS[w]
            j = self.take(i)
            r = self.es_below100(j) if self.w(j) not in ("cero",) else None
            if r is not None:
                return v + r[0], r[1]
            return v, j
        return self.es_below100(i)

    def es_number(self, i: int) -> tuple[Decimal, int, Decimal | None] | None:
        if self.w(i) == "mil" or (self.w(i) in ES_ONE and self.w(i + 1) == "mil"):
            j = (i + 2) if self.w(i) in ES_ONE else (i + 1)
            self.used.append("mil")
            v = 1000
        else:
            r = self.es_below1000(i)
            if r is None:
                return None
            v, j = r
            if self.w(j) == "mil" and v > 0:
                self.used.append("mil")
                v *= 1000
                j += 1
            else:
                pair = self._es_pair(i, v, j)
                return pair if pair is not None else self._es_cents(Decimal(v), j)
        r = self.es_below1000(j)
        if r is not None:
            v += r[0]
            j = r[1]
        return self._es_cents(Decimal(v), j)

    def _es_pair(self, i: int, v: int, j: int) -> tuple[Decimal, int, Decimal | None] | None:
        """A colloquial price pair ("doce cincuenta" = 12.50, "diecinueve noventa"): like the English pair, the value
        is 1250 and the cents reading 12.50 is kept in `alt` (hourly pay reads `alt`)."""
        if not (0 < v < 100) or self.w(i) in ES_HUNDREDS or self.w(j) == "con":
            return None
        nxt = self.w(j)
        second = nxt in ES_TENS or (nxt in ES_TEENS and ES_TEENS[nxt] >= 10)
        if not second or (nxt == "once" and not self.spanish_once):
            return None
        save = list(self.used)
        r = self.es_below100(j)
        if r is None or r[0] < 10 or self.w(r[1]) in ("mil", "cientos") or self.w(r[1]) in ES_HUNDREDS:
            self.used = save
            return None
        b, j2 = r
        return Decimal(v * 100 + b), j2, Decimal(v) + Decimal(b) / HUNDRED

    def _es_cents(self, v: Decimal, j: int) -> tuple[Decimal, int, Decimal | None]:
        if self.w(j) == "con":
            r = self.es_below100(j + 1)
            if r is not None and r[0] < 100:
                return v + Decimal(r[0]) / HUNDRED, r[1], None
        return v, j, None


def _digit_value(tok: _Tok, text: str) -> Decimal | None:
    raw = tok.text
    if raw.startswith("$"):
        raw = raw[1:]
    mult = Decimal(1)
    if raw.lower().endswith("k"):
        raw = raw[:-1]
        mult = THOUSAND
    raw = raw.replace(",", "")
    try:
        value = Decimal(raw) * mult
    except ArithmeticError:
        return None
    if _ORDINAL.match(text, tok.end):
        return None  # "1st", "15th": dates, not amounts
    return value


def find_numbers(text: str, *, spanish: bool = False) -> list[Num]:
    """Every number in the text, left to right. `spanish` reads "once" as eleven (else it is "one time")."""
    toks = _tokens(text)
    out: list[Num] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.text[0].isdigit() or (tok.text[0] == "$" and len(tok.text) > 1 and tok.text[1].isdigit()):
            value = _digit_value(tok, text)
            if value is not None:
                dollar = tok.text.startswith("$") or bool(_DOLLAR_AFTER.match(text, tok.end))
                out.append(Num(value, tok.start, tok.end, dollar=dollar, text=tok.text))
            i += 1
            continue
        best: tuple[Decimal, int, Decimal | None, list[str]] | None = None
        for reader_fn in ("en_number", "es_number"):
            reader = _Reader(toks, spanish)
            r = getattr(reader, reader_fn)(i)
            if r is not None and r[1] > i and (best is None or r[1] > best[1]):
                best = (r[0], r[1], r[2], reader.used)
        if best is None or (toks[i].word in ("a", "an") and best[1] <= i + 1):
            i += 1
            continue
        value, j, alt, used = best
        if toks[i].word == "one" and _not_a_number_one(toks, i):
            i += 1
            continue
        start, end = toks[i].start, toks[j - 1].end
        dollar = bool(_DOLLAR_AFTER.match(text, end))
        out.append(Num(value, start, end, words=True, teen_ty=any(u in TEEN_TY for u in used), alt=alt,
                       dollar=dollar, text=text[start:end]))
        i = j
    return out


def _not_a_number_one(toks: list[_Tok], i: int) -> bool:
    prev = toks[i - 1].word if i > 0 else ""
    nxt = toks[i + 1].word if i + 1 < len(toks) else ""
    return prev in ("no", "the", "this", "that", "which", "every", "each", "any", "some", "unlimited") or nxt in (
        "of", "more", "sec", "second", "moment", "minute", "day")

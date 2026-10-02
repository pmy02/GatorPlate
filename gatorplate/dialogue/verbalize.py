"""Numbers, phone numbers, codes, web addresses and hours as words (spoken text) or as digits and symbols (web display).

Phone text is spoken exactly as written (docs/BRAIN_API.md §7): no digits or symbols, money in words, phone numbers and
codes as digit groups, web addresses spoken. The web `display` uses digits and symbols. Spanish words are used for the
one Spanish phone notice and for the Spanish web conversation. Money is Decimal; nothing here uses float or round().
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from gatorplate.contracts.common import Lang

_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

_ES_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
             "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
             "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
             "veintinueve"]
_ES_TENS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_ES_HUNDREDS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
                "ochocientos", "novecientos"]

DIGIT_WORDS = {
    Lang.en: ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
    Lang.es: ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"],
}
_URL_WORDS = {Lang.en: {".": "dot", "/": "slash", "-": "dash"}, Lang.es: {".": "punto", "/": "barra", "-": "guion"}}

_DOLLAR = Decimal(1)
_CENT = Decimal("0.01")


# ---------------------------------------------------------------------------------------------- integers in words

def _en_below_100(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    tens, ones = divmod(n, 10)
    return _EN_TENS[tens] + (f"-{_EN_ONES[ones]}" if ones else "")


def _en_below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_EN_ONES[hundreds]} hundred")
    if rest or not parts:
        parts.append(_en_below_100(rest))
    return " ".join(parts)


def _en_int(n: int) -> str:
    """Plain cardinal: 12 -> 'twelve', 2025 -> 'two thousand twenty-five'."""
    if n < 0:
        return "minus " + _en_int(-n)
    if n < 1000:
        return _en_below_1000(n)
    parts = []
    for size, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if n >= size:
            count, n = divmod(n, size)
            parts.append(f"{_en_below_1000(count)} {name}")
    if n:
        parts.append(_en_below_1000(n))
    return " ".join(parts)


def _es_below_100(n: int) -> str:
    if n < 30:
        return _ES_UNITS[n]
    tens, ones = divmod(n, 10)
    return _ES_TENS[tens] + (f" y {_ES_UNITS[ones]}" if ones else "")


def _es_below_1000(n: int) -> str:
    if n == 100:
        return "cien"
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(_ES_HUNDREDS[hundreds])
    if rest or not parts:
        parts.append(_es_below_100(rest))
    return " ".join(parts)


def _es_apocope(text: str) -> str:
    """'uno' before a noun or 'mil' becomes 'un' ('veintiuno' -> 'veintiún')."""
    if text.endswith("veintiuno"):
        return text[: -len("veintiuno")] + "veintiún"
    if text.endswith("uno"):
        return text[: -len("uno")] + "un"
    return text


def _es_int(n: int) -> str:
    """Plain cardinal: 12 -> 'doce', 1100 -> 'mil cien'."""
    if n < 0:
        return "menos " + _es_int(-n)
    if n < 1000:
        return _es_below_1000(n)
    parts = []
    millions, n = divmod(n, 1_000_000)
    if millions:
        parts.append("un millón" if millions == 1 else f"{_es_apocope(_es_int(millions))} millones")
    thousands, n = divmod(n, 1000)
    if thousands:
        parts.append("mil" if thousands == 1 else f"{_es_apocope(_es_below_1000(thousands))} mil")
    if n:
        parts.append(_es_below_1000(n))
    return " ".join(parts)


def int_words(n: int, lang: Lang = Lang.en) -> str:
    return _es_int(n) if lang == Lang.es else _en_int(n)


# ---------------------------------------------------------------------------------------------- money

def whole_dollars(amount: Decimal | int) -> int:
    """Whole dollars, half-up (display and speech only; the rules engine owns every computed amount)."""
    number = amount if isinstance(amount, Decimal) else Decimal(amount)
    return int(number.quantize(_DOLLAR, rounding=ROUND_HALF_UP))


def _en_dollars(n: int) -> str:
    """Bank rule: under 1,000 plain; 1,000-9,999 with a hundreds digit other than zero in hundreds ('eleven hundred');
    whole thousands, a zero hundreds digit and 10,000 or more in thousands."""
    if 1000 <= n <= 9999 and (n // 100) % 10 != 0:
        hundreds, rest = divmod(n, 100)
        text = f"{_en_below_100(hundreds)} hundred"
        if rest:
            text += f" {_en_below_100(rest)}"
        return text
    return _en_int(n)


def money_words(amount: Decimal | int, lang: Lang = Lang.en, *, cents: bool = False) -> str:
    """'three hundred six dollars', 'eleven hundred dollars'; with cents=True and a fraction 'eighteen dollars fifty'.
    Spanish: 'trescientos seis dólares', 'mil cien dólares', 'dieciocho dólares cincuenta'."""
    number = amount if isinstance(amount, Decimal) else Decimal(amount)
    if cents and number != number.to_integral_value():
        exact = number.quantize(_CENT, rounding=ROUND_HALF_UP)
        whole = int(exact.to_integral_value(rounding=ROUND_DOWN))
        fraction = int((exact - Decimal(whole)) * 100)
        if lang == Lang.es:
            return f"{_es_money_whole(whole)} {_es_below_100(fraction)}"
        return f"{_en_money_whole(whole)} {_en_below_100(fraction)}"
    whole = whole_dollars(number)
    return _es_money_whole(whole) if lang == Lang.es else _en_money_whole(whole)


def _en_money_whole(n: int) -> str:
    return f"{_en_dollars(n)} {'dollar' if n == 1 else 'dollars'}"


def _es_money_whole(n: int) -> str:
    if n == 1:
        return "un dólar"
    return f"{_es_apocope(_es_int(n))} dólares"


def money_display(amount: Decimal | int, *, cents: bool = False) -> str:
    """'$306', '$1,100'; with cents=True and a fraction '$18.50'."""
    number = amount if isinstance(amount, Decimal) else Decimal(amount)
    if cents and number != number.to_integral_value():
        return f"${number.quantize(_CENT, rounding=ROUND_HALF_UP):,.2f}"
    return f"${whole_dollars(number):,}"


def number_display(value: Decimal | int) -> str:
    """'15', '7.5' (hours a week and similar plain numbers)."""
    number = value if isinstance(value, Decimal) else Decimal(value)
    if number == number.to_integral_value():
        return str(int(number))
    return f"{number.normalize():f}"


def number_words(value: Decimal | int, lang: Lang = Lang.en) -> str:
    """Whole numbers in words; a fraction is spoken with its whole part ('seven and a half' is not attempted)."""
    number = value if isinstance(value, Decimal) else Decimal(value)
    return int_words(whole_dollars(number), lang)


# ---------------------------------------------------------------------------------------------- digit groups

def digits_spoken(digits: str, lang: Lang = Lang.en, *, group: int = 3) -> str:
    """'481206' -> 'four eight one, two zero six' (groups of three, comma between groups)."""
    clean = [d for d in digits if d.isdigit()]
    words = [DIGIT_WORDS[lang][int(d)] for d in clean]
    groups = [" ".join(words[i:i + group]) for i in range(0, len(words), group)]
    return ", ".join(groups)


def code_display(code: str) -> str:
    """'481206' -> '481 206'."""
    return f"{code[:3]} {code[3:]}" if len(code) == 6 else code


# ---------------------------------------------------------------------------------------------- web addresses

def _label_spoken(label: str, lang: Lang) -> str:
    out = []
    for chunk in _split_alnum(label):
        if chunk.isdigit():
            out.append(" ".join(DIGIT_WORDS[lang][int(d)] for d in chunk))
        elif chunk in _URL_WORDS[lang]:
            out.append(_URL_WORDS[lang][chunk])
        else:
            out.append(chunk)
    return " ".join(out)


def _split_alnum(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    kind = None
    for ch in text:
        k = "d" if ch.isdigit() else "a" if ch.isalpha() else "s"
        if k == kind and k != "s":
            current += ch
        else:
            if current:
                chunks.append(current)
            current, kind = ch, k
    if current:
        chunks.append(current)
    return chunks


def url_spoken(base_url: str, path: str, lang: Lang = Lang.en) -> str:
    """'https://gatorplate.fly.dev' + '/go' -> 'gatorplate dot fly dot dev slash go' (no scheme, no port; digits and
    symbols as words, so the phone text rules hold for any host). A development address (a numeric or loopback host)
    is spoken as 'localhost', so local runs keep the same word budgets as the deployed app."""
    host = (urlsplit(base_url).hostname or base_url).lower()
    if host == "localhost" or host.replace(".", "").isdigit() or ":" in host:
        host = "localhost"
    dot = _URL_WORDS[lang]["."]
    spoken_host = f" {dot} ".join(_label_spoken(label, lang) for label in host.split(".") if label)
    spoken_path = " ".join(f"{_URL_WORDS[lang]['/']} {_label_spoken(part, lang)}"
                           for part in path.strip("/").split("/") if part)
    return f"{spoken_host} {spoken_path}".strip()


def url_display(base_url: str, path: str) -> str:
    """'https://gatorplate.fly.dev' + '/go' -> 'gatorplate.fly.dev/go' (the port is kept when there is one)."""
    parts = urlsplit(base_url)
    host = parts.netloc or base_url
    return f"{host}/{path.strip('/')}"

"""Display formatting for the student card: money, dates and months in English or Spanish (docs/UI_SPEC.md A4.7).

Code inserts every number; these helpers only format values the rules engine and the case already hold. Money is
Decimal or int, never float; whole dollars are rounded half-up (docs/SPEC.md §5.5).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from gatorplate.contracts.common import Lang

_MONTHS = {
    Lang.en: ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"),
    Lang.es: ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
              "noviembre", "diciembre"),
}
_MONTHS_SHORT = {
    Lang.en: ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    Lang.es: ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
}
_WEEKDAYS_SHORT = {
    Lang.en: ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    Lang.es: ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
}


def money(amount: Decimal | int | str) -> str:
    """"$306", "$1,100": whole dollars, half-up, with a thousands comma."""
    number = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    whole = number.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"${whole:,.0f}"


def month_name(day: date, lang: Lang) -> str:
    """"October" / "octubre"."""
    return _MONTHS[Lang(lang)][day.month - 1]


def day_text(day: date, lang: Lang) -> str:
    """The estimated filing day: "Fri, Oct 2" / "vie 2 de oct"."""
    lang = Lang(lang)
    weekday = _WEEKDAYS_SHORT[lang][day.weekday()]
    month = _MONTHS_SHORT[lang][day.month - 1]
    if lang is Lang.es:
        return f"{weekday} {day.day} de {month}"
    return f"{weekday}, {month} {day.day}"

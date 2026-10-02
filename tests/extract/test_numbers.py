"""Numbers in English and Spanish speech -> Decimal (no float), with the teen/ty flag."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gatorplate.extract.numbers import find_numbers


def values(text: str, spanish: bool = False) -> list[Decimal]:
    return [n.value for n in find_numbers(text, spanish=spanish)]


@pytest.mark.parametrize("text,expect", [
    ("Eleven hundred.", ["1100"]),
    ("fifteen hundred", ["1500"]),
    ("About a thousand.", ["1000"]),
    ("Two grand a month", ["2000"]),
    ("one thousand two hundred and fifty", ["1250"]),
    ("about nine hundred a month", ["900"]),
    ("twenty-two", ["22"]),
    ("a hundred a week", ["100"]),
    ("1.2k a month", ["1200"]),
    ("Like 20k a year", ["20000"]),
    ("I get $1,227.50 every two weeks.", ["1227.50", "2"]),
    ("$614.32 per week", ["614.32"]),
    ("I pay nine-fifty.", ["950"]),
    ("Twelve fifty a month.", ["1250"]),
])
def test_english(text: str, expect: list[str]) -> None:
    assert values(text) == [Decimal(e) for e in expect]


@pytest.mark.parametrize("text,expect", [
    ("Mil cien.", ["1100"]),
    ("Gano mil quinientos al mes.", ["1500"]),
    ("mil doscientos cincuenta", ["1250"]),
    ("Gano dieciocho mil al año.", ["18000"]),
    ("doscientos cincuenta", ["250"]),
    ("treinta y cinco", ["35"]),
    ("Tengo dos hijos, de cuatro y siete años.", ["2", "4", "7"]),
    ("diecinueve con cincuenta la hora", ["19.50"]),
    ("Tengo veintiún años", ["21"]),
    ("son once unidades", ["11"]),
])
def test_spanish(text: str, expect: list[str]) -> None:
    assert values(text, spanish=True) == [Decimal(e) for e in expect]


def test_pair_keeps_the_cents_reading() -> None:
    (n,) = find_numbers("nineteen fifty an hour")
    assert n.value == Decimal("1950") and n.alt == Decimal("19.50")


@pytest.mark.parametrize("text,flag", [
    ("fifteen hundred", True), ("forty bucks", True), ("thirteen dollars", True), ("eleven hundred", False),
    ("twelve units", False), ("nine hundred", False), ("1500", False), ("quince dólares", True),
    ("cincuenta", True), ("doce", False),
])
def test_teen_ty(text: str, flag: bool) -> None:
    (n,) = find_numbers(text, spanish=True)
    assert n.teen_ty is flag


@pytest.mark.parametrize("text", [
    "I went there once", "No one sends me money.", "the 1st and the 15th", "one sec", "The unlimited one.",
    "una licenciatura",
])
def test_not_numbers(text: str) -> None:
    assert [n for n in find_numbers(text) if n.value > 1 or n.text.lower() in ("one", "once", "una")] == []


def test_no_float() -> None:
    assert all(isinstance(n.value, Decimal) for n in find_numbers("19.50 and 1.2k and $3"))

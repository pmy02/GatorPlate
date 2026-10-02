"""Fixtures for the understanding tests (fake language model, settings with every GP_* variable cleared)."""

from __future__ import annotations

from typing import Any

import pytest

from gatorplate.extract import Understander
from gatorplate.extract.keywords import KeywordMatcher
from gatorplate.extract.parser import Parser
from gatorplate.extract.redact import Redactor
from tests.extract.support import load_utterances


@pytest.fixture(scope="session")
def utterances() -> list[dict[str, Any]]:
    return load_utterances()


@pytest.fixture(scope="session")
def redactor() -> Redactor:
    return Redactor()


@pytest.fixture(scope="session")
def keywords() -> KeywordMatcher:
    return KeywordMatcher()


@pytest.fixture(scope="session")
def parser() -> Parser:
    return Parser()


@pytest.fixture
def understander(settings_test) -> Understander:
    return Understander(settings=settings_test)

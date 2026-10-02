"""Only GP_* settings configure the language-model client: vendor-standard variables in the environment are ignored,
the client gets exactly the settings' key and base URL, and without a key there is no client (closed mode)."""

from __future__ import annotations

from pydantic import SecretStr

from gatorplate.config import Settings
from gatorplate.contracts.common import Lang
from gatorplate.contracts.extraction import PendingQuestion
from gatorplate.contracts.slots import SlotName
from gatorplate.extract import Understander
from gatorplate.extract.llm.anthropic_client import AnthropicClient

JUNK = {
    "ANTHROPIC_API_KEY": "junk-vendor",
    "ANTHROPIC_AUTH_TOKEN": "junk-token",
    "ANTHROPIC_BASE_URL": "https://junk.invalid",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Junk: 1",
    "ANTHROPIC_PROFILE": "junk",
}


def test_vendor_variables_are_ignored(clean_gp_env, tmp_path) -> None:
    for name, value in JUNK.items():
        clean_gp_env.setenv(name, value)
    clean_gp_env.setenv("GP_LLM_PROVIDER", "anthropic")
    clean_gp_env.setenv("GP_LLM_API_KEY", "gp-key")
    clean_gp_env.setenv("GP_LLM_BASE_URL", "https://gp.example.invalid")
    settings = Settings(env="test", db_path=tmp_path / "x.db")
    understander = Understander.from_settings(settings)
    client = understander.llm
    assert isinstance(client, AnthropicClient)
    sdk = client.sdk
    assert sdk.api_key == "gp-key"
    assert sdk.auth_token is None
    assert str(sdk.base_url).rstrip("/") == "https://gp.example.invalid"
    assert sdk.max_retries == 0
    assert "X-Junk" not in dict(sdk.default_headers)
    assert client.model == settings.llm_model == "claude-haiku-4-5"


def test_explicit_settings_win(clean_gp_env, tmp_path) -> None:
    for name, value in JUNK.items():
        clean_gp_env.setenv(name, value)
    settings = Settings(env="test", db_path=tmp_path / "x.db", llm_provider="anthropic",
                        llm_api_key=SecretStr("other-key"), llm_base_url="https://other.example.invalid")
    client = Understander(settings=settings).llm
    assert isinstance(client, AnthropicClient)
    assert client.sdk.api_key == "other-key"
    assert str(client.sdk.base_url).rstrip("/") == "https://other.example.invalid"


async def test_no_key_no_client_closed_mode(clean_gp_env, tmp_path) -> None:
    for name, value in JUNK.items():
        clean_gp_env.setenv(name, value)  # a vendor key in the environment must not create a client
    settings = Settings(env="test", db_path=tmp_path / "x.db", llm_provider="anthropic", llm_api_key=SecretStr(""))
    understander = Understander(settings=settings)
    assert understander.llm is None
    assert understander.llm_health()["status"] == "no_key"
    result = await understander.understand(
        text="I work at the campus library, about 900 a month. Nobody gives me cash.", masked=False,
        confidence=0.9, dtmf=None,
        pending=PendingQuestion(key="ask.income", slots=[SlotName.earned_monthly, SlotName.other_cash_monthly],
                                kind="number"),
        known={}, recent=[], last_prompt=None, lang=Lang.en, deadline=understander.clock.monotonic() + 2.6,
        closed_mode=False)
    assert result.llm.status == "skipped"
    assert {o.slot for o in result.observations} == {SlotName.earned_monthly, SlotName.other_cash_monthly}


def test_fake_provider_needs_no_key(settings_test) -> None:
    understander = Understander(settings=settings_test)
    assert understander.llm is not None and understander.llm.provider == "fake"
    assert understander.llm_health()["provider"] == "fake"

"""Settings are GP_* only, passed explicitly; prod refuses missing or development secrets; nothing outside
gatorplate/config.py reads the environment."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from gatorplate.config import DEV_CONSOLE_PASSCODE, DEV_GATEWAY_SECRET, DEV_SESSION_SECRET, Settings

ROOT = Path(__file__).resolve().parent.parent
PROD_SECRETS = {"GP_GATEWAY_SECRET": "x" * 64, "GP_CONSOLE_PASSCODE": "p" * 20,
                "GP_SESSION_SECRET": "y" * 48}


def test_defaults(clean_gp_env) -> None:
    s = Settings()
    assert s.env == "dev" and s.llm_provider == "fake" and s.card_delivery == "code"
    assert s.public_base_url == "http://127.0.0.1:8000"
    assert s.llm_base_url == "https://api.anthropic.com" and s.llm_model == "claude-haiku-4-5"
    assert s.llm_api_key.get_secret_value() == ""
    assert s.debug_keys is True and s.demo_mode is True and s.daily_reset is False and s.live_transcript is False
    assert s.programs is True and s.programs_table == Path("data/rules/programs_2026.json")
    assert s.rules_table == Path("data/rules/ca_fy2027.json")
    assert s.gateway_secret.get_secret_value() == DEV_GATEWAY_SECRET
    assert s.console_passcode.get_secret_value() == DEV_CONSOLE_PASSCODE
    assert s.session_secret.get_secret_value() == DEV_SESSION_SECRET
    assert s.programs_table_path.is_absolute() and s.programs_table_path.exists()
    assert s.rules_table_path.exists() and s.guards_path.exists()


def test_gp_variables_are_read(clean_gp_env) -> None:
    clean_gp_env.setenv("GP_PROGRAMS", "0")
    clean_gp_env.setenv("GP_CARD_DELIVERY", "screen")
    clean_gp_env.setenv("GP_LLM_TIMEOUT_S", "1.5")
    clean_gp_env.setenv("GP_PROGRAMS_TABLE", "data/rules/other.json")
    s = Settings()
    assert s.programs is False and s.card_delivery == "screen" and s.llm_timeout_s == 1.5
    assert s.programs_table == Path("data/rules/other.json")


def test_vendor_variables_are_ignored(clean_gp_env) -> None:
    clean_gp_env.setenv("ANTHROPIC_API_KEY", "junk-vendor-value-should-not-be-read")
    clean_gp_env.setenv("ANTHROPIC_BASE_URL", "https://junk.invalid")
    clean_gp_env.setenv("LLM_API_KEY", "junk")
    s = Settings()
    assert s.llm_api_key.get_secret_value() == ""
    assert s.llm_base_url == "https://api.anthropic.com"


def test_no_env_file(clean_gp_env, tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("GP_ENV=prod\nGP_PROGRAMS=0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.env == "dev" and s.programs is True


def test_prod_refuses_missing_secrets(clean_gp_env) -> None:
    clean_gp_env.setenv("GP_ENV", "prod")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("name,dev_value", [("GP_GATEWAY_SECRET", DEV_GATEWAY_SECRET),
                                            ("GP_CONSOLE_PASSCODE", DEV_CONSOLE_PASSCODE),
                                            ("GP_SESSION_SECRET", DEV_SESSION_SECRET)])
def test_prod_refuses_dev_secrets(clean_gp_env, name: str, dev_value: str) -> None:
    clean_gp_env.setenv("GP_ENV", "prod")
    for key, value in PROD_SECRETS.items():
        clean_gp_env.setenv(key, value)
    clean_gp_env.setenv(name, dev_value)
    with pytest.raises(ValidationError):
        Settings()


def test_prod_with_real_secrets(clean_gp_env) -> None:
    clean_gp_env.setenv("GP_ENV", "prod")
    for key, value in PROD_SECRETS.items():
        clean_gp_env.setenv(key, value)
    s = Settings()
    assert s.is_prod and s.debug_keys is False
    assert "x" * 64 not in repr(s)


def test_settings_fixture(settings_test: Settings) -> None:
    assert settings_test.env == "test" and settings_test.llm_provider == "fake"
    assert settings_test.debug_keys is True and settings_test.card_delivery == "code"


def test_env_example_lists_every_setting() -> None:
    names = [line.split("=")[0] for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert all(line.endswith("=") for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
               if line.strip())
    assert sorted(names) == sorted(f"GP_{field.upper()}" for field in Settings.model_fields)
    assert not (ROOT / ".env").exists()


ENV_READ = re.compile(r"\bos\.environ\b|\bos\.getenv\b|\bgetenv\(|\benviron\[|from os import [^\n]*environ")


def test_no_environment_reads_outside_config() -> None:
    offenders = []
    for path in sorted((ROOT / "gatorplate").rglob("*.py")):
        if path.relative_to(ROOT).as_posix() == "gatorplate/config.py":
            continue
        if ENV_READ.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_no_vendor_variable_names_in_code() -> None:
    vendor = re.compile(r"\bANTHROPIC_(?:API_KEY|BASE_URL|AUTH_TOKEN)\b")
    offenders = [p.relative_to(ROOT).as_posix() for p in (ROOT / "gatorplate").rglob("*.py")
                 if vendor.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_empty_variables_mean_unset(clean_gp_env) -> None:
    clean_gp_env.setenv("GP_PROGRAMS", "")
    clean_gp_env.setenv("GP_GATEWAY_SECRET", "")
    s = Settings()
    assert s.programs is True and s.gateway_secret.get_secret_value() == DEV_GATEWAY_SECRET

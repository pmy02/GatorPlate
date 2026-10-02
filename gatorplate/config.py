"""Settings: the only module that reads the environment, and only GP_* variables (docs/SPEC.md §8.9).

No env file and no other source. Every component receives Settings (or the values it needs) through Deps. In dev and
test the three secrets default to public development values; in prod the app refuses to start unless all three are
set and differ from those values. The language model client gets its key and base URL from here, as arguments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# Public development values (never valid in prod). The gateway value is the public HMAC test-vector secret of
# contracts/examples/hmac_vectors.json.
DEV_GATEWAY_SECRET = "test-secret-do-not-use"
DEV_CONSOLE_PASSCODE = "dev"
DEV_SESSION_SECRET = "dev-session-secret"
DEV_SECRETS = {
    "gateway_secret": DEV_GATEWAY_SECRET,
    "console_passcode": DEV_CONSOLE_PASSCODE,
    "session_secret": DEV_SESSION_SECRET,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", env_file=None, extra="ignore", case_sensitive=False,
                                      env_ignore_empty=True)

    env: Literal["dev", "test", "prod"] = "dev"
    public_base_url: str = "http://127.0.0.1:8000"
    db_path: Path = Path("var/gatorplate.db")
    demo_mode: bool = True
    daily_reset: bool = False
    debug_keys: bool | None = None  # None: True in dev and test, False in prod
    live_transcript: bool = False
    card_delivery: Literal["screen", "code"] = "code"

    llm_provider: Literal["fake", "anthropic"] = "fake"
    llm_model: str = "claude-haiku-4-5"
    llm_fallback_model: str = ""  # provider errors only, never timeouts
    llm_api_key: SecretStr = SecretStr("")  # empty: no client, closed mode
    llm_base_url: str = "https://api.anthropic.com"
    llm_timeout_s: float = 2.3
    turn_budget_s: float = 2.6
    llm_daily_turn_cap: int = 1500
    llm_hedge_ms: int = 0

    rules_table: Path = Path("data/rules/ca_fy2027.json")
    programs: bool = True  # False hides every programs surface
    programs_table: Path = Path("data/rules/programs_2026.json")
    tz: str = "America/Los_Angeles"
    card_ttl_days: int = 7
    short_code_ttl_h: int = 24
    demo_phone_display: str = ""  # empty: no demo number shown

    gateway_secret: SecretStr = SecretStr("")
    console_passcode: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        **unused_sources: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Explicit arguments, then GP_* environment variables. The dotenv and file sources pydantic-settings also
        # offers are dropped: no .env file and no secrets directory.
        return init_settings, env_settings

    @model_validator(mode="after")
    def _environment_rules(self) -> Settings:
        if self.debug_keys is None:
            self.debug_keys = self.env != "prod"
        for name, dev_value in DEV_SECRETS.items():
            current = getattr(self, name).get_secret_value()
            if self.env == "prod":
                if not current:
                    raise ValueError(f"GP_{name.upper()} must be set in prod")
                if current == dev_value:
                    raise ValueError(f"GP_{name.upper()} must not be the public development value in prod")
            elif not current:
                setattr(self, name, SecretStr(dev_value))
        return self

    # ------------------------------------------------------------------------------------------ helpers

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @staticmethod
    def repo_path(path: Path | str) -> Path:
        """A relative setting path resolved against the repository root (absolute paths stay as they are)."""
        p = Path(path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def rules_table_path(self) -> Path:
        return self.repo_path(self.rules_table)

    @property
    def programs_table_path(self) -> Path:
        return self.repo_path(self.programs_table)

    @property
    def db_file(self) -> Path:
        return self.repo_path(self.db_path)

    @property
    def content_dir(self) -> Path:
        return REPO_ROOT / "data" / "content"

    @property
    def guards_path(self) -> Path:
        return self.content_dir / "guards.json"

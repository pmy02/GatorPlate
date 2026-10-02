"""fly.toml: the deploy values stay exactly as planned, secrets and switchable settings stay out of the file, and the
[http_service] and health-check windows keep GatorPlate's own layout (no two keys follow each other as in the hosting
platform's generated or documented example, a layout the repository's copied-code check flags)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLY = ROOT / "fly.toml"
CONFIG = tomllib.loads(FLY.read_text(encoding="utf-8"))

# The order in which the hosting platform's generated (and documented) example lists these keys (key names only).
GENERATED_HTTP_ORDER = ["internal_port", "force_https", "auto_stop_machines", "auto_start_machines",
                        "min_machines_running"]
GENERATED_CHECK_ORDER = ["grace_period", "interval", "method", "timeout", "path"]


def test_app_and_region() -> None:
    assert CONFIG["app"] == "gatorplate"
    assert CONFIG["primary_region"] == "iad"


def test_env_values() -> None:
    assert CONFIG["env"] == {
        "GP_ENV": "prod",
        "GP_PUBLIC_BASE_URL": "https://gatorplate.fly.dev",
        "GP_DB_PATH": "/data/gatorplate.db",
        "GP_LLM_PROVIDER": "anthropic",
        "GP_LLM_HEDGE_MS": "1250",
        "GP_DEBUG_KEYS": "0",
        "GP_DEMO_MODE": "1",
        "GP_LIVE_TRANSCRIPT": "1",
        "GP_TZ": "America/Los_Angeles",
    }


def test_http_service_values() -> None:
    service = dict(CONFIG["http_service"])
    checks = service.pop("checks")
    assert service == {
        "internal_port": 8080,
        "force_https": True,
        "auto_stop_machines": "off",
        "auto_start_machines": True,
        "min_machines_running": 1,
    }
    assert checks == [{"grace_period": "10s", "interval": "15s", "method": "GET", "path": "/v1/health",
                       "timeout": "5s"}]


def test_volume_and_machine() -> None:
    assert CONFIG["mounts"] == {"source": "gp_data", "destination": "/data"}
    assert CONFIG["vm"] == [{"size": "shared-cpu-1x", "memory": "512mb"}]


def test_secrets_and_switchable_settings_are_not_in_the_file() -> None:
    for name in ("GP_LLM_API_KEY", "GP_GATEWAY_SECRET", "GP_CONSOLE_PASSCODE", "GP_SESSION_SECRET",
                 "GP_CARD_DELIVERY", "GP_DEMO_PHONE_DISPLAY", "GP_PROGRAMS"):
        assert name not in CONFIG["env"]


def test_internal_port_matches_the_dockerfile() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    port = CONFIG["http_service"]["internal_port"]
    assert f"EXPOSE {port}" in dockerfile
    assert f"--port {port}" in dockerfile


def keys_in_file_order(table: str) -> list[str]:
    """The keys of one table header's block, in file order (comments and blank lines skipped)."""
    keys: list[str] = []
    inside = False
    for line in FLY.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            inside = stripped == table
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped)
        if inside and m:
            keys.append(m.group(1))
    return keys


def adjacent_in_generated_order(keys: list[str], generated: list[str]) -> list[tuple[str, str]]:
    follows = set(zip(generated, generated[1:], strict=False))
    return [pair for pair in zip(keys, keys[1:], strict=False) if pair in follows]


def test_http_service_window_is_not_the_generated_layout() -> None:
    keys = keys_in_file_order("[http_service]")
    assert sorted(keys) == sorted(GENERATED_HTTP_ORDER)
    assert adjacent_in_generated_order(keys, GENERATED_HTTP_ORDER) == []


def test_health_check_window_is_not_the_generated_layout() -> None:
    keys = keys_in_file_order("[[http_service.checks]]")
    assert sorted(keys) == sorted(GENERATED_CHECK_ORDER)
    assert adjacent_in_generated_order(keys, GENERATED_CHECK_ORDER) == []

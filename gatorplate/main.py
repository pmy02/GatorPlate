"""ASGI entry point: `uvicorn gatorplate.main:app` (one worker).

The app is built lazily on first access of `app`, so importing this module has no side effects.
"""

from __future__ import annotations

from typing import Any


def build_app() -> Any:
    from gatorplate.api.app import create_app
    from gatorplate.config import Settings
    from gatorplate.wiring import build_deps

    return create_app(build_deps(Settings()))


def __getattr__(name: str) -> Any:
    if name == "app":
        application = build_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)

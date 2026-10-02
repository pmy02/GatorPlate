"""In-process harness for the card tests: the real wiring (`wiring.build_deps`) behind a TestClient, the fake
language model, phone turns signed with the public development secret, and the event bus wrapped so a test can see
what the API published. Tests that use it skip, with that reason, while the wiring is still the foundation stub.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gatorplate.clock import default_test_clock
from gatorplate.config import DEV_CONSOLE_PASSCODE, DEV_GATEWAY_SECRET, Settings
from tools import e2e_run as runner

ROOT = Path(__file__).resolve().parents[2]
STUB_REASON = "wiring.build_deps is still the foundation stub (wired at integration)"


class RecordingBus:
    """Delegates to the real event bus and remembers every publish (type and flags only)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.published: list[dict] = []

    def publish(self, type: str, **kwargs: Any) -> Any:  # noqa: A002 - the port's parameter name
        event = self._inner.publish(type, **kwargs)
        summary = getattr(event, "summary", None)
        self.published.append({"type": type, "changed_programs": bool(kwargs.get("changed_programs")),
                               "case_id": kwargs.get("case_id") or getattr(kwargs.get("case"), "id", None),
                               "found_display": getattr(summary, "found_display", None)})
        return event

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def summarize(self) -> Any:
        return self._inner.summarize

    @summarize.setter
    def summarize(self, fn: Any) -> None:
        # create_app installs the programs-aware summarizer; it must reach the real bus.
        self._inner.summarize = fn


@dataclasses.dataclass
class Harness:
    client: TestClient
    deps: Any
    bus: RecordingBus
    target: runner.Target

    def login(self) -> None:
        r = self.client.post("/api/console/login", json={"passcode": DEV_CONSOLE_PASSCODE})
        assert r.status_code == 200, r.status_code

    def play(self, script_id: str, *, send_end: bool = True) -> runner.ItemResult:
        """Plays a script's turns (and its end block unless send_end is false); returns the runner's result with
        the case id it found through the console."""
        path = next(p for d in runner.SCRIPTS_DIRS for p in d.glob(f"{script_id}.json"))
        script = runner.load_script(path)
        if not send_end:
            script = script.model_copy(update={"end": None, "final": None})
        result = runner.Player(script, self.target, runner.OutputGuard()).run()
        assert result.case_id, f"no case found for {script_id}: {result.failures[:5]}"
        return result

    def end(self, result: runner.ItemResult, reason: str = "completed") -> None:
        """/end for a call played with send_end=False (phone channel)."""
        r = self.target.post(f"/v1/calls/{result.call_id}/end", {"v": 1, "reason": reason}, channel="phone")
        assert r.status_code == 200, r.status_code

    def detail(self, case_id: str) -> dict:
        r = self.client.get(f"/api/cases/{case_id}")
        assert r.status_code == 200, r.status_code
        return r.json()

    def card_token(self, case_id: str) -> str:
        url = self.detail(case_id).get("card_url")
        assert url, "the case has no card"
        return url.rstrip("/").split("/")[-1]


def build(settings: Settings, *, fixed_clock: bool = True) -> Harness:
    from gatorplate.ids import SystemIds
    from gatorplate.wiring import build_deps, compose

    try:
        # One fixed clock reaches every component (brain, stores, understanding and API).
        deps = compose(settings, clock=default_test_clock(), ids=SystemIds()) if fixed_clock else build_deps(settings)
    except NotImplementedError:
        pytest.skip(STUB_REASON)
    clock = deps.clock
    bus = RecordingBus(deps.events)
    deps = dataclasses.replace(deps, events=bus)
    from gatorplate.api.app import create_app

    try:
        app = create_app(deps)
    except NotImplementedError:
        pytest.skip("api.app.create_app is still the foundation stub")
    client = TestClient(app)
    client.__enter__()
    target = runner.Target(client=client, base="http://testserver", secret=DEV_GATEWAY_SECRET,
                           passcode=DEV_CONSOLE_PASSCODE, debug_keys=bool(settings.debug_keys),
                           card_delivery=settings.card_delivery)
    # Sign with the app's clock when the gateway check reads it; fall back to wall time otherwise.
    target.clock = lambda: clock.now().timestamp()
    probe = target.post("/v1/calls/" + "f" * 32 + "/end", {"v": 1, "reason": "completed"}, channel="phone")
    if probe.status_code == 401:
        target.clock = None
    return Harness(client=client, deps=deps, bus=bus, target=target)


def close(h: Harness) -> None:
    h.client.__exit__(None, None, None)


def answers(h: Harness, token: str, body: dict, lang: str = "en") -> Any:
    return h.client.post(f"/api/card/{token}/answers", params={"lang": lang}, content=json.dumps(body),
                         headers={"Content-Type": "application/json"})


def progress(h: Harness, token: str, body: dict, lang: str = "en") -> Any:
    return h.client.post(f"/api/card/{token}/progress", params={"lang": lang}, content=json.dumps(body),
                         headers={"Content-Type": "application/json"})

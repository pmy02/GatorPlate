"""A text call to the Brain API from the terminal (docs/BRAIN_API.md): interactive, or scripted from an E2E script.

    make say ARGS="--script maria_g1"            # plays maria_g1's student turns, then its /end block
    make say ARGS="--channel web --lang es"      # interactive web call in Spanish
    make say APP_PORT=8004 ARGS="--script maria_g1"

Phone calls are signed with GP_GATEWAY_SECRET from this process's environment, or with the public development
secret against a local server; web calls open a session and use its bearer token. When the server stops answering
(connection error or 502/503/504), a request is retried with the same call id and seq for up to 15 seconds, so a
server restart mid-call resumes the call. Interactive commands: `/dtmf <key>`, `/silence`, `/end [reason]`,
`/quit`; any other line is an utterance.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import httpx  # noqa: E402

try:  # imported as tools.say_call (tests) or run as a script from tools/
    from tools import e2e_run as runner  # noqa: E402
except ImportError:  # pragma: no cover
    import e2e_run as runner  # type: ignore[no-redef]  # noqa: E402

RETRY_STATUSES = {502, 503, 504}


class Caller:
    def __init__(self, target: runner.Target, channel: str, lang: str, *, retry_s: float = 15.0, test: bool = False,
                 out: Any = None) -> None:
        self.t, self.channel, self.lang, self.retry_s, self.test = target, channel, lang, retry_s, test
        self.out = out or sys.stdout
        self.call_id = uuid.uuid4().hex
        self.token: str | None = None
        self.seq = 0
        self.turns = 0
        self.started = time.monotonic()
        self.last_keys: list[str] | None = None
        self.ended = False

    def _post(self, path: str, body: dict, *, auth_channel: str | None) -> Any:
        deadline = time.monotonic() + self.retry_s
        while True:
            try:
                r = self.t.post(path, body, channel=auth_channel, token=self.token,
                                auth="normal" if auth_channel else "none")
                if r.status_code not in RETRY_STATUSES:
                    return r
            except httpx.TransportError:
                r = None
            if time.monotonic() >= deadline:
                if r is None:
                    raise SystemExit("the server did not answer within the retry window")
                return r
            time.sleep(0.5)

    def start(self) -> dict:
        if self.channel == "web":
            r = self._post("/api/web/sessions", {"lang": self.lang}, auth_channel=None)
            if r.status_code != 200:
                raise SystemExit(f"web session: HTTP {r.status_code}")
            self.call_id, self.token = r.json()["call_id"], r.json()["token"]
        body = {"v": 1, "seq": 0, "channel": self.channel, "lang": self.lang, "test": self.test}
        return self._show(self._post(f"/v1/calls/{self.call_id}/start", body, auth_channel=self.channel))

    def turn(self, event: dict) -> dict:
        self.seq += 1
        body = {"v": 1, "seq": self.seq, "lang": self.lang, **event}
        if event["event"] != "silence":
            self.turns += 1
        return self._show(self._post(f"/v1/calls/{self.call_id}/turn", body, auth_channel=self.channel))

    def end(self, reason: str = "completed") -> None:
        if self.ended:
            return
        body = {"v": 1, "reason": reason, "turns": self.turns,
                "duration_ms": int((time.monotonic() - self.started) * 1000)}
        r = self._post(f"/v1/calls/{self.call_id}/end", body, auth_channel=self.channel)
        self.ended = True
        print(f"[end {reason}] HTTP {r.status_code}", file=self.out)

    def _show(self, r: Any) -> dict:
        if r.status_code != 200:
            try:
                code = (r.json().get("error") or {}).get("code")
            except ValueError:  # a proxy page, not the contract's error envelope
                code = "not an error envelope"
            print(f"HTTP {r.status_code}: {code}", file=self.out)
            return {}
        reply = r.json()
        debug = reply.get("debug") or {}
        self.last_keys = debug.get("keys")
        keys = f"[{', '.join(self.last_keys)}] " if self.last_keys else ""
        print(f"GatorPlate {keys}({reply['lang']}): {reply['say']}", file=self.out)
        if reply.get("ask"):
            print(f"  ask ({reply['expect']}): {reply['ask']}", file=self.out)
        if reply.get("card_url"):
            print(f"  card: {reply['card_url']}", file=self.out)
        if reply.get("hold_s"):
            print(f"  (holding {reply['hold_s']} s)", file=self.out)
        if reply.get("end"):
            print(f"  (call ends: {reply['end_reason']})", file=self.out)
        return reply


def play_script(caller: Caller, script: runner.Script) -> int:
    """The script's student turns in order (conditional turns only when their question was asked), then its /end
    block. Turns that test errors (other calls, bad auth, explicit seq, repeats) are not played here. The call is
    always ended, so the case is never left live: with the script's end block, else with the reason of a reply that
    ended the call (docs/BRAIN_API.md §5.3), else as a hang-up; a failed request ends it with `error`."""
    reply = caller.start()
    if not reply:
        caller.end("error")
        return 1
    for turn in script.turns[1:]:
        if turn.call != "this" or turn.auth != "normal" or turn.seq is not None or turn.repeat_previous \
                or turn.expect_status != 200:
            continue
        if turn.when_pending is not None and turn.when_pending not in (caller.last_keys or []):
            continue
        if turn.end_call is not None:
            caller.end(turn.end_call.reason)
            return 0
        if turn.user is not None:
            print(f"Student: {turn.user}", file=caller.out)
            reply = caller.turn({"event": "utterance", "text": turn.user, "masked": turn.masked,
                                 "confidence": turn.confidence, "interrupted": turn.interrupted,
                                 "typed": turn.typed})
        elif turn.dtmf is not None:
            print(f"Student presses {turn.dtmf}", file=caller.out)
            reply = caller.turn({"event": "dtmf", "dtmf": turn.dtmf})
        elif turn.silence is not None:
            print("(silence)", file=caller.out)
            reply = caller.turn({"event": "silence", "silence_n": turn.silence.n, "silence_ms": turn.silence.ms})
        if not reply:
            caller.end("error")
            return 1
        if reply.get("end") and script.end is None:
            break
    if script.end is not None:
        caller.end(script.end.reason)
    elif reply.get("end"):
        caller.end(reply.get("end_reason") or "completed")
    else:
        caller.end("caller_hangup")
    return 0


def interactive(caller: Caller) -> int:
    caller.start()
    silence_n = 0
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        if text == "/quit":
            break
        if text.startswith("/end"):
            caller.end(text.split(maxsplit=1)[1] if " " in text else "completed")
            return 0
        if text.startswith("/dtmf"):
            silence_n = 0
            reply = caller.turn({"event": "dtmf", "dtmf": text.split(maxsplit=1)[1] if " " in text else ""})
        elif text == "/silence":
            silence_n += 1
            reply = caller.turn({"event": "silence", "silence_n": silence_n, "silence_ms": 5000 * silence_n})
        else:
            silence_n = 0
            reply = caller.turn({"event": "utterance", "text": text, "masked": False, "confidence": None,
                                 "interrupted": False, "typed": True})
        if reply.get("end"):
            caller.end(reply["end_reason"])
            return 0
    caller.end("caller_hangup")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="A text call to the Brain API (interactive or scripted).")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--script", help="play this E2E script's student turns (tests/e2e/scripts, tests/adversarial)")
    p.add_argument("--channel", choices=["phone", "web"], default="phone")
    p.add_argument("--lang", choices=["en", "es"], default="en")
    p.add_argument("--test", action="store_true", help="mark the call as a team test call (StartRequest.test)")
    p.add_argument("--retry-s", type=float, default=15.0, help="retry window when the server stops answering")
    args = p.parse_args(argv)

    script = None
    if args.script:
        matches = [s for _, s in runner.load_scripts(runner.SCRIPTS_DIRS) if s.id == args.script]
        if not matches:
            print(f"no script with id {args.script}", file=sys.stderr)
            return 2
        script = matches[0]
    channel = script.channel if script else args.channel
    lang = script.lang if script else ("en" if channel == "phone" else args.lang)
    local = runner.is_local_base(args.base)
    secret = os.environ.get("GP_GATEWAY_SECRET") or (runner.DEV_GATEWAY_SECRET if local else None)
    if channel == "phone" and secret is None:
        print("a phone call to a non-local server needs GP_GATEWAY_SECRET in the environment", file=sys.stderr)
        return 2
    with httpx.Client(base_url=args.base, timeout=10.0) as client:
        target = runner.Target(client=client, base=args.base, secret=secret, passcode=None)
        caller = Caller(target, channel, lang, retry_s=args.retry_s, test=args.test or (script.test if script
                                                                                        else False))
        return play_script(caller, script) if script else interactive(caller)


if __name__ == "__main__":
    sys.exit(main())

"""GatewayLines: the lines the hosted voice gateway says on its own (docs/BRAIN_API.md §8), built from the `line.*`
keys of the sentence bank. `GET /v1/lines?lang=en` must equal contracts/examples/lines_en.json exactly."""

from __future__ import annotations

from gatorplate.contracts.brain_api import GatewayLines
from gatorplate.contracts.common import Channel, Lang
from gatorplate.dialogue.templates import Bank

LINE_FIELDS: dict[str, str] = {
    "retry": "line.retry",
    "fatal": "line.fatal",
    "fatal_start": "line.fatal_start",
    "no_input_bye": "line.no_input_bye",
    "time_limit": "line.time_limit",
    "line_unavailable": "line.line_unavailable",
}


def _text(variant: str | dict) -> str:
    if isinstance(variant, dict):
        return " ".join(p for p in (variant.get("say") or "", variant.get("ask") or "") if p)
    return variant


def gateway_lines(bank: Bank, lang: Lang) -> GatewayLines:
    filler = [_text(v) for v in bank.variants("line.filler", lang, Channel.phone)]
    values = {name: _text(bank.variants(key, lang, Channel.phone)[0]) for name, key in LINE_FIELDS.items()}
    return GatewayLines(lang=lang, filler=filler, **values)

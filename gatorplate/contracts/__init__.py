"""GatorPlate's internal contracts: the models every module shares, the Brain API mirror of the frozen schema, the
ports, the domain errors and the console wording. Imports nothing from the app."""

from gatorplate.contracts import (  # noqa: F401  (import order matters: no cycles)
    brain_api,
    card_api,
    case,
    common,
    console_api,
    console_text,
    errors,
    extraction,
    ports,
    programs,
    rules_io,
    session,
    slots,
    summary,
)

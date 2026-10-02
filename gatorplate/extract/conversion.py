"""Monthly conversion for the understanding step: plausibility checks, comparing two readings, and adding amounts
said with different periods. Factors come from the rules table's `conversion` section (docs/SPEC.md §5.5):
weekly x 4.33, every two weeks x 2.167, twice a month x 2, yearly / 12, hourly = rate x hours a week x 4.33; cents
half-up once. The authoritative normalization of a stored slot is the rules module's; this copy reads the same data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from gatorplate.contracts.slots import SLOT_SPECS, SlotName

DEFAULT_RULES = Path(__file__).resolve().parent.parent.parent / "data" / "rules" / "ca_fy2027.json"
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Conversion:
    multipliers: dict[str, Decimal]
    year_divisor: Decimal

    @classmethod
    def load(cls, rules_path: Path | str | None = None) -> Conversion:
        return _load(str(rules_path or DEFAULT_RULES))

    def monthly(self, value: Decimal | str, period: str | None, hours_per_week: Decimal | float | None = None
                ) -> Decimal | None:
        """Monthly amount (cents half-up), or None when it cannot be computed (hourly pay without hours)."""
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value))
            if period is None or period == "once":
                result = amount
            elif period == "hour":
                if hours_per_week is None:
                    return None
                hours = hours_per_week if isinstance(hours_per_week, Decimal) else Decimal(str(hours_per_week))
                result = amount * hours * self.multipliers["week"]
            elif period == "year":
                result = amount / self.year_divisor
            elif period in self.multipliers:
                result = amount * self.multipliers[period]
            else:
                return None
            if not result.is_finite():
                return None
            return result.quantize(CENT, rounding=ROUND_HALF_UP)
        except (ArithmeticError, ValueError):  # not a number, or too large to hold in cents: cannot tell
            return None


def in_range(slot: SlotName, value: str, period: str | None, hours_per_week: Decimal | float | None,
             conversion: Conversion) -> bool | None:
    """Plausibility from SLOT_SPECS (not policy): money is checked as a monthly amount. None = cannot tell."""
    spec = SLOT_SPECS[slot]
    if spec.type == "money":
        number = conversion.monthly(value, period if spec.periodic else None, hours_per_week)
        if number is None:
            return None
    elif spec.type == "int":
        if not value.lstrip("-").isdigit():
            return False
        number = Decimal(value)
    else:
        return None
    return (spec.min is None or number >= spec.min) and (spec.max is None or number <= spec.max)


@lru_cache(maxsize=4)
def _load(path: str) -> Conversion:
    data = json.loads(Path(path).read_text(encoding="utf-8"))["conversion"]
    multipliers = {name: Decimal(str(raw)) for name, raw in data["multipliers"].items()}
    return Conversion(multipliers=multipliers, year_divisor=Decimal(str(data["year_divisor"])))

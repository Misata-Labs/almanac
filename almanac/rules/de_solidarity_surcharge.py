"""German solidarity surcharge (Solidaritätszuschlag) on assessed income tax.

The surcharge is a percentage of the income tax that serves as its base, but
it is levied only when the base exceeds an exemption limit (Freigrenze),
which is doubled for spouses assessed jointly. Just above the limit a
phase-in caps the surcharge at a percentage of the excess over the limit, so
it rises smoothly instead of jumping to the full rate. Fractions of a cent
are dropped (SolZG 1995 §§ 3 and 4).

Parameters::

    rate_percent: 5.5
    phase_in_percent: 11.9
    exemption_limit: {single: 20350, joint: 40700}
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)


def exemption_limit(parameters: Mapping[str, Any], joint: bool = False) -> Decimal:
    return Decimal(str(parameters["exemption_limit"]["joint" if joint else "single"]))


def surcharge(parameters: Mapping[str, Any], income_tax: Any, joint: bool = False) -> Decimal:
    """Solidarity surcharge in euros and cents on an income tax base."""
    base = Decimal(str(income_tax))
    limit = exemption_limit(parameters, joint)
    if base <= limit:
        return Decimal("0.00")
    full = base * Decimal(str(parameters["rate_percent"])) / _HUNDRED
    capped = (base - limit) * Decimal(str(parameters["phase_in_percent"])) / _HUNDRED
    return min(full, capped).quantize(_CENT, rounding=ROUND_DOWN)


def evaluate(parameters: Mapping[str, Any], value: Any) -> str:
    if isinstance(value, Mapping):
        return str(surcharge(parameters, value["income_tax"], bool(value.get("joint"))))
    return str(surcharge(parameters, value))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "rate" and not stat.args:
        return float(parameters["rate_percent"])
    if stat.name == "exemption_limit" and len(stat.args) == 1:
        return float(exemption_limit(parameters, stat.args[0] == "joint"))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

"""ISO 4217 currency code and minor-unit rule.

The parameters hold the current ISO 4217 list: for each alphabetic code the
numeric code, name and number of minor units (decimal places), or null for
codes such as precious metals that have no minor unit. The rule answers
whether a code is current, how many decimals an amount in it carries, and
whether a decimal amount is representable in that currency.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from almanac.models import Statistic


def currency(parameters: Mapping[str, Any], code: str) -> dict[str, Any]:
    try:
        return dict(parameters["currencies"][code.upper()])
    except KeyError as exc:
        raise KeyError(f"{code!r} is not a current ISO 4217 code") from exc


def is_current(code: str, parameters: Mapping[str, Any]) -> bool:
    return code.upper() in parameters["currencies"]


def minor_units(code: str, parameters: Mapping[str, Any]) -> int | None:
    """Number of decimal places for amounts in ``code``, or None when the currency has no minor unit."""
    return currency(parameters, code)["minor_units"]


def is_representable(amount: str, code: str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``amount`` has no more decimals than the currency allows."""
    places = minor_units(code, parameters)
    exponent = Decimal(amount).normalize().as_tuple().exponent
    decimals = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return decimals <= (places or 0)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "amount" in value:
            return is_representable(str(value["amount"]), str(value["currency"]), parameters)
        if "minor_units_of" in value:
            return minor_units(str(value["minor_units_of"]), parameters)
    return is_current(str(value), parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    currencies = parameters["currencies"]
    if stat.name == "count" and not stat.args:
        return len(currencies)
    if stat.name == "count" and len(stat.args) == 1:
        wanted = None if stat.args[0] == "none" else int(stat.args[0])
        return sum(1 for c in currencies.values() if c["minor_units"] == wanted)
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

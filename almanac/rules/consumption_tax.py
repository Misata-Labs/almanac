"""Consumption-tax rate schedule with tax computation.

A value-added tax, goods and services tax or consumption tax charges a
percentage of the value of a supply. The parameters hold the named rates in
force together (``slabs``) and, optionally, the rounding step for amounts.
The rule answers whether a percentage is one of the published rates, and
computes the tax either on a tax-exclusive amount (rate x value) or within a
tax-inclusive amount (the tax fraction rate / (100 + rate), the form tax
authorities publish as 9/109 or 1/11).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from almanac.models import Statistic

_DEFAULT_STEP = "0.01"


def slabs(parameters: Mapping[str, Any]) -> dict[str, Decimal]:
    return {name: Decimal(str(rate)) for name, rate in parameters["slabs"].items()}


def rate(parameters: Mapping[str, Any], slab: str) -> Decimal:
    try:
        return slabs(parameters)[slab]
    except KeyError as exc:
        raise KeyError(f"no slab named {slab!r}") from exc


def is_slab(percentage: float | str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``percentage`` is one of the published rates."""
    return Decimal(str(percentage)) in set(slabs(parameters).values())


def slab_name(percentage: float | str, parameters: Mapping[str, Any]) -> str:
    wanted = Decimal(str(percentage))
    for name, value in slabs(parameters).items():
        if value == wanted:
            return name
    raise KeyError(f"{percentage}% is not a published slab")


def tax_fraction(parameters: Mapping[str, Any], slab: str) -> Fraction:
    """Share of a tax-inclusive amount that is tax: rate / (100 + rate), in lowest terms."""
    percentage = Fraction(rate(parameters, slab))
    return percentage / (100 + percentage)


def _round(amount: Decimal, parameters: Mapping[str, Any]) -> Decimal:
    return amount.quantize(Decimal(str(parameters.get("rounding", _DEFAULT_STEP))), rounding=ROUND_HALF_UP)


def tax_on_net(amount: float | str, parameters: Mapping[str, Any], slab: str = "standard") -> Decimal:
    """Tax charged on a tax-exclusive amount."""
    return _round(Decimal(str(amount)) * rate(parameters, slab) / 100, parameters)


def tax_in_gross(amount: float | str, parameters: Mapping[str, Any], slab: str = "standard") -> Decimal:
    """Tax contained in a tax-inclusive amount, using the tax fraction."""
    fraction = tax_fraction(parameters, slab)
    return _round(Decimal(str(amount)) * fraction.numerator / fraction.denominator, parameters)


def gross_from_net(amount: float | str, parameters: Mapping[str, Any], slab: str = "standard") -> Decimal:
    """Tax-inclusive amount for a tax-exclusive one."""
    net = Decimal(str(amount))
    return _round(net, parameters) + tax_on_net(net, parameters, slab)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    """A bare percentage asks slab membership; ``{net|gross, slab}`` returns the tax as a string."""
    if not isinstance(value, Mapping):
        return is_slab(value, parameters)
    slab = str(value.get("slab", "standard"))
    if "net" in value:
        return str(tax_on_net(value["net"], parameters, slab))
    if "gross" in value:
        return str(tax_in_gross(value["gross"], parameters, slab))
    raise ValueError("expected a 'net' or 'gross' amount")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["slabs"])
    if stat.name == "slab" and len(stat.args) == 1:
        return float(rate(parameters, stat.args[0]))
    if stat.name == "tax_fraction" and len(stat.args) == 1:
        return float(tax_fraction(parameters, stat.args[0]))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

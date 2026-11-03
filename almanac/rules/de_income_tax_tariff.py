"""German income tax tariff under § 32a EStG, with the splitting method for joint assessment.

The statute defines the tariff as zones of taxable income. Below the basic
allowance the tax is nil; the two progressive zones are quadratic in a
variable that is one ten-thousandth of the income above the zone's offset;
the two top zones are linear with a fixed deduction. Taxable income is
rounded down to full euros before the formula applies and the resulting tax
is rounded down to full euros. Spouses assessed jointly pay twice the tax on
half their joint taxable income (§ 32a(5)).

The parameters carry the zones exactly as the statute states them::

    zones:
      - {upper: 12348, formula: zero}
      - {upper: 17799, formula: quadratic, offset: 12348, a: 914.51, b: 1400, c: 0}
      - {upper: 277825, formula: linear, rate: 0.42, deduction: 11135.63}
      - {upper: null, formula: linear, rate: 0.45, deduction: 19470.38}

``upper`` is the last whole-euro income of the zone (``null`` for the top zone).
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_TEN_THOUSAND = Decimal(10000)


def _euros(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), rounding=ROUND_FLOOR))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def zone_for(parameters: Mapping[str, Any], income: int) -> Mapping[str, Any]:
    """The zone whose income range contains ``income`` (already rounded to whole euros)."""
    for zone in parameters["zones"]:
        if zone.get("upper") is None or income <= int(zone["upper"]):
            return zone
    raise ValueError(f"no tariff zone covers {income}")


def tariff(parameters: Mapping[str, Any], taxable_income: Any) -> int:
    """Tariff income tax in whole euros for one taxable income (§ 32a(1))."""
    income = max(0, _euros(_decimal(taxable_income)))
    zone = zone_for(parameters, income)
    formula = zone["formula"]
    if formula == "zero":
        return 0
    x = Decimal(income)
    if formula == "quadratic":
        u = (x - _decimal(zone["offset"])) / _TEN_THOUSAND
        tax = (_decimal(zone["a"]) * u + _decimal(zone["b"])) * u + _decimal(zone.get("c", 0))
    elif formula == "linear":
        tax = _decimal(zone["rate"]) * x - _decimal(zone["deduction"])
    else:
        raise ValueError(f"unknown tariff formula {formula!r}")
    return max(0, _euros(tax))


def splitting(parameters: Mapping[str, Any], joint_taxable_income: Any) -> int:
    """Tax for spouses assessed jointly: twice the tariff on half the joint taxable income (§ 32a(5))."""
    return 2 * tariff(parameters, _decimal(joint_taxable_income) / 2)


def evaluate(parameters: Mapping[str, Any], value: Any) -> int:
    if isinstance(value, Mapping):
        income = value["income"]
        return splitting(parameters, income) if value.get("splitting") else tariff(parameters, income)
    return tariff(parameters, value)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["zones"])
    if stat.name == "tax" and len(stat.args) == 1:
        return tariff(parameters, stat.args[0])
    if stat.name == "splitting" and len(stat.args) == 1:
        return splitting(parameters, stat.args[0])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

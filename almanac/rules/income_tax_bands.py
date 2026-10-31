"""Progressive income tax bands with a tapered personal allowance.

The parameters describe a tax-free allowance, how it tapers above an income
threshold, and the bands of taxable income with their rates. The rule
computes the allowance and the tax due for a yearly income, which is what a
payroll or personal-finance generator needs to produce consistent records.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_PENNY = Decimal("0.01")


def personal_allowance(parameters: Mapping[str, Any], income: Decimal) -> Decimal:
    """Allowance after tapering: reduced by one unit for every ``taper_ratio`` units above the threshold."""
    allowance = Decimal(str(parameters["personal_allowance"]))
    taper = parameters.get("taper")
    if taper and income > Decimal(str(taper["above"])):
        reduction = (income - Decimal(str(taper["above"]))) / Decimal(str(taper["ratio"]))
        allowance = max(Decimal(0), allowance - reduction)
    return allowance


def tax_due(parameters: Mapping[str, Any], income: Decimal | str | float) -> Decimal:
    """Tax on ``income`` for the year, applying the allowance then each band in order."""
    total_income = Decimal(str(income))
    taxable = max(Decimal(0), total_income - personal_allowance(parameters, total_income))
    tax = Decimal(0)
    lower = Decimal(0)
    for band in parameters["bands"]:
        upper = Decimal(str(band["up_to"])) if band.get("up_to") is not None else None
        rate = Decimal(str(band["rate_percent"])) / Decimal(100)
        slice_top = taxable if upper is None else min(taxable, upper)
        if slice_top > lower:
            tax += (slice_top - lower) * rate
        if upper is None or taxable <= upper:
            break
        lower = upper
    return tax.quantize(_PENNY, rounding=ROUND_HALF_UP)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "allowance_for" in value:
        return str(personal_allowance(parameters, Decimal(str(value["allowance_for"]))))
    income = value["income"] if isinstance(value, Mapping) else value
    return str(tax_due(parameters, income))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["bands"])
    if stat.name == "rate" and len(stat.args) == 1:
        return next(b["rate_percent"] for b in parameters["bands"] if b["name"] == stat.args[0])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

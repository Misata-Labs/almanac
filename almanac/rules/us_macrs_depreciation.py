"""MACRS depreciation by the IRS percentage tables.

IRS Publication 946 Appendix A gives, for each recovery period, the share of
the unadjusted basis deductible in each year of recovery. The parameters hold
one list of percentages per recovery period, year one first; the rule returns
the rate for a year and, given a basis, the deduction rounded to whole
dollars as the publication's worked examples show it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic


def _rates(parameters: Mapping[str, Any], recovery_period: str) -> list[Any]:
    try:
        return list(parameters["rates"][recovery_period])
    except KeyError as exc:
        raise KeyError(f"no table for recovery period {recovery_period!r}") from exc


def rate(parameters: Mapping[str, Any], recovery_period: str, year: int) -> Decimal:
    """Percentage of the unadjusted basis deductible in recovery ``year`` (1-based); zero after the last year."""
    rates = _rates(parameters, recovery_period)
    if year < 1:
        raise ValueError("recovery years start at 1")
    return Decimal(str(rates[year - 1])) if year <= len(rates) else Decimal(0)


def deduction(parameters: Mapping[str, Any], basis: Any, recovery_period: str, year: int) -> int:
    """Depreciation deduction for ``year``: the basis times the table percentage, rounded to whole dollars."""
    amount = Decimal(str(basis)) * rate(parameters, recovery_period, year) / 100
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    period, year = str(value["recovery_period"]), int(value["year"])
    if "basis" in value:
        return deduction(parameters, value["basis"], period, year)
    return float(rate(parameters, period, year))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    tables = parameters["rates"]
    if stat.name == "count" and not stat.args:
        return len(tables)
    if stat.name == "years" and len(stat.args) == 1:
        return len(tables[stat.args[0]])
    if stat.name == "total" and len(stat.args) == 1:
        return float(sum(Decimal(str(r)) for r in tables[stat.args[0]]))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

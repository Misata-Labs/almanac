"""UK income tax treatment of carried interest from the 2026-27 tax year (ITTOIA 2005 s. 23I and Sch. A1).

Carried interest arising to an individual who performs investment management
services is treated as the profits of a deemed trade. The profits are the
non-qualifying carried interest plus a fixed fraction of the qualifying
carried interest, each net of its share of permitted deductions. The share of
a sum that is qualifying depends on the investment scheme's average holding
period, by a table of month bands.

Parameters: ``qualifying_fraction_percent`` (the fraction of qualifying
profits taxed) and ``holding_period_bands`` (rows with ``min_months``,
exclusive ``max_months`` or null, and ``qualifying_percent``).

``evaluate`` takes ``average_holding_months`` and returns the qualifying
percentage, or with ``carried_interest`` (and optional
``permitted_deductions``) returns the amount treated as trading profits. The
exceptions that treat carried interest as wholly qualifying, the territorial
rules and the averaging adjustments are not modelled.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from almanac.models import Statistic


def qualifying_percent(parameters: Mapping[str, Any], average_holding_months: Decimal) -> Decimal:
    for band in parameters["holding_period_bands"]:
        lower = Decimal(str(band["min_months"]))
        upper = band.get("max_months")
        if average_holding_months >= lower and (upper is None or average_holding_months < Decimal(str(upper))):
            return Decimal(str(band["qualifying_percent"]))
    raise ValueError(f"no band covers an average holding period of {average_holding_months} months")


def trading_profits(parameters: Mapping[str, Any], carried_interest: Decimal, average_holding_months: Decimal, permitted_deductions: Decimal = Decimal(0)) -> Decimal:
    """Amount treated as profits of the deemed trade for the tax year."""
    share = qualifying_percent(parameters, average_holding_months) / 100
    net = carried_interest - permitted_deductions
    qualifying = net * share
    non_qualifying = net - qualifying
    return non_qualifying + qualifying * Decimal(str(parameters["qualifying_fraction_percent"])) / 100


def _plain(value: Decimal) -> int | float:
    value = value.quantize(Decimal("0.01"))
    return int(value) if value == value.to_integral_value() else float(value)


def evaluate(parameters: Mapping[str, Any], value: Any) -> int | float:
    months = Decimal(str(value["average_holding_months"]))
    if "carried_interest" not in value:
        return _plain(qualifying_percent(parameters, months))
    return _plain(trading_profits(parameters, Decimal(str(value["carried_interest"])), months, Decimal(str(value.get("permitted_deductions", 0)))))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["holding_period_bands"])
    if stat.name == "qualifying_fraction_percent" and not stat.args:
        return float(parameters["qualifying_fraction_percent"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

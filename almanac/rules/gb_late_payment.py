"""Statutory compensation and interest on late commercial payments in the United Kingdom.

The Late Payment of Commercial Debts (Interest) Act 1998 entitles a supplier to
a fixed sum for each late qualifying debt, banded by the size of the debt
(section 5A), and to statutory interest at a margin over the Bank of England's
official dealing rate (Bank Rate). The Late Payment of Commercial Debts (Rate
of Interest) (No. 3) Order 2002 fixes the reference day: the rate in force on
30 June applies to interest that starts to run from 1 July to 31 December, and
the rate in force on 31 December to interest that starts to run from 1 January
to 30 June.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from almanac.models import Statistic


def fixed_sum(debt: Any, parameters: Mapping[str, Any]) -> int | float:
    """The fixed sum due for a late debt of ``debt`` pounds."""
    amount = Decimal(str(debt))
    for band in parameters["fixed_sums"]:
        if band.get("below") is None or amount < Decimal(str(band["below"])):
            return band["sum"]
    raise ValueError("fixed_sums must end with an open band")


def reference_day(interest_starts: Any) -> date:
    """The day whose official dealing rate sets the statutory rate for interest starting on ``interest_starts``."""
    start = date.fromisoformat(str(interest_starts))
    return date(start.year, 6, 30) if start.month >= 7 else date(start.year - 1, 12, 31)


def statutory_rate(official_dealing_rate: Any, parameters: Mapping[str, Any]) -> float:
    """Statutory interest in percent a year given the official dealing rate in force on the reference day."""
    return float(Decimal(str(parameters["margin_percent"])) + Decimal(str(official_dealing_rate)))


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if "debt" in value:
        return fixed_sum(value["debt"], parameters)
    if "official_dealing_rate" in value:
        return statutory_rate(value["official_dealing_rate"], parameters)
    return reference_day(value["interest_starts"]).isoformat()


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["fixed_sums"])
    if stat.name == "margin_percent" and not stat.args:
        return parameters["margin_percent"]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

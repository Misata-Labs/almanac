"""HHS poverty guidelines: the annual income guideline for a household size.

The Department of Health and Human Services publishes one table for the 48
contiguous states and the District of Columbia and one each for Alaska and
Hawaii. Each table lists household sizes one to eight; larger households add
a fixed amount for each person beyond eight. Programmes express eligibility
as a percentage of the guideline (138 percent, 200 percent and so on), so the
rule also reports income as a percentage of the guideline.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic


def _area(parameters: Mapping[str, Any], area: str) -> Mapping[str, Any]:
    try:
        return parameters["areas"][area]
    except KeyError as exc:
        raise KeyError(f"unknown guideline area {area!r}") from exc


def guideline(parameters: Mapping[str, Any], area: str, persons: int) -> int:
    """Poverty guideline in dollars for ``persons`` in a family or household in ``area``."""
    if persons < 1:
        raise ValueError("a household has at least one person")
    table = _area(parameters, area)
    listed = {int(size): int(amount) for size, amount in table["guidelines"].items()}
    largest = max(listed)
    if persons <= largest:
        return listed[persons]
    return listed[largest] + (persons - largest) * int(table["additional_person"])


def percent_of_guideline(parameters: Mapping[str, Any], area: str, persons: int, income: Any) -> Decimal:
    """Household income as a percentage of its guideline, to two decimal places."""
    share = Decimal(str(income)) * 100 / Decimal(guideline(parameters, area, persons))
    return share.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    area, persons = value["area"], int(value["persons"])
    if "income" in value:
        return str(percent_of_guideline(parameters, area, persons, value["income"]))
    return guideline(parameters, area, persons)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["areas"])
    if stat.name == "guideline" and len(stat.args) == 2:
        return guideline(parameters, stat.args[0], int(stat.args[1]))
    if stat.name == "additional_person" and len(stat.args) == 1:
        return int(_area(parameters, stat.args[0])["additional_person"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

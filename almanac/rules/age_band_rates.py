"""Rates that depend on an age band and an effective date, such as minimum wages.

The parameters list rate tables by effective date; each table maps a band
(an age range or a special category such as apprentice) to an hourly rate.
The rule returns the rate for a worker's age on a date.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from almanac.models import Statistic


def table_on(parameters: Mapping[str, Any], day: date) -> Mapping[str, Any]:
    tables = sorted(parameters["tables"], key=lambda t: t["from"])
    chosen = [t for t in tables if date.fromisoformat(str(t["from"])) <= day]
    if not chosen:
        raise ValueError(f"no rate table in force on {day}")
    return chosen[-1]


def band_for(parameters: Mapping[str, Any], age: int, category: str | None = None) -> str:
    if category:
        return category
    for band in parameters["bands"]:
        low, high = band.get("min_age", 0), band.get("max_age")
        if age >= low and (high is None or age <= high):
            return band["name"]
    raise ValueError(f"no band covers age {age}")


def rate(parameters: Mapping[str, Any], age: int, day: date, category: str | None = None) -> Any:
    """Hourly rate for ``age`` (or the special ``category``) on ``day``."""
    return table_on(parameters, day)["rates"][band_for(parameters, age, category)]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    return rate(parameters, int(value["age"]), date.fromisoformat(str(value["on"])), value.get("category"))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["tables"])
    if stat.name == "rate" and len(stat.args) == 2:
        return table_on(parameters, date.fromisoformat(stat.args[1]))["rates"][stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

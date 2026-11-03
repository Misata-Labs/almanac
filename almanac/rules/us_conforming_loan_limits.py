"""FHFA conforming loan limits by county and number of units.

Most US counties carry the national baseline limit; high-cost areas and the
statutorily designated areas carry a higher one. The parameters list every
county by its five-digit FIPS code, the baseline limits by unit count, and
the limits of the counties above the baseline. The rule returns the limit for
a county and unit count, and whether a loan amount is within it.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic

UNIT_COLUMNS = {1: "one_unit", 2: "two_unit", 3: "three_unit", 4: "four_unit"}


def limit(parameters: Mapping[str, Any], fips: str, units: int = 1) -> int:
    """Loan limit in dollars for a property of ``units`` units (one to four) in county ``fips``."""
    if fips not in parameters["counties"]:
        raise KeyError(f"no county with FIPS code {fips!r}")
    try:
        column = UNIT_COLUMNS[units]
    except KeyError as exc:
        raise ValueError("conforming loan limits cover one to four units") from exc
    row = parameters["above_baseline"].get(fips, parameters["baseline"])
    return int(row[column])


def is_conforming(parameters: Mapping[str, Any], fips: str, amount: Any, units: int = 1) -> bool:
    return float(amount) <= limit(parameters, fips, units)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    fips, units = str(value["fips"]), int(value.get("units", 1))
    if "amount" in value:
        return is_conforming(parameters, fips, value["amount"], units)
    return limit(parameters, fips, units)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["counties"])
    if stat.name == "above_baseline" and not stat.args:
        return len(parameters["above_baseline"])
    if stat.name == "max" and len(stat.args) == 1:
        rows = [*parameters["above_baseline"].values(), parameters["baseline"]]
        return max(int(row[stat.args[0]]) for row in rows)
    if stat.name == "limit" and len(stat.args) == 2:
        return limit(parameters, stat.args[0], int(stat.args[1]))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

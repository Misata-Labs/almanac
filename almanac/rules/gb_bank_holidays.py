"""United Kingdom bank holiday calendar rule.

Bank holidays differ between England and Wales, Scotland, and Northern
Ireland. The parameters hold the published dates per division and year;
the rule answers whether a date is a bank holiday in a division.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from almanac.models import Statistic


def holidays(parameters: Mapping[str, Any], division: str, year: int) -> list[dict[str, Any]]:
    """Return the published holiday records for ``division`` in ``year``."""
    try:
        return list(parameters["divisions"][division][str(year)])
    except KeyError as exc:
        raise KeyError(f"no published bank holidays for {division} {year}") from exc


def is_bank_holiday(day: date, parameters: Mapping[str, Any], division: str) -> bool:
    return any(record["date"] == day.isoformat() for record in holidays(parameters, division, day.year))


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    day = date.fromisoformat(str(value["date"]))
    return is_bank_holiday(day, parameters, str(value["division"]))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> int:
    if stat.name == "count" and len(stat.args) == 2:
        return len(holidays(parameters, stat.args[0], int(stat.args[1])))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

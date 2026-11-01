"""United States legal public holidays, 5 U.S.C. 6103, with the observed-day rules.

Holidays are either a fixed date or an ordinal weekday of a month. For a
Monday-to-Friday workweek a holiday falling on Saturday is observed on the
Friday before and one falling on Sunday on the Monday after, as the
statute and 5 CFR 610.202 provide.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Mapping

from almanac.models import Statistic

_WEEKDAYS = {name.lower(): index for index, name in enumerate(calendar.day_name)}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def _nth_weekday(year: int, month: int, weekday: str, ordinal: str) -> date:
    target = _WEEKDAYS[weekday.lower()]
    if ordinal == "last":
        last = date(year, month, calendar.monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - target) % 7)
    first = date(year, month, 1)
    offset = (target - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (_ORDINALS[ordinal] - 1))


def holiday_date(holiday: Mapping[str, Any], year: int) -> date:
    """The statutory date of ``holiday`` in ``year``, before any observance shift."""
    if "day" in holiday:
        return date(year, int(holiday["month"]), int(holiday["day"]))
    return _nth_weekday(year, int(holiday["month"]), holiday["weekday"], holiday["ordinal"])


def observed_date(holiday_day: date, parameters: Mapping[str, Any]) -> date:
    rules = parameters.get("observance", {})
    if holiday_day.weekday() == 5 and rules.get("saturday") == "preceding_friday":
        return holiday_day - timedelta(days=1)
    if holiday_day.weekday() == 6 and rules.get("sunday") == "following_monday":
        return holiday_day + timedelta(days=1)
    return holiday_day


def holidays(parameters: Mapping[str, Any], year: int) -> list[dict[str, Any]]:
    """Every holiday of ``year`` with its statutory and observed dates."""
    out = []
    for holiday in parameters["holidays"]:
        day = holiday_date(holiday, year)
        out.append({"name": holiday["name"], "date": day.isoformat(), "observed": observed_date(day, parameters).isoformat()})
    return out


def is_holiday(day: date, parameters: Mapping[str, Any], observed: bool = True) -> bool:
    key = "observed" if observed else "date"
    return any(h[key] == day.isoformat() for h in holidays(parameters, day.year))


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "year" in value and "name" in value:
        return next(h for h in holidays(parameters, int(value["year"])) if h["name"] == value["name"])
    if isinstance(value, Mapping):
        return is_holiday(date.fromisoformat(str(value["date"])), parameters, bool(value.get("observed", True)))
    return is_holiday(date.fromisoformat(str(value)), parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["holidays"])
    if stat.name == "count" and len(stat.args) == 1:
        return len({h["observed"] for h in holidays(parameters, int(stat.args[0]))})
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

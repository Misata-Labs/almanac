"""United Kingdom clock-change (British Summer Time) calendar rule.

The clocks go forward on the last Sunday in March and back on the last
Sunday in October. The rule computes both dates for a year from that
ordinal-weekday description so published dates can be checked against it.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Mapping

_WEEKDAYS = {name.lower(): index for index, name in enumerate(calendar.day_name)}


def last_weekday_of_month(year: int, month: int, weekday: str) -> date:
    last_day = calendar.monthrange(year, month)[1]
    target = _WEEKDAYS[weekday.lower()]
    candidate = date(year, month, last_day)
    return candidate.replace(day=last_day - (candidate.weekday() - target) % 7)


def transition(parameters: Mapping[str, Any], year: int, which: str) -> date:
    """Return the ``forward`` or ``back`` transition date for ``year``."""
    spec = parameters["transitions"][which]
    if spec["ordinal"] != "last":
        raise ValueError(f"unsupported ordinal {spec['ordinal']!r}")
    return last_weekday_of_month(year, int(spec["month"]), spec["weekday"])


def clock_changes(parameters: Mapping[str, Any], year: int) -> dict[str, str]:
    return {which: transition(parameters, year, which).isoformat() for which in ("forward", "back")}


def is_summer_time(day: date, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``day`` falls inside British Summer Time, counting both transition days."""
    forward = transition(parameters, day.year, "forward")
    back = transition(parameters, day.year, "back")
    return forward <= day <= back


def evaluate(parameters: Mapping[str, Any], value: Any) -> dict[str, str]:
    return clock_changes(parameters, int(value["year"]))

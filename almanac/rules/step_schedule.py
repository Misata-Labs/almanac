"""Step schedule rule: a value that changes on announced dates.

Policy rates, reference rates and administered prices move in steps. The
parameters list each step with the first date it applies; the rule answers
which value was in force on a date and how many steps the schedule has.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import Any, Mapping

from almanac.models import Statistic


def _steps(parameters: Mapping[str, Any]) -> list[tuple[date, Any]]:
    steps = sorted((date.fromisoformat(str(s["from"])), s["value"]) for s in parameters["steps"])
    return steps


def value_on(parameters: Mapping[str, Any], day: date) -> Any:
    """Return the value in force on ``day``; raises if ``day`` precedes the first step."""
    steps = _steps(parameters)
    index = bisect_right([d for d, _ in steps], day)
    if index == 0:
        raise ValueError(f"{day} precedes the first step {steps[0][0]}")
    return steps[index - 1][1]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    day = date.fromisoformat(str(value["on"] if isinstance(value, Mapping) else value))
    return value_on(parameters, day)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    steps = _steps(parameters)
    if stat.name == "count" and not stat.args:
        return len(steps)
    if stat.name == "value" and len(stat.args) == 1:
        return value_on(parameters, date.fromisoformat(stat.args[0]))
    if stat.name in ("min", "max") and not stat.args:
        values = [float(v) for _, v in steps]
        return min(values) if stat.name == "min" else max(values)
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

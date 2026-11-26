"""United States additional first-year (bonus) depreciation percentage (26 U.S.C. 168(k)).

The percentage of the adjusted basis of qualified property deductible in the
year it is placed in service depends on when the property was acquired and
when it was placed in service. Property acquired after ``full_expensing_acquired_after``
takes ``full_expensing_percent`` whenever it is placed in service. Property
acquired earlier follows the phase-down schedule by placed-in-service date in
``phase_down``, with a separate schedule for property with a longer production
period (and certain aircraft) described in section 168(k)(2)(B) and (C).

``evaluate`` takes ``acquired`` and ``placed_in_service`` dates and an optional
``longer_production_period`` flag, and returns the percentage; a placed-in-service
date after the last phase-down window gives 0. Elections out of bonus
depreciation and the transitional election of a reduced percentage are not
modelled.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from almanac.models import Statistic


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def percent(parameters: Mapping[str, Any], acquired: date, placed_in_service: date, longer_production_period: bool = False) -> int:
    if placed_in_service < acquired:
        raise ValueError("property cannot be placed in service before it is acquired")
    if acquired > _day(parameters["full_expensing_acquired_after"]):
        return int(parameters["full_expensing_percent"])
    schedule = parameters["phase_down"]["longer_production_period" if longer_production_period else "general"]
    windows = sorted(schedule, key=lambda w: _day(w["placed_in_service_after"]))
    if placed_in_service <= _day(windows[0]["placed_in_service_after"]):
        raise ValueError(f"property placed in service on {placed_in_service} precedes the schedule")
    for window in windows:
        if _day(window["placed_in_service_after"]) < placed_in_service < _day(window["placed_in_service_before"]):
            return int(window["percent"])
    return 0


def evaluate(parameters: Mapping[str, Any], value: Any) -> int:
    return percent(parameters, _day(value["acquired"]), _day(value["placed_in_service"]), bool(value.get("longer_production_period", False)))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and len(stat.args) == 1:
        return len(parameters["phase_down"][stat.args[0]])
    if stat.name == "full_expensing_percent" and not stat.args:
        return int(parameters["full_expensing_percent"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

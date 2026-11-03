"""Classification of Indian enterprises as micro, small or medium.

Under the Micro, Small and Medium Enterprises Development Act, 2006 the
Central Government notifies ceilings on investment in plant and machinery or
equipment and on annual turnover for each category. Both ceilings apply
together: an enterprise belongs to the smallest category whose ceilings it
does not exceed on either criterion, and an enterprise above the medium
ceilings is not an MSME. The parameters hold each notified set of ceilings
with the date it took effect, so a record can be classified as of any date.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from almanac.models import Statistic

CATEGORIES = ("micro", "small", "medium")
NOT_MSME = "not_msme"


def ceilings_on(parameters: Mapping[str, Any], day: date) -> Mapping[str, Mapping[str, Any]]:
    """The ceilings in force on ``day``; raises if ``day`` precedes the first notified set."""
    schedules = sorted(parameters["schedules"], key=lambda s: date.fromisoformat(str(s["from"])))
    current = None
    for schedule in schedules:
        if date.fromisoformat(str(schedule["from"])) <= day:
            current = schedule
    if current is None:
        raise ValueError(f"{day} precedes the first notified classification")
    return current["ceilings"]


def classify(parameters: Mapping[str, Any], investment: Any, turnover: Any, day: date) -> str:
    """Category of an enterprise with the given investment and turnover (in rupees) on ``day``."""
    investment, turnover = Decimal(str(investment)), Decimal(str(turnover))
    ceilings = ceilings_on(parameters, day)
    for category in CATEGORIES:
        limit = ceilings[category]
        if investment <= Decimal(str(limit["investment"])) and turnover <= Decimal(str(limit["turnover"])):
            return category
    return NOT_MSME


def evaluate(parameters: Mapping[str, Any], value: Any) -> str:
    return classify(parameters, value["investment"], value["turnover"], date.fromisoformat(str(value["on"])))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["schedules"])
    if stat.name == "ceiling" and len(stat.args) == 3:
        day, category, criterion = stat.args
        return ceilings_on(parameters, date.fromisoformat(day))[category][criterion]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

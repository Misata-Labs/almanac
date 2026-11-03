"""Regulation F telephone call frequency presumptions for debt collectors (12 CFR 1006.14(b)).

A debt collector is presumed to comply with the ban on repeated or continuous
calls when, for one person and one debt, it neither places more than a set
number of calls within a run of consecutive days nor calls within a run of
consecutive days after a telephone conversation, the conversation day counting
as the first day. Calls that the regulation excludes (made with the person's
direct prior consent, not connected, or to the persons listed in 1006.6(d))
should be left out of the call history before it is passed in.

The rule also answers whether a local time at the consumer's location falls
outside the hours that 12 CFR 1006.6(b)(1)(i) treats as convenient by default.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any, Iterable, Mapping

from almanac.models import Statistic


def _dates(values: Iterable[Any]) -> list[date]:
    return [date.fromisoformat(str(v)) for v in values]


def presumed_compliant(calls: Iterable[Any], conversations: Iterable[Any], proposed: Any, parameters: Mapping[str, Any]) -> bool:
    """Whether placing a call on ``proposed`` keeps both call frequencies within the presumption of compliance.

    ``calls`` lists the dates of earlier counted calls to the person about the debt, one item per call;
    ``conversations`` lists the dates of telephone conversations with the person about the debt.
    """
    day = date.fromisoformat(str(proposed))
    window = timedelta(days=int(parameters["call_window_days"]) - 1)
    in_window = sum(1 for d in _dates(calls) if day - window <= d <= day)
    if in_window + 1 > int(parameters["max_calls_in_window"]):
        return False
    quiet = timedelta(days=int(parameters["post_conversation_days"]) - 1)
    return not any(c <= day <= c + quiet for c in _dates(conversations))


def is_inconvenient_time(local_time: Any, parameters: Mapping[str, Any]) -> bool:
    """Whether a local time at the consumer's location is presumed inconvenient for communication."""
    moment = local_time if isinstance(local_time, time) else time.fromisoformat(str(local_time))
    earliest = time.fromisoformat(str(parameters["convenient_from"]))
    latest = time.fromisoformat(str(parameters["convenient_until"]))
    return moment < earliest or moment > latest


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    if "local_time" in value:
        return is_inconvenient_time(value["local_time"], parameters)
    return presumed_compliant(value.get("calls", []), value.get("conversations", []), value["proposed"], parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name in ("max_calls_in_window", "call_window_days", "post_conversation_days") and not stat.args:
        return int(parameters[stat.name])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

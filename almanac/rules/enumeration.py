"""Membership rule for published code lists.

Many official sources publish closed vocabularies: company types, account
statuses, filing categories. The parameters hold one or more named sets of
code to label; the rule answers whether a code belongs to a set, and can
report each set's size.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def codes(parameters: Mapping[str, Any], set_name: str) -> dict[str, str]:
    try:
        return dict(parameters["sets"][set_name])
    except KeyError as exc:
        raise KeyError(f"unknown code set {set_name!r}") from exc


def is_member(code: str, parameters: Mapping[str, Any], set_name: str) -> bool:
    return code in codes(parameters, set_name)


def label(code: str, parameters: Mapping[str, Any], set_name: str) -> str:
    return codes(parameters, set_name)[code]


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_member(str(value["value"]), parameters, str(value["set"]))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> int:
    if stat.name == "count" and len(stat.args) == 1:
        return len(codes(parameters, stat.args[0]))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

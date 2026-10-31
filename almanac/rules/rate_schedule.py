"""Named rate schedule rule.

A schedule is a small set of named percentage rates in force together, such
as the slabs of a value-added tax. The rule answers whether a percentage is
one of the published rates, names the rate, and reports the schedule's size.
Entries may add context such as carve-outs or effective dates alongside the
slabs; the rule itself only reads ``slabs``.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def slabs(parameters: Mapping[str, Any]) -> dict[str, float]:
    return {name: float(rate) for name, rate in parameters["slabs"].items()}


def is_slab(rate: float, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``rate`` (a percentage) is one of the published rates."""
    return float(rate) in set(slabs(parameters).values())


def slab_name(rate: float, parameters: Mapping[str, Any]) -> str:
    for name, value in slabs(parameters).items():
        if value == float(rate):
            return name
    raise KeyError(f"{rate}% is not a published slab")


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_slab(float(value), parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["slabs"])
    if stat.name == "slab" and len(stat.args) == 1:
        return slabs(parameters)[stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

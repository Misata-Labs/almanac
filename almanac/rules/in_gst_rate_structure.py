"""India GST rate structure rule.

The rule holds the rate slabs the GST Council has decided on, with the date
they took effect, and answers whether a given percentage is a slab in force.
Goods the Council has explicitly carved out of a change keep their earlier
rates; the parameters name those carve-outs so generators can respect them.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def slabs(parameters: Mapping[str, Any]) -> dict[str, float]:
    return {name: float(rate) for name, rate in parameters["slabs"].items()}


def is_slab(rate: float, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``rate`` (a percentage) is one of the published slabs."""
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

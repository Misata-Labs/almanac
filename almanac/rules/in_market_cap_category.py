"""Large, mid and small cap categories for Indian mutual fund portfolios.

SEBI defines the equity investment universe of mutual funds by rank in full
market capitalisation: the parameters list each category with the first and
last rank it covers (the last left open for the smallest category). The rule
names the category of a company from its rank in the list AMFI publishes.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def category(parameters: Mapping[str, Any], rank: int) -> str:
    """Category of the company ranked ``rank`` (1 is the largest) by full market capitalisation."""
    if rank < 1:
        raise ValueError(f"rank must be at least 1, got {rank}")
    for band in parameters["bands"]:
        if rank >= int(band["from_rank"]) and (band["to_rank"] is None or rank <= int(band["to_rank"])):
            return str(band["name"])
    raise ValueError(f"no category covers rank {rank}")


def evaluate(parameters: Mapping[str, Any], value: Any) -> str:
    rank = value["rank"] if isinstance(value, Mapping) else value
    return category(parameters, int(rank))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["bands"])
    if stat.name == "last_rank" and len(stat.args) == 1:
        return next(b["to_rank"] for b in parameters["bands"] if b["name"] == stat.args[0])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

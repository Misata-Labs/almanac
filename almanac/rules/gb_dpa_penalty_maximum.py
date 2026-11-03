"""Maximum penalty under the UK data protection regime (Data Protection Act 2018, section 157).

Each infringement carries either the higher or the standard maximum amount.
For an undertaking the maximum is a fixed sum or a share of its total annual
worldwide turnover in the preceding financial year, whichever is higher; for
anyone else it is the fixed sum alone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from almanac.models import Statistic


def maximum_penalty(tier: str, parameters: Mapping[str, Any], undertaking: bool = False, turnover: Any = None) -> Decimal:
    """The maximum penalty in pounds for ``tier`` ('higher' or 'standard')."""
    level = parameters["tiers"][tier]
    fixed = Decimal(str(level["fixed_gbp"]))
    if not undertaking:
        return fixed
    if turnover is None:
        raise ValueError("an undertaking's maximum depends on its worldwide turnover")
    share = Decimal(str(turnover)) * Decimal(str(level["turnover_percent"])) / 100
    return max(fixed, share)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Decimal:
    return maximum_penalty(str(value["tier"]), parameters, bool(value.get("undertaking", False)), value.get("turnover"))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "value" and len(stat.args) == 2:
        return parameters["tiers"][stat.args[0]][stat.args[1]]
    if stat.name == "count" and not stat.args:
        return len(parameters["tiers"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

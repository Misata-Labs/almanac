"""ERISA plan-asset significant participation test (29 CFR 2510.3-101(f)).

Equity participation in an entity by benefit plan investors is significant
when, immediately after the most recent acquisition of an equity interest,
benefit plan investors hold the threshold percentage or more of the value of
any class of equity interests. Interests held by persons with discretionary
authority or control over the entity's assets, or who give investment advice
for a fee about them, and their affiliates, are disregarded (unless held by a
benefit plan investor), so they are removed from the denominator.

``evaluate`` takes the value held by benefit plan investors, the total value
of the class and the value to disregard, and returns whether participation is
significant, or with ``output: share`` the percentage benefit plan investors
hold after the disregarded interests are removed.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from almanac.models import Statistic


def share_percent(benefit_plan_value: Decimal, total_value: Decimal, disregarded_value: Decimal = Decimal(0)) -> Decimal:
    """Benefit plan investors' share of the class, in percent, with disregarded interests excluded."""
    counted = total_value - disregarded_value
    if counted <= 0:
        raise ValueError("the class has no value left once disregarded interests are excluded")
    if benefit_plan_value > counted:
        raise ValueError("benefit plan investors cannot hold more than the counted value of the class")
    return benefit_plan_value / counted * 100


def is_significant(parameters: Mapping[str, Any], benefit_plan_value: Decimal, total_value: Decimal, disregarded_value: Decimal = Decimal(0)) -> bool:
    return share_percent(benefit_plan_value, total_value, disregarded_value) >= Decimal(str(parameters["threshold_percent"]))


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool | float:
    figures = [Decimal(str(value.get(key, 0))) for key in ("benefit_plan_value", "total_value", "disregarded_value")]
    if value.get("output") == "share":
        return float(share_percent(*figures).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return is_significant(parameters, *figures)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "threshold_percent" and not stat.args:
        return float(parameters["threshold_percent"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

"""United States qualified small business stock gain exclusion (26 U.S.C. 1202).

A non-corporate taxpayer excludes from gross income a percentage of the gain
on qualified small business stock. The percentage depends on when the stock
was acquired and how long it was held, and the gain eligible for exclusion
from one issuer is capped at the greater of a dollar limit (reduced by
eligible gain from that issuer already taken into account) and a multiple of
the adjusted basis of the stock disposed of in the year.

Parameters:

* ``acquisition_periods``: the exclusion for stock acquired on or before the
  applicable date, by acquisition window, each with a percentage and a
  holding period the stock must exceed (``more_than_years``).
* ``applicable_date``: stock acquired after it follows ``holding_schedule``,
  a table of whole years held (at least) to percentage.
* ``dollar_limit``: the per-issuer cap before and after the applicable date.
* ``basis_multiple``: the multiple of adjusted basis in the alternative cap.

``evaluate`` takes ``acquired`` and ``sold`` dates and returns the exclusion
percentage, or with ``gain`` (and ``adjusted_basis``, ``prior_eligible_gain``)
the excluded amount. The empowerment-zone and AMT rules are not modelled, and
the dollar limit for post-applicable-date stock is not reduced for same-year
gain on older stock of the same issuer.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from almanac.models import Statistic


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _anniversary(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year + years, day=28)


def whole_years_held(acquired: date, sold: date) -> int:
    """Complete years from the acquisition date to the sale date."""
    years = sold.year - acquired.year
    return years if _anniversary(acquired, years) <= sold else years - 1


def acquired_after_applicable_date(parameters: Mapping[str, Any], acquired: date) -> bool:
    return acquired > _day(parameters["applicable_date"])


def exclusion_percent(parameters: Mapping[str, Any], acquired: date, sold: date) -> int:
    """Percentage of eligible gain excluded; 0 when the holding period is not met."""
    if sold <= acquired:
        raise ValueError("the sale date must follow the acquisition date")
    if acquired_after_applicable_date(parameters, acquired):
        held = whole_years_held(acquired, sold)
        qualifying = [row for row in parameters["holding_schedule"] if held >= int(row["years_held"])]
        return max((int(row["percent"]) for row in qualifying), default=0)
    for period in parameters["acquisition_periods"]:
        if _day(period["acquired_after"]) < acquired <= _day(period["acquired_on_or_before"]):
            return int(period["percent"]) if sold > _anniversary(acquired, int(period["more_than_years"])) else 0
    raise ValueError(f"stock acquired on {acquired} is outside the periods the section covers")


def gain_cap(parameters: Mapping[str, Any], acquired: date, adjusted_basis: Decimal, prior_eligible_gain: Decimal) -> Decimal:
    """Per-issuer cap on eligible gain: the greater of the remaining dollar limit and the basis multiple."""
    era = "after_applicable_date" if acquired_after_applicable_date(parameters, acquired) else "on_or_before_applicable_date"
    remaining = max(Decimal(0), Decimal(str(parameters["dollar_limit"][era])) - prior_eligible_gain)
    return max(remaining, Decimal(str(parameters["basis_multiple"])) * adjusted_basis)


def excluded_gain(parameters: Mapping[str, Any], acquired: date, sold: date, gain: Decimal, adjusted_basis: Decimal, prior_eligible_gain: Decimal = Decimal(0)) -> Decimal:
    percent = exclusion_percent(parameters, acquired, sold)
    eligible = min(max(gain, Decimal(0)), gain_cap(parameters, acquired, adjusted_basis, prior_eligible_gain))
    return eligible * percent / 100


def evaluate(parameters: Mapping[str, Any], value: Any) -> int | float:
    acquired, sold = _day(value["acquired"]), _day(value["sold"])
    if "gain" not in value:
        return exclusion_percent(parameters, acquired, sold)
    amount = excluded_gain(
        parameters,
        acquired,
        sold,
        Decimal(str(value["gain"])),
        Decimal(str(value.get("adjusted_basis", 0))),
        Decimal(str(value.get("prior_eligible_gain", 0))),
    )
    return int(amount) if amount == amount.to_integral_value() else float(amount.quantize(Decimal("0.01")))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "dollar_limit" and len(stat.args) == 1:
        return parameters["dollar_limit"][stat.args[0]]
    if stat.name == "max_percent" and not stat.args:
        return max(int(row["percent"]) for row in parameters["holding_schedule"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

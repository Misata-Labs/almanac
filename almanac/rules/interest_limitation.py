"""Earnings-based interest limitation rule.

Most interest limitation regimes cap the deduction for interest expense at a
fixed share of a tax measure of earnings, usually a tax EBITDA: the United
States business interest limitation (26 U.S.C. 163(j)), the UK Corporate
Interest Restriction (TIOPA 2010 Part 10), the German Zinsschranke (section
4h EStG) and the Dutch earnings-stripping rule (article 15b Wet Vpb 1969),
which transpose or parallel article 4 of the EU Anti-Tax Avoidance Directive.

The regimes share one formula and differ in their parameters:

* ``ratio_percent``: the share of the earnings base that may be absorbed.
* Interest income (and, in the United States, floor plan financing interest)
  is always deductible against interest expense; only the excess is limited.
* ``allowance_floor``: a minimum allowance (the UK de minimis amount, the
  Dutch EUR 1 million threshold); the allowance is the greater of the ratio
  amount and the floor.
* ``exemption_threshold``: a cliff-edge exemption (the German Freigrenze):
  when net interest expense is below the threshold the rule does not apply.
* ``gross_receipts_limit``: a small-business exemption (the US section 448(c)
  test): taxpayers whose average gross receipts do not exceed it are exempt.
* ``depreciation_addback``: dated steps saying whether depreciation and
  amortisation are added back to the earnings base for taxable years that
  begin on or after each date, so a base defined as EBIT in some years and
  EBITDA in others can be expressed.

``evaluate`` takes one taxable year's figures and returns the deductible
interest expense, the disallowed amount (normally carried forward), or the
allowance.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from almanac.models import Statistic

OUTPUTS = ("deductible", "disallowed", "limit")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def _number(value: Decimal) -> int | float:
    """Plain number for comparison with vector expectations: integral values as int, others to the cent."""
    quantised = value.quantize(Decimal("0.01"))
    return int(quantised) if quantised == quantised.to_integral_value() else float(quantised)


def adds_back_depreciation(parameters: Mapping[str, Any], year_start: date | None) -> bool:
    """Whether depreciation and amortisation are added back for a taxable year beginning on ``year_start``."""
    steps = sorted((date.fromisoformat(str(s["from"])), bool(s["value"])) for s in parameters.get("depreciation_addback", []))
    if not steps:
        return True
    if year_start is None:
        raise ValueError("tax_year_start is required when the depreciation add-back depends on the year")
    index = bisect_right([d for d, _ in steps], year_start)
    if index == 0:
        raise ValueError(f"no rule for taxable years beginning {year_start}; the schedule starts {steps[0][0]}")
    return steps[index - 1][1]


def earnings_base(parameters: Mapping[str, Any], figures: Mapping[str, Any]) -> Decimal:
    """The earnings measure the ratio applies to: earnings plus depreciation when the add-back applies."""
    year_start = date.fromisoformat(str(figures["tax_year_start"])) if figures.get("tax_year_start") else None
    base = _decimal(figures.get("earnings"))
    if adds_back_depreciation(parameters, year_start):
        base += _decimal(figures.get("depreciation"))
    return base


def is_exempt(parameters: Mapping[str, Any], figures: Mapping[str, Any]) -> bool:
    """Whether the limitation does not apply at all, by the small-business or the net-interest exemption."""
    receipts_limit = parameters.get("gross_receipts_limit")
    receipts = figures.get("average_gross_receipts")
    if receipts_limit is not None and receipts is not None and _decimal(receipts) <= _decimal(receipts_limit):
        return True
    threshold = parameters.get("exemption_threshold")
    if threshold is not None:
        net = _decimal(figures.get("interest_expense")) - _decimal(figures.get("interest_income"))
        return net < _decimal(threshold)
    return False


def allowance(parameters: Mapping[str, Any], figures: Mapping[str, Any]) -> Decimal:
    """The amount of interest expense in excess of interest income that may be deducted."""
    ratio_amount = max(Decimal(0), earnings_base(parameters, figures) * _decimal(parameters["ratio_percent"]) / 100)
    floor = parameters.get("allowance_floor")
    return max(ratio_amount, _decimal(floor)) if floor is not None else ratio_amount


def limit(parameters: Mapping[str, Any], figures: Mapping[str, Any]) -> Decimal:
    """Total interest expense deductible for the year: interest income, floor plan interest and the allowance."""
    return _decimal(figures.get("interest_income")) + _decimal(figures.get("floor_plan_interest")) + allowance(parameters, figures)


def deductible(parameters: Mapping[str, Any], figures: Mapping[str, Any]) -> Decimal:
    expense = _decimal(figures.get("interest_expense"))
    if is_exempt(parameters, figures):
        return expense
    return min(expense, limit(parameters, figures))


def evaluate(parameters: Mapping[str, Any], value: Any) -> int | float:
    if not isinstance(value, Mapping):
        raise TypeError("interest_limitation vectors take a mapping of the year's figures")
    output = value.get("output", "deductible")
    if output == "deductible":
        return _number(deductible(parameters, value))
    if output == "disallowed":
        return _number(_decimal(value.get("interest_expense")) - deductible(parameters, value))
    if output == "limit":
        return _number(limit(parameters, value))
    raise ValueError(f"output must be one of {', '.join(OUTPUTS)}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "ratio_percent" and not stat.args:
        return float(parameters["ratio_percent"])
    if stat.name in ("allowance_floor", "exemption_threshold", "gross_receipts_limit") and not stat.args:
        return parameters.get(stat.name)
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

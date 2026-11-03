"""Payroll formulas of India's Labour Codes.

The Code on Wages, 2019, the Industrial Relations Code, 2020 and the Code on
Social Security, 2020 state a handful of formulas that every payroll, exit
and HR record in India has to satisfy. The entry parameters carry the
statutory figures and name the formula in ``parameters["formula"]``; this
module applies them:

- ``code_wages``: the wage of section 2(y) of the Code on Wages, which adds
  back excluded allowances above the notified share of total remuneration.
- ``bonus``: the minimum and maximum annual bonus of section 26.
- ``wage_payment``: the payment deadline of section 17 for a wage period and
  the section 18(3) ceiling on deductions.
- ``gratuity``: gratuity under section 53 of the Code on Social Security.
- ``retrenchment``: retrenchment compensation, re-skilling fund credit and
  lay-off compensation under sections 67, 70 and 83 of the Industrial
  Relations Code.

Money is computed in ``Decimal`` and returned as a string rounded to the
paisa, so results compare exactly in test vectors.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_PAISA = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(_PAISA, rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def code_wages(parameters: Mapping[str, Any], included: Any, excluded: Any) -> Decimal:
    """Wages under section 2(y): basic pay, dearness and retaining allowance plus any excess of the excluded items.

    ``included`` is the sum of the components the definition includes and
    ``excluded`` the sum of the payments under clauses (a) to (i) it
    excludes. Where the excluded payments exceed the notified share of all
    remuneration, the excess is deemed remuneration and added to wages.
    """
    included, excluded = _dec(included), _dec(excluded)
    limit = (included + excluded) * _dec(parameters["excluded_share_limit_percent"]) / 100
    return included + max(Decimal(0), excluded - limit)


def bonus_range(parameters: Mapping[str, Any], wages_earned: Any) -> tuple[Decimal, Decimal]:
    """Minimum and maximum bonus for a year's wages: the minimum rate or the floor amount, and the maximum rate."""
    wages = _dec(wages_earned)
    numerator, denominator = parameters["minimum_rate_fraction"]
    minimum = max(wages * _dec(numerator) / _dec(denominator), _dec(parameters["minimum_amount"]))
    maximum = wages * _dec(parameters["maximum_percent"]) / 100
    return minimum, max(minimum, maximum)


def wage_payment_deadline(parameters: Mapping[str, Any], wage_period: str, period_end: date) -> date:
    """Last day on which wages for a wage period ending on ``period_end`` may be paid.

    Daily and weekly wages fall due on the day the period ends (the end of
    the shift, or the last working day before the weekly holiday);
    fortnightly wages by the given number of days after the fortnight;
    monthly wages by the given day of the following month.
    """
    rule = parameters["payment_deadlines"][wage_period]
    if "days_after_period_end" in rule:
        return period_end + timedelta(days=int(rule["days_after_period_end"]))
    if "day_of_following_month" in rule:
        year, month = (period_end.year + 1, 1) if period_end.month == 12 else (period_end.year, period_end.month + 1)
        day = min(int(rule["day_of_following_month"]), calendar.monthrange(year, month)[1])
        return date(year, month, day)
    return period_end


def deduction_ceiling(parameters: Mapping[str, Any], wages: Any) -> Decimal:
    """Largest total of authorised deductions allowed from one wage period's wages."""
    return _dec(wages) * _dec(parameters["deduction_ceiling_percent"]) / 100


def _counted_years(years: int, months: int, part_year_months_above: int) -> int:
    """Completed years plus one for a part year longer than the stated number of months."""
    return years + (1 if months > part_year_months_above else 0)


def gratuity(parameters: Mapping[str, Any], case: Mapping[str, Any]) -> Decimal:
    """Gratuity payable on termination, or zero when the qualifying service is not met.

    ``case`` holds ``monthly_wage`` (last drawn), ``years`` and ``months`` of
    continuous service, the ``reason`` for termination and an optional
    ``fixed_term`` flag. A monthly-rated employee's daily wage is the monthly
    wage divided by the month divisor. Fixed-term and deceased employees are
    paid pro rata on the exact service; others on completed years, counting a
    part year above the stated months as a full year. The total is capped at
    the notified ceiling.
    """
    years, months = int(case["years"]), int(case.get("months", 0))
    service_months = years * 12 + months
    reason = case["reason"]
    fixed_term = bool(case.get("fixed_term")) or reason == "fixed_term_expiry"
    if fixed_term:
        qualifying_months = int(parameters["fixed_term_qualifying_years"]) * 12
    elif reason in parameters["reasons_without_qualifying_service"]:
        qualifying_months = 0
    else:
        qualifying_months = int(parameters["qualifying_years"]) * 12
    if service_months < qualifying_months or service_months == 0:
        return Decimal(0)
    daily = _dec(case["monthly_wage"]) / _dec(parameters["month_divisor"])
    per_year = daily * _dec(parameters["days_per_year"])
    if fixed_term or reason == "death":
        amount = per_year * _dec(service_months) / 12
    else:
        amount = per_year * _counted_years(years, months, int(parameters["part_year_months_above"]))
    return min(amount, _dec(parameters["ceiling"]))


def retrenchment(parameters: Mapping[str, Any], case: Mapping[str, Any]) -> Decimal:
    """Retrenchment compensation, re-skilling fund credit or daily lay-off compensation for a worker.

    ``component`` selects the amount: ``compensation`` (days of average pay
    for every completed year or part year above the stated months, payable
    only after the qualifying service), ``reskilling_fund`` (days of wages
    last drawn credited to the worker), or ``layoff_daily`` (the share of
    basic wages and dearness allowance paid for each day of lay-off).
    """
    component = case["component"]
    if component == "reskilling_fund":
        return _dec(case["daily_wage"]) * _dec(parameters["reskilling_fund_days"])
    if component == "layoff_daily":
        return _dec(case["daily_basic_and_dearness"]) * _dec(parameters["layoff_compensation_percent"]) / 100
    years, months = int(case["years"]), int(case.get("months", 0))
    if years * 12 + months < int(parameters["qualifying_months"]):
        return Decimal(0)
    counted = _counted_years(years, months, int(parameters["part_year_months_above"]))
    return _dec(case["average_daily_pay"]) * _dec(parameters["days_per_year"]) * counted


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    formula = parameters["formula"]
    if formula == "code_wages":
        return _money(code_wages(parameters, value["included"], value["excluded"]))
    if formula == "bonus":
        minimum, maximum = bonus_range(parameters, value["wages_earned"])
        return {"minimum": _money(minimum), "maximum": _money(maximum)}
    if formula == "wage_payment":
        if "deductions_ceiling_for" in value:
            return _money(deduction_ceiling(parameters, value["deductions_ceiling_for"]))
        return wage_payment_deadline(parameters, value["wage_period"], date.fromisoformat(str(value["period_end"]))).isoformat()
    if formula == "gratuity":
        return _money(gratuity(parameters, value))
    if formula == "retrenchment":
        return _money(retrenchment(parameters, value))
    raise ValueError(f"unknown formula {formula!r}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "parameter" and len(stat.args) == 1:
        return parameters[stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

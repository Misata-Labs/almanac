"""End-of-service gratuity under the labour laws of the Gulf states.

Gulf labour laws pay a departing worker a lump sum that grows with length of
service: a stated amount of wage for each year of an initial band of years
and a larger amount for each later year, with part years counted pro rata
and the whole computed on the last wage. The laws differ in four places,
each held in the parameters:

``wage_unit``
    ``"month"`` when the tiers accrue months of wage per year of service (the
    Saudi Labour Law's half-month and one-month wage), ``"day"`` when they
    accrue days of wage (the UAE's 21 and 30 days). Day accruals convert a
    monthly wage to a daily one by dividing by ``days_per_month``.
``tiers``
    Ordered bands ``{"up_to_years": 5, "per_year": "0.5"}``; the last band
    has ``"up_to_years": null`` and covers every later year.
``minimum_years`` and ``cap_months``
    Service below ``minimum_years`` earns nothing; the award never exceeds
    ``cap_months`` months of wage. Both are optional.
``resignation``
    Optional bands ``{"from_years": 2, "from_inclusive": true, "fraction":
    "1/3"}`` giving the share of the award due when the worker resigns. The
    last band whose threshold the service meets applies; service below every
    band earns nothing. Without this parameter a resignation earns the full
    award.

Amounts are computed exactly and rounded half-up to ``rounding`` (default
0.01) only at the end.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from almanac.models import Statistic

_DEFAULT_STEP = "0.01"


def _fraction(value: Any) -> Fraction:
    return Fraction(str(value))


def _tiers(parameters: Mapping[str, Any]) -> list[tuple[Fraction | None, Fraction]]:
    tiers = []
    for tier in parameters["tiers"]:
        upper = tier.get("up_to_years")
        tiers.append((None if upper is None else _fraction(upper), _fraction(tier["per_year"])))
    if tiers[-1][0] is not None:
        raise ValueError("the last tier must be open-ended (up_to_years: null)")
    return tiers


def accrual_for_year(parameters: Mapping[str, Any], year: int) -> Fraction:
    """Wage units (months or days, per ``wage_unit``) accrued by the ``year``-th year of service, counted from 1."""
    if year < 1:
        raise ValueError("service years are counted from 1")
    for upper, per_year in _tiers(parameters):
        if upper is None or year <= upper:
            return per_year
    raise AssertionError("unreachable: the last tier is open-ended")


def accrued_units(parameters: Mapping[str, Any], years: Fraction) -> Fraction:
    """Wage units accrued over ``years`` of service, part years pro rata within their tier."""
    total = Fraction(0)
    lower = Fraction(0)
    for upper, per_year in _tiers(parameters):
        top = years if upper is None else min(years, upper)
        if top > lower:
            total += (top - lower) * per_year
        if upper is None or years <= upper:
            break
        lower = upper
    return total


def _units_in_months(parameters: Mapping[str, Any], units: Fraction) -> Fraction:
    unit = parameters["wage_unit"]
    if unit == "month":
        return units
    if unit == "day":
        return units / _fraction(parameters["days_per_month"])
    raise ValueError(f"unknown wage_unit {unit!r}")


def resignation_fraction(parameters: Mapping[str, Any], years: Fraction) -> Fraction:
    """Share of the award due on resignation after ``years`` of service."""
    bands = parameters.get("resignation")
    if not bands:
        return Fraction(1)
    share = Fraction(0)
    for band in bands:
        threshold = _fraction(band["from_years"])
        inclusive = band.get("from_inclusive", True)
        if years > threshold or (inclusive and years == threshold):
            share = _fraction(band["fraction"])
    return share


def award_in_months(parameters: Mapping[str, Any], years: Fraction, reason: str = "termination") -> Fraction:
    """The award expressed in months of wage, after the minimum-service rule, the cap and any resignation share."""
    if years < 0:
        raise ValueError("service cannot be negative")
    if years < _fraction(parameters.get("minimum_years", 0)):
        return Fraction(0)
    months = _units_in_months(parameters, accrued_units(parameters, years))
    cap = parameters.get("cap_months")
    if cap is not None:
        months = min(months, _fraction(cap))
    if reason == "resignation":
        months *= resignation_fraction(parameters, years)
    elif reason != "termination":
        raise ValueError(f"unknown reason {reason!r}; expected 'termination' or 'resignation'")
    return months


def award(parameters: Mapping[str, Any], monthly_wage: Any, years: Any, reason: str = "termination") -> Decimal:
    """The award in currency for a monthly wage and length of service, rounded to ``rounding``."""
    months = award_in_months(parameters, _fraction(years), reason)
    exact = _fraction(monthly_wage) * months
    step = Decimal(str(parameters.get("rounding", _DEFAULT_STEP)))
    return (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(step, rounding=ROUND_HALF_UP)


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    """Apply the scheme to a vector input.

    ``{"monthly_wage", "years", "reason"}`` returns the award as a string.
    ``{"op": "accrual", "year": n}`` returns the wage units accrued by the
    n-th year of service; ``{"op": "resignation_fraction", "years": y}``
    returns the share due on resignation; ``{"op": "award_months", "years":
    y, "reason": r}`` returns the award in months of wage. Fractions are
    returned as ``"p/q"`` strings, whole numbers without a denominator.
    """
    op = value.get("op", "award")
    if op == "award":
        return str(award(parameters, value["monthly_wage"], value["years"], value.get("reason", "termination")))
    if op == "accrual":
        return _fraction_text(accrual_for_year(parameters, int(value["year"])))
    if op == "resignation_fraction":
        return _fraction_text(resignation_fraction(parameters, _fraction(value["years"])))
    if op == "award_months":
        return _fraction_text(award_in_months(parameters, _fraction(value["years"]), value.get("reason", "termination")))
    raise ValueError(f"unsupported op {op!r}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    """``tier_count``, ``accrual[n]`` (as a float) and ``cap_months``."""
    if stat.name == "tier_count" and not stat.args:
        return len(parameters["tiers"])
    if stat.name == "accrual" and len(stat.args) == 1:
        return float(accrual_for_year(parameters, int(stat.args[0])))
    if stat.name == "cap_months" and not stat.args:
        return float(parameters["cap_months"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

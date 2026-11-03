"""Irish income tax and Universal Social Charge for a year of assessment.

Income tax is charged at the standard rate on income up to the standard rate
band for the taxpayer's circumstances and at the higher rate on the balance;
tax credits are then deducted and cannot make the tax negative. A married
couple or civil partners with two incomes may increase their band by the
lower of a fixed maximum and the second income. The employee (PAYE) credit
is limited to a percentage of the employment income.

The Universal Social Charge is a separate charge on aggregate income in
slices, each with its own rate.

An entry selects the charge with ``parameters.charge``:

* ``income_tax``: ``standard_rate_percent``, ``higher_rate_percent``,
  ``standard_rate_bands`` (by circumstance), ``two_income_increase_max``,
  ``tax_credits`` (by name) and ``employee_credit_cap_percent``.
* ``usc``: ``bands`` as ``{up_to, rate_percent}`` slices, the last with
  ``up_to: null``.

Results are in euros and cents; pass ``round: euro`` to compare with
published examples that round to whole euros.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping

from almanac.models import Statistic

_CENT = Decimal("0.01")
_EURO = Decimal(1)
_HUNDRED = Decimal(100)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def standard_rate_band(parameters: Mapping[str, Any], status: str, second_income: Any = 0) -> Decimal:
    """The standard rate band for ``status``, with the two-income increase where it applies."""
    band = _decimal(parameters["standard_rate_bands"][status])
    if status == "married_two_incomes":
        band += min(_decimal(parameters["two_income_increase_max"]), max(Decimal(0), _decimal(second_income)))
    return band


def credit_amount(parameters: Mapping[str, Any], name: str, employment_income: Decimal) -> Decimal:
    amount = _decimal(parameters["tax_credits"][name])
    if name == "employee":
        amount = min(amount, employment_income * _decimal(parameters["employee_credit_cap_percent"]) / _HUNDRED)
    return amount


def income_tax(parameters: Mapping[str, Any], income: Any, status: str, credits: Iterable[str] = (), second_income: Any = 0) -> Decimal:
    """Income tax after credits on ``income`` (the combined income for a jointly assessed couple)."""
    total = _decimal(income)
    band = standard_rate_band(parameters, status, second_income)
    standard = min(total, band) * _decimal(parameters["standard_rate_percent"]) / _HUNDRED
    higher = max(Decimal(0), total - band) * _decimal(parameters["higher_rate_percent"]) / _HUNDRED
    relief = sum((credit_amount(parameters, name, total) for name in credits), Decimal(0))
    return max(Decimal(0), standard + higher - relief).quantize(_CENT, rounding=ROUND_HALF_UP)


def usc(parameters: Mapping[str, Any], income: Any) -> Decimal:
    """Universal Social Charge on aggregate income, slice by slice."""
    total = _decimal(income)
    charge = Decimal(0)
    lower = Decimal(0)
    for band in parameters["bands"]:
        upper = None if band.get("up_to") is None else _decimal(band["up_to"])
        top = total if upper is None else min(total, upper)
        if top > lower:
            charge += (top - lower) * _decimal(band["rate_percent"]) / _HUNDRED
        if upper is None or total <= upper:
            break
        lower = upper
    return charge.quantize(_CENT, rounding=ROUND_HALF_UP)


def evaluate(parameters: Mapping[str, Any], value: Any) -> str:
    query = value if isinstance(value, Mapping) else {"income": value}
    if parameters["charge"] == "usc":
        amount = usc(parameters, query["income"])
    else:
        amount = income_tax(parameters, query["income"], query.get("status", "single"), query.get("credits", ()), query.get("second_income", 0))
    if query.get("round") == "euro":
        amount = amount.quantize(_EURO, rounding=ROUND_HALF_UP)
    return str(amount)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if parameters["charge"] == "usc":
        if stat.name == "count" and not stat.args:
            return len(parameters["bands"])
        if stat.name == "rate" and len(stat.args) == 1:
            return float(parameters["bands"][int(stat.args[0])]["rate_percent"])
    else:
        if stat.name == "band" and len(stat.args) == 1:
            return float(parameters["standard_rate_bands"][stat.args[0]])
        if stat.name == "credit" and len(stat.args) == 1:
            return float(parameters["tax_credits"][stat.args[0]])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

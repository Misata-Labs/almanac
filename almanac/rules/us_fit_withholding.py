"""US federal income tax withholding by the percentage method of IRS Publication 15-T.

Publication 15-T's Worksheet 1A annualises the wages of one payroll period,
adjusts them for the employee's Form W-4, finds the row of the Annual
Percentage Method table for the filing status and Step 2 checkbox, and
divides the annual tentative amount back to the payroll period before
applying credits and extra withholding. The parameters hold the annual
withholding rate schedules and the worksheet's fixed amounts; the rule runs
the worksheet line by line.

Each schedule row carries ``at_least``, ``less_than`` (null on the top row),
``base`` (column C), ``rate_percent`` (column D) and ``excess_over``
(column E).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_CENT = Decimal("0.01")
_ZERO = Decimal(0)

FILING_STATUS_ALIASES = {
    "married_filing_jointly": "married_filing_jointly",
    "qualifying_surviving_spouse": "married_filing_jointly",
    "married": "married_filing_jointly",
    "single": "single_or_married_filing_separately",
    "married_filing_separately": "single_or_married_filing_separately",
    "single_or_married_filing_separately": "single_or_married_filing_separately",
    "head_of_household": "head_of_household",
}


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def schedule_name(filing_status: str) -> str:
    """Normalise a Form W-4 filing status to the name of its withholding schedule."""
    try:
        return FILING_STATUS_ALIASES[filing_status]
    except KeyError as exc:
        raise KeyError(f"unknown filing status {filing_status!r}") from exc


def schedule_row(parameters: Mapping[str, Any], adjusted_annual_wage: Decimal, filing_status: str, checkbox: bool = False) -> Mapping[str, Any]:
    """The table row whose column A is at most, and column B above, the adjusted annual wage (Worksheet 1A, line 2b)."""
    rows = parameters["schedules"]["checkbox" if checkbox else "standard"][schedule_name(filing_status)]
    for row in rows:
        upper = row.get("less_than")
        if _money(row["at_least"]) <= adjusted_annual_wage and (upper is None or adjusted_annual_wage < _money(upper)):
            return row
    raise ValueError(f"no schedule row covers {adjusted_annual_wage}")


def tentative_annual_withholding(parameters: Mapping[str, Any], adjusted_annual_wage: Any, filing_status: str, checkbox: bool = False) -> Decimal:
    """Annual tentative withholding for an Adjusted Annual Wage Amount (Worksheet 1A, lines 2a to 2g)."""
    wage = max(_ZERO, _money(adjusted_annual_wage))
    row = schedule_row(parameters, wage, filing_status, checkbox)
    excess = wage - _money(row["excess_over"])
    tax = _money(row["base"]) + excess * _money(row["rate_percent"]) / 100
    return tax.quantize(_CENT, rounding=ROUND_HALF_UP)


def adjusted_annual_wage(parameters: Mapping[str, Any], worksheet: Mapping[str, Any]) -> Decimal:
    """Adjusted Annual Wage Amount (Worksheet 1A, lines 1a to 1l)."""
    periods = pay_periods(parameters, worksheet)
    annual = _money(worksheet["wages"]) * periods
    if worksheet.get("form_w4_2020_or_later", True):
        status = schedule_name(worksheet["filing_status"])
        if worksheet.get("checkbox", False):
            adjustment = _ZERO
        else:
            adjustment = _money(parameters["step2_adjustment"][status if status == "married_filing_jointly" else "other"])
        deductions = _money(worksheet.get("step4b", 0)) + adjustment
        return max(_ZERO, annual + _money(worksheet.get("step4a", 0)) - deductions)
    allowances = _money(worksheet.get("allowances", 0)) * _money(parameters["allowance_value"])
    return max(_ZERO, annual - allowances)


def pay_periods(parameters: Mapping[str, Any], worksheet: Mapping[str, Any]) -> int:
    frequency = worksheet.get("pay_frequency", "annually")
    try:
        return int(parameters["pay_periods"][frequency])
    except KeyError as exc:
        raise KeyError(f"unknown pay frequency {frequency!r}") from exc


def withholding(parameters: Mapping[str, Any], worksheet: Mapping[str, Any]) -> Decimal:
    """Federal income tax to withhold for one payroll period (Worksheet 1A, line 4b), to the cent.

    ``worksheet`` takes ``wages`` for the period, ``pay_frequency``, ``filing_status`` and,
    for a 2020 or later Form W-4, ``checkbox`` (Step 2), ``step3`` (credits), ``step4a``
    (other income), ``step4b`` (deductions) and ``step4c`` (extra withholding). For an
    earlier form set ``form_w4_2020_or_later`` to false and give ``allowances``; the
    filing status is then ``single`` or ``married``.
    """
    periods = pay_periods(parameters, worksheet)
    modern = worksheet.get("form_w4_2020_or_later", True)
    wage = adjusted_annual_wage(parameters, worksheet)
    annual = tentative_annual_withholding(parameters, wage, worksheet["filing_status"], modern and worksheet.get("checkbox", False))
    per_period = annual / periods
    credits = _money(worksheet.get("step3", 0)) / periods if modern else _ZERO
    amount = max(_ZERO, per_period - credits) + _money(worksheet.get("step4c", 0))
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if "adjusted_annual_wage" in value:
        return str(tentative_annual_withholding(parameters, value["adjusted_annual_wage"], value["filing_status"], value.get("checkbox", False)))
    return str(withholding(parameters, value))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    schedules = parameters["schedules"]
    if stat.name == "count" and not stat.args:
        return sum(len(rows) for table in schedules.values() for rows in table.values())
    if stat.name == "rows" and len(stat.args) == 2:
        return len(schedules[stat.args[0]][stat.args[1]])
    if stat.name == "top_rate" and len(stat.args) == 2:
        return schedules[stat.args[0]][stat.args[1]][-1]["rate_percent"]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

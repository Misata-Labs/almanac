"""Income tax from a statutory bracket table that states the tax due at each bracket's lower bound.

Many tax laws print their scale as rows of "income over L: tax is B plus r %
of the part above L", sometimes less a fixed reduction (a tax-reducing amount
that works like a credit). Applying the table row by row reproduces the
statute exactly, including any rounding the legislator built into the B
column, which a slice-by-slice computation can miss by a few cents.

Parameters::

    brackets:
      - {name: first, over: 0, base_tax: 0, rate_percent: 9.5}
      - {name: second, over: 12450, base_tax: 1182.75, rate_percent: 12}
      - {name: top, over: 120000, base_tax: 10800, rate_percent: 32, reduction: 0}

The row whose ``over`` is the largest value strictly below the income
applies; an income at or below the first ``over`` uses the first row. The
result is never negative and is rounded to cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from almanac.models import Statistic

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def bracket_for(parameters: Mapping[str, Any], income: Decimal) -> Mapping[str, Any]:
    """The table row that applies to ``income``."""
    rows = sorted(parameters["brackets"], key=lambda row: _decimal(row["over"]))
    chosen = rows[0]
    for row in rows:
        if income > _decimal(row["over"]):
            chosen = row
    return chosen


def tax_due(parameters: Mapping[str, Any], income: Any) -> Decimal:
    """Tax on ``income``: the row's base tax, plus its rate on the excess, less any reduction."""
    amount = _decimal(income)
    row = bracket_for(parameters, amount)
    excess = max(Decimal(0), amount - _decimal(row["over"]))
    tax = _decimal(row["base_tax"]) + excess * _decimal(row["rate_percent"]) / _HUNDRED - _decimal(row.get("reduction", 0))
    return max(Decimal(0), tax).quantize(_CENT, rounding=ROUND_HALF_UP)


def marginal_rate(parameters: Mapping[str, Any], income: Any) -> float:
    return float(bracket_for(parameters, _decimal(income))["rate_percent"])


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "marginal_rate_for" in value:
        return marginal_rate(parameters, value["marginal_rate_for"])
    income = value["income"] if isinstance(value, Mapping) else value
    return str(tax_due(parameters, income))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    rows = parameters["brackets"]
    if stat.name == "count" and not stat.args:
        return len(rows)
    if stat.name == "rate" and len(stat.args) == 1:
        return float(next(row["rate_percent"] for row in rows if row["name"] == stat.args[0]))
    if stat.name == "tax" and len(stat.args) == 1:
        return float(tax_due(parameters, stat.args[0]))
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

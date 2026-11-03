"""Size tests of India's Companies Act, 2013.

Two tests decide which obligations a generated Indian company carries:

- ``small_company``: section 2(85) with the ceilings prescribed in rule 2(1)(t)
  of the Companies (Specification of Definitions Details) Rules, 2014. A
  company other than a public company is small when neither its paid-up
  share capital nor its turnover exceeds the prescribed ceiling, unless it is
  a holding or subsidiary company, a section 8 company or a company governed
  by a special Act.
- ``csr``: section 135. A company meeting any one of the net worth, turnover
  or net profit thresholds must spend at least the stated share of its
  average net profits of the preceding financial years (fewer years for a
  young company), and needs a CSR committee only when that amount exceeds
  the stated ceiling.

The entry parameters name the test in ``parameters["formula"]``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Sequence

from almanac.models import Statistic

_PAISA = Decimal("0.01")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def is_small_company(parameters: Mapping[str, Any], case: Mapping[str, Any]) -> bool:
    """Whether a company with the given capital, turnover and status is a small company."""
    if case.get("public_company") or any(case.get(flag) for flag in parameters["excluded_flags"]):
        return False
    return _dec(case["paid_up_capital"]) <= _dec(parameters["paid_up_capital_ceiling"]) and _dec(case["turnover"]) <= _dec(parameters["turnover_ceiling"])


def csr_applies(parameters: Mapping[str, Any], net_worth: Any, turnover: Any, net_profit: Any) -> bool:
    """Whether any section 135(1) threshold is met in the immediately preceding financial year."""
    thresholds = parameters["applicability_thresholds"]
    return (
        _dec(net_worth) >= _dec(thresholds["net_worth"])
        or _dec(turnover) >= _dec(thresholds["turnover"])
        or _dec(net_profit) >= _dec(thresholds["net_profit"])
    )


def csr_obligation(parameters: Mapping[str, Any], net_profits: Sequence[Any]) -> Decimal:
    """Minimum CSR spend: the stated share of the average net profit of the preceding years, never negative."""
    years = [_dec(p) for p in net_profits[: int(parameters["averaging_years"])]]
    if not years:
        return Decimal(0)
    average = sum(years, Decimal(0)) / len(years)
    return max(Decimal(0), average * _dec(parameters["spend_percent"]) / 100).quantize(_PAISA, rounding=ROUND_HALF_UP)


def csr(parameters: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    """Applicability, minimum spend and committee requirement for one company-year."""
    if not csr_applies(parameters, case["net_worth"], case["turnover"], case["net_profit"]):
        return {"applies": False, "obligation": "0.00", "committee_required": False}
    obligation = csr_obligation(parameters, case["preceding_net_profits"])
    return {
        "applies": True,
        "obligation": str(obligation),
        "committee_required": obligation > _dec(parameters["committee_exemption_ceiling"]),
    }


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    formula = parameters["formula"]
    if formula == "small_company":
        return is_small_company(parameters, value)
    if formula == "csr":
        return csr(parameters, value)
    raise ValueError(f"unknown formula {formula!r}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "parameter" and len(stat.args) == 1:
        return parameters[stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

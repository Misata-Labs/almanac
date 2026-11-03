"""Deposit and share insurance coverage by ownership category (12 CFR 330 for FDIC, 12 CFR 745 for NCUA).

Insurance is counted per depositor, per insured institution, per ownership
category. Most categories add the depositor's interests together and insure the
total up to the standard maximum amount. Trust accounts are insured per
beneficiary instead, and the two insurers count beneficiaries differently:

* ``per_beneficiary_capped`` (FDIC, 12 CFR 330.10 as amended in 2024): the
  standard maximum times the number of eligible beneficiaries, counting no
  more than ``max_beneficiaries`` of them, for each grantor.
* ``per_beneficiary_with_floor`` (NCUA, 12 CFR 745.4): the standard maximum
  times the number of different beneficiaries, for each owner; when more than
  ``floor_beneficiaries`` beneficiaries are named and the balance exceeds that
  many times the standard maximum, coverage is the greater of that multiple and
  the sum of each beneficiary's interest capped at the standard maximum.

Co-owners of a trust deposit are presumed to own it in equal shares, so the
coverage of an account with several owners is the per-owner coverage times
the number of owners.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from almanac.models import Statistic


def _money(value: Any) -> Decimal:
    return Decimal(str(value))


def _plain(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def aggregate_coverage(interests: Iterable[Any], parameters: Mapping[str, Any]) -> dict[str, int | float]:
    """Insured and uninsured parts of one depositor's interests in a category that aggregates to the limit."""
    limit = _money(parameters["standard_maximum"])
    total = sum((_money(i) for i in interests), Decimal(0))
    insured = min(total, limit)
    return {"insured": _plain(insured), "uninsured": _plain(total - insured)}


def trust_coverage(parameters: Mapping[str, Any], beneficiaries: int | None = None, beneficiary_interests: Iterable[Any] | None = None, balance: Any = None, owners: int = 1) -> dict[str, int | float]:
    """Maximum trust coverage for a grantor or owner group, with the insured split when ``balance`` is given."""
    limit = _money(parameters["standard_maximum"])
    rule = parameters["trust_rule"]
    interests = [_money(i) for i in beneficiary_interests] if beneficiary_interests is not None else None
    count = len(interests) if interests is not None else int(beneficiaries)
    if rule["method"] == "per_beneficiary_capped":
        per_owner = limit * min(count, int(rule["max_beneficiaries"]))
    elif rule["method"] == "per_beneficiary_with_floor":
        floor_count = int(rule["floor_beneficiaries"])
        per_owner = limit * count
        share = _money(balance) / owners if balance is not None else None
        if count > floor_count and share is not None and share > limit * floor_count:
            if interests is None:
                raise ValueError("beneficiary_interests are required when the floor applies")
            capped = sum((min(i, limit) for i in interests), Decimal(0))
            per_owner = max(limit * floor_count, capped)
    else:
        raise ValueError(f"unknown trust method {rule['method']!r}")
    coverage = per_owner * owners
    result: dict[str, int | float] = {"coverage": _plain(coverage)}
    if balance is not None:
        insured = min(_money(balance), coverage)
        result.update({"insured": _plain(insured), "uninsured": _plain(_money(balance) - insured)})
    return result


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    category = value["category"]
    basis = parameters["categories"][category]["basis"]
    if basis == "per_beneficiary":
        return trust_coverage(
            parameters,
            beneficiaries=value.get("beneficiaries"),
            beneficiary_interests=value.get("beneficiary_interests"),
            balance=value.get("balance"),
            owners=int(value.get("owners", 1)),
        )
    return aggregate_coverage(value["interests"], parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "standard_maximum" and not stat.args:
        return parameters["standard_maximum"]
    if stat.name == "count" and not stat.args:
        return len(parameters["categories"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

"""Hart-Scott-Rodino premerger notification: reportability and filing fee (15 U.S.C. 18a).

Section 7A(a)(2) of the Clayton Act requires notification of an acquisition
when the voting securities and assets the acquiring person would hold in the
acquired person exceed a size-of-transaction threshold. Above the upper
threshold every such acquisition is reportable; between the lower and upper
thresholds it is reportable only when the parties also meet one of three
size-of-person tests. The filing fee is set by the size of transaction alone,
from a schedule of tiers. The Federal Trade Commission republishes every
threshold and fee each year adjusted for the change in gross national product
and consumer prices.

Parameters carry the published dollar amounts:

``size_of_transaction``
    ``all_transactions_above_usd``: transactions in excess of this are
    reportable regardless of the size of the parties (7A(a)(2)(A)).
    ``size_of_person_test_above_usd``: transactions in excess of this but not
    in excess of the upper threshold are reportable when a size-of-person
    test is met (7A(a)(2)(B)(i)).
``size_of_person``
    ``smaller_person_usd`` and ``larger_person_usd``: the two size-of-person
    amounts of 7A(a)(2)(B)(ii).
``filing_fees``
    Tiers in ascending order, each with ``from_usd`` (inclusive), ``below_usd``
    (exclusive, null for the open top tier) and ``fee_usd``.

Exemptions under section 7A(c) and the HSR rules (16 CFR parts 801 to 803),
the valuation of the transaction and the aggregation of holdings are outside
the rule: the caller supplies the size of transaction as determined under the
Act.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic

REPORTABLE = "reportable"
REPORTABLE_IF_SIZE_OF_PERSON = "size-of-person test applies"
NOT_REPORTABLE = "not reportable"


def _usd(value: Any) -> int:
    amount = float(value)
    if amount < 0:
        raise ValueError("amounts must not be negative")
    return round(amount)


def transaction_band(size_of_transaction: Any, parameters: Mapping[str, Any]) -> str:
    """Classify a size of transaction against the two thresholds of section 7A(a)(2)."""
    value = _usd(size_of_transaction)
    thresholds = parameters["size_of_transaction"]
    if value > thresholds["all_transactions_above_usd"]:
        return REPORTABLE
    if value > thresholds["size_of_person_test_above_usd"]:
        return REPORTABLE_IF_SIZE_OF_PERSON
    return NOT_REPORTABLE


def _largest(person: Mapping[str, Any]) -> int:
    return max(_usd(person.get("annual_net_sales_usd", 0)), _usd(person.get("total_assets_usd", 0)))


def meets_size_of_person(acquiring: Mapping[str, Any], acquired: Mapping[str, Any], parameters: Mapping[str, Any]) -> bool:
    """Whether one of the three size-of-person tests of section 7A(a)(2)(B)(ii) is met.

    (I) a manufacturing acquired person with annual net sales or total assets of
    the smaller amount or more, acquired by a person with total assets or annual
    net sales of the larger amount or more; (II) a non-manufacturing acquired
    person with total assets of the smaller amount or more, acquired by a person
    of the larger amount or more; (III) an acquired person with annual net sales
    or total assets of the larger amount or more, acquired by a person of the
    smaller amount or more.
    """
    smaller = parameters["size_of_person"]["smaller_person_usd"]
    larger = parameters["size_of_person"]["larger_person_usd"]
    acquirer = _largest(acquiring)
    if acquired.get("manufacturing", False):
        acquired_size_for_first_tests = _largest(acquired)
    else:
        acquired_size_for_first_tests = _usd(acquired.get("total_assets_usd", 0))
    if acquired_size_for_first_tests >= smaller and acquirer >= larger:
        return True
    return _largest(acquired) >= larger and acquirer >= smaller


def is_reportable(size_of_transaction: Any, acquiring: Mapping[str, Any] | None, acquired: Mapping[str, Any] | None, parameters: Mapping[str, Any]) -> bool:
    """Whether section 7A(a)(2) requires notification, before any exemption is applied."""
    band = transaction_band(size_of_transaction, parameters)
    if band == REPORTABLE:
        return True
    if band == NOT_REPORTABLE:
        return False
    if acquiring is None or acquired is None:
        raise ValueError("the size-of-person test needs both the acquiring and the acquired person")
    return meets_size_of_person(acquiring, acquired, parameters)


def filing_fee(size_of_transaction: Any, parameters: Mapping[str, Any]) -> int:
    """The filing fee in US dollars for a transaction of the given size."""
    value = _usd(size_of_transaction)
    for tier in parameters["filing_fees"]:
        below = tier["below_usd"]
        if value >= tier["from_usd"] and (below is None or value < below):
            return int(tier["fee_usd"])
    raise ValueError(f"no filing fee tier covers {value}")


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    """Answer one query: ``{"fee": size}``, ``{"band": size}`` or ``{"reportable": size, "acquiring": ..., "acquired": ...}``."""
    if not isinstance(value, Mapping):
        return filing_fee(value, parameters)
    if "fee" in value:
        return filing_fee(value["fee"], parameters)
    if "band" in value:
        return transaction_band(value["band"], parameters)
    if "reportable" in value:
        return is_reportable(value["reportable"], value.get("acquiring"), value.get("acquired"), parameters)
    raise ValueError(f"unrecognised query {sorted(value)}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "tier_count" and not stat.args:
        return len(parameters["filing_fees"])
    if stat.name == "fee" and len(stat.args) == 1:
        return filing_fee(stat.args[0], parameters)
    if stat.name == "threshold" and len(stat.args) == 1:
        (name,) = stat.args
        merged = {**parameters["size_of_transaction"], **parameters["size_of_person"]}
        return merged[name]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

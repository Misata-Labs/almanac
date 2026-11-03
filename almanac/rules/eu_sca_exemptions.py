"""Strong customer authentication exemptions under PSD2 (Commission Delegated Regulation (EU) 2018/389).

Three exemptions are limit tests a payment service provider applies before
asking the payer to authenticate:

* contactless payments at the point of sale (Article 11),
* low-value remote payments (Article 16), each exempt when the payment is no
  larger than a single-payment limit and either the cumulative amount or the
  number of earlier payments since the payer last authenticated stays within
  its limit;
* transaction risk analysis (Article 18), where the largest exempt amount (the
  exemption threshold value) depends on the provider's fraud rate for the
  payment type, read from the Annex table.

The cumulative amount and count passed in describe the payments made since the
last strong customer authentication, excluding the payment being tested.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from almanac.models import Statistic

PAYMENT_TYPES = ("card", "credit_transfer")


def limit_exempt(exemption: str, amount: Any, previous_cumulative: Any, previous_count: int, parameters: Mapping[str, Any]) -> bool:
    """Whether a payment qualifies for the contactless or low-value remote exemption."""
    limits = parameters[exemption]
    if Decimal(str(amount)) > Decimal(str(limits["max_amount_eur"])):
        return False
    within_cumulative = Decimal(str(previous_cumulative)) <= Decimal(str(limits["max_cumulative_eur"]))
    return within_cumulative or int(previous_count) <= int(limits["max_consecutive"])


def tra_threshold(payment_type: str, fraud_rate_percent: Any, parameters: Mapping[str, Any]) -> int | None:
    """The largest exemption threshold value whose reference fraud rate the provider's rate does not exceed."""
    if payment_type not in PAYMENT_TYPES:
        raise ValueError(f"payment_type must be one of {PAYMENT_TYPES}")
    rate = Decimal(str(fraud_rate_percent))
    eligible = [band["etv_eur"] for band in parameters["tra_bands"] if rate <= Decimal(str(band[f"{payment_type}_reference_fraud_rate_percent"]))]
    return max(eligible) if eligible else None


def tra_exempt(payment_type: str, fraud_rate_percent: Any, amount: Any, parameters: Mapping[str, Any]) -> bool:
    """Whether a remote payment of ``amount`` euros can rely on transaction risk analysis."""
    threshold = tra_threshold(payment_type, fraud_rate_percent, parameters)
    return threshold is not None and Decimal(str(amount)) <= threshold


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    exemption = value["exemption"]
    if exemption in ("contactless", "low_value_remote"):
        return limit_exempt(exemption, value["amount"], value.get("previous_cumulative", 0), int(value.get("previous_count", 0)), parameters)
    if exemption == "tra_threshold":
        return tra_threshold(value["payment_type"], value["fraud_rate_percent"], parameters)
    if exemption == "tra":
        return tra_exempt(value["payment_type"], value["fraud_rate_percent"], value["amount"], parameters)
    raise ValueError(f"unknown exemption {exemption!r}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and not stat.args:
        return len(parameters["tra_bands"])
    if stat.name == "value" and len(stat.args) == 2:
        return parameters[stat.args[0]][stat.args[1]]
    if stat.name == "max" and stat.args == ("etv_eur",):
        return max(band["etv_eur"] for band in parameters["tra_bands"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

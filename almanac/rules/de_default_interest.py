"""German statutory default interest (Verzugszinsen) under sections 247, 286 and 288 BGB.

A money debt in default bears interest at a fixed margin over the base rate
(Basiszinssatz) in force on each day: one margin when a consumer is party to
the transaction, a higher one for payment claims between businesses. A
creditor of a business debtor may also claim a flat fee. A debtor of a
payment claim is in default at the latest when it has not paid within a
fixed number of days after the due date and receipt of the invoice; the
period starts the day after the later of the two events and ends with its
last day. Moving that last day off a weekend or public holiday is not
modelled, because holidays differ between the federal states.

The base rate steps, margins, fee and period are parameters taken from the
Bundesbank series and the statute.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def base_rate_on(parameters: Mapping[str, Any], day: date) -> Decimal:
    """The base rate in percent in force on ``day``."""
    steps = sorted((date.fromisoformat(str(s["from"])), Decimal(str(s["value"]))) for s in parameters["base_rate_steps"])
    index = bisect_right([d for d, _ in steps], day)
    if index == 0:
        raise ValueError(f"{day} precedes the first base rate step {steps[0][0]}")
    return steps[index - 1][1]


def default_rate_on(parameters: Mapping[str, Any], day: date, consumer_involved: bool) -> Decimal:
    """The default interest rate in percent a year on ``day``."""
    if day < date.fromisoformat(str(parameters["applies_from"])):
        raise ValueError(f"the margins apply to obligations arising from {parameters['applies_from']}")
    margin = parameters["margin_points"]["consumer" if consumer_involved else "business"]
    return base_rate_on(parameters, day) + Decimal(str(margin))


def flat_fee(parameters: Mapping[str, Any], debtor_is_consumer: bool) -> int:
    """The flat fee in euros the creditor of a payment claim may claim on default."""
    return 0 if debtor_is_consumer else int(parameters["flat_fee_eur"])


def last_day_to_pay(parameters: Mapping[str, Any], due: date, invoice_received: date) -> date:
    """The last day of the payment period before default begins without a reminder."""
    return max(due, invoice_received) + timedelta(days=int(parameters["payment_period_days"]))


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if "base_rate_on" in value:
        return float(base_rate_on(parameters, date.fromisoformat(str(value["base_rate_on"]))))
    if "rate_on" in value:
        return float(default_rate_on(parameters, date.fromisoformat(str(value["rate_on"])), bool(value["consumer_involved"])))
    if "flat_fee" in value:
        return flat_fee(parameters, bool(value["flat_fee"]["debtor_is_consumer"]))
    if "due" in value:
        return last_day_to_pay(parameters, date.fromisoformat(str(value["due"])), date.fromisoformat(str(value["invoice_received"]))).isoformat()
    raise ValueError(f"unsupported input {value!r}")

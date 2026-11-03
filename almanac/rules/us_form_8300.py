"""Reporting schedule for cash received in a trade or business (26 U.S.C. 6050I, Form 8300).

A business that receives cash of more than a threshold amount for one transaction,
or for related transactions, files a return within a fixed number of days. When
the cash arrives in instalments, 26 CFR 1.6050I-1(b) aggregates payments that
have not yet been reported: a report falls due each time the unreported payments
received within a twelve-month window together exceed the threshold, counted
from the day of the payment that tipped the total over.

The rule replays a payment history in date order and returns every report it
triggers. A payment belongs to the window when it is received before the first
anniversary of the earliest unreported payment still in the window; older
payments drop out as later ones arrive. The optional combined report for
several payments inside one filing period is not modelled: each trigger is
returned on its own.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping

from almanac.models import Statistic


def _anniversary(day: date) -> date:
    """The same calendar day one year later; 29 February maps to 1 March."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return date(day.year + 1, 3, 1)


def _payments(payments: Iterable[Mapping[str, Any]]) -> list[tuple[date, Decimal]]:
    parsed = [(date.fromisoformat(str(p["date"])), Decimal(str(p["amount"]))) for p in payments]
    return sorted(parsed, key=lambda item: item[0])


def reports(payments: Iterable[Mapping[str, Any]], parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every report the payment history triggers, as trigger date, due date and amount reported."""
    threshold = Decimal(str(parameters["threshold"]))
    days = timedelta(days=int(parameters["report_within_days"]))
    window: list[tuple[date, Decimal]] = []
    triggered: list[dict[str, Any]] = []
    for day, amount in _payments(payments):
        window = [(d, a) for d, a in window if day < _anniversary(d)]
        window.append((day, amount))
        total = sum((a for _, a in window), Decimal(0))
        if total > threshold:
            triggered.append({"triggered_on": day.isoformat(), "due_by": (day + days).isoformat(), "amount": _plain(total)})
            window = []
    return triggered


def is_reportable(amount: float | int | str, parameters: Mapping[str, Any]) -> bool:
    """Whether a single cash receipt exceeds the reporting threshold on its own."""
    return Decimal(str(amount)) > Decimal(str(parameters["threshold"]))


def _plain(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "payments" in value:
        return reports(value["payments"], parameters)
    return is_reportable(value["amount"] if isinstance(value, Mapping) else value, parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name in ("threshold", "report_within_days") and not stat.args:
        return parameters[stat.name]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

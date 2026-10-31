"""Keyed reference table rule.

Many official publications are tables keyed by a code: an exchange rate per
currency, an indicator per economy, a rate per category. The parameters hold
the rows keyed by that code; the rule looks a key up, optionally returning
one named column, and reports the table's size.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def row(parameters: Mapping[str, Any], key: str) -> dict[str, Any]:
    try:
        return dict(parameters["rows"][key])
    except KeyError as exc:
        raise KeyError(f"no row for key {key!r}") from exc


def lookup(parameters: Mapping[str, Any], key: str, column: str | None = None) -> Any:
    """Return the row for ``key``, or one of its columns when ``column`` is given."""
    record = row(parameters, key)
    return record if column is None else record[column]


def has_key(parameters: Mapping[str, Any], key: str) -> bool:
    return key in parameters["rows"]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        return lookup(parameters, str(value["key"]), value.get("column"))
    return has_key(parameters, str(value))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    rows = parameters["rows"]
    if stat.name == "count" and not stat.args:
        return len(rows)
    if stat.name == "value" and len(stat.args) == 2:
        return rows[stat.args[0]][stat.args[1]]
    if stat.name in ("min", "max", "mean") and len(stat.args) == 1:
        values = [float(r[stat.args[0]]) for r in rows.values() if r.get(stat.args[0]) is not None]
        return {"min": min, "max": max, "mean": lambda v: sum(v) / len(v)}[stat.name](values)
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

"""Public holiday lists with business-day arithmetic.

A holiday list is either dated (a published calendar: one record per date,
optionally restricted to named regions) or recurring (a statute: a fixed day
of a month, an ordinal weekday of a month, or an offset from Easter Sunday).
The two forms share one record shape, so the same functions answer whether a
day is a holiday, whether it is a business day, and which business day comes
next, for any economy whose official calendar is held in an entry.

Record shapes::

    {"date": "2026-04-06", "name": "Lundi de Pâques"}
    {"name": "Fiesta del Trabajo", "month": 5, "day": 1}
    {"name": "Memorial Day", "month": 5, "weekday": "monday", "ordinal": "last"}
    {"name": "Easter Monday", "easter_offset": 1}

Any record may carry ``regions``, a list of codes the holiday applies to;
a record without it applies everywhere. An ordinal-weekday record may carry
``fixed_if_weekday`` ({"day": 1, "weekday": "friday"}) for statutes that keep
the fixed date when it falls on a particular weekday. Other keys (``kind``,
``observed``, ``information``) are carried through untouched.

Optional parameters: ``weekend`` (weekday names, default Saturday and Sunday)
and ``years`` ({"from": int, "to": int}) stating the coverage of a dated list.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Iterator, Mapping

from almanac.models import Statistic

_WEEKDAYS = {name.lower(): index for index, name in enumerate(calendar.day_name)}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_DEFAULT_WEEKEND = ("saturday", "sunday")


def easter(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: str, ordinal: str) -> date:
    """The ``ordinal`` (first..fourth or last) ``weekday`` of ``month`` in ``year``."""
    target = _WEEKDAYS[weekday.lower()]
    if ordinal == "last":
        last = date(year, month, calendar.monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - target) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(target - first.weekday()) % 7 + 7 * (_ORDINALS[ordinal] - 1))


def recurring_date(record: Mapping[str, Any], year: int) -> date:
    """The calendar date of a recurring record in ``year``."""
    if "easter_offset" in record:
        return easter(year) + timedelta(days=int(record["easter_offset"]))
    month = int(record["month"])
    if "day" in record:
        return date(year, month, int(record["day"]))
    fixed = record.get("fixed_if_weekday")
    if fixed is not None:
        candidate = date(year, month, int(fixed["day"]))
        if candidate.weekday() == _WEEKDAYS[str(fixed["weekday"]).lower()]:
            return candidate
    return nth_weekday(year, month, record["weekday"], record["ordinal"])


def coverage(parameters: Mapping[str, Any]) -> tuple[int, int] | None:
    """The years a dated list covers, or None for a purely recurring list."""
    years = parameters.get("years")
    if years:
        return int(years["from"]), int(years["to"])
    dated = [int(r["date"][:4]) for r in parameters["holidays"] if "date" in r]
    return (min(dated), max(dated)) if dated else None


def _applies(record: Mapping[str, Any], region: str | None) -> bool:
    regions = record.get("regions")
    return regions is None or region is None or region in regions


def _records(parameters: Mapping[str, Any], year: int, region: str | None) -> Iterator[dict[str, Any]]:
    span = coverage(parameters)
    if span is not None and not span[0] <= year <= span[1]:
        raise KeyError(f"no published holidays for {year}; the list covers {span[0]} to {span[1]}")
    for record in parameters["holidays"]:
        if not _applies(record, region):
            continue
        if "date" in record:
            if record["date"].startswith(f"{year:04d}-"):
                yield dict(record)
        else:
            yield {**record, "date": recurring_date(record, year).isoformat()}


def holidays_in(parameters: Mapping[str, Any], year: int, region: str | None = None) -> list[dict[str, Any]]:
    """Every holiday of ``year`` that applies in ``region`` (or anywhere when ``region`` is None), by date."""
    return sorted(_records(parameters, year, region), key=lambda r: (r["date"], r["name"]))


def holiday_dates(parameters: Mapping[str, Any], year: int, region: str | None = None) -> set[date]:
    return {date.fromisoformat(r["date"]) for r in _records(parameters, year, region)}


def is_holiday(parameters: Mapping[str, Any], day: date, region: str | None = None) -> bool:
    return day in holiday_dates(parameters, day.year, region)


def is_weekend(parameters: Mapping[str, Any], day: date) -> bool:
    weekend = {_WEEKDAYS[name.lower()] for name in parameters.get("weekend", _DEFAULT_WEEKEND)}
    return day.weekday() in weekend


def is_business_day(parameters: Mapping[str, Any], day: date, region: str | None = None) -> bool:
    return not is_weekend(parameters, day) and not is_holiday(parameters, day, region)


def add_business_days(parameters: Mapping[str, Any], day: date, count: int, region: str | None = None) -> date:
    """The business day ``count`` steps from ``day``; zero returns ``day`` itself even on a holiday."""
    step = timedelta(days=1 if count >= 0 else -1)
    remaining = abs(count)
    while remaining:
        day += step
        if is_business_day(parameters, day, region):
            remaining -= 1
    return day


def next_business_day(parameters: Mapping[str, Any], day: date, region: str | None = None) -> date:
    """The first business day strictly after ``day``."""
    return add_business_days(parameters, day, 1, region)


def business_days_in(parameters: Mapping[str, Any], year: int, region: str | None = None) -> int:
    holidays = holiday_dates(parameters, year, region)
    day, count = date(year, 1, 1), 0
    while day.year == year:
        if not is_weekend(parameters, day) and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return count


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    """Apply the list to a vector input.

    A bare ISO date asks whether the day is a holiday anywhere. A mapping
    names an ``op`` (``is_holiday`` by default, ``is_business_day``,
    ``next_business_day``, ``add_business_days`` with ``days``, or
    ``holidays`` for a ``year``) and optionally a ``region``.
    """
    if not isinstance(value, Mapping):
        return is_holiday(parameters, date.fromisoformat(str(value)))
    region = value.get("region")
    op = value.get("op", "holidays" if "year" in value else "is_holiday")
    if op == "holidays":
        return [{"date": r["date"], "name": r["name"]} for r in holidays_in(parameters, int(value["year"]), region)]
    day = date.fromisoformat(str(value["date"]))
    if op == "is_holiday":
        return is_holiday(parameters, day, region)
    if op == "is_business_day":
        return is_business_day(parameters, day, region)
    if op == "next_business_day":
        return next_business_day(parameters, day, region).isoformat()
    if op == "add_business_days":
        return add_business_days(parameters, day, int(value["days"]), region).isoformat()
    raise ValueError(f"unsupported op {op!r}")


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    """Named statistics: ``count``, ``count[year]``, ``count[region,year]``, ``business_days[year]``,
    ``business_days[region,year]`` and ``list_length[key]`` for an auxiliary list parameter."""
    if stat.name == "count" and not stat.args:
        return len(parameters["holidays"])
    if stat.name in ("count", "business_days") and stat.args:
        region, year = (None, stat.args[0]) if len(stat.args) == 1 else stat.args
        if stat.name == "count":
            return len(holiday_dates(parameters, int(year), region))
        return business_days_in(parameters, int(year), region)
    if stat.name == "list_length" and len(stat.args) == 1:
        return len(parameters[stat.args[0]])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

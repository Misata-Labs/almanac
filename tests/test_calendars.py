"""Tests for the generic holiday list rule used by the public holiday calendar entries."""

from __future__ import annotations

from datetime import date

import pytest

from almanac.models import Statistic
from almanac.rules import holiday_list

# Easter Monday, Ascension and Whit Monday as published in the etalab jours fériés list for metropolitan France.
ETALAB_EASTER_HOLIDAYS = {
    2006: ("2006-04-17", "2006-05-25", "2006-06-05"),
    2016: ("2016-03-28", "2016-05-05", "2016-05-16"),
    2024: ("2024-04-01", "2024-05-09", "2024-05-20"),
    2026: ("2026-04-06", "2026-05-14", "2026-05-25"),
    2027: ("2027-03-29", "2027-05-06", "2027-05-17"),
    2030: ("2030-04-22", "2030-05-30", "2030-06-10"),
    2031: ("2031-04-14", "2031-05-22", "2031-06-02"),
}

DATED = {
    "holidays": [
        {"date": "2026-01-01", "name": "New Year"},
        {"date": "2026-04-23", "name": "Regional day", "regions": ["north"]},
        {"date": "2026-12-25", "name": "Christmas"},
        {"date": "2026-12-26", "name": "Boxing Day", "regions": ["north", "south"]},
    ],
    "regions": ["north", "south"],
}

RECURRING = {
    "holidays": [
        {"name": "New Year", "month": 1, "day": 1},
        {"name": "Easter Monday", "easter_offset": 1},
        {"name": "Spring Monday", "month": 5, "weekday": "monday", "ordinal": "first"},
        {"name": "Last Monday", "month": 10, "weekday": "monday", "ordinal": "last"},
        {"name": "February holiday", "month": 2, "weekday": "monday", "ordinal": "first", "fixed_if_weekday": {"day": 1, "weekday": "friday"}},
    ]
}


@pytest.mark.parametrize("year, published", sorted(ETALAB_EASTER_HOLIDAYS.items()))
def test_easter_offsets_reproduce_published_french_dates(year, published):
    monday, ascension, whit_monday = published
    sunday = holiday_list.easter(year)
    assert (sunday + holiday_list.timedelta(days=1)).isoformat() == monday
    assert (sunday + holiday_list.timedelta(days=39)).isoformat() == ascension
    assert (sunday + holiday_list.timedelta(days=50)).isoformat() == whit_monday


def test_nth_weekday_first_and_last():
    assert holiday_list.nth_weekday(2026, 5, "monday", "first") == date(2026, 5, 4)
    assert holiday_list.nth_weekday(2026, 10, "monday", "last") == date(2026, 10, 26)
    assert holiday_list.nth_weekday(2026, 11, "thursday", "fourth") == date(2026, 11, 26)


def test_fixed_if_weekday_keeps_the_fixed_date_only_on_that_weekday():
    record = RECURRING["holidays"][-1]
    assert holiday_list.recurring_date(record, 2030) == date(2030, 2, 1)  # 1 February 2030 is a Friday
    assert holiday_list.recurring_date(record, 2026) == date(2026, 2, 2)  # first Monday otherwise


def test_dated_list_respects_regions():
    assert holiday_list.is_holiday(DATED, date(2026, 4, 23))
    assert holiday_list.is_holiday(DATED, date(2026, 4, 23), "north")
    assert not holiday_list.is_holiday(DATED, date(2026, 4, 23), "south")
    assert [r["name"] for r in holiday_list.holidays_in(DATED, 2026, "south")] == ["New Year", "Christmas", "Boxing Day"]


def test_dated_list_refuses_years_outside_coverage():
    with pytest.raises(KeyError):
        holiday_list.is_holiday(DATED, date(2027, 1, 1))


def test_business_day_arithmetic_skips_weekends_and_holidays():
    assert not holiday_list.is_business_day(DATED, date(2026, 12, 25))
    assert not holiday_list.is_business_day(DATED, date(2026, 12, 27))  # Sunday
    assert holiday_list.next_business_day(DATED, date(2026, 12, 24)) == date(2026, 12, 28)
    assert holiday_list.add_business_days(DATED, date(2026, 12, 31), -4) == date(2026, 12, 24)
    assert holiday_list.add_business_days(DATED, date(2026, 12, 25), 0) == date(2026, 12, 25)


def test_custom_weekend():
    friday_saturday = {**DATED, "weekend": ["friday", "saturday"]}
    assert holiday_list.is_business_day(friday_saturday, date(2026, 12, 27))
    assert not holiday_list.is_business_day(friday_saturday, date(2026, 12, 26))


def test_evaluate_dispatches_on_op():
    assert holiday_list.evaluate(DATED, "2026-01-01") is True
    assert holiday_list.evaluate(DATED, {"date": "2026-04-23", "region": "south"}) is False
    assert holiday_list.evaluate(DATED, {"op": "next_business_day", "date": "2026-12-24"}) == "2026-12-28"
    assert holiday_list.evaluate(DATED, {"op": "add_business_days", "date": "2026-12-24", "days": 2}) == "2026-12-29"
    assert holiday_list.evaluate(RECURRING, {"year": 2026})[1] == {"date": "2026-02-02", "name": "February holiday"}
    with pytest.raises(ValueError):
        holiday_list.evaluate(DATED, {"op": "unknown", "date": "2026-01-01"})


def test_statistics():
    assert holiday_list.statistic(DATED, Statistic.parse("count")) == 4
    assert holiday_list.statistic(DATED, Statistic.parse("count[2026]")) == 4
    assert holiday_list.statistic(DATED, Statistic.parse("count[south,2026]")) == 3
    assert holiday_list.statistic(DATED, Statistic.parse("business_days[2026]")) == 261 - 3
    assert holiday_list.statistic(RECURRING, Statistic.parse("count[2026]")) == 5
    assert holiday_list.statistic({**DATED, "extra": [1, 2]}, Statistic.parse("list_length[extra]")) == 2
    with pytest.raises(ValueError):
        holiday_list.statistic(DATED, Statistic.parse("mean[x]"))

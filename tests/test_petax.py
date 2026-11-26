"""Tests for the private equity tax and fund regulation rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from almanac.models import Statistic
from almanac.rules import (
    erisa_plan_asset_test,
    gb_carried_interest,
    interest_limitation,
    us_bonus_depreciation,
    us_qsbs_exclusion,
)

US_163J = {
    "ratio_percent": 30,
    "allowance_floor": None,
    "exemption_threshold": None,
    "gross_receipts_limit": 32000000,
    "depreciation_addback": [
        {"from": "2018-01-01", "value": True},
        {"from": "2022-01-01", "value": False},
        {"from": "2025-01-01", "value": True},
    ],
}
FLOOR_RULE = {"ratio_percent": 30, "allowance_floor": 2000000, "exemption_threshold": None, "gross_receipts_limit": None}
CLIFF_RULE = {"ratio_percent": 30, "allowance_floor": None, "exemption_threshold": 3000000, "gross_receipts_limit": None}


def test_interest_limitation_reproduces_the_treasury_examples():
    example = {"tax_year_start": "2021-01-01", "earnings": 100, "interest_expense": 50, "floor_plan_interest": 10, "interest_income": 20}
    assert interest_limitation.evaluate(US_163J, {**example, "output": "limit"}) == 60
    assert interest_limitation.evaluate(US_163J, example) == 50
    assert interest_limitation.evaluate(US_163J, {**example, "interest_expense": 80}) == 60
    assert interest_limitation.evaluate(US_163J, {**example, "interest_expense": 80, "output": "disallowed"}) == 20


def test_interest_limitation_switches_the_depreciation_add_back_by_year():
    figures = {"earnings": 70, "depreciation": 30, "interest_expense": 40}
    assert interest_limitation.evaluate(US_163J, {**figures, "tax_year_start": "2021-07-01"}) == 30
    assert interest_limitation.evaluate(US_163J, {**figures, "tax_year_start": "2024-01-01"}) == 21
    assert interest_limitation.evaluate(US_163J, {**figures, "tax_year_start": "2025-01-01"}) == 30
    with pytest.raises(ValueError):
        interest_limitation.evaluate(US_163J, {**figures, "tax_year_start": "2017-01-01"})
    with pytest.raises(ValueError):
        interest_limitation.evaluate(US_163J, figures)


def test_interest_limitation_small_business_exemption_is_inclusive():
    figures = {"tax_year_start": "2026-01-01", "earnings": 0, "interest_expense": 500}
    assert interest_limitation.evaluate(US_163J, {**figures, "average_gross_receipts": 32000000}) == 500
    assert interest_limitation.evaluate(US_163J, {**figures, "average_gross_receipts": 32000001}) == 0


def test_interest_limitation_negative_earnings_give_no_ratio_allowance():
    figures = {"tax_year_start": "2026-01-01", "earnings": -1000, "interest_expense": 300, "interest_income": 100}
    assert interest_limitation.evaluate(US_163J, figures) == 100


def test_interest_limitation_floor_and_cliff_exemptions():
    assert interest_limitation.evaluate(FLOOR_RULE, {"earnings": 1000000, "interest_expense": 2500000}) == 2000000
    assert interest_limitation.evaluate(FLOOR_RULE, {"earnings": 10000000, "interest_expense": 4000000}) == 3000000
    # The cliff exemption applies only below the threshold of net interest; at the threshold the full rule bites.
    assert interest_limitation.evaluate(CLIFF_RULE, {"earnings": 0, "interest_expense": 2999999}) == 2999999
    assert interest_limitation.evaluate(CLIFF_RULE, {"earnings": 0, "interest_expense": 3000000}) == 0
    # The threshold is tested on net interest: income offsets expense before the comparison.
    assert interest_limitation.evaluate(CLIFF_RULE, {"earnings": 0, "interest_expense": 3500000, "interest_income": 1000000}) == 3500000
    assert interest_limitation.evaluate(CLIFF_RULE, {"earnings": 0, "interest_expense": 4500000, "interest_income": 1000000}) == 1000000


def test_interest_limitation_rejects_unknown_outputs_and_scalars():
    with pytest.raises(ValueError):
        interest_limitation.evaluate(FLOOR_RULE, {"earnings": 1, "interest_expense": 1, "output": "rate"})
    with pytest.raises(TypeError):
        interest_limitation.evaluate(FLOOR_RULE, 5)
    assert interest_limitation.statistic(FLOOR_RULE, Statistic(name="allowance_floor")) == 2000000


QSBS = {
    "applicable_date": "2025-07-04",
    "acquisition_periods": [
        {"acquired_after": "1993-08-10", "acquired_on_or_before": "2009-02-17", "percent": 50, "more_than_years": 5},
        {"acquired_after": "2009-02-17", "acquired_on_or_before": "2010-09-27", "percent": 75, "more_than_years": 5},
        {"acquired_after": "2010-09-27", "acquired_on_or_before": "2025-07-04", "percent": 100, "more_than_years": 5},
    ],
    "holding_schedule": [{"years_held": 3, "percent": 50}, {"years_held": 4, "percent": 75}, {"years_held": 5, "percent": 100}],
    "dollar_limit": {"on_or_before_applicable_date": 10000000, "after_applicable_date": 15000000},
    "basis_multiple": 10,
}


@pytest.mark.parametrize(
    ("acquired", "sold", "percent"),
    [
        ("2025-08-01", "2028-07-31", 0),
        ("2025-08-01", "2028-08-01", 50),
        ("2025-08-01", "2029-08-01", 75),
        ("2025-08-01", "2040-01-01", 100),
        ("2025-07-04", "2029-07-05", 0),
        ("2025-07-04", "2030-07-05", 100),
        ("2010-09-27", "2015-09-28", 75),
        ("2010-09-28", "2015-09-29", 100),
        ("2000-01-01", "2005-01-02", 50),
    ],
)
def test_qsbs_percentage_follows_acquisition_window_and_holding_period(acquired, sold, percent):
    assert us_qsbs_exclusion.evaluate(QSBS, {"acquired": acquired, "sold": sold}) == percent


def test_qsbs_leap_day_acquisition_counts_whole_years():
    assert us_qsbs_exclusion.whole_years_held(date(2028, 2, 29), date(2031, 2, 28)) == 3
    assert us_qsbs_exclusion.whole_years_held(date(2028, 2, 29), date(2031, 2, 27)) == 2


def test_qsbs_gain_cap_is_the_greater_of_dollar_limit_and_basis_multiple():
    base = {"acquired": "2026-01-02", "sold": "2031-01-02"}
    assert us_qsbs_exclusion.evaluate(QSBS, {**base, "gain": 20000000, "adjusted_basis": 1000000}) == 15000000
    assert us_qsbs_exclusion.evaluate(QSBS, {**base, "gain": 20000000, "adjusted_basis": 2500000}) == 20000000
    assert us_qsbs_exclusion.evaluate(QSBS, {**base, "gain": 20000000, "adjusted_basis": 0, "prior_eligible_gain": 16000000}) == 0
    old = {"acquired": "2014-03-01", "sold": "2024-03-01", "gain": 12000000, "adjusted_basis": 500000, "prior_eligible_gain": 4000000}
    assert us_qsbs_exclusion.evaluate(QSBS, old) == 6000000


def test_qsbs_rejects_impossible_dates_and_uncovered_periods():
    with pytest.raises(ValueError):
        us_qsbs_exclusion.evaluate(QSBS, {"acquired": "2026-01-01", "sold": "2025-01-01"})
    with pytest.raises(ValueError):
        us_qsbs_exclusion.evaluate(QSBS, {"acquired": "1990-01-01", "sold": "2000-01-01"})
    assert us_qsbs_exclusion.statistic(QSBS, Statistic(name="dollar_limit", args=("after_applicable_date",))) == 15000000


BONUS = {
    "full_expensing_acquired_after": "2025-01-19",
    "full_expensing_percent": 100,
    "phase_down": {
        "general": [
            {"placed_in_service_after": "2017-09-27", "placed_in_service_before": "2023-01-01", "percent": 100},
            {"placed_in_service_after": "2022-12-31", "placed_in_service_before": "2024-01-01", "percent": 80},
            {"placed_in_service_after": "2023-12-31", "placed_in_service_before": "2025-01-01", "percent": 60},
            {"placed_in_service_after": "2024-12-31", "placed_in_service_before": "2026-01-01", "percent": 40},
            {"placed_in_service_after": "2025-12-31", "placed_in_service_before": "2027-01-01", "percent": 20},
        ],
        "longer_production_period": [
            {"placed_in_service_after": "2017-09-27", "placed_in_service_before": "2024-01-01", "percent": 100},
            {"placed_in_service_after": "2023-12-31", "placed_in_service_before": "2025-01-01", "percent": 80},
        ],
    },
}


def test_bonus_depreciation_depends_on_acquisition_then_placed_in_service_date():
    assert us_bonus_depreciation.evaluate(BONUS, {"acquired": "2025-01-19", "placed_in_service": "2025-02-01"}) == 40
    assert us_bonus_depreciation.evaluate(BONUS, {"acquired": "2025-01-20", "placed_in_service": "2025-02-01"}) == 100
    assert us_bonus_depreciation.evaluate(BONUS, {"acquired": "2022-06-01", "placed_in_service": "2023-01-01"}) == 80
    assert us_bonus_depreciation.evaluate(BONUS, {"acquired": "2022-06-01", "placed_in_service": "2023-01-01", "longer_production_period": True}) == 100
    assert us_bonus_depreciation.evaluate(BONUS, {"acquired": "2024-01-01", "placed_in_service": "2027-01-01"}) == 0


def test_bonus_depreciation_rejects_dates_outside_the_schedule():
    with pytest.raises(ValueError):
        us_bonus_depreciation.evaluate(BONUS, {"acquired": "2017-01-01", "placed_in_service": "2017-09-27"})
    with pytest.raises(ValueError):
        us_bonus_depreciation.evaluate(BONUS, {"acquired": "2024-05-01", "placed_in_service": "2024-04-01"})
    assert us_bonus_depreciation.statistic(BONUS, Statistic(name="count", args=("general",))) == 5


def test_plan_asset_test_matches_the_regulation_examples():
    params = {"threshold_percent": 25}
    assert erisa_plan_asset_test.evaluate(params, {"benefit_plan_value": 30, "total_value": 100}) is True
    assert erisa_plan_asset_test.evaluate(params, {"benefit_plan_value": 10, "total_value": 100}) is False
    example_4 = {"benefit_plan_value": 1000, "total_value": 10000, "disregarded_value": 6500}
    assert erisa_plan_asset_test.evaluate(params, {**example_4, "output": "share"}) == 28.6
    assert erisa_plan_asset_test.evaluate(params, example_4) is True
    assert erisa_plan_asset_test.is_significant(params, Decimal(25), Decimal(100)) is True


def test_plan_asset_test_rejects_inconsistent_values():
    with pytest.raises(ValueError):
        erisa_plan_asset_test.evaluate({"threshold_percent": 25}, {"benefit_plan_value": 10, "total_value": 100, "disregarded_value": 100})
    with pytest.raises(ValueError):
        erisa_plan_asset_test.evaluate({"threshold_percent": 25}, {"benefit_plan_value": 60, "total_value": 100, "disregarded_value": 50})


CARRY = {
    "qualifying_fraction_percent": 72.5,
    "holding_period_bands": [
        {"min_months": 0, "max_months": 36, "qualifying_percent": 0},
        {"min_months": 36, "max_months": 37, "qualifying_percent": 20},
        {"min_months": 37, "max_months": 38, "qualifying_percent": 40},
        {"min_months": 38, "max_months": 39, "qualifying_percent": 60},
        {"min_months": 39, "max_months": 40, "qualifying_percent": 80},
        {"min_months": 40, "max_months": None, "qualifying_percent": 100},
    ],
}


@pytest.mark.parametrize(("months", "percent"), [(0, 0), (35.99, 0), (36, 20), (37.5, 40), (39.99, 80), (40, 100), (120, 100)])
def test_carried_interest_qualifying_share_by_average_holding_period(months, percent):
    assert gb_carried_interest.evaluate(CARRY, {"average_holding_months": months}) == percent


def test_carried_interest_trading_profits_blend_qualifying_and_non_qualifying_amounts():
    assert gb_carried_interest.evaluate(CARRY, {"average_holding_months": 48, "carried_interest": 1000000}) == 725000
    assert gb_carried_interest.evaluate(CARRY, {"average_holding_months": 20, "carried_interest": 1000000}) == 1000000
    # 40% of 900,000 is qualifying: 540,000 taxed in full plus 72.5% of 360,000.
    assert gb_carried_interest.evaluate(CARRY, {"average_holding_months": 37, "carried_interest": 1000000, "permitted_deductions": 100000}) == 801000
    with pytest.raises(ValueError):
        gb_carried_interest.evaluate(CARRY, {"average_holding_months": -1})

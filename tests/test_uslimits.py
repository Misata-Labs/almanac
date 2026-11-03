"""Tests for the US withholding, poverty guideline, MACRS and conforming loan limit rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from almanac.models import Statistic
from almanac.rules import us_conforming_loan_limits, us_fit_withholding, us_macrs_depreciation, us_poverty_guidelines


def _row(at_least, less_than, base, rate, excess_over):
    return {"at_least": at_least, "less_than": less_than, "base": base, "rate_percent": rate, "excess_over": excess_over}


SINGLE_ROWS = [_row(0, 10000, 0, 0, 0), _row(10000, 50000, 0, 10, 10000), _row(50000, None, 4000, 20, 50000)]
WITHHOLDING = {
    "pay_periods": {"annually": 1, "monthly": 12, "biweekly": 26, "weekly": 52},
    "step2_adjustment": {"married_filing_jointly": 12000, "other": 6000},
    "allowance_value": 4000,
    "schedules": {
        "standard": {
            "single_or_married_filing_separately": SINGLE_ROWS,
            "married_filing_jointly": [_row(0, 20000, 0, 0, 0), _row(20000, None, 0, 10, 20000)],
            "head_of_household": [_row(0, None, 0, 10, 0)],
        },
        "checkbox": {
            "single_or_married_filing_separately": [_row(0, 5000, 0, 0, 0), _row(5000, None, 0, 20, 5000)],
            "married_filing_jointly": [_row(0, None, 0, 15, 0)],
            "head_of_household": [_row(0, None, 0, 12, 0)],
        },
    },
}


def test_tentative_withholding_follows_the_table_row():
    assert us_fit_withholding.tentative_annual_withholding(WITHHOLDING, 10000, "single") == Decimal("0.00")
    assert us_fit_withholding.tentative_annual_withholding(WITHHOLDING, 30000, "single") == Decimal("2000.00")
    assert us_fit_withholding.tentative_annual_withholding(WITHHOLDING, 60000, "married_filing_separately") == Decimal("6000.00")
    assert us_fit_withholding.tentative_annual_withholding(WITHHOLDING, 15000, "single", checkbox=True) == Decimal("2000.00")


def test_worksheet_annualises_adjusts_and_divides():
    # 2,500 monthly = 30,000 a year; less the 6,000 Step 2 adjustment = 24,000; 10% of 14,000 = 1,400 a year.
    sheet = {"wages": 2500, "pay_frequency": "monthly", "filing_status": "single"}
    assert us_fit_withholding.withholding(WITHHOLDING, sheet) == Decimal("116.67")
    # Step 3 credits are spread over the periods, Step 4(c) is added per period.
    sheet_with_credits = {**sheet, "step3": 1200, "step4c": 25}
    assert us_fit_withholding.withholding(WITHHOLDING, sheet_with_credits) == Decimal("41.67")
    # Credits never take withholding below zero before Step 4(c).
    assert us_fit_withholding.withholding(WITHHOLDING, {**sheet, "step3": 100000, "step4c": 10}) == Decimal("10.00")


def test_worksheet_checkbox_skips_the_step2_adjustment():
    sheet = {"wages": 2500, "pay_frequency": "monthly", "filing_status": "single", "checkbox": True}
    # 30,000 a year on the checkbox schedule: 20% of 25,000 = 5,000 a year.
    assert us_fit_withholding.withholding(WITHHOLDING, sheet) == Decimal("416.67")


def test_worksheet_handles_pre_2020_forms_with_allowances():
    sheet = {"wages": 3000, "pay_frequency": "monthly", "filing_status": "married", "form_w4_2020_or_later": False, "allowances": 2, "step3": 999}
    # 36,000 less two allowances of 4,000 = 28,000; 10% of 8,000 = 800 a year; Step 3 is ignored.
    assert us_fit_withholding.withholding(WITHHOLDING, sheet) == Decimal("66.67")


def test_withholding_rejects_unknown_inputs():
    with pytest.raises(KeyError):
        us_fit_withholding.schedule_name("widowed")
    with pytest.raises(KeyError):
        us_fit_withholding.withholding(WITHHOLDING, {"wages": 1, "pay_frequency": "fortnightly", "filing_status": "single"})


def test_withholding_evaluate_and_statistics():
    assert us_fit_withholding.evaluate(WITHHOLDING, {"adjusted_annual_wage": 50000, "filing_status": "single"}) == "4000.00"
    assert us_fit_withholding.statistic(WITHHOLDING, Statistic.parse("count")) == 10
    assert us_fit_withholding.statistic(WITHHOLDING, Statistic.parse("top_rate[standard,single_or_married_filing_separately]")) == 20


POVERTY = {
    "areas": {
        "contiguous_states_and_dc": {"guidelines": {1: 10000, 2: 13000, 3: 16000}, "additional_person": 3000},
        "alaska": {"guidelines": {"1": 12000, "2": 15500, "3": 19000}, "additional_person": 3500},
    }
}


def test_poverty_guideline_uses_table_then_increment():
    assert us_poverty_guidelines.guideline(POVERTY, "contiguous_states_and_dc", 2) == 13000
    assert us_poverty_guidelines.guideline(POVERTY, "alaska", 3) == 19000
    assert us_poverty_guidelines.guideline(POVERTY, "contiguous_states_and_dc", 5) == 22000
    with pytest.raises(ValueError):
        us_poverty_guidelines.guideline(POVERTY, "alaska", 0)
    with pytest.raises(KeyError):
        us_poverty_guidelines.guideline(POVERTY, "guam", 1)


def test_poverty_percent_of_guideline():
    assert us_poverty_guidelines.evaluate(POVERTY, {"area": "contiguous_states_and_dc", "persons": 1, "income": 13800}) == "138.00"
    assert us_poverty_guidelines.statistic(POVERTY, Statistic.parse("additional_person[alaska]")) == 3500


MACRS = {"rates": {"3-year": [33.33, 44.45, 14.81, 7.41], "5-year": [20.0, 32.0, 19.2, 11.52, 11.52, 5.76]}}


def test_macrs_rate_and_deduction():
    assert us_macrs_depreciation.rate(MACRS, "3-year", 2) == Decimal("44.45")
    assert us_macrs_depreciation.rate(MACRS, "3-year", 5) == Decimal(0)
    assert us_macrs_depreciation.deduction(MACRS, 10000, "5-year", 4) == 1152
    # Deductions round to the nearest whole dollar.
    assert us_macrs_depreciation.deduction(MACRS, 1500, "3-year", 4) == 111
    assert us_macrs_depreciation.deduction(MACRS, 150, "3-year", 1) == 50
    assert us_macrs_depreciation.evaluate(MACRS, {"recovery_period": "5-year", "year": 1}) == 20.0
    with pytest.raises(KeyError):
        us_macrs_depreciation.rate(MACRS, "39-year", 1)
    with pytest.raises(ValueError):
        us_macrs_depreciation.rate(MACRS, "5-year", 0)


def test_macrs_statistics():
    assert us_macrs_depreciation.statistic(MACRS, Statistic.parse("years[5-year]")) == 6
    assert us_macrs_depreciation.statistic(MACRS, Statistic.parse("total[5-year]")) == pytest.approx(100.0)


LOAN_LIMITS = {
    "baseline": {"one_unit": 100, "two_unit": 130, "three_unit": 160, "four_unit": 190},
    "counties": {"01001": "A COUNTY, AL", "06037": "B COUNTY, CA"},
    "above_baseline": {"06037": {"one_unit": 150, "two_unit": 195, "three_unit": 240, "four_unit": 285}},
}


def test_conforming_limits_default_to_baseline():
    assert us_conforming_loan_limits.limit(LOAN_LIMITS, "01001") == 100
    assert us_conforming_loan_limits.limit(LOAN_LIMITS, "06037", 4) == 285
    assert us_conforming_loan_limits.evaluate(LOAN_LIMITS, {"fips": "06037", "amount": 151}) is False
    assert us_conforming_loan_limits.evaluate(LOAN_LIMITS, {"fips": "01001", "units": 2, "amount": 130}) is True
    with pytest.raises(KeyError):
        us_conforming_loan_limits.limit(LOAN_LIMITS, "99999")
    with pytest.raises(ValueError):
        us_conforming_loan_limits.limit(LOAN_LIMITS, "01001", 5)


def test_conforming_limit_statistics():
    assert us_conforming_loan_limits.statistic(LOAN_LIMITS, Statistic.parse("count")) == 2
    assert us_conforming_loan_limits.statistic(LOAN_LIMITS, Statistic.parse("max[one_unit]")) == 150
    assert us_conforming_loan_limits.statistic(LOAN_LIMITS, Statistic.parse("limit[06037,2]")) == 195

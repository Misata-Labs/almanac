"""Unit tests for the Indian labour-code, MSME, Companies Act and market-cap rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from almanac.rules import in_companies_act, in_labour_codes, in_market_cap_category, in_msme

GRATUITY = {
    "formula": "gratuity",
    "days_per_year": 15,
    "month_divisor": 26,
    "part_year_months_above": 6,
    "qualifying_years": 5,
    "reasons_without_qualifying_service": ["death", "disablement", "fixed_term_expiry"],
    "fixed_term_qualifying_years": 1,
    "ceiling": 2000000,
}
RETRENCHMENT = {
    "formula": "retrenchment",
    "qualifying_months": 12,
    "days_per_year": 15,
    "part_year_months_above": 6,
    "reskilling_fund_days": 15,
    "layoff_compensation_percent": 50,
}
WAGE_PAYMENT = {
    "formula": "wage_payment",
    "payment_deadlines": {
        "daily": {},
        "weekly": {},
        "fortnightly": {"days_after_period_end": 2},
        "monthly": {"day_of_following_month": 7},
    },
    "deduction_ceiling_percent": 50,
}
CRORE = 10_000_000
MSME = {
    "schedules": [
        {"from": "2020-07-01", "ceilings": {"micro": {"investment": CRORE, "turnover": 5 * CRORE}, "small": {"investment": 10 * CRORE, "turnover": 50 * CRORE}, "medium": {"investment": 50 * CRORE, "turnover": 250 * CRORE}}},
        {"from": "2025-04-01", "ceilings": {"micro": {"investment": 25_000_000, "turnover": 10 * CRORE}, "small": {"investment": 25 * CRORE, "turnover": 100 * CRORE}, "medium": {"investment": 125 * CRORE, "turnover": 500 * CRORE}}},
    ]
}
CSR = {
    "formula": "csr",
    "applicability_thresholds": {"net_worth": 500 * CRORE, "turnover": 1000 * CRORE, "net_profit": 5 * CRORE},
    "spend_percent": 2,
    "averaging_years": 3,
    "committee_exemption_ceiling": 5_000_000,
}
SMALL = {"formula": "small_company", "paid_up_capital_ceiling": 4 * CRORE, "turnover_ceiling": 40 * CRORE, "excluded_flags": ["holding_or_subsidiary", "section_8_company", "special_act_company"]}


def test_code_wages_adds_back_exclusions_above_half():
    params = {"formula": "code_wages", "excluded_share_limit_percent": 50}
    assert in_labour_codes.code_wages(params, 40000, 60000) == Decimal(50000)
    assert in_labour_codes.code_wages(params, 50000, 50000) == Decimal(50000)
    assert in_labour_codes.evaluate(params, {"included": 70000, "excluded": 30000}) == "70000.00"


def test_bonus_floor_and_ceiling():
    params = {"formula": "bonus", "minimum_rate_fraction": [1, 12], "minimum_amount": 100, "maximum_percent": 20}
    assert in_labour_codes.evaluate(params, {"wages_earned": 120000}) == {"minimum": "10000.00", "maximum": "24000.00"}
    assert in_labour_codes.evaluate(params, {"wages_earned": 300}) == {"minimum": "100.00", "maximum": "100.00"}


def test_wage_payment_deadlines_cross_month_and_year_ends():
    assert in_labour_codes.wage_payment_deadline(WAGE_PAYMENT, "monthly", date(2026, 12, 31)) == date(2027, 1, 7)
    assert in_labour_codes.wage_payment_deadline(WAGE_PAYMENT, "fortnightly", date(2026, 2, 27)) == date(2026, 3, 1)
    assert in_labour_codes.wage_payment_deadline(WAGE_PAYMENT, "weekly", date(2026, 4, 11)) == date(2026, 4, 11)
    assert in_labour_codes.evaluate(WAGE_PAYMENT, {"deductions_ceiling_for": 12345}) == "6172.50"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ({"monthly_wage": 26000, "years": 5, "reason": "resignation"}, "75000.00"),
        ({"monthly_wage": 26000, "years": 5, "months": 7, "reason": "resignation"}, "90000.00"),
        ({"monthly_wage": 26000, "years": 4, "months": 11, "reason": "resignation"}, "0.00"),
        ({"monthly_wage": 26000, "years": 2, "reason": "disablement"}, "30000.00"),
        ({"monthly_wage": 26000, "years": 1, "months": 6, "reason": "resignation", "fixed_term": True}, "22500.00"),
        ({"monthly_wage": 26000, "years": 0, "months": 11, "reason": "fixed_term_expiry"}, "0.00"),
        ({"monthly_wage": 900000, "years": 25, "reason": "superannuation"}, "2000000.00"),
    ],
)
def test_gratuity(case, expected):
    assert in_labour_codes.evaluate(GRATUITY, case) == expected


def test_retrenchment_components():
    assert in_labour_codes.evaluate(RETRENCHMENT, {"component": "compensation", "average_daily_pay": 1000, "years": 3, "months": 7}) == "60000.00"
    assert in_labour_codes.evaluate(RETRENCHMENT, {"component": "compensation", "average_daily_pay": 1000, "years": 0, "months": 11}) == "0.00"
    assert in_labour_codes.evaluate(RETRENCHMENT, {"component": "reskilling_fund", "daily_wage": 800}) == "12000.00"
    assert in_labour_codes.evaluate(RETRENCHMENT, {"component": "layoff_daily", "daily_basic_and_dearness": 601}) == "300.50"


def test_unknown_formula_is_rejected():
    with pytest.raises(ValueError):
        in_labour_codes.evaluate({"formula": "overtime"}, {})


def test_msme_classification_is_composite_and_dated():
    assert in_msme.classify(MSME, CRORE, 6 * CRORE, date(2021, 1, 1)) == "small"
    assert in_msme.classify(MSME, 2 * CRORE, 8 * CRORE, date(2025, 3, 31)) == "small"
    assert in_msme.classify(MSME, 2 * CRORE, 8 * CRORE, date(2025, 4, 1)) == "micro"
    assert in_msme.classify(MSME, 126 * CRORE, 10 * CRORE, date(2026, 1, 1)) == "not_msme"
    with pytest.raises(ValueError):
        in_msme.classify(MSME, CRORE, CRORE, date(2020, 6, 30))


def test_small_company_and_exclusions():
    assert in_companies_act.evaluate(SMALL, {"paid_up_capital": 4 * CRORE, "turnover": 40 * CRORE})
    assert not in_companies_act.evaluate(SMALL, {"paid_up_capital": CRORE, "turnover": 41 * CRORE})
    assert not in_companies_act.evaluate(SMALL, {"paid_up_capital": CRORE, "turnover": CRORE, "special_act_company": True})


def test_csr_obligation_and_committee():
    case = {"net_worth": 0, "turnover": 0, "net_profit": 5 * CRORE, "preceding_net_profits": [5 * CRORE, 4 * CRORE, 3 * CRORE]}
    assert in_companies_act.evaluate(CSR, case) == {"applies": True, "obligation": "800000.00", "committee_required": False}
    large = {**case, "preceding_net_profits": [40 * CRORE, 30 * CRORE, 20 * CRORE]}
    assert in_companies_act.evaluate(CSR, large) == {"applies": True, "obligation": "6000000.00", "committee_required": True}
    assert in_companies_act.csr_obligation(CSR, [-5 * CRORE, CRORE, CRORE]) == Decimal(0)
    assert in_companies_act.csr_obligation(CSR, [CRORE, CRORE, CRORE, 100 * CRORE]) == Decimal("200000.00")
    assert not in_companies_act.csr_applies(CSR, 499 * CRORE, 999 * CRORE, 4 * CRORE)


def test_market_cap_category_boundaries():
    params = {"bands": [{"name": "large_cap", "from_rank": 1, "to_rank": 100}, {"name": "mid_cap", "from_rank": 101, "to_rank": 250}, {"name": "small_cap", "from_rank": 251, "to_rank": None}]}
    assert [in_market_cap_category.category(params, r) for r in (1, 100, 101, 250, 251, 5000)] == ["large_cap", "large_cap", "mid_cap", "mid_cap", "small_cap", "small_cap"]
    with pytest.raises(ValueError):
        in_market_cap_category.category(params, 0)

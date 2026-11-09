"""Unit tests for the Gulf end-of-service gratuity rule."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from almanac.models import Statistic
from almanac.rules import gcc_end_of_service as eos

SAUDI = {
    "wage_unit": "month",
    "tiers": [{"up_to_years": 5, "per_year": "1/2"}, {"up_to_years": None, "per_year": "1"}],
    "resignation": [
        {"from_years": 2, "from_inclusive": True, "fraction": "1/3"},
        {"from_years": 5, "from_inclusive": False, "fraction": "2/3"},
        {"from_years": 10, "from_inclusive": True, "fraction": "1"},
    ],
}
UAE = {
    "wage_unit": "day",
    "days_per_month": 30,
    "tiers": [{"up_to_years": 5, "per_year": "21"}, {"up_to_years": None, "per_year": "30"}],
    "minimum_years": 1,
    "cap_months": 24,
}


def test_accrual_by_service_year() -> None:
    assert eos.accrual_for_year(SAUDI, 1) == Fraction(1, 2)
    assert eos.accrual_for_year(SAUDI, 5) == Fraction(1, 2)
    assert eos.accrual_for_year(SAUDI, 6) == 1
    assert eos.accrual_for_year(UAE, 6) == 30
    with pytest.raises(ValueError):
        eos.accrual_for_year(SAUDI, 0)


def test_part_years_accrue_pro_rata_within_their_tier() -> None:
    assert eos.accrued_units(SAUDI, Fraction(5, 2)) == Fraction(5, 4)
    assert eos.accrued_units(SAUDI, Fraction(15, 2)) == 5
    assert eos.accrued_units(UAE, Fraction(11, 2)) == 105 + 15


def test_saudi_resignation_bands_follow_article_85() -> None:
    assert eos.resignation_fraction(SAUDI, Fraction(3, 2)) == 0
    assert eos.resignation_fraction(SAUDI, Fraction(2)) == Fraction(1, 3)
    assert eos.resignation_fraction(SAUDI, Fraction(5)) == Fraction(1, 3)
    assert eos.resignation_fraction(SAUDI, Fraction(51, 10)) == Fraction(2, 3)
    assert eos.resignation_fraction(SAUDI, Fraction(10)) == 1
    assert eos.resignation_fraction(UAE, Fraction(3)) == 1


def test_award_amounts() -> None:
    assert eos.award(SAUDI, 10000, 10) == Decimal("75000.00")
    assert eos.award(SAUDI, 10000, 3, "resignation") == Decimal("5000.00")
    assert eos.award(SAUDI, 8000, "7.5", "resignation") == Decimal("26666.67")
    assert eos.award(UAE, 10000, 5) == Decimal("35000.00")
    assert eos.award(UAE, 9000, "2.5") == Decimal("15750.00")


def test_minimum_service_and_cap() -> None:
    assert eos.award(UAE, 10000, "0.99") == Decimal("0.00")
    assert eos.award_in_months(UAE, Fraction(30)) == 24
    assert eos.award(UAE, 10000, 30) == Decimal("240000.00")


def test_rounding_step() -> None:
    assert eos.award({**SAUDI, "rounding": "0.001"}, 1000, Fraction(1, 3)) == Decimal("166.667")


def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        eos.award(SAUDI, 1000, 1, "retirement")
    with pytest.raises(ValueError):
        eos.award(SAUDI, 1000, -1)
    with pytest.raises(ValueError):
        eos.award({**SAUDI, "tiers": [{"up_to_years": 5, "per_year": "1"}]}, 1000, 1)
    with pytest.raises(ValueError):
        eos.award({**SAUDI, "wage_unit": "week"}, 1000, 1)


def test_evaluate_operations() -> None:
    assert eos.evaluate(SAUDI, {"monthly_wage": 10000, "years": 10}) == "75000.00"
    assert eos.evaluate(SAUDI, {"op": "accrual", "year": 3}) == "1/2"
    assert eos.evaluate(SAUDI, {"op": "resignation_fraction", "years": 7}) == "2/3"
    assert eos.evaluate(UAE, {"op": "award_months", "years": "0.9"}) == "0"
    assert eos.evaluate(UAE, {"op": "award_months", "years": 30}) == "24"
    with pytest.raises(ValueError):
        eos.evaluate(SAUDI, {"op": "unknown"})


def test_statistics() -> None:
    assert eos.statistic(UAE, Statistic.parse("tier_count")) == 2
    assert eos.statistic(UAE, Statistic.parse("accrual[2]")) == 21.0
    assert eos.statistic(UAE, Statistic.parse("cap_months")) == 24.0
    with pytest.raises(ValueError):
        eos.statistic(UAE, Statistic.parse("median"))

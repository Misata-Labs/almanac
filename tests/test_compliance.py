from __future__ import annotations

from decimal import Decimal

import pytest

from almanac.models import Statistic
from almanac.rules import eu_sca_exemptions, gb_dpa_penalty_maximum, gb_late_payment, us_deposit_insurance, us_form_8300, us_regf_call_frequency

FORM_8300 = {"threshold": 10000, "report_within_days": 15}
REG_F = {"max_calls_in_window": 7, "call_window_days": 7, "post_conversation_days": 7, "convenient_from": "08:00", "convenient_until": "21:00"}
FDIC = {
    "standard_maximum": 250000,
    "trust_rule": {"method": "per_beneficiary_capped", "max_beneficiaries": 5},
    "categories": {"joint": {"basis": "aggregate"}, "trust": {"basis": "per_beneficiary"}},
}
NCUA = {**FDIC, "trust_rule": {"method": "per_beneficiary_with_floor", "floor_beneficiaries": 5}}
LATE = {"fixed_sums": [{"below": 1000, "sum": 40}, {"below": 10000, "sum": 70}, {"below": None, "sum": 100}], "margin_percent": 8}
DPA = {"tiers": {"higher": {"fixed_gbp": 17500000, "turnover_percent": 4}, "standard": {"fixed_gbp": 8700000, "turnover_percent": 2}}}
SCA = {
    "contactless": {"max_amount_eur": 50, "max_cumulative_eur": 150, "max_consecutive": 5},
    "low_value_remote": {"max_amount_eur": 30, "max_cumulative_eur": 100, "max_consecutive": 5},
    "tra_bands": [
        {"etv_eur": 500, "card_reference_fraud_rate_percent": 0.01, "credit_transfer_reference_fraud_rate_percent": 0.005},
        {"etv_eur": 250, "card_reference_fraud_rate_percent": 0.06, "credit_transfer_reference_fraud_rate_percent": 0.01},
        {"etv_eur": 100, "card_reference_fraud_rate_percent": 0.13, "credit_transfer_reference_fraud_rate_percent": 0.015},
    ],
}


def test_form_8300_reports_initial_and_aggregated_payments():
    payments = [
        {"date": "1991-01-10", "amount": 11000},
        {"date": "1991-02-15", "amount": 4000},
        {"date": "1991-03-20", "amount": 6000},
        {"date": "1991-05-15", "amount": 12000},
    ]
    assert us_form_8300.reports(payments, FORM_8300) == [
        {"triggered_on": "1991-01-10", "due_by": "1991-01-25", "amount": 11000},
        {"triggered_on": "1991-05-15", "due_by": "1991-05-30", "amount": 22000},
    ]


def test_form_8300_window_drops_payments_older_than_a_year():
    payments = [{"date": "2026-01-05", "amount": 6000}, {"date": "2026-06-01", "amount": 3000}, {"date": "2027-03-01", "amount": 2000}]
    assert us_form_8300.reports(payments, FORM_8300) == []
    assert us_form_8300.reports([*payments, {"date": "2027-03-02", "amount": 6000}], FORM_8300)[0]["amount"] == 11000


def test_form_8300_threshold_is_exclusive_and_handles_leap_day():
    assert not us_form_8300.is_reportable(10000, FORM_8300)
    assert us_form_8300.is_reportable("10000.01", FORM_8300)
    leap = [{"date": "2024-02-29", "amount": 6000}, {"date": "2025-02-28", "amount": 6000}]
    assert us_form_8300.reports(leap, FORM_8300)[0]["triggered_on"] == "2025-02-28"


def test_regf_seven_calls_in_seven_days_and_conversation_quiet_period():
    week = [f"2026-04-0{d}" for d in range(1, 8)]
    assert us_regf_call_frequency.presumed_compliant(week[:6], [], week[6], REG_F)
    assert not us_regf_call_frequency.presumed_compliant(week, [], "2026-04-07", REG_F)
    assert us_regf_call_frequency.presumed_compliant(week, [], "2026-04-08", REG_F)
    assert not us_regf_call_frequency.presumed_compliant([], ["2026-08-14"], "2026-08-20", REG_F)
    assert us_regf_call_frequency.presumed_compliant([], ["2026-08-14"], "2026-08-21", REG_F)


def test_regf_inconvenient_time_boundaries():
    assert us_regf_call_frequency.is_inconvenient_time("07:59", REG_F)
    assert not us_regf_call_frequency.is_inconvenient_time("08:00", REG_F)
    assert not us_regf_call_frequency.is_inconvenient_time("21:00", REG_F)
    assert us_regf_call_frequency.is_inconvenient_time("21:00:01", REG_F)


def test_deposit_insurance_aggregates_to_the_limit():
    assert us_deposit_insurance.aggregate_coverage([75000, 100000, 125000], FDIC) == {"insured": 250000, "uninsured": 50000}
    assert us_deposit_insurance.aggregate_coverage([], FDIC) == {"insured": 0, "uninsured": 0}


def test_fdic_trust_coverage_caps_beneficiaries_and_scales_by_owner():
    assert us_deposit_insurance.trust_coverage(FDIC, beneficiaries=7) == {"coverage": 1250000}
    assert us_deposit_insurance.trust_coverage(FDIC, beneficiaries=2, owners=2, balance=900000) == {"coverage": 1000000, "insured": 900000, "uninsured": 0}


def test_ncua_trust_floor_applies_only_above_five_beneficiaries_and_balance():
    interests = [125000, 125000, 125000, 15000, 175000, 935000]
    assert us_deposit_insurance.trust_coverage(NCUA, beneficiary_interests=interests, balance=1500000)["coverage"] == 1250000
    assert us_deposit_insurance.trust_coverage(NCUA, beneficiary_interests=[250000, 275000, 275000, 275000, 15000, 175000, 310000], balance=1500000)["coverage"] == 1440000
    assert us_deposit_insurance.trust_coverage(NCUA, beneficiaries=7, balance=1000000)["coverage"] == 1750000
    with pytest.raises(ValueError):
        us_deposit_insurance.trust_coverage(NCUA, beneficiaries=7, balance=2000000)


def test_late_payment_bands_reference_day_and_rate():
    assert [gb_late_payment.fixed_sum(d, LATE) for d in (999.99, 1000, 9999.99, 10000)] == [40, 70, 70, 100]
    assert gb_late_payment.reference_day("2026-12-31").isoformat() == "2026-06-30"
    assert gb_late_payment.reference_day("2026-01-01").isoformat() == "2025-12-31"
    assert gb_late_payment.statutory_rate("3.75", LATE) == 11.75


def test_dpa_penalty_is_higher_of_fixed_or_turnover_share():
    assert gb_dpa_penalty_maximum.maximum_penalty("higher", DPA) == 17500000
    assert gb_dpa_penalty_maximum.maximum_penalty("higher", DPA, undertaking=True, turnover=2_000_000_000) == Decimal(80000000)
    assert gb_dpa_penalty_maximum.maximum_penalty("standard", DPA, undertaking=True, turnover=1_000_000) == 8700000
    with pytest.raises(ValueError):
        gb_dpa_penalty_maximum.maximum_penalty("standard", DPA, undertaking=True)


def test_sca_limit_exemptions_need_amount_and_one_running_limit():
    assert eu_sca_exemptions.limit_exempt("contactless", 50, 150, 9, SCA)
    assert eu_sca_exemptions.limit_exempt("contactless", 50, 151, 5, SCA)
    assert not eu_sca_exemptions.limit_exempt("contactless", 50, 151, 6, SCA)
    assert not eu_sca_exemptions.limit_exempt("low_value_remote", "30.01", 0, 0, SCA)


def test_sca_transaction_risk_analysis_threshold():
    assert eu_sca_exemptions.tra_threshold("card", 0.01, SCA) == 500
    assert eu_sca_exemptions.tra_threshold("card", 0.011, SCA) == 250
    assert eu_sca_exemptions.tra_threshold("credit_transfer", 0.015, SCA) == 100
    assert eu_sca_exemptions.tra_threshold("credit_transfer", 0.02, SCA) is None
    assert eu_sca_exemptions.tra_exempt("card", 0.13, 100, SCA)
    with pytest.raises(ValueError):
        eu_sca_exemptions.tra_threshold("cash", 0.01, SCA)
    assert eu_sca_exemptions.statistic(SCA, Statistic(name="max", args=("etv_eur",))) == 500

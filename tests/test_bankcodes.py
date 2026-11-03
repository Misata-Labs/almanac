from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from almanac.rules import (
    de_bank_account_check,
    de_default_interest,
    gb_account_standardisation,
    gb_sort_code_modulus,
    iban,
)

ENTRIES = Path(__file__).resolve().parent.parent / "entries"


def parameters(relative: str) -> dict:
    return yaml.safe_load((ENTRIES / relative).read_text(encoding="utf-8"))["spec"]["parameters"]


@pytest.fixture(scope="module")
def german() -> dict:
    return parameters("banking/DE/de-bank-account-check-digit-methods.yaml")


@pytest.fixture(scope="module")
def uk() -> dict:
    return parameters("banking/GB/gb-sort-code-modulus-check.yaml")


MOD10 = {"methods": {"00": {"variants": [{"positions": list(range(1, 10)), "weights": [2, 1], "check": 10, "reduce": "mod10", "cross_sum": True}]}}}


def test_german_cross_sum_method_pads_to_ten_digits():
    assert de_bank_account_check.is_valid("00", "9290701", MOD10)
    assert not de_bank_account_check.is_valid("00", "9290702", MOD10)


def test_german_rejects_malformed_accounts(german):
    assert not de_bank_account_check.is_valid("06", "12345678901", german)
    assert not de_bank_account_check.is_valid("06", "12a4", german)


def test_german_unknown_method_raises(german):
    with pytest.raises(KeyError):
        de_bank_account_check.is_valid("ZZ", "1234567", german)


def test_german_method_09_and_range_exception(german):
    assert de_bank_account_check.is_valid("09", "1", german)
    assert de_bank_account_check.is_valid("99", "0396000000", german)
    assert de_bank_account_check.is_valid("99", "0068007003", german)


def test_german_shifted_sub_account_variants(german):
    assert de_bank_account_check.is_valid("63", "0001234566", german)
    assert de_bank_account_check.is_valid("76", "0000123456", german)
    assert not de_bank_account_check.is_valid("63", "1123456600", german)


def test_german_digit_dependent_variants(german):
    assert de_bank_account_check.is_valid("61", "0260760481", german)
    assert de_bank_account_check.is_valid("88", "99913003", german)


def test_german_complete_issues_valid_numbers(german):
    for code in ("00", "06", "10", "32", "63"):
        filled = de_bank_account_check.complete(code, "0123456000", german)
        assert filled is not None and de_bank_account_check.is_valid(code, filled, german)


def test_german_method_24_procedure(german):
    assert de_bank_account_check.is_valid("24", "138301", german)
    assert not de_bank_account_check.is_valid("24", "138302", german)


def test_uk_test_cases_and_unchecked_sort_codes(uk):
    assert gb_sort_code_modulus.is_valid("089999", "66374958", uk)
    assert not gb_sort_code_modulus.is_valid("089999", "66374959", uk)
    assert gb_sort_code_modulus.is_valid("000001", "12345678", uk)
    assert gb_sort_code_modulus.is_valid("08-99-99", "66374958", uk)


def test_uk_exceptions(uk):
    assert gb_sort_code_modulus.is_valid("309070", "12345668", uk)
    assert gb_sort_code_modulus.is_valid("180002", "00000190", uk)
    assert not gb_sort_code_modulus.is_valid("938063", "15764273", uk)


def test_uk_rejects_malformed_input(uk):
    assert not gb_sort_code_modulus.is_valid("08999", "66374958", uk)
    assert not gb_sort_code_modulus.is_valid("089999", "6637495", uk)


def test_uk_row_parsing():
    row = gb_sort_code_modulus.parse_row("309001 309633 MOD11 0 0 3 2 9 8 5 7 6 5 4 3 2 1 2")
    assert row[2] == "MOD11" and row[3][4] == 9 and row[4] == 2
    assert gb_sort_code_modulus.parse_row("010004 016715 MOD11 0 0 0 0 0 0 8 7 6 5 4 3 2 1")[4] is None


STANDARDISE = {"ten_digit": {"natwest": "last_eight", "leeds": "first_eight"}, "nine_digit": {"santander": "first_digit_to_sort_code"}, "pad_from": 6}


def test_uk_account_standardisation():
    assert gb_account_standardisation.standardise("60-00-00", "01-23456789", "natwest", STANDARDISE) == ("600000", "23456789")
    assert gb_account_standardisation.standardise("090000", "123456789", "santander", STANDARDISE) == ("090001", "23456789")
    assert gb_account_standardisation.standardise("200000", "123456", None, STANDARDISE) == ("200000", "00123456")
    with pytest.raises(ValueError):
        gb_account_standardisation.standardise("200000", "1234567890", None, STANDARDISE)
    with pytest.raises(ValueError):
        gb_account_standardisation.standardise("200000", "12345", None, STANDARDISE)


IBAN = {"modulus": 97, "complement_base": 98, "valid_remainder": 1, "letter_values": {chr(65 + i): 10 + i for i in range(26)}, "lengths": {"AZ": 28}}


def test_iban_calculation_and_validation():
    assert iban.check_digits("AZ", "NABZ00000000137010002944", IBAN) == "84"
    assert iban.is_valid("az84 nabz 0000 0000 1370 1000 2944", IBAN)
    assert not iban.is_valid("AZ84NABZ0000000013701000294", IBAN)
    assert not iban.is_valid("AZ84NABZ0000000013701000294!", IBAN)
    assert not iban.is_valid("84AZ", IBAN)


def test_iban_single_digit_check_digits_are_zero_padded():
    for bban in ("NABZ00000000137010002900", "NABZ00000000137010002901", "NABZ00000000137010002902"):
        digits = iban.check_digits("AZ", bban, IBAN)
        assert len(digits) == 2 and iban.is_valid(f"AZ{digits}{bban}", IBAN)


DEFAULT = {
    "applies_from": "2014-07-29",
    "margin_points": {"consumer": 5, "business": 9},
    "flat_fee_eur": 40,
    "payment_period_days": 30,
    "base_rate_steps": [{"from": "2014-07-01", "value": -0.73}, {"from": "2026-07-01", "value": 1.52}],
}


def test_default_interest_rates_and_fee():
    assert de_default_interest.default_rate_on(DEFAULT, date(2026, 7, 1), consumer_involved=False) == Decimal("10.52")
    assert de_default_interest.default_rate_on(DEFAULT, date(2026, 6, 30), consumer_involved=True) == Decimal("4.27")
    assert de_default_interest.flat_fee(DEFAULT, debtor_is_consumer=True) == 0
    with pytest.raises(ValueError):
        de_default_interest.default_rate_on(DEFAULT, date(2014, 7, 28), consumer_involved=True)


def test_default_interest_payment_period_starts_after_later_event():
    assert de_default_interest.last_day_to_pay(DEFAULT, date(2026, 3, 10), date(2026, 3, 5)) == date(2026, 4, 9)
    with pytest.raises(ValueError):
        de_default_interest.evaluate(DEFAULT, {"unknown": 1})

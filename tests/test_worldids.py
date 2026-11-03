"""Unit tests for the national identifier rules added for the world's major economies."""

from __future__ import annotations

import pytest

from almanac.rules import (
    au_abn,
    be_national_number,
    ch_ahv_number,
    de_steuer_id,
    dk_cpr,
    fi_hetu,
    fr_siret,
    ie_pps,
    in_pan,
    iso7064_mod11_10,
    pl_pesel,
    se_personnummer,
    us_tin_format,
    weighted_modulus,
    za_id,
)

ABN = {"weights": [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19], "modulus": 89, "first_digit_offset": 1}
BSN = {"weights": [9, 8, 7, 6, 5, 4, 3, 2], "modulus": 11, "check": "remainder", "remainder_map": {"10": None}}
ORGNR = {"weights": [3, 2, 7, 6, 5, 4, 3, 2], "modulus": 11, "check": "complement", "remainder_map": {"0": 0, "1": None}}
LT = {
    "weights": [1, 2, 3, 4, 5, 6, 7, 8, 9, 1],
    "fallback_weights": [3, 4, 5, 6, 7, 8, 9, 1, 2, 3],
    "retry_remainder": 10,
    "modulus": 11,
    "check": "remainder",
    "remainder_map": {"10": 0},
}
PESEL = {
    "check_digit": {"weights": [1, 3, 7, 9, 1, 3, 7, 9, 1, 3], "modulus": 10, "check": "complement", "remainder_map": {"0": 0}},
    "month_offsets": {"80": 1800, "0": 1900, "20": 2000, "40": 2100, "60": 2200},
}
IDNR = {"check_digit": {"modulus": 11, "radix": 10, "body_length": 10}, "repeat_counts": [2, 3], "allow_leading_zero": False}
CPR = {
    "weights": [4, 3, 2, 7, 6, 5, 4, 3, 2],
    "modulus": 11,
    "centuries": [
        {"serial_first_digit": "4", "year_from": 0, "year_to": 36, "century": 2000},
        {"serial_first_digit": "4", "year_from": 37, "year_to": 99, "century": 1900},
        {"serial_first_digit": "5", "year_from": 58, "year_to": 99, "century": 1800},
    ],
}
BE = {"modulus": 97, "prefix_by_birth_period": {"1800-1999": "", "2000-": "2"}}
SSN = {"area_forbidden": ["000", "666"], "area_forbidden_ranges": [["900", "999"]], "group_forbidden": ["00"], "serial_forbidden": ["0000"]}
ZA = {"sex_ranges": {"female": [0, 4999], "male": [5000, 9999]}, "citizenship_codes": {"0": "citizen", "1": "permanent resident", "2": "refugee"}}
FI = {"century_signs": {"1800": ["+"], "1900": ["-", "Y"], "2000": ["A", "B"]}, "business_id_pattern": r"[0-9]{7}-[0-9]"}


def test_abn_worked_example_and_issuing():
    assert au_abn.is_valid("51 824 753 556", ABN)
    assert au_abn.weighted_sum("41824753556", {**ABN, "first_digit_offset": 0}) == 534
    assert au_abn.check_digits("824753556", ABN) == "51"
    assert not au_abn.is_valid("5182475355", ABN)


def test_weighted_modulus_remainder_and_invalid_remainder():
    assert weighted_modulus.is_valid("999990068", BSN)
    assert not weighted_modulus.is_valid("123456789", BSN)
    assert weighted_modulus.check_digit("60000000", BSN) is None


def test_weighted_modulus_complement_with_mapped_remainders():
    assert weighted_modulus.is_valid("974760673", ORGNR)
    assert weighted_modulus.check_digit("10000004", ORGNR) == "0"
    assert weighted_modulus.check_digit("10000013", ORGNR) is None


def test_weighted_modulus_fallback_pass():
    assert weighted_modulus.check_digit("3330924006", LT) == "4"
    assert weighted_modulus.is_valid("10101010005", LT)


def test_weighted_modulus_check_position_inside_number():
    params = {"weights": [3, 7, 9, 5, 8, 4, 2, 1, 6], "modulus": 11, "check": "remainder", "check_position": 4}
    body = "123" + "010180"
    digit = weighted_modulus.check_digit(body, params)
    assert weighted_modulus.is_valid("123" + digit + "010180", params)


def test_weighted_modulus_rejects_wrong_length():
    assert not weighted_modulus.is_valid("99999006", BSN)
    with pytest.raises(ValueError):
        weighted_modulus.check_digit("12a45678", BSN)


def test_pesel_example_and_century_decoding():
    assert pl_pesel.check_digit("0207080362", PESEL) == "8"
    assert pl_pesel.birth_date("02070803628", PESEL).isoformat() == "1902-07-08"
    assert pl_pesel.birth_date("02270803620", PESEL).year == 2002
    assert pl_pesel.sex("02070803628") == "female"
    assert not pl_pesel.is_valid("02990803628", PESEL)


def test_iso7064_and_idnr_examples():
    for number in ("02476291358", "86095742719", "47036892816", "65929970489", "57549285017", "25768131411"):
        assert iso7064_mod11_10.check_digit(number[:10], IDNR["check_digit"]) == number[-1]
    assert de_steuer_id.is_valid("86095742719", IDNR)
    assert not de_steuer_id.is_valid("02476291358", IDNR)
    assert de_steuer_id.is_valid("02476291358", {**IDNR, "allow_leading_zero": True})


def test_idnr_structure_rules():
    assert not de_steuer_id.has_valid_structure("1234567890", IDNR)
    assert not de_steuer_id.has_valid_structure("1112345678", IDNR)
    assert de_steuer_id.has_valid_structure("6592997048", IDNR)
    assert not de_steuer_id.has_valid_structure("1122345678", IDNR)


def test_cpr_example_and_unused_remainder():
    assert dk_cpr.check_digit("070761428", CPR) == "5"
    assert dk_cpr.satisfies_modulus("070761-4285", CPR)
    assert dk_cpr.birth_date("0707614285", CPR).isoformat() == "1961-07-07"
    assert dk_cpr.birth_date("0101204002", CPR).year == 2020
    bodies = (f"{i:09d}" for i in range(10**8, 10**8 + 200))
    assert any(dk_cpr.check_digit(body, CPR) is None for body in bodies)


def test_belgian_number_periods():
    assert be_national_number.control_number("420122051", "1800-1999", BE) == "81"
    assert be_national_number.birth_period_of("42.01.22.051-81", BE) == "1800-1999"
    control = be_national_number.control_number("010203001", "2000-", BE)
    assert be_national_number.birth_period_of(f"010203001{control}", BE) == "2000-"
    assert be_national_number.sex("42012205181") == "male"
    with pytest.raises(ValueError):
        be_national_number.control_number("420122051", "1700-", BE)


def test_personnummer_forms():
    assert se_personnummer.check_digit("640823323", {}) == "4"
    assert se_personnummer.is_valid("640823-3234", {})
    assert se_personnummer.is_valid("196408233234", {})
    assert not se_personnummer.is_valid("640823-323", {})


def test_south_african_id():
    body = "940510500108"
    number = body + za_id.check_digit(body, {})
    assert za_id.is_valid(number, ZA)
    assert za_id.sex(number, ZA) == "male"
    assert za_id.citizenship(number, ZA) == "citizen"
    assert not za_id.is_valid(body + "3" + number[-1], ZA)


def test_ssn_and_itin_formats():
    assert us_tin_format.is_valid("234-56-7890", SSN)
    for bad in ("000-12-3456", "666-12-3456", "950-12-3456", "234-00-3456", "234-56-0000"):
        assert not us_tin_format.is_valid(bad, SSN)
    itin = {"area_required_prefix": "9"}
    assert us_tin_format.mask_is_consistent("9xx-xx-xxxx", itin)
    assert not us_tin_format.is_valid("812-70-1234", itin)


def test_shape_only_rules():
    assert fr_siret.siren_of("999 999 999 99999", {"siren_length": 9, "nic_length": 5}) == "999999999"
    assert ch_ahv_number.parts("756.1234.5678.97", {"country_code": "756"})["control_digit"] == "7"
    pan = {"holder_types": {"P": "Individual"}, "sequence_range": [1, 9999]}
    assert in_pan.holder_type("AFZPK7190K", pan) == "Individual"
    assert not in_pan.is_valid("AFZPK0000K", pan)
    trn = {"patterns": {"trn": r"[0-9]{7}[A-Z]{1,2}"}}
    assert ie_pps.is_valid("1497955KA", trn, "trn")
    with pytest.raises(KeyError):
        ie_pps.is_valid("CHY 1", trn, "chy")


def test_finnish_century_signs():
    assert fi_hetu.century_of("A", FI) == 2000
    assert fi_hetu.is_personal_code("010190-123K", FI)
    assert not fi_hetu.is_personal_code("010190Z123K", FI)
    assert fi_hetu.is_business_id("1234567-8", FI)
    with pytest.raises(ValueError):
        fi_hetu.century_of("Q", FI)

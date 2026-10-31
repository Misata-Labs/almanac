from __future__ import annotations

from datetime import date

import pytest

from almanac.rules import br_pix_identifiers, gb_bank_holidays, gb_clock_change, gb_nino, gb_utr, gb_vrn, load_rule
from almanac.models import Statistic

NINO = {
    "excluded_first_letters": list("DFIQUV"),
    "excluded_second_letters": list("DFIOQUV"),
    "invalid_prefixes": ["BG", "GB", "NK", "KN", "TN", "NT", "ZZ"],
    "suffix_letters": list("ABCD"),
    "optional_spaces": True,
}
UTR = {"length": 10, "weights": [6, 7, 8, 9, 10, 5, 4, 3, 2], "remainder_lookup": "21987654321", "modulus": 11, "check_position": 0, "sa_affix": "K"}
VRN = {"length": 9, "weights": [8, 7, 6, 5, 4, 3, 2], "modulus": 97, "variant_offset": 55}
CLOCK = {"transitions": {"forward": {"month": 3, "weekday": "sunday", "ordinal": "last"}, "back": {"month": 10, "weekday": "sunday", "ordinal": "last"}}}
PIX = {"fields": {"txid": {"pattern": "[a-zA-Z0-9]{26,35}"}, "end_to_end_id": {"pattern": "[a-zA-Z0-9]{32}", "min_length": 32, "max_length": 32}}}
HOLIDAYS = {
    "divisions": {
        "scotland": {"2026": [{"date": "2026-01-01"}, {"date": "2026-01-02"}]},
        "england-and-wales": {"2026": [{"date": "2026-01-01"}]},
    }
}


def test_load_rule_rejects_modules_outside_package():
    with pytest.raises(ValueError):
        load_rule("os.path")


def test_nino_pattern_is_built_from_exclusions():
    assert gb_nino.build_pattern(NINO).pattern.startswith("[ABCEGHJKLMNOPRSTWXYZ][ABCEGHJKLMNPRSTWXYZ]")
    assert gb_nino.is_valid("AB123456C", NINO)
    assert not gb_nino.is_valid("AB123456C\n", NINO)


def test_nino_without_optional_spaces():
    strict = {**NINO, "optional_spaces": False}
    assert not gb_nino.is_valid("AB 12 34 56 C", strict)
    assert gb_nino.is_valid("AB123456C", strict)


def test_utr_check_digit_reproduces_official_examples():
    assert gb_utr.check_digit("234567890", UTR) == "2"
    assert gb_utr.check_digit("108834503", UTR) == "2"
    assert gb_utr.check_digit("097172564", UTR) == "1"


def test_utr_check_digit_rejects_wrong_length():
    with pytest.raises(ValueError):
        gb_utr.check_digit("12345", UTR)


def test_utr_affix_only_for_self_assessment():
    assert gb_utr.is_valid("K2234567890", UTR, "sa")
    assert not gb_utr.is_valid("K2234567890", UTR, "ct")
    with pytest.raises(ValueError):
        gb_utr.is_valid("2234567890", UTR, "paye")


def test_vrn_check_digit_variants():
    assert gb_vrn.check_digits("1017476", VRN, "mod97") == "96"
    assert gb_vrn.check_digits("1017476", VRN, "mod9755") == "41"
    assert gb_vrn.check_digits("0000000", VRN) == "97"
    with pytest.raises(ValueError):
        gb_vrn.check_digits("1017476", VRN, "mod42")


def test_vrn_generated_numbers_validate():
    for body in ("1234567", "0000001", "9999999"):
        for variant in ("mod97", "mod9755"):
            assert gb_vrn.is_valid(body + gb_vrn.check_digits(body, VRN, variant), VRN)


def test_clock_change_last_sunday():
    assert gb_clock_change.last_weekday_of_month(2026, 3, "sunday") == date(2026, 3, 29)
    assert gb_clock_change.last_weekday_of_month(2027, 10, "sunday") == date(2027, 10, 31)
    assert gb_clock_change.clock_changes(CLOCK, 2028) == {"forward": "2028-03-26", "back": "2028-10-29"}


def test_summer_time_window_is_inclusive():
    assert gb_clock_change.is_summer_time(date(2026, 3, 29), CLOCK)
    assert gb_clock_change.is_summer_time(date(2026, 10, 25), CLOCK)
    assert not gb_clock_change.is_summer_time(date(2026, 10, 26), CLOCK)
    assert not gb_clock_change.is_summer_time(date(2026, 3, 28), CLOCK)


def test_clock_change_rejects_unknown_ordinal():
    broken = {"transitions": {"forward": {"month": 3, "weekday": "sunday", "ordinal": "first"}}}
    with pytest.raises(ValueError):
        gb_clock_change.transition(broken, 2026, "forward")


def test_bank_holiday_lookup_and_statistics():
    assert gb_bank_holidays.is_bank_holiday(date(2026, 1, 2), HOLIDAYS, "scotland")
    assert not gb_bank_holidays.is_bank_holiday(date(2026, 1, 2), HOLIDAYS, "england-and-wales")
    assert gb_bank_holidays.statistic(HOLIDAYS, Statistic.parse("count[scotland,2026]")) == 2
    with pytest.raises(KeyError):
        gb_bank_holidays.holidays(HOLIDAYS, "scotland", 1999)
    with pytest.raises(ValueError):
        gb_bank_holidays.statistic(HOLIDAYS, Statistic.parse("mean"))


def test_pix_field_validation():
    assert br_pix_identifiers.is_valid("a" * 26, PIX, "txid")
    assert not br_pix_identifiers.is_valid("a" * 36, PIX, "txid")
    assert br_pix_identifiers.is_valid("E" + "1" * 31, PIX, "end_to_end_id")
    assert not br_pix_identifiers.is_valid("E" + "1" * 32, PIX, "end_to_end_id")
    with pytest.raises(KeyError):
        br_pix_identifiers.is_valid("x", PIX, "unknown")


from almanac.rules import enumeration, gb_email_address, gb_hmrc_reference, gb_tax_code

HMRC_REF = {
    "modulus": 23,
    "check_alphabet": "ABCDEFGHXJKLMNYPQRSTZVW",
    "families": {
        "sdlt": {
            "pattern": r"^\d{9}M[A-Z]$",
            "check_index": 10,
            "weights": [6, 7, 8, 9, 10, 5, 4, 3, 2],
            "letter_values": {},
        },
        "epaye": {
            "pattern": r"^\d{3}P[A-Z]\d{6}[A-Z_0-9]{2}$",
            "check_index": 4,
            "weights": [9, 10, 11, 12, 0, 8, 7, 6, 5, 4, 3, 2, 1],
            "letter_values": {"A": 33, "B": 34, "W": 55, "X": 41, "Y": 47},
            "special_prefix": "961",
            "special_prefix_pattern": r"^961P[A-Z]\d{8}$",
        },
    },
}


def test_character_values_follow_the_source_fallback():
    assert gb_hmrc_reference.character_value("7", {}) == 7
    assert gb_hmrc_reference.character_value("A", {"A": 33}) == 33
    assert gb_hmrc_reference.character_value("I", {}) == 18
    assert gb_hmrc_reference.character_value("_", {}) == -1


def test_sdlt_check_character_can_be_generated():
    assert gb_hmrc_reference.check_character("123456789M", HMRC_REF, "sdlt") == "A"
    assert gb_hmrc_reference.is_valid("123456789MA", HMRC_REF, "sdlt")
    assert not gb_hmrc_reference.is_valid("123456789MB", HMRC_REF, "sdlt")


def test_epaye_special_prefix_rules():
    assert gb_hmrc_reference.is_valid("961PA0045782X", HMRC_REF, "epaye")
    assert not gb_hmrc_reference.is_valid("961PA1145782X", HMRC_REF, "epaye")


def test_tax_code_and_email_patterns():
    assert gb_tax_code.is_valid("1257L", {"pattern": r"^([K]*([1-9][0-9]{0,5}|0)[TLPY]*|BR|NT|D[01])$"})
    assert not gb_tax_code.is_valid("1257L\n", {"pattern": r"^([K]*([1-9][0-9]{0,5}|0)[TLPY]*|BR|NT|D[01])$"})
    params = {"address_pattern": r"^([a-z]+)@([a-z]+(?:\.[a-z]+)*)$", "domain_pattern": r"^([a-z]+(?:\.[a-z]+)*)$"}
    assert gb_email_address.evaluate(params, "a@b.c")
    assert gb_email_address.evaluate(params, {"part": "domain", "value": "b.c"})
    assert not gb_email_address.evaluate(params, {"part": "domain", "value": "b."})


def test_enumeration_membership_and_labels():
    params = {"sets": {"status": {"active": "Active", "dissolved": "Dissolved"}}}
    assert enumeration.is_member("active", params, "status")
    assert enumeration.label("dissolved", params, "status") == "Dissolved"
    assert enumeration.statistic(params, Statistic.parse("count[status]")) == 2
    with pytest.raises(KeyError):
        enumeration.codes(params, "type")
    with pytest.raises(ValueError):
        enumeration.statistic(params, Statistic.parse("mean"))

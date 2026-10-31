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


from almanac.rules import br_cnpj, rate_schedule

CNPJ = {
    "base_pattern": r"^[0-9A-Z]{12}$",
    "modulus": 11,
    "zero_below_remainder": 2,
    "weights_first": [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    "weights_second": [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
}
GST = {"slabs": {"nil": 0, "merit": 5, "standard": 18, "de_merit": 40}}


def test_cnpj_reproduces_the_receita_federal_example():
    assert br_cnpj.check_digits("12.ABC.345/01DE", CNPJ) == "35"
    assert br_cnpj.is_valid("12.ABC.345/01DE-35", CNPJ)
    assert not br_cnpj.is_valid("12.ABC.345/01DE-36", CNPJ)


def test_cnpj_character_values_and_zero_rule():
    assert br_cnpj.character_value("A") == 17 and br_cnpj.character_value("0") == 0
    zero_rule = {**CNPJ, "zero_below_remainder": 2}
    base = "000000000000"
    assert br_cnpj.check_digits(base, zero_rule) == "00"
    with pytest.raises(ValueError):
        br_cnpj.check_digits("12345", CNPJ)
    assert not br_cnpj.is_valid("12.ABC.345/01DE-3X", CNPJ)


def test_gst_slabs():
    assert rate_schedule.is_slab(18, GST) and not rate_schedule.is_slab(12, GST)
    assert rate_schedule.slab_name(40, GST) == "de_merit"
    assert rate_schedule.statistic(GST, Statistic.parse("slab[merit]")) == 5
    assert rate_schedule.statistic(GST, Statistic.parse("count")) == 4
    with pytest.raises(KeyError):
        rate_schedule.slab_name(12, GST)


from almanac.rules import age_band_rates, income_tax_bands, lookup_table, step_schedule

TAX = {"personal_allowance": 12570, "taper": {"above": 100000, "ratio": 2}, "bands": [{"name": "basic", "up_to": 37700, "rate_percent": 20}, {"name": "higher", "up_to": 112570, "rate_percent": 40}, {"name": "additional", "up_to": None, "rate_percent": 45}]}
WAGES = {"bands": [{"name": "adult", "min_age": 21}, {"name": "youth", "min_age": 18, "max_age": 20}, {"name": "minor", "max_age": 17}], "tables": [{"from": "2026-04-01", "rates": {"adult": 12.71, "youth": 10.85, "minor": 8, "apprentice": 8}}, {"from": "2027-04-01", "rates": {"adult": 13.21, "youth": 11.27, "minor": 8.31, "apprentice": 8.31}}]}
STEPS = {"steps": [{"from": "2025-01-01", "value": 12.25}, {"from": "2025-01-30", "value": 13.25}, {"from": "2025-06-19", "value": 15.0}]}
TABLE = {"rows": {"IND": {"value": 2.5, "name": "India"}, "GBR": {"value": 50.0, "name": "United Kingdom"}}}


def test_income_tax_bands_compute_allowance_and_tax():
    from decimal import Decimal

    assert income_tax_bands.tax_due(TAX, 35000) == Decimal("4486.00")
    assert income_tax_bands.tax_due(TAX, 12570) == Decimal("0.00")
    assert income_tax_bands.tax_due(TAX, 50270) == Decimal("7540.00")
    assert income_tax_bands.personal_allowance(TAX, Decimal(110000)) == Decimal(7570)
    assert income_tax_bands.personal_allowance(TAX, Decimal(130000)) == Decimal(0)
    assert income_tax_bands.evaluate(TAX, {"income": 200000}) == "76831.50"
    assert income_tax_bands.statistic(TAX, Statistic.parse("rate[higher]")) == 40


def test_age_band_rates_pick_table_and_band():
    assert age_band_rates.rate(WAGES, 30, date(2026, 6, 1)) == 12.71
    assert age_band_rates.rate(WAGES, 19, date(2027, 4, 1)) == 11.27
    assert age_band_rates.rate(WAGES, 30, date(2026, 6, 1), category="apprentice") == 8
    with pytest.raises(ValueError):
        age_band_rates.rate(WAGES, 30, date(2020, 1, 1))
    assert age_band_rates.statistic(WAGES, Statistic.parse("rate[minor,2027-05-01]")) == 8.31


def test_step_schedule_value_in_force():
    assert step_schedule.value_on(STEPS, date(2025, 1, 29)) == 12.25
    assert step_schedule.value_on(STEPS, date(2025, 1, 30)) == 13.25
    assert step_schedule.evaluate(STEPS, {"on": "2025-12-31"}) == 15.0
    with pytest.raises(ValueError):
        step_schedule.value_on(STEPS, date(2024, 12, 31))
    assert step_schedule.statistic(STEPS, Statistic.parse("max")) == 15.0
    assert step_schedule.statistic(STEPS, Statistic.parse("count")) == 3


def test_lookup_table_rows_and_statistics():
    assert lookup_table.lookup(TABLE, "IND", "value") == 2.5
    assert lookup_table.evaluate(TABLE, "GBR") is True and lookup_table.evaluate(TABLE, "WLD") is False
    assert lookup_table.statistic(TABLE, Statistic.parse("max[value]")) == 50.0
    assert lookup_table.statistic(TABLE, Statistic.parse("value[IND,name]")) == "India"
    with pytest.raises(KeyError):
        lookup_table.lookup(TABLE, "ZZZ")

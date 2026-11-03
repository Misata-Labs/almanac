"""Unit tests for the e-invoicing rule modules: schema field formats, SdI file names, Peppol participant identifiers and ZATCA transaction codes."""

from __future__ import annotations

import pytest

from almanac.rules import einvoice_field_format, it_sdi_file_name, peppol_participant_id, sa_zatca_transaction_code

FIELDS = {
    "fields": {
        "CodiceDestinatario": {"patterns": ["[A-Z0-9]{6,7}"]},
        "Titolo": {"patterns": ["(\\p{IsBasicLatin}{2,10})"]},
        "Denominazione": {"patterns": ["[\\p{IsBasicLatin}\\p{IsLatin-1Supplement}]{1,80}"]},
        "RFC": {
            "patterns": ["[A-Z&Ñ]{3,4}[0-9]{2}(0[1-9]|1[012])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{2}[0-9A]"],
            "min_length": 12,
            "max_length": 13,
            "whitespace": "collapse",
        },
        "Fixed": {"length": 4},
    }
}

SDI = {"identifier_length": {"IT": [11, 16], "other": [2, 28]}, "progressive_max_length": 5, "extensions": [".xml", ".xml.p7m", ".zip"]}

PEPPOL = {
    "meta_scheme": "iso6523-actorid-upis",
    "min_value_length": 1,
    "max_value_length": 130,
    "value_pattern": "[A-Za-z0-9._~-]+",
    "active_icd": ["0002", "0088", "0208"],
}

ZATCA = {
    "type_codes": {"388": {}, "386": {}, "383": {}, "381": {}},
    "subtypes": {"01": "tax invoice", "02": "simplified tax invoice"},
    "flags": ["third_party", "nominal", "export", "summary", "self_billed"],
    "forbidden_combinations": [["export", "self_billed"]],
}


def test_patterns_match_the_whole_value():
    assert einvoice_field_format.is_valid("ABC1234", FIELDS, "CodiceDestinatario")
    assert einvoice_field_format.is_valid("AAAAAA", FIELDS, "CodiceDestinatario")
    assert not einvoice_field_format.is_valid("XABC1234", FIELDS, "CodiceDestinatario")
    assert not einvoice_field_format.is_valid("ABC12", FIELDS, "CodiceDestinatario")


def test_unicode_block_escapes_translate_inside_and_outside_classes():
    assert einvoice_field_format.is_valid("Dott.", FIELDS, "Titolo")
    assert not einvoice_field_format.is_valid("Dótt", FIELDS, "Titolo")
    assert einvoice_field_format.is_valid("Società Agricola", FIELDS, "Denominazione")
    assert not einvoice_field_format.is_valid("Ŝocietà", FIELDS, "Denominazione")


def test_length_and_whitespace_facets():
    assert einvoice_field_format.is_valid(" AAA010101AAA ", FIELDS, "RFC")
    assert einvoice_field_format.is_valid("AAAA010101AA1", FIELDS, "RFC")
    assert not einvoice_field_format.is_valid("AAA011301AAA", FIELDS, "RFC")
    assert einvoice_field_format.is_valid("abcd", FIELDS, "Fixed")
    assert not einvoice_field_format.is_valid("abc", FIELDS, "Fixed")


def test_unknown_field_and_block_are_errors():
    with pytest.raises(KeyError):
        einvoice_field_format.is_valid("x", FIELDS, "Missing")
    with pytest.raises(ValueError):
        einvoice_field_format.compile_pattern("\\p{IsGreek}+")


def test_sml_hash_matches_policy_example_and_ignores_case():
    expected = "Y7DZFXAF3D4CJZ4KCGRXTEC6TWVCGA4KY7ZWA5BOIF6MSWD4TDRQ"
    assert peppol_participant_id.sml_hash("0088:123abc") == expected
    assert peppol_participant_id.sml_hash("0088:123ABC") == expected
    assert peppol_participant_id.sml_hash("iso6523-actorid-upis::0088:123abc") == expected
    name = peppol_participant_id.dns_name("0088:123abc", PEPPOL, "edelivery.tech.ec.europa.eu.")
    assert name == f"{expected}.iso6523-actorid-upis.edelivery.tech.ec.europa.eu."


@pytest.mark.parametrize(
    ("identifier", "valid"),
    [
        ("0088:7300010000001", True),
        ("0002:542034942", True),
        ("iso6523-actorid-upis::0208:0123456789", True),
        ("other-scheme::0088:7300010000001", False),
        ("0088", False),
        ("0088:", False),
        ("0088:" + "9" * 130, True),
        ("0088:" + "9" * 131, False),
        ("0088:abc/def", False),
        ("9999:abc", False),
    ],
)
def test_participant_identifier_validity(identifier, valid):
    assert peppol_participant_id.is_valid(identifier, PEPPOL) is valid


def test_transaction_code_parsing_and_rules():
    parsed = sa_zatca_transaction_code.parse("0211010", ZATCA)
    assert parsed == {"subtype": "02", "third_party": True, "nominal": True, "export": False, "summary": True, "self_billed": False}
    assert sa_zatca_transaction_code.is_valid("0100000", ZATCA)
    assert sa_zatca_transaction_code.is_valid("0100001", ZATCA)
    assert not sa_zatca_transaction_code.is_valid("0100101", ZATCA)
    assert not sa_zatca_transaction_code.is_valid("0100200", ZATCA)
    assert not sa_zatca_transaction_code.is_valid("03000000", ZATCA)


def test_transaction_code_evaluate_dispatch():
    assert sa_zatca_transaction_code.evaluate(ZATCA, {"type_code": "386"}) is True
    assert sa_zatca_transaction_code.evaluate(ZATCA, {"type_code": "380"}) is False
    assert sa_zatca_transaction_code.evaluate(ZATCA, {"transaction_code": "0100100", "field": "export"}) is True


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("ITAAABBB99T99X999W_00001.xml", True),
        ("IT99999999999_00002.xml.p7m", True),
        ("IT99999999999_a1B2.zip", True),
        ("FR12_1.xml", True),
        ("FR1_1.xml", False),
        ("IT9999999999_00001.xml", False),
        ("IT99999999999_000001.xml", False),
        ("it99999999999_00001.xml", False),
        ("IT99999999999_00001.xml.zip", False),
        ("IT99999999999.xml", False),
    ],
)
def test_sdi_file_names(name, valid):
    assert it_sdi_file_name.is_valid(name, SDI) is valid


def test_sdi_file_name_parts():
    assert it_sdi_file_name.parse("IT99999999999_00002.xml.p7m") == {"country": "IT", "identifier": "99999999999", "progressive": "00002", "extension": ".xml.p7m"}

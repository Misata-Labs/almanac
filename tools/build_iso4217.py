"""Regenerate the ISO 4217 currency entry from the maintenance agency's published list.

SIX Financial Information maintains ISO 4217 on behalf of ISO and publishes
the current list as XML (List One). Run from the repository root:

    uv run python tools/build_iso4217.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

URL = "https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml"
PUBLISHER = "SIX Financial Information (ISO 4217 Maintenance Agency)"
LICENSE = "unstated"


def build(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    published = root.attrib["Pblshd"]
    currencies: dict[str, dict] = {}
    for entry in root.iter("CcyNtry"):
        code = entry.findtext("Ccy")
        if not code:
            continue
        units = entry.findtext("CcyMnrUnts")
        currencies.setdefault(
            code,
            {
                "name": entry.findtext("CcyNm"),
                "numeric": entry.findtext("CcyNbr"),
                "minor_units": None if units in (None, "N.A.") else int(units),
            },
        )
    currencies = dict(sorted(currencies.items()))
    by_units = {}
    for c in currencies.values():
        by_units[c["minor_units"]] = by_units.get(c["minor_units"], 0) + 1

    def ev(locator: str, value, unit: str, snippet: str, role: str = "primary") -> dict:
        return evidence(PUBLISHER, f"ISO 4217 List One (current currency and funds codes), published {published}", URL, locator, value, unit, snippet, LICENSE, raw, role)

    vectors = [
        {"input": "USD", "expected": True, "origin": "source"},
        {"input": "XXX", "expected": True, "origin": "source", "note": "the code for transactions with no currency"},
        {"input": "ZZZ", "expected": False, "origin": "derived"},
        {"input": {"minor_units_of": "JPY"}, "expected": 0, "origin": "source"},
        {"input": {"minor_units_of": "KWD"}, "expected": 3, "origin": "source"},
        {"input": {"minor_units_of": "USD"}, "expected": 2, "origin": "source"},
        {"input": {"minor_units_of": "CLF"}, "expected": 4, "origin": "source"},
        {"input": {"minor_units_of": "XAU"}, "expected": None, "origin": "source", "note": "listed as N.A."},
        {"input": {"amount": "100.50", "currency": "USD"}, "expected": True, "origin": "derived"},
        {"input": {"amount": "100.5", "currency": "JPY"}, "expected": False, "origin": "derived"},
        {"input": {"amount": "1.234", "currency": "BHD"}, "expected": True, "origin": "derived"},
        {"input": {"amount": "1.2345", "currency": "BHD"}, "expected": False, "origin": "derived"},
    ]
    return {
        "id": "global-iso4217-currency-minor-units",
        "title": f"ISO 4217 current currency codes with numeric codes and minor units, list published {published}",
        "kind": "rule",
        "domain": "currency",
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "valid_from": published,
        "valid_to": None,
        "spec": {"implementation": "almanac.rules.currency_minor_units", "parameters": {"published": published, "currencies": currencies}, "vectors": vectors},
        "evidence": [
            ev("ISO_4217@Pblshd", published, "date", "<ISO_4217 Pblshd="),
            ev("CcyNtry[Ccy=JPY]/CcyMnrUnts", "0", "integer", "<Ccy>JPY</Ccy>"),
            ev("CcyNtry[Ccy=KWD]/CcyMnrUnts", "3", "integer", "<Ccy>KWD</Ccy>"),
            ev("CcyNtry[Ccy=XAU]/CcyMnrUnts", "N.A.", "text", "<Ccy>XAU</Ccy>"),
        ],
        "assumed": [
            {
                "parameter": "currencies[*].minor_units = null",
                "value": "N.A. in the source",
                "method": "derived",
                "rationale": "The list marks precious metals, test codes and the no-currency code with N.A.; these are stored as null and treated as having no decimal places.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(currencies), "tolerance": 0},
            {"statistic": "count[2]", "expected": by_units.get(2, 0), "tolerance": 0},
            {"statistic": "count[0]", "expected": by_units.get(0, 0), "tolerance": 0},
            {"statistic": "count[3]", "expected": by_units.get(3, 0), "tolerance": 0},
            {"statistic": "count[none]", "expected": by_units.get(None, 0), "tolerance": 0},
        ],
        "notes": (
            f"The current ISO 4217 list (List One, published {published}) as the ISO 4217 Maintenance Agency distributes "
            "it in XML. The list has one row per country or territory; rows are collapsed to one record per alphabetic "
            "code, keeping the name, the three-digit numeric code and the number of minor units. The XML carries no "
            "licence statement and the maintenance agency's site terms were not confirmed, so the entry is held at "
            "license-review. valid_from is the list's own publication date; it stays valid until the next amendment "
            "replaces the list, at which point the content hash changes and the verifier reports it."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

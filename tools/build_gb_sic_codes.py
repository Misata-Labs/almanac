"""Regenerate the UK SIC 2007 condensed code list entry from the GOV.UK publication.

Run from the repository root:

    uv run python tools/build_gb_sic_codes.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

URL = "https://assets.publishing.service.gov.uk/media/5a7f8639e5274a2e87db65e1/SIC07_CH_condensed_list_en.csv"
PUBLISHER = "Companies House (GOV.UK publication)"
LICENSE = "OGL-UK-3.0"


def build(raw: bytes) -> dict:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    codes = {r["SIC Code"]: r["Description"] for r in rows}
    first = rows[0]
    return {
        "id": "gb-sic-2007-condensed-codes",
        "title": f"UK Standard Industrial Classification 2007, condensed list used by Companies House ({len(codes)} codes)",
        "kind": "rule",
        "domain": "company",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "valid_from": "2026-10-31",
        "valid_to": None,
        "tags": ["sic", "industry-codes", "code-list", "companies-house"],
        "use_cases": ["company-generation", "kyb-onboarding", "audit-demo", "customer-segmentation"],
        "spec": {
            "implementation": "almanac.rules.enumeration",
            "parameters": {"sets": {"sic_2007": codes}},
            "vectors": [
                {"input": {"set": "sic_2007", "value": first["SIC Code"]}, "expected": True, "origin": "source"},
                {"input": {"set": "sic_2007", "value": "62012"}, "expected": "62012" in codes, "origin": "source"},
                {"input": {"set": "sic_2007", "value": "99999"}, "expected": "99999" in codes, "origin": "source"},
                {"input": {"set": "sic_2007", "value": "1110"}, "expected": False, "origin": "derived", "note": "codes are five digits with leading zeros"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "SIC 2007 condensed list (CSV attachment to the GOV.UK publication)", URL, "row 1", f'{first["SIC Code"]},"{first["Description"]}"', "text", "SIC Code,Description", LICENSE, raw),
            evidence(PUBLISHER, "SIC 2007 condensed list (CSV attachment to the GOV.UK publication)", URL, "row for 62012", codes.get("62012", ""), "text", "62012,", LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count[sic_2007]", "expected": len(codes), "tolerance": 0},
        ],
        "notes": (
            "The condensed SIC 2007 list Companies House accepts when a company states its nature of business, as "
            "published on GOV.UK. Codes are five digits with leading zeros; descriptions are copied unchanged. valid_from "
            "is the access date; the list changes rarely and the content hash records the version read. GOV.UK publishes "
            "its content under the Open Government Licence v3.0."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

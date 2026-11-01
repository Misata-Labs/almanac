"""Regenerate the US VIN check-digit entry from 49 CFR 565.15 via the eCFR API, with the regulation's own
sample calculation and NHTSA's VIN decoder as test vectors. Run from the repository root:

    uv run python tools/build_us_vin.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

CFR_DATE = "2026-10-29"
CFR_URL = f"https://www.ecfr.gov/api/versioner/v1/full/{CFR_DATE}/title-49.xml?part=565"
VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
VALID_VIN = "1HGCM82633A004352"
INVALID_VIN = "1HGCM82633A004353"
SAMPLE_VIN = "1G4AH59H45G118341"
LICENSE = "unstated"


def section(raw: bytes) -> str:
    text = raw.decode("utf-8")
    match = re.search(r'<DIV8 N="565.15".*?</DIV8>', text, re.S)
    if match is None:
        raise ValueError("section 565.15 not found")
    return match.group(0)


def table(sec: str, caption: str) -> list[list[str]]:
    start = sec.index(caption)
    block = sec[start : sec.index("</TABLE>", start)]
    rows = []
    for row in re.findall(r"<TR>(.*?)</TR>", block, re.S):
        rows.append([html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in re.findall(r"<TD[^>]*>(.*?)</TD>", row, re.S)])
    return rows


def build(cfr_raw: bytes, valid_raw: bytes, invalid_raw: bytes) -> dict:
    sec = section(cfr_raw)
    values = {}
    for row in table(sec, "Table III"):
        letter, value = row[0].split("=")
        values[letter.strip()] = int(value)
    for digit in "0123456789":
        values[digit] = int(digit)
    weights = []
    for row in table(sec, "Table IV"):
        weights.append(0 if "check" in row[1] else int(row[1]))
    valid_result = json.loads(valid_raw)["Results"][0]
    invalid_result = json.loads(invalid_raw)["Results"][0]
    return {
        "id": "us-vin-check-digit",
        "title": "United States vehicle identification number (VIN) check digit, 49 CFR 565.15",
        "kind": "rule",
        "domain": "automotive",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2009-04-30",
        "valid_to": None,
        "tags": ["vin", "check-digit", "vehicle", "nhtsa", "49-cfr-565"],
        "use_cases": ["insurance", "fleet-demo", "automotive-demo", "claims-generation"],
        "spec": {
            "implementation": "almanac.rules.us_vin",
            "parameters": {
                "permitted_letters": "ABCDEFGHJKLMNPRSTUVWXYZ",
                "character_values": values,
                "weights": weights,
                "modulus": 11,
                "check_position": 9,
            },
            "vectors": [
                {"input": {"check_digit_for": SAMPLE_VIN}, "expected": "4", "origin": "source", "note": "Table VI sample calculation: products sum to 411, remainder 4"},
                {"input": SAMPLE_VIN, "expected": True, "origin": "source"},
                {"input": VALID_VIN, "expected": True, "origin": "source", "note": "NHTSA decoder: check digit is correct"},
                {"input": INVALID_VIN, "expected": False, "origin": "source", "note": "NHTSA decoder: check digit does not calculate properly"},
                {"input": "1G4AH59H45G11834", "expected": False, "origin": "derived", "note": "sixteen characters"},
                {"input": "1G4AH59H45G1183I1", "expected": False, "origin": "derived", "note": "I is not a permitted character"},
            ],
        },
        "evidence": [
            evidence("National Highway Traffic Safety Administration via the eCFR API", f"49 CFR part 565, Vehicle Identification Number (VIN) Requirements, as of {CFR_DATE} (XML)", CFR_URL, "section 565.15(c)(1), Table III", "P = 7", "text", "Assigned Values", LICENSE, cfr_raw),
            evidence("National Highway Traffic Safety Administration via the eCFR API", f"49 CFR part 565, Vehicle Identification Number (VIN) Requirements, as of {CFR_DATE} (XML)", CFR_URL, "section 565.15(c)(2), Table IV", "(check digit)", "text", "VIN Position and Weight Factor", LICENSE, cfr_raw),
            evidence("National Highway Traffic Safety Administration via the eCFR API", f"49 CFR part 565, Vehicle Identification Number (VIN) Requirements, as of {CFR_DATE} (XML)", CFR_URL, "section 565.15(c)(5), Table VI", "= 411", "text", "Add the resulting products and divide the total by 11", LICENSE, cfr_raw),
            evidence("National Highway Traffic Safety Administration via the eCFR API", f"49 CFR part 565, Vehicle Identification Number (VIN) Requirements, as of {CFR_DATE} (XML)", CFR_URL, "section 565.13(g)", "[ABCDEFGHJKLMNPRSTUVWXYZ]", "text", "Each character in each VIN shall be one of the letters in the set", LICENSE, cfr_raw),
            evidence("National Highway Traffic Safety Administration", f"vPIC VIN decoder result for {VALID_VIN} (JSON)", VPIC.format(vin=VALID_VIN), "Results[0].ErrorText", valid_result["ErrorText"], "text", "Check Digit (9th position) is correct", LICENSE, valid_raw, role="supporting"),
            evidence("National Highway Traffic Safety Administration", f"vPIC VIN decoder result for {INVALID_VIN} (JSON)", VPIC.format(vin=INVALID_VIN), "Results[0].ErrorText", invalid_result["ErrorText"], "text", "does not calculate properly", LICENSE, invalid_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "vectors[0].input",
                "value": SAMPLE_VIN,
                "method": "derived",
                "rationale": "Table VI prints the sample VIN with position nine blank and shows the products for all seventeen positions; the characters are read from the table and the resulting check digit 4 inserted, which reproduces the table's products and total of 411.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "vector_count", "expected": 6, "tolerance": 0},
        ],
        "notes": (
            "The check digit in position nine of a seventeen-character VIN, as 49 CFR 565.15(c) prescribes: each character "
            "takes its numeric value or the letter value of Table III, is multiplied by the position weight of Table IV, "
            "the products are summed and divided by 11, and the remainder is the check digit, written X for 10. Letters I, "
            "O and Q are not permitted (565.13(g)). The regulation's own Table VI calculation and two decoder results from "
            "NHTSA's vPIC service supply the vectors. valid_from is the date from which subpart B applies to all vehicles "
            "(565.11). US government works carry no copyright, but neither source states terms, so the entry is held at "
            "license-review."
        ),
    }


def main() -> int:
    write(build(fetch(CFR_URL), fetch(VPIC.format(vin=VALID_VIN)), fetch(VPIC.format(vin=INVALID_VIN))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

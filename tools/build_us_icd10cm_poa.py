"""Regenerate the ICD-10-CM FY2026 present-on-admission exempt category entry from the CDC/NCHS archive.

The archive lists every diagnosis code exempt from POA reporting. The entry keeps the three-character
categories that contain exempt codes with the number of exempt codes under each, and the archive's own
code count. Run from the repository root:

    uv run python tools/build_us_icd10cm_poa.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

URL = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026/POAexemptCodesFY26.zip"
PUBLISHER = "Centers for Disease Control and Prevention, National Center for Health Statistics"
LICENSE = "unstated"


def build(raw: bytes) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    readme = archive.read("ReadMePOAexemptFY26.txt").decode("utf-8")
    lines = archive.read("POAexemptCodesFY26.txt").decode("utf-8").splitlines()
    header, *records = [line.rstrip("\r").split("\t") for line in lines if line.strip()]
    if header != ["Order26", "POAexemptCode", "Description"]:
        raise ValueError(f"unexpected header {header}")
    stated = int(re.search(r"exempt codes, for FY2026 \(([\d,]+) codes\)", readme).group(1).replace(",", ""))
    if stated != len(records):
        raise ValueError(f"readme states {stated} codes, file has {len(records)}")
    categories: dict[str, dict] = {}
    for _, code, description in records:
        category = code[:3]
        entry = categories.setdefault(category, {"chapter_letter": code[0], "exempt_codes": 0, "first_code": code, "first_code_title": description})
        entry["exempt_codes"] += 1
    by_letter: dict[str, int] = {}
    for c in categories.values():
        by_letter[c["chapter_letter"]] = by_letter.get(c["chapter_letter"], 0) + c["exempt_codes"]
    largest = max(categories, key=lambda k: categories[k]["exempt_codes"])
    first_code, first_title = records[0][1], records[0][2]
    return {
        "id": "us-icd-10-cm-2026-poa-exempt-categories",
        "title": f"ICD-10-CM FY2026 present-on-admission (POA) exempt codes by three-character category ({len(categories)} categories over {len(records)} exempt codes)",
        "kind": "rule",
        "domain": "healthcare",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2025-10-01",
        "valid_to": "2026-09-30",
        "tags": ["icd-10-cm", "present-on-admission", "poa", "diagnosis-codes", "clinical-coding", "cdc"],
        "use_cases": ["health-demo", "claims-generation", "clinical-records", "insurance"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"exempt_code_count": len(records), "exempt_codes_by_chapter_letter": dict(sorted(by_letter.items())), "rows": categories},
            "vectors": [
                {"input": {"key": first_code[:3], "column": "first_code"}, "expected": first_code, "origin": "source"},
                {"input": {"key": largest, "column": "exempt_codes"}, "expected": categories[largest]["exempt_codes"], "origin": "source", "note": "category with the most exempt codes"},
                {"input": {"key": "Z99", "column": "chapter_letter"}, "expected": "Z", "origin": "source"},
                {"input": "V03", "expected": "V03" in categories, "origin": "source"},
                {"input": "E11", "expected": False, "origin": "derived", "note": "type 2 diabetes codes are not POA exempt"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "ICD-10-CM FY2026 POA exempt codes archive (ReadMePOAexemptFY26.txt and POAexemptCodesFY26.txt)", URL, "ReadMePOAexemptFY26.txt, first list description", f"{stated:,}", "count", "List of Present On Admission (POA) exempt codes, for FY2026", LICENSE, raw),
            evidence(PUBLISHER, "ICD-10-CM FY2026 POA exempt codes archive (ReadMePOAexemptFY26.txt and POAexemptCodesFY26.txt)", URL, "POAexemptCodesFY26.txt, first data line", first_code, "text", f"{first_code} {first_title}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "rows[*].exempt_codes", "value": "count of exempt codes beginning with the category", "method": "derived", "rationale": "Counted from POAexemptCodesFY26.txt; the file lists codes, not categories."},
            {"parameter": "exempt_codes_by_chapter_letter", "value": "count of exempt codes by first letter", "method": "derived", "rationale": "Summed from the same file as a quick view of which chapters the exemption concentrates in."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(categories), "tolerance": 0},
            {"statistic": "max[exempt_codes]", "expected": categories[largest]["exempt_codes"], "tolerance": 0},
        ],
        "notes": (
            "Diagnosis codes exempt from present-on-admission reporting on inpatient claims for the fiscal year "
            "beginning 1 October 2025, as listed by CDC/NCHS, reduced to the three-character categories that contain "
            "at least one exempt code, each with its count of exempt codes and its first exempt code and title. The "
            "exemption concentrates in injury, external cause and status codes, which a claims generator should leave "
            "without a POA indicator. The archive carries no licence statement, so the entry is held at license-review."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

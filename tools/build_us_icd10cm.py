"""Regenerate the ICD-10-CM FY2026 category entry from the CDC/NCHS code files.

The code descriptions archive holds every valid code and the tabular order
file. The entry keeps the three-character categories with their long titles,
the number of valid codes under each, and the code shape observed across the
whole list. Run from the repository root:

    uv run python tools/build_us_icd10cm.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

URL = "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026/icd10cm-Code%20Descriptions-2026.zip"
PUBLISHER = "Centers for Disease Control and Prevention, National Center for Health Statistics"
LICENSE = "unstated"
PATTERN = r"^[A-Z][0-9A-Z]{2}[0-9A-Z]{0,4}$"


def build(raw: bytes) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    codes = [line for line in archive.read("icd10cm-codes-2026.txt").decode("utf-8").splitlines() if line.strip()]
    order = [line for line in archive.read("icd10cm-order-2026.txt").decode("utf-8").splitlines() if line.strip()]
    valid = {line.split()[0]: line[8:].strip() for line in codes}
    categories: dict[str, dict] = {}
    for line in order:
        code = line[6:13].strip()
        if len(code) == 3:
            categories[code] = {"title": line[16:77].strip(), "billable_as_is": line[14] == "1", "valid_codes": 0}
    for code in valid:
        categories[code[:3]]["valid_codes"] += 1
    shape = re.compile(PATTERN)
    assert all(shape.match(c) for c in valid)
    first_code, first_title = codes[0].split(None, 1)
    return {
        "id": "us-icd-10-cm-2026-categories",
        "title": f"ICD-10-CM FY2026 three-character categories with code counts ({len(categories)} categories over {len(valid)} valid codes)",
        "kind": "rule",
        "domain": "healthcare",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2025-10-01",
        "valid_to": "2026-09-30",
        "tags": ["icd-10-cm", "diagnosis-codes", "clinical-coding", "code-list", "cdc"],
        "use_cases": ["health-demo", "insurance", "claims-generation", "clinical-records"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"code_pattern": PATTERN, "valid_code_count": len(valid), "rows": categories},
            "vectors": [
                {"input": {"key": "A00", "column": "title"}, "expected": categories["A00"]["title"], "origin": "source"},
                {"input": {"key": "U09", "column": "title"}, "expected": categories["U09"]["title"], "origin": "source"},
                {"input": {"key": "E11", "column": "valid_codes"}, "expected": categories["E11"]["valid_codes"], "origin": "source", "note": "type 2 diabetes mellitus subcodes counted from the code list"},
                {"input": "A00", "expected": True, "origin": "source"},
                {"input": "A000", "expected": False, "origin": "derived", "note": "A000 is a valid code but not a category"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "ICD-10-CM FY2026 code descriptions archive (icd10cm-codes-2026.txt and icd10cm-order-2026.txt)", URL, "icd10cm-codes-2026.txt, first line", f"{first_code} {first_title}", "text", "A000", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "code_pattern", "value": PATTERN, "method": "derived", "rationale": "Observed shape of every valid code in the FY2026 list (3 to 7 characters, a letter first, letters and digits after); the files do not state a pattern."},
            {"parameter": "rows[*].valid_codes", "value": "count of valid codes beginning with the category", "method": "derived", "rationale": "Counted from icd10cm-codes-2026.txt."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(categories), "tolerance": 0},
            {"statistic": "max[valid_codes]", "expected": max(c["valid_codes"] for c in categories.values()), "tolerance": 0},
        ],
        "notes": (
            "The three-character categories of ICD-10-CM for the fiscal year beginning 1 October 2025, read from the "
            "tabular order file in the CDC/NCHS code descriptions archive, with each category's long title, whether the "
            "category itself is a billable code, and how many valid codes sit under it. The archive is a ZIP whose text "
            "files the verifier cannot search, so the evidence snippet is checked against the decoded archive bytes only "
            "loosely; re-run the builder to re-derive everything from the archive. ICD-10 is a WHO classification and "
            "ICD-10-CM its US clinical modification; the archive carries no licence statement, so the entry is held at "
            "license-review."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

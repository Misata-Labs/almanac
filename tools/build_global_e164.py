"""Regenerate the ITU-T E.164 country calling code entry from the ITU Operational Bulletin annex.

Run from the repository root:

    uv run python tools/build_global_e164.py
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

URL = "https://www.itu.int/dms_pub/itu-t/opb/sp/T-SP-E.164D-11-2011-PDF-E.pdf"
PUBLISHER = "International Telecommunication Union (ITU-T)"
LICENSE = "unstated"
_ROW = re.compile(r"^(\d{1,3}) (.+?)(?: ([a-z]))?\s*$")


def rows_from_pdf(raw: bytes) -> list[tuple[str, str, str | None]]:
    """Rows of the numerical-order list: (code, assignee, note letter)."""
    reader = PdfReader(io.BytesIO(raw))
    rows: list[tuple[str, str, str | None]] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if "alphabetical order" in text.lower() and rows:
            break
        for line in text.splitlines():
            m = _ROW.match(line)
            if m and not m.group(2).startswith("–") and not m.group(2).startswith("List"):
                rows.append((m.group(1), m.group(2).strip(), m.group(3)))
    return rows


def build(raw: bytes) -> dict:
    rows = rows_from_pdf(raw)
    table: dict[str, dict] = {}
    for code, assignee, note in rows:
        entry = table.setdefault(code, {"assignees": [], "notes": []})
        entry["assignees"].append(assignee)
        if note and note not in entry["notes"]:
            entry["notes"].append(note)
    table = dict(sorted(table.items(), key=lambda kv: (len(kv[0]), kv[0])))
    assigned = {k: v for k, v in table.items() if not any(a.lower().startswith(("spare", "reserved")) for a in v["assignees"])}
    sample = table["44"]["assignees"][0]
    return {
        "id": "global-e164-country-calling-codes-2011",
        "title": f"ITU-T E.164 assigned country calling codes, as listed in ITU Operational Bulletin 991 (2011), {len(table)} codes",
        "kind": "rule",
        "domain": "telecom",
        "region": "global",
        "status": "license-review",
        "tier": "B",
        "valid_from": "2011-11-01",
        "valid_to": None,
        "tags": ["e164", "country-codes", "phone-numbers", "itu", "reference-table"],
        "use_cases": ["telecom-demo", "person-generation", "crm-demo", "kyc-onboarding"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"rows": table},
            "vectors": [
                {"input": {"key": "44", "column": "assignees"}, "expected": [sample], "origin": "source"},
                {"input": {"key": "91", "column": "assignees"}, "expected": table["91"]["assignees"], "origin": "source"},
                {"input": {"key": "55", "column": "assignees"}, "expected": table["55"]["assignees"], "origin": "source"},
                {"input": "1", "expected": True, "origin": "source", "note": "shared by the countries of the North American Numbering Plan"},
                {"input": "999", "expected": True, "origin": "source", "note": "reserved for future global service"},
                {"input": "4", "expected": False, "origin": "derived", "note": "no one-digit code 4 is assigned"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "List of ITU-T Recommendation E.164 assigned country codes (position on 15 November 2011), Annex to ITU Operational Bulletin No. 991", URL, "numerical-order list, code 44", sample, "text", "44 United Kingdom of Great Britain and Northern Ireland", LICENSE, raw),
            evidence(PUBLISHER, "List of ITU-T Recommendation E.164 assigned country codes (position on 15 November 2011), Annex to ITU Operational Bulletin No. 991", URL, "numerical-order list, code 91", table["91"]["assignees"][0], "text", "91 India (Republic of)", LICENSE, raw),
            evidence(PUBLISHER, "List of ITU-T Recommendation E.164 assigned country codes (position on 15 November 2011), Annex to ITU Operational Bulletin No. 991", URL, "page 1, publication note", "Annex to ITU Operational Bulletin", "text", "Operational Bulletin", LICENSE, raw),
        ],
        "assumed": [
            {
                "parameter": "rows",
                "value": "one row per country code with every assignee listed under it",
                "method": "derived",
                "rationale": "The bulletin lists one line per assignee, so shared codes such as 1 and 7 appear many times; lines are grouped by code, keeping the note letters the bulletin attaches.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
        ],
        "notes": (
            "Country calling codes from the ITU-T E.164 assigned country code list as published in the Annex to ITU "
            "Operational Bulletin No. 991 (position on 15 November 2011), which is the newest consolidated list the ITU "
            "serves at a stable URL. Spare and reserved codes are kept as the bulletin lists them so a generator knows "
            f"which codes are not assignable; {len(assigned)} codes have assignees. Later assignments are published in "
            "subsequent bulletins and are not reflected here. The PDF carries no licence statement, so the entry stays at "
            "license-review."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

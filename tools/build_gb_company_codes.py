"""Regenerate the Companies House code-list entry from its pinned source.

The company type and company status vocabularies are read from the
enumerations file Companies House publishes for its public API. Run from the
repository root:

    uv run python tools/build_gb_company_codes.py
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import TAXONOMY  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT = "05067abc50da2c9277bb5d3504187f55e5ec9e24"
URL = f"https://raw.githubusercontent.com/companieshouse/api-enumerations/{COMMIT}/constants.yml"
ACCESSED = date(2026, 10, 31)
SETS = {"company_type": "line 55", "company_status": "line 137"}


def fetch(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response.content


def build(raw: bytes) -> dict:
    constants = yaml.safe_load(raw)
    sets = {name: {str(code): str(label) for code, label in constants[name].items()} for name in SETS}
    sha = hashlib.sha256(raw).hexdigest()

    def item(locator: str, value: str, snippet: str) -> dict:
        return {
            "publisher": "Companies House",
            "title": "Companies House API enumerations (companieshouse/api-enumerations constants.yml)",
            "url": URL,
            "accessed_at": ACCESSED.isoformat(),
            "locator": locator,
            "value": value,
            "unit": "text",
            "snippet": snippet,
            "source_license": "unstated",
            "content_sha256": sha,
        }

    vectors = [
        {"input": {"set": "company_type", "value": "ltd"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_type", "value": "plc"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_type", "value": "llp"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_type", "value": "registered-overseas-entity"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_type", "value": "limited"}, "expected": False, "origin": "derived", "note": "label fragment, not a code"},
        {"input": {"set": "company_type", "value": "LTD"}, "expected": False, "origin": "derived", "note": "codes are lower case"},
        {"input": {"set": "company_status", "value": "active"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_status", "value": "dissolved"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_status", "value": "administration"}, "expected": True, "origin": "source"},
        {"input": {"set": "company_status", "value": "struck-off"}, "expected": False, "origin": "derived"},
    ]
    return {
        "id": "gb-company-type-and-status-codes",
        "title": "United Kingdom Companies House company type and company status codes",
        "kind": "rule",
        "domain": "company",
        "region": "GB",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2026-09-11",
        "valid_to": None,
        "spec": {"implementation": "almanac.rules.enumeration", "parameters": {"sets": sets}, "vectors": vectors},
        "evidence": [
            item("line 55, company_type", "'ltd' : \"Private limited company\"", "company_type:"),
            item("line 137, company_status", "'active' : \"Active\"", "company_status:"),
            item("lines 55-91, company_type (36 codes)", "'registered-overseas-entity' : \"Overseas entity\"", "'united-kingdom-societas' : \"United Kingdom Societas\""),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count[company_type]", "expected": len(sets["company_type"]), "tolerance": 0},
            {"statistic": "count[company_status]", "expected": len(sets["company_status"]), "tolerance": 0},
        ],
        "notes": (
            "The code lists are the company_type and company_status enumerations Companies House publishes "
            f"for its public API (companieshouse/api-enumerations, commit {COMMIT[:8]}); codes and labels are "
            "copied unchanged. The repository carries no licence file, so the entry stays at license-review "
            "until the publisher's terms for this file are confirmed; Companies House data is generally "
            "released under the Open Government Licence, but that is not stated here. valid_from is the "
            "date of the pinned revision; valid_to is open."
        ),
    }


def main() -> int:
    entry = build(fetch(URL))
    path = REPO_ROOT / "entries" / "company" / "GB" / f"{entry['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if entry["id"] in TAXONOMY:
        tags, use_cases = TAXONOMY[entry["id"]]
        entry = {**entry, "tags": tags, "use_cases": use_cases}
    path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

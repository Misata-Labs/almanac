"""Regenerate the GOV.UK calendar entries from their pinned machine-readable sources.

The bank holiday entry is built from the JSON endpoint behind
www.gov.uk/bank-holidays; the clock-change entry from the JSON data and
English labels published in alphagov/frontend. Run from the repository root:

    uv run python tools/build_gb_calendars.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT = "b078a86e3d8262f58192a5484b66970de9a9dac7"
BASE = f"https://raw.githubusercontent.com/alphagov/frontend/{COMMIT}/"
HOLIDAYS_URL = "https://www.gov.uk/bank-holidays.json"
CLOCKS_URL = BASE + "lib/data/when-do-the-clocks-change.json"
LOCALE_URL = BASE + "config/locales/en.yml"
ACCESSED = date(2026, 10, 31)
PUBLISHER = "Government Digital Service (GOV.UK)"
LICENSE = "MIT"
DIVISIONS = {
    "common.nations.england-and-wales_slug": "england-and-wales",
    "common.nations.scotland_slug": "scotland",
    "common.nations.northern-ireland_slug": "northern-ireland",
}
SUBSTITUTE_NOTE = "common.substitute_day"


def fetch(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response.content


def iso(dmy: str) -> str:
    return datetime.strptime(dmy, "%d/%m/%Y").date().isoformat()


def evidence(url: str, title: str, locator: str, value: str, unit: str, snippet: str, content: bytes, role: str = "primary") -> dict:
    return {
        "publisher": PUBLISHER,
        "title": title,
        "url": url,
        "accessed_at": ACCESSED.isoformat(),
        "locator": locator,
        "value": value,
        "unit": unit,
        "snippet": snippet,
        "source_license": LICENSE,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "role": role,
    }


def build_bank_holidays(holidays_raw: bytes) -> dict:
    data = json.loads(holidays_raw)
    divisions: dict[str, dict[str, list[dict]]] = {}
    for name in ("england-and-wales", "scotland", "northern-ireland"):
        by_year: dict[str, list[dict]] = {}
        for event in data[name]["events"]:
            by_year.setdefault(event["date"][:4], []).append(
                {
                    "date": event["date"],
                    "title": event["title"],
                    "substitute_day": event["notes"] == "Substitute day",
                    "bunting": bool(event["bunting"]),
                }
            )
        divisions[name] = dict(sorted(by_year.items()))
    years = sorted(next(iter(divisions.values())).keys())
    first_year, last_year = years[0], years[-1]

    def find(division: str, year: str, title: str) -> dict:
        return next(e for e in divisions[division][year] if e["title"] == title)

    ew_boxing_2026 = find("england-and-wales", "2026", "Boxing Day")
    vectors = [
        {"input": {"date": ew_boxing_2026["date"], "division": "england-and-wales"}, "expected": True, "origin": "source", "note": "substitute day for Boxing Day"},
        {"input": {"date": "2026-12-26", "division": "england-and-wales"}, "expected": False, "origin": "derived", "note": "Boxing Day falls on a Saturday and is not itself listed"},
        {"input": {"date": find("england-and-wales", "2026", "Good Friday")["date"], "division": "england-and-wales"}, "expected": True, "origin": "source"},
        {"input": {"date": find("scotland", "2026", "2nd January")["date"], "division": "scotland"}, "expected": True, "origin": "source"},
        {"input": {"date": "2026-01-02", "division": "england-and-wales"}, "expected": False, "origin": "derived"},
        {"input": {"date": find("scotland", "2026", "St Andrew’s Day")["date"], "division": "scotland"}, "expected": True, "origin": "source"},
        {"input": {"date": find("northern-ireland", "2026", "St Patrick’s Day")["date"], "division": "northern-ireland"}, "expected": True, "origin": "source"},
        {"input": {"date": "2026-03-17", "division": "scotland"}, "expected": False, "origin": "derived"},
        {"input": {"date": find("northern-ireland", "2026", "Battle of the Boyne (Orangemen’s Day)")["date"], "division": "northern-ireland"}, "expected": True, "origin": "source", "note": "substitute day for the Battle of the Boyne"},
        {"input": {"date": "2026-07-12", "division": "northern-ireland"}, "expected": False, "origin": "derived", "note": "12 July 2026 is a Sunday"},
        {"input": {"date": find("scotland", "2025", "St Andrew’s Day")["date"], "division": "scotland"}, "expected": True, "origin": "source", "note": "substitute day for St Andrew's Day 2025"},
        {"input": {"date": "2025-11-30", "division": "scotland"}, "expected": False, "origin": "derived", "note": "30 November 2025 is a Sunday"},
    ]
    tests = [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}]
    for name in divisions:
        for year in years:
            if int(year) >= 2025:
                tests.append({"statistic": f"count[{name},{year}]", "expected": len(divisions[name][year]), "tolerance": 0})

    return {
        "id": "gb-bank-holidays",
        "title": f"United Kingdom bank holidays by nation, {first_year} to {last_year}",
        "kind": "rule",
        "domain": "calendar",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{first_year}-01-01",
        "valid_to": f"{last_year}-12-31",
        "spec": {
            "implementation": "almanac.rules.gb_bank_holidays",
            "parameters": {"divisions": divisions},
            "vectors": vectors,
        },
        "evidence": [
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays JSON (www.gov.uk/bank-holidays.json)", 'england-and-wales.events[title="Boxing Day", 2026].date', ew_boxing_2026["date"], "date", '"notes":"Substitute day"', holidays_raw),
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays JSON (www.gov.uk/bank-holidays.json)", 'scotland.events[title="St Andrew’s Day", 2026].date', find("scotland", "2026", "St Andrew’s Day")["date"], "date", '"title":"St Andrew’s Day"', holidays_raw),
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays JSON (www.gov.uk/bank-holidays.json)", "northern-ireland.division", "northern-ireland", "text", '"division":"northern-ireland"', holidays_raw),
        ],
        "assumed": [],
        "tests": tests,
        "notes": (
            "Dates are the bank holidays GOV.UK publishes for England and Wales, Scotland and Northern Ireland from "
            f"{first_year} to {last_year}, read from the JSON endpoint behind www.gov.uk/bank-holidays. Titles are the "
            "English titles the endpoint carries; substitute_day is true where the source notes a substitute day and "
            "bunting is copied unchanged. Bank holidays are set by the Banking and Financial Dealings Act 1971 and by royal "
            "proclamation; future years can change by proclamation, so re-run the verifier before relying on them. The "
            "endpoint is maintained by the Government Digital Service. GOV.UK publishes its content under the Open "
            "Government Licence v3.0, stated in the footer of every GOV.UK page; those pages render dynamically and are "
            "not hashed here. The Scotland list for 2026 includes a World Cup bank holiday exactly as published."
        ),
    }


def build_clock_change(clocks_raw: bytes, locale_raw: bytes) -> dict:
    data = json.loads(clocks_raw)
    locale = yaml.safe_load(locale_raw)["en"]
    division = next(iter(data["divisions"].values()))
    years = sorted(k for k in division if k.isdigit())
    published: dict[str, dict[str, str]] = {}
    for year in years:
        events = division[year]
        published[year] = {
            "forward": iso(next(e["date"] for e in events if e["title"].endswith("start_title"))),
            "back": iso(next(e["date"] for e in events if e["title"].endswith("end_title"))),
        }
    vectors = [{"input": {"year": int(year)}, "expected": dict(published[year]), "origin": "source"} for year in years]
    return {
        "id": "gb-clock-change",
        "title": f"United Kingdom clock changes (British Summer Time), {years[0]} to {years[-1]}",
        "kind": "rule",
        "domain": "calendar",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{years[0]}-01-01",
        "valid_to": f"{years[-1]}-12-31",
        "spec": {
            "implementation": "almanac.rules.gb_clock_change",
            "parameters": {
                "transitions": {
                    "forward": {"month": 3, "weekday": "sunday", "ordinal": "last", "local_time": "01:00"},
                    "back": {"month": 10, "weekday": "sunday", "ordinal": "last", "local_time": "02:00"},
                },
                "published": published,
            },
            "vectors": vectors,
        },
        "evidence": [
            evidence(CLOCKS_URL, "GOV.UK clock change data (alphagov/frontend lib/data/when-do-the-clocks-change.json)", 'divisions["common.united-kingdom_slug"]["2026"][0].date', "29/03/2026", "date", '"title": "when_do_the_clocks_change.start_title"', clocks_raw),
            evidence(CLOCKS_URL, "GOV.UK clock change data (alphagov/frontend lib/data/when-do-the-clocks-change.json)", 'divisions["common.united-kingdom_slug"]["2027"][1].date', "31/10/2027", "date", '"title": "when_do_the_clocks_change.end_title"', clocks_raw),
            evidence(LOCALE_URL, "GOV.UK frontend English locale (config/locales/en.yml)", "en.bank_holidays.clock_change_explanation", locale["bank_holidays"]["clock_change_explanation"], "text", "last Sunday in March, and back 1 hour at 2am", locale_raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "vector_count", "expected": len(vectors), "tolerance": 0},
        ],
        "notes": (
            "The rule computes the last Sunday of March (clocks forward, 01:00 local) and the last Sunday of "
            "October (clocks back, 02:00 local) as GOV.UK states, and every published date for "
            f"{years[0]} to {years[-1]} in the JSON behind www.gov.uk/when-do-the-clocks-change reproduces "
            f"from it (alphagov/frontend commit {COMMIT[:8]}, data last updated {data['last_updated']}). "
            "The published dates are kept under parameters.published for direct lookup. Transition times are "
            "taken from the same GOV.UK sentence; the underlying statute is the Summer Time Act 1972."
        ),
    }


def write(entry: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=110)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def main() -> int:
    holidays_raw, clocks_raw, locale_raw = fetch(HOLIDAYS_URL), fetch(CLOCKS_URL), fetch(LOCALE_URL)
    target = REPO_ROOT / "entries" / "calendar" / "GB"
    write(build_bank_holidays(holidays_raw), target / "gb-bank-holidays.yaml")
    write(build_clock_change(clocks_raw, locale_raw), target / "gb-clock-change.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())

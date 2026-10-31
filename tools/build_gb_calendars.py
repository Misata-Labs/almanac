"""Regenerate the GOV.UK calendar entries from their pinned machine-readable sources.

Both entries are built deterministically from the bank-holiday and
clock-change JSON files published in alphagov/frontend, plus the English
labels in its locale file. Run from the repository root:

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
HOLIDAYS_URL = BASE + "lib/data/bank-holidays.json"
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


def evidence(url: str, title: str, locator: str, value: str, unit: str, snippet: str, content: bytes) -> dict:
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
    }


def build_bank_holidays(holidays_raw: bytes, locale_raw: bytes) -> dict:
    data = json.loads(holidays_raw)
    labels = yaml.safe_load(locale_raw)["en"]["bank_holidays"]
    divisions: dict[str, dict[str, list[dict]]] = {}
    for slug, name in DIVISIONS.items():
        years = {k: v for k, v in data["divisions"][slug].items() if k.isdigit()}
        divisions[name] = {
            year: [
                {
                    "date": iso(event["date"]),
                    "title": labels[event["title"].removeprefix("bank_holidays.")],
                    "title_key": event["title"],
                    "substitute_day": event["notes"] == SUBSTITUTE_NOTE,
                    "bunting": bool(event["bunting"]),
                }
                for event in events
            ]
            for year, events in sorted(years.items())
        }
    years = sorted(next(iter(divisions.values())).keys())
    first_year, last_year = years[0], years[-1]

    ew_2026 = divisions["england-and-wales"]["2026"]
    sc_2026 = divisions["scotland"]["2026"]
    ni_2026 = divisions["northern-ireland"]["2026"]
    vectors = [
        {"input": {"date": ew_2026[-1]["date"], "division": "england-and-wales"}, "expected": True, "origin": "source", "note": "substitute day for Boxing Day"},
        {"input": {"date": "2026-12-26", "division": "england-and-wales"}, "expected": False, "origin": "derived", "note": "Boxing Day falls on a Saturday and is not itself listed"},
        {"input": {"date": ew_2026[1]["date"], "division": "england-and-wales"}, "expected": True, "origin": "source", "note": "Good Friday"},
        {"input": {"date": sc_2026[1]["date"], "division": "scotland"}, "expected": True, "origin": "source", "note": "2nd January"},
        {"input": {"date": "2026-01-02", "division": "england-and-wales"}, "expected": False, "origin": "derived"},
        {"input": {"date": sc_2026[-3]["date"], "division": "scotland"}, "expected": True, "origin": "source", "note": "St Andrew's Day"},
        {"input": {"date": ni_2026[1]["date"], "division": "northern-ireland"}, "expected": True, "origin": "source", "note": "St Patrick's Day"},
        {"input": {"date": "2026-03-17", "division": "scotland"}, "expected": False, "origin": "derived"},
        {"input": {"date": ni_2026[6]["date"], "division": "northern-ireland"}, "expected": True, "origin": "source", "note": "substitute day for the Battle of the Boyne"},
        {"input": {"date": "2026-07-12", "division": "northern-ireland"}, "expected": False, "origin": "derived", "note": "12 July 2026 is a Sunday"},
        {"input": {"date": divisions["scotland"]["2025"][6]["date"], "division": "scotland"}, "expected": True, "origin": "source", "note": "substitute day for St Andrew's Day 2025"},
        {"input": {"date": "2025-11-30", "division": "scotland"}, "expected": False, "origin": "derived", "note": "30 November 2025 is a Sunday"},
    ]
    tests = [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}]
    for name in DIVISIONS.values():
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
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays data (alphagov/frontend lib/data/bank-holidays.json)", "top-level last_updated", data["last_updated"], "text", '"description": "bank_holidays.calendar.description"', holidays_raw),
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays data (alphagov/frontend lib/data/bank-holidays.json)", 'divisions["common.nations.england-and-wales_slug"]["2026"][7].date', "28/12/2026", "date", '"title": "bank_holidays.boxing_day"', holidays_raw),
            evidence(HOLIDAYS_URL, "GOV.UK bank holidays data (alphagov/frontend lib/data/bank-holidays.json)", 'divisions["common.nations.scotland_slug"]["2026"][5].date', "15/06/2026", "date", '"title": "bank_holidays.world_cup"', holidays_raw),
            evidence(LOCALE_URL, "GOV.UK frontend English locale (config/locales/en.yml)", "en.bank_holidays.late_august", "Summer bank holiday", "text", "late_august: Summer bank holiday", locale_raw),
            evidence(LOCALE_URL, "GOV.UK frontend English locale (config/locales/en.yml)", "en.common.bank_holiday_on_wkend", "a ‘substitute’ weekday becomes a bank holiday, normally the following Monday", "text", "If a bank holiday is on a weekend", locale_raw),
        ],
        "assumed": [
            {
                "parameter": "divisions.*.*.title",
                "value": "English label from config/locales/en.yml",
                "method": "derived",
                "rationale": "The data file carries locale keys such as bank_holidays.new_year; the English text is joined from the same repository's locale file and the key is kept alongside it.",
            }
        ],
        "tests": tests,
        "notes": (
            "Dates are the bank holidays GOV.UK publishes for England and Wales, Scotland and Northern "
            f"Ireland from {first_year} to {last_year}, read from the JSON data behind www.gov.uk/bank-holidays "
            f"in alphagov/frontend (commit {COMMIT[:8]}, data last updated {data['last_updated']}). Dates are "
            "converted from DD/MM/YYYY to ISO 8601; substitute_day is true where the source notes a substitute "
            "day and bunting is copied unchanged. Bank holidays are set by the Banking and Financial Dealings "
            "Act 1971 and by royal proclamation; the source is maintained by the Government Digital Service "
            "under the MIT licence and GOV.UK content is also available under the Open Government Licence v3. "
            "Future years can change by proclamation, so re-run the verifier before relying on them. The "
            "Scotland list for 2026 includes a World Cup bank holiday on 15 June 2026 exactly as published; "
            "it is flagged for human review. Division names are derived from the source slugs."
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
    write(build_bank_holidays(holidays_raw, locale_raw), target / "gb-bank-holidays.yaml")
    write(build_clock_change(clocks_raw, locale_raw), target / "gb-clock-change.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())

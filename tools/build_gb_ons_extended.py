"""Regenerate the extended UK series entries from static ONS dataset downloads.

Three entries: the daily card spending indicator for 2023 with its four
spending categories, CPIH by COICOP division for 2025, and economic activity
status given age group from the Labour Force Survey. Each reads the full
time-series CSV that ONS serves for one dataset version, a byte-stable file
pinned by version number. Run from the repository root:

    uv run python tools/build_gb_ons_extended.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://api.beta.ons.gov.uk/v1/datasets"
DOWNLOADS = "https://download.ons.gov.uk/downloads/datasets"
PUBLISHER = "Office for National Statistics"
LICENSE = "OGL-UK-3.0"
LICENSE_URL = f"{API}/cpih01"
CARDS_URL = f"{DOWNLOADS}/uk-spending-on-cards/editions/time-series/versions/130.csv"
CARDS_META_URL = f"{API}/uk-spending-on-cards"
CARDS_VERSION_URL = f"{API}/uk-spending-on-cards/editions/time-series/versions/130"
CPIH_URL = f"{DOWNLOADS}/cpih01/editions/time-series/versions/67.csv"
LFS_URL = f"{DOWNLOADS}/labour-market/editions/PWT24/versions/1.csv"
LFS_META_URL = f"{API}/labour-market"
CARD_CATEGORIES = {"Delayable": "delayable", "Social": "social", "Staple": "staple", "Work Related": "work_related"}
DIVISIONS = [f"CP{i:02d}" for i in range(1, 13)]
DIVISION_COLUMNS = {code: code.lower() for code in DIVISIONS}
AGE_GROUPS = ["16-17", "18-24", "25-34", "35-49", "50-64", "65+", "16-64", "16+"]
ACTIVITY = {"In Employment": "in_employment", "Unemployed": "unemployed", "Economically Inactive": "economically_inactive"}
LFS_PERIOD = "Feb-Apr 2025"


def csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def csv_line(row: dict) -> str:
    """The row as it appears in the file, for snippets that must match the raw bytes."""
    return ",".join(row.values())


def card_spending(raw: bytes, meta_raw: bytes, version_raw: bytes, license_raw: bytes) -> dict:
    year = 2023
    rows = [r for r in csv_rows(raw) if r["Time"] == str(year) and r["v4_1"]]
    by_day: dict[str, dict[str, float]] = {}
    for row in rows:
        day = datetime.strptime(f"{row['DayMonth']}-{year}", "%d-%m-%Y").date().isoformat()
        by_day.setdefault(day, {})[row["Category"]] = float(row["v4_1"])
    points = [
        {"period": day, "value": values["Aggregate"], **{column: values[label] for label, column in CARD_CATEGORIES.items()}}
        for day, values in sorted(by_day.items())
        if set(values) == {"Aggregate", *CARD_CATEGORIES}
    ]
    first, last = points[0], points[-1]
    peak = max(points, key=lambda p: p["value"])
    first_row = next(r for r in rows if r["Category"] == "Aggregate" and datetime.strptime(f"{r['DayMonth']}-{year}", "%d-%m-%Y").date().isoformat() == first["period"])
    meta = json.loads(meta_raw)
    version = json.loads(version_raw)
    return {
        "id": f"gb-card-spending-index-daily-{year}",
        "title": f"UK spending on credit and debit cards, daily index by spending category (aggregate, staple, delayable, social, work-related), {year}",
        "kind": "temporal",
        "domain": "economy",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": ["card-payments", "consumer-spending", "faster-indicators", "daily", "seasonality"],
        "use_cases": ["payments-demo", "retail-demo", "demand-forecasting", "fintech-demo", "capacity-planning"],
        "spec": {"variable": "card_spending_index", "unit": "decimal", "frequency": "daily", "columns": list(CARD_CATEGORIES.values()), "series": points},
        "evidence": [
            evidence(PUBLISHER, "ONS dataset uk-spending-on-cards version 130, full time-series CSV (v4 format)", CARDS_URL, f"row calendar-years={year}, DayMonth={first_row['DayMonth']}, Category=Aggregate, column v4_1", first_row["v4_1"], "decimal", csv_line(first_row), LICENSE, raw),
            evidence(PUBLISHER, f"ONS dataset metadata uk-spending-on-cards ({meta['title']})", CARDS_META_URL, "description", meta["description"], "text", '"id":"uk-spending-on-cards"', LICENSE, meta_raw),
            evidence(PUBLISHER, "ONS dataset uk-spending-on-cards, version 130 metadata (release date and category definitions)", CARDS_VERSION_URL, "release_date", version["release_date"], "text", '"version":130', LICENSE, version_raw),
            evidence(PUBLISHER, "ONS dataset metadata cpih01 (licence statement for ONS datasets)", LICENSE_URL, "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "series[*].period",
                "value": "ISO dates built from the DayMonth column and the calendar year",
                "method": "derived",
                "rationale": f"The file keys each observation by a dd-mm day label and a calendar year; the two are combined into a date. Days carrying a data marking instead of a value, and days missing any of the five categories, are left out, leaving {len(points)} days.",
            }
        ],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": f"column[social,{first['period']}]", "expected": first["social"], "tolerance": 1e-9},
            {"statistic": "max", "expected": peak["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(points), "tolerance": 0},
        ],
        "notes": (
            f"Daily index of UK spending on credit and debit cards for {year}, an ONS experimental faster indicator built "
            "from the CHAPS payments that card processors make to around 100 major UK retail corporates, as the full "
            "time-series CSV of version 130 of the uk-spending-on-cards dataset publishes it. The aggregate is the series "
            "value; the four category columns follow ONS's classification of retailers (staple, delayable, social and "
            "work-related). The index base is not stated in the dataset metadata. Other years are dropped. The metadata "
            "carries no licence field; ONS publishes its datasets under the Open Government Licence v3.0, as the cpih01 "
            "metadata states."
        ),
    }


def cpih_divisions(raw: bytes, meta_raw: bytes) -> dict:
    year = 2025
    rows = [r for r in csv_rows(raw) if r["Time"].endswith(f"-{str(year)[2:]}") and r["cpih1dim1aggid"] in {"CP00", *DIVISIONS}]
    by_month: dict[str, dict[str, float]] = {}
    labels: dict[str, str] = {}
    for row in rows:
        month = datetime.strptime(row["Time"], "%b-%y").strftime("%Y-%m")
        by_month.setdefault(month, {})[row["cpih1dim1aggid"]] = float(row["v4_0"])
        labels[row["cpih1dim1aggid"]] = row["Aggregate"]
    points = [{"period": month, "value": values["CP00"], **{column: values[code] for code, column in DIVISION_COLUMNS.items()}} for month, values in sorted(by_month.items())]
    first, last = points[0], points[-1]
    first_row = next(r for r in rows if r["cpih1dim1aggid"] == "CP01" and datetime.strptime(r["Time"], "%b-%y").strftime("%Y-%m") == first["period"])
    meta = json.loads(meta_raw)
    division_list = "; ".join(f"{column} = {labels[code]}" for code, column in DIVISION_COLUMNS.items())
    return {
        "id": f"gb-cpih-divisions-index-monthly-{year}",
        "title": f"UK CPIH index by COICOP division (01 food to 12 miscellaneous) beside the all-items index, monthly {year}",
        "kind": "temporal",
        "domain": "economy",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": ["inflation", "prices", "cpih", "coicop", "index"],
        "use_cases": ["pricing", "retail-demo", "contract-indexation", "financial-planning", "demand-forecasting"],
        "spec": {"variable": "cpih_index_2015_100", "unit": "decimal", "frequency": "monthly", "columns": list(DIVISION_COLUMNS.values()), "series": points},
        "evidence": [
            evidence(PUBLISHER, "ONS dataset cpih01 version 67, full time-series CSV (v4 format)", CPIH_URL, f"row Time={first_row['Time']}, uk-only=K02000001, cpih1dim1aggid=CP01, column v4_0", first_row["v4_0"], "decimal", csv_line(first_row), LICENSE, raw),
            evidence(PUBLISHER, "ONS dataset metadata cpih01 (title and licence)", LICENSE_URL, "license", meta["license"], "text", '"license":"Open Government Licence v3.0"', LICENSE, meta_raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"column[cp01,{last['period']}]", "expected": last["cp01"], "tolerance": 1e-9},
            {"statistic": f"column[cp04,{first['period']}]", "expected": first["cp04"], "tolerance": 1e-9},
            {"statistic": f"column[cp12,{last['period']}]", "expected": last["cp12"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(points), "tolerance": 0},
        ],
        "notes": (
            f"CPIH index (2015 = 100) for the United Kingdom, monthly for {year}, for the twelve COICOP divisions as columns "
            "beside the all-items index as the series value, from the full time-series CSV of version 67 of the ONS cpih01 "
            f"dataset; other aggregates and years are dropped. The columns are the division codes in lower case: {division_list}. The all-items series alone is "
            "the entry gb-cpih-all-items-index-monthly-2025. ONS publishes the dataset under the Open Government Licence "
            "v3.0, as its metadata states."
        ),
    }


def economic_activity_by_age(raw: bytes, meta_raw: bytes, license_raw: bytes) -> dict:
    rows = [r for r in csv_rows(raw) if r["Time"] == LFS_PERIOD and r["UnitOfMeasure"] == "Levels" and r["Sex"] == "All adults" and r["SeasonalAdjustment"] == "Seasonally Adjusted"]
    levels = {(r["AgeGroups"], r["EconomicActivity"]): int(r["v4_0"]) for r in rows}
    distributions = {}
    for age in AGE_GROUPS:
        counts = {key: levels[(age, label)] for label, key in ACTIVITY.items()}
        total = sum(counts.values())
        distributions[age] = {"family": "categorical", "parameters": {"shares": {k: round(v / total, 6) for k, v in counts.items()}, "persons": counts, "total": total}}
    sample = next(r for r in rows if r["AgeGroups"] == "25-34" and r["EconomicActivity"] == "In Employment")
    meta = json.loads(meta_raw)
    start, end = "2025-02-01", "2025-04-30"
    return {
        "id": "gb-economic-activity-by-age-group-2025",
        "title": "UK economic activity status (in employment, unemployed, economically inactive) given age group, Labour Force Survey February to April 2025",
        "kind": "conditional",
        "domain": "employment",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": start, "end": end},
        "tags": ["labour-market", "employment", "unemployment", "by-age", "labour-force-survey"],
        "use_cases": ["person-generation", "hr-analytics", "workforce-planning", "credit-risk", "customer-segmentation"],
        "spec": {"variable": "economic_activity_status", "unit": "ratio", "given": "age_group", "distributions": distributions},
        "evidence": [
            evidence(PUBLISHER, "ONS dataset labour-market edition PWT24 version 1, full CSV (v4 format)", LFS_URL, f"row Time={LFS_PERIOD}, Levels, In Employment, 25-34, All adults, Seasonally Adjusted, column v4_0", sample["v4_0"], "count", csv_line(sample), LICENSE, raw),
            evidence(PUBLISHER, f"ONS dataset metadata labour-market ({meta['title']})", LFS_META_URL, "description", "It uses internationally recognised definitions of employment, unemployment and economic activity.", "text", '"id":"labour-market"', LICENSE, meta_raw),
            evidence(PUBLISHER, "ONS dataset metadata cpih01 (licence statement for ONS datasets)", LICENSE_URL, "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distributions[*].parameters.shares",
                "value": "persons in each status divided by the three statuses' total",
                "method": "derived",
                "rationale": "The file publishes seasonally adjusted population levels per status; in employment plus unemployed equals the economically active level, and the three statuses partition the age group's population. Shares are the levels divided by their sum.",
            }
        ],
        "tests": [
            {"statistic": "share[25-34,in_employment]", "expected": distributions["25-34"]["parameters"]["shares"]["in_employment"], "tolerance": 0.003},
            {"statistic": "share[65+,economically_inactive]", "expected": distributions["65+"]["parameters"]["shares"]["economically_inactive"], "tolerance": 0.003},
            {"statistic": "share[16-17,unemployed]", "expected": distributions["16-17"]["parameters"]["shares"]["unemployed"], "tolerance": 0.003},
            {"statistic": "sum_of_shares[35-49]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[16+]", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            "Economic activity status of the UK household population given age group, from the Labour Force Survey "
            "levels for the rolling quarter February to April 2025 (all adults, seasonally adjusted) in edition PWT24 of "
            "the ONS labour-market dataset. The six age groups partition people aged 16 and over; 16-64 and 16+ are the "
            "working-age and whole-population totals. Person counts sit beside the shares. The LFS is a sample survey "
            "weighted to population totals. The labour-market metadata carries no licence field; ONS publishes its "
            "datasets under the Open Government Licence v3.0, as the cpih01 metadata states."
        ),
    }


def main() -> int:
    license_raw = fetch(LICENSE_URL)
    write(card_spending(fetch(CARDS_URL), fetch(CARDS_META_URL), fetch(CARDS_VERSION_URL), license_raw))
    write(cpih_divisions(fetch(CPIH_URL), license_raw))
    write(economic_activity_by_age(fetch(LFS_URL), fetch(LFS_META_URL), license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())

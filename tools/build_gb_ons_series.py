"""Regenerate the UK monthly series entries from the ONS API: the CPIH all-items index and the
retail sales index (chained volume, all retailing excluding automotive fuel), both for 2025.
Run from the repository root:

    uv run python tools/build_gb_ons_series.py
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
YEAR = 2025
CPIH_VERSION = f"{API}/cpih01/editions/time-series/versions/67"
CPIH_URL = "https://download.ons.gov.uk/downloads/datasets/cpih01/editions/time-series/versions/67.csv"
LICENSE_URL = f"{API}/cpih01"
RSI_VERSION = f"{API}/retail-sales-index/editions/time-series/versions/45"
RSI_URL = "https://download.ons.gov.uk/downloads/datasets/retail-sales-index/editions/time-series/versions/45.csv"
RSI_META_URL = f"{API}/retail-sales-index"
PUBLISHER = "Office for National Statistics"
LICENSE = "OGL-UK-3.0"


def period(label: str) -> str:
    return datetime.strptime(label, "%b-%y").strftime("%Y-%m")


def csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def build(raw: bytes, meta_raw: bytes) -> dict:
    rows = [r for r in csv_rows(raw) if r["uk-only"] == "K02000001" and r["cpih1dim1aggid"] == "CP00" and r["Time"].endswith(f"-{str(YEAR)[2:]}")]
    points = sorted(({"period": period(r["Time"]), "value": float(r["v4_0"])} for r in rows), key=lambda p: p["period"])
    meta = json.loads(meta_raw)
    first, last = points[0], points[-1]
    first_label = datetime.strptime(first["period"], "%Y-%m").strftime("%b-%y")
    return {
        "id": f"gb-cpih-all-items-index-monthly-{YEAR}",
        "title": f"UK Consumer Prices Index including owner occupiers' housing costs (CPIH), all items index, monthly {YEAR}",
        "kind": "temporal",
        "domain": "economy",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": ["inflation", "prices", "cpih", "index"],
        "use_cases": ["pricing", "financial-planning", "contract-indexation"],
        "spec": {"variable": "cpih_index_2015_100", "unit": "decimal", "frequency": "monthly", "columns": [], "series": points},
        "evidence": [
            evidence(PUBLISHER, "ONS dataset cpih01 version 67, full time-series CSV (v4 format)", CPIH_URL, f"row Time={first_label}, uk-only=K02000001, cpih1dim1aggid=CP00, column v4_0", f"{first_label},{first_label},K02000001,United Kingdom,CP00,Overall Index", "text", f"{first_label},K02000001,United Kingdom,CP00", LICENSE, raw),
            evidence(PUBLISHER, "ONS dataset metadata cpih01 (title and licence)", LICENSE_URL, "license", meta["license"], "text", '"license":"Open Government Licence v3.0"', LICENSE, meta_raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(points), "tolerance": 0},
        ],
        "notes": (
            f"CPIH all-items index (2015 = 100) for the United Kingdom, monthly for {YEAR}, from version 67 of the ONS "
            "cpih01 dataset as the full time-series CSV the ONS serves for that version (the API's observation endpoint "
            f"embeds internal hostnames and is not byte-stable); months outside {YEAR} are dropped. The index is the headline measure of UK consumer price inflation. ONS publishes the "
            "dataset under the Open Government Licence v3.0, as its metadata states."
        ),
    }


def build_retail(raw: bytes, meta_raw: bytes, license_raw: bytes) -> dict:
    rows = [
        r for r in csv_rows(raw)
        if r["countries"] == "K03000001" and r["sic-unofficial"] == "all-retailing-excluding-automotive-fuel"
        and r["type-of-prices"] == "chained-volume-of-retail-sales" and r["seasonal-adjustment"] == "seasonal-adjustment"
        and r["Time"].endswith(f"-{str(YEAR)[2:]}")
    ]
    points = sorted(({"period": period(r["Time"]), "value": float(r["v4_1"])} for r in rows), key=lambda p: p["period"])
    meta = json.loads(meta_raw)
    first, last = points[0], points[-1]
    peak = max(points, key=lambda p: p["value"])
    first_label = datetime.strptime(first["period"], "%Y-%m").strftime("%b-%y")
    return {
        "id": f"gb-retail-sales-index-volume-monthly-{YEAR}",
        "title": f"Great Britain retail sales index, chained volume, all retailing excluding automotive fuel, seasonally adjusted, monthly {YEAR}",
        "kind": "temporal",
        "domain": "economy",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": ["retail", "sales-index", "seasonality", "consumer"],
        "use_cases": ["retail-demo", "demand-forecasting", "sales-generation"],
        "spec": {"variable": "retail_sales_volume_index", "unit": "decimal", "frequency": "monthly", "columns": [], "series": points},
        "evidence": [
            evidence(PUBLISHER, "ONS dataset retail-sales-index version 45, full time-series CSV (v4 format)", RSI_URL, f"row Time={first_label}, Great Britain, all retailing excluding automotive fuel, chained volume, seasonally adjusted, column v4_1", f"{first_label},K03000001,Great Britain,all-retailing-excluding-automotive-fuel,All retailing excluding automotive fuel,chained-volume-of-retail-sales", "text", "all-retailing-excluding-automotive-fuel,All retailing excluding automotive fuel,chained-volume-of-retail-sales,Chained volume of retail sales,seasonal-adjustment", LICENSE, raw),
            evidence(PUBLISHER, "ONS dataset metadata retail-sales-index", RSI_META_URL, "title", meta["title"], "text", '"id":"retail-sales-index"', LICENSE, meta_raw),
            evidence(PUBLISHER, "ONS dataset metadata cpih01 (licence statement for ONS datasets)", LICENSE_URL, "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": "max", "expected": peak["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(points), "tolerance": 0},
        ],
        "notes": (
            f"Retail sales index for Great Britain, chained volume measure, all retailing excluding automotive fuel, "
            f"seasonally adjusted, monthly for {YEAR}, from the full time-series CSV of version 45 of the ONS "
            "retail-sales-index dataset (other series and years dropped; the API's observation endpoint is not byte-stable). The retail-sales-index metadata "
            "carries no licence field; ONS publishes its datasets under the Open Government Licence v3.0, as the cpih01 "
            "metadata states."
        ),
    }


def main() -> int:
    license_raw = fetch(LICENSE_URL)
    write(build(fetch(CPIH_URL), license_raw))
    write(build_retail(fetch(RSI_URL), fetch(RSI_META_URL), license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Regenerate the UK monthly series entries from the ONS API: the CPIH all-items index and the
retail sales index (chained volume, all retailing excluding automotive fuel), both for 2025.
Run from the repository root:

    uv run python tools/build_gb_ons_series.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://api.beta.ons.gov.uk/v1/datasets"
YEAR = 2025
CPIH_VERSION = f"{API}/cpih01/editions/time-series/versions/67"
CPIH_URL = f"{CPIH_VERSION}/observations?time=*&geography=K02000001&aggregate=CP00"
LICENSE_URL = f"{API}/cpih01"
RSI_VERSION = f"{API}/retail-sales-index/editions/time-series/versions/45"
RSI_URL = (
    f"{RSI_VERSION}/observations?time=*&geography=K03000001&prices=chained-volume-of-retail-sales"
    "&seasonaladjustment=seasonal-adjustment&unofficialstandardindustrialclassification=all-retailing-excluding-automotive-fuel"
)
RSI_META_URL = f"{API}/retail-sales-index"
PUBLISHER = "Office for National Statistics"
LICENSE = "OGL-UK-3.0"


def period(label: str) -> str:
    return datetime.strptime(label, "%b-%y").strftime("%Y-%m")


def build(raw: bytes, meta_raw: bytes) -> dict:
    obs = json.loads(raw)["observations"]
    points = sorted(
        ({"period": period(o["dimensions"]["Time"]["id"]), "value": float(o["observation"])} for o in obs if o["dimensions"]["Time"]["id"].endswith(f"-{str(YEAR)[2:]}")),
        key=lambda p: p["period"],
    )
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
            evidence(PUBLISHER, "ONS API, dataset cpih01 version 67, observations for CP00 (overall index), United Kingdom", CPIH_URL, f'observations[Time={first_label}].observation', str(first["value"]).rstrip("0").rstrip(".") if first["value"] != int(first["value"]) else str(int(first["value"])), "decimal", f'"id":"{first_label}","label":"{first_label}"}}}},"observation":', LICENSE, raw),
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
            "cpih01 dataset through the ONS API observations endpoint, which returns the full history; months outside "
            f"{YEAR} are dropped. The index is the headline measure of UK consumer price inflation. ONS publishes the "
            "dataset under the Open Government Licence v3.0, as its metadata states."
        ),
    }


def build_retail(raw: bytes, meta_raw: bytes, license_raw: bytes) -> dict:
    obs = json.loads(raw)["observations"]
    points = sorted(
        ({"period": period(o["dimensions"]["Time"]["id"]), "value": float(o["observation"])} for o in obs if o["dimensions"]["Time"]["id"].endswith(f"-{str(YEAR)[2:]}")),
        key=lambda p: p["period"],
    )
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
            evidence(PUBLISHER, "ONS API, dataset retail-sales-index version 45, observations (chained volume, all retailing excluding automotive fuel, seasonally adjusted, Great Britain)", RSI_URL, f'observations[Time={first_label}].observation', str(first["value"]).rstrip("0").rstrip(".") if first["value"] != int(first["value"]) else str(int(first["value"])), "decimal", f'"id":"{first_label}","label":"{first_label}"', LICENSE, raw),
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
            f"seasonally adjusted, monthly for {YEAR}, from version 45 of the ONS retail-sales-index dataset through the "
            "ONS API observations endpoint (full history returned; other years dropped). The retail-sales-index metadata "
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

"""Regenerate the UK House Price Index entry from HM Land Registry's linked-data API (monthly, 2025).

Run from the repository root:

    uv run python tools/build_gb_house_prices.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

YEAR = 2025
REGION = "united-kingdom"
PUBLISHER = "HM Land Registry"
LICENSE = "OGL-UK-3.0"


def month_url(month: int) -> str:
    return f"https://landregistry.data.gov.uk/data/ukhpi/region/{REGION}/month/{YEAR}-{month:02d}.json"


def build(months: list[tuple[str, bytes]]) -> dict:
    series = []
    items = []
    for url, raw in months:
        topic = json.loads(raw)["result"]["primaryTopic"]
        period = url[-12:-5]
        series.append(
            {
                "period": period,
                "value": float(topic["averagePrice"]),
                "house_price_index": float(topic["housePriceIndex"]),
                "annual_change_percent": float(topic["percentageAnnualChange"]),
                "sales_volume": float(topic["salesVolume"]),
            }
        )
        items.append(evidence(PUBLISHER, f"UK House Price Index, {REGION}, {period} (linked-data API JSON)", url, "result.primaryTopic.averagePrice", topic["averagePrice"], "currency:GBP", '"averagePrice" :', LICENSE, raw))
    first, last = series[0], series[-1]
    peak = max(series, key=lambda p: p["value"])
    return {
        "id": f"gb-house-price-index-monthly-{YEAR}",
        "title": f"UK House Price Index: average price, index, annual change and sales volume, monthly {YEAR}",
        "kind": "temporal",
        "domain": "property",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": ["house-prices", "property", "ukhpi", "land-registry", "time-series"],
        "use_cases": ["mortgage-origination", "insurance", "property-demo", "household-generation"],
        "spec": {
            "variable": "average_price_gbp",
            "unit": "currency:GBP",
            "frequency": "monthly",
            "columns": ["house_price_index", "annual_change_percent", "sales_volume"],
            "series": series,
        },
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": "max", "expected": peak["value"], "tolerance": 0},
            {"statistic": f"column[sales_volume,{first['period']}]", "expected": first["sales_volume"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"UK-wide average house price, house price index (January 2015 = 100), annual percentage change and sales "
            f"volume for each month of {YEAR}, from HM Land Registry's UK House Price Index linked-data API, one request "
            "per month. Recent months are provisional and are revised as late registrations arrive, so a later re-fetch may "
            "change the content hashes; the figures recorded are those served on the access date. HM Land Registry "
            "publishes the UK HPI under the Open Government Licence v3.0, as the UK HPI application states."
        ),
    }


def main() -> int:
    months = [(month_url(m), fetch(month_url(m))) for m in range(1, 13)]
    write(build(months))
    return 0


if __name__ == "__main__":
    sys.exit(main())

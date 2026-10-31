"""Regenerate the central bank policy rate entry from the BIS Data Portal API (monthly, 2025).

Run from the repository root:

    uv run python tools/build_bis_policy_rates.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

AREAS = ["US", "GB", "XM", "JP", "BR", "IN", "CH", "CA", "AU"]
YEAR = 2025
DATA_URL = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.{'+'.join(AREAS)}?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=csv"
TERMS_URL = "https://www.bis.org/terms_conditions.htm"
PUBLISHER = "Bank for International Settlements"
LICENSE = "BIS terms and conditions (statistics subject to 'About BIS statistics' terms)"


def build(raw: bytes, terms_raw: bytes) -> dict:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    by_period: dict[str, dict[str, float]] = {}
    for row in rows:
        by_period.setdefault(row["TIME_PERIOD"], {})[row["REF_AREA"]] = float(row["OBS_VALUE"])
    periods = sorted(by_period)
    columns = [f"{a.lower()}_percent" for a in AREAS if a != "US"]
    series = []
    for p in periods:
        point = {"period": p, "value": by_period[p]["US"]}
        for a in AREAS:
            if a != "US":
                point[f"{a.lower()}_percent"] = by_period[p][a]
        series.append(point)
    last = series[-1]
    us_first = next(r for r in rows if r["REF_AREA"] == "US" and r["TIME_PERIOD"] == periods[0])
    return {
        "id": f"global-central-bank-policy-rates-monthly-{YEAR}",
        "title": f"Central bank policy rates, monthly {YEAR} (US, GB, euro area, JP, BR, IN, CH, CA, AU)",
        "kind": "temporal",
        "domain": "rates",
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "spec": {"variable": "us_percent", "unit": "percent", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER, "BIS Data Portal, dataflow WS_CBPOL (central bank policy rates), monthly (SDMX CSV)", DATA_URL, f"REF_AREA=US, TIME_PERIOD={periods[0]}, OBS_VALUE", us_first["OBS_VALUE"], "percent", f"M,US,", LICENSE, raw),
            evidence(PUBLISHER, "BIS Data Portal, dataflow WS_CBPOL (central bank policy rates), monthly (SDMX CSV)", DATA_URL, "TITLE for the US series", us_first["TITLE"], "text", us_first["TITLE"][:60], LICENSE, raw),
            evidence(PUBLISHER, "BIS terms and conditions", TERMS_URL, "Copyright and permissions", "Users may use the statistics published in the BIS Data Portal in accordance with the terms set out under the heading", "text", "Users may use the statistics published in the BIS Data Portal", LICENSE, terms_raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": f"column[in_percent,{last['period']}]", "expected": last["in_percent"], "tolerance": 1e-9},
            {"statistic": f"column[xm_percent,{periods[0]}]", "expected": series[0]["xm_percent"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"End-of-month central bank policy rates for {YEAR} from the BIS Data Portal (dataflow WS_CBPOL), in percent, "
            "for the United States (primary series), United Kingdom, euro area, Japan, Brazil, India, Switzerland, Canada "
            "and Australia. The BIS general terms permit limited extracts with attribution but refer statistics to a "
            "separate 'About BIS statistics' notice that was not fetched, so the entry is held at license-review until "
            "those terms are confirmed."
        ),
    }


def main() -> int:
    write(build(fetch(DATA_URL), fetch(TERMS_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

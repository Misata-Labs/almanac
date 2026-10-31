"""Regenerate the ECB euro foreign exchange reference rate entry (monthly averages, 2025).

Run from the repository root:

    uv run python tools/build_ecb_fx.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

CURRENCIES = ["USD", "GBP", "JPY", "INR", "BRL", "CNY", "CHF"]
YEAR = 2025
DATA_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/M."
    + "+".join(CURRENCIES)
    + f".EUR.SP00.A?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=csvdata"
)
PUBLISHER = "European Central Bank"
LICENSE = "ECB-free-use-with-attribution"


def build(raw: bytes) -> dict:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    by_period: dict[str, dict[str, float]] = {}
    for row in rows:
        by_period.setdefault(row["TIME_PERIOD"], {})[row["CURRENCY"]] = float(row["OBS_VALUE"])
    periods = sorted(by_period)
    columns = [f"{c.lower()}_per_eur" for c in CURRENCIES if c != "USD"]
    series = []
    for p in periods:
        point = {"period": p, "value": round(by_period[p]["USD"], 6)}
        for c in CURRENCIES:
            if c != "USD":
                point[f"{c.lower()}_per_eur"] = round(by_period[p][c], 6)
        series.append(point)
    last = series[-1]
    usd_jan = next(r for r in rows if r["CURRENCY"] == "USD" and r["TIME_PERIOD"] == periods[0])
    return {
        "id": f"global-ecb-euro-fx-reference-rates-monthly-{YEAR}",
        "title": f"ECB euro foreign exchange reference rates, monthly averages {YEAR} (USD, GBP, JPY, INR, BRL, CNY, CHF per EUR)",
        "kind": "temporal",
        "domain": "currency",
        "region": "global",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "spec": {"variable": "usd_per_eur", "unit": "ratio", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER, "ECB Data Portal, dataset EXR, monthly average reference rates (SDMX CSV)", DATA_URL, f"KEY=EXR.M.USD.EUR.SP00.A, TIME_PERIOD={periods[0]}, OBS_VALUE", usd_jan["OBS_VALUE"], "ratio", f"EXR.M.USD.EUR.SP00.A,M,USD,EUR,SP00,A,{periods[0]}", LICENSE, raw),
            evidence(PUBLISHER, "ECB Data Portal, dataset EXR, monthly average reference rates (SDMX CSV)", DATA_URL, "TITLE_COMPL for the USD series", "ECB reference exchange rate, US dollar/Euro, 2.15 pm (C.E.T.)", "text", "US dollar/Euro ECB reference exchange rate", LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-6},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-6},
            {"statistic": f"column[gbp_per_eur,{last['period']}]", "expected": last["gbp_per_eur"], "tolerance": 1e-6},
            {"statistic": f"column[inr_per_eur,{periods[0]}]", "expected": series[0]["inr_per_eur"], "tolerance": 1e-6},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"Monthly averages of the ECB euro foreign exchange reference rates for {YEAR}, quoted as units of foreign "
            "currency per euro, from the ECB Data Portal's SDMX CSV endpoint (dataset EXR, series SP00.A, frequency M). "
            "The primary series is USD per EUR; the other currencies ride along as columns. Values are rounded to six "
            "decimals. The ECB's website disclaimer states that users may make free use of information obtained from it "
            "provided it is reproduced accurately and the ECB is cited as the source; the page is rendered dynamically "
            "and cannot be hashed, so the clause is recorded under the licence identifier ECB-free-use-with-attribution "
            "documented in CONTRIBUTING.md rather than as evidence."
        ),
    }


def main() -> int:
    write(build(fetch(DATA_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

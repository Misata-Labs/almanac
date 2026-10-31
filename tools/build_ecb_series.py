"""Regenerate the euro area entries from the ECB Data Portal: HICP inflation, the deposit facility rate
and the cost of borrowing for house purchase, all for 2025. Run from the repository root:

    uv run python tools/build_ecb_series.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://data-api.ecb.europa.eu/service/data"
PUBLISHER = "European Central Bank"
LICENSE = "ECB-free-use-with-attribution"
YEAR = 2025
LICENSE_NOTE = (
    "The ECB's website disclaimer states that users may make free use of information obtained from it provided it is "
    "reproduced accurately and the ECB is cited as the source; the page renders dynamically, so the clause is carried by "
    "the licence identifier ECB-free-use-with-attribution documented in CONTRIBUTING.md."
)


def rows_of(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def temporal(entry_id: str, title: str, key: str, url: str, raw: bytes, variable: str, unit: str, tags: list[str], use_cases: list[str], note: str) -> dict:
    rows = rows_of(raw)
    series = [{"period": r["TIME_PERIOD"], "value": float(r["OBS_VALUE"])} for r in rows]
    first, last = series[0], series[-1]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "economy",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": tags + ["ecb", "euro-area"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": "monthly", "columns": [], "series": series},
        "evidence": [
            evidence(PUBLISHER, f"ECB Data Portal, series {key} (SDMX CSV)", url, f"TIME_PERIOD={first['period']}, OBS_VALUE", rows[0]["OBS_VALUE"], unit, f"{key},", LICENSE, raw),
            evidence(PUBLISHER, f"ECB Data Portal, series {key} (SDMX CSV)", url, "TITLE_COMPL", rows[0]["TITLE_COMPL"][:90], "text", rows[0]["TITLE"], LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " " + LICENSE_NOTE,
    }


def deposit_facility(raw: bytes, url: str) -> dict:
    rows = rows_of(raw)
    steps = [{"from": r["TIME_PERIOD"], "value": float(r["OBS_VALUE"])} for r in rows]
    key = rows[0]["KEY"]
    return {
        "id": f"eu-ecb-deposit-facility-rate-changes-{YEAR}",
        "title": f"ECB deposit facility rate: changes decided in {YEAR}",
        "kind": "rule",
        "domain": "rates",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": steps[0]["from"],
        "valid_to": None,
        "tags": ["ecb", "euro-area", "policy-rate", "step-schedule"],
        "use_cases": ["banking-demo", "treasury", "loan-pricing"],
        "spec": {
            "implementation": "almanac.rules.step_schedule",
            "parameters": {"series": key, "unit": "percent", "steps": steps},
            "vectors": [
                {"input": {"on": steps[0]["from"]}, "expected": steps[0]["value"], "origin": "source"},
                {"input": {"on": steps[-1]["from"]}, "expected": steps[-1]["value"], "origin": "source"},
                {"input": {"on": f"{YEAR}-12-31"}, "expected": steps[-1]["value"], "origin": "derived", "note": "last change still in force at year end"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, f"ECB Data Portal, series {key} (deposit facility, date of changes)", url, f"TIME_PERIOD={steps[0]['from']}, OBS_VALUE", rows[0]["OBS_VALUE"], "percent", f"{key},", LICENSE, raw),
            evidence(PUBLISHER, f"ECB Data Portal, series {key} (deposit facility, date of changes)", url, f"TIME_PERIOD={steps[-1]['from']}, OBS_VALUE", rows[-1]["OBS_VALUE"], "percent", rows[-1]["TIME_PERIOD"], LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": f"value[{YEAR}-12-31]", "expected": steps[-1]["value"], "tolerance": 1e-9},
        ],
        "notes": (
            f"Each change to the ECB deposit facility rate decided in {YEAR}, with the date from which the new level "
            "applied, from the ECB Data Portal's key-interest-rate series (dates of changes, raw data). The schedule "
            "starts at the first change of the year; the level in force before it is not part of this entry. "
            + LICENSE_NOTE
        ),
    }


def main() -> int:
    hicp_url = f"{API}/ICP/M.U2.N.000000.4.ANR?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=csvdata"
    dfr_url = f"{API}/FM/B.U2.EUR.4F.KR.DFR.LEV?startPeriod={YEAR}-01-01&endPeriod={YEAR}-12-31&format=csvdata"
    mir_url = f"{API}/MIR/M.U2.B.A2C.AM.R.A.2250.EUR.N?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=csvdata"
    write(temporal(
        f"eu-hicp-inflation-annual-rate-monthly-{YEAR}",
        f"Euro area HICP inflation, annual rate of change by month, {YEAR}",
        "ICP.M.U2.N.000000.4.ANR", hicp_url, fetch(hicp_url), "hicp_annual_rate_percent", "percent",
        ["inflation", "prices"], ["pricing", "financial-planning", "banking-demo"],
        f"Euro area (changing composition) HICP overall index, annual rate of change, monthly for {YEAR}, compiled by Eurostat and published by the ECB Data Portal.",
    ))
    write(temporal(
        f"eu-cost-of-borrowing-house-purchase-monthly-{YEAR}",
        f"Euro area cost of borrowing for households for house purchase, monthly {YEAR}",
        "MIR.M.U2.B.A2C.AM.R.A.2250.EUR.N", mir_url, fetch(mir_url), "mortgage_rate_percent", "percent",
        ["mortgage", "lending-rates"], ["banking-demo", "loan-pricing", "mortgage-origination"],
        f"Euro area cost-of-borrowing indicator for households for house purchase (annualised agreed rate, new business), monthly for {YEAR}, from the ECB MFI interest rate statistics.",
    ))
    write(deposit_facility(fetch(dfr_url), dfr_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())

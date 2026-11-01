"""Regenerate the US Treasury Fiscal Data entries: average interest rates on Treasury securities at a
month end, and the daily Debt to the Penny series for a calendar year. Run from the repository root:

    uv run python tools/build_us_fiscal_data.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
PUBLISHER = "US Department of the Treasury, Bureau of the Fiscal Service"
LICENSE = "unstated"
LICENSE_NOTE = (
    "The Fiscal Data dataset pages render their licence section dynamically and were not captured, so the licence "
    "is recorded as unstated and the entry held at license-review even though US federal publications are normally "
    "free to reuse."
)
RATES_DATE = "2025-12-31"
DEBT_YEAR = 2025


def average_interest_rates(raw: bytes, url: str) -> dict:
    data = json.loads(raw)["data"]
    rows = {
        r["security_desc"]: {"security_type": r["security_type_desc"], "avg_interest_rate_percent": float(r["avg_interest_rate_amt"]), "source_line": int(r["src_line_nbr"])}
        for r in data
    }
    bills = next(r for r in data if r["security_desc"] == "Treasury Bills")
    total = next(r for r in data if r["security_desc"] == "Total Interest-bearing Debt")
    return {
        "id": f"us-treasury-average-interest-rates-{RATES_DATE[:7]}",
        "title": f"Average interest rates on US Treasury securities by security class, {RATES_DATE} ({len(rows)} lines)",
        "kind": "rule",
        "domain": "treasury",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": RATES_DATE[:8] + "01",
        "valid_to": RATES_DATE,
        "tags": ["interest-rates", "treasury-securities", "public-debt", "reference-table", "fiscal-data"],
        "use_cases": ["treasury", "loan-pricing", "financial-planning", "banking-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"record_date": RATES_DATE, "unit": "percent per year", "rows": rows},
            "vectors": [
                {"input": {"key": "Treasury Bills", "column": "avg_interest_rate_percent"}, "expected": float(bills["avg_interest_rate_amt"]), "origin": "source"},
                {"input": {"key": "Total Interest-bearing Debt", "column": "avg_interest_rate_percent"}, "expected": float(total["avg_interest_rate_amt"]), "origin": "source"},
                {"input": {"key": "Treasury Notes", "column": "security_type"}, "expected": "Marketable", "origin": "source"},
                {"input": "Treasury Bonds", "expected": True, "origin": "source"},
                {"input": "Treasury Perpetuals", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, f"Fiscal Data API, Average Interest Rates on U.S. Treasury Securities, record_date {RATES_DATE}", url, 'data[security_desc="Treasury Bills"].avg_interest_rate_amt', bills["avg_interest_rate_amt"], "percent", '"security_desc":"Treasury Bills","avg_interest_rate_amt":"' + bills["avg_interest_rate_amt"] + '"', LICENSE, raw),
            evidence(PUBLISHER, f"Fiscal Data API, Average Interest Rates on U.S. Treasury Securities, record_date {RATES_DATE}", url, 'data[security_desc="Total Interest-bearing Debt"].avg_interest_rate_amt', total["avg_interest_rate_amt"], "percent", '"security_desc":"Total Interest-bearing Debt","avg_interest_rate_amt":"' + total["avg_interest_rate_amt"] + '"', LICENSE, raw),
            evidence(PUBLISHER, f"Fiscal Data API, Average Interest Rates on U.S. Treasury Securities, record_date {RATES_DATE}", url, "meta.total-count", len(data), "count", '"total-count":', LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[Total Marketable,avg_interest_rate_percent]", "expected": rows["Total Marketable"]["avg_interest_rate_percent"], "tolerance": 0},
            {"statistic": "max[avg_interest_rate_percent]", "expected": max(r["avg_interest_rate_percent"] for r in rows.values()), "tolerance": 0},
        ],
        "notes": (
            f"The average interest rate on each class of outstanding US Treasury securities at {RATES_DATE}, one row "
            "per line of the Treasury's monthly statement (marketable classes, non-marketable classes, their "
            "subtotals and the total for all interest-bearing debt), from the Fiscal Data API. Subtotal and total "
            "lines are kept as rows because the source publishes them; a generator weighting instruments should "
            "use the individual classes. " + LICENSE_NOTE
        ),
    }


def debt_to_the_penny(raw: bytes, url: str) -> dict:
    data = json.loads(raw)["data"]
    series = [
        {"period": r["record_date"], "value": float(r["tot_pub_debt_out_amt"]), "debt_held_by_public": float(r["debt_held_public_amt"]), "intragovernmental_holdings": float(r["intragov_hold_amt"])}
        for r in sorted(data, key=lambda r: r["record_date"])
    ]
    first_point, last_point = data[0], data[-1]
    return {
        "id": f"us-public-debt-to-the-penny-{DEBT_YEAR}",
        "title": f"United States total public debt outstanding, daily (Debt to the Penny), {DEBT_YEAR}",
        "kind": "temporal",
        "domain": "treasury",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": series[0]["period"], "end": series[-1]["period"]},
        "tags": ["public-debt", "treasury", "daily-series", "fiscal-data"],
        "use_cases": ["treasury", "financial-reporting", "financial-planning"],
        "spec": {
            "variable": "total_public_debt_outstanding_usd",
            "unit": "currency:USD",
            "frequency": "daily",
            "columns": ["debt_held_by_public", "intragovernmental_holdings"],
            "series": series,
        },
        "evidence": [
            evidence(PUBLISHER, f"Fiscal Data API, Debt to the Penny, record_date in {DEBT_YEAR}", url, f'data[record_date="{first_point["record_date"]}"].tot_pub_debt_out_amt', first_point["tot_pub_debt_out_amt"], "currency:USD", f'"tot_pub_debt_out_amt":"{first_point["tot_pub_debt_out_amt"]}"', LICENSE, raw),
            evidence(PUBLISHER, f"Fiscal Data API, Debt to the Penny, record_date in {DEBT_YEAR}", url, f'data[record_date="{last_point["record_date"]}"].tot_pub_debt_out_amt', last_point["tot_pub_debt_out_amt"], "currency:USD", f'"tot_pub_debt_out_amt":"{last_point["tot_pub_debt_out_amt"]}"', LICENSE, raw),
            evidence(PUBLISHER, f"Fiscal Data API, Debt to the Penny, record_date in {DEBT_YEAR}", url, "meta.total-count", len(data), "count", '"total-count":', LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{series[0]['period']}]", "expected": series[0]["value"], "tolerance": 0.01},
            {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 0.01},
            {"statistic": f"column[debt_held_by_public,{series[-1]['period']}]", "expected": series[-1]["debt_held_by_public"], "tolerance": 0.01},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
            {"statistic": "max", "expected": max(p["value"] for p in series), "tolerance": 0.01},
        ],
        "notes": (
            f"Total public debt outstanding of the United States for every business day the Treasury reported in "
            f"{DEBT_YEAR}, split into debt held by the public and intragovernmental holdings, from the Fiscal Data "
            "Debt to the Penny dataset. Values are US dollars to the cent as published; the series only has points "
            "on reporting days, so weekends and federal holidays are absent. " + LICENSE_NOTE
        ),
    }


def main() -> int:
    rates_url = f"{API}/v2/accounting/od/avg_interest_rates?filter=record_date:eq:{RATES_DATE}&page%5Bsize%5D=100"
    debt_url = f"{API}/v2/accounting/od/debt_to_penny?filter=record_date:gte:{DEBT_YEAR}-01-01,record_date:lte:{DEBT_YEAR}-12-31&page%5Bsize%5D=400"
    write(average_interest_rates(fetch(rates_url), rates_url))
    write(debt_to_the_penny(fetch(debt_url), debt_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())

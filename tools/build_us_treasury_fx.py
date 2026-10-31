"""Regenerate the US Treasury reporting rates of exchange entry for a quarter-end date.

Run from the repository root:

    uv run python tools/build_us_treasury_fx.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

RECORD_DATE = "2025-12-31"
URL = f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/rates_of_exchange?filter=record_date:eq:{RECORD_DATE}&page%5Bsize%5D=300"
PUBLISHER = "US Department of the Treasury, Bureau of the Fiscal Service"
LICENSE = "unstated"


def build(raw: bytes) -> dict:
    data = json.loads(raw)["data"]
    rows = {r["country_currency_desc"]: {"country": r["country"], "currency": r["currency"], "rate_per_usd": float(r["exchange_rate"]), "effective_date": r["effective_date"]} for r in data}
    rows = dict(sorted(rows.items()))
    sample = next(r for r in data if r["country_currency_desc"] == "India-Rupee")
    return {
        "id": "us-treasury-reporting-rates-of-exchange-2025-12-31",
        "title": f"US Treasury reporting rates of exchange as of {RECORD_DATE} ({len(rows)} country-currency pairs)",
        "kind": "rule",
        "domain": "currency",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": RECORD_DATE,
        "valid_to": None,
        "tags": ["exchange-rates", "treasury", "reference-table", "reporting"],
        "use_cases": ["financial-reporting", "multi-currency-ledger", "audit-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"record_date": RECORD_DATE, "unit": "foreign currency units per USD", "rows": rows},
            "vectors": [
                {"input": {"key": "India-Rupee", "column": "rate_per_usd"}, "expected": float(sample["exchange_rate"]), "origin": "source"},
                {"input": {"key": "Euro Zone-Euro", "column": "rate_per_usd"}, "expected": rows["Euro Zone-Euro"]["rate_per_usd"], "origin": "source"},
                {"input": "Japan-Yen", "expected": True, "origin": "source"},
                {"input": "Atlantis-Shell", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, f"Fiscal Data API, Treasury Reporting Rates of Exchange, record_date {RECORD_DATE}", URL, 'data[country_currency_desc="India-Rupee"].exchange_rate', sample["exchange_rate"], "ratio", '"country_currency_desc":"India-Rupee"', LICENSE, raw),
            evidence(PUBLISHER, f"Fiscal Data API, Treasury Reporting Rates of Exchange, record_date {RECORD_DATE}", URL, "meta.total-count", len(data), "count", '"total-count":', LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[United Kingdom-Pound,rate_per_usd]", "expected": rows["United Kingdom-Pound"]["rate_per_usd"], "tolerance": 0},
        ],
        "notes": (
            f"The exchange rates the US Treasury prescribes for converting foreign currency into US dollars in federal "
            f"financial reporting, as of {RECORD_DATE}, one row per country-currency pair, from the Fiscal Data API. The "
            "dataset page's licence section renders dynamically and was not captured, so the licence is recorded as "
            "unstated and the entry held at license-review even though US federal publications are normally free to reuse."
        ),
    }


def main() -> int:
    write(build(fetch(URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

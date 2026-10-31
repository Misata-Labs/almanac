"""Regenerate the Banco Central do Brasil time-series entries (SGS): the Selic target as a step
schedule, IPCA monthly inflation, and the household credit default rate, all for 2025.
Run from the repository root:

    uv run python tools/build_br_bcb_series.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

YEAR = 2025
PUBLISHER = "Banco Central do Brasil"
LICENSE = "ODbL-1.0"
LICENSE_NOTE = (
    "The BCB open data catalogue (dadosabertos.bcb.gov.br) lists this series under the Open Database License; the "
    "catalogue API answers vary between requests, so that record is referenced here rather than hashed as evidence."
)


def sgs_url(code: int) -> str:
    return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/{YEAR}&dataFinal=31/12/{YEAR}"


def iso(dmy: str) -> str:
    return datetime.strptime(dmy, "%d/%m/%Y").date().isoformat()


def selic(raw: bytes, url: str) -> dict:
    rows = json.loads(raw)
    steps = []
    for r in rows:
        if not steps or float(r["valor"]) != steps[-1]["value"]:
            steps.append({"from": iso(r["data"]), "value": float(r["valor"])})
    return {
        "id": f"br-selic-target-rate-changes-{YEAR}",
        "title": f"Brazil Selic target rate set by the Copom: levels in force during {YEAR}",
        "kind": "rule",
        "domain": "rates",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{YEAR}-01-01",
        "valid_to": f"{YEAR}-12-31",
        "tags": ["policy-rate", "selic", "step-schedule", "bcb"],
        "use_cases": ["banking-demo", "loan-pricing", "treasury"],
        "spec": {
            "implementation": "almanac.rules.step_schedule",
            "parameters": {"series": "bcdata.sgs.432", "unit": "percent per year", "steps": steps},
            "vectors": [
                {"input": {"on": f"{YEAR}-01-01"}, "expected": float(rows[0]["valor"]), "origin": "source"},
                {"input": {"on": f"{YEAR}-12-31"}, "expected": float(rows[-1]["valor"]), "origin": "source"},
                {"input": {"on": steps[1]["from"]}, "expected": steps[1]["value"], "origin": "source", "note": "first change of the year"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "SGS series 432, Taxa de juros - Meta Selic definida pelo Copom (daily, JSON)", url, f"data=01/01/{YEAR}, valor", rows[0]["valor"], "percent", f'{{"data":"01/01/{YEAR}","valor":', LICENSE, raw),
            evidence(PUBLISHER, "SGS series 432, Taxa de juros - Meta Selic definida pelo Copom (daily, JSON)", url, f"data=31/12/{YEAR}, valor", rows[-1]["valor"], "percent", f'{{"data":"31/12/{YEAR}","valor":', LICENSE, raw),
        ],
        "assumed": [
            {
                "parameter": "steps[*].from",
                "value": "first calendar day on which the daily series shows a new level",
                "method": "derived",
                "rationale": "The series publishes the target level for every day; the schedule keeps only the days on which the level differs from the previous day. The first step is the level on 1 January, not a decision date.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": "max", "expected": max(s["value"] for s in steps), "tolerance": 0},
        ],
        "notes": (
            f"The Selic target rate (percent per year) in force on each day of {YEAR} from SGS series 432, reduced to "
            "the dates on which the level changed. " + LICENSE_NOTE
        ),
    }


def temporal(entry_id: str, title: str, code: int, series_name: str, raw: bytes, url: str, variable: str, unit: str, tags: list[str], use_cases: list[str], note: str) -> dict:
    rows = json.loads(raw)
    series = [{"period": iso(r["data"])[:7], "value": float(r["valor"])} for r in rows]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "economy",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": tags + ["bcb", "sgs"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": "monthly", "columns": [], "series": series},
        "evidence": [
            evidence(PUBLISHER, f"SGS series {code}, {series_name} (monthly, JSON)", url, f"data=01/01/{YEAR}, valor", rows[0]["valor"], unit, f'{{"data":"01/01/{YEAR}","valor":', LICENSE, raw),
            evidence(PUBLISHER, f"SGS series {code}, {series_name} (monthly, JSON)", url, f"data={rows[-1]['data']}, valor", rows[-1]["valor"], unit, f'{{"data":"{rows[-1]["data"]}","valor":', LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{series[0]['period']}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " " + LICENSE_NOTE,
    }


def main() -> int:
    url = sgs_url(432)
    write(selic(fetch(url), url))
    url = sgs_url(433)
    write(temporal(f"br-ipca-monthly-inflation-{YEAR}", f"Brazil IPCA consumer price inflation, monthly variation, {YEAR}", 433, "Índice nacional de preços ao consumidor-amplo (IPCA), variação mensal", fetch(url), url, "ipca_monthly_percent", "percent", ["inflation", "prices", "ipca"], ["pricing", "financial-planning"], f"Monthly percentage variation of the IPCA, Brazil's headline consumer price index compiled by IBGE, for {YEAR} as published by the BCB time-series system (SGS 433)."))
    url = sgs_url(21084)
    write(temporal(f"br-household-credit-default-rate-{YEAR}", f"Brazil credit portfolio default rate, individuals, monthly {YEAR}", 21084, "Inadimplência da carteira de crédito - Pessoas físicas - Total", fetch(url), url, "default_rate_percent", "percent", ["credit-risk", "default", "household-credit"], ["credit-risk", "banking-demo", "collections"], f"Share of the credit portfolio of individuals (pessoas físicas) in arrears, monthly for {YEAR}, from SGS series 21084 of the BCB credit statistics."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

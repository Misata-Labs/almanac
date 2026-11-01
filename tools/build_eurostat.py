"""Regenerate the Eurostat entries: monthly unemployment and HICP inflation for ten member states,
household electricity prices, population by sex, and single-year age distributions for Germany and
France. Run from the repository root:

    uv run python tools/build_eurostat.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
PUBLISHER = "Eurostat"
LICENSE = "CC-BY-4.0"
GEOS = ["DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"]
YEAR = 2025
LICENSE_NOTE = (
    "Eurostat's copyright notice states that its data are released under the Creative Commons Attribution 4.0 "
    "International licence; the notice page renders dynamically and is referenced rather than hashed."
)


def rows_of(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def monthly_by_geo(entry_id: str, title: str, url: str, raw: bytes, variable: str, unit: str, tags: list[str], use_cases: list[str], note: str) -> dict:
    rows = rows_of(raw)
    by_period: dict[str, dict[str, float]] = {}
    for r in rows:
        by_period.setdefault(r["TIME_PERIOD"], {})[r["geo"]] = float(r["OBS_VALUE"])
    periods = sorted(by_period)
    columns = [f"{g.lower()}" for g in GEOS if g != "DE"]
    series = []
    for p in periods:
        point = {"period": p, "value": by_period[p]["DE"]}
        for g in GEOS:
            if g != "DE":
                point[g.lower()] = by_period[p][g]
        series.append(point)
    de_first = next(r for r in rows if r["geo"] == "DE" and r["TIME_PERIOD"] == periods[0])
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "economy",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": tags + ["eurostat", "by-country"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER, f"Eurostat SDMX 2.1 API, dataflow {de_first['DATAFLOW']} (SDMX-CSV)", url, f"geo=DE, TIME_PERIOD={periods[0]}, OBS_VALUE", de_first["OBS_VALUE"], unit, f"DE,{periods[0]},{de_first['OBS_VALUE']}", LICENSE, raw),
            evidence(PUBLISHER, f"Eurostat SDMX 2.1 API, dataflow {de_first['DATAFLOW']} (SDMX-CSV)", url, "LAST UPDATE", de_first["LAST UPDATE"], "text", de_first["DATAFLOW"], LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"column[fr,{periods[-1]}]", "expected": series[-1]["fr"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " Germany is the primary series; the other nine member states ride along as columns keyed by their two-letter geo code. " + LICENSE_NOTE,
    }


def electricity(url: str, raw: bytes) -> dict:
    rows = rows_of(raw)
    table = {r["geo"]: {"eur_per_kwh": float(r["OBS_VALUE"]), "period": r["TIME_PERIOD"]} for r in rows}
    table = dict(sorted(table.items()))
    period = rows[0]["TIME_PERIOD"]
    return {
        "id": f"eu-household-electricity-prices-{period.replace('-', '').lower()}",
        "title": f"Household electricity prices including taxes, consumption band 2 500 to 4 999 kWh, {period}, ten member states",
        "kind": "rule",
        "domain": "energy",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{period[:4]}-01-01",
        "valid_to": f"{period[:4]}-06-30",
        "tags": ["electricity", "energy-prices", "eurostat", "reference-table", "utilities"],
        "use_cases": ["utilities-demo", "pricing", "household-generation"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"dataflow": "nrg_pc_204", "key": "S.E7000.KWH2500-4999.KWH.I_TAX.EUR", "rows": table},
            "vectors": [
                {"input": {"key": "DE", "column": "eur_per_kwh"}, "expected": table["DE"]["eur_per_kwh"], "origin": "source"},
                {"input": {"key": "FR", "column": "eur_per_kwh"}, "expected": table["FR"]["eur_per_kwh"], "origin": "source"},
                {"input": "XX", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "Eurostat SDMX 2.1 API, dataflow nrg_pc_204 (electricity prices for household consumers), SDMX-CSV", url, f"geo=DE, TIME_PERIOD={period}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["geo"] == "DE"), "decimal", f"DE,{period}", LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
            {"statistic": "max[eur_per_kwh]", "expected": max(v["eur_per_kwh"] for v in table.values()), "tolerance": 0},
        ],
        "notes": (
            f"Electricity prices for household consumers, all taxes and levies included, consumption band DC "
            f"(2 500 to 4 999 kWh per year), in euro per kWh for the half-year {period}, from Eurostat dataflow nrg_pc_204. "
            "valid_from and valid_to bound the half-year the prices describe. " + LICENSE_NOTE
        ),
    }


def population_by_sex(url: str, raw: bytes) -> dict:
    rows = rows_of(raw)
    table: dict[str, dict] = {}
    for r in rows:
        table.setdefault(r["geo"], {})[{"F": "female", "M": "male"}[r["sex"]]] = int(float(r["OBS_VALUE"]))
    for geo, v in table.items():
        v["female_share"] = round(v["female"] / (v["female"] + v["male"]), 6)
    table = dict(sorted(table.items()))
    year = rows[0]["TIME_PERIOD"]
    return {
        "id": f"eu-population-by-sex-{year}",
        "title": f"Population on 1 January {year} by sex, ten member states (Eurostat demo_pjan)",
        "kind": "rule",
        "domain": "demographics",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "tags": ["population", "sex", "eurostat", "reference-table"],
        "use_cases": ["person-generation", "customer-segmentation", "market-sizing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"dataflow": "demo_pjan", "rows": table},
            "vectors": [
                {"input": {"key": "DE", "column": "female"}, "expected": table["DE"]["female"], "origin": "source"},
                {"input": {"key": "FR", "column": "male"}, "expected": table["FR"]["male"], "origin": "source"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "Eurostat SDMX 2.1 API, dataflow demo_pjan (population on 1 January by age and sex), SDMX-CSV", url, f"geo=DE, sex=F, TIME_PERIOD={year}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["geo"] == "DE" and r["sex"] == "F"), "count", f"F,DE,{year}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "rows[*].female_share", "value": "female / (female + male)", "method": "derived", "rationale": "Eurostat publishes the counts; the share is their ratio."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
        ],
        "notes": f"Population on 1 January {year} by sex for ten member states from Eurostat dataflow demo_pjan (age TOTAL). " + LICENSE_NOTE,
    }


def age_marginal(geo: str, name: str, url: str, raw: bytes) -> dict:
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    counts: dict[str, int] = {}
    for r in rows:
        age = r["age"]
        if age in ("TOTAL", "UNK"):
            continue
        label = {"Y_LT1": "0", "Y_OPEN": "100+"}.get(age, age[1:])
        counts[label] = int(float(r["OBS_VALUE"]))
    counts = dict(sorted(counts.items(), key=lambda kv: (kv[0] == "100+", int(kv[0].rstrip("+")))))
    total = sum(counts.values())
    shares = {k: round(v / total, 6) for k, v in counts.items()}
    return {
        "id": f"{geo.lower()}-population-by-single-year-of-age-{year}",
        "title": f"{name} population on 1 January {year} by single year of age (Eurostat demo_pjan)",
        "kind": "marginal",
        "domain": "demographics",
        "region": geo,
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-01-01"},
        "tags": ["population", "age", "eurostat"],
        "use_cases": ["person-generation", "customer-segmentation", "insurance", "pensions"],
        "spec": {"variable": "age", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total}}},
        "evidence": [
            evidence(PUBLISHER, "Eurostat SDMX 2.1 API, dataflow demo_pjan (population on 1 January by age and sex), SDMX-CSV", url, f"geo={geo}, age=Y_LT1, TIME_PERIOD={year}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["age"] == "Y_LT1"), "count", f"Y_LT1,T,{geo},{year}", LICENSE, raw),
            evidence(PUBLISHER, "Eurostat SDMX 2.1 API, dataflow demo_pjan (population on 1 January by age and sex), SDMX-CSV", url, f"geo={geo}, age=TOTAL, TIME_PERIOD={year}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["age"] == "TOTAL"), "count", f"TOTAL,T,{geo},{year}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "count / sum of counts over known ages", "method": "derived", "rationale": "Eurostat publishes counts per single year of age; the TOTAL and UNK rows are dropped and shares are counts over the sum of the known ages. Y_LT1 is labelled 0 and Y_OPEN 100+."},
        ],
        "tests": [
            {"statistic": 'share["0"]', "expected": shares["0"], "tolerance": 0.002},
            {"statistic": 'share["100+"]', "expected": shares["100+"], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": f"{name} population on 1 January {year} by single year of age, both sexes, from Eurostat dataflow demo_pjan. " + LICENSE_NOTE,
    }


def main() -> int:
    geo = "+".join(GEOS)
    url = f"{API}/une_rt_m/M.SA.TOTAL.PC_ACT.T.{geo}?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=SDMX-CSV"
    write(monthly_by_geo(f"eu-unemployment-rate-monthly-{YEAR}", f"Unemployment rate, seasonally adjusted, monthly {YEAR}, ten member states", url, fetch(url), "unemployment_rate_percent", "percent", ["unemployment", "labour"], ["hr-analytics", "credit-risk", "market-sizing"], f"Monthly seasonally adjusted unemployment rate (percent of the active population, all ages, both sexes) for {YEAR} from Eurostat dataflow une_rt_m."))
    url = f"{API}/prc_hicp_manr/M.RCH_A.CP00.{geo}?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=SDMX-CSV"
    write(monthly_by_geo(f"eu-hicp-inflation-by-country-monthly-{YEAR}", f"HICP inflation, annual rate of change, monthly {YEAR}, ten member states", url, fetch(url), "hicp_annual_rate_percent", "percent", ["inflation", "prices", "hicp"], ["pricing", "financial-planning", "contract-indexation"], f"Monthly annual rate of change of the all-items HICP for {YEAR} from Eurostat dataflow prc_hicp_manr."))
    url = f"{API}/nrg_pc_204/S.E7000.KWH2500-4999.KWH.I_TAX.EUR.{geo}?startPeriod={YEAR}-S1&endPeriod={YEAR}-S1&format=SDMX-CSV"
    write(electricity(url, fetch(url)))
    url = f"{API}/demo_pjan/A.NR.TOTAL.F+M.{geo}?startPeriod=2024&endPeriod=2024&format=SDMX-CSV"
    write(population_by_sex(url, fetch(url)))
    for code, name in (("DE", "Germany"), ("FR", "France")):
        url = f"{API}/demo_pjan/A.NR..T.{code}?startPeriod=2024&endPeriod=2024&format=SDMX-CSV"
        write(age_marginal(code, name, url, fetch(url)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

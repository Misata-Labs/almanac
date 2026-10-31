"""Regenerate the World Bank indicator reference tables (one lookup entry per indicator).

Each indicator becomes a rule entry implemented by ``lookup_table``: rows are
keyed by ISO 3166-1 alpha-3 code and hold the indicator value for the chosen
year, with aggregates removed. Run from the repository root:

    uv run python tools/build_world_indicators.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://api.worldbank.org/v2"
COUNTRIES_URL = f"{API}/country?format=json&per_page=400"
LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
PUBLISHER = "World Bank"
LICENSE = "CC-BY-4.0"

# (indicator id, year, entry id, variable, unit, tags, use cases)
INDICATORS = [
    ("NY.GDP.PCAP.CD", 2024, "global-gdp-per-capita-2024", "gdp_per_capita_usd", "currency:USD", ["macro", "income"], ["market-sizing", "customer-segmentation"]),
    ("NY.GDP.MKTP.CD", 2024, "global-gdp-2024", "gdp_usd", "currency:USD", ["macro"], ["market-sizing"]),
    ("FP.CPI.TOTL.ZG", 2024, "global-inflation-cpi-2024", "inflation_percent", "percent", ["macro", "prices"], ["pricing", "financial-planning"]),
    ("SL.UEM.TOTL.ZS", 2024, "global-unemployment-rate-2024", "unemployment_percent", "percent", ["labour"], ["hr-analytics", "credit-risk"]),
    ("SL.TLF.CACT.ZS", 2024, "global-labour-force-participation-2024", "participation_percent", "percent", ["labour"], ["hr-analytics"]),
    ("IT.NET.USER.ZS", 2024, "global-internet-users-2024", "internet_users_percent", "percent", ["digital", "telecom"], ["digital-channels", "telecom-demo"]),
    ("IT.CEL.SETS.P2", 2024, "global-mobile-subscriptions-per-100-2024", "mobile_subscriptions_per_100", "ratio", ["telecom"], ["telecom-demo"]),
    ("SP.URB.TOTL.IN.ZS", 2024, "global-urban-population-share-2024", "urban_percent", "percent", ["demographics"], ["address-generation", "logistics"]),
    ("SP.DYN.LE00.IN", 2023, "global-life-expectancy-2023", "life_expectancy_years", "decimal", ["health", "demographics"], ["insurance", "pensions"]),
    ("SP.DYN.TFRT.IN", 2023, "global-fertility-rate-2023", "births_per_woman", "decimal", ["demographics"], ["household-generation"]),
    ("SP.POP.TOTL.FE.ZS", 2024, "global-female-population-share-2024", "female_percent", "percent", ["demographics"], ["person-generation"]),
    ("FX.OWN.TOTL.ZS", 2024, "global-financial-account-ownership-2024", "account_ownership_percent", "percent", ["financial-inclusion", "banking"], ["banking-demo", "kyc-onboarding"]),
]


def economies(countries_raw: bytes) -> dict[str, dict]:
    return {c["id"]: c for c in json.loads(countries_raw)[1] if c["region"]["value"] != "Aggregates"}


def build(indicator: str, year: int, entry_id: str, variable: str, unit: str, tags: list[str], use_cases: list[str], data_raw: bytes, meta_raw: bytes, countries: dict[str, dict], countries_raw: bytes, license_raw: bytes) -> dict:
    meta, rows_raw = json.loads(data_raw)
    info = json.loads(meta_raw)[1][0]
    rows: dict[str, dict] = {}
    for r in rows_raw:
        code = r["countryiso3code"]
        if code in countries and r["value"] is not None:
            rows[code] = {"name": r["country"]["value"], "value": r["value"]}
    rows = dict(sorted(rows.items()))
    values = [r["value"] for r in rows.values()]
    sample = rows.get("IND") or next(iter(rows.values()))
    sample_code = "IND" if "IND" in rows else next(iter(rows))
    high = max(rows, key=lambda k: rows[k]["value"])
    low = min(rows, key=lambda k: rows[k]["value"])
    data_url = f"{API}/country/all/indicator/{indicator}?date={year}&format=json&per_page=400"
    return {
        "id": entry_id,
        "title": f"{info['name']}, by economy, {year} (World Bank, {len(rows)} economies)",
        "kind": "rule",
        "domain": "economy",
        "region": "global",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "tags": tags + ["world-bank", "reference-table"],
        "use_cases": use_cases,
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"indicator": indicator, "year": year, "variable": variable, "unit": unit, "rows": rows},
            "vectors": [
                {"input": {"key": sample_code, "column": "value"}, "expected": sample["value"], "origin": "source"},
                {"input": {"key": high, "column": "value"}, "expected": rows[high]["value"], "origin": "source", "note": "largest value"},
                {"input": {"key": low, "column": "value"}, "expected": rows[low]["value"], "origin": "source", "note": "smallest value"},
                {"input": sample_code, "expected": True, "origin": "source"},
                {"input": "WLD", "expected": False, "origin": "derived", "note": "aggregates are excluded"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, f"World Development Indicators API, {indicator} ({info['name']}), {year}", data_url, f'rows[countryiso3code={sample_code}].value', sample["value"], unit, f'"countryiso3code":"{sample_code}"', LICENSE, data_raw),
            evidence(PUBLISHER, f"World Development Indicators API, {indicator} ({info['name']}), {year}", data_url, "lastupdated", meta["lastupdated"], "date", '"lastupdated":', LICENSE, data_raw),
            evidence(PUBLISHER, f"World Bank indicator metadata, {indicator}", f"{API}/indicator/{indicator}?format=json", "name", info["name"], "text", f'"id":"{indicator}"', LICENSE, meta_raw),
            evidence(PUBLISHER, "World Bank country API (region classification used to exclude aggregates)", COUNTRIES_URL, 'country[id=IND].region.value', "South Asia", "text", '"id":"IND"', LICENSE, countries_raw),
            evidence(PUBLISHER, "World Bank Data Catalog public licenses", LICENSE_URL, "Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "rows",
                "value": "economies only",
                "method": "derived",
                "rationale": "Rows whose region is 'Aggregates' in the World Bank country API, and rows without a value for the year, are dropped; everything else is copied unchanged.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[value]", "expected": max(values), "tolerance": 0},
            {"statistic": "min[value]", "expected": min(values), "tolerance": 0},
        ],
        "notes": (
            f"{info['name']} for {year} from the World Development Indicators API (indicator {indicator}, data last "
            f"updated {meta['lastupdated']}), one row per economy keyed by ISO 3166-1 alpha-3 code, with regional and "
            f"income aggregates removed. Source note from the World Bank: {(info.get('sourceNote') or '').strip()[:400]} "
            "The World Bank licenses its datasets under CC BY 4.0."
        ),
    }


def build_classification(countries_raw: bytes, license_raw: bytes) -> dict:
    rows = {
        code: {"name": c["name"], "iso2": c["iso2Code"], "region": c["region"]["value"].strip(), "income_group": c["incomeLevel"]["value"], "capital": c["capitalCity"]}
        for code, c in sorted(economies(countries_raw).items())
    }
    groups: dict[str, int] = {}
    for r in rows.values():
        groups[r["income_group"]] = groups.get(r["income_group"], 0) + 1
    return {
        "id": "global-economy-classification",
        "title": f"World Bank economies with ISO codes, region and income group ({len(rows)} economies)",
        "kind": "rule",
        "domain": "economy",
        "region": "global",
        "status": "verified",
        "tier": "A",
        "valid_from": "2026-10-31",
        "valid_to": None,
        "tags": ["world-bank", "reference-table", "country-codes", "income-group"],
        "use_cases": ["customer-segmentation", "market-sizing", "address-generation"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"rows": rows},
            "vectors": [
                {"input": {"key": "IND", "column": "income_group"}, "expected": rows["IND"]["income_group"], "origin": "source"},
                {"input": {"key": "GBR", "column": "region"}, "expected": rows["GBR"]["region"], "origin": "source"},
                {"input": {"key": "BRA", "column": "iso2"}, "expected": "BR", "origin": "source"},
                {"input": "WLD", "expected": False, "origin": "derived", "note": "aggregates are excluded"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, "World Bank country API", COUNTRIES_URL, 'country[id=IND].incomeLevel.value', rows["IND"]["income_group"], "text", '"id":"IND"', LICENSE, countries_raw),
            evidence(PUBLISHER, "World Bank country API", COUNTRIES_URL, 'country[id=GBR].region.value', rows["GBR"]["region"], "text", '"id":"GBR"', LICENSE, countries_raw),
            evidence(PUBLISHER, "World Bank Data Catalog public licenses", LICENSE_URL, "Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
        ],
        "notes": (
            "Every economy in the World Bank country API with its ISO alpha-3 and alpha-2 codes, region, income group "
            "and capital, aggregates removed. valid_from is the access date because the classification is revised each "
            "July; the content hash changes when it does. The World Bank licenses its datasets under CC BY 4.0."
        ),
    }


def main() -> int:
    countries_raw = fetch(COUNTRIES_URL)
    license_raw = fetch(LICENSE_URL)
    countries = economies(countries_raw)
    write(build_classification(countries_raw, license_raw))
    for indicator, year, entry_id, variable, unit, tags, use_cases in INDICATORS:
        data_raw = fetch(f"{API}/country/all/indicator/{indicator}?date={year}&format=json&per_page=400")
        meta_raw = fetch(f"{API}/indicator/{indicator}?format=json")
        write(build(indicator, year, entry_id, variable, unit, tags, use_cases, data_raw, meta_raw, countries, countries_raw, license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())

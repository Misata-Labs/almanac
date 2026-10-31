"""Regenerate the world population by economy entry from the World Bank API.

Run from the repository root:

    uv run python tools/build_world_population.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

YEAR = 2024
DATA_URL = f"https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?date={YEAR}&format=json&per_page=400"
COUNTRIES_URL = "https://api.worldbank.org/v2/country?format=json&per_page=400"
LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
PUBLISHER = "World Bank"
LICENSE = "CC-BY-4.0"


def build(data_raw: bytes, countries_raw: bytes, license_raw: bytes) -> dict:
    meta, rows = json.loads(data_raw)
    countries = {c["id"]: c for c in json.loads(countries_raw)[1]}
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for row in rows:
        code = row["countryiso3code"]
        country = countries.get(code)
        if not country or country["region"]["value"] == "Aggregates" or row["value"] is None:
            continue
        counts[code] = int(row["value"])
        names[code] = row["country"]["value"]
    counts = dict(sorted(counts.items()))
    total = sum(counts.values())
    shares = {code: round(v / total, 8) for code, v in counts.items()}
    largest = max(shares, key=shares.get)
    india = rows and next(r for r in rows if r["countryiso3code"] == "IND")
    return {
        "id": f"global-population-by-economy-{YEAR}",
        "title": f"World population by economy, {YEAR} (World Bank, {len(counts)} economies)",
        "kind": "marginal",
        "domain": "demographics",
        "region": "global",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "spec": {
            "variable": "economy_iso3",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "names": names, "total": total}},
        },
        "evidence": [
            evidence(PUBLISHER, f"World Development Indicators API, SP.POP.TOTL (Population, total), {YEAR}", DATA_URL, 'rows[countryiso3code=IND].value', india["value"], "count", '"countryiso3code":"IND"', LICENSE, data_raw),
            evidence(PUBLISHER, f"World Development Indicators API, SP.POP.TOTL (Population, total), {YEAR}", DATA_URL, "lastupdated", meta["lastupdated"], "date", '"lastupdated":', LICENSE, data_raw),
            evidence(PUBLISHER, "World Bank country API (region classification used to exclude aggregates)", COUNTRIES_URL, 'country[id=IND].region.value', "South Asia", "text", '"id":"IND"', LICENSE, countries_raw),
            evidence(PUBLISHER, "World Bank Data Catalog public licenses", LICENSE_URL, "Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "population / sum over economies that are not aggregates",
                "method": "derived",
                "rationale": "The indicator response mixes economies and regional or income aggregates; rows whose region is 'Aggregates' in the country API, and rows without a value, are dropped before shares are computed.",
            }
        ],
        "tests": [
            {"statistic": f"share[{largest}]", "expected": shares[largest], "tolerance": 0.002},
            {"statistic": "share[IND]", "expected": shares["IND"], "tolerance": 0.002},
            {"statistic": "share[GBR]", "expected": shares["GBR"], "tolerance": 0.001},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-6},
        ],
        "notes": (
            f"Population of every World Bank economy for {YEAR} from the World Development Indicators API "
            f"(indicator SP.POP.TOTL, data last updated {meta['lastupdated']}), with regional and income aggregates "
            "removed using the region classification of the country API. Shares are the derived population weights; "
            "counts and names are kept beside them. The World Bank licenses its datasets under CC BY 4.0."
        ),
    }


def main() -> int:
    write(build(fetch(DATA_URL), fetch(COUNTRIES_URL), fetch(LICENSE_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Regenerate the England and Wales Census 2021 distribution entries from the ONS API.

Each table below becomes one marginal entry: counts come from the census
observations endpoint at country level, England and Wales are summed, and
shares are derived from the counts. Run from the repository root:

    uv run python tools/build_gb_census_2021.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://api.beta.ons.gov.uk/v1"
LICENSE_URL = f"{API}/datasets/mid-year-pop-est"
CENSUS_DAY = date(2021, 3, 21)
PUBLISHER = "Office for National Statistics"
LICENSE = "OGL-UK-3.0"

# (entry id suffix, population type, dimension id, variable, title fragment, metadata dataset id or None)
TABLES = [
    ("sex", "UR", "sex", "sex", "usual residents by sex", "TS008"),
    ("age", "UR", "resident_age_101a", "age", "usual residents by single year of age", "TS007"),
    ("ethnic-group", "UR", "ethnic_group_tb_20b", "ethnic_group", "usual residents by ethnic group (20 categories)", "TS021"),
    ("religion", "UR", "religion_tb", "religion", "usual residents by religion", "TS030"),
    ("marital-status", "UR", "legal_partnership_status", "legal_partnership_status", "usual residents aged 16 and over by marital and civil partnership status", "TS002"),
    ("economic-activity", "UR", "economic_activity_status_12a", "economic_activity_status", "usual residents aged 16 and over by economic activity status (12 categories)", "TS066"),
    ("general-health", "UR", "health_in_general", "general_health", "usual residents by general health", "TS037"),
    ("highest-qualification", "UR", "highest_qualification", "highest_qualification", "usual residents aged 16 and over by highest level of qualification", "TS067"),
    ("household-size", "HH", "hh_size_9a", "household_size", "households by household size", "TS017"),
    ("tenure", "HH", "hh_tenure_9a", "tenure", "households by tenure", "TS054"),
    ("car-availability", "HH", "number_of_cars_6a", "car_or_van_availability", "households by car or van availability", "TS045"),
    ("accommodation-type", "HH", "accommodation_type", "accommodation_type", "households by accommodation type", "TS044"),
]


def observations_url(population_type: str, dimension: str) -> str:
    return f"{API}/population-types/{population_type}/census-observations?area-type=ctry&dimensions={dimension}"


def totals(raw: bytes, dimension_id: str) -> tuple[dict[str, int], dict[str, str]]:
    """Sum observations over countries; returns label-keyed counts and label-to-option-id map."""
    counts: dict[str, int] = {}
    ids: dict[str, str] = {}
    for obs in json.loads(raw)["observations"]:
        option = next(d for d in obs["dimensions"] if d["dimension_id"] == dimension_id)
        counts[option["option"]] = counts.get(option["option"], 0) + int(obs["observation"])
        ids[option["option"]] = option["option_id"]
    return counts, ids


def first_england_observation(raw: bytes) -> tuple[str, int]:
    obs = json.loads(raw)["observations"]
    first = next(o for o in obs if o["dimensions"][0]["option"] == "England")
    return first["dimensions"][1]["option"], int(first["observation"])


def build(suffix: str, population_type: str, dimension: str, variable: str, title_fragment: str, dataset_id: str, raw: bytes, meta_raw: bytes, license_raw: bytes) -> dict:
    counts, ids = totals(raw, dimension)
    total = sum(counts.values())
    shares = {label: round(count / total, 6) for label, count in counts.items()}
    label, england_count = first_england_observation(raw)
    unit_label = "households" if population_type == "HH" else "usual residents"
    largest = max(shares, key=shares.get)
    smallest = min(shares, key=shares.get)
    meta = json.loads(meta_raw)
    tolerance = 0.005 if len(shares) <= 2 else 0.002
    return {
        "id": f"gb-census-2021-{suffix}",
        "title": f"England and Wales {title_fragment}, Census 2021",
        "kind": "marginal",
        "domain": "demographics",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": CENSUS_DAY.isoformat(), "end": CENSUS_DAY.isoformat()},
        "spec": {
            "variable": variable,
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {"shares": shares, "counts": counts, "total": total, "option_ids": ids},
            },
        },
        "evidence": [
            evidence(PUBLISHER, f"Census 2021 observations: {unit_label} by {dimension}, by country (ONS API)", observations_url(population_type, dimension), f'observations[ctry=England, {dimension}="{label}"].observation', england_count, "count", f'"option":"{label}","option_id":"{ids[label]}"}}],"observation":', LICENSE, raw),
            evidence(PUBLISHER, f"ONS dataset metadata {dataset_id} ({meta.get('title')})", f"{API}/datasets/{dataset_id}", "description", "The estimates are as at Census Day, 21 March 2021.", "text", "Census Day, 21 March 2021", LICENSE, meta_raw),
            evidence(PUBLISHER, "ONS dataset metadata, Population Estimates (licence statement)", LICENSE_URL, "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "count / total over England and Wales",
                "method": "derived",
                "rationale": "The API publishes counts per country; England and Wales are summed and each share is the summed count divided by the total. Any 'Does not apply' category is kept so shares describe the full population base.",
            }
        ],
        "tests": [
            {"statistic": f'share["{largest}"]', "expected": shares[largest], "tolerance": tolerance},
            {"statistic": f'share["{smallest}"]', "expected": shares[smallest], "tolerance": tolerance},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            f"Census 2021 {unit_label} of England and Wales by {variable.replace('_', ' ')} from the ONS census "
            f"observations API (population type {population_type}, dimension {dimension}, area type country), summed over "
            "England and Wales. Category labels are the ONS labels and option_ids keep the ONS codes. Counts sit beside the "
            "shares so they can be re-derived. Reference date is Census Day, 21 March 2021. ONS publishes its datasets "
            "under the Open Government Licence v3.0, as the licence field of its dataset metadata states; the census "
            "observations endpoint itself carries no licence field."
        ),
    }


def main() -> int:
    license_raw = fetch(LICENSE_URL)
    for suffix, population_type, dimension, variable, title_fragment, dataset_id in TABLES:
        raw = fetch(observations_url(population_type, dimension))
        meta_raw = fetch(f"{API}/datasets/{dataset_id}")
        write(build(suffix, population_type, dimension, variable, title_fragment, dataset_id, raw, meta_raw, license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())

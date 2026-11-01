"""Regenerate the second set of England and Wales Census 2021 marginal entries from the ONS API.

Each table becomes one marginal entry: counts come from the census
observations endpoint at country level, England and Wales are summed, and
shares are derived from the counts. The tables extend the first set (sex,
age, ethnic group and so on) with country of birth, industry, occupation,
hours worked, disability, unpaid care, detailed economic activity, household
composition, dwelling type and health deprivation. Run from the repository
root:

    uv run python tools/build_gb_census_extended.py
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

# (entry id suffix, population type, dimension id, variable, title fragment, metadata dataset id, tags, use cases)
TABLES = [
    ("country-of-birth", "UR", "country_of_birth_60a", "country_of_birth", "usual residents by country of birth (60 categories)", "TS004", ["census", "country-of-birth", "migration", "population"], ["person-generation", "customer-segmentation", "kyc-onboarding"]),
    ("industry", "UR", "industry_current_88a", "industry", "usual residents aged 16 and over in employment by industry (88 SIC 2007 divisions)", "TS060", ["census", "industry", "sic-2007", "employment"], ["person-generation", "hr-analytics", "workforce-planning", "customer-segmentation"]),
    ("occupation", "UR", "occupation_current_105a", "occupation", "usual residents aged 16 and over in employment by occupation (105 SOC 2020 minor groups)", "TS063", ["census", "occupation", "soc-2020", "employment"], ["person-generation", "hr-analytics", "workforce-planning", "credit-risk"]),
    ("hours-worked", "UR", "hours_per_week_worked", "hours_worked", "usual residents aged 16 and over in employment by hours worked per week", "TS059", ["census", "hours-worked", "employment", "part-time"], ["person-generation", "hr-analytics", "workforce-planning", "payroll-demo"]),
    ("disability", "UR", "disability", "disability", "usual residents by disability under the Equality Act", "TS038", ["census", "disability", "health", "population"], ["person-generation", "health-demo", "insurance", "claims-generation"]),
    ("unpaid-care", "UR", "is_carer", "unpaid_care", "usual residents aged 5 and over by provision of unpaid care", "TS039", ["census", "unpaid-care", "carers", "health"], ["person-generation", "health-demo", "household-generation"]),
    ("economic-activity-detailed", "UR", "activity_last_week", "economic_activity_last_week", "usual residents aged 16 and over by economic activity status in the week before the census (16 categories)", "TS066", ["census", "economic-activity", "employment", "students"], ["person-generation", "hr-analytics", "credit-risk"]),
    ("household-composition", "HH", "hh_family_composition_37a", "household_composition", "households by household composition (37 categories)", "TS003", ["census", "households", "household-composition", "families"], ["household-generation", "person-generation", "customer-segmentation", "insurance"]),
    ("dwelling-type", "HH", "accom_by_dwelling_type", "dwelling_type", "households by accommodation and dwelling type (shared or unshared)", "TS044", ["census", "households", "housing", "dwelling-type"], ["household-generation", "property-demo", "insurance", "utilities-demo"]),
    ("health-deprivation", "HH", "hh_deprivation_health", "health_deprivation", "households by deprivation in the health and disability dimension", "TS011", ["census", "households", "deprivation", "health"], ["household-generation", "health-demo", "insurance", "customer-segmentation"]),
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


def quoted(label: str) -> str:
    """A statistic argument, double-quoted when the label holds a comma or bracket."""
    return f'"{label}"' if any(c in label for c in ",[]") else label


def build(suffix: str, population_type: str, dimension: str, variable: str, title_fragment: str, dataset_id: str, tags: list[str], use_cases: list[str], raw: bytes, meta_raw: bytes, license_raw: bytes) -> dict:
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
        "tags": tags,
        "use_cases": use_cases,
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
            {"statistic": f"share[{quoted(largest)}]", "expected": shares[largest], "tolerance": tolerance},
            {"statistic": f"share[{quoted(smallest)}]", "expected": shares[smallest], "tolerance": tolerance},
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
    for suffix, population_type, dimension, variable, title_fragment, dataset_id, tags, use_cases in TABLES:
        raw = fetch(observations_url(population_type, dimension))
        meta_raw = fetch(f"{API}/datasets/{dataset_id}")
        write(build(suffix, population_type, dimension, variable, title_fragment, dataset_id, tags, use_cases, raw, meta_raw, license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())

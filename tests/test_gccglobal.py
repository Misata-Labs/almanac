"""Tests for the per-country GCC migration, population, labour, remittance and health entries and the builder's helpers.

The entry checks read the committed YAML, so they test the published figures
the builder copied rather than a restatement of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRIES = REPO_ROOT / "entries"
COUNTRIES = ("SA", "AE", "QA", "KW", "BH", "OM")

sys.path.insert(0, str(REPO_ROOT / "tools"))
from build_gcc_global import OTHER, band_label, top_with_remainder


def entry(domain: str, region: str, entry_id: str) -> dict:
    return yaml.safe_load((ENTRIES / domain / region / f"{entry_id}.yaml").read_text(encoding="utf-8"))


def per_country(domain: str, pattern: str) -> dict[str, dict]:
    """The entry matching ``pattern`` (with {cc} for the lower-case country code) for each GCC state."""
    found = {}
    for region in COUNTRIES:
        matches = sorted((ENTRIES / domain / region).glob(pattern.format(cc=region.lower()) + ".yaml"))
        assert len(matches) == 1, (region, pattern, matches)
        found[region] = yaml.safe_load(matches[0].read_text(encoding="utf-8"))
    return found


ORIGINS = per_country("demographics", "{cc}-migrant-stock-by-country-of-origin-and-sex-2024")
STOCKS = per_country("demographics", "{cc}-international-migrant-stock-and-share-1990-2024")
MIGRANT_AGES = per_country("demographics", "{cc}-migrant-stock-by-age-and-sex-2020")
POPULATION = per_country("demographics", "{cc}-population-by-age-and-sex-2025")
PROJECTIONS = per_country("demographics", "{cc}-population-projections-2025-2050")
REMITTANCES = per_country("payments", "{cc}-remittance-outflows-and-sending-cost-*")
ACTIVITY = per_country("employment", "{cc}-employment-by-economic-activity-and-sex-2024")
HEALTH = per_country("healthcare", "{cc}-adult-obesity-overweight-and-diabetes-by-sex-*")
COUNTRY_CONDITIONALS = {"origin": ORIGINS, "migrant-age": MIGRANT_AGES, "population": POPULATION, "activity": ACTIVITY}
SINGLE_CONDITIONALS = [
    ("employment", "QA", "qa-employment-by-activity-and-citizenship-2024"),
    ("employment", "QA", "qa-employment-by-skill-level-and-citizenship-2024"),
    ("employment", "QA", "qa-employment-by-age-and-citizenship-2024"),
    ("demographics", "OM", "om-foreign-citizens-by-country-of-citizenship-2024"),
]


def counts_of(parameters: dict) -> dict[str, float]:
    return parameters.get("counts") or parameters["thousand_persons"]


def assert_shares_match_counts(distributions: dict[str, dict]) -> None:
    for given, distribution in distributions.items():
        parameters = distribution["parameters"]
        counts = counts_of(parameters)
        total = sum(counts.values())
        assert set(counts) == set(parameters["shares"]), given
        for category, share in parameters["shares"].items():
            assert share == pytest.approx(counts[category] / total, abs=1e-6), (given, category)


def test_top_with_remainder_keeps_largest_and_pools_the_rest() -> None:
    kept = top_with_remainder({"A": 5, "B": 30, "C": 10, "D": 1}, 50, 2)
    assert list(kept) == ["B", "C", OTHER]
    assert kept[OTHER] == 10


def test_top_with_remainder_omits_an_empty_remainder() -> None:
    assert top_with_remainder({"A": 2, "B": 3}, 5, 5) == {"B": 3, "A": 2}


@pytest.mark.parametrize(("band", "label"), [("0004", "0-4"), ("2529", "25-29"), ("80UP", "80+")])
def test_band_label(band: str, label: str) -> None:
    assert band_label(band) == label


@pytest.mark.parametrize("family", sorted(COUNTRY_CONDITIONALS))
@pytest.mark.parametrize("region", COUNTRIES)
def test_country_shares_reproduce_published_counts(family: str, region: str) -> None:
    assert_shares_match_counts(COUNTRY_CONDITIONALS[family][region]["spec"]["distributions"])


@pytest.mark.parametrize(("domain", "region", "entry_id"), SINGLE_CONDITIONALS)
def test_citizenship_shares_reproduce_published_counts(domain: str, region: str, entry_id: str) -> None:
    assert_shares_match_counts(entry(domain, region, entry_id)["spec"]["distributions"])


@pytest.mark.parametrize("region", COUNTRIES)
def test_entries_are_filed_under_their_own_country(region: str) -> None:
    for family in (ORIGINS, STOCKS, MIGRANT_AGES, POPULATION, PROJECTIONS, REMITTANCES, ACTIVITY, HEALTH):
        data = family[region]
        assert data["region"] == region
        assert data["id"].startswith(f"{region.lower()}-")


@pytest.mark.parametrize("region", COUNTRIES)
def test_origin_remainder_closes_to_the_destination_total(region: str) -> None:
    distributions = ORIGINS[region]["spec"]["distributions"]
    assert set(distributions) == {"total", "male", "female"}
    for sex, distribution in distributions.items():
        parameters = distribution["parameters"]
        assert sum(parameters["counts"].values()) == parameters["total_migrants"], sex
        assert len([k for k in parameters["counts"] if k != OTHER]) <= 30, sex
        for code in parameters["counts"]:
            assert code == OTHER or (len(code) == 3 and code.isupper()), code


@pytest.mark.parametrize("region", COUNTRIES)
def test_sex_specific_migrant_totals_add_to_both_sexes(region: str) -> None:
    totals = {sex: d["parameters"]["total_migrants"] for sex, d in ORIGINS[region]["spec"]["distributions"].items()}
    assert totals["male"] + totals["female"] == pytest.approx(totals["total"], rel=1e-3)


@pytest.mark.parametrize("region", COUNTRIES)
def test_stock_series_matches_origin_total(region: str) -> None:
    series = STOCKS[region]["spec"]["series"]
    latest = series[-1]
    assert latest["period"] == "2024"
    assert latest["migrant_stock"] == ORIGINS[region]["spec"]["distributions"]["total"]["parameters"]["total_migrants"]
    assert all(0 < point["value"] < 100 for point in series)


@pytest.mark.parametrize("region", COUNTRIES)
def test_migrant_age_groups_close_to_published_totals(region: str) -> None:
    for sex, distribution in MIGRANT_AGES[region]["spec"]["distributions"].items():
        parameters = distribution["parameters"]
        assert len(parameters["shares"]) == 16, sex
        assert sum(parameters["counts"].values()) == pytest.approx(parameters["total_migrants"], rel=0.01), sex


@pytest.mark.parametrize("region", COUNTRIES)
def test_population_age_groups_run_from_zero_to_eighty_plus(region: str) -> None:
    for distribution in POPULATION[region]["spec"]["distributions"].values():
        bands = list(distribution["parameters"]["shares"])
        assert bands[0] == "0-4" and bands[-1] == "80+" and len(bands) == 17


@pytest.mark.parametrize("region", COUNTRIES)
def test_projection_sexes_add_to_total(region: str) -> None:
    rows = PROJECTIONS[region]["spec"]["parameters"]["rows"]
    assert list(rows) == [str(year) for year in range(2025, 2051)]
    for year, row in rows.items():
        assert row["male"] + row["female"] == pytest.approx(row["total"], rel=1e-3), year


@pytest.mark.parametrize("region", COUNTRIES)
def test_remittance_rows_are_years_with_at_least_one_value(region: str) -> None:
    for year, row in REMITTANCES[region]["spec"]["parameters"]["rows"].items():
        assert year.isdigit() and len(year) == 4
        assert row["personal_remittances_paid_usd"] is not None or row["sending_cost_percent"] is not None, year


@pytest.mark.parametrize("region", COUNTRIES)
def test_who_estimates_sit_inside_their_uncertainty_intervals(region: str) -> None:
    for measure, row in HEALTH[region]["spec"]["parameters"]["rows"].items():
        for column, value in row.items():
            if column.endswith("_percent"):
                stem = column.removesuffix("_percent")
                assert row[f"{stem}_low"] <= value <= row[f"{stem}_high"], (measure, column)

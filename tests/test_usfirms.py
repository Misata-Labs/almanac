"""Tests for the US Census firm-distribution entries and the parsing helpers of their builder.

The entry checks read the committed YAML, so they test the published figures the builder copied:
shares agree with the counts they come from, mutually exclusive classes add up to the published
totals where the source publishes counts without noise, and derived per-employee figures follow
from the published cells.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRIES = REPO_ROOT / "entries" / "business" / "US"

sys.path.insert(0, str(REPO_ROOT / "tools"))
from build_us_firms import cbp_sector, number, per_unit, shares, strip_code

PREFIXES = ("us-susb-", "us-bds-", "us-cbp-", "us-bfs-", "us-abs-")
ENTRY_PATHS = sorted(
    path
    for path in ENTRIES.glob("*.yaml")
    if path.name.startswith(PREFIXES) or "leverage-and-return-ratios" in path.name
)


def load(entry_id: str) -> dict:
    return yaml.safe_load((ENTRIES / f"{entry_id}.yaml").read_text(encoding="utf-8"))


def slices(data: dict) -> dict[str, dict]:
    """Parameters of every categorical distribution in a marginal or conditional entry."""
    spec = data["spec"]
    if data["kind"] == "conditional":
        return {key: dist["parameters"] for key, dist in spec["distributions"].items()}
    if data["kind"] == "marginal":
        return {"": spec["distribution"]["parameters"]}
    return {}


# ----------------------------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("02: <5", "<5"),
        ("04:10-14", "10-14"),
        ("7: 100-499 employees", "100-499"),
        ("11: 20,000+ employees", "20,000+"),
        ("a) 0", "0"),
        ("l) Left Censored", "Left Censored"),
        ("2: Corporation", "Corporation"),
    ],
)
def test_strip_code_drops_ordering_prefix_and_unit(label: str, expected: str) -> None:
    assert strip_code(label) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("13.2 ", 13.2), ("6395635", 6395635), (42, 42), ("X", None), ("D", None), ("N", None), ("S", None), ("", None), (None, None), ("-0.550", -0.55)],
)
def test_number_reads_figures_and_rejects_suppression_codes(text: object, expected: object) -> None:
    assert number(text) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [("------", "all"), ("31----", "31-33"), ("44----", "44-45"), ("48----", "48-49"), ("54----", "54"), ("541---", None), ("5411--", None)],
)
def test_cbp_sector_keys_follow_susb(code: str, expected: str | None) -> None:
    assert cbp_sector(code) == expected


def test_shares_skip_missing_and_zero_counts() -> None:
    assert shares({"a": 1, "b": 3, "c": None, "d": 0}) == {"a": 0.25, "b": 0.75}


def test_per_unit_handles_missing_and_zero_denominators() -> None:
    assert per_unit(1234, 10, 1000) == 123400
    assert per_unit(None, 10) is None
    assert per_unit(5, 0) is None
    assert per_unit(7, 3, digits=2) == 2.33


# ----------------------------------------------------------------------------------------------
# Committed entries
# ----------------------------------------------------------------------------------------------


def test_expected_entries_are_present() -> None:
    assert len(ENTRY_PATHS) >= 18


@pytest.mark.parametrize("path", ENTRY_PATHS, ids=lambda p: p.stem)
def test_entry_shape(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["id"] == path.stem
    assert len(data["title"]) <= 140
    assert {"firms", "business", "census"} <= set(data["tags"])
    assert {"pe-portfolio-demo", "deal-sourcing-demo", "synthetic-companies", "valuation-demo", "kyb-onboarding"} <= set(data["use_cases"])
    assert path.stat().st_size < 400_000
    assert all(item["source_license"] == "unstated" for item in data["evidence"])
    assert data["status"] == "license-review"


@pytest.mark.parametrize("path", ENTRY_PATHS, ids=lambda p: p.stem)
def test_categorical_shares_add_to_one(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tolerance = 0.002 if data["id"].startswith("us-abs-") else 0.0001
    for key, params in slices(data).items():
        assert sum(params["shares"].values()) == pytest.approx(1, abs=tolerance), key


@pytest.mark.parametrize(
    ("entry_id", "count_key"),
    [
        ("us-susb-firms-by-employment-size-2022", "firms"),
        ("us-susb-employment-size-by-sector-2022", "firms"),
        ("us-susb-employment-size-by-state-2022", "firms"),
        ("us-susb-employment-size-by-legal-form-2022", "firms"),
        ("us-susb-legal-form-by-sector-2022", "firms"),
        ("us-susb-receipts-size-by-sector-2022", "firms"),
        ("us-cbp-establishment-size-by-sector-2023", "establishments"),
        ("us-cbp-establishment-size-by-state-2023", "establishments"),
        ("us-bds-firms-by-firm-age-2023", "firms"),
        ("us-bds-firms-by-firm-size-2023", "firms"),
    ],
)
def test_shares_follow_counts(entry_id: str, count_key: str) -> None:
    for key, params in slices(load(entry_id)).items():
        counts = {k: params[count_key][k] for k in params["shares"]}
        total = sum(counts.values())
        for category, share in params["shares"].items():
            assert share == pytest.approx(counts[category] / total, abs=1e-6), (key, category)


@pytest.mark.parametrize(
    "entry_id",
    ["us-susb-firms-by-employment-size-2022", "us-susb-employment-size-by-sector-2022", "us-susb-employment-size-by-state-2022", "us-susb-employment-size-by-legal-form-2022"],
)
def test_susb_firm_counts_of_exclusive_classes_add_to_total(entry_id: str) -> None:
    for key, params in slices(load(entry_id)).items():
        assert sum(params["firms"][c] for c in params["shares"]) == params["firms"]["Total"], key


def lower_bound(band: str) -> int:
    """Lower bound of a published receipts band in thousands of dollars ('<100' starts at zero)."""
    return 0 if band.startswith("<") else int(band.replace(",", "").split("-")[0].rstrip("+"))


def test_susb_receipts_bands_add_to_total_for_all_sectors() -> None:
    params = slices(load("us-susb-receipts-size-by-sector-2022"))["all"]
    assert sum(params["firms"][c] for c in params["shares"]) == params["firms"]["Total"]
    below = sum(params["firms"][c] for c in params["shares"] if lower_bound(c) < 100_000)
    assert below + params["firms"]["100,000+"] == params["firms"]["Total"]


@pytest.mark.parametrize("entry_id", ["us-susb-employment-size-by-sector-2022", "us-susb-receipts-size-by-sector-2022", "us-susb-employment-size-by-state-2022"])
def test_susb_per_employee_figures_follow_published_cells(entry_id: str) -> None:
    for key, params in slices(load(entry_id)).items():
        for category, employment in params["employment"].items():
            receipts = params["receipts_usd_thousands"][category]
            payroll = params["annual_payroll_usd_thousands"][category]
            assert params["receipts_per_employee_usd"][category] == per_unit(receipts, employment, 1000), (key, category)
            assert params["annual_payroll_per_employee_usd"][category] == per_unit(payroll, employment, 1000), (key, category)


def test_susb_industry_totals_receipts_per_establishment() -> None:
    rows = load("us-susb-industry-totals-by-naics-3-digit-2022")["spec"]["parameters"]["rows"]
    for code, row in rows.items():
        assert row["receipts_per_establishment_usd"] == per_unit(row["receipts_usd_thousands"], row["establishments"], 1000), code
        assert row["level"] == ("subsector" if len(code) == 3 else "sector")


def test_cbp_published_classes_do_not_exceed_totals() -> None:
    for key, params in slices(load("us-cbp-establishment-size-by-sector-2023")).items():
        published = sum(v for k, v in params["establishments"].items() if k != "Total" and v is not None)
        assert published <= params["establishments"]["Total"], key
    rows = load("us-cbp-establishment-size-by-state-and-sector-2023")["spec"]["parameters"]["rows"]
    for key, row in rows.items():
        published = sum(v for k, v in row.items() if k.startswith("establishments_") and v is not None)
        assert published <= row["establishments"], key


@pytest.mark.parametrize("entry_id", ["us-bfs-business-applications-by-state-2025", "us-bfs-business-applications-by-sector-2025"])
def test_bfs_annual_totals_add_monthly_figures(entry_id: str) -> None:
    params = slices(load(entry_id))[""]
    for name in ("business_applications", "high_propensity_applications", "applications_with_planned_wages"):
        for key, months in params[f"{name}_monthly"].items():
            assert len(months) == 12
            assert sum(months.values()) == params[name][key], (name, key)
    for key, value in params["applications_with_planned_wages"].items():
        assert value <= params["high_propensity_applications"][key] <= params["business_applications"][key], key


def test_bds_series_is_annual_and_unbroken() -> None:
    series = load("us-bds-business-dynamics-1978-2023")["spec"]["series"]
    years = [int(point["period"]) for point in series]
    assert years == list(range(years[0], years[-1] + 1))


def test_bds_age_by_size_slices_add_to_size_marginal() -> None:
    """Each size slice adds to the size marginal, short only of the cells BDS withholds (D) for disclosure."""
    by_size = slices(load("us-bds-firms-by-firm-size-2023"))[""]
    for size, params in slices(load("us-bds-firm-age-by-firm-size-2023")).items():
        published = sum(v for v in params["firms"].values() if v is not None)
        assert 0 <= by_size["firms"][size] - published <= max(10, 0.001 * by_size["firms"][size]), size


@pytest.mark.parametrize(
    "entry_id",
    ["us-qfr-manufacturing-leverage-and-return-ratios-by-industry-2026q2", "us-qfr-manufacturing-leverage-and-return-ratios-by-asset-size-2026q2", "us-qfr-nonmanufacturing-leverage-and-return-ratios-by-industry-2026q2"],
)
def test_qfr_rows_carry_five_quarters_of_core_ratios(entry_id: str) -> None:
    quarters = ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    for key, row in load(entry_id)["spec"]["parameters"]["rows"].items():
        for name in ("return_on_equity_after_tax_percent", "return_on_assets_after_tax_percent", "total_liabilities_to_equity", "interest_coverage"):
            assert all(f"{name}_{q}" in row for q in quarters), (key, name)
        if "stockholders_equity_percent_of_assets_2026Q2" in row:
            total = row["total_liabilities_percent_of_assets_2026Q2"] + row["stockholders_equity_percent_of_assets_2026Q2"]
            assert total == pytest.approx(100, abs=0.02), key

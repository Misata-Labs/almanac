"""Tests for the business population entries and the helpers of tools/build_biz_population.py.

The entry checks read the committed YAML, so they test the published figures the
builder copied and the ratios it derived from them rather than a restatement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRIES = REPO_ROOT / "entries" / "business"

sys.path.insert(0, str(REPO_ROOT / "tools"))
from build_ae_stats import Sheet
from build_biz_population import abs_key, band_slug, bpe_band, bpe_blocks, number, ratio, shares, without_notes

SBS_COUNTRIES = ("EU", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE")


def entry(region: str, entry_id: str) -> dict:
    return yaml.safe_load((ENTRIES / region / f"{entry_id}.yaml").read_text(encoding="utf-8"))


def rows_of(data: dict) -> dict[str, dict]:
    return data["spec"]["parameters"]["rows"]


def close(actual: float | None, expected: float | None, tolerance: float = 1e-6) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return abs(actual - expected) <= tolerance


# --- helpers ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("5690265", 5690265), ("9.6999999999999993", 9.7), ("0", 0), (" [x]", None), ("[c]", None), ("", None), (None, None), ("1,234", 1234), ("-583", -583)],
)
def test_number_reads_published_cells(text, expected):
    value = number(text)
    assert value == expected
    assert type(value) is type(expected)


def test_ratio_and_shares():
    assert ratio(None, 5) is None
    assert ratio(5, 0) is None
    assert ratio(1, 3, 100, 2) == 33.33
    split = shares({"a": 1, "b": 3})
    assert split == {"a": 0.25, "b": 0.75}


def test_labels_are_normalised():
    assert without_notes("With no employees (registered) [Note 2] [Note 5]") == "With no employees (registered)"
    assert bpe_band("   10 to 19") == "10-19"
    assert bpe_band("All businesses") == "all"
    assert bpe_band("1000 or more") == "1000+"
    assert bpe_band("Employee size band") is None
    assert abs_key("Non–employing") == "Non-employing"
    assert band_slug("250+") == "250_plus"
    assert band_slug("10000-49999") == "10000_49999"


def test_bpe_blocks_split_sections_and_combined_letters():
    cells = {}
    layout = [
        ["Employee size band", "Business number", "Employment", "Turnover"],
        ["All Industries ", None, None, None],
        ["All businesses", "100", "5", "50"],
        ["1", "60", "1", "10"],
        ["B, D and E Mining and Quarrying; Electricity", None, None, None],
        ["All businesses", "40", "4", "40"],
        ["With no employees (registered) [Note 2]", "40", "4", "40"],
    ]
    for r, row in enumerate(layout, start=1):
        for c, value in enumerate(row, start=1):
            if value is not None:
                cells[(r, c)] = value
    blocks = bpe_blocks(Sheet(cells))
    assert list(blocks) == ["ALL", "B+D+E"]
    assert blocks["B+D+E"][0] == "Mining and Quarrying; Electricity"
    assert set(blocks["B+D+E"][1]) == {"all", "0-registered"}


# --- UK Business Population Estimates and ONS --------------------------------------------------------------------

BPE_CONDITIONALS = ("gb-business-population-size-band-by-industry-section-2025", "gb-business-population-size-band-by-region-2025")
ONS_CONDITIONALS = ("gb-enterprises-by-employment-size-band-and-sic-division-2026", "gb-enterprises-by-turnover-size-band-and-sic-division-2026")


@pytest.mark.parametrize("entry_id", BPE_CONDITIONALS)
def test_bpe_shares_follow_business_counts(entry_id):
    for given, distribution in entry("GB", entry_id)["spec"]["distributions"].items():
        parameters = distribution["parameters"]
        counts = parameters["businesses"]
        total = sum(counts.values())
        assert list(parameters["shares"]) == list(counts), given
        for band, share in parameters["shares"].items():
            assert close(share, counts[band] / total), (given, band)
        assert abs(total - parameters["all_businesses"]) <= 0.01 * parameters["all_businesses"], given
        for band, value in parameters["turnover_per_employment_gbp_thousand"].items():
            turnover, employment = parameters["turnover_gbp_million"][band], parameters["employment_thousands"][band]
            assert close(value, ratio(turnover, employment, 1, 3)), (given, band)


def test_bpe_size_band_table_derivations():
    rows = rows_of(entry("GB", "gb-business-population-by-size-band-2025"))
    bands = [k for k in rows if k not in ("all", "employers")]
    assert abs(sum(rows[b]["businesses"] for b in bands) - rows["all"]["businesses"]) <= 0.001 * rows["all"]["businesses"]
    for key, row in rows.items():
        assert close(row["turnover_per_employment_gbp_thousand"], round(row["turnover_gbp_million"] / row["employment_thousands"], 3)), key
        assert close(row["turnover_per_business_gbp_thousand"], round(row["turnover_gbp_million"] * 1000 / row["businesses"], 3)), key


def test_bpe_regions_cover_every_nation_and_region():
    distributions = entry("GB", "gb-business-population-size-band-by-region-2025")["spec"]["distributions"]
    assert {"United Kingdom", "England", "Wales", "Scotland", "Northern Ireland", "London"} <= set(distributions)
    assert len(distributions) == 14


@pytest.mark.parametrize("entry_id", ONS_CONDITIONALS)
def test_ons_division_shares_follow_counts(entry_id):
    distributions = entry("GB", entry_id)["spec"]["distributions"]
    assert len(distributions) > 70
    for given, distribution in distributions.items():
        parameters = distribution["parameters"]
        total = sum(parameters["enterprises"].values())
        assert total > 0, given
        for band, share in parameters["shares"].items():
            assert close(share, parameters["enterprises"][band] / total), (given, band)


def test_ons_region_table_is_internally_consistent():
    rows = rows_of(entry("GB", "gb-enterprises-and-local-units-by-region-size-and-legal-status-2026"))
    uk = rows["K02000001"]
    employment = sum(v for k, v in uk.items() if k.startswith("enterprises_employment_"))
    turnover = sum(v for k, v in uk.items() if k.startswith("enterprises_turnover_"))
    legal = sum(uk[f"enterprises_{status}"] for status in ("company", "sole_proprietor", "partnership", "public_corporation", "central_government", "local_authority", "non_profit_or_mutual"))
    for total in (employment, turnover, legal):
        assert abs(total - uk["enterprises"]) <= 50
    regions = [k for k in rows if k.startswith("E12")]
    assert len(regions) == 9
    assert abs(sum(rows[k]["enterprises"] for k in regions) - rows["E92000001"]["enterprises"]) <= 50
    assert close(uk["local_units_per_enterprise"], round(uk["local_units"] / uk["enterprises"], 4))


# --- Eurostat ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("region", SBS_COUNTRIES)
def test_size_class_accounts_derivations(region):
    data = entry(region, f"{region.lower()}-enterprise-accounts-by-nace-and-size-class-2024")
    rows = rows_of(data)
    assert "B-S_X_O_S94|TOTAL" in rows
    for key, row in rows.items():
        nace, size = key.split("|")
        assert size in data["spec"]["parameters"]["size_classes"], key
        assert close(row["net_turnover_per_enterprise_teur"], ratio(row["net_turnover_meur"], row["enterprises"], 1000, 3)), key
        assert close(row["net_turnover_per_person_employed_teur"], ratio(row["net_turnover_meur"], row["persons_employed"], 1000, 3)), key
        total = rows.get(f"{nace}|TOTAL")
        if total is not None:
            assert close(row["enterprise_share_of_activity"], ratio(row["enterprises"], total["enterprises"])), key


def test_size_classes_partition_the_business_economy():
    rows = rows_of(entry("DE", "de-enterprise-accounts-by-nace-and-size-class-2024"))
    classes = ("2-9", "10-19", "20-49", "50-249", "GE250")
    agg = "B-S_X_O_S94"
    parts = [rows[f"{agg}|{c}"]["enterprises"] for c in classes if f"{agg}|{c}" in rows]
    assert sum(parts) <= rows[f"{agg}|TOTAL"]["enterprises"]
    large = rows[f"{agg}|GE250"]
    assert large["net_turnover_per_enterprise_teur"] > rows[f"{agg}|10-19"]["net_turnover_per_enterprise_teur"]


def test_high_growth_rows_are_sections_only():
    rows = rows_of(entry("EU", "eu-high-growth-enterprises-by-nace-section-2024"))
    assert not any(k.endswith("|B-S_X_O_S94") for k in rows)
    assert {k.split("|")[0] for k in rows} == {"EU27_2020", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"}
    for key, row in rows.items():
        rate = row["high_growth_share_of_enterprises_10_plus_percent"]
        assert rate is None or 0 <= rate <= 100, key


def test_legal_form_shares():
    rows = rows_of(entry("EU", "eu-enterprise-demography-by-legal-form-2024"))
    for key, row in rows.items():
        geo = key.split("|")[0]
        assert close(row["share_of_active_enterprises"], ratio(row["active_enterprises"], rows[f"{geo}|TOTAL"]["active_enterprises"])), key
    for geo in ("DE", "FR", "IT"):
        parts = sum(rows[f"{geo}|{form}"]["active_enterprises"] for form in ("ENT_LL", "ENT_PA", "ENT_SOLE"))
        assert parts <= rows[f"{geo}|TOTAL"]["active_enterprises"]


def test_small_mid_cap_classes_partition_large_enterprises():
    rows = rows_of(entry("EU", "eu-enterprises-by-extended-size-class-including-small-mid-caps-2024"))
    for geo in ("DE", "ES", "PL"):
        classes = ("0-9", "10-19", "20-49", "50-249", "250-749", "GE750")
        assert abs(sum(rows[f"{geo}|{c}"]["enterprises"] for c in classes) - rows[f"{geo}|TOTAL"]["enterprises"]) <= 5


# --- OECD, World Bank and ABS --------------------------------------------------------------------------------------


def test_oecd_rows_use_one_year_per_economy():
    rows = rows_of(entry("global", "global-enterprises-and-employment-by-size-class-oecd-sdbs-2021-2024"))
    years: dict[str, set[int]] = {}
    for key, row in rows.items():
        years.setdefault(key.split("|")[0], set()).add(row["year"])
    assert all(len(found) == 1 for found in years.values())
    assert "USA" not in years
    assert all(f"{area}|_T" in rows for area in years)


@pytest.mark.parametrize("entry_id", ["global-enterprise-survey-finance-trade-and-ownership-by-economy", "global-enterprise-survey-firm-age-collateral-growth-and-experience-by-economy"])
def test_enterprise_survey_rows(entry_id):
    data = entry("global", entry_id)
    rows = rows_of(data)
    anchor = data["spec"]["parameters"]["indicators"][data["spec"]["parameters"]["anchor_indicator"]]
    assert len(rows) > 100
    for code, row in rows.items():
        assert len(code) == 3 and code.isupper()
        assert row[anchor] is not None
        assert 2006 <= row["survey_year"] <= 2025


@pytest.mark.parametrize(("entry_id", "total"), [("au-businesses-by-employment-size-entries-exits-and-survival-2025-26", "Total"), ("au-businesses-by-anzsic-division-entries-exits-and-survival-2025-26", "All Industries")])
def test_abs_flows_balance(entry_id, total):
    rows = rows_of(entry("AU", entry_id))
    assert total in rows
    for key, row in rows.items():
        assert row["entries_births"] + row["entries_other"] == row["entries_total"], key
        assert row["exits_cancellations"] + row["exits_other"] == row["exits_total"], key
        assert close(row["exit_rate_percent"], ratio(row["exits_total"], row["operating_at_start"], 100, 2)), key
    assert rows[total]["share_of_businesses_at_end"] == 1.0

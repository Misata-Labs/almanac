"""Tests for the Qatar, Kuwait, Bahrain and Oman statistics entries and their builders' parsing helpers.

The entry checks read the committed YAML, so they test the published figures the builders copied:
shares agree with counts, groups that the sources print as totals add up, and cross-table identities
the sources imply hold.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRIES = REPO_ROOT / "entries"

sys.path.insert(0, str(REPO_ROOT / "tools"))
from _gulf4 import categorical, csv_line, number, ods_export, ods_licence_query, share_tests, whole
from build_gulf4_kw import array_after, categories_after, chart_title, data_snippet
from build_gulf4_om import Bulletin

ENTRY_IDS = {
    "QA": [
        ("employment", "qa-labour-force-status-by-nationality-and-sex-2025"),
        ("employment", "qa-economically-active-by-occupation-nationality-and-sex-2025"),
        ("employment", "qa-paid-employment-and-average-wage-by-sector-and-sex-2023"),
        ("employment", "qa-economically-active-by-activity-and-sector-2024"),
        ("demographics", "qa-population-by-sex-and-age-group-2024"),
        ("economy", "qa-cpi-by-expenditure-group-monthly-2025"),
        ("tourism", "qa-hotel-guests-by-nationality-and-rating-2022"),
        ("automotive", "qa-registered-vehicles-by-licence-type-2022"),
        ("healthcare", "qa-registered-deaths-by-age-nationality-and-sex-2022"),
    ],
    "KW": [
        ("employment", "kw-workers-by-nationality-group-sector-and-sex-2026-03"),
        ("employment", "kw-workers-by-nationality-and-sex-2026-03"),
        ("employment", "kw-average-monthly-wage-by-nationality-sector-and-sex-2026-03"),
        ("employment", "kw-kuwaiti-government-workers-by-age-group-and-sex-2026-03"),
        ("payments", "kw-bank-cards-valid-and-issued-monthly-2026"),
    ],
    "BH": [
        ("demographics", "bh-population-by-nationality-sex-and-age-group-2025"),
        ("demographics", "bh-population-by-governorate-nationality-and-sex-2025"),
        ("economy", "bh-cpi-by-coicop-division-monthly-2025-10-2026-09"),
        ("employment", "bh-private-sector-workers-by-wage-band-nationality-and-sex-2023"),
        ("employment", "bh-private-sector-workers-by-activity-nationality-and-sex-2023"),
        ("automotive", "bh-vehicles-registered-in-use-by-type-2025"),
        ("tourism", "bh-inbound-visitors-by-region-of-residence-monthly-2025"),
        ("employment", "bh-lmra-active-expatriate-work-permits-quarterly-2021-2025"),
        ("healthcare", "bh-deaths-by-age-group-nationality-and-sex-2022"),
    ],
    "OM": [
        ("demographics", "om-registered-population-by-governorate-and-nationality-2026-09"),
        ("employment", "om-workers-by-sector-and-nationality-2026-09"),
        ("employment", "om-expatriate-workers-by-nationality-2026-09"),
        ("economy", "om-cpi-by-group-with-weights-2026-09"),
        ("tourism", "om-hotel-guests-by-nationality-jan-sep-2026"),
        ("automotive", "om-registered-vehicles-by-registration-type-2026-09"),
    ],
}
ALL = [(region, domain, entry_id) for region, items in ENTRY_IDS.items() for domain, entry_id in items]


def load(region: str, domain: str, entry_id: str) -> dict:
    return yaml.safe_load((ENTRIES / domain / region / f"{entry_id}.yaml").read_text(encoding="utf-8"))


def entry(entry_id: str) -> dict:
    region, domain, _ = next(item for item in ALL if item[2] == entry_id)
    return load(region, domain, entry_id)


def distributions(data: dict) -> dict[str, dict]:
    spec = data["spec"]
    return spec["distributions"] if data["kind"] == "conditional" else {"": spec["distribution"]}


# Helpers shared by the builders.


def test_categorical_keeps_counts_beside_shares():
    dist = categorical({"a": 3.0, "b": 1}, {"a": "أ", "c": "ج"})
    params = dist["parameters"]
    assert params["counts"] == {"a": 3, "b": 1} and isinstance(params["counts"]["a"], int)
    assert params["shares"] == {"a": 0.75, "b": 0.25}
    assert params["total"] == 4
    assert params["labels_ar"] == {"a": "أ"}
    with pytest.raises(ValueError):
        categorical({"a": 0})


def test_cell_parsing():
    assert number(" 1,234.5 ") == 1234.5
    assert number("") is None
    assert whole(12.0) == 12 and whole(1.5) == 1.5
    raw = "﻿year,sex,value\n2025,Male,10\n2025,Female,12\n".encode()
    assert csv_line(raw, ",Female,") == "2025,Female,12"
    with pytest.raises(LookupError):
        csv_line(raw, "Other")


def test_opendatasoft_export_is_pinned_and_ordered():
    url = ods_export("https://portal.example", "ds", select=["year", "sex"], where="year=date'2025'", order_by=["sex", "year"])
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.path == "/api/explore/v2.1/catalog/datasets/ds/exports/csv"
    assert query == {"delimiter": [","], "select": ["year,sex"], "where": ["year=date'2025'"], "order_by": ["sex,year"]}
    licence = parse_qs(urlsplit(ods_licence_query("https://portal.example", "ds")).query)
    assert licence["where"] == ['dataset_id="ds"'] and "modified" not in licence["select"][0]


def test_share_tests_name_the_conditioning_group():
    tests = share_tests({"Qatari|Males": categorical({"x": 2, "y": 1})}, 1)
    assert tests[0]["statistic"] == 'share["Qatari|Males","x"]'
    assert tests[-1]["statistic"] == 'sum_of_shares["Qatari|Males"]'


def test_lmis_chart_parsing():
    html = (
        "<h3>chart one heading</h3>"
        "text: 'chart one', categories: ['a','b',], series: [{ name: 'ذكور', data: [5,7,] },{ name: ' إناث ', data:[1,2,] }]"
        "text: 'chart two', categories: ['c',], series: [{ name: 'ذكور', data: [9,] }]"
    )
    assert chart_title(html, "one") == "chart one"
    assert categories_after(html, "chart two") == ["c"]
    assert array_after(html, "chart one", "ذكور") == [5, 7]
    assert array_after(html, "chart one", "إناث") == [1, 2]
    assert array_after(html, "chart two", "ذكور") == [9]
    assert data_snippet(html, [5, 7]) == "data: [5,7,]"


def test_bulletin_rows_read_numbers_after_a_label():
    bulletin = Bulletin.__new__(Bulletin)
    bulletin.pages = ["Item - Muscat 2.7 1,528,611 1,569,604 - Total -0.4 12 13.5"]
    cells, matched = bulletin.row(1, "Muscat", 3)
    assert cells == ["2.7", "1,528,611", "1,569,604"] and matched == "Muscat 2.7 1,528,611 1,569,604"
    assert bulletin.row(1, "Total", 3)[0] == ["-0.4", "12", "13.5"]
    with pytest.raises(LookupError):
        bulletin.row(1, "Dhofar", 2)


# Every entry.


@pytest.mark.parametrize(("region", "domain", "entry_id"), ALL, ids=[item[2] for item in ALL])
def test_entry_shape(region, domain, entry_id):
    data = load(region, domain, entry_id)
    assert data["id"] == entry_id and data["region"] == region and data["domain"] == domain
    assert len(data["title"]) < 140
    assert "gcc" in data["tags"]
    assert {"qatar": "QA", "kuwait": "KW", "bahrain": "BH", "oman": "OM"}[data["tags"][0]] == region
    expected_status = "verified" if region == "QA" else "license-review"
    assert data["status"] == expected_status
    for item in data["evidence"]:
        assert len(item["snippet"].split()) < 25


DISTRIBUTIONS = [item for item in ALL if load(*item)["kind"] in ("marginal", "conditional")]


@pytest.mark.parametrize(("region", "domain", "entry_id"), DISTRIBUTIONS, ids=[item[2] for item in DISTRIBUTIONS])
def test_shares_reproduce_counts(region, domain, entry_id):
    for given, dist in distributions(load(region, domain, entry_id)).items():
        params = dist["parameters"]
        total = sum(params["counts"].values())
        assert params["total"] == pytest.approx(total), given
        assert set(params["shares"]) == set(params["counts"]), given
        for category, count in params["counts"].items():
            assert params["shares"][category] == pytest.approx(count / total, abs=1e-8), (given, category)


# Cross-table identities.


def test_kuwait_age_report_matches_the_government_sector_chart():
    ages = entry("kw-kuwaiti-government-workers-by-age-group-and-sex-2026-03")["spec"]["distributions"]
    groups = entry("kw-workers-by-nationality-group-sector-and-sex-2026-03")["spec"]["distributions"]
    for sex in ("male", "female"):
        assert ages[sex]["parameters"]["total"] == groups[f"government|{sex}"]["parameters"]["counts"]["Kuwait"]


def test_kuwait_sector_counts_do_not_exceed_all_sectors():
    groups = entry("kw-workers-by-nationality-group-sector-and-sex-2026-03")["spec"]["distributions"]
    for sex in ("male", "female"):
        everyone = groups[f"all_sectors|{sex}"]["parameters"]["counts"]
        for group, count in everyone.items():
            government = groups[f"government|{sex}"]["parameters"]["counts"][group]
            private = groups[f"private|{sex}"]["parameters"]["counts"][group]
            assert government + private <= count, (sex, group)


def test_kuwait_top_nationalities_include_the_kuwaiti_count():
    top = entry("kw-workers-by-nationality-and-sex-2026-03")["spec"]["distributions"]
    groups = entry("kw-workers-by-nationality-group-sector-and-sex-2026-03")["spec"]["distributions"]
    for sex in ("male", "female"):
        assert top[sex]["parameters"]["counts"]["Kuwait"] == groups[f"all_sectors|{sex}"]["parameters"]["counts"]["Kuwait"]


def test_kuwait_wage_table_covers_both_sectors_and_groups():
    rows = entry("kw-average-monthly-wage-by-nationality-sector-and-sex-2026-03")["spec"]["parameters"]["rows"]
    assert set(rows) == {f"{s}|{n}|{x}" for s in ("government", "private") for n in ("kuwaiti", "non_kuwaiti") for x in ("male", "female")}
    assert all(r["average_monthly_wage_kwd"] > 0 for r in rows.values())


def test_kuwait_cards_add_up():
    for point in entry("kw-bank-cards-valid-and-issued-monthly-2026")["spec"]["series"]:
        assert point["credit_cards_valid_thousands"] + point["debit_cards_valid_thousands"] == pytest.approx(point["value"], abs=0.15)


def test_oman_cpi_weights_sum_to_one_hundred():
    rows = entry("om-cpi-by-group-with-weights-2026-09")["spec"]["parameters"]["rows"]
    assert sum(r["weight"] for k, r in rows.items() if k != "00") == pytest.approx(100, abs=0.01)
    assert rows["00"]["weight"] == 100


def test_oman_population_nationality_shares_match_the_bulletin_callouts():
    groups = entry("om-registered-population-by-governorate-and-nationality-2026-09")["spec"]["distributions"]
    omani = groups["Omani"]["parameters"]["counts"]
    expatriate = groups["Expatriate"]["parameters"]["counts"]
    assert round(omani["Muscat"] / (omani["Muscat"] + expatriate["Muscat"]) * 100, 1) == 39.0
    omani_total, expatriate_total = sum(omani.values()), sum(expatriate.values())
    assert round(omani_total / (omani_total + expatriate_total) * 100, 2) == 56.44


def test_oman_expatriate_nationalities_sum_to_the_sector_total():
    nationalities = entry("om-expatriate-workers-by-nationality-2026-09")["spec"]["distribution"]["parameters"]["total"]
    sectors = entry("om-workers-by-sector-and-nationality-2026-09")["spec"]["distributions"]["Expatriate"]["parameters"]["total"]
    assert nationalities == sectors


def test_bahrain_wage_bands_are_ordered_and_contiguous():
    dist = entry("bh-private-sector-workers-by-wage-band-nationality-and-sex-2023")["spec"]["distributions"]["Bahraini|Male"]
    bands = list(dist["parameters"]["bands_bhd"].values())
    assert bands[0]["low"] == 0 and bands[-1]["high"] is None
    for lower, upper in zip(bands, bands[1:]):
        assert upper["low"] == lower["high"] + 1


def test_bahrain_population_tables_agree_on_group_totals():
    by_age = entry("bh-population-by-nationality-sex-and-age-group-2025")["spec"]["distributions"]
    by_governorate = entry("bh-population-by-governorate-nationality-and-sex-2025")["spec"]["distributions"]
    assert set(by_age) == set(by_governorate)
    for group in by_age:
        assert by_age[group]["parameters"]["total"] == pytest.approx(by_governorate[group]["parameters"]["total"], rel=0.01), group


def test_qatar_wage_table_has_a_wage_for_every_sector():
    for sex, dist in entry("qa-paid-employment-and-average-wage-by-sector-and-sex-2023")["spec"]["distributions"].items():
        params = dist["parameters"]
        assert set(params["average_monthly_wage_qar"]) == set(params["counts"]), sex
        assert all(w > 0 for w in params["average_monthly_wage_qar"].values())


def test_qatar_cpi_covers_twelve_months_and_twelve_groups():
    spec = entry("qa-cpi-by-expenditure-group-monthly-2025")["spec"]
    assert [p["period"] for p in spec["series"]] == [f"2025-{m:02d}" for m in range(1, 13)]
    assert len(spec["columns"]) == 12

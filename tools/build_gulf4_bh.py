"""Build the Bahrain statistics entries from the Bahrain open data portal (data.gov.bh, Opendatasoft).

Population by nationality, sex, age group and governorate; the consumer price index by COICOP division;
private-sector workers covered by the Social Insurance Organization by wage band, economic activity,
nationality and sex; active expatriate work permits from the Labour Market Regulatory Authority;
vehicles registered in use; inbound visitors by region of residence; and deaths by age group. Every
export is pinned to the periods it covers with an explicit column list and sort order. Run from the
repository root:

    uv run python tools/build_gulf4_bh.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, write  # noqa: E402
from _gulf4 import (  # noqa: E402
    categorical,
    csv_line,
    csv_rows,
    fetch_patiently,
    marginal_tests,
    number,
    ods_export,
    share_tests,
    shares_assumption,
    whole,
)

PORTAL = "https://www.data.gov.bh"
LICENSE = "unstated"
PUBLISHER_IGA = "Information & eGovernment Authority, Kingdom of Bahrain"
PUBLISHER_SIO = "Social Insurance Organization, Kingdom of Bahrain (via the Bahrain open data portal)"
PUBLISHER_LMRA = "Labour Market Regulatory Authority, Kingdom of Bahrain (via the Bahrain open data portal)"
PUBLISHER_TRAFFIC = "Ministry of Interior, General Directorate of Traffic, Kingdom of Bahrain (via the Bahrain open data portal)"
PUBLISHER_TOURISM = "Bahrain Tourism & Exhibitions Authority (via the Bahrain open data portal)"
PUBLISHER_MOH = "Ministry of Health, Kingdom of Bahrain (via the Bahrain open data portal)"
LICENSE_NOTE = (
    "The Bahrain open data portal publishes no licence for this dataset (its catalogue licence field is empty), "
    "so the entry stays at license-review until the Information & eGovernment Authority's reuse terms are confirmed."
)
TAGS = ["bahrain", "gcc"]

CPI_MONTHS = [("2025", "10 October"), ("2025", "11 November"), ("2025", "12 December")] + [
    ("2026", m) for m in ("01 January", "02 February", "03 March", "04 April", "05 May", "06 June", "07 July", "08 August", "09 September")
]
CPI_DIVISIONS = {
    "1": "food_non_alcoholic_beverages",
    "2": "alcoholic_beverages_tobacco",
    "3": "clothing_footwear",
    "4": "housing_utilities_fuels",
    "5": "furnishings_household_equipment",
    "6": "health",
    "7": "transport",
    "8": "communication",
    "9": "recreation_culture",
    "10": "education",
    "11": "restaurants_hotels",
    "12": "miscellaneous_goods_services",
}
MONTH_NUMBER = {m.split()[1]: m.split()[0] for _, m in CPI_MONTHS}


def label(text: str) -> str:
    """Collapse the doubled spaces some Bahraini exports carry inside category labels."""
    return " ".join(text.split())


def export(dataset: str, select: list[str], where: str, order_by: list[str]) -> tuple[str, bytes]:
    url = ods_export(PORTAL, dataset, select=select, where=where, order_by=order_by)
    return url, fetch_patiently(url)


def grouped(rows: list[dict], given: tuple[str, ...], variable: str, value: str, arabic: str | None = None) -> tuple[dict, dict]:
    """Counts per conditioning group, in export order, with Arabic labels for the variable when present."""
    counts: dict[str, dict[str, float]] = {}
    labels_ar: dict[str, str] = {}
    for r in rows:
        v = number(r[value])
        if v is None:
            continue
        key = "|".join(r[g] for g in given)
        category = label(r[variable])
        counts.setdefault(key, {})[category] = counts.get(key, {}).get(category, 0) + v
        if arabic:
            labels_ar[category] = label(r[arabic])
    return counts, labels_ar


def population_by_age() -> dict:
    dataset = "01-population-by-nationality-sex-agegroups"
    url, raw = export(dataset, ["n", "year", "nationality", "sex", "age_group", "population", "ljnsy", "ljns"], "year=date'2025-06'", ["n"])
    rows = csv_rows(raw)
    counts, _ = grouped(rows, ("nationality", "sex"), "age_group", "population")
    dists = {k: categorical(v) for k, v in counts.items()}
    first = csv_line(raw, ",Bahraini,Male,0-4,")
    last = csv_line(raw, ",Non-Bahraini,Female,85+,")
    title = "Bahrain open data portal, dataset 01-population-by-nationality-sex-agegroups (CSV export, June 2025)"
    return {
        "id": "bh-population-by-nationality-sex-and-age-group-2025",
        "title": "Bahrain population by nationality, sex and five-year age group, mid-2025",
        "kind": "conditional",
        "domain": "demographics",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-06-30", "end": "2025-06-30"},
        "tags": TAGS + ["population", "age", "sex", "nationality", "population-pyramid", "iga"],
        "use_cases": ["synthetic-customers", "synthetic-employees", "person-generation", "customer-segmentation", "banking-demo", "retail-demo"],
        "spec": {"variable": "age_group", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            evidence(PUBLISHER_IGA, title, url, "row nationality=Bahraini, sex=Male, age_group=0-4", first.split(",")[5], "count", ",".join(first.split(",")[:6]), LICENSE, raw),
            evidence(PUBLISHER_IGA, title, url, "row nationality=Non-Bahraini, sex=Female, age_group=85+", last.split(",")[5], "count", ",".join(last.split(",")[:6]), LICENSE, raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Groups are nationality (Bahraini, Non-Bahraini) by sex.")],
        "tests": share_tests(dists, 1) + [{"statistic": 'share["Bahraini|Male","0-4"]', "expected": dists["Bahraini|Male"]["parameters"]["shares"]["0-4"], "tolerance": 0.005}],
        "notes": (
            "Mid-year (June) 2025 population estimate of the Kingdom of Bahrain by nationality (Bahraini, Non-Bahraini), "
            "sex and five-year age group (0-4 to 85+), published by the Information & eGovernment Authority. Each group "
            "keeps the published counts beside the shares, so the four groups together form the population pyramid; "
            "group totals give the nationality-by-sex split. " + LICENSE_NOTE
        ),
    }


def population_by_governorate() -> dict:
    dataset = "02-population-by-governorate-nationality-sex"
    url, raw = export(dataset, ["year", "nationality", "sex", "governorate", "population", "ljnsy", "ljns", "lmhfz"], "year=date'2025-06'", ["nationality", "sex", "governorate"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("nationality", "sex"), "governorate", "population", "lmhfz")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    line = csv_line(raw, ",Non-Bahraini,Male,Capital,")
    title = "Bahrain open data portal, dataset 02-population-by-governorate-nationality-sex (CSV export, June 2025)"
    return {
        "id": "bh-population-by-governorate-nationality-and-sex-2025",
        "title": "Bahrain population by governorate given nationality and sex, mid-2025",
        "kind": "conditional",
        "domain": "demographics",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-06-30", "end": "2025-06-30"},
        "tags": TAGS + ["population", "governorate", "sex", "nationality", "iga"],
        "use_cases": ["synthetic-customers", "address-generation", "person-generation", "customer-segmentation", "retail-demo"],
        "spec": {"variable": "governorate", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            evidence(PUBLISHER_IGA, title, url, "row nationality=Non-Bahraini, sex=Male, governorate=Capital", line.split(",")[4], "count", ",".join(line.split(",")[:5]), LICENSE, raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "The Not Stated governorate row is kept with its published count.")],
        "tests": share_tests(dists),
        "notes": (
            "Mid-year (June) 2025 population of Bahrain across its four governorates (Capital, Muharraq, Northern, Southern) "
            "for each nationality and sex group, with the Arabic governorate names from the same export. " + LICENSE_NOTE
        ),
    }


def cpi_monthly() -> dict:
    dataset = "01-consumer-price-index-division-and-group-index-number"
    months = " or ".join(f"(year=date'{y}' and month=\"{m}\")" for y, m in CPI_MONTHS)
    where = f'(level=0 or level=2) and ({months})'
    url, raw = export(dataset, ["n", "year", "month", "coicop_code", "level", "coicop_division_group", "point", "lshhr"], where, ["n"])
    rows = csv_rows(raw)
    series_map: dict[str, dict[str, float]] = {}
    for r in rows:
        period = f"{r['year']}-{r['month'].split()[0]}"
        code = r["coicop_code"].lstrip("0") or "0"
        series_map.setdefault(period, {})["value" if code == "0" else CPI_DIVISIONS[code]] = round(float(r["point"]), 4)
    periods = sorted(series_map)
    series = [{"period": p, **series_map[p]} for p in periods]
    columns = list(CPI_DIVISIONS.values())
    head = next(r for r in rows if r["coicop_code"] == "0" and r["year"] == "2026" and r["month"] == "09 September")
    food = next(r for r in rows if r["coicop_code"].lstrip("0") == "1" and r["year"] == "2025" and r["month"] == "10 October")
    title = "Bahrain open data portal, dataset 01-consumer-price-index-division-and-group-index-number (CSV export)"
    return {
        "id": "bh-cpi-by-coicop-division-monthly-2025-10-2026-09",
        "title": "Bahrain consumer price index by COICOP division, monthly, October 2025 to September 2026",
        "kind": "temporal",
        "domain": "economy",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "tags": TAGS + ["cpi", "inflation", "prices", "coicop", "monthly", "time-series", "iga"],
        "use_cases": ["retail-demo", "pricing", "contract-indexation", "demand-forecasting", "banking-demo"],
        "spec": {"variable": "cpi_general_index", "unit": "decimal", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER_IGA, title, url, "row year=2026, month=09 September, coicop_code=0 (general index), point", head["point"], "decimal", csv_line(raw, f"{head['n']},2026,09 September,0,").rsplit(",", 1)[0], LICENSE, raw),
            evidence(PUBLISHER_IGA, title, url, "row year=2025, month=10 October, coicop division 1 (food and non-alcoholic beverages), point", food["point"], "decimal", csv_line(raw, f"{food['n']},2025,10 October,").rsplit(",", 1)[0], LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series_map["2026-09"]["value"], "tolerance": 1e-9},
            {"statistic": "column[food_non_alcoholic_beverages,2025-10]", "expected": series_map["2025-10"]["food_non_alcoholic_beverages"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Monthly consumer price index for Bahrain, the general index (COICOP code 0) as the series value and the twelve "
            "COICOP divisions as columns, for the twelve latest published months (October 2025 to September 2026). Index "
            "points are rounded to four decimals from the full-precision export; the dataset does not state its base "
            "period in the export, so treat the values as index points rather than percentage changes. Division columns: "
            + ", ".join(f"{k} = {v}" for k, v in CPI_DIVISIONS.items()) + ". " + LICENSE_NOTE
        ),
    }


def wage_bands() -> dict:
    dataset = "03-workers-by-social-ins-sy-private-sector-by-monthly-wage-g-nat-and-sex"
    url, raw = export(
        dataset,
        ["n", "year", "monthly_wage_groups_bahraini_dinar", "nationality", "sex", "value", "ljnsy", "ljns"],
        "year=date'2023'",
        ["n"],
    )
    rows = csv_rows(raw)
    counts, _ = grouped(rows, ("nationality", "sex"), "monthly_wage_groups_bahraini_dinar", "value")
    dists = {k: categorical(v) for k, v in counts.items()}
    bands = {}
    for band in next(iter(counts.values())):
        numbers = [int(x.replace(",", "")) for x in re.findall(r"[\d,]+", band)]
        if band.startswith("Less than"):
            bands[band] = {"low": 0, "high": numbers[0] - 1}
        elif band.endswith("+"):
            bands[band] = {"low": numbers[0], "high": None}
        else:
            bands[band] = {"low": numbers[0], "high": numbers[1]}
    for dist in dists.values():
        dist["parameters"]["bands_bhd"] = {band: dict(bounds) for band, bounds in bands.items()}
    line = csv_line(raw, ",Non-Bahraini,Male,").split(",")
    line_bh = csv_line(raw, "1,500 +", ",Bahraini,Female,")
    title = "Bahrain open data portal, dataset 03-workers-by-social-ins-sy-private-sector-by-monthly-wage-g-nat-and-sex (CSV export, 2023)"
    return {
        "id": "bh-private-sector-workers-by-wage-band-nationality-and-sex-2023",
        "title": "Bahrain private-sector insured workers by monthly wage band (BHD) given nationality and sex, 2023",
        "kind": "conditional",
        "domain": "employment",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "tags": TAGS + ["wages", "salary", "wage-bands", "private-sector", "nationality", "sex", "social-insurance", "sio"],
        "use_cases": ["synthetic-employees", "hr-demo", "payroll-demo", "hr-analytics", "banking-demo"],
        "spec": {"variable": "monthly_wage_band_bhd", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            evidence(PUBLISHER_SIO, title, url, "first row for nationality=Non-Bahraini, sex=Male", line[5], "count", ",".join(line[:6]), LICENSE, raw),
            evidence(PUBLISHER_SIO, title, url, "row wage band 1,500 +, nationality=Bahraini, sex=Female", line_bh.split('"')[-1].split(",")[3], "count", line_bh.rsplit(",", 2)[0], LICENSE, raw),
        ],
        "assumed": [
            shares_assumption("distributions.*.parameters.shares", ""),
            {
                "parameter": "distributions.*.parameters.bands_bhd",
                "value": "low and high Bahraini dinar bounds read from each band label",
                "method": "derived",
                "rationale": "The source labels bands as text ('50 - 99', '1,500 +'); the numeric bounds restate those labels so a generator can draw a wage inside the band. 'Less than 50' becomes 0 to 49 and the open top band has no upper bound.",
            },
        ],
        "tests": share_tests(dists, 1),
        "notes": (
            "Workers covered by the Social Insurance Organization's private-sector scheme in 2023, by monthly wage band in "
            "Bahraini dinars, for Bahraini and non-Bahraini men and women. The bands are those of the source (Less than 50, "
            "50 - 99, ... 1,000 - 1,499, 1,500 +), with doubled spaces in the labels collapsed. Coverage is the private "
            "sector scheme only; government employees are not included. " + LICENSE_NOTE
        ),
    }


def workers_by_activity() -> dict:
    dataset = "02-workers-covered-by-social-ins-sys-private-sector-by-eco-act-nat-and-sex"
    url, raw = export(dataset, ["n", "year", "economic_activity", "nationality", "sex", "value", "lnsht_lqtsdy", "ljnsy", "ljns"], "year=date'2023'", ["n"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("nationality", "sex"), "economic_activity", "value", "lnsht_lqtsdy")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    line = csv_line(raw, ",Construction,Non-Bahraini,Male,").split(",")
    title = "Bahrain open data portal, dataset 02-workers-covered-by-social-ins-sys-private-sector-by-eco-act-nat-and-sex (CSV export, 2023)"
    return {
        "id": "bh-private-sector-workers-by-activity-nationality-and-sex-2023",
        "title": "Bahrain private-sector insured workers by economic activity given nationality and sex, 2023",
        "kind": "conditional",
        "domain": "employment",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "tags": TAGS + ["employment", "economic-activity", "industry", "private-sector", "nationality", "sex", "social-insurance", "sio"],
        "use_cases": ["synthetic-employees", "hr-demo", "workforce-planning", "company-generation", "hr-analytics"],
        "spec": {"variable": "economic_activity", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            evidence(PUBLISHER_SIO, title, url, "row economic_activity=Construction, nationality=Non-Bahraini, sex=Male", line[5], "count", ",".join(line[:6]), LICENSE, raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "")],
        "tests": share_tests(dists, 1),
        "notes": (
            "Workers covered by the Social Insurance Organization's private-sector scheme in 2023 by economic activity "
            "(the source's ISIC Rev. 3 style sections, plus 'Non-classified records' and 'Temporarily additional activities' "
            "as published), for Bahraini and non-Bahraini men and women, with Arabic activity names from the same export. "
            "Private-sector coverage only. " + LICENSE_NOTE
        ),
    }


def vehicles() -> dict:
    dataset = "01-vehicle-registered-in-use"
    url, raw = export(dataset, ["n", "year", "type", "item", "value", "lnw", "lbyn"], "year=date'2025'", ["n"])
    rows = csv_rows(raw)
    counts: dict[str, float] = {}
    labels_ar: dict[str, str] = {}
    for r in rows:
        counts[label(r["item"])] = number(r["value"])
        labels_ar[label(r["item"])] = label(r["lbyn"])
    dist = categorical(counts, labels_ar)
    line = csv_line(raw, ",Private,").split(",")
    title = "Bahrain open data portal, dataset 01-vehicle-registered-in-use (CSV export, 2025)"
    return {
        "id": "bh-vehicles-registered-in-use-by-type-2025",
        "title": "Bahrain vehicles registered in use by registration type, 2025",
        "kind": "marginal",
        "domain": "automotive",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["vehicles", "vehicle-registrations", "fleet", "traffic"],
        "use_cases": ["automotive-demo", "fleet-demo", "insurance", "synthetic-customers"],
        "spec": {"variable": "vehicle_registration_type", "unit": "ratio", "distribution": dist},
        "evidence": [
            evidence(PUBLISHER_TRAFFIC, title, url, "row item=Private", line[4], "count", ",".join(line[:5]), LICENSE, raw),
        ],
        "assumed": [shares_assumption("distribution.parameters.shares", "Categories with a published zero are kept.")],
        "tests": marginal_tests(dist),
        "notes": (
            "Vehicles registered and in use in Bahrain in 2025 by registration type (private, private hire, goods vehicles, "
            "motorcycles, taxis, diplomatic and so on), as published by the General Directorate of Traffic, with Arabic "
            "type names from the same export. " + LICENSE_NOTE
        ),
    }


def inbound_visitors() -> dict:
    dataset = "05-inbound-visitors-by-countryregion-of-residence"
    columns = ["other_gcc", "europe", "asia", "middle_east", "america", "other_countries"]
    url, raw = export(dataset, ["n", "year", "month", "ksa", *columns, "lshhr"], "year=date'2025'", ["n"])
    rows = csv_rows(raw)
    series = []
    for r in rows:
        point = {"period": f"2025-{r['month'].split()[0]}", "value": whole(number(r["ksa"]))}
        point.update({c: whole(number(r[c])) for c in columns})
        series.append(point)
    january = csv_line(raw, ",2025,01 January,")
    title = "Bahrain open data portal, dataset 05-inbound-visitors-by-countryregion-of-residence (CSV export, 2025)"
    return {
        "id": "bh-inbound-visitors-by-region-of-residence-monthly-2025",
        "title": "Bahrain inbound visitors by region of residence, monthly 2025",
        "kind": "temporal",
        "domain": "tourism",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["tourism", "visitors", "arrivals", "monthly", "time-series", "seasonality"],
        "use_cases": ["tourism-demo", "demand-forecasting", "retail-demo", "synthetic-customers"],
        "spec": {"variable": "inbound_visitors_resident_in_saudi_arabia", "unit": "count", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER_TOURISM, title, url, "row year=2025, month=01 January (ksa, then the other regions)", rows[0]["ksa"], "count", ",".join(january.split(",")[1:4]), LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "value[2025-01]", "expected": series[0]["value"], "tolerance": 0},
            {"statistic": "column[europe,2025-12]", "expected": series[-1]["europe"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Monthly inbound visitors (arrivals) to Bahrain in 2025 by region of residence, from the Inbound Tourism Survey "
            "published by the Bahrain Tourism & Exhibitions Authority. Visitors resident in Saudi Arabia are the series value; "
            "the other GCC states, Europe, Asia, the Middle East, the Americas and other countries ride along as columns. "
            "The source publishes no all-regions total; summing the seven figures gives one. " + LICENSE_NOTE
        ),
    }


def work_permits() -> dict:
    dataset = "lmra1-active-work-permits-for-expatriate"
    url, raw = export(dataset, ["n", "year", "quarter", "number", "lrb"], "year>=date'2021' and year<=date'2025'", ["n"])
    rows = csv_rows(raw)
    series = [{"period": f"{r['year']}-{r['quarter']}", "value": whole(number(r["number"]))} for r in rows]
    line = csv_line(raw, ",2025,Q4,")
    title = "Bahrain open data portal, dataset lmra1-active-work-permits-for-expatriate (CSV export, 2021 to 2025)"
    return {
        "id": "bh-lmra-active-expatriate-work-permits-quarterly-2021-2025",
        "title": "Bahrain active work permits for expatriates, quarterly 2021 to 2025 (LMRA)",
        "kind": "temporal",
        "domain": "employment",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2021-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["work-permits", "expatriates", "migrant-workers", "quarterly", "time-series", "lmra"],
        "use_cases": ["synthetic-employees", "workforce-planning", "hr-analytics", "market-sizing"],
        "spec": {"variable": "active_expatriate_work_permits", "unit": "count", "frequency": "quarterly", "columns": [], "series": series},
        "evidence": [
            evidence(PUBLISHER_LMRA, title, url, "row year=2025, quarter=Q4", line.split(",")[3], "count", ",".join(line.split(",")[1:4]), LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "value[2025-Q4]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": "value[2021-Q1]", "expected": series[0]["value"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Active work permits held by expatriate workers in Bahrain at each quarter from 2021 to 2025, published by the "
            "Labour Market Regulatory Authority on the national open data portal. Periods are labelled year-quarter. " + LICENSE_NOTE
        ),
    }


def deaths_by_age() -> dict:
    dataset = "22-deaths-by-age-groups"
    url, raw = export(dataset, ["n", "year", "nationality", "sex", "age_group", "deaths", "ljnsy", "jns", "fy_t_lsn"], "year=date'2022'", ["n"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("nationality", "sex"), "age_group", "deaths", "fy_t_lsn")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    line = csv_line(raw, ",Non-Bahraini,Male,75 +,").split(",")
    title = "Bahrain open data portal, dataset 22-deaths-by-age-groups (CSV export, 2022)"
    return {
        "id": "bh-deaths-by-age-group-nationality-and-sex-2022",
        "title": "Bahrain registered deaths by age group given nationality and sex, 2022",
        "kind": "conditional",
        "domain": "healthcare",
        "region": "BH",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2022-01-01", "end": "2022-12-31"},
        "tags": TAGS + ["deaths", "mortality", "vital-statistics", "age", "nationality", "sex"],
        "use_cases": ["health-demo", "insurance", "synthetic-customers", "claims-generation"],
        "spec": {"variable": "age_group_at_death", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            evidence(PUBLISHER_MOH, title, url, "row nationality=Non-Bahraini, sex=Male, age_group=75 +", line[5], "count", ",".join(line[:6]), LICENSE, raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Age labels have doubled spaces collapsed ('1  -  4' becomes '1 - 4').")],
        "tests": share_tests(dists, 1),
        "notes": (
            "Deaths registered in Bahrain in 2022 by age group of the deceased (under a week, under a month, under a year, "
            "then five-year bands to 75 +), for Bahraini and non-Bahraini men and women, from the Ministry of Health's vital "
            "statistics on the national open data portal, with Arabic age-group labels from the same export. " + LICENSE_NOTE
        ),
    }


BUILDERS = [population_by_age, population_by_governorate, cpi_monthly, wage_bands, workers_by_activity, vehicles, inbound_visitors, work_permits, deaths_by_age]


def build(names: list[str] | None = None) -> list[Path]:
    """Build every entry, or only the builders named (for example ``cpi_monthly``)."""
    chosen = [b for b in BUILDERS if not names or b.__name__ in names]
    return [write(builder()) for builder in chosen]


if __name__ == "__main__":
    build(sys.argv[1:])

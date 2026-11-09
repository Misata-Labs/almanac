"""Build the Qatar statistics entries from the Qatar open data portal (data.gov.qa, Opendatasoft), whose
National Planning Council datasets are published under CC BY 4.0.

Labour-force status by nationality and sex, employed persons by occupation, nationality and sex,
paid employment and average monthly wage by sector and sex, the economically active population by
sector and economic activity, population by sex and age group, the monthly consumer price index by
expenditure group, hotel guests by nationality and hotel rating, registered vehicles by licence type,
and registered deaths by age, nationality and sex. Every export is pinned to one period with an
explicit column list and sort order. Run from the repository root:

    uv run python tools/build_gulf4_qa.py [builder names...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

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
    ods_licence_query,
    share_tests,
    shares_assumption,
    whole,
)

PORTAL = "https://www.data.gov.qa"
LICENSE = "CC-BY-4.0"
PUBLISHER = "National Planning Council, State of Qatar (Qatar open data portal)"
TAGS = ["qatar", "gcc", "npc"]
LICENSE_NOTE = "The portal's catalogue record for the dataset gives the licence as CC BY with the Creative Commons Attribution 4.0 licence URL."
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CPI_GROUPS = {
    "001": "food_beverages",
    "002": "tobacco",
    "003": "clothing_footwear",
    "004": "housing_utilities_fuels",
    "005": "furnishings_household_equipment",
    "006": "health",
    "007": "transport",
    "008": "communication",
    "009": "recreation_culture",
    "010": "education",
    "011": "restaurants_hotels",
    "012": "miscellaneous_goods_services",
}
VEHICLE_COLUMNS = {
    "private": "Private",
    "private_transport": "Private transport",
    "heavy_equipment_and_machinery": "Heavy equipment and machinery",
    "trailer": "Trailer",
    "motorcycles": "Motorcycles",
    "taxis_and_limousines": "Taxis and limousines",
    "government": "Government",
    "public_transport": "Public transport",
    "other": "Other",
}


def export(dataset: str, select: list[str], year: str, order_by: list[str]) -> tuple[str, bytes]:
    """Fetch an export pinned to ``year``; the portal types ``year`` as a date in some datasets and text in others."""
    failure: Exception | None = None
    for where in (f"year=date'{year}'", f'year="{year}"', f"year={year}"):
        url = ods_export(PORTAL, dataset, select=select, where=where, order_by=order_by)
        try:
            raw = fetch_patiently(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            failure = exc
            continue
        if len(raw.decode("utf-8-sig").splitlines()) > 1:
            return url, raw
    raise RuntimeError(f"{dataset}: no export for {year}") from failure


def licence_item(dataset: str) -> dict:
    url = ods_licence_query(PORTAL, dataset)
    raw = fetch_patiently(url)
    return evidence(
        PUBLISHER,
        f"Qatar open data portal catalogue, licence fields of dataset {dataset} (JSON)",
        url,
        "results[0].default.license_url",
        "https://creativecommons.org/licenses/by/4.0/",
        "text",
        '"default.license_url": "https://creativecommons.org/licenses/by/4.0/"',
        LICENSE,
        raw,
        role="supporting",
    )


def export_title(dataset: str, period: str) -> str:
    return f"Qatar open data portal, dataset {dataset} (CSV export, {period})"


def row_item(dataset: str, period: str, url: str, raw: bytes, needles: tuple[str, ...], value_index: int, locator: str, unit: str = "count") -> dict:
    line = csv_line(raw, *needles)
    cells = line.split(",")
    return evidence(PUBLISHER, export_title(dataset, period), url, locator, cells[value_index], unit, ",".join(cells[: value_index + 1]), LICENSE, raw)


def grouped(rows: list[dict], given: tuple[str, ...], variable: str, value: str, arabic: str | None = None) -> tuple[dict, dict]:
    counts: dict[str, dict[str, float]] = {}
    labels_ar: dict[str, str] = {}
    for r in rows:
        v = number(r[value])
        if v is None:
            continue
        key = "|".join(r[g].strip() for g in given)
        category = " ".join(r[variable].split())
        counts.setdefault(key, {})[category] = counts.get(key, {}).get(category, 0) + v
        if arabic:
            labels_ar[category] = r[arabic].strip()
    return counts, labels_ar


def labour_force_status() -> dict:
    dataset = "population-15-years-and-above-by-relation-to-labour-force-nationality-and-gender"
    url, raw = export(dataset, ["year", "nationality", "gender", "labour_force_status", "count", "ljnsy", "lnw", "hl_lqw_l_ml"], "2025", ["nationality", "gender", "labour_force_status"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("nationality", "gender"), "labour_force_status", "count", "hl_lqw_l_ml")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    return {
        "id": "qa-labour-force-status-by-nationality-and-sex-2025",
        "title": "Qatar population aged 15+ by relation to the labour force given nationality and sex, 2025",
        "kind": "conditional",
        "domain": "employment",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["labour-force", "employment", "unemployment", "nationality", "sex", "labour-force-survey"],
        "use_cases": ["synthetic-customers", "synthetic-employees", "person-generation", "hr-analytics", "banking-demo"],
        "spec": {"variable": "labour_force_status", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            row_item(dataset, "2025", url, raw, ("2025,Non Qatari,Males,Employed,",), 4, "row nationality=Non Qatari, gender=Males, labour_force_status=Employed"),
            row_item(dataset, "2025", url, raw, ("2025,Qatari,Females,Employed,",), 4, "row nationality=Qatari, gender=Females, labour_force_status=Employed"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Blank cells (for example housewife among men) are unpublished and left out rather than set to zero.")],
        "tests": share_tests(dists, 2),
        "notes": (
            "Population aged 15 and over in Qatar in 2025 by relation to the labour force (employed, unemployed with previous "
            "employment, seeking work for the first time, student, housewife, retired, disabled, other) for Qatari and "
            "non-Qatari men and women, from the National Planning Council's labour force statistics, with Arabic status "
            "labels from the same export. " + LICENSE_NOTE
        ),
    }


def occupation() -> dict:
    dataset = "economically-active-population-15-years-and-above-by-nationality-gender-and-occupation"
    url, raw = export(dataset, ["year", "nationality", "gender", "occupation", "total", "ljnsy", "ljns", "lmhn"], "2025", ["nationality", "gender", "occupation"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("nationality", "gender"), "occupation", "total", "lmhn")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    return {
        "id": "qa-economically-active-by-occupation-nationality-and-sex-2025",
        "title": "Qatar economically active population aged 15+ by occupation given nationality and sex, 2025",
        "kind": "conditional",
        "domain": "employment",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["occupation", "isco", "employment", "nationality", "sex", "labour-force-survey"],
        "use_cases": ["synthetic-employees", "hr-demo", "workforce-planning", "person-generation", "hr-analytics"],
        "spec": {"variable": "occupation", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            row_item(dataset, "2025", url, raw, ("2025,Non-Qatari,Males,Craft And Related Trades Workers,",), 4, "row nationality=Non-Qatari, gender=Males, occupation=Craft And Related Trades Workers"),
            row_item(dataset, "2025", url, raw, ("2025,Qatari,Females,Professionals,",), 4, "row nationality=Qatari, gender=Females, occupation=Professionals"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "")],
        "tests": share_tests(dists, 2),
        "notes": (
            "Economically active population aged 15 and over in Qatar in 2025 by major occupation group (the source's nine "
            "ISCO-style groups, from legislators, senior officials and managers to elementary occupations) for Qatari and "
            "non-Qatari men and women, with Arabic occupation names from the same export. " + LICENSE_NOTE
        ),
    }


def wages_by_sector() -> dict:
    dataset = "workers-in-paid-employment-and-average-monthly-wage-by-gender-and-sector"
    url, raw = export(dataset, ["year", "gender", "sector", "paid_employment_workers", "monthly_average_wage_qr", "lnw", "lqt"], "2023", ["gender", "sector"])
    rows = csv_rows(raw)
    dists = {}
    for gender in sorted({r["gender"] for r in rows}):
        subset = [r for r in rows if r["gender"] == gender]
        dist = categorical({r["sector"].strip(): number(r["paid_employment_workers"]) for r in subset}, {r["sector"].strip(): r["lqt"].strip() for r in subset})
        dist["parameters"]["average_monthly_wage_qar"] = {r["sector"].strip(): whole(number(r["monthly_average_wage_qr"])) for r in subset}
        dists[gender] = dist
    return {
        "id": "qa-paid-employment-and-average-wage-by-sector-and-sex-2023",
        "title": "Qatar workers in paid employment by sector given sex, with average monthly wage (QAR), 2023",
        "kind": "conditional",
        "domain": "employment",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "tags": TAGS + ["wages", "salary", "sector", "government", "private-sector", "domestic-workers", "sex", "labour-force-survey"],
        "use_cases": ["synthetic-employees", "payroll-demo", "hr-demo", "banking-demo", "workforce-planning"],
        "spec": {"variable": "sector", "unit": "ratio", "given": "sex", "distributions": dists},
        "evidence": [
            row_item(dataset, "2023", url, raw, ("2023,Males,Private,",), 3, "row gender=Males, sector=Private, paid_employment_workers"),
            row_item(dataset, "2023", url, raw, ("2023,Females,Government Department,",), 4, "row gender=Females, sector=Government Department, monthly_average_wage_qr", "currency:QAR"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "The average wage per sector is published, not derived.")],
        "tests": share_tests(dists, 2),
        "notes": (
            "Workers in paid employment in Qatar in 2023 by sector (government department, government company or corporation, "
            "mixed, private, domestic, diplomatic or international, non-profit) for men and women, with the average monthly "
            "wage in Qatari riyals for each sector and sex under average_monthly_wage_qar. The source does not split this "
            "table by nationality. " + LICENSE_NOTE
        ),
    }


def sector_activity() -> dict:
    dataset = "economically-active-population-15-years-and-above-by-sector-and-economic-activity"
    url, raw = export(dataset, ["year", "sector", "economic_activity", "number", "lqt", "lnsht_lqtsdy"], "2024", ["sector", "economic_activity"])
    rows = csv_rows(raw)
    counts, labels_ar = grouped(rows, ("sector",), "economic_activity", "number", "lnsht_lqtsdy")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items() if sum(v.values()) > 0}
    return {
        "id": "qa-economically-active-by-activity-and-sector-2024",
        "title": "Qatar economically active population aged 15+ by economic activity given sector, 2024",
        "kind": "conditional",
        "domain": "employment",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2024-01-01", "end": "2024-12-31"},
        "tags": TAGS + ["economic-activity", "industry", "isic", "sector", "employment", "labour-force-survey"],
        "use_cases": ["synthetic-employees", "company-generation", "hr-demo", "workforce-planning"],
        "spec": {"variable": "economic_activity", "unit": "ratio", "given": "sector", "distributions": dists},
        "evidence": [
            row_item(dataset, "2024", url, raw, ("2024,Private,Construction,",), 3, "row sector=Private, economic_activity=Construction"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "")],
        "tests": share_tests(dists, 1),
        "notes": (
            "Economically active population aged 15 and over in Qatar in 2024 by economic activity (ISIC Rev. 4 sections as "
            "published) within each sector of employment (government department, government company or corporation, mixed, "
            "private, domestic, diplomatic or international, non-profit), with Arabic activity names. " + LICENSE_NOTE
        ),
    }


def age_key(label: str) -> int:
    return int(re.match(r"\d+", label).group(0))


def population_by_age() -> dict:
    dataset = "population-estimates-by-gender-and-age-groups"
    url, raw = export(dataset, ["year", "gender", "age_groups", "total", "lnw"], "2024", ["gender", "age_groups"])
    rows = csv_rows(raw)
    dists = {}
    for gender in sorted({r["gender"] for r in rows}):
        subset = sorted((r for r in rows if r["gender"] == gender), key=lambda r: age_key(r["age_groups"]))
        dists[gender] = categorical({" ".join(r["age_groups"].split()): number(r["total"]) for r in subset})
    return {
        "id": "qa-population-by-sex-and-age-group-2024",
        "title": "Qatar population estimates by age group given sex, 2024",
        "kind": "conditional",
        "domain": "demographics",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2024-01-01", "end": "2024-12-31"},
        "tags": TAGS + ["population", "age", "sex", "population-pyramid"],
        "use_cases": ["synthetic-customers", "person-generation", "customer-segmentation", "insurance", "retail-demo"],
        "spec": {"variable": "age_group", "unit": "ratio", "given": "sex", "distributions": dists},
        "evidence": [
            row_item(dataset, "2024", url, raw, ("2024,Males,30 - 34,",), 3, "row gender=Males, age_groups=30 - 34"),
            row_item(dataset, "2024", url, raw, ("2024,Females,80 +,",), 3, "row gender=Females, age_groups=80 +"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Age groups are ordered by their lower bound.")],
        "tests": share_tests(dists, 2),
        "notes": (
            "Population estimates for Qatar in 2024 by age group (under 1, 1-4, then five-year bands to 80+) for males and "
            "females. This table is not split by nationality. " + LICENSE_NOTE
        ),
    }


def cpi_monthly() -> dict:
    dataset = "consumer-price-index-cpi-by-expenditure-group-monthly"
    url, raw = export(dataset, ["year", "month", "group_code", "group", "cpi_index", "lshhr", "lmjmw"], "2025", ["month", "group_code"])
    rows = csv_rows(raw)
    points: dict[str, dict] = {}
    for r in rows:
        period = f"2025-{MONTHS.index(r['month']) + 1:02d}"
        key = "value" if r["group_code"].strip("0") == "" else CPI_GROUPS[r["group_code"]]
        points.setdefault(period, {})[key] = float(r["cpi_index"])
    series = [{"period": p, **points[p]} for p in sorted(points)]
    general = csv_line(raw, "2025,Dec,0,")
    food = csv_line(raw, "2025,Jan,001,")
    title = export_title(dataset, "2025")
    return {
        "id": "qa-cpi-by-expenditure-group-monthly-2025",
        "title": "Qatar consumer price index by expenditure group, monthly 2025",
        "kind": "temporal",
        "domain": "economy",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": TAGS + ["cpi", "inflation", "prices", "coicop", "monthly", "time-series"],
        "use_cases": ["retail-demo", "pricing", "contract-indexation", "demand-forecasting", "banking-demo"],
        "spec": {"variable": "cpi_general_index", "unit": "decimal", "frequency": "monthly", "columns": list(CPI_GROUPS.values()), "series": series},
        "evidence": [
            evidence(PUBLISHER, title, url, "row year=2025, month=Dec, group_code=0 (general index), cpi_index", general.split(",")[4], "decimal", ",".join(general.split(",")[:5]), LICENSE, raw),
            evidence(PUBLISHER, title, url, "row year=2025, month=Jan, group_code=001 (food and beverages), cpi_index", food.split(",")[4], "decimal", ",".join(food.split(",")[:5]), LICENSE, raw),
            licence_item(dataset),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "value[2025-12]", "expected": points["2025-12"]["value"], "tolerance": 1e-9},
            {"statistic": "column[food_beverages,2025-01]", "expected": points["2025-01"]["food_beverages"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Monthly consumer price index for Qatar in 2025, the general index (group code 0) as the series value and the "
            "twelve expenditure groups as columns: " + ", ".join(f"{k} = {v}" for k, v in CPI_GROUPS.items()) + ". 2025 is "
            "the latest complete year on the portal; the export does not state the base period. " + LICENSE_NOTE
        ),
    }


def hotel_guests() -> dict:
    dataset = "hotel-guests-by-nationality-hotel-rating-and-hotel-stays"
    url, raw = export(dataset, ["year", "metric", "hotel_rating", "nationality", "number", "lmqys", "drj_lfndq", "ljnsy"], "2022", ["metric", "hotel_rating", "nationality"])
    rows = [r for r in csv_rows(raw) if r["metric"] == "Guests"]
    counts, labels_ar = grouped(rows, ("hotel_rating",), "nationality", "number", "ljnsy")
    dists = {k: categorical(v, labels_ar) for k, v in counts.items()}
    nights_rows = [r for r in csv_rows(raw) if r["metric"] == "Nights"]
    nights, _ = grouped(nights_rows, ("hotel_rating",), "nationality", "number")
    for rating, dist in dists.items():
        dist["parameters"]["nights"] = {k: whole(v) for k, v in nights.get(rating, {}).items()}
    return {
        "id": "qa-hotel-guests-by-nationality-and-rating-2022",
        "title": "Qatar hotel guests by nationality group given hotel rating, with nights of stay, 2022",
        "kind": "conditional",
        "domain": "tourism",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2022-01-01", "end": "2022-12-31"},
        "tags": TAGS + ["tourism", "hotels", "hotel-guests", "nationality", "length-of-stay"],
        "use_cases": ["tourism-demo", "synthetic-customers", "retail-demo", "customer-segmentation"],
        "spec": {"variable": "guest_nationality_group", "unit": "ratio", "given": "hotel_rating", "distributions": dists},
        "evidence": [
            row_item(dataset, "2022", url, raw, ("2022,Guests,Five Star,Europeans,",), 4, "row metric=Guests, hotel_rating=Five Star, nationality=Europeans"),
            row_item(dataset, "2022", url, raw, ("2022,Nights,Five Star,Europeans,",), 4, "row metric=Nights, hotel_rating=Five Star, nationality=Europeans"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Nights of stay ride along per nationality group; nights divided by guests gives the mean length of stay.")],
        "tests": share_tests(dists, 1),
        "notes": (
            "Hotel guests in Qatar in 2022 by nationality group (Qataris, other GCC, other Arabs, Asians, Africans, Europeans, "
            "Americans, Australians and New Zealanders) within each hotel rating (five, four, three, two and one star), with "
            "the nights of stay for the same cells. 2022 is the latest year on the portal for this table. " + LICENSE_NOTE
        ),
    }


def vehicles() -> dict:
    dataset = "registered-vehicles-and-motor-cycles-by-type-of-license"
    url, raw = export(dataset, ["year", *VEHICLE_COLUMNS], "2022", ["year"])
    row = csv_rows(raw)[0]
    dist = categorical({label: number(row[column]) for column, label in VEHICLE_COLUMNS.items()})
    line = csv_line(raw, "2022,")
    return {
        "id": "qa-registered-vehicles-by-licence-type-2022",
        "title": "Qatar registered vehicles and motorcycles by type of licence, 2022",
        "kind": "marginal",
        "domain": "automotive",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2022-01-01", "end": "2022-12-31"},
        "tags": TAGS + ["vehicles", "vehicle-registrations", "fleet"],
        "use_cases": ["automotive-demo", "fleet-demo", "insurance", "synthetic-customers"],
        "spec": {"variable": "vehicle_licence_type", "unit": "ratio", "distribution": dist},
        "evidence": [
            evidence(PUBLISHER, export_title(dataset, "2022"), url, "row year=2022, columns " + ", ".join(VEHICLE_COLUMNS), row["private"], "count", ",".join(line.split(",")[:3]), LICENSE, raw),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distribution.parameters.shares", "Column names are rendered as readable labels.")],
        "tests": marginal_tests(dist),
        "notes": "Registered vehicles and motorcycles in Qatar in 2022 (the latest year on the portal) by type of licence: private, private transport, heavy equipment and machinery, trailer, motorcycles, taxis and limousines, government, public transport and other. " + LICENSE_NOTE,
    }


def deaths_by_age() -> dict:
    dataset = "registered-deaths-by-nationality-gender-and-age"
    url, raw = export(dataset, ["year", "nationality", "gender", "age_in_years", "value", "ljnsy", "lnw", "l_mr_blsnwt"], "2022", ["nationality", "gender", "age_in_years"])
    rows = [r for r in csv_rows(raw) if r["gender"] in ("Males", "Females")]
    counts, labels_ar = grouped(rows, ("nationality", "gender"), "age_in_years", "value", "l_mr_blsnwt")

    def order(label: str) -> tuple[int, int]:
        if label == "Under 1 Year":
            return (0, 0)
        if label == "Not Stated":
            return (2, 0)
        return (1, age_key(label))

    dists = {k: categorical(dict(sorted(v.items(), key=lambda kv: order(kv[0]))), labels_ar) for k, v in counts.items()}
    return {
        "id": "qa-registered-deaths-by-age-nationality-and-sex-2022",
        "title": "Qatar registered deaths by age given nationality and sex, 2022",
        "kind": "conditional",
        "domain": "healthcare",
        "region": "QA",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2022-01-01", "end": "2022-12-31"},
        "tags": TAGS + ["deaths", "mortality", "vital-statistics", "age", "nationality", "sex"],
        "use_cases": ["health-demo", "insurance", "synthetic-customers", "claims-generation"],
        "spec": {"variable": "age_at_death", "unit": "ratio", "given": "nationality|sex", "distributions": dists},
        "evidence": [
            row_item(dataset, "2022", url, raw, ("2022,Non-Qataris,Males,Under 1 Year,",), 4, "row nationality=Non-Qataris, gender=Males, age_in_years=Under 1 Year"),
            licence_item(dataset),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", "Ages are under 1, single years 1 to 4, five-year bands to 95 +, and not stated, ordered by age. Rows whose sex is not stated are left out.")],
        "tests": share_tests(dists, 1),
        "notes": (
            "Deaths registered in Qatar in 2022 by age of the deceased for Qatari and non-Qatari men and women, with Arabic "
            "age labels from the same export; 2022 is the latest year on the portal for this table. " + LICENSE_NOTE
        ),
    }


BUILDERS = [labour_force_status, occupation, wages_by_sector, sector_activity, population_by_age, cpi_monthly, hotel_guests, vehicles, deaths_by_age]


def build(names: list[str] | None = None) -> list[Path]:
    """Build every entry, or only the builders named (for example ``cpi_monthly``)."""
    chosen = [b for b in BUILDERS if not names or b.__name__ in names]
    return [write(builder()) for builder in chosen]


if __name__ == "__main__":
    build(sys.argv[1:])

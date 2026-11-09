"""Regenerate the United Arab Emirates statistics entries.

Sources:

- Statistics Centre Abu Dhabi (SCAD) Excel publications: consumer prices, hotel
  establishments, banks based in the emirate, births, building permits and
  completions.
- The federal open data portal Bayanat: Central Bank of the UAE aggregated bank
  liabilities, Ministry of Interior vehicle and driving-licence registrations, and
  the Federal Competitiveness and Statistics Centre unemployment rates.

Every value is read from the fetched workbook or XML file, and every evidence
item is checked against the text the verifier extracts from the same bytes
before the entry is written. Run from the repository root:

    uv run python tools/build_ae_stats.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

SCAD = "Statistics Centre Abu Dhabi"
SCAD_LICENSE = "SCAD terms of use: reproduction without further permission, with acknowledgement of SCAD as the source"
SCAD_TERMS_NOTE = (
    "SCAD's terms of use (https://www.scad.gov.ae/terms-of-use) state that its publications and tables may be "
    "reproduced without further permission provided SCAD is acknowledged as the source; the page is rendered "
    "per request and is referenced rather than hashed, so the entry stays at licence review."
)
SCAD_DOCS = "https://www.scad.gov.ae/documents/20122"

BAYANAT_LICENSE = "CC-BY-4.0"
BAYANAT_TERMS_NOTE = (
    "Bayanat, the UAE federal open data portal run by the Federal Competitiveness and Statistics Centre, states on "
    "its Copyright and Data Licensing page that datasets on the portal are available under the Creative Commons "
    "Attribution 4.0 International licence unless otherwise stated; that page is rendered per request and is "
    "referenced rather than hashed. Bayanat download links carry an opaque resource token issued by the portal."
)
BAYANAT = "https://bayanat.ae/api/DatasetResources/DownloadSingle?fileName=data&resourceID="

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


# --- workbook access --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sheet:
    """A worksheet as raw cell text, keyed by (row, column) with one-based indices."""

    cells: dict[tuple[int, int], str]

    def rows(self) -> list[list[str | None]]:
        if not self.cells:
            return []
        height = max(r for r, _ in self.cells)
        width = max(c for _, c in self.cells)
        return [[self.cells.get((r, c)) for c in range(1, width + 1)] for r in range(1, height + 1)]

    def find_row(self, label: str, column: int = 2, start: int = 1) -> list[str | None]:
        """The first row at or after ``start`` whose ``column`` holds ``label`` once trimmed."""
        for index, row in enumerate(self.rows(), start=1):
            if index >= start and row[column - 1] is not None and row[column - 1].strip() == label:
                return row
        raise KeyError(f"no row labelled {label!r}")


def _cell_position(ref: str) -> tuple[int, int]:
    letters, digits = re.match(r"([A-Z]+)(\d+)", ref).groups()
    column = 0
    for ch in letters:
        column = column * 26 + ord(ch) - 64
    return int(digits), column


def read_workbook(raw: bytes) -> dict[str, Sheet]:
    """Read every worksheet's cells as the raw text stored in the file, so numbers keep their published digits."""
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = set(archive.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).findall(f"{_MAIN}si"):
            shared.append("".join(t.text or "" for t in item.iter(f"{_MAIN}t")))
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels")).iter(f"{_PKG_REL}Relationship")
    }
    sheets: dict[str, Sheet] = {}
    for sheet in ElementTree.fromstring(archive.read("xl/workbook.xml")).iter(f"{_MAIN}sheet"):
        target = targets[sheet.get(f"{_REL}id")]
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        cells: dict[tuple[int, int], str] = {}
        for cell in ElementTree.fromstring(archive.read(path)).iter(f"{_MAIN}c"):
            kind = cell.get("t")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{_MAIN}t"))
            else:
                v = cell.find(f"{_MAIN}v")
                if v is None or v.text is None:
                    continue
                text = shared[int(v.text)] if kind == "s" else v.text
            cells[_cell_position(cell.get("r"))] = text
        sheets[sheet.get("name").strip()] = Sheet(cells)
    return sheets


def number(text: str | None) -> float | None:
    """A published numeric cell as a float; SCAD writes ':' for a suppressed or unavailable value."""
    if text is None or text.strip() in (":", "", "-"):
        return None
    return float(text)


def table_title(sheet: Sheet) -> str:
    """The English table title SCAD writes in the first labelled cell of column B."""
    return next(row[1] for row in sheet.rows() if row[1] and row[1].startswith("Table"))


def count(text: str | None) -> int:
    value = number(text)
    return 0 if value is None else int(round(value))


# --- evidence ---------------------------------------------------------------------------------------------------


def checked(publisher: str, title: str, url: str, locator: str, value, unit: str, snippet: str, license_id: str, raw: bytes, content_type: str, role: str = "primary") -> dict:
    """An evidence item whose snippet and value are confirmed against the verifier's view of the same bytes."""
    text = " ".join(Resource(url=url, content=raw, content_type=content_type).text.split())
    for needle in (snippet, str(value)):
        if " ".join(needle.split()) not in text:
            raise ValueError(f"{needle!r} not found in {url}")
    return evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role)


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def scad_evidence(title: str, url: str, raw: bytes, locator: str, value: str, unit: str, snippet: str) -> dict:
    return checked(SCAD, title, url, locator, value, unit, snippet, SCAD_LICENSE, raw, XLSX)


def shares_of(counts: dict[str, float], digits: int = 6) -> dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, digits) for k, v in counts.items()}


def quoted(*args: str) -> str:
    return ",".join(f'"{a}"' for a in args)


SCAD_ASSUMED_SHARES = {
    "method": "derived",
    "rationale": "SCAD publishes counts; each share is the count divided by the sum of the counts in its distribution.",
}


# --- Abu Dhabi consumer prices ----------------------------------------------------------------------------------

CPI_URL = f"{SCAD_DOCS}/2303931/publication_63882_322_4_18_2025_EN.xlsx/2182010c-28e1-3455-0bd4-76131ca92607"
CPI_TITLE = "SCAD, Consumer Price Index, December 2025 (Excel tables), Table 1: monthly series by group, 2022-2025 (2021=100)"

CPI_GROUPS = {
    "Food and beverages": "food_and_beverages",
    "Tobacco": "tobacco",
    "Clothing and footwear": "clothing_and_footwear",
    "Housing, water, electricity, gas and other fuels": "housing_water_electricity_gas",
    "Furnishings, household equipment and routine household maintenance": "furnishings_household_equipment",
    "Health": "health",
    "Transport": "transport",
    "Communication": "communication",
    "Recreation and culture": "recreation_and_culture",
    "Education": "education",
    "Restaurants and hotels": "restaurants_and_hotels",
    "Insurance and financial services": "insurance_and_financial_services",
    "Personal care, social protection and miscellaneous goods": "personal_care_and_miscellaneous",
}


def cpi_table(raw: bytes) -> tuple[list[str], dict[str, list[str | None]]]:
    sheet = read_workbook(raw)["Table 1"]
    rows = sheet.rows()
    years_row = next(r for r in rows if any(v == "2022" for v in r if v))
    months_row = next(r for r in rows if r[2] == "Weights")
    periods, year = [], None
    for col in range(3, len(months_row)):
        if years_row[col]:
            year = years_row[col].strip()
        if months_row[col] in MONTHS:
            periods.append((col, f"{year}-{MONTHS.index(months_row[col]) + 1:02d}"))
    table = {}
    for label in ["Consumer Price Index", *CPI_GROUPS]:
        row = sheet.find_row(label)
        table[label] = row
    return [p for _, p in periods], {label: [row[2]] + [row[col] for col, _ in periods] for label, row in table.items()}


def abu_dhabi_cpi(raw: bytes) -> list[dict]:
    periods, table = cpi_table(raw)
    headline = table["Consumer Price Index"]
    series = []
    for i, period in enumerate(periods, start=1):
        point = {"period": period, "value": float(headline[i])}
        for label, key in CPI_GROUPS.items():
            point[key] = float(table[label][i])
        series.append(point)
    first, last = periods[0], periods[-1]
    temporal = {
        "id": "ae-abu-dhabi-cpi-by-group-monthly-2022-2025",
        "title": f"Abu Dhabi consumer price index by expenditure group, monthly {first[:4]} to {last[:4]} (2021=100, SCAD)",
        "kind": "temporal",
        "domain": "economy",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": f"{first}-01", "end": f"{last}-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "inflation", "prices", "cpi", "coicop", "scad"],
        "use_cases": ["retail-demo", "pricing", "contract-indexation", "financial-planning", "synthetic-customers"],
        "spec": {"variable": "cpi_index_2021_100", "unit": "decimal", "frequency": "monthly", "columns": list(CPI_GROUPS.values()), "series": series},
        "evidence": [
            scad_evidence(CPI_TITLE, CPI_URL, raw, f"Table 1, row 'Consumer Price Index', column {last}", headline[-1], "decimal", "Table 1: Monthly series for Consumer price Index by Group, 2022-2025"),
            scad_evidence(CPI_TITLE, CPI_URL, raw, f"Table 1, row 'Transport', column {first}", table["Transport"][1], "decimal", "Housing, water, electricity, gas and other fuels"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last}]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": f"column[transport,{first}]", "expected": series[0]["transport"], "tolerance": 1e-9},
            {"statistic": f"column[restaurants_and_hotels,{last}]", "expected": series[-1]["restaurants_and_hotels"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Monthly consumer price index for the Emirate of Abu Dhabi, all items (value) and the thirteen COICOP-based "
            "expenditure groups SCAD publishes (columns), base 2021=100, not seasonally adjusted, from Table 1 of SCAD's "
            "December 2025 Consumer Price Index release. Use the group indices to drift synthetic prices by category or to "
            "index contracts; the basket weights are in ae-abu-dhabi-cpi-basket-weights. " + SCAD_TERMS_NOTE
        ),
    }
    weights = {label: float(table[label][0]) for label in CPI_GROUPS}
    total_weight = sum(weights.values())
    weight_shares = {label: round(w / total_weight, 6) for label, w in weights.items()}
    marginal = {
        "id": "ae-abu-dhabi-cpi-basket-weights",
        "title": "Abu Dhabi consumer price index basket weights by expenditure group (2021=100 series, SCAD)",
        "kind": "marginal",
        "domain": "economy",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": f"{first}-01", "end": f"{last}-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "cpi", "household-spending", "basket-weights", "coicop", "scad"],
        "use_cases": ["retail-demo", "synthetic-customers", "household-generation", "sales-generation", "market-sizing"],
        "spec": {
            "variable": "household_expenditure_group",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": weight_shares, "weights_percent": weights, "total": round(total_weight, 6)}},
        },
        "evidence": [
            scad_evidence(CPI_TITLE, CPI_URL, raw, "Table 1, column 'Weights', row 'Housing, water, electricity, gas and other fuels'", table["Housing, water, electricity, gas and other fuels"][0], "percent", "Housing, water, electricity, gas and other fuels"),
            scad_evidence(CPI_TITLE, CPI_URL, raw, "Table 1, column 'Weights', row 'Consumer Price Index'", headline[0], "percent", "Table 1: Monthly series for Consumer price Index by Group, 2022-2025"),
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "weight / sum of the thirteen group weights", "method": "derived", "rationale": "SCAD publishes each group's weight in percent of the all-items index; the shares rescale the published one-decimal weights so they sum to exactly one."},
        ],
        "tests": [
            {"statistic": 'share["Housing, water, electricity, gas and other fuels"]', "expected": weight_shares["Housing, water, electricity, gas and other fuels"], "tolerance": 0.005},
            {"statistic": 'share["Food and beverages"]', "expected": weight_shares["Food and beverages"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            "Expenditure weights of the Abu Dhabi consumer price index (2021=100 series) for its thirteen groups, from the "
            "Weights column of Table 1 in SCAD's December 2025 Consumer Price Index release. The weights describe how the "
            "average household budget in the emirate splits across categories, which makes them a ready category mix for "
            "synthetic household spending or retail baskets. Published weights (percent) ride along as weights_percent. "
            + SCAD_TERMS_NOTE
        ),
    }
    return [temporal, marginal]


# --- Abu Dhabi hotel establishments -----------------------------------------------------------------------------

HOTEL_FILES = {
    "2025-01": "2313850/publication_63660_58_4_7_2025_EN.xlsx/5a366015-70ee-520a-588b-f44d9c5563a1",
    "2025-02": "2313850/publication_63708_58_4_8_2025_EN.xlsx/9df9c63b-94c3-345d-8967-cce5042f16e9",
    "2025-03": "2313850/publication_63715_58_4_9_2025_EN.xlsx/af8878e2-c022-2bb2-21fb-ba1a3d75897c",
    "2025-04": "2313850/publication_63726_58_4_10_2025_EN.xlsx/3ac21c47-74bd-5b65-cb7a-6499dda40dfa",
    "2025-06": "2313850/publication_63777_58_4_12_2025_EN.xlsx/51f8cd33-89cb-d184-703d-9bf009f022b2",
    "2025-07": "2313850/publication_63793_58_4_13_2025_EN.xlsx/225269e7-9e5a-3a12-e2a3-68ff7987af46",
    "2025-08": "2313850/publication_63817_58_4_14_2025_EN.xlsx/332f4c81-76ca-8000-414e-0d7f24cf4853",
    "2025-09": "2313850/publication_63832_58_4_15_2025_EN.xlsx/b16b946a-5f21-78fc-a176-80e51cab0990",
    "2025-10": "2313850/publication_63847_58_4_16_2025_EN.xlsx/32a22176-97c5-8eef-d1fe-37546142b7de",
    "2025-12": "3308573/publication_63960_58_4_18_2025_EN.xlsx/8ed0a99a-f6fe-f85b-5504-ca94c458c757",
}

HOTEL_INDICATORS = {
    "Number of hotel establishments": "establishments",
    "Number of rooms": "rooms",
    "Number of guests (Thousand)": "guests_thousand",
    "Number of guest nights (Thousand Night)": "guest_nights_thousand",
    "Average length of stay (nights)": "average_length_of_stay_nights",
    "Average room rate (AED)": "average_room_rate_aed",
    "Revenue per available room (AED)": "revpar_aed",
}
HOTEL_REVENUES = {"Room revenues": "room_revenue_aed_million", "Food and beverages": "food_and_beverage_revenue_aed_million", "Other revenues": "other_revenue_aed_million"}
WORLD_REGIONS = [
    "UAE",
    "GCC",
    "Other Arab countries",
    "Asia (excluding Arab countries)",
    "Europe",
    "North and South America",
    "Africa (excluding Arab countries)",
    "Australia and New Zealand",
    "Others & Not mentioned",
]


def hotel_month_label(period: str) -> str:
    return f"{MONTHS[int(period[5:]) - 1]} {period[:4]}"


def abu_dhabi_hotels() -> list[dict]:
    series, conditional, evidence_items, guests = [], {}, [], {}
    for period, path in HOTEL_FILES.items():
        url = f"{SCAD_DOCS}/{path}"
        raw = fetch(url)
        book = read_workbook(raw)
        key_table = book["Table 1"]
        point: dict = {"period": period, "value": round(float(key_table.find_row("Occupancy rate (%)")[2]), 6)}
        for label, column in HOTEL_INDICATORS.items():
            value = float(key_table.find_row(label)[2])
            point[column] = round(value, 4)
        for label, column in HOTEL_REVENUES.items():
            point[column] = round(float(book["Table 9"].find_row(label)[2]), 4)
        series.append(point)
        regions = book["Table 4"]
        counts = {}
        for region in WORLD_REGIONS:
            counts[region] = round(float(regions.find_row(region)[2]) * 1000)
        guests[period] = counts
        conditional[period] = counts
        title = f"SCAD, Hotel Establishments Statistics, {hotel_month_label(period)} (Excel tables)"
        occupancy_raw = key_table.find_row("Occupancy rate (%)")[2]
        evidence_items.append(
            scad_evidence(title, url, raw, "Table 1, row 'Occupancy rate (%)'", occupancy_raw, "ratio", table_title(key_table))
        )
        evidence_items.append(
            scad_evidence(title, url, raw, "Table 4, row 'Europe' (thousand guests)", regions.find_row("Europe")[2], "decimal", table_title(regions))
        )
    periods = list(HOTEL_FILES)
    missing = [p for p in (f"2025-{m:02d}" for m in range(1, 13)) if p not in HOTEL_FILES]
    gap_note = (
        f" SCAD's publication list carries no monthly hotel release for {', '.join(missing)}, so those months are absent from the series."
        if missing
        else ""
    )
    hotel_evidence = [e for i, e in enumerate(evidence_items) if i % 2 == 0]
    guest_evidence = [e for i, e in enumerate(evidence_items) if i % 2 == 1]
    columns = list(HOTEL_INDICATORS.values()) + list(HOTEL_REVENUES.values())
    indicators = {
        "id": "ae-abu-dhabi-hotel-indicators-monthly-2025",
        "title": "Abu Dhabi hotel establishments: occupancy, average room rate, RevPAR, guests and revenue, monthly 2025 (SCAD)",
        "kind": "temporal",
        "domain": "tourism",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "tourism", "hotels", "occupancy", "adr", "revpar", "seasonality", "scad"],
        "use_cases": ["tourism-demo", "pricing", "demand-forecasting", "capacity-planning", "sales-generation"],
        "spec": {"variable": "hotel_occupancy_rate", "unit": "ratio", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": hotel_evidence,
        "assumed": [
            {"parameter": "series[*]", "value": "rounded to six (occupancy) or four (other columns) decimal places", "method": "derived", "rationale": "SCAD stores computed ratios and averages at full floating-point precision; the evidence records the stored value exactly."},
        ],
        "tests": [
            {"statistic": "value[2025-12]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": "column[average_room_rate_aed,2025-12]", "expected": series[-1]["average_room_rate_aed"], "tolerance": 1e-9},
            {"statistic": "column[rooms,2025-01]", "expected": series[0]["rooms"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Key indicators of hotel establishments in the Emirate of Abu Dhabi by month in 2025, from Table 1 (key "
            "indicators) and Table 9 (revenues by type, AED million) of SCAD's monthly Hotel Establishments Statistics "
            "releases, compiled by the Department of Culture and Tourism and marked preliminary. value is the occupancy "
            "rate as a ratio; average_room_rate_aed is the average daily room rate and revpar_aed the revenue per available "
            "room, both in dirhams; guests and guest nights are in thousands." + gap_note + " " + SCAD_TERMS_NOTE
        ),
    }
    distributions = {
        period: {"family": "categorical", "parameters": {"shares": shares_of(counts), "counts": counts, "total": sum(counts.values())}}
        for period, counts in conditional.items()
    }
    dec = distributions["2025-12"]["parameters"]["shares"]
    jul = distributions["2025-07"]["parameters"]["shares"]
    by_region = {
        "id": "ae-abu-dhabi-hotel-guests-by-world-region-monthly-2025",
        "title": "Abu Dhabi hotel guests by world region of nationality, given month, 2025 (SCAD)",
        "kind": "conditional",
        "domain": "tourism",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "tourism", "hotels", "source-markets", "nationality", "seasonality", "scad"],
        "use_cases": ["tourism-demo", "synthetic-customers", "customer-segmentation", "crm-demo"],
        "spec": {"variable": "guest_world_region", "unit": "ratio", "given": "month", "distributions": distributions},
        "evidence": guest_evidence,
        "assumed": [
            {"parameter": "distributions[*].parameters.counts", "value": "published thousands x 1000, rounded to whole guests", "method": "derived", "rationale": "Table 4 publishes guests in thousands with three decimals, which is a whole number of guests."},
            {"parameter": "distributions[*].parameters.shares", "value": "count / sum of the nine world-region counts", **SCAD_ASSUMED_SHARES},
        ],
        "tests": [
            {"statistic": f'share[{quoted("2025-12", "Europe")}]', "expected": dec["Europe"], "tolerance": 0.005},
            {"statistic": f'share[{quoted("2025-07", "GCC")}]', "expected": jul["GCC"], "tolerance": 0.005},
            {"statistic": 'sum_of_shares["2025-01"]', "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            "Hotel guests in the Emirate of Abu Dhabi by world region of nationality for each month of 2025 with a SCAD "
            "release, from Table 4 of the monthly Hotel Establishments Statistics (preliminary data from the Department of "
            "Culture and Tourism). Condition on the booking month to draw a guest's source market with its seasonality: GCC "
            "and other Arab guests rise in summer, European guests in the winter season. 'UAE' counts residents of the UAE "
            "of any nationality as published." + gap_note + " " + SCAD_TERMS_NOTE
        ),
    }
    return [indicators, by_region]


# --- Abu Dhabi banks --------------------------------------------------------------------------------------------

BANKS_URL = f"{SCAD_DOCS}/3350763/publication_64055_14_3_5_2026_EN.xlsx/e911c4ac-cce8-fc97-feb1-3a300769618f"
BANKS_TITLE = "SCAD, Bank Statistics, Second Quarter 2026 (Excel tables; source Central Bank of the UAE)"


def quarter_period(label: str) -> str:
    q, year = label.rstrip("*").split()
    return f"{year}-{q}"


def quarterly_rows(sheet: Sheet) -> tuple[list[str], list[str], dict[str, list[str]]]:
    rows = sheet.rows()
    header = next(r for r in rows if r[1] == "Type")
    cols = [i for i, v in enumerate(header) if v and re.match(r"Q[1-4] \d{4}", v)]
    labels = [header[i] for i in cols]
    data = {}
    for r in rows[rows.index(header) + 1 :]:
        if r[1] and r[2] is not None and number(r[2]) is not None:
            data[r[1].strip()] = [r[i] for i in cols]
    return labels, [quarter_period(label) for label in labels], data


def abu_dhabi_banks(raw: bytes) -> list[dict]:
    book = read_workbook(raw)
    preliminary_note = "Quarters marked with an asterisk in the source (the latest) are preliminary estimates."
    entries = []

    labels, periods, lending = quarterly_rows(book["Table 5"])
    lend_columns = {"Business Loans": "business_loans", "Overdrafts": "overdrafts", "Trust Receipts": "trust_receipts", "Other Loans & Advances": "other_loans_and_advances"}
    series = []
    for i, period in enumerate(periods):
        point = {"period": period, "value": round(float(lending["Personal Loans"][i]), 4)}
        for label, key in lend_columns.items():
            point[key] = round(float(lending[label][i]), 4)
        series.append(point)
    entries.append(
        {
            "id": "ae-abu-dhabi-bank-lending-rates-quarterly",
            "title": f"Average interest rates on loans by type, banks based in Abu Dhabi, quarterly {periods[0]} to {periods[-1]} (SCAD, CBUAE)",
            "kind": "temporal",
            "domain": "banking",
            "region": "AE",
            "status": "license-review",
            "tier": "A",
            "observed_period": {"start": f"{periods[0][:4]}-01-01", "end": "2026-06-30"},
            "tags": ["uae", "gcc", "abu-dhabi", "interest-rates", "lending", "personal-loans", "cbuae", "scad"],
            "use_cases": ["banking-demo", "loan-pricing", "credit-risk", "synthetic-customers"],
            "spec": {"variable": "personal_loan_rate_percent", "unit": "percent", "frequency": "quarterly", "columns": list(lend_columns.values()), "series": series},
            "evidence": [
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 5, row 'Personal Loans', column {labels[0]}", lending["Personal Loans"][0], "percent", table_title(book["Table 5"])),
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 5, row 'Overdrafts', column {labels[-1]}", lending["Overdrafts"][-1], "percent", "Trust Receipts"),
            ],
            "assumed": [{"parameter": "series[*]", "value": "rounded to four decimal places", "method": "derived", "rationale": "Some quarters are stored at full floating-point precision; the evidence records the stored value."}],
            "tests": [
                {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-9},
                {"statistic": f"column[business_loans,{periods[-1]}]", "expected": series[-1]["business_loans"], "tolerance": 1e-9},
                {"statistic": "count", "expected": len(series), "tolerance": 0},
            ],
            "notes": (
                "Average interest rate, percent a year, charged by banks based in the Emirate of Abu Dhabi on personal loans "
                "(value), business loans, overdrafts, trust receipts and other loans and advances, by quarter, from Table 5 of "
                "SCAD's Bank Statistics release (source: Central Bank of the UAE). Use as the centre of a synthetic loan-rate "
                "distribution by product. " + preliminary_note + " " + SCAD_TERMS_NOTE
            ),
        }
    )

    labels, periods, deposits = quarterly_rows(book["Table 6"])
    dep_columns = {"Up to 7 Days": "up_to_7_days", "1 Month": "one_month", "2 Months": "two_months", "3 Months": "three_months", "6 Months": "six_months", "1 Year": "one_year", "Over 1 Year": "over_one_year"}
    series = []
    for i, period in enumerate(periods):
        point = {"period": period, "value": round(float(deposits["Savings Deposit"][i]), 4)}
        for label, key in dep_columns.items():
            point[key] = round(float(deposits[label][i]), 4)
        series.append(point)
    entries.append(
        {
            "id": "ae-abu-dhabi-bank-deposit-rates-quarterly",
            "title": f"Average interest rates on savings and time deposits by tenor, banks based in Abu Dhabi, quarterly {periods[0]} to {periods[-1]} (SCAD)",
            "kind": "temporal",
            "domain": "banking",
            "region": "AE",
            "status": "license-review",
            "tier": "A",
            "observed_period": {"start": f"{periods[0][:4]}-01-01", "end": "2026-06-30"},
            "tags": ["uae", "gcc", "abu-dhabi", "interest-rates", "deposits", "savings", "cbuae", "scad"],
            "use_cases": ["banking-demo", "treasury", "personal-finance", "synthetic-customers"],
            "spec": {"variable": "savings_deposit_rate_percent", "unit": "percent", "frequency": "quarterly", "columns": list(dep_columns.values()), "series": series},
            "evidence": [
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 6, row 'Savings Deposit', column {labels[-1]}", deposits["Savings Deposit"][-1], "percent", "Savings Deposit"),
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 6, row '1 Year', column {labels[0]}", deposits["1 Year"][0], "percent", "Up to 7 Days"),
            ],
            "assumed": [{"parameter": "series[*]", "value": "rounded to four decimal places", "method": "derived", "rationale": "Most quarters are stored at full floating-point precision; the evidence records the stored value."}],
            "tests": [
                {"statistic": f"value[{periods[-1]}]", "expected": series[-1]["value"], "tolerance": 1e-9},
                {"statistic": f"column[one_year,{periods[0]}]", "expected": series[0]["one_year"], "tolerance": 1e-9},
                {"statistic": "count", "expected": len(series), "tolerance": 0},
            ],
            "notes": (
                "Average interest rate, percent a year, paid by banks based in the Emirate of Abu Dhabi on savings deposits "
                "(value) and on time deposits by tenor from up to seven days to over one year, by quarter, from Table 6 of "
                "SCAD's Bank Statistics release (source: Central Bank of the UAE). " + preliminary_note + " " + SCAD_TERMS_NOTE
            ),
        }
    )

    labels, periods, income = quarterly_rows(book["Table 1"])
    _, _, employees = quarterly_rows(book["Table 3"])
    _, _, compensation = quarterly_rows(book["Table 4"])
    net_income = income["Net income of banks based in the Emirate of Abu Dhabi"]
    staff = employees["Number of employees"]
    pay = compensation["Average compensation of employees"]
    series = [
        {"period": p, "value": round(float(net_income[i]), 3), "employees": count(staff[i]), "average_compensation_per_employee": round(float(pay[i]), 2)}
        for i, p in enumerate(periods)
    ]
    entries.append(
        {
            "id": "ae-abu-dhabi-banks-income-and-employees-quarterly",
            "title": f"Banks based in Abu Dhabi: net income, employees and average compensation per employee, quarterly {periods[0]} to {periods[-1]} (SCAD)",
            "kind": "temporal",
            "domain": "banking",
            "region": "AE",
            "status": "license-review",
            "tier": "A",
            "observed_period": {"start": f"{periods[0][:4]}-01-01", "end": "2026-06-30"},
            "tags": ["uae", "gcc", "abu-dhabi", "banks", "net-income", "headcount", "compensation", "cbuae", "scad"],
            "use_cases": ["banking-demo", "financial-reporting", "hr-analytics", "synthetic-employees"],
            "spec": {"variable": "net_income_aed_million", "unit": "currency:AED", "frequency": "quarterly", "columns": ["employees", "average_compensation_per_employee"], "series": series},
            "evidence": [
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 1, column {labels[0]} (Million AED)", net_income[0], "currency:AED", table_title(book["Table 1"])),
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 3, column {labels[-1]}", staff[-1], "count", table_title(book["Table 3"])),
                scad_evidence(BANKS_TITLE, BANKS_URL, raw, f"Table 4, column {labels[0]}", pay[0], "decimal", table_title(book["Table 4"])),
            ],
            "assumed": [{"parameter": "series[*]", "value": "net income rounded to three decimals, compensation to two", "method": "derived", "rationale": "Some quarters are stored at full floating-point precision; the evidence records the stored value."}],
            "tests": [
                {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-9},
                {"statistic": f"column[employees,{periods[-1]}]", "expected": series[-1]["employees"], "tolerance": 0},
                {"statistic": f"column[average_compensation_per_employee,{periods[0]}]", "expected": series[0]["average_compensation_per_employee"], "tolerance": 1e-9},
                {"statistic": "count", "expected": len(series), "tolerance": 0},
            ],
            "notes": (
                "Net income in AED million (value), total employees and average compensation per employee of banks based in the "
                "Emirate of Abu Dhabi by quarter, from Tables 1, 3 and 4 of SCAD's Bank Statistics release (source: Central "
                "Bank of the UAE). The release states no unit for average compensation; it is a per-worker amount in dirhams "
                "for the quarter as published and should be read as such, not as a monthly salary. " + preliminary_note + " "
                + SCAD_TERMS_NOTE
            ),
        }
    )
    return entries


# --- Abu Dhabi births -------------------------------------------------------------------------------------------

BIRTHS_URL = f"{SCAD_DOCS}/3422848/publication_64080_17_1_1_2025_EN.xlsx/5c7f95d5-08ff-000e-03c8-39d08b7c4747"
BIRTHS_TITLE = "SCAD, Birth Statistics 2025 (Excel tables; source Department of Health - Abu Dhabi)"


def citizenship_blocks(rows: list[list[str | None]]) -> dict[tuple[str, str], list[str | None]]:
    """Rows of a SCAD births table keyed by (citizenship, sex); sex rows follow their citizenship heading."""
    blocks, current = {}, None
    for r in rows:
        label = (r[1] or "").strip()
        if label in ("Emirati", "Non-Emirati", "Citizenship Not Stated*"):
            current = label.rstrip("*")
        elif current and label in ("Male", "Female"):
            blocks[(current, label)] = r
    return blocks


def abu_dhabi_births(raw: bytes) -> list[dict]:
    book = read_workbook(raw)
    monthly = book["Table 2"]
    rows = monthly.rows()
    blocks = citizenship_blocks(rows)
    total = monthly.find_row("Total")
    keys = {("Emirati", "Male"): "emirati_male", ("Emirati", "Female"): "emirati_female", ("Non-Emirati", "Male"): "non_emirati_male", ("Non-Emirati", "Female"): "non_emirati_female"}
    series = []
    for m in range(12):
        point = {"period": f"2025-{m + 1:02d}", "value": count(total[2 + m])}
        for block, key in keys.items():
            point[key] = count(blocks[block][2 + m])
        series.append(point)
    temporal = {
        "id": "ae-abu-dhabi-births-by-month-citizenship-sex-2025",
        "title": "Abu Dhabi live births by month, citizenship (Emirati, non-Emirati) and sex, 2025 (SCAD)",
        "kind": "temporal",
        "domain": "demographics",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "births", "citizenship", "sex", "seasonality", "scad"],
        "use_cases": ["synthetic-customers", "person-generation", "household-generation", "health-demo"],
        "spec": {"variable": "live_births", "unit": "count", "frequency": "monthly", "columns": list(keys.values()), "series": series},
        "evidence": [
            scad_evidence(BIRTHS_TITLE, BIRTHS_URL, raw, "Table 2, row 'Total', column 'Total'", total[14], "count", "Citizenship and Gender"),
            scad_evidence(BIRTHS_TITLE, BIRTHS_URL, raw, "Table 2, row 'Non-Emirati / Male', column January", blocks[("Non-Emirati", "Male")][2], "count", "Citizenship Not Stated*"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "value[2025-01]", "expected": series[0]["value"], "tolerance": 0},
            {"statistic": "column[emirati_female,2025-12]", "expected": series[-1]["emirati_female"], "tolerance": 0},
            {"statistic": "count", "expected": 12, "tolerance": 0},
        ],
        "notes": (
            "Live births registered in the Emirate of Abu Dhabi in 2025 by month (value is all births), with Emirati and "
            "non-Emirati births split by sex as columns, from Table 2 of SCAD's Birth Statistics 2025 (source: Department of "
            "Health - Abu Dhabi). The total also includes births with citizenship or sex not stated, which have no column. "
            "Use it to date synthetic births and to set the citizen share and sex ratio of newborns. " + SCAD_TERMS_NOTE
        ),
    }

    regional = book["Table 1"]
    rrows = regional.rows()
    header = next(r for r in rrows if r[2] and "Abu Dhabi Region" in r[2])
    region_cols = {"Abu Dhabi Region": 2, "Al Ain Region": 3, "Al Dhafra Region": 4}
    for name, col in region_cols.items():
        if name not in (header[col] or ""):
            raise ValueError(f"unexpected column layout for {name}")
    rblocks = citizenship_blocks(rrows)
    combos = {("Emirati", "Male"): "Emirati male", ("Emirati", "Female"): "Emirati female", ("Non-Emirati", "Male"): "Non-Emirati male", ("Non-Emirati", "Female"): "Non-Emirati female"}
    distributions = {}
    for region, col in region_cols.items():
        counts = {label: count(rblocks[block][col]) for block, label in combos.items()}
        distributions[region] = {"family": "categorical", "parameters": {"shares": shares_of(counts), "counts": counts, "total": sum(counts.values())}}
    ad = distributions["Abu Dhabi Region"]["parameters"]["shares"]
    dh = distributions["Al Dhafra Region"]["parameters"]["shares"]
    conditional = {
        "id": "ae-abu-dhabi-births-by-region-citizenship-sex-2025",
        "title": "Abu Dhabi live births by citizenship and sex, given region of the emirate, 2025 (SCAD)",
        "kind": "conditional",
        "domain": "demographics",
        "region": "AE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "tags": ["uae", "gcc", "abu-dhabi", "births", "citizenship", "sex", "regions", "scad"],
        "use_cases": ["synthetic-customers", "person-generation", "address-generation", "household-generation"],
        "spec": {"variable": "citizenship_and_sex", "unit": "ratio", "given": "region", "distributions": distributions},
        "evidence": [
            scad_evidence(BIRTHS_TITLE, BIRTHS_URL, raw, "Table 1, row 'Emirati / Male', column 'Abu Dhabi Region'", rblocks[("Emirati", "Male")][2], "count", table_title(book["Table 1"])),
            scad_evidence(BIRTHS_TITLE, BIRTHS_URL, raw, "Table 1, row 'Non-Emirati / Female', column 'Al Ain Region'", rblocks[("Non-Emirati", "Female")][3], "count", "Al Dhafra Region"),
        ],
        "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "count / sum of the four citizenship and sex counts", **SCAD_ASSUMED_SHARES}],
        "tests": [
            {"statistic": f'share[{quoted("Abu Dhabi Region", "Non-Emirati male")}]', "expected": ad["Non-Emirati male"], "tolerance": 0.005},
            {"statistic": f'share[{quoted("Al Dhafra Region", "Emirati female")}]', "expected": dh["Emirati female"], "tolerance": 0.005},
            {"statistic": 'sum_of_shares["Al Ain Region"]', "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            "Live births in 2025 in each of the three regions of the Emirate of Abu Dhabi (Abu Dhabi, Al Ain, Al Dhafra) "
            "split by citizenship and sex, from Table 1 of SCAD's Birth Statistics 2025. Births abroad, births with region "
            "not stated, and births with citizenship or sex not stated are left out. The Emirati share differs sharply by "
            "region, which makes the table a compact prior for the citizenship of a synthetic resident given their region. "
            + SCAD_TERMS_NOTE
        ),
    }
    return [temporal, conditional]


# --- Abu Dhabi building permits and completions -----------------------------------------------------------------

BUILDING_URL = f"{SCAD_DOCS}/3369624/publication_64093_18_3_5_2026_EN.xlsx/e2462bc4-1828-fdda-e555-a645b37cb999"
BUILDING_TITLE = "SCAD, Building Completion Statistics, Second Quarter 2026 (Excel tables; source Department of Municipalities and Transport)"
AD_REGIONS = {"Abu Dhabi Region": 2, "Al Ain Region": 3, "Al Dhafra Region": 4}


def region_table(sheet: Sheet, categories: list[str]) -> dict[str, dict[str, int]]:
    header = next(r for r in sheet.rows() if r[2] == "Abu Dhabi Region")
    for name, col in AD_REGIONS.items():
        if header[col] != name:
            raise ValueError(f"unexpected column layout for {name}")
    return {region: {c: count(sheet.find_row(c)[col]) for c in categories} for region, col in AD_REGIONS.items()}


def abu_dhabi_buildings(raw: bytes) -> list[dict]:
    book = read_workbook(raw)
    usages = ["Residential", "Commercial", "Industrial", "Public facilities", "Agricultural", "Other"]
    permits = region_table(book["Table 2"], usages)
    construction = ["New building", "Additions", "Other - Modification"]
    completions = region_table(book["Table 3"], construction)
    q_note = "SCAD marks 2026 data as preliminary."

    def distributions(table: dict[str, dict[str, int]]) -> dict:
        return {r: {"family": "categorical", "parameters": {"shares": shares_of(c), "counts": c, "total": sum(c.values())}} for r, c in table.items()}

    permit_d = distributions(permits)
    completion_d = distributions(completions)
    return [
        {
            "id": "ae-abu-dhabi-building-permits-by-usage-and-region-2026q2",
            "title": "Abu Dhabi building permits issued by building usage, given region, second quarter 2026 (SCAD)",
            "kind": "conditional",
            "domain": "property",
            "region": "AE",
            "status": "license-review",
            "tier": "A",
            "observed_period": {"start": "2026-04-01", "end": "2026-06-30"},
            "tags": ["uae", "gcc", "abu-dhabi", "construction", "building-permits", "property", "regions", "scad"],
            "use_cases": ["proptech-demo", "property-demo", "market-sizing", "insurance"],
            "spec": {"variable": "building_usage", "unit": "ratio", "given": "region", "distributions": permit_d},
            "evidence": [
                scad_evidence(BUILDING_TITLE, BUILDING_URL, raw, "Table 2, row 'Residential', column 'Abu Dhabi Region'", book["Table 2"].find_row("Residential")[2], "count", table_title(book["Table 2"])),
                scad_evidence(BUILDING_TITLE, BUILDING_URL, raw, "Table 2, row 'Commercial', column 'Al Ain Region'", book["Table 2"].find_row("Commercial")[3], "count", "Public facilities"),
            ],
            "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "count / sum of the six usage counts", **SCAD_ASSUMED_SHARES}],
            "tests": [
                {"statistic": f'share[{quoted("Abu Dhabi Region", "Residential")}]', "expected": permit_d["Abu Dhabi Region"]["parameters"]["shares"]["Residential"], "tolerance": 0.005},
                {"statistic": f'share[{quoted("Al Ain Region", "Commercial")}]', "expected": permit_d["Al Ain Region"]["parameters"]["shares"]["Commercial"], "tolerance": 0.005},
                {"statistic": 'sum_of_shares["Al Dhafra Region"]', "expected": 1, "tolerance": 1e-4},
            ],
            "notes": (
                "Building permits issued in the Emirate of Abu Dhabi in the second quarter of 2026 by building usage "
                "(residential, commercial, industrial, public facilities, agricultural, other) for each region, from Table 2 "
                "of SCAD's Building Completion Statistics. Use it to give synthetic construction projects or new property "
                "listings a realistic usage mix by region. " + q_note + " " + SCAD_TERMS_NOTE
            ),
        },
        {
            "id": "ae-abu-dhabi-building-completions-by-type-and-region-2026q2",
            "title": "Abu Dhabi building completions by type of construction, given region, second quarter 2026 (SCAD)",
            "kind": "conditional",
            "domain": "property",
            "region": "AE",
            "status": "license-review",
            "tier": "A",
            "observed_period": {"start": "2026-04-01", "end": "2026-06-30"},
            "tags": ["uae", "gcc", "abu-dhabi", "construction", "building-completions", "property", "regions", "scad"],
            "use_cases": ["proptech-demo", "property-demo", "market-sizing"],
            "spec": {"variable": "construction_type", "unit": "ratio", "given": "region", "distributions": completion_d},
            "evidence": [
                scad_evidence(BUILDING_TITLE, BUILDING_URL, raw, "Table 3, row 'New building', column 'Abu Dhabi Region'", book["Table 3"].find_row("New building")[2], "count", table_title(book["Table 3"])),
            ],
            "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "count / sum of the three construction-type counts", **SCAD_ASSUMED_SHARES}],
            "tests": [
                {"statistic": f'share[{quoted("Abu Dhabi Region", "New building")}]', "expected": completion_d["Abu Dhabi Region"]["parameters"]["shares"]["New building"], "tolerance": 0.005},
                {"statistic": f'share[{quoted("Al Ain Region", "Other - Modification")}]', "expected": completion_d["Al Ain Region"]["parameters"]["shares"]["Other - Modification"], "tolerance": 0.005},
                {"statistic": 'sum_of_shares["Al Dhafra Region"]', "expected": 1, "tolerance": 1e-4},
            ],
            "notes": (
                "Buildings completed in the Emirate of Abu Dhabi in the second quarter of 2026 by type of construction (new "
                "building, additions, other modification) for each region, from Table 3 of SCAD's Building Completion "
                "Statistics. " + q_note + " " + SCAD_TERMS_NOTE
            ),
        },
    ]


# --- Central Bank of the UAE: aggregated bank liabilities (Bayanat) ---------------------------------------------

LIABILITIES_URL = BAYANAT + "VyUxgSp1_0Dt4g1TivZs-2auHqV6G5KZULT8X3LwhGE"
LIABILITIES_META_URL = BAYANAT + "91uqDpwGqVDn7o6ae_2etN3uwON-eOqUNuyAXfstA84"
CBUAE = "Central Bank of the UAE (published on Bayanat)"


def cbuae_liabilities(raw: bytes, meta_raw: bytes) -> list[dict]:
    root = ElementTree.fromstring(raw)
    records = []
    for row in root.iter("row"):
        fields = {child.tag: (child.text or "").strip() for child in row}
        records.append(fields)
    year, month = records[0]["Year"], records[0]["Month"]
    period_month = MONTHS.index(month[:3]) + 1
    rows = {}
    for r in records:
        key = r["Third_Cat"] if r["Third_Cat"] == r["Second_Cat"] else f"{r['Second_Cat']}: {r['Third_Cat']}"
        rows[key] = {"main_category": r["Main_Cat"], "amount": float(r["Amount"])}
    deposit_parts = {
        "Demand deposits (LCY)": rows["Monetary Deposits: Demand Deposits (LCY)"]["amount"],
        "Time deposits (LCY)": rows["Quasi Monetary Deposits: Time Deposits (LCY)"]["amount"],
        "Savings deposits (LCY)": rows["Quasi Monetary Deposits: Savings Deposits (LCY)"]["amount"],
        "Other deposits (FCY)": rows["Quasi Monetary Deposits: Other Deposits (FCY)"]["amount"],
        "Government deposits (LCY + FCY)": rows["Government Deposits (LCY + FCY)"]["amount"],
        "Other domestic deposits (LCY + FCY)": rows["Other Domestic Deposits (LCY + FCY)"]["amount"],
        "Non-resident deposits (LCY + FCY)": rows["Other Deposits (LCY + FCY)"]["amount"],
    }
    last_day = {2: 28}.get(period_month, 30 if period_month in (4, 6, 9, 11) else 31)
    period = f"{year}-{period_month:02d}"
    title = f"CBUAE Banks Aggregated Balance Sheet - Liabilities (All Banks), {month} {year} (XML, Bayanat)"
    meta_title = f"CBUAE Banks Aggregated Balance Sheet - Metadata - Liabilities (All Banks), {month} {year} (Bayanat)"

    def item(locator: str, value: str, snippet: str) -> dict:
        return checked(CBUAE, title, LIABILITIES_URL, locator, value, "decimal", snippet, BAYANAT_LICENSE, raw, "text/xml")

    meta = checked(CBUAE, meta_title, LIABILITIES_META_URL, "Metadata sheet, field 'Calculation methodology'", "IMF's Monetary and Financial Statistics Manual and Compilation Guide", "text", "IMF's Monetary and Financial Statistics Manual and Compilation Guide", BAYANAT_LICENSE, meta_raw, XLSX, role="supporting")
    raw_amount = {r["Third_Cat"]: r["Amount"] for r in records}
    lookup = {
        "id": f"ae-banks-aggregated-liabilities-{period}",
        "title": f"UAE banks aggregated balance sheet liabilities by category, all banks, end of {MONTH_NAMES[period_month - 1]} {year} (CBUAE)",
        "kind": "rule",
        "domain": "banking",
        "region": "AE",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{period}-{last_day:02d}",
        "valid_to": f"{period}-{last_day:02d}",
        "tags": ["uae", "gcc", "banks", "balance-sheet", "deposits", "liabilities", "cbuae", "reference-table"],
        "use_cases": ["banking-demo", "treasury", "financial-reporting", "market-sizing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"dataset": "Banks Aggregated Balance Sheet - Liabilities (All Banks)", "period": period, "rows": rows},
            "vectors": [
                {"input": {"key": "Quasi Monetary Deposits: Savings Deposits (LCY)", "column": "amount"}, "expected": rows["Quasi Monetary Deposits: Savings Deposits (LCY)"]["amount"], "origin": "source"},
                {"input": {"key": "Total Liabilities", "column": "amount"}, "expected": rows["Total Liabilities"]["amount"], "origin": "source"},
                {"input": "Equity", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            item("row Third_Cat='Savings Deposits (LCY)', Amount", raw_amount["Savings Deposits (LCY)"], "<Third_Cat>Savings Deposits (LCY)</Third_Cat>"),
            item("row Third_Cat='Total Liabilities', Amount", raw_amount["Total Liabilities"], "<Third_Cat>Total Liabilities</Third_Cat>"),
            meta,
        ],
        "assumed": [
            {"parameter": "parameters.rows keys", "value": "Third_Cat, prefixed with Second_Cat when the two differ", "method": "derived", "rationale": "The source repeats a category name at several levels (subtotals carry the same name at the second and third level); prefixing keeps keys unique."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
        ],
        "notes": (
            f"Liabilities side of the aggregated balance sheet of all banks operating in the UAE at the end of {month} {year}, "
            "by category: domestic monetary deposits (demand deposits and bankers' drafts), quasi-monetary deposits (time and "
            "savings deposits in dirhams, other deposits in foreign currency), government and other domestic deposits, "
            "amounts due to the central bank and resident banks, capital market funding, foreign liabilities including "
            "non-resident deposits, capital and reserves, provisions and other liabilities, with subtotals and the total. "
            "Compiled by the Central Bank of the UAE under the IMF Monetary and Financial Statistics Manual. The dataset "
            "states no unit; CBUAE monetary statistics report balance-sheet amounts in AED million, so treat amounts as such "
            "only after checking the CBUAE bulletin. LCY is local currency (dirham) and FCY foreign currency. "
            + BAYANAT_TERMS_NOTE
        ),
    }
    shares = shares_of(deposit_parts)
    mix = {
        "id": f"ae-bank-deposit-mix-{period}",
        "title": f"UAE bank deposits by type and residency, all banks, end of {MONTH_NAMES[period_month - 1]} {year} (CBUAE)",
        "kind": "marginal",
        "domain": "banking",
        "region": "AE",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{period}-{last_day:02d}", "end": f"{period}-{last_day:02d}"},
        "tags": ["uae", "gcc", "banks", "deposits", "account-types", "residents", "non-residents", "cbuae"],
        "use_cases": ["banking-demo", "synthetic-customers", "customer-segmentation", "fintech-demo"],
        "spec": {
            "variable": "deposit_type",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": shares, "amounts": deposit_parts, "total": round(sum(deposit_parts.values()), 6)}},
        },
        "evidence": [
            item("row Third_Cat='Demand Deposits (LCY)', Amount", raw_amount["Demand Deposits (LCY)"], "<Third_Cat>Demand Deposits (LCY)</Third_Cat>"),
            item("row Third_Cat='Time Deposits (LCY)', Amount", raw_amount["Time Deposits (LCY)"], "<Third_Cat>Time Deposits (LCY)</Third_Cat>"),
            item("row Main_Cat='Foreign Liabilities', Third_Cat='Other Deposits (LCY + FCY)', Amount", raw_amount["Other Deposits (LCY + FCY)"], "<Third_Cat>Other Deposits (LCY + FCY)</Third_Cat>"),
            meta,
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "amount / sum of the seven deposit amounts", "method": "derived", "rationale": "CBUAE publishes balances; the shares are each deposit balance over the sum of the deposit balances listed. Non-resident deposits are the 'Other Deposits (LCY + FCY)' line under Foreign Liabilities."},
        ],
        "tests": [
            {"statistic": 'share["Demand deposits (LCY)"]', "expected": shares["Demand deposits (LCY)"], "tolerance": 0.005},
            {"statistic": 'share["Non-resident deposits (LCY + FCY)"]', "expected": shares["Non-resident deposits (LCY + FCY)"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            f"Balance-weighted mix of deposits held with UAE banks at the end of {month} {year}: resident deposits in dirhams "
            "split into demand, time and savings deposits, resident foreign-currency deposits, government deposits, other "
            "domestic deposits, and non-resident deposits. Shares weight by balance, not by number of accounts, so use them "
            "for the split of a synthetic bank's deposit book rather than for account counts. Source: CBUAE Banks Aggregated "
            "Balance Sheet - Liabilities (All Banks). " + BAYANAT_TERMS_NOTE
        ),
    }
    return [lookup, mix]


# --- Ministry of Interior: vehicles and driving licences (Bayanat) ----------------------------------------------

VEHICLES_URL = BAYANAT + "PZ7PAVb0neBeqzk7BI7mXSt6AnsbpTXzxhPV20wbwdA"
LICENCES_URL = BAYANAT + "WecTNrdOR_Un6Dw6IwG4KvsnGSEyPY9O35HLD-mSRAo"
MOI = "Ministry of Interior (published on Bayanat)"
# The dataset spells one vehicle type two ways (with and without the hamza on the alef of "and over").
VEHICLE_TYPE_SPELLINGS = {"شحن ثقيل 12 طن فاكثر": "شحن ثقيل 12 طن فأكثر"}


def moi_vehicles(raw: bytes) -> list[dict]:
    rows = read_workbook(raw)["Data Set"].rows()
    if [c.strip() for c in rows[0][:4]] != ["Year", "Vehicle type", "Vehicle color", "Total"]:
        raise ValueError("unexpected vehicle dataset header")
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    year = None
    for r in rows[1:]:
        if r[0] is None:
            continue
        year = r[0]
        vehicle_type = VEHICLE_TYPE_SPELLINGS.get(r[1].strip(), r[1].strip())
        by_type[vehicle_type][r[2].strip()] += count(r[3])
    year = str(int(float(year)))
    type_totals = {t: sum(c.values()) for t, c in by_type.items()}
    type_totals = dict(sorted(type_totals.items(), key=lambda kv: -kv[1]))
    distributions = {
        t: {"family": "categorical", "parameters": {"shares": shares_of(dict(sorted(by_type[t].items(), key=lambda kv: -kv[1]))), "counts": dict(sorted(by_type[t].items(), key=lambda kv: -kv[1])), "total": type_totals[t]}}
        for t in type_totals
    }
    top_type = next(iter(type_totals))
    top_colour = next(iter(distributions[top_type]["parameters"]["counts"]))
    first = rows[1]
    title = f"MOI Registered vehicles {year}: vehicle type by colour (Excel, Bayanat)"
    ev = [
        checked(MOI, title, VEHICLES_URL, "Data Set sheet, header row", "Vehicle color", "text", "Total number of vehicles registered in the country", BAYANAT_LICENSE, raw, XLSX),
        checked(MOI, title, VEHICLES_URL, f"Data Set sheet, row 2 ({first[1].strip()}, {first[2].strip()}), column Total", first[3], "count", "The year in which the vehicle was registered", BAYANAT_LICENSE, raw, XLSX),
    ]
    type_shares = shares_of(type_totals)
    note_tail = (
        " Labels are kept in Arabic exactly as the Ministry publishes them (the dataset gives no English labels). Rows "
        "repeated for the same type and colour in the source are summed. " + BAYANAT_TERMS_NOTE
    )
    second_type = list(type_totals)[1]
    return [
        {
            "id": f"ae-registered-vehicles-by-type-{year}",
            "title": f"UAE vehicles registered in {year} by vehicle type (Ministry of Interior)",
            "kind": "marginal",
            "domain": "automotive",
            "region": "AE",
            "status": "verified",
            "tier": "A",
            "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
            "tags": ["uae", "gcc", "vehicles", "registrations", "vehicle-type", "moi"],
            "use_cases": ["fleet-demo", "automotive-demo", "insurance", "synthetic-customers"],
            "spec": {"variable": "vehicle_type", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": type_shares, "counts": type_totals, "total": sum(type_totals.values())}}},
            "evidence": ev,
            "assumed": [{"parameter": "distribution.parameters.counts", "value": "sum over colours of each vehicle type", "method": "derived", "rationale": "The Ministry publishes registrations by type and colour; type totals are the sum of the type's rows, and shares are totals over the grand total."},
                {"parameter": "vehicle type labels", "value": VEHICLE_TYPE_SPELLINGS, "method": "derived", "rationale": "The source spells the heavy cargo 12 tonnes and over type two ways; rows under the variant spelling are counted under the common one."},
            ],
            "tests": [
                {"statistic": f'share["{top_type}"]', "expected": type_shares[top_type], "tolerance": 0.005},
                {"statistic": f'share["{second_type}"]', "expected": type_shares[second_type], "tolerance": 0.005},
                {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
            ],
            "notes": f"Vehicles registered in the UAE in {year} by vehicle type, from the Ministry of Interior's federal traffic system dataset 'Registered vehicles {year}'." + note_tail,
        },
        {
            "id": f"ae-registered-vehicles-colour-by-type-{year}",
            "title": f"UAE vehicles registered in {year}: colour given vehicle type (Ministry of Interior)",
            "kind": "conditional",
            "domain": "automotive",
            "region": "AE",
            "status": "verified",
            "tier": "A",
            "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
            "tags": ["uae", "gcc", "vehicles", "registrations", "vehicle-colour", "moi"],
            "use_cases": ["fleet-demo", "automotive-demo", "insurance", "synthetic-customers"],
            "spec": {"variable": "vehicle_colour", "unit": "ratio", "given": "vehicle_type", "distributions": distributions},
            "evidence": ev,
            "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "count / type total", "method": "derived", "rationale": "Shares are each colour's registrations over the type's registrations; duplicate type and colour rows are summed first."},
                {"parameter": "vehicle type labels", "value": VEHICLE_TYPE_SPELLINGS, "method": "derived", "rationale": "The source spells the heavy cargo 12 tonnes and over type two ways; rows under the variant spelling are counted under the common one."},
            ],
            "tests": [
                {"statistic": f'share[{quoted(top_type, top_colour)}]', "expected": distributions[top_type]["parameters"]["shares"][top_colour], "tolerance": 0.005},
                {"statistic": f'sum_of_shares["{top_type}"]', "expected": 1, "tolerance": 1e-4},
            ],
            "notes": f"Colour of vehicles registered in the UAE in {year}, conditioned on vehicle type, from the Ministry of Interior dataset 'Registered vehicles {year}'. Draw a type from ae-registered-vehicles-by-type-{year}, then a colour from this table." + note_tail,
        },
    ]


def moi_licences(raw: bytes) -> dict:
    rows = read_workbook(raw)["Data Set"].rows()
    labels = rows[1]
    data = next(r for r in rows[2:] if r[0])
    year = str(int(float(data[0])))
    if (labels[1], labels[2]) != ("Male", "Female"):
        raise ValueError("unexpected licence dataset layout")
    counts = {"male": count(data[1]), "female": count(data[2])}
    if counts["male"] + counts["female"] != count(data[3]):
        raise ValueError("licence counts do not add to the published total")
    shares = shares_of(counts)
    title = f"MOI Registered (new) licenses by gender {year} (Excel, Bayanat)"
    return {
        "id": f"ae-new-driving-licences-by-sex-{year}",
        "title": f"UAE new driving licences issued in {year} by sex (Ministry of Interior)",
        "kind": "marginal",
        "domain": "automotive",
        "region": "AE",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": ["uae", "gcc", "driving-licences", "sex", "moi"],
        "use_cases": ["synthetic-customers", "person-generation", "insurance", "fleet-demo"],
        "spec": {"variable": "sex", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": count(data[3])}}},
        "evidence": [
            checked(MOI, title, LICENCES_URL, "Data Set sheet, row 3, column Male", data[1], "count", "Male", BAYANAT_LICENSE, raw, XLSX),
            checked(MOI, title, LICENCES_URL, "Data Set sheet, row 3, column Total", data[3], "count", "Female", BAYANAT_LICENSE, raw, XLSX),
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "count / total", "method": "derived", "rationale": "The Ministry publishes counts by sex and their total; shares are their ratio."}],
        "tests": [
            {"statistic": "share[female]", "expected": shares["female"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            f"New driving licences registered in the UAE in {year} by holder's sex, from the Ministry of Interior dataset "
            f"'Registered (new) licenses by gender {year}'. Use the female share when assigning licences to synthetic adults. "
            + BAYANAT_TERMS_NOTE
        ),
    }


# --- FCSC unemployment rates (Bayanat) --------------------------------------------------------------------------

UNEMPLOYMENT_URL = BAYANAT + "rxMuitcKamCo79i_pjKJZEEPMKDvx_Cb4aPo5H9g7RM"
FCSC = "Federal Competitiveness and Statistics Centre (published on Bayanat)"


def fcsc_unemployment(raw: bytes) -> dict:
    rows = read_workbook(raw)["Sheet1"].rows()
    if [c.strip() for c in rows[0][:5]] != ["Year", "Age", "Nationality", "Gender", "Value"]:
        raise ValueError("unexpected unemployment dataset header")
    year = max(int(float(r[0])) for r in rows[1:] if r[0])
    table, raw_values = {}, {}
    for r in rows[1:]:
        if not r[0] or int(float(r[0])) != year:
            continue
        key = f"{r[2].strip()}|{r[3].strip()}|{r[1].strip()}"
        table[key] = {"nationality": r[2].strip(), "sex": r[3].strip(), "age_group": r[1].strip(), "unemployment_rate": round(float(r[4]), 6)}
        raw_values[key] = r[4]
    k1, k2 = "Citizen|Female|20 - 24", "Non-Citizen|Total|Total"
    title = "FCSC Unemployment rate by nationality, age and gender, 2016-2018 (Excel, Bayanat)"
    return {
        "id": f"ae-unemployment-rate-by-nationality-age-sex-{year}",
        "title": f"UAE unemployment rate by nationality (citizen, non-citizen), age group and sex, {year} (FCSC)",
        "kind": "rule",
        "domain": "employment",
        "region": "AE",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "tags": ["uae", "gcc", "unemployment", "labour-force", "nationality", "age", "sex", "fcsc", "reference-table"],
        "use_cases": ["synthetic-employees", "synthetic-customers", "hr-analytics", "credit-risk", "workforce-planning"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key_format": "nationality|sex|age_group", "unit": "ratio of the labour force", "rows": table},
            "vectors": [
                {"input": {"key": k1, "column": "unemployment_rate"}, "expected": table[k1]["unemployment_rate"], "origin": "source"},
                {"input": {"key": k2, "column": "unemployment_rate"}, "expected": table[k2]["unemployment_rate"], "origin": "source"},
                {"input": "Citizen|Male|70 - 74", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            checked(FCSC, title, UNEMPLOYMENT_URL, f"Sheet1, Year={year}, Age='20 - 24', Nationality=Citizen, Gender=Female", raw_values[k1], "ratio", "Non-Citizen", BAYANAT_LICENSE, raw, XLSX),
            checked(FCSC, title, UNEMPLOYMENT_URL, f"Sheet1, Year={year}, Age=Total, Nationality=Non-Citizen, Gender=Total", raw_values[k2], "ratio", "15 - 19", BAYANAT_LICENSE, raw, XLSX),
        ],
        "assumed": [{"parameter": "rows[*].unemployment_rate", "value": "rounded to six decimal places", "method": "derived", "rationale": "The dataset stores rates at full floating-point precision; the evidence records the stored value."}],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
        ],
        "notes": (
            f"Unemployment rate (unemployed as a ratio of the labour force) in the UAE in {year} by nationality (Citizen, "
            "Non-Citizen, Total), sex (Male, Female, Total) and five-year age group from 15 - 19 to 65 +, with totals, from the "
            "Federal Competitiveness and Statistics Centre labour force survey dataset 'Unemployment rate by nationality, age "
            f"and gender' (2016-2018). {year} is the latest year the federal open data portal carries for this breakdown. "
            "Keys are nationality|sex|age_group. The gap between citizen and non-citizen rates is large and should drive the "
            "employment status of synthetic residents by nationality. " + BAYANAT_TERMS_NOTE
        ),
    }


def main() -> int:
    for entry in abu_dhabi_cpi(fetch(CPI_URL)):
        write(entry)
    for entry in abu_dhabi_hotels():
        write(entry)
    for entry in abu_dhabi_banks(fetch(BANKS_URL)):
        write(entry)
    for entry in abu_dhabi_births(fetch(BIRTHS_URL)):
        write(entry)
    for entry in abu_dhabi_buildings(fetch(BUILDING_URL)):
        write(entry)
    for entry in cbuae_liabilities(fetch(LIABILITIES_URL), fetch(LIABILITIES_META_URL)):
        write(entry)
    for entry in moi_vehicles(fetch(VEHICLES_URL)):
        write(entry)
    write(moi_licences(fetch(LICENCES_URL)))
    write(fcsc_unemployment(fetch(UNEMPLOYMENT_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

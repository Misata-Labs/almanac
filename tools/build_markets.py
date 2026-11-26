"""Regenerate the markets entries: industry activity, pricing-power and leading-indicator series.

The entries are monthly or quarterly temporal series over closed periods that portfolio monitoring,
value-creation plans and synthetic KPI series are benchmarked against:

- Federal Reserve G.17: industrial production by market group and by NAICS industry, and capacity
  utilization, through Data Download Program packages pinned to 2023-01..2025-12.
- US Census Bureau economic indicators: manufacturers' shipments, new orders and inventory ratios (M3),
  Quarterly Services Survey revenue, monthly retail sales and inventory ratios, business inventories,
  construction spending, new residential construction, and the quarterly e-commerce share of retail.
- Eurostat short-term business statistics: industrial production, services turnover, producer prices
  and retail trade volume.
- OECD: composite leading indicators, business confidence and consumer confidence.
- ONS: monthly GDP by industry and the Business Insights and Conditions Survey expectations.

Run from the repository root:

    uv run python tools/build_markets.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

START_YEAR, END_YEAR = 2023, 2025
MONTHS = [f"{y}-{m:02d}" for y in range(START_YEAR, END_YEAR + 1) for m in range(1, 13)]
QUARTERS = [f"{y}-Q{q}" for y in range(START_YEAR, END_YEAR + 1) for q in range(1, 5)]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PE_USE_CASES = ["pe-portfolio-demo", "valuation-demo", "forecasting-demo"]
BASE_TAGS = ["economy", "industry", "kpis"]

FED = "Board of Governors of the Federal Reserve System"
CENSUS = "U.S. Census Bureau"
EUROSTAT = "Eurostat"
OECD = "OECD"
ONS = "Office for National Statistics"

UNSTATED_US = (
    "The publisher is a US federal body and the resource carries no licence statement, so the licence is recorded "
    "as unstated and the entry held at license-review."
)
UNSTATED_OECD = (
    "The OECD resource carries no licence statement and the OECD terms page is not byte-stable, so the licence is "
    "recorded as unstated and the entry held at license-review until a reviewer confirms the terms for OECD data."
)
EUROSTAT_LICENSE_NOTE = (
    "Eurostat's copyright notice states that its data are released under the Creative Commons Attribution 4.0 "
    "International licence; the notice page renders dynamically and is referenced rather than hashed."
)
ONS_LICENSE_URL = "https://api.beta.ons.gov.uk/v1/datasets/cpih01"


# ---------------------------------------------------------------------------------------------------------------
# Resources and evidence


@dataclass
class Source:
    """A fetched resource together with the text the verifier searches for snippets and values."""

    url: str
    raw: bytes
    text: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.raw:
            raise RuntimeError(f"{self.url} returned an empty body")
        self.text = " ".join(Resource(url=self.url, content=self.raw, content_type="").text.split())

    def require(self, fragment: str) -> str:
        """Return ``fragment`` after confirming it appears, whitespace-collapsed, in the searchable text."""
        if " ".join(fragment.split()) not in self.text:
            raise AssertionError(f"{fragment!r} not found in {self.url}")
        return fragment


def load(url: str) -> Source:
    return Source(url, fetch(url))


def cite(source: Source, publisher: str, title: str, locator: str, value, unit: str, snippet: str, license_id: str, role: str = "primary") -> dict:
    source.require(snippet)
    source.require(str(value))
    return evidence(publisher, title, source.url, locator, value, unit, snippet, license_id, source.raw, role)


def number(text: str) -> float | int:
    """Parse a published figure, keeping whole numbers as integers so the YAML mirrors the source."""
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


# ---------------------------------------------------------------------------------------------------------------
# Temporal entry assembly


@dataclass
class Panel:
    """Period-keyed values for a primary series and named companion columns."""

    periods: list[str]
    primary: dict[str, float]
    columns: dict[str, dict[str, float]]
    dropped: list[str] = field(default_factory=list)

    def complete(self) -> Panel:
        """Drop companion columns with a gap in the window; the primary series must be complete."""
        missing = [p for p in self.periods if p not in self.primary]
        if missing:
            raise AssertionError(f"primary series lacks {missing}")
        kept = {name: values for name, values in self.columns.items() if all(p in values for p in self.periods)}
        dropped = [name for name in self.columns if name not in kept]
        for name in dropped:
            print(f"  dropped column {name}: gaps in the window")
        return Panel(self.periods, self.primary, kept, dropped)

    def series(self) -> list[dict]:
        return [{"period": p, "value": self.primary[p], **{name: values[p] for name, values in self.columns.items()}} for p in self.periods]


def temporal(
    entry_id: str,
    title: str,
    region: str,
    status: str,
    variable: str,
    unit: str,
    frequency: str,
    panel: Panel,
    observed: tuple[str, str],
    evidence_items: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str],
    assumed: list[dict] | None = None,
    domain: str = "economy",
) -> dict:
    panel = panel.complete()
    if len(title) > 140:
        raise AssertionError(f"title of {entry_id} is {len(title)} characters")
    series = panel.series()
    first, last = series[0], series[-1]
    values = [point["value"] for point in series]
    tests = [
        {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
        {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
        {"statistic": "max", "expected": max(values), "tolerance": 1e-9},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    for name in list(panel.columns)[:2]:
        tests.append({"statistic": f"column[{name},{last['period']}]", "expected": last[name], "tolerance": 1e-9})
    if panel.dropped:
        notes += f" Columns left out because the source has gaps in the window: {', '.join(panel.dropped)}."
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": "A",
        "observed_period": {"start": observed[0], "end": observed[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": list(panel.columns), "series": series},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": tests,
        "notes": notes,
    }


MONTHLY_WINDOW = (f"{START_YEAR}-01-01", f"{END_YEAR}-12-31")


# ---------------------------------------------------------------------------------------------------------------
# Federal Reserve G.17 (Data Download Program packages)

G17_PACKAGE = (
    "https://www.federalreserve.gov/datadownload/Output.aspx?rel=G17&series={package}&lastobs="
    "&from=01/01/2023&to=12/31/2025&filetype=csv&label=include&layout=seriescolumn&type=package"
)
G17_TABLE4 = "5d88c03b0036f0334d78f6bafefc5101"  # Table 4: industrial production, market and industry groups
G17_TABLE7 = "f213ee970e317c0f3cc80e775d35b8e5"  # Table 7: capacity utilization

G17_MARKET_GROUPS = {
    "B50030": "final_products_and_nonindustrial_supplies",
    "B51000": "consumer_goods",
    "B51100": "durable_consumer_goods",
    "B51110": "automotive_products",
    "B51121": "computers_video_audio_equipment",
    "B51122": "appliances_furniture_carpeting",
    "B51123": "miscellaneous_durable_goods",
    "B51200": "nondurable_consumer_goods",
    "B51211": "foods_and_tobacco",
    "B51212": "clothing",
    "B51213": "chemical_products",
    "B51214": "paper_products",
    "B51220": "consumer_energy_products",
    "B52100": "business_equipment",
    "B52110": "transit_equipment",
    "B52120": "information_processing_equipment",
    "B52130": "industrial_and_other_equipment",
    "B52300": "defense_and_space_equipment",
    "B54100": "construction_supplies",
    "B54200": "business_supplies",
    "B53000": "materials",
    "B53100": "durable_goods_materials",
    "B53200": "nondurable_goods_materials",
    "B53300": "energy_materials",
}
G17_INDUSTRIES = {
    "GMFD": "durable_manufacturing",
    "G321": "wood_product_321",
    "G327": "nonmetallic_mineral_product_327",
    "G331": "primary_metal_331",
    "G332": "fabricated_metal_product_332",
    "G333": "machinery_333",
    "G334": "computer_and_electronic_product_334",
    "G335": "electrical_equipment_335",
    "G3361T3": "motor_vehicles_and_parts_3361_3",
    "G3364T9": "aerospace_and_other_transportation_3364_9",
    "G337": "furniture_337",
    "G339": "miscellaneous_manufacturing_339",
    "GMFN": "nondurable_manufacturing",
    "G311A2": "food_beverage_tobacco_311_312",
    "G313A4": "textiles_313_314",
    "G315A6": "apparel_and_leather_315_316",
    "G322": "paper_322",
    "G323": "printing_323",
    "G324": "petroleum_and_coal_324",
    "G325": "chemical_325",
    "G326": "plastics_and_rubber_326",
    "G21": "mining_21",
    "G2211A2": "electric_and_gas_utilities_2211_2212",
}
G17_UTILIZATION = {
    "GMF": "manufacturing_naics",
    "GMFD": "durable_manufacturing",
    "GMFN": "nondurable_manufacturing",
    **{code: name for code, name in G17_INDUSTRIES.items() if code not in ("GMFD", "GMFN")},
    "G3344": "semiconductor_and_electronic_component_3344",
    "B5610C": "crude_processing",
    "B562A3C": "primary_and_semifinished_processing",
    "B5640C": "finished_processing",
}


def g17_frame(source: Source) -> tuple[dict[str, str], dict[str, dict[str, float]], dict[str, str]]:
    """Parse a seriescolumn package into descriptions by series id, values by series and period, and raw rows."""
    rows = list(csv.reader(io.StringIO(source.raw.decode("utf-8"))))
    ids = rows[5][1:]
    descriptions = dict(zip(ids, rows[0][1:]))
    values: dict[str, dict[str, float]] = {sid: {} for sid in ids}
    raw_rows: dict[str, str] = {}
    for line, row in zip(source.raw.decode("utf-8").splitlines()[6:], rows[6:]):
        period = row[0]
        raw_rows[period] = line
        for sid, cell in zip(ids, row[1:]):
            if cell not in ("", "ND"):
                values[sid][period] = number(cell)
    return descriptions, values, raw_rows


def g17_entry(entry_id: str, title: str, source: Source, prefix: str, primary: str, columns: dict[str, str], variable: str, unit: str, notes: str, tags: list[str], use_cases: list[str]) -> dict:
    descriptions, values, raw_rows = g17_frame(source)
    primary_id = f"{prefix}.{primary}.S"
    panel = Panel(MONTHS, values[primary_id], {name: values[f"{prefix}.{code}.S"] for code, name in columns.items()})
    sample_code, sample_name = next(iter(columns.items()))
    package_title = f"Federal Reserve Data Download Program, G.17 package {source.url.split('series=')[1].split('&')[0]} (CSV, 2023-01 to 2025-12)"
    order = list(descriptions)

    def row_snippet(period: str, series_id: str) -> str:
        """The row from its period through the cited cell when that fits a snippet, else the row's opening cells."""
        fields = raw_rows[period].split(",")
        through = ",".join(fields[: order.index(series_id) + 2])
        return through if len(through) <= 200 else ",".join(fields[:3])

    sample_id = f"{prefix}.{sample_code}.S"
    items = [
        cite(source, FED, package_title, f"Series Description row, column {primary_id}", primary_id, "text", f'"{descriptions[primary_id]}"', "unstated"),
        cite(source, FED, package_title, f"Time Period {MONTHS[0]}, column {primary_id}", values[primary_id][MONTHS[0]], unit, row_snippet(MONTHS[0], primary_id), "unstated"),
        cite(source, FED, package_title, f"Time Period {MONTHS[-1]}, column {sample_id} ({sample_name})", values[sample_id][MONTHS[-1]], unit, row_snippet(MONTHS[-1], sample_id), "unstated"),
    ]
    return temporal(entry_id, title, "US", "license-review", variable, unit, "monthly", panel, MONTHLY_WINDOW, items, notes + " " + UNSTATED_US, tags, use_cases)


def build_g17() -> list[dict]:
    ip = load(G17_PACKAGE.format(package=G17_TABLE4))
    cu = load(G17_PACKAGE.format(package=G17_TABLE7))
    common = (
        "The package is requested for January 2023 to December 2025 only, so the content hash changes only when "
        "the Board revises those months."
    )
    return [
        g17_entry(
            "us-industrial-production-by-market-group-monthly-2023-2025",
            "US industrial production index by market group, seasonally adjusted, monthly 2023-2025 (2022=100)",
            ip, "IP", "B50001", G17_MARKET_GROUPS, "industrial_production_index_total", "decimal",
            "Seasonally adjusted industrial production index (2022=100) from Federal Reserve statistical release G.17, "
            "Table 4. The primary series is the total index (B50001); the columns are market groups (final products, "
            "consumer goods by durability, business equipment, defense and space equipment, construction and business "
            "supplies, and materials by type), each keyed by a descriptive name for its G.17 code. " + common,
            BASE_TAGS + ["leading-indicators", "industrial-production", "federal-reserve"], PE_USE_CASES + ["capacity-planning", "demand-forecasting"],
        ),
        g17_entry(
            "us-industrial-production-by-naics-industry-monthly-2023-2025",
            "US industrial production index by NAICS industry, seasonally adjusted, monthly 2023-2025 (2022=100)",
            ip, "IP", "GMF", G17_INDUSTRIES, "industrial_production_index_manufacturing", "decimal",
            "Seasonally adjusted industrial production index (2022=100) from Federal Reserve statistical release G.17, "
            "Table 4. The primary series is manufacturing on the NAICS basis (GMF); the columns are durable and "
            "nondurable manufacturing, the three-digit NAICS manufacturing industries the release publishes, mining "
            "and electric and gas utilities. Column names end in the NAICS code. " + common,
            BASE_TAGS + ["leading-indicators", "industrial-production", "naics", "federal-reserve"], PE_USE_CASES + ["capacity-planning", "market-sizing"],
        ),
        g17_entry(
            "us-capacity-utilization-by-industry-monthly-2023-2025",
            "US capacity utilization rate by NAICS industry and stage of process, seasonally adjusted, monthly 2023-2025",
            cu, "CAPUTL", "B50001", G17_UTILIZATION, "capacity_utilization_percent_total_industry", "percent",
            "Seasonally adjusted capacity utilization (output as a percent of capacity) from Federal Reserve statistical "
            "release G.17, Table 7. The primary series is total industry (B50001); the columns are manufacturing on the "
            "NAICS basis, the three-digit NAICS industries, semiconductors, mining, utilities and the three stages of "
            "process (crude, primary and semifinished, finished). " + common,
            BASE_TAGS + ["leading-indicators", "capacity-utilization", "naics", "federal-reserve"], PE_USE_CASES + ["capacity-planning"],
        ),
    ]


# ---------------------------------------------------------------------------------------------------------------
# US Census Bureau economic indicator time series (one ZIP per programme)

CENSUS_ZIP = "https://www.census.gov/econ_getzippedfile/?programCode={code}"
CENSUS_SECTIONS = ("CATEGORIES", "DATA TYPES", "ERROR TYPES", "GEO LEVELS", "TIME PERIODS", "NOTES", "DATA UPDATED ON", "DATA")


@dataclass
class CensusTable:
    """One programme's time-series CSV: lookup sections plus the data rows keyed by their dimensions."""

    source: Source
    name: str
    categories: dict[str, tuple[str, str]]  # code -> (index, raw line)
    data_types: dict[str, tuple[str, str]]
    geos: dict[str, str]
    periods: dict[str, str]  # index -> label such as Jan-2023 or Q1-2025
    period_lines: dict[str, str]
    rows: dict[tuple[str, str, str, str, str], tuple[str, str]]  # (period, category, type, geo, adjusted) -> (value, line)
    updated: str

    def cell(self, period: str, category: str, data_type: str, adjusted: bool, geo: str = "US") -> tuple[str, str] | None:
        index = next(idx for idx, label in self.periods.items() if label == period)
        key = (index, self.categories[category][0], self.data_types[data_type][0], self.geos[geo], "1" if adjusted else "0")
        return self.rows.get(key)

    def series(self, labels: Iterable[str], category: str, data_type: str, adjusted: bool, geo: str = "US") -> dict[str, float]:
        out: dict[str, float] = {}
        for label in labels:
            hit = self.cell(label, category, data_type, adjusted, geo)
            if hit is not None and re.fullmatch(r"-?[0-9.]+", hit[0]):
                out[label] = number(hit[0])
        return out

    def evidence(self, label: str, category: str, data_type: str, adjusted: bool, unit: str, geo: str = "US", definitions: bool = True) -> list[dict]:
        """Cite the data row behind one value, preceded by its category, data type and period definitions unless
        ``definitions`` is false, in which case only the category line accompanies the data row."""
        title = f"U.S. Census Bureau economic indicators time series, {self.name} dataset ({self.name}-mf.csv in ZIP)"
        value, line = self.cell(label, category, data_type, adjusted, geo)
        index = [idx for idx, lab in self.periods.items() if lab == label][0]
        items = [cite(self.source, CENSUS, title, f"CATEGORIES section, cat_code {category}", category, "text", self.categories[category][1], "unstated")]
        if definitions:
            items.append(cite(self.source, CENSUS, title, f"DATA TYPES section, dt_code {data_type}", data_type, "text", self.data_types[data_type][1], "unstated"))
            items.append(cite(self.source, CENSUS, title, f"TIME PERIODS section, per_idx {index}", label, "text", self.period_lines[index], "unstated"))
        adjustment = "seasonally adjusted" if adjusted else "not seasonally adjusted"
        items.append(cite(self.source, CENSUS, title, f"DATA section, period {label}, {category}, {data_type}, {adjustment}", number(value), unit, line, "unstated"))
        return items


def census_table(code: str) -> CensusTable:
    source = load(CENSUS_ZIP.format(code=code))
    text = Resource(url=source.url, content=source.raw, content_type="").text
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in CENSUS_SECTIONS and stripped not in sections:
            current = stripped
            sections[current] = []
        elif current and stripped and not stripped.startswith("=="):
            sections[current].append(stripped)

    def lookup(lines: list[str], code_field: str, index_field: str) -> dict[str, tuple[str, str]]:
        reader = csv.DictReader(io.StringIO("\n".join(lines)))
        return {row[code_field]: (row[index_field], raw) for row, raw in zip(reader, lines[1:])}

    periods_reader = list(csv.DictReader(io.StringIO("\n".join(sections["TIME PERIODS"]))))
    rows = {}
    data_lines = sections["DATA"]
    header = data_lines[0].split(",")
    for raw in data_lines[1:]:
        record = dict(zip(header, raw.split(",")))
        if record.get("et_idx", "0") != "0":
            continue
        rows[(record["per_idx"], record["cat_idx"], record["dt_idx"], record["geo_idx"], record["is_adj"])] = (record["val"], raw)
    return CensusTable(
        source=source,
        name=code,
        categories=lookup(sections["CATEGORIES"], "cat_code", "cat_idx"),
        data_types=lookup(sections["DATA TYPES"], "dt_code", "dt_idx"),
        geos={code_: idx for code_, (idx, _) in lookup(sections["GEO LEVELS"], "geo_code", "geo_idx").items()},
        periods={r["per_idx"]: r["per_name"] for r in periods_reader},
        period_lines={r["per_idx"]: raw for r, raw in zip(periods_reader, sections["TIME PERIODS"][1:])},
        rows=rows,
        updated=sections["DATA UPDATED ON"][0],
    )


def census_month(period: str) -> str:
    year, month = period.split("-")
    return f"{MONTH_NAMES[int(month) - 1]}-{year}"


def census_panel(table: CensusTable, periods: list[str], label_of: Callable[[str], str], primary: tuple[str, str], columns: dict[str, tuple[str, str]], adjusted: bool, geo: str = "US") -> Panel:
    def keyed(category: str, data_type: str) -> dict[str, float]:
        by_label = table.series([label_of(p) for p in periods], category, data_type, adjusted, geo)
        return {p: by_label[label_of(p)] for p in periods if label_of(p) in by_label}

    return Panel(periods, keyed(*primary), {name: keyed(cat, dt) for name, (cat, dt) in columns.items()})


def census_notes(table: CensusTable, body: str) -> str:
    return (
        f"{body} Source: the {table.name} time-series dataset the Census Bureau publishes as one ZIP per programme "
        f"(data updated {table.updated}). The ZIP is replaced at each release, so the content hash changes then; the "
        f"values for the window are also subject to the programme's routine revisions. {UNSTATED_US}"
    )


M3_INDUSTRIES = {
    "MDM": "durable_goods",
    "MNM": "nondurable_goods",
    "21S": "wood_products",
    "27S": "nonmetallic_mineral_products",
    "31S": "primary_metals",
    "32S": "fabricated_metal_products",
    "33S": "machinery",
    "34S": "computer_and_electronic_products",
    "35S": "electrical_equipment_appliances",
    "36S": "transportation_equipment",
    "MVP": "motor_vehicles_and_parts",
    "37S": "furniture",
    "39S": "miscellaneous_products",
    "11S": "food_products",
    "12S": "beverage_and_tobacco",
    "22S": "paper_products",
    "24S": "petroleum_and_coal_products",
    "25S": "chemical_products",
    "25B": "pharmaceutical_and_medicine",
    "26S": "plastics_and_rubber_products",
    "TCG": "capital_goods",
    "NXA": "nondefense_capital_goods_ex_aircraft",
    "COG": "consumer_goods",
    "ITI": "information_technology_industries",
}
# Market groupings and detailed industries for which M3 publishes no inventories to shipments ratio.
M3_NO_RATIO = {"MVP", "25B", "TCG", "NXA", "COG", "ITI"}
M3_ORDERS = {
    "MDM": "durable_goods",
    "MXT": "manufacturing_ex_transportation",
    "31S": "primary_metals",
    "32S": "fabricated_metal_products",
    "33S": "machinery",
    "34S": "computer_and_electronic_products",
    "35S": "electrical_equipment_appliances",
    "36S": "transportation_equipment",
    "MVP": "motor_vehicles_and_parts",
    "TCG": "capital_goods",
    "NDE": "nondefense_capital_goods",
    "NXA": "nondefense_capital_goods_ex_aircraft",
    "DEF": "defense_capital_goods",
    "CDG": "consumer_durable_goods",
    "ITI": "information_technology_industries",
    "CMS": "construction_materials_and_supplies",
}


def build_m3() -> list[dict]:
    table = census_table("M3")
    tags = BASE_TAGS + ["manufacturing", "census-bureau", "naics"]
    entries = []
    shipments = census_panel(table, MONTHS, census_month, ("MTM", "VS"), {n: (c, "VS") for c, n in M3_INDUSTRIES.items()}, adjusted=True)
    entries.append(temporal(
        "us-manufacturers-shipments-by-industry-monthly-2023-2025",
        "US manufacturers' value of shipments by industry, seasonally adjusted, millions of dollars, monthly 2023-2025 (M3)",
        "US", "license-review", "shipments_total_manufacturing_musd", "currency:USD", "monthly", shipments, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "MTM", "VS", True, "currency:USD") + table.evidence(census_month(MONTHS[-1]), "33S", "VS", True, "currency:USD", definitions=False),
        census_notes(table, "Seasonally adjusted value of shipments in millions of US dollars from the Manufacturers' Shipments, Inventories and Orders (M3) survey. The primary series is total manufacturing (MTM); the columns are durable and nondurable goods, the M3 industry groups and the market groupings (capital goods, nondefense capital goods excluding aircraft, consumer goods, information technology industries), keyed by descriptive names for the M3 category codes."),
        tags + ["revenue"], PE_USE_CASES + ["market-sizing", "demand-forecasting"],
        assumed=[{"parameter": "spec.unit", "value": "currency:USD (millions)", "method": "derived", "rationale": "The DATA TYPES section gives the unit MLN$; values are kept in millions of US dollars as published."}],
    ))
    orders = census_panel(table, MONTHS, census_month, ("MTM", "NO"), {n: (c, "NO") for c, n in M3_ORDERS.items()}, adjusted=True)
    orders.columns["unfilled_orders_total_manufacturing"] = census_panel(table, MONTHS, census_month, ("MTM", "UO"), {}, adjusted=True).primary
    entries.append(temporal(
        "us-manufacturers-new-orders-by-industry-monthly-2023-2025",
        "US manufacturers' new orders by industry incl. core capital goods, seasonally adjusted, millions of dollars, monthly 2023-2025 (M3)",
        "US", "license-review", "new_orders_total_manufacturing_musd", "currency:USD", "monthly", orders, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "MTM", "NO", True, "currency:USD") + table.evidence(census_month(MONTHS[-1]), "NXA", "NO", True, "currency:USD", definitions=False),
        census_notes(table, "Seasonally adjusted new orders in millions of US dollars from the M3 survey, a leading indicator of manufacturing activity. The primary series is total manufacturing (MTM); the columns cover durable goods, manufacturing excluding transportation, the durable industry groups, capital goods split into nondefense, nondefense excluding aircraft (the core capital goods series) and defense, consumer durables, information technology industries and construction materials, plus total unfilled orders."),
        tags + ["leading-indicators", "orders"], PE_USE_CASES + ["demand-forecasting", "capacity-planning"],
        assumed=[{"parameter": "spec.unit", "value": "currency:USD (millions)", "method": "derived", "rationale": "The DATA TYPES section gives the unit MLN$; values are kept in millions of US dollars as published."}],
    ))
    ratios = census_panel(table, MONTHS, census_month, ("MTM", "IS"), {n: (c, "IS") for c, n in M3_INDUSTRIES.items() if c not in M3_NO_RATIO}, adjusted=True)
    entries.append(temporal(
        "us-manufacturers-inventories-to-shipments-ratio-by-industry-monthly-2023-2025",
        "US manufacturers' total inventories to shipments ratio by industry, seasonally adjusted, monthly 2023-2025 (M3)",
        "US", "license-review", "inventories_to_shipments_ratio_total_manufacturing", "ratio", "monthly", ratios, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "MTM", "IS", True, "ratio") + table.evidence(census_month(MONTHS[-1]), "33S", "IS", True, "ratio", definitions=False),
        census_notes(table, "Seasonally adjusted ratio of end-of-month total inventories to monthly value of shipments from the M3 survey, the benchmark for inventory days and working-capital assumptions. The primary series is total manufacturing (MTM); the columns are durable and nondurable goods and the M3 industry groups (the survey publishes no ratio for motor vehicles and parts, pharmaceuticals or the market groupings)."),
        tags + ["working-capital", "inventory"], PE_USE_CASES + ["capacity-planning", "financial-reporting"],
    ))
    return entries


QSS_PERIODS = ["2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]
QSS_INDUSTRIES = {
    "22T": "utilities_22",
    "4849YT": "transportation_and_warehousing_48_49",
    "484T": "truck_transportation_484",
    "493T": "warehousing_and_storage_493",
    "51T": "information_51",
    "5112T": "software_publishers_5112",
    "517T": "telecommunications_517",
    "518T": "data_processing_and_hosting_518",
    "52T": "finance_and_insurance_52",
    "53T": "real_estate_and_rental_53",
    "532T": "rental_and_leasing_532",
    "54T": "professional_scientific_technical_54",
    "5411T": "legal_services_5411",
    "5412T": "accounting_and_payroll_5412",
    "5413T": "architecture_and_engineering_5413",
    "5415T": "computer_systems_design_5415",
    "5416T": "management_consulting_5416",
    "5418T": "advertising_and_pr_5418",
    "56T": "administrative_and_waste_services_56",
    "5613T": "employment_services_5613",
    "562T": "waste_management_562",
    "61A": "educational_services_61",
    "62A": "health_care_and_social_assistance_62",
    "621A": "ambulatory_health_care_621",
    "622A": "hospitals_622",
    "623A": "nursing_and_residential_care_623",
    "71A": "arts_entertainment_recreation_71",
    "721T": "accommodation_721",
    "81A": "other_services_81",
    "811T": "repair_and_maintenance_811",
}


def qss_label(period: str) -> str:
    year, quarter = period.split("-")
    return f"{quarter}-{year}"


def build_qss() -> dict:
    table = census_table("QSS")
    panel = census_panel(table, QSS_PERIODS, qss_label, ("000000A", "QREV"), {n: (c, "QREV") for c, n in QSS_INDUSTRIES.items()}, adjusted=False)
    return temporal(
        "us-services-revenue-by-naics-industry-quarterly-2024q3-2026q2",
        "US services industries total revenue by NAICS industry, not seasonally adjusted, millions of dollars, 2024Q3-2026Q2 (QSS)",
        "US", "license-review", "revenue_selected_services_total_musd", "currency:USD", "quarterly", panel, ("2024-07-01", "2026-06-30"),
        table.evidence(qss_label(QSS_PERIODS[0]), "000000A", "QREV", False, "currency:USD") + table.evidence(qss_label(QSS_PERIODS[-1]), "5415T", "QREV", False, "currency:USD", definitions=False),
        census_notes(table, "Quarterly total operating revenue in millions of US dollars, not seasonally adjusted, from the Quarterly Services Survey for the eight quarters from 2024Q3 to 2026Q2 (the advance estimate for 2026Q3 is left out). The primary series is the selected services total; the columns are NAICS sectors and the three- and four-digit industries most often held by services portfolios, with the NAICS code at the end of each column name. Year-over-year growth should be read across the same quarter because the series is not seasonally adjusted."),
        BASE_TAGS + ["services", "revenue", "census-bureau", "naics"], PE_USE_CASES + ["market-sizing", "demand-forecasting"],
        assumed=[{"parameter": "spec.unit", "value": "currency:USD (millions)", "method": "derived", "rationale": "The DATA TYPES section gives the unit MLN$; values are kept in millions of US dollars as published."}],
    )


MRTS_KINDS = {
    "44000": "retail_trade_44_45",
    "4400A": "retail_trade_ex_auto",
    "4400C": "gafo",
    "441": "motor_vehicle_and_parts_441",
    "442": "furniture_and_home_furnishings_442",
    "443": "electronics_and_appliances_443",
    "444": "building_materials_and_garden_444",
    "445": "food_and_beverage_stores_445",
    "4451": "grocery_stores_4451",
    "446": "health_and_personal_care_446",
    "447": "gasoline_stations_447",
    "448": "clothing_and_accessories_448",
    "451": "sporting_goods_hobby_books_451",
    "452": "general_merchandise_452",
    "452311": "warehouse_clubs_and_supercenters_452311",
    "453": "miscellaneous_store_retailers_453",
    "454": "nonstore_retailers_454",
    "4541": "electronic_shopping_and_mail_order_4541",
    "722": "food_services_and_drinking_places_722",
}

# Kinds of business for which the survey publishes a seasonally adjusted inventories to sales ratio.
MRTS_RATIO_KINDS = ["4400A", "441", "444", "445", "448", "452"]


def build_mrts() -> list[dict]:
    table = census_table("MRTS")
    tags = BASE_TAGS + ["retail", "census-bureau", "naics"]
    sales = census_panel(table, MONTHS, census_month, ("44X72", "SM"), {n: (c, "SM") for c, n in MRTS_KINDS.items()}, adjusted=True)
    ratios = census_panel(table, MONTHS, census_month, ("44000", "IR"), {MRTS_KINDS[c]: (c, "IR") for c in MRTS_RATIO_KINDS}, adjusted=True)
    return [
        temporal(
            "us-retail-sales-by-kind-of-business-monthly-2023-2025",
            "US retail and food services sales by kind of business (NAICS), seasonally adjusted, millions of dollars, monthly 2023-2025",
            "US", "license-review", "sales_retail_and_food_services_musd", "currency:USD", "monthly", sales, MONTHLY_WINDOW,
            table.evidence(census_month(MONTHS[0]), "44X72", "SM", True, "currency:USD") + table.evidence(census_month(MONTHS[-1]), "4541", "SM", True, "currency:USD", definitions=False),
            census_notes(table, "Seasonally adjusted monthly sales in millions of US dollars from the Monthly Retail Trade Survey. The primary series is retail trade and food services (44X72); the columns are the NAICS kinds of business, with GAFO (general merchandise, apparel, furniture and other) and electronic shopping and mail-order houses, keyed by descriptive names ending in the NAICS code."),
            tags + ["sales"], PE_USE_CASES + ["retail-demo", "demand-forecasting", "market-sizing"],
            assumed=[{"parameter": "spec.unit", "value": "currency:USD (millions)", "method": "derived", "rationale": "The DATA TYPES section gives the unit MLN$; values are kept in millions of US dollars as published."}],
        ),
        temporal(
            "us-retail-inventories-to-sales-ratio-by-kind-of-business-monthly-2023-2025",
            "US retail inventories to sales ratio by kind of business (NAICS), seasonally adjusted, monthly 2023-2025",
            "US", "license-review", "inventories_to_sales_ratio_retail_trade", "ratio", "monthly", ratios, MONTHLY_WINDOW,
            table.evidence(census_month(MONTHS[0]), "44000", "IR", True, "ratio") + table.evidence(census_month(MONTHS[-1]), "452", "IR", True, "ratio", definitions=False),
            census_notes(table, "Seasonally adjusted ratio of end-of-month inventories to monthly sales for retailers from the Monthly Retail Trade Survey, the benchmark for retail inventory days. The primary series is retail trade (44000, food services carry no inventories in the survey); the columns are retail excluding motor vehicles and the kinds of business for which the survey publishes the ratio, keyed by descriptive names ending in the NAICS code."),
            tags + ["working-capital", "inventory"], PE_USE_CASES + ["retail-demo", "capacity-planning"],
        ),
    ]


def build_mtis() -> dict:
    table = census_table("MTIS")
    columns = {
        "manufacturers_ratio": ("MNFCTR", "IR"),
        "retailers_ratio": ("RETAIL", "IR"),
        "merchant_wholesalers_ratio": ("WHLSLR", "IR"),
        "total_business_sales_musd": ("TOTBUS", "SM"),
        "total_business_inventories_musd": ("TOTBUS", "IM"),
    }
    panel = census_panel(table, MONTHS, census_month, ("TOTBUS", "IR"), columns, adjusted=True)
    return temporal(
        "us-business-inventories-to-sales-ratio-monthly-2023-2025",
        "US total business inventories to sales ratio with manufacturers, retailers and wholesalers, seasonally adjusted, monthly 2023-2025",
        "US", "license-review", "inventories_to_sales_ratio_total_business", "ratio", "monthly", panel, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "TOTBUS", "IR", True, "ratio") + table.evidence(census_month(MONTHS[-1]), "WHLSLR", "IR", True, "ratio", definitions=False),
        census_notes(table, "Seasonally adjusted inventories to sales ratio for total business from the Manufacturing and Trade Inventories and Sales (MTIS) release, with the ratios for manufacturers, retailers and merchant wholesalers and total business sales and inventories in millions of US dollars as columns."),
        BASE_TAGS + ["working-capital", "inventory", "census-bureau"], PE_USE_CASES + ["capacity-planning", "financial-reporting"],
    )


VIP_TYPES = {
    "A00XX": "residential",
    "ANRXX": "nonresidential",
    "A01XX": "lodging",
    "A02XX": "office",
    "A03XX": "commercial",
    "A04XX": "health_care",
    "A05XX": "educational",
    "A06XX": "religious",
    "A07XX": "public_safety",
    "A08XX": "amusement_and_recreation",
    "A09XX": "transportation",
    "A10XX": "communication",
    "A11XX": "power",
    "A12XX": "highway_and_street",
    "A13XX": "sewage_and_waste_disposal",
    "A14XX": "water_supply",
    "A15XX": "conservation_and_development",
    "A20IX": "manufacturing",
}


def build_vip() -> dict:
    table = census_table("VIP")
    columns = {"private_total": ("AXXXX", "V"), "public_total": ("AXXXX", "P"), **{name: (code, "T") for code, name in VIP_TYPES.items()}}
    panel = census_panel(table, MONTHS, census_month, ("AXXXX", "T"), columns, adjusted=True)
    return temporal(
        "us-construction-spending-by-type-monthly-2023-2025",
        "US construction spending put in place by type of construction, seasonally adjusted annual rate, millions of dollars, monthly 2023-2025",
        "US", "license-review", "construction_spending_total_saar_musd", "currency:USD", "monthly", panel, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "AXXXX", "T", True, "currency:USD") + table.evidence(census_month(MONTHS[-1]), "A20IX", "T", True, "currency:USD", definitions=False),
        census_notes(table, "Value of construction put in place at a seasonally adjusted annual rate, in millions of US dollars, from the Construction Spending (VIP) survey. The primary series is total construction; the columns are total private and total public construction and the total (private plus public) for each type of construction."),
        BASE_TAGS + ["construction", "census-bureau", "leading-indicators"], PE_USE_CASES + ["market-sizing", "property-demo"],
        assumed=[{"parameter": "spec.unit", "value": "currency:USD (millions, annual rate)", "method": "derived", "rationale": "The DATA TYPES section gives the unit MLN$ and the categories are the annual-rate series; values are kept as published."}],
    )


def build_resconst() -> dict:
    table = census_table("RESCONST")
    columns = {
        "starts_single_family": ("ASTARTS", "SINGLE"),
        "starts_five_units_or_more": ("ASTARTS", "MULTI"),
        "permits_total": ("APERMITS", "TOTAL"),
        "permits_single_family": ("APERMITS", "SINGLE"),
        "completions_total": ("ACOMPLETIONS", "TOTAL"),
        "under_construction_total": ("UNDERCONST", "TOTAL"),
        "authorized_not_started_total": ("AUTHNOTSTD", "TOTAL"),
    }
    panel = census_panel(table, MONTHS, census_month, ("ASTARTS", "TOTAL"), columns, adjusted=True)
    return temporal(
        "us-new-residential-construction-monthly-2023-2025",
        "US new residential construction: housing starts, permits and completions, seasonally adjusted annual rate, thousands, monthly 2023-2025",
        "US", "license-review", "housing_starts_total_saar_thousands", "decimal", "monthly", panel, MONTHLY_WINDOW,
        table.evidence(census_month(MONTHS[0]), "ASTARTS", "TOTAL", True, "decimal") + table.evidence(census_month(MONTHS[-1]), "APERMITS", "TOTAL", True, "decimal", definitions=False),
        census_notes(table, "New residential construction for the United States, in thousands of housing units, seasonally adjusted. The primary series is total housing starts at an annual rate; the columns are single-family starts and starts in buildings with five units or more, permits (total and single-family) and completions at annual rates, and the monthly stock of units under construction and authorized but not started."),
        BASE_TAGS + ["construction", "housing", "census-bureau", "leading-indicators"], PE_USE_CASES + ["property-demo", "demand-forecasting"],
    )


ECOMMERCE_URL = "https://www.census.gov/retail/mrts/www/data/excel/tsadjustedsales.xlsx"
ORDINALS = {"1st": "Q1", "2nd": "Q2", "3rd": "Q3", "4th": "Q4"}


def build_ecommerce() -> dict:
    source = load(ECOMMERCE_URL)
    sheet = openpyxl.load_workbook(io.BytesIO(source.raw), data_only=True).worksheets[0]
    found: dict[str, tuple] = {}
    for row in sheet.iter_rows(values_only=True):
        label = row[1]
        match = re.fullmatch(r"(1st|2nd|3rd|4th) quarter (\d{4})", str(label or "").strip())
        if match:
            found[f"{match.group(2)}-{ORDINALS[match.group(1)]}"] = (label, *row[2:9])
    panel = Panel(
        QUARTERS,
        {q: found[q][3] for q in QUARTERS if q in found},
        {
            "total_retail_sales_musd": {q: found[q][1] for q in QUARTERS if q in found},
            "ecommerce_sales_musd": {q: found[q][2] for q in QUARTERS if q in found},
            "ecommerce_change_from_prior_quarter_percent": {q: found[q][5] for q in QUARTERS if q in found},
            "ecommerce_change_from_year_ago_percent": {q: found[q][7] for q in QUARTERS if q in found},
            "total_change_from_year_ago_percent": {q: found[q][6] for q in QUARTERS if q in found},
        },
    )
    title = "U.S. Census Bureau, Estimated Quarterly U.S. Retail Sales (Adjusted): Total and E-commerce, time series workbook"
    first, last = found[QUARTERS[0]], found[QUARTERS[-1]]
    items = [
        cite(source, CENSUS, title, f"row {first[0]}, column E-commerce as a Percent of Total", first[3], "percent", first[0], "unstated"),
        cite(source, CENSUS, title, f"row {last[0]}, column E-commerce (millions of dollars)", last[2], "currency:USD", last[0], "unstated"),
    ]
    return temporal(
        "us-retail-ecommerce-share-quarterly-2023-2025",
        "US retail e-commerce sales and share of total retail sales, seasonally adjusted, quarterly 2023-2025",
        "US", "license-review", "ecommerce_share_of_retail_percent", "percent", "quarterly", panel, MONTHLY_WINDOW, items,
        "E-commerce sales as a percent of total retail sales, seasonally adjusted, by quarter from 2023Q1 to 2025Q4, from the "
        "Census Bureau's quarterly e-commerce report time-series workbook (estimates from the Monthly Retail Trade Survey and "
        "administrative records, employer businesses only). Columns carry total retail and e-commerce sales in millions of "
        "US dollars and the percent changes from the prior quarter and the same quarter a year earlier. The workbook is "
        "rewritten each quarter and its latest quarter is preliminary; the window ends well before it. " + UNSTATED_US,
        BASE_TAGS + ["retail", "ecommerce", "census-bureau"], PE_USE_CASES + ["retail-demo", "digital-channels", "market-sizing"],
    )


# ---------------------------------------------------------------------------------------------------------------
# Eurostat short-term business statistics (SDMX-CSV)

EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
EU_GEOS = ["EU27_2020", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"]


def eurostat(dataflow: str, key: str) -> tuple[Source, list[dict], list[str]]:
    url = f"{EUROSTAT_API}/{dataflow}/{key}?startPeriod={START_YEAR}-01&endPeriod={END_YEAR}-12&format=SDMX-CSV"
    source = load(url)
    text = source.raw.decode("utf-8")
    return source, list(csv.DictReader(io.StringIO(text))), text.splitlines()[1:]


def eurostat_entry(entry_id: str, title: str, dataflow: str, key: str, by: str, primary: str, names: dict[str, str], variable: str, unit: str, body: str, tags: list[str], use_cases: list[str]) -> dict:
    source, rows, lines = eurostat(dataflow, key)
    table: dict[str, dict[str, float]] = {}
    raw_of: dict[tuple[str, str], str] = {}
    flagged = set()
    for row, line in zip(rows, lines):
        if row["OBS_VALUE"]:
            table.setdefault(row[by], {})[row["TIME_PERIOD"]] = number(row["OBS_VALUE"])
            raw_of[(row[by], row["TIME_PERIOD"])] = line
            if row.get("OBS_FLAG"):
                flagged.add(row["OBS_FLAG"])
    panel = Panel(MONTHS, table.get(primary, {}), {name: table.get(code, {}) for code, name in names.items()})
    dataset_title = f"Eurostat SDMX 2.1 API, dataflow {dataflow} (SDMX-CSV), {START_YEAR}-01 to {END_YEAR}-12"
    sample_code = next(iter(names))
    last_update = rows[0]["LAST UPDATE"]

    def snippet(code: str, period: str) -> str:
        fields = raw_of[(code, period)].split(",")
        return ",".join(fields[2:10])

    items = [
        cite(source, EUROSTAT, dataset_title, f"{by}={primary}, TIME_PERIOD={MONTHS[0]}, OBS_VALUE", table[primary][MONTHS[0]], unit, snippet(primary, MONTHS[0]), "CC-BY-4.0"),
        cite(source, EUROSTAT, dataset_title, f"{by}={sample_code}, TIME_PERIOD={MONTHS[-1]}, OBS_VALUE", table[sample_code][MONTHS[-1]], unit, snippet(sample_code, MONTHS[-1]), "CC-BY-4.0"),
        cite(source, EUROSTAT, dataset_title, "LAST UPDATE column", last_update, "text", f"{rows[0]['DATAFLOW']},{last_update}", "CC-BY-4.0"),
    ]
    flags = f" Observation flags present in the window: {', '.join(sorted(flagged))} (p provisional, e estimated, c confidential)." if flagged else ""
    notes = f"{body} Dataset last updated {last_update}; the query is pinned to {START_YEAR}-01..{END_YEAR}-12 but Eurostat rewrites the dataset at each release, so the content hash changes then.{flags} {EUROSTAT_LICENSE_NOTE}"
    return temporal(entry_id, title, "EU", "verified", variable, unit, "monthly", panel, MONTHLY_WINDOW, items, notes, tags, use_cases)


def geo_columns() -> dict[str, str]:
    return {geo: geo.lower() for geo in EU_GEOS if geo != "EU27_2020"}


IP_NACE = {
    "B": "mining_b",
    "C": "manufacturing_c",
    "D": "energy_supply_d",
    "MIG_CAG": "capital_goods",
    "MIG_ING": "intermediate_goods",
    "MIG_DCOG": "consumer_durables",
    "MIG_NDCOG": "consumer_nondurables",
    "MIG_NRG_X_E": "energy",
    "C10": "food_c10",
    "C11": "beverages_c11",
    "C13": "textiles_c13",
    "C14": "apparel_c14",
    "C16": "wood_c16",
    "C17": "paper_c17",
    "C18": "printing_c18",
    "C19": "coke_and_refined_petroleum_c19",
    "C20": "chemicals_c20",
    "C21": "pharmaceuticals_c21",
    "C22": "rubber_and_plastics_c22",
    "C23": "non_metallic_minerals_c23",
    "C24": "basic_metals_c24",
    "C25": "fabricated_metals_c25",
    "C26": "computer_electronic_optical_c26",
    "C27": "electrical_equipment_c27",
    "C28": "machinery_c28",
    "C29": "motor_vehicles_c29",
    "C30": "other_transport_equipment_c30",
    "C31": "furniture_c31",
    "C32": "other_manufacturing_c32",
    "C33": "repair_and_installation_c33",
}
SERVICES_NACE = {
    "H": "transportation_and_storage_h",
    "H49": "land_transport_h49",
    "H51": "air_transport_h51",
    "H52": "warehousing_h52",
    "H53": "postal_and_courier_h53",
    "I": "accommodation_and_food_i",
    "I55": "accommodation_i55",
    "I56": "food_and_beverage_service_i56",
    "J": "information_and_communication_j",
    "J58": "publishing_j58",
    "J61": "telecommunications_j61",
    "J62": "computer_programming_consultancy_j62",
    "J63": "information_services_j63",
    "L68": "real_estate_l68",
    "M_STS": "professional_scientific_technical_m",
    "M69_M702": "legal_accounting_management_consultancy_m69_m702",
    "M71": "architecture_engineering_m71",
    "M73": "advertising_market_research_m73",
    "N": "administrative_and_support_n",
    "N77": "rental_and_leasing_n77",
    "N78": "employment_activities_n78",
    "N79": "travel_agencies_n79",
    "N81": "buildings_and_landscape_services_n81",
    "N82": "office_and_business_support_n82",
}
PPI_NACE = {
    "B": "mining_b",
    "C": "manufacturing_c",
    "D": "energy_supply_d",
    "E36": "water_supply_e36",
    "MIG_CAG": "capital_goods",
    "MIG_ING": "intermediate_goods",
    "MIG_DCOG": "consumer_durables",
    "MIG_NDCOG": "consumer_nondurables",
    "MIG_NRG": "energy",
    **{code: name for code, name in IP_NACE.items() if code.startswith("C") and len(code) == 3},
}


def build_eurostat() -> list[dict]:
    tags = BASE_TAGS + ["eurostat", "nace"]
    sts = "Eurostat short-term business statistics"
    return [
        eurostat_entry(
            "eu-industrial-production-by-nace-monthly-2023-2025",
            "EU27 industrial production index by NACE section, division and main industrial grouping, seasonally adjusted, monthly 2023-2025",
            "sts_inpr_m", "M.PRD." + "+".join(["B-D", *IP_NACE]) + ".SCA.I21.EU27_2020", "nace_r2", "B-D", IP_NACE,
            "industrial_production_index_total_industry", "decimal",
            f"{sts}: volume index of production (2021=100), seasonally and calendar adjusted, for the EU27 (from 2020). The primary series is total industry excluding construction (B-D); the columns are mining, manufacturing and energy supply, the main industrial groupings (capital, intermediate, durable and non-durable consumer goods, energy) and the NACE Rev. 2 manufacturing divisions, with the NACE code at the end of each column name.",
            tags + ["leading-indicators", "industrial-production"], PE_USE_CASES + ["capacity-planning", "demand-forecasting"],
        ),
        eurostat_entry(
            "eu-industrial-production-by-country-monthly-2023-2025",
            "Industrial production index, total industry (B-D), seasonally adjusted, monthly 2023-2025, EU27 and ten member states",
            "sts_inpr_m", "M.PRD.B-D.SCA.I21." + "+".join(EU_GEOS), "geo", "EU27_2020", geo_columns(),
            "industrial_production_index_eu27", "decimal",
            f"{sts}: volume index of production (2021=100), seasonally and calendar adjusted, total industry excluding construction (B-D). The primary series is the EU27 (from 2020); the columns are ten member states keyed by their two-letter geo code.",
            tags + ["leading-indicators", "industrial-production", "by-country"], PE_USE_CASES + ["capacity-planning"],
        ),
        eurostat_entry(
            "eu-services-turnover-by-nace-monthly-2023-2025",
            "EU27 services turnover index by NACE section and division, seasonally adjusted, monthly 2023-2025",
            "sts_setu_m", "M.NETTUR." + "+".join(["H-N_X_K", *SERVICES_NACE]) + ".SCA.I21.EU27_2020", "nace_r2", "H-N_X_K", SERVICES_NACE,
            "services_turnover_index_h_to_n_ex_k", "decimal",
            f"{sts}: index of net turnover in value (2021=100), seasonally and calendar adjusted, for the EU27 (from 2020). The primary series is services H to N excluding financial services (H-N_X_K); the columns are NACE Rev. 2 sections and divisions for transport, accommodation and food, information and communication, real estate, professional and administrative services, with the NACE code at the end of each column name. Turnover is in current prices, so it carries both volume and price effects.",
            tags + ["services", "revenue"], PE_USE_CASES + ["market-sizing", "demand-forecasting"],
        ),
        eurostat_entry(
            "eu-producer-prices-domestic-by-nace-monthly-2023-2025",
            "EU27 producer prices in industry, domestic market, by NACE section, division and grouping, not adjusted, monthly 2023-2025",
            "sts_inppd_m", "M.PRC_PRR_DOM." + "+".join(["B-E36", *PPI_NACE]) + ".NSA.I21.EU27_2020", "nace_r2", "B-E36", PPI_NACE,
            "producer_price_index_domestic_industry", "decimal",
            f"{sts}: producer price index for the domestic market (2021=100), not seasonally adjusted, for the EU27 (from 2020). The primary series is industry including water supply (B-E36); the columns are mining, manufacturing, energy and water supply, the main industrial groupings and the NACE Rev. 2 manufacturing divisions. Output-price inflation by division is the pricing-power benchmark for industrial portfolio companies.",
            tags + ["prices", "producer-prices", "pricing-power"], PE_USE_CASES + ["pricing", "contract-indexation"],
        ),
        eurostat_entry(
            "eu-producer-prices-annual-change-by-country-monthly-2023-2025",
            "Producer prices in industry, domestic market, annual rate of change, monthly 2023-2025, EU27 and ten member states",
            "sts_inppd_m", "M.PRC_PRR_DOM.B-E36.NSA.PCH_SM." + "+".join(EU_GEOS), "geo", "EU27_2020", geo_columns(),
            "producer_price_annual_change_percent_eu27", "percent",
            f"{sts}: percentage change on the same month of the previous year of the domestic producer price index for industry including water supply (B-E36), not seasonally adjusted. The primary series is the EU27 (from 2020); the columns are ten member states keyed by their two-letter geo code.",
            tags + ["prices", "producer-prices", "pricing-power", "by-country"], PE_USE_CASES + ["pricing", "contract-indexation"],
        ),
        eurostat_entry(
            "eu-retail-trade-volume-by-country-monthly-2023-2025",
            "Retail trade volume index (NACE G47), seasonally adjusted, monthly 2023-2025, EU27 and ten member states",
            "sts_trtu_m", "M.VOL_SLS.G47.SCA.I21." + "+".join(EU_GEOS), "geo", "EU27_2020", geo_columns(),
            "retail_trade_volume_index_eu27", "decimal",
            f"{sts}: deflated turnover (volume of sales) index for retail trade except motor vehicles and motorcycles (NACE G47), 2021=100, seasonally and calendar adjusted. The primary series is the EU27 (from 2020); the columns are ten member states keyed by their two-letter geo code.",
            tags + ["retail", "by-country"], PE_USE_CASES + ["retail-demo", "demand-forecasting"],
        ),
    ]


# ---------------------------------------------------------------------------------------------------------------
# OECD composite leading indicators and confidence (SDMX CSV with labels)

OECD_DATA = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,"
OECD_CLI_AREAS = ["USA", "GBR", "DEU", "FRA", "ITA", "ESP", "JPN", "KOR", "CHN", "IND", "IDN", "BRA", "MEX", "CAN", "AUS", "TUR", "ZAF", "G7", "G20"]
OECD_CONFIDENCE_AREAS = ["USA", "GBR", "DEU", "FRA", "ITA", "ESP", "NLD", "POL", "SWE", "IRL", "JPN", "KOR", "CHN", "IND", "BRA", "MEX", "CAN", "AUS", "TUR", "ZAF", "EA20", "OECD", "G7"]


def oecd_entry(entry_id: str, title: str, measure: str, areas: list[str], variable: str, body: str, tags: list[str]) -> dict:
    url = f"{OECD_DATA}/{'+'.join(areas)}.M.{measure}...AA...H?startPeriod={START_YEAR}-01&endPeriod={END_YEAR}-12&format=csvfilewithlabels"
    source = load(url)
    text = source.raw.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    lines = text.splitlines()[1:]
    table: dict[str, dict[str, float]] = {}
    raw_of: dict[tuple[str, str], str] = {}
    for row, line in zip(rows, lines):
        if row["OBS_VALUE"]:
            table.setdefault(row["REF_AREA"], {})[row["TIME_PERIOD"]] = number(row["OBS_VALUE"])
            raw_of[(row["REF_AREA"], row["TIME_PERIOD"])] = line
    names = {area: area.lower() for area in areas if area != "USA"}
    panel = Panel(MONTHS, table.get("USA", {}), {name: table.get(area, {}) for area, name in names.items()})
    label = rows[0]["Measure"]
    dataset_title = f"OECD Data Explorer SDMX API, dataflow DSD_STES@DF_CLI, measure {measure} amplitude adjusted (CSV with labels), {START_YEAR}-01 to {END_YEAR}-12"

    def snippet(area: str, period: str) -> str:
        line = raw_of[(area, period)]
        start = line.index(f",{area},") + 1
        end = line.index(f",{period},") + len(f",{period},")
        tail = line[end:].split(",")[1]
        return line[start:end] + "," + tail

    items = [
        cite(source, OECD, dataset_title, f"REF_AREA=USA, TIME_PERIOD={MONTHS[0]}, OBS_VALUE", table["USA"][MONTHS[0]], "decimal", snippet("USA", MONTHS[0]), "unstated"),
        cite(source, OECD, dataset_title, f"REF_AREA=GBR, TIME_PERIOD={MONTHS[-1]}, OBS_VALUE", table["GBR"][MONTHS[-1]], "decimal", snippet("GBR", MONTHS[-1]), "unstated"),
    ]
    notes = (
        f"{body} Monthly values of the OECD {label.lower()} series, amplitude adjusted, OECD harmonised "
        "methodology, from the OECD composite leading indicators dataflow. The primary series is the United States; the "
        "columns are the other economies and aggregates keyed by their lower-case reference-area codes (ISO 3166-1 alpha-3 "
        "for countries). Recent months are revised as new component data arrive, so the content hash changes at each OECD "
        "update. " + UNSTATED_OECD
    )
    return temporal(entry_id, title, "global", "license-review", variable, "decimal", "monthly", panel, MONTHLY_WINDOW, items, notes, BASE_TAGS + ["leading-indicators", "oecd", "by-country"] + tags, PE_USE_CASES + ["demand-forecasting", "credit-risk"])


def build_oecd() -> list[dict]:
    return [
        oecd_entry(
            "global-oecd-composite-leading-indicator-monthly-2023-2025",
            "OECD composite leading indicator, amplitude adjusted, monthly 2023-2025, 17 economies plus G7 and G20",
            "LI", OECD_CLI_AREAS, "composite_leading_indicator_usa",
            "The composite leading indicator is built to anticipate turning points in economic activity relative to trend.",
            ["business-cycle"],
        ),
        oecd_entry(
            "global-oecd-business-confidence-monthly-2023-2025",
            "OECD composite business confidence indicator, amplitude adjusted, monthly 2023-2025, 20 economies plus euro area, OECD and G7",
            "BCICP", OECD_CONFIDENCE_AREAS, "business_confidence_usa",
            "The business confidence indicator summarises national business tendency surveys.",
            ["business-confidence", "surveys"],
        ),
        oecd_entry(
            "global-oecd-consumer-confidence-monthly-2023-2025",
            "OECD composite consumer confidence indicator, amplitude adjusted, monthly 2023-2025, 20 economies plus euro area, OECD and G7",
            "CCICP", OECD_CONFIDENCE_AREAS, "consumer_confidence_usa",
            "The consumer confidence indicator summarises national consumer opinion surveys.",
            ["consumer-confidence", "surveys", "consumer"],
        ),
    ]


# ---------------------------------------------------------------------------------------------------------------
# ONS: monthly GDP by industry and the Business Insights and Conditions Survey

ONS_GDP_URL = "https://download.ons.gov.uk/downloads/datasets/gdp-to-four-decimal-places/editions/time-series/versions/69.csv"
ONS_GDP_META = "https://api.beta.ons.gov.uk/v1/datasets/gdp-to-four-decimal-places"
BICS_URL = (
    "https://www.ons.gov.uk/file?uri=/economy/economicoutputandproductivity/output/datasets/"
    "businessinsightsandimpactontheukeconomy/bicswave168/bicswave168dataset.xlsx"
)


def ons_licence() -> dict:
    source = load(ONS_LICENSE_URL)
    return cite(source, ONS, "ONS dataset metadata cpih01 (licence statement for ONS datasets)", "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', "OGL-UK-3.0", role="supporting")


def build_ons_gdp(licence: dict) -> dict:
    source = load(ONS_GDP_URL)
    meta = load(ONS_GDP_META)
    unit_text = re.search(r'"unit_of_measure":"([^"]*)"', meta.raw.decode("utf-8")).group(1)
    text = source.raw.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    lines = text.splitlines()[1:]
    table: dict[str, dict[str, float]] = {}
    raw_of: dict[tuple[str, str], str] = {}
    labels: dict[str, str] = {}
    for row, line in zip(rows, lines):
        month, year = row["Time"].split("-")
        period = f"20{year}-{MONTH_NAMES.index(month) + 1:02d}"
        code = row["sic-unofficial"]
        table.setdefault(code, {})[period] = number(row["v4_0"])
        raw_of[(code, period)] = line
        labels[code] = row["UnofficialStandardIndustrialClassification"]
    columns = {code: "sic_" + code.lower().replace("--", "_to_").replace("-", "_") for code in sorted(table) if code != "A--T"}
    panel = Panel(MONTHS, table["A--T"], {name: table[code] for code, name in columns.items()})
    title = "ONS dataset gdp-to-four-decimal-places version 69, full time-series CSV (v4 format)"
    items = [
        cite(source, ONS, title, f"row Time={raw_of[('A--T', MONTHS[0])].split(',')[1]}, A-T Monthly GDP, column v4_0", table["A--T"][MONTHS[0]], "decimal", raw_of[("A--T", MONTHS[0])], "OGL-UK-3.0"),
        cite(source, ONS, title, f"row Time={raw_of[('C', MONTHS[-1])].split(',')[1]}, C Manufacturing, column v4_0", table["C"][MONTHS[-1]], "decimal", raw_of[("C", MONTHS[-1])], "OGL-UK-3.0"),
        cite(meta, ONS, "ONS dataset metadata gdp-to-four-decimal-places", "unit_of_measure", unit_text, "text", f'"unit_of_measure":"{unit_text}"', "OGL-UK-3.0", role="supporting"),
        licence,
    ]
    return temporal(
        "gb-monthly-gdp-by-industry-index-monthly-2023-2025",
        "UK monthly GDP index by industry section (index of production, services and construction), seasonally adjusted, monthly 2023-2025",
        "GB", "verified", "monthly_gdp_index_a_to_t", "decimal", "monthly", panel, MONTHLY_WINDOW, items,
        "Seasonally adjusted gross value added volume indices from the ONS GDP monthly estimate, which incorporates the "
        f"index of production and the index of services. The dataset metadata gives the unit as '{unit_text}', but the "
        "levels sit close to 100 in 2023, so the reference year in that field appears out of date; read the series as "
        "relative indices of output. The primary series is monthly GDP (sections A to T); "
        "the columns are the published aggregates (B-E production, G-T services, G and I distribution, hotels and restaurants, "
        "H and J transport and communication, K-N business services and finance, O-T government and other services) and each "
        "SIC 2007 section, keyed as sic_ plus the section code. Taken from the full time-series CSV of version 69 of the ONS "
        "gdp-to-four-decimal-places dataset; other months are dropped. ONS publishes its datasets under the Open Government "
        "Licence v3.0, as the cpih01 metadata states.",
        BASE_TAGS + ["gdp", "ons", "sic"], PE_USE_CASES + ["demand-forecasting", "market-sizing"],
    )


def bics_period(label: str) -> str | None:
    match = re.fullmatch(r"1 (\w+) (\d{4}) to \d+ \w+ \d{4}", label.strip())
    if not match:
        return None
    month = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].index(match.group(1)) + 1
    return f"{match.group(2)}-{month:02d}"


def build_bics(licence: dict) -> dict:
    source = load(BICS_URL)
    workbook = openpyxl.load_workbook(io.BytesIO(source.raw), read_only=True, data_only=True)

    def sheet_rows(name: str) -> list[tuple]:
        """Data rows of a weighted time-series sheet: everything below the header row that starts with Dates."""
        rows = list(workbook[name].iter_rows(values_only=True))
        start = next(i for i, row in enumerate(rows) if row and row[0] == "Dates")
        return [row for row in rows[start + 1:] if row and row[0]]

    turnover = sheet_rows("Turnover Expectations TS (WTD)")
    prices = sheet_rows("Price Expectations TS (WTD)")
    turnover_all = {bics_period(r[0]): r for r in turnover if r[2] == "All businesses" and bics_period(r[0])}
    prices_all = {bics_period(r[0]): r for r in prices if r[2] == "Not permanently stopped trading" and r[3] == "All businesses" and bics_period(r[0])}

    def column(rows: dict[str, tuple], index: int) -> dict[str, float]:
        return {p: r[index] for p, r in rows.items() if isinstance(r[index], (int, float))}

    panel = Panel(
        MONTHS,
        column(turnover_all, 3),
        {
            "turnover_stay_same": column(turnover_all, 4),
            "turnover_decrease": column(turnover_all, 5),
            "turnover_not_sure": column(turnover_all, 6),
            "prices_increase": column(prices_all, 4),
            "prices_stay_same": column(prices_all, 5),
            "prices_decrease": column(prices_all, 6),
            "prices_not_sure": column(prices_all, 7),
            "prices_not_applicable": column(prices_all, 8),
        },
    )
    title = "ONS Business Insights and Conditions Survey, wave 168 dataset (xlsx), weighted time series sheets"
    first_t, last_p = turnover_all[MONTHS[0]], prices_all[MONTHS[-1]]
    items = [
        cite(source, ONS, title, "sheet Turnover Expectations TS (WTD), header", "Expect turnover to increase", "text", "Expect turnover to increase", "OGL-UK-3.0"),
        cite(source, ONS, title, f"sheet Turnover Expectations TS (WTD), row {first_t[0].strip()}, {first_t[1]}, All businesses", first_t[3], "ratio", first_t[0].strip(), "OGL-UK-3.0"),
        cite(source, ONS, title, "sheet Price Expectations TS (WTD), header", "Prices will increase", "text", "Prices will increase", "OGL-UK-3.0"),
        cite(source, ONS, title, f"sheet Price Expectations TS (WTD), row {last_p[0].strip()}, {last_p[1]}, Not permanently stopped trading, All businesses", last_p[4], "ratio", last_p[0].strip(), "OGL-UK-3.0"),
        licence,
    ]
    return temporal(
        "gb-bics-turnover-and-price-expectations-monthly-2023-2025",
        "UK businesses' expectations for turnover and selling prices, weighted shares, all businesses, monthly 2023-2025 (BICS)",
        "GB", "verified", "share_expecting_turnover_increase", "ratio", "monthly", panel, MONTHLY_WINDOW, items,
        "Weighted shares of UK businesses from the ONS Business Insights and Conditions Survey (BICS), all industries and "
        "size bands. Each period is the month the expectation refers to; the question is asked in the wave fielded during "
        "the preceding month. The primary series is the share of businesses currently trading that expect turnover to "
        "increase; the turnover columns complete that question's answers. The price columns answer the question on "
        "expected prices of goods or services sold, as shares of businesses not permanently stopped trading. Shares are "
        "proportions between 0 and 1 as the workbook stores them. Taken from the weighted time-series sheets of the wave "
        "168 dataset, a fixed per-wave file; ONS publishes it under the Open Government Licence v3.0.",
        BASE_TAGS + ["leading-indicators", "business-confidence", "surveys", "pricing-power", "ons"], PE_USE_CASES + ["pricing", "demand-forecasting"],
    )


# ---------------------------------------------------------------------------------------------------------------


def main() -> int:
    builders: list[Callable[[], list[dict] | dict]] = [build_g17, build_m3, build_qss, build_mrts, build_mtis, build_vip, build_resconst, build_ecommerce, build_eurostat, build_oecd]
    for builder in builders:
        print(f"{builder.__name__}:")
        result = builder()
        for entry in result if isinstance(result, list) else [result]:
            write(entry)
    licence = ons_licence()
    for builder in (build_ons_gdp, build_bics):
        print(f"{builder.__name__}:")
        write(builder(licence))
    return 0


if __name__ == "__main__":
    sys.exit(main())

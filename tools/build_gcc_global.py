"""Regenerate the GCC migration, nationality, population, labour, remittance and health entries.

Gulf populations are majority foreign, so nationality mixes, the sex and age structure of migrants
and the flows of money sent home shape realistic synthetic customers and employees more than
anywhere else. Every source here is intergovernmental and fetched live:

* UN DESA Population Division, International Migrant Stock 2024 (destination and origin, and
  destination workbooks) and 2020 (age and sex), XLSX under CC BY 3.0 IGO.
* UN Population Division data portal location list, which maps M49 codes to ISO 3166 codes.
* World Bank API: population by five-year age group and sex, projections to 2050, personal
  remittances paid and the average cost of sending remittances (CC BY 4.0).
* ILOSTAT data API: employment by citizenship for Qatar, unemployment by citizenship for Saudi Arabia
  and Qatar, Saudi earnings by citizenship, ILO modelled employment by activity, and Oman's foreign
  citizens by country of citizenship.
* WHO Global Health Observatory OData API: adult obesity, overweight and diabetes prevalence by sex.

Each GCC state gets its own entries under its ISO 3166-1 region code (SA, AE, QA, KW, BH, OM), with
ids prefixed by that code; the multi-country source files are shared between them. Run from the
repository root:

    uv run python tools/build_gcc_global.py
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write
from build_labour import (
    ILO,
    ILO_LICENSE_NOTE,
    UNSTATED,
    CsvRow,
    IloTable,
    Source,
    csv_rows,
    lookup_entry,
    lookup_vectors,
    numeric,
    shares_of,
)

# ---------------------------------------------------------------- constants

GCC = ("SAU", "ARE", "QAT", "KWT", "BHR", "OMN")
GCC_QUERY = "+".join(GCC)

UNDESA = "United Nations Department of Economic and Social Affairs, Population Division"
UNDESA_FILES = "https://www.un.org/development/desa/pd/sites/www.un.org.development.desa.pd/files"
IMS_ORIGIN_URL = f"{UNDESA_FILES}/undesa_pd_2024_ims_stock_by_sex_destination_and_origin.xlsx"
IMS_DESTINATION_URL = f"{UNDESA_FILES}/undesa_pd_2024_ims_stock_by_sex_and_destination.xlsx"
IMS_AGE_URL = f"{UNDESA_FILES}/undesa_pd_2020_ims_stock_by_age_sex_and_destination.xlsx"
UN_LOCATIONS_URL = "https://population.un.org/dataportalapi/api/v1/locations?pageSize=500&pageNumber=1"
CC_BY_IGO = "CC-BY-3.0-IGO"
IGO_LICENSE_SNIPPET = "made available under a Creative Commons license CC BY 3.0 IGO"
UNDESA_LICENSE_NOTE = (
    " The workbook states that it is made available under CC BY 3.0 IGO. That licence permits reuse with attribution but is "
    "not on the verifier's permissive list, so the entry stays at license-review until a reviewer accepts it."
)

WORLD_BANK = "World Bank"
WB_API = "https://api.worldbank.org/v2"
WB_LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
CC_BY = "CC-BY-4.0"

ILO_API = "https://rplumber.ilo.org"
ILO_LABELS_URL = f"{ILO_API}/metadata/dic/?var=classif1&lang=en&format=.csv"

WHO = "World Health Organization (Global Health Observatory)"
GHO_API = "https://ghoapi.azureedge.net/api"
WHO_LICENSE_NOTE = (
    " The GHO API carries no licence statement, so the licence is recorded as unstated and the entry stays at "
    "license-review until a reviewer confirms the WHO terms that apply."
)

GCC_TAGS = ["gcc", "migration", "nationality"]
PEOPLE_USE_CASES = ["synthetic-customers", "synthetic-employees", "person-generation", "kyc-onboarding", "customer-segmentation"]
LABOUR_USE_CASES = ["synthetic-employees", "payroll-demo", "hr-analytics", "workforce-planning"]
REMITTANCE_USE_CASES = ["remittance-demo", "banking-demo", "payments-demo", "kyc-onboarding"]
TOP_ORIGINS = 30
OTHER = "OTHER"


# ---------------------------------------------------------------- shared helpers


def conditional(entry_id: str, title: str, domain: str, region: str, variable: str, given: str, distributions: dict[str, dict], items: list[dict], assumed: list[dict], tests: list[dict], tags: list[str], use_cases: list[str], notes: str, period: tuple[str, str], status: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "conditional",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": "ratio", "given": given, "distributions": distributions},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def categorical(counts: dict[str, float], **extra: Any) -> dict:
    return {"family": "categorical", "parameters": {"shares": shares_of(counts), "counts": counts, **extra}}


def share_tests(distributions: dict[str, dict], picks: Iterable[tuple[str, str]], tolerance: float = 0.005) -> list[dict]:
    """Share tests for chosen (given, category) pairs plus a sum-of-shares check for each conditioning value picked."""
    tests = []
    givens: list[str] = []
    for given, category in picks:
        tests.append({"statistic": f"share[{given},{category}]", "expected": distributions[given]["parameters"]["shares"][category], "tolerance": tolerance})
        if given not in givens:
            givens.append(given)
    return tests + [{"statistic": f"sum_of_shares[{given}]", "expected": 1, "tolerance": 1e-4} for given in givens]


def shares_assumption(parameter: str, rationale: str) -> dict:
    return {"parameter": parameter, "value": "count / total", "method": "derived", "rationale": rationale}


def top_with_remainder(counts: dict[str, float], total: float, limit: int) -> dict[str, float]:
    """The ``limit`` largest categories in descending order, plus the remainder of ``total`` under OTHER."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    kept = dict(ranked)
    remainder = total - sum(kept.values())
    if remainder > 0:
        kept[OTHER] = remainder
    return kept


def temporal(entry_id: str, title: str, domain: str, region: str, variable: str, unit: str, frequency: str, columns: list[str], series: list[dict], items: list[dict], assumed: list[dict], tests: list[dict], tags: list[str], use_cases: list[str], notes: str, period: tuple[str, str], status: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


@dataclass(frozen=True)
class Country:
    """A GCC state with the codes each source keys it by."""

    iso3: str
    iso2: str
    name: str
    m49: int

    @property
    def prefix(self) -> str:
        """The entry id prefix and lower-case region code, for example 'ae'."""
        return self.iso2.lower()


@dataclass
class Locations:
    """M49 numeric codes and ISO 3166 codes from the UN Population Division data portal."""

    source: Source
    by_m49: dict[int, dict] = field(init=False)
    by_iso3: dict[str, dict] = field(init=False)

    def __post_init__(self) -> None:
        records = json.loads(self.source.raw)["data"]
        self.by_m49 = {r["id"]: r for r in records}
        self.by_iso3 = {r["iso3"]: r for r in records if r.get("iso3")}

    def iso3(self, m49: int) -> str:
        record = self.by_m49.get(m49)
        return record["iso3"] if record and record.get("iso3") else f"M49-{m49}"

    def m49(self, iso3: str) -> int:
        return self.by_iso3[iso3]["id"]

    def country(self, iso3: str) -> Country:
        record = self.by_iso3[iso3]
        return Country(iso3, record["iso2"], record["name"], record["id"])

    def cite(self, iso3: str) -> dict:
        record = self.by_iso3[iso3]
        snippet = f'{{"id":{record["id"]},"name":"{record["name"]}","iso3":"{iso3}"'
        return self.source.cite(UNDESA, "UN Population Division data portal API, list of locations (M49 code, name, ISO codes)", f"data[iso3={iso3}].id", record["id"], "integer", snippet, UNSTATED, role="supporting")


# ---------------------------------------------------------------- UN DESA workbooks


class UnWorkbook:
    """A UN DESA XLSX: sheet rows through openpyxl and each sheet's XML so a cited cell quotes its stored markup."""

    def __init__(self, source: Source, sheets: Iterable[str]) -> None:
        self.source = source
        book = openpyxl.load_workbook(io.BytesIO(source.raw), read_only=True, data_only=True)
        self.rows = {name: list(book[name].iter_rows(values_only=True)) for name in sheets}
        archive = zipfile.ZipFile(io.BytesIO(source.raw))
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        targets = {rel_id: target for rel_id, target in re.findall(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}
        targets |= {rel_id: target for target, rel_id in re.findall(r'<Relationship[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels)}
        self._xml: dict[str, str] = {}
        for name, rel_id in re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', workbook_xml):
            if name in self.rows:
                target = targets[rel_id].lstrip("/")
                self._xml[name] = archive.read(target if target.startswith("xl/") else f"xl/{target}").decode("utf-8")

    def markup(self, sheet: str, row: int, column: int) -> str:
        """The stored ``<c>`` element of a cell given its zero-based row and column in ``rows``."""
        reference = f"{get_column_letter(column + 1)}{row + 1}"
        xml = self._xml[sheet]
        start = xml.find(f'<c r="{reference}"')
        if start < 0:
            raise ValueError(f"{sheet}!{reference} not found")
        return xml[start : xml.index("</c>", start) + len("</c>")]

    def cite(self, title: str, sheet: str, row: int, column: int, description: str, unit: str) -> dict:
        markup = self.markup(sheet, row, column)
        value = self.rows[sheet][row][column]
        if isinstance(value, float):
            # Excel stores up to 17 significant digits, which Python's shortest repr does not reproduce; quote the stored text.
            value = int(value) if value.is_integer() else re.search(r"<v>([^<]+)</v>", markup).group(1)
        reference = f"{get_column_letter(column + 1)}{row + 1}"
        return self.source.cite(UNDESA, title, f"{sheet}!{reference} ({description})", value, unit, markup, CC_BY_IGO)

    def cite_license(self, title: str) -> dict:
        return self.source.cite(UNDESA, title, "Table of contents, copyright line", "CC BY 3.0 IGO", "text", IGO_LICENSE_SNIPPET, CC_BY_IGO, role="supporting")


def header_row(rows: list[tuple], first: str) -> int:
    return next(i for i, row in enumerate(rows) if row and row[0] == first)


def year_columns(header: tuple, year: int) -> list[int]:
    """Positions of ``year`` in a header that repeats the year columns for both sexes, males and females."""
    return [i for i, cell in enumerate(header) if cell == year]


IMS_ORIGIN_TITLE = "International Migrant Stock 2024: Destination and origin (XLSX, Table 1)"
IMS_DESTINATION_TITLE = "International Migrant Stock 2024: Destination (XLSX, Tables 1 to 4)"
IMS_AGE_TITLE = "International Migrant Stock 2020: Age, sex and destination (XLSX, Table 1)"
DATA_TYPE_SNIPPET = "C, which indicates that estimates were derived from data on foreign citizens"


@dataclass
class OriginTable:
    """Migrant stock by destination and origin for the GCC destinations, read from Table 1 of the 2024 workbook."""

    book: UnWorkbook
    locations: Locations
    sheet: str = "Table 1"
    year: int = 2024

    def __post_init__(self) -> None:
        rows = self.book.rows[self.sheet]
        self.header = header_row(rows, "Index")
        self.both, self.male, self.female = year_columns(rows[self.header], self.year)
        self.by_destination: dict[str, list[int]] = {}
        codes = {self.locations.m49(iso3): iso3 for iso3 in GCC}
        for index, row in enumerate(rows[self.header + 1 :], start=self.header + 1):
            if isinstance(row[4], int) and row[4] in codes:
                self.by_destination.setdefault(codes[row[4]], []).append(index)

    def row(self, index: int) -> tuple:
        return self.book.rows[self.sheet][index]

    def world_row(self, iso3: str) -> int:
        return next(i for i in self.by_destination[iso3] if self.row(i)[6] == 900)

    def origin_rows(self, iso3: str) -> list[int]:
        """Rows for single origin countries (M49 codes below 900) and the residual 'Others' row."""
        return [i for i in self.by_destination[iso3] if self.row(i)[6] < 900 or self.row(i)[5] == "Others"]

    def counts(self, iso3: str, column: int) -> tuple[dict[str, int], int]:
        total = int(self.row(self.world_row(iso3))[column])
        counts: dict[str, int] = {}
        for index in self.origin_rows(iso3):
            row = self.row(index)
            if row[5] == "Others" or not isinstance(row[column], (int, float)):
                continue
            counts[self.locations.iso3(row[6])] = int(row[column])
        listed = sum(counts.values()) + sum(int(self.row(i)[column]) for i in self.origin_rows(iso3) if self.row(i)[5] == "Others")
        if abs(listed - total) > 0.01 * total:
            raise ValueError(f"{iso3}: origins sum to {listed}, world total is {total}")
        return counts, total

    def names(self, iso3: str) -> dict[str, str]:
        return {self.locations.iso3(self.row(i)[6]): self.row(i)[5].rstrip("*").strip() for i in self.origin_rows(iso3) if self.row(i)[5] != "Others"}

    def origin_index(self, destination: str, origin: str) -> int:
        return next(i for i in self.origin_rows(destination) if self.locations.iso3(self.row(i)[6]) == origin)

    def cite(self, index: int, column: int, sex: str) -> dict:
        row = self.row(index)
        return self.book.cite(IMS_ORIGIN_TITLE, self.sheet, index, column, f"destination {row[1]}, origin {row[5]}, {sex}, {self.year}", "count")


def ims_origin_entry(table: OriginTable, country: Country) -> dict:
    iso3 = country.iso3
    names = table.names(iso3)
    distributions: dict[str, dict] = {}
    for sex, column in (("total", table.both), ("male", table.male), ("female", table.female)):
        counts, total = table.counts(iso3, column)
        kept = top_with_remainder(counts, total, TOP_ORIGINS)
        distributions[sex] = categorical(kept, total_migrants=total, origin_names={k: names[k] for k in kept if k != OTHER}, year=table.year)
    leaders = {sex: next(k for k in d["parameters"]["shares"] if k != OTHER) for sex, d in distributions.items()}
    items = [
        table.cite(table.world_row(iso3), table.both, "both sexes"),
        table.cite(table.world_row(iso3), table.male, "males"),
        table.cite(table.world_row(iso3), table.female, "females"),
        table.cite(table.origin_index(iso3, leaders["total"]), table.both, "both sexes"),
        table.cite(table.origin_index(iso3, leaders["female"]), table.female, "females"),
        table.book.source.cite(UNDESA, IMS_ORIGIN_TITLE, "Migrant notes, type of data", "C", "text", DATA_TYPE_SNIPPET, CC_BY_IGO, role="supporting"),
        table.book.cite_license(IMS_ORIGIN_TITLE),
        table.locations.cite(iso3),
    ]
    data_type = table.row(table.world_row(iso3))[3]
    listed = len([k for k in distributions["total"]["parameters"]["shares"] if k != OTHER])
    return conditional(
        f"{country.prefix}-migrant-stock-by-country-of-origin-and-sex-{table.year}",
        f"{country.name}: international migrant stock by country of origin, given sex, mid-{table.year} (UN DESA)",
        "demographics", country.iso2, "country_of_origin_iso3", "sex", distributions, items,
        [
            shares_assumption("distributions[*].parameters.shares", "Each origin's 2024 migrant stock for the sex in question divided by the total migrant stock of that sex (origin 'World'); at most the 30 largest listed origins are kept and the rest of the total, including the workbook's 'Others' row, is pooled as OTHER."),
            {"parameter": "categories", "value": "ISO 3166-1 alpha-3", "method": "derived", "rationale": "The workbook identifies origins by M49 code; codes are mapped to ISO alpha-3 with the UN Population Division location list. A code without an ISO mapping would be kept as M49-<code>."},
        ],
        share_tests(distributions, [(sex, leaders[sex]) for sex in ("total", "male", "female")]),
        GCC_TAGS + ["international-migrant-stock", "country-of-origin", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["remittance-demo", "banking-demo"],
        f"Country-of-origin mix of the international migrants living in {country.name} at 1 July {table.year}, for both sexes ('total'), males and females, "
        "from UN DESA International Migrant Stock 2024 (destination and origin workbook, Table 1). "
        f"The type of data for {country.name} is '{data_type}': C means the estimates are derived from data on foreign citizens, so 'origin' is effectively "
        "the country of citizenship and the distribution can drive nationality for synthetic residents" + (" (R: refugees are added)" if "R" in str(data_type).split() else "") + ". "
        f"The workbook lists {listed} origin countries for {country.name}; at most the 30 largest per sex are kept, with the remainder (including the "
        "workbook's 'Others' row) pooled as OTHER. The origin mix of female migrants differs from that of male migrants, so draw nationality after sex. "
        "Counts (persons), the sex-specific total and the origin names ride alongside the shares; origins are keyed by ISO 3166-1 alpha-3 code." + UNDESA_LICENSE_NOTE,
        (f"{table.year}-07-01", f"{table.year}-07-01"), "license-review",
    )


@dataclass
class DestinationTables:
    """Tables 1 to 4 of the 2024 destination workbook, with each GCC state's row located in every table."""

    book: UnWorkbook
    countries: list[Country]
    names: tuple[str, ...] = ("Table 1", "Table 2", "Table 3", "Table 4")

    def __post_init__(self) -> None:
        self.headers = {name: next(i for i, r in enumerate(self.book.rows[name]) if 1990 in r) for name in self.names}
        first = self.book.rows["Table 1"]
        by_code = {c.m49: c.iso3 for c in self.countries}
        self.located: dict[str, dict[str, int]] = {}
        for index, row in enumerate(first[self.headers["Table 1"] + 1 :], start=self.headers["Table 1"] + 1):
            if isinstance(row[4], int) and row[4] in by_code:
                self.located[by_code[row[4]]] = {"Table 1": index}
        # Table 2 carries no location code, so the other tables are matched on the shared Index column and the name is checked.
        for at in self.located.values():
            key, name = first[at["Table 1"]][0], first[at["Table 1"]][1]
            for other in self.names[1:]:
                rows = self.book.rows[other]
                at[other] = next(i for i, r in enumerate(rows) if i > self.headers[other] and r[0] == key)
                if rows[at[other]][1] != name:
                    raise ValueError(f"{other} row {at[other]} is {rows[at[other]][1]!r}, expected {name!r}")

    def years(self) -> list[int]:
        return sorted({y for y in self.book.rows["Table 1"][self.headers["Table 1"]] if isinstance(y, int)})

    def column(self, table: str, year: int, block: int) -> int:
        """Column of ``year`` in the given block (0 both sexes, 1 males, 2 females)."""
        return year_columns(self.book.rows[table][self.headers[table]], year)[block]

    def value(self, iso3: str, table: str, year: int, block: int = 0) -> Any:
        return self.book.rows[table][self.located[iso3][table]][self.column(table, year, block)]

    def cite(self, iso3: str, table: str, year: int, block: int, description: str, unit: str) -> dict:
        return self.book.cite(IMS_DESTINATION_TITLE, table, self.located[iso3][table], self.column(table, year, block), description, unit)


def ims_stock_entry(tables: DestinationTables, country: Country) -> dict:
    iso3 = country.iso3
    years = tables.years()
    columns = [
        "migrant_stock", "migrant_stock_male", "migrant_stock_female",
        "total_population_thousands", "total_population_male_thousands", "total_population_female_thousands",
        "migrant_share_male_percent", "migrant_share_female_percent", "female_share_of_migrants_percent",
    ]
    series = []
    for year in years:
        series.append({
            "period": str(year),
            "value": tables.value(iso3, "Table 3", year),
            "migrant_stock": tables.value(iso3, "Table 1", year, 0),
            "migrant_stock_male": tables.value(iso3, "Table 1", year, 1),
            "migrant_stock_female": tables.value(iso3, "Table 1", year, 2),
            "total_population_thousands": tables.value(iso3, "Table 2", year, 0),
            "total_population_male_thousands": tables.value(iso3, "Table 2", year, 1),
            "total_population_female_thousands": tables.value(iso3, "Table 2", year, 2),
            "migrant_share_male_percent": tables.value(iso3, "Table 3", year, 1),
            "migrant_share_female_percent": tables.value(iso3, "Table 3", year, 2),
            "female_share_of_migrants_percent": tables.value(iso3, "Table 4", year),
        })
    first, last = years[0], years[-1]
    latest = series[-1]
    items = [
        tables.cite(iso3, "Table 3", last, 0, f"{country.name}, migrants as percentage of population, both sexes, {last}", "percent"),
        tables.cite(iso3, "Table 3", first, 0, f"{country.name}, migrants as percentage of population, both sexes, {first}", "percent"),
        tables.cite(iso3, "Table 1", last, 0, f"{country.name}, migrant stock, both sexes, {last}", "count"),
        tables.cite(iso3, "Table 1", last, 2, f"{country.name}, migrant stock, females, {last}", "count"),
        tables.cite(iso3, "Table 4", last, 0, f"{country.name}, female migrants as percentage of migrant stock, {last}", "percent"),
        tables.book.cite_license(IMS_DESTINATION_TITLE),
        tables.book.source.cite(UNDESA, IMS_DESTINATION_TITLE, "Notes, reference date", "Years given refer to 1 July.", "text", "Years given refer to 1 July.", CC_BY_IGO, role="supporting"),
    ]
    return temporal(
        f"{country.prefix}-international-migrant-stock-and-share-{first}-{last}",
        f"{country.name}: international migrant stock, total population and migrant share by sex, {first} to {last} (UN DESA)",
        "demographics", country.iso2, "migrant_share_of_population_percent", "percent", "annual", columns, series, items, [],
        [
            {"statistic": f"value[{last}]", "expected": latest["value"], "tolerance": 1e-9},
            {"statistic": f"value[{first}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"column[migrant_stock,{last}]", "expected": latest["migrant_stock"], "tolerance": 0},
            {"statistic": f"column[migrant_share_male_percent,{last}]", "expected": latest["migrant_share_male_percent"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        GCC_TAGS + ["international-migrant-stock", "migrant-share", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["market-sizing"],
        f"International migrants in {country.name} as a percentage of the total population (the series value, Table 3, both sexes) at 1 July of "
        f"{', '.join(str(y) for y in years)}, with the migrant stock for both sexes, males and females (Table 1), the total population in thousands by sex "
        "(Table 2), the migrant share among males and among females (Table 3) and female migrants as a percentage of all migrants (Table 4), from the UN DESA "
        "International Migrant Stock 2024 destination workbook. Values are copied unchanged. Observations are five years apart up to 2020 and four years "
        "apart after that; frequency 'annual' means one point per listed year. Use the latest value to split a synthetic population into nationals and "
        "foreign residents, and the male and female shares to reproduce the sex imbalance among migrants." + UNDESA_LICENSE_NOTE,
        (f"{first}-07-01", f"{last}-07-01"), "license-review",
    )


@dataclass
class AgeTable:
    """Migrant stock by five-year age group and sex in 2020, from Table 1 of the 2020 age and sex workbook."""

    book: UnWorkbook
    countries: list[Country]
    locations: Locations
    sheet: str = "Table 1"
    year: int = 2020

    def __post_init__(self) -> None:
        rows = self.book.rows[self.sheet]
        self.header = header_row(rows, "Index")
        self.labels = rows[self.header]
        totals = [i for i, cell in enumerate(self.labels) if cell == "Total"]
        first_age = self.labels.index("0-4")
        self.blocks = {"total": (first_age, totals[0]), "male": (totals[0] + 1, totals[1]), "female": (totals[1] + 1, totals[2])}
        by_code = {c.m49: c.iso3 for c in self.countries}
        self.found = {by_code[r[4]]: i for i, r in enumerate(rows) if i > self.header and r[1] == self.year and r[4] in by_code}

    def column(self, sex: str, label: str) -> int:
        start, end = self.blocks[sex]
        return next(i for i in range(start, end) if str(self.labels[i]).strip() == label)


def ims_age_entry(table: AgeTable, country: Country) -> dict:
    row_index = table.found[country.iso3]
    row = table.book.rows[table.sheet][row_index]
    distributions: dict[str, dict] = {}
    for sex, (start, end) in table.blocks.items():
        counts = {str(table.labels[i]).strip(): int(row[i]) for i in range(start, end)}
        published = int(row[end])
        if abs(sum(counts.values()) - published) > 0.01 * published:
            raise ValueError(f"{country.iso3} {sex}: age groups sum to {sum(counts.values())}, total is {published}")
        distributions[sex] = categorical(counts, total_migrants=published, year=table.year)
    modes = {sex: max(d["parameters"]["counts"], key=d["parameters"]["counts"].get) for sex, d in distributions.items()}
    items = [
        table.book.cite(IMS_AGE_TITLE, table.sheet, row_index, table.column("male", modes["male"]), f"{country.name}, {table.year}, males aged {modes['male']}", "count"),
        table.book.cite(IMS_AGE_TITLE, table.sheet, row_index, table.column("female", modes["female"]), f"{country.name}, {table.year}, females aged {modes['female']}", "count"),
        table.book.cite(IMS_AGE_TITLE, table.sheet, row_index, table.blocks["total"][1], f"{country.name}, {table.year}, both sexes, total", "count"),
        table.book.cite_license(IMS_AGE_TITLE),
        table.locations.cite(country.iso3),
    ]
    return conditional(
        f"{country.prefix}-migrant-stock-by-age-and-sex-{table.year}",
        f"{country.name}: international migrant stock by five-year age group, given sex, mid-{table.year} (UN DESA)",
        "demographics", country.iso2, "age_group", "sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Migrants in each five-year age group (0-4 to 75+) divided by the sum over the groups for that sex; the published total is kept beside the counts and differs from the sum only by rounding.")],
        share_tests(distributions, [(sex, modes[sex]) for sex in ("total", "male", "female")]),
        GCC_TAGS + ["international-migrant-stock", "by-age", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["hr-analytics"],
        f"Age distribution of the international migrants living in {country.name} at 1 July {table.year}, for both sexes ('total'), males and females, in "
        "sixteen five-year groups from 0-4 to 75+, from UN DESA International Migrant Stock 2020 (age, sex and destination workbook, Table 1). The 2024 "
        "revision's downloads carry no age breakdown, so 2020 is the latest age structure for migrants. Combined with the 2024 migrant share and the "
        "population pyramid it lets a generator give foreign residents their own age profile." + UNDESA_LICENSE_NOTE,
        (f"{table.year}-07-01", f"{table.year}-07-01"), "license-review",
    )



# ---------------------------------------------------------------- World Bank API


@dataclass
class WorldBankQuery:
    """A World Bank API JSON response holding one or more indicators for the GCC economies."""

    source: Source
    values: dict[tuple[str, str, str], float | None] = field(init=False)
    last_updated: str = field(init=False)

    def __post_init__(self) -> None:
        meta, records = json.loads(self.source.raw)
        if meta.get("pages", 1) != 1:
            raise ValueError(f"{self.source.url} is paginated")
        self.last_updated = meta["lastupdated"]
        self.values = {(r["indicator"]["id"], r["countryiso3code"], r["date"]): r["value"] for r in records}

    def value(self, indicator: str, iso3: str, year: int) -> float | None:
        return self.values.get((indicator, iso3, str(year)))

    def cite(self, title: str, indicator: str, iso3: str, year: int, unit: str) -> dict:
        pattern = rf'"indicator":\{{"id":"{re.escape(indicator)}","value":"[^"]*"\}},"country":\{{"id":"[A-Z0-9]+","value":"[^"]*"\}},"countryiso3code":"{iso3}","date":"{year}","value":[^,]+'
        match = re.search(pattern, self.source.raw.decode("utf-8"))
        if match is None:
            raise ValueError(f"{indicator} {iso3} {year} not in {self.source.url}")
        return self.source.cite(WORLD_BANK, title, f"[indicator={indicator}, countryiso3code={iso3}, date={year}].value", self.value(indicator, iso3, year), unit, match.group(0), CC_BY)


def wb_url(indicators: Iterable[str], dates: str, source_id: int | None = None) -> str:
    suffix = f"&source={source_id}" if source_id else ""
    return f"{WB_API}/country/{';'.join(GCC)}/indicator/{';'.join(indicators)}?date={dates}&format=json&per_page=1000{suffix}"


def wb_license(source: Source) -> dict:
    return source.cite(WORLD_BANK, "World Bank Data Catalog public licenses", "Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", CC_BY, role="supporting")


def wb_metadata(source: Source, indicator: str, snippet: str) -> dict:
    return source.cite(WORLD_BANK, f"World Bank indicator metadata, {indicator}", "sourceOrganization", snippet, "text", snippet, CC_BY, role="supporting")


AGE_BANDS = ("0004", "0509", "1014", "1519", "2024", "2529", "3034", "3539", "4044", "4549", "5054", "5559", "6064", "6569", "7074", "7579", "80UP")


def band_label(band: str) -> str:
    return "80+" if band == "80UP" else f"{int(band[:2])}-{int(band[2:])}"


def wb_age_entry(query: WorldBankQuery, metadata: Source, license_source: Source, country: Country, year: int) -> dict:
    iso3 = country.iso3
    distributions: dict[str, dict] = {}
    for sex, suffix in (("male", "MA"), ("female", "FE")):
        counts = {band_label(b): query.value(f"SP.POP.{b}.{suffix}", iso3, year) for b in AGE_BANDS}
        if any(v is None for v in counts.values()):
            raise ValueError(f"{iso3} {sex} {year}: missing age groups")
        distributions[sex] = categorical({k: int(v) for k, v in counts.items()}, year=year)
    title = f"World Bank API, population by five-year age group and sex (SP.POP.<age>.MA/FE), source 40, {year}, GCC economies"
    modes = {sex: max(d["parameters"]["counts"], key=d["parameters"]["counts"].get) for sex, d in distributions.items()}
    band_of = {band_label(b): b for b in AGE_BANDS}
    items = [
        query.cite(title, f"SP.POP.{band_of[modes['male']]}.MA", iso3, year, "count"),
        query.cite(title, f"SP.POP.{band_of[modes['female']]}.FE", iso3, year, "count"),
        query.cite(title, "SP.POP.0004.FE", iso3, year, "count"),
        wb_metadata(metadata, "SP.POP.0004.MA", "age\\/sex distributions of the United Nations Population Division's World Population Prospects"),
        wb_license(license_source),
    ]
    return conditional(
        f"{country.prefix}-population-by-age-and-sex-{year}",
        f"{country.name}: population by five-year age group, given sex, {year} (World Bank, based on UN World Population Prospects)",
        "demographics", country.iso2, "age_group", "sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Persons in each five-year age group divided by the sum of the seventeen groups (0-4 to 80+) for that sex.")],
        share_tests(distributions, [("male", modes["male"]), ("female", modes["female"]), ("female", "0-4")]),
        ["gcc", "population", "age-pyramid", "by-age", "by-sex", "world-bank"], PEOPLE_USE_CASES + ["insurance", "pensions"],
        f"Mid-year {year} population of {country.name} in seventeen five-year age groups (0-4 to 80+) for males and females, from the World Bank "
        "Population estimates and projections database (API source 40, indicators SP.POP.0004.MA to SP.POP.80UP.FE). The World Bank derives these from "
        "its total population and the age and sex distributions of the UN World Population Prospects. Counts ride beside the shares, so a generator can "
        "reproduce both the shape of each pyramid and the ratio of men to women at each age, which migrant labour skews in the GCC. "
        f"Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{year}-01-01", f"{year}-12-31"), "verified",
    )


def wb_projection_entry(query: WorldBankQuery, metadata: Source, license_source: Source, country: Country, first: int, last: int) -> dict:
    iso3 = country.iso3
    rows = {
        str(year): {
            "total": int(query.value("SP.POP.TOTL", iso3, year)),
            "male": int(query.value("SP.POP.TOTL.MA.IN", iso3, year)),
            "female": int(query.value("SP.POP.TOTL.FE.IN", iso3, year)),
        }
        for year in range(first, last + 1)
    }
    title = f"World Bank API, population total, male and female, source 40 (Population estimates and projections), {first}-{last}, GCC economies"
    items = [
        query.cite(title, "SP.POP.TOTL", iso3, first, "count"),
        query.cite(title, "SP.POP.TOTL", iso3, last, "count"),
        query.cite(title, "SP.POP.TOTL.MA.IN", iso3, last, "count"),
        query.cite(title, "SP.POP.TOTL.FE.IN", iso3, last, "count"),
        wb_metadata(metadata, "SP.POP.TOTL.MA.IN", "World Population Prospects, United Nations (UN), publisher: UN Population Division"),
        wb_license(license_source),
    ]
    first_key, last_key = str(first), str(last)
    return lookup_entry(
        f"{country.prefix}-population-projections-{first}-{last}",
        f"{country.name}: total, male and female population, annual {first} to {last} (World Bank population projections)",
        "demographics", country.iso2, rows, {"source": "World Bank API source 40", "indicators": {"total": "SP.POP.TOTL", "male": "SP.POP.TOTL.MA.IN", "female": "SP.POP.TOTL.FE.IN"}, "url": query.source.url},
        lookup_vectors(rows, "total", (first_key, last_key)) + [{"input": {"key": last_key, "column": "male"}, "expected": rows[last_key]["male"], "origin": "source"}],
        items,
        [
            {"statistic": f"value[{first_key},total]", "expected": rows[first_key]["total"], "tolerance": 0},
            {"statistic": f"value[{last_key},female]", "expected": rows[last_key]["female"], "tolerance": 0},
            {"statistic": "max[total]", "expected": max(r["total"] for r in rows.values()), "tolerance": 0},
        ],
        ["gcc", "population", "projections", "by-sex", "world-bank"], PEOPLE_USE_CASES + ["market-sizing", "demand-forecasting"],
        f"Total, male and female mid-year population of {country.name} for every year from {first} to {last}, from the World Bank Population estimates "
        "and projections database (API source 40: SP.POP.TOTL, SP.POP.TOTL.MA.IN, SP.POP.TOTL.FE.IN), which builds on the UN World Population "
        "Prospects. Years after the latest estimate are projections, not observations, so the table is a reference keyed by year (valid_to is the end "
        f"of the projection horizon) rather than an observed series. Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{first}-01-01", f"{last}-12-31"),
    )


REMITTANCES_PAID = "BM.TRF.PWKR.CD.DT"
REMITTANCE_COST = "SI.RMT.COST.OB.ZS"


def wb_remittance_entry(paid: WorldBankQuery, cost: WorldBankQuery, metadata: dict[str, Source], license_source: Source, country: Country, first: int, last: int) -> dict:
    iso3 = country.iso3
    rows: dict[str, dict] = {}
    for year in range(first, last + 1):
        record = {"personal_remittances_paid_usd": paid.value(REMITTANCES_PAID, iso3, year), "sending_cost_percent": cost.value(REMITTANCE_COST, iso3, year)}
        if any(v is not None for v in record.values()):
            rows[str(year)] = record
    paid_years = [y for y, r in rows.items() if r["personal_remittances_paid_usd"] is not None]
    cost_years = [y for y, r in rows.items() if r["sending_cost_percent"] is not None]
    paid_title = f"World Bank API, {REMITTANCES_PAID} (Personal remittances, paid, current US$), {first}-{last}, GCC economies"
    cost_title = f"World Bank API, {REMITTANCE_COST} (Average transaction cost of sending remittances from a specific country, %), GCC economies"
    items = [
        paid.cite(paid_title, REMITTANCES_PAID, iso3, int(paid_years[-1]), "currency:USD"),
        paid.cite(paid_title, REMITTANCES_PAID, iso3, int(paid_years[0]), "currency:USD"),
        cost.cite(cost_title, REMITTANCE_COST, iso3, int(cost_years[-1]), "percent"),
        wb_metadata(metadata[REMITTANCES_PAID], REMITTANCES_PAID, "IMF balance of payments data, International Monetary Fund (IMF)"),
        wb_metadata(metadata[REMITTANCE_COST], REMITTANCE_COST, "Remittance Prices Worldwide, World Bank (WB)"),
        wb_license(license_source),
    ]
    vectors = [
        {"input": {"key": paid_years[-1], "column": "personal_remittances_paid_usd"}, "expected": rows[paid_years[-1]]["personal_remittances_paid_usd"], "origin": "source"},
        {"input": {"key": cost_years[-1], "column": "sending_cost_percent"}, "expected": rows[cost_years[-1]]["sending_cost_percent"], "origin": "source"},
        {"input": "1990", "expected": False, "origin": "derived"},
    ]
    gaps = [y for y in rows if None in rows[y].values()]
    period = (min(rows), max(rows))
    return lookup_entry(
        f"{country.prefix}-remittance-outflows-and-sending-cost-{period[0]}-{period[1]}",
        f"{country.name}: personal remittances paid (US$) and average cost of sending remittances (%), annual {period[0]} to {period[1]} (World Bank)",
        "payments", country.iso2, rows, {"indicators": {"personal_remittances_paid_usd": REMITTANCES_PAID, "sending_cost_percent": REMITTANCE_COST}, "urls": [paid.source.url, cost.source.url]},
        vectors, items,
        [
            {"statistic": f"value[{paid_years[-1]},personal_remittances_paid_usd]", "expected": rows[paid_years[-1]]["personal_remittances_paid_usd"], "tolerance": 1e-3},
            {"statistic": "max[personal_remittances_paid_usd]", "expected": max(rows[y]["personal_remittances_paid_usd"] for y in paid_years), "tolerance": 1e-3},
            {"statistic": f"value[{cost_years[-1]},sending_cost_percent]", "expected": rows[cost_years[-1]]["sending_cost_percent"], "tolerance": 1e-9},
        ],
        ["gcc", "remittances", "migration", "balance-of-payments", "fees", "world-bank"], REMITTANCE_USE_CASES + ["pricing", "market-sizing"],
        f"For {country.name}, one row per year: personal remittances paid in current US dollars (indicator {REMITTANCES_PAID}: personal transfers plus "
        "compensation of employees paid to non-residents, from IMF balance of payments data and World Bank staff estimates) and the average total cost, as a "
        f"percentage of the amount sent, of sending USD 200 from {country.name} across the providers in the World Bank's Remittance Prices Worldwide database "
        f"(indicator {REMITTANCE_COST}). Remittances paid are published for {paid_years[0]} to {paid_years[-1]} and the cost for {cost_years[0]} to {cost_years[-1]}"
        + (f"; a column is null where that indicator has no value ({', '.join(gaps)})" if gaps else "") + ". The outflow sets the annual scale of a synthetic "
        "outbound remittance ledger and the cost prices its fees; the destination mix can be taken from the UN DESA migrant-stock-by-origin entry. Rows are "
        f"keyed by year. Data last updated {paid.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{period[0]}-01-01", f"{period[1]}-12-31"),
    )



# ---------------------------------------------------------------- ILOSTAT


def ilo_query(indicator: str, areas: str, year: int) -> str:
    """An ILOSTAT data API query closed to exactly one year, so later revisions and projections stay out."""
    return f"{ILO_API}/data/indicator/?id={indicator}&ref_area={areas}&timefrom={year}&timeto={year}&format=.csv"


@dataclass
class IloLabels:
    """English labels for ILOSTAT classification codes, from the classif1 dictionary."""

    source: Source
    labels: dict[str, str] = field(init=False)
    lines: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        # A few labels span two lines; their continuation lines parse to a single field and are skipped.
        parsed = [r for r in csv_rows(self.source.raw) if "classif1.label" in r.fields]
        self.labels = {r["classif1"]: r["classif1.label"] for r in parsed}
        self.lines = {r["classif1"]: r.line for r in parsed}

    def label(self, code: str) -> str:
        return self.labels[code].split(": ", 1)[1] if ": " in self.labels[code] else self.labels[code]

    def cite(self, code: str) -> dict:
        return self.source.cite(ILO, "ILOSTAT metadata API, classif1 dictionary (English labels), CSV", f"classif1={code}", self.labels[code], "text", self.lines[code], UNSTATED, role="supporting")


SEXES = {"SEX_T": "total", "SEX_M": "men", "SEX_F": "women"}
CITIZENSHIP = {"CCT_CIT_TOTAL": "all", "CCT_CIT_CITIZEN": "citizens", "CCT_CIT_NONCIT": "foreign_citizens"}


def ilo_table(indicator: str, name: str, areas: str, year: int) -> IloTable:
    return IloTable(indicator, name, Source(ilo_query(indicator, areas, year)))


def by_citizenship_and_sex(table: IloTable, area: str, year: int, prefix: str, total: str) -> tuple[dict[str, dict[str, float]], dict[str, CsvRow]]:
    """Counts per category for each citizenship and sex, with the total row of each group for checking."""
    groups: dict[str, dict[str, float]] = {}
    totals: dict[str, CsvRow] = {}
    for row in table.select(ref_area=area, time=str(year)):
        if row["classif2"] not in CITIZENSHIP:
            continue
        key = f"{CITIZENSHIP[row['classif2']]}:{SEXES[row['sex']]}"
        if row["classif1"] == total:
            totals[key] = row
        elif row["classif1"].startswith(prefix):
            groups.setdefault(key, {})[row["classif1"]] = float(row["obs_value"])
    for key, counts in groups.items():
        published = float(totals[key]["obs_value"])
        if abs(sum(counts.values()) - published) > 0.01 * published:
            raise ValueError(f"{table.indicator} {key}: categories sum to {sum(counts.values())}, total is {published}")
    return groups, totals


def ilo_citizenship_conditional(table: IloTable, labels: IloLabels, area: str, region: str, year: int, prefix: str, total: str, entry_id: str, title: str, variable: str, picks: list[tuple[str, str]], cited: list[tuple[str, str]], tags: list[str], notes: str) -> dict:
    groups, totals = by_citizenship_and_sex(table, area, year, prefix, total)
    codes = sorted({code for counts in groups.values() for code in counts})
    distributions = {
        key: {"family": "categorical", "parameters": {"shares": shares_of(counts), "thousand_persons": counts, "labels": {c: labels.label(c) for c in counts}, "year": year}}
        for key, counts in sorted(groups.items())
    }
    items = []
    for key, code in cited:
        cit, sex = key.split(":")
        row = next(r for r in table.select(ref_area=area, time=str(year), classif1=code) if CITIZENSHIP.get(r["classif2"]) == cit and SEXES[r["sex"]] == sex)
        items.append(table.cite(row, f"ref_area={area}, sex={row['sex']}, classif1={code}, classif2={row['classif2']}", "count"))
    items.append(table.cite(totals["foreign_citizens:total"], f"ref_area={area}, sex=SEX_T, classif1={total}, classif2=CCT_CIT_NONCIT", "count"))
    items += [labels.cite(codes[0]), labels.cite("CCT_CIT_NONCIT")]
    return conditional(
        entry_id, title, "employment", region, variable, "citizenship_and_sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "ILOSTAT publishes thousands of employed persons per category; shares are each category over the sum of the categories for that citizenship and sex, kept only where the sum is within one percent of the published total.")],
        share_tests(distributions, picks),
        tags, LABOUR_USE_CASES + ["synthetic-customers", "person-generation"],
        notes + " Conditioning keys are '<citizenship>:<sex>' with citizenship all, citizens or foreign_citizens and sex total, men or women; the "
        "published thousands and the English category labels ride alongside the shares. " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), "license-review",
    )


def qa_employment_by_activity(labels: IloLabels, year: int) -> dict:
    table = ilo_table("EMP_TEMP_SEX_ECO_CCT_NB_A", "Employment by sex, economic activity and citizenship (thousands)", "QAT", year)
    return ilo_citizenship_conditional(
        table, labels, "QAT", "QA", year, "ECO_AGGREGATE_", "ECO_AGGREGATE_TOTAL",
        f"qa-employment-by-activity-and-citizenship-{year}", f"Qatar employment by aggregate economic activity, given citizenship and sex, {year} (ILOSTAT, labour force survey)",
        "economic_activity_aggregate",
        [("citizens:total", "ECO_AGGREGATE_PUB"), ("foreign_citizens:men", "ECO_AGGREGATE_CON"), ("foreign_citizens:women", "ECO_AGGREGATE_PUB"), ("all:total", "ECO_AGGREGATE_MKT")],
        [("citizens:total", "ECO_AGGREGATE_PUB"), ("foreign_citizens:men", "ECO_AGGREGATE_CON")],
        GCC_TAGS + ["employment", "economic-activity", "by-citizenship", "by-sex", "ilostat", "labour-force-survey"],
        f"Employed persons in Qatar in {year} by aggregate economic activity (agriculture; manufacturing; construction; mining, electricity, gas and water; "
        "market services; public administration, community, social and other services) for citizens and foreign citizens, by sex, from ILOSTAT indicator "
        "EMP_TEMP_SEX_ECO_CCT_NB (labour force survey). Citizens work overwhelmingly in public administration and services while most foreign men work in "
        "construction and market services, so drawing the sector after nationality gives a realistic synthetic workforce.",
    )


def qa_employment_by_skill(labels: IloLabels, year: int) -> dict:
    table = ilo_table("EMP_TEMP_SEX_OCU_CCT_NB_A", "Employment by sex, occupation and citizenship (thousands)", "QAT", year)
    return ilo_citizenship_conditional(
        table, labels, "QAT", "QA", year, "OCU_SKILL_", "OCU_SKILL_TOTAL",
        f"qa-employment-by-skill-level-and-citizenship-{year}", f"Qatar employment by occupational skill level, given citizenship and sex, {year} (ILOSTAT, labour force survey)",
        "occupation_skill_level",
        [("citizens:total", "OCU_SKILL_L3-4"), ("foreign_citizens:men", "OCU_SKILL_L2"), ("foreign_citizens:women", "OCU_SKILL_L1"), ("all:total", "OCU_SKILL_L2")],
        [("citizens:total", "OCU_SKILL_L3-4"), ("foreign_citizens:women", "OCU_SKILL_L1")],
        GCC_TAGS + ["employment", "occupations", "skill-level", "isco-08", "by-citizenship", "by-sex", "ilostat"],
        f"Employed persons in Qatar in {year} by occupational skill level (ISCO-08 skill level 1 low, level 2 medium, levels 3 and 4 high) for citizens "
        "and foreign citizens, by sex, from ILOSTAT indicator EMP_TEMP_SEX_OCU_CCT_NB (labour force survey). The skill mix differs sharply between "
        "nationals and migrants and between foreign men and women.",
    )


def qa_employment_by_age(labels: IloLabels, year: int) -> dict:
    table = ilo_table("EMP_TEMP_SEX_AGE_CCT_NB_A", "Employment by sex, age and citizenship (thousands)", "QAT", year)
    return ilo_citizenship_conditional(
        table, labels, "QAT", "QA", year, "AGE_AGGREGATE_Y", "AGE_AGGREGATE_YGE15",
        f"qa-employment-by-age-and-citizenship-{year}", f"Qatar employment by broad age group, given citizenship and sex, {year} (ILOSTAT, labour force survey)",
        "age_group",
        [("citizens:total", "AGE_AGGREGATE_Y15-24"), ("foreign_citizens:men", "AGE_AGGREGATE_Y25-54"), ("foreign_citizens:women", "AGE_AGGREGATE_Y25-54"), ("all:total", "AGE_AGGREGATE_Y55-64")],
        [("citizens:total", "AGE_AGGREGATE_Y15-24"), ("foreign_citizens:men", "AGE_AGGREGATE_Y25-54")],
        GCC_TAGS + ["employment", "by-age", "by-citizenship", "by-sex", "ilostat"],
        f"Employed persons in Qatar in {year} in the broad age groups 15-24, 25-54, 55-64 and 65+ for citizens and foreign citizens, by sex, from ILOSTAT "
        "indicator EMP_TEMP_SEX_AGE_CCT_NB (labour force survey), for assigning ages to synthetic employees by nationality.",
    )


UNEMPLOYMENT_AGES = {"AGE_YTHADULT_YGE15": "age_15_plus", "AGE_YTHADULT_Y15-24": "age_15_24", "AGE_YTHADULT_YGE25": "age_25_plus", "AGE_YTHADULT_Y15-64": "age_15_64"}


def unemployment_by_citizenship(country: Country, year: int) -> dict:
    table = ilo_table("UNE_DEAP_SEX_AGE_CCT_RT_A", "Unemployment rate by sex, age and citizenship (%)", country.iso3, year)
    rows: dict[str, dict] = {}
    for row in table.rows:
        if row["classif1"] in UNEMPLOYMENT_AGES and row["classif2"] in CITIZENSHIP:
            rows.setdefault(f"{CITIZENSHIP[row['classif2']]}:{SEXES[row['sex']]}", {})[UNEMPLOYMENT_AGES[row["classif1"]]] = numeric(row["obs_value"])
    rows = {key: {column: record.get(column) for column in UNEMPLOYMENT_AGES.values()} for key, record in sorted(rows.items())}
    cited = {("AGE_YTHADULT_YGE15", "CCT_CIT_CITIZEN", "SEX_F"), ("AGE_YTHADULT_YGE15", "CCT_CIT_NONCIT", "SEX_M"), ("AGE_YTHADULT_Y15-24", "CCT_CIT_NONCIT", "SEX_T")}
    items = [table.cite(r, f"ref_area={country.iso3}, sex={r['sex']}, classif1={r['classif1']}, classif2={r['classif2']}", "percent") for r in table.rows if (r["classif1"], r["classif2"], r["sex"]) in cited]
    lead = "age_15_plus"
    missing = sorted({column for record in rows.values() for column, value in record.items() if value is None})
    return lookup_entry(
        f"{country.prefix}-unemployment-rate-by-citizenship-sex-and-age-{year}",
        f"{country.name}: unemployment rate by citizenship, sex and age group, {year} (ILOSTAT, labour force survey)",
        "employment", country.iso2, rows, {"indicator": table.indicator, "url": table.source.url, "year": year, "age_columns": UNEMPLOYMENT_AGES},
        lookup_vectors(rows, lead, ("citizens:women", "foreign_citizens:men", "all:total")), items,
        [
            {"statistic": f"value[citizens:women,{lead}]", "expected": rows["citizens:women"][lead], "tolerance": 1e-9},
            {"statistic": "value[foreign_citizens:total,age_15_24]", "expected": rows["foreign_citizens:total"]["age_15_24"], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values()), "tolerance": 1e-9},
        ],
        GCC_TAGS + ["unemployment", "by-citizenship", "by-sex", "by-age", "ilostat", "labour-force-survey"], LABOUR_USE_CASES + ["credit-risk", "synthetic-customers"],
        f"Unemployment rate (percent of the labour force) in {country.name} in {year} for citizens, foreign citizens and all persons, by sex, for ages 15+, "
        "15-24, 25+ and 15-64, from ILOSTAT indicator UNE_DEAP_SEX_AGE_CCT_RT (labour force survey). The query is closed to that one year. Rows are keyed "
        "'<citizenship>:<sex>' with citizenship all, citizens or foreign_citizens and sex total, men or women"
        + (f"; {', '.join(missing)} is null where ILOSTAT publishes no value" if missing else "") + ". " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), status="license-review",
    )


@dataclass
class ModelledEmployment:
    """ILO modelled estimates of employment by sex and ISIC Rev.4 section group for the GCC economies in one year."""

    labels: IloLabels
    year: int
    table: IloTable = field(init=False)

    def __post_init__(self) -> None:
        self.table = ilo_table("EMP_2EMP_SEX_ECO_NB_A", "Employment by sex and economic activity, ILO modelled estimates (thousands)", GCC_QUERY, self.year)

    def counts(self, area: str, sex_code: str) -> dict[str, float]:
        selected = self.table.select(ref_area=area, sex=sex_code, time=str(self.year))
        counts = {r["classif1"]: float(r["obs_value"]) for r in selected if r["classif1"].startswith("ECO_ISIC4_") and r["classif1"] != "ECO_ISIC4_TOTAL"}
        total = next(float(r["obs_value"]) for r in selected if r["classif1"] == "ECO_ISIC4_TOTAL")
        if abs(sum(counts.values()) - total) > 0.01 * total:
            raise ValueError(f"{area} {sex_code}: sections sum to {sum(counts.values())}, total is {total}")
        return counts

    def row(self, area: str, sex_code: str, code: str) -> CsvRow:
        return next(r for r in self.table.select(ref_area=area, sex=sex_code, classif1=code, time=str(self.year)))


def employment_by_activity(modelled: ModelledEmployment, country: Country) -> dict:
    year, area = modelled.year, country.iso3
    distributions: dict[str, dict] = {}
    for code, sex in SEXES.items():
        counts = modelled.counts(area, code)
        distributions[sex] = {"family": "categorical", "parameters": {"shares": shares_of(counts), "thousand_persons": counts, "labels": {c: modelled.labels.label(c) for c in counts}, "year": year}}
    leaders = {sex: max(d["parameters"]["thousand_persons"], key=d["parameters"]["thousand_persons"].get) for sex, d in distributions.items()}
    items = [
        modelled.table.cite(modelled.row(area, "SEX_M", leaders["men"]), f"ref_area={area}, sex=SEX_M, classif1={leaders['men']}", "count"),
        modelled.table.cite(modelled.row(area, "SEX_F", leaders["women"]), f"ref_area={area}, sex=SEX_F, classif1={leaders['women']}", "count"),
        modelled.table.cite(modelled.row(area, "SEX_T", "ECO_ISIC4_TOTAL"), f"ref_area={area}, sex=SEX_T, classif1=ECO_ISIC4_TOTAL", "count"),
        modelled.labels.cite(leaders["men"]),
        modelled.labels.cite("ECO_ISIC4_LMN"),
    ]
    return conditional(
        f"{country.prefix}-employment-by-economic-activity-and-sex-{year}",
        f"{country.name}: employment by ISIC Rev.4 section group, given sex, {year} (ILO modelled estimates)",
        "employment", country.iso2, "isic_rev4_section_group", "sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Thousands employed in each ISIC Rev.4 section group divided by the sum over the groups for that sex, kept only where the sum is within one percent of the published ECO_ISIC4_TOTAL.")],
        share_tests(distributions, [(sex, leaders[sex]) for sex in ("total", "men", "women")]),
        ["gcc", "employment", "economic-activity", "isic-rev4", "by-sex", "ilostat", "modelled-estimates"], LABOUR_USE_CASES + ["company-generation", "market-sizing"],
        f"Employment in {country.name} in {year} in fourteen ISIC Rev.4 section groups (A; B; C; D and E; F; G; H and J; I; K; L, M and N; O; P; Q; R, S, T and U) "
        "for all persons ('total'), men and women, from ILOSTAT indicator EMP_2EMP_SEX_ECO_NB (ILO modelled estimates). The modelled series covers all six GCC "
        "states for the same year, which the survey series do not. Codes keep the ILOSTAT form (ECO_ISIC4_<sections>); the parameters carry the English "
        "labels and the thousands employed. The query is closed to one year so that projections for later years stay out. " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), "license-review",
    )


def sa_earnings_by_citizenship(year: int) -> dict:
    table = ilo_table("EAR_EMTA_SEX_CCT_CUR_NB_A", "Average monthly earnings of employees by sex, citizenship and currency", "SAU", year)
    currencies = {"CUR_TYPE_LCU": "sar", "CUR_TYPE_USD": "usd", "CUR_TYPE_PPP": "usd_ppp"}
    rows: dict[str, dict] = {}
    for row in table.rows:
        if row["classif1"] in CITIZENSHIP and row["classif2"] in currencies:
            rows.setdefault(f"{CITIZENSHIP[row['classif1']]}:{SEXES[row['sex']]}", {})[f"mean_monthly_earnings_{currencies[row['classif2']]}"] = numeric(row["obs_value"])
    rows = dict(sorted(rows.items()))
    pick = {("CCT_CIT_CITIZEN", "SEX_M", "CUR_TYPE_LCU"), ("CCT_CIT_NONCIT", "SEX_F", "CUR_TYPE_LCU"), ("CCT_CIT_NONCIT", "SEX_T", "CUR_TYPE_USD")}
    items = [table.cite(r, f"ref_area=SAU, sex={r['sex']}, classif1={r['classif1']}, classif2={r['classif2']}", "currency:USD" if r["classif2"] == "CUR_TYPE_USD" else "currency:SAR") for r in table.rows if (r["classif1"], r["sex"], r["classif2"]) in pick]
    lead = "mean_monthly_earnings_sar"
    return lookup_entry(
        f"sa-mean-monthly-earnings-by-sex-and-citizenship-{year}", f"Saudi Arabia mean monthly earnings of employees by citizenship and sex, {year}, in SAR, US$ and PPP US$ (ILOSTAT)",
        "income", "SA", rows, {"indicator": table.indicator, "url": table.source.url, "year": year, "currency": "SAR"},
        lookup_vectors(rows, lead, ("citizens:men", "foreign_citizens:women")), items,
        [
            {"statistic": f"value[citizens:total,{lead}]", "expected": rows["citizens:total"][lead], "tolerance": 1e-9},
            {"statistic": f"value[foreign_citizens:total,{lead}]", "expected": rows["foreign_citizens:total"][lead], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values()), "tolerance": 1e-9},
        ],
        GCC_TAGS + ["earnings", "pay", "by-citizenship", "by-sex", "ilostat", "labour-force-survey"], LABOUR_USE_CASES + ["synthetic-customers", "credit-risk"],
        f"Mean nominal monthly earnings of employees in Saudi Arabia in {year} for citizens, foreign citizens and all employees, by sex, in Saudi riyals, "
        "US dollars and PPP dollars, from ILOSTAT indicator EAR_EMTA_SEX_CCT_CUR_NB (labour force survey). This is the latest year ILOSTAT holds for the "
        "series. Citizens' mean earnings are well above those of foreign citizens for both sexes, so synthetic salaries should be drawn after nationality. Rows are keyed "
        "'<citizenship>:<sex>'. " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), status="license-review",
    )


def om_foreign_citizens(labels: IloLabels, locations: Locations, year: int) -> dict:
    sources = {
        "working_age_population": ilo_table("POP_MFRC_SEX_CCT_NB_A", "Working age foreign citizens by sex and country of citizenship (thousands)", "OMN", year),
        "employed": ilo_table("EMP_MFRC_SEX_CCT_NB_A", "Employed foreign citizens by sex and country of citizenship (thousands)", "OMN", year),
    }
    distributions: dict[str, dict] = {}
    for population, table in sources.items():
        for code, sex in SEXES.items():
            selected = table.select(ref_area="OMN", sex=code, time=str(year))
            counts = {(OTHER if r["classif1"] == "CCT_CTZ_X" else r["classif1"].removeprefix("CCT_CTZ_")): float(r["obs_value"]) for r in selected if r["classif1"] != "CCT_CTZ_TOTAL"}
            total = next(float(r["obs_value"]) for r in selected if r["classif1"] == "CCT_CTZ_TOTAL")
            if abs(sum(counts.values()) - total) > 0.01 * total:
                raise ValueError(f"OMN {population} {sex}: countries sum to {sum(counts.values())}, total is {total}")
            names = {k: labels.label(f"CCT_CTZ_{k}") for k in counts if k != OTHER}
            unknown = [k for k in names if k not in locations.by_iso3]
            if unknown:
                raise ValueError(f"citizenship codes {unknown} are not ISO alpha-3")
            distributions[f"{population}:{sex}"] = {"family": "categorical", "parameters": {"shares": shares_of(counts), "thousand_persons": counts, "country_names": names, "total_thousand_persons": total, "year": year}}
    cited = {("working_age_population", "SEX_T", "CCT_CTZ_TOTAL"), ("working_age_population", "SEX_T", "CCT_CTZ_BGD"), ("working_age_population", "SEX_F", "CCT_CTZ_PHL"), ("employed", "SEX_T", "CCT_CTZ_TOTAL"), ("employed", "SEX_M", "CCT_CTZ_IND")}
    items = [table.cite(r, f"ref_area=OMN, sex={r['sex']}, classif1={r['classif1']}", "count") for population, table in sources.items() for r in table.rows if (population, r["sex"], r["classif1"]) in cited]
    items += [labels.cite("CCT_CTZ_BGD"), labels.cite("CCT_CTZ_X")]
    picks = [("working_age_population:total", "BGD"), ("working_age_population:women", "PHL"), ("employed:men", "IND"), ("employed:total", OTHER)]
    return conditional(
        f"om-foreign-citizens-by-country-of-citizenship-{year}", f"Oman working-age and employed foreign citizens by country of citizenship, given sex, {year} (ILOSTAT)",
        "demographics", "OM", "country_of_citizenship_iso3", "population_and_sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Thousands of foreign citizens of each listed country divided by the sum over the listed countries and 'Other countries' (OTHER); the sum is checked against the published total.")],
        share_tests(distributions, picks),
        GCC_TAGS + ["foreign-citizens", "country-of-citizenship", "by-sex", "ilostat", "labour-migration"], PEOPLE_USE_CASES + ["remittance-demo", "hr-analytics"],
        f"Foreign citizens in Oman in {year} by country of citizenship, for the working-age population (ILOSTAT indicator POP_MFRC_SEX_CCT_NB) and for "
        "employed persons (EMP_MFRC_SEX_CCT_NB), each for all persons, men and women, from ILOSTAT's international labour migration statistics. ILOSTAT "
        "lists the main countries of citizenship separately and pools the rest as 'Other countries' (OTHER here). This is a citizenship-based count from "
        "national sources, complementing the UN DESA origin estimates for Oman. Conditioning keys are '<population>:<sex>'. " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), "license-review",
    )


# ---------------------------------------------------------------- WHO GHO


@dataclass
class GhoIndicator:
    """A WHO GHO OData response for one indicator, filtered to one year and the GCC economies."""

    code: str
    year: int
    source: Source = field(init=False)
    records: list[dict] = field(init=False)

    def __post_init__(self) -> None:
        areas = ",".join(f"%27{a}%27" for a in GCC)
        self.source = Source(f"{GHO_API}/{self.code}?$filter=TimeDim%20eq%20{self.year}%20and%20SpatialDim%20in%20({areas})")
        self.records = json.loads(self.source.raw)["value"]

    def find(self, area: str, sex: str, age: str | None = None) -> dict:
        matches = [r for r in self.records if r["SpatialDim"] == area and r["Dim1"] == sex and (age is None or r["Dim2"] == age)]
        if len(matches) != 1:
            raise ValueError(f"{self.code} {area} {sex} {age}: {len(matches)} records")
        return matches[0]

    def cite(self, record: dict, name: str) -> dict:
        raw = self.source.raw.decode("utf-8")
        match = re.search(rf'"Id":{record["Id"]},.*?"Value":"[^"]*","NumericValue":[0-9.]+', raw)
        if match is None:
            raise ValueError(f"record {record['Id']} not in {self.source.url}")
        snippet = re.search(r'"Value":"[^"]*","NumericValue":[0-9.]+$', match.group(0)).group(0)
        locator = f"value[Id={record['Id']}] (SpatialDim={record['SpatialDim']}, Dim1={record['Dim1']}" + (f", Dim2={record['Dim2']}" if record.get("Dim2") else "") + ").NumericValue"
        return self.source.cite(WHO, f"WHO GHO OData API, {self.code} ({name}), {self.year}, GCC economies", locator, record["NumericValue"], "percent", snippet, UNSTATED)


GHO_SEXES = {"SEX_BTSX": "both_sexes", "SEX_MLE": "men", "SEX_FMLE": "women"}
# Row key, GHO indicator, age group dimension and the indicator's name as it is cited.
GHO_MEASURES = (
    ("obesity_18_plus", "NCD_BMI_30A", "AGEGROUP_YEARS18-PLUS", "prevalence of obesity among adults, BMI 30 or more, age-standardised"),
    ("overweight_18_plus", "NCD_BMI_25A", "AGEGROUP_YEARS18-PLUS", "prevalence of overweight among adults, BMI 25 or more, age-standardised"),
    ("diabetes_18_plus", "NCD_DIABETES_PREVALENCE_AGESTD", "AGEGROUP_YEARS18-PLUS", "prevalence of diabetes, age-standardised"),
    ("diabetes_30_plus", "NCD_DIABETES_PREVALENCE_AGESTD", "AGEGROUP_YEARS30-PLUS", "prevalence of diabetes, age-standardised"),
)


def who_health_entry(indicators: dict[str, GhoIndicator], country: Country) -> dict:
    rows: dict[str, dict] = {}
    for key, code, age, _ in GHO_MEASURES:
        gho = indicators[code]
        record: dict[str, Any] = {"indicator": code, "year": gho.year}
        for sex, label in GHO_SEXES.items():
            found = gho.find(country.iso3, sex, age)
            record[f"{label}_percent"] = found["NumericValue"]
            record[f"{label}_low"] = found["Low"]
            record[f"{label}_high"] = found["High"]
        rows[key] = record
    names = {key: name for key, _, _, name in GHO_MEASURES}
    cited = (("obesity_18_plus", "SEX_FMLE"), ("obesity_18_plus", "SEX_MLE"), ("overweight_18_plus", "SEX_BTSX"), ("diabetes_18_plus", "SEX_MLE"), ("diabetes_30_plus", "SEX_FMLE"))
    ages = {key: age for key, _, age, _ in GHO_MEASURES}
    items = [indicators[rows[key]["indicator"]].cite(indicators[rows[key]["indicator"]].find(country.iso3, sex, ages[key]), names[key]) for key, sex in cited]
    years = sorted({r["year"] for r in rows.values()})
    return lookup_entry(
        f"{country.prefix}-adult-obesity-overweight-and-diabetes-by-sex-{years[0]}-{years[-1]}",
        f"{country.name}: age-standardised adult obesity, overweight and diabetes prevalence by sex, {years[0]} and {years[-1]} (WHO GHO)",
        "healthcare", country.iso2, rows, {"urls": {code: g.source.url for code, g in indicators.items()}},
        lookup_vectors(rows, "women_percent", ("obesity_18_plus", "diabetes_18_plus")) + [{"input": {"key": "overweight_18_plus", "column": "both_sexes_percent"}, "expected": rows["overweight_18_plus"]["both_sexes_percent"], "origin": "source"}],
        items,
        [
            {"statistic": "value[obesity_18_plus,women_percent]", "expected": rows["obesity_18_plus"]["women_percent"], "tolerance": 1e-9},
            {"statistic": "value[diabetes_18_plus,men_percent]", "expected": rows["diabetes_18_plus"]["men_percent"], "tolerance": 1e-9},
            {"statistic": "max[both_sexes_percent]", "expected": max(r["both_sexes_percent"] for r in rows.values()), "tolerance": 1e-9},
        ],
        ["gcc", "obesity", "overweight", "bmi", "diabetes", "ncd", "by-sex", "who", "health"], ["health-demo", "insurance", "synthetic-customers", "clinical-records"],
        f"Age-standardised prevalence (percent) among adults in {country.name}, for both sexes, men and women, with the lower and upper bounds of the WHO "
        "uncertainty interval (_low and _high): obesity (BMI 30 or more, GHO indicator NCD_BMI_30A) and overweight (BMI 25 or more, NCD_BMI_25A) for ages "
        f"18 and over in {rows['obesity_18_plus']['year']}, and diabetes (NCD_DIABETES_PREVALENCE_AGESTD) for ages 18 and over and 30 and over in "
        f"{rows['diabetes_18_plus']['year']}, the latest year that indicator carries. Each GHO query is filtered to one year and the six GCC states. "
        "Rows are keyed by measure and record their indicator and year. The World Bank diabetes table already in the archive gives one both-sexes figure "
        "for ages 20 to 79; this adds the split by sex." + WHO_LICENSE_NOTE,
        (f"{years[0]}-01-01", f"{years[-1]}-12-31"), status="license-review",
    )



# ---------------------------------------------------------------- main


def main() -> int:
    locations = Locations(Source(UN_LOCATIONS_URL))
    countries = [locations.country(iso3) for iso3 in GCC]
    by_iso3 = {c.iso3: c for c in countries}

    origin = OriginTable(UnWorkbook(Source(IMS_ORIGIN_URL), ["Table 1"]), locations)
    destination = DestinationTables(UnWorkbook(Source(IMS_DESTINATION_URL), DestinationTables.names), countries)
    ages = AgeTable(UnWorkbook(Source(IMS_AGE_URL), ["Table 1"]), countries, locations)

    license_source = Source(WB_LICENSE_URL)
    age_indicators = [f"SP.POP.{band}.{sex}" for sex in ("MA", "FE") for band in AGE_BANDS]
    population = WorldBankQuery(Source(wb_url(age_indicators, "2025", 40)))
    population_meta = Source(f"{WB_API}/indicator/SP.POP.0004.MA?format=json")
    projections = WorldBankQuery(Source(wb_url(["SP.POP.TOTL", "SP.POP.TOTL.MA.IN", "SP.POP.TOTL.FE.IN"], "2025:2050", 40)))
    projections_meta = Source(f"{WB_API}/indicator/SP.POP.TOTL.MA.IN?format=json")
    paid = WorldBankQuery(Source(wb_url([REMITTANCES_PAID], "2010:2024")))
    cost = WorldBankQuery(Source(wb_url([REMITTANCE_COST], "2010:2024")))
    remittance_meta = {code: Source(f"{WB_API}/indicator/{code}?format=json") for code in (REMITTANCES_PAID, REMITTANCE_COST)}

    labels = IloLabels(Source(ILO_LABELS_URL))
    modelled = ModelledEmployment(labels, 2024)
    gho = {"NCD_BMI_30A": GhoIndicator("NCD_BMI_30A", 2024), "NCD_BMI_25A": GhoIndicator("NCD_BMI_25A", 2024), "NCD_DIABETES_PREVALENCE_AGESTD": GhoIndicator("NCD_DIABETES_PREVALENCE_AGESTD", 2022)}

    for country in countries:
        write(ims_origin_entry(origin, country))
        write(ims_stock_entry(destination, country))
        write(ims_age_entry(ages, country))
        write(wb_age_entry(population, population_meta, license_source, country, 2025))
        write(wb_projection_entry(projections, projections_meta, license_source, country, 2025, 2050))
        write(wb_remittance_entry(paid, cost, remittance_meta, license_source, country, 2010, 2024))
        write(employment_by_activity(modelled, country))
        write(who_health_entry(gho, country))

    write(qa_employment_by_activity(labels, 2024))
    write(qa_employment_by_skill(labels, 2024))
    write(qa_employment_by_age(labels, 2024))
    write(unemployment_by_citizenship(by_iso3["SAU"], 2025))
    write(unemployment_by_citizenship(by_iso3["QAT"], 2024))
    write(sa_earnings_by_citizenship(2020))
    write(om_foreign_citizens(labels, locations, 2024))
    return 0


if __name__ == "__main__":
    sys.exit(main())

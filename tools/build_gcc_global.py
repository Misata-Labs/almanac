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

Tables spanning the six GCC states are filed under region SA. Run from the repository root:

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
from build_labour import ILO, ILO_LICENSE_NOTE, UNSTATED, CsvRow, IloTable, Source, csv_rows, lookup_entry, lookup_vectors, numeric, shares_of

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


def ims_origin_entry(table: OriginTable) -> dict:
    distributions: dict[str, dict] = {}
    for iso3 in GCC:
        counts, total = table.counts(iso3, table.both)
        kept = top_with_remainder(counts, total, TOP_ORIGINS)
        names = table.names(iso3)
        distributions[iso3] = categorical(kept, total_migrants=total, origin_names={k: names[k] for k in kept if k != OTHER}, year=table.year)
    items = [table.cite(table.world_row(iso3), table.both, "both sexes") for iso3 in GCC]
    items += [
        table.cite(table.origin_index("SAU", "IND"), table.both, "both sexes"),
        table.cite(table.origin_index("ARE", "IND"), table.both, "both sexes"),
        table.cite(table.origin_index("QAT", "NPL"), table.both, "both sexes"),
        table.cite(table.origin_index("KWT", "EGY"), table.both, "both sexes"),
        table.book.source.cite(UNDESA, IMS_ORIGIN_TITLE, "Migrant notes, type of data", "C", "text", DATA_TYPE_SNIPPET, CC_BY_IGO, role="supporting"),
        table.book.cite_license(IMS_ORIGIN_TITLE),
        table.locations.cite("IND"),
    ]
    picks = [("SAU", "IND"), ("ARE", "IND"), ("QAT", "NPL"), ("KWT", "EGY"), ("BHR", "IND"), ("OMN", "BGD")]
    return conditional(
        "gcc-migrant-stock-by-origin-2024", "International migrant stock by country of origin, given GCC destination, mid-2024: up to 30 largest origins (UN DESA)",
        "demographics", "SA", "country_of_origin_iso3", "destination_iso3", distributions, items,
        [
            shares_assumption("distributions[*].parameters.shares", "Each origin's 2024 migrant stock (both sexes) divided by the destination's total migrant stock (origin 'World'); the 30 largest origins are kept and the rest of the total, including the workbook's 'Others' row, is pooled as OTHER."),
            {"parameter": "categories", "value": "ISO 3166-1 alpha-3", "method": "derived", "rationale": "The workbook identifies origins by M49 code; codes are mapped to ISO alpha-3 with the UN Population Division location list. A code without an ISO mapping would be kept as M49-<code>."},
        ],
        share_tests(distributions, picks),
        GCC_TAGS + ["international-migrant-stock", "country-of-origin", "un-desa", "population"], PEOPLE_USE_CASES + ["remittance-demo", "banking-demo"],
        "Share of each GCC state's international migrants by country of origin at 1 July 2024, from UN DESA International Migrant Stock 2024 "
        "(destination and origin workbook, Table 1). For all six states the type of data is C (Saudi Arabia: C R): the estimates are derived from "
        "data on foreign citizens, so 'origin' is effectively the country of citizenship and the distribution can drive nationality for synthetic "
        "residents. Each destination keeps its 30 largest listed origins (fewer where the workbook lists fewer) and an OTHER remainder; counts (persons), the destination total and the origin "
        "names ride alongside the shares. Destinations and origins are keyed by ISO 3166-1 alpha-3 code." + UNDESA_LICENSE_NOTE,
        ("2024-07-01", "2024-07-01"), "license-review",
    )


def ims_origin_by_sex_entry(table: OriginTable) -> dict:
    distributions: dict[str, dict] = {}
    for iso3 in GCC:
        for sex, column in (("male", table.male), ("female", table.female)):
            counts, total = table.counts(iso3, column)
            kept = top_with_remainder(counts, total, TOP_ORIGINS)
            distributions[f"{iso3}-{sex}"] = categorical(kept, total_migrants=total, year=table.year)
    items = [
        table.cite(table.world_row("SAU"), table.male, "males"),
        table.cite(table.world_row("SAU"), table.female, "females"),
        table.cite(table.world_row("ARE"), table.female, "females"),
        table.cite(table.origin_index("SAU", "PHL"), table.female, "females"),
        table.cite(table.origin_index("KWT", "IND"), table.male, "males"),
        table.book.cite_license(IMS_ORIGIN_TITLE),
    ]
    picks = [("SAU-female", "PHL"), ("SAU-male", "IND"), ("KWT-male", "IND"), ("ARE-female", "IND"), ("QAT-male", "IND")]
    return conditional(
        "gcc-migrant-stock-by-origin-and-sex-2024", "International migrant stock by country of origin, given GCC destination and sex, mid-2024: up to 30 largest origins (UN DESA)",
        "demographics", "SA", "country_of_origin_iso3", "destination_iso3_and_sex", distributions, items,
        [
            shares_assumption("distributions[*].parameters.shares", "Each origin's 2024 male or female migrant stock divided by the destination's male or female total (origin 'World'); the 30 largest origins for that sex are kept and the remainder, including 'Others', is pooled as OTHER."),
            {"parameter": "categories", "value": "ISO 3166-1 alpha-3", "method": "derived", "rationale": "M49 origin codes are mapped to ISO alpha-3 with the UN Population Division location list."},
        ],
        share_tests(distributions, picks),
        GCC_TAGS + ["international-migrant-stock", "country-of-origin", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["remittance-demo"],
        "Country-of-origin mix of male and female migrants in each GCC state at 1 July 2024, from UN DESA International Migrant Stock 2024 "
        "(destination and origin workbook, Table 1, male and female columns). Conditioning keys are '<destination ISO3>-male' and "
        "'<destination ISO3>-female'. The origin mix of female migrants differs from that of male migrants, so drawing nationality after sex "
        "reproduces both mixes, which the both-sexes table cannot. The 30 largest listed origins per sex are kept with an OTHER "
        "remainder; counts and the sex-specific total ride alongside. Estimates are derived from data on foreign citizens (type of data C)." + UNDESA_LICENSE_NOTE,
        ("2024-07-01", "2024-07-01"), "license-review",
    )


def ims_destination_entry(book: UnWorkbook, locations: Locations) -> dict:
    tables = {name: book.rows[name] for name in ("Table 1", "Table 2", "Table 3", "Table 4")}
    headers = {name: next(i for i, r in enumerate(rows) if 1990 in r) for name, rows in tables.items()}
    codes = {locations.m49(iso3): iso3 for iso3 in GCC}
    located: dict[str, dict[str, int]] = {}
    first = tables["Table 1"]
    for index, row in enumerate(first[headers["Table 1"] + 1 :], start=headers["Table 1"] + 1):
        if isinstance(row[4], int) and row[4] in codes:
            located[codes[row[4]]] = {"Table 1": index}
    # Table 2 carries no location code, so every table is matched on the shared Index column and the name is checked.
    for iso3, at in located.items():
        key, name = first[at["Table 1"]][0], first[at["Table 1"]][1]
        for other in ("Table 2", "Table 3", "Table 4"):
            rows = tables[other]
            at[other] = next(i for i, r in enumerate(rows) if i > headers[other] and r[0] == key)
            if rows[at[other]][1] != name:
                raise ValueError(f"{other} row {at[other]} is {rows[at[other]][1]!r}, expected {name!r}")
    years = [y for y in tables["Table 3"][headers["Table 3"]] if isinstance(y, int)][:8]
    rows: dict[str, dict] = {}
    for iso3 in GCC:
        at = located[iso3]
        t1, t2, t3, t4 = (tables[n][at[n]] for n in ("Table 1", "Table 2", "Table 3", "Table 4"))
        c1 = year_columns(tables["Table 1"][headers["Table 1"]], 2024)
        c2 = year_columns(tables["Table 2"][headers["Table 2"]], 2024)
        c3 = year_columns(tables["Table 3"][headers["Table 3"]], 2024)
        c4 = year_columns(tables["Table 4"][headers["Table 4"]], 2024)
        record: dict[str, Any] = {
            "name": t1[1],
            "m49": t1[4],
            "type_of_data": t1[3],
            "migrant_stock_2024": t1[c1[0]],
            "migrant_stock_male_2024": t1[c1[1]],
            "migrant_stock_female_2024": t1[c1[2]],
            "total_population_thousands_2024": t2[c2[0]],
            "total_population_male_thousands_2024": t2[c2[1]],
            "total_population_female_thousands_2024": t2[c2[2]],
            "migrant_share_percent_2024": t3[c3[0]],
            "migrant_share_male_percent_2024": t3[c3[1]],
            "migrant_share_female_percent_2024": t3[c3[2]],
            "female_share_of_migrants_percent_2024": t4[c4[0]],
        }
        first3 = year_columns(tables["Table 3"][headers["Table 3"]], years[0])[0]
        for offset, year in enumerate(years):
            record[f"migrant_share_percent_{year}"] = t3[first3 + offset]
        rows[iso3] = record
    sau, qat, are = located["SAU"], located["QAT"], located["ARE"]
    items = [
        book.cite(IMS_DESTINATION_TITLE, "Table 1", sau["Table 1"], year_columns(tables["Table 1"][headers["Table 1"]], 2024)[0], "Saudi Arabia, migrant stock, both sexes, 2024", "count"),
        book.cite(IMS_DESTINATION_TITLE, "Table 1", qat["Table 1"], year_columns(tables["Table 1"][headers["Table 1"]], 2024)[2], "Qatar, migrant stock, females, 2024", "count"),
        book.cite(IMS_DESTINATION_TITLE, "Table 3", are["Table 3"], year_columns(tables["Table 3"][headers["Table 3"]], 2024)[0], "United Arab Emirates, migrants as percentage of population, 2024", "percent"),
        book.cite(IMS_DESTINATION_TITLE, "Table 4", qat["Table 4"], year_columns(tables["Table 4"][headers["Table 4"]], 2024)[0], "Qatar, female migrants as percentage of migrant stock, 2024", "percent"),
        book.cite_license(IMS_DESTINATION_TITLE),
        locations.cite("SAU"),
    ]
    lead = "migrant_share_percent_2024"
    return lookup_entry(
        "gcc-migrant-stock-and-share-of-population-1990-2024", "GCC international migrant stock by sex, total population and migrant share of population, 1990 to 2024 (UN DESA)",
        "demographics", "SA", rows, {"source_tables": list(tables), "year": 2024, "history_years": years},
        lookup_vectors(rows, lead, ("SAU", "QAT")) + [{"input": {"key": "ARE", "column": "migrant_stock_2024"}, "expected": rows["ARE"]["migrant_stock_2024"], "origin": "source"}],
        items,
        [
            {"statistic": f"value[QAT,{lead}]", "expected": rows["QAT"][lead], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values()), "tolerance": 1e-9},
            {"statistic": f"min[{lead}]", "expected": min(r[lead] for r in rows.values()), "tolerance": 1e-9},
            {"statistic": "value[SAU,migrant_stock_female_2024]", "expected": rows["SAU"]["migrant_stock_female_2024"], "tolerance": 0},
        ],
        GCC_TAGS + ["international-migrant-stock", "migrant-share", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["market-sizing"],
        "For each GCC state, the international migrant stock at 1 July 2024 for both sexes, males and females (Table 1), the total population in "
        "thousands (Table 2), migrants as a percentage of the population by sex (Table 3) and female migrants as a percentage of all migrants (Table 4), "
        f"plus the both-sexes migrant share for {', '.join(str(y) for y in years)}, from the UN DESA International Migrant Stock 2024 destination workbook. "
        "Values are copied unchanged. Use migrant_share_percent_2024 to split a synthetic population into nationals and foreign residents, and the "
        "male and female shares to reproduce the strong male skew among migrants. type_of_data is the workbook's code (C: derived from data on foreign "
        "citizens; R: refugees added). Rows are keyed by ISO 3166-1 alpha-3 code; m49 is the UN location code." + UNDESA_LICENSE_NOTE,
        ("2024-07-01", None), status="license-review",
    )


def ims_age_entry(book: UnWorkbook, locations: Locations) -> dict:
    sheet = "Table 1"
    rows = book.rows[sheet]
    header = header_row(rows, "Index")
    labels = rows[header]
    totals = [i for i, cell in enumerate(labels) if cell == "Total"]
    blocks = {"total": (6, totals[0]), "male": (totals[0] + 1, totals[1]), "female": (totals[1] + 1, totals[2])}
    codes = {locations.m49(iso3): iso3 for iso3 in GCC}
    found: dict[str, int] = {}
    for index, row in enumerate(rows[header + 1 :], start=header + 1):
        if row[1] == 2020 and row[4] in codes:
            found[codes[row[4]]] = index
    distributions: dict[str, dict] = {}
    for iso3 in GCC:
        row = rows[found[iso3]]
        for sex, (start, end) in blocks.items():
            counts = {str(labels[i]).strip(): int(row[i]) for i in range(start, end)}
            published = int(row[end])
            if abs(sum(counts.values()) - published) > 0.01 * published:
                raise ValueError(f"{iso3} {sex}: age groups sum to {sum(counts.values())}, total is {published}")
            distributions[f"{iso3}-{sex}"] = categorical(counts, total_migrants=published, year=2020)
    qat, sau = found["QAT"], found["SAU"]
    items = [
        book.cite(IMS_AGE_TITLE, sheet, qat, blocks["male"][0] + 6, "Qatar, 2020, males aged 30-34", "count"),
        book.cite(IMS_AGE_TITLE, sheet, qat, blocks["male"][1], "Qatar, 2020, males, total", "count"),
        book.cite(IMS_AGE_TITLE, sheet, sau, blocks["female"][0] + 5, "Saudi Arabia, 2020, females aged 25-29", "count"),
        book.cite(IMS_AGE_TITLE, sheet, sau, blocks["total"][1], "Saudi Arabia, 2020, both sexes, total", "count"),
        book.cite_license(IMS_AGE_TITLE),
        locations.cite("QAT"),
    ]
    picks = [("QAT-male", "30-34"), ("SAU-female", "25-29"), ("ARE-total", "35-39"), ("OMN-male", "30-34")]
    return conditional(
        "gcc-migrant-stock-by-age-and-sex-2020", "International migrant stock by five-year age group, given GCC destination and sex, mid-2020 (UN DESA)",
        "demographics", "SA", "age_group", "destination_iso3_and_sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Migrants in each five-year age group (0-4 to 75+) divided by the sum over the groups for that destination and sex; the published total is kept beside the counts and differs from the sum only by rounding.")],
        share_tests(distributions, picks),
        GCC_TAGS + ["international-migrant-stock", "by-age", "by-sex", "un-desa", "population"], PEOPLE_USE_CASES + ["hr-analytics"],
        "Age distribution of international migrants in each GCC state at 1 July 2020, for both sexes ('<ISO3>-total'), males and females, in sixteen "
        "five-year groups from 0-4 to 75+, from UN DESA International Migrant Stock 2020 (age, sex and destination workbook, Table 1). The 2024 "
        "revision's downloads carry no age breakdown, so 2020 is the latest age structure for migrants. Combined with the 2024 migrant share and the "
        "population pyramid it lets a generator give foreign residents the concentrated working-age profile the data show." + UNDESA_LICENSE_NOTE,
        ("2020-07-01", "2020-07-01"), "license-review",
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


def wb_age_entry(query: WorldBankQuery, metadata: Source, license_source: Source, year: int) -> dict:
    distributions: dict[str, dict] = {}
    for iso3 in GCC:
        for sex, suffix in (("male", "MA"), ("female", "FE")):
            counts = {band_label(b): query.value(f"SP.POP.{b}.{suffix}", iso3, year) for b in AGE_BANDS}
            if any(v is None for v in counts.values()):
                raise ValueError(f"{iso3} {sex} {year}: missing age groups")
            distributions[f"{iso3}-{sex}"] = categorical({k: int(v) for k, v in counts.items()}, year=year)
    title = f"World Bank API, population by five-year age group and sex (SP.POP.<age>.MA/FE), source 40, {year}, GCC economies"
    items = [
        query.cite(title, "SP.POP.2529.MA", "QAT", year, "count"),
        query.cite(title, "SP.POP.2529.FE", "QAT", year, "count"),
        query.cite(title, "SP.POP.3034.MA", "ARE", year, "count"),
        query.cite(title, "SP.POP.0004.FE", "SAU", year, "count"),
        wb_metadata(metadata, "SP.POP.0004.MA", "age\\/sex distributions of the United Nations Population Division's World Population Prospects"),
        wb_license(license_source),
    ]
    picks = [("QAT-male", "25-29"), ("QAT-female", "25-29"), ("ARE-male", "30-34"), ("SAU-female", "0-4"), ("KWT-male", "35-39")]
    return conditional(
        f"gcc-population-by-age-and-sex-{year}", f"Population by five-year age group, given GCC economy and sex, {year} (World Bank, based on UN World Population Prospects)",
        "demographics", "SA", "age_group", "economy_iso3_and_sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Persons in each five-year age group divided by the sum of the seventeen groups (0-4 to 80+) for that economy and sex.")],
        share_tests(distributions, picks),
        ["gcc", "population", "age-pyramid", "by-age", "by-sex", "world-bank"], PEOPLE_USE_CASES + ["insurance", "pensions"],
        f"Mid-year {year} population of each GCC state in seventeen five-year age groups (0-4 to 80+) for males and females, from the World Bank "
        "Population estimates and projections database (API source 40, indicators SP.POP.0004.MA to SP.POP.80UP.FE). The World Bank derives these "
        "from its total population and the age and sex distributions of the UN World Population Prospects. Counts are kept beside the shares, so "
        "the male-heavy working-age bulge that migrant labour creates (compare the male and female 25-44 groups) can be sampled directly. "
        f"Conditioning keys are '<ISO3>-male' and '<ISO3>-female'. Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{year}-01-01", f"{year}-12-31"), "verified",
    )


def wb_projection_entry(query: WorldBankQuery, metadata: Source, license_source: Source, first: int, last: int) -> dict:
    rows: dict[str, dict] = {}
    for iso3 in GCC:
        record: dict[str, Any] = {}
        for year in range(first, last + 1):
            record[f"total_{year}"] = int(query.value("SP.POP.TOTL", iso3, year))
        for year in range(first, last + 1, 5):
            record[f"male_{year}"] = int(query.value("SP.POP.TOTL.MA.IN", iso3, year))
            record[f"female_{year}"] = int(query.value("SP.POP.TOTL.FE.IN", iso3, year))
        rows[iso3] = record
    title = f"World Bank API, population total, male and female, source 40 (Population estimates and projections), {first}-{last}, GCC economies"
    items = [
        query.cite(title, "SP.POP.TOTL", "SAU", last, "count"),
        query.cite(title, "SP.POP.TOTL", "QAT", first, "count"),
        query.cite(title, "SP.POP.TOTL.MA.IN", "ARE", last, "count"),
        query.cite(title, "SP.POP.TOTL.FE.IN", "OMN", first, "count"),
        wb_metadata(metadata, "SP.POP.TOTL.MA.IN", "World Population Prospects, United Nations (UN), publisher: UN Population Division"),
        wb_license(license_source),
    ]
    lead = f"total_{last}"
    return lookup_entry(
        f"gcc-population-projections-{first}-{last}", f"GCC population, annual totals {first} to {last} and male and female every five years (World Bank projections)",
        "demographics", "SA", rows, {"source": "World Bank API source 40", "indicators": ["SP.POP.TOTL", "SP.POP.TOTL.MA.IN", "SP.POP.TOTL.FE.IN"], "url": query.source.url},
        lookup_vectors(rows, lead, ("SAU", "QAT")) + [{"input": {"key": "ARE", "column": f"male_{last}"}, "expected": rows["ARE"][f"male_{last}"], "origin": "source"}],
        items,
        [
            {"statistic": f"value[SAU,{lead}]", "expected": rows["SAU"][lead], "tolerance": 0},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values()), "tolerance": 0},
            {"statistic": f"value[OMN,female_{first}]", "expected": rows["OMN"][f"female_{first}"], "tolerance": 0},
        ],
        ["gcc", "population", "projections", "by-sex", "world-bank"], PEOPLE_USE_CASES + ["market-sizing", "demand-forecasting"],
        f"Total population of each GCC state for every year from {first} to {last}, and male and female population every five years, from the World Bank "
        "Population estimates and projections database (API source 40), which projects forward from the UN World Population Prospects. Values after the "
        "latest estimate year are projections, not observations. Rows are keyed by ISO 3166-1 alpha-3 code; columns are named <series>_<year>. "
        f"Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{first}-01-01", f"{last}-12-31"),
    )


def wb_remittances_paid_entry(query: WorldBankQuery, metadata: Source, license_source: Source, first: int, last: int) -> dict:
    indicator = "BM.TRF.PWKR.CD.DT"
    rows = {iso3: {f"usd_{year}": query.value(indicator, iso3, year) for year in range(first, last + 1)} for iso3 in GCC}
    title = f"World Bank API, {indicator} (Personal remittances, paid, current US$), {first}-{last}, GCC economies"
    items = [
        query.cite(title, indicator, "SAU", last, "currency:USD"),
        query.cite(title, indicator, "ARE", last, "currency:USD"),
        query.cite(title, indicator, "KWT", first, "currency:USD"),
        wb_metadata(metadata, indicator, "IMF balance of payments data, International Monetary Fund (IMF)"),
        wb_license(license_source),
    ]
    lead = f"usd_{last}"
    missing = sorted(f"{iso3} {k[4:]}" for iso3, r in rows.items() for k, v in r.items() if v is None)
    return lookup_entry(
        f"gcc-personal-remittances-paid-{first}-{last}", f"Personal remittances paid by GCC economies, current US dollars, annual {first} to {last} (World Bank)",
        "economy", "SA", rows, {"indicator": indicator, "url": query.source.url},
        lookup_vectors(rows, lead, ("SAU", "ARE", "KWT")), items,
        [
            {"statistic": f"value[SAU,{lead}]", "expected": rows["SAU"][lead], "tolerance": 1e-3},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values() if r[lead] is not None), "tolerance": 1e-3},
        ],
        ["gcc", "remittances", "migration", "balance-of-payments", "world-bank"], REMITTANCE_USE_CASES + ["market-sizing"],
        f"Personal remittances paid (indicator {indicator}: personal transfers plus compensation of employees, from IMF balance of payments data and World "
        f"Bank staff estimates) by each GCC state for {first} to {last}, in current US dollars. Personal transfers are current transfers from resident to non-resident households. The series "
        "sets the annual scale for a synthetic outbound remittance ledger; the destination mix can be taken from the UN DESA migrant-stock-by-origin entry. "
        + (f"Years without a published value are null: {', '.join(missing)}. " if missing else "")
        + f"Rows are keyed by ISO 3166-1 alpha-3 code. Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{first}-01-01", f"{last}-12-31"),
    )


def wb_remittance_cost_entry(query: WorldBankQuery, metadata: Source, license_source: Source, first: int, last: int) -> dict:
    indicator = "SI.RMT.COST.OB.ZS"
    rows = {iso3: {f"percent_{year}": query.value(indicator, iso3, year) for year in range(first, last + 1)} for iso3 in GCC}
    title = f"World Bank API, {indicator} (Average transaction cost of sending remittances from a specific country, %), {first}-{last}, GCC economies"
    items = [
        query.cite(title, indicator, "SAU", last, "percent"),
        query.cite(title, indicator, "QAT", last, "percent"),
        query.cite(title, indicator, "KWT", first, "percent"),
        wb_metadata(metadata, indicator, "Remittance Prices Worldwide, World Bank (WB)"),
        wb_license(license_source),
    ]
    lead = f"percent_{last}"
    missing = sorted(f"{iso3} {k[8:]}" for iso3, r in rows.items() for k, v in r.items() if v is None)
    return lookup_entry(
        f"gcc-remittance-sending-cost-{first}-{last}", f"Average cost of sending USD 200 in remittances from each GCC economy, percent, annual {first} to {last} (World Bank)",
        "payments", "SA", rows, {"indicator": indicator, "url": query.source.url},
        lookup_vectors(rows, lead, ("SAU", "QAT", "KWT")), items,
        [
            {"statistic": f"value[QAT,{lead}]", "expected": rows["QAT"][lead], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values() if r[lead] is not None), "tolerance": 1e-9},
            {"statistic": f"min[{lead}]", "expected": min(r[lead] for r in rows.values() if r[lead] is not None), "tolerance": 1e-9},
        ],
        ["gcc", "remittances", "fees", "remittance-prices", "world-bank"], REMITTANCE_USE_CASES + ["pricing"],
        f"Average total transaction cost, as a percentage of the amount sent, of sending USD 200 from each GCC state (indicator {indicator}), averaged over the "
        f"remittance service providers in the World Bank's Remittance Prices Worldwide database, for {first} to {last}. Use it to price fees on synthetic "
        "outbound transfers. " + (f"Years without a published value are null: {', '.join(missing)}. " if missing else "")
        + f"Rows are keyed by ISO 3166-1 alpha-3 code. Data last updated {query.last_updated}. The World Bank licenses its data under CC BY 4.0.",
        (f"{first}-01-01", f"{last}-12-31"),
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
        notes + f" Conditioning keys are '<citizenship>:<sex>' with citizenship all, citizens or foreign_citizens and sex total, men or women; the "
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


def unemployment_by_citizenship(sau_year: int, qat_year: int) -> dict:
    name = "Unemployment rate by sex, age and citizenship (%)"
    tables = {"SAU": ilo_table("UNE_DEAP_SEX_AGE_CCT_RT_A", name, "SAU", sau_year), "QAT": ilo_table("UNE_DEAP_SEX_AGE_CCT_RT_A", name, "QAT", qat_year)}
    ages = {"AGE_YTHADULT_YGE15": "age_15_plus", "AGE_YTHADULT_Y15-24": "age_15_24", "AGE_YTHADULT_YGE25": "age_25_plus", "AGE_YTHADULT_Y15-64": "age_15_64"}
    rows: dict[str, dict] = {}
    cited: list[tuple[IloTable, CsvRow]] = []
    for area, table in tables.items():
        for row in table.rows:
            if row["classif1"] not in ages or row["classif2"] not in CITIZENSHIP:
                continue
            key = f"{area}:{CITIZENSHIP[row['classif2']]}:{SEXES[row['sex']]}"
            rows.setdefault(key, {"year": int(row["time"])})[ages[row["classif1"]]] = numeric(row["obs_value"])
            if (row["classif1"], row["classif2"], row["sex"]) in {("AGE_YTHADULT_YGE15", "CCT_CIT_CITIZEN", "SEX_F"), ("AGE_YTHADULT_Y15-24", "CCT_CIT_NONCIT", "SEX_T")}:
                cited.append((table, row))
    rows = {key: {"year": record["year"], **{column: record.get(column) for column in ages.values()}} for key, record in sorted(rows.items())}
    items = [t.cite(r, f"ref_area={r['ref_area']}, sex={r['sex']}, classif1={r['classif1']}, classif2={r['classif2']}", "percent") for t, r in cited]
    lead = "age_15_plus"
    return lookup_entry(
        "gcc-unemployment-rate-by-citizenship-sex-and-age", f"Unemployment rate by citizenship, sex and age: Saudi Arabia {sau_year} and Qatar {qat_year} (ILOSTAT)",
        "employment", "SA", rows, {"indicator": "UNE_DEAP_SEX_AGE_CCT_RT_A", "urls": [t.source.url for t in tables.values()], "age_columns": ages},
        lookup_vectors(rows, lead, ("SAU:citizens:women", "SAU:foreign_citizens:men", "QAT:citizens:total")), items,
        [
            {"statistic": f"value[SAU:citizens:women,{lead}]", "expected": rows["SAU:citizens:women"][lead], "tolerance": 1e-9},
            {"statistic": "value[SAU:foreign_citizens:total,age_15_24]", "expected": rows["SAU:foreign_citizens:total"]["age_15_24"], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values() if r.get(lead) is not None), "tolerance": 1e-9},
        ],
        GCC_TAGS + ["unemployment", "by-citizenship", "by-sex", "by-age", "ilostat", "labour-force-survey"], LABOUR_USE_CASES + ["credit-risk", "synthetic-customers"],
        f"Unemployment rate (percent of the labour force) for citizens, foreign citizens and all persons, by sex, for ages 15+, 15-24, 25+ and 15-64, from "
        f"ILOSTAT indicator UNE_DEAP_SEX_AGE_CCT_RT (labour force surveys): Saudi Arabia {sau_year} and Qatar {qat_year}, the GCC states ILOSTAT publishes "
        "this series for. Each query is closed to one year. Rows are keyed '<ISO3>:<citizenship>:<sex>'; a column is null where ILOSTAT "
        "publishes no value. " + ILO_LICENSE_NOTE,
        (f"{min(sau_year, qat_year)}-01-01", f"{max(sau_year, qat_year)}-12-31"), status="license-review",
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


def gcc_employment_by_activity(labels: IloLabels, year: int) -> dict:
    table = ilo_table("EMP_2EMP_SEX_ECO_NB_A", "Employment by sex and economic activity, ILO modelled estimates (thousands)", GCC_QUERY, year)
    distributions: dict[str, dict] = {}
    for area in GCC:
        for code, sex in SEXES.items():
            selected = table.select(ref_area=area, sex=code, time=str(year))
            counts = {r["classif1"]: float(r["obs_value"]) for r in selected if r["classif1"].startswith("ECO_ISIC4_") and r["classif1"] != "ECO_ISIC4_TOTAL"}
            total = next(float(r["obs_value"]) for r in selected if r["classif1"] == "ECO_ISIC4_TOTAL")
            if abs(sum(counts.values()) - total) > 0.01 * total:
                raise ValueError(f"{area} {sex}: sections sum to {sum(counts.values())}, total is {total}")
            distributions[f"{area}:{sex}"] = {"family": "categorical", "parameters": {"shares": shares_of(counts), "thousand_persons": counts, "labels": {c: labels.label(c) for c in counts}, "year": year}}
    cited = [r for r in table.rows if (r["ref_area"], r["sex"], r["classif1"]) in {("SAU", "SEX_M", "ECO_ISIC4_F"), ("ARE", "SEX_F", "ECO_ISIC4_RSTU"), ("QAT", "SEX_T", "ECO_ISIC4_TOTAL")}]
    items = [table.cite(r, f"ref_area={r['ref_area']}, sex={r['sex']}, classif1={r['classif1']}", "count") for r in cited]
    items += [labels.cite("ECO_ISIC4_RSTU"), labels.cite("ECO_ISIC4_LMN")]
    picks = [("SAU:men", "ECO_ISIC4_F"), ("ARE:women", "ECO_ISIC4_RSTU"), ("QAT:total", "ECO_ISIC4_F"), ("KWT:women", "ECO_ISIC4_O"), ("OMN:total", "ECO_ISIC4_G")]
    return conditional(
        f"gcc-employment-by-economic-activity-and-sex-{year}", f"Employment by ISIC Rev.4 section group, given GCC economy and sex, {year} (ILO modelled estimates)",
        "employment", "SA", "isic_rev4_section_group", "economy_iso3_and_sex", distributions, items,
        [shares_assumption("distributions[*].parameters.shares", "Thousands employed in each ISIC Rev.4 section group divided by the sum over the groups for that economy and sex, kept only where the sum is within one percent of the published ECO_ISIC4_TOTAL.")],
        share_tests(distributions, picks),
        ["gcc", "employment", "economic-activity", "isic-rev4", "by-sex", "ilostat", "modelled-estimates"], LABOUR_USE_CASES + ["company-generation", "market-sizing"],
        f"Employment in {year} in fourteen ISIC Rev.4 section groups (A; B; C; D and E; F; G; H and J; I; K; L, M and N; O; P; Q; R, S, T and U) for each GCC "
        "state, for all persons, men and women, from ILOSTAT indicator EMP_2EMP_SEX_ECO_NB (ILO modelled estimates). The modelled "
        "series covers all six states for the same year, which the survey series do not. Codes keep the ILOSTAT form (ECO_ISIC4_<sections>); the "
        "parameters carry the English labels and the thousands employed. Conditioning keys are '<ISO3>:<sex>' with sex total, men or women. The query "
        "is closed to one year so that projections for later years stay out. " + ILO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), "license-review",
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


def who_weight_entry(year: int) -> dict:
    indicators = {"obesity": (GhoIndicator("NCD_BMI_30A", year), "prevalence of obesity among adults, BMI 30 or more, age-standardised"), "overweight": (GhoIndicator("NCD_BMI_25A", year), "prevalence of overweight among adults, BMI 25 or more, age-standardised")}
    rows: dict[str, dict] = {}
    for area in GCC:
        record: dict[str, Any] = {}
        for measure, (gho, _) in indicators.items():
            for sex, label in GHO_SEXES.items():
                found = gho.find(area, sex, "AGEGROUP_YEARS18-PLUS")
                record[f"{measure}_{label}_percent"] = found["NumericValue"]
                record[f"{measure}_{label}_low"] = found["Low"]
                record[f"{measure}_{label}_high"] = found["High"]
        rows[area] = record
    obesity, overweight = indicators["obesity"][0], indicators["overweight"][0]
    items = [
        obesity.cite(obesity.find("KWT", "SEX_FMLE", "AGEGROUP_YEARS18-PLUS"), indicators["obesity"][1]),
        obesity.cite(obesity.find("SAU", "SEX_MLE", "AGEGROUP_YEARS18-PLUS"), indicators["obesity"][1]),
        overweight.cite(overweight.find("QAT", "SEX_BTSX", "AGEGROUP_YEARS18-PLUS"), indicators["overweight"][1]),
    ]
    lead = "obesity_women_percent"
    return lookup_entry(
        f"gcc-adult-obesity-and-overweight-by-sex-{year}", f"Age-standardised prevalence of obesity and overweight among adults 18+ by sex, GCC economies, {year} (WHO GHO)",
        "healthcare", "SA", rows, {"indicators": ["NCD_BMI_30A", "NCD_BMI_25A"], "urls": [g.source.url for g, _ in indicators.values()], "year": year},
        lookup_vectors(rows, lead, ("KWT", "SAU")), items,
        [
            {"statistic": f"value[KWT,{lead}]", "expected": rows["KWT"][lead], "tolerance": 1e-9},
            {"statistic": "value[SAU,obesity_men_percent]", "expected": rows["SAU"]["obesity_men_percent"], "tolerance": 1e-9},
            {"statistic": "max[overweight_both_sexes_percent]", "expected": max(r["overweight_both_sexes_percent"] for r in rows.values()), "tolerance": 1e-9},
        ],
        ["gcc", "obesity", "overweight", "bmi", "by-sex", "who", "health"], ["health-demo", "insurance", "synthetic-customers", "clinical-records"],
        f"Age-standardised prevalence (percent) of obesity (BMI 30 or more, GHO indicator NCD_BMI_30A) and overweight (BMI 25 or more, NCD_BMI_25A) among "
        f"adults aged 18 and over in each GCC state in {year}, for both sexes, men and women, with the lower and upper bounds of the WHO uncertainty interval "
        "(_low and _high), from the WHO Global Health Observatory; each query is filtered to one year. "
        "Rows are keyed by ISO 3166-1 alpha-3 code." + WHO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), status="license-review",
    )


def who_diabetes_entry(year: int) -> dict:
    gho = GhoIndicator("NCD_DIABETES_PREVALENCE_AGESTD", year)
    ages = {"AGEGROUP_YEARS18-PLUS": "18_plus", "AGEGROUP_YEARS30-PLUS": "30_plus"}
    rows: dict[str, dict] = {}
    for area in GCC:
        record: dict[str, Any] = {}
        for age, age_label in ages.items():
            for sex, label in GHO_SEXES.items():
                found = gho.find(area, sex, age)
                record[f"diabetes_{age_label}_{label}_percent"] = found["NumericValue"]
                record[f"diabetes_{age_label}_{label}_low"] = found["Low"]
                record[f"diabetes_{age_label}_{label}_high"] = found["High"]
        rows[area] = record
    name = "prevalence of diabetes, age-standardised"
    items = [gho.cite(gho.find("KWT", "SEX_MLE", "AGEGROUP_YEARS18-PLUS"), name), gho.cite(gho.find("BHR", "SEX_FMLE", "AGEGROUP_YEARS30-PLUS"), name)]
    lead = "diabetes_18_plus_both_sexes_percent"
    return lookup_entry(
        f"gcc-diabetes-prevalence-by-sex-{year}", f"Age-standardised prevalence of diabetes among adults 18+ and 30+ by sex, GCC economies, {year} (WHO GHO)",
        "healthcare", "SA", rows, {"indicator": gho.code, "url": gho.source.url, "year": year},
        lookup_vectors(rows, lead, ("KWT", "BHR")), items,
        [
            {"statistic": "value[KWT,diabetes_18_plus_men_percent]", "expected": rows["KWT"]["diabetes_18_plus_men_percent"], "tolerance": 1e-9},
            {"statistic": "value[BHR,diabetes_30_plus_women_percent]", "expected": rows["BHR"]["diabetes_30_plus_women_percent"], "tolerance": 1e-9},
            {"statistic": f"max[{lead}]", "expected": max(r[lead] for r in rows.values()), "tolerance": 1e-9},
        ],
        ["gcc", "diabetes", "ncd", "by-sex", "who", "health"], ["health-demo", "insurance", "synthetic-customers", "clinical-records"],
        f"Age-standardised prevalence (percent) of diabetes among adults aged 18 and over and aged 30 and over in each GCC state in {year}, for both sexes, men and "
        "women, with the lower and upper bounds of the uncertainty interval (_low and _high), from WHO GHO indicator NCD_DIABETES_PREVALENCE_AGESTD "
        f"({year} is the latest year the indicator carries). The World Bank diabetes table already in the archive gives one both-sexes figure for ages 20 to 79; "
        "this one adds the split by sex. Rows are keyed by ISO 3166-1 alpha-3 code." + WHO_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), status="license-review",
    )


# ---------------------------------------------------------------- main


def main() -> int:
    locations = Locations(Source(UN_LOCATIONS_URL))

    origin = OriginTable(UnWorkbook(Source(IMS_ORIGIN_URL), ["Table 1"]), locations)
    write(ims_origin_entry(origin))
    write(ims_origin_by_sex_entry(origin))
    write(ims_destination_entry(UnWorkbook(Source(IMS_DESTINATION_URL), ["Table 1", "Table 2", "Table 3", "Table 4"]), locations))
    write(ims_age_entry(UnWorkbook(Source(IMS_AGE_URL), ["Table 1"]), locations))

    license_source = Source(WB_LICENSE_URL)
    age_indicators = [f"SP.POP.{band}.{sex}" for sex in ("MA", "FE") for band in AGE_BANDS]
    write(wb_age_entry(WorldBankQuery(Source(wb_url(age_indicators, "2025", 40))), Source(f"{WB_API}/indicator/SP.POP.0004.MA?format=json"), license_source, 2025))
    projections = WorldBankQuery(Source(wb_url(["SP.POP.TOTL", "SP.POP.TOTL.MA.IN", "SP.POP.TOTL.FE.IN"], "2025:2050", 40)))
    write(wb_projection_entry(projections, Source(f"{WB_API}/indicator/SP.POP.TOTL.MA.IN?format=json"), license_source, 2025, 2050))
    write(wb_remittances_paid_entry(WorldBankQuery(Source(wb_url(["BM.TRF.PWKR.CD.DT"], "2010:2024"))), Source(f"{WB_API}/indicator/BM.TRF.PWKR.CD.DT?format=json"), license_source, 2010, 2024))
    write(wb_remittance_cost_entry(WorldBankQuery(Source(wb_url(["SI.RMT.COST.OB.ZS"], "2016:2023"))), Source(f"{WB_API}/indicator/SI.RMT.COST.OB.ZS?format=json"), license_source, 2016, 2023))

    labels = IloLabels(Source(ILO_LABELS_URL))
    write(qa_employment_by_activity(labels, 2024))
    write(qa_employment_by_skill(labels, 2024))
    write(qa_employment_by_age(labels, 2024))
    write(unemployment_by_citizenship(2025, 2024))
    write(sa_earnings_by_citizenship(2020))
    write(gcc_employment_by_activity(labels, 2024))
    write(om_foreign_citizens(labels, locations, 2024))

    write(who_weight_entry(2024))
    write(who_diabetes_entry(2022))
    return 0


if __name__ == "__main__":
    sys.exit(main())

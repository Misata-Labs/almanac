"""Regenerate the business population entries: firm counts, employment, turnover and accounts by size
class outside the United States, for sizing mid-markets and generating synthetic portfolio companies.

Sources: the UK Business Population Estimates 2025 (Department for Business and Trade), UK business:
activity, size and location 2026 (ONS), Eurostat structural business statistics by size class, high-growth
enterprises, business demography by legal form and the small mid-cap size classes, OECD structural and
demographic business statistics, World Bank Enterprise Surveys indicators and the ABS Counts of Australian
Businesses. Run from the repository root:

    uv run python tools/build_biz_population.py [bpe] [ons] [eurostat] [oecd] [wbes] [abs]

With no arguments every group is rebuilt. Every resource is fetched twice and used only when both responses
hash alike, and every evidence item is checked against the fetched text before an entry is written, so a
build fails rather than leaving an entry the verifier would reject.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write
from build_ae_stats import Sheet, read_workbook
from build_eurostat_extended import LICENSE_NOTE as EUROSTAT_LICENSE_NOTE
from build_eurostat_extended import codelist, data_url, dataflow_title

from almanac.fetch import Resource

Record = dict[str, Any]

MAX_SNIPPET_WORDS = 24
OGL = "OGL-UK-3.0"
CC_BY = "CC-BY-4.0"
TAGS = ["firms", "business", "smes", "size-class"]
USE_CASES = ["pe-portfolio-demo", "deal-sourcing-demo", "synthetic-companies", "valuation-demo", "kyb-onboarding", "market-sizing"]


# --- fetching and citation -------------------------------------------------------------------------------------


def fetch_stable(url: str) -> bytes:
    """Fetch a URL twice and return its bytes only when both responses hash alike."""
    first, second = fetch(url), fetch(url)
    if sha(first) != sha(second):
        raise RuntimeError(f"unstable bytes at {url}")
    return first


def collapse(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class Document:
    """One fetched resource that cites only snippets and values its searchable text contains."""

    publisher: str
    title: str
    url: str
    raw: bytes
    license_id: str

    @classmethod
    def get(cls, publisher: str, title: str, url: str, license_id: str) -> Document:
        return cls(publisher, title, url, fetch_stable(url), license_id)

    @cached_property
    def text(self) -> str:
        """The text the verifier searches: ZIP text members for a workbook, decoded bytes otherwise."""
        return collapse(Resource(self.url, self.raw, "").text)

    def leading(self, phrase: str, minimum: int = 4) -> str:
        """The longest opening run of ``phrase`` (at most the snippet limit) that the text contains verbatim.

        Spreadsheet titles are often stored as several formatted runs, so only the part inside one run is searchable.
        """
        words = collapse(phrase).split()[:MAX_SNIPPET_WORDS]
        for end in range(len(words), minimum - 1, -1):
            candidate = " ".join(words[:end])
            if candidate in self.text:
                return candidate
        raise ValueError(f"no searchable opening of {phrase!r} in {self.url}")

    def cite(self, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet exceeds {MAX_SNIPPET_WORDS} words: {snippet!r}")
        for needle, what in ((snippet, "snippet"), (str(value), "value")):
            if collapse(needle) not in self.text:
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        return evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, self.license_id, self.raw, role)


# --- numbers ---------------------------------------------------------------------------------------------------


def number(text: str | None) -> int | float | None:
    """A published cell as a number: integers stay integers, and suppression markers such as [c] or [x] read as None."""
    if text is None:
        return None
    cleaned = text.strip().replace(",", "")
    if not cleaned or cleaned.startswith("[") or cleaned in {":", "-", ".."}:
        return None
    value = float(cleaned)
    return int(value) if value.is_integer() and "." not in cleaned and "E" not in cleaned.upper() else value


def ratio(numerator: Any, denominator: Any, scale: float = 1, digits: int = 6) -> float | None:
    """Divide two published figures, or return None when either is missing or the denominator is zero."""
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) * scale / float(denominator), digits)


def shares(counts: Mapping[str, int | float]) -> dict[str, float]:
    total = sum(counts.values())
    return {key: round(value / total, 6) for key, value in counts.items()}


def without_notes(label: str) -> str:
    """A spreadsheet label with its [Note n] markers and surrounding whitespace removed."""
    return collapse(re.sub(r"\[\s*Note\s*\d+\s*\]", " ", label, flags=re.I))


def rule_entry(entry_id: str, title: str, region: str, valid: tuple[str, str], tags: list[str], parameters: dict, vectors: list[dict], items: list[dict], assumed: list[dict], tests: list[dict], notes: str, status: str = "verified") -> dict:
    """A keyed reference table entry served by the lookup_table rule."""
    if len(title) > 140:
        raise ValueError(f"title too long for {entry_id}: {len(title)} characters")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "business",
        "region": region,
        "status": status,
        "tier": "A",
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": TAGS + tags,
        "use_cases": USE_CASES,
        "spec": {"implementation": "almanac.rules.lookup_table", "parameters": parameters, "vectors": vectors},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def conditional_entry(entry_id: str, title: str, region: str, period: tuple[str, str], tags: list[str], variable: str, given: str, distributions: dict, items: list[dict], assumed: list[dict], tests: list[dict], notes: str) -> dict:
    """A size-band distribution per conditioning value, with the published counts and per-band figures beside the shares."""
    if len(title) > 140:
        raise ValueError(f"title too long for {entry_id}: {len(title)} characters")
    return {
        "id": entry_id,
        "title": title,
        "kind": "conditional",
        "domain": "business",
        "region": region,
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": TAGS + tags,
        "use_cases": USE_CASES,
        "spec": {"variable": variable, "unit": "ratio", "given": given, "distributions": distributions},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def lookup_vector(rows: Mapping[str, Record], key: str, column: str, origin: str = "source", note: str | None = None) -> dict:
    vector = {"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": origin}
    if note:
        vector["note"] = note
    return vector


def max_of(rows: Mapping[str, Record], column: str) -> float:
    return max(float(r[column]) for r in rows.values() if r.get(column) is not None)


# --- UK Business Population Estimates 2025 (Department for Business and Trade) ----------------------------------

DBT = "Department for Business and Trade"
BPE_PATH = "government/statistics/business-population-estimates-2025"
BPE_CONTENT_URL = f"https://www.gov.uk/api/content/{BPE_PATH}"
BPE_XLSX_TITLE = "Business population estimates for the UK and regions 2025: detailed tables (MS Excel)"
BPE_BANDS = {
    "With no employees (unregistered)": "0-unregistered",
    "With no employees (registered)": "0-registered",
    "1": "1",
    "2 to 4": "2-4",
    "5 to 9": "5-9",
    "10 to 19": "10-19",
    "20 to 49": "20-49",
    "50 to 99": "50-99",
    "100 to 199": "100-199",
    "200 to 249": "200-249",
    "250 to 499": "250-499",
    "500 or more": "500+",
    "500 to 999": "500-999",
    "1000 or more": "1000+",
}
BPE_TOTALS = {"All businesses": "all", "All employers": "employers"}
BPE_REGION_TABLES = {
    "Table 11": "North East", "Table 12": "North West", "Table 13": "Yorkshire and the Humber", "Table 14": "East Midlands",
    "Table 15": "West Midlands", "Table 16": "East of England", "Table 17": "London", "Table 18": "South East",
    "Table 19": "South West", "Table 20": "England", "Table 21": "Wales", "Table 22": "Scotland", "Table 23": "Northern Ireland",
}
BPE_NOTES = (
    "The Business Population Estimates count private-sector businesses at the start of 2025, combining businesses registered for VAT or PAYE "
    "on the Inter-Departmental Business Register with estimates of unregistered businesses. The release notes say that companies with a single "
    "PAYE employee are counted with no employees (the employee is treated as a working proprietor), that the turnover of unregistered "
    "businesses is imputed from registered zero-employee businesses in the same sector, that all-industry turnover totals leave out section K "
    "(financial and insurance activities) because its turnover is not available on a comparable basis, and that business counts are rounded so "
    "totals may differ slightly from the sum of the bands; [c] marks a disclosive cell and [x] a cell that is not available, both stored as null. "
    "Employment counts working proprietors and employees, in thousands; turnover is in million pounds excluding VAT. "
    "GOV.UK content is published under the Open Government Licence v3.0."
)


def bpe_band(label: str | None) -> str | None:
    """The size-band key for a BPE row label, or None for a row that is not a size band."""
    if label is None:
        return None
    clean = without_notes(label)
    return BPE_TOTALS.get(clean) or BPE_BANDS.get(clean)


def bpe_blocks(sheet: Sheet) -> dict[str, tuple[str, dict[str, list[str | None]]]]:
    """Split a sectioned BPE sheet into blocks keyed by heading code, each with its rows keyed by size band."""
    rows = sheet.rows()
    start = next(i for i, row in enumerate(rows) if row[0] and row[0].strip() == "Employee size band") + 1
    blocks: dict[str, tuple[str, dict[str, list[str | None]]]] = {}
    current: dict[str, list[str | None]] | None = None
    for row in rows[start:]:
        label = row[0]
        if label is None or not label.strip():
            continue
        band = bpe_band(label)
        if band is not None and current is not None:
            current[band] = row
            continue
        if all(cell is None or not cell.strip() for cell in row[1:]):
            heading = collapse(label)
            match = re.match(r"^([A-Z](?:(?:,\s*|\s+and\s+)[A-Z])*)\s+(.*)$", heading)
            code, name = ("+".join(re.split(r",\s*|\s+and\s+", match.group(1))), match.group(2)) if match else ("ALL", heading)
            current = {}
            blocks[code] = (name, current)
    return blocks


def bpe_header(sheet: Sheet, row_label: str = "Employee size band") -> list[str]:
    header = next(row for row in sheet.rows() if row[0] and row[0].strip() == row_label)
    return [collapse(without_notes(cell or "")) for cell in header]


def bpe_documents() -> tuple[Document, Document]:
    content = Document.get(f"{DBT} (GOV.UK)", f"GOV.UK content API item for /{BPE_PATH} (JSON)", BPE_CONTENT_URL, OGL)
    item = json.loads(content.raw)
    url = next(a["url"] for a in item["details"]["attachments"] if a.get("title") == BPE_XLSX_TITLE)
    workbook = Document.get(DBT, "Business population estimates for the UK and regions 2025: detailed tables (XLSX)", url, OGL)
    return content, workbook


def bpe_release_item(content: Document, workbook: Document) -> dict:
    return content.cite("details.attachments[title=detailed tables (MS Excel)].url", workbook.url, "text", BPE_XLSX_TITLE, role="supporting")


def bpe_size_band_table(content: Document, workbook: Document, sheets: dict[str, Sheet]) -> dict:
    sheet = sheets["Table 1"]
    header = bpe_header(sheet)
    expected = ["Business number", "Employment number (thousands)", "Employees number (thousands)", "Working Proprietors number (thousands)", "Turnover (£ millions)"]
    if header[1:6] != expected:
        raise ValueError(f"unexpected Table 1 header {header}")
    rows: dict[str, Record] = {}
    for row in sheet.rows():
        band = bpe_band(row[0])
        if band is None:
            continue
        businesses, employment, employees, proprietors, turnover = (number(c) for c in row[1:6])
        rows[band] = {
            "label": without_notes(row[0]),
            "businesses": businesses,
            "employment_thousands": employment,
            "employees_thousands": employees,
            "working_proprietors_thousands": proprietors,
            "turnover_gbp_million": turnover,
            "businesses_percent": number(row[6]),
            "employment_percent": number(row[7]),
            "turnover_percent": number(row[10]),
            "turnover_per_employment_gbp_thousand": ratio(turnover, employment, 1, 3),
            "turnover_per_business_gbp_thousand": ratio(turnover, businesses, 1000, 3),
            "employment_per_business": ratio(employment, businesses, 1000, 3),
        }
    raw = {band: row for row in sheet.rows() if (band := bpe_band(row[0]))}
    items = [
        workbook.cite("Table 1, row All businesses, column Business number", int(raw["all"][1]), "count", "Table 1 (UK private sector): Number and percentage of businesses in the private sector"),
        workbook.cite("Table 1, row 1000 or more, column Turnover (£ millions)", int(raw["1000+"][5]), "currency:GBP", "1000 or more"),
        workbook.cite("Table 1, row 10 to 19, column Business number", int(raw["10-19"][1]), "count", "10 to 19"),
        bpe_release_item(content, workbook),
    ]
    return rule_entry(
        "gb-business-population-by-size-band-2025",
        "UK private-sector businesses, employment and turnover by employee size band, start of 2025 (DBT Business Population Estimates)",
        "GB",
        ("2025-01-01", "2025-12-31"),
        ["business-population-estimates", "turnover", "employment", "revenue-per-employee"],
        {"source_table": "Table 1", "rows": rows},
        [
            lookup_vector(rows, "all", "businesses"),
            lookup_vector(rows, "1000+", "turnover_gbp_million"),
            lookup_vector(rows, "10-19", "businesses"),
            lookup_vector(rows, "50-99", "turnover_per_employment_gbp_thousand", "derived", "turnover_gbp_million / employment_thousands"),
            {"input": "250+", "expected": False, "origin": "derived", "note": "the table splits 250 or more into 250-499, 500-999 and 1000+"},
        ],
        items,
        [
            {"parameter": "rows[*].turnover_per_employment_gbp_thousand", "value": "turnover_gbp_million / employment_thousands", "method": "derived", "rationale": "Turnover per person employed (working proprietors plus employees) in thousand pounds, from the published turnover and employment of the band."},
            {"parameter": "rows[*].turnover_per_business_gbp_thousand", "value": "turnover_gbp_million * 1000 / businesses", "method": "derived", "rationale": "Average turnover per business of the band in thousand pounds."},
            {"parameter": "rows[*].employment_per_business", "value": "employment_thousands * 1000 / businesses", "method": "derived", "rationale": "Average headcount (working proprietors plus employees) per business of the band."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[all,businesses]", "expected": rows["all"]["businesses"], "tolerance": 0},
            {"statistic": "max[turnover_per_employment_gbp_thousand]", "expected": max_of(rows, "turnover_per_employment_gbp_thousand"), "tolerance": 0},
        ],
        "UK private-sector business population at the start of 2025 from Table 1 of the Business Population Estimates detailed tables, one row per employee "
        "size band (zero-employee businesses split into unregistered and VAT or PAYE registered, then 1, 2-4, 5-9, 10-19, 20-49, 50-99, 100-199, 200-249, "
        "250-499, 500-999 and 1000 or more) plus the all-businesses and all-employers totals. Each row carries the number of businesses, employment, "
        "employees and working proprietors in thousands, turnover in million pounds, the published percentages, and derived turnover per person "
        "employed, turnover per business and headcount per business. " + BPE_NOTES,
    )


def bpe_distribution(name: str, block: dict[str, list[str | None]], exclude: Iterable[str] = ("all", "employers")) -> dict:
    """A categorical size-band distribution of business counts with employment and turnover by band beside it."""
    bands = {band: row for band, row in block.items() if band not in exclude}
    counts = {band: number(row[1]) for band, row in bands.items()}
    employment = {band: number(row[2]) for band, row in bands.items()}
    turnover = {band: number(row[3]) for band, row in bands.items()}
    return {
        "family": "categorical",
        "parameters": {
            "shares": shares(counts),
            "businesses": counts,
            "employment_thousands": employment,
            "turnover_gbp_million": turnover,
            "turnover_per_employment_gbp_thousand": {band: ratio(turnover[band], employment[band], 1, 3) for band in bands},
            "label": name,
            "all_businesses": number(block["all"][1]),
        },
    }


BPE_DISTRIBUTION_ASSUMED = [
    {"parameter": "distributions[*].parameters.shares", "value": "businesses in a band / sum of businesses over the bands", "method": "derived", "rationale": "Shares are taken over the published size bands (the all-businesses and all-employers totals are kept out); because the counts are rounded, the band sum can differ slightly from the published all-businesses figure, which is kept as all_businesses."},
    {"parameter": "distributions[*].parameters.turnover_per_employment_gbp_thousand", "value": "turnover_gbp_million / employment_thousands", "method": "derived", "rationale": "Turnover per person employed in thousand pounds for the band; null where either input is suppressed or not available."},
]


def bpe_by_section(content: Document, workbook: Document, sheets: dict[str, Sheet]) -> dict:
    blocks = bpe_blocks(sheets["Table 5"])
    header = bpe_header(sheets["Table 5"])
    if header[1:4] != ["Business number", "Employment number (thousands)", "Turnover (£ millions)"]:
        raise ValueError(f"unexpected Table 5 header {header}")
    distributions = {code: bpe_distribution(name, rows) for code, (name, rows) in blocks.items()}
    manufacturing = blocks["C"][1]
    items = [
        workbook.cite("Table 5, block C Manufacturing, row All businesses, column Business number", int(manufacturing["all"][1]), "count", "C Manufacturing"),
        workbook.cite("Table 5, block C Manufacturing, row 10 to 19, column Business number", int(manufacturing["10-19"][1]), "count", "Table 5 (UK sections): Number of businesses in the private sector and their associated employment and"),
        workbook.cite("Table 5, block F Construction, row 2 to 4, column Turnover (£ millions)", int(blocks["F"][1]["2-4"][3]), "currency:GBP", "F Construction"),
        bpe_release_item(content, workbook),
    ]
    c = distributions["C"]["parameters"]["shares"]
    f = distributions["F"]["parameters"]["shares"]
    return conditional_entry(
        "gb-business-population-size-band-by-industry-section-2025",
        "UK private-sector businesses by employee size band given SIC 2007 section, with employment and turnover, start of 2025 (DBT)",
        "GB",
        ("2025-01-01", "2025-01-01"),
        ["business-population-estimates", "sic-2007", "industry", "turnover", "employment", "revenue-per-employee"],
        "employee_size_band",
        "sic_section",
        distributions,
        items,
        BPE_DISTRIBUTION_ASSUMED,
        [
            {"statistic": "share[C,10-19]", "expected": c["10-19"], "tolerance": 0.005},
            {"statistic": "share[F,0-unregistered]", "expected": f["0-unregistered"], "tolerance": 0.01},
            {"statistic": "sum_of_shares[C]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[ALL]", "expected": 1, "tolerance": 1e-4},
        ],
        "Size-band distribution of UK private-sector businesses at the start of 2025 for each SIC 2007 section, from Table 5 of the Business Population "
        "Estimates detailed tables, keyed by section letter (B+D+E is the combined mining, energy and water block the table publishes; ALL is all industries). Each distribution is over twelve employee size bands (zero employees unregistered "
        "and registered, 1, 2-4, 5-9, 10-19, 20-49, 50-99, 100-199, 200-249, 250-499 and 500 or more) and carries the published business counts, "
        "employment in thousands, turnover in million pounds, derived turnover per person employed, the section name and the published all-businesses "
        "total. Sample a band from the shares, then size the firm's revenue from turnover_per_employment_gbp_thousand of the same band. " + BPE_NOTES,
    )


def bpe_by_region(content: Document, workbook: Document, sheets: dict[str, Sheet]) -> dict:
    distributions = {"United Kingdom": bpe_distribution("United Kingdom", bpe_blocks(sheets["Table 5"])["ALL"][1])}
    for table, region in BPE_REGION_TABLES.items():
        title = sheets[table].rows()[0][0] or ""
        if f"({region})" not in title:
            raise ValueError(f"{table} is not the {region} table: {title!r}")
        distributions[region] = bpe_distribution(region, bpe_blocks(sheets[table])["ALL"][1])
    london = bpe_blocks(sheets["Table 17"])["ALL"][1]
    scotland = bpe_blocks(sheets["Table 22"])["ALL"][1]
    items = [
        workbook.cite("Table 17 (London), block All Industries, row All businesses, column Business number", int(london["all"][1]), "count", "Table 17 (London): Number of businesses in the private sector and their associated employment and turnover,"),
        workbook.cite("Table 22 (Scotland), block All Industries, row 250 to 499, column Business number", int(scotland["250-499"][1]), "count", "Table 22 (Scotland): Number of businesses in the private sector and their associated employment and"),
        bpe_release_item(content, workbook),
    ]
    ldn = distributions["London"]["parameters"]["shares"]
    return conditional_entry(
        "gb-business-population-size-band-by-region-2025",
        "UK private-sector businesses by employee size band given region or nation, with employment and turnover, start of 2025 (DBT)",
        "GB",
        ("2025-01-01", "2025-01-01"),
        ["business-population-estimates", "region", "turnover", "employment", "revenue-per-employee"],
        "employee_size_band",
        "region",
        distributions,
        items,
        BPE_DISTRIBUTION_ASSUMED,
        [
            {"statistic": "share[London,2-4]", "expected": ldn["2-4"], "tolerance": 0.01},
            {"statistic": "sum_of_shares[London]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[Northern Ireland]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[United Kingdom]", "expected": 1, "tolerance": 1e-4},
        ],
        "Size-band distribution of private-sector businesses at the start of 2025 for the United Kingdom, the nine English regions, England, Wales, "
        "Scotland and Northern Ireland, from the all-industries block of Tables 11 to 23 (and Table 5 for the United Kingdom) of the Business "
        "Population Estimates detailed tables. Each distribution is over the same twelve employee size bands as the by-section entry and carries "
        "business counts, employment in thousands, turnover in million pounds and derived turnover per person employed. " + BPE_NOTES,
    )


def build_bpe() -> list[dict]:
    content, workbook = bpe_documents()
    sheets = read_workbook(workbook.raw)
    return [bpe_size_band_table(content, workbook, sheets), bpe_by_section(content, workbook, sheets), bpe_by_region(content, workbook, sheets)]


# --- ONS UK business: activity, size and location 2026 --------------------------------------------------------

ONS = "Office for National Statistics"
ONS_URL = "https://www.ons.gov.uk/file?uri=/businessindustryandtrade/business/activitysizeandlocation/datasets/ukbusinessactivitysizeandlocation/2026/ukbusinessworkbook2026.xlsx"
ONS_TITLE = "UK business: activity, size and location, 2026 (XLSX workbook)"
ONS_NOTES = (
    "Counts are VAT and/or PAYE based enterprises (or local units, the individual sites of an enterprise) from a 2026 snapshot of the "
    "Inter-Departmental Business Register, published on 24 September 2026. The workbook notes say that counts are rounded to base 5 to avoid "
    "disclosure (so a zero is not necessarily a true zero and totals can differ slightly from the sum of their parts), that employment comes "
    "mainly from the Business Register Employment Survey with PAYE jobs or VAT-imputed employment for the smallest units, that turnover is "
    "mainly from VAT returns for a twelve-month period covering the 2024/2025 financial year and is stated in thousand pounds, and that a new "
    "SIC coding tool introduced in late 2025 changed some detailed industry assignments. Unlike the Business Population Estimates, these counts "
    "exclude unregistered businesses and cover public-sector and non-profit bodies as well as private businesses. "
    "ONS publishes under the Open Government Licence v3.0."
)
ONS_PERIOD_ASSUMED = {
    "parameter": "observed_period",
    "value": "2026-01-01 to 2026-09-24",
    "method": "assumed",
    "rationale": "The workbook describes a 2026 snapshot of the IDBR and its publication date of 24 September 2026 but does not state the snapshot date, so the period runs from the start of 2026 to publication.",
}


def ons_area(label: str) -> tuple[str, str]:
    code, _, name = collapse(label).partition(" : ")
    return code, name


def ons_division_table(sheet: Sheet) -> tuple[list[str], dict[str, tuple[str, list[int]]], str]:
    """The UK block of a division-by-sizeband table: band labels and, per division code, its label and counts."""
    rows = sheet.rows()
    header_index = next(i for i, row in enumerate(rows) if row[1] and row[1].startswith("K02000001"))
    if not rows[header_index][1].startswith("K02000001 : United Kingdom"):
        raise ValueError("the first block is not the United Kingdom")
    bands_row = rows[header_index + 1]
    width = bands_row.index("Total", 1)
    bands = [collapse(b) for b in bands_row[1:width]]
    divisions: dict[str, tuple[str, list[int]]] = {}
    for row in rows[header_index + 2:]:
        if row[0] is None:
            continue
        label = collapse(row[0])
        if label == "Total":
            break
        code, _, name = label.partition(" : ")
        divisions[code] = (name, [number(c) for c in row[1:width + 1]])
    return bands, divisions, rows[0][0] or ""


def ons_division_entry(document: Document, sheets: dict[str, Sheet], table: str, variable: str, kind: str) -> dict:
    bands, divisions, table_title = ons_division_table(sheets[table])
    distributions: dict[str, dict] = {}
    empty = []
    for code, (name, counts) in divisions.items():
        by_band = dict(zip(bands, counts[:-1]))
        if sum(by_band.values()) == 0:
            empty.append(code)
            continue
        distributions[code] = {"family": "categorical", "parameters": {"shares": shares(by_band), "enterprises": by_band, "total": counts[-1], "label": name}}
    snippet = document.leading(table_title)
    retail = divisions["47"]
    top = bands[-1]
    items = [
        document.cite(f"{table}, row 47 (Retail trade), UK block, column Total", retail[1][-1], "count", f"47 : {retail[0]}"),
        document.cite(f"{table}, row 62 (Computer programming), UK block, column {top}", divisions["62"][1][len(bands) - 1], "count", snippet),
    ]
    noun = "employment" if kind == "employment" else "turnover"
    unit_phrase = "persons employed" if kind == "employment" else "thousand pounds of annual turnover"
    entry_id = f"gb-enterprises-by-{noun}-size-band-and-sic-division-2026"
    c62 = distributions["62"]["parameters"]["shares"]
    c47 = distributions["47"]["parameters"]["shares"]
    return conditional_entry(
        entry_id,
        f"UK VAT/PAYE enterprises by {noun} size band given SIC 2007 division, 2026 (ONS UK business: activity, size and location)",
        "GB",
        ("2026-01-01", "2026-09-24"),
        ["ons", "idbr", "sic-2007", "industry", noun + "-band"],
        variable,
        "sic_division",
        distributions,
        items,
        [
            {"parameter": "distributions[*].parameters.shares", "value": "enterprises in a band / sum of enterprises over the bands", "method": "derived", "rationale": "Shares over the published size bands of the UK block; the published total is kept as total and can differ slightly from the band sum because each count is rounded to base 5."},
            ONS_PERIOD_ASSUMED,
        ],
        [
            {"statistic": f"share[47,{bands[0]}]", "expected": c47[bands[0]], "tolerance": 0.01},
            {"statistic": f"share[62,{bands[0]}]", "expected": c62[bands[0]], "tolerance": 0.01},
            {"statistic": "sum_of_shares[47]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[62]", "expected": 1, "tolerance": 1e-4},
        ],
        f"Distribution of UK enterprises over {noun} size bands ({', '.join(bands)}, in {unit_phrase}) for each two-digit SIC 2007 division, "
        f"from the United Kingdom block of {table} of the ONS workbook. Each distribution carries the published counts by band, the published total "
        f"and the division name. Divisions whose published counts are all zero are omitted: {', '.join(empty) or 'none'}. " + ONS_NOTES,
    )


LEGAL_STATUS_KEYS = {
    "1 - Company (incl. Building Society)": "company",
    "2 - Sole Proprietor": "sole_proprietor",
    "3 - Partnership": "partnership",
    "4 - Public Corporation/Nationalised Body": "public_corporation",
    "5 - Central Government": "central_government",
    "6 - Local Authority": "local_authority",
    "7 - Non-profit Body or Mutual Association": "non_profit_or_mutual",
    "Total": "total",
}


def band_slug(band: str) -> str:
    return band.replace("-", "_").replace("+", "_plus")


def ons_blocks(sheet: Sheet) -> tuple[dict[str, dict[str, list[int | None]]], dict[str, str], list[str]]:
    """A legal-status-by-region table as {legal status key: {area code: counts}}, the area names and the band labels."""
    rows = sheet.rows()
    header = next(i for i, row in enumerate(rows) if row[1] and row[1].startswith("1 - Company"))
    statuses = [(i, collapse(c)) for i, c in enumerate(rows[header]) if c]
    bands_row = rows[header + 1]
    blocks: dict[str, dict[str, list[int | None]]] = {}
    names: dict[str, str] = {}
    bands: list[str] = []
    for position, (column, status) in enumerate(statuses):
        end = statuses[position + 1][0] if position + 1 < len(statuses) else len(bands_row)
        labels = [collapse(b) for b in bands_row[column:end] if b]
        if labels[-1] != "Total":
            raise ValueError(f"block {status} does not end with Total")
        bands = labels[:-1]
        key = LEGAL_STATUS_KEYS[status]
        blocks[key] = {}
        for row in rows[header + 2:]:
            if row[0] is None or ":" not in row[0]:
                continue
            code, name = ons_area(row[0])
            names[code] = name
            blocks[key][code] = [number(c) for c in row[column:column + len(labels)]]
    return blocks, names, bands


def ons_region_entry(document: Document, sheets: dict[str, Sheet]) -> dict:
    employment, names, employment_bands = ons_blocks(sheets["Table 14"])
    turnover, _, turnover_bands = ons_blocks(sheets["Table 15"])
    local_units, _, unit_bands = ons_blocks(sheets["Table 24"])
    header = next(row for row in sheets["Table 3"].rows() if row[1] and row[1].startswith("K02000001"))
    display = dict(ons_area(cell) for cell in header if cell and " : " in cell)
    rows: dict[str, Record] = {}
    for code in names:
        record: Record = {"name": display[code], "enterprises": employment["total"][code][-1]}
        for band, value in zip(employment_bands, employment["total"][code]):
            record[f"enterprises_employment_{band_slug(band)}"] = value
        for band, value in zip(turnover_bands, turnover["total"][code]):
            record[f"enterprises_turnover_gbp_thousand_{band_slug(band)}"] = value
        for status in LEGAL_STATUS_KEYS.values():
            if status != "total":
                record[f"enterprises_{status}"] = employment[status][code][-1]
        record["local_units"] = local_units["total"][code][-1]
        for band, value in zip(unit_bands, local_units["total"][code]):
            record[f"local_units_employment_{band_slug(band)}"] = value
        record["local_units_per_enterprise"] = ratio(record["local_units"], record["enterprises"], 1, 4)
        record["company_share_of_enterprises"] = ratio(record["enterprises_company"], record["enterprises"])
        rows[code] = record
    uk, london = "K02000001", "E12000007"
    items = [
        document.cite("Table 14, row K02000001 : UNITED KINGDOM, Total block, column Total", rows[uk]["enterprises"], "count", document.leading(sheets["Table 14"].rows()[0][0])),
        document.cite("Table 15, row E12000007 : London, Total block, column 50000+", rows[london][f"enterprises_turnover_gbp_thousand_{band_slug(turnover_bands[-1])}"], "count", document.leading(sheets["Table 15"].rows()[0][0])),
        document.cite("Table 24, row K02000001 : UNITED KINGDOM, Total block, column Total", rows[uk]["local_units"], "count", document.leading(sheets["Table 24"].rows()[0][0])),
    ]
    top_turnover = f"enterprises_turnover_gbp_thousand_{band_slug(turnover_bands[-1])}"
    return rule_entry(
        "gb-enterprises-and-local-units-by-region-size-and-legal-status-2026",
        "UK enterprises and local units by region and nation, employment band, turnover band and legal status, 2026 (ONS)",
        "GB",
        ("2026-01-01", "2026-12-31"),
        ["ons", "idbr", "region", "legal-status", "local-units", "turnover-band"],
        {"source_tables": ["Table 14", "Table 15", "Table 24"], "employment_bands": employment_bands, "turnover_bands_gbp_thousand": turnover_bands, "rows": rows},
        [
            lookup_vector(rows, uk, "enterprises"),
            lookup_vector(rows, london, top_turnover),
            lookup_vector(rows, uk, "local_units"),
            lookup_vector(rows, uk, "local_units_per_enterprise", "derived", "local_units / enterprises"),
            {"input": "E12000010", "expected": False, "origin": "derived", "note": "no such English region"},
        ],
        items,
        [
            {"parameter": "rows[*].local_units_per_enterprise", "value": "local_units / enterprises", "method": "derived", "rationale": "Average number of sites per enterprise in the area; an enterprise is located at its main operating site or head office while its local units are counted where they are."},
            {"parameter": "rows[*].company_share_of_enterprises", "value": "enterprises_company / enterprises", "method": "derived", "rationale": "Share of enterprises that are companies (including building societies)."},
            ONS_PERIOD_ASSUMED,
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{london},enterprises]", "expected": rows[london]["enterprises"], "tolerance": 0},
            {"statistic": "max[local_units_per_enterprise]", "expected": max_of(rows, "local_units_per_enterprise"), "tolerance": 0},
        ],
        "One row per area keyed by GSS code (United Kingdom, Great Britain, England and Wales, England, the nine English regions, Wales, Scotland and "
        "Northern Ireland) from the total blocks of Tables 14, 15 and 24 of the ONS workbook: enterprises by employment size band "
        f"({', '.join(employment_bands)} persons), enterprises by turnover size band ({', '.join(turnover_bands)} thousand pounds), enterprises by "
        "legal status (company including building society, sole proprietor, partnership, public corporation or nationalised body, central "
        "government, local authority, non-profit body or mutual association), and local units by employment size band. An enterprise is placed "
        "at its main operating site or head office, so an area's local units can outnumber its enterprises. " + ONS_NOTES,
    )


def build_ons() -> list[dict]:
    document = Document.get(ONS, ONS_TITLE, ONS_URL, OGL)
    sheets = read_workbook(document.raw)
    return [
        ons_division_entry(document, sheets, "Table 3", "employment_size_band", "employment"),
        ons_division_entry(document, sheets, "Table 8", "turnover_size_band_gbp_thousand", "turnover"),
        ons_region_entry(document, sheets),
    ]


# --- Eurostat ---------------------------------------------------------------------------------------------------

EUROSTAT = "Eurostat"
EU_GEOS = ["EU27_2020", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"]
SBS_YEAR = "2024"
SBS_SECTIONS = ["B-S_X_O_S94", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "P", "Q", "R", "S95", "S96"]
SBS_SIZES = ["0_1", "2-9", "10-19", "20-49", "50-249", "GE250", "TOTAL"]
SBS_INDICATORS = {
    "ENT_NR": "enterprises",
    "EMP_NR": "persons_employed",
    "NETTUR_MEUR": "net_turnover_meur",
    "AV_MEUR": "value_added_meur",
    "GOS_MEUR": "gross_operating_surplus_meur",
    "EXPN_SAL_BEN_MEUR": "employee_benefits_expense_meur",
    "GOR_PC": "gross_operating_rate_percent",
}
COUNTS = {"enterprises", "persons_employed"}


def eurostat_rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def eurostat_value(row: dict[str, str], column: str) -> int | float | None:
    if not row["OBS_VALUE"]:
        return None
    value = float(row["OBS_VALUE"])
    return int(value) if column in COUNTS else value


def flag_note(cells: Iterable[tuple[str, str]], flags: Mapping[str, str]) -> str:
    """Spell out which row keys carry each observation flag so a reader knows which cells Eurostat qualifies."""
    grouped: dict[str, set[str]] = {}
    for key, code in cells:
        for letter in code:
            grouped.setdefault(letter, set()).add(key)
    if not grouped:
        return ""
    parts = []
    for code, keys in sorted(grouped.items()):
        listed = sorted(keys)
        shown = ", ".join(listed[:12]) + (f" and {len(listed) - 12} more" if len(listed) > 12 else "")
        parts.append(f"{flags.get(code, code)} ({code}) on {shown}")
    return " Observation flags published with the data: " + "; ".join(parts) + "."


@dataclass(frozen=True)
class Labels:
    """English labels of the Eurostat codelists the entries use."""

    geo: dict[str, str]
    nace: dict[str, str]
    size: dict[str, str]
    flags: dict[str, str]
    indicators: dict[str, str]
    legal_forms: dict[str, str]

    @classmethod
    def fetch(cls) -> Labels:
        return cls(codelist("GEO"), codelist("NACE_R2"), codelist("SIZE_EMP"), codelist("OBS_FLAG"), codelist("INDIC_SBS"), codelist("LEG_FORM"))


def eurostat_document(dataflow: str, description: str, key: str) -> Document:
    return Document.get(EUROSTAT, dataflow_title(dataflow, description), data_url(dataflow, key, SBS_YEAR, SBS_YEAR), CC_BY)


def eurostat_cite(document: Document, row: dict[str, str], dims: Iterable[str], unit: str) -> dict:
    """Cite one SDMX-CSV observation by its dimension codes, with the row's own code sequence as the snippet."""
    codes = [row[d] for d in dims]
    locator = ", ".join(f"{d}={row[d]}" for d in dims) + f", TIME_PERIOD={row['TIME_PERIOD']}, OBS_VALUE"
    return document.cite(locator, row["OBS_VALUE"], unit, ",".join(codes + [row["TIME_PERIOD"], row["OBS_VALUE"]]))


SBS_ASSUMED = [
    {"parameter": "rows[*].net_turnover_per_enterprise_teur", "value": "net_turnover_meur * 1000 / enterprises", "method": "derived", "rationale": "Average turnover per enterprise of the size class in thousand euro."},
    {"parameter": "rows[*].net_turnover_per_person_employed_teur", "value": "net_turnover_meur * 1000 / persons_employed", "method": "derived", "rationale": "Turnover per person employed in thousand euro, the revenue-per-head benchmark for the size class."},
    {"parameter": "rows[*].value_added_per_person_employed_teur", "value": "value_added_meur * 1000 / persons_employed", "method": "derived", "rationale": "Apparent labour productivity in thousand euro per person employed."},
    {"parameter": "rows[*].gross_operating_surplus_to_turnover", "value": "gross_operating_surplus_meur / net_turnover_meur", "method": "derived", "rationale": "Operating margin proxy as a ratio; Eurostat's gross_operating_rate_percent is the published percentage and is kept beside it."},
    {"parameter": "rows[*].employee_benefits_share_of_turnover", "value": "employee_benefits_expense_meur / net_turnover_meur", "method": "derived", "rationale": "Personnel costs as a share of turnover."},
    {"parameter": "rows[*].enterprise_share_of_activity", "value": "enterprises / enterprises of the TOTAL size class of the same activity", "method": "derived", "rationale": "Share of the activity's enterprises in the size class, for sampling a size class given an activity; the other *_share_of_activity columns do the same for persons employed and turnover."},
]


def sbs_entry(geo: str, labels: Labels) -> dict:
    key = f"A.{'+'.join(SBS_INDICATORS)}.{'+'.join(SBS_SECTIONS)}.{'+'.join(SBS_SIZES)}.{geo}"
    document = eurostat_document("sbs_sc_ovw", "enterprise statistics by size class and NACE Rev. 2 activity", key)
    source = eurostat_rows(document.raw)
    if {r["TIME_PERIOD"] for r in source} != {SBS_YEAR}:
        raise ValueError(f"sbs_sc_ovw {geo} is not limited to {SBS_YEAR}")
    rows: dict[str, Record] = {}
    for nace in SBS_SECTIONS:
        for size in SBS_SIZES:
            rows[f"{nace}|{size}"] = {"activity": labels.nace[nace], "size_class": labels.size[size], **dict.fromkeys(SBS_INDICATORS.values())}
    for r in source:
        rows[f"{r['nace_r2']}|{r['size_emp']}"][SBS_INDICATORS[r["indic_sbs"]]] = eurostat_value(r, SBS_INDICATORS[r["indic_sbs"]])
    for row_key, record in rows.items():
        total = rows[f"{row_key.split('|')[0]}|TOTAL"]
        record["net_turnover_per_enterprise_teur"] = ratio(record["net_turnover_meur"], record["enterprises"], 1000, 3)
        record["net_turnover_per_person_employed_teur"] = ratio(record["net_turnover_meur"], record["persons_employed"], 1000, 3)
        record["value_added_per_person_employed_teur"] = ratio(record["value_added_meur"], record["persons_employed"], 1000, 3)
        record["gross_operating_surplus_to_turnover"] = ratio(record["gross_operating_surplus_meur"], record["net_turnover_meur"])
        record["employee_benefits_share_of_turnover"] = ratio(record["employee_benefits_expense_meur"], record["net_turnover_meur"])
        record["enterprise_share_of_activity"] = ratio(record["enterprises"], total["enterprises"])
        record["persons_employed_share_of_activity"] = ratio(record["persons_employed"], total["persons_employed"])
        record["net_turnover_share_of_activity"] = ratio(record["net_turnover_meur"], total["net_turnover_meur"])
    rows = {k: v for k, v in rows.items() if any(v[c] is not None for c in SBS_INDICATORS.values())}
    flagged = [(f"{r['nace_r2']}|{r['size_emp']}", r["OBS_FLAG"]) for r in source if r["OBS_FLAG"] and r["OBS_VALUE"]]
    withheld = sorted({f"{r['nace_r2']}|{r['size_emp']}" for r in source if not r["OBS_VALUE"]})

    def find(nace: str, size: str, indicator: str) -> dict[str, str] | None:
        return next((r for r in source if r["nace_r2"] == nace and r["size_emp"] == size and r["indic_sbs"] == indicator and r["OBS_VALUE"]), None)

    dims = ("indic_sbs", "nace_r2", "size_emp", "geo")
    total_ent = find("B-S_X_O_S94", "TOTAL", "ENT_NR")
    large_c = find("C", "GE250", "NETTUR_MEUR") or find("C", "GE250", "ENT_NR")
    mid_c = find("C", "50-249", "GOR_PC") or find("C", "TOTAL", "GOR_PC")
    items = [
        eurostat_cite(document, total_ent, dims, "count"),
        eurostat_cite(document, large_c, dims, "currency:EUR" if large_c["indic_sbs"] == "NETTUR_MEUR" else "count"),
        eurostat_cite(document, mid_c, dims, "percent"),
    ]
    agg = "B-S_X_O_S94|TOTAL"
    large_key = "C|GE250"
    mid_key = f"C|{mid_c['size_emp']}"
    derived_key = next(k for k in ("C|10-19", "G|10-19", agg) if k in rows and rows[k]["net_turnover_per_enterprise_teur"] is not None)
    is_eu = geo == "EU27_2020"
    name = labels.geo[geo]
    entry_id = f"{'eu' if is_eu else geo.lower()}-enterprise-accounts-by-nace-and-size-class-{SBS_YEAR}"
    region = "EU" if is_eu else geo
    title_name = "EU27" if is_eu else name
    return rule_entry(
        entry_id,
        f"{title_name} enterprise accounts by NACE section and employment size class with derived ratios, {SBS_YEAR} (Eurostat sbs_sc_ovw)",
        region,
        (f"{SBS_YEAR}-01-01", f"{SBS_YEAR}-12-31"),
        ["structural-business-statistics", "nace", "turnover", "value-added", "operating-margin", "eurostat", "revenue-per-employee"],
        {"dataflow": "sbs_sc_ovw", "key": key, "period": SBS_YEAR, "geo": geo, "size_classes": {s: labels.size[s] for s in SBS_SIZES}, "rows": rows},
        [
            lookup_vector(rows, agg, "enterprises"),
            lookup_vector(rows, large_key, SBS_INDICATORS[large_c["indic_sbs"]]),
            lookup_vector(rows, mid_key, "gross_operating_rate_percent"),
            lookup_vector(rows, derived_key, "net_turnover_per_enterprise_teur", "derived", "net_turnover_meur * 1000 / enterprises"),
            {"input": "A|TOTAL", "expected": False, "origin": "derived", "note": "agriculture is outside structural business statistics"},
        ],
        items,
        SBS_ASSUMED,
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{agg},enterprises]", "expected": rows[agg]["enterprises"], "tolerance": 0},
            {"statistic": "max[net_turnover_per_person_employed_teur]", "expected": max_of(rows, "net_turnover_per_person_employed_teur"), "tolerance": 0},
        ],
        f"Structural business statistics for {name} in {SBS_YEAR} from Eurostat dataflow sbs_sc_ovw, one row per NACE Rev. 2 activity and size class of "
        f"persons employed, keyed activity|size_class: the aggregate B-S_X_O_S94 ({labels.nace['B-S_X_O_S94']}), sections B to R except O, and "
        "divisions S95 and S96, each for the classes 0_1, 2-9, 10-19, 20-49, 50-249, GE250 and TOTAL; classes are by persons employed, not employees, "
        "and a class the country does not publish has no row. Published columns, with their INDIC_SBS labels: "
        + "; ".join(f"{column} ({labels.indicators[code]})" for code, column in SBS_INDICATORS.items())
        + ". Derived columns give "
        "turnover per enterprise and per person employed, value added per person employed, the operating-surplus and personnel-cost shares of "
        "turnover, and each class's share of the activity's enterprises, persons employed and turnover; every derived column is null where an input "
        "is missing. This complements the by-NACE enterprise accounts entries, which have no size dimension."
        + (f" Cells Eurostat withholds as confidential (no value) occur in: {', '.join(withheld[:20])}{' and more' if len(withheld) > 20 else ''}." if withheld else "")
        + flag_note(flagged, labels.flags) + " " + EUROSTAT_LICENSE_NOTE,
    )


HG_INDICATORS = {
    "ENT_HGRW_NR": "high_growth_enterprises",
    "ENT_HGRWR_PC": "high_growth_share_of_enterprises_10_plus_percent",
    "SAL_HGRW_NR": "employees_in_high_growth_enterprises",
    "SAL_HGRWR_PC": "high_growth_share_of_employees_10_plus_percent",
    "ENT_HGRW_SALSIZE_NR": "employees_per_high_growth_enterprise",
    "ENT_HGRW_YNG_NR": "young_high_growth_enterprises",
    "ENT_HGRWR_YNG_PC": "young_high_growth_share_of_enterprises_10_plus_percent",
    "SAL_HGRW_YNG_NR": "employees_in_young_high_growth_enterprises",
}
HG_COUNTS = {"high_growth_enterprises", "employees_in_high_growth_enterprises", "young_high_growth_enterprises", "employees_in_young_high_growth_enterprises"}
HG_ACTIVITIES = ["B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "P", "Q", "R", "S95", "S96"]


def hg_entry(labels: Labels) -> dict:
    key = f"A.{'+'.join(HG_INDICATORS)}.{'+'.join(HG_ACTIVITIES)}.{'+'.join(EU_GEOS)}"
    document = eurostat_document("bd_hg", "high growth enterprises and related employment by NACE Rev. 2 activity", key)
    source = eurostat_rows(document.raw)
    rows: dict[str, Record] = {}
    for r in source:
        row_key = f"{r['geo']}|{r['nace_r2']}"
        record = rows.setdefault(row_key, {"geo_name": labels.geo[r["geo"]], "activity": labels.nace[r["nace_r2"]], **dict.fromkeys(HG_INDICATORS.values())})
        column = HG_INDICATORS[r["indic_sbs"]]
        record[column] = None if not r["OBS_VALUE"] else (int(float(r["OBS_VALUE"])) if column in HG_COUNTS else float(r["OBS_VALUE"]))
    rows = dict(sorted((k, v) for k, v in rows.items() if any(v[c] is not None for c in HG_INDICATORS.values())))
    flagged = [(f"{r['geo']}|{r['nace_r2']}", r["OBS_FLAG"]) for r in source if r["OBS_FLAG"] and r["OBS_VALUE"]]
    dims = ("indic_sbs", "nace_r2", "geo")

    def cell(geo: str, nace: str, indicator: str) -> dict[str, str]:
        return next(r for r in source if r["geo"] == geo and r["nace_r2"] == nace and r["indic_sbs"] == indicator and r["OBS_VALUE"])

    items = [
        eurostat_cite(document, cell("EU27_2020", "C", "ENT_HGRW_NR"), dims, "count"),
        eurostat_cite(document, cell("DE", "M", "ENT_HGRWR_PC"), dims, "percent"),
        eurostat_cite(document, cell("FR", "J", "ENT_HGRW_NR"), dims, "count"),
    ]
    definitions = "; ".join(f"{column}: {labels.indicators[code]}" for code, column in HG_INDICATORS.items())
    return rule_entry(
        f"eu-high-growth-enterprises-by-nace-section-{SBS_YEAR}",
        f"High-growth and young high-growth enterprises and their employees by NACE section, EU27 and ten member states, {SBS_YEAR} (Eurostat bd_hg)",
        "EU",
        (f"{SBS_YEAR}-01-01", f"{SBS_YEAR}-12-31"),
        ["business-demography", "high-growth", "gazelles", "nace", "eurostat", "by-country"],
        {"dataflow": "bd_hg", "key": key, "period": SBS_YEAR, "rows": rows},
        [
            lookup_vector(rows, "EU27_2020|C", "high_growth_enterprises"),
            lookup_vector(rows, "DE|M", "high_growth_share_of_enterprises_10_plus_percent"),
            lookup_vector(rows, "FR|J", "high_growth_enterprises"),
            {"input": "DE|B-S_X_O_S94", "expected": False, "origin": "derived", "note": "the business-economy total is left out; rows are NACE sections and divisions only"},
        ],
        items,
        [],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[EU27_2020|C,high_growth_enterprises]", "expected": rows["EU27_2020|C"]["high_growth_enterprises"], "tolerance": 0},
            {"statistic": "max[high_growth_share_of_enterprises_10_plus_percent]", "expected": max_of(rows, "high_growth_share_of_enterprises_10_plus_percent"), "tolerance": 0},
        ],
        f"High-growth enterprises measured in employment for {SBS_YEAR} from Eurostat dataflow bd_hg, one row per country and activity keyed geo|nace "
        "for the EU27 and DE, FR, IT, ES, NL, PL, SE, BE, AT and IE, over NACE sections B to R except O and divisions S95 and S96 (the "
        f"business-economy total is not included, so the table carries the industry split only). Column definitions from Eurostat's INDIC_SBS codelist: {definitions}. Shares relate to the population of active "
        "enterprises with at least 10 employees, so they cannot be read as shares of all enterprises. Use the rate to flag a fraction of synthetic "
        "10-plus-employee portfolio companies as high-growth." + flag_note(flagged, labels.flags) + " " + EUROSTAT_LICENSE_NOTE,
    )


LEGAL_FORMS = ["TOTAL", "ENT_LL", "ENT_PA", "ENT_SOLE"]
LF_INDICATORS = {
    "ENT_NR": "active_enterprises",
    "ENT_BRTH_NR": "enterprise_births",
    "ENT_DTH_NR": "enterprise_deaths",
    "ENT_BRTHR_PC": "birth_rate_percent",
    "ENT_DTHR_PC": "death_rate_percent",
    "EMP_NR": "persons_employed",
    "SAL_NR": "employees",
}


def legal_form_entry(labels: Labels) -> dict:
    key = f"A.{'+'.join(LF_INDICATORS)}.{'+'.join(LEGAL_FORMS)}.B-S_X_O_S94.{'+'.join(EU_GEOS)}"
    document = eurostat_document("bd_l_form", "business demography by legal form and NACE Rev. 2 activity", key)
    source = eurostat_rows(document.raw)
    rows: dict[str, Record] = {}
    for r in source:
        record = rows.setdefault(f"{r['geo']}|{r['leg_form']}", {"geo_name": labels.geo[r["geo"]], "legal_form": labels.legal_forms[r["leg_form"]], **dict.fromkeys(LF_INDICATORS.values())})
        column = LF_INDICATORS[r["indic_sbs"]]
        record[column] = None if not r["OBS_VALUE"] else (float(r["OBS_VALUE"]) if column.endswith("percent") else int(float(r["OBS_VALUE"])))
    for row_key, record in rows.items():
        total = rows.get(f"{row_key.split('|')[0]}|TOTAL", {})
        record["share_of_active_enterprises"] = ratio(record["active_enterprises"], total.get("active_enterprises"))
        record["share_of_persons_employed"] = ratio(record["persons_employed"], total.get("persons_employed"))
        record["persons_employed_per_enterprise"] = ratio(record["persons_employed"], record["active_enterprises"], 1, 3)
    rows = dict(sorted(rows.items()))
    flagged = [(f"{r['geo']}|{r['leg_form']}", r["OBS_FLAG"]) for r in source if r["OBS_FLAG"] and r["OBS_VALUE"]]
    dims = ("indic_sbs", "leg_form", "nace_r2", "geo")

    def cell(geo: str, form: str, indicator: str) -> dict[str, str]:
        return next(r for r in source if r["geo"] == geo and r["leg_form"] == form and r["indic_sbs"] == indicator and r["OBS_VALUE"])

    items = [
        eurostat_cite(document, cell("FR", "ENT_LL", "ENT_NR"), dims, "count"),
        eurostat_cite(document, cell("IT", "ENT_SOLE", "ENT_BRTHR_PC"), dims, "percent"),
        eurostat_cite(document, cell("NL", "ENT_PA", "ENT_NR"), dims, "count"),
    ]
    return rule_entry(
        f"eu-enterprise-demography-by-legal-form-{SBS_YEAR}",
        f"Active enterprises, births, deaths and employment by legal form, EU27 and ten member states, {SBS_YEAR} (Eurostat bd_l_form)",
        "EU",
        (f"{SBS_YEAR}-01-01", f"{SBS_YEAR}-12-31"),
        ["business-demography", "legal-form", "births", "deaths", "eurostat", "by-country"],
        {"dataflow": "bd_l_form", "key": key, "period": SBS_YEAR, "legal_forms": {f: labels.legal_forms[f] for f in LEGAL_FORMS}, "rows": rows},
        [
            lookup_vector(rows, "FR|ENT_LL", "active_enterprises"),
            lookup_vector(rows, "IT|ENT_SOLE", "birth_rate_percent"),
            lookup_vector(rows, "NL|ENT_PA", "active_enterprises"),
            lookup_vector(rows, "DE|ENT_LL", "share_of_active_enterprises", "derived", "active_enterprises / active_enterprises of DE|TOTAL"),
            {"input": "FR|ENT_COOP", "expected": False, "origin": "derived", "note": "only the three broad legal forms and the total are kept"},
        ],
        items,
        [
            {"parameter": "rows[*].share_of_active_enterprises", "value": "active_enterprises / active_enterprises of the country's TOTAL row", "method": "derived", "rationale": "Legal-form mix of the active enterprise population, for assigning a legal form to a synthetic company; share_of_persons_employed does the same for employment. The three forms need not add up to the total, which also covers other legal forms."},
            {"parameter": "rows[*].persons_employed_per_enterprise", "value": "persons_employed / active_enterprises", "method": "derived", "rationale": "Average size of an active enterprise of the legal form."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[FR|ENT_LL,active_enterprises]", "expected": rows["FR|ENT_LL"]["active_enterprises"], "tolerance": 0},
            {"statistic": "max[share_of_active_enterprises]", "expected": max_of(rows, "share_of_active_enterprises"), "tolerance": 0},
        ],
        f"Business demography by legal form for {SBS_YEAR} from Eurostat dataflow bd_l_form for the business economy aggregate B-S_X_O_S94, one row per "
        "country and legal form keyed geo|leg_form for the EU27 and DE, FR, IT, ES, NL, PL, SE, BE, AT and IE: "
        + ", ".join(f"{f} ({labels.legal_forms[f]})" for f in LEGAL_FORMS)
        + ". Published columns: active enterprises, enterprise births and deaths, the birth and death rates (births or deaths over active enterprises, "
        "in percent), persons employed and employees; derived columns give the legal form's share of active enterprises and persons employed and its "
        "average headcount." + flag_note(flagged, labels.flags) + " " + EUROSTAT_LICENSE_NOTE,
    )


SMC_SIZES = ["0-9", "10-19", "20-49", "50-249", "250-749", "GE750", "TOTAL"]
SMC_INDICATORS = {
    "ENT_NR": "enterprises",
    "EMP_NR": "persons_employed",
    "NETTUR_MEUR": "net_turnover_meur",
    "AV_MEUR": "value_added_meur",
    "NETTUR_EMP_TEUR": "net_turnover_per_person_employed_teur",
    "LABPRY_TEUR": "apparent_labour_productivity_teur",
}


def smc_entry(labels: Labels) -> dict:
    key = f"A.{'+'.join(SMC_SIZES)}.B-S_X_O_S94.{'+'.join(SMC_INDICATORS)}."
    document = eurostat_document("sbs_ovw_smc", "enterprises by extended size classes including small mid caps and NACE Rev. 2 activity", key)
    source = eurostat_rows(document.raw)
    rows: dict[str, Record] = {}
    for r in source:
        record = rows.setdefault(f"{r['geo']}|{r['size_emp']}", {"geo_name": labels.geo[r["geo"]], "size_class": labels.size[r["size_emp"]], **dict.fromkeys(SMC_INDICATORS.values())})
        column = SMC_INDICATORS[r["indic_sbs"]]
        record[column] = eurostat_value(r, column)
    for row_key, record in rows.items():
        total = rows.get(f"{row_key.split('|')[0]}|TOTAL", {})
        record["net_turnover_per_enterprise_teur"] = ratio(record["net_turnover_meur"], record["enterprises"], 1000, 3)
        record["enterprise_share_of_total"] = ratio(record["enterprises"], total.get("enterprises"))
        record["net_turnover_share_of_total"] = ratio(record["net_turnover_meur"], total.get("net_turnover_meur"))
    rows = dict(sorted((k, v) for k, v in rows.items() if any(v[c] is not None for c in SMC_INDICATORS.values())))
    geos = sorted({k.split("|")[0] for k in rows})
    flagged = [(f"{r['geo']}|{r['size_emp']}", r["OBS_FLAG"]) for r in source if r["OBS_FLAG"] and r["OBS_VALUE"]]
    dims = ("size_emp", "nace_r2", "indic_sbs", "geo")

    def cell(geo: str, size: str, indicator: str) -> dict[str, str]:
        return next(r for r in source if r["geo"] == geo and r["size_emp"] == size and r["indic_sbs"] == indicator and r["OBS_VALUE"])

    items = [
        eurostat_cite(document, cell("DE", "250-749", "ENT_NR"), dims, "count"),
        eurostat_cite(document, cell("ES", "250-749", "NETTUR_MEUR"), dims, "currency:EUR"),
        eurostat_cite(document, cell("PL", "GE750", "ENT_NR"), dims, "count"),
    ]
    return rule_entry(
        f"eu-enterprises-by-extended-size-class-including-small-mid-caps-{SBS_YEAR}",
        f"Enterprises, employment and turnover by extended size class including small mid-caps (250-749 persons employed), {SBS_YEAR} (Eurostat)",
        "EU",
        (f"{SBS_YEAR}-01-01", f"{SBS_YEAR}-12-31"),
        ["structural-business-statistics", "mid-market", "small-mid-caps", "turnover", "eurostat", "by-country", "revenue-per-employee"],
        {"dataflow": "sbs_ovw_smc", "key": key, "period": SBS_YEAR, "geos": geos, "size_classes": {s: labels.size[s] for s in SMC_SIZES}, "rows": rows},
        [
            lookup_vector(rows, "DE|250-749", "enterprises"),
            lookup_vector(rows, "ES|250-749", "net_turnover_meur"),
            lookup_vector(rows, "PL|GE750", "enterprises"),
            lookup_vector(rows, "DE|250-749", "net_turnover_per_enterprise_teur", "derived", "net_turnover_meur * 1000 / enterprises"),
            {"input": "IT|250-749", "expected": False, "origin": "derived", "note": "Italy publishes no extended large-enterprise classes in this flow"},
        ],
        items,
        [
            {"parameter": "rows[*].net_turnover_per_enterprise_teur", "value": "net_turnover_meur * 1000 / enterprises", "method": "derived", "rationale": "Average turnover per enterprise of the size class in thousand euro, the revenue anchor for a synthetic mid-cap."},
            {"parameter": "rows[*].enterprise_share_of_total", "value": "enterprises / enterprises of the country's TOTAL row", "method": "derived", "rationale": "Share of the country's business-economy enterprises in the size class; net_turnover_share_of_total does the same for turnover. The classes 0-9, 10-19, 20-49, 50-249, 250-749 and 750 or more partition the total, up to rounding, where all are published."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[DE|250-749,enterprises]", "expected": rows["DE|250-749"]["enterprises"], "tolerance": 0},
            {"statistic": "max[net_turnover_per_enterprise_teur]", "expected": max_of(rows, "net_turnover_per_enterprise_teur"), "tolerance": 0},
        ],
        f"Business economy (B-S_X_O_S94) statistics for {SBS_YEAR} by extended size class of persons employed from Eurostat dataflow sbs_ovw_smc, which "
        "splits the large-enterprise class into 250-749 and 750 or more persons employed to identify small mid-caps; one row per country and size class keyed geo|size_class. Eurostat publishes "
        f"this flow for {len(geos)} countries: {', '.join(geos)}, of which {', '.join(g for g in geos if g in EU_GEOS)} are among the ten member states "
        "covered elsewhere in the Almanac. Countries without a 250-749 row publish no small mid-cap split. Size classes: " + ", ".join(f"{s} ({labels.size[s]})" for s in SMC_SIZES) + ". Published columns: enterprises, persons employed, net "
        "turnover and value added in million euro, net turnover per person employed and apparent labour productivity in thousand euro; derived "
        "columns give turnover per enterprise and the class's share of enterprises and turnover." + flag_note(flagged, labels.flags) + " " + EUROSTAT_LICENSE_NOTE,
    )


def build_eurostat() -> list[dict]:
    labels = Labels.fetch()
    return [sbs_entry(geo, labels) for geo in EU_GEOS] + [hg_entry(labels), legal_form_entry(labels), smc_entry(labels)]


# --- OECD structural and demographic business statistics -------------------------------------------------------

OECD = "OECD"
OECD_SIZES = ["_T", "S1T9", "S10T19", "S20T49", "S10T49", "S50T249", "S_GE10", "S_GE250"]
OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_SDBSBSC_ISIC4@DF_SDBS_ISIC4,1.0/"
    f"A..ENTR+EMPN.BTNXK.{'+'.join(OECD_SIZES)}.?startPeriod=2020&endPeriod=2024&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
OECD_LICENSE_NOTE = (
    "The OECD terms and conditions page could not be fetched byte-stably, so the licence is recorded as unstated and the entry stays at "
    "license-review until a reviewer confirms the terms that apply to OECD data."
)


def build_oecd() -> list[dict]:
    document = Document.get(OECD, "OECD Data Explorer SDMX API, DF_SDBS_ISIC4 (structural business statistics by size class, ISIC Rev. 4), CSV with labels", OECD_URL, "unstated")
    source = list(csv.DictReader(io.StringIO(document.raw.decode("utf-8-sig"))))
    if {r["UNIT_MULT"] for r in source} != {"0"}:
        raise ValueError("unexpected unit multiplier in SDBS")
    totals = {(r["REF_AREA"], r["TIME_PERIOD"]) for r in source if r["SIZE_CLASS"] == "_T" and r["MEASURE"] == "ENTR" and r["OBS_VALUE"]}
    latest = {area: max(year for a, year in totals if a == area) for area, _ in totals}
    rows: dict[str, Record] = {}
    for r in source:
        area = r["REF_AREA"]
        if area not in latest or r["TIME_PERIOD"] != latest[area] or not r["OBS_VALUE"]:
            continue
        record = rows.setdefault(f"{area}|{r['SIZE_CLASS']}", {"country": r["Reference area"], "year": int(r["TIME_PERIOD"]), "size_class": r["Size class"], "enterprises": None, "persons_employed": None})
        record["enterprises" if r["MEASURE"] == "ENTR" else "persons_employed"] = int(float(r["OBS_VALUE"]))
    for row_key, record in rows.items():
        total = rows[f"{row_key.split('|')[0]}|_T"]
        record["enterprise_share_of_total"] = ratio(record["enterprises"], total["enterprises"])
        record["employment_share_of_total"] = ratio(record["persons_employed"], total["persons_employed"])
        record["persons_employed_per_enterprise"] = ratio(record["persons_employed"], record["enterprises"], 1, 3)
    rows = dict(sorted(rows.items()))
    countries = sorted({k.split("|")[0] for k in rows})
    years = sorted({r["year"] for r in rows.values()})

    def cell(area: str, measure: str, size: str) -> dict[str, str]:
        return next(r for r in source if r["REF_AREA"] == area and r["MEASURE"] == measure and r["SIZE_CLASS"] == size and r["TIME_PERIOD"] == latest[area] and r["OBS_VALUE"])

    def cite(r: dict[str, str]) -> dict:
        locator = f"REF_AREA={r['REF_AREA']}, MEASURE={r['MEASURE']}, ACTIVITY={r['ACTIVITY']}, SIZE_CLASS={r['SIZE_CLASS']}, TIME_PERIOD={r['TIME_PERIOD']}, OBS_VALUE"
        snippet = f"{r['REF_AREA']},{r['Reference area']},{r['MEASURE']},{r['Measure']},{r['ACTIVITY']}"
        return document.cite(locator, r["OBS_VALUE"], "count", snippet)

    items = [cite(cell("CAN", "ENTR", "S50T249")), cite(cell("JPN", "EMPN", "S_GE250")), cite(cell("NOR", "ENTR", "_T"))]
    stale = sorted(f"{c} ({latest[c]})" for c in countries if latest[c] != str(years[-1]))
    return [rule_entry(
        f"global-enterprises-and-employment-by-size-class-oecd-sdbs-{years[0]}-{years[-1]}",
        f"Enterprises and persons employed by employment size class, business economy, {len(countries)} economies, latest year {years[0]}-{years[-1]} (OECD SDBS)",
        "global",
        (f"{years[0]}-01-01", f"{years[-1]}-12-31"),
        ["oecd", "sdbs", "structural-business-statistics", "by-country"],
        {"dataflow": "OECD.SDD.TPS,DSD_SDBSBSC_ISIC4@DF_SDBS_ISIC4,1.0", "activity": "BTNXK", "rows": rows},
        [
            lookup_vector(rows, "CAN|S50T249", "enterprises"),
            lookup_vector(rows, "JPN|S_GE250", "persons_employed"),
            lookup_vector(rows, "NOR|_T", "enterprises"),
            lookup_vector(rows, "CAN|S50T249", "enterprise_share_of_total", "derived", "enterprises / enterprises of CAN|_T"),
            {"input": "USA|_T", "expected": False, "origin": "derived", "note": "the United States publishes no SDBS size-class data in this flow"},
        ],
        items,
        [
            {"parameter": "rows", "value": "latest year per economy", "method": "derived", "rationale": "For each economy the query window 2020-2024 is narrowed to the latest year in which the total enterprise count is published; the row's year column says which year that is."},
            {"parameter": "rows[*].enterprise_share_of_total", "value": "enterprises / enterprises of the economy's _T row", "method": "derived", "rationale": "Share of the economy's enterprises in the size class; employment_share_of_total does the same for persons employed. Classes overlap (S10T49 contains S10T19 and S20T49; S_GE10 contains every class from 10 up), so shares of overlapping classes must not be added."},
            {"parameter": "rows[*].persons_employed_per_enterprise", "value": "persons_employed / enterprises", "method": "derived", "rationale": "Average headcount of an enterprise in the size class."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[NOR|_T,enterprises]", "expected": rows["NOR|_T"]["enterprises"], "tolerance": 0},
            {"statistic": "max[persons_employed_per_enterprise]", "expected": max_of(rows, "persons_employed_per_enterprise"), "tolerance": 0},
        ],
        "Number of enterprises and persons employed by employment size class for the business economy except financial and insurance activities "
        "(ISIC Rev. 4 activity BTNXK) from the OECD Structural and Demographic Business Statistics dataflow DF_SDBS_ISIC4, one row per economy and "
        f"size class keyed ISO3|size_class with the latest published year for each of {len(countries)} economies ({', '.join(countries)}). Size "
        "classes kept where published: _T (total), S1T9, S10T19, S20T49, S10T49, S50T249, S_GE10 and S_GE250, each with the OECD English label; "
        "not every economy publishes every class, so some carry only the coarser ones. Economies whose latest year is earlier than the newest in the table: " + (", ".join(stale) or "none") + ". "
        + OECD_LICENSE_NOTE,
        status="license-review",
    )]


# --- World Bank Enterprise Surveys -----------------------------------------------------------------------------

WORLD_BANK = "World Bank"
WB_API = "https://api.worldbank.org/v2"
WB_COUNTRIES_URL = f"{WB_API}/country?format=json&per_page=400"
WB_LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
WB_YEARS = "2006:2025"


@dataclass(frozen=True)
class SurveyTable:
    """One lookup of Enterprise Surveys indicators by economy, every row anchored on one survey year."""

    entry_id: str
    title: str
    source: int
    source_name: str
    indicators: dict[str, tuple[str, str]]
    tags: list[str]
    description: str

    @property
    def anchor(self) -> str:
        return next(iter(self.indicators))

    def url(self, indicator: str) -> str:
        return f"{WB_API}/country/all/indicator/{indicator}?source={self.source}&date={WB_YEARS}&format=json&per_page=20000"


SURVEY_TABLES = [
    SurveyTable(
        "global-enterprise-survey-finance-trade-and-ownership-by-economy",
        "World Bank Enterprise Surveys: firm finance, exporting and ownership indicators by economy, latest survey {first}-{last}",
        2,
        "World Development Indicators",
        {
            "IC.FRM.BNKL.ZS": ("bank_loan_or_credit_line_percent", "percent"),
            "IC.FRM.BNKS.ZS": ("banks_finance_investment_percent", "percent"),
            "IC.FRM.BKWC.ZS": ("banks_finance_working_capital_percent", "percent"),
            "IC.FRM.CRDC.FL.ZS": ("fully_credit_constrained_percent", "percent"),
            "IC.FRM.CRDC.PT.ZS": ("partially_credit_constrained_percent", "percent"),
            "IC.FRM.EXS.ZS": ("exporting_directly_10_percent_of_sales_percent", "percent"),
            "IC.FRM.FEMO.ZS": ("female_participation_in_ownership_percent", "percent"),
            "IC.FRM.FEMM.ZS": ("female_top_manager_percent", "percent"),
            "IC.FRM.FO.ZS": ("foreign_ownership_10_percent_percent", "percent"),
        },
        ["access-to-finance", "credit", "exporters", "ownership"],
        "Columns are percentages of surveyed firms: with a bank loan or line of credit, using banks to finance investment, using banks to finance "
        "working capital, fully and partially credit constrained, exporting directly at least 10 percent of sales, with female participation in "
        "ownership, with a female top manager, and with at least 10 percent foreign ownership.",
    ),
    SurveyTable(
        "global-enterprise-survey-firm-age-collateral-growth-and-experience-by-economy",
        "World Bank Enterprise Surveys: firm age, collateral, sales growth and manager experience by economy, surveys {first}-{last}",
        13,
        "Enterprise Surveys",
        {
            "IC.FRM.FCHAR.CAR1": ("establishment_age_years", "decimal"),
            "IC.FRM.FIN.FIN11": ("loans_requiring_collateral_percent", "percent"),
            "IC.FRM.FIN.FIN10": ("collateral_value_percent_of_loan", "percent"),
            "IC.FRM.SLS.GROW.PEFT1": ("real_annual_sales_growth_percent", "percent"),
            "IC.FRM.PROD.GROW.PEFT3": ("real_annual_labor_productivity_growth_percent", "percent"),
            "IC.FRM.WRKF.WK8": ("top_manager_experience_years", "decimal"),
        },
        ["firm-age", "collateral", "sales-growth", "productivity", "management"],
        "Columns: average age of the establishment in years, proportion of loans requiring collateral, value of collateral needed for a loan as a "
        "percentage of the loan amount, real annual sales growth, real annual labour productivity growth (both in percent), and the top manager's "
        "years of experience in the firm's sector. This World Bank API source was last updated in 2022, so its latest surveys are older than those "
        "of the finance, trade and ownership table, and the two tables' survey years differ for many economies.",
    ),
]


def survey_entry(table: SurveyTable, countries_doc: Document, license_doc: Document, economies: Mapping[str, Mapping[str, Any]]) -> dict:
    documents: dict[str, Document] = {}
    values: dict[str, dict[str, dict[str, float]]] = {}
    names: dict[str, str] = {}
    for indicator in table.indicators:
        document = Document.get(WORLD_BANK, f"World Bank API, source {table.source}, {indicator}, {WB_YEARS} (JSON)", table.url(indicator), CC_BY)
        documents[indicator] = document
        meta, data = json.loads(document.raw)
        if meta["total"] > meta["per_page"]:
            raise ValueError(f"{indicator} needs more than one page")
        for r in data:
            code = r["countryiso3code"]
            if r["value"] is None or code not in economies:
                continue
            values.setdefault(indicator, {}).setdefault(code, {})[r["date"]] = r["value"]
            names[code] = r["country"]["value"]
    rows: dict[str, Record] = {}
    for code, by_year in sorted(values[table.anchor].items()):
        year = max(by_year)
        record: Record = {"name": names[code], "survey_year": int(year), "income_level": economies[code]["incomeLevel"]["value"], "region": economies[code]["region"]["value"]}
        for indicator, (column, _) in table.indicators.items():
            record[column] = values.get(indicator, {}).get(code, {}).get(year)
        rows[code] = record
    sample = "IND" if "IND" in rows else next(iter(rows))
    anchor_column = table.indicators[table.anchor][0]
    lastupdated = json.loads(documents[table.anchor].raw)[0]["lastupdated"]
    items = [
        documents[indicator].cite(f"rows[countryiso3code={sample}, date={rows[sample]['survey_year']}].value", rows[sample][column], unit, f'"countryiso3code":"{sample}"')
        for indicator, (column, unit) in table.indicators.items() if rows[sample][column] is not None
    ]
    items.append(documents[table.anchor].cite("lastupdated", lastupdated, "date", '"lastupdated":'))
    items.append(countries_doc.cite("country[id=IND].region.value", "South Asia", "text", '"id":"IND"'))
    items.append(license_doc.cite("Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", role="supporting"))
    years = sorted({r["survey_year"] for r in rows.values()})
    recent = sum(1 for r in rows.values() if r["survey_year"] >= 2019)
    top = max(rows, key=lambda k: rows[k][anchor_column])
    return rule_entry(
        table.entry_id,
        table.title.format(first=years[0], last=years[-1]),
        "global",
        (f"{years[0]}-01-01", f"{years[-1]}-12-31"),
        ["enterprise-surveys", "world-bank", "by-country"] + table.tags,
        {"source": f"World Bank API source {table.source} ({table.source_name})", "years": WB_YEARS, "anchor_indicator": table.anchor, "indicators": {k: c for k, (c, _) in table.indicators.items()}, "rows": rows},
        [
            lookup_vector(rows, sample, anchor_column),
            lookup_vector(rows, sample, "survey_year"),
            lookup_vector(rows, top, anchor_column, note=f"largest {anchor_column}"),
            {"input": "WLD", "expected": False, "origin": "derived", "note": "aggregates are excluded"},
        ],
        items,
        [
            {"parameter": "rows[*].survey_year", "value": f"latest year in {WB_YEARS} with a published {table.anchor} value", "method": "derived", "rationale": "Each economy's row is anchored on its most recent survey year for the first indicator; every other column is taken from the same year and is null when that survey does not publish it, so all values in a row come from one survey."},
            {"parameter": "rows", "value": "economies only", "method": "derived", "rationale": "Rows whose region is 'Aggregates' in the World Bank country API are dropped."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"max[{anchor_column}]", "expected": max_of(rows, anchor_column), "tolerance": 0},
            {"statistic": "max[survey_year]", "expected": years[-1], "tolerance": 0},
        ],
        f"Firm-level survey indicators from the World Bank Enterprise Surveys as served by the World Bank API source {table.source} ({table.source_name}; "
        f"data last updated {lastupdated}), one row per economy keyed by ISO 3166-1 alpha-3 code with the year of its latest survey for {table.anchor}, "
        f"its World Bank income level and region. {table.description} Indicator codes: {', '.join(table.indicators)}. {recent} of {len(rows)} "
        "economies have a survey from 2019 or later; older rows describe their survey year, not today. The values describe the firms each survey "
        "covers, not all businesses in the economy. The World Bank licenses its datasets under CC BY 4.0.",
    )


def build_wbes() -> list[dict]:
    countries_doc = Document.get(WORLD_BANK, "World Bank country API (region classification used to exclude aggregates)", WB_COUNTRIES_URL, CC_BY)
    license_doc = Document.get(WORLD_BANK, "World Bank Data Catalog public licenses", WB_LICENSE_URL, CC_BY)
    economies = {c["id"]: c for c in json.loads(countries_doc.raw)[1] if c["region"]["value"] != "Aggregates"}
    return [survey_entry(table, countries_doc, license_doc, economies) for table in SURVEY_TABLES]


# --- ABS Counts of Australian Businesses ----------------------------------------------------------------------

ABS = "Australian Bureau of Statistics"
ABS_URL = "https://www.abs.gov.au/statistics/economy/business-indicators/counts-australian-businesses-including-entries-and-exits/jul2022-jun2026/8165DC01.xlsx"
ABS_TITLE = "8165.0 Counts of Australian Businesses, including Entries and Exits, June 2022 - June 2026, Data cube 1 (XLSX)"
ABS_YEAR = "2025-26"
ABS_NOTES = (
    "Source: ABS release 8165.0, data cube 1, released 18 August 2026; flow columns come from the 2025-26 block of the flow table. "
    "Entries split into births and other entries and exits into cancellations and other exits as the "
    "ABS publishes them. Survival columns follow the businesses operating in June 2022 to June 2023, 2024, 2025 and 2026. The ABS website "
    "copyright page states that, unless otherwise noted, its content is licensed under Creative Commons Attribution 4.0 International; that page "
    "renders with varying bytes between fetches, so it is referenced rather than hashed and the entry is held at license-review until the licence "
    "of this file is confirmed."
)
FLOW_COLUMNS = ["operating_at_start", "entries_births", "entries_other", "entries_total", "exits_cancellations", "exits_other", "exits_total"]
SURVIVAL_COLUMNS = ["operating_june_2022", "survived_to_june_2023", "survival_rate_2023_percent", "survived_to_june_2024", "survival_rate_2024_percent", "survived_to_june_2025", "survival_rate_2025_percent", "survived_to_june_2026", "survival_rate_2026_percent"]


def abs_key(label: str) -> str:
    return collapse(label.replace("–", "-"))


def abs_year_block(sheet: Sheet, year: str) -> dict[str, list[str | None]]:
    """The rows of one financial-year block of an ABS flow table, keyed by their normalised label."""
    rows = sheet.rows()
    start = next(i for i, row in enumerate(rows) if row[0] and row[0].strip() == year)
    block: dict[str, list[str | None]] = {}
    for row in rows[start + 1:]:
        label = row[0]
        if label is None or not label.strip():
            continue
        if re.match(r"^\d{4}-\d{2}$", label.strip()) or label.startswith("©"):
            break
        if row[1] is not None:
            block[abs_key(label)] = row
    return block


def abs_survival(sheet: Sheet) -> dict[str, list[str | None]]:
    return {abs_key(row[0]): row for row in sheet.rows()[5:] if row[0] and row[1] is not None and not row[0].startswith("©")}


def abs_header(sheet: Sheet) -> list[str]:
    return [collapse(c or "") for c in sheet.rows()[3]]


def abs_entry(document: Document, sheets: dict[str, Sheet], flow_table: str, survival_table: str, entry_id: str, title: str, key_name: str, tags: list[str], vector_keys: tuple[str, str], note: str) -> dict:
    flow, survival = sheets[flow_table], sheets[survival_table]
    header = abs_header(flow)
    expected = ["Operating at start of financial year", "Entries - Births", "Entries - Other", "Entries - Total", "Exits - Cancellations", "Exits - Other", "Exits - Total"]
    if header[1:8] != expected:
        raise ValueError(f"unexpected {flow_table} header {header}")
    end_column = header.index("Operating at end of financial year")
    survival_header = abs_header(survival)
    if survival_header[1] != "Operating in June 2022" or survival_header[8] != "Survived to June 2026":
        raise ValueError(f"unexpected {survival_table} header {survival_header}")
    block = abs_year_block(flow, ABS_YEAR)
    survivors = abs_survival(survival)
    rows: dict[str, Record] = {}
    for key, row in block.items():
        record: Record = {"label": collapse(row[0])}
        record.update({column: number(cell) for column, cell in zip(FLOW_COLUMNS, row[1:8])})
        record["operating_at_end"] = number(row[end_column])
        record["entry_rate_percent"] = ratio(record["entries_total"], record["operating_at_start"], 100, 2)
        record["exit_rate_percent"] = ratio(record["exits_total"], record["operating_at_start"], 100, 2)
        record["birth_rate_percent"] = ratio(record["entries_births"], record["operating_at_start"], 100, 2)
        survival_cells = survivors[key][1:10] if key in survivors else [None] * len(SURVIVAL_COLUMNS)
        record.update({column: number(cell) for column, cell in zip(SURVIVAL_COLUMNS, survival_cells)})
        rows[key] = record
    total_key = next(k for k in rows if k.startswith(("Total", "All Industries")) and not k.startswith("Total employing"))
    for record in rows.values():
        record["share_of_businesses_at_end"] = ratio(record["operating_at_end"], rows[total_key]["operating_at_end"])
    first, second = vector_keys
    flow_title = collapse(flow.rows()[1][0])
    survival_title = collapse(survival.rows()[1][0])
    items = [
        document.cite(f"{flow_table}, block {ABS_YEAR}, row {block[first][0]}, column Operating at end of financial year", int(block[first][end_column]), "count", document.leading(flow_title)),
        document.cite(f"{flow_table}, block {ABS_YEAR}, row {block[second][0]}, column Entries - Births", int(block[second][2]), "count", block[second][0]),
        document.cite(f"{survival_table}, row {survivors[first][0]}, column Survived to June 2026", int(survivors[first][8]), "count", document.leading(survival_title)),
    ]
    return rule_entry(
        entry_id,
        title,
        "AU",
        ("2025-07-01", "2026-06-30"),
        ["abs", "business-register", "entries", "exits", "survival"] + tags,
        {"source_tables": [flow_table, survival_table], "financial_year": ABS_YEAR, "key": key_name, "rows": rows},
        [
            lookup_vector(rows, first, "operating_at_end"),
            lookup_vector(rows, second, "entries_births"),
            lookup_vector(rows, first, "survived_to_june_2026"),
            lookup_vector(rows, second, "exit_rate_percent", "derived", "exits_total / operating_at_start * 100"),
            {"input": "Unknown size", "expected": False, "origin": "derived", "note": "not a published row"},
        ],
        items,
        [
            {"parameter": "rows[*].entry_rate_percent", "value": "entries_total / operating_at_start * 100", "method": "derived", "rationale": "Entries during 2025-26 relative to businesses operating at its start; exit_rate_percent and birth_rate_percent do the same for total exits and for births."},
            {"parameter": "rows[*].share_of_businesses_at_end", "value": f"operating_at_end / operating_at_end of {total_key}", "method": "derived", "rationale": "Share of all businesses operating at the end of the year, for sampling a category."},
            {"parameter": "valid_from, valid_to", "value": "2025-07-01 to 2026-06-30", "method": "assumed", "rationale": "The 2025-26 financial year is taken as July 2025 to June 2026, consistent with the June reference points of the cube's title and survival tables."},
        ],
        [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{total_key},operating_at_end]", "expected": rows[total_key]["operating_at_end"], "tolerance": 0},
            {"statistic": "max[exit_rate_percent]", "expected": max_of(rows, "exit_rate_percent"), "tolerance": 0},
        ],
        note + " " + ABS_NOTES,
        status="license-review",
    )


def build_abs() -> list[dict]:
    document = Document.get(ABS, ABS_TITLE, ABS_URL, CC_BY)
    sheets = read_workbook(document.raw)
    return [
        abs_entry(
            document, sheets, "Table 13", "Table 15",
            "au-businesses-by-employment-size-entries-exits-and-survival-2025-26",
            "Australian businesses by employment size range: counts, entries, exits and four-year survival, 2025-26 (ABS 8165.0)",
            "employment size range", ["employment-size"], ("1-4", "20-199"),
            "Counts of Australian businesses for 2025-26 by employment size range (non-employing, 1-4, 5-19, 20-199 and 200 or more employees, plus "
            "the employing and grand totals) from Tables 13 and 15 of data cube 1, keyed by the published range with en dashes written as hyphens. "
            "Each row carries businesses operating at the start and end of the year, entries and exits, derived entry, birth and exit rates, the "
            "category's share of all businesses, and survival of the June 2022 population to June 2026. Size ranges are by employment, not turnover; "
            "this release publishes no turnover size ranges.",
        ),
        abs_entry(
            document, sheets, "Table 1", "Table 2",
            "au-businesses-by-anzsic-division-entries-exits-and-survival-2025-26",
            "Australian businesses by ANZSIC division: counts, entries, exits and four-year survival, 2025-26 (ABS 8165.0)",
            "ANZSIC division name", ["anzsic", "industry"], ("Construction", "Retail Trade"),
            "Counts of Australian businesses for 2025-26 by ANZSIC 2006 industry division (plus Currently Unknown and All Industries) from Tables 1 "
            "and 2 of data cube 1, keyed by division name. Each row carries businesses operating at the start and end of the year, entries and exits, "
            "derived entry, birth and exit rates, the division's share of all businesses, and survival of the June 2022 population to June 2026.",
        ),
    ]


# --- driver -----------------------------------------------------------------------------------------------------

GROUPS: dict[str, Callable[[], list[dict]]] = {"bpe": build_bpe, "ons": build_ons, "eurostat": build_eurostat, "oecd": build_oecd, "wbes": build_wbes, "abs": build_abs}


def main(argv: list[str]) -> int:
    selected = argv or list(GROUPS)
    unknown = [name for name in selected if name not in GROUPS]
    if unknown:
        raise SystemExit(f"unknown group(s): {', '.join(unknown)}; choose from {', '.join(GROUPS)}")
    for name in selected:
        for entry in GROUPS[name]():
            write(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

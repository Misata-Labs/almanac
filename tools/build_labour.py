"""Regenerate the labour-market value pools behind synthetic HR, payroll and workforce datasets.

Sources, all fetched live and cited by hash:

* ONS: the SOC 2020 occupation code list and the 2025 sickness-absence workbook (OGL-UK-3.0).
* OECD SDMX CSV: wages, minimum wages, job tenure, temporary and part-time work, unemployment
  duration, employment protection, retirement ages, tax wedge, participation and working hours.
* ILOSTAT CSV: monthly earnings and employment by ISCO-08 occupation, informal employment, hours.
* Eurostat SDMX CSV: job vacancy rate by NACE section, temporary and part-time shares, labour
  market transitions and the statutory minimum wage history.
* Gesetze im Internet XML: the German social insurance contribution rates fixed in statute.
* OPM PDF salary tables: the 2026 General Schedule base table and four locality tables.

Run from the repository root:

    uv run python tools/build_labour.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write
from build_eurostat_extended import LICENSE_NOTE as EUROSTAT_LICENSE_NOTE
from build_eurostat_extended import codelist, data_url, dataflow_title

from almanac.fetch import Resource

ONS = "Office for National Statistics"
OGL = "OGL-UK-3.0"
OECD = "Organisation for Economic Co-operation and Development"
ILO = "International Labour Organization (ILOSTAT)"
EUROSTAT = "Eurostat"
CC_BY = "CC-BY-4.0"
BMJ = "Bundesministerium der Justiz (Gesetze im Internet)"
OPM = "U.S. Office of Personnel Management"
UNSTATED = "unstated"

OECD_API = "https://sdmx.oecd.org/public/rest/data"
ILO_API = "https://rplumber.ilo.org/data/indicator/"
OPM_TABLES = "https://www.opm.gov/policy-data-oversight/pay-leave/salaries-wages/salary-tables/pdf/2026"
GII = "https://www.gesetze-im-internet.de"
ONS_FILE = "https://www.ons.gov.uk/file?uri="
SOC_URL = ONS_FILE + "/methodology/classificationsandstandards/standardoccupationalclassificationsoc/soc2020/soc2020volume1structureanddescriptionsofunitgroups/soc2020volume1structureanddescriptionofunitgroupsexcel20260827.xlsx"
SICKNESS_URL = ONS_FILE + "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/datasets/sicknessabsenceinthelabourmarket/2025/sicknessabsence2025.xlsx"

OECD_LICENSE_NOTE = (
    "The OECD terms and conditions page could not be fetched byte-stably in this session, so the licence is recorded as unstated "
    "and the entry stays at license-review until a reviewer confirms the terms that apply to OECD data."
)
ILO_LICENSE_NOTE = (
    "The ILOSTAT terms-of-use page could not be fetched byte-stably in this session, so the licence is recorded as unstated and "
    "the entry stays at license-review until a reviewer confirms the terms that apply to ILOSTAT data."
)
HR_USE_CASES = ["payroll-demo", "hr-demo", "workforce-planning-demo", "synthetic-employees"]
MAX_SNIPPET_WORDS = 24


# ---------------------------------------------------------------- shared helpers


def collapse(text: str) -> str:
    return " ".join(text.split())


class Source:
    """A fetched resource seen the way the verifier sees it, so snippets are checked before they are written."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.raw = fetch(url)
        self.text = collapse(Resource(url=url, content=self.raw, content_type="").text)

    def contains(self, needle: str) -> bool:
        return collapse(needle) in self.text

    def cite(self, publisher: str, title: str, locator: str, value: Any, unit: str, snippet: str, license_id: str, role: str = "primary") -> dict:
        for needle, what in ((snippet, "snippet"), (str(value), "value")):
            if not self.contains(needle):
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet exceeds {MAX_SNIPPET_WORDS} words: {snippet!r}")
        return evidence(publisher, title, self.url, locator, value, unit, snippet, license_id, self.raw, role)


def shorten(segment: str) -> str:
    """Trim a CSV segment from the left, at comma boundaries, until it fits the snippet word limit."""
    while len(segment.split()) > MAX_SNIPPET_WORDS:
        segment = segment[segment.index(",") + 1 :]
    return segment


@dataclass(frozen=True)
class CsvRow:
    """One parsed CSV row together with the raw line it came from, so a snippet can be cut from the bytes."""

    fields: dict[str, str]
    line: str

    def __getitem__(self, key: str) -> str:
        return self.fields[key]

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)

    def snippet(self, start_field: str, value_field: str = "OBS_VALUE") -> str:
        """The raw line from the first occurrence of ``start_field``'s value to the end of ``value_field``'s value."""
        value = self.fields[value_field]
        start = self.line.index(self.fields[start_field])
        end = self.line.index(value, start) + len(value)
        return shorten(self.line[start:end])


def csv_rows(raw: bytes) -> list[CsvRow]:
    lines = raw.decode("utf-8-sig").splitlines()
    header = next(csv.reader([lines[0]]))
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = next(csv.reader([line]))
        rows.append(CsvRow(dict(zip(header, values)), line))
    return rows


def numeric(text: str) -> float | int:
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def iso3_only(code: str) -> bool:
    """Keep national economies and drop OECD and EU aggregates such as OECD, EU27 or G7."""
    return len(code) == 3 and code.isalpha()


def lookup_entry(entry_id: str, title: str, domain: str, region: str, rows: dict[str, dict], parameters: dict, vectors: list[dict], items: list[dict], tests: list[dict], tags: list[str], use_cases: list[str], notes: str, valid: tuple[str, str | None], status: str = "verified", tier: str = "A", assumed: list[dict] | None = None) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": tier,
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": "almanac.rules.lookup_table", "parameters": {**parameters, "rows": rows}, "vectors": vectors},
        "evidence": items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, {"statistic": "count", "expected": len(rows), "tolerance": 0}, *tests],
        "notes": notes,
    }


def lookup_vectors(rows: dict[str, dict], column: str, keys: Iterable[str]) -> list[dict]:
    vectors = [{"input": {"key": k, "column": column}, "expected": rows[k][column], "origin": "source"} for k in keys if k in rows and rows[k].get(column) is not None]
    return vectors + [{"input": "XX", "expected": False, "origin": "derived"}]


def column_tests(rows: dict[str, dict], column: str, key: str) -> list[dict]:
    values = [r[column] for r in rows.values() if r.get(column) is not None]
    argument = f'"{key}"' if re.search(r"[,\[\]]", key) else key
    return [
        {"statistic": f"value[{argument},{column}]", "expected": rows[key][column], "tolerance": 1e-9},
        {"statistic": f"max[{column}]", "expected": max(values), "tolerance": 1e-9},
    ]


def conditional_entry(entry_id: str, title: str, domain: str, region: str, variable: str, distributions: dict[str, dict], items: list[dict], assumed: list[dict], tests: list[dict], tags: list[str], use_cases: list[str], notes: str, period: tuple[str, str], status: str = "verified") -> dict:
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
        "spec": {"variable": variable, "unit": "ratio", "given": "country", "distributions": distributions},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def shares_of(counts: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, 6) for k, v in counts.items()}


# ---------------------------------------------------------------- ONS workbooks


class Workbook:
    """An ONS XLSX read through openpyxl, with the sheet XML at hand so cell citations quote the stored markup."""

    def __init__(self, source: Source) -> None:
        self.source = source
        self.book = openpyxl.load_workbook(io.BytesIO(source.raw), read_only=True, data_only=True)
        archive = zipfile.ZipFile(io.BytesIO(source.raw))
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        rels = archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        targets = dict(re.findall(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels)) | {b: a for a, b in re.findall(r'<Relationship[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels)}
        self.sheet_xml: dict[str, str] = {}
        for name, rel_id in re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', workbook_xml):
            target = targets[rel_id].lstrip("/")
            member = target if target.startswith("xl/") else f"xl/{target}"
            self.sheet_xml[name.replace("&amp;", "&")] = archive.read(member).decode("utf-8")
        self.shared = archive.read("xl/sharedStrings.xml").decode("utf-8")

    def rows(self, sheet: str) -> list[tuple]:
        return [tuple(c for c in row) for row in self.book[sheet].iter_rows()]

    def cell_markup(self, sheet: str, coordinate: str) -> str:
        match = re.search(rf'<c r="{coordinate}"[^>]*>(?:<f>[^<]*</f>)?<v>[^<]*</v></c>', self.sheet_xml[sheet])
        if match is None:
            raise ValueError(f"{sheet}!{coordinate} has no stored value")
        return match.group(0)

    def cite_cell(self, title: str, sheet: str, cell, description: str, unit: str = "percent") -> dict:
        value = cell.value
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return self.source.cite(ONS, title, f"{sheet}!{cell.coordinate} ({description})", value, unit, self.cell_markup(sheet, cell.coordinate), OGL)


def header_index(rows: list[tuple], first: str) -> int:
    return next(i for i, row in enumerate(rows) if isinstance(row[0].value, str) and row[0].value.startswith(first))


def clean_label(text: str) -> str:
    return re.sub(r"\s*\[note [0-9, ]+\]", "", text).strip()


def year_row(rows: list[tuple], year: int) -> tuple:
    return next(row for row in rows if row[0].value in (year, str(year)))


def column_labels(header: tuple, prefix: str) -> list[str]:
    """Column labels such as 'aged 16 to 24' from headers like 'Sickness absence rate\\naged 16 to 24\\n(%)'."""
    labels = []
    for cell in header[1:]:
        if cell.value is None:
            break
        label = collapse(str(cell.value).replace(prefix, "").replace("(%)", ""))
        labels.append(clean_label(label))
    return labels


def soc_2020_code_list(source: Source) -> dict:
    book = Workbook(source)
    sets: dict[str, dict[str, str]] = {"major_groups": {}, "sub_major_groups": {}, "minor_groups": {}, "unit_groups": {}}
    level_of = {1: "major_groups", 2: "sub_major_groups", 3: "minor_groups", 4: "unit_groups"}
    for row in book.rows("SOC2020 descriptions")[1:]:
        codes = [row[i].value for i in range(1, 5)]
        code = next((str(c) for c in codes if c not in (None, "<blank>")), None)
        if code is None or row[5].value in (None, "<blank>"):
            continue
        sets[level_of[len(code)]][code] = collapse(str(row[5].value))
    if len(sets["unit_groups"]) < 400:
        raise ValueError("SOC 2020 unit groups not read")
    title = "SOC 2020 Volume 1: structure and descriptions of unit groups (XLSX, SOC2020 descriptions sheet)"
    items = [
        book.source.cite(ONS, title, "SOC2020 descriptions, unit group 1111 title", "Chief executives and senior officials", "text", "<t>Chief executives and senior officials</t>", OGL),
        book.source.cite(ONS, title, "SOC2020 descriptions, major group 9 title", sets["major_groups"]["9"], "text", f"<t>{sets['major_groups']['9']}</t>", OGL),
        book.source.cite(ONS, title, "SOC2020 descriptions, header row", "SOC2020 Unit Group", "text", "<t>SOC2020 Unit Group</t>", OGL, role="supporting"),
    ]
    first_unit = min(sets["unit_groups"])
    return {
        "id": "gb-soc-2020-occupation-code-list",
        "title": "SOC 2020 occupation classification: major, sub-major, minor and unit groups with titles (ONS)",
        "kind": "rule",
        "domain": "employment",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "valid_from": "2020-01-01",
        "valid_to": None,
        "tags": ["occupations", "soc-2020", "code-list", "ons", "hr"],
        "use_cases": HR_USE_CASES + ["person-generation", "hr-analytics"],
        "spec": {
            "implementation": "almanac.rules.enumeration",
            "parameters": {"classification": "SOC 2020", "sets": sets},
            "vectors": [
                {"input": {"value": "1111", "set": "unit_groups"}, "expected": True, "origin": "source"},
                {"input": {"value": first_unit, "set": "unit_groups"}, "expected": True, "origin": "source"},
                {"input": {"value": "9", "set": "major_groups"}, "expected": True, "origin": "source"},
                {"input": {"value": "0000", "set": "unit_groups"}, "expected": False, "origin": "derived"},
            ],
        },
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count[unit_groups]", "expected": len(sets["unit_groups"]), "tolerance": 0},
            {"statistic": "count[major_groups]", "expected": len(sets["major_groups"]), "tolerance": 0},
            {"statistic": "count[minor_groups]", "expected": len(sets["minor_groups"]), "tolerance": 0},
        ],
        "notes": (
            "The four levels of the Standard Occupational Classification 2020 read from the ONS Volume 1 workbook (SOC2020 descriptions sheet): "
            f"{len(sets['major_groups'])} major groups (one digit), {len(sets['sub_major_groups'])} sub-major groups (two digits), {len(sets['minor_groups'])} minor groups (three digits) "
            f"and {len(sets['unit_groups'])} unit groups (four digits), each mapped to its title. Unit group codes are the keys used by ASHE and other ONS "
            "occupation tables, so a synthetic job record can carry a real SOC code and title. The workbook's descriptive text is not reproduced. "
            "ONS publishes the classification under the Open Government Licence v3.0."
        ),
    }


SICKNESS_TITLE = "Sickness absence in the UK labour market: 2025 (XLSX dataset)"
SICKNESS_LICENSE_NOTE = " ONS publishes the dataset under the Open Government Licence v3.0 and labels it official statistics in development."


def sickness_annual(book: Workbook) -> dict:
    rate = {str(r[0].value): r for r in book.rows("Table 1")[4:] if r[0].value is not None and str(r[0].value).isdigit()}
    days = {str(r[0].value): r for r in book.rows("Table 2")[4:] if r[0].value is not None and str(r[0].value).isdigit()}
    per_worker = {str(r[0].value): r for r in book.rows("Table 3")[4:] if r[0].value is not None and str(r[0].value).isdigit()}
    by_sex = {str(r[0].value): r for r in book.rows("Table 6")[4:] if r[0].value is not None and str(r[0].value).isdigit()}
    series = []
    for year in sorted(rate):
        series.append({
            "period": year,
            "value": float(rate[year][1].value),
            "days_lost_millions": float(days[year][1].value),
            "days_lost_per_worker": float(per_worker[year][1].value),
            "men_rate_percent": float(by_sex[year][1].value),
            "women_rate_percent": float(by_sex[year][2].value),
        })
    first, last = series[0]["period"], series[-1]["period"]
    items = [
        book.cite_cell(SICKNESS_TITLE, "Table 1", rate[first][1], f"sickness absence rate, {first}"),
        book.cite_cell(SICKNESS_TITLE, "Table 1", rate[last][1], f"sickness absence rate, {last}"),
        book.cite_cell(SICKNESS_TITLE, "Table 3", per_worker[last][1], f"days lost per worker, {last}", "decimal"),
        book.cite_cell(SICKNESS_TITLE, "Table 6", by_sex[last][2], f"sickness absence rate, women, {last}"),
    ]
    return {
        "id": f"gb-sickness-absence-rate-annual-{first}-{last}",
        "title": f"UK sickness absence rate, days lost and days lost per worker, annual {first} to {last}, with rates by sex (ONS LFS)",
        "kind": "temporal",
        "domain": "employment",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{first}-01-01", "end": f"{last}-12-31"},
        "tags": ["sickness-absence", "absence", "labour-force-survey", "ons", "hr"],
        "use_cases": HR_USE_CASES + ["hr-analytics", "insurance"],
        "spec": {"variable": "sickness_absence_rate_percent", "unit": "percent", "frequency": "annual", "columns": ["days_lost_millions", "days_lost_per_worker", "men_rate_percent", "women_rate_percent"], "series": series},
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last}]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": f"column[women_rate_percent,{last}]", "expected": series[-1]["women_rate_percent"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "The sickness absence rate is the percentage of working hours lost to sickness or injury among workers in the UK, from the ONS Labour Force Survey, "
            "with the number of working days lost (millions), days lost per worker and the rate for men and women, one point per calendar year "
            f"(Tables 1, 2, 3 and 6 of the 2025 workbook). Years {first} to {last} are kept as published." + SICKNESS_LICENSE_NOTE
        ),
    }


def sickness_by_age_and_sex(book: Workbook) -> dict:
    rows8 = book.rows("Table 8")
    header = rows8[header_index(rows8, "Year")]
    labels = column_labels(header, "Sickness absence rate")
    all_persons = year_row(rows8, 2025)
    rows19 = book.rows("Table 19")
    men_start = header_index(rows19, "Age Groups\n(Men)")
    women_start = next(i for i, r in enumerate(rows19) if isinstance(r[0].value, str) and r[0].value.startswith("Age Groups\n(Women)"))
    bands = [r[0].value for r in rows19[men_start + 1 : women_start] if r[0].value]
    men = {r[0].value: r for r in rows19[men_start + 1 : women_start] if r[0].value}
    women = {r[0].value: r for r in rows19[women_start + 1 : women_start + 1 + len(bands)] if r[0].value}
    rows: dict[str, dict] = {}
    for band, label, cell in zip(bands, labels, all_persons[1:]):
        rows[band] = {"label": label, "all_persons_2025": float(cell.value), "men_2025": float(men[band][1].value), "women_2025": float(women[band][1].value), "all_persons_2024": None}
    all_2024 = year_row(rows8, 2024)
    for band, cell in zip(bands, all_2024[1:]):
        rows[band]["all_persons_2024"] = float(cell.value)
    items = [
        book.cite_cell(SICKNESS_TITLE, "Table 8", all_persons[1], f"sickness absence rate 2025, {labels[0]}"),
        book.cite_cell(SICKNESS_TITLE, "Table 19", men[bands[-1]][1], f"sickness absence rate 2025, men, {bands[-1]}"),
        book.cite_cell(SICKNESS_TITLE, "Table 19", women[bands[0]][1], f"sickness absence rate 2025, women, {bands[0]}"),
    ]
    return lookup_entry(
        "gb-sickness-absence-rate-by-age-group-and-sex-2025", "UK sickness absence rate by age group and sex, 2025, with 2024 comparison (ONS LFS)", "employment", "GB",
        rows, {"year": 2025, "source_tables": ["Table 8", "Table 19"]}, lookup_vectors(rows, "all_persons_2025", bands[:2]), items,
        column_tests(rows, "men_2025", bands[-1]) + column_tests(rows, "women_2025", bands[0]),
        ["sickness-absence", "absence", "by-age", "by-sex", "ons", "hr"], HR_USE_CASES + ["hr-analytics", "insurance"],
        "Percentage of working hours lost to sickness or injury in 2025 by age band for all workers (Table 8) and for men and women separately (Table 19), "
        "with the 2024 all-worker rate alongside, from the ONS sickness absence workbook. Rows are keyed by the age band as the workbook labels it." + SICKNESS_LICENSE_NOTE,
        ("2025-01-01", "2025-12-31"),
    )


def sickness_by_region_and_sex(book: Workbook) -> dict:
    rows9 = book.rows("Table 9")
    start = header_index(rows9, "Geographic area")
    all_rows = {clean_label(r[0].value): r for r in rows9[start + 1 :] if isinstance(r[0].value, str)}
    rows20 = book.rows("Table 20")
    men_start = header_index(rows20, "Geographic area (Men)")
    women_start = next(i for i, r in enumerate(rows20) if isinstance(r[0].value, str) and r[0].value.startswith("Geographic area (Women)"))
    men = {clean_label(r[0].value): r for r in rows20[men_start + 1 : women_start] if isinstance(r[0].value, str)}
    women = {clean_label(r[0].value): r for r in rows20[women_start + 1 : women_start + 1 + len(men)] if isinstance(r[0].value, str)}
    rows = {area: {"all_persons_2025": float(r[1].value), "all_persons_2024": float(r[2].value), "men_2025": float(men[area][1].value), "women_2025": float(women[area][1].value)} for area, r in all_rows.items()}
    items = [
        book.cite_cell(SICKNESS_TITLE, "Table 9", all_rows["United Kingdom"][1], "sickness absence rate 2025, United Kingdom"),
        book.cite_cell(SICKNESS_TITLE, "Table 9", all_rows["London"][1], "sickness absence rate 2025, London"),
        book.cite_cell(SICKNESS_TITLE, "Table 20", women["Scotland"][1], "sickness absence rate 2025, women, Scotland"),
    ]
    return lookup_entry(
        "gb-sickness-absence-rate-by-region-and-sex-2025", "UK sickness absence rate by region and country of work and by sex, 2025 (ONS LFS)", "employment", "GB",
        rows, {"year": 2025, "source_tables": ["Table 9", "Table 20"]}, lookup_vectors(rows, "all_persons_2025", ["United Kingdom", "London"]), items,
        column_tests(rows, "women_2025", "Scotland") + column_tests(rows, "men_2025", "United Kingdom"),
        ["sickness-absence", "absence", "by-region", "by-sex", "ons", "hr"], HR_USE_CASES + ["hr-analytics", "insurance"],
        "Percentage of working hours lost to sickness or injury in 2025 by UK region and country for all workers, with the 2024 rate, and for men and women "
        "(Tables 9 and 20 of the ONS sickness absence workbook). The United Kingdom, Great Britain and England totals are kept beside the nine English regions, "
        "Wales, Scotland and Northern Ireland; the '[note 15]' markers on the aggregate labels are removed from the keys." + SICKNESS_LICENSE_NOTE,
        ("2025-01-01", "2025-12-31"),
    )


def sickness_by_occupation(book: Workbook) -> dict:
    rows16 = book.rows("Table 16 SOC20")
    start = header_index(rows16, "Occupation Groups")
    rate_rows = {collapse(r[0].value): r for r in rows16[start + 1 :] if isinstance(r[0].value, str)}
    rows16b = book.rows("Table 16b SOC20")
    start_b = header_index(rows16b, "Occupation Groups")
    days_rows = {collapse(r[0].value): r for r in rows16b[start_b + 1 :] if isinstance(r[0].value, str)}
    rows = {}
    for major, (group, r) in enumerate(rate_rows.items(), start=1):
        rows[group] = {"soc_2020_major_group": str(major), "rate_2025": float(r[1].value), "rate_2024": float(r[2].value), "rate_2023": float(r[3].value), "days_lost_per_worker_2025": float(days_rows[group][1].value)}
    first, last = next(iter(rows)), list(rows)[-1]
    items = [
        book.cite_cell(SICKNESS_TITLE, "Table 16 SOC20", rate_rows[first][1], f"sickness absence rate 2025, {first}"),
        book.cite_cell(SICKNESS_TITLE, "Table 16 SOC20", rate_rows[last][1], f"sickness absence rate 2025, {last}"),
        book.cite_cell(SICKNESS_TITLE, "Table 16b SOC20", days_rows[last][1], f"days lost per worker 2025, {last}", "decimal"),
    ]
    return lookup_entry(
        "gb-sickness-absence-rate-by-occupation-group-2025", "UK sickness absence rate and days lost per worker by SOC 2020 major occupation group, 2025 (ONS LFS)", "employment", "GB",
        rows, {"year": 2025, "source_tables": ["Table 16 SOC20", "Table 16b SOC20"]}, lookup_vectors(rows, "rate_2025", [first, last]), items,
        column_tests(rows, "days_lost_per_worker_2025", last) + column_tests(rows, "rate_2024", first),
        ["sickness-absence", "absence", "occupations", "soc-2020", "ons", "hr"], HR_USE_CASES + ["hr-analytics", "insurance"],
        "Percentage of working hours lost to sickness or injury in 2025, 2024 and 2023 and working days lost per worker in 2025 for each of the nine SOC 2020 major "
        "occupation groups (Tables 16 SOC20 and 16b SOC20 of the ONS sickness absence workbook). Rows are keyed by the group title as the workbook spells it; "
        "the soc_2020_major_group column gives the one-digit code in the order the table lists the groups, which follows the classification." + SICKNESS_LICENSE_NOTE,
        ("2025-01-01", "2025-12-31"),
        assumed=[{"parameter": "rows[*].soc_2020_major_group", "value": "1 to 9 in table order", "method": "derived", "rationale": "The workbook lists the nine SOC 2020 major groups in classification order without their codes; the code is the row's position."}],
    )


def sickness_by_industry(book: Workbook) -> dict:
    rows21 = book.rows("Table 21")
    start = header_index(rows21, "Industry Sectors")
    sector_rows = {collapse(r[0].value): r for r in rows21[start + 1 :] if isinstance(r[0].value, str)}
    rows = {}
    for label, r in sector_rows.items():
        sections, name = label.split(":", 1)
        rows[sections.strip()] = {"name": name.strip(), "rate_2025": float(r[1].value), "rate_2024": float(r[2].value), "rate_2023": float(r[3].value)}
    keys = list(rows)
    items = [
        book.cite_cell(SICKNESS_TITLE, "Table 21", sector_rows[next(iter(sector_rows))][1], f"sickness absence rate 2025, {next(iter(sector_rows))}"),
        book.cite_cell(SICKNESS_TITLE, "Table 21", sector_rows[list(sector_rows)[-1]][1], f"sickness absence rate 2025, {list(sector_rows)[-1]}"),
    ]
    return lookup_entry(
        "gb-sickness-absence-rate-by-industry-section-2025", "UK sickness absence rate by industry section (SIC 2007), 2025 with 2024 and 2023 (ONS LFS)", "employment", "GB",
        rows, {"year": 2025, "source_tables": ["Table 21"]}, lookup_vectors(rows, "rate_2025", [keys[0], keys[-1]]), items,
        column_tests(rows, "rate_2025", "C") + column_tests(rows, "rate_2024", "Q"),
        ["sickness-absence", "absence", "by-industry", "sic-2007", "ons", "hr"], HR_USE_CASES + ["hr-analytics", "insurance"],
        "Percentage of working hours lost to sickness or injury in 2025, 2024 and 2023 by industry sector (Table 21 of the ONS sickness absence workbook). "
        "Rows are keyed by the SIC 2007 section letters the workbook puts in front of each label (for example C, or B,D,E for the combined sector)." + SICKNESS_LICENSE_NOTE,
        ("2025-01-01", "2025-12-31"),
    )


def sickness_by_employer(book: Workbook) -> dict:
    groups = [("Table 11", "sector"), ("Table 13", "public_sector_organisation"), ("Table 14", "employment_classification"), ("Table 15", "workforce_size"), ("Table 17", "employment_pattern")]
    rows: dict[str, dict] = {}
    cells: dict[str, Any] = {}
    for sheet, group in groups:
        table = book.rows(sheet)
        header = table[header_index(table, "Year")]
        labels = column_labels(header, "Sickness absence rate")
        row_2025, row_2024 = year_row(table, 2025), year_row(table, 2024)
        for index, label in enumerate(labels, start=1):
            key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            rows[key] = {"label": label, "group": group, "rate_2025": float(row_2025[index].value), "rate_2024": float(row_2024[index].value)}
            cells[key] = (sheet, row_2025[index])
    items = [
        book.cite_cell(SICKNESS_TITLE, *cells["public_sector"], "sickness absence rate 2025, public sector"),
        book.cite_cell(SICKNESS_TITLE, *cells["part_time"], "sickness absence rate 2025, part-time"),
        book.cite_cell(SICKNESS_TITLE, *cells["500_or_more_employees"], "sickness absence rate 2025, 500 or more employees"),
    ]
    return lookup_entry(
        "gb-sickness-absence-rate-by-employer-characteristics-2025", "UK sickness absence rate by sector, workforce size, employment pattern and classification, 2025 and 2024 (ONS LFS)", "employment", "GB",
        rows, {"year": 2025, "source_tables": [s for s, _ in groups]}, lookup_vectors(rows, "rate_2025", ["public_sector", "part_time"]), items,
        column_tests(rows, "rate_2025", "500_or_more_employees") + column_tests(rows, "rate_2024", "private_sector"),
        ["sickness-absence", "absence", "employer", "ons", "hr"], HR_USE_CASES + ["hr-analytics", "insurance"],
        "Percentage of working hours lost to sickness or injury in 2025 and 2024 by public versus private sector (Table 11), by large public sector organisation type "
        "against the private sector (Table 13), employees versus self-employed (Table 14), workforce size band (Table 15) and full-time versus part-time (Table 17), "
        "from the ONS sickness absence workbook. Rows are keyed by a slug of the column heading; the group column names the table each row came from." + SICKNESS_LICENSE_NOTE,
        ("2025-01-01", "2025-12-31"),
    )


# ---------------------------------------------------------------- ASHE via Nomis

ASHE_URL = (
    "https://www.nomisweb.co.uk/api/v01/dataset/NM_99_1.data.csv?geography=2092957697,2092957698,2092957699,2013265921...2013265932"
    "&date=2025&sex=5...9&item=1,2,4,6,8,13,15&pay=5,7&measures=20100"
    "&select=geography_code,geography_name,date_name,sex_name,item_name,pay_name,obs_value,obs_status_name"
)
ASHE_GROUPS = {"Total": "all", "Male": "men", "Female": "women", "Full Time Workers": "full_time", "Part Time Workers": "part_time"}
ASHE_ITEMS = {"Number of jobs": "employee_jobs", "Median": "median", "Mean": "mean", "10 percentile": "p10", "25 percentile": "p25", "75 percentile": "p75", "90 percentile": "p90"}
ASHE_TITLE = "Nomis API, dataset NM_99_1 (Annual Survey of Hours and Earnings, workplace analysis), CSV"


def ashe_pay_by_region(source: Source, pay: str, slug: str, unit: str, noun: str) -> dict:
    data = [r for r in csv_rows(source.raw) if r["PAY_NAME"] == pay]
    rows: dict[str, dict] = {}
    suppressed = 0
    for r in data:
        key = f"{r['GEOGRAPHY_CODE']}:{ASHE_GROUPS[r['SEX_NAME']]}"
        record = rows.setdefault(key, {"area": r["GEOGRAPHY_NAME"], "group": ASHE_GROUPS[r["SEX_NAME"]]})
        record[ASHE_ITEMS[r["ITEM_NAME"]]] = numeric(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
        suppressed += not r["OBS_VALUE"]
    rows = dict(sorted(rows.items()))

    def line(code: str, group: str, item: str) -> CsvRow:
        name = next(k for k, v in ASHE_GROUPS.items() if v == group)
        return next(r for r in data if r["GEOGRAPHY_CODE"] == code and r["SEX_NAME"] == name and r["ITEM_NAME"] == item)

    cited = [("K02000001", "all", "Median"), ("E12000007", "full_time", "90 percentile"), ("W92000004", "women", "Mean")]
    items = []
    for code, group, item in cited:
        row = line(code, group, item)
        items.append(source.cite(ONS, ASHE_TITLE, f"GEOGRAPHY_CODE={code}, SEX_NAME={row['SEX_NAME']}, ITEM_NAME={item}, PAY_NAME={pay}, OBS_VALUE", row["OBS_VALUE"], unit, row.snippet("GEOGRAPHY_CODE", "OBS_VALUE"), OGL))
    jobs = line("K02000001", "all", "Number of jobs")
    items.append(source.cite(ONS, ASHE_TITLE, f"GEOGRAPHY_CODE=K02000001, SEX_NAME=Total, ITEM_NAME=Number of jobs, PAY_NAME={pay}, OBS_VALUE", jobs["OBS_VALUE"], "count", jobs.snippet("GEOGRAPHY_CODE", "OBS_VALUE"), OGL))
    areas = sorted({r["GEOGRAPHY_NAME"] for r in data})
    return lookup_entry(
        f"gb-ashe-{slug}-by-region-and-worker-group-2025", f"UK {noun} percentiles by region and country of work, by sex and full-time or part-time, April 2025 (ONS ASHE)", "employment", "GB",
        rows, {"dataset": "NM_99_1", "pay": pay, "url": source.url, "key_format": "<ONS geography code>:<group>", "groups": sorted(set(ASHE_GROUPS.values()))},
        lookup_vectors(rows, "median", ["K02000001:all", "E12000007:full_time"]), items,
        column_tests(rows, "median", "K02000001:all") + column_tests(rows, "p90", "E12000007:full_time") + [{"statistic": "value[W92000004:women,mean]", "expected": rows["W92000004:women"]["mean"], "tolerance": 1e-9}],
        ["pay", "earnings", "ashe", "percentiles", "by-region", "by-sex", "ons"], HR_USE_CASES + ["hr-analytics", "person-generation"],
        f"{noun.capitalize()} of employee jobs in the April 2025 Annual Survey of Hours and Earnings, workplace-based, from the ONS dataset NM_99_1 served by Nomis: the number of employee jobs, the median, the mean and the "
        "10th, 25th, 75th and 90th percentiles, for each combination of area and worker group. Areas are the United Kingdom, Great Britain, England, Wales, Scotland, Northern Ireland and the nine English regions "
        f"({len(areas)} in all); groups are all employees, men, women, full-time and part-time. Rows are keyed '<ONS geography code>:<group>', for example K02000001:all. "
        f"{suppressed} cells that ONS suppresses as statistically unreliable are null. The 2025 figures are the latest Nomis serves; ONS also publishes 2026 provisional ASHE tables only as ZIP archives of spreadsheets, which the verifier cannot read. "
        "valid_from and valid_to bound the survey year; the ASHE reference date is in April. ONS publishes ASHE under the Open Government Licence v3.0.",
        ("2025-01-01", "2025-12-31"),
    )


# ---------------------------------------------------------------- OECD


def oecd_url(flow: str, key: str, start: str) -> str:
    return f"{OECD_API}/{flow}/{key}?startPeriod={start}&format=csvfilewithlabels"


def oecd_title(flow: str, name: str) -> str:
    return f"OECD Data Explorer SDMX API, dataflow {flow} ({name}), CSV with labels"


@dataclass
class OecdTable:
    """An OECD SDMX-CSV response, filtered to one year, with the labelled rows kept for citation."""

    flow: str
    name: str
    source: Source
    year: str
    rows: list[CsvRow] = field(init=False)

    def __post_init__(self) -> None:
        self.rows = [r for r in csv_rows(self.source.raw) if r["TIME_PERIOD"] == self.year and r["OBS_VALUE"] != ""]

    def select(self, **dims: str) -> list[CsvRow]:
        return [r for r in self.rows if all(r.get(k) == v for k, v in dims.items())]

    def one(self, area: str, **dims: str) -> CsvRow | None:
        found = self.select(REF_AREA=area, **dims)
        if len(found) > 1:
            raise ValueError(f"{self.flow}: {area} {dims} matches {len(found)} rows")
        return found[0] if found else None

    def areas(self) -> list[str]:
        return sorted({r["REF_AREA"] for r in self.rows if iso3_only(r["REF_AREA"])})

    def names(self) -> dict[str, str]:
        return {r["REF_AREA"]: r["Reference area"] for r in self.rows}

    def cite(self, row: CsvRow, locator: str, unit: str) -> dict:
        return self.source.cite(OECD, oecd_title(self.flow, self.name), f"{locator}, TIME_PERIOD={row['TIME_PERIOD']}, OBS_VALUE", row["OBS_VALUE"], unit, row.snippet("REF_AREA"), UNSTATED)


def oecd_lookup(table: OecdTable, columns: dict[str, dict[str, str]], casts: dict[str, Callable] | None = None) -> tuple[dict[str, dict], dict[str, CsvRow]]:
    """Rows keyed by ISO3 code with one column per dimension filter; returns the rows and the cited cells per column (DEU or first area)."""
    names = table.names()
    rows: dict[str, dict] = {}
    cells: dict[str, CsvRow] = {}
    for area in table.areas():
        record: dict[str, Any] = {"name": names[area]}
        for column, dims in columns.items():
            row = table.one(area, **dims)
            record[column] = (casts or {}).get(column, numeric)(row["OBS_VALUE"]) if row else None
            if row and (column not in cells or area == "DEU"):
                cells[column] = row
        if any(record[c] is not None for c in columns):
            rows[area] = record
    return rows, cells


def oecd_entry(entry_id: str, title: str, domain: str, table: OecdTable, columns: dict[str, dict[str, str]], units: dict[str, str], tags: list[str], use_cases: list[str], notes: str, lead: str | None = None, test_keys: tuple[str, str] = ("DEU", "FRA"), casts: dict[str, Callable] | None = None, assumed: list[dict] | None = None, extra_parameters: dict | None = None) -> dict:
    rows, cells = oecd_lookup(table, columns, casts)
    lead = lead or next(iter(columns))
    items = [table.cite(cells[c], f"REF_AREA={cells[c]['REF_AREA']}, " + ", ".join(f"{k}={v}" for k, v in columns[c].items()), units[c]) for c in columns if c in cells]
    tests = column_tests(rows, lead, test_keys[0]) + [{"statistic": f"value[{test_keys[1]},{lead}]", "expected": rows[test_keys[1]][lead], "tolerance": 1e-9}]
    year = table.year
    return lookup_entry(
        entry_id, title, domain, "global", rows, {"dataflow": table.flow, "url": table.source.url, "period": year, **(extra_parameters or {})},
        lookup_vectors(rows, lead, test_keys), items, tests, tags + ["oecd", "reference-table", "by-country"], use_cases,
        notes + f" Rows are keyed by ISO 3166-1 alpha-3 code and carry the OECD reference-area label; OECD, EU and G7 aggregates are left out. Values are the {year} observations of the dataflow. " + OECD_LICENSE_NOTE,
        (f"{year}-01-01", f"{year}-12-31"), status="license-review", assumed=assumed,
    )


def oecd_wages(table: OecdTable) -> dict:
    columns = {
        "usd_ppp_constant_prices": {"UNIT_MEASURE": "USD_PPP", "PRICE_BASE": "Q"},
        "national_currency_current_prices": {"PRICE_BASE": "V"},
    }
    entry = oecd_entry(
        "global-oecd-average-annual-wages-2024", "Average annual wages by country, 2024: constant-price USD PPP and current-price national currency (OECD)", "employment", table, columns,
        {"usd_ppp_constant_prices": "currency:USD", "national_currency_current_prices": "decimal"}, ["wages", "pay", "earnings", "average-wage"], HR_USE_CASES + ["hr-analytics", "market-sizing"],
        "Average annual wages per full-time equivalent employee from the OECD earnings dataflow AV_AN_WAGE: the constant-price series converted at purchasing power parities (US dollars, PPP converted, constant prices) "
        "and the current-price series in national currency units. The currency column names the national currency the second column is expressed in.",
    )
    currency = {r["REF_AREA"]: r["UNIT_MEASURE"] for r in table.select(PRICE_BASE="V")}
    for area, record in entry["spec"]["parameters"]["rows"].items():
        record["currency"] = currency.get(area)
    return entry


def oecd_minimum_wages(relative: OecdTable, levels: OecdTable) -> dict:
    columns = {"minimum_to_mean_wage_percent": {"AGGREGATION_OPERATION": "MEAN"}, "minimum_to_median_wage_percent": {"AGGREGATION_OPERATION": "MEDIAN"}}
    entry = oecd_entry(
        "global-oecd-minimum-wages-and-relative-levels-2024", "Statutory minimum wages by country, 2024: annual, monthly and hourly levels in national currency and ratio to mean and median wages (OECD)", "employment", relative, columns,
        {"minimum_to_mean_wage_percent": "percent", "minimum_to_median_wage_percent": "percent"}, ["minimum-wage", "wages", "pay"], HR_USE_CASES + ["hr-analytics", "personal-finance"],
        "Minimum wages relative to the mean and median wages of full-time workers (OECD dataflow MIN2AVE, percent) joined with the statutory minimum wage at current prices in national currency "
        "(dataflow MW_CURP) per year, per month and per hour where the OECD publishes that pay period.",
        extra_parameters={"levels_dataflow": levels.flow, "levels_url": levels.source.url},
    )
    rows = entry["spec"]["parameters"]["rows"]
    cited = None
    for area, record in rows.items():
        for column, period in (("minimum_wage_annual", "A"), ("minimum_wage_monthly", "M"), ("minimum_wage_hourly", "H")):
            row = levels.one(area, PAY_PERIOD=period)
            record[column] = numeric(row["OBS_VALUE"]) if row else None
            record["currency"] = row["UNIT_MEASURE"] if row else record.get("currency")
            if row and period == "A" and (cited is None or area == "FRA"):
                cited = row
    entry["evidence"].append(levels.cite(cited, f"REF_AREA={cited['REF_AREA']}, PAY_PERIOD=A", "decimal"))
    entry["tests"].append({"statistic": f"value[{cited['REF_AREA']},minimum_wage_annual]", "expected": rows[cited["REF_AREA"]]["minimum_wage_annual"], "tolerance": 1e-9})
    return entry


def oecd_tenure(table: OecdTable) -> dict:
    base = {"SEX": "_T", "TENURE": "TOTD", "MEASURE": "TENURE_EMP_DEP"}
    columns = {
        "average_tenure_years_all_ages": {**base, "AGE": "_T"},
        "average_tenure_years_15_24": {**base, "AGE": "Y15T24"},
        "average_tenure_years_25_54": {**base, "AGE": "Y25T54"},
        "average_tenure_years_55_64": {**base, "AGE": "Y55T64"},
        "average_tenure_years_men": {**base, "SEX": "M", "AGE": "_T"},
        "average_tenure_years_women": {**base, "SEX": "F", "AGE": "_T"},
        "average_tenure_years_all_employment": {"SEX": "_T", "TENURE": "TOTD", "MEASURE": "TENURE_EMP", "AGE": "_T"},
    }
    return oecd_entry(
        "global-oecd-average-job-tenure-by-age-band-2024", "Average job tenure in years by country, 2024: dependent employment by age band and sex, and all employment (OECD)", "employment", table, columns,
        {c: "decimal" for c in columns}, ["tenure", "job-tenure", "length-of-service"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "Average length of time workers have been with their current employer, in years, from OECD dataflow DF_TENURE_AVE (job tenure intervals, average job tenure, total declared tenure). "
        "The dependent-employment measure is given for all ages, for the 15 to 24, 25 to 54 and 55 to 64 age bands and for men and women; the all-employment measure, which includes the self-employed, is the last column.",
    )


def oecd_temporary(table: OecdTable) -> dict:
    base = {"MEASURE": "EMP_TEMP", "WORKER_STATUS": "ICSE93_1"}
    columns = {
        "temporary_share_of_employees_percent": {**base, "SEX": "_T", "AGE": "_T"},
        "temporary_share_men_percent": {**base, "SEX": "M", "AGE": "_T"},
        "temporary_share_women_percent": {**base, "SEX": "F", "AGE": "_T"},
        "temporary_share_15_24_percent": {**base, "SEX": "_T", "AGE": "Y15T24"},
        "temporary_share_25_54_percent": {**base, "SEX": "_T", "AGE": "Y25T54"},
    }
    return oecd_entry(
        "global-oecd-temporary-employment-share-2024", "Temporary employment as a share of employees by country, 2024, by sex and for young and prime-age workers (OECD)", "employment", table, columns,
        {c: "percent" for c in columns}, ["temporary-employment", "contract-type", "fixed-term"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "Share of employees whose job is temporary (fixed-term, agency or other non-permanent contract) from OECD dataflow DF_TEMP_I (employment by permanency of the job, incidence, percentage of employees in the same subgroup), "
        "for all employees, men, women and the 15 to 24 and 25 to 54 age bands. The complement of each share is the permanent-contract share.",
    )


def oecd_part_time(table: OecdTable) -> dict:
    base = {"MEASURE": "EMP", "UNIT_MEASURE": "PT_POP_SUB", "WORK_TIME_ARNGMNT": "PT", "AGE": "_T", "JOB_COVERAGE": "MAIN"}
    columns = {
        "part_time_share_of_employment_percent": {**base, "SEX": "_T", "WORKER_STATUS": "_T"},
        "part_time_share_men_percent": {**base, "SEX": "M", "WORKER_STATUS": "_T"},
        "part_time_share_women_percent": {**base, "SEX": "F", "WORKER_STATUS": "_T"},
        "part_time_share_of_employees_percent": {**base, "SEX": "_T", "WORKER_STATUS": "ICSE93_1"},
    }
    return oecd_entry(
        "global-oecd-part-time-employment-share-2024", "Part-time employment as a share of total employment by country and sex, 2024, OECD common definition (under 30 usual hours)", "employment", table, columns,
        {c: "percent" for c in columns}, ["part-time", "working-time", "hours"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "Share of people in employment who usually work fewer than 30 hours a week in their main job, the OECD common definition of part-time work, from dataflow DF_FTPT_COMMON_INC "
        "(incidence of full-time and part-time employment, percentage of population in the same subgroup), for all workers, men, women and for employees only.",
    )


def oecd_unemployment_duration(table: OecdTable) -> dict:
    bands = {"M_LT1": "under_1_month", "M_1T2": "1_to_2_months", "M_3T5": "3_to_5_months", "M_6T11": "6_to_11_months", "Y_GE1": "12_months_and_over"}
    names = table.names()
    distributions = {}
    cited: dict[str, CsvRow] = {}
    for area in table.areas():
        found = {bands[r["DURATION"]]: float(r["OBS_VALUE"]) for r in table.select(REF_AREA=area, SEX="_T", AGE="_T") if r["DURATION"] in bands}
        if len(found) != len(bands):
            continue
        distributions[area] = {"family": "categorical", "parameters": {"shares": shares_of(found), "published_percent": found, "name": names[area]}}
        if area in ("DEU", "USA"):
            cited[area] = next(r for r in table.select(REF_AREA=area, SEX="_T", AGE="_T") if r["DURATION"] == "Y_GE1")
    items = [table.cite(row, f"REF_AREA={area}, SEX=_T, AGE=_T, DURATION=Y_GE1", "percent") for area, row in cited.items()]
    return conditional_entry(
        "global-oecd-unemployment-duration-distribution-2024", "Distribution of the unemployed by duration of unemployment, given country, 2024 (OECD)", "employment", "global", "unemployment_duration",
        distributions, items,
        [{"parameter": "distributions[*].parameters.shares", "value": "published percent of a band / sum over the five bands", "method": "derived", "rationale": "The OECD publishes the percentage of the unemployed in each duration band; the five bands are normalised to sum to one so that unemployed persons of unknown duration are excluded."}],
        [
            {"statistic": "share[DEU,12_months_and_over]", "expected": distributions["DEU"]["parameters"]["shares"]["12_months_and_over"], "tolerance": 0.005},
            {"statistic": "share[USA,under_1_month]", "expected": distributions["USA"]["parameters"]["shares"]["under_1_month"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[DEU]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[USA]", "expected": 1, "tolerance": 1e-4},
        ],
        ["unemployment", "unemployment-duration", "oecd", "by-country"], HR_USE_CASES + ["hr-analytics", "credit-risk", "collections"],
        f"How long unemployed people have been looking for work, both sexes and all ages, for {len(distributions)} countries in 2024, from OECD dataflow DF_DUR_I (incidence of unemployment by duration, percentage of the unemployed). "
        "Each distribution keeps the published percentages beside the derived shares. Countries missing any of the five bands are left out. " + OECD_LICENSE_NOTE,
        ("2024-01-01", "2024-12-31"), status="license-review",
    )


def oecd_hours_bands(table: OecdTable) -> dict:
    bands = {"H1T19": "1_to_19_hours", "H20T29": "20_to_29_hours", "H30T34": "30_to_34_hours", "H35T39": "35_to_39_hours", "H_GE40": "40_hours_and_over"}
    names = table.names()
    distributions = {}
    cited: dict[str, CsvRow] = {}
    for area in table.areas():
        rows = [r for r in table.select(REF_AREA=area, SEX="_T", AGE="_T", WORKER_STATUS="_T") if r["HOUR_BANDS"] in bands]
        found = {bands[r["HOUR_BANDS"]]: float(r["OBS_VALUE"]) for r in rows}
        if len(found) != len(bands) or sum(found.values()) <= 0:
            continue
        distributions[area] = {"family": "categorical", "parameters": {"shares": shares_of(found), "thousand_persons": found, "name": names[area]}}
        if area in ("DEU", "GBR"):
            cited[area] = next(r for r in rows if r["HOUR_BANDS"] == "H_GE40")
    items = [table.cite(row, f"REF_AREA={area}, SEX=_T, AGE=_T, WORKER_STATUS=_T, HOUR_BANDS=H_GE40", "count") for area, row in cited.items()]
    return conditional_entry(
        "global-oecd-usual-weekly-hours-bands-2024", "Distribution of employment by usual weekly hours band in the main job, given country, 2024 (OECD)", "employment", "global", "usual_weekly_hours_band",
        distributions, items,
        [{"parameter": "distributions[*].parameters.shares", "value": "persons in a band / sum over the five bands", "method": "derived", "rationale": "The OECD publishes thousands of employed persons per usual-hours band; shares are each band over the sum of the five bands, so persons whose hours are unknown are excluded."}],
        [
            {"statistic": "share[DEU,40_hours_and_over]", "expected": distributions["DEU"]["parameters"]["shares"]["40_hours_and_over"], "tolerance": 0.005},
            {"statistic": "share[GBR,1_to_19_hours]", "expected": distributions["GBR"]["parameters"]["shares"]["1_to_19_hours"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[DEU]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[GBR]", "expected": 1, "tolerance": 1e-4},
        ],
        ["hours", "working-time", "oecd", "by-country"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "capacity-planning"],
        f"Employed persons by band of usual weekly hours worked in the main job (1 to 19, 20 to 29, 30 to 34, 35 to 39, 40 and over), both sexes and all ages, for {len(distributions)} countries in 2024, "
        "from OECD dataflow DF_USL_WK_HRS (usual hours worked by weekly hour bands, thousands of persons). Each distribution keeps the published counts beside the derived shares. " + OECD_LICENSE_NOTE,
        ("2024-01-01", "2024-12-31"), status="license-review",
    )


def oecd_average_hours(table: OecdTable) -> dict:
    base = {"SEX": "_T", "AGE": "Y15T64", "WORKER_STATUS": "_T", "AGGREGATION_OPERATION": "MEAN"}
    columns = {
        "usual_weekly_hours_all_workers": {**base, "WORK_TIME_ARNGMNT": "_T"},
        "usual_weekly_hours_full_time": {**base, "WORK_TIME_ARNGMNT": "FT"},
        "usual_weekly_hours_part_time": {**base, "WORK_TIME_ARNGMNT": "PT"},
        "usual_weekly_hours_employees": {**base, "WORKER_STATUS": "ICSE93_1", "WORK_TIME_ARNGMNT": "_T"},
        "usual_weekly_hours_men": {**base, "SEX": "M", "WORK_TIME_ARNGMNT": "_T"},
        "usual_weekly_hours_women": {**base, "SEX": "F", "WORK_TIME_ARNGMNT": "_T"},
    }
    return oecd_entry(
        "global-oecd-average-usual-weekly-hours-2024", "Average usual weekly hours worked in the main job by country, 2024, ages 15 to 64: all workers, full-time, part-time, employees, men and women (OECD)", "employment", table, columns,
        {c: "decimal" for c in columns}, ["hours", "working-time", "weekly-hours"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "capacity-planning"],
        "Mean usual weekly hours worked in the main job by people aged 15 to 64 from OECD dataflow DF_AVG_USL_WK_WKD, for all workers, for full-time and part-time workers (national definitions of full and part time), "
        "for employees only and for men and women. A zero in the source for a sex or working-time split is kept as published.",
    )


def oecd_epl(table: OecdTable) -> dict:
    columns = {
        "regular_contracts_individual_and_collective_dismissals": {"MEASURE": "EPL_OV", "VERSION": "VERSION4"},
        "regular_contracts_individual_dismissals": {"MEASURE": "EPL_R", "VERSION": "VERSION4"},
        "collective_dismissals_additional_provisions": {"MEASURE": "EPL_CD", "VERSION": "VERSION4"},
        "temporary_contracts": {"MEASURE": "EPL_T", "VERSION": "VERSION4"},
    }
    return oecd_entry(
        "global-oecd-employment-protection-index-2024", "Strictness of employment protection legislation by country, 2024, OECD indicators version 4 on a 0 to 6 scale", "employment", table, columns,
        {c: "decimal" for c in columns}, ["employment-protection", "dismissal", "labour-law"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "OECD indicators of the strictness of employment protection legislation (dataflow DF_EPL, version 4 methodology, scale 0 least restrictive to 6 most restrictive): regular contracts against individual and collective dismissals, "
        "regular contracts against individual dismissals only, the additional provisions for collective dismissals, and the regulation of temporary contracts.",
    )


def oecd_retirement(table: OecdTable) -> dict:
    columns = {
        "current_retirement_age_men": {"MEASURE": "CRPLF22", "SEX": "M"},
        "current_retirement_age_women": {"MEASURE": "CRPLF22", "SEX": "F"},
        "future_retirement_age_men": {"MEASURE": "FRPLF22", "SEX": "M"},
        "future_retirement_age_women": {"MEASURE": "FRPLF22", "SEX": "F"},
        "effective_labour_market_exit_age_men": {"MEASURE": "ELMEA", "SEX": "M"},
        "effective_labour_market_exit_age_women": {"MEASURE": "ELMEA", "SEX": "F"},
    }
    return oecd_entry(
        "global-oecd-retirement-ages-2024", "Current and future normal retirement ages and effective labour market exit age by country and sex, 2024 (OECD Pensions at a Glance)", "pensions", table, columns,
        {c: "decimal" for c in columns}, ["retirement-age", "pensions", "retirement"], HR_USE_CASES + ["pensions", "hr-analytics", "workforce-planning"],
        "From OECD dataflow DF_PAG (Pensions at a Glance): the current normal retirement age for a person who entered the labour force at age 22, the future normal retirement age for someone entering at 22 "
        "under legislated rules, and the average effective age at which workers leave the labour market, each for men and women.",
    )


def oecd_tax_wedge(table: OecdTable) -> dict:
    base = {"HOUSEHOLD_TYPE": "S_C0", "INCOME_PRINCIPAL": "AW100"}
    columns = {
        "average_tax_wedge_percent_of_labour_costs": {**base, "MEASURE": "AV_TW", "UNIT_MEASURE": "PT_COS_LB"},
        "net_personal_average_tax_rate_percent": {**base, "MEASURE": "NPATR", "UNIT_MEASURE": "PT_WG_EARN_G"},
        "employee_social_security_percent_of_labour_costs": {**base, "MEASURE": "EESSC", "UNIT_MEASURE": "PT_COS_LB"},
        "employer_social_security_and_payroll_tax_percent_of_labour_costs": {**base, "MEASURE": "ERSSC_PT", "UNIT_MEASURE": "PT_COS_LB"},
    }
    return oecd_entry(
        "global-oecd-tax-wedge-single-earner-2025", "Tax wedge and its components for a single earner without children at the average wage, by country, 2025 (OECD Taxing Wages)", "tax", table, columns,
        {c: "percent" for c in columns}, ["tax-wedge", "social-contributions", "payroll-tax", "income-tax"], HR_USE_CASES + ["hr-analytics", "personal-finance", "tax-filing-demo"],
        "OECD Taxing Wages decomposition (dataflow DF_TW_DECOMP) for a single person without children earning 100 percent of the average wage: the average tax wedge as a percentage of total labour costs, "
        "the net personal average tax rate as a percentage of gross wage earnings, and employee social security contributions and employer contributions plus payroll taxes as percentages of labour costs. "
        "Labour costs minus the tax wedge is take-home pay, so the row turns a gross-salary value into an employer cost and a net salary.",
    )


def oecd_participation(table: OecdTable) -> dict:
    bands = ["Y15T19", "Y20T24", "Y25T29", "Y30T34", "Y35T39", "Y40T44", "Y45T49", "Y50T54", "Y55T59", "Y60T64", "Y65T69", "Y70T74"]
    columns = {
        "participation_rate_15_64": {"SEX": "_T", "AGE": "Y15T64"},
        "participation_rate_men_15_64": {"SEX": "M", "AGE": "Y15T64"},
        "participation_rate_women_15_64": {"SEX": "F", "AGE": "Y15T64"},
    }
    for band in bands:
        columns[f"participation_rate_{band[1:].replace('T', '_')}"] = {"SEX": "_T", "AGE": band}
    return oecd_entry(
        "global-oecd-labour-force-participation-by-age-and-sex-2024", "Labour force participation rate by country, 2024: ages 15 to 64 by sex and five-year age bands from 15 to 74 (OECD)", "employment", table, columns,
        {c: "percent" for c in columns}, ["labour-force", "participation", "by-age", "by-sex"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "person-generation"],
        "Labour force as a percentage of the population of the same age and sex from OECD dataflow DF_LFS_INDIC (employment and unemployment by five-year age group and sex, indicators, measure LF_RATE): "
        "the 15 to 64 rate for all persons, men and women, and the all-persons rate for each five-year band from 15 to 19 up to 70 to 74.",
    )


# ---------------------------------------------------------------- ILOSTAT


def ilo_url(indicator: str, timefrom: str) -> str:
    return f"{ILO_API}?id={indicator}&timefrom={timefrom}&format=.csv"


def ilo_title(indicator: str, name: str) -> str:
    return f"ILOSTAT data API (rplumber), indicator {indicator} ({name}), CSV"


@dataclass
class IloTable:
    indicator: str
    name: str
    source: Source
    rows: list[CsvRow] = field(init=False)

    def __post_init__(self) -> None:
        self.rows = [r for r in csv_rows(self.source.raw) if r["obs_value"] != ""]

    def latest_year(self, area: str, **dims: str) -> str | None:
        years = {r["time"] for r in self.rows if r["ref_area"] == area and all(r.get(k) == v for k, v in dims.items())}
        return max(years) if years else None

    def select(self, **dims: str) -> list[CsvRow]:
        return [r for r in self.rows if all(r.get(k) == v for k, v in dims.items())]

    def cite(self, row: CsvRow, locator: str, unit: str) -> dict:
        return self.source.cite(ILO, ilo_title(self.indicator, self.name), f"{locator}, time={row['time']}, obs_value", row["obs_value"], unit, row.snippet("ref_area", "obs_value"), UNSTATED)


def ilo_period(rows: dict[str, dict]) -> tuple[str, str]:
    years = sorted({str(r["year"]) for r in rows.values()})
    return f"{years[0]}-01-01", f"{years[-1]}-12-31"


def ilo_monthly_earnings(table: IloTable) -> dict:
    groups = {f"OCU_ISCO08_{n}": f"isco_{n}" for n in range(10)} | {"OCU_ISCO08_X": "isco_not_classified", "OCU_ISCO08_TOTAL": "total"}
    rows: dict[str, dict] = {}
    cited: dict[str, CsvRow] = {}
    for area in sorted({r["ref_area"] for r in table.rows}):
        year = table.latest_year(area, sex="SEX_T", classif1="OCU_ISCO08_TOTAL", classif2="CUR_TYPE_LCU")
        if year is None:
            continue
        local = {groups[r["classif1"]]: numeric(r["obs_value"]) for r in table.select(ref_area=area, sex="SEX_T", classif2="CUR_TYPE_LCU", time=year) if r["classif1"] in groups}
        if sum(1 for n in range(1, 10) if f"isco_{n}" in local) < 8:
            continue
        record: dict[str, Any] = {"year": int(year)}
        for column in groups.values():
            record[f"local_currency_{column}"] = local.get(column)
        for code, label in (("CUR_TYPE_USD", "usd"), ("CUR_TYPE_PPP", "usd_ppp")):
            found = table.select(ref_area=area, sex="SEX_T", classif1="OCU_ISCO08_TOTAL", classif2=code, time=year)
            record[f"{label}_total"] = numeric(found[0]["obs_value"]) if found else None
        for sex, label in (("SEX_M", "men"), ("SEX_F", "women")):
            found = table.select(ref_area=area, sex=sex, classif1="OCU_ISCO08_TOTAL", classif2="CUR_TYPE_LCU", time=year)
            record[f"local_currency_total_{label}"] = numeric(found[0]["obs_value"]) if found else None
        rows[area] = record
        if area in ("GBR", "MEX"):
            cited[area] = next(r for r in table.select(ref_area=area, sex="SEX_T", classif2="CUR_TYPE_LCU", time=year) if r["classif1"] == "OCU_ISCO08_1")
    items = [table.cite(row, f"ref_area={area}, sex=SEX_T, classif1=OCU_ISCO08_1, classif2=CUR_TYPE_LCU", "decimal") for area, row in cited.items()]
    lead = "local_currency_isco_1"
    tests = column_tests(rows, lead, "GBR") + [{"statistic": "value[MEX,local_currency_total]", "expected": rows["MEX"]["local_currency_total"], "tolerance": 1e-9}]
    return lookup_entry(
        "global-ilo-monthly-earnings-by-occupation-latest", "Mean nominal monthly earnings of employees by ISCO-08 major occupation group and by sex, latest year per economy (ILOSTAT)", "income", "global",
        rows, {"indicator": table.indicator, "url": table.source.url, "occupation_groups": {f"isco_{n}": f"ISCO-08 major group {n}" for n in range(10)}},
        lookup_vectors(rows, lead, ("GBR", "MEX")), items, tests, ["earnings", "pay", "occupations", "isco-08", "ilostat", "reference-table", "by-country"], HR_USE_CASES + ["hr-analytics", "person-generation"],
        f"Mean nominal monthly earnings of employees for {len(rows)} economies from ILOSTAT indicator EAR_EMTA_SEX_OCU_CUR_NB (average monthly earnings of employees by sex, occupation and currency): "
        "in local currency for each ISCO-08 major group (0 armed forces to 9 elementary occupations, plus not elsewhere classified and the total), the total for men and women, and the total converted to US dollars "
        "and to PPP dollars where published. Each row carries the latest year since 2023 for which the economy reports a local-currency total; economies with fewer than eight of the nine civilian major groups are left out. "
        "Rows are keyed by ISO 3166-1 alpha-3 code. " + ILO_LICENSE_NOTE,
        ilo_period(rows), status="license-review",
    )


def ilo_employment_by_occupation(table: IloTable) -> dict:
    groups = {f"OCU_ISCO08_{n}": f"isco_{n}" for n in range(10)} | {"OCU_ISCO08_X": "isco_not_classified"}
    distributions = {}
    cited: dict[str, CsvRow] = {}
    for area in sorted({r["ref_area"] for r in table.rows}):
        year = table.latest_year(area, sex="SEX_T", classif1="OCU_ISCO08_TOTAL")
        if year is None:
            continue
        rows = table.select(ref_area=area, sex="SEX_T", time=year)
        counts = {groups[r["classif1"]]: float(r["obs_value"]) for r in rows if r["classif1"] in groups}
        total = next((float(r["obs_value"]) for r in rows if r["classif1"] == "OCU_ISCO08_TOTAL"), None)
        if total is None or len(counts) < 9 or abs(sum(counts.values()) - total) > 0.02 * total:
            continue
        distributions[area] = {"family": "categorical", "parameters": {"shares": shares_of(counts), "thousand_persons": counts, "year": int(year)}}
        if area in ("DEU", "IND"):
            cited[area] = next(r for r in rows if r["classif1"] == "OCU_ISCO08_2")
    items = [table.cite(row, f"ref_area={area}, sex=SEX_T, classif1=OCU_ISCO08_2", "count") for area, row in cited.items()]
    years = sorted({str(d["parameters"]["year"]) for d in distributions.values()})
    return conditional_entry(
        "global-ilo-employment-by-occupation-shares-latest", "Employment shares by ISCO-08 major occupation group, given economy, latest year since 2024 (ILOSTAT)", "employment", "global", "isco_08_major_group",
        distributions, items,
        [{"parameter": "distributions[*].parameters.shares", "value": "thousand persons in a group / sum over the published groups", "method": "derived", "rationale": "ILOSTAT publishes employment in thousands per ISCO-08 major group; shares are each group over the sum of the groups, kept only where that sum is within two percent of the published total."}],
        [
            {"statistic": "share[DEU,isco_2]", "expected": distributions["DEU"]["parameters"]["shares"]["isco_2"], "tolerance": 0.005},
            {"statistic": "share[IND,isco_6]", "expected": distributions["IND"]["parameters"]["shares"]["isco_6"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[DEU]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[IND]", "expected": 1, "tolerance": 1e-4},
        ],
        ["occupations", "isco-08", "employment", "ilostat", "by-country"], HR_USE_CASES + ["hr-analytics", "person-generation", "workforce-planning"],
        f"Share of employed persons in each ISCO-08 major group (0 armed forces, 1 managers, 2 professionals, 3 technicians, 4 clerical, 5 service and sales, 6 skilled agricultural, 7 craft, 8 plant and machine operators, 9 elementary, plus not elsewhere classified) "
        f"for {len(distributions)} economies, from ILOSTAT indicator EMP_TEMP_SEX_OCU_NB (employment by sex and occupation, thousands). Each economy uses its latest reported year ({', '.join(years)}), recorded in the distribution's parameters, "
        "and keeps the published thousands beside the derived shares. Economies are keyed by ISO 3166-1 alpha-3 code. " + ILO_LICENSE_NOTE,
        (f"{years[0]}-01-01", f"{years[-1]}-12-31"), status="license-review",
    )


def ilo_informal(table: IloTable) -> dict:
    rows: dict[str, dict] = {}
    cited: dict[str, CsvRow] = {}
    for area in sorted({r["ref_area"] for r in table.rows}):
        year = table.latest_year(area, sex="SEX_T")
        if year is None:
            continue
        values = {r["sex"]: numeric(r["obs_value"]) for r in table.select(ref_area=area, time=year)}
        rows[area] = {"year": int(year), "informal_employment_rate_percent": values["SEX_T"], "men_percent": values.get("SEX_M"), "women_percent": values.get("SEX_F")}
        if area in ("IND", "BRA"):
            cited[area] = next(r for r in table.select(ref_area=area, time=year) if r["sex"] == "SEX_T")
    items = [table.cite(row, f"ref_area={area}, sex=SEX_T", "percent") for area, row in cited.items()]
    lead = "informal_employment_rate_percent"
    return lookup_entry(
        "global-ilo-informal-employment-rate-latest", "Informal employment as a share of total employment by economy and sex, latest year since 2023 (ILOSTAT)", "employment", "global",
        rows, {"indicator": table.indicator, "url": table.source.url}, lookup_vectors(rows, lead, ("IND", "BRA")), items,
        column_tests(rows, lead, "IND") + [{"statistic": "value[BRA,women_percent]", "expected": rows["BRA"]["women_percent"], "tolerance": 1e-9}],
        ["informal-employment", "employment", "ilostat", "reference-table", "by-country"], HR_USE_CASES + ["hr-analytics", "market-sizing", "credit-risk"],
        f"Informal employment as a percentage of total employment for {len(rows)} economies from ILOSTAT indicator EMP_NIFL_SEX_RT (informal employment rate by sex), for all persons, men and women, "
        "each row at the latest year the economy reports since 2023. Rows are keyed by ISO 3166-1 alpha-3 code. " + ILO_LICENSE_NOTE,
        ilo_period(rows), status="license-review",
    )


def ilo_hours(table: IloTable) -> dict:
    rows: dict[str, dict] = {}
    cited: dict[str, CsvRow] = {}
    for area in sorted({r["ref_area"] for r in table.rows}):
        year = table.latest_year(area, sex="SEX_T", classif1="ECO_SECTOR_TOTAL")
        if year is None:
            continue
        values = {r["sex"]: numeric(r["obs_value"]) for r in table.select(ref_area=area, classif1="ECO_SECTOR_TOTAL", time=year)}
        sectors = {r["classif1"]: numeric(r["obs_value"]) for r in table.select(ref_area=area, sex="SEX_T", time=year)}
        rows[area] = {
            "year": int(year),
            "weekly_hours_all": values["SEX_T"],
            "weekly_hours_men": values.get("SEX_M"),
            "weekly_hours_women": values.get("SEX_F"),
            "weekly_hours_agriculture": sectors.get("ECO_SECTOR_AGR"),
            "weekly_hours_industry": sectors.get("ECO_SECTOR_IND"),
            "weekly_hours_services": sectors.get("ECO_SECTOR_SER"),
        }
        if area in ("DEU", "MEX"):
            cited[area] = next(r for r in table.select(ref_area=area, classif1="ECO_SECTOR_TOTAL", time=year) if r["sex"] == "SEX_T")
    items = [table.cite(row, f"ref_area={area}, sex=SEX_T, classif1=ECO_SECTOR_TOTAL", "decimal") for area, row in cited.items()]
    lead = "weekly_hours_all"
    return lookup_entry(
        "global-ilo-average-weekly-hours-worked-latest", "Average weekly hours actually worked per employed person by economy, sex and broad sector, latest year since 2024 (ILOSTAT)", "employment", "global",
        rows, {"indicator": table.indicator, "url": table.source.url}, lookup_vectors(rows, lead, ("DEU", "MEX")), items,
        column_tests(rows, lead, "DEU") + [{"statistic": "value[MEX,weekly_hours_women]", "expected": rows["MEX"]["weekly_hours_women"], "tolerance": 1e-9}],
        ["hours", "working-time", "weekly-hours", "ilostat", "reference-table", "by-country"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "capacity-planning"],
        f"Average weekly hours actually worked per employed person for {len(rows)} economies from ILOSTAT indicator HOW_TEMP_SEX_ECO_NB (by sex and economic activity), for all persons, men, women and the "
        "agriculture, industry and services broad sectors where published, each row at the latest year the economy reports since 2024. Rows are keyed by ISO 3166-1 alpha-3 code. " + ILO_LICENSE_NOTE,
        ilo_period(rows), status="license-review",
    )


# ---------------------------------------------------------------- Eurostat


@dataclass
class EurostatTable:
    flow: str
    name: str
    source: Source
    names: dict[str, str]
    rows: list[CsvRow] = field(init=False)

    def __post_init__(self) -> None:
        self.rows = [r for r in csv_rows(self.source.raw) if r["OBS_VALUE"] != ""]

    def select(self, **dims: str) -> list[CsvRow]:
        return [r for r in self.rows if all(r.get(k) == v for k, v in dims.items())]

    def cite(self, row: CsvRow, dims: str, unit: str) -> dict:
        return self.source.cite(EUROSTAT, dataflow_title(self.flow, self.name), f"geo={row['geo']}, {dims}, TIME_PERIOD={row['TIME_PERIOD']}, OBS_VALUE", row["OBS_VALUE"], unit, row.snippet("freq"), CC_BY)


def eurostat_entry(entry_id: str, title: str, table: EurostatTable, rows: dict[str, dict], items: list[dict], lead: str, keys: tuple[str, str], tags: list[str], use_cases: list[str], notes: str, valid: tuple[str, str], key: str, extra_tests: list[dict] | None = None) -> dict:
    tests = column_tests(rows, lead, keys[0]) + [{"statistic": f"value[{keys[1]},{lead}]", "expected": rows[keys[1]][lead], "tolerance": 1e-9}] + (extra_tests or [])
    return lookup_entry(
        entry_id, title, "employment", "EU", rows, {"dataflow": table.flow, "key": key, "url": table.source.url}, lookup_vectors(rows, lead, keys), items, tests,
        tags + ["eurostat", "reference-table", "by-country"], use_cases, notes + " Rows are keyed by the Eurostat geo code and carry the English name from the GEO codelist. " + EUROSTAT_LICENSE_NOTE, valid,
    )


def eurostat_vacancy_rate(table: EurostatTable, period: str) -> dict:
    sections = ["B-S"] + [chr(c) for c in range(ord("B"), ord("S") + 1)]
    rows: dict[str, dict] = {}
    for geo in sorted({r["geo"] for r in table.rows}):
        record: dict[str, Any] = {"name": table.names.get(geo, geo)}
        for section in sections:
            found = table.select(geo=geo, nace_r2=section)
            record[section.lower().replace("-", "_")] = numeric(found[0]["OBS_VALUE"]) if found else None
        if record["b_s"] is not None:
            rows[geo] = record
    de = table.select(geo="DE", nace_r2="B-S")[0]
    fr = table.select(geo="FR", nace_r2="J")[0]
    items = [table.cite(de, "nace_r2=B-S, sizeclas=GE10, indic_em=JVR", "percent"), table.cite(fr, "nace_r2=J, sizeclas=GE10, indic_em=JVR", "percent")]
    year, quarter = period.split("-Q")
    start = f"{year}-{(int(quarter) - 1) * 3 + 1:02d}-01"
    end = {"1": f"{year}-03-31", "2": f"{year}-06-30", "3": f"{year}-09-30", "4": f"{year}-12-31"}[quarter]
    return eurostat_entry(
        f"eu-job-vacancy-rate-by-nace-section-{period.lower().replace('-', '')}", f"Job vacancy rate by NACE Rev. 2 section, {period}, enterprises with ten or more employees, all countries reported by Eurostat", table, rows, items, "b_s", ("DE", "FR"),
        ["vacancies", "job-vacancy-rate", "by-industry", "nace"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "capacity-planning"],
        f"Job vacancy rate (vacant posts as a percentage of occupied plus vacant posts, not seasonally adjusted) in {period} for enterprises with ten or more employees, from Eurostat dataflow jvs_q_nace2: "
        "the business economy total (NACE sections B to S, column b_s) and each section B to S where the country reports it. Columns are the lower-case section letter.",
        (start, end), f"Q.NSA..GE10.JVR. ({period})", [{"statistic": "value[FR,j]", "expected": rows["FR"]["j"], "tolerance": 1e-9}],
    )


def eurostat_sex_split(table: EurostatTable, period: str, column_prefix: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for geo in sorted({r["geo"] for r in table.rows}):
        values = {r["sex"]: numeric(r["OBS_VALUE"]) for r in table.select(geo=geo, TIME_PERIOD=period)}
        if "T" in values:
            rows[geo] = {"name": table.names.get(geo, geo), f"{column_prefix}_percent": values["T"], f"{column_prefix}_men_percent": values.get("M"), f"{column_prefix}_women_percent": values.get("F")}
    return rows


def eurostat_temporary(table: EurostatTable) -> dict:
    periods = defaultdict(set)
    for r in table.rows:
        periods[r["TIME_PERIOD"]].add(r["geo"])
    period = max(periods, key=lambda p: (len(periods[p]), p))
    rows = eurostat_sex_split(table, period, "temporary_share_of_employees")
    de = next(r for r in table.select(geo="DE", sex="T", TIME_PERIOD=period))
    fr = next(r for r in table.select(geo="FR", sex="F", TIME_PERIOD=period))
    items = [table.cite(de, "unit=PC, sex=T, age=Y15-64", "percent"), table.cite(fr, "unit=PC, sex=F, age=Y15-64", "percent")]
    year, quarter = period.split("-Q")
    start = f"{year}-{(int(quarter) - 1) * 3 + 1:02d}-01"
    end = {"1": f"{year}-03-31", "2": f"{year}-06-30", "3": f"{year}-09-30", "4": f"{year}-12-31"}[quarter]
    return eurostat_entry(
        f"eu-temporary-employees-share-by-sex-{period.lower().replace('-', '')}", f"Temporary employees as a percentage of all employees aged 15 to 64, by sex, {period}, all countries reported by Eurostat", table, rows, items,
        "temporary_share_of_employees_percent", ("DE", "FR"), ["temporary-employment", "contract-type", "fixed-term", "by-sex"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        f"Employees aged 15 to 64 with a temporary contract as a percentage of all employees of that age in {period}, for all persons, men and women, from Eurostat dataflow lfsq_etpga (quarterly Labour Force Survey). "
        f"{period} is the latest quarter in the fetched range with the widest country coverage.",
        (start, end), f"Q.PC.T+M+F.Y15-64. ({period})", [{"statistic": "value[FR,temporary_share_of_employees_women_percent]", "expected": rows["FR"]["temporary_share_of_employees_women_percent"], "tolerance": 1e-9}],
    )


def eurostat_part_time(table: EurostatTable, year: str) -> dict:
    rows = eurostat_sex_split(table, year, "part_time_share_of_employment")
    de = next(r for r in table.select(geo="DE", sex="T"))
    nl = next(r for r in table.select(geo="NL", sex="F"))
    items = [table.cite(de, "unit=PC, sex=T, age=Y15-64", "percent"), table.cite(nl, "unit=PC, sex=F, age=Y15-64", "percent")]
    return eurostat_entry(
        f"eu-part-time-employment-share-by-sex-{year}", f"Part-time employment as a percentage of total employment aged 15 to 64, by sex, {year}, all countries reported by Eurostat", table, rows, items,
        "part_time_share_of_employment_percent", ("DE", "NL"), ["part-time", "working-time", "hours", "by-sex"], HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        f"Employed persons aged 15 to 64 working part time as a percentage of total employment of that age in {year}, for all persons, men and women, from Eurostat dataflow lfsa_eppga (annual Labour Force Survey, "
        "part-time status as declared by the respondent).",
        (f"{year}-01-01", f"{year}-12-31"), f"A.PC.T+M+F.Y15-64. ({year})", [{"statistic": "value[NL,part_time_share_of_employment_women_percent]", "expected": rows["NL"]["part_time_share_of_employment_women_percent"], "tolerance": 1e-9}],
    )


def eurostat_transitions(table: EurostatTable, period: str) -> dict:
    transitions = {"EMP_EMP": "employed_to_employed", "EMP_UNE": "employed_to_unemployed", "EMP_INAC": "employed_to_inactive", "UNE_EMP": "unemployed_to_employed", "UNE_UNE": "unemployed_to_unemployed", "UNE_INAC": "unemployed_to_inactive", "INAC_EMP": "inactive_to_employed", "INAC_UNE": "inactive_to_unemployed", "INAC_INAC": "inactive_to_inactive"}
    rows: dict[str, dict] = {}
    for geo in sorted({r["geo"] for r in table.rows}):
        values = {r["wstatus"]: numeric(r["OBS_VALUE"]) for r in table.select(geo=geo, sex="T", TIME_PERIOD=period)}
        if "EMP_EMP" in values:
            rows[geo] = {"name": table.names.get(geo, geo), **{column: values.get(code) for code, column in transitions.items()}}
    de = next(r for r in table.select(geo="DE", sex="T", wstatus="EMP_UNE", TIME_PERIOD=period))
    es = next(r for r in table.select(geo="ES", sex="T", wstatus="UNE_EMP", TIME_PERIOD=period))
    items = [table.cite(de, "unit=PC_EMP, s_adj=NSA, wstatus=EMP_UNE, sex=T", "percent"), table.cite(es, "unit=PC_UNE, s_adj=NSA, wstatus=UNE_EMP, sex=T", "percent")]
    year, quarter = period.split("-Q")
    start = f"{year}-{(int(quarter) - 1) * 3 + 1:02d}-01"
    end = {"1": f"{year}-03-31", "2": f"{year}-06-30", "3": f"{year}-09-30", "4": f"{year}-12-31"}[quarter]
    return eurostat_entry(
        f"eu-labour-market-transitions-{period.lower().replace('-', '')}", f"Quarterly labour market transitions between employment, unemployment and inactivity, {period}, all countries reported by Eurostat", table, rows, items,
        "employed_to_unemployed", ("DE", "ES"), ["labour-market-transitions", "churn", "unemployment", "flows"], HR_USE_CASES + ["hr-analytics", "workforce-planning", "credit-risk", "collections"],
        f"Share of people in each labour status in the previous quarter who were employed, unemployed or inactive in {period}, both sexes, not seasonally adjusted, from Eurostat dataflow lfsi_long_q. "
        "The three columns starting from a status are percentages of the people who held that status a quarter earlier (units PC_EMP, PC_UNE and PC_INAC respectively), so each triple sums to about one hundred; "
        "employed_to_unemployed and employed_to_inactive together give a quarterly job-separation probability for a synthetic workforce.",
        (start, end), f"Q..NSA..T. ({period})", [{"statistic": "value[ES,unemployed_to_employed]", "expected": rows["ES"]["unemployed_to_employed"], "tolerance": 1e-9}],
    )


def eurostat_minimum_wage_history(table: EurostatTable) -> dict:
    geos = sorted({r["geo"] for r in table.rows})
    rows: dict[str, dict] = {}
    for period in sorted({r["TIME_PERIOD"] for r in table.rows}):
        values = {r["geo"]: numeric(r["OBS_VALUE"]) for r in table.select(TIME_PERIOD=period)}
        year, half = period.split("-S")
        rows[period] = {"from": f"{year}-01-01" if half == "1" else f"{year}-07-01", **{geo.lower(): values.get(geo) for geo in geos}}
    first, last = next(iter(rows)), list(rows)[-1]
    de_last = next(r for r in table.select(geo="DE", TIME_PERIOD=last))
    fr_first = next(r for r in table.select(geo="FR", TIME_PERIOD=first))
    items = [table.cite(de_last, "currency=EUR", "currency:EUR"), table.cite(fr_first, "currency=EUR", "currency:EUR")]
    tests = [
        {"statistic": f"value[{last},de]", "expected": rows[last]["de"], "tolerance": 1e-9},
        {"statistic": f"value[{first},fr]", "expected": rows[first]["fr"], "tolerance": 1e-9},
        {"statistic": "max[de]", "expected": max(r["de"] for r in rows.values() if r["de"] is not None), "tolerance": 1e-9},
    ]
    vectors = [{"input": {"key": last, "column": "de"}, "expected": rows[last]["de"], "origin": "source"}, {"input": {"key": first, "column": "fr"}, "expected": rows[first]["fr"], "origin": "source"}, {"input": "2000-S1", "expected": False, "origin": "derived"}]
    return lookup_entry(
        f"eu-statutory-monthly-minimum-wage-history-{first[:4]}-{last[:4]}", f"Statutory gross monthly minimum wages in euro, half-yearly {first[:4]} to {last[:4]}, every country reported by Eurostat", "employment", "EU",
        rows, {"dataflow": table.flow, "key": "S.EUR.", "url": table.source.url, "countries": {geo.lower(): table.names.get(geo, geo) for geo in geos}}, vectors, items, tests,
        ["minimum-wage", "wages", "history", "eurostat", "reference-table", "by-country"], HR_USE_CASES + ["hr-analytics", "personal-finance", "contract-indexation"],
        f"Gross monthly statutory minimum wages in euro on 1 January and 1 July of each year from {first[:4]} to {last[:4]}, from Eurostat dataflow earn_mw_cur (semi-annual data, currency EUR). "
        "Rows are keyed by the Eurostat half-year label (for example 2026-S1) and carry the first day of that half in the from column, so a generator can pick the minimum wage in force on any date; "
        "the other columns are the lower-case geo codes, listed with their English names under countries, with null where a country has no statutory minimum wage or no value for the half-year. " + EUROSTAT_LICENSE_NOTE,
        (rows[first]["from"], f"{last[:4]}-12-31"),
        assumed=[{"parameter": "rows[*].from", "value": "1 January for S1, 1 July for S2", "method": "derived", "rationale": "Eurostat's bi-annual series reports the minimum wage in force on 1 January and 1 July; the from date restates the half-year label as that reference day."}],
    )


# ---------------------------------------------------------------- Germany


def statute_section(source: Source, section: str) -> str:
    """Plain text of one section (``enbez``) of a Gesetze-im-Internet XML law, read from the zip's single XML member."""
    archive = zipfile.ZipFile(io.BytesIO(source.raw))
    xml = next(archive.read(m) for m in archive.namelist() if m.endswith(".xml")).decode("utf-8")
    for norm in re.findall(r"<norm[^>]*>(.*?)</norm>", xml, re.DOTALL):
        label = re.search(r"<enbez>(.*?)</enbez>", norm)
        if label and label.group(1) == section:
            return collapse(re.sub(r"<[^>]+>", " ", norm))
    raise ValueError(f"section {section} not found in {source.url}")


def german_contribution_rates() -> dict:
    laws = {
        "pension": ("bsv_2018", "§ 1", r"in der allgemeinen Rentenversicherung (\d+,\d) Prozent", "Beitragssatzverordnung 2018 (BSV 2018), § 1"),
        "health_general": ("sgb_5", "§ 241", r"Der allgemeine Beitragssatz beträgt (\d+,\d) Prozent", "SGB V § 241 Allgemeiner Beitragssatz"),
        "health_reduced": ("sgb_5", "§ 243", r"Der ermäßigte Beitragssatz beträgt (\d+,\d) Prozent", "SGB V § 243 Ermäßigter Beitragssatz"),
        "long_term_care": ("pbav_2025", "§ 1", r"zum 1. Januar 2025 auf (\d+,\d) Prozent", "Pflege-Beitragssatz-Anpassungsverordnung 2025 (PBAV 2025), § 1"),
        "unemployment": ("sgb_3", "§ 341", r"Der Beitragssatz beträgt (\d+,\d) Prozent", "SGB III § 341 Beitragssatz und Beitragsbemessung"),
    }
    sources = {slug: Source(f"{GII}/{slug}/xml.zip") for slug in {law[0] for law in laws.values()}}
    slabs: dict[str, float] = {}
    basis: dict[str, str] = {}
    items = []
    for name, (slug, section, pattern, citation) in laws.items():
        text = statute_section(sources[slug], section)
        match = re.search(pattern, text)
        if match is None:
            raise ValueError(f"{citation}: rate not found")
        slabs[name] = float(match.group(1).replace(",", "."))
        basis[name] = citation
        snippet = text[match.start() : match.end()]
        items.append(sources[slug].cite(BMJ, f"Gesetze im Internet, {slug.upper().replace('_', ' ')} (XML archive)", f"{citation}, text", match.group(1), "text", snippet, UNSTATED))
    sharing = statute_section(sources["sgb_5"], "§ 249")
    sharing_match = re.search(r"tragen die nach dem Arbeitsentgelt zu bemessenden Beiträge jeweils zur Hälfte", sharing)
    if sharing_match is None:
        raise ValueError("SGB V § 249 cost-sharing sentence not found")
    items.append(sources["sgb_5"].cite(BMJ, "Gesetze im Internet, SGB 5 (XML archive)", "SGB V § 249 Absatz 1, text", "jeweils zur Hälfte", "text", sharing_match.group(0), UNSTATED, role="supporting"))
    return {
        "id": "de-social-insurance-contribution-rates-2025",
        "title": "Germany statutory social insurance contribution rates in force from 1 January 2025: pension, health, long-term care and unemployment insurance",
        "kind": "rule",
        "domain": "tax",
        "region": "DE",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2025-01-01",
        "valid_to": None,
        "tags": ["social-contributions", "payroll", "social-insurance", "statute", "reference-table"],
        "use_cases": HR_USE_CASES + ["hr-analytics", "personal-finance", "tax-filing-demo"],
        "spec": {
            "implementation": "almanac.rules.rate_schedule",
            "parameters": {"slabs": slabs, "unit": "percent of contributory earnings", "legal_basis": basis, "sources": {slug: s.url for slug, s in sources.items()}},
            "vectors": [
                {"input": slabs["health_general"], "expected": True, "origin": "source"},
                {"input": slabs["pension"], "expected": True, "origin": "source"},
                {"input": slabs["long_term_care"], "expected": True, "origin": "source"},
                {"input": 12.5, "expected": False, "origin": "derived"},
            ],
        },
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(slabs), "tolerance": 0},
            {"statistic": "slab[health_general]", "expected": slabs["health_general"], "tolerance": 0},
            {"statistic": "slab[unemployment]", "expected": slabs["unemployment"], "tolerance": 0},
        ],
        "notes": (
            "Percentage contribution rates of the German statutory social insurance read from the consolidated laws on Gesetze im Internet: the general pension insurance rate fixed by the Beitragssatzverordnung 2018, "
            "the general and reduced statutory health insurance rates (SGB V, the reduced rate applies to members without sickness-benefit entitlement; a fund-specific supplementary rate under SGB V § 242 comes on top and is not in this entry), "
            "the long-term care insurance rate set from 1 January 2025 by the PBAV 2025 (surcharges and reductions by number of children under SGB XI § 55 are not in this entry), and the unemployment insurance rate (SGB III). "
            "SGB V § 249 states that employee and employer each bear half of the earnings-based health contributions. The pension rate of the BSV 2018 was set for 2018 and continues under SGB VI § 158(4) through annual "
            "announcements in the Bundesgesetzblatt that are not on this site, so a reviewer should confirm no later ordinance changed it. valid_from is the day the long-term care rate took effect; the other rates were already in force. "
            "Gesetze im Internet carries no licence statement, so the licence is recorded as unstated."
        ),
    }


# ---------------------------------------------------------------- OPM General Schedule


def opm_text(source: Source) -> str:
    """The salary table text with the fragments pypdf splits off a kerned '1' joined back onto their numbers."""
    text = Resource(url=source.url, content=source.raw, content_type="").text
    lines = text.split("\n")
    joined: list[str] = []
    for line in lines:
        if joined and joined[-1] and not joined[-1].endswith(" ") and joined[-1][-1].isdigit() and line[:1].isdigit():
            joined[-1] += line
        else:
            joined.append(line)
    return " ".join(joined)


def opm_grades(text: str, steps: int = 10, with_wgi: bool = True) -> dict[str, dict]:
    """Rows keyed GS-1 to GS-15 from the token stream that follows the 'Step 10' header."""
    body = text[text.index("Step 10") + len("Step 10") :]
    tokens = re.findall(r"V\s?ARIES|[\d,]+", body)
    per_row = 1 + steps + (1 if with_wgi else 0)
    rows: dict[str, dict] = {}
    position = 0
    for grade in range(1, 16):
        chunk = tokens[position : position + per_row]
        if int(chunk[0]) != grade:
            raise ValueError(f"expected grade {grade}, found {chunk[0]}")
        record = {f"step_{s}": int(chunk[s].replace(",", "")) for s in range(1, steps + 1)}
        if with_wgi:
            record["within_grade_increase"] = None if "ARIES" in chunk[-1] else int(chunk[-1].replace(",", ""))
        rows[f"GS-{grade}"] = record
        position += per_row
    return rows


def opm_base_table(source: Source) -> dict:
    text = opm_text(source)
    rows = opm_grades(text)
    title = "Salary Table 2026-GS, annual rates by grade and step (PDF)"
    items = [
        source.cite(OPM, title, "Grade 1, Step 1", "22,584", "currency:USD", "$ 22,584 $ 23,341", UNSTATED),
        source.cite(OPM, title, "Grade 15, Step 10", f"{rows['GS-15']['step_10']:,}", "currency:USD", f"{rows['GS-15']['step_9']:,} {rows['GS-15']['step_10']:,}", UNSTATED),
        source.cite(OPM, title, "Grade 7, within-grade amount", f"{rows['GS-7']['within_grade_increase']:,}", "currency:USD", f"{rows['GS-7']['step_10']:,} {rows['GS-7']['within_grade_increase']:,}", UNSTATED),
        source.cite(OPM, title, "table heading", "Effective January 2026", "text", "Effective January 2026 Annual Rates by Grade and Step", UNSTATED, role="supporting"),
    ]
    return {
        "id": "us-opm-general-schedule-base-pay-2026",
        "title": "US federal General Schedule base pay table 2026: annual rate by grade GS-1 to GS-15 and step 1 to 10, with within-grade increase (OPM)",
        "kind": "rule",
        "domain": "employment",
        "region": "US",
        "status": "license-review",
        "tier": "B",
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
        "tags": ["pay", "salary", "general-schedule", "federal", "pay-scale", "reference-table"],
        "use_cases": HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"table": "2026-GS", "general_increase_percent": 1, "rows": rows},
            "vectors": [
                {"input": {"key": "GS-1", "column": "step_1"}, "expected": rows["GS-1"]["step_1"], "origin": "source"},
                {"input": {"key": "GS-15", "column": "step_10"}, "expected": rows["GS-15"]["step_10"], "origin": "source"},
                {"input": {"key": "GS-7", "column": "within_grade_increase"}, "expected": rows["GS-7"]["within_grade_increase"], "origin": "source"},
                {"input": "GS-16", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": 15, "tolerance": 0},
            {"statistic": "value[GS-1,step_1]", "expected": rows["GS-1"]["step_1"], "tolerance": 0},
            {"statistic": "max[step_10]", "expected": rows["GS-15"]["step_10"], "tolerance": 0},
        ],
        "notes": (
            "Annual base pay in US dollars for each General Schedule grade and step effective January 2026, incorporating the 1 percent general increase, from the OPM salary table 2026-GS, "
            "with the within-grade increase amount for each grade (null for GS-1 and GS-2, where the table says the amount varies). Locality payments are added on top (see the locality entry). The PDF renders some digits with kerning that splits them across lines in extracted text, "
            "so the builder rejoins those fragments before parsing; cited cells are ones that extract cleanly. OPM states no licence on the table; US federal government works are generally not subject to copyright."
        ),
    }


LOCALITIES = {"DCB": "Washington-Baltimore-Arlington, DC-MD-VA-WV-PA", "NY": "New York-Newark, NY-NJ-CT-PA", "SF": "San Jose-San Francisco-Oakland, CA", "RUS": "Rest of U.S."}


def opm_locality_tables(sources: dict[str, Source]) -> dict:
    rows: dict[str, dict] = {}
    items = []
    for code, source in sources.items():
        text = opm_text(source)
        match = re.search(r"Locality Payment of ([\d.]+)%", text)
        if match is None:
            raise ValueError(f"{code}: locality percentage not found")
        grades = opm_grades(text, with_wgi=False)
        rows[code] = {"name": LOCALITIES[code], "locality_pay_percent": float(match.group(1)), "grades": grades}
        title = f"Salary Table 2026-{code}, annual rates by grade and step (PDF)"
        items.append(source.cite(OPM, title, "table heading, locality payment", match.group(1), "percent", match.group(0), UNSTATED))
        items.append(source.cite(OPM, title, "Grade 5, Step 1", f"{grades['GS-5']['step_1']:,}", "currency:USD", f"{grades['GS-4']['step_10']:,} 5 {grades['GS-5']['step_1']:,}", UNSTATED))
    return {
        "id": "us-opm-general-schedule-locality-pay-2026-selected",
        "title": "US General Schedule 2026 locality pay for Washington DC, New York, San Francisco and Rest of U.S. by grade and step (OPM)",
        "kind": "rule",
        "domain": "employment",
        "region": "US",
        "status": "license-review",
        "tier": "B",
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
        "tags": ["pay", "salary", "general-schedule", "locality-pay", "federal", "pay-scale", "reference-table"],
        "use_cases": HR_USE_CASES + ["hr-analytics", "workforce-planning"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"year": 2026, "rows": rows},
            "vectors": [
                {"input": {"key": "DCB", "column": "locality_pay_percent"}, "expected": rows["DCB"]["locality_pay_percent"], "origin": "source"},
                {"input": {"key": "RUS", "column": "locality_pay_percent"}, "expected": rows["RUS"]["locality_pay_percent"], "origin": "source"},
                {"input": "LA", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": items,
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[locality_pay_percent]", "expected": max(r["locality_pay_percent"] for r in rows.values()), "tolerance": 1e-9},
            {"statistic": "value[NY,locality_pay_percent]", "expected": rows["NY"]["locality_pay_percent"], "tolerance": 1e-9},
        ],
        "notes": (
            "Four of the 2026 OPM locality pay tables, keyed by OPM's table code: the locality payment percentage applied to the base General Schedule and the resulting annual rate for every grade and step "
            "(the grades mapping, keyed GS-1 to GS-15 with columns step_1 to step_10). Rates at GS-15 that would exceed the Executive Schedule level IV cap are published capped and kept as published. "
            "The Rest of U.S. table applies wherever no specific locality area is defined. The same kerning repair as the base table entry is applied before parsing. OPM states no licence on the tables."
        ),
    }


# ---------------------------------------------------------------- main


def main() -> int:
    soc = Source(SOC_URL)
    write(soc_2020_code_list(soc))

    sickness = Workbook(Source(SICKNESS_URL))
    for build in (sickness_annual, sickness_by_age_and_sex, sickness_by_region_and_sex, sickness_by_occupation, sickness_by_industry, sickness_by_employer):
        write(build(sickness))

    ashe = Source(ASHE_URL)
    write(ashe_pay_by_region(ashe, "Annual pay - gross", "annual-gross-pay", "currency:GBP", "gross annual pay"))
    write(ashe_pay_by_region(ashe, "Hourly pay - gross", "hourly-gross-pay", "currency:GBP", "gross hourly pay"))

    def oecd(flow: str, name: str, key: str, start: str, year: str) -> OecdTable:
        return OecdTable(flow, name, Source(oecd_url(flow, key, start)), year)

    write(oecd_wages(oecd("OECD.ELS.SAE,DSD_EARNINGS@AV_AN_WAGE,1.0", "average annual wages", "all", "2024", "2024")))
    write(oecd_minimum_wages(oecd("OECD.ELS.SAE,DSD_EARNINGS@MIN2AVE,1.0", "minimum relative to average wages of full-time workers", "all", "2024", "2024"), oecd("OECD.ELS.SAE,DSD_EARNINGS@MW_CURP,1.0", "minimum wages at current prices in national currency units", "all", "2024", "2024")))
    write(oecd_tenure(oecd("OECD.ELS.SAE,DSD_TENURE@DF_TENURE_AVE,1.0", "employment by job tenure intervals, average job tenure", "all", "2024", "2024")))
    write(oecd_temporary(oecd("OECD.ELS.SAE,DSD_TEMP@DF_TEMP_I,1.0", "employment by permanency of the job, incidence", "all", "2024", "2024")))
    write(oecd_part_time(oecd("OECD.ELS.SAE,DSD_FTPT@DF_FTPT_COMMON_INC,1.0", "incidence of full-time and part-time employment, OECD-harmonised definition", "all", "2024", "2024")))
    write(oecd_unemployment_duration(oecd("OECD.ELS.SAE,DSD_DUR@DF_DUR_I,1.0", "incidence of unemployment by duration", "all", "2024", "2024")))
    write(oecd_epl(oecd("OECD.ELS.JAI,DSD_EPL@DF_EPL,1.0", "strictness of employment protection", "all", "2023", "2024")))
    write(oecd_retirement(oecd("OECD.ELS.SPD,DSD_PAG@DF_PAG,1.0", "pensions at a glance", "all", "2022", "2024")))
    write(oecd_tax_wedge(oecd("OECD.CTP.TPS,DSD_TAX_WAGES_DECOMP@DF_TW_DECOMP,2.1", "labour taxation, tax wedge decompositions", ".AV_TW+NPATR+EESSC+ERSSC_PT..S_C0.AW100..A", "2025", "2025")))
    write(oecd_participation(oecd("OECD.ELS.SAE,DSD_LFS@DF_LFS_INDIC,1.1", "employment and unemployment by five-year age group and sex, indicators", ".LF_RATE....", "2024", "2024")))
    write(oecd_hours_bands(oecd("OECD.ELS.SAE,DSD_HW@DF_USL_WK_HRS,1.0", "usual hours worked by weekly hour bands", "all", "2024", "2024")))
    write(oecd_average_hours(oecd("OECD.ELS.SAE,DSD_HW@DF_AVG_USL_WK_WKD,1.0", "average usual weekly hours worked on the main job", "all", "2024", "2024")))

    def ilo(indicator: str, name: str, timefrom: str) -> IloTable:
        return IloTable(indicator, name, Source(ilo_url(indicator, timefrom)))

    write(ilo_monthly_earnings(ilo("EAR_EMTA_SEX_OCU_CUR_NB_A", "average monthly earnings of employees by sex, occupation and currency", "2023")))
    write(ilo_employment_by_occupation(ilo("EMP_TEMP_SEX_OCU_NB_A", "employment by sex and occupation, thousands", "2024")))
    write(ilo_informal(ilo("EMP_NIFL_SEX_RT_A", "informal employment rate by sex", "2023")))
    write(ilo_hours(ilo("HOW_TEMP_SEX_ECO_NB_A", "average weekly hours actually worked per employed person by sex and economic activity", "2024")))

    names = codelist("GEO")

    def eurostat(flow: str, name: str, key: str, start: str, end: str) -> EurostatTable:
        return EurostatTable(flow, name, Source(data_url(flow, key, start, end)), names)

    write(eurostat_vacancy_rate(eurostat("jvs_q_nace2", "job vacancy statistics by NACE Rev. 2 activity, quarterly data", "Q.NSA..GE10.JVR.", "2025-Q4", "2025-Q4"), "2025-Q4"))
    write(eurostat_temporary(eurostat("lfsq_etpga", "temporary employees as percentage of the total number of employees, quarterly data", "Q.PC.T+M+F.Y15-64.", "2026-Q1", "2026-Q2")))
    write(eurostat_part_time(eurostat("lfsa_eppga", "part-time employment as percentage of the total employment, by sex and age", "A.PC.T+M+F.Y15-64.", "2025", "2025"), "2025"))
    write(eurostat_transitions(eurostat("lfsi_long_q", "labour market transitions, quarterly data", "Q..NSA..T.", "2026-Q1", "2026-Q1"), "2026-Q1"))
    write(eurostat_minimum_wage_history(eurostat("earn_mw_cur", "monthly minimum wages, bi-annual data", "S.EUR.", "2016-01-01", "2026-12-31")))

    write(german_contribution_rates())

    write(opm_base_table(Source(f"{OPM_TABLES}/GS.pdf")))
    write(opm_locality_tables({code: Source(f"{OPM_TABLES}/{code}.pdf") for code in LOCALITIES}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

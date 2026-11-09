"""Regenerate the Saudi Arabia statistics entries from GASTAT and SAMA publications.

Sources, all static files served under fixed document URLs:

* General Authority for Statistics (GASTAT) workbooks from the statistics
  publication pages of stats.gov.sa: the Labour Force Survey tables and the
  register-based labour market tables (GOSI, civil service and domestic
  workers) for the second quarter of 2026, the 2024 population estimates, the
  September 2026 consumer price index and average price tables, the 2023
  Household Income and Consumption Expenditure Survey, the tourism
  establishments tables for the second quarter of 2026 (Ministry of Tourism
  data) and the 2024 healthcare establishments tables (Ministry of Health
  data).
* Saudi Central Bank (SAMA) Monthly Statistical Bulletin workbook for
  September 2026: point-of-sale, e-commerce, ATM, SARIE and instant payment
  activity and personal transfers abroad, plus the weekly point-of-sale report
  PDF for the four weeks to 31 October 2026.

Every value is read from the fetched bytes. Evidence values are the cell
strings exactly as the workbook XML stores them, and each snippet and value is
checked against the same searchable text the verifier builds before an entry
is written. Run from the repository root:

    uv run python tools/build_sa_stats.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

GASTAT = "General Authority for Statistics (GASTAT)"
SAMA = "Saudi Central Bank (SAMA)"
# Neither publisher attaches an SPDX licence to these files. GASTAT's website use policy permits reuse with
# attribution, but that page is not byte-stable, so it cannot be cited; entries stay at license-review.
LICENSE = "unstated"
STATUS = "license-review"

DOCS = "https://www.stats.gov.sa/documents/20117"
LFS_URL = f"{DOCS}/2435273/Labor+Market+Statistics+Q2+2026+EN+%282%29.xlsx/1eb7c5ce-46c1-c8b3-b8e6-9538d3e76422"
REGISTER_URL = f"{DOCS}/2435273/Register-based+Labour+Market+Statistics-+Q2+2026+EN.xlsx/fbbb6b2c-5d38-ae17-3cab-a54c3df75356"
POPULATION_URL = f"{DOCS}/2435273/Population_Estimates_Statistics_2024_EN.xlsx_fixed_2514649/6703cee3-3703-18e0-fc1b-956a76d75847"
POPULATION_PDF_URL = f"{DOCS}/2435273/Population_Estimates_Publication_2024_EN.pdf_fixed_3226306/7d123c57-1626-7d2f-ba7f-8a719f928f28"
CPI_URL = f"{DOCS}/2435267/CPI+Tables-Sep+2026-AR-EN+%281%29.xlsx/33c4aa4c-84da-cd22-da4a-c1b045b28e69"
PRICES_URL = f"{DOCS}/2435259/APGSTables-Sep2026-AR-EN.xlsx/9196b580-40d4-b507-77a9-7bd042a3a2ed"
HIES_URL = f"{DOCS}/2435273/Publication_tables_of_Household_Income_and_Consumption_Expenditure_Survey_2023_2_%281%29.xlsx_fixed_2613883/f482083a-b92a-ab65-d41b-7d1bf7c23e6e"
TOURISM_URL = f"{DOCS}/2435281/Tourism+Establishments+Statistics+Q2+of+2026+EN+%281%29.xlsx/55242e87-417c-29f8-5f27-53c918fc9d5f"
HEALTH_URL = f"{DOCS}/2435273/Healthcare_Establishments_and_workforce_Statistics_2024_EN_%281%29.xlsx_fixed_4215695/82a743c6-210f-5e89-60c8-97593875f8d9"
SAMA_BULLETIN_URL = "https://www.sama.gov.sa/en-US/Statistics/MonthlyStatistics/Monthly_Statistical_Bulletin_For_Sep_2026.xlsx"
SAMA_POS_WEEKLY_URL = "https://www.sama.gov.sa/en-US/Statistics/Indices/POS_EN/Weekly_Points_of_Sale_Transactions_Report_31st_Oct_2026.pdf"

SA_TAGS = ["saudi-arabia", "gcc"]
GROUPS = ("saudi-male", "saudi-female", "saudi-total", "non-saudi-male", "non-saudi-female", "non-saudi-total", "total-male", "total-female", "total-total")
LICENSE_NOTE = (
    "Neither file carries a licence statement, so the entry stays at license-review; GASTAT's website use policy "
    "permits reuse, including commercial reuse, with GASTAT acknowledged as the source and changes indicated."
)
SAMA_LICENSE_NOTE = "SAMA publishes no licence for its statistical files, so the entry stays at license-review."


# ---------------------------------------------------------------- fetched resources


def collapse(text: str) -> str:
    return " ".join(text.split())


def searchable_text(raw: bytes) -> str:
    """The text the verifier searches: PDF page text, the text members of a ZIP (XLSX), or the decoded bytes."""
    if raw.startswith(b"%PDF"):
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    if raw.startswith(b"PK\x03\x04"):
        archive = zipfile.ZipFile(io.BytesIO(raw))
        members = (i for i in archive.infolist() if i.filename.lower().endswith((".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".tsv")))
        return "\n".join(f"== {i.filename} ==\n" + archive.read(i).decode("utf-8", errors="replace") for i in members)
    return raw.decode("utf-8", errors="replace")


class Source:
    """A fetched publication whose evidence items are checked against its searchable text when they are cited."""

    def __init__(self, publisher: str, title: str, url: str) -> None:
        self.publisher, self.title, self.url = publisher, title, url
        self.raw = fetch(url)
        self._text: str | None = None

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = collapse(searchable_text(self.raw))
        return self._text

    def cite(self, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        for needle, what in ((snippet, "snippet"), (str(value), "value")):
            if collapse(needle) not in self.text:
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        if len(snippet.split()) > 24:
            raise ValueError(f"snippet exceeds 24 words: {snippet!r}")
        return evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, LICENSE, self.raw, role)


class Workbook(Source):
    """An XLSX publication read both through openpyxl and as raw sheet XML, so evidence quotes stored cell text."""

    def __init__(self, publisher: str, title: str, url: str) -> None:
        super().__init__(publisher, title, url)
        self.book = openpyxl.load_workbook(io.BytesIO(self.raw), data_only=True)
        self._archive = zipfile.ZipFile(io.BytesIO(self.raw))
        self._sheet_xml: dict[str, str] = {}
        self._paths = self._sheet_paths()

    def _sheet_paths(self) -> dict[str, str]:
        workbook_xml = self._archive.read("xl/workbook.xml").decode("utf-8")
        rels_xml = self._archive.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        targets = {m.group(1): m.group(2) for m in re.finditer(r'<Relationship [^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"', rels_xml)}
        targets.update({m.group(2): m.group(1) for m in re.finditer(r'<Relationship [^>]*?Target="([^"]+)"[^>]*?Id="([^"]+)"', rels_xml)})
        paths = {}
        for m in re.finditer(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', workbook_xml):
            target = targets[m.group(2)].lstrip("/")
            paths[m.group(1).replace("&amp;", "&")] = target if target.startswith("xl/") else f"xl/{target}"
        return paths

    def sheet_name(self, name: str) -> str:
        matches = [s for s in self.book.sheetnames if s.strip() == name.strip()]
        if len(matches) != 1:
            raise KeyError(f"sheet {name!r} not found uniquely in {self.url}: {self.book.sheetnames}")
        return matches[0]

    def sheet(self, name: str):
        return self.book[self.sheet_name(name)]

    def stored(self, sheet: str, ref: str) -> str:
        """The text of a cell's <v> element exactly as the workbook stores it."""
        name = self.sheet_name(sheet)
        if name not in self._sheet_xml:
            self._sheet_xml[name] = self._archive.read(self._paths[name]).decode("utf-8")
        match = re.search(rf'<c r="{ref}"[^>]*?>(?:<f[^>]*?(?:/>|>.*?</f>))?<v>([^<]*)</v>', self._sheet_xml[name])
        if match is None:
            raise KeyError(f"no stored value for {name}!{ref}")
        return match.group(1)

    def cite_cell(self, sheet: str, ref: str, what: str, snippet: str, unit: str = "decimal", role: str = "primary") -> dict:
        """Evidence for one numeric cell; the value is the stored text, which always appears verbatim in the sheet XML."""
        text = self.stored(sheet, ref)
        value: Any = int(text) if re.fullmatch(r"-?\d+", text) else (float(text) if repr(float(text)) == text else text)
        return self.cite(f"sheet {self.sheet_name(sheet).strip()}, cell {ref} ({what})", value, unit, snippet, role)


def text_of(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def find_cell(ws, predicate, start_row: int = 1) -> tuple[int, int]:
    for row in ws.iter_rows(min_row=start_row):
        for cell in row:
            if cell.value is not None and predicate(text_of(cell.value)):
                return cell.row, cell.column
    raise KeyError(f"no matching cell in sheet {ws.title!r} from row {start_row}")


def ref(row: int, column: int) -> str:
    return f"{get_column_letter(column)}{row}"


def r(value: float, digits: int) -> float:
    return round(float(value), digits)


# ---------------------------------------------------------------- nationality x sex tables


class GroupTable:
    """A GASTAT table whose columns are nationality (Saudi, Non Saudi, Total) by sex (Male, Female, Total).

    ``rows`` maps each row label to the nine values in GROUPS order; ``cells`` keeps the cell reference of every
    value so evidence can point at it.
    """

    def __init__(self, book: Workbook, sheet: str, title: str, label_column: int | None = None, stop: Iterable[str] = ("Total",)) -> None:
        self.book, self.sheet_name = book, sheet
        ws = book.sheet(sheet)
        title_row, _ = find_cell(ws, lambda t: t.startswith(title))
        header_row, first = find_cell(ws, lambda t: t == "Male", start_row=title_row)
        sexes = [text_of(ws.cell(header_row, first + i).value) for i in range(9)]
        if sexes != ["Male", "Female", "Total"] * 3:
            raise ValueError(f"{sheet}: unexpected sex header {sexes}")
        nationality = [text_of(ws.cell(header_row - 1, first + i).value) for i in (0, 3, 6)]
        if nationality[0] != "Saudi" or nationality[1] != "Non Saudi":
            raise ValueError(f"{sheet}: unexpected nationality header {nationality}")
        self.label_column = label_column or first - 1
        self.rows: dict[str, list[float]] = {}
        self.cells: dict[str, list[str]] = {}
        stops = set(stop)
        for row in range(header_row + 1, ws.max_row + 1):
            label = text_of(ws.cell(row, self.label_column).value)
            values = [ws.cell(row, first + i).value for i in range(9)]
            if not label or label.startswith("Source") or not all(isinstance(v, (int, float)) for v in values):
                if self.rows:
                    break
                continue
            self.rows[label] = [float(v) for v in values]
            self.cells[label] = [ref(row, first + i) for i in range(9)]
            if label in stops:
                break

    def value(self, label: str, group: str) -> float:
        return self.rows[label][GROUPS.index(group)]

    def cite(self, label: str, group: str, snippet: str, unit: str = "decimal") -> dict:
        return self.book.cite_cell(self.sheet_name, self.cells[label][GROUPS.index(group)], f"{label}, {group}", snippet, unit)


def percent_conditional(table: GroupTable, categories: list[str]) -> dict[str, dict]:
    """Per nationality-sex group, a categorical distribution whose shares are the published percentages / 100."""
    distributions = {}
    for index, group in enumerate(GROUPS):
        percents = {c: table.rows[c][index] for c in categories}
        distributions[group] = {
            "family": "categorical",
            "parameters": {"shares": {c: r(p / 100, 6) for c, p in percents.items()}, "percent": {c: r(p, 4) for c, p in percents.items()}},
        }
    return distributions


def count_conditional(table: GroupTable, categories: list[str], total_label: str) -> dict[str, dict]:
    """Per nationality-sex group, a categorical distribution of published counts with derived shares."""
    distributions = {}
    for index, group in enumerate(GROUPS):
        counts = {c: int(table.rows[c][index]) for c in categories}
        total = int(table.rows[total_label][index])
        if sum(counts.values()) != total:
            raise ValueError(f"{table.sheet_name}: {group} categories sum to {sum(counts.values())}, table total {total}")
        if total == 0:
            continue
        distributions[group] = {
            "family": "categorical",
            "parameters": {"shares": {c: r(n / total, 6) for c, n in counts.items()}, "counts": counts, "total": total},
        }
    return distributions


def conditional_spec(variable: str, given: str, distributions: dict) -> dict:
    return {"variable": variable, "unit": "ratio", "given": given, "distributions": distributions}


def share_tests(distributions: dict, picks: list[tuple[str, str]], tolerance: float = 0.004) -> list[dict]:
    tests = []
    for group, category in picks:
        tests.append({"statistic": f'share["{group}","{category}"]', "expected": distributions[group]["parameters"]["shares"][category], "tolerance": tolerance})
    for group in list(distributions)[:3]:
        tests.append({"statistic": f'sum_of_shares["{group}"]', "expected": 1, "tolerance": 0.002})
    return tests


def lookup_vectors(rows: dict, picks: list[tuple[str, str]], absent: str) -> list[dict]:
    vectors = [{"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": "source"} for key, column in picks]
    vectors.append({"input": picks[0][0], "expected": True, "origin": "source"})
    vectors.append({"input": absent, "expected": False, "origin": "derived", "note": "not a row of the table"})
    return vectors


def base(entry_id: str, title: str, kind: str, domain: str, tags: list[str], use_cases: list[str]) -> dict:
    if len(title) > 140:
        raise ValueError(f"title too long ({len(title)}): {title}")
    return {"id": entry_id, "title": title, "kind": kind, "domain": domain, "region": "SA", "status": STATUS, "tier": "A", "tags": SA_TAGS + tags, "use_cases": use_cases}


GROUP_NOTE = (
    "Groups are nationality (saudi, non-saudi, total) by sex (male, female, total), keyed as "
    "saudi-male, saudi-female, saudi-total, non-saudi-male and so on, matching the publication's nine columns."
)
ROUNDING = {"parameter": "rows", "value": "rounded", "method": "derived", "rationale": "Published values carry full floating-point precision; they are rounded for readability (rates and percentages to 4 decimals, riyal amounts to 2)."}


# ---------------------------------------------------------------- Labour Force Survey, Q2 2026


LFS_PERIOD = {"start": "2026-04-01", "end": "2026-06-30"}


def lfs_indicators(lfs: Workbook) -> dict:
    table = GroupTable(lfs, "1", "Main labour market indicators", stop=("Labour Force Participation rate",))
    names = {"Unemployment Rate": "unemployment_rate_percent", "Employment-to-population ratio": "employment_to_population_percent", "Labour Force Participation rate": "participation_rate_percent"}
    rows = {group: {column: r(table.value(label, group), 4) for label, column in names.items()} for group in GROUPS}
    entry = base("sa-labour-market-indicators-by-nationality-sex-2026q2", "Saudi Arabia unemployment, employment and participation rates by nationality and sex, Q2 2026 (GASTAT LFS)", "rule", "employment", ["labour-force", "unemployment", "participation", "nationality", "lfs", "gastat"], ["synthetic-employees", "hr-demo", "workforce-planning", "synthetic-customers"])
    return {
        **entry,
        "valid_from": LFS_PERIOD["start"],
        "valid_to": LFS_PERIOD["end"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "percent", "population": "aged 15 and over", "rows": rows},
            "vectors": lookup_vectors(rows, [("saudi-female", "unemployment_rate_percent"), ("non-saudi-male", "participation_rate_percent"), ("total-total", "employment_to_population_percent")], "gcc-total"),
        },
        "evidence": [
            table.cite("Unemployment Rate", "saudi-female", "Main labour market indicators by nationality and sex"),
            table.cite("Labour Force Participation rate", "non-saudi-male", "Labour Force Participation rate"),
            table.cite("Employment-to-population ratio", "total-total", "Employment-to-population ratio"),
            lfs.cite("sheet Index, title", "Labour Market Statistics, KSA, Second Quarter 2026", "text", "Labour Market Statistics, KSA, Second Quarter 2026"),
        ],
        "assumed": [ROUNDING],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": 9, "tolerance": 0},
            {"statistic": "max[unemployment_rate_percent]", "expected": max(v["unemployment_rate_percent"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Headline Labour Force Survey rates for the second quarter of 2026 from GASTAT's Labour Market Statistics workbook, "
            "Table 1: unemployment rate, employment-to-population ratio and labour force participation rate for the population "
            f"aged 15 and over, in per cent. {GROUP_NOTE} Use the participation and unemployment rates to assign an employment "
            f"status to synthetic adults by nationality and sex. {LICENSE_NOTE}"
        ),
    }


def lfs_unemployment_series(lfs: Workbook) -> dict:
    table = GroupTable(lfs, "2-1", "Quarterly Unemployment rate by nationality and sex", stop=("2026 Q2",))
    series = []
    for label, values in table.rows.items():
        year, quarter = label.split()
        point = {"period": f"{year}-{quarter}", "value": r(values[GROUPS.index("total-total")], 4)}
        point.update({group.replace("-", "_"): r(v, 4) for group, v in zip(GROUPS, values) if group != "total-total"})
        series.append(point)
    columns = [g.replace("-", "_") for g in GROUPS if g != "total-total"]
    first, last = series[0]["period"], series[-1]["period"]
    entry = base("sa-unemployment-rate-by-nationality-sex-quarterly-2021-2026", f"Saudi Arabia unemployment rate by nationality and sex, quarterly {first} to {last} (GASTAT LFS)", "temporal", "employment", ["unemployment", "labour-force", "quarterly", "time-series", "nationality", "lfs", "gastat"], ["hr-demo", "workforce-planning", "credit-risk", "demand-forecasting"])
    return {
        **entry,
        "observed_period": {"start": "2021-01-01", "end": LFS_PERIOD["end"]},
        "spec": {"variable": "unemployment_rate_percent", "unit": "percent", "frequency": "quarterly", "columns": columns, "series": series},
        "evidence": [
            table.cite("2026 Q2", "total-total", "Quarterly Unemployment rate by nationality and sex - time series"),
            table.cite("2021 Q1", "saudi-female", "Year / Quarter"),
            table.cite("2026 Q2", "saudi-male", "Data collection method"),
        ],
        "assumed": [{**ROUNDING, "parameter": "series"}],
        "tests": [
            {"statistic": f"value[{last}]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": f"column[saudi_female,{first}]", "expected": series[0]["saudi_female"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Quarterly unemployment rate (per cent, population aged 15 and over) from GASTAT's Labour Force Survey, Table 2-1 of "
            "the Q2 2026 Labour Market Statistics workbook. value is the national rate; the other columns are the nationality by "
            "sex rates. The 2026 Q1 row is stored in the workbook rounded to one decimal, unlike the other quarters. GASTAT notes "
            "the collection mode changed over the period (telephone interviews to Q1 2022, mixed personal and telephone "
            f"interviews afterwards, personal interviews only in Q1 2025), so level shifts can reflect method. {LICENSE_NOTE}"
        ),
    }


def lfs_unemployment_by_region(lfs: Workbook) -> dict:
    table = GroupTable(lfs, "2-4", "Unemployment Rate by nationality, sex and administrative region")
    rows = {label: {g: r(v, 4) for g, v in zip(GROUPS, values)} for label, values in table.rows.items()}
    entry = base("sa-unemployment-rate-by-region-nationality-sex-2026q2", "Saudi Arabia unemployment rate by administrative region, nationality and sex, Q2 2026 (GASTAT LFS)", "rule", "employment", ["unemployment", "by-region", "nationality", "lfs", "gastat"], ["synthetic-employees", "hr-demo", "address-generation", "credit-risk"])
    return {
        **entry,
        "valid_from": LFS_PERIOD["start"],
        "valid_to": LFS_PERIOD["end"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "percent", "rows": rows},
            "vectors": lookup_vectors(rows, [("Riyadh", "saudi-female"), ("Jazan", "saudi-male"), ("Total", "total-total")], "Dubai"),
        },
        "evidence": [
            table.cite("Riyadh", "saudi-female", "Unemployment Rate by nationality, sex and administrative region"),
            table.cite("Jazan", "saudi-male", "Administrative Region"),
            table.cite("Total", "total-total", "Northern Border"),
        ],
        "assumed": [ROUNDING],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[saudi-female]", "expected": max(v["saudi-female"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Unemployment rate in per cent for each of the 13 administrative regions and the Kingdom, by nationality and sex, "
            f"from Table 2-4 of GASTAT's Q2 2026 Labour Market Statistics workbook. Region names are GASTAT's English labels. {GROUP_NOTE} "
            f"Small cells (for example non-Saudi women in Al-Baha) can be zero or volatile because they rest on few survey respondents. {LICENSE_NOTE}"
        ),
    }


def lfs_employed_distribution(lfs: Workbook, sheet: str, title: str, entry_id: str, entry_title: str, variable: str, tags: list[str], picks: list[tuple[str, str]], classification: str) -> dict:
    table = GroupTable(lfs, sheet, title)
    categories = [c for c in table.rows if c != "Total"]
    distributions = percent_conditional(table, categories)
    entry = base(entry_id, entry_title, "conditional", "employment", tags + ["nationality", "lfs", "gastat"], ["synthetic-employees", "hr-demo", "workforce-planning", "company-generation"])
    first, second = picks[0], picks[1]
    return {
        **entry,
        "observed_period": LFS_PERIOD,
        "spec": conditional_spec(variable, "nationality_sex", distributions),
        "evidence": [
            table.cite(first[1], first[0], title),
            table.cite(second[1], second[0], second[1]),
            lfs.cite("sheet Index, title", "Labour Market Statistics, KSA, Second Quarter 2026", "text", "Labour Market Statistics, KSA, Second Quarter 2026"),
        ],
        "assumed": [{"parameter": "distributions.*.parameters.shares", "value": "percent / 100", "method": "derived", "rationale": "The table publishes percentage distributions of the employed; shares are those percentages divided by 100 and rounded to 6 decimals. The published percentages sit beside the shares, and each group's column totals 100 in the source."}],
        "tests": share_tests(distributions, picks),
        "notes": (
            f"Percentage distribution of employed persons (Labour Force Survey, Q2 2026) by {classification}, for each nationality "
            f"and sex group, from Table {sheet} of GASTAT's Labour Market Statistics workbook. {GROUP_NOTE} 'Undefined' is GASTAT's "
            f"own category for unclassified responses and is kept so shares sum to one. {LICENSE_NOTE}"
        ),
    }


def lfs_wages(lfs: Workbook, sheet: str, title: str, entry_id: str, entry_title: str, dimension: str, picks: list[tuple[str, str]], absent: str) -> dict:
    table = GroupTable(lfs, sheet, title)
    rows = {label: {g: r(v, 2) for g, v in zip(GROUPS, values)} for label, values in table.rows.items()}
    entry = base(entry_id, entry_title, "rule", "employment", ["wages", "earnings", "nationality", "lfs", "gastat"], ["synthetic-employees", "payroll-demo", "hr-demo", "customer-segmentation"])
    return {
        **entry,
        "valid_from": LFS_PERIOD["start"],
        "valid_to": LFS_PERIOD["end"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "currency:SAR", "measure": "average monthly wage per paid employee in main work", "rows": rows},
            "vectors": lookup_vectors(rows, picks, absent),
        },
        "evidence": [
            table.cite(picks[0][0], picks[0][1], title, "currency:SAR"),
            table.cite(picks[1][0], picks[1][1], "Average Monthly Wages Includes", "currency:SAR"),
            table.cite("Total", "total-total", "Source : Estimated data from LFS - GaStat", "currency:SAR"),
        ],
        "assumed": [ROUNDING],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[total-total]", "expected": max(v["total-total"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            f"Average monthly wage in Saudi riyals per paid employee in main work, by {dimension}, nationality and sex, from "
            f"Table {sheet} of GASTAT's Q2 2026 Labour Market Statistics workbook (Labour Force Survey estimates covering paid "
            f"employees and paid apprentices who reported their wage). {GROUP_NOTE} These are survey means, so use them as the "
            f"centre of a wage distribution, not as a cap or floor. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- register-based labour market, Q2 2026


def register_conditional(reg: Workbook, sheet: str, title: str, entry_id: str, entry_title: str, variable: str, tags: list[str], picks: list[tuple[str, str]], total_label: str, use_cases: list[str], what: str) -> dict:
    table = GroupTable(reg, sheet, title, stop=(total_label,))
    categories = [c for c in table.rows if c != total_label]
    distributions = count_conditional(table, categories, total_label)
    entry = base(entry_id, entry_title, "conditional", "employment", tags + ["gosi", "social-insurance-register", "nationality", "gastat"], use_cases)
    return {
        **entry,
        "observed_period": LFS_PERIOD,
        "spec": conditional_spec(variable, "nationality_sex", distributions),
        "evidence": [
            table.cite(picks[0][1], picks[0][0], title, "count"),
            table.cite(picks[1][1], picks[1][0], "Preliminary data", "count"),
            table.cite(total_label, "total-total", "Data pulled on 02-08-2026", "count"),
        ],
        "assumed": [{"parameter": "distributions.*.parameters.shares", "value": "count / group total", "method": "derived", "rationale": "The table publishes counts; each share is the category count divided by the group's published total, rounded to 6 decimals. The builder checks that the categories add up to the published total."}],
        "tests": share_tests(distributions, picks),
        "notes": (
            f"Workers on the job registered with the General Organization for Social Insurance (GOSI) in the second quarter of 2026, "
            f"by {what}, for each nationality and sex group, from Table {sheet} of GASTAT's Register-based Labour Market Statistics "
            f"workbook (GOSI source, preliminary data pulled on 2 August 2026). The register covers private-sector employees and "
            f"public employees under the social insurance rules; civil-service staff, the security and military sectors and domestic "
            f"workers are outside it. {GROUP_NOTE} Counts sit beside the shares. {LICENSE_NOTE}"
        ),
    }


def register_sector(reg: Workbook) -> dict:
    table = GroupTable(reg, "2-3", "Registered in the General Organization of Social Insurance and Civil Service and Domestic Workers by nationality, sex and Sector", stop=("Domestic worker ***",))
    sector_names = {"Governmental*": "government (civil service)", "public**": "public (GOSI-registered)", "Private": "private", "Domestic worker ***": "domestic worker"}
    counts: dict[str, int] = {}
    for label, sector in sector_names.items():
        for group in ("saudi-male", "saudi-female", "non-saudi-male", "non-saudi-female"):
            nationality, sex = group.rsplit("-", 1)
            counts[f"{sector}|{nationality}|{sex}"] = int(table.value(label, group))
        if int(table.value(label, "total-total")) != sum(int(table.value(label, g)) for g in ("saudi-male", "saudi-female", "non-saudi-male", "non-saudi-female")):
            raise ValueError(f"2-3: {label} groups do not add up to the total")
    # Saudi domestic workers are structurally absent from the register, so their zero cells are left out.
    counts = {k: v for k, v in counts.items() if v}
    total = sum(counts.values())
    shares = {k: r(v / total, 6) for k, v in counts.items()}
    entry = base("sa-registered-workers-by-sector-nationality-sex-2026q2", "Saudi Arabia registered workers by sector, nationality and sex, Q2 2026 (GOSI, civil service and domestic workers)", "marginal", "employment", ["gosi", "civil-service", "domestic-workers", "sector", "nationality", "gastat"], ["synthetic-employees", "hr-demo", "workforce-planning", "payroll-demo"])
    return {
        **entry,
        "observed_period": LFS_PERIOD,
        "spec": {"variable": "sector_nationality_sex", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total}}},
        "evidence": [
            table.cite("Private", "non-saudi-male", "by nationality, sex and Sector", "count"),
            table.cite("Governmental*", "saudi-female", "The government sector : civil service regulations", "count"),
            table.cite("Domestic worker ***", "non-saudi-female", "Source: NIC and data owner MHRSD***", "count"),
            table.cite("public**", "saudi-male", "employees in the government sector subject to the insurance insurance regulations", "count"),
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "count / total", "method": "derived", "rationale": "Each share is the published count for a sector, nationality and sex cell divided by the sum of all sixteen cells. The builder checks each sector's four cells against its published total."}],
        "tests": [
            {"statistic": 'share["private|non-saudi|male"]', "expected": shares["private|non-saudi|male"], "tolerance": 0.004},
            {"statistic": 'share["domestic worker|non-saudi|female"]', "expected": shares["domestic worker|non-saudi|female"], "tolerance": 0.004},
            {"statistic": 'share["government (civil service)|saudi|female"]', "expected": shares["government (civil service)|saudi|female"], "tolerance": 0.004},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "Registered workers in the second quarter of 2026 by sector, nationality and sex, from Table 2-3 of GASTAT's "
            "Register-based Labour Market Statistics workbook. Categories are 'sector|nationality|sex'. Government means staff under "
            "the civil service regulations; public means government-sector staff registered with GOSI; private means GOSI-registered "
            "private-sector employees; domestic workers come from the National Information Center with MHRSD as data owner and "
            "are all non-Saudi. The security and military sectors and anyone not in these registers are excluded. GOSI and MHRSD "
            f"figures are preliminary. {LICENSE_NOTE}"
        ),
    }


def domestic_workers(reg: Workbook) -> dict:
    ws = reg.sheet("7-2")
    title_row, _ = find_cell(ws, lambda t: t.startswith("Non - Saudi domestic workers by Sex"))
    header_row, male_col = find_cell(ws, lambda t: t == "Male", start_row=title_row)
    if [text_of(ws.cell(header_row, male_col + i).value) for i in range(3)] != ["Male", "Female", "Total"]:
        raise ValueError("7-2: unexpected header")
    counts: dict[str, dict[str, int]] = {"male": {}, "female": {}, "total": {}}
    cells: dict[str, list[str]] = {}
    for row in range(header_row + 1, ws.max_row + 1):
        label = text_of(ws.cell(row, male_col - 1).value)
        if not label or label.startswith("Source"):
            break
        values = [ws.cell(row, male_col + i).value for i in range(3)]
        cells[label] = [ref(row, male_col + i) for i in range(3)]
        if label == "Total":
            totals = dict(zip(("male", "female", "total"), (int(v) for v in values)))
            break
        for sex, v in zip(("male", "female", "total"), values):
            counts[sex][label] = int(v)
    distributions = {}
    for sex, by_job in counts.items():
        if sum(by_job.values()) != totals[sex]:
            raise ValueError(f"7-2: {sex} occupations do not add up to the total")
        distributions[sex] = {"family": "categorical", "parameters": {"shares": {k: r(v / totals[sex], 6) for k, v in by_job.items()}, "counts": by_job, "total": totals[sex]}}
    entry = base("sa-domestic-workers-by-occupation-sex-2026q2", "Saudi Arabia non-Saudi domestic workers by household occupation and sex, Q2 2026 (GASTAT register data)", "conditional", "employment", ["domestic-workers", "occupation", "gastat"], ["synthetic-employees", "household-generation", "hr-demo"])
    return {
        **entry,
        "observed_period": LFS_PERIOD,
        "spec": conditional_spec("household_occupation", "sex", distributions),
        "evidence": [
            reg.cite_cell("7-2", cells["Drivers"][0], "Drivers, male", "Non - Saudi domestic workers by Sex and Main Groups of Household Occupations", "count"),
            reg.cite_cell("7-2", cells["Servants and house cleaners"][1], "Servants and house cleaners, female", "Servants and house cleaners", "count"),
            reg.cite_cell("7-2", cells["Total"][2], "Total, total", "Source: NIC and data owner MHRSD", "count"),
        ],
        "assumed": [{"parameter": "distributions.*.parameters.shares", "value": "count / sex total", "method": "derived", "rationale": "Shares are the published counts divided by the published total for each sex, rounded to 6 decimals; the builder checks the occupations add up to that total."}],
        "tests": [
            {"statistic": 'share["male","Drivers"]', "expected": distributions["male"]["parameters"]["shares"]["Drivers"], "tolerance": 0.004},
            {"statistic": 'share["female","Servants and house cleaners"]', "expected": distributions["female"]["parameters"]["shares"]["Servants and house cleaners"], "tolerance": 0.004},
            {"statistic": 'sum_of_shares["total"]', "expected": 1, "tolerance": 0.002},
        ],
        "notes": (
            "Non-Saudi domestic workers in the second quarter of 2026 by main household occupation group and sex, from Table 7-2 "
            "of GASTAT's Register-based Labour Market Statistics workbook (source: National Information Center, data owner MHRSD). "
            f"Occupation labels are GASTAT's English labels. Counts sit beside the shares. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- population estimates, mid-2024


def population(pop: Workbook, pdf: Source) -> list[dict]:
    ws = pop.book.worksheets[0]
    header_row, age_col = find_cell(ws, lambda t: t == "Age Group")
    columns = {}
    for col in range(age_col + 1, ws.max_column + 1):
        sex = text_of(ws.cell(header_row, col).value)
        block = next((text_of(ws.cell(header_row - 1, c).value) for c in range(col, age_col, -1) if ws.cell(header_row - 1, c).value is not None), "")
        if block.endswith("2024") and sex in ("Female", "Male", "Total"):
            nationality = {"Saudi 2024": "saudi", "Non-Saudi 2024": "non-saudi", "Total 2024": "total"}[block]
            columns[f"{nationality}-{sex.lower()}"] = col
    if len(columns) != 9:
        raise ValueError(f"population: found columns {columns}")
    ages, cells = [], {}
    for row in range(header_row + 1, ws.max_row + 1):
        label = text_of(ws.cell(row, age_col).value)
        if not label:
            continue
        cells[label] = {g: ref(row, c) for g, c in columns.items()}
        if label == "Total":
            break
        ages.append(label)

    def count(label: str, group: str) -> int:
        return int(ws[cells[label][group]].value)

    distributions = {}
    for group in GROUPS:
        counts = {a: count(a, group) for a in ages}
        total = count("Total", group)
        if sum(counts.values()) != total:
            raise ValueError(f"population: {group} ages do not add up")
        distributions[group] = {"family": "categorical", "parameters": {"shares": {a: r(n / total, 6) for a, n in counts.items()}, "counts": counts, "total": total}}
    period = {"start": "2024-07-01", "end": "2024-07-01"}
    mid_year = {"parameter": "observed_period", "value": "2024-07-01", "method": "assumed", "rationale": "GASTAT describes the estimates as the population in mid-2024 without naming a day; 1 July 2024 is used as the reference date."}
    cite_reference = pdf.cite("page 1, headline", "Total population exceeds 35 million by mid-2024", "text", "Total population exceeds 35 million by mid-2024", role="supporting")
    age = base("sa-population-by-age-nationality-sex-2024", "Saudi Arabia population by five-year age group given nationality and sex, mid-2024 (GASTAT population estimates)", "conditional", "demographics", ["population", "age", "nationality", "population-estimates", "gastat"], ["synthetic-customers", "person-generation", "household-generation", "insurance", "market-sizing"])
    age_entry = {
        **age,
        "observed_period": period,
        "spec": conditional_spec("age_group", "nationality_sex", distributions),
        "evidence": [
            pop.cite_cell(ws.title, cells["25-29"]["non-saudi-male"], "25-29, Non-Saudi 2024 male", "Non-Saudi 2024", "count"),
            pop.cite_cell(ws.title, cells["0-4"]["saudi-female"], "0-4, Saudi 2024 female", "Age Group", "count"),
            pop.cite_cell(ws.title, cells["Total"]["total-total"], "Total, Total 2024", "Total 2024", "count"),
            cite_reference,
        ],
        "assumed": [{"parameter": "distributions.*.parameters.shares", "value": "count / group total", "method": "derived", "rationale": "Shares are the published counts divided by the group's published total, rounded to 6 decimals; the builder checks the age groups add up to the total."}, mid_year],
        "tests": share_tests(distributions, [("non-saudi-male", "30-34"), ("saudi-female", "0-4"), ("total-total", "80+")]),
        "notes": (
            "Mid-2024 population estimates by five-year age group (open-ended 80+) for each nationality and sex group, from the "
            "'Population Estimates Statistics 2024' workbook GASTAT publishes beside its estimates release; the 2023 columns of "
            f"the same sheet are ignored. {GROUP_NOTE} The estimates are projected from the May 2022 census base. Counts sit "
            f"beside the shares. {LICENSE_NOTE}"
        ),
    }
    joint_counts = {f"{n}|{s}": count("Total", f"{n}-{s}") for n in ("saudi", "non-saudi") for s in ("male", "female")}
    total = count("Total", "total-total")
    if sum(joint_counts.values()) != total:
        raise ValueError("population: nationality and sex totals do not add up")
    shares = {k: r(v / total, 6) for k, v in joint_counts.items()}
    joint = base("sa-population-by-nationality-sex-2024", "Saudi Arabia population by nationality (Saudi, non-Saudi) and sex, mid-2024 (GASTAT population estimates)", "marginal", "demographics", ["population", "nationality", "sex", "population-estimates", "gastat"], ["synthetic-customers", "person-generation", "kyc-onboarding", "market-sizing"])
    joint_entry = {
        **joint,
        "observed_period": period,
        "spec": {"variable": "nationality_sex", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": joint_counts, "total": total}}},
        "evidence": [
            pop.cite_cell(ws.title, cells["Total"]["saudi-male"], "Total, Saudi 2024 male", "Saudi 2024", "count"),
            pop.cite_cell(ws.title, cells["Total"]["non-saudi-male"], "Total, Non-Saudi 2024 male", "Non-Saudi 2024", "count"),
            pop.cite_cell(ws.title, cells["Total"]["total-total"], "Total, Total 2024", "Total 2024", "count"),
            cite_reference,
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "count / total", "method": "derived", "rationale": "Shares are the four published nationality and sex totals divided by the published total population."}, mid_year],
        "tests": [
            {"statistic": 'share["non-saudi|male"]', "expected": shares["non-saudi|male"], "tolerance": 0.004},
            {"statistic": 'share["saudi|female"]', "expected": shares["saudi|female"], "tolerance": 0.004},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "Mid-2024 population of Saudi Arabia split by nationality (Saudi, non-Saudi) and sex, from the totals row of GASTAT's "
            "Population Estimates Statistics 2024 workbook. Categories are 'nationality|sex'. The non-Saudi population is strongly "
            "male because of the migrant workforce, so draw nationality and sex jointly rather than independently. "
            f"{LICENSE_NOTE}"
        ),
    }
    return [age_entry, joint_entry]


# ---------------------------------------------------------------- consumer prices, September 2026


DIVISION_KEYS = {
    "FOOD AND BEVERAGES": "food_and_beverages",
    "TOBACCO": "tobacco",
    "CLOTHING AND FOOTWEAR": "clothing_and_footwear",
    "HOUSING, WATER, ELECTRICITY, GAS AND OTHER FUELS": "housing_water_electricity_gas",
    "FURNISHINGS, HOUSEHOLD EQUIPMENT AND ROUTINE HOUSEHOLD MAINTENANCE": "furnishings_household_equipment",
    "HEALTH": "health",
    "TRANSPORT": "transport",
    "INFORMATION AND COMMUNICATION": "information_and_communication",
    "RECREATION, SPORT AND CULTURE": "recreation_sport_and_culture",
    "EDUCATION SERVICES": "education_services",
    "RESTAURANTS AND ACCOMMODATION SERVICES": "restaurants_and_accommodation",
    "INSURANCE AND FINANCIAL SERVICES": "insurance_and_financial_services",
    "PERSONAL CARE, SOCIAL PROTECTION AND MISCELLANEOUS GOODS AND SERVICES": "personal_care_and_miscellaneous",
}


def cpi_weights(cpi: Workbook) -> dict:
    ws = cpi.sheet("1.1")
    rows = {}
    for row in range(1, ws.max_row + 1):
        english = text_of(ws.cell(row, 9).value).upper()
        if english in DIVISION_KEYS and isinstance(ws.cell(row, 3).value, (int, float)):
            rows[english] = (row, float(ws.cell(row, 3).value))
        if len(rows) == len(DIVISION_KEYS):
            break
    if len(rows) != len(DIVISION_KEYS):
        raise ValueError(f"cpi 1.1: found {list(rows)}")
    weights = {name.title(): r(w, 4) for name, (_, w) in rows.items()}
    shares = {name.title(): r(w / 100, 6) for name, (_, w) in rows.items()}
    entry = base("sa-cpi-weights-by-coicop-division-2026", "Saudi Arabia CPI basket weights by COICOP 2018 division, 2026 (GASTAT)", "marginal", "retail", ["cpi", "coicop", "household-spending", "weights", "prices", "gastat"], ["retail-demo", "sales-generation", "pricing", "household-generation"])
    food_row, health_row = rows["FOOD AND BEVERAGES"][0], rows["HEALTH"][0]
    return {
        **entry,
        "observed_period": {"start": "2026-01-01", "end": "2026-09-30"},
        "spec": {"variable": "coicop_division", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "weights_percent": weights}}},
        "evidence": [
            cpi.cite_cell("1.1", ref(food_row, 3), "FOOD AND BEVERAGES weight", "Indices and Rates of Changes Summary by Expenditure Divisions, September 2026", "percent"),
            cpi.cite_cell("1.1", ref(health_row, 3), "HEALTH weight", "Weights are updated at the beginning of each year based on the chain-linking methodology.", "percent"),
            cpi.cite("sheet 1.1, base", "2023=100", "text", "2023=100", role="supporting"),
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "weight / 100", "method": "derived", "rationale": "The CPI weights are published in per cent of the basket; shares are those weights divided by 100 and rounded to 6 decimals."}],
        "tests": [
            {"statistic": 'share["Food And Beverages"]', "expected": shares["Food And Beverages"], "tolerance": 0.004},
            {"statistic": 'share["Transport"]', "expected": shares["Transport"], "tolerance": 0.004},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0002},
        ],
        "notes": (
            "Weights of the thirteen COICOP 2018 divisions in Saudi Arabia's consumer price index (base 2023=100) as shown in "
            "Table 1.1 of GASTAT's September 2026 CPI workbook. GASTAT updates the weights at the start of each year under its "
            "chain-linking method, so these are the 2026 weights. They describe the household consumption basket and suit "
            "allocating synthetic household or card spend across categories. Division names are GASTAT's English labels in title "
            f"case. {LICENSE_NOTE}"
        ),
    }


def cpi_series(cpi: Workbook) -> dict:
    index_ws, change_ws = cpi.sheet("5.1"), cpi.sheet("5.2")

    def header_columns(ws) -> tuple[int, dict[str, int]]:
        row, _ = find_cell(ws, lambda t: t == "General Index")
        found = {}
        for col in range(1, ws.max_column + 1):
            label = text_of(ws.cell(row, col).value).upper()
            if label == "GENERAL INDEX":
                found["general"] = col
            elif label in DIVISION_KEYS:
                found[DIVISION_KEYS[label]] = col
        if len(found) != len(DIVISION_KEYS) + 1:
            raise ValueError(f"{ws.title}: division columns {sorted(found)}")
        return row, found

    def monthly_rows(ws, header: int) -> dict[str, int]:
        months = {}
        for row in range(header + 1, ws.max_row + 1):
            year, month = ws.cell(row, 1).value, ws.cell(row, 2).value
            if isinstance(year, int) and isinstance(month, int):
                months[f"{year}-{month:02d}"] = row
        return months

    index_header, index_cols = header_columns(index_ws)
    change_header, change_cols = header_columns(change_ws)
    index_rows, change_rows = monthly_rows(index_ws, index_header), monthly_rows(change_ws, change_header)
    periods = [p for p in index_rows if "2025-10" <= p <= "2026-09"]
    if len(periods) != 12:
        raise ValueError(f"cpi: months found {periods}")
    columns = [k for k in DIVISION_KEYS.values()] + ["general_annual_change_percent"]
    series = []
    for period in periods:
        point = {"period": period, "value": r(index_ws.cell(index_rows[period], index_cols["general"]).value, 4)}
        point.update({key: r(index_ws.cell(index_rows[period], index_cols[key]).value, 4) for key in DIVISION_KEYS.values()})
        point["general_annual_change_percent"] = r(change_ws.cell(change_rows[period], change_cols["general"]).value, 4)
        series.append(point)
    entry = base("sa-cpi-by-coicop-division-monthly-2025-10-2026-09", "Saudi Arabia consumer price index by COICOP division, monthly October 2025 to September 2026 (GASTAT, 2023=100)", "temporal", "retail", ["cpi", "inflation", "coicop", "prices", "monthly", "time-series", "gastat"], ["retail-demo", "pricing", "contract-indexation", "demand-forecasting"])
    return {
        **entry,
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "spec": {"variable": "cpi_general_index", "unit": "decimal", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            cpi.cite_cell("5.1", ref(index_rows["2026-09"], index_cols["general"]), "General Index, September 2026", "Index Series by Expenditure Category, 2013-2026"),
            cpi.cite_cell("5.1", ref(index_rows["2025-10"], index_cols["transport"]), "TRANSPORT, October 2025", "COICOP (2018) Code:"),
            cpi.cite_cell("5.2", ref(change_rows["2026-09"], change_cols["general"]), "General Index annual change, September 2026", "Annual Rate of Change Series By Expenditure Category 2014-2026", "percent"),
        ],
        "assumed": [{**ROUNDING, "parameter": "series"}],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": "column[transport,2025-10]", "expected": series[0]["transport"], "tolerance": 0},
            {"statistic": "column[general_annual_change_percent,2026-09]", "expected": series[-1]["general_annual_change_percent"], "tolerance": 0},
            {"statistic": "count", "expected": 12, "tolerance": 0},
        ],
        "notes": (
            "Monthly consumer price index for Saudi Arabia (base 2023=100) for the general index (value) and the thirteen COICOP "
            "2018 divisions from Table 5.1 of GASTAT's September 2026 CPI workbook, with the general index's year-on-year change in per cent "
            "from Table 5.2. Use the division indices to drift synthetic prices month by month or to index contracts. "
            f"{LICENSE_NOTE}"
        ),
    }


def average_prices(prices: Workbook) -> dict:
    ws = prices.sheet("1")
    header_row, _ = find_cell(ws, lambda t: t == "Sep")
    rows, cells = {}, {}
    for row in range(header_row + 1, ws.max_row + 1):
        values = [ws.cell(row, c).value for c in range(2, 11)]
        item, unit = text_of(values[8]), text_of(values[7])
        if not item or not unit or not all(isinstance(v, (int, float)) for v in values[2:7]):
            continue
        if item in rows:
            raise ValueError(f"average prices: duplicate item {item!r}")
        rows[item] = {
            "unit": unit,
            "price_2026_09": r(values[2], 2),
            "price_2026_08": r(values[3], 2),
            "price_2025_09": r(values[4], 2),
            "change_vs_2026_08_percent": r(values[5], 2),
            "change_vs_2025_09_percent": r(values[6], 2),
        }
        cells[item] = row
    if len(rows) < 100:
        raise ValueError(f"average prices: only {len(rows)} items")
    entry = base("sa-average-retail-prices-2026-09", f"Saudi Arabia average retail prices of {len(rows)} goods and services, September 2026 (GASTAT)", "rule", "retail", ["prices", "retail-prices", "basket", "gastat"], ["retail-demo", "pricing", "sales-generation", "invoicing"])
    picks = [("Local Fresh Milk (Al Marai)", "price_2026_09"), ("Fresh Cattle Meat", "price_2026_09"), ("Local Eggs", "unit")]
    for item, _ in picks:
        if item not in rows:
            raise ValueError(f"average prices: {item!r} missing")
    return {
        **entry,
        "valid_from": "2026-09-01",
        "valid_to": "2026-09-30",
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "currency:SAR", "rows": rows},
            "vectors": lookup_vectors(rows, picks, "Imaginary Item"),
        },
        "evidence": [
            prices.cite_cell("1", ref(cells["Local Fresh Milk (Al Marai)"], 4), "Local Fresh Milk (Al Marai), Sep 2026", "Annual Changes in the Kingdom", "currency:SAR"),
            prices.cite_cell("1", ref(cells["Fresh Cattle Meat"], 4), "Fresh Cattle Meat, Sep 2026", "Fresh Cattle Meat", "currency:SAR"),
            prices.cite("sheet 1, Local Eggs unit", "1 plate", "text", "Local Eggs"),
        ],
        "assumed": [{"parameter": "rows", "value": "item rows only", "method": "derived", "rationale": "Section and group heading rows, which carry no prices, are dropped; item names and units are GASTAT's English labels and prices are rounded to 2 decimals."}],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
        ],
        "notes": (
            "Average consumer prices in Saudi riyals for the items GASTAT tracks in its monthly 'Average Prices of Goods and "
            "Services' release, September 2026, with the August 2026 and September 2025 prices and the percentage changes. Rows "
            "are keyed by GASTAT's English item label, which often names a brand, and carry the pack size in unit. Prices include "
            f"the brand and pack the survey prices, so they suit realistic retail baskets and invoice lines. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- household income and expenditure, 2023


def hies_table(hies: Workbook, sheet: str) -> tuple[dict[str, list[float]], dict[str, list[str]]]:
    """Rows of a HIES table keyed by the English half of the bilingual label, with Saudi, Non Saudi and Total values."""
    ws = hies.sheet(sheet)
    header_row, col = find_cell(ws, lambda t: t.endswith("Saudi") and t.startswith("السعوديين"))
    rows, cells = {}, {}
    for row in range(header_row + 1, ws.max_row + 1):
        label = ws.cell(row, col - 1).value
        values = [ws.cell(row, col + i).value for i in range(3)]
        if label is None or not all(isinstance(v, (int, float)) for v in values):
            if rows:
                break
            continue
        english = " ".join(str(label).split("\n")[-1].split())
        rows[english] = [float(v) for v in values]
        cells[english] = [ref(row, col + i) for i in range(3)]
    return rows, cells


def hies_by_region(hies: Workbook) -> dict:
    income, income_cells = hies_table(hies, "1-2")
    median, median_cells = hies_table(hies, "2-2")
    spending, spending_cells = hies_table(hies, "1-3")
    if not (list(income) == list(median) == list(spending)):
        raise ValueError("hies: region rows differ between tables")
    rows = {}
    for region in income:
        rows[region] = {}
        for i, nat in enumerate(("saudi", "non_saudi", "total")):
            rows[region][f"mean_disposable_income_{nat}"] = income[region][i]
            rows[region][f"median_disposable_income_{nat}"] = median[region][i]
            rows[region][f"mean_consumption_expenditure_{nat}"] = spending[region][i]
    entry = base("sa-household-income-expenditure-by-region-nationality-2023", "Saudi Arabia household monthly disposable income and consumption by region and nationality of head, 2023 (GASTAT HIES)", "rule", "income", ["household-income", "household-spending", "by-region", "nationality", "hies", "gastat"], ["household-generation", "synthetic-customers", "customer-segmentation", "credit-risk"])
    return {
        **entry,
        "valid_from": "2023-01-01",
        "valid_to": "2023-12-31",
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "currency:SAR", "period": "per household per month", "rows": rows},
            "vectors": lookup_vectors(rows, [("Riyadh", "mean_disposable_income_saudi"), ("Jazan", "median_disposable_income_total"), ("Total", "mean_consumption_expenditure_non_saudi")], "Doha"),
        },
        "evidence": [
            hies.cite_cell("1-2", income_cells["Riyadh"][0], "Riyadh, Saudi", "Average Household Monthly Disposable Income by Administrative Region and Nationality of Household Head", "currency:SAR"),
            hies.cite_cell("2-2", median_cells["Jazan"][2], "Jazan, Total", "Median Household Monthly Disposable Income by Administrative Region and Nationality of Household Head", "currency:SAR"),
            hies.cite_cell("1-3", spending_cells["Total"][1], "Total, Non Saudi", "Average Household Monthly Consumption Expenditure by Administrative Region and Nationality of Household Head", "currency:SAR"),
            hies.cite("sheet content, title", "Household Income and Consumption Expenditure Survey Indicators, KSA, 2023", "text", "Household Income and Consumption Expenditure Survey Indicators, KSA, 2023"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[mean_disposable_income_saudi]", "expected": max(v["mean_disposable_income_saudi"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Mean and median household monthly disposable income and mean household monthly consumption expenditure, in Saudi "
            "riyals, by administrative region and nationality of the household head (saudi, non_saudi, total), from Tables 1-2, "
            "2-2 and 1-3 of GASTAT's Household Income and Consumption Expenditure Survey 2023 workbook. GASTAT notes that 2023 is "
            "the first survey to use the disposable income and consumption expenditure method, so earlier rounds are not "
            "comparable. Use the mean and median together to fit a skewed income distribution per region and nationality. "
            f"{LICENSE_NOTE}"
        ),
    }


def hies_coicop(hies: Workbook) -> dict:
    rows, cells = hies_table(hies, "11-4")
    distributions = {}
    for i, nat in enumerate(("saudi", "non-saudi", "total")):
        amounts = {k: v[i] for k, v in rows.items()}
        total = sum(amounts.values())
        distributions[nat] = {"family": "categorical", "parameters": {"shares": {k: r(v / total, 6) for k, v in amounts.items()}, "mean_monthly_sar": amounts}}
    entry = base("sa-household-spending-by-coicop-nationality-2023", "Saudi Arabia household monthly cash consumption by COICOP division given nationality of head, 2023 (GASTAT HIES)", "conditional", "income", ["household-spending", "coicop", "nationality", "hies", "gastat"], ["retail-demo", "household-generation", "sales-generation", "customer-segmentation"])
    return {
        **entry,
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "spec": conditional_spec("coicop_division", "nationality_of_head", distributions),
        "evidence": [
            hies.cite_cell("11-4", cells["Food and beverages"][0], "Food and beverages, Saudi", "Average Household Monthly Final Monetary Consumption Expenditure by COICOP Divisions and Nationality of Household Head", "currency:SAR"),
            hies.cite_cell("11-4", cells["Restaurants and accommodation services"][1], "Restaurants and accommodation services, Non Saudi", "Restaurants and accommodation services", "currency:SAR"),
            hies.cite_cell("11-4", cells["Transport"][2], "Transport, Total", "Household Income and Consumption Expenditure Survey 2023", "currency:SAR"),
        ],
        "assumed": [{"parameter": "distributions.*.parameters.shares", "value": "division mean / sum of division means", "method": "derived", "rationale": "The table publishes mean monthly riyal amounts per division; each share is a division's amount over the sum of the thirteen amounts for that nationality, rounded to 6 decimals. GASTAT also publishes percentage shares (Table 12-4); these derived shares agree with them up to rounding."}],
        "tests": share_tests(distributions, [("saudi", "Food and beverages"), ("non-saudi", "Housing, water, electricity, gas and other fuels"), ("total", "Transport")]),
        "notes": (
            "Mean household monthly final monetary (cash) consumption expenditure in Saudi riyals by COICOP division, for "
            "households headed by a Saudi, by a non-Saudi, and overall, from Table 11-4 of GASTAT's Household Income and "
            "Consumption Expenditure Survey 2023 workbook. The riyal means sit beside the derived shares, so a generator can draw "
            f"both the category of a purchase and a plausible monthly budget per category. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- tourism establishments, Q2 2026


def tourism_regions(tour: Workbook) -> dict:
    def regional(sheet: str, columns: int) -> tuple[dict[str, list[float]], dict[str, list[str]]]:
        ws = tour.sheet(sheet)
        values, cells = {}, {}
        for row in range(1, ws.max_row + 1):
            if isinstance(ws.cell(row, 1).value, int) and isinstance(ws.cell(row, 2).value, str):
                name = text_of(ws.cell(row, 2).value)
                values[name] = [ws.cell(row, 3 + i).value for i in range(columns)]
                cells[name] = [ref(row, 3 + i) for i in range(columns)]
        if len(values) != 13:
            raise ValueError(f"tourism {sheet}: {len(values)} regions")
        return values, cells

    counts, count_cells = regional("2.1", 3)
    apartments_occupancy, _ = regional("2.3", 4)
    hotel_occupancy, hotel_occ_cells = regional("2.4", 4)
    apartments_adr, _ = regional("2.9", 4)
    hotel_adr, hotel_adr_cells = regional("2.10", 4)
    rows = {
        region: {
            "hotels": int(counts[region][1]),
            "serviced_apartments_and_other": int(counts[region][0]),
            "hotel_occupancy_rate": r(hotel_occupancy[region][3], 4),
            "serviced_apartment_occupancy_rate": r(apartments_occupancy[region][3], 4),
            "hotel_average_daily_rate_sar": r(hotel_adr[region][3], 2),
            "serviced_apartment_average_daily_rate_sar": r(apartments_adr[region][3], 2),
        }
        for region in counts
    }
    entry = base("sa-hotel-occupancy-and-daily-rate-by-region-2026q2", "Saudi Arabia licensed hotels, occupancy and average daily rate by region and facility type, Q2 2026 (GASTAT, Ministry of Tourism)", "rule", "tourism", ["hotels", "occupancy", "average-daily-rate", "by-region", "gastat", "ministry-of-tourism"], ["tourism-demo", "pricing", "capacity-planning", "payments-demo"])
    return {
        **entry,
        "valid_from": LFS_PERIOD["start"],
        "valid_to": LFS_PERIOD["end"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"occupancy_unit": "ratio", "rate_unit": "currency:SAR", "rows": rows},
            "vectors": lookup_vectors(rows, [("Makkah Al Mukarramah", "hotels"), ("Ar Riyadh", "hotel_occupancy_rate"), ("Tabuk", "hotel_average_daily_rate_sar")], "Dubai"),
        },
        "evidence": [
            tour.cite_cell("2.1", count_cells["Makkah Al Mukarramah"][1], "Makkah Al Mukarramah, Number of hotels", "Number of licensed tourist hospitality facilities by regions and facility type for Q2 of 2026", "count"),
            tour.cite_cell("2.4", hotel_occ_cells["Ar Riyadh"][3], "Ar Riyadh, quarterly average", "Occupancy rate in hotels by regions and month for Q2 of 2026", "ratio"),
            tour.cite_cell("2.10", hotel_adr_cells["Tabuk"][3], "Tabuk, quarterly average", "Average daily rate in hotels by regions and month for Q2 of 2026", "currency:SAR"),
            tour.cite("sheet 2.10, note", "The average daily rate does not include Value Added Tax (VAT) or municipal service fees.", "text", "The average daily rate does not include Value Added Tax (VAT) or municipal service fees.", role="supporting"),
        ],
        "assumed": [{"parameter": "rows", "value": "quarterly averages", "method": "derived", "rationale": "Occupancy and average daily rate are the 'Quarterly average' columns of Tables 2.3, 2.4, 2.9 and 2.10, rounded (occupancy to 4 decimals, rates to 2); facility counts are copied from Table 2.1."}],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": 13, "tolerance": 0},
            {"statistic": "max[hotel_average_daily_rate_sar]", "expected": max(v["hotel_average_daily_rate_sar"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Licensed tourist hospitality facilities, occupancy rate (share of rooms sold, 0 to 1) and average daily rate in Saudi "
            "riyals by administrative region for the second quarter of 2026, for hotels and for serviced apartments and other "
            "hospitality facilities, from GASTAT's Tourism Establishments Statistics workbook (Ministry of Tourism Tourism "
            "Monitoring Platform, preliminary data). Average daily rates exclude VAT and municipal fees. Region names are the "
            f"publication's English labels. {LICENSE_NOTE}"
        ),
    }


def tourism_quarterly(tour: Workbook) -> dict:
    occupancy, adr = tour.sheet("1.2"), tour.sheet("1.3")

    def quarters(ws) -> dict[str, tuple[int, float, float]]:
        out = {}
        for row in range(1, ws.max_row + 1):
            m = re.fullmatch(r"Q([1-4]) ?of (\d{4})", text_of(ws.cell(row, 1).value))
            if m:
                out[f"{m.group(2)}-Q{m.group(1)}"] = (row, float(ws.cell(row, 2).value), float(ws.cell(row, 3).value))
        return out

    occ, rate = quarters(occupancy), quarters(adr)
    if list(occ) != list(rate):
        raise ValueError("tourism: quarter lists differ")
    series = [{"period": p, "value": r(occ[p][2], 4), "serviced_apartment_occupancy_rate": r(occ[p][1], 4), "hotel_average_daily_rate_sar": r(rate[p][2], 2), "serviced_apartment_average_daily_rate_sar": r(rate[p][1], 2)} for p in occ]
    first, last = series[0]["period"], series[-1]["period"]
    entry = base("sa-hotel-occupancy-and-daily-rate-quarterly-2023-2026", f"Saudi Arabia hotel and serviced apartment occupancy and average daily rate, quarterly {first} to {last} (GASTAT)", "temporal", "tourism", ["hotels", "occupancy", "average-daily-rate", "quarterly", "time-series", "gastat", "ministry-of-tourism"], ["tourism-demo", "pricing", "demand-forecasting", "capacity-planning"])
    return {
        **entry,
        "observed_period": {"start": "2023-01-01", "end": "2026-06-30"},
        "spec": {"variable": "hotel_occupancy_rate", "unit": "ratio", "frequency": "quarterly", "columns": ["serviced_apartment_occupancy_rate", "hotel_average_daily_rate_sar", "serviced_apartment_average_daily_rate_sar"], "series": series},
        "evidence": [
            tour.cite_cell("1.2", ref(occ[last][0], 3), f"{last}, Occupancy rate in hotels", "Occupancy rate in tourist hospitality facilities", "ratio"),
            tour.cite_cell("1.3", ref(rate[first][0], 3), f"{first}, Average daily rate in hotels", "Average daily rate in tourist hospitality facilities", "currency:SAR"),
            tour.cite_cell("1.3", ref(rate[last][0], 2), f"{last}, serviced apartments", "Source: Ministry of Tourism - Tourism Monitoring Platform", "currency:SAR"),
        ],
        "assumed": [{**ROUNDING, "parameter": "series"}],
        "tests": [
            {"statistic": f"value[{last}]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": f"column[hotel_average_daily_rate_sar,{first}]", "expected": series[0]["hotel_average_daily_rate_sar"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Quarterly national occupancy rate (0 to 1; value is hotels) and average daily rate in Saudi riyals for hotels and for "
            "serviced apartments and other hospitality facilities, from Tables 1.2 and 1.3 of GASTAT's Q2 2026 Tourism "
            "Establishments Statistics workbook (Ministry of Tourism data, preliminary). Hotel rates peak in the second quarter in "
            f"some years because of the Hajj and Umrah seasons. Average daily rates exclude VAT and municipal fees. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- healthcare establishments, 2024


def hospitals(health: Workbook) -> dict:
    def regional(sheet: str) -> tuple[dict[str, list[int]], dict[str, list[str]]]:
        ws = health.sheet(sheet)
        header_row, col = find_cell(ws, lambda t: t == "Administrative region")
        if [text_of(ws.cell(header_row, col + i).value) for i in range(1, 4)] != ["Government", "Private", "Total"]:
            raise ValueError(f"health {sheet}: unexpected header")
        values, cells = {}, {}
        for row in range(header_row + 1, ws.max_row + 1):
            name = text_of(ws.cell(row, col).value)
            if not name or name.startswith("Source"):
                break
            values[name] = [int(ws.cell(row, col + i).value) for i in range(1, 4)]
            cells[name] = [ref(row, col + i) for i in range(1, 4)]
            if name == "Total":
                break
        return values, cells

    hosp, hosp_cells = regional("1")
    beds, bed_cells = regional("4")
    if list(hosp) != list(beds):
        raise ValueError("health: region lists differ")
    rows = {region: {"hospitals_government": hosp[region][0], "hospitals_private": hosp[region][1], "hospitals_total": hosp[region][2], "beds_government": beds[region][0], "beds_private": beds[region][1], "beds_total": beds[region][2]} for region in hosp}
    entry = base("sa-hospitals-and-beds-by-region-sector-2024", "Saudi Arabia hospitals and hospital beds by administrative region and sector, 2024 (GASTAT, Ministry of Health)", "rule", "healthcare", ["hospitals", "hospital-beds", "by-region", "gastat", "ministry-of-health"], ["health-demo", "claims-generation", "capacity-planning", "address-generation"])
    return {
        **entry,
        "valid_from": "2024-01-01",
        "valid_to": "2024-12-31",
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"unit": "count", "rows": rows},
            "vectors": lookup_vectors(rows, [("Riyadh", "hospitals_private"), ("Eastern Region", "beds_total"), ("Total", "beds_government")], "Kuwait"),
        },
        "evidence": [
            health.cite_cell("1", hosp_cells["Riyadh"][1], "Riyadh, Private", "Number of hospitals by administrative region and sector for 2024", "count"),
            health.cite_cell("4", bed_cells["Eastern Region"][2], "Eastern Region, Total", "Number of hospital beds by administrative region and sector for 2024", "count"),
            health.cite_cell("4", bed_cells["Total"][0], "Total, Government", "Source: Ministry of Health 2024", "count"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[beds_total]", "expected": max(v["beds_total"] for v in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Number of hospitals and hospital beds in 2024 by administrative region and sector (government, private), from Tables "
            "1 and 4 of GASTAT's Healthcare Establishments and Workforce Statistics 2024 workbook (Ministry of Health data). Use the "
            "counts to weight where synthetic hospital claims or admissions happen and how they split between public and private "
            f"providers. {LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- SAMA monthly bulletin, September 2026


BULLETIN_MONTHS = [f"2025-{m:02d}" for m in (10, 11, 12)] + [f"2026-{m:02d}" for m in range(1, 10)]


def bulletin_rows(sama: Workbook, sheet: str, period_column: int = 1) -> dict[str, int]:
    ws = sama.sheet(sheet)
    rows = {}
    for row in range(1, ws.max_row + 1):
        value = ws.cell(row, period_column).value
        if isinstance(value, datetime):
            rows[f"{value.year}-{value.month:02d}"] = row
    missing = [m for m in BULLETIN_MONTHS if m not in rows]
    if missing:
        raise ValueError(f"bulletin {sheet}: months missing {missing}")
    return rows


def expect_header(sama: Workbook, sheet: str, cells: dict[str, str]) -> None:
    ws = sama.sheet(sheet)
    for cell, label in cells.items():
        if text_of(ws[cell].value) != label:
            raise ValueError(f"bulletin {sheet}!{cell}: expected {label!r}, found {text_of(ws[cell].value)!r}")


def card_payments(sama: Workbook) -> dict:
    expect_header(sama, "30c", {"C10": "Sales", "D10": "Number of", "E10": "Number of Points", "J10": "Sales", "F11": "Mobile Transactions", "G11": "Cards Transactions"})
    expect_header(sama, "30a", {"C10": "ATMs*", "D10": "Cards Issued*", "K11": "Total", "N11": "Total"})
    pos, atm = bulletin_rows(sama, "30c"), bulletin_rows(sama, "30a")
    pos_ws, atm_ws = sama.sheet("30c"), sama.sheet("30a")
    series = []
    for month in BULLETIN_MONTHS:
        p, a = pos[month], atm[month]
        series.append({
            "period": month,
            "value": r(pos_ws[f"C{p}"].value, 1),
            "pos_transactions": int(pos_ws[f"D{p}"].value),
            "pos_terminals": int(pos_ws[f"E{p}"].value),
            "pos_nfc_mobile_transactions": int(pos_ws[f"F{p}"].value),
            "pos_nfc_card_transactions": int(pos_ws[f"G{p}"].value),
            "mada_ecommerce_sales_sar_thousand": r(pos_ws[f"J{p}"].value, 1),
            "mada_ecommerce_transactions": int(pos_ws[f"K{p}"].value),
            "atms": int(atm_ws[f"C{a}"].value),
            "cards_issued": int(atm_ws[f"D{a}"].value),
            "atm_transactions": int(atm_ws[f"K{a}"].value),
            "atm_cash_withdrawals_sar_million": r(atm_ws[f"N{a}"].value, 2),
        })
    columns = [k for k in series[0] if k not in ("period", "value")]
    entry = base("sa-card-payments-pos-ecommerce-atm-monthly-2025-10-2026-09", "Saudi Arabia POS, mada e-commerce and ATM activity, monthly October 2025 to September 2026 (SAMA)", "temporal", "payments", ["pos", "card-payments", "ecommerce", "mada", "atm", "monthly", "time-series", "sama"], ["payments-demo", "fintech-demo", "retail-demo", "demand-forecasting"])
    last, first = pos[BULLETIN_MONTHS[-1]], pos[BULLETIN_MONTHS[0]]
    return {
        **entry,
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "spec": {"variable": "pos_sales_sar_thousand", "unit": "currency:SAR", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            sama.cite_cell("30c", f"C{last}", "Total Points of Sale Transactions, Sales, September 2026", "Table 30c: Points of Sale Transactions and E-Commerce Transactions", "currency:SAR"),
            sama.cite_cell("30c", f"K{first}", "E-Commerce Transactions Using Mada Cards, Number, October 2025", "E-Commerce Transactions Using Mada Cards", "count"),
            sama.cite_cell("30a", f"K{atm[BULLETIN_MONTHS[-1]]}", "No. of Transactions, Total, September 2026", "Table 30a: Automated Teller Machines Statistics", "count"),
            sama.cite("sheet 30c, footnote", "it does not include transactions by Visa, MasterCard and other credit cards.", "text", "it does not include transactions by Visa, MasterCard and other credit cards.", role="supporting"),
        ],
        "assumed": [{"parameter": "series", "value": "rounded", "method": "derived", "rationale": "Riyal amounts are rounded (POS and e-commerce sales in thousands to 1 decimal, ATM withdrawals in millions to 2); counts are copied unchanged."}],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": "column[mada_ecommerce_transactions,2025-10]", "expected": series[0]["mada_ecommerce_transactions"], "tolerance": 0},
            {"statistic": "column[atm_transactions,2026-09]", "expected": series[-1]["atm_transactions"], "tolerance": 0},
            {"statistic": "count", "expected": 12, "tolerance": 0},
        ],
        "notes": (
            "Monthly card payment activity in Saudi Arabia from SAMA's Monthly Statistical Bulletin for September 2026. value is "
            "point-of-sale sales in thousands of riyals (Table 30c); the columns add POS transaction counts, terminals at month "
            "end, near-field-communication POS transactions made with mobile phones and with cards, mada e-commerce sales (thousand "
            "riyals) and transactions, and from Table 30a the number of ATMs and cards issued at month end, ATM transactions (cash "
            "withdrawals and other transactions, mada and bank networks combined) and ATM cash withdrawals in millions of riyals. "
            "mada e-commerce covers online shopping, in-app purchases and e-wallets with mada cards only, not Visa, MasterCard or "
            f"other credit cards. Average ticket is sales divided by transactions. {SAMA_LICENSE_NOTE}"
        ),
    }


def instant_payments(sama: Workbook) -> dict:
    for sheet in ("27a", "27b"):
        expect_header(sama, sheet, {"C9": "Customer Payments", "F9": "Interbank Payments", "J9": "Total", "K9": "Instant Payments", "K10": "System"})
    value_rows, count_rows = bulletin_rows(sama, "27a"), bulletin_rows(sama, "27b")
    values_ws, counts_ws = sama.sheet("27a"), sama.sheet("27b")
    series = []
    for month in BULLETIN_MONTHS:
        v, c = value_rows[month], count_rows[month]
        series.append({
            "period": month,
            "value": int(counts_ws[f"K{c}"].value),
            "instant_payments_value_sar_million": r(values_ws[f"K{v}"].value, 2),
            "sarie_customer_payments": int(counts_ws[f"E{c}"].value),
            "sarie_customer_payments_value_sar_million": r(values_ws[f"E{v}"].value, 2),
            "sarie_total_transactions": int(counts_ws[f"J{c}"].value),
            "sarie_total_value_sar_million": r(values_ws[f"J{v}"].value, 2),
        })
    columns = [k for k in series[0] if k not in ("period", "value")]
    entry = base("sa-instant-payments-and-sarie-monthly-2025-10-2026-09", "Saudi Arabia instant payments and SARIE transfers, number and value, monthly October 2025 to September 2026 (SAMA)", "temporal", "payments", ["instant-payments", "sarie", "credit-transfers", "monthly", "time-series", "sama"], ["payments-demo", "fintech-demo", "banking-demo", "payments-reconciliation"])
    return {
        **entry,
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "spec": {"variable": "instant_payment_transactions", "unit": "count", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            sama.cite_cell("27b", f"K{count_rows['2026-09']}", "Instant Payments System, number, September 2026", "Table 27b: Number of Transactions for Saudi Arabian Riyal Interbank Express System", "count"),
            sama.cite_cell("27a", f"K{value_rows['2025-10']}", "Instant Payments System, value, October 2025", "Table 27a: Value of Transactions for Saudi Arabian Riyal Interbank Express System", "currency:SAR"),
            sama.cite_cell("27a", f"J{value_rows['2026-09']}", "SARIE total value, September 2026", "Instant Payments System launched on Feb 21, 2021.", "currency:SAR"),
        ],
        "assumed": [{"parameter": "series", "value": "rounded", "method": "derived", "rationale": "Values in millions of riyals are rounded to 2 decimals; counts are copied unchanged."}],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": "column[instant_payments_value_sar_million,2025-10]", "expected": series[0]["instant_payments_value_sar_million"], "tolerance": 0},
            {"statistic": "column[sarie_total_value_sar_million,2026-09]", "expected": series[-1]["sarie_total_value_sar_million"], "tolerance": 0},
            {"statistic": "count", "expected": 12, "tolerance": 0},
        ],
        "notes": (
            "Monthly number (value) and value in millions of riyals of payments through Saudi Arabia's Instant Payments System "
            "(launched 21 February 2021), with SARIE (Saudi Arabian Riyal Interbank Express) customer payments and SARIE totals "
            "(customer, interbank and other payments including direct debits), from Tables 27a and 27b of SAMA's Monthly "
            "Statistical Bulletin for September 2026. Dividing value by number gives the average transfer size, which is far "
            f"smaller for instant payments than for SARIE. {SAMA_LICENSE_NOTE}"
        ),
    }


def personal_transfers(sama: Workbook) -> dict:
    expect_header(sama, "25", {"P8": "Personal Transfers", "P10": "Saudis", "Q10": "Non-Saudis", "U9": "Sub-Total (A)"})
    rows = bulletin_rows(sama, "25", period_column=11)
    ws = sama.sheet("25")
    series = [{"period": m, "value": r(ws[f"Q{rows[m]}"].value, 2), "saudis_sar_million": r(ws[f"P{rows[m]}"].value, 2)} for m in BULLETIN_MONTHS]
    entry = base("sa-personal-transfers-abroad-by-nationality-monthly-2025-10-2026-09", "Saudi Arabia bank sales of foreign exchange for personal transfers abroad by Saudis and non-Saudis, monthly Oct 2025 to Sep 2026 (SAMA)", "temporal", "payments", ["remittances", "personal-transfers", "foreign-exchange", "nationality", "monthly", "time-series", "sama"], ["payments-demo", "fintech-demo", "banking-demo", "multi-currency-ledger"])
    return {
        **entry,
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "spec": {"variable": "personal_transfers_non_saudis_sar_million", "unit": "currency:SAR", "frequency": "monthly", "columns": ["saudis_sar_million"], "series": series},
        "evidence": [
            sama.cite_cell("25", f"Q{rows['2026-09']}", "Personal Transfers, Non-Saudis, September 2026", "Sales of Foreign Exchange", "currency:SAR"),
            sama.cite_cell("25", f"P{rows['2025-10']}", "Personal Transfers, Saudis, October 2025", "Personal Transfers", "currency:SAR"),
            sama.cite_cell("25", f"Q{rows['2025-10']}", "Personal Transfers, Non-Saudis, October 2025", "Non-Saudis", "currency:SAR"),
        ],
        "assumed": [{"parameter": "series", "value": "rounded", "method": "derived", "rationale": "Values in millions of riyals are rounded to 2 decimals."}],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": "column[saudis_sar_million,2025-10]", "expected": series[0]["saudis_sar_million"], "tolerance": 0},
            {"statistic": "count", "expected": 12, "tolerance": 0},
        ],
        "notes": (
            "Monthly bank sales of foreign exchange attributed to personal transfers abroad, in millions of riyals, split by "
            "Saudis and non-Saudis, from Table 25 (Bank Purchases and Sales of Foreign Exchange, section A, sales attributable to "
            "specific purposes) of SAMA's Monthly Statistical Bulletin for September 2026. The non-Saudi series (value) is the "
            "monthly measure commonly read as expatriate workers' remittances; the balance of payments workers' remittances "
            f"line is quarterly and defined differently. {SAMA_LICENSE_NOTE}"
        ),
    }


POS_TOP_LEVEL = {
    "Transportation": ["Airlines", "Auto & Equipment Rentals", "Trade of Vehicles & Spare Parts", "Maintenance & Repair of Vehicles", "Freight Transport & Postal & Courier Services", "Others"],
    "Health": ["Medical Services", "Pharmacies & Medical Supplies", "Personal Care"],
    "Restaurants & Café": [],
    "Bakeries & Pastries": [],
    "Hotels": [],
    "Food & Beverages": [],
    "Apparel, Clothing & Accessories": [],
    "Recreation & Culture": ["Books & Stationery", "Recreation"],
    "Professional & Business Services": [],
    "Electronic & Electric Devices": [],
    "Furniture & Home Supplies": [],
    "Construction & Building Materials": [],
    "Jewelry": [],
    "Telecommunication": [],
    "Education": [],
    "Public Utilities & Services": [],
    "Gas Stations": [],
    "Laundry Services": [],
    "Others": [],
}


def pos_by_activity(sama: Workbook) -> dict:
    for sheet in ("30d", "30e"):
        expect_header(sama, sheet, {"A7": "Activity", "N7": "Q3 2026"})
    count_ws, value_ws = sama.sheet("30d"), sama.sheet("30e")
    labels = []
    for row in range(8, count_ws.max_row + 1):
        label = text_of(count_ws[f"A{row}"].value)
        if label != text_of(value_ws[f"A{row}"].value):
            raise ValueError(f"30d/30e row {row}: labels differ")
        if label:
            labels.append((row, label))
        if label == "Total":
            break
    # The tables list each top-level activity followed by its sub-activities; walk them in that order.
    expected = []
    for top, subs in POS_TOP_LEVEL.items():
        expected.append(("top", top))
        expected.extend(("sub", s) for s in subs)
    expected.append(("total", "Total"))
    if [label for _, label in labels] != [label for _, label in expected]:
        raise ValueError(f"30d: activity order changed: {[label for _, label in labels]}")
    counts, values, sub_counts, cells = {}, {}, {}, {}
    parent = ""
    for (row, label), (level, _) in zip(labels, expected):
        count, value = float(count_ws[f"N{row}"].value), float(value_ws[f"N{row}"].value)
        if level == "top":
            parent = label
            counts[label], values[label] = r(count, 3), r(value, 3)
            cells[label] = row
        elif level == "sub":
            sub_counts[f"{parent} / {label}"] = {"transactions_thousand": r(count, 3), "sales_sar_thousand": r(value, 3)}
        else:
            total_count, total_value, total_row = count, value, row
    if abs(sum(counts.values()) - total_count) > 1 or abs(sum(values.values()) - total_value) > 10:
        raise ValueError("30d/30e: top-level activities do not add up to the total")
    shares = {k: r(v / total_count, 6) for k, v in counts.items()}
    average_ticket = {k: r(values[k] / counts[k], 2) for k in counts}
    entry = base("sa-pos-transactions-by-activity-2026q3", "Saudi Arabia point-of-sale transactions and sales by merchant activity, Q3 2026 (SAMA)", "marginal", "payments", ["pos", "card-payments", "merchant-category", "average-ticket", "sama"], ["payments-demo", "retail-demo", "sales-generation", "fintech-demo"])
    return {
        **entry,
        "observed_period": {"start": "2026-07-01", "end": "2026-09-30"},
        "spec": {
            "variable": "merchant_activity",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {
                    "shares": shares,
                    "transactions_thousand": counts,
                    "sales_sar_thousand": values,
                    "average_ticket_sar": average_ticket,
                    "sub_activities": sub_counts,
                    "total_transactions_thousand": r(total_count, 3),
                    "total_sales_sar_thousand": r(total_value, 3),
                },
            },
        },
        "evidence": [
            sama.cite_cell("30d", f"N{cells['Restaurants & Café']}", "Restaurants & Café, Q3 2026", "Table 30d: Points of Sale Transactions by Activity (Number of Transactions)", "count"),
            sama.cite_cell("30e", f"N{cells['Gas Stations']}", "Gas Stations, Q3 2026", "Table 30e: Points of Sale Transactions by Activity (Value of Transactions)", "currency:SAR"),
            sama.cite_cell("30d", f"N{total_row}", "Total, Q3 2026", "Transactions in Thousand", "count"),
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "activity transactions / total transactions", "method": "derived", "rationale": "Shares are each top-level activity's Q3 2026 transaction count over the published total; sub-activities (for example airlines within transportation) are kept separately so nothing is counted twice. The builder checks the top-level activities add up to the total."},
            {"parameter": "distribution.parameters.average_ticket_sar", "value": "sales / transactions", "method": "derived", "rationale": "Average ticket in riyals is the activity's sales (thousand riyals) divided by its transactions (thousands)."},
        ],
        "tests": [
            {"statistic": 'share["Restaurants & Café"]', "expected": shares["Restaurants & Café"], "tolerance": 0.004},
            {"statistic": 'share["Gas Stations"]', "expected": shares["Gas Stations"], "tolerance": 0.004},
            {"statistic": 'share["Jewelry"]', "expected": shares["Jewelry"], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0002},
        ],
        "notes": (
            "Point-of-sale card transactions in Saudi Arabia in the third quarter of 2026 by merchant activity, from Tables 30d "
            "(number, thousands) and 30e (sales, thousand riyals) of SAMA's Monthly Statistical Bulletin for September 2026. "
            "shares weight activities by number of transactions, so a generator draws the merchant category of a card payment "
            "and then its amount around average_ticket_sar. Sub-activities of transportation, health and recreation and culture "
            f"are listed under sub_activities. Activity labels are SAMA's. {SAMA_LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- SAMA weekly POS report, October 2026


CITY_LINE = re.compile(r"^([A-Z][A-Za-z' -]+?)\s+[^\x00-\x7f].*?\s((?:[\d,]+\s+){8})(-?[\d.]+)\s+(-?[\d.]+)\s*$")


def pos_by_city(pdf: Source) -> dict:
    reader = PdfReader(io.BytesIO(pdf.raw))
    weeks = 4
    cities: dict[str, dict[str, Any]] = {}
    for page in reader.pages[1:]:
        for line in (page.extract_text() or "").splitlines():
            m = CITY_LINE.match(line.strip())
            if not m:
                continue
            name = m.group(1).strip()
            numbers = m.group(2).split()
            transactions = [int(n.replace(",", "")) for n in numbers[0::2]]
            sales = [int(n.replace(",", "")) for n in numbers[1::2]]
            if len(transactions) != weeks or name in cities:
                raise ValueError(f"pos weekly: unexpected city line {line!r}")
            cities[name] = {"transactions": transactions, "sales": sales, "printed": numbers}
    if len(cities) < 50 or "Riyadh" not in cities or "Others" not in cities:
        raise ValueError(f"pos weekly: parsed {len(cities)} cities")
    month_counts = {c: sum(v["transactions"]) for c, v in cities.items()}
    month_sales = {c: sum(v["sales"]) for c, v in cities.items()}
    total = sum(month_counts.values())
    shares = {c: r(n / total, 6) for c, n in month_counts.items()}
    entry = base("sa-pos-transactions-by-city-2026-10", "Saudi Arabia point-of-sale transactions and sales by city, four weeks 4 to 31 October 2026 (SAMA weekly POS report)", "marginal", "payments", ["pos", "card-payments", "by-city", "weekly", "sama"], ["payments-demo", "retail-demo", "address-generation", "sales-generation"])
    entry["tier"] = "B"
    riyadh, jeddah = cities["Riyadh"], cities["Jeddah"]
    return {
        **entry,
        "observed_period": {"start": "2026-10-04", "end": "2026-10-31"},
        "spec": {
            "variable": "city",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {"shares": shares, "transactions_thousand": month_counts, "sales_sar_thousand": month_sales, "weekly_transactions_thousand": {c: v["transactions"] for c, v in cities.items()}},
            },
        },
        "evidence": [
            pdf.cite("page 2, Table 2.1, Riyadh, week 25-31 October 2026, number of transactions", riyadh["printed"][6], "count", "Table 2.1: By Cities"),
            pdf.cite("page 3, Table 2.2, Jeddah, week 4-10 October 2026, value of transactions", jeddah["printed"][1], "currency:SAR", "Table 2.2: By Cities"),
            pdf.cite("page 2, header", "25 Oct,26 - 31 Oct,26", "text", "Number of Transactions: In Thousand"),
            pdf.cite("page 3, note", "Saudi Central Bank Portal for Open Data.", "text", "Points of sale transactions by activity for cities are available on", role="supporting"),
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "city transactions / sum over cities", "method": "derived", "rationale": "Each city's number of transactions is summed over the four published weeks and divided by the sum over all listed cities including 'Others'; the city tables carry no total row of their own."},
            {"parameter": "distribution.parameters.transactions_thousand", "value": "sum of four weeks", "method": "derived", "rationale": "Transactions (thousands) and sales (thousand riyals) are the sums of the four weekly figures printed in the report; the weekly transaction counts are kept beside them."},
        ],
        "tests": [
            {"statistic": 'share["Riyadh"]', "expected": shares["Riyadh"], "tolerance": 0.004},
            {"statistic": 'share["Jeddah"]', "expected": shares["Jeddah"], "tolerance": 0.004},
            {"statistic": 'share["Others"]', "expected": shares["Others"], "tolerance": 0.004},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0002},
        ],
        "notes": (
            "Point-of-sale card transactions (thousands) and sales (thousand riyals) by city for the four weeks from 4 to 31 "
            "October 2026, from Tables 2.1 and 2.2 of SAMA's Weekly Points of Sale Transactions report published for the week "
            f"ending 31 October 2026. {len(cities) - 1} named cities plus 'Others' are listed; city names are SAMA's English spellings "
            "(for example Tabouk, Hayel, Ar'ar). The report is a PDF, so the entry is tier B; values are parsed from its extracted "
            f"text and every figure keeps its weekly breakdown. {SAMA_LICENSE_NOTE}"
        ),
    }


# ---------------------------------------------------------------- main


def main() -> int:
    lfs = Workbook(GASTAT, "Labor Market Statistics, Second Quarter 2026 (LFS tables, XLSX)", LFS_URL)
    reg = Workbook(GASTAT, "Register-based Labour Market Statistics, Second Quarter 2026 (XLSX)", REGISTER_URL)
    pop = Workbook(GASTAT, "Population Estimates Statistics 2024 (XLSX)", POPULATION_URL)
    pop_pdf = Source(GASTAT, "Population Estimates Publication 2024 (PDF)", POPULATION_PDF_URL)
    cpi = Workbook(GASTAT, "Consumer Price Index tables, September 2026 (XLSX)", CPI_URL)
    prices = Workbook(GASTAT, "Average Prices of Goods and Services tables, September 2026 (XLSX)", PRICES_URL)
    hies = Workbook(GASTAT, "Household Income and Consumption Expenditure Survey 2023, publication tables (XLSX)", HIES_URL)
    tour = Workbook(GASTAT, "Tourism Establishments Statistics, Q2 of 2026 (XLSX)", TOURISM_URL)
    health = Workbook(GASTAT, "Healthcare Establishments and Workforce Statistics 2024 (XLSX)", HEALTH_URL)
    sama = Workbook(SAMA, "Monthly Statistical Bulletin, September 2026 (XLSX)", SAMA_BULLETIN_URL)
    pos_weekly = Source(SAMA, "Weekly Points of Sale Transactions Report, 31 October 2026 (PDF)", SAMA_POS_WEEKLY_URL)

    entries = [
        lfs_indicators(lfs),
        lfs_unemployment_series(lfs),
        lfs_unemployment_by_region(lfs),
        lfs_employed_distribution(lfs, "3-4", "Percentage distribution of Employed by nationality, sex and Main Groups of Occupations(%)", "sa-employed-by-occupation-nationality-sex-2026q2", "Saudi Arabia employed persons by ISCO-08 major occupation group given nationality and sex, Q2 2026 (GASTAT LFS)", "occupation_major_group", ["occupation", "isco"], [("saudi-female", "Professionals"), ("non-saudi-male", "Elementary occupations"), ("total-total", "Managers")], "major occupation group (Saudi classification based on ISCO-08)"),
        lfs_employed_distribution(lfs, "3-5", "Percentage distribution of employed by nationality, sex and main economic activity (%)", "sa-employed-by-economic-activity-nationality-sex-2026q2", "Saudi Arabia employed persons by ISIC economic activity section given nationality and sex, Q2 2026 (GASTAT LFS)", "economic_activity_section", ["industry", "isic"], [("saudi-male", "Public administration and defense; compulsory social security"), ("non-saudi-female", "Construction"), ("total-total", "Construction")], "economic activity section (Saudi classification based on ISIC)"),
        lfs_wages(lfs, "6-1", "Average Monthly Wages per Paid employee of main Work by Sex , Nationality and Age Group 5 Years", "sa-average-monthly-wage-by-age-nationality-sex-2026q2", "Saudi Arabia average monthly wage of paid employees by five-year age group, nationality and sex, Q2 2026 (GASTAT LFS)", "five-year age group", [("30-34", "saudi-female"), ("25-29", "non-saudi-male")], "10-14"),
        lfs_wages(lfs, "6-2", "Average Monthly Wages per Paid employee in main work by nationality, sex and educational level", "sa-average-monthly-wage-by-education-nationality-sex-2026q2", "Saudi Arabia average monthly wage of paid employees by education level, nationality and sex, Q2 2026 (GASTAT LFS)", "education level (ISCED 2011)", [("Master’s or equivalent level", "saudi-male"), ("Primary education", "non-saudi-female")], "Kindergarten"),
        register_conditional(reg, "3-3", "Participants on the job Subject to the rules and regulations of social insurance by nationality, sex and Age group", "sa-gosi-participants-by-age-nationality-sex-2026q2", "Saudi Arabia GOSI-registered workers by age group given nationality and sex, Q2 2026 (GASTAT register-based statistics)", "age_group", ["age"], [("non-saudi-male", "30-34"), ("saudi-female", "25-29"), ("total-total", "65+")], "Total", ["synthetic-employees", "hr-demo", "payroll-demo", "pensions"], "five-year age group"),
        register_conditional(reg, "3-4", "Participants on the job Subject to the rules and regulations of social insurance by nationality, sex and Administrative Region", "sa-gosi-participants-by-region-nationality-sex-2026q2", "Saudi Arabia GOSI-registered workers by administrative region given nationality and sex, Q2 2026 (GASTAT register-based statistics)", "administrative_region", ["by-region"], [("saudi-female", "Riyadh"), ("non-saudi-male", "Eastern Province"), ("total-total", "Makkah")], "Total", ["synthetic-employees", "hr-demo", "address-generation", "workforce-planning"], "administrative region of work"),
        register_conditional(reg, "3-5", "Participants on the job Subject to the rules and regulations of social insurance by nationality, sex and Main Groups of Occupations", "sa-gosi-participants-by-occupation-nationality-sex-2026q2", "Saudi Arabia GOSI-registered workers by ISCO-08 major occupation group given nationality and sex, Q2 2026 (GASTAT)", "occupation_major_group", ["occupation", "isco"], [("non-saudi-male", "Elementary occupations"), ("saudi-female", "Clerical support workers"), ("total-total", "Professionals")], "Total", ["synthetic-employees", "hr-demo", "payroll-demo", "workforce-planning"], "major occupation group (subscriptions, so a person with jobs in two occupations can be counted twice)"),
        register_conditional(reg, "3-8", "Participants on the job Subject to the rules and regulations of social insurance by nationality, sex and main groups of economic activities", "sa-gosi-participants-by-economic-activity-nationality-sex-2026q2", "Saudi Arabia GOSI-registered workers by ISIC economic activity given nationality and sex, Q2 2026 (GASTAT register-based statistics)", "economic_activity_section", ["industry", "isic"], [("non-saudi-male", "Construction"), ("saudi-female", "Wholesale and retail trade; repair of motor vehicles and motorcycles"), ("total-total", "Manufacturing")], "Total", ["synthetic-employees", "company-generation", "kyb-onboarding", "hr-demo"], "economic activity section (ISIC Rev. 4)"),
        register_sector(reg),
        domestic_workers(reg),
        *population(pop, pop_pdf),
        cpi_weights(cpi),
        cpi_series(cpi),
        average_prices(prices),
        hies_by_region(hies),
        hies_coicop(hies),
        tourism_regions(tour),
        tourism_quarterly(tour),
        hospitals(health),
        card_payments(sama),
        instant_payments(sama),
        personal_transfers(sama),
        pos_by_activity(sama),
        pos_by_city(pos_weekly),
    ]
    for entry in entries:
        write(entry)
    print(f"{len(entries)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())

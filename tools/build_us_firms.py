"""Regenerate the US firm-level distributions built from US Census Bureau static files.

Private equity teams size markets, source deals and generate synthetic portfolio companies from
these tables, so each entry keeps the published counts next to the shares and per-employee
figures a generator draws from:

* Statistics of US Businesses (SUSB) 2022: firms, establishments, employment, annual payroll and
  receipts by enterprise employment size, by enterprise receipts size, by legal form of
  organisation, by state and by NAICS sector or subsector.
* Business Dynamics Statistics (BDS) 2023: firm counts, establishment entry and exit and job flows
  by firm age, firm size and sector, and the national series from 1978.
* County Business Patterns (CBP) 2023: establishments by employment size class, sector and state.
* Business Formation Statistics (BFS): monthly business applications in 2025, nationally, by
  state and by sector.
* Annual Business Survey (ABS), reference year 2024: new credit applications, outcomes and
  lending sources by owner demographics.
* Quarterly Financial Report (QFR), second quarter 2026: return and balance-sheet ratios.

Every resource is a static file (the Census API now refuses requests without a key). Each URL is
fetched twice and kept only when both responses hash alike. The Census Bureau publishes no licence
statement with these files, so every entry records ``source_license: unstated`` and stays at
``license-review``. Run from the repository root:

    uv run python tools/build_us_firms.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write

from almanac.fetch import Resource

CENSUS = "US Census Bureau"
LICENSE = "unstated"
STATUS = "license-review"
LICENSE_NOTE = (
    "The Census Bureau publishes these files without a licence statement, so the licence is recorded as "
    "unstated and the entry held at license-review."
)
USE_CASES = ["pe-portfolio-demo", "deal-sourcing-demo", "synthetic-companies", "valuation-demo", "kyb-onboarding"]
SHARE_DIGITS = 6
SHARE_TOLERANCE = 0.005

SUSB_BASE = "https://www2.census.gov/programs-surveys/susb/tables/2022/"
SUSB_DETAILED_URL = SUSB_BASE + "us_state_naics_detailedsizes_2022.txt"
SUSB_LARGE_EMPLOYMENT_URL = SUSB_BASE + "us_naicssector_large_emplsize_2022.xlsx"
SUSB_RECEIPTS_URL = SUSB_BASE + "us_6digitnaics_rcptsize_2022.xlsx"
SUSB_LARGE_RECEIPTS_URL = SUSB_BASE + "us_naicssector_large_rcptsize_2022.xlsx"
SUSB_LFO_URL = SUSB_BASE + "us_state_naicssector_lfo_2022.xlsx"
SUSB_TITLE = "Statistics of US Businesses 2022"
LFO_TITLE = f"{SUSB_TITLE}: US and states by legal form, NAICS sector and enterprise employment size (us_state_naicssector_lfo_2022.xlsx)"
LABEL_ASSUMPTION = {"parameter": "label", "value": "sector titles from the SUSB 2022 legal-form workbook", "method": "derived", "rationale": "The file carries NAICS sector codes only; the titles come from the SUSB workbook, which prints code and title for the same sectors."}

BDS_BASE = "https://www2.census.gov/programs-surveys/bds/tables/time-series/2023/"
BDS_YEAR = "2023"
BDS_TITLE = "Business Dynamics Statistics 1978-2023"

CBP_BASE = "https://www2.census.gov/programs-surveys/cbp/datasets/2023/"
CBP_US_URL = CBP_BASE + "cbp23us.zip"
CBP_STATE_URL = CBP_BASE + "cbp23st.zip"
CBP_TITLE = "County Business Patterns 2023"

BFS_URL = "https://www.census.gov/econ/bfs/csv/bfs_monthly.csv"
BFS_DOCUMENTATION_URL = "https://www.census.gov/econ/bfs/pdf/technical_documentation.pdf"
BFS_YEAR = "2025"
BFS_TITLE = "Business Formation Statistics, monthly file (bfs_monthly.csv)"

ABS_BASE = "https://www2.census.gov/programs-surveys/abs/data/2025/"
ABS_APPLICATION_URL = ABS_BASE + "CI-1-New-credit-application.xlsx"
ABS_SOURCES_URL = ABS_BASE + "CI-2-Lending-sources-of-new-credit.xlsx"
ABS_RECEIVED_URL = ABS_BASE + "CI-3-Amount-of-requested-new-credit-recieved.xlsx"

QFR_URL = "https://www2.census.gov/econ/qfr/xls/qfr26q2f.xlsx"
QFR_QUARTER = "2026Q2"
QFR_TITLE = "Quarterly Financial Report, financial data tables workbook, 2026Q2 release (qfr26q2f.xlsx)"

Record = dict[str, Any]


# ----------------------------------------------------------------------------------------------
# Fetching, checking and small numeric helpers
# ----------------------------------------------------------------------------------------------

RESOURCES: dict[str, bytes] = {}


def get(url: str) -> bytes:
    """Fetch a URL twice, keep its bytes only when both responses hash alike, and remember them for the run."""
    if url not in RESOURCES:
        first, second = fetch(url), fetch(url)
        if sha(first) != sha(second):
            raise RuntimeError(f"unstable bytes at {url}")
        RESOURCES[url] = first
    return RESOURCES[url]


TEXTS: dict[str, str] = {}


def resource_text(url: str) -> str:
    """The resource's searchable text with whitespace collapsed, as the verifier sees it."""
    if url not in TEXTS:
        TEXTS[url] = " ".join(Resource(url, RESOURCES[url], "").text.split())
    return TEXTS[url]


def finish(entry: Record) -> None:
    """Fail when an evidence snippet or value would not be found by the verifier, then write the entry."""
    for item in entry["evidence"]:
        text = resource_text(item["url"])
        for label, needle in (("snippet", item["snippet"]), ("value", str(item["value"]))):
            if " ".join(needle.split()) not in text:
                raise ValueError(f"{entry['id']}: {label} {needle!r} not found in {item['url']}")
        if len(item["snippet"].split()) > 24:
            raise ValueError(f"{entry['id']}: snippet too long: {item['snippet']!r}")
    if len(entry["title"]) > 140:
        raise ValueError(f"{entry['id']}: title longer than 140 characters")
    write(entry)


def number(text: Any) -> int | float | None:
    """A published figure, or None for the suppression and not-applicable codes the files use."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return text
    value = str(text).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", value):
        return None
    return float(value) if "." in value else int(value)


def shares(counts: Mapping[str, float | None]) -> dict[str, float]:
    total = sum(v for v in counts.values() if v)
    return {k: round(v / total, SHARE_DIGITS) for k, v in counts.items() if v}


def per_unit(numerator: float | None, denominator: float | None, scale: float = 1, digits: int = 0) -> float | int | None:
    """``numerator * scale / denominator``, rounded; None when either figure is missing or the denominator is zero."""
    if numerator is None or not denominator:
        return None
    value = round(numerator * scale / denominator, digits)
    return int(value) if digits == 0 else value


def strip_code(label: str) -> str:
    """Drop the ordering prefix ('02: ', 'a) ') and the trailing ' employees' from a published class label."""
    label = re.sub(r"^\s*(\d+:|[a-z]\))\s*", "", str(label))
    return re.sub(r"\s+employees$", "", label).strip()


def share_tests(distribution: Mapping[str, Any], given: str | None = None, picks: int = 2) -> list[Record]:
    """The share of the largest categories and the declared total, for a marginal or one conditional slice."""
    prefix = f'"{given}",' if given is not None else ""
    top = sorted(distribution["shares"].items(), key=lambda kv: -kv[1])[:picks]
    tests = [{"statistic": f'share[{prefix}"{k}"]', "expected": v, "tolerance": SHARE_TOLERANCE} for k, v in top]
    total = f'sum_of_shares["{given}"]' if given is not None else "sum_of_shares"
    return tests + [{"statistic": total, "expected": 1, "tolerance": 0.0001}]


def census_evidence(url: str, title: str, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> Record:
    return evidence(CENSUS, title, url, locator, value, unit, snippet, LICENSE, RESOURCES[url], role)


def base_entry(entry_id: str, title: str, kind: str, period: tuple[str, str], tags: list[str], use_cases: list[str] | None = None) -> Record:
    entry: Record = {
        "id": entry_id,
        "title": title,
        "kind": kind,
        "domain": "business",
        "region": "US",
        "status": STATUS,
        "tier": "A",
    }
    if kind == "rule":
        entry["valid_from"], entry["valid_to"] = period
    else:
        entry["observed_period"] = {"start": period[0], "end": period[1]}
    entry["tags"] = ["firms", "business", "census", *tags]
    entry["use_cases"] = list(dict.fromkeys([*USE_CASES, *(use_cases or [])]))
    return entry


def xlsx_rows(url: str, sheet: str | None = None, start: int = 1) -> list[tuple]:
    workbook = load_workbook(io.BytesIO(RESOURCES[url]), read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
    return list(worksheet.iter_rows(min_row=start, values_only=True))


def csv_rows(raw: bytes) -> list[dict[str, str]]:
    """Rows of a CSV file; the SUSB text files are Windows-1252, the rest UTF-8."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return list(csv.DictReader(io.StringIO(text)))


def zip_member(raw: bytes) -> bytes:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    (name,) = [n for n in archive.namelist() if n.endswith(".txt")]
    return archive.read(name)


# ----------------------------------------------------------------------------------------------
# Statistics of US Businesses 2022
# ----------------------------------------------------------------------------------------------

SUSB_MEASURES = ("firms", "establishments", "employment", "annual_payroll_usd_thousands", "receipts_usd_thousands")
SUSB_DERIVED = [
    {"parameter": "receipts_per_employee_usd", "value": "1000 * receipts_usd_thousands / employment", "method": "derived", "rationale": "Receipts per employee in whole dollars from the published receipts ($1,000) and employment of the same cell."},
    {"parameter": "annual_payroll_per_employee_usd", "value": "1000 * annual_payroll_usd_thousands / employment", "method": "derived", "rationale": "Annual payroll per employee in whole dollars from the published payroll ($1,000) and employment of the same cell."},
    {"parameter": "shares", "value": "firms in the class / firms in all mutually exclusive classes", "method": "derived", "rationale": "Shares are computed from the published firm counts; subtotal classes such as <20 and <500 are kept in the measures but excluded from the shares."},
]
SUSB_NOISE_NOTE = (
    "SUSB applies noise to employment, payroll and receipts (flags G, H and J mark low, medium and high noise); "
    "firm and establishment counts carry no noise flag. The tables credit the 2022 County Business Patterns and "
    "Economic Census as their source. "
)
CLASSIC_SIZES = ["<5", "5-9", "10-19", "20-99", "100-499", "500+"]
# Mutually exclusive classes interleaved with the published <20 and <500 subtotals and the total.
CLASSIC_ORDER = ["<5", "5-9", "10-19", "<20", "20-99", "100-499", "<500", "500+", "Total"]


def susb_measures(cells: Iterable[Any]) -> Record:
    return dict(zip(SUSB_MEASURES, (number(c) for c in cells)))


def with_ratios(record: Record) -> Record:
    record = dict(record)
    record["receipts_per_employee_usd"] = per_unit(record["receipts_usd_thousands"], record["employment"], 1000)
    record["annual_payroll_per_employee_usd"] = per_unit(record["annual_payroll_usd_thousands"], record["employment"], 1000)
    return record


def pivot(classes: Mapping[str, Record], order: Iterable[str], exclusive: Iterable[str]) -> Record:
    """Turn per-class records into per-measure dictionaries keyed by class, with firm shares over the exclusive classes."""
    order = [c for c in order if c in classes]
    exclusive = [c for c in exclusive if c in classes]
    result: Record = {"shares": shares({c: classes[c]["firms"] for c in exclusive})}
    for measure in (*SUSB_MEASURES, "receipts_per_employee_usd", "annual_payroll_per_employee_usd"):
        result[measure] = {c: classes[c][measure] for c in order}
    return result


def susb_detailed() -> list[dict[str, str]]:
    return csv_rows(get(SUSB_DETAILED_URL))


def susb_lfo() -> list[Record]:
    """Rows of the legal-form workbook: state, legal form, sector and size class with their five measures."""
    rows = []
    for r in xlsx_rows(SUSB_LFO_URL, "LFO", start=4):
        if not r[0]:
            continue
        rows.append({
            "state": r[0], "state_name": r[1], "lfo": strip_code(r[2]), "naics": r[3], "naics_label": r[4],
            "size": strip_code(r[5]), **susb_measures([r[6], r[7], r[8], r[10], r[12]]),
        })
    return rows


def susb_national_by_employment_size() -> Record:
    detailed = [r for r in susb_detailed() if r["STATE"] == "00" and r["NAICS"] == "--"]
    classes: dict[str, Record] = {}
    order: list[str] = []
    for r in detailed:
        label = strip_code(r["ENTRSIZEDSCR"])
        classes[label] = with_ratios(susb_measures([r["FIRM"], r["ESTB"], r["EMPL"], r["PAYR"], r["RCPT"]]))
        order.append(label)
    large = [r for r in xlsx_rows(SUSB_LARGE_EMPLOYMENT_URL, start=4) if r[0] == "--"]
    for r in large:
        label = strip_code(r[2])
        if label not in classes:
            classes[label] = with_ratios(susb_measures([r[3], r[4], r[5], r[7], r[9]]))
            order.insert(order.index("5,000+"), label)
    order.remove("5,000+")
    exclusive = [c for c in order if c not in ("Total", "<20", "<500", "500+")]
    params = pivot(classes, order, exclusive)
    total = classes["Total"]
    largest = classes["20,000+"]
    entry = base_entry(
        "us-susb-firms-by-employment-size-2022",
        f"US employer firms by enterprise employment size, {len(exclusive)} classes from <5 to 20,000+ employees, with payroll and receipts (SUSB 2022)",
        "marginal", ("2022-01-01", "2022-12-31"), ["susb", "firm-size", "employment-size", "receipts", "payroll", "lower-middle-market", "categorical"], ["market-sizing", "company-generation"],
    )
    entry["spec"] = {"variable": "enterprise_employment_size_class", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {**params, "size_unit": "employees of the enterprise"}}}
    entry["evidence"] = [
        census_evidence(SUSB_DETAILED_URL, f"{SUSB_TITLE}: US and states, NAICS, detailed employment sizes (us_state_naics_detailedsizes_2022.txt)", "row STATE=00, NAICS=--, ENTRSIZE=01 (Total), column FIRM", total["firms"], "count", f"00,--,01,{total['firms']},{total['establishments']}"),
        census_evidence(SUSB_DETAILED_URL, f"{SUSB_TITLE}: US and states, NAICS, detailed employment sizes (us_state_naics_detailedsizes_2022.txt)", "row STATE=00, NAICS=--, ENTRSIZE=02 (<5), column FIRM", classes["<5"]["firms"], "count", f"00,--,02,{classes['<5']['firms']}"),
        census_evidence(SUSB_LARGE_EMPLOYMENT_URL, f"{SUSB_TITLE}: US, NAICS sectors, large enterprise employment sizes (us_naicssector_large_emplsize_2022.xlsx)", "row NAICS '--' Total, size '11: 20,000+ employees', column Firms", largest["firms"], "count", "The Number of Firms and Establishments, Employment, Annual Payroll, and Receipts by Industry and Enterprise Employment Size: 2022"),
        census_evidence(SUSB_LARGE_EMPLOYMENT_URL, f"{SUSB_TITLE}: US, NAICS sectors, large enterprise employment sizes (us_naicssector_large_emplsize_2022.xlsx)", "row NAICS '--' Total, size '11: 20,000+ employees', column Receipts ($1,000)", largest["receipts_usd_thousands"], "currency:USD", "11: 20,000+ employees"),
    ]
    entry["assumed"] = SUSB_DERIVED + [
        {"parameter": "classes", "value": "<5 to 2,500-4,999 from the detailed file; 5,000-9,999, 10,000-19,999 and 20,000+ from the large-size workbook", "method": "derived", "rationale": "The detailed file stops at 5,000+; the large-size workbook splits that class, so the two are joined at 5,000 employees to give mutually exclusive classes."},
    ]
    entry["tests"] = share_tests(params) + [
        {"statistic": 'share["20,000+"]', "expected": params["shares"]["20,000+"], "tolerance": 0.001},
    ]
    entry["notes"] = (
        "Employer firms (enterprises) in the United States in 2022 by enterprise employment size, the backbone of "
        "lower-middle-market sizing: the share of firms in each mutually exclusive size class, and for every class, and "
        "for the subtotals <20 and <500 and the total, the published firms, establishments, employment, annual payroll "
        "and receipts (both in thousands of dollars), with derived receipts and payroll per employee. Classes are by "
        "enterprise employment size, as the tables are titled. " + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_by_sector(rows: list[Record]) -> dict[str, Record]:
    """Classic size classes by sector from the legal-form workbook (all legal forms, United States)."""
    out: dict[str, Record] = {}
    for r in rows:
        if r["state"] != "00" or r["lfo"] != "Total":
            continue
        key = "all" if r["naics"] == "--" else r["naics"]
        out.setdefault(key, {"label": "All sectors" if key == "all" else r["naics_label"], "classes": {}})
        out[key]["classes"][r["size"]] = with_ratios(r)
    return out


def susb_employment_size_by_sector(lfo_rows: list[Record]) -> Record:
    sectors = susb_by_sector(lfo_rows)
    distributions = {}
    for key, sector in sectors.items():
        params = pivot(sector["classes"], CLASSIC_ORDER, CLASSIC_SIZES)
        distributions[key] = {"family": "categorical", "parameters": {"label": sector["label"], **params}}
    manufacturing = distributions["31-33"]["parameters"]
    entry = base_entry(
        "us-susb-employment-size-by-sector-2022",
        "US employer firms by enterprise employment size given NAICS sector, with receipts and payroll per employee (SUSB 2022)",
        "conditional", ("2022-01-01", "2022-12-31"), ["susb", "firm-size", "employment-size", "by-sector", "receipts", "payroll", "lower-middle-market"], ["market-sizing", "company-generation", "lbo-modelling"],
    )
    entry["spec"] = {"variable": "enterprise_employment_size_class", "unit": "ratio", "given": "naics_sector", "distributions": distributions}
    title = LFO_TITLE
    entry["evidence"] = [
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, 1: Total LFO, NAICS 31-33, size '7: 100-499 employees', column Firms", manufacturing["firms"]["100-499"], "count", "7: 100-499 employees"),
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, 1: Total LFO, NAICS 31-33, size '7: 100-499 employees', column Receipts ($1,000)", manufacturing["receipts_usd_thousands"]["100-499"], "currency:USD", "The Number of Firms and Establishments, Employment, Annual Payroll, and Receipts by State, LFO, Industry, and Enterprise Employment Size: 2022"),
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, 1: Total LFO, NAICS --, size '9: 500+ employees', column Employment", distributions["all"]["parameters"]["employment"]["500+"], "count", "9: 500+ employees"),
    ]
    entry["assumed"] = SUSB_DERIVED
    entry["tests"] = share_tests(distributions["all"]["parameters"], "all") + share_tests(manufacturing, "31-33", 1) + share_tests(distributions["54"]["parameters"], "54", 1)
    entry["notes"] = (
        "For each NAICS sector (keyed by its code, with 'all' for all sectors), the share of US employer firms in the six "
        "enterprise employment size classes <5, 5-9, 10-19, 20-99, 100-499 and 500+, which carry the 20, 100 and 500 "
        "employee cut-offs used to define small and lower-middle-market companies. Each slice also gives, by class and for "
        "the subtotals <20 and <500 and the total, the published firms, establishments, employment, annual payroll and "
        "receipts (thousands of dollars), plus derived receipts and payroll per employee. A firm counts in every sector in "
        "which it has an establishment, so sector firm counts add to more than the all-sector count. " + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_receipts_size_by_sector() -> Record:
    small = [r for r in xlsx_rows(SUSB_RECEIPTS_URL, start=4) if r[0] and (r[0] == "--" or re.fullmatch(r"\d\d(-\d\d)?", str(r[0])))]
    large = [r for r in xlsx_rows(SUSB_LARGE_RECEIPTS_URL, start=4) if r[0] and (r[0] == "--" or re.fullmatch(r"\d\d(-\d\d)?", str(r[0])))]
    sectors: dict[str, Record] = {}
    for r in small:
        key = "all" if r[0] == "--" else str(r[0])
        sector = sectors.setdefault(key, {"label": "All sectors" if key == "all" else r[1], "classes": {}, "order": []})
        label = strip_code(r[2])
        sector["classes"][label] = with_ratios(susb_measures([r[3], r[4], r[5], r[7], r[9]]))
        sector["order"].append(label)
    for r in large:
        key = "all" if r[0] == "--" else str(r[0])
        label = strip_code(r[2])
        if label in ("Total", "<100,000"):
            continue
        sectors[key]["classes"][label] = with_ratios(susb_measures([r[3], r[4], r[5], r[7], r[9]]))
        sectors[key]["order"].append(label)
    distributions = {}
    for key, sector in sectors.items():
        order = [c for c in sector["order"] if c != "100,000+"] + ["100,000+"]
        exclusive = [c for c in order if c not in ("Total", "100,000+")]
        distributions[key] = {"family": "categorical", "parameters": {"label": sector["label"], "class_unit": "enterprise receipts, thousands of US dollars", **pivot(sector["classes"], order, exclusive)}}
    everything = distributions["all"]["parameters"]
    manufacturing = distributions["31-33"]["parameters"]
    entry = base_entry(
        "us-susb-receipts-size-by-sector-2022",
        f"US employer firms by enterprise receipts size given NAICS sector, {len(everything['shares'])} bands from under $100,000 to $2.5 billion and over (SUSB 2022)",
        "conditional", ("2022-01-01", "2022-12-31"), ["susb", "receipts-size", "revenue-bands", "by-sector", "lower-middle-market", "deal-size"], ["market-sizing", "company-generation", "lbo-modelling"],
    )
    entry["spec"] = {"variable": "enterprise_receipts_size_class", "unit": "ratio", "given": "naics_sector", "distributions": distributions}
    small_title = f"{SUSB_TITLE}: US, 6-digit NAICS by enterprise receipts size (us_6digitnaics_rcptsize_2022.xlsx)"
    large_title = f"{SUSB_TITLE}: US, NAICS sectors by large enterprise receipts size (us_naicssector_large_rcptsize_2022.xlsx)"
    entry["evidence"] = [
        census_evidence(SUSB_RECEIPTS_URL, small_title, "sheet 'US 6-digit NAICS', NAICS 31-33, size '16: 50,000-74,999', column Firms", manufacturing["firms"]["50,000-74,999"], "count", "16: 50,000-74,999"),
        census_evidence(SUSB_RECEIPTS_URL, small_title, "sheet 'US 6-digit NAICS', NAICS --, size '02: <100', column Firms", everything["firms"]["<100"], "count", "The Number of Firms and Establishments, Employment, Annual Payroll, and Receipts by Industry and Enterprise Receipts Size: 2022"),
        census_evidence(SUSB_LARGE_RECEIPTS_URL, large_title, "sheet 'US large receipt sizes', NAICS --, size '7: 2,500,000+', column Firms", everything["firms"]["2,500,000+"], "count", "7: 2,500,000+"),
    ]
    entry["assumed"] = SUSB_DERIVED + [
        {"parameter": "classes", "value": "<100 to 75,000-99,999 from the 6-digit workbook; 100,000-249,999 to 2,500,000+ from the large-size workbook", "method": "derived", "rationale": "The 6-digit workbook stops at 100,000+ ($100 million and over); the large-size workbook splits that band, so the two are joined at $100 million to give mutually exclusive bands. The 100,000+ band is kept in the measures as a subtotal."},
    ]
    entry["tests"] = share_tests(everything, "all") + share_tests(manufacturing, "31-33", 1) + [
        {"statistic": 'share["all","10,000-14,999"]', "expected": everything["shares"]["10,000-14,999"], "tolerance": SHARE_TOLERANCE},
    ]
    entry["notes"] = (
        "For each NAICS sector (keyed by its code, with 'all' for all sectors), the share of US employer firms in each "
        "enterprise receipts band, with the published firms, establishments, employment, annual payroll and receipts and "
        "derived receipts and payroll per employee for every band. Band labels are as published, in thousands of dollars: "
        "'10,000-14,999' is $10 million to just under $15 million of annual receipts, '<100' is under $100,000. The bands "
        "from $10 million to $100 million are the lower middle market most private equity sourcing targets. Firms without "
        "receipts in 2022 fall in the lowest band. " + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_legal_form_by_sector(lfo_rows: list[Record]) -> Record:
    sectors: dict[str, Record] = {}
    for r in lfo_rows:
        if r["state"] != "00" or r["size"] != "Total" or r["lfo"] == "Total":
            continue
        key = "all" if r["naics"] == "--" else r["naics"]
        sector = sectors.setdefault(key, {"label": "All sectors" if key == "all" else r["naics_label"], "classes": {}})
        sector["classes"][r["lfo"]] = with_ratios(r)
    distributions = {}
    for key, sector in sectors.items():
        order = list(sector["classes"])
        distributions[key] = {"family": "categorical", "parameters": {"label": sector["label"], **pivot(sector["classes"], order, order)}}
    everything = distributions["all"]["parameters"]
    title = LFO_TITLE
    entry = base_entry(
        "us-susb-legal-form-by-sector-2022",
        "US employer firms by legal form of organization given NAICS sector, with employment, payroll and receipts (SUSB 2022)",
        "conditional", ("2022-01-01", "2022-12-31"), ["susb", "legal-form", "corporations", "s-corporations", "partnerships", "by-sector"], ["company-generation", "kyb-onboarding"],
    )
    entry["spec"] = {"variable": "legal_form_of_organization", "unit": "ratio", "given": "naics_sector", "distributions": distributions}
    entry["evidence"] = [
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, LFO '3: S-Corporation', NAICS --, size '1: Total', column Firms", everything["firms"]["S-Corporation"], "count", "3: S-Corporation"),
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, LFO '5: Sole Propietorship' (spelling as published), NAICS --, size '1: Total', column Firms", everything["firms"]["Sole Propietorship"], "count", "5: Sole Propietorship"),
    ]
    entry["assumed"] = SUSB_DERIVED[:2] + [
        {"parameter": "shares", "value": "firms with the legal form / firms of all legal forms listed in the sector", "method": "derived", "rationale": "Shares are computed from the published firm counts of the seven legal forms; forms absent from a sector's rows are omitted."},
    ]
    entry["tests"] = share_tests(everything, "all", 3) + share_tests(distributions["54"]["parameters"], "54", 1) + share_tests(distributions["62"]["parameters"], "62", 1)
    entry["notes"] = (
        "For each NAICS sector (keyed by its code, with 'all' for all sectors), the share of US employer firms by legal "
        "form of organization (Corporation, S-Corporation, Partnership, Sole Propietorship as the source spells it, "
        "Nonprofit, Government, Other), with the published firms, establishments, employment, annual payroll and receipts "
        "and derived receipts and payroll per employee. Useful for assigning a plausible entity type to a synthetic "
        "company in a KYB or deal-sourcing demo. " + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_employment_size_by_legal_form(lfo_rows: list[Record]) -> Record:
    forms: dict[str, Record] = {}
    for r in lfo_rows:
        if r["state"] != "00" or r["naics"] != "--":
            continue
        forms.setdefault(r["lfo"], {})[r["size"]] = with_ratios(r)
    distributions = {lfo: {"family": "categorical", "parameters": pivot(classes, CLASSIC_ORDER, CLASSIC_SIZES)} for lfo, classes in forms.items()}
    title = LFO_TITLE
    corporations = distributions["Corporation"]["parameters"]
    entry = base_entry(
        "us-susb-employment-size-by-legal-form-2022",
        "US employer firms by enterprise employment size given legal form of organization, with receipts per employee (SUSB 2022)",
        "conditional", ("2022-01-01", "2022-12-31"), ["susb", "legal-form", "firm-size", "employment-size", "receipts"], ["company-generation", "kyb-onboarding"],
    )
    entry["spec"] = {"variable": "enterprise_employment_size_class", "unit": "ratio", "given": "legal_form_of_organization", "distributions": distributions}
    entry["evidence"] = [
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, LFO '2: Corporation', NAICS --, size '9: 500+ employees', column Firms", corporations["firms"]["500+"], "count", "2: Corporation"),
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, United States, LFO '4: Partnership', NAICS --, size '2: <5 employees', column Firms", distributions["Partnership"]["parameters"]["firms"]["<5"], "count", "4: Partnership"),
    ]
    entry["assumed"] = SUSB_DERIVED
    entry["tests"] = share_tests(corporations, "Corporation", 1) + share_tests(distributions["S-Corporation"]["parameters"], "S-Corporation", 1) + share_tests(distributions["Partnership"]["parameters"], "Partnership", 1)
    entry["notes"] = (
        "For each legal form of organization (Total, Corporation, S-Corporation, Partnership, Sole Propietorship as the "
        "source spells it, Nonprofit, Government, Other), the share of US employer firms in the enterprise employment size "
        "classes <5, 5-9, 10-19, 20-99, 100-499 and 500+, with the published firms, establishments, employment, annual "
        "payroll and receipts and derived receipts and payroll per employee by class and for the subtotals <20 and <500. "
        "Pairs with the legal-form-by-sector entry to draw an entity type and a size together. " + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_employment_size_by_state(lfo_rows: list[Record]) -> Record:
    states: dict[str, Record] = {}
    for r in lfo_rows:
        if r["state"] == "00" or r["naics"] != "--" or r["lfo"] != "Total":
            continue
        state = states.setdefault(r["state_name"], {"fips": r["state"], "classes": {}})
        state["classes"][r["size"]] = with_ratios(r)
    distributions = {name: {"family": "categorical", "parameters": {"state_fips": s["fips"], **pivot(s["classes"], CLASSIC_ORDER, CLASSIC_SIZES)}} for name, s in states.items()}
    title = LFO_TITLE
    texas = distributions["Texas"]["parameters"]
    entry = base_entry(
        "us-susb-employment-size-by-state-2022",
        "US employer firms by enterprise employment size given state, with employment, payroll and receipts (SUSB 2022)",
        "conditional", ("2022-01-01", "2022-12-31"), ["susb", "firm-size", "employment-size", "by-state", "receipts"], ["market-sizing", "company-generation", "address-generation"],
    )
    entry["spec"] = {"variable": "enterprise_employment_size_class", "unit": "ratio", "given": "state", "distributions": distributions}
    entry["evidence"] = [
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, state 48 Texas, LFO '1: Total', NAICS --, size '1: Total', column Firms", texas["firms"]["Total"], "count", "Texas"),
        census_evidence(SUSB_LFO_URL, title, "sheet LFO, state 48 Texas, LFO '1: Total', NAICS --, size '6: 20-99 employees', column Firms", texas["firms"]["20-99"], "count", "6: 20-99 employees"),
    ]
    entry["assumed"] = SUSB_DERIVED
    entry["tests"] = share_tests(texas, "Texas", 1) + share_tests(distributions["California"]["parameters"], "California", 1) + share_tests(distributions["Wyoming"]["parameters"], "Wyoming", 1)
    entry["notes"] = (
        "For each state and the District of Columbia (keyed by the name the source prints, with its FIPS code), the share "
        "of employer firms with establishments in the state by enterprise employment size (<5, 5-9, 10-19, 20-99, 100-499, "
        "500+), with firms, establishments, employment, annual payroll and receipts in the state and derived receipts and "
        "payroll per employee. Size is the firm's national employment, so a large multi-state firm counts in the 500+ "
        "class of every state where it operates; state firm counts therefore add to more than the national count. "
        + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


def susb_industry_totals() -> Record:
    rows = {}
    for r in susb_detailed():
        code = r["NAICS"]
        if r["STATE"] != "00" or r["ENTRSIZE"] != "01" or not (re.fullmatch(r"\d\d(\d)?", code) or re.fullmatch(r"\d\d-\d\d", code)):
            continue
        record = susb_measures([r["FIRM"], r["ESTB"], r["EMPL"], r["PAYR"], r["RCPT"]])
        rows[code] = {
            "description": r["NAICSDSCR"],
            "level": "sector" if len(code) != 3 else "subsector",
            **record,
            "receipts_per_establishment_usd": per_unit(record["receipts_usd_thousands"], record["establishments"], 1000),
            "receipts_per_firm_usd": per_unit(record["receipts_usd_thousands"], record["firms"], 1000),
            "receipts_per_employee_usd": per_unit(record["receipts_usd_thousands"], record["employment"], 1000),
            "annual_payroll_per_employee_usd": per_unit(record["annual_payroll_usd_thousands"], record["employment"], 1000),
            "employees_per_establishment": per_unit(record["employment"], record["establishments"], digits=2),
        }
    food = rows["722"]
    entry = base_entry(
        "us-susb-industry-totals-by-naics-3-digit-2022",
        f"US firms, establishments, employment, payroll, receipts and receipts per establishment by NAICS sector and subsector (SUSB 2022, {len(rows)} codes)",
        "rule", ("2022-01-01", "2022-12-31"), ["susb", "economic-census", "by-industry", "naics", "receipts", "revenue-per-establishment", "reference-table"], ["market-sizing", "company-generation", "lbo-modelling"],
    )
    entry["spec"] = {
        "implementation": "almanac.rules.lookup_table",
        "parameters": {"release": "Statistics of US Businesses 2022, United States, all enterprise sizes", "rows": rows},
        "vectors": [
            {"input": {"key": "722", "column": "receipts_usd_thousands"}, "expected": food["receipts_usd_thousands"], "origin": "source"},
            {"input": {"key": "722", "column": "establishments"}, "expected": food["establishments"], "origin": "source"},
            {"input": {"key": "31-33", "column": "firms"}, "expected": rows["31-33"]["firms"], "origin": "source"},
            {"input": {"key": "722", "column": "receipts_per_establishment_usd"}, "expected": food["receipts_per_establishment_usd"], "origin": "derived"},
            {"input": "722", "expected": True, "origin": "source"},
            {"input": "7225", "expected": False, "origin": "derived", "note": "four-digit industries are not in this table"},
        ],
    }
    title = f"{SUSB_TITLE}: US and states, NAICS, detailed employment sizes (us_state_naics_detailedsizes_2022.txt)"
    entry["evidence"] = [
        census_evidence(SUSB_DETAILED_URL, title, "row STATE=00, NAICS=722, ENTRSIZE=01, column RCPT ($1,000)", food["receipts_usd_thousands"], "currency:USD", f"00,722,01,{food['firms']},{food['establishments']},{food['employment']}"),
        census_evidence(SUSB_DETAILED_URL, title, "row STATE=00, NAICS=31-33, ENTRSIZE=01, column FIRM", rows["31-33"]["firms"], "count", f"00,31-33,01,{rows['31-33']['firms']}"),
    ]
    entry["assumed"] = SUSB_DERIVED[:2] + [
        {"parameter": "receipts_per_establishment_usd", "value": "1000 * receipts_usd_thousands / establishments", "method": "derived", "rationale": "Average receipts per establishment in whole dollars."},
        {"parameter": "receipts_per_firm_usd", "value": "1000 * receipts_usd_thousands / firms", "method": "derived", "rationale": "Average receipts per firm in whole dollars; a firm counts once in each industry where it has an establishment."},
        {"parameter": "employees_per_establishment", "value": "employment / establishments", "method": "derived", "rationale": "Average employment per establishment, two decimals."},
    ]
    entry["tests"] = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
        {"statistic": 'value["722",receipts_usd_thousands]', "expected": food["receipts_usd_thousands"], "tolerance": 0},
        {"statistic": 'value["31-33",employment]', "expected": rows["31-33"]["employment"], "tolerance": 0},
    ]
    entry["notes"] = (
        "Employer firms, establishments, employment, annual payroll and receipts (thousands of dollars) for every "
        "NAICS sector and three-digit subsector in the United States in 2022, with derived receipts per establishment, per "
        "firm and per employee, payroll per employee and employees per establishment. SUSB takes its 2022 receipts from the "
        "2022 Economic Census, so this table stands in for the Economic Census core statistics, whose own files are "
        "published only as pipe-delimited .dat members that the verifier cannot search. It covers employer businesses only. "
        + SUSB_NOISE_NOTE + LICENSE_NOTE
    )
    return entry


# ----------------------------------------------------------------------------------------------
# Business Dynamics Statistics 2023
# ----------------------------------------------------------------------------------------------

BDS_MEASURES = {
    "firms": "firms",
    "estabs": "establishments",
    "emp": "employment",
    "estabs_entry_rate": "establishment_entry_rate_percent",
    "estabs_exit_rate": "establishment_exit_rate_percent",
    "job_creation_rate": "job_creation_rate_percent",
    "job_destruction_rate": "job_destruction_rate_percent",
    "net_job_creation_rate": "net_job_creation_rate_percent",
    "reallocation_rate": "reallocation_rate_percent",
    "firmdeath_firms": "firm_deaths",
}
BDS_NOTE = (
    "Entry, exit and job flow measures cover the twelve months before the reference date ('during the last 12 months' "
    "in the Census variable labels), and rates are percentages of the published denominator (the 'denom' column). "
    "Cells the source marks X (not applicable), D (withheld to avoid disclosing data of individual companies), N or S "
    "are omitted or null. "
)
BDS_ASSUMED = [
    {"parameter": "shares", "value": "firms in the class / firms in all classes", "method": "derived", "rationale": "Shares are computed from the published firm counts of the mutually exclusive classes."},
]


def bds_url(name: str) -> str:
    return f"{BDS_BASE}bds{BDS_YEAR}_{name}.csv" if name else f"{BDS_BASE}bds{BDS_YEAR}.csv"


def bds_rows(name: str) -> list[dict[str, str]]:
    return csv_rows(get(bds_url(name)))


def bds_record(row: Mapping[str, str]) -> Record:
    return {label: number(row[column]) for column, label in BDS_MEASURES.items()}


def bds_pivot(classes: Mapping[str, Record]) -> Record:
    result: Record = {"shares": shares({c: r["firms"] for c, r in classes.items()})}
    for measure in BDS_MEASURES.values():
        result[measure] = {c: r[measure] for c, r in classes.items()}
    return result


def bds_line(row: Mapping[str, str], columns: int) -> str:
    """The first ``columns`` comma-separated fields of a row exactly as the CSV prints them."""
    return ",".join(list(row.values())[:columns])


def bds_national_series() -> Record:
    rows = bds_rows("")
    series = []
    for r in rows:
        record = bds_record(r)
        point = {"period": r["year"], "value": record.pop("firms")}
        point.update({k: v for k, v in record.items()})
        series.append(point)
    columns = [c for c in series[0] if c not in ("period", "value")]
    latest, first = rows[-1], rows[0]
    url = bds_url("")
    entry = base_entry(
        "us-bds-business-dynamics-1978-2023",
        "US business dynamics 1978-2023: firms, establishments, employment, establishment entry and exit, job creation and destruction rates (BDS)",
        "temporal", (f"{first['year']}-01-01", f"{latest['year']}-12-31"), ["bds", "business-dynamics", "entry-exit", "job-creation", "firm-deaths", "annual-series"], ["demand-forecasting", "market-sizing"],
    )
    entry["spec"] = {"variable": "employer_firms", "unit": "count", "frequency": "annual", "columns": columns, "series": series}
    title = f"{BDS_TITLE}: economy-wide time series (bds{BDS_YEAR}.csv)"
    entry["evidence"] = [
        census_evidence(url, title, f"row year={latest['year']}, column firms", int(latest["firms"]), "count", bds_line(latest, 4)),
        census_evidence(url, title, f"row year={latest['year']}, column estabs_entry_rate", latest["estabs_entry_rate"], "percent", bds_line(latest, 7)),
        census_evidence(url, title, f"row year={first['year']}, column firms", int(first["firms"]), "count", bds_line(first, 4)),
    ]
    entry["assumed"] = []
    entry["tests"] = [
        {"statistic": f"value[{latest['year']}]", "expected": int(latest["firms"]), "tolerance": 0},
        {"statistic": f"column[establishment_entry_rate_percent,{latest['year']}]", "expected": float(latest["estabs_entry_rate"]), "tolerance": 0},
        {"statistic": f"column[job_destruction_rate_percent,{first['year']}]", "expected": float(first["job_destruction_rate"]), "tolerance": 0},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    entry["notes"] = (
        "Economy-wide annual Business Dynamics Statistics from 1978 to 2023: employer firms (the series value), "
        "establishments, employment, establishment entry and exit rates, job creation, destruction, net job creation and "
        "reallocation rates (percent) and the number of firm deaths. Use it to give a synthetic economy realistic "
        "start-up, closure and churn rates for any year. " + BDS_NOTE + LICENSE_NOTE
    )
    return entry


def bds_marginal(name: str, column: str, entry_id: str, title: str, variable: str, tags: list[str], notes: str) -> Record:
    rows = [r for r in bds_rows(name) if r["year"] == BDS_YEAR]
    classes = {strip_code(r[column]): bds_record(r) for r in rows}
    params = bds_pivot(classes)
    first, last = rows[0], rows[-1]
    url = bds_url(name)
    entry = base_entry(entry_id, title, "marginal", (f"{BDS_YEAR}-01-01", f"{BDS_YEAR}-12-31"), ["bds", "business-dynamics", *tags], ["company-generation"])
    entry["spec"] = {"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": params}}
    resource_title = f"{BDS_TITLE}: by {variable.replace('_', ' ')} (bds{BDS_YEAR}_{name}.csv)"
    entry["evidence"] = [
        census_evidence(url, resource_title, f"row year={BDS_YEAR}, {column}='{first[column]}', column firms", int(first["firms"]), "count", bds_line(first, 3)),
        census_evidence(url, resource_title, f"row year={BDS_YEAR}, {column}='{last[column]}', column firms", int(last["firms"]), "count", bds_line(last, 3)),
    ]
    entry["assumed"] = BDS_ASSUMED
    entry["tests"] = share_tests(params, picks=3)
    entry["notes"] = notes + " " + BDS_NOTE + LICENSE_NOTE
    return entry


def bds_conditional(name: str, given_column: str, column: str, entry_id: str, title: str, variable: str, given: str, tags: list[str], picks: list[str], notes: str, labels: Mapping[str, str] | None = None) -> Record:
    rows = [r for r in bds_rows(name) if r["year"] == BDS_YEAR]
    grouped: dict[str, dict[str, Record]] = {}
    for r in rows:
        grouped.setdefault(strip_code(r[given_column]), {})[strip_code(r[column])] = bds_record(r)
    distributions = {}
    for key, classes in grouped.items():
        params = bds_pivot({c: rec for c, rec in classes.items() if rec["firms"]})
        if labels:
            params = {"label": labels.get(key, key), **params}
        distributions[key] = {"family": "categorical", "parameters": params}
    url = bds_url(name)
    entry = base_entry(entry_id, title, "conditional", (f"{BDS_YEAR}-01-01", f"{BDS_YEAR}-12-31"), ["bds", "business-dynamics", *tags], ["company-generation"])
    entry["spec"] = {"variable": variable, "unit": "ratio", "given": given, "distributions": distributions}
    resource_title = f"{BDS_TITLE}: by {given.replace('_', ' ')} and {variable.replace('_', ' ')} (bds{BDS_YEAR}_{name}.csv)"
    first = rows[0]
    sample = next(r for r in rows if strip_code(r[given_column]) == picks[0] and number(r["firms"]))
    entry["evidence"] = [
        census_evidence(url, resource_title, f"row year={BDS_YEAR}, {given_column}='{first[given_column]}', {column}='{first[column]}', column firms", int(first["firms"]), "count", bds_line(first, 4)),
        census_evidence(url, resource_title, f"row year={BDS_YEAR}, {given_column}='{sample[given_column]}', {column}='{sample[column]}', column firms", int(sample["firms"]), "count", bds_line(sample, 4)),
    ]
    entry["assumed"] = BDS_ASSUMED + ([LABEL_ASSUMPTION] if labels else [])
    entry["tests"] = [t for key in picks for t in share_tests(distributions[key]["parameters"], key, 1)]
    entry["notes"] = notes + " " + BDS_NOTE + LICENSE_NOTE
    return entry


def sector_labels(lfo_rows: list[Record]) -> dict[str, str]:
    """Sector titles keyed by NAICS sector code from the SUSB legal-form workbook, which BDS and CBP codes share."""
    return {r["naics"]: r["naics_label"] for r in lfo_rows if r["naics"] != "--"}


def bds_sector_rates(labels: Mapping[str, str]) -> Record:
    rows = bds_rows("sec")
    years = [str(y) for y in range(int(BDS_YEAR) - 4, int(BDS_YEAR) + 1)]
    table: dict[str, Record] = {}
    for r in rows:
        if r["year"] not in years:
            continue
        row = table.setdefault(r["sector"], {"label": labels.get(r["sector"], r["sector"])})
        record = bds_record(r)
        for measure in ("firms", "employment", "establishment_entry_rate_percent", "establishment_exit_rate_percent", "job_creation_rate_percent", "job_destruction_rate_percent", "reallocation_rate_percent", "firm_deaths"):
            row[f"{measure}_{r['year']}"] = record[measure]
    latest = next(r for r in rows if r["year"] == BDS_YEAR and r["sector"] == "54")
    url = bds_url("sec")
    entry = base_entry(
        "us-bds-sector-dynamics-2019-2023",
        "US business dynamics by NAICS sector, 2019-2023: firms, employment, establishment entry and exit, job flows and firm deaths (BDS)",
        "rule", (f"{years[0]}-01-01", f"{BDS_YEAR}-12-31"), ["bds", "business-dynamics", "entry-exit", "by-sector", "firm-deaths", "reference-table"], ["market-sizing", "credit-risk"],
    )
    rate = f"establishment_entry_rate_percent_{BDS_YEAR}"
    entry["spec"] = {
        "implementation": "almanac.rules.lookup_table",
        "parameters": {"release": f"Business Dynamics Statistics {BDS_YEAR} release, sector table", "rows": table},
        "vectors": [
            {"input": {"key": "54", "column": rate}, "expected": float(latest["estabs_entry_rate"]), "origin": "source"},
            {"input": {"key": "54", "column": f"firms_{BDS_YEAR}"}, "expected": int(latest["firms"]), "origin": "source"},
            {"input": "62", "expected": True, "origin": "source"},
            {"input": "92", "expected": False, "origin": "derived", "note": "BDS excludes public administration"},
        ],
    }
    entry["evidence"] = [
        census_evidence(url, f"{BDS_TITLE}: by sector (bds{BDS_YEAR}_sec.csv)", f"row year={BDS_YEAR}, sector=54, column estabs_entry_rate", latest["estabs_entry_rate"], "percent", bds_line(latest, 9)),
        census_evidence(SUSB_LFO_URL, LFO_TITLE, "sheet LFO, column 'NAICS Description' for NAICS 54 (sector title used as label)", labels["54"], "text", labels["54"], role="supporting"),
    ]
    entry["assumed"] = [LABEL_ASSUMPTION]
    entry["tests"] = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(table), "tolerance": 0},
        {"statistic": f'value["54",{rate}]', "expected": float(latest["estabs_entry_rate"]), "tolerance": 0},
        {"statistic": f"max[{rate}]", "expected": max(v[rate] for v in table.values() if v.get(rate) is not None), "tolerance": 0},
    ]
    entry["notes"] = (
        f"For each NAICS sector, five years ({years[0]} to {BDS_YEAR}) of employer firms, employment, establishment entry and "
        "exit rates, job creation and destruction rates, reallocation rate and firm deaths, with the column name suffixed by "
        "the year. Lets a sourcing or credit model tell high-churn sectors (construction, accommodation and food) from "
        "stable ones. " + BDS_NOTE + LICENSE_NOTE
    )
    return entry


# ----------------------------------------------------------------------------------------------
# County Business Patterns 2023
# ----------------------------------------------------------------------------------------------

CBP_SIZES = [("<5", "<5"), ("5-9", "5_9"), ("10-19", "10_19"), ("20-49", "20_49"), ("50-99", "50_99"), ("100-249", "100_249"), ("250-499", "250_499"), ("500-999", "500_999"), ("1,000+", "1000")]
CBP_NOTE = (
    "CBP counts establishments with paid employees; its size classes (columns n<5 to n1000) are the establishment's own "
    "employment, not the firm's. Employment, payroll and first-quarter payroll carry noise "
    "flags (G low, H medium, J high, N not available); establishment counts carry none. Size classes whose count the "
    "source prints as N are null and left out of the shares, so the published classes can add to slightly less than "
    "the total. "
)
CBP_ASSUMED = [
    {"parameter": "shares", "value": "establishments in the class / establishments in all classes", "method": "derived", "rationale": "Shares are computed from the published establishment counts n<5 to n1000; classes printed as N are left out."},
    {"parameter": "annual_payroll_per_employee_usd", "value": "1000 * ap / emp", "method": "derived", "rationale": "Annual payroll ($1,000) per employee in whole dollars, by class where the source publishes both."},
]


def cbp_rows(url: str) -> list[dict[str, str]]:
    return csv_rows(zip_member(get(url)))


def cbp_sector(code: str) -> str | None:
    """'31----' -> '31-33'-style sector keys as SUSB writes them; None for anything below sector level."""
    if code == "------":
        return "all"
    match = re.fullmatch(r"(\d\d)----", code)
    if not match:
        return None
    return {"31": "31-33", "44": "44-45", "48": "48-49"}.get(match.group(1), match.group(1))


def cbp_slice(row: Mapping[str, str]) -> Record:
    """Establishments, employment and payroll by establishment size class for one CBP row."""
    est = {label: number(row[f"n{suffix}"]) for label, suffix in CBP_SIZES}
    emp = {label: number(row[f"e{suffix}"]) for label, suffix in CBP_SIZES}
    payroll = {label: number(row[f"a{suffix}"]) for label, suffix in CBP_SIZES}
    return {
        "shares": shares(est),
        "establishments": {**est, "Total": int(row["est"])},
        "employment": {**emp, "Total": number(row["emp"])},
        "annual_payroll_usd_thousands": {**payroll, "Total": number(row["ap"])},
        "annual_payroll_per_employee_usd": {**{k: per_unit(payroll[k], emp[k], 1000) for k in est}, "Total": per_unit(number(row["ap"]), number(row["emp"]), 1000)},
    }


def cbp_line(url: str, row: Mapping[str, str], columns: int) -> str:
    """The first ``columns`` fields of the row's line exactly as the CSV prints them, quotes included."""
    key = ",".join(f'"{v}"' for v in list(row.values())[:3])
    text = zip_member(RESOURCES[url]).decode("utf-8")
    start = text.index("\n" + key + ",") + 1
    return ",".join(text[start:text.index("\n", start)].split(",")[:columns])


def cbp_size_by_sector(labels: Mapping[str, str]) -> Record:
    rows = [r for r in cbp_rows(CBP_US_URL) if r["lfo"] == "-" and cbp_sector(r["naics"])]
    distributions = {}
    for r in rows:
        key = cbp_sector(r["naics"])
        distributions[key] = {"family": "categorical", "parameters": {"label": "All sectors" if key == "all" else labels[key], **cbp_slice(r)}}
    total = next(r for r in rows if r["naics"] == "------")
    manufacturing = next(r for r in rows if r["naics"] == "31----")
    entry = base_entry(
        "us-cbp-establishment-size-by-sector-2023",
        "US establishments by employment size class given NAICS sector, with employment and payroll per employee (CBP 2023)",
        "conditional", ("2023-01-01", "2023-12-31"), ["cbp", "establishments", "establishment-size", "by-sector", "payroll"], ["market-sizing", "company-generation", "payroll-demo"],
    )
    entry["spec"] = {"variable": "establishment_employment_size_class", "unit": "ratio", "given": "naics_sector", "distributions": distributions}
    title = f"{CBP_TITLE}: US by NAICS and legal form (cbp23us.zip, cbp23us.txt)"
    entry["evidence"] = [
        census_evidence(CBP_US_URL, title, 'row naics="------", lfo="-", column est', int(total["est"]), "count", cbp_line(CBP_US_URL, total, 10)),
        census_evidence(CBP_US_URL, title, 'row naics="31----", lfo="-", column est', int(manufacturing["est"]), "count", cbp_line(CBP_US_URL, manufacturing, 10)),
    ]
    entry["assumed"] = CBP_ASSUMED + [LABEL_ASSUMPTION, {"parameter": "sector keys", "value": "31----, 44---- and 48---- keyed as 31-33, 44-45 and 48-49", "method": "derived", "rationale": "CBP writes each multi-code sector under its first code; the keys follow SUSB and BDS so the entries join on one sector code."}]
    entry["tests"] = share_tests(distributions["all"]["parameters"], "all", 2) + share_tests(distributions["31-33"]["parameters"], "31-33", 1) + share_tests(distributions["72"]["parameters"], "72", 1)
    entry["notes"] = (
        "For each NAICS sector (keyed by the SUSB-style code, with 'all' for all sectors and '99' for industries not "
        "classified), the share of US establishments in each establishment employment size class (<5 to 1,000+), with "
        "establishment counts, employment, annual payroll ($1,000) and derived annual payroll per employee by "
        "class and in total. " + CBP_NOTE + LICENSE_NOTE
    )
    return entry


def cbp_state_names(lfo_rows: list[Record]) -> dict[str, str]:
    return {r["state"]: r["state_name"] for r in lfo_rows if r["state"] != "00"}


def cbp_size_by_state(names: Mapping[str, str]) -> Record:
    rows = [r for r in cbp_rows(CBP_STATE_URL) if r["lfo"] == "-" and r["naics"] == "------"]
    distributions = {names[r["fipstate"]]: {"family": "categorical", "parameters": {"state_fips": r["fipstate"], **cbp_slice(r)}} for r in rows}
    california = next(r for r in rows if r["fipstate"] == "06")
    entry = base_entry(
        "us-cbp-establishment-size-by-state-2023",
        "US establishments by employment size class given state, with employment and payroll per employee (CBP 2023)",
        "conditional", ("2023-01-01", "2023-12-31"), ["cbp", "establishments", "establishment-size", "by-state", "payroll"], ["market-sizing", "company-generation", "address-generation"],
    )
    entry["spec"] = {"variable": "establishment_employment_size_class", "unit": "ratio", "given": "state", "distributions": distributions}
    title = f"{CBP_TITLE}: states by NAICS and legal form (cbp23st.zip, cbp23st.txt)"
    entry["evidence"] = [census_evidence(CBP_STATE_URL, title, 'row fipstate="06", naics="------", lfo="-", column est', int(california["est"]), "count", cbp_line(CBP_STATE_URL, california, 10))]
    entry["assumed"] = CBP_ASSUMED + [{"parameter": "state names", "value": "names from the SUSB 2022 legal-form workbook keyed by FIPS code", "method": "derived", "rationale": "The CBP state file carries FIPS codes only; names come from the SUSB workbook, which prints both."}]
    entry["tests"] = share_tests(distributions["California"]["parameters"], "California", 1) + share_tests(distributions["Texas"]["parameters"], "Texas", 1) + share_tests(distributions["Vermont"]["parameters"], "Vermont", 1)
    entry["notes"] = (
        "For each state and the District of Columbia (keyed by name, with the FIPS code), the share of establishments in "
        "each establishment employment size class (<5 to 1,000+) across all sectors, with establishment counts, "
        "employment, annual payroll ($1,000) and derived payroll per employee by class. " + CBP_NOTE + LICENSE_NOTE
    )
    return entry


def cbp_sector_by_state(names: Mapping[str, str]) -> Record:
    rows = [r for r in cbp_rows(CBP_STATE_URL) if r["lfo"] == "-" and cbp_sector(r["naics"]) not in (None, "all")]
    grouped: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        grouped.setdefault(r["fipstate"], []).append(r)
    distributions = {}
    for fips, state_rows in grouped.items():
        est = {cbp_sector(r["naics"]): int(r["est"]) for r in state_rows}
        emp = {cbp_sector(r["naics"]): number(r["emp"]) for r in state_rows}
        payroll = {cbp_sector(r["naics"]): number(r["ap"]) for r in state_rows}
        distributions[names[fips]] = {"family": "categorical", "parameters": {
            "state_fips": fips,
            "shares": shares(est),
            "establishments": est,
            "employment": emp,
            "annual_payroll_usd_thousands": payroll,
            "annual_payroll_per_employee_usd": {k: per_unit(payroll[k], emp[k], 1000) for k in est},
        }}
    sample = next(r for r in rows if r["fipstate"] == "36" and r["naics"] == "52----")
    entry = base_entry(
        "us-cbp-establishments-by-sector-and-state-2023",
        "US establishments by NAICS sector given state, with employment and payroll per employee (CBP 2023)",
        "conditional", ("2023-01-01", "2023-12-31"), ["cbp", "establishments", "by-state", "by-sector", "payroll"], ["market-sizing", "company-generation", "address-generation"],
    )
    entry["spec"] = {"variable": "naics_sector", "unit": "ratio", "given": "state", "distributions": distributions}
    title = f"{CBP_TITLE}: states by NAICS and legal form (cbp23st.zip, cbp23st.txt)"
    entry["evidence"] = [census_evidence(CBP_STATE_URL, title, 'row fipstate="36", naics="52----", lfo="-", column est', int(sample["est"]), "count", cbp_line(CBP_STATE_URL, sample, 10))]
    entry["assumed"] = [
        {"parameter": "shares", "value": "establishments in the sector / establishments in all sector rows of the state", "method": "derived", "rationale": "Shares are computed from the published sector establishment counts, including sector 99 (industries not classified)."},
        CBP_ASSUMED[1],
        {"parameter": "state names", "value": "names from the SUSB 2022 legal-form workbook keyed by FIPS code", "method": "derived", "rationale": "The CBP state file carries FIPS codes only; names come from the SUSB workbook, which prints both."},
    ]
    entry["tests"] = share_tests(distributions["New York"]["parameters"], "New York", 1) + share_tests(distributions["Florida"]["parameters"], "Florida", 1)
    entry["notes"] = (
        "For each state and the District of Columbia, the share of establishments in each NAICS sector (keyed by the "
        "SUSB-style sector code; the source writes 31----, 44---- and 48---- for 31-33, 44-45 and 48-49), with establishment "
        "counts, employment, annual payroll ($1,000) and derived payroll per employee. Sector titles are in the "
        "CBP size-by-sector entry. " + CBP_NOTE + LICENSE_NOTE
    )
    return entry


def cbp_size_by_state_and_sector(names: Mapping[str, str]) -> Record:
    rows = [r for r in cbp_rows(CBP_STATE_URL) if r["lfo"] == "-" and cbp_sector(r["naics"]) not in (None, "all")]
    table = {}
    for r in rows:
        key = f"{r['fipstate']}|{cbp_sector(r['naics'])}"
        table[key] = {"establishments": int(r["est"]), **{f"establishments_{label}": number(r[f"n{suffix}"]) for label, suffix in CBP_SIZES}}
    sample_row = next(r for r in rows if r["fipstate"] == "48" and r["naics"] == "23----")
    sample = table["48|23"]
    entry = base_entry(
        "us-cbp-establishment-size-by-state-and-sector-2023",
        "US establishment counts by employment size class for every state and NAICS sector (CBP 2023)",
        "rule", ("2023-01-01", "2023-12-31"), ["cbp", "establishments", "establishment-size", "by-state", "by-sector", "reference-table"], ["market-sizing", "company-generation"],
    )
    entry["spec"] = {
        "implementation": "almanac.rules.lookup_table",
        "parameters": {"release": "County Business Patterns 2023, state file, all legal forms", "key": "state FIPS code | NAICS sector code", "state_names": {fips: names[fips] for fips in sorted({k.split("|")[0] for k in table})}, "rows": table},
        "vectors": [
            {"input": {"key": "48|23", "column": "establishments"}, "expected": sample["establishments"], "origin": "source"},
            {"input": {"key": "48|23", "column": "establishments_<5"}, "expected": sample["establishments_<5"], "origin": "source"},
            {"input": "06|54", "expected": True, "origin": "source"},
            {"input": "48|92", "expected": False, "origin": "derived", "note": "CBP excludes public administration"},
        ],
    }
    title = f"{CBP_TITLE}: states by NAICS and legal form (cbp23st.zip, cbp23st.txt)"
    entry["evidence"] = [census_evidence(CBP_STATE_URL, title, 'row fipstate="48", naics="23----", lfo="-", columns est and n<5', sample["establishments"], "count", cbp_line(CBP_STATE_URL, sample_row, 10))]
    entry["assumed"] = [{"parameter": "state_names", "value": "names from the SUSB 2022 legal-form workbook keyed by FIPS code", "method": "derived", "rationale": "The CBP state file carries FIPS codes only; names come from the SUSB workbook, which prints both."}]
    entry["tests"] = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(table), "tolerance": 0},
        {"statistic": 'value["48|23",establishments_<5]', "expected": sample["establishments_<5"], "tolerance": 0},
        {"statistic": "max[establishments]", "expected": max(r["establishments"] for r in table.values()), "tolerance": 0},
    ]
    entry["notes"] = (
        "Establishment counts by establishment employment size class (<5, 5-9, 10-19, 20-49, 50-99, 100-249, 250-499, "
        "500-999, 1,000+) and in total for every state and NAICS sector, keyed 'FIPS|sector' (for example '48|23' is "
        "construction in Texas; sector codes follow SUSB, so manufacturing is '31-33'). The counts are the published "
        "establishment counts, which carry no noise. Use it to place a synthetic establishment in a state, sector and size "
        "class at once. " + CBP_NOTE + LICENSE_NOTE
    )
    return entry


# ----------------------------------------------------------------------------------------------
# Business Formation Statistics, 2025
# ----------------------------------------------------------------------------------------------

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
BFS_SERIES = {"BA_BA": "business_applications", "BA_HBA": "high_propensity_applications", "BA_WBA": "applications_with_planned_wages", "BA_CBA": "applications_from_corporations"}
BFS_NOTE = (
    "Business applications are applications for an Employer Identification Number on IRS Form SS-4; the Census Bureau "
    "classes as high-propensity those whose characteristics are associated with a high rate of becoming a business "
    "with payroll, and as applications with planned wages the high-propensity ones that state a first wages-paid date. "
    "The file at this URL is replaced with each monthly release and recent months are revised, so the content hash is "
    "expected to change at the next release. "
)


def bfs_rows() -> list[dict[str, str]]:
    return [r for r in csv_rows(get(BFS_URL)) if r["year"] == BFS_YEAR]


def bfs_line(row: Mapping[str, str], months: int = 2) -> str:
    return ",".join(list(row.values())[: 5 + months])


def bfs_series_evidence() -> Record:
    return census_evidence(BFS_DOCUMENTATION_URL, "Business Formation Statistics: technical documentation (technical_documentation.pdf)", "slide 'Available Business Formation Statistics Data', series list", "WBA", "text", "Business Applications with Planned Wages (WBA)", role="supporting")


def bfs_monthly_national() -> Record:
    rows = {(r["sa"], r["series"]): r for r in bfs_rows() if r["geo"] == "US" and r["naics_sector"] == "TOTAL"}
    series = []
    for i, month in enumerate(MONTHS):
        point: Record = {"period": f"{BFS_YEAR}-{i + 1:02d}", "value": number(rows[("U", "BA_BA")][month])}
        for code, name in BFS_SERIES.items():
            if code != "BA_BA":
                point[name] = number(rows[("U", code)][month])
        for code, name in BFS_SERIES.items():
            point[f"{name}_seasonally_adjusted"] = number(rows[("A", code)][month])
        point["projected_business_formations_within_4_quarters"] = number(rows[("U", "BF_PBF4Q")][month])
        series.append(point)
    columns = [c for c in series[0] if c not in ("period", "value")]
    ba = rows[("U", "BA_BA")]
    hba = rows[("U", "BA_HBA")]
    entry = base_entry(
        "us-bfs-business-applications-monthly-2025",
        "US business applications by month, 2025: all, high-propensity, planned-wage and corporate, unadjusted and seasonally adjusted (BFS)",
        "temporal", (f"{BFS_YEAR}-01-01", f"{BFS_YEAR}-12-31"), ["bfs", "business-applications", "business-formation", "start-ups", "monthly-series", "leading-indicator"], ["demand-forecasting", "event-timestamps"],
    )
    entry["spec"] = {"variable": "business_applications", "unit": "count", "frequency": "monthly", "columns": columns, "series": series}
    entry["evidence"] = [
        census_evidence(BFS_URL, BFS_TITLE, f"row sa=U, naics_sector=TOTAL, series=BA_BA, geo=US, year={BFS_YEAR}, columns jan and feb", number(ba["jan"]), "count", bfs_line(ba)),
        census_evidence(BFS_URL, BFS_TITLE, f"row sa=U, naics_sector=TOTAL, series=BA_HBA, geo=US, year={BFS_YEAR}, columns jan and feb", number(hba["jan"]), "count", bfs_line(hba)),
        bfs_series_evidence(),
    ]
    entry["assumed"] = []
    entry["tests"] = [
        {"statistic": f"value[{BFS_YEAR}-01]", "expected": number(ba["jan"]), "tolerance": 0},
        {"statistic": f"column[high_propensity_applications,{BFS_YEAR}-01]", "expected": number(hba["jan"]), "tolerance": 0},
        {"statistic": "count", "expected": 12, "tolerance": 0},
    ]
    entry["notes"] = (
        f"Monthly US business applications in {BFS_YEAR}, not seasonally adjusted (the series value), with high-propensity "
        "applications, applications with planned wages and applications from corporations, the seasonally adjusted "
        "versions of all four, and the projected number of business formations within four quarters. " + BFS_NOTE + LICENSE_NOTE
    )
    return entry


def bfs_annual(rows: list[dict[str, str]], key: str) -> dict[str, Record]:
    """Annual totals and monthly figures of the unadjusted application series, grouped by ``key``."""
    out: dict[str, Record] = {}
    for r in rows:
        if r["sa"] != "U" or r["series"] not in BFS_SERIES:
            continue
        months = [number(r[m]) for m in MONTHS]
        record = out.setdefault(r[key], {})
        record[BFS_SERIES[r["series"]]] = sum(months)
        record[f"{BFS_SERIES[r['series']]}_monthly"] = dict(zip(MONTHS, months))
    return out


def bfs_marginal(entry_id: str, title: str, variable: str, rows: list[dict[str, str]], key: str, sample: str, tags: list[str], notes: str, assumed: list[Record]) -> Record:
    annual = bfs_annual(rows, key)
    params: Record = {"shares": shares({k: v["business_applications"] for k, v in annual.items()})}
    for name in BFS_SERIES.values():
        params[name] = {k: v[name] for k, v in annual.items()}
    params["high_propensity_share"] = {k: per_unit(v["high_propensity_applications"], v["business_applications"], digits=4) for k, v in annual.items()}
    for name in ("business_applications", "high_propensity_applications", "applications_with_planned_wages"):
        params[f"{name}_monthly"] = {k: v[f"{name}_monthly"] for k, v in annual.items()}
    row = next(r for r in rows if r[key] == sample and r["sa"] == "U" and r["series"] == "BA_BA")
    entry = base_entry(entry_id, title, "marginal", (f"{BFS_YEAR}-01-01", f"{BFS_YEAR}-12-31"), ["bfs", "business-applications", "business-formation", "start-ups", *tags], ["market-sizing"])
    entry["spec"] = {"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": params}}
    entry["evidence"] = [
        census_evidence(BFS_URL, BFS_TITLE, f"row sa=U, series=BA_BA, {key}={sample}, year={BFS_YEAR}, columns jan and feb", number(row["jan"]), "count", bfs_line(row)),
        bfs_series_evidence(),
    ]
    entry["assumed"] = [
        {"parameter": "annual totals", "value": "sum of the twelve unadjusted monthly figures", "method": "derived", "rationale": "The file publishes months only; annual totals add the unadjusted months."},
        {"parameter": "shares", "value": "annual business applications / sum over all categories", "method": "derived", "rationale": "Shares of the derived annual totals of all business applications."},
        {"parameter": "high_propensity_share", "value": "high_propensity_applications / business_applications", "method": "derived", "rationale": "Fraction of the year's applications that are high-propensity, four decimals."},
        *assumed,
    ]
    entry["tests"] = share_tests(params, picks=3)
    entry["notes"] = notes + " " + BFS_NOTE + LICENSE_NOTE
    return entry


def bfs_by_state() -> Record:
    rows = [r for r in bfs_rows() if r["naics_sector"] == "TOTAL" and re.fullmatch(r"[A-Z]{2}", r["geo"]) and r["geo"] not in ("US", "MW", "NO", "SO", "WE", "PR")]
    return bfs_marginal(
        "us-bfs-business-applications-by-state-2025",
        "US business applications by state, 2025: share of all applications, with high-propensity and planned-wage counts by month (BFS)",
        "state", rows, "geo", "CA", ["by-state"],
        f"Business applications filed in {BFS_YEAR} in each state and the District of Columbia (keyed by postal code): the share of "
        "all applications, annual totals of all, high-propensity, planned-wage and corporate applications, the high-propensity "
        "share, and unadjusted monthly figures for the first three series. Regional aggregates and Puerto Rico are left out.",
        [],
    )


def bfs_by_sector() -> Record:
    rows = [r for r in bfs_rows() if r["geo"] == "US" and r["naics_sector"] != "TOTAL"]
    return bfs_marginal(
        "us-bfs-business-applications-by-sector-2025",
        "US business applications by NAICS sector, 2025: share of all applications, with high-propensity and planned-wage counts by month (BFS)",
        "naics_sector", rows, "naics_sector", "NAICS54", ["by-sector"],
        f"US business applications filed in {BFS_YEAR} by NAICS sector, keyed by the codes the file uses (NAICS11 to NAICS81, "
        "NAICSMNF, NAICSRET, NAICSTW and NONAICS for applications without a sector): the share of all applications, annual "
        "totals of all, high-propensity, planned-wage and corporate applications, the high-propensity share, and unadjusted "
        "monthly figures for the first three series.",
        [{"parameter": "NAICSMNF, NAICSRET, NAICSTW", "value": "stand for sectors 31-33, 44-45 and 48-49", "method": "derived", "rationale": "The file lists every other sector by its two-digit code and omits these three multi-code sectors, which these three codes fill."}],
    )


# ----------------------------------------------------------------------------------------------
# Annual Business Survey, reference year 2024
# ----------------------------------------------------------------------------------------------

ABS_NOTE = (
    "Percentages of employer firms classifiable by owner sex, ethnicity, race and veteran status, from the 2025 Annual "
    "Business Survey (reference year 2024); the source marks these data preliminary. Groups overlap: a firm can count in "
    "more than one race group and in the minority and sex rows at once. Estimates the source marks S are null. "
)


def abs_table(url: str) -> tuple[list[str], dict[str, Record], dict[str, Record]]:
    """Answer columns, then percentages and standard errors keyed by owner group, from one ABS company-information table."""
    rows = xlsx_rows(url)
    header = rows[5]
    width = next(i for i, h in enumerate(header) if h and str(h).strip().startswith("SE"))
    answers = [" ".join(str(h).split()) for h in header[1:width]]
    percents, errors = {}, {}
    for r in rows[6:]:
        if r[0] is None:
            break
        if all(v is None for v in r[1:]):
            continue
        group = " ".join(str(r[0]).split())
        percents[group] = {a: number(v) for a, v in zip(answers, r[1:width])}
        errors[group] = {a: number(v) for a, v in zip(answers, r[width:2 * width - 1])}
    return answers, percents, errors


def abs_distribution(url: str, entry_id: str, title: str, variable: str, resource_title: str, notes: str) -> Record:
    answers, percents, errors = abs_table(url)
    answers = [a for a in answers if a != "Total"]
    distributions = {}
    for group, values in percents.items():
        distributions[group] = {"family": "categorical", "parameters": {
            "shares": {a: round(values[a] / 100, 4) for a in answers if values[a] is not None},
            "percent_of_employer_firms": {a: values[a] for a in answers},
            "standard_error_percentage_points": {a: errors[group][a] for a in answers},
        }}
    sample = percents["Total"]
    first = answers[0]
    entry = base_entry(entry_id, title, "conditional", ("2024-01-01", "2024-12-31"), ["abs", "owner-demographics", "credit", "small-business-lending"], ["private-credit-demo", "credit-risk", "loan-pricing"])
    entry["spec"] = {"variable": variable, "unit": "ratio", "given": "owner_group", "distributions": distributions}
    entry["evidence"] = [
        census_evidence(url, resource_title, f"row Total, column '{first}'", sample[first], "percent", " ".join(str(xlsx_rows(url)[1][0]).split())),
        census_evidence(url, resource_title, "row Female, column '" + answers[1] + "'", percents["Female"][answers[1]], "percent", "Estimates in this table cover reference year 2024"),
    ]
    entry["assumed"] = [{"parameter": "shares", "value": "published percent / 100", "method": "derived", "rationale": "The published percentages of employer firms restated as fractions; they add to one up to the source's rounding."}]
    entry["tests"] = [
        {"statistic": f'share["Total","{first}"]', "expected": round(sample[first] / 100, 4), "tolerance": SHARE_TOLERANCE},
        {"statistic": 'sum_of_shares["Total"]', "expected": 1, "tolerance": 0.002},
        {"statistic": f'share["Female","{answers[1]}"]', "expected": round(percents["Female"][answers[1]] / 100, 4), "tolerance": SHARE_TOLERANCE},
    ]
    entry["notes"] = notes + " " + ABS_NOTE + LICENSE_NOTE
    return entry


def abs_lending_sources() -> Record:
    answers, percents, errors = abs_table(ABS_SOURCES_URL)
    rows = {group: {**{a: v for a, v in values.items()}, **{f"SE {a}": errors[group][a] for a in answers}} for group, values in percents.items()}
    total = rows["Total"]
    resource_title = "Annual Business Survey 2025, Company Information Table 2: lending sources of new credit (CI-2)"
    entry = base_entry(
        "us-abs-lending-sources-of-new-credit-by-owner-group-2024",
        "US employer firms' lending sources of new credit in 2024 (bank, credit union, fintech, finance company, CDFI) by owner group (ABS)",
        "rule", ("2024-01-01", "2024-12-31"), ["abs", "owner-demographics", "credit", "small-business-lending", "fintech", "reference-table"], ["private-credit-demo", "credit-risk", "loan-pricing"],
    )
    entry["spec"] = {
        "implementation": "almanac.rules.lookup_table",
        "parameters": {"release": "2025 Annual Business Survey, reference year 2024, preliminary", "unit": "percent of employer firms; SE columns are standard errors in percentage points", "rows": rows},
        "vectors": [
            {"input": {"key": "Total", "column": "Bank"}, "expected": total["Bank"], "origin": "source"},
            {"input": {"key": "Total", "column": "Fintech/online lender"}, "expected": total["Fintech/online lender"], "origin": "source"},
            {"input": "Veteran", "expected": True, "origin": "source"},
        ],
    }
    entry["evidence"] = [
        census_evidence(ABS_SOURCES_URL, resource_title, "row Total, column Bank", total["Bank"], "percent", "Lending sources of new credit by sex, race, ethnicity, minority status, and veteran status: 2024"),
        census_evidence(ABS_SOURCES_URL, resource_title, "row Total, column Fintech/online lender", total["Fintech/online lender"], "percent", "Fintech/online lender"),
    ]
    entry["assumed"] = []
    entry["tests"] = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
        {"statistic": 'value["Total",Bank]', "expected": total["Bank"], "tolerance": 0},
    ]
    entry["notes"] = (
        "For each owner group (Total, sex, race, ethnicity, minority and veteran status), the percentage of employer firms "
        "that used each lending source (bank, credit union, fintech or online lender, finance company, Community Development "
        "Financial Institution, other) for new credit in 2024, with standard errors. A firm can name several sources, so a "
        "row adds to more than 100. Keys are the source's row labels with whitespace collapsed. " + ABS_NOTE + LICENSE_NOTE
    )
    return entry


# ----------------------------------------------------------------------------------------------
# Quarterly Financial Report, return and balance-sheet ratios
# ----------------------------------------------------------------------------------------------

QFR_INCOME_RATIOS = {
    "Total current assets to total current liabilities": "current_ratio",
    "Total cash, U.S. Government and other securities, to total current liabilities": "cash_to_current_liabilities",
    "Total stockholders' equity to total debt": "equity_to_total_debt",
}
QFR_BALANCE_RATIOS = {
    "Short-term debt, including current portion of long-term debt": "short_term_debt_percent_of_assets",
    "Long-term debt": "long_term_debt_percent_of_assets",
    "Total liabilities": "total_liabilities_percent_of_assets",
    "Stockholders' equity": "stockholders_equity_percent_of_assets",
}
QFR_ASSUMED = [
    {"parameter": "total_liabilities_to_equity", "value": "Total liabilities / Stockholders' equity (balance sheet, million dollars)", "method": "derived", "rationale": "Leverage ratio from the two balance-sheet totals of the same quarter and industry, two decimals."},
    {"parameter": "interest_coverage", "value": "Income (loss) from operations / Interest expense (income statement, million dollars)", "method": "derived", "rationale": "Operating income over interest expense for the quarter, two decimals; an EBIT-style coverage, as the QFR does not publish EBITDA."},
    {"parameter": "rows", "value": "one row per column heading", "method": "derived", "rationale": "Row keys are the Census column headings; each row's NAICS scope comes from its table title."},
]


def qfr_label(cell: Any) -> str:
    return " ".join(re.sub(r"[.…]{2,}", " ", str(cell or "")).replace("…", " ").split())


def qfr_sheet(workbook: Any, table: int, part: int) -> list[tuple]:
    return list(workbook[f"T{table:02d}_{part}-{QFR_QUARTER}"].iter_rows(values_only=True))


def qfr_quarters(rows: list[tuple]) -> list[str]:
    raw = [re.sub(r"\s+", "", str(q)).replace("_", "") for q in rows[4][1:6]]
    return [f"{q[2:]}Q{q[0]}" for q in raw]


def qfr_find(rows: list[tuple], label: str, start: int = 0) -> tuple | None:
    return next((r for r in rows[start:] if qfr_label(r[0]) == label), None)


def qfr_index(rows: list[tuple], test: Callable[[str], bool]) -> int | None:
    return next((i for i, r in enumerate(rows) if test(qfr_label(r[0]))), None)


def qfr_blocks(workbook: Any, table: int) -> list[Record]:
    """Return and balance-sheet ratios of each column block of one QFR table pair.

    The asset-size tables for $50 million and over print no balance-sheet ratio section, so those
    published ratios are absent from their rows; the derived leverage and coverage are present for every row.
    """
    income = qfr_sheet(workbook, table, 0)
    balance = qfr_sheet(workbook, table, 1)
    title = " ".join(str(income[1][0]).split())
    scope = re.search(r"For Corporations in (.*?), ", title + ", ").group(1)
    quarters = qfr_quarters(income)
    operating_start = qfr_index(income, lambda label: label == "OPERATING RATIOS")
    equity_index = qfr_index(income, lambda label: label.startswith("Annual rate of profit on stockholders' equity"))
    assets_index = qfr_index(income, lambda label: label.startswith("Annual rate of profit on total assets"))
    ratio_start = qfr_index(balance, lambda label: label == "SELECTED BALANCE SHEET RATIOS")
    rows = {
        "return_on_equity_before_tax_percent": income[equity_index + 1],
        "return_on_equity_after_tax_percent": income[equity_index + 2],
        "return_on_assets_before_tax_percent": income[assets_index + 1],
        "return_on_assets_after_tax_percent": income[assets_index + 2],
        **{name: qfr_find(income, label, operating_start) for label, name in QFR_INCOME_RATIOS.items()},
    }
    if ratio_start is not None:
        rows.update({name: qfr_find(balance, label, ratio_start) for label, name in QFR_BALANCE_RATIOS.items()})
    rows = {name: row for name, row in rows.items() if row is not None}
    operating = qfr_find(income, "Income (loss) from operations")
    interest = qfr_find(income, "Interest expense")
    liabilities = qfr_find(balance, "Total liabilities")
    equity = qfr_find(balance, "Stockholders' equity")
    blocks = []
    for start in (1, 6):
        header = income[3][start] if len(income[3]) > start else None
        if not header:
            continue
        record: Record = {"table": f"Table {table}.0 and {table}.1", "naics_scope": scope, "column_heading": re.sub(r"\s+\d$", "", " ".join(str(header).split()))}
        for name, row in rows.items():
            for i, quarter in enumerate(quarters):
                record[f"{name}_{quarter}"] = row[start + i]
        for i, quarter in enumerate(quarters):
            record[f"total_liabilities_to_equity_{quarter}"] = per_unit(liabilities[start + i], equity[start + i], digits=2)
            record[f"interest_coverage_{quarter}"] = per_unit(operating[start + i], interest[start + i], digits=2)
        record["_sample"] = {name: dict(zip(quarters, rows[name][start:start + 5])) for name in ("return_on_equity_after_tax_percent", "current_ratio") if name in rows}
        blocks.append(record)
    return blocks


def qfr_collect(tables: Iterable[int], keep: Callable[[str], bool]) -> dict[str, Record]:
    workbook = load_workbook(io.BytesIO(get(QFR_URL)), read_only=True, data_only=True)
    rows: dict[str, Record] = {}
    for table in tables:
        for block in qfr_blocks(workbook, table):
            key = re.sub(r"\s+\d(\s|$)", r"\1", block["column_heading"]).strip()
            if keep(key) and key not in rows:
                rows[key] = block
    return rows


def qfr_visible(samples: Mapping[str, Record], name: str, preferred: str) -> tuple[str, str, float]:
    """Row, quarter and figure of ``name`` that the sheet XML stores in its shortest form, so the verifier finds it as written.

    The preferred row is tried first, latest quarter first.
    """
    text = resource_text(QFR_URL)
    for key in [preferred, *(k for k in samples if k != preferred)]:
        for quarter, value in reversed(list(samples[key].get(name, {}).items())):
            if isinstance(value, (int, float)) and f"<v>{value}</v>" in text:
                return key, quarter, value
    raise ValueError(f"no {name} figure is stored in its shortest form")


def qfr_entry(rows: dict[str, Record], entry_id: str, title: str, coverage: str, sample_key: str, tags: list[str]) -> Record:
    roe = f"return_on_equity_after_tax_percent_{QFR_QUARTER}"
    current = f"current_ratio_{QFR_QUARTER}"
    leverage = f"total_liabilities_to_equity_{QFR_QUARTER}"
    samples = {k: v.pop("_sample") for k, v in rows.items()}
    sample = rows[sample_key]
    highest = max(rows, key=lambda k: rows[k][roe] if rows[k][roe] is not None else float("-inf"))
    entry = base_entry(entry_id, title, "rule", ("2026-04-01", "2026-06-30"), ["quarterly-financial-report", "leverage", "return-on-equity", "current-ratio", "interest-coverage", "balance-sheet", *tags], ["lbo-modelling", "private-credit-demo", "credit-risk", "financial-reporting"])
    entry["spec"] = {
        "implementation": "almanac.rules.lookup_table",
        "parameters": {"release": "Quarterly Financial Report, second quarter 2026", "coverage": coverage, "rows": rows},
        "vectors": [
            {"input": {"key": sample_key, "column": roe}, "expected": sample[roe], "origin": "source"},
            {"input": {"key": sample_key, "column": current}, "expected": sample[current], "origin": "source"},
            {"input": {"key": highest, "column": roe}, "expected": rows[highest][roe], "origin": "source", "note": "highest after-tax return on equity in the latest quarter"},
            {"input": {"key": sample_key, "column": leverage}, "expected": sample[leverage], "origin": "derived"},
            {"input": sample_key, "expected": True, "origin": "source"},
        ],
    }
    roe_key, roe_quarter, roe_value = qfr_visible(samples, "return_on_equity_after_tax_percent", sample_key)
    current_key, current_quarter, current_value = qfr_visible(samples, "current_ratio", sample_key)
    entry["evidence"] = [
        census_evidence(QFR_URL, QFR_TITLE, f"{rows[roe_key]['table']}, column '{rows[roe_key]['column_heading']}', annual rate of profit on stockholders' equity after income taxes, {roe_quarter}", roe_value, "percent", "Annual rate of profit on stockholders' equity at end of period:"),
        census_evidence(QFR_URL, QFR_TITLE, f"{rows[current_key]['table']}, column '{rows[current_key]['column_heading']}', total current assets to total current liabilities, {current_quarter}", current_value, "ratio", "Total current assets to total current liabilities"),
        census_evidence(QFR_URL, QFR_TITLE, "finHead!A1", "FINANCIAL DATA TABLES", "text", "This workbook consist of 170 financial tables - 85 income and 85 balance sheets.", role="supporting"),
    ]
    entry["assumed"] = QFR_ASSUMED
    entry["tests"] = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
        {"statistic": f'value["{sample_key}",{roe}]', "expected": sample[roe], "tolerance": 0},
        {"statistic": f"max[{roe}]", "expected": rows[highest][roe], "tolerance": 0},
    ]
    entry["notes"] = (
        "Return and balance-sheet ratios for the five quarters 2Q 2025 to 2Q 2026 from the Census Bureau Quarterly "
        f"Financial Report, second quarter 2026. Coverage: {coverage}. Published ratios: annual rate of profit on "
        "stockholders' equity and on total assets, before and after income taxes (percent); current ratio, cash and "
        "securities to current liabilities, and stockholders' equity to total debt (times); short-term debt, long-term "
        "debt, total liabilities and stockholders' equity as percent of total assets. Derived: total liabilities to equity "
        "and interest coverage (income from operations over interest expense). After-tax margins on sales are in the "
        "existing QFR margin entries. The pinned quarterly workbook under /econ/qfr/xls/ does not change after release, "
        "but later releases revise these quarters. " + LICENSE_NOTE
    )
    return entry


# ----------------------------------------------------------------------------------------------


def main() -> int:
    for url in (SUSB_DETAILED_URL, SUSB_LARGE_EMPLOYMENT_URL, SUSB_RECEIPTS_URL, SUSB_LARGE_RECEIPTS_URL, SUSB_LFO_URL):
        get(url)
    lfo_rows = susb_lfo()
    finish(susb_national_by_employment_size())
    finish(susb_employment_size_by_sector(lfo_rows))
    finish(susb_receipts_size_by_sector())
    finish(susb_legal_form_by_sector(lfo_rows))
    finish(susb_employment_size_by_legal_form(lfo_rows))
    finish(susb_employment_size_by_state(lfo_rows))
    finish(susb_industry_totals())

    labels = sector_labels(lfo_rows)
    finish(bds_national_series())
    finish(bds_marginal(
        "fa", "fage", "us-bds-firms-by-firm-age-2023",
        "US employer firms by firm age (0 to 26+ years), with employment, entry, exit and job flow rates (BDS 2023)",
        "firm_age", ["firm-age", "firm-vintage", "start-ups"],
        "US employer firms in 2023 by firm age in years (0, 1, 2, 3, 4, 5, 6 to 10, 11 to 15, 16 to 20, 21 to 25, 26+ and "
        "the source's Left Censored class of firms whose age the data cannot establish), with the share of firms, "
        "establishments, employment, establishment entry and exit rates, job creation, destruction, net and reallocation "
        "rates and firm deaths. Age 0 firms are start-ups; the source publishes their entry and job creation rates as 200.",
    ))
    finish(bds_marginal(
        "fz", "fsize", "us-bds-firms-by-firm-size-2023",
        "US employer firms by firm employment size (1-4 to 10,000+), with employment, entry, exit and job flow rates (BDS 2023)",
        "firm_size", ["firm-size", "employment-size"],
        "US employer firms in 2023 by firm employment size (1 to 4, 5 to 9, 10 to 19, 20 to 99, 100 to 499, 500 to 999, "
        "1000 to 2499, 2500 to 4999, 5000 to 9999, 10000+), with the share of firms, establishments, employment, "
        "establishment entry and exit rates, job creation, destruction, net and reallocation rates and firm deaths.",
    ))
    finish(bds_conditional(
        "fa_fz", "fsize", "fage", "us-bds-firm-age-by-firm-size-2023",
        "US employer firms by firm age given firm employment size, with employment and job flow rates (BDS 2023)",
        "firm_age", "firm_size", ["firm-age", "firm-size", "firm-vintage"], ["20 to 99", "100 to 499", "10000+"],
        "For each firm employment size class, the share of US employer firms in 2023 by firm age (0 to 26+ years and Left "
        "Censored), with establishments, employment, entry, exit and job flow rates and firm deaths. Draw a size first, "
        "then a founding vintage from this slice, to give synthetic portfolio companies realistic ages.",
    ))
    finish(bds_conditional(
        "sec_fa", "sector", "fage", "us-bds-firm-age-by-sector-2023",
        "US employer firms by firm age given NAICS sector, with employment and job flow rates (BDS 2023)",
        "firm_age", "naics_sector", ["firm-age", "firm-vintage", "by-sector"], ["54", "31-33", "72"],
        "For each NAICS sector (keyed by code, with the title in 'label'), the share of US employer firms in 2023 by firm age "
        "(0 to 26+ years and Left Censored), with establishments, employment, entry, exit and job flow rates and firm deaths.",
        labels,
    ))
    finish(bds_conditional(
        "sec_fz", "sector", "fsize", "us-bds-firm-size-by-sector-2023",
        "US employer firms by firm employment size given NAICS sector, with employment and job flow rates (BDS 2023)",
        "firm_size", "naics_sector", ["firm-size", "employment-size", "by-sector"], ["54", "31-33", "23"],
        "For each NAICS sector (keyed by code, with the title in 'label'), the share of US employer firms in 2023 by firm "
        "employment size (1 to 4 to 10000+), with establishments, employment, entry, exit and job flow rates and firm deaths.",
        labels,
    ))
    finish(bds_sector_rates(labels))

    names = cbp_state_names(lfo_rows)
    get(CBP_US_URL)
    get(CBP_STATE_URL)
    finish(cbp_size_by_sector(labels))
    finish(cbp_size_by_state(names))
    finish(cbp_sector_by_state(names))
    finish(cbp_size_by_state_and_sector(names))

    get(BFS_URL)
    get(BFS_DOCUMENTATION_URL)
    finish(bfs_monthly_national())
    finish(bfs_by_state())
    finish(bfs_by_sector())

    for url in (ABS_APPLICATION_URL, ABS_SOURCES_URL, ABS_RECEIVED_URL):
        get(url)
    finish(abs_distribution(
        ABS_APPLICATION_URL, "us-abs-new-credit-application-by-owner-group-2024",
        "US employer firms that applied for new credit in 2024, given owner sex, race, ethnicity, minority and veteran status (ABS)",
        "new_credit_application", "Annual Business Survey 2025, Company Information Table 1: new credit application (CI-1)",
        "For each owner group (Total, sex, race, ethnicity, minority and veteran status), the shares of employer firms that "
        "applied for new credit in 2024, did not apply, or did not know, with the published percentages and standard errors.",
    ))
    finish(abs_distribution(
        ABS_RECEIVED_URL, "us-abs-new-credit-received-by-owner-group-2024",
        "US employer firms by share of requested new credit received in 2024, given owner sex, race, ethnicity, minority and veteran status (ABS)",
        "new_credit_received", "Annual Business Survey 2025, Company Information Table 3: amount of requested new credit received (CI-3)",
        "For each owner group, the shares of employer firms that received none, some or all of the new credit they "
        "requested in 2024, or did not know, with the published percentages and standard errors. Answer labels keep the "
        "source's spelling.",
    ))
    finish(abs_lending_sources())

    get(QFR_URL)
    manufacturing = qfr_collect(range(1, 34), lambda k: k.endswith(" All Total Asset Sizes"))
    finish(qfr_entry(
        {k.removesuffix(" All Total Asset Sizes"): v for k, v in manufacturing.items()},
        "us-qfr-manufacturing-leverage-and-return-ratios-by-industry-2026q2",
        f"US manufacturing corporations: return on equity, leverage and interest coverage by NAICS industry, 2Q 2025-2Q 2026 ({len(manufacturing)} industries)",
        "manufacturing corporations of all asset sizes", "All Manufacturing", ["manufacturing", "by-industry"],
    ))
    sizes = qfr_collect([1, 2, 15, *range(34, 40), *range(70, 82)], lambda k: "Total Assets" in k or "All Total Asset Sizes" in k)
    finish(qfr_entry(
        sizes, "us-qfr-manufacturing-leverage-and-return-ratios-by-asset-size-2026q2",
        f"US manufacturing corporations: return on equity, leverage and interest coverage by asset size, 2Q 2025-2Q 2026 ({len(sizes)} cuts)",
        "manufacturing corporations by total-asset size class (under $10 million to $5 billion and over), for all, durable and nondurable manufacturing",
        "All Manufacturing Total Assets $25 Million to less than $50 Million", ["manufacturing", "by-asset-size", "lower-middle-market"],
    ))
    nonmanufacturing = qfr_collect(range(82, 92), lambda k: k.endswith(" Total Assets $50 Million and Over"))
    finish(qfr_entry(
        {k.removesuffix(" Total Assets $50 Million and Over"): v for k, v in nonmanufacturing.items()},
        "us-qfr-nonmanufacturing-leverage-and-return-ratios-by-industry-2026q2",
        "US nonmanufacturing corporations with $50M+ assets: return on equity, leverage and interest coverage by industry, 2Q 2025-2Q 2026",
        "mining, wholesale trade, retail trade, information and professional and technical services corporations with total assets of $50 million and over",
        "All Retail Trade", ["retail", "wholesale", "information", "by-industry"],
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

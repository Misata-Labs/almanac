"""Regenerate the deal, distress and exit entries behind synthetic deal pipelines and credit books.

* Federal Trade Commission notices in the Federal Register (govinfo bulk XML): the 2026
  Hart-Scott-Rodino thresholds and filing-fee tiers, and the Clayton Act section 8 thresholds.
* Administrative Office of the US Courts: bankruptcy filings by chapter, nature of debt and
  district (Table F-2), and the quarterly business filings of the three-month F-2 tables.
* The Insolvency Service: company insolvencies by type and month, and the business insolvency
  demography tables by industry, company age, employment size and turnover.
* Office for National Statistics: cross-border and domestic mergers and acquisitions by quarter.
* Companies House: annual register movements, companies by SIC section and by age.
* Eurostat: the quarterly registration and bankruptcy index (sts_rb_q) and high-growth
  enterprises (bd_hg).
* OECD: FDI positions by partner economy and by industry, and the FDI Regulatory
  Restrictiveness Index.

Every resource is fetched twice and must hash alike. Every evidence snippet and value is checked
against the fetched text before an entry is written. Run from the repository root:

    uv run python tools/build_dealflow.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO_ROOT, evidence, fetch, sha, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

MAX_SNIPPET_WORDS = 24
OGL = "OGL-UK-3.0"
CC_BY = "CC-BY-4.0"
UNSTATED = "unstated"

US_LICENSE_NOTE = (
    "The publisher is a US federal body and the resource carries no licence statement, so the licence is recorded "
    "as unstated and the entry held at license-review."
)
OECD_LICENSE_NOTE = (
    "No licence statement was found in the OECD file or in a byte-stable OECD document, so the licence is recorded "
    "as unstated and the entry held at license-review."
)
EUROSTAT_LICENSE_NOTE = (
    "Eurostat's copyright notice states that its data are released under the Creative Commons Attribution 4.0 "
    "International licence; the notice page renders dynamically and is referenced rather than hashed."
)

DEAL_TAGS = ["deals"]
DISTRESS_TAGS = ["insolvency", "distress"]


# ----------------------------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------------------------


def collapse(text: str) -> str:
    return " ".join(text.split())


def scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class Source:
    """One fetched resource that cites only snippets and values its bytes contain."""

    publisher: str
    title: str
    url: str
    raw: bytes
    license_id: str

    @cached_property
    def text(self) -> str:
        return collapse(Resource(self.url, self.raw, "").text)

    def cite(self, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet exceeds {MAX_SNIPPET_WORDS} words: {snippet!r}")
        for needle, what in ((snippet, "snippet"), (scalar_text(value), "value")):
            if collapse(needle) not in self.text:
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        return evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, self.license_id, self.raw, role)


_CACHE: dict[str, bytes] = {}


def fetch_stable(url: str) -> bytes:
    """Fetch a URL twice and return its bytes only when both responses hash alike."""
    if url not in _CACHE:
        first, second = fetch(url), fetch(url)
        if sha(first) != sha(second):
            raise RuntimeError(f"unstable bytes at {url}")
        _CACHE[url] = first
    return _CACHE[url]


def source(publisher: str, title: str, url: str, license_id: str) -> Source:
    return Source(publisher, title, url, fetch_stable(url), license_id)


def csv_rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def raw_lines(raw: bytes) -> list[str]:
    return raw.decode("utf-8-sig").splitlines()


def workbook(raw: bytes):
    return load_workbook(io.BytesIO(raw), data_only=True, read_only=True)


def sheet_rows(raw: bytes, name: str) -> list[tuple]:
    return [row for row in workbook(raw)[name].iter_rows(values_only=True) if any(cell is not None for cell in row)]


def share(count: float, total: float) -> float:
    return round(count / total, 6)


def number_or_none(text: str) -> float | int | None:
    """A published cell as a number; suppressed or unavailable markers become None."""
    text = text.strip()
    if not text or text.startswith("["):
        return None
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def write_entry(entry: dict) -> None:
    if len(entry["title"]) > 140:
        raise ValueError(f"{entry['id']}: title longer than 140 characters")
    write(entry)


# ----------------------------------------------------------------------------------------------
# Hart-Scott-Rodino and Clayton Act section 8 (Federal Register, 16 January 2026)
# ----------------------------------------------------------------------------------------------

FTC = "Federal Trade Commission"
FR_BULK_URL = "https://www.govinfo.gov/bulkdata/FR/2026/01/FR-2026-01-16.xml"
FR_TITLE = "Federal Register, 16 January 2026, govinfo bulk XML (FR Doc. 2026-00877 and the following notice)"
USC_18A_URL = "https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap1-sec18a.htm"
HSR_SUBJECT = "Revised Jurisdictional Thresholds for Section 7A of the Clayton Act"
SECTION8_SUBJECT = "Revised Jurisdictional Thresholds for Section 8 of the Clayton Act"


def usd_amount(text: str) -> int:
    """Dollar amount written as '$26.8 million', '$1.174 billion' or '2,460,000'."""
    match = re.search(r"\$?([\d,]+(?:\.\d+)?)\s*(million|billion)?", text)
    if match is None:
        raise ValueError(f"no amount in {text!r}")
    number = Decimal(match.group(1).replace(",", ""))
    scale = {"million": Decimal(10) ** 6, "billion": Decimal(10) ** 9, None: Decimal(1)}[match.group(2)]
    return int(number * scale)


def notice(root: ET.Element, subject: str) -> ET.Element:
    for item in root.iter("NOTICE"):
        heading = item.find("PREAMB/SUBJECT")
        if heading is not None and collapse("".join(heading.itertext())) == subject:
            return item
    raise ValueError(f"notice {subject!r} not found")


def table_rows(table: ET.Element) -> list[list[str]]:
    return [[collapse("".join(cell.itertext())) for cell in row.findall("ENT")] for row in table.findall("ROW")]


def hsr_entries() -> None:
    fr = source(FTC, FR_TITLE, FR_BULK_URL, UNSTATED)
    usc = source("Office of the Law Revision Counsel, US House of Representatives (via govinfo)", "15 U.S.C. 18a, United States Code 2023 edition (HTML)", USC_18A_URL, UNSTATED)
    root = ET.fromstring(fr.raw)
    hsr = notice(root, HSR_SUBJECT)
    tables = hsr.findall(".//GPOTABLE")
    adjusted = {original: final.rstrip(".") for original, final in table_rows(tables[1])}
    fee_rows = table_rows(tables[2])
    effective = collapse("".join(hsr.find("PREAMB/DATES/P").itertext())).rstrip(".")
    effective_date = date(2026, 2, 17)
    if effective != "February 17, 2026":
        raise ValueError(f"unexpected effective date {effective!r}")

    fees = []
    for _, _, fee, band in fee_rows:
        amounts = [usd_amount(part) for part in re.findall(r"\$[\d.,]+ (?:million|billion)", band)]
        lower = 0 if band.startswith("less than") else amounts[0]
        upper = None if band.rstrip(".").endswith("or more") else amounts[-1]
        fees.append({"from_usd": lower, "below_usd": upper, "fee_usd": usd_amount(fee), "published_band": band.rstrip("."), "published_fee": fee})
    for lower_tier, upper_tier in zip(fees, fees[1:]):
        if lower_tier["below_usd"] != upper_tier["from_usd"]:
            raise ValueError("filing fee tiers are not contiguous")

    parameters = {
        "size_of_transaction": {
            "all_transactions_above_usd": usd_amount(adjusted["$200 million"]),
            "size_of_person_test_above_usd": usd_amount(adjusted["$50 million"]),
        },
        "size_of_person": {
            "smaller_person_usd": usd_amount(adjusted["$10 million"]),
            "larger_person_usd": usd_amount(adjusted["$100 million"]),
        },
        "filing_fees": fees,
        "adjusted_thresholds": {original: final for original, final in adjusted.items()},
    }
    top, upper_band, lower_band = parameters["size_of_transaction"]["all_transactions_above_usd"], fees[1]["from_usd"], fees[-1]["from_usd"]
    manufacturing_target = {"manufacturing": True, "annual_net_sales_usd": parameters["size_of_person"]["smaller_person_usd"], "total_assets_usd": 0}
    large_acquirer = {"annual_net_sales_usd": parameters["size_of_person"]["larger_person_usd"], "total_assets_usd": 0}
    small_acquirer = {"annual_net_sales_usd": parameters["size_of_person"]["larger_person_usd"] - 1, "total_assets_usd": 0}
    service_target_sales_only = {"manufacturing": False, "annual_net_sales_usd": parameters["size_of_person"]["smaller_person_usd"], "total_assets_usd": 0}
    mid = parameters["size_of_transaction"]["size_of_person_test_above_usd"] + 1_000_000
    vectors = [
        {"input": {"fee": 100_000_000}, "expected": fees[0]["fee_usd"], "origin": "source", "note": f"first tier, {fees[0]['published_band']}"},
        {"input": {"fee": upper_band}, "expected": fees[1]["fee_usd"], "origin": "source", "note": f"second tier starts at {fees[1]['published_band']}"},
        {"input": {"fee": fees[3]["from_usd"]}, "expected": fees[3]["fee_usd"], "origin": "source", "note": fees[3]["published_band"]},
        {"input": {"fee": lower_band}, "expected": fees[-1]["fee_usd"], "origin": "source", "note": f"top tier, {fees[-1]['published_band']}"},
        {"input": {"fee": lower_band - 1}, "expected": fees[-2]["fee_usd"], "origin": "derived", "note": "one dollar below the top tier"},
        {"input": {"band": top + 1}, "expected": "reportable", "origin": "derived", "note": "in excess of the 7A(a)(2)(A) threshold"},
        {"input": {"band": top}, "expected": "size-of-person test applies", "origin": "derived", "note": "exactly at the upper threshold is not in excess of it"},
        {"input": {"band": parameters["size_of_transaction"]["size_of_person_test_above_usd"]}, "expected": "not reportable", "origin": "derived"},
        {"input": {"reportable": mid, "acquiring": dict(large_acquirer), "acquired": dict(manufacturing_target)}, "expected": True, "origin": "derived", "note": "size-of-person test (I) met at both minimums"},
        {"input": {"reportable": mid, "acquiring": dict(small_acquirer), "acquired": dict(manufacturing_target)}, "expected": False, "origin": "derived", "note": "acquirer one dollar short of the larger amount"},
        {"input": {"reportable": mid, "acquiring": dict(large_acquirer), "acquired": dict(service_target_sales_only)}, "expected": False, "origin": "derived", "note": "test (II) counts only the total assets of a non-manufacturing acquired person"},
    ]
    entry = {
        "id": "us-hsr-premerger-thresholds-and-filing-fees-2026",
        "title": "Hart-Scott-Rodino premerger notification thresholds and filing-fee tiers in force from 17 February 2026",
        "kind": "rule",
        "domain": "deals",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": effective_date.isoformat(),
        "valid_to": None,
        "tags": DEAL_TAGS + ["m-and-a", "hart-scott-rodino", "antitrust", "filing-fee", "thresholds", "ftc"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "lbo-modelling", "compliance-demo"],
        "spec": {"implementation": "almanac.rules.us_hsr_premerger", "parameters": parameters, "vectors": vectors},
        "evidence": [
            fr.cite("NOTICE 'Revised Jurisdictional Thresholds for Section 7A of the Clayton Act', DATES", effective, "date", HSR_SUBJECT),
            fr.cite("Section 7A notice, adjusted threshold table, row '$200 million'", adjusted["$200 million"], "text", f"<ENT>{adjusted['$200 million']}.</ENT>"),
            fr.cite("Section 7A notice, adjusted threshold table, row '$50 million'", adjusted["$50 million"], "text", f"<ENT>{adjusted['$50 million']}.</ENT>"),
            fr.cite("Section 7A notice, adjusted threshold table, row '$10 million'", adjusted["$10 million"], "text", f"<ENT>{adjusted['$10 million']}.</ENT>"),
            fr.cite("Section 7A notice, adjusted threshold table, row '$100 million'", adjusted["$100 million"], "text", f"<ENT>{adjusted['$100 million']}.</ENT>"),
            fr.cite("Section 7A notice, filing fee table, row 1", fee_rows[0][2], "currency:USD", fee_rows[0][3]),
            fr.cite("Section 7A notice, filing fee table, row 2", fee_rows[1][2], "currency:USD", fee_rows[1][3]),
            fr.cite("Section 7A notice, filing fee table, row 4", fee_rows[3][2], "currency:USD", fee_rows[3][3]),
            fr.cite("Section 7A notice, filing fee table, row 6", fee_rows[5][2], "currency:USD", fee_rows[5][3]),
            usc.cite("15 U.S.C. 18a(a)(2)(B)(ii)(II)", "not engaged in manufacturing", "text", "any voting securities or assets of a person not engaged in manufacturing which has total assets of $10,000,000", role="supporting"),
        ],
        "assumed": [
            {"parameter": "size_of_transaction, size_of_person, filing_fees[*].from_usd and below_usd", "value": "published '$x million' or '$x billion' as whole dollars", "method": "derived", "rationale": "The notice states amounts in millions or billions of dollars; the rule restates them as whole dollars, and the published wording is kept beside each fee tier."},
            {"parameter": "meaning of the size-of-person tests", "value": "15 U.S.C. 18a(a)(2)(B)(ii)", "method": "derived", "rationale": "The notice lists adjusted amounts by subsection; which amount applies to which party and to which measure (net sales, total assets) is taken from the statute text cited as supporting evidence."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "tier_count", "expected": len(fees), "tolerance": 0},
            {"statistic": "threshold[all_transactions_above_usd]", "expected": parameters["size_of_transaction"]["all_transactions_above_usd"], "tolerance": 0},
            {"statistic": f"fee[{lower_band}]", "expected": fees[-1]["fee_usd"], "tolerance": 0},
        ],
        "notes": (
            "Thresholds of the Hart-Scott-Rodino Antitrust Improvements Act and the filing fee schedule as revised by the "
            "Federal Trade Commission's annual notice published in the Federal Register on 16 January 2026 (FR Doc. "
            "2026-00877), effective 17 February 2026, thirty days after publication. An acquisition is reportable when the "
            "acquiring person would hold voting securities and assets of the acquired person in excess of the upper "
            "size-of-transaction threshold, or in excess of the lower threshold when one of the three size-of-person tests "
            "of section 7A(a)(2)(B)(ii) is also met. The filing fee depends only on the size of transaction, in six tiers "
            "whose lower bounds are inclusive ('not less than'). Exemptions, valuation rules and aggregation under 16 CFR "
            "parts 801 to 803 are not modelled. The rule answers {'fee': size}, {'band': size} and {'reportable': size, "
            "'acquiring': {...}, 'acquired': {...}} with annual_net_sales_usd, total_assets_usd and, for the acquired person, "
            "manufacturing. Values are read from the govinfo bulk XML of that day's Federal Register. " + US_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    section8 = notice(root, SECTION8_SUBJECT)
    summary = collapse("".join(section8.find("PREAMB/SUM/P").itertext()))
    match = re.search(r"are \$([\d,]+) for Section 8\(a\)\(1\), and \$([\d,]+) for Section 8\(a\)\(2\)\(A\)", summary)
    if match is None:
        raise ValueError("section 8 thresholds not found")
    capital, sales = (int(group.replace(",", "")) for group in match.groups())
    rows = {
        "8(a)(1)": {"description": "Each competitor corporation has capital, surplus and undivided profits aggregating more than this amount", "threshold_usd": capital, "published": f"${match.group(1)}"},
        "8(a)(2)(A)": {"description": "No corporation is covered if the competitive sales of either corporation are less than this amount", "threshold_usd": sales, "published": f"${match.group(2)}"},
    }
    entry = {
        "id": "us-clayton-act-section-8-interlocking-directorate-thresholds-2026",
        "title": "Clayton Act section 8 interlocking directorate thresholds, 2026 (capital and competitive sales)",
        "kind": "rule",
        "domain": "deals",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2026-01-16",
        "valid_to": None,
        "tags": DEAL_TAGS + ["antitrust", "board-composition", "thresholds", "ftc", "reference-table"],
        "use_cases": ["pe-portfolio-demo", "deal-sourcing-demo", "compliance-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "Clayton Act subsection", "rows": rows},
            "vectors": [
                {"input": {"key": "8(a)(1)", "column": "threshold_usd"}, "expected": capital, "origin": "source"},
                {"input": {"key": "8(a)(2)(A)", "column": "threshold_usd"}, "expected": sales, "origin": "source"},
                {"input": "8(a)(2)(B)", "expected": False, "origin": "derived", "note": "the percentage tests of 8(a)(2)(B) and (C) are not adjusted and not tabulated"},
            ],
        },
        "evidence": [
            fr.cite("NOTICE 'Revised Jurisdictional Thresholds for Section 8 of the Clayton Act', SUMMARY", f"${match.group(1)}", "currency:USD", f"${match.group(1)} for Section 8(a)(1)"),
            fr.cite("NOTICE 'Revised Jurisdictional Thresholds for Section 8 of the Clayton Act', SUMMARY", f"${match.group(2)}", "currency:USD", f"${match.group(2)} for Section 8(a)(2)(A)"),
            fr.cite("NOTICE 'Revised Jurisdictional Thresholds for Section 8 of the Clayton Act', SUMMARY", "take effect immediately", "text", "The new thresholds, which take effect immediately"),
        ],
        "assumed": [{"parameter": "rows[*].threshold_usd", "value": "published dollar amounts without separators", "method": "derived", "rationale": "Restates the dollar amounts in the notice as integers; the published form is kept in 'published'."}],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "value[8(a)(1),threshold_usd]", "expected": capital, "tolerance": 0},
            {"statistic": "count", "expected": 2, "tolerance": 0},
        ],
        "notes": (
            "Section 8 of the Clayton Act bars, with exceptions, one person from serving as a director or officer of two "
            "competing corporations. Corporations are covered when each has capital, surplus and undivided profits above the "
            "8(a)(1) amount, and neither is covered when the competitive sales of either are below the 8(a)(2)(A) amount. The "
            "Federal Trade Commission revised both amounts for gross national product in the notice published on 16 January "
            "2026, effective immediately. Useful for checking board interlocks across a synthetic private-equity portfolio. "
            + US_LICENSE_NOTE
        ),
    }
    write_entry(entry)


# ----------------------------------------------------------------------------------------------
# US bankruptcy filings (Administrative Office of the US Courts, Table F-2)
# ----------------------------------------------------------------------------------------------

USCOURTS = "Administrative Office of the US Courts"
USCOURTS_FILES = "https://www.uscourts.gov/sites/default/files"
F2_12M_URL = f"{USCOURTS_FILES}/document/bf_f2_0930.2026.xlsx"
F2_QUARTERLY = [
    ("2024-Q4", f"{USCOURTS_FILES}/2025-01/bf_f2.3_1231.2024.xlsx", "December 31, 2024"),
    ("2025-Q1", f"{USCOURTS_FILES}/document/bf_f2.3_0331.2025.xlsx", "March 31, 2025"),
    ("2025-Q2", f"{USCOURTS_FILES}/document/bf_f2.3_0630.2025.xlsx", "June 30, 2025"),
    ("2025-Q3", f"{USCOURTS_FILES}/document/bf_f2.3_0930.2025.xlsx", "September 30, 2025"),
    ("2025-Q4", f"{USCOURTS_FILES}/document/bf_f2.3_1231.2025.xlsx", "December 31, 2025"),
    ("2026-Q1", f"{USCOURTS_FILES}/document/bf_f2.3_0331.2026.xlsx", "March 31, 2026"),
    ("2026-Q2", f"{USCOURTS_FILES}/document/bf_f2.3_0630.2026.xlsx", "June 30, 2026"),
    ("2026-Q3", f"{USCOURTS_FILES}/document/bf_f2.3_0930.2026.xlsx", "September 30, 2026"),
]
F2_COLUMNS = [
    "total", "total_chapter_7", "total_chapter_11", "total_chapter_13", "total_other_chapters",
    "business_total", "business_chapter_7", "business_chapter_11", "business_chapter_13", "business_other_chapters",
    "nonbusiness_total", "nonbusiness_chapter_7", "nonbusiness_chapter_11", "nonbusiness_chapter_13",
]


def f2_table(raw: bytes) -> dict[str, dict[str, int]]:
    """Rows of the business and nonbusiness F-2 sheet keyed by district (circuit subtotals dropped)."""
    rows = sheet_rows(raw, workbook(raw).sheetnames[0])
    table = {}
    for row in rows[1:]:
        label = row[0]
        if not isinstance(label, str) or not isinstance(row[1], (int, float, str)):
            continue
        if label.strip() != label or re.fullmatch(r"\s*\d+(st|nd|rd|th)", label):
            continue
        try:
            values = [0 if cell == "-" else int(cell) for cell in row[1:15]]
        except (TypeError, ValueError):
            continue
        table[label.replace("²", "").strip()] = dict(zip(F2_COLUMNS, values))
    return table


def us_bankruptcy_entries() -> None:
    f2 = source(USCOURTS, "Table F-2, bankruptcy cases commenced by chapter, 12 months ending 30 September 2026 (bf_f2_0930.2026.xlsx)", F2_12M_URL, UNSTATED)
    table = f2_table(f2.raw)
    total = table.pop("Total")
    districts = table
    for column in F2_COLUMNS:
        if sum(row[column] for row in districts.values()) != total[column]:
            raise ValueError(f"district rows do not sum to the total for {column}")

    business = {"chapter_7": total["business_chapter_7"], "chapter_11": total["business_chapter_11"], "chapter_13": total["business_chapter_13"], "other_chapters": total["business_other_chapters"]}
    nonbusiness = {"chapter_7": total["nonbusiness_chapter_7"], "chapter_11": total["nonbusiness_chapter_11"], "chapter_13": total["nonbusiness_chapter_13"]}
    if sum(business.values()) != total["business_total"] or sum(nonbusiness.values()) != total["nonbusiness_total"]:
        raise ValueError("chapter counts do not add up to the published totals")
    shares = {name: {key: share(value, sum(counts.values())) for key, value in counts.items()} for name, counts in (("business", business), ("nonbusiness", nonbusiness))}
    period = "During the 12-Month Period Ending September 30, 2026"
    entry = {
        "id": "us-bankruptcy-filings-by-chapter-and-nature-of-debt-12m-2026-09",
        "title": "US bankruptcy filings by chapter, business and nonbusiness, 12 months to 30 September 2026",
        "kind": "conditional",
        "domain": "company",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2025-10-01", "end": "2026-09-30"},
        "tags": DISTRESS_TAGS + ["bankruptcy", "chapter-11", "us-courts", "court-statistics"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "collections"],
        "spec": {
            "variable": "bankruptcy_chapter",
            "unit": "ratio",
            "given": "predominant_nature_of_debt",
            "distributions": {
                name: {"family": "categorical", "parameters": {"shares": shares[name], "counts": counts}}
                for name, counts in (("business", business), ("nonbusiness", nonbusiness))
            },
        },
        "evidence": [
            f2.cite("Table F-2, row Total, column Business Chapter 11", total["business_chapter_11"], "count", period),
            f2.cite("Table F-2, row Total, column Business All Chapters", total["business_total"], "count", f"<v>{total['business_total']}</v>"),
            f2.cite("Table F-2, row Total, column Nonbusiness Chapter 7", total["nonbusiness_chapter_7"], "count", f"<v>{total['nonbusiness_chapter_7']}</v>"),
            f2.cite("Table F-2, row Total, column Nonbusiness All Chapters", total["nonbusiness_total"], "count", "Predominant Nature of Debt"),
        ],
        "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "count / total of the nature-of-debt group", "method": "derived", "rationale": "The table publishes counts; shares divide each chapter by the business or nonbusiness total, rounded to six decimals."}],
        "tests": [
            {"statistic": "share[business,chapter_11]", "expected": shares["business"]["chapter_11"], "tolerance": 0.005},
            {"statistic": "share[business,chapter_7]", "expected": shares["business"]["chapter_7"], "tolerance": 0.005},
            {"statistic": "share[nonbusiness,chapter_13]", "expected": shares["nonbusiness"]["chapter_13"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[business]", "expected": 1, "tolerance": 0.0001},
            {"statistic": "sum_of_shares[nonbusiness]", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "Cases commenced in the US bankruptcy courts in the twelve months ending 30 September 2026, by chapter of the "
            "Bankruptcy Code and predominant nature of debt, from Table F-2 of the Administrative Office of the US Courts. "
            "'Other chapters' covers chapters 9, 12 and 15 and section 304 cases and is published for business filings only. "
            "The table's note defines the nature of debt as business when the debtor is a corporation or partnership or when "
            "debt related to the operation of a business predominates. Subchapter V cases are not tabulated separately in "
            "F-2. " + US_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    rows = {code: {key: value for key, value in row.items()} for code, row in districts.items()}
    biggest = max(rows, key=lambda code: rows[code]["business_chapter_11"])
    entry = {
        "id": "us-bankruptcy-filings-by-district-12m-2026-09",
        "title": "US bankruptcy filings by federal judicial district, chapter and nature of debt, 12 months to 30 September 2026",
        "kind": "rule",
        "domain": "company",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2025-10-01",
        "valid_to": "2026-09-30",
        "tags": DISTRESS_TAGS + ["bankruptcy", "chapter-11", "us-courts", "by-district", "reference-table"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "deal-sourcing-demo", "credit-risk", "address-generation"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "district code as printed in Table F-2 (state abbreviation, then N, S, E, W, M or C for divided states)", "columns": F2_COLUMNS, "rows": rows},
            "vectors": [
                {"input": {"key": biggest, "column": "business_chapter_11"}, "expected": rows[biggest]["business_chapter_11"], "origin": "source"},
                {"input": {"key": "DE", "column": "business_chapter_11"}, "expected": rows["DE"]["business_chapter_11"], "origin": "source"},
                {"input": {"key": "DE", "column": "total"}, "expected": rows["DE"]["total"], "origin": "source"},
                {"input": "ZZ", "expected": False, "origin": "derived", "note": "no such district"},
            ],
        },
        "evidence": [
            f2.cite(f"Table F-2, row {biggest}, column Business Chapter 11", rows[biggest]["business_chapter_11"], "count", f"<t>{biggest}</t>"),
            f2.cite("Table F-2, row DE, column Business Chapter 11", rows["DE"]["business_chapter_11"], "count", period),
            f2.cite("Table F-2, row DE, column Total All Chapters", rows["DE"]["total"], "count", f"<v>{rows['DE']['total']}</v>"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f'value["{biggest}",business_chapter_11]', "expected": rows[biggest]["business_chapter_11"], "tolerance": 0},
        ],
        "notes": (
            f"Bankruptcy cases commenced in each of the {len(rows)} federal judicial districts (including the territories) in the "
            "twelve months ending 30 September 2026, from Table F-2 of the Administrative Office of the US Courts, with the "
            "fourteen columns of the table: totals by chapter and the business and nonbusiness splits. Circuit subtotals are "
            "dropped; a dash in the source (no business filings in Guam and the Northern Mariana Islands) is read as zero; "
            "AR covers both Arkansas districts, as the source notes; the district rows sum to the published national total for every column. Business chapter 11 filings "
            "concentrate in a few venues, which matters when generating a plausible docket for distressed portfolio "
            "companies. " + US_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    series, cites = [], []
    for period_label, url, ending in F2_QUARTERLY:
        quarter = source(USCOURTS, f"Table F-2 three-month, business and nonbusiness cases commenced, quarter ending {ending}", url, UNSTATED)
        totals = f2_table(quarter.raw)["Total"]
        series.append({
            "period": period_label,
            "value": totals["business_chapter_11"],
            "business_total": totals["business_total"],
            "business_chapter_7": totals["business_chapter_7"],
            "business_chapter_13": totals["business_chapter_13"],
            "nonbusiness_total": totals["nonbusiness_total"],
            "all_filings": totals["total"],
        })
        cites.append(quarter.cite("Table F-2 three-month, row Total, column Business Chapter 11", totals["business_chapter_11"], "count", f"During the Three-Month Period Ending {ending}"))
    last, first = series[-1], series[0]
    entry = {
        "id": "us-business-bankruptcy-filings-quarterly-2024q4-2026q3",
        "title": "US business chapter 11 and other bankruptcy filings by quarter, 2024Q4 to 2026Q3",
        "kind": "temporal",
        "domain": "company",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2024-10-01", "end": "2026-09-30"},
        "tags": DISTRESS_TAGS + ["bankruptcy", "chapter-11", "us-courts", "quarterly-series"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "demand-forecasting"],
        "spec": {
            "variable": "business_chapter_11_filings",
            "unit": "count",
            "frequency": "quarterly",
            "columns": ["business_total", "business_chapter_7", "business_chapter_13", "nonbusiness_total", "all_filings"],
            "series": series,
        },
        "evidence": cites,
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": f"column[business_total,{last['period']}]", "expected": last["business_total"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "National totals of the three-month versions of Table F-2 for eight consecutive quarters, one workbook per "
            "quarter as first published (later revisions are not folded back). The value is business chapter 11 cases; "
            "the columns carry all business cases, business chapter 7 and 13, all nonbusiness cases and all cases. Quarters "
            "are calendar quarters (2024-Q4 is October to December 2024). " + US_LICENSE_NOTE
        ),
    }
    write_entry(entry)


# ----------------------------------------------------------------------------------------------
# UK company insolvencies (The Insolvency Service)
# ----------------------------------------------------------------------------------------------

INSOLVENCY = "The Insolvency Service"
INSOLVENCY_SERIES_URL = "https://assets.publishing.service.gov.uk/media/6af73003740e16c0699ca831/Long-Run_Series_in_CSV_Format_-_Company_Insolvency_Statistics_October_2026.csv"
INSOLVENCY_META_URL = "https://assets.publishing.service.gov.uk/media/6afb2af0e1a418027274e0b3/Metadata_for_Long-Run_Series_in_CSV_Format_-_Company_Insolvency_Statistics_October_2026.csv"
DEMOGRAPHY_URL = "https://assets.publishing.service.gov.uk/media/6a33c35f0bea238415c9a204/Full_Data_in_CSV_Format_-_Business_Insolvency_Demography_2015_to_2025.csv"
DEMOGRAPHY_META_URL = "https://assets.publishing.service.gov.uk/media/6a33fd0f0bea238415c9a276/Metadata_for_Full_Data_in_CSV_Format_-_Business_Insolvency_Demography_2015_to_2025.csv"
INSOLVENCY_TYPES = {
    "compliq_ew_nsa": "compulsory_liquidations",
    "cvl_ew_nsa": "creditors_voluntary_liquidations",
    "admin_ew_nsa": "administrations",
    "cva_ew_nsa": "company_voluntary_arrangements",
    "rec_ew_nsa": "administrative_receiverships",
    "total_ew_sa": "total_seasonally_adjusted",
    "tot_rate_ew": "rolling_12_month_rate_per_10000_companies",
}


def gb_insolvency_entries() -> None:
    series_source = source(INSOLVENCY, "Company Insolvency Statistics October 2026, long-run series (CSV)", INSOLVENCY_SERIES_URL, OGL)
    meta = source(INSOLVENCY, "Company Insolvency Statistics October 2026, metadata for the long-run series (CSV)", INSOLVENCY_META_URL, OGL)
    rows = csv_rows(series_source.raw)
    lines = {line.split(",", 1)[0]: line for line in raw_lines(series_source.raw)[1:]}
    selected = [row for row in rows if "2025-01" <= row["period"] <= "2026-10"]
    series = []
    for row in selected:
        point = {"period": row["period"], "value": int(row["total_ew_nsa"])}
        for field, column in INSOLVENCY_TYPES.items():
            value = number_or_none(row[field])
            if value is None:
                raise ValueError(f"{row['period']} {field} is not published")
            point[column] = value
        series.append(point)
    first, last = series[0], series[-1]
    year_2025 = [p for p in series if p["period"].startswith("2025")]
    cvl_share = share(sum(p["creditors_voluntary_liquidations"] for p in year_2025), sum(p["value"] for p in year_2025))

    def row_snippet(period: str, fields: int) -> str:
        return ",".join(lines[period].split(",")[:fields])

    entry = {
        "id": "gb-company-insolvencies-by-type-monthly-2025-2026",
        "title": "Company insolvencies in England and Wales by type, monthly January 2025 to October 2026, with the insolvency rate",
        "kind": "temporal",
        "domain": "company",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2026-10-31"},
        "tags": DISTRESS_TAGS + ["insolvency-service", "liquidation", "administration", "monthly-series"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "collections"],
        "spec": {
            "variable": "company_insolvencies_not_seasonally_adjusted",
            "unit": "count",
            "frequency": "monthly",
            "columns": list(INSOLVENCY_TYPES.values()),
            "series": series,
        },
        "evidence": [
            series_source.cite(f"row period={last['period']}, column total_ew_nsa", last["value"], "count", row_snippet(last["period"], 8)),
            series_source.cite(f"row period={first['period']}, column cvl_ew_nsa", first["creditors_voluntary_liquidations"], "count", row_snippet(first["period"], 11)),
            series_source.cite(f"row period={last['period']}, column tot_rate_ew", last["rolling_12_month_rate_per_10000_companies"], "decimal", row_snippet(last["period"], 16)),
            meta.cite("variable tot_rate_ew", "Total 12-month rolling insolvency rate per 10000 companies", "text", "tot_rate_ew,Total 12-month rolling insolvency rate per 10000 companies,England and Wales", role="supporting"),
            meta.cite("Licence", "Open Government Licence 3.0", "text", "Licence,Open Government Licence 3.0", role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": f"column[creditors_voluntary_liquidations,{first['period']}]", "expected": first["creditors_voluntary_liquidations"], "tolerance": 0},
            {"statistic": f"column[rolling_12_month_rate_per_10000_companies,{last['period']}]", "expected": last["rolling_12_month_rate_per_10000_companies"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Registered company insolvencies in England and Wales each month from January 2025 to October 2026, from the "
            "long-run CSV of the Insolvency Service's October 2026 release. The value is the total not seasonally adjusted; "
            "the columns split it into compulsory liquidations, creditors' voluntary liquidations (CVLs), administrations, "
            "company voluntary arrangements (CVAs) and administrative receiverships, and add the seasonally adjusted total and "
            "the 12-month rolling insolvency rate per 10,000 companies. CVLs were "
            f"{round(100 * cvl_share, 1)} per cent of 2025 insolvencies. The latest months are provisional and are revised in "
            "later releases. Scotland and Northern Ireland, published in the same file, are left out. The file states the "
            "Open Government Licence 3.0."
        ),
    }
    entry["assumed"].append({"parameter": "notes: CVL share of 2025", "value": cvl_share, "method": "derived", "rationale": "Sum of monthly CVLs over the sum of monthly totals for January to December 2025."})
    write_entry(entry)

    demography = source(INSOLVENCY, "Business Insolvency Demography 2015 to 2025, full data (CSV)", DEMOGRAPHY_URL, OGL)
    demography_meta = source(INSOLVENCY, "Business Insolvency Demography 2015 to 2025, metadata (CSV)", DEMOGRAPHY_META_URL, OGL)
    licence_cite = demography_meta.cite("Licence", "Open Government Licence 3.0", "text", "Open Government Licence 3.0", role="supporting")
    records = csv_rows(demography.raw)
    demography_lines = raw_lines(demography.raw)

    def table(demographic: str) -> tuple[dict[str, dict], list[str]]:
        out: dict[str, dict] = {}
        order: list[str] = []
        for record in records:
            if record["Demographic"] != demographic or record["Geography"] != "ew":
                continue
            kind = "count" if record["Type"] == "Volume" else "rate_per_10000"
            key = record["Variable"]
            if key not in out:
                out[key] = {}
                order.append(key)
            for part, label in (("total", "total"), ("ad", "administrations"), ("cl", "compulsory_liquidations"), ("cvl", "creditors_voluntary_liquidations"), ("other", "other")):
                out[key][f"{label}_{kind}"] = number_or_none(record[f"2025_{part}"])
        return out, order

    def line_tail(demographic: str, kind: str, variable: str) -> str:
        prefix = f"{demographic},{kind},ew,{variable},"
        line = next(line for line in demography_lines if line.startswith(prefix))
        return ",".join(line.split(",")[-5:])

    profiles = [
        ("Industry", "gb-company-insolvencies-by-industry-2025", "Company insolvencies in England and Wales by SIC 2007 section and type, 2025, with rates per 10,000 companies", "SIC 2007 section letter (Unknown where the company has no SIC code)", "I", "by-industry", ["sic-2007"]),
        ("Age", "gb-company-insolvencies-by-company-age-2025", "Company insolvencies in England and Wales by company age and type, 2025, with rates per 10,000 companies", "company age band at insolvency", "4 to 7 years", "by-company-age", ["firm-age"]),
        ("Employees", "gb-company-insolvencies-by-employee-size-2025", "Company insolvencies in England and Wales by employee size band and type, 2025, with rates per 10,000 companies", "employee size band", "20 to 49", "by-size-class", ["employment-size"]),
        ("Turnover", "gb-company-insolvencies-by-turnover-band-2025", "Company insolvencies in England and Wales by turnover band and type, 2025, with rates per 10,000 companies", "turnover band in pounds", "2000000 to 5000000", "by-turnover", ["turnover-band"]),
    ]
    for demographic, entry_id, title, key_label, sample, tag, extra_tags in profiles:
        rows_by_key, order = table(demographic)
        total = rows_by_key["Total"]
        highest = max((k for k in order if k not in ("Total", "Unknown") and rows_by_key[k]["total_rate_per_10000"] is not None), key=lambda k: rows_by_key[k]["total_rate_per_10000"])
        entry = {
            "id": entry_id,
            "title": title.replace("10,000", "10000"),
            "kind": "rule",
            "domain": "company",
            "region": "GB",
            "status": "verified",
            "tier": "A",
            "valid_from": "2025-01-01",
            "valid_to": "2025-12-31",
            "tags": DISTRESS_TAGS + ["insolvency-service", tag, "reference-table"] + extra_tags,
            "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "synthetic-companies"],
            "spec": {
                "implementation": "almanac.rules.lookup_table",
                "parameters": {"key": key_label, "geography": "England and Wales", "year": 2025, "rows": rows_by_key},
                "vectors": [
                    {"input": {"key": sample, "column": "total_count"}, "expected": rows_by_key[sample]["total_count"], "origin": "source"},
                    {"input": {"key": sample, "column": "total_rate_per_10000"}, "expected": rows_by_key[sample]["total_rate_per_10000"], "origin": "source"},
                    {"input": {"key": "Total", "column": "total_count"}, "expected": total["total_count"], "origin": "source"},
                    {"input": "Not a band", "expected": False, "origin": "derived"},
                ],
            },
            "evidence": [
                demography.cite(f"row {demographic},Volume,ew,{sample}, columns 2025_total to 2025_other", rows_by_key[sample]["total_count"], "count", line_tail(demographic, "Volume", sample)),
                demography.cite(f"row {demographic},Rate per 10000,ew,{sample}, columns 2025_total to 2025_other", rows_by_key[sample]["total_rate_per_10000"], "decimal", line_tail(demographic, "Rate per 10000", sample)),
                demography.cite(f"row {demographic},Volume,ew,Total, column 2025_total", total["total_count"], "count", line_tail(demographic, "Volume", "Total")),
            ]
            + ([demography.cite(f"row {demographic},Rate per 10000,ew,{highest}, column 2025_total", rows_by_key[highest]["total_rate_per_10000"], "decimal", line_tail(demographic, "Rate per 10000", highest))] if highest != sample else [])
            + [licence_cite],
            "assumed": [],
            "tests": [
                {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
                {"statistic": f'value["{sample}",total_rate_per_10000]', "expected": rows_by_key[sample]["total_rate_per_10000"], "tolerance": 0},
                {"statistic": "count", "expected": len(rows_by_key), "tolerance": 0},
            ],
            "notes": (
                f"Company insolvencies registered in England and Wales in 2025 by {key_label}, from the Insolvency Service's "
                "Business Insolvency Demography 2015 to 2025 release. Each row gives counts and rates per 10,000 companies for all insolvencies and for "
                "administrations, compulsory liquidations, creditors' voluntary liquidations and other procedures. Published counts "
                "are multiples of five; null marks a cell the publisher suppressed ([c]) for disclosure control. "
                f"The highest overall rate among known bands is '{highest}'. Rates are the published ones, not recomputed. "
                "The file is published under the Open Government Licence 3.0."
            ),
        }
        write_entry(entry)


# ----------------------------------------------------------------------------------------------
# UK mergers and acquisitions (ONS)
# ----------------------------------------------------------------------------------------------

ONS = "Office for National Statistics"
MA_URL = "https://www.ons.gov.uk/file?uri=/businessindustryandtrade/changestobusiness/mergersandacquisitions/datasets/mergersandacquisitionsinvolvingukcompanies/current/newversionq22026rftmatablewithr1andcdid.xlsx"
MA_TITLE = "Mergers and acquisitions involving UK companies, Quarter 2 2026 dataset (XLSX)"
ONS_LICENSE_URL = "https://api.beta.ons.gov.uk/v1/datasets/cpih01"
MA_PERIODS = ["2024 Q3", "2024 Q4", "2025 Q1", "2025 Q2", "2025 Q3", "2025 Q4", "2026 Q1", "2026 Q2"]


def ons_number(cell: Any) -> int:
    """A Table 1 or 8 cell; early-revision cells read like '4,141 [er]'."""
    if isinstance(cell, (int, float)):
        return int(cell)
    return int(str(cell).replace("[er]", "").replace(",", "").strip())


def quarter_period(label: str) -> str:
    year, quarter = label.split(" Q")
    return f"{year}-Q{quarter}"


def gb_ma_entries() -> None:
    ma = source(ONS, MA_TITLE, MA_URL, OGL)
    licence = source(ONS, "ONS dataset metadata cpih01 (licence statement for ONS datasets)", ONS_LICENSE_URL, OGL)
    licence_cite = licence.cite("license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', role="supporting")

    def quarters(sheet: str) -> dict[str, tuple]:
        return {row[0]: row for row in sheet_rows(ma.raw, sheet) if isinstance(row[0], str) and row[0] in MA_PERIODS}

    def cell_text(cell: Any) -> str:
        return f"<v>{cell}</v>" if isinstance(cell, (int, float)) else str(cell)

    table1 = quarters("Table 1")
    names = ["outward_acquisitions_value_gbp_millions", "outward_disposals_number", "outward_disposals_value_gbp_millions", "inward_acquisitions_number", "inward_acquisitions_value_gbp_millions", "inward_disposals_number", "inward_disposals_value_gbp_millions"]
    series = []
    for label in MA_PERIODS:
        row = table1[label]
        point = {"period": quarter_period(label), "value": ons_number(row[1])}
        point.update({name: ons_number(cell) for name, cell in zip(names, row[2:9])})
        series.append(point)
    last_label, first_label = MA_PERIODS[-1], MA_PERIODS[0]
    last, first = series[-1], series[0]
    entry = {
        "id": "gb-cross-border-mergers-acquisitions-quarterly-2024q3-2026q2",
        "title": "Cross-border mergers, acquisitions and disposals involving UK companies, number and value by quarter, 2024Q3 to 2026Q2",
        "kind": "temporal",
        "domain": "deals",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2024-07-01", "end": "2026-06-30"},
        "tags": DEAL_TAGS + ["m-and-a", "cross-border", "ons", "quarterly-series"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "market-sizing"],
        "spec": {"variable": "outward_acquisitions_number", "unit": "count", "frequency": "quarterly", "columns": names, "series": series},
        "evidence": [
            ma.cite(f"Table 1, row '{last_label}', number of acquisitions abroad by UK companies", last["value"], "count", "Summary of Cross-Border Mergers, Acquisitions and Disposals"),
            ma.cite(f"Table 1, row '{last_label}', value of transactions in the UK by foreign companies (GBP million)", last["inward_acquisitions_value_gbp_millions"], "currency:GBP", cell_text(table1[last_label][6])),
            ma.cite(f"Table 1, row '{first_label}', number of acquisitions in the UK by foreign companies", first["inward_acquisitions_number"], "count", cell_text(table1[first_label][5])),
            ma.cite("Table 1, units line", "All figures in this table are in £ million", "text", "All figures in this table are in £ million", role="supporting"),
            licence_cite,
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"column[inward_acquisitions_value_gbp_millions,{last['period']}]", "expected": last["inward_acquisitions_value_gbp_millions"], "tolerance": 0},
            {"statistic": f"column[inward_acquisitions_number,{first['period']}]", "expected": first["inward_acquisitions_number"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Cross-border mergers, acquisitions and disposals worth £1 million or more involving UK companies, from "
            "Table 1 of the ONS Mergers and Acquisitions dataset published with the Q2 2026 release. Outward deals are "
            "acquisitions or disposals abroad by UK companies; inward deals are acquisitions or disposals in the UK by foreign "
            "companies. Values are in millions of pounds. 2026 Q1 is marked [er] (earliest revision) in the source and its "
            "figures are read without that marker; quarters are revised as late survey returns arrive. The value of a quarter "
            "can swing with a single large deal. Released under the Open "
            "Government Licence v3.0."
        ),
    }
    write_entry(entry)

    table8 = quarters("Table 8")
    series = [{"period": quarter_period(label), "value": ons_number(table8[label][1]), "total_value_gbp_millions": ons_number(table8[label][2])} for label in MA_PERIODS]
    last, first = series[-1], series[0]
    entry = {
        "id": "gb-domestic-mergers-acquisitions-quarterly-2024q3-2026q2",
        "title": "Domestic mergers and acquisitions of UK companies by other UK companies, number and value by quarter, 2024Q3 to 2026Q2",
        "kind": "temporal",
        "domain": "deals",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2024-07-01", "end": "2026-06-30"},
        "tags": DEAL_TAGS + ["m-and-a", "domestic", "ons", "quarterly-series"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "market-sizing"],
        "spec": {"variable": "domestic_mergers_and_acquisitions_number", "unit": "count", "frequency": "quarterly", "columns": ["total_value_gbp_millions"], "series": series},
        "evidence": [
            ma.cite(f"Table 8, row '{last_label}', total number of all mergers and acquisitions", last["value"], "count", "Summary of Mergers and Acquisitions in the UK by other UK Companies"),
            ma.cite(f"Table 8, row '{last_label}', total value (GBP million)", last["total_value_gbp_millions"], "currency:GBP", cell_text(table8[last_label][2])),
            ma.cite(f"Table 8, row '{first_label}', total number", first["value"], "count", cell_text(table8[first_label][1])),
            licence_cite,
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"column[total_value_gbp_millions,{last['period']}]", "expected": last["total_value_gbp_millions"], "tolerance": 0},
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Acquisitions of UK companies by other UK companies worth £1 million or more, from Table 8 of the ONS "
            "Mergers and Acquisitions dataset published with the Q2 2026 release; values in millions of pounds. The split "
            "between independent companies and sales of subsidiaries is suppressed for 2026 Q2 and is left out. 2026 Q1 "
            "carries the source's [er] marker. Released under the Open Government Licence v3.0."
        ),
    }
    write_entry(entry)


# ----------------------------------------------------------------------------------------------
# UK companies register (Companies House)
# ----------------------------------------------------------------------------------------------

COMPANIES_HOUSE = "Companies House"
CRA_URL = "https://assets.publishing.service.gov.uk/media/6a3d1a97eaee00074150f4df/Companies_register_activities_April_2025_to_March_2026.xlsx"
CRA_TITLE = "Companies register activities, April 2025 to March 2026 (XLSX)"


def gb_register_entries() -> None:
    cra = source(COMPANIES_HOUSE, CRA_TITLE, CRA_URL, OGL)

    a1 = sheet_rows(cra.raw, "Table A1")
    years = [cell for cell in a1[2][1:] if cell]
    uk_start = next(i for i, row in enumerate(a1) if row[0] == "United Kingdom")
    labels = {
        "On register at start of period": "register_at_start",
        "Incorporations": "incorporations",
        "Dissolved": "dissolved",
        "Restored to the register": "restored",
        "On register at end of period": "register_at_end",
        "Of which: in liquidation": "in_liquidation_at_end",
        "Of which: in course of dissolution": "in_course_of_dissolution_at_end",
        "Effective number on register at end of period": "effective_register_at_end",
    }
    block: dict[str, list] = {}
    for row in a1[uk_start + 1:]:
        if row[0] in ("England and Wales",):
            break
        if row[0] in labels and labels[row[0]] not in block:
            block[labels[row[0]]] = list(row[1:1 + len(years)])
    series = []
    for index, year in enumerate(years):
        point = {"period": year, "value": int(block["incorporations"][index])}
        for column in ("dissolved", "restored", "register_at_start", "register_at_end", "in_liquidation_at_end", "in_course_of_dissolution_at_end", "effective_register_at_end"):
            point[column] = int(block[column][index])
        point["dissolution_rate_percent"] = round(100 * point["dissolved"] / point["register_at_start"], 2)
        series.append(point)
    last, first = series[-1], series[0]
    columns = [key for key in series[0] if key not in ("period", "value")]
    entry = {
        "id": "gb-companies-register-movements-annual-2016-17-to-2025-26",
        "title": "UK companies register by financial year: incorporations, dissolutions, restorations and register size, 2016-17 to 2025-26",
        "kind": "temporal",
        "domain": "company",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2016-04-01", "end": "2026-03-31"},
        "tags": ["companies-house", "incorporations", "dissolutions", "company-register", "annual-series"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "synthetic-companies", "kyb-onboarding", "market-sizing"],
        "spec": {"variable": "incorporations", "unit": "count", "frequency": "annual", "columns": columns, "series": series},
        "evidence": [
            cra.cite(f"Table A1, United Kingdom, row Incorporations, column {last['period']}", last["value"], "count", "Summary of changes in the number of companies on the register, 2016-17 to 2025-26"),
            cra.cite(f"Table A1, United Kingdom, row Dissolved, column {last['period']}", last["dissolved"], "count", f"<v>{last['dissolved']}</v>"),
            cra.cite(f"Table A1, United Kingdom, row Incorporations, column {first['period']}", first["value"], "count", f"<v>{first['value']}</v>"),
            cra.cite(f"Table A1, United Kingdom, row Effective number on register at end of period, column {last['period']}", last["effective_register_at_end"], "count", "Effective number on register at end of period"),
        ],
        "assumed": [{"parameter": "series[*].dissolution_rate_percent", "value": "100 * dissolved / register_at_start", "method": "derived", "rationale": "Companies dissolved in the year as a percentage of the register at the start of the year, rounded to two decimals."}],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"column[dissolved,{last['period']}]", "expected": last["dissolved"], "tolerance": 0},
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Movements on the UK register of companies formed under the Companies Act 2006 for each financial year April to "
            "March, from Table A1 (United Kingdom block) of Companies House's Companies register activities release for April "
            "2025 to March 2026. The effective register excludes companies in liquidation or in the course of dissolution. "
            "Limited liability partnerships and other corporate bodies are not included. Published on GOV.UK under the Open "
            "Government Licence v3.0."
        ),
    }
    write_entry(entry)

    c2 = sheet_rows(cra.raw, "Table C2")
    header = list(c2[2])
    column = header.index("2025-26")
    counts, names = {}, {}
    for row in c2[3:]:
        if isinstance(row[0], str) and re.fullmatch(r"[A-UX]", row[0]):
            counts[row[0]] = int(row[column])
            names[row[0]] = row[1].strip()
    total_row = next(row for row in c2 if row[0] == "Total")
    if sum(counts.values()) != total_row[column]:
        raise ValueError("SIC section counts do not sum to the published total")
    total = sum(counts.values())
    shares = {code: share(value, total) for code, value in counts.items()}
    top = max(counts, key=counts.get)
    entry = {
        "id": "gb-corporate-bodies-by-sic-section-2025-26",
        "title": "SIC 2007 sections declared by UK corporate bodies on the Companies House register, 2025-26",
        "kind": "marginal",
        "domain": "company",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-04-01", "end": "2026-03-31"},
        "tags": ["companies-house", "sic-2007", "by-industry", "company-register"],
        "use_cases": ["synthetic-companies", "kyb-onboarding", "deal-sourcing-demo", "pe-portfolio-demo", "company-generation"],
        "spec": {
            "variable": "sic_2007_section",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "names": names}},
        },
        "evidence": [
            cra.cite(f"Table C2, row {top}, column 2025-26", counts[top], "count", names[top]),
            cra.cite("Table C2, row Total, column 2025-26", total, "count", f"<v>{total}</v>"),
            cra.cite("Table C2, note 3", "Up to four Standard Industrial Classification (SIC) codes", "text", "Up to four Standard Industrial Classification (SIC) codes can be submitted and captured per corporate body record", role="supporting"),
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "count / sum of section counts", "method": "derived", "rationale": "Companies House publishes counts of SIC codes by section; shares divide each by the published total."}],
        "tests": [
            {"statistic": f"share[{top}]", "expected": shares[top], "tolerance": 0.005},
            {"statistic": "share[C]", "expected": shares["C"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "SIC 2007 sections recorded on the UK register in 2025-26, from Table C2 of Companies House's Companies register "
            "activities release (all corporate body types). A corporate body may record up to four SIC codes, so the counts "
            "are codes, not companies; the shares are therefore the industry mix of declared "
            "activities, which is what a generator needs to assign a section to a synthetic UK company. Section X is "
            "'Code not elsewhere classified'. Published on GOV.UK under the Open "
            "Government Licence v3.0."
        ),
    }
    write_entry(entry)

    a5 = sheet_rows(cra.raw, "Table A5")
    bands = {}
    published = {}
    for row in a5:
        label = row[0]
        if isinstance(label, str) and label.startswith("Percentage of companies aged"):
            band = label.replace("Percentage of companies aged ", "").strip()
            published[band] = row[5]
    total_percent = sum(published.values())
    bands = {band: round(value / total_percent, 6) for band, value in published.items()}
    average = next(row for row in a5 if row[0] == "Average age of companies (years)")[5]
    first_band = next(iter(published))
    entry = {
        "id": "gb-companies-by-age-since-incorporation-2026-03",
        "title": "Age since incorporation of companies on the UK effective register at 31 March 2026",
        "kind": "marginal",
        "domain": "company",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2026-03-31", "end": "2026-03-31"},
        "tags": ["companies-house", "firm-age", "company-register"],
        "use_cases": ["synthetic-companies", "kyb-onboarding", "pe-portfolio-demo", "credit-underwriting-demo", "company-generation"],
        "spec": {
            "variable": "company_age_band",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": bands, "published_percent": published, "average_age_years": average}},
        },
        "evidence": [
            cra.cite(f"Table A5, row 'Percentage of companies aged {first_band}', column Effective register", published[first_band], "percent", "Analysis of companies on the register in the UK at 31 March 2026 by age since incorporation"),
            cra.cite("Table A5, row 'Average age of companies (years)', column Effective register", average, "decimal", "Average age of companies (years)"),
        ],
        "assumed": [{"parameter": "distribution.parameters.shares", "value": "published percent / sum of published percents", "method": "derived", "rationale": f"The published percentages sum to {round(total_percent, 6)}; shares rescale them to sum to one."}],
        "tests": [
            {"statistic": f'share["{first_band}"]', "expected": bands[first_band], "tolerance": 0.005},
            {"statistic": 'share["1-4 years"]', "expected": bands["1-4 years"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "Share of companies on the UK effective register (excluding those in liquidation or the course of dissolution) by "
            "age since incorporation at 31 March 2026, in thirteen bands, from Table A5 of Companies House's Companies register "
            "activities release for April 2025 to March 2026; the published average age of the effective register rides beside "
            "the shares. Companies House notes that the age categorisation changed in 2022. Published on GOV.UK under the Open "
            "Government Licence v3.0."
        ),
    }
    write_entry(entry)


# ----------------------------------------------------------------------------------------------
# Eurostat: registrations and bankruptcies, high-growth enterprises
# ----------------------------------------------------------------------------------------------

EUROSTAT = "Eurostat"
EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
RB_NACE = ["B-S_X_O_S94", "B-E", "F", "G", "H", "I", "J", "K-N", "P-S_X_S94"]
RB_QUARTERS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]


def eurostat_url(dataflow: str, key: str, start: str, end: str) -> str:
    return f"{EUROSTAT_API}/data/{dataflow}/{key}?startPeriod={start}&endPeriod={end}&format=SDMX-CSV"


def eurostat_labels(name: str) -> dict[str, str]:
    root = ET.fromstring(fetch(f"{EUROSTAT_API}/codelist/ESTAT/{name}"))
    structure = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}"
    common = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}"
    lang = "{http://www.w3.org/XML/1998/namespace}lang"
    labels = {}
    for code in root.iter(f"{structure}Code"):
        for name_node in code.findall(f"{common}Name"):
            if name_node.get(lang) == "en":
                labels[code.get("id")] = name_node.text or ""
    return labels


def eurostat_line(raw: bytes, *fields: str) -> str:
    """The SDMX-CSV substring from the first given field through the observation value."""
    needle = ",".join(fields)
    for line in raw_lines(raw):
        if needle in line:
            start = line.index(needle)
            end = line.index(",", start + len(needle) + 1)
            return line[start:end]
    raise ValueError(f"no line with {needle!r}")


def eu_entries() -> None:
    geo_names = eurostat_labels("GEO")
    nace_names = eurostat_labels("NACE_R2")
    flags_note = "Eurostat flags: b break in series, e estimated, p provisional."

    url = eurostat_url("sts_rb_q", "Q.BKRT+REG.B-S_X_O_S94.SCA.I21.EU27_2020", "2024-Q1", "2026-Q3")
    eu = source(EUROSTAT, "Eurostat SDMX 2.1 API, dataflow sts_rb_q (registrations and bankruptcies index), EU27, SDMX-CSV", url, CC_BY)
    rows = csv_rows(eu.raw)
    values = {(r["indic_bt"], r["TIME_PERIOD"]): float(r["OBS_VALUE"]) for r in rows}
    periods = sorted({period for _, period in values})
    series = [{"period": p, "value": values[("BKRT", p)], "registrations_index": values[("REG", p)]} for p in periods]
    last, first = series[-1], series[0]
    entry = {
        "id": "eu-business-bankruptcies-and-registrations-index-quarterly-2024q1-2026q3",
        "title": "EU business bankruptcy and registration indices (2021=100), seasonally adjusted, quarterly 2024Q1 to 2026Q3",
        "kind": "temporal",
        "domain": "company",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2024-01-01", "end": "2026-09-30"},
        "tags": DISTRESS_TAGS + ["bankruptcy", "business-registrations", "eurostat", "quarterly-series", "index"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "deal-sourcing-demo"],
        "spec": {"variable": "bankruptcy_declarations_index_2021_100", "unit": "decimal", "frequency": "quarterly", "columns": ["registrations_index"], "series": series},
        "evidence": [
            eu.cite(f"BKRT, B-S_X_O_S94, SCA, I21, EU27_2020, {last['period']}", eurostat_line(eu.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", last["period"]).rsplit(",", 1)[1], "decimal", eurostat_line(eu.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", last["period"])),
            eu.cite(f"REG, B-S_X_O_S94, SCA, I21, EU27_2020, {last['period']}", eurostat_line(eu.raw, "REG", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", last["period"]).rsplit(",", 1)[1], "decimal", eurostat_line(eu.raw, "REG", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", last["period"])),
            eu.cite(f"BKRT, B-S_X_O_S94, SCA, I21, EU27_2020, {first['period']}", eurostat_line(eu.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", first["period"]).rsplit(",", 1)[1], "decimal", eurostat_line(eu.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", "EU27_2020", first["period"])),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"column[registrations_index,{last['period']}]", "expected": last["registrations_index"], "tolerance": 0},
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Quarterly indices (2021 = 100) of declarations of bankruptcy and of new business registrations for the EU-27, "
            "business economy excluding public administration and activities of membership organisations (NACE B-S excluding "
            "O and S94), seasonally and calendar adjusted, from Eurostat's short-term business statistics dataflow sts_rb_q. "
            "The dataflow carries indices and growth rates, not counts; use the indices to scale a synthetic default rate "
            "through time rather than as levels. " + EUROSTAT_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    key = "Q.BKRT.B-S_X_O_S94.SCA.I21."
    url = eurostat_url("sts_rb_q", key, RB_QUARTERS[0], RB_QUARTERS[-1])
    by_geo = source(EUROSTAT, "Eurostat SDMX 2.1 API, dataflow sts_rb_q, bankruptcies by country, SDMX-CSV", url, CC_BY)
    table: dict[str, dict] = {}
    flagged = []
    for r in csv_rows(by_geo.raw):
        geo = r["geo"]
        table.setdefault(geo, {"name": geo_names.get(geo, geo)})
        table[geo][r["TIME_PERIOD"]] = float(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
        if r["OBS_FLAG"]:
            flagged.append(f"{geo} {r['TIME_PERIOD']} ({r['OBS_FLAG']})")
    for geo in table:
        for quarter in RB_QUARTERS:
            table[geo].setdefault(quarter, None)
    sample_geo = "FR"
    sample_q = RB_QUARTERS[-1]
    sample_line = eurostat_line(by_geo.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", sample_geo, sample_q)
    de_line = eurostat_line(by_geo.raw, "BKRT", "B-S_X_O_S94", "SCA", "I21", "DE", RB_QUARTERS[0])
    entry = {
        "id": "eu-business-bankruptcies-index-by-country-quarterly-2025-2026",
        "title": "Business bankruptcy declarations index (2021=100) by European country, seasonally adjusted, 2025Q1 to 2026Q3",
        "kind": "rule",
        "domain": "company",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": "2025-01-01",
        "valid_to": "2026-09-30",
        "tags": DISTRESS_TAGS + ["bankruptcy", "eurostat", "by-country", "index", "reference-table"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "Eurostat geo code", "columns": RB_QUARTERS, "rows": table},
            "vectors": [
                {"input": {"key": sample_geo, "column": sample_q}, "expected": table[sample_geo][sample_q], "origin": "source"},
                {"input": {"key": "DE", "column": RB_QUARTERS[0]}, "expected": table["DE"][RB_QUARTERS[0]], "origin": "source"},
                {"input": "US", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            by_geo.cite(f"BKRT, SCA, I21, {sample_geo}, {sample_q}", sample_line.rsplit(",", 1)[1], "decimal", sample_line),
            by_geo.cite(f"BKRT, SCA, I21, DE, {RB_QUARTERS[0]}", de_line.rsplit(",", 1)[1], "decimal", de_line),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": f"value[{sample_geo},{sample_q}]", "expected": table[sample_geo][sample_q], "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
        ],
        "notes": (
            "Index of declarations of bankruptcy (2021 = 100), seasonally and calendar adjusted, for the business economy "
            "excluding public administration and membership organisations, by country and quarter from 2025-Q1 to 2026-Q3, "
            "from Eurostat dataflow sts_rb_q. Rows cover EU member states, the EU and euro-area aggregates and the other "
            "reporting countries; null marks a quarter not yet reported. Each country's index is relative to its own 2021 "
            "level, so compare movements, not levels, across countries. "
            + (f"Flagged observations: {', '.join(flagged)}. {flags_note} " if flagged else "")
            + EUROSTAT_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    url = eurostat_url("sts_rb_q", f"Q.BKRT+REG.{'+'.join(RB_NACE)}.SCA.I21.EU27_2020", RB_QUARTERS[0], RB_QUARTERS[-1])
    by_nace = source(EUROSTAT, "Eurostat SDMX 2.1 API, dataflow sts_rb_q, EU27 by NACE aggregate, SDMX-CSV", url, CC_BY)
    sector_rows: dict[str, dict] = {}
    for r in csv_rows(by_nace.raw):
        prefix = "bankruptcies" if r["indic_bt"] == "BKRT" else "registrations"
        sector_rows.setdefault(r["nace_r2"], {"name": nace_names.get(r["nace_r2"], r["nace_r2"])})
        sector_rows[r["nace_r2"]][f"{prefix}_{r['TIME_PERIOD']}"] = float(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
    construction = eurostat_line(by_nace.raw, "BKRT", "F", "SCA", "I21", "EU27_2020", sample_q)
    hospitality = eurostat_line(by_nace.raw, "BKRT", "I", "SCA", "I21", "EU27_2020", sample_q)
    entry = {
        "id": "eu-business-bankruptcies-and-registrations-index-by-sector-2025-2026",
        "title": "EU business bankruptcy and registration indices (2021=100) by NACE sector aggregate, seasonally adjusted, 2025Q1 to 2026Q3",
        "kind": "rule",
        "domain": "company",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": "2025-01-01",
        "valid_to": "2026-09-30",
        "tags": DISTRESS_TAGS + ["bankruptcy", "business-registrations", "eurostat", "by-industry", "index", "reference-table"],
        "use_cases": ["private-credit-demo", "credit-underwriting-demo", "pe-portfolio-demo", "credit-risk", "deal-sourcing-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "NACE Rev. 2 aggregate code", "geography": "EU27_2020", "rows": sector_rows},
            "vectors": [
                {"input": {"key": "F", "column": f"bankruptcies_{sample_q}"}, "expected": sector_rows["F"][f"bankruptcies_{sample_q}"], "origin": "source"},
                {"input": {"key": "I", "column": f"bankruptcies_{sample_q}"}, "expected": sector_rows["I"][f"bankruptcies_{sample_q}"], "origin": "source"},
                {"input": "Z", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            by_nace.cite(f"BKRT, F, SCA, I21, EU27_2020, {sample_q}", construction.rsplit(",", 1)[1], "decimal", construction),
            by_nace.cite(f"BKRT, I, SCA, I21, EU27_2020, {sample_q}", hospitality.rsplit(",", 1)[1], "decimal", hospitality),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": f"value[F,bankruptcies_{sample_q}]", "expected": sector_rows["F"][f"bankruptcies_{sample_q}"], "tolerance": 0},
            {"statistic": "count", "expected": len(sector_rows), "tolerance": 0},
        ],
        "notes": (
            "EU-27 indices (2021 = 100) of bankruptcy declarations and new business registrations for the nine NACE Rev. 2 "
            "aggregates Eurostat publishes in sts_rb_q (industry B-E, construction F, trade G, transport H, accommodation and "
            "food I, information and communication J, financial, real estate and business services K-N, education, health and "
            "other services P-S excluding S94, and the business-economy total), seasonally and calendar adjusted, 2025-Q1 to "
            "2026-Q3. Columns are named bankruptcies_<quarter> and registrations_<quarter>. " + EUROSTAT_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    indicators = {
        "ENT_HGRW_NR": "high_growth_enterprises",
        "ENT_HGRWR_PC": "high_growth_share_of_active_10plus_percent",
        "SAL_HGRW_NR": "employees_in_high_growth_enterprises",
        "SAL_HGRWR_PC": "high_growth_share_of_employees_percent",
        "ENT_HGRW_YNG_NR": "young_high_growth_enterprises",
        "ENT_HGRWR_YNG_PC": "young_high_growth_share_percent",
    }
    indicator_names = eurostat_labels("INDIC_SBS")
    url = eurostat_url("bd_hg", f"A.{'+'.join(indicators)}.B-S_X_O_S94.", "2024", "2024")
    hg = source(EUROSTAT, "Eurostat SDMX 2.1 API, dataflow bd_hg (high growth enterprises), 2024, SDMX-CSV", url, CC_BY)
    hg_rows: dict[str, dict] = {}
    hg_flags = []
    for r in csv_rows(hg.raw):
        geo = r["geo"]
        hg_rows.setdefault(geo, {"name": geo_names.get(geo, geo), **{name: None for name in indicators.values()}})
        value = number_or_none(r["OBS_VALUE"])
        hg_rows[geo][indicators[r["indic_sbs"]]] = value
        if r["OBS_FLAG"]:
            hg_flags.append(f"{geo} {r['indic_sbs']} ({r['OBS_FLAG']})")
    de_count = eurostat_line(hg.raw, "ENT_HGRW_NR", "B-S_X_O_S94", "DE", "2024")
    eu_share = eurostat_line(hg.raw, "ENT_HGRWR_PC", "B-S_X_O_S94", "EU27_2020", "2024")
    entry = {
        "id": "eu-high-growth-enterprises-by-country-2024",
        "title": "High-growth enterprises and their employment by European country, business economy, 2024",
        "kind": "rule",
        "domain": "business",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": "2024-01-01",
        "valid_to": "2024-12-31",
        "tags": ["business-demography", "high-growth", "gazelles", "eurostat", "by-country", "reference-table"] + DEAL_TAGS,
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "synthetic-companies", "market-sizing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "Eurostat geo code", "activity": "B-S_X_O_S94", "columns": list(indicators.values()), "indicator_labels": {column: indicator_names[code] for code, column in indicators.items()}, "rows": hg_rows},
            "vectors": [
                {"input": {"key": "DE", "column": "high_growth_enterprises"}, "expected": hg_rows["DE"]["high_growth_enterprises"], "origin": "source"},
                {"input": {"key": "EU27_2020", "column": "high_growth_share_of_active_10plus_percent"}, "expected": hg_rows["EU27_2020"]["high_growth_share_of_active_10plus_percent"], "origin": "source"},
                {"input": "US", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            hg.cite("ENT_HGRW_NR, B-S_X_O_S94, DE, 2024", de_count.rsplit(",", 1)[1], "count", de_count),
            hg.cite("ENT_HGRWR_PC, B-S_X_O_S94, EU27_2020, 2024", eu_share.rsplit(",", 1)[1], "percent", eu_share),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "value[EU27_2020,high_growth_enterprises]", "expected": hg_rows["EU27_2020"]["high_growth_enterprises"], "tolerance": 0},
            {"statistic": "count", "expected": len(hg_rows), "tolerance": 0},
        ],
        "notes": (
            "High-growth enterprises in 2024 by country for the business economy excluding public administration and "
            "membership organisations, from Eurostat dataflow bd_hg. High growth is measured in employment. Columns give the "
            "count of high-growth enterprises, their number divided by active enterprises with at least 10 employees, their "
            "employees, those employees divided by employees in active enterprises with at least 10 employees, and the same "
            "count and share for young high-growth enterprises; parameters.indicator_labels carries Eurostat's label for each "
            "indicator. "
            + (f"Flagged observations: {', '.join(hg_flags)}. {flags_note} " if hg_flags else "")
            + EUROSTAT_LICENSE_NOTE
        ),
    }
    write_entry(entry)


# ----------------------------------------------------------------------------------------------
# OECD: FDI positions and FDI Regulatory Restrictiveness Index
# ----------------------------------------------------------------------------------------------

OECD = "OECD"
OECD_API = "https://sdmx.oecd.org/public/rest/data"
FDI_REPORTERS = ["USA", "GBR", "DEU", "FRA", "JPN"]
# Germany publishes only the all-activity total in the industry breakdown, so it is left out there.
FDI_INDUSTRY_REPORTERS = ["USA", "GBR", "FRA", "JPN"]
FDI_SECTIONS = list("ABCDEFGHIJKLMNPQRS")
RRI_SECTORS = ["_T", "B", "C", "D351", "F", "G45_47", "H51", "J61", "K6419", "L", "M691_692_702_71_721_74"]
RRI_POLICIES = {"_T": "total", "CLAS1_1": "foreign_equity_limits", "CLAS1_2": "screening_and_approval", "CLAS1_3": "key_foreign_personnel", "_O": "other_restrictions"}


def oecd_url(flow: str, key: str, year: str) -> str:
    return f"{OECD_API}/{flow}/{key}?startPeriod={year}&endPeriod={year}&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"


def oecd_snippet(raw: bytes, row: dict[str, str], anchor: str) -> str:
    """The raw CSV text of a row from the anchor field through the observation value."""
    for line in raw_lines(raw):
        if f",{row['REF_AREA']}," in line and f",{row['MEASURE_PRINCIPLE']}," in line and f",{anchor}," in line and f",{row['OBS_VALUE']}," in line:
            start = line.index(f",{anchor},") + 1
            end = line.index(f",{row['OBS_VALUE']},", start) + len(row["OBS_VALUE"]) + 1
            snippet = line[start:end]
            words = snippet.split()
            return " ".join(words[-MAX_SNIPPET_WORDS:])
    raise ValueError(f"no raw line for {anchor}")


def iso3_codes() -> set[str]:
    path = REPO_ROOT / "entries/geography/global/global-iso-3166-country-codes-cog-2025.yaml"
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))["spec"]["parameters"]["rows"]
    return {row["iso3"] for row in rows.values() if row.get("iso3")}


def fdi_value(text: str) -> float:
    return round(float(text), 1)


def oecd_entries() -> None:
    countries = iso3_codes()
    key = f"{'+'.join(FDI_REPORTERS)}.LE_FA_F.USD_EXC.DI+DO.NET_FDI.ALL.D.S1..IMC._T.A.CTRY_IND"
    url = oecd_url("OECD.DAF.INV,DSD_FDI@DF_FDI_POS_CTRY,1.0", key, "2024")
    pos = source(OECD, "OECD FDI positions by counterpart area (DF_FDI_POS_CTRY), 2024, CSV with labels", url, UNSTATED)
    records = csv_rows(pos.raw)
    rows: dict[str, dict] = {}
    world_rows = {}
    for direction, label in (("DI", "inward"), ("DO", "outward")):
        for reporter in FDI_REPORTERS:
            selected = [r for r in records if r["REF_AREA"] == reporter and r["MEASURE_PRINCIPLE"] == direction]
            world = next(r for r in selected if r["COUNTERPART_AREA"] == "W")
            partners = [r for r in selected if r["COUNTERPART_AREA"] in countries and r["OBS_VALUE"] and r["CONF_STATUS"] == "F"]
            partners.sort(key=lambda r: float(r["OBS_VALUE"]), reverse=True)
            top = partners[:15]
            rows[f"{reporter}:{label}"] = {
                "reporter": world["Reference area"],
                "direction": label,
                "world_usd_millions": fdi_value(world["OBS_VALUE"]),
                "top_partners_usd_millions": {r["COUNTERPART_AREA"]: fdi_value(r["OBS_VALUE"]) for r in top},
                "top_partner_names": {r["COUNTERPART_AREA"]: r["Counterpart area"] for r in top},
            }
            world_rows[(reporter, direction)] = world
    us_in = world_rows[("USA", "DI")]
    gb_out = world_rows[("GBR", "DO")]
    us_first = next(iter(rows["USA:inward"]["top_partners_usd_millions"]))
    us_first_row = next(r for r in records if r["REF_AREA"] == "USA" and r["MEASURE_PRINCIPLE"] == "DI" and r["COUNTERPART_AREA"] == us_first)
    entry = {
        "id": "global-oecd-fdi-positions-by-partner-2024",
        "title": "Inward and outward FDI positions of the US, UK, Germany, France and Japan by partner economy, end-2024",
        "kind": "rule",
        "domain": "deals",
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2024-12-31",
        "valid_to": "2024-12-31",
        "tags": DEAL_TAGS + ["fdi", "cross-border", "oecd", "by-country", "reference-table"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "market-sizing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "reporter ISO3 code and direction", "unit": "US dollars, millions, exchange-rate converted", "rows": rows},
            "vectors": [
                {"input": {"key": "USA:inward", "column": "world_usd_millions"}, "expected": rows["USA:inward"]["world_usd_millions"], "origin": "source"},
                {"input": {"key": "GBR:outward", "column": "world_usd_millions"}, "expected": rows["GBR:outward"]["world_usd_millions"], "origin": "source"},
                {"input": "IND:inward", "expected": False, "origin": "derived", "note": "India does not report to this OECD dataflow"},
            ],
        },
        "evidence": [
            pos.cite("REF_AREA=USA, MEASURE_PRINCIPLE=DI, COUNTERPART_AREA=W, 2024", us_in["OBS_VALUE"], "currency:USD", oecd_snippet(pos.raw, us_in, "W")),
            pos.cite("REF_AREA=GBR, MEASURE_PRINCIPLE=DO, COUNTERPART_AREA=W, 2024", gb_out["OBS_VALUE"], "currency:USD", oecd_snippet(pos.raw, gb_out, "W")),
            pos.cite(f"REF_AREA=USA, MEASURE_PRINCIPLE=DI, COUNTERPART_AREA={us_first}, 2024", us_first_row["OBS_VALUE"], "currency:USD", oecd_snippet(pos.raw, us_first_row, us_first)),
        ],
        "assumed": [
            {"parameter": "rows[*].world_usd_millions and top_partners_usd_millions", "value": "published value rounded to 0.1", "method": "derived", "rationale": "The OECD publishes positions in millions of US dollars to several decimals; the table keeps one decimal."},
            {"parameter": "rows[*].top_partners_usd_millions", "value": "15 largest individual partner economies", "method": "derived", "rationale": "Partners are limited to ISO 3166 economies (regional and economic aggregates dropped, ISO list from the archive's ISO 3166 entry), confidential cells left out, and ranked by position."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "value[USA:inward,world_usd_millions]", "expected": rows["USA:inward"]["world_usd_millions"], "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
        ],
        "notes": (
            "Foreign direct investment positions at the end of 2024 under the directional principle (inward: foreign "
            "investment in the reporter; outward: the reporter's investment abroad), all resident units, immediate "
            "counterpart, total of equity and debt, in millions of US dollars converted at market exchange rates, from OECD "
            "dataflow DF_FDI_POS_CTRY (BMD4). Each row carries the world total and the fifteen largest individual partner "
            "economies; partners whose data are confidential are not ranked. Partners are immediate counterparts, "
            "not ultimate investors. India does not report to this dataflow. " + OECD_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    key = f"{'+'.join(FDI_INDUSTRY_REPORTERS)}.LE_FA_F.USD_EXC.DI+DO.NET_FDI.ALL.D.S1.W.IMC.{'+'.join(FDI_SECTIONS + ['_T'])}.A."
    url = oecd_url("OECD.DAF.INV,DSD_FDI@DF_FDI_POS_IND,1.0", key, "2024")
    ind = source(OECD, "OECD FDI positions by economic activity (DF_FDI_POS_IND), 2024, CSV with labels", url, UNSTATED)
    records = csv_rows(ind.raw)
    section_names = {}
    industry_rows: dict[str, dict] = {}
    for direction, label in (("DI", "inward"), ("DO", "outward")):
        for reporter in FDI_INDUSTRY_REPORTERS:
            selected = {r["ACTIVITY"]: r for r in records if r["REF_AREA"] == reporter and r["MEASURE_PRINCIPLE"] == direction}
            row = {"total_usd_millions": fdi_value(selected["_T"]["OBS_VALUE"]) if selected.get("_T", {}).get("OBS_VALUE") else None}
            for section in FDI_SECTIONS:
                cell = selected.get(section)
                row[section] = fdi_value(cell["OBS_VALUE"]) if cell and cell["OBS_VALUE"] and cell["CONF_STATUS"] == "F" else None
                if cell:
                    section_names[section] = cell["Economic activity"]
            industry_rows[f"{reporter}:{label}"] = row
    manufacturing = next(r for r in records if r["REF_AREA"] == "USA" and r["MEASURE_PRINCIPLE"] == "DI" and r["ACTIVITY"] == "C")
    finance = next(r for r in records if r["REF_AREA"] == "FRA" and r["MEASURE_PRINCIPLE"] == "DO" and r["ACTIVITY"] == "K")
    entry = {
        "id": "global-oecd-fdi-positions-by-industry-2024",
        "title": "Inward and outward FDI positions of the US, UK, France and Japan by ISIC section, end-2024",
        "kind": "rule",
        "domain": "deals",
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2024-12-31",
        "valid_to": "2024-12-31",
        "tags": DEAL_TAGS + ["fdi", "cross-border", "oecd", "by-industry", "reference-table"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "market-sizing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "reporter ISO3 code and direction", "unit": "US dollars, millions, exchange-rate converted", "sections": section_names, "rows": industry_rows},
            "vectors": [
                {"input": {"key": "USA:inward", "column": "C"}, "expected": industry_rows["USA:inward"]["C"], "origin": "source"},
                {"input": {"key": "FRA:outward", "column": "K"}, "expected": industry_rows["FRA:outward"]["K"], "origin": "source"},
                {"input": "CHN:inward", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            ind.cite("REF_AREA=USA, MEASURE_PRINCIPLE=DI, ACTIVITY=C, 2024", manufacturing["OBS_VALUE"], "currency:USD", oecd_snippet(ind.raw, manufacturing, "C")),
            ind.cite("REF_AREA=FRA, MEASURE_PRINCIPLE=DO, ACTIVITY=K, 2024", finance["OBS_VALUE"], "currency:USD", oecd_snippet(ind.raw, finance, "K")),
        ],
        "assumed": [{"parameter": "rows[*]", "value": "published value rounded to 0.1", "method": "derived", "rationale": "Positions in millions of US dollars kept to one decimal."}],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "value[USA:inward,C]", "expected": industry_rows["USA:inward"]["C"], "tolerance": 0},
            {"statistic": "count", "expected": len(industry_rows), "tolerance": 0},
        ],
        "notes": (
            "FDI positions at the end of 2024 by ISIC Rev. 4 section of the resident enterprise (inward) or of the resident "
            "investor (outward), world counterpart, directional principle, all resident units, in millions of US dollars, "
            "from OECD dataflow DF_FDI_POS_IND (BMD4). Null marks a confidential or unreported cell, so sections need not sum to "
            "the total; net positions can be negative. Germany publishes "
            "only the all-activity total in this breakdown and India does not report to the dataflow, so neither is included. "
            + OECD_LICENSE_NOTE
        ),
    }
    write_entry(entry)

    key = f".{'+'.join(RRI_SECTORS)}.{'+'.join(RRI_POLICIES)}.RR.IX"
    url = oecd_url("OECD.DAF.INV,DSD_FDIRRI_SCORES@DF_FDIRRI_SCORES,2.0", key, "2025")
    rri = source(OECD, "OECD FDI Regulatory Restrictiveness Index scores (DF_FDIRRI_SCORES), 2025, CSV with labels", url, UNSTATED)
    records = csv_rows(rri.raw)
    sector_names = {}
    rri_rows: dict[str, dict] = {}
    for r in records:
        country = rri_rows.setdefault(r["REF_AREA"], {"name": r["Reference area"]})
        sector_names[r["ACTIVITY"]] = r["Economic activity"]
        if r["ACTIVITY"] == "_T":
            country[RRI_POLICIES[r["POL_CAT"]]] = float(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
        elif r["POL_CAT"] == "_T":
            country[f"sector_{r['ACTIVITY']}"] = float(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
    columns = list(RRI_POLICIES.values()) + [f"sector_{s}" for s in RRI_SECTORS if s != "_T"]
    for country in rri_rows.values():
        for column in columns:
            country.setdefault(column, None)
    india = next(r for r in records if r["REF_AREA"] == "IND" and r["ACTIVITY"] == "_T" and r["POL_CAT"] == "_T")
    usa = next(r for r in records if r["REF_AREA"] == "USA" and r["ACTIVITY"] == "_T" and r["POL_CAT"] == "CLAS1_2")
    entry = {
        "id": "global-oecd-fdi-regulatory-restrictiveness-index-2025",
        "title": "OECD FDI Regulatory Restrictiveness Index by country, restriction type and selected sector, 2025",
        "kind": "rule",
        "domain": "deals",
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2025-01-01",
        "valid_to": "2025-12-31",
        "tags": DEAL_TAGS + ["fdi", "cross-border", "regulation", "oecd", "by-country", "reference-table"],
        "use_cases": ["deal-sourcing-demo", "pe-portfolio-demo", "valuation-demo", "compliance-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"key": "ISO3 reference area", "scale": "0 (open) to 1 (closed)", "sectors": {s: sector_names.get(s) for s in RRI_SECTORS}, "columns": columns, "rows": rri_rows},
            "vectors": [
                {"input": {"key": "IND", "column": "total"}, "expected": rri_rows["IND"]["total"], "origin": "source"},
                {"input": {"key": "USA", "column": "screening_and_approval"}, "expected": rri_rows["USA"]["screening_and_approval"], "origin": "source"},
                {"input": "ZZZ", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            rri.cite("REF_AREA=IND, ACTIVITY=_T, POL_CAT=_T, 2025", india["OBS_VALUE"], "decimal", f"IND,India,_T,Total - All activities,_T,Total,RR,Regulatory restrictiveness,IX,Index,2025,,{india['OBS_VALUE']}"),
            rri.cite("REF_AREA=USA, ACTIVITY=_T, POL_CAT=CLAS1_2, 2025", usa["OBS_VALUE"], "decimal", f"USA,United States,_T,Total - All activities,CLAS1_2,Screening and approval,RR,Regulatory restrictiveness,IX,Index,2025,,{usa['OBS_VALUE']}"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "value[IND,total]", "expected": rri_rows["IND"]["total"], "tolerance": 0},
            {"statistic": "count", "expected": len(rri_rows), "tolerance": 0},
        ],
        "notes": (
            "Statutory restrictions on foreign direct investment scored by the OECD from 0 (open) to 1 (closed), 2025 "
            "edition, from dataflow DF_FDIRRI_SCORES. For each economy the row carries the all-sector index and its four "
            "components (foreign equity limits, screening and approval, restrictions on key foreign personnel, other "
            "restrictions) and the overall index for ten sectors: mining, manufacturing, electricity, construction, retail, "
            "air transport, telecommunications, banking (other monetary intermediation), real estate and professional "
            "services. " + OECD_LICENSE_NOTE
        ),
    }
    write_entry(entry)


def main() -> int:
    hsr_entries()
    us_bankruptcy_entries()
    gb_insolvency_entries()
    gb_ma_entries()
    gb_register_entries()
    eu_entries()
    oecd_entries()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

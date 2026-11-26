"""Regenerate the private equity tax and fund regulation entries.

These are the rules that drive deal structuring, fund formation and exit
modelling, each read from the statute, regulation or official dataset that
states it:

* OECD Corporate Tax Statistics (SDMX CSV): combined statutory corporate income
  tax rates, forward-looking effective tax rates and standard withholding tax
  rates by jurisdiction.
* United States Code (govinfo, 2024 edition) and Public Law 119-21 (govinfo
  USLM XML): QSBS exclusion, business interest limitation, bonus depreciation,
  carried interest holding period, net investment income tax and the qualified
  business income deduction; IRS Rev. Proc. 2025-32 for 2026 indexed amounts.
* eCFR (pinned date) and the Federal Register: Regulation D, adviser
  exemptions, qualified client amounts, venture capital fund definitions, the
  ERISA plan-asset test.
* legislation.gov.uk and the GOV.UK content API: Business Asset Disposal
  Relief, carried interest, Corporate Interest Restriction, substantial
  shareholding exemption, EIS and SEIS.
* Basiswettenbestand (wetten.overheid.nl): the Dutch earnings-stripping rule.

Run from the repository root:

    uv run python tools/build_pe_tax.py
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import evidence, fetch, write

from almanac.fetch import Resource

MAX_SNIPPET_WORDS = 24
UNSTATED = "unstated"
OGL = "OGL-UK-3.0"

ECFR_DATE = "2026-11-02"
ECFR = "https://www.ecfr.gov/api/versioner/v1/full"
GOVINFO = "https://www.govinfo.gov/content/pkg"
LEGISLATION = "https://www.legislation.gov.uk"
LEGISLATION_DATE = "2026-11-26"
OECD = "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS"

OLRC = "Office of the Law Revision Counsel, US House of Representatives, via govinfo"
GPO = "US Government Publishing Office (govinfo)"
OFR = "Office of the Federal Register via the eCFR API"
IRS = "Internal Revenue Service, US Department of the Treasury"
SEC_FR = "US Securities and Exchange Commission, Federal Register via govinfo"
OECD_CTP = "OECD Centre for Tax Policy and Administration"
TNA = "The National Archives (legislation.gov.uk)"
HMRC = "HM Revenue & Customs"
KOOP = "Overheid.nl (Basiswettenbestand)"

TAGS = ["tax", "private-equity", "structuring"]
FUND_TAGS = ["funds", "private-equity", "regulation"]

US_LICENSE_NOTE = (
    "Works of the US federal government carry no copyright in the United States, but the cited resources state no "
    "reuse terms, so the licence is recorded as unstated and the entry held at license-review."
)
OECD_LICENSE_NOTE = (
    "The OECD SDMX response carries no licence statement, so the licence is recorded as unstated and the entry held at "
    "license-review until a reviewer confirms the OECD terms that apply to the dataset."
)
UK_LICENSE_NOTE = (
    "legislation.gov.uk publishes Crown copyright legislation for reuse, but the cited resource carries no licence "
    "statement of its own, so the licence is recorded as unstated and the entry held at license-review."
)
NL_LICENSE_NOTE = (
    "Dutch statutes carry no copyright under the Auteurswet, but the BWB XML carries no licence statement, so the "
    "licence is recorded as unstated and the entry stays at license-review."
)


def collapse(text: str) -> str:
    return " ".join(text.split())


def strip_markup(markup: str) -> str:
    """Readable text of an HTML or XML resource, one line per block, whitespace collapsed within lines."""
    markup = re.sub(r"<(script|style).*?</\1>", "", markup, flags=re.DOTALL)
    markup = re.sub(r'<a class="noteRef[^"]*"[^>]*>[^<]*</a>', "", markup)
    markup = re.sub(r"</(p|P|h\d|li|tr|td|th|al|lid|div|DIV\d)>|<br\s*/?>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return "\n".join(collapse(line) for line in text.splitlines() if line.strip())


@dataclass(frozen=True)
class Doc:
    """One fetched resource, searched the way the verifier searches it."""

    publisher: str
    title: str
    url: str
    raw: bytes
    license_id: str = UNSTATED

    @cached_property
    def searchable(self) -> str:
        return collapse(Resource(url=self.url, content=self.raw, content_type="").text)

    @cached_property
    def plain(self) -> str:
        """Tag-free text for parsing values; PDFs and ZIPs use the verifier's extracted text."""
        resource = Resource(url=self.url, content=self.raw, content_type="")
        if resource.is_pdf or resource.is_zip:
            return resource.text
        return strip_markup(self.raw.decode("utf-8", errors="replace"))

    def find(self, pattern: str, group: int = 1, flags: int = 0) -> str:
        match = re.search(pattern, self.plain, flags)
        if match is None:
            raise ValueError(f"pattern {pattern!r} not found in {self.url}")
        return match.group(group)

    def cite(self, locator: str, value, unit: str, snippet: str, role: str = "primary") -> dict:
        """Evidence item; fails at build time when the snippet or value is not in the fetched bytes."""
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet exceeds {MAX_SNIPPET_WORDS} words: {snippet!r}")
        for needle, what in ((snippet, "snippet"), (str(value), "value")):
            if collapse(needle) not in self.searchable:
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        return evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, self.license_id, self.raw, role)


def get(publisher: str, title: str, url: str, license_id: str = UNSTATED) -> Doc:
    return Doc(publisher, title, url, fetch(url), license_id)


def money(text: str) -> int:
    return int(text.replace("$", "").replace("£", "").replace("€", "").replace(",", "").replace(".", "").strip())


def us_date(text: str) -> str:
    for layout in ("%B %d, %Y", "%b. %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, layout).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    if text.startswith("Sept. "):
        return us_date(text.replace("Sept. ", "Sep. "))
    raise ValueError(f"unrecognised date {text!r}")


def number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def rule(entry_id: str, title: str, domain: str, region: str, tier: str, valid_from: str, valid_to: str | None, tags: list[str], use_cases: list[str], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], tests: list[dict], notes: str, assumed: list[dict] | None = None, status: str = "license-review") -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": f"almanac.rules.{implementation}", "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes,
    }


def vector(value, expected, origin: str = "source", note: str | None = None) -> dict:
    item = {"input": value, "expected": expected, "origin": origin}
    if note:
        item["note"] = note
    return item


def lookup(key: str, column: str = "value") -> dict:
    return {"key": key, "column": column}


# --------------------------------------------------------------------------- OECD Corporate Tax Statistics


def oecd_csv(doc: Doc) -> list[dict]:
    return list(csv.DictReader(io.StringIO(doc.raw.decode("utf-8"))))


def oecd_row_snippet(row: dict, columns: list[str], value_column: str = "OBS_VALUE") -> str:
    """The run of CSV cells from the reference area to the observation value, as it appears in the file."""
    header = list(row.keys())
    start, end = header.index(columns[0]), header.index(value_column)
    return ",".join(row[name] for name in header[start : end + 1])


def oecd_statutory_cit() -> dict:
    url = f"{OECD},DSD_TAX_CIT@DF_CIT,2.0/.A.CIT_C.ST.PT_INC_TAX.S13...?startPeriod=2000&endPeriod=2026&format=csvfilewithlabels&dimensionAtObservation=AllDimensions"
    doc = get(OECD_CTP, "OECD Corporate Tax Statistics, combined statutory corporate income tax rates 2000-2026 (SDMX CSV)", url)
    records = oecd_csv(doc)
    rows: dict[str, dict] = {}
    for record in records:
        row = rows.setdefault(record["REF_AREA"], {"name": record["Reference area"]})
        row[record["TIME_PERIOD"]] = number(record["OBS_VALUE"])
    rows = {code: dict(sorted(row.items(), key=lambda kv: (kv[0] != "name", kv[0]))) for code, row in sorted(rows.items())}
    by_key = {(r["REF_AREA"], r["TIME_PERIOD"]): r for r in records}
    cited = [("USA", "2026"), ("GBR", "2026"), ("DEU", "2026"), ("IRL", "2026"), ("FRA", "2026"), ("USA", "2000")]
    items = [
        doc.cite(f"row REF_AREA={code}, TIME_PERIOD={year}", by_key[(code, year)]["OBS_VALUE"], "percent", oecd_row_snippet(by_key[(code, year)], ["REF_AREA"]))
        for code, year in cited
    ]
    years = sorted({r["TIME_PERIOD"] for r in records})
    usa_2026 = rows["USA"]["2026"]
    deu_2000 = rows["DEU"]["2000"]
    return rule(
        "global-oecd-combined-statutory-corporate-income-tax-rates-2000-2026",
        "Combined (central and sub-central) statutory corporate income tax rates by jurisdiction, 2000-2026 (OECD Corporate Tax Statistics)",
        "tax",
        "global",
        "A",
        f"{years[0]}-01-01",
        f"{years[-1]}-12-31",
        [*TAGS, "corporate-income-tax", "statutory-rate", "oecd", "by-country", "reference-table"],
        ["lbo-modelling", "valuation-demo", "tax-demo", "pe-portfolio-demo"],
        "lookup_table",
        {
            "dataflow": "OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,2.0",
            "measure": "CIT_C (combined corporate income tax rate), statutory, general government",
            "unit": "percent of taxable income",
            "key": "ISO 3166-1 alpha-3 jurisdiction code (OECD REF_AREA)",
            "columns": "name, then one column per year with the rate in force that year",
            "rows": rows,
        },
        [
            vector(lookup("USA", "2026"), usa_2026),
            vector(lookup("DEU", "2000"), deu_2000),
            vector(lookup("IRL", "2026"), rows["IRL"]["2026"]),
            vector("ATLANTIS", False, "derived", "not a reporting jurisdiction"),
        ],
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[GBR,2026]", "expected": rows["GBR"]["2026"], "tolerance": 0},
            {"statistic": "value[USA,2026]", "expected": usa_2026, "tolerance": 0},
        ],
        (
            "The OECD's combined statutory corporate income tax rate for each jurisdiction in its Corporate Tax "
            "Statistics database: the central government rate plus the sub-central rate, adjusted where sub-central tax "
            "is deductible at central level (for the United States an average of state rates, for Germany trade tax at "
            "an average multiplier). Rows are keyed by the OECD reference area code and carry one column per year; a "
            "year is absent where the OECD publishes no value. Rates are the statutory headline rates in force for the "
            "year and do not reflect preferential regimes, small business rates or effective tax burdens. "
            + OECD_LICENSE_NOTE
        ),
    )


def oecd_effective_tax_rates() -> dict:
    url = f"{OECD},DSD_ETR@DF_ETR_BASELINE,2.1/.A.EATR+EMTR.PT_INC_TAX.BASELINE.FIXED.COMPOSITE._Z?startPeriod=2025&endPeriod=2025&format=csvfilewithlabels"
    doc = get(OECD_CTP, "OECD Corporate Tax Statistics, effective tax rates (EATR and EMTR), composite asset, fixed macroeconomic scenario, 2025 (SDMX CSV)", url)
    records = oecd_csv(doc)
    rows: dict[str, dict] = {}
    for record in records:
        row = rows.setdefault(record["REF_AREA"], {"name": record["Reference area"]})
        row[record["MEASURE"].lower() + "_percent"] = number(record["OBS_VALUE"])
    rows = dict(sorted(rows.items()))
    by_key = {(r["REF_AREA"], r["MEASURE"]): r for r in records}
    cited = [("USA", "EATR"), ("USA", "EMTR"), ("GBR", "EATR"), ("DEU", "EATR"), ("IRL", "EMTR")]
    items = [doc.cite(f"row REF_AREA={code}, MEASURE={measure}", by_key[(code, measure)]["OBS_VALUE"], "percent", oecd_row_snippet(by_key[(code, measure)], ["REF_AREA"])) for code, measure in cited]
    return rule(
        "global-oecd-effective-tax-rates-2025",
        "Forward-looking effective average and marginal corporate tax rates (EATR, EMTR) by jurisdiction, 2025 (OECD Corporate Tax Statistics)",
        "tax",
        "global",
        "A",
        "2025-01-01",
        "2025-12-31",
        [*TAGS, "corporate-income-tax", "effective-tax-rate", "oecd", "by-country", "reference-table"],
        ["lbo-modelling", "valuation-demo", "tax-demo", "pe-portfolio-demo"],
        "lookup_table",
        {
            "dataflow": "OECD.CTP.TPS,DSD_ETR@DF_ETR_BASELINE,2.1",
            "scenario": "baseline tax basis, fixed interest and inflation rates, composite asset",
            "unit": "percent of taxable income",
            "key": "ISO 3166-1 alpha-3 jurisdiction code (OECD REF_AREA)",
            "rows": rows,
        },
        [
            vector(lookup("USA", "eatr_percent"), rows["USA"]["eatr_percent"]),
            vector(lookup("USA", "emtr_percent"), rows["USA"]["emtr_percent"]),
            vector(lookup("DEU", "eatr_percent"), rows["DEU"]["eatr_percent"]),
            vector("ATLANTIS", False, "derived", "not a covered jurisdiction"),
        ],
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[GBR,eatr_percent]", "expected": rows["GBR"]["eatr_percent"], "tolerance": 0},
        ],
        (
            "Forward-looking effective tax rates the OECD computes from each jurisdiction's statutory rate and capital "
            "allowance rules for a hypothetical investment: the effective average tax rate (EATR) measures the tax share "
            "of a profitable project's pre-tax return and drives location choices; the effective marginal tax rate (EMTR) "
            "measures the tax wedge on a marginal project and drives investment scale. The figures are the composite "
            "asset (a weighted mix of buildings, tangibles, software and inventories) under the scenario with common "
            "fixed interest and inflation rates, as published to several decimal places. They are model outputs, not "
            "observed tax payments. " + OECD_LICENSE_NOTE
        ),
    )


def oecd_withholding_tax_rates() -> dict:
    url = f"{OECD},DSD_WHT@DF_WHT_STANDARD,1.0/._Z.A.WHT_DIV+WHT_INT+WHT_ROY.PT_INC_TAX.STA._Z?startPeriod=2026&endPeriod=2026&format=csvfilewithlabels"
    doc = get(OECD_CTP, "OECD Corporate Tax Statistics, standard withholding tax rates on dividends, interest and royalties, 2026 (SDMX CSV)", url)
    records = oecd_csv(doc)
    column = {"WHT_DIV": "dividends_percent", "WHT_INT": "interest_percent", "WHT_ROY": "royalties_percent"}
    rows: dict[str, dict] = {}
    for record in records:
        row = rows.setdefault(record["REF_AREA"], {"name": record["Reference area"]})
        row[column[record["MEASURE"]]] = number(record["OBS_VALUE"])
    rows = {code: {"name": row["name"], **{c: row.get(c) for c in column.values()}} for code, row in sorted(rows.items())}
    by_key = {(r["REF_AREA"], r["MEASURE"]): r for r in records}
    cited = [("USA", "WHT_DIV"), ("GBR", "WHT_INT"), ("DEU", "WHT_DIV"), ("NLD", "WHT_DIV"), ("IRL", "WHT_ROY")]
    items = [doc.cite(f"row REF_AREA={code}, MEASURE={measure}", by_key[(code, measure)]["OBS_VALUE"], "percent", oecd_row_snippet(by_key[(code, measure)], ["REF_AREA"])) for code, measure in cited]
    return rule(
        "global-oecd-standard-withholding-tax-rates-2026",
        "Standard (non-treaty) withholding tax rates on dividends, interest and royalties paid to non-residents, by jurisdiction, 2026 (OECD)",
        "tax",
        "global",
        "A",
        "2026-01-01",
        "2026-12-31",
        [*TAGS, "withholding-tax", "cross-border", "oecd", "by-country", "reference-table"],
        ["lbo-modelling", "fund-administration-demo", "tax-demo", "valuation-demo"],
        "lookup_table",
        {
            "dataflow": "OECD.CTP.TPS,DSD_WHT@DF_WHT_STANDARD,1.0",
            "legal_basis": "standard (domestic law) rates, before any tax treaty reduction",
            "unit": "percent of the gross payment",
            "key": "ISO 3166-1 alpha-3 jurisdiction code (OECD REF_AREA)",
            "rows": rows,
        },
        [
            vector(lookup("USA", "dividends_percent"), rows["USA"]["dividends_percent"]),
            vector(lookup("GBR", "interest_percent"), rows["GBR"]["interest_percent"]),
            vector(lookup("GBR", "dividends_percent"), rows["GBR"]["dividends_percent"]),
            vector("ATLANTIS", False, "derived", "not a covered jurisdiction"),
        ],
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[USA,royalties_percent]", "expected": rows["USA"]["royalties_percent"], "tolerance": 0},
        ],
        (
            "The withholding tax rate a jurisdiction applies under its domestic law to dividends, interest and royalties "
            "paid to non-resident companies, as collected for the OECD Corporate Tax Statistics. These are the rates "
            "before any reduction under a double tax treaty or an EU directive, which commonly lower them to zero for "
            "qualifying holdings; the OECD publishes treaty rates in a separate dataflow. A column is null where the "
            "OECD publishes no rate for that payment type. " + OECD_LICENSE_NOTE
        ),
    )


def oecd_interest_limitation_rules() -> dict:
    url = f"{OECD},DSD_QDD_ILR@DF_QDD_ILR,2.0/.A.ILR+RULE_TYPE+FAM+RV+DMT+LA+GR+CF.REGIME1+_Z?startPeriod=2026&endPeriod=2026&format=csvfilewithlabels"
    doc = get(OECD_CTP, "OECD Corporate Tax Statistics, interest limitation rules, main regime, 2026 (SDMX CSV)", url)
    records = oecd_csv(doc)
    column = {"ILR": "has_rule", "RULE_TYPE": "rule_type", "FAM": "financial_measure", "RV": "ratio_as_published", "DMT": "de_minimis_as_published", "LA": "interest_basis", "GR": "group_ratio_rule", "CF": "carry_forward_or_back"}
    rows: dict[str, dict] = {}
    for record in records:
        row = rows.setdefault(record["REF_AREA"], {"name": record["Reference area"]})
        row[column[record["MEASURE"]]] = " ".join(record["OBS_VALUE"].split())
    rows = {code: {"name": row["name"], **{c: row.get(c) for c in column.values()}} for code, row in sorted(rows.items())}
    by_key = {(r["REF_AREA"], r["MEASURE"]): r for r in records}
    cited = [("DEU", "RULE_TYPE"), ("DEU", "DMT"), ("GBR", "RV"), ("GBR", "DMT"), ("USA", "LA"), ("NLD", "FAM")]
    items = [doc.cite(f"row REF_AREA={code}, MEASURE={measure}, REGIME=REGIME1", by_key[(code, measure)]["OBS_VALUE"], "text", oecd_row_snippet(by_key[(code, measure)], ["REF_AREA"])) for code, measure in cited]
    with_rule = sum(1 for row in rows.values() if row["has_rule"] == "Yes")
    return rule(
        "global-oecd-interest-limitation-rules-2026",
        "Interest limitation rules by jurisdiction, 2026: rule type, earnings measure, ratio, de minimis, group ratio (OECD Corporate Tax Statistics)",
        "tax",
        "global",
        "A",
        "2026-01-01",
        "2026-12-31",
        [*TAGS, "interest-limitation", "atad", "beps-action-4", "oecd", "by-country", "reference-table"],
        ["lbo-modelling", "private-credit-demo", "tax-demo", "valuation-demo"],
        "lookup_table",
        {
            "dataflow": "OECD.CTP.TPS,DSD_QDD_ILR@DF_QDD_ILR,2.0",
            "regime": "REGIME1 (the main rule) where reported; has_rule may come from the not-applicable regime for jurisdictions without a rule",
            "key": "ISO 3166-1 alpha-3 jurisdiction code (OECD REF_AREA)",
            "columns": "values as the OECD publishes them (free text); null where not reported",
            "rows": rows,
        },
        [
            vector(lookup("DEU", "rule_type"), rows["DEU"]["rule_type"]),
            vector(lookup("GBR", "ratio_as_published"), rows["GBR"]["ratio_as_published"]),
            vector(lookup("USA", "interest_basis"), rows["USA"]["interest_basis"]),
            vector(lookup("DEU", "de_minimis_as_published"), rows["DEU"]["de_minimis_as_published"]),
            vector("ATLANTIS", False, "derived", "not a covered jurisdiction"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        (
            "The OECD's survey of interest limitation rules (BEPS Action 4 and, for EU members, article 4 of the Anti-Tax "
            "Avoidance Directive) for 2026: whether a jurisdiction has a rule, its type (fixed ratio, earnings stripping, "
            "thin capitalisation), the earnings measure, the ratio, any de minimis threshold, whether it applies to net "
            "or gross interest, whether a group ratio escape exists and whether disallowed amounts carry over. The cells "
            "are free text supplied by each jurisdiction and kept as published, whitespace collapsed; some numeric cells "
            "are not ratios in the form the law states them (Germany's ratio cell holds a fraction that does not read as "
            "30%), so the statute-level entries for the United States, United Kingdom and the Netherlands should be "
            f"preferred where they exist. {with_rule} jurisdictions report a rule. " + OECD_LICENSE_NOTE
        ),
        [{"parameter": "rows.*", "value": "whitespace", "method": "derived", "rationale": "Line breaks inside published cells are collapsed to single spaces; the text is otherwise unchanged."}],
    )


# --------------------------------------------------------------------------- United States: Internal Revenue Code


def usc(title: int, path: str, section: str, heading: str) -> Doc:
    url = f"{GOVINFO}/USCODE-2024-title{title}/html/USCODE-2024-title{title}-{path}.htm"
    return get(OLRC, f"{title} U.S.C. {section}, {heading} (United States Code 2024 edition, HTML)", url)


def public_law_119_21() -> Doc:
    return get(GPO, "Public Law 119-21, 139 Stat. 72 (July 4, 2025), USLM XML", f"{GOVINFO}/PLAW-119publ21/uslm/PLAW-119publ21.xml")


def rev_proc_2025_32() -> Doc:
    return get(IRS, "Rev. Proc. 2025-32, 2026 inflation-adjusted items (PDF)", "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf")


def plaw_section(doc: Doc, number: str) -> str:
    """Plain text of one section of the public law, for parsing."""
    text = doc.plain
    start = text.index(f"SEC. {number}.")
    end = re.search(r"SEC\. \d+\.", text[start + 10 :])
    return text[start : start + 10 + end.start()] if end else text[start:]


def us_qsbs(plaw: Doc) -> dict:
    code = usc(26, "subtitleA-chap1-subchapP-partI-sec1202", "1202", "Partial exclusion for gain from certain small business stock")
    law = collapse(plaw_section(plaw, "70431"))
    enacted = plaw.find(r"PUBLIC LAW 119.21.(\w+ \d+, \d{4})", flags=re.IGNORECASE)
    applicable_date = us_date(enacted.title())
    rra_1993 = us_date(code.find(r"Pub\. L\. 103.66, which was approved (\w+\. \d+, \d{4})"))
    arra_2009 = us_date(code.find(r"Pub\. L\. 111.5, which was approved (\w+\. \d+, \d{4})"))
    csbja_2010 = us_date(code.find(r"Pub\. L\. 111.240, which was approved (\w+\. \d+, \d{4})"))
    base_percent = int(code.find(r"gross income shall not include (\d+) percent of any gain from the sale or exchange of qualified small business stock held for more than (\d+) years"))
    base_years = int(code.find(r"qualified small business stock held for more than (\d+) years"))
    percent_2009 = int(code.find(r"\(A\) paragraph \(1\) shall be applied by substituting \"(\d+) percent\" for \"50 percent\""))
    percent_2010 = int(code.find(r"\(4\) (\d+) percent exclusion for stock acquired during certain periods in 2010"))
    schedule = [{"years_held": int(y), "percent": int(p)} for y, p in re.findall(r"(\d) years(?: or more)? (\d+)%", law)]
    old_limit = money(re.search(r"on or before the applicable date, (\$[\d,]+), reduced by", law).group(1))
    new_limit = money(re.search(r"after the applicable date, (\$[\d,]+), reduced by the sum of", law).group(1))
    multiple = int(code.find(r"\(B\) (\d+) times the aggregate adjusted bases of qualified small business stock"))
    old_assets = money(re.search(r"by striking “ (\$[\d,]+) ” and inserting “ \$[\d,]+ ”\.", law).group(1))
    new_assets = money(re.search(r"by striking “ \$[\d,]+ ” and inserting “ (\$[\d,]+) ”\.", law).group(1))
    rounding = money(re.search(r"rounded to the nearest multiple of (\$[\d,]+)", law).group(1))
    parameters = {
        "currency": "USD",
        "applicable_date": applicable_date,
        "acquisition_periods": [
            {"acquired_after": rra_1993, "acquired_on_or_before": arra_2009, "percent": base_percent, "more_than_years": base_years, "section": "1202(a)(1)(A)"},
            {"acquired_after": arra_2009, "acquired_on_or_before": csbja_2010, "percent": percent_2009, "more_than_years": base_years, "section": "1202(a)(3)"},
            {"acquired_after": csbja_2010, "acquired_on_or_before": applicable_date, "percent": percent_2010, "more_than_years": base_years, "section": "1202(a)(4)"},
        ],
        "holding_schedule": schedule,
        "dollar_limit": {"on_or_before_applicable_date": old_limit, "after_applicable_date": new_limit},
        "married_filing_separately_dollar_limit_on_or_before_applicable_date": old_limit // 2,
        "basis_multiple": multiple,
        "aggregate_gross_assets_limit": {"stock_issued_on_or_before_applicable_date": old_assets, "stock_issued_after_applicable_date": new_assets},
        "inflation_adjustment": {"amounts": ["dollar_limit.after_applicable_date", "aggregate_gross_assets_limit.stock_issued_after_applicable_date"], "taxable_years_beginning_after": 2026, "base_year": 2025, "rounding_multiple": rounding},
    }
    after = "2025-08-01"
    items = [
        code.cite("subsection (a)(1)", f"{base_percent} percent", "percent", f"shall not include {base_percent} percent of any gain from the sale or exchange of qualified small business stock held for more than {base_years} years"),
        code.cite("subsection (a)(4) heading", f"{percent_2010} percent", "percent", f"{percent_2010} percent exclusion for stock acquired during certain periods in 2010 and thereafter"),
        code.cite("subsection (b)(1)(B)", f"{multiple} times", "integer", f"{multiple} times the aggregate adjusted bases of qualified small business stock issued by such corporation"),
        code.cite("References in Text notes", "Feb. 17, 2009", "date", "which was approved Feb. 17, 2009"),
        code.cite("References in Text notes", "Sept. 27, 2010", "date", "which was approved Sept. 27, 2010"),
        code.cite("References in Text notes", "Aug. 10, 1993", "date", "which was approved Aug. 10, 1993"),
        code.cite("subsection (a)(3)(A)", f"{percent_2009} percent", "percent", "(A) paragraph (1) shall be applied by substituting"),
        code.cite("subsection (d)(1)(A)", f"${old_assets:,}", "currency:USD", f"and before the issuance did not exceed ${old_assets:,},"),
        plaw.cite("section 70431(a)(2), new section 1202(a)(5) table", f"{schedule[0]['percent']}%", "percent", f"{schedule[0]['years_held']} years"),
        plaw.cite("section 70431(a)(2), new section 1202(a)(5) table", f"{schedule[1]['percent']}%", "percent", f"{schedule[1]['years_held']} years"),
        plaw.cite("section 70431(a)(2), new section 1202(a)(5) table", f"{schedule[2]['percent']}%", "percent", "5 years or more"),
        plaw.cite("section 70431(b)(2), new section 1202(b)(5)(A)", f"${rounding:,}", "currency:USD", f"such increase shall be rounded to the nearest multiple of ${rounding:,}."),
        plaw.cite("section 70431(a)(1), new section 1202(a)(1)(B)", "at least 3 years", "text", "qualified small business stock acquired after the applicable date and held for at least 3 years"),
        plaw.cite("section 70431(b)(2), new section 1202(b)(4)(A)", f"${old_limit:,}", "currency:USD", f"if such stock was acquired by the taxpayer on or before the applicable date, ${old_limit:,}, reduced by the aggregate amount"),
        plaw.cite("section 70431(b)(2), new section 1202(b)(4)(B)", f"${new_limit:,}", "currency:USD", f"if such stock was acquired by the taxpayer after the applicable date, ${new_limit:,}, reduced by the sum of"),
        plaw.cite("section 70431(c)(2), inflation adjustment of the gross assets limit", f"${new_assets:,}", "currency:USD", f"In the case of any taxable year beginning after 2026, the ${new_assets:,} amounts in paragraphs (1)(A) and (1)(B)"),
        plaw.cite("approval date", "July 4, 2025", "date", 'approvedDate date="2025-07-04"'),
    ]
    vectors = [
        vector({"acquired": after, "sold": "2028-08-01"}, schedule[0]["percent"], note="new section 1202(a)(5): 3 years held"),
        vector({"acquired": after, "sold": "2029-08-01"}, schedule[1]["percent"], note="new section 1202(a)(5): 4 years held"),
        vector({"acquired": after, "sold": "2030-08-01"}, schedule[2]["percent"], note="new section 1202(a)(5): 5 years or more"),
        vector({"acquired": "2015-01-15", "sold": "2020-01-16"}, percent_2010, note="section 1202(a)(4): acquired after the 2010 Act, held more than 5 years"),
        vector({"acquired": "2009-06-01", "sold": "2015-06-02"}, percent_2009, note="section 1202(a)(3)"),
        vector({"acquired": "2005-03-01", "sold": "2012-03-02"}, base_percent, note="section 1202(a)(1)"),
        vector({"acquired": after, "sold": "2028-07-31"}, 0, "derived", "one day short of 3 years"),
        vector({"acquired": "2015-01-15", "sold": "2020-01-15"}, 0, "derived", "exactly 5 years is not more than 5 years"),
        vector({"acquired": "2026-01-02", "sold": "2031-01-02", "gain": 20000000, "adjusted_basis": 1000000}, new_limit, "derived", "capped at the dollar limit, which exceeds 10 times basis"),
        vector({"acquired": "2026-01-02", "sold": "2031-01-02", "gain": 20000000, "adjusted_basis": 2500000}, 20000000, "derived", "10 times basis exceeds the gain"),
        vector({"acquired": "2026-01-02", "sold": "2030-01-02", "gain": 8000000, "adjusted_basis": 100000}, 6000000, "derived", "4 years held: 75% of the gain"),
        vector({"acquired": "2014-03-01", "sold": "2024-03-01", "gain": 12000000, "adjusted_basis": 500000, "prior_eligible_gain": 4000000}, 6000000, "derived", "dollar limit reduced by prior eligible gain from the same issuer"),
    ]
    return rule(
        "us-qsbs-section-1202-gain-exclusion",
        "US qualified small business stock gain exclusion (26 U.S.C. 1202) before and after Public Law 119-21: percentages, holding periods, caps",
        "tax",
        "US",
        "B",
        rra_1993,
        None,
        [*TAGS, "qsbs", "section-1202", "capital-gains", "exit", "obbba"],
        ["lbo-modelling", "valuation-demo", "tax-demo", "pe-portfolio-demo"],
        "us_qsbs_exclusion",
        parameters,
        vectors,
        items,
        [
            {"statistic": "dollar_limit[after_applicable_date]", "expected": new_limit, "tolerance": 0},
            {"statistic": "max_percent", "expected": schedule[-1]["percent"], "tolerance": 0},
        ],
        (
            "Section 1202 lets a non-corporate holder exclude part of the gain on stock of a qualified small business "
            "(a C corporation with aggregate gross assets within the limit when the stock is issued) acquired at original "
            "issue. Stock acquired on or before the applicable date (the date Public Law 119-21 was enacted) keeps the "
            "earlier regime: 50, 75 or 100 percent depending on the acquisition window, only if held for more than five "
            "years, with a per-issuer cap of the greater of the dollar limit (reduced by earlier eligible gain from the "
            "issuer) and ten times the adjusted basis of the stock sold. Stock acquired after that date qualifies after "
            "three years, with the exclusion stepping up by whole years held, a higher dollar limit and, for stock issued "
            "after that date, a higher gross assets limit; both new amounts are indexed for taxable years beginning after "
            "2026. The pre-enactment text is read from the 2024 edition of the Code and the changes from the public law "
            "itself, since no edition of the Code yet incorporates them. The rule does not model the empowerment-zone "
            "percentage, the AMT preference, the qualified trade or business tests, or the reduction of the post-enactment "
            "dollar limit for same-year gain on older stock of the same issuer. " + US_LICENSE_NOTE
        ),
        [
            {"parameter": "married_filing_separately_dollar_limit_on_or_before_applicable_date", "value": old_limit // 2, "method": "derived", "rationale": "Section 1202(b)(3)(A) substitutes $5,000,000 for the $10,000,000 amount for separate returns; recorded for reference."},
            {"parameter": "acquisition_periods", "value": "dates", "method": "derived", "rationale": "The windows are bounded by the enactment dates the Code's References in Text notes give for the 1993, 2009 and 2010 Acts and the approval date of Public Law 119-21."},
        ],
    )


def us_business_interest_limitation(plaw: Doc, rev_proc: Doc) -> dict:
    code = usc(26, "subtitleA-chap1-subchapB-partVI-sec163", "163", "Interest")
    gross_receipts = usc(26, "subtitleA-chap1-subchapE-partII-subpartA-sec448", "448", "Limitation on use of cash method of accounting")
    regs = get(OFR, f"26 CFR 1.163(j)-2, Deduction for business interest expense limited (eCFR XML, {ECFR_DATE})", f"{ECFR}/{ECFR_DATE}/title-26.xml?section=1.163(j)-2")
    ratio = int(code.find(r"\(B\) (\d+) percent of the adjusted taxable income of such taxpayer for such taxable year"))
    old_cutoff = us_date(code.find(r"\(v\) in the case of taxable years beginning before (\w+ \d+, \d{4}), any deduction allowable for depreciation"))
    start = us_date(code.find(r"13301\(c\).{0,120}?\[amending this section and sections 381 and 382 of this title\] shall apply to taxable years beginning after (\w+ \d+, \d{4})"))
    law = collapse(plaw_section(plaw, "70303"))
    restored_after = re.search(r"The amendments made by this section shall apply to taxable years beginning after (\w+ \d+, \d{4})\.", law).group(1)
    # "Taxable years beginning after December 31, YYYY" start on 1 January of the following year.
    restored = date(int(us_date(restored_after)[:4]) + 1, 1, 1).isoformat()
    first_year = date(int(start[:4]) + 1, 1, 1).isoformat()
    receipts_2026 = money(rev_proc.find(r"which precedes such taxable year does not exceed\s*(\$[\d,]+)\.\s+\.31", flags=re.DOTALL))
    base_receipts = money(gross_receipts.find(r"which precedes such taxable year does not exceed (\$[\d,]+)\."))
    parameters = {
        "currency": "USD",
        "ratio_percent": ratio,
        "base": "adjusted taxable income (section 163(j)(8))",
        "allowance_floor": None,
        "exemption_threshold": None,
        "gross_receipts_limit": receipts_2026,
        "gross_receipts_limit_tax_year": 2026,
        "gross_receipts_limit_statutory_base": base_receipts,
        "depreciation_addback": [
            {"from": first_year, "value": True},
            {"from": old_cutoff, "value": False},
            {"from": restored, "value": True},
        ],
        "carryforward": "disallowed business interest is carried forward indefinitely (section 163(j)(2))",
    }
    example_1 = {"tax_year_start": "2021-01-01", "earnings": 100, "interest_expense": 50, "floor_plan_interest": 10, "interest_income": 20}
    example_2 = {**example_1, "interest_expense": 80}
    items = [
        code.cite("subsection (j)(1)(B)", f"{ratio} percent", "percent", f"{ratio} percent of the adjusted taxable income of such taxpayer for such taxable year"),
        code.cite("subsection (j)(8)(A)(v)", "January 1, 2022", "date", "in the case of taxable years beginning before January 1, 2022, any deduction allowable for depreciation, amortization, or depletion"),
        code.cite("subsection (j)(3)", "section 448(c)", "text", "which meets the gross receipts test of section 448(c) for any taxable year, paragraph (1) shall not apply"),
        code.cite("Effective Date of 2017 Amendment note, Pub. L. 115-97 section 13301(c)", "December 31, 2017", "date", "[amending this section and sections 381 and 382 of this title] shall apply to taxable years beginning after December 31, 2017"),
        plaw.cite("section 70303(a) and (c)(1)", restored_after, "date", f"The amendments made by this section shall apply to taxable years beginning after {restored_after}."),
        plaw.cite("section 70303(a)", "163(j)(8)(A)(v)", "text", "163(j)(8)(A)(v)"),
        rev_proc.cite("page 23, section 4.30", f"${receipts_2026:,}", "currency:USD", f"which precedes such taxable year does not exceed ${receipts_2026:,}"),
        gross_receipts.cite("subsection (c)(1)", f"${base_receipts:,}", "currency:USD", f"which precedes such taxable year does not exceed ${base_receipts:,}", role="supporting"),
        regs.cite("paragraph (h)(1), Example 1", "$60x", "text", "X's section 163(j) limitation is $60x"),
        regs.cite("paragraph (h)(2), Example 2", "$20x", "text", "X may only deduct $60x of its business interest expense for the 2021 taxable year, and the remaining $20x"),
    ]
    vectors = [
        vector({**example_1, "output": "limit"}, 60, note="26 CFR 1.163(j)-2(h)(1), Example 1, amounts in units of x"),
        vector(example_1, 50, note="Example 1: business interest expense within the limitation is deductible in full"),
        vector(example_2, 60, note="26 CFR 1.163(j)-2(h)(2), Example 2"),
        vector({**example_2, "output": "disallowed"}, 20, note="Example 2: carried forward"),
        vector({"tax_year_start": "2023-01-01", "earnings": 70, "depreciation": 30, "interest_expense": 40}, 21, "derived", "2022 to 2024: no depreciation add-back, 30% of 70"),
        vector({"tax_year_start": "2026-01-01", "earnings": 70, "depreciation": 30, "interest_expense": 40}, 30, "derived", "from 2025: depreciation added back, 30% of 100"),
        vector({"tax_year_start": "2026-01-01", "earnings": 70, "depreciation": 30, "interest_expense": 40, "average_gross_receipts": receipts_2026}, 40, "derived", "small business exemption at the 2026 gross receipts limit"),
    ]
    return rule(
        "us-business-interest-limitation-section-163j",
        "US business interest limitation (26 U.S.C. 163(j)): 30% of adjusted taxable income, EBITDA add-back by year, 2026 small business test",
        "tax",
        "US",
        "B",
        first_year,
        None,
        [*TAGS, "interest-limitation", "section-163j", "leverage", "ebitda", "obbba"],
        ["lbo-modelling", "private-credit-demo", "tax-demo", "valuation-demo"],
        "interest_limitation",
        parameters,
        vectors,
        items,
        [{"statistic": "ratio_percent", "expected": ratio, "tolerance": 0}, {"statistic": "gross_receipts_limit", "expected": receipts_2026, "tolerance": 0}],
        (
            "Section 163(j) caps the deduction for business interest at the sum of business interest income, 30 percent "
            "of adjusted taxable income (ATI) and floor plan financing interest; the excess carries forward without time "
            "limit. ATI added back depreciation, amortisation and depletion (an EBITDA measure) for taxable years "
            "beginning before 2022 and, after Public Law 119-21 struck the time limit, again for taxable years beginning "
            "after 31 December 2024; for 2022 to 2024 it was an EBIT measure. Taxpayers other than tax shelters that meet "
            "the section 448(c) gross receipts test (average annual gross receipts for the three prior years not above "
            "the indexed amount, here the amount for taxable years beginning in 2026) are exempt. From 2026 the same Act "
            "also removes subpart F and GILTI inclusions from ATI (section 70342), which this rule does not model, nor "
            "does it model the partnership rules or the real property and farming elections. The worked examples are the "
            "Treasury regulation's, in units of x. " + US_LICENSE_NOTE
        ),
        [{"parameter": "depreciation_addback", "value": [first_year, old_cutoff, restored], "method": "derived", "rationale": "Step dates restate the statutory wording: taxable years beginning after December 31, 2017; before January 1, 2022; and after December 31, 2024 (Public Law 119-21 section 70303(c))."}],
    )


def us_bonus_depreciation(plaw: Doc) -> dict:
    code = usc(26, "subtitleA-chap1-subchapB-partVI-sec168", "168", "Accelerated cost recovery system")
    text = code.plain
    block_a = text[text.index("(6) Applicable percentage") : text.index("(B) Rule for property with longer production periods")]
    block_b = text[text.index("(B) Rule for property with longer production periods") : text.index("(C) Rule for plants bearing fruits and nuts")]
    pattern = r"placed in service after (\w+ \d+, \d{4}), and before (\w+ \d+, \d{4}), (\d+) percent"

    def windows(block: str) -> list[dict]:
        return [{"placed_in_service_after": us_date(a), "placed_in_service_before": us_date(b), "percent": int(p)} for a, b, p in re.findall(pattern, block)]

    general, longer = windows(block_a), windows(block_b)
    law = collapse(plaw_section(plaw, "70301"))
    acquired_after = re.search(r"shall apply to property acquired after (\w+ \d+, \d{4})\.", law).group(1)
    full = int(re.search(r"by striking “ the applicable percentage ” and inserting “ (\d+) percent ”", law).group(1))
    parameters = {
        "full_expensing_acquired_after": us_date(acquired_after),
        "full_expensing_percent": full,
        "phase_down": {"general": general, "longer_production_period": longer},
        "binding_contract_rule": "property is not treated as acquired after the date on which a written binding contract is entered into for its acquisition (Public Law 119-21 section 70301(c)(4))",
        "transitional_election": "for the first taxable year ending after January 19, 2025 a taxpayer may elect 40 percent (60 percent for longer production period property) instead of 100 percent",
    }
    items = [
        code.cite("subsection (k)(6)(A)(i)", "100 percent", "percent", "placed in service after September 27, 2017, and before January 1, 2023, 100 percent"),
        code.cite("subsection (k)(6)(A)(iii)", "60 percent", "percent", "placed in service after December 31, 2023, and before January 1, 2025, 60 percent"),
        code.cite("subsection (k)(6)(A)(iv)", "40 percent", "percent", "placed in service after December 31, 2024, and before January 1, 2026, 40 percent"),
        code.cite("subsection (k)(6)(A)(v)", "20 percent", "percent", "placed in service after December 31, 2025, and before January 1, 2027, 20 percent"),
        code.cite("subsection (k)(6)(B)(iv)", "40 percent", "percent", "placed in service after December 31, 2025, and before January 1, 2027, 40 percent"),
        plaw.cite("section 70301(c)(1)", acquired_after, "date", f"shall apply to property acquired after {acquired_after}."),
        plaw.cite("section 70301(b)(1)(A)", f"{full} percent", "percent", f"{full} percent"),
    ]
    vectors = [
        vector({"acquired": "2025-03-01", "placed_in_service": "2025-04-01"}, full, note="Public Law 119-21 section 70301: acquired after January 19, 2025"),
        vector({"acquired": "2024-06-01", "placed_in_service": "2024-07-01"}, 60, note="section 168(k)(6)(A)(iii)"),
        vector({"acquired": "2024-12-01", "placed_in_service": "2025-06-01"}, 40, note="section 168(k)(6)(A)(iv): acquired before the Act's effective date"),
        vector({"acquired": "2024-12-01", "placed_in_service": "2026-03-01"}, 20, note="section 168(k)(6)(A)(v)"),
        vector({"acquired": "2024-12-01", "placed_in_service": "2026-03-01", "longer_production_period": True}, 40, note="section 168(k)(6)(B)(iv)"),
        vector({"acquired": "2019-05-01", "placed_in_service": "2019-05-02"}, 100, note="section 168(k)(6)(A)(i)"),
        vector({"acquired": "2024-12-01", "placed_in_service": "2027-02-01"}, 0, "derived", "after the last phase-down window"),
        vector({"acquired": "2026-11-01", "placed_in_service": "2031-01-01"}, full, "derived", "full expensing has no end date"),
    ]
    return rule(
        "us-bonus-depreciation-section-168k",
        "US bonus depreciation percentage (26 U.S.C. 168(k)) by acquisition and placed-in-service date, with 100% restored by Public Law 119-21",
        "tax",
        "US",
        "B",
        general[0]["placed_in_service_after"],
        None,
        [*TAGS, "depreciation", "bonus-depreciation", "section-168k", "capex", "obbba"],
        ["lbo-modelling", "valuation-demo", "tax-demo", "financial-reporting"],
        "us_bonus_depreciation",
        parameters,
        vectors,
        items,
        [{"statistic": "count[general]", "expected": len(general), "tolerance": 0}, {"statistic": "full_expensing_percent", "expected": full, "tolerance": 0}],
        (
            "Section 168(k) allows a first-year deduction of a percentage of the adjusted basis of qualified property. "
            "The Tax Cuts and Jobs Act set the percentage at 100 for property placed in service after 27 September 2017 "
            "and phased it down by 20 points a year from 2023 (one year later for longer production period property). "
            "Public Law 119-21 replaced the applicable percentage with 100 percent and removed the phase-down for property "
            "acquired after 19 January 2025; property acquired on or before that date under a binding contract keeps the "
            "phase-down by placed-in-service date. The schedule is read from the 2024 edition of the Code and the change "
            "from the public law. Specified plants, the transitional election of a reduced percentage, elections out and "
            "the pre-2017 regime for property acquired before 28 September 2017 are outside the rule. " + US_LICENSE_NOTE
        ),
    )


def us_carried_interest_holding_period() -> dict:
    code = usc(26, "subtitleA-chap1-subchapO-partIV-sec1061", "1061", "Partnership interests held in connection with performance of services")
    years = int(code.find(r'by substituting "(\d) years" for "1 year"'))
    effective = us_date(code.find(r"13309\(c\).{0,200}?shall apply to taxable years beginning after (\w+ \d+, \d{4})"))
    rows = {
        "applicable_partnership_interest_holding_period": {"value": years, "unit": "years", "comparison": "more than", "section": "1061(a)", "description": "long-term capital gain on an applicable partnership interest is recharacterised as short-term unless the asset was held for more than this period"},
        "general_long_term_holding_period": {"value": 1, "unit": "years", "comparison": "more than", "section": "1222(3)", "description": "the general holding period for long-term capital gain that section 1061 replaces for these interests"},
    }
    items = [
        code.cite("subsection (a)(2)", f"{years} years", "integer", "computed by applying paragraphs (3) and (4) of sections"),
        code.cite("subsection (a)", "short-term capital gain", "text", "shall be treated as short-term capital gain, notwithstanding section 83 or any election in effect under section 83(b)"),
        code.cite("subsection (c)(4)(A)", "corporation", "text", "any interest in a partnership directly or indirectly held by a corporation"),
        code.cite("Effective Date note", "December 31, 2017", "date", "shall apply to taxable years beginning after December 31, 2017"),
    ]
    first_year = date(int(effective[:4]) + 1, 1, 1).isoformat()
    return rule(
        "us-carried-interest-section-1061-holding-period",
        "US carried interest three-year holding period for applicable partnership interests (26 U.S.C. 1061)",
        "tax",
        "US",
        "B",
        first_year,
        None,
        [*TAGS, "carried-interest", "section-1061", "capital-gains", "fund-manager"],
        ["fund-administration-demo", "tax-demo", "lbo-modelling"],
        "lookup_table",
        {"rows": rows, "applicable_trade_or_business": "raising or returning capital and investing in, disposing of or developing specified assets (securities, commodities, real estate held for rental or investment, cash, options or derivatives on them)"},
        [
            vector(lookup("applicable_partnership_interest_holding_period"), years),
            vector(lookup("general_long_term_holding_period"), 1, "derived", "section 1222 is cited by section 1061(a)(2) but not fetched"),
            vector("capital_interest_exception", False, "derived", "the exceptions are described in the notes, not as rows"),
        ],
        items,
        [{"statistic": "value[applicable_partnership_interest_holding_period,value]", "expected": years, "tolerance": 0}],
        (
            "Section 1061 recharacterises as short-term capital gain the part of a taxpayer's net long-term capital gain on "
            "an applicable partnership interest (a carried interest received for substantial services in a business of "
            "raising or returning capital and investing in specified assets) that would not be long-term if the holding "
            "period were more than three years instead of more than one. Interests held by a corporation and capital "
            "interests commensurate with capital contributed are excluded. The rule applies to taxable years beginning after "
            "31 December 2017 and was not changed by Public Law 119-21. " + US_LICENSE_NOTE
        ),
        [{"parameter": "rows.general_long_term_holding_period.value", "value": 1, "method": "derived", "rationale": "Section 1061(a)(2) substitutes 3 years for the 1 year in section 1222(3) and (4); the 1-year figure is taken from that substitution clause."}],
    )


def us_net_investment_income_tax() -> dict:
    code = usc(26, "subtitleA-chap2A-sec1411", "1411", "Imposition of tax")
    rate = float(code.find(r"a tax equal to ([\d.]+) percent of the lesser of"))
    joint = money(code.find(r"surviving spouse \(as defined in section 2\(a\)\), (\$[\d,]+),"))
    other = money(code.find(r"\(3\) in any other case, (\$[\d,]+)\."))
    effective = us_date(code.find(r"enacting this chapter and amending section 6654 of this title\] shall apply to taxable years beginning after (December 31, 2012)"))
    rows = {
        "rate": {"value": rate, "unit": "percent", "section": "1411(a)(1)"},
        "threshold_joint_return_or_surviving_spouse": {"value": joint, "unit": "USD", "section": "1411(b)(1)"},
        "threshold_married_filing_separately": {"value": joint // 2, "unit": "USD", "section": "1411(b)(2)", "rule": "one half of the joint-return amount"},
        "threshold_other": {"value": other, "unit": "USD", "section": "1411(b)(3)"},
    }
    items = [
        code.cite("subsection (a)(1)", f"{rate} percent", "percent", f"a tax equal to {rate} percent of the lesser of"),
        code.cite("subsection (b)(1)", f"${joint:,}", "currency:USD", f"or a surviving spouse (as defined in section 2(a)), ${joint:,},"),
        code.cite("subsection (b)(3)", f"${other:,}", "currency:USD", f"in any other case, ${other:,}."),
        code.cite("Effective Date note", "December 31, 2012", "date", "shall apply to taxable years beginning after December 31, 2012"),
    ]
    return rule(
        "us-net-investment-income-tax-section-1411",
        "US net investment income tax (26 U.S.C. 1411): 3.8% rate and modified adjusted gross income thresholds by filing status",
        "tax",
        "US",
        "B",
        date(int(effective[:4]) + 1, 1, 1).isoformat(),
        None,
        [*TAGS, "niit", "section-1411", "investment-income", "capital-gains"],
        ["tax-demo", "tax-filing-demo", "fund-administration-demo", "valuation-demo"],
        "lookup_table",
        {"currency": "USD", "indexed_for_inflation": False, "rows": rows},
        [
            vector(lookup("rate"), rate),
            vector(lookup("threshold_joint_return_or_surviving_spouse"), joint),
            vector(lookup("threshold_other"), other),
            vector(lookup("threshold_married_filing_separately"), joint // 2, "derived", "half of the joint amount"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": joint, "tolerance": 0}],
        (
            "Section 1411 imposes a tax on individuals equal to 3.8 percent of the lesser of net investment income and the "
            "excess of modified adjusted gross income over a threshold that depends on filing status. Net investment "
            "income covers interest, dividends, rents, royalties, passive trade or business income and net gains on "
            "property not held in an active trade or business, so it reaches most fund distributions and exit gains of "
            "passive investors. The thresholds are fixed in the statute and are not indexed for inflation. Estates and "
            "trusts use the start of the top bracket instead. " + US_LICENSE_NOTE
        ),
        [{"parameter": "rows.threshold_married_filing_separately.value", "value": joint // 2, "method": "derived", "rationale": "Section 1411(b)(2) states the threshold as one half of the joint-return amount."}],
    )


def us_qualified_business_income_deduction(plaw: Doc, rev_proc: Doc) -> dict:
    code = usc(26, "subtitleA-chap1-subchapB-partVI-sec199A", "199A", "Qualified business income")
    rate = int(code.find(r"\(A\) (\d+) percent of the taxpayer's qualified business income with respect to the qualified trade or business"))
    law = collapse(plaw_section(plaw, "70105"))
    phase_other, phase_joint = (money(x) for x in re.search(r"inserting “ (\$[\d,]+) \((\$[\d,]+) in the case of a joint return\) ”", law).groups())
    minimum = money(re.search(r"“\(B\) (\$[\d,]+)\. ”", law).group(1)) if re.search(r"“\(B\) (\$[\d,]+)\. ”", law) else money(re.search(r"\(B\) (\$[\d,]+)\.", law).group(1))
    minimum_qbi = money(re.search(r"is at least (\$[\d,]+)\.", law).group(1))
    table = re.search(r"Married Individuals Filing Joint Returns (\$[\d,]+)\s+(\$[\d,]+).*?Returns\s+(\$[\d,]+)\s+(\$[\d,]+).*?All Other Returns (\$[\d,]+)\s+(\$[\d,]+)", rev_proc.plain, re.DOTALL)
    joint_t, joint_end, mfs_t, mfs_end, other_t, other_end = (money(x) for x in table.groups())
    rows = {
        "deduction_rate": {"value": rate, "unit": "percent", "section": "199A(b)(2)(A)"},
        "threshold_joint": {"value": joint_t, "unit": "USD", "section": "199A(e)(2)", "tax_year": 2026},
        "phase_in_end_joint": {"value": joint_end, "unit": "USD", "section": "199A(b)(3)(B), (d)(3)(A)", "tax_year": 2026},
        "threshold_married_filing_separately": {"value": mfs_t, "unit": "USD", "section": "199A(e)(2)", "tax_year": 2026},
        "phase_in_end_married_filing_separately": {"value": mfs_end, "unit": "USD", "section": "199A(b)(3)(B), (d)(3)(A)", "tax_year": 2026},
        "threshold_other": {"value": other_t, "unit": "USD", "section": "199A(e)(2)", "tax_year": 2026},
        "phase_in_end_other": {"value": other_end, "unit": "USD", "section": "199A(b)(3)(B), (d)(3)(A)", "tax_year": 2026},
        "phase_in_range_joint": {"value": phase_joint, "unit": "USD", "section": "199A(b)(3)(B) as amended by Public Law 119-21"},
        "phase_in_range_other": {"value": phase_other, "unit": "USD", "section": "199A(b)(3)(B) as amended by Public Law 119-21"},
        "minimum_deduction": {"value": minimum, "unit": "USD", "section": "199A(i)(1)(B)", "indexed_after": 2026},
        "minimum_active_qbi_for_minimum_deduction": {"value": minimum_qbi, "unit": "USD", "section": "199A(i)(2)(A)", "indexed_after": 2026},
    }
    items = [
        code.cite("subsection (b)(2)(A)", f"{rate} percent", "percent", f"{rate} percent of the taxpayer's qualified business income with respect to the qualified trade or business"),
        plaw.cite("section 70105(a)(1)", f"${phase_joint:,}", "currency:USD", f"${phase_other:,} (${phase_joint:,} in the case of a joint return)"),
        plaw.cite("section 70105(b)(1), new section 199A(i)(2)(A)", f"${minimum_qbi:,}", "currency:USD", f"is at least ${minimum_qbi:,}."),
        plaw.cite("section 70105(c)", "December 31, 2025", "date", "The amendments made by this section shall apply to taxable years beginning after December 31, 2025."),
        rev_proc.cite("page 21, section 4.26", f"${joint_t:,}", "currency:USD", f"Married Individuals Filing Joint Returns ${joint_t:,}"),
        rev_proc.cite("page 21, section 4.26", f"${other_t:,}", "currency:USD", f"All Other Returns ${other_t:,}"),
        rev_proc.cite("page 7, section 2.12", f"${minimum}", "currency:USD", "amended § 199A(i) to add a minimum deduction of"),
    ]
    return rule(
        "us-qualified-business-income-deduction-section-199a-2026",
        "US qualified business income deduction (26 U.S.C. 199A) for taxable years beginning in 2026: 20% rate, thresholds and phase-in ranges",
        "tax",
        "US",
        "B",
        "2026-01-01",
        "2026-12-31",
        [*TAGS, "qbi", "section-199a", "pass-through", "obbba", "rev-proc-2025-32"],
        ["tax-demo", "tax-filing-demo", "lbo-modelling", "valuation-demo"],
        "lookup_table",
        {"currency": "USD", "tax_year": 2026, "rows": rows},
        [
            vector(lookup("deduction_rate"), rate),
            vector(lookup("threshold_joint"), joint_t),
            vector(lookup("phase_in_end_other"), other_end),
            vector(lookup("minimum_deduction"), minimum),
            vector("deduction_rate_2017", False, "derived", "not a row of this table"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[threshold_other,value]", "expected": other_t, "tolerance": 0}],
        (
            "Section 199A lets individuals and other non-corporate owners of pass-through businesses deduct 20 percent of "
            "qualified business income, subject above a taxable-income threshold to wage and capital limits and the "
            "exclusion of specified service businesses, phased in over a range above the threshold. Public Law 119-21 made "
            "the deduction permanent (it was to end after 2025), widened the phase-in ranges and added a minimum deduction "
            "for taxpayers with at least the stated amount of active qualified business income, effective for taxable "
            "years beginning after 2025. The 2026 thresholds and phase-in end points are those Rev. Proc. 2025-32 "
            "publishes; the phase-in end equals the threshold plus the range. " + US_LICENSE_NOTE
        ),
    )


# --------------------------------------------------------------------------- United States: fund regulation


def ecfr(title: int, section: str, heading: str) -> Doc:
    url = f"{ECFR}/{ECFR_DATE}/title-{title}.xml?section={section}"
    return get(OFR, f"{title} CFR {section}, {heading} (eCFR XML, {ECFR_DATE})", url)


def ecfr_version(title: int, section: str) -> tuple[str, dict]:
    """Date the section's current text took effect, from the eCFR versions endpoint, with its evidence item."""
    url = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?section={section}&issue_date%5Blte%5D={ECFR_DATE}"
    doc = get(OFR, f"eCFR versions of {title} CFR {section} (JSON)", url)
    day = max(v["date"] for v in json.loads(doc.raw)["content_versions"])
    return day, doc.cite("content_versions[*].date, latest", day, "date", f'"date":"{day}"', role="supporting")


def regulation_d_accredited_investor() -> dict:
    doc = ecfr(17, "230.501", "Definitions and terms used in Regulation D")
    since, version_item = ecfr_version(17, "230.501")
    text = collapse(doc.plain)

    def amount(pattern: str) -> int:
        match = re.search(pattern, text)
        if match is None:
            raise ValueError(f"pattern {pattern!r} not found in 17 CFR 230.501")
        return money(match.group(1))

    net_worth = amount(r"joint net worth with that person's spouse or spousal equivalent, exceeds (\$[\d,]+);")
    income = amount(r"individual income in excess of (\$[\d,]+) in each of the two most recent years")
    joint_income = amount(r"spousal equivalent in excess of (\$[\d,]+) in each of those years")
    entity_assets = amount(r"limited liability company, not formed for the specific purpose of acquiring the securities offered, with total assets in excess of (\$[\d,]+);")
    trust_assets = amount(r"\(7\) Any trust, with total assets in excess of (\$[\d,]+),")
    investments = amount(r"owning investments in excess of (\$[\d,]+);")
    family_office = amount(r"With assets under management in excess of (\$[\d,]+),")
    plan_assets = amount(r"if such plan has total assets in excess of (\$[\d,]+);")

    def row(paragraph: str, who: str, test: str, threshold: int | None) -> dict:
        return {"paragraph": paragraph, "investor": who, "test": test, "threshold_usd": threshold, "comparison": "exceeds" if threshold else None}

    rows = {
        "natural_person_net_worth": row("230.501(a)(5)", "natural person", "individual or joint (with spouse or spousal equivalent) net worth, excluding the primary residence and the debt it secures up to its value", net_worth),
        "natural_person_income": row("230.501(a)(6)", "natural person", "individual income in each of the two most recent years, with a reasonable expectation of the same in the current year", income),
        "natural_person_joint_income": row("230.501(a)(6)", "natural person", "joint income with spouse or spousal equivalent in each of the two most recent years, with the same expectation", joint_income),
        "professional_certification": row("230.501(a)(10)", "natural person", "holds in good standing a professional certification, designation or credential the Commission has designated", None),
        "knowledgeable_employee": row("230.501(a)(11)", "natural person", "knowledgeable employee of a private fund issuer relying on section 3(c)(1) or 3(c)(7)", None),
        "director_officer_general_partner": row("230.501(a)(4)", "natural person", "director, executive officer or general partner of the issuer or of its general partner", None),
        "entity_total_assets": row("230.501(a)(3)", "501(c)(3) organisation, corporation, business trust, partnership or LLC not formed to acquire the securities", "total assets", entity_assets),
        "trust_total_assets": row("230.501(a)(7)", "trust not formed to acquire the securities, directed by a sophisticated person", "total assets", trust_assets),
        "entity_investments": row("230.501(a)(9)", "entity of another type not formed to acquire the securities", "investments as defined in rule 2a51-1(b)", investments),
        "family_office_assets_under_management": row("230.501(a)(12)", "family office not formed to acquire the securities", "assets under management", family_office),
        "benefit_plan_total_assets": row("230.501(a)(1)", "state or ERISA employee benefit plan", "total assets (or a qualifying fiduciary or accredited self-directed decision makers)", plan_assets),
        "entity_all_owners_accredited": row("230.501(a)(8)", "entity", "all equity owners are accredited investors", None),
        "regulated_institution": row("230.501(a)(1)", "bank, broker-dealer, registered or exempt reporting adviser, insurance company, registered fund, BDC, SBIC or RBIC", "status", None),
    }
    items = [
        doc.cite("paragraph (a)(5)", f"${net_worth:,}", "currency:USD", f"joint net worth with that person's spouse or spousal equivalent, exceeds ${net_worth:,};"),
        doc.cite("paragraph (a)(5)(i)(A)", "primary residence", "text", "The person's primary residence shall not be included as an asset;"),
        doc.cite("paragraph (a)(6)", f"${income:,}", "currency:USD", f"had an individual income in excess of ${income:,} in each of the two most recent years"),
        doc.cite("paragraph (a)(6)", f"${joint_income:,}", "currency:USD", f"spouse or spousal equivalent in excess of ${joint_income:,} in each of those years"),
        doc.cite("paragraph (a)(3)", f"${entity_assets:,}", "currency:USD", f"not formed for the specific purpose of acquiring the securities offered, with total assets in excess of ${entity_assets:,};"),
        doc.cite("paragraph (a)(9)", f"${investments:,}", "currency:USD", f"owning investments in excess of ${investments:,};"),
        doc.cite("paragraph (a)(12)", f"${family_office:,}", "currency:USD", f"With assets under management in excess of ${family_office:,},"),
        doc.cite("paragraph (a)(11)", "knowledgeable employee", "text", "Any natural person who is a"),
        version_item,
    ]
    return rule(
        "us-regulation-d-accredited-investor-definition",
        "US Regulation D accredited investor categories and dollar thresholds (17 CFR 230.501(a))",
        "funds",
        "US",
        "A",
        since,
        None,
        [*FUND_TAGS, "accredited-investor", "regulation-d", "investor-eligibility"],
        ["fund-administration-demo", "kyb-onboarding", "kyc-onboarding"],
        "lookup_table",
        {"currency": "USD", "indexed_for_inflation": False, "rows": rows},
        [
            vector(lookup("natural_person_net_worth", "threshold_usd"), net_worth),
            vector(lookup("natural_person_income", "threshold_usd"), income),
            vector(lookup("natural_person_joint_income", "threshold_usd"), joint_income),
            vector(lookup("entity_investments", "threshold_usd"), investments),
            vector(lookup("knowledgeable_employee", "threshold_usd"), None),
            vector("sophisticated_non_accredited_purchaser", False, "derived", "not an accredited investor category"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[threshold_usd]", "expected": max(entity_assets, investments), "tolerance": 0}],
        (
            "The categories of accredited investor in Rule 501(a) of Regulation D, which private funds rely on to offer "
            "interests under Rule 506(b) or 506(c). Natural persons qualify by net worth (excluding the primary residence), "
            "by income in each of the last two years, by holding a designated professional certification, or as "
            "knowledgeable employees of the fund; entities qualify by total assets, investments or assets under "
            "management above the stated amount (each requiring that the entity was not formed to acquire the securities), "
            "by regulated status, or because all their equity owners are accredited. All thresholds are tests of "
            "'in excess of'. The amounts are not indexed. valid_from is the date the section's current text took effect "
            "according to the eCFR; the income and net worth tests are much older. The family client category of "
            "paragraph (a)(13) is omitted. "
            + US_LICENSE_NOTE
        ),
        [{"parameter": "valid_from", "value": since, "method": "derived", "rationale": "Latest content version date of the section in the eCFR versions endpoint, bounded by the pinned eCFR date."}],
    )


def regulation_d_rule_506() -> dict:
    rule_506 = ecfr(17, "230.506", "Exemption for limited offers and sales without regard to dollar amount of offering")
    rule_501 = ecfr(17, "230.501", "Definitions and terms used in Regulation D")
    since, version_item = ecfr_version(17, "230.506")
    purchasers = int(rule_506.find(r"there are no more than, (\d+) purchasers of securities from the issuer"))
    days = int(rule_506.find(r"in any (\d+)-calendar-day period"))
    rows = {
        "rule_506b_max_non_accredited_purchasers": {"value": purchasers, "unit": "purchasers", "paragraph": "230.506(b)(2)(i)", "description": "purchasers counted under 230.501(e), which excludes accredited investors"},
        "rule_506b_purchaser_count_period_days": {"value": days, "unit": "calendar days", "paragraph": "230.506(b)(2)(i)"},
        "rule_506b_non_accredited_sophistication_required": {"value": True, "unit": "boolean", "paragraph": "230.506(b)(2)(ii)"},
        "rule_506c_all_purchasers_accredited": {"value": True, "unit": "boolean", "paragraph": "230.506(c)(2)(i)"},
        "rule_506c_reasonable_steps_to_verify": {"value": True, "unit": "boolean", "paragraph": "230.506(c)(2)(ii)"},
    }
    items = [
        rule_506.cite("paragraph (b)(2)(i)", str(purchasers), "count", f"that there are no more than, {purchasers} purchasers of securities from the issuer in offerings under this section in any {days}-calendar-day period"),
        rule_506.cite("paragraph (c)(2)(i)", "accredited investors", "text", "All purchasers of securities sold in any offering under paragraph (c) of this section are accredited investors."),
        rule_501.cite("paragraph (e)(1)(iv)", "Any accredited investor", "text", "(iv) Any accredited investor."),
        version_item,
    ]
    return rule(
        "us-regulation-d-rule-506-purchaser-limits",
        "US Regulation D Rule 506(b) and 506(c) purchaser conditions: 35 non-accredited purchasers per 90 days, accredited-only 506(c)",
        "funds",
        "US",
        "A",
        since,
        None,
        [*FUND_TAGS, "regulation-d", "rule-506", "private-placement"],
        ["fund-administration-demo", "kyb-onboarding", "deal-sourcing-demo"],
        "lookup_table",
        {"rows": rows},
        [
            vector(lookup("rule_506b_max_non_accredited_purchasers"), purchasers),
            vector(lookup("rule_506b_purchaser_count_period_days"), days),
            vector(lookup("rule_506c_all_purchasers_accredited"), True),
            vector("rule_504_offering_limit", False, "derived", "Rule 504 is not part of this table"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        (
            "Rule 506 is the safe harbour most private funds use to offer interests without registration. Under 506(b) "
            "there may be no more than 35 purchasers in any 90-calendar-day period, counted under Rule 501(e), which "
            "excludes accredited investors and certain relatives and controlled entities, so the limit in practice applies "
            "to non-accredited purchasers, each of whom must be sophisticated (alone or with a purchaser representative); "
            "general solicitation is not permitted. Under 506(c) general solicitation is allowed but every purchaser must "
            "be an accredited investor and the issuer must take reasonable steps to verify that status. valid_from is the "
            "date the section's current text took effect according to the eCFR. "
            + US_LICENSE_NOTE
        ),
        [{"parameter": "valid_from", "value": since, "method": "derived", "rationale": "Latest content version date of the section in the eCFR versions endpoint, bounded by the pinned eCFR date."}],
    )


def investment_company_act_exclusions() -> dict:
    definitions = usc(15, "chap2D-subchapI-sec80a-2", "80a-2", "Definitions; applicability; rulemaking considerations")
    exclusions = usc(15, "chap2D-subchapI-sec80a-3", "80a-3", "Definition of investment company")
    venture = ecfr(17, "270.3c-7", "Inflation-adjusted definition of qualifying venture capital fund")
    since, version_item = ecfr_version(17, "270.3c-7")
    owners = re.search(r"beneficially owned by not more than (\w+) hundred persons \(or, in the case of a qualifying venture capital fund, (\d+) persons\)", exclusions.plain)
    max_owners = {"one": 100}[owners.group(1)]
    max_owners_vc = int(owners.group(2))
    look_through = int(exclusions.find(r"if the company owns (\d+) per centum or more of the outstanding voting securities of the issuer"))
    statutory_vc_cap = money(exclusions.find(r"a venture capital fund that has not more than (\$[\d,]+) in aggregate capital contributions"))
    adjusted_vc_cap = money(venture.find(r"has not more than (\$[\d,]+) in aggregate capital contributions and uncalled committed capital"))
    qp_person = money(definitions.find(r"who owns not less than (\$[\d,]+) in investments, as defined by the Commission;"))
    qp_family = money(definitions.find(r"\(ii\) any company that owns not less than (\$[\d,]+) in investments and that is owned directly or indirectly"))
    qp_institution = money(definitions.find(r"in the aggregate owns and invests on a discretionary basis, not less than (\$[\d,]+) in investments\."))
    rows = {
        "section_3c1_max_beneficial_owners": {"value": max_owners, "unit": "persons", "section": "80a-3(c)(1)"},
        "section_3c1_max_beneficial_owners_qualifying_venture_capital_fund": {"value": max_owners_vc, "unit": "persons", "section": "80a-3(c)(1)"},
        "qualifying_venture_capital_fund_max_capital": {"value": adjusted_vc_cap, "unit": "USD", "section": "80a-3(c)(1)(C)(i); 17 CFR 270.3c-7(a)", "statutory_amount": statutory_vc_cap, "description": "aggregate capital contributions and uncalled committed capital"},
        "section_3c1_look_through_voting_percent": {"value": look_through, "unit": "percent", "section": "80a-3(c)(1)(A)", "description": "an investing fund owning this share or more of the voting securities is counted through to its own holders"},
        "section_3c7_owners": {"value": "qualified purchasers only", "unit": "text", "section": "80a-3(c)(7)(A)"},
        "qualified_purchaser_natural_person_investments": {"value": qp_person, "unit": "USD", "section": "80a-2(a)(51)(A)(i)", "comparison": "not less than"},
        "qualified_purchaser_family_company_investments": {"value": qp_family, "unit": "USD", "section": "80a-2(a)(51)(A)(ii)", "comparison": "not less than"},
        "qualified_purchaser_discretionary_investor_investments": {"value": qp_institution, "unit": "USD", "section": "80a-2(a)(51)(A)(iv)", "comparison": "not less than"},
    }
    items = [
        exclusions.cite("subsection (c)(1)", "250 persons", "count", "beneficially owned by not more than one hundred persons (or, in the case of a qualifying venture capital fund, 250 persons)"),
        exclusions.cite("subsection (c)(1)(A)", f"{look_through} per centum", "percent", f"if the company owns {look_through} per centum or more of the outstanding voting securities of the issuer"),
        exclusions.cite("subsection (c)(1)(C)(i)", f"${statutory_vc_cap:,}", "currency:USD", f"a venture capital fund that has not more than ${statutory_vc_cap:,} in aggregate capital contributions and uncalled committed", role="supporting"),
        exclusions.cite("subsection (c)(7)(A)", "qualified purchasers", "text", "the outstanding securities of which are owned exclusively by persons who, at the time of acquisition of such securities, are qualified purchasers"),
        venture.cite("paragraph (a)", f"${adjusted_vc_cap:,}", "currency:USD", f"that has not more than ${adjusted_vc_cap:,} in aggregate capital contributions and uncalled committed capital"),
        version_item,
        definitions.cite("paragraph (51)(A)(i)", f"${qp_person:,}", "currency:USD", f"who owns not less than ${qp_person:,} in investments, as defined by the Commission;"),
        definitions.cite("paragraph (51)(A)(ii)", f"${qp_family:,}", "currency:USD", f"(ii) any company that owns not less than ${qp_family:,} in investments and that is owned directly or indirectly"),
        definitions.cite("paragraph (51)(A)(iv)", f"${qp_institution:,}", "currency:USD", f"in the aggregate owns and invests on a discretionary basis, not less than ${qp_institution:,} in investments."),
    ]
    return rule(
        "us-investment-company-act-private-fund-exclusions",
        "US Investment Company Act private fund exclusions: 3(c)(1) owner limits, qualifying venture fund cap, 3(c)(7) qualified purchaser thresholds",
        "funds",
        "US",
        "B",
        since,
        None,
        [*FUND_TAGS, "investment-company-act", "section-3c1", "section-3c7", "qualified-purchaser", "investor-eligibility"],
        ["fund-administration-demo", "kyb-onboarding", "kyc-onboarding"],
        "lookup_table",
        {"currency": "USD", "rows": rows},
        [
            vector(lookup("section_3c1_max_beneficial_owners"), max_owners),
            vector(lookup("section_3c1_max_beneficial_owners_qualifying_venture_capital_fund"), max_owners_vc),
            vector(lookup("qualifying_venture_capital_fund_max_capital"), adjusted_vc_cap),
            vector(lookup("qualified_purchaser_natural_person_investments"), qp_person),
            vector(lookup("qualified_purchaser_discretionary_investor_investments"), qp_institution),
            vector("section_3c5_mortgage_banker", False, "derived", "other exclusions are not part of this table"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[qualified_purchaser_family_company_investments,value]", "expected": qp_family, "tolerance": 0}],
        (
            "The two exclusions from the definition of investment company that private equity and venture funds rely on. "
            "Section 3(c)(1) covers an issuer not making a public offering whose securities are beneficially owned by no "
            "more than 100 persons, or 250 for a qualifying venture capital fund, whose aggregate capital contributions and "
            "uncalled committed capital may not exceed a statutory amount the SEC indexes every five years (17 CFR "
            "270.3c-7 sets the current figure; valid_from is the date that rule's current text took effect). An investing "
            "company holding the stated share of the voting securities that is itself a private fund is looked through. "
            "Section 3(c)(7) covers an issuer owned exclusively by qualified purchasers: natural persons and family "
            "companies owning the lower investments amount, and persons investing at least the higher amount on a "
            "discretionary basis. " + US_LICENSE_NOTE
        ),
        [{"parameter": "rows.section_3c1_max_beneficial_owners.value", "value": max_owners, "method": "derived", "rationale": "The statute writes the number in words ('one hundred persons'); the builder converts it."}],
    )


def qualified_client_thresholds() -> dict:
    rule_text = ecfr(17, "275.205-3", "Exemption from the compensation prohibition of section 205(a)(1) for investment advisers")
    order_url = f"{GOVINFO}/FR-2026-05-01/html/2026-08480.htm"
    order = get(SEC_FR, "Order Approving Adjustment for Inflation of the Dollar Amount Tests in Rule 205-3, 91 FR 23520 (May 1, 2026), HTML", order_url)
    text = collapse(order.plain)
    aum_old, aum_new = (money(x) for x in re.search(r"assets-under- management test would increase from (\$[\d,]+) to (\$[\d,]+)", text).groups())
    nw_old, nw_new = (money(x) for x in re.search(r"net worth test would increase from (\$[\d,]+) to (\$[\d,]+)", text).groups())
    effective_text = re.search(r"This Order is effective as of (\w+ \d+, \d{4})\.", text).group(1)
    effective = us_date(effective_text)
    previous_effective = us_date(re.search(r"The 2021 Order was effective as of (\w+ \d+, \d{4})\.", text).group(1))
    rows = {
        "assets_under_management_test": {"value": aum_new, "unit": "USD", "comparison": "at least", "paragraph": "275.205-3(d)(1)(i)", "effective": effective, "previous_value": aum_old, "previous_effective": previous_effective},
        "net_worth_test": {"value": nw_new, "unit": "USD", "comparison": "more than", "paragraph": "275.205-3(d)(1)(ii)(A)", "effective": effective, "previous_value": nw_old, "previous_effective": previous_effective, "excludes": "primary residence and the debt it secures up to its value"},
        "employee_participation_months": {"value": int(rule_text.find(r"for at least (\d+) months")), "unit": "months", "paragraph": "275.205-3(d)(1)(iii)(B)"},
    }
    items = [
        order.cite("section IV, first ordering paragraph", f"${aum_new:,}", "currency:USD", f"entering into the contract has at least ${aum_new:,} under the management"),
        order.cite("section IV, second ordering paragraph", f"${nw_new:,}", "currency:USD", f"with assets held jointly with a spouse) of more than ${nw_new:,}."),
        order.cite("section II", f"${aum_old:,}", "currency:USD", f"test would increase from ${aum_old:,} to ${aum_new:,}"),
        order.cite("section II", f"${nw_old:,}", "currency:USD", f"net worth test would increase from ${nw_old:,} to ${nw_new:,}"),
        order.cite("section III", effective_text, "date", f"This Order is effective as of {effective_text}."),
        order.cite("footnote 9", "August 16, 2021", "date", "The 2021 Order was effective as of August 16,"),
        rule_text.cite("paragraph (e)", "$100,000", "currency:USD", "rounding the product to the nearest multiple of $100,000", role="supporting"),
        rule_text.cite("paragraph (d)(1)(i)", "most recent order", "text", "at least the applicable dollar amount specified in the most recent order"),
    ]
    return rule(
        "us-qualified-client-thresholds",
        "US qualified client thresholds for adviser performance fees (17 CFR 275.205-3) as adjusted by the SEC order effective 29 June 2026",
        "funds",
        "US",
        "B",
        effective,
        None,
        [*FUND_TAGS, "qualified-client", "performance-fee", "carried-interest", "investor-eligibility"],
        ["fund-administration-demo", "kyb-onboarding", "kyc-onboarding"],
        "lookup_table",
        {"currency": "USD", "rows": rows, "next_adjustment": "approximately every five years by Commission order, indexed to the PCE price index and rounded to the nearest $100,000"},
        [
            vector(lookup("assets_under_management_test"), aum_new),
            vector(lookup("net_worth_test"), nw_new),
            vector(lookup("net_worth_test", "previous_value"), nw_old),
            vector("qualified_purchaser", False, "derived", "a qualified purchaser is a qualified client, but not a row of this table"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[assets_under_management_test,value]", "expected": aum_new, "tolerance": 0}],
        (
            "A registered investment adviser may charge a performance fee (such as carried interest from a 3(c)(1) fund) "
            "only to qualified clients: clients with at least the assets-under-management amount with the adviser "
            "immediately after contracting, with net worth above the net-worth amount (excluding the primary residence), "
            "qualified purchasers, or certain officers and knowledgeable employees of the adviser. Rule 205-3 sets the "
            "amounts by reference to the most recent SEC inflation order; the order published on 1 May 2026 raised them "
            "with effect from 29 June 2026 and does not apply retroactively to existing contracts. The previous amounts "
            "and the date they took effect are kept for contracts entered into before then. " + US_LICENSE_NOTE
        ),
    )


def private_fund_adviser_thresholds() -> dict:
    exemption = ecfr(17, "275.203(m)-1", "Private fund adviser exemption")
    form_pf = ecfr(17, "275.204(b)-1", "Reporting by investment advisers to private funds")
    exemption_since, exemption_version = ecfr_version(17, "275.203(m)-1")
    form_pf_since, form_pf_version = ecfr_version(17, "275.204(b)-1")
    exempt_limit = exemption.find(r"\(2\) Manages private fund assets of less than \$(\d+) million\.")
    form_pf_floor = form_pf.find(r"you managed private fund assets of at least \$(\d+) million")
    rows = {
        "private_fund_adviser_exemption_us": {"value": int(exempt_limit) * 1_000_000, "unit": "USD", "comparison": "less than", "measure": "private fund assets (regulatory assets under management of qualifying private funds), calculated annually", "paragraph": "275.203(m)-1(a)", "effective": exemption_since},
        "private_fund_adviser_exemption_non_us": {"value": int(exempt_limit) * 1_000_000, "unit": "USD", "comparison": "less than", "measure": "private fund assets managed at a place of business in the United States", "paragraph": "275.203(m)-1(b)", "effective": exemption_since},
        "form_pf_filing_threshold": {"value": int(form_pf_floor) * 1_000_000, "unit": "USD", "comparison": "at least", "measure": "private fund assets at the end of the most recently completed fiscal year, for registered advisers", "paragraph": "275.204(b)-1(a)", "effective": form_pf_since},
    }
    items = [
        exemption.cite("paragraph (a)(2)", f"${exempt_limit} million", "text", f"Manages private fund assets of less than ${exempt_limit} million."),
        exemption.cite("paragraph (b)(2)", f"${exempt_limit} million", "text", f"solely attributable to private fund assets, the total value of which is less than ${exempt_limit} million."),
        form_pf.cite("paragraph (a)", f"${form_pf_floor} million", "text", f"you managed private fund assets of at least ${form_pf_floor} million, you must complete and file a report on Form PF"),
        exemption_version,
        form_pf_version,
    ]
    return rule(
        "us-private-fund-adviser-exemption-and-form-pf-thresholds",
        "US private fund adviser registration exemption (under $150 million) and Form PF filing threshold (17 CFR 275.203(m)-1, 275.204(b)-1)",
        "funds",
        "US",
        "A",
        max(exemption_since, form_pf_since),
        None,
        [*FUND_TAGS, "investment-advisers-act", "adviser-registration", "form-pf", "aum-threshold"],
        ["fund-administration-demo", "kyb-onboarding", "pe-portfolio-demo"],
        "lookup_table",
        {"currency": "USD", "rows": rows},
        [
            vector(lookup("private_fund_adviser_exemption_us"), int(exempt_limit) * 1_000_000),
            vector(lookup("form_pf_filing_threshold"), int(form_pf_floor) * 1_000_000),
            vector(lookup("form_pf_filing_threshold", "comparison"), "at least"),
            vector("large_private_equity_fund_adviser", False, "derived", "the Form PF large adviser thresholds are in the form's instructions, not the CFR text"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": int(exempt_limit) * 1_000_000, "tolerance": 0}],
        (
            "An investment adviser that advises only qualifying private funds and has less than the stated private fund "
            "assets in the United States is exempt from SEC registration (it files as an exempt reporting adviser). A "
            "registered adviser to private funds with at least the Form PF amount of private fund assets at its fiscal "
            "year end must file Form PF; the higher thresholds for large hedge fund, liquidity fund and private equity fund "
            "advisers are set in the form's instructions, which the CFR text does not reproduce, so they are left out. "
            "The rules state the amounts in millions of dollars; the table carries them in dollars. Each row's effective "
            "date is the date its section's current text took effect according to the eCFR. " + US_LICENSE_NOTE
        ),
        [{"parameter": "rows.*.value", "value": "USD", "method": "derived", "rationale": "The regulation states the thresholds as '$150 million'; the builder multiplies by one million."}],
    )


def venture_capital_fund_definition() -> dict:
    doc = ecfr(17, "275.203(l)-1", "Venture capital fund defined")
    since, version_item = ecfr_version(17, "275.203(l)-1")
    basket = int(doc.find(r"holds no more than (\d+) percent of the amount of the fund's aggregate capital contributions"))
    leverage = int(doc.find(r"in excess of (\d+) percent of the private fund's aggregate capital contributions"))
    days = int(doc.find(r"non-renewable term of no longer than (\d+) calendar days"))
    rows = {
        "non_qualifying_investment_basket_percent": {"value": basket, "unit": "percent", "of": "aggregate capital contributions and uncalled committed capital", "paragraph": "275.203(l)-1(a)(2)"},
        "max_leverage_percent": {"value": leverage, "unit": "percent", "of": "aggregate capital contributions and uncalled committed capital", "paragraph": "275.203(l)-1(a)(3)"},
        "max_borrowing_term_days": {"value": days, "unit": "calendar days", "paragraph": "275.203(l)-1(a)(3)", "description": "borrowing, guarantees and leverage must be non-renewable for no longer than this term (portfolio company guarantees up to the investment value excepted)"},
        "redemption_rights": {"value": False, "unit": "boolean", "paragraph": "275.203(l)-1(a)(4)", "description": "holders may not withdraw or redeem except in extraordinary circumstances"},
        "represents_venture_strategy": {"value": True, "unit": "boolean", "paragraph": "275.203(l)-1(a)(1)"},
    }
    items = [
        doc.cite("paragraph (a)(2)", f"{basket} percent", "percent", f"holds no more than {basket} percent of the amount of the fund's aggregate capital contributions and uncalled committed capital"),
        doc.cite("paragraph (a)(3)", f"{leverage} percent", "percent", f"in excess of {leverage} percent of the private fund's aggregate capital contributions and uncalled committed capital"),
        doc.cite("paragraph (a)(3)", f"{days} calendar days", "integer", f"is for a non-renewable term of no longer than {days} calendar days"),
        version_item,
    ]
    return rule(
        "us-venture-capital-fund-definition",
        "US venture capital fund definition for the adviser exemption (17 CFR 275.203(l)-1): 20% basket, 15% leverage, 120-day borrowing",
        "funds",
        "US",
        "A",
        since,
        None,
        [*FUND_TAGS, "venture-capital", "investment-advisers-act", "fund-definition"],
        ["fund-administration-demo", "kyb-onboarding", "deal-sourcing-demo"],
        "lookup_table",
        {"rows": rows},
        [
            vector(lookup("non_qualifying_investment_basket_percent"), basket),
            vector(lookup("max_leverage_percent"), leverage),
            vector(lookup("max_borrowing_term_days"), days),
            vector("management_fee_cap", False, "derived", "the definition sets no fee terms"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        (
            "An adviser that advises solely venture capital funds is exempt from SEC registration under section 203(l) of "
            "the Advisers Act. A private fund is a venture capital fund if it represents that it pursues a venture strategy, "
            "keeps assets other than qualifying investments (equity bought directly from qualifying portfolio companies) "
            "and short-term holdings within the stated basket of its capital contributions and uncalled commitments, does "
            "not borrow or guarantee beyond the stated share of that capital or for longer than the stated term, gives "
            "investors no redemption rights except in extraordinary circumstances, and is not a registered fund or BDC. "
            "The same definition fixes which funds can be qualifying venture capital funds under section 3(c)(1) of the "
            "Investment Company Act. " + US_LICENSE_NOTE
        ),
    )


def erisa_plan_asset_test() -> dict:
    doc = ecfr(29, "2510.3-101", "Definition of plan assets, plan investments")
    since, version_item = ecfr_version(29, "2510.3-101")
    threshold = int(doc.find(r"(\d+) percent or more of the value of any class of equity interests in the entity is held by benefit plan investors"))
    items = [
        doc.cite("paragraph (f)(1)", f"{threshold} percent", "percent", f"{threshold} percent or more of the value of any class of equity interests in the entity is held by benefit plan investors"),
        doc.cite("paragraph (j)(2)", "more than 25 percent", "text", "such investors hold more than 25 percent of the limited partnership interests in U"),
        doc.cite("paragraph (j)(3)", "10 percent", "percent", "benefit plan investors in the aggregate hold only 10 percent of the value of the limited partnership interests in U"),
        doc.cite("paragraph (j)(4)", "28.6%", "percent", "is approximately 28.6% ($1000/$3500)"),
        version_item,
    ]
    return rule(
        "us-erisa-plan-asset-significant-participation-test",
        "US ERISA plan-asset regulation: 25% significant participation test by benefit plan investors (29 CFR 2510.3-101(f))",
        "funds",
        "US",
        "A",
        since,
        None,
        [*FUND_TAGS, "erisa", "plan-assets", "benefit-plan-investors", "fund-formation"],
        ["fund-administration-demo", "kyb-onboarding"],
        "erisa_plan_asset_test",
        {"threshold_percent": threshold, "test": "benefit plan investors hold the threshold or more of the value of any class of equity interests, immediately after the most recent acquisition", "disregarded": "interests of persons with discretionary authority or control over the entity's assets or who give investment advice for a fee about them, and their affiliates (other than benefit plan investors)"},
        [
            vector({"benefit_plan_value": 30, "total_value": 100}, True, note="paragraph (j)(2): plan 15% plus governmental plan 15%"),
            vector({"benefit_plan_value": 10, "total_value": 100}, False, note="paragraph (j)(3)"),
            vector({"benefit_plan_value": 1000, "total_value": 10000, "disregarded_value": 6500, "output": "share"}, 28.6, note="paragraph (j)(4): $1000/$3500"),
            vector({"benefit_plan_value": 1000, "total_value": 10000, "disregarded_value": 6500}, True, note="paragraph (j)(4)"),
            vector({"benefit_plan_value": 25, "total_value": 100}, True, "derived", "exactly the threshold is significant ('25 percent or more')"),
            vector({"benefit_plan_value": 2499, "total_value": 10000}, False, "derived", "just below the threshold"),
        ],
        items,
        [{"statistic": "threshold_percent", "expected": threshold, "tolerance": 0}],
        (
            "When an employee benefit plan invests in a fund that is neither publicly offered, a registered investment "
            "company nor an operating company (including a venture capital or real estate operating company), the plan's "
            "assets include an undivided interest in the fund's underlying assets, making the manager an ERISA fiduciary, "
            "unless equity participation by benefit plan investors is not significant. Participation is significant when "
            "benefit plan investors hold 25 percent or more of the value of any class of equity interests immediately after "
            "the most recent acquisition, disregarding interests held by the manager, advisers for a fee and their "
            "affiliates. Private equity funds therefore cap benefit plan investors below the threshold or qualify as a "
            "venture capital operating company. The vectors are the regulation's own examples in paragraph (j). "
            "valid_from is the date the eCFR versions endpoint gives for the section's current text, which is the start "
            "of the eCFR's version history rather than the date the 25 percent test was adopted. "
            + US_LICENSE_NOTE
        ),
        [{"parameter": "valid_from", "value": since, "method": "derived", "rationale": "Latest content version date in the eCFR versions endpoint, which for this section is the start of the eCFR's history; the test itself is older."}],
    )


# --------------------------------------------------------------------------- United Kingdom


def legislation(path: str, label: str, form: str = "xml") -> Doc:
    """A provision on legislation.gov.uk, pinned to a point-in-time date; HTML where the XML lists unapplied effects."""
    url = f"{LEGISLATION}/{path}/{LEGISLATION_DATE}/data.{form}"
    return get(TNA, f"{label} (legislation.gov.uk {form.upper()}, version of {LEGISLATION_DATE})", url)


def govuk(path: str, title: str) -> Doc:
    return get(f"{HMRC} (GOV.UK)", title, f"https://www.gov.uk/api/content/{path}", OGL)


def uk_date(text: str) -> str:
    return datetime.strptime(text, "%d %B %Y").replace(tzinfo=UTC).date().isoformat()


def gb_business_asset_disposal_relief() -> dict:
    guide = govuk("business-asset-disposal-relief", "Business Asset Disposal Relief (GOV.UK content API, JSON)")
    paper = govuk(
        "government/publications/capital-gains-tax-reduction-in-the-business-asset-disposal-relief-lifetime-limit/capital-gains-tax-new-business-asset-disposal-relief-lifetime-limit",
        "Capital Gains Tax: new Business Asset Disposal Relief lifetime limit, Budget 2026 tax information and impact note (GOV.UK content API, JSON)",
    )
    text = guide.plain
    top, top_from = re.search(r"(\d+)% on all gains on qualifying assets disposed of from (\d+ \w+ \d{4})", text).groups()
    middle, middle_from = re.search(r"(\d+)% on all gains on qualifying assets disposed of between (\d+ \w+ \d{4}) and", text).groups()
    base, base_to = re.search(r"(\d+)% on all gains on qualifying assets disposed of on or before (\d+ \w+ \d{4})", text).groups()
    lifetime = re.search(r"You can claim a total of £(\d+) million in Business Asset Disposal Relief over your lifetime", text).group(1)
    reduced, reduced_from = re.search(r"reduces the lifetime limit for Business Asset Disposal Relief from £1 million to £([\d,]+) for qualifying disposals made on or after (\d+ \w+ \d{4})", collapse(paper.plain)).groups()
    steps = [{"from": uk_date(middle_from), "value": int(middle)}, {"from": uk_date(top_from), "value": int(top)}]
    items = [
        guide.cite("details.body, rate list", f"{top}%", "percent", f"{top}% on all gains on qualifying assets disposed of from {top_from}"),
        guide.cite("details.body, rate list", f"{middle}%", "percent", f"{middle}% on all gains on qualifying assets disposed of between {middle_from} and"),
        guide.cite("details.body, rate list", f"{base}%", "percent", f"{base}% on all gains on qualifying assets disposed of on or before {base_to}"),
        guide.cite("details.body, lifetime limit", f"£{lifetime} million", "currency:GBP", f"You can claim a total of £{lifetime} million in Business Asset Disposal Relief over your lifetime"),
        guide.cite("details.body, shares", "5%", "percent", "This means that you have at least 5% of both the:"),
        paper.cite("details.body, General description of the measure", f"£{reduced}", "currency:GBP", f"to £{reduced} for qualifying disposals made on or after {reduced_from}", role="supporting"),
    ]
    return rule(
        "gb-business-asset-disposal-relief",
        "UK Business Asset Disposal Relief: Capital Gains Tax rate by disposal date (10%, 14%, 18%) and lifetime limit",
        "tax",
        "GB",
        "A",
        steps[0]["from"],
        None,
        [*TAGS, "capital-gains-tax", "badr", "exit", "founder", "step-schedule"],
        ["lbo-modelling", "valuation-demo", "tax-demo", "pe-portfolio-demo"],
        "step_schedule",
        {
            "unit": "percent",
            "steps": steps,
            "rate_on_or_before_first_step": {"value": int(base), "applies_to": f"disposals on or before {uk_date(base_to)}"},
            "lifetime_limit_gbp": int(lifetime) * 1_000_000,
            "announced_lifetime_limit": {"value_gbp": money(reduced), "from": uk_date(reduced_from), "status": "announced at Budget 2026 for Finance Bill 2026-27; not yet enacted"},
            "personal_company_min_holding_percent": 5,
            "min_qualifying_period_years": 2,
        },
        [
            vector({"on": steps[0]["from"]}, int(middle)),
            vector({"on": steps[1]["from"]}, int(top)),
            vector({"on": "2026-11-26"}, int(top), "derived", "latest step still in force"),
            vector({"on": "2026-04-05"}, int(middle), "derived", "last day of the 2025-26 tax year"),
        ],
        items,
        [{"statistic": "count", "expected": len(steps), "tolerance": 0}, {"statistic": "max", "expected": int(top), "tolerance": 0}],
        (
            "Business Asset Disposal Relief (formerly Entrepreneurs' Relief) charges qualifying gains on disposals of all "
            "or part of a business, or of shares in a personal trading company in which the individual has held at least 5% "
            "of the shares and votes and been an officer or employee for two years, at a reduced Capital Gains Tax rate, up "
            "to a lifetime limit of qualifying gains. The rate was 10% for disposals on or before 5 April 2025 (kept as "
            "rate_on_or_before_first_step because the source gives no start date for it), 14% in 2025-26 and 18% from 6 "
            "April 2026. A reduction of the lifetime limit for disposals from 6 April 2027 was announced at Budget 2026 "
            "and is recorded as announced, not enacted. The guide and the tax information and impact note are published "
            "under the Open Government Licence."
        ),
        [
            {"parameter": "personal_company_min_holding_percent", "value": 5, "method": "derived", "rationale": "The guide states the 5% personal company test and the two-year period in prose; recorded as parameters for convenience."},
            {"parameter": "lifetime_limit_gbp", "value": int(lifetime) * 1_000_000, "method": "derived", "rationale": "The guide states the limit as '£1 million'; the builder converts it to pounds."},
        ],
        status="verified",
    )


def gb_carried_interest() -> dict:
    section = legislation("ukpga/2026/11/section/58", "Finance Act 2026, section 58, Carried interest")
    schedule = legislation("ukpga/2026/11/schedule/11", "Finance Act 2026, Schedule 11, Carried interest")
    cgt = legislation("ukpga/2025/8/section/12", "Finance Act 2025, section 12, Rate of CGT for carried interest gains")
    fraction = number(section.find(r"the sum of the non-qualifying profits of the trade and ([\d.]+)% of the qualifying profits of the trade"))
    commencement = section.find(r"have effect for the tax year (\d{4}-\d{2}) and subsequent tax years")
    table = collapse(schedule.plain)
    bands = []
    first = re.search(r"Less than (\d+) months (\d+)%", table)
    bands.append({"min_months": 0, "max_months": int(first.group(1)), "qualifying_percent": int(first.group(2))})
    for low, high, pct in re.findall(r"At least (\d+) months but less than (\d+) months (\d+)%", table):
        bands.append({"min_months": int(low), "max_months": int(high), "qualifying_percent": int(pct)})
    last = re.search(r"(\d+) months or more (\d+)%", table)
    bands.append({"min_months": int(last.group(1)), "max_months": None, "qualifying_percent": int(last.group(2))})
    old_rates = re.search(r"which provides for rates of (\d+)% or (\d+)% on carried interest gains", collapse(cgt.plain)).groups()
    new_rate = int(cgt.find(r"are charged to capital gains tax at a rate of (\d+)%"))
    cgt_from = cgt.find(r"have effect in relation to carried interest arising on or after (\d+ \w+ \d{4})")
    start_year = int(commencement[:4])
    items = [
        section.cite("section 58(2), new ITTOIA 2005 s. 23I(2)(b)", f"{fraction}%", "percent", f"the sum of the non-qualifying profits of the trade and {fraction}% of the qualifying profits of the trade"),
        section.cite("section 58(6)", commencement, "text", f"have effect for the tax year {commencement} and subsequent tax years"),
        schedule.cite("Part 1, new Sch. A1 para. 12(2)", "Less than 36 months", "text", "Less than 36 months"),
        schedule.cite("Part 1, new Sch. A1 para. 12(2)", "40 months or more", "text", "40 months or more"),
        cgt.cite("section 12(1)(c), new TCGA 1992 s. 1H(4B)", f"{new_rate}%", "percent", f"charged to capital gains tax at a rate of {new_rate}%"),
        cgt.cite("section 12(3)", cgt_from, "date", f"have effect in relation to carried interest arising on or after {cgt_from}"),
        cgt.cite("section 12(1)(a)", f"{old_rates[1]}%", "percent", f"which provides for rates of {old_rates[0]}% or {old_rates[1]}% on carried interest gains"),
    ]
    return rule(
        "gb-carried-interest-income-tax-regime",
        "UK carried interest regime from 2026-27 (ITTOIA 2005 s. 23I, Sch. A1): 72.5% of qualifying carry taxed as trading profits, holding-period bands",
        "tax",
        "GB",
        "A",
        date(start_year, 4, 6).isoformat(),
        None,
        [*TAGS, "carried-interest", "fund-manager", "income-tax", "capital-gains-tax"],
        ["fund-administration-demo", "tax-demo", "lbo-modelling"],
        "gb_carried_interest",
        {
            "currency": "GBP",
            "qualifying_fraction_percent": fraction,
            "holding_period_bands": bands,
            "first_tax_year": commencement,
            "capital_gains_tax_before_regime": {
                "rates_percent_to_2025_04_05": [int(r) for r in old_rates],
                "rate_percent_from": {"from": uk_date(cgt_from), "value": new_rate},
                "note": "carried interest gains were charged to CGT until the income tax regime took effect for 2026-27",
            },
        },
        [
            vector({"average_holding_months": 35}, bands[0]["qualifying_percent"], note="Sch. A1 para. 12(2): less than 36 months"),
            vector({"average_holding_months": 36}, bands[1]["qualifying_percent"], note="at least 36 but less than 37 months"),
            vector({"average_holding_months": 39.5}, bands[4]["qualifying_percent"], note="at least 39 but less than 40 months"),
            vector({"average_holding_months": 48}, bands[-1]["qualifying_percent"], note="40 months or more"),
            vector({"average_holding_months": 48, "carried_interest": 1000000}, 725000, "derived", "wholly qualifying: 72.5% taxed"),
            vector({"average_holding_months": 30, "carried_interest": 1000000}, 1000000, "derived", "wholly non-qualifying: taxed in full"),
            vector({"average_holding_months": 37, "carried_interest": 1000000, "permitted_deductions": 100000}, 801000, "derived", "40% qualifying of 900,000 net: 540,000 + 72.5% of 360,000"),
        ],
        items,
        [{"statistic": "count", "expected": len(bands), "tolerance": 0}, {"statistic": "qualifying_fraction_percent", "expected": fraction, "tolerance": 0}],
        (
            "From the 2026-27 tax year carried interest arising to an individual who performs investment management services "
            "is taxed as the profits of a deemed trade (income tax and Class 4 National Insurance) instead of as a capital "
            "gain. Qualifying carried interest enters the profits at 72.5% of its amount; the qualifying share of each sum "
            "depends on the investment scheme's average holding period, from none below 36 months rising by 20 points a "
            "month to all of it at 40 months or more. Before the regime, carried interest gains were charged to Capital "
            "Gains Tax at 18% or 28% and, for carried interest arising on or after 6 April 2025, at a single 32% rate. "
            "The rule does not model the exceptions treating carried interest as wholly qualifying, the territorial scope "
            "or the holding period averaging adjustments. " + UK_LICENSE_NOTE
        ),
    )


def gb_corporate_interest_restriction() -> dict:
    capacity = legislation("ukpga/2010/8/section/392", "Taxation (International and Other Provisions) Act 2010, section 392, interest capacity")
    fixed_ratio = legislation("ukpga/2010/8/section/397", "Taxation (International and Other Provisions) Act 2010, section 397, fixed ratio method")
    guidance = govuk("guidance/restriction-on-corporation-tax-relief-for-interest-deductions", "Restriction on Corporation Tax relief for interest deductions (GOV.UK content API, JSON)")
    ratio = int(fixed_ratio.find(r"(\d+)% of the aggregate tax-EBITDA of the group for the period"))
    commencement = legislation("ukpga/2017/32/schedule/5/paragraph/25", "Finance (No. 2) Act 2017, Schedule 5, paragraph 25, commencement of the corporate interest restriction")
    de_minimis = int(re.search(r"the de minimis amount.{0,40}?£(\d+) million", collapse(capacity.plain)).group(1))
    start = commencement.find(r"periods of account of worldwide groups that begin on or after (\d+ \w+ \d{4})\.")
    carry_years = int(guidance.find(r"carry forward unused interest allowance for up to (\d+) years"))
    parameters = {
        "currency": "GBP",
        "ratio_percent": ratio,
        "base": "aggregate tax-EBITDA of the worldwide group's UK members (fixed ratio method)",
        "allowance_floor": de_minimis * 1_000_000,
        "exemption_threshold": None,
        "gross_receipts_limit": None,
        "fixed_ratio_debt_cap": "the basic interest allowance is the lower of the ratio amount and the fixed ratio debt cap (s. 397(1)(b)); not modelled",
        "group_ratio_election": "a group ratio based on the group's net third-party interest to EBITDA may be elected instead (s. 398); not modelled",
        "unused_allowance_carry_forward_years": carry_years,
    }
    items = [
        fixed_ratio.cite("section 397(1)(a)", f"{ratio}%", "percent", f"{ratio}% of the aggregate tax-EBITDA of the group for the period"),
        capacity.cite("section 392(3)(a)", f"£{de_minimis} million", "currency:GBP", f"£{de_minimis} million"),
        capacity.cite("section 392(2)", "de minimis amount", "text", "the interest capacity of the worldwide group for the period is the de minimis amount"),
        guidance.cite("details.body", f"{carry_years} years", "integer", f"carry forward unused interest allowance for up to {carry_years} years"),
        commencement.cite("paragraph 25(1)", start, "date", f"periods of account of worldwide groups that begin on or after {start}."),
    ]
    vectors = [
        vector({"earnings": 10000000, "interest_expense": 4000000}, 3000000, "derived", "30% of tax-EBITDA exceeds the de minimis amount"),
        vector({"earnings": 1000000, "interest_expense": 2500000}, 2000000, "derived", "the de minimis amount is the floor of interest capacity"),
        vector({"earnings": 0, "interest_expense": 2000000}, 2000000, "source", "the de minimis amount stated in s. 392(3)(a) is deductible whatever the tax-EBITDA"),
        vector({"earnings": 1000000, "interest_expense": 1800000}, 1800000, "derived", "net interest below the de minimis amount is not restricted"),
        vector({"earnings": 10000000, "interest_expense": 4000000, "output": "disallowed"}, 1000000, "derived", "carried forward indefinitely"),
    ]
    return rule(
        "gb-corporate-interest-restriction",
        "UK Corporate Interest Restriction (TIOPA 2010 Part 10): 30% of tax-EBITDA fixed ratio, £2 million de minimis",
        "tax",
        "GB",
        "B",
        uk_date(start),
        None,
        [*TAGS, "interest-limitation", "corporate-interest-restriction", "leverage", "ebitda", "atad"],
        ["lbo-modelling", "private-credit-demo", "tax-demo", "valuation-demo"],
        "interest_limitation",
        parameters,
        vectors,
        items,
        [{"statistic": "ratio_percent", "expected": ratio, "tolerance": 0}, {"statistic": "allowance_floor", "expected": de_minimis * 1_000_000, "tolerance": 0}],
        (
            "The Corporate Interest Restriction limits a worldwide group's UK net tax-interest expense to its interest "
            "capacity: the interest allowance for the period (30% of the aggregate tax-EBITDA of its UK companies under "
            "the fixed ratio method, capped by the fixed ratio debt cap, or a group ratio if elected) plus unused "
            "allowance brought forward, but never less than the £2 million de minimis amount, pro-rated for periods other "
            "than a year. Disallowed interest is carried forward without time limit and unused allowance for five years. "
            "The rule models the fixed ratio method with the de minimis floor; the debt cap, group ratio and public "
            "infrastructure options are described but not computed. " + UK_LICENSE_NOTE
        ),
        [{"parameter": "allowance_floor", "value": de_minimis * 1_000_000, "method": "derived", "rationale": "Section 392(3) states the de minimis amount as '£2 million'; the builder converts it to pounds."}],
    )


def gb_substantial_shareholding_exemption() -> dict:
    doc = legislation("ukpga/1992/12/schedule/7AC", "Taxation of Chargeable Gains Act 1992, Schedule 7AC, exemptions for disposals by companies with substantial shareholding", "html")
    text = collapse(doc.plain)
    share = int(re.search(r"it holds not less than (\d+)% of the company’s ordinary share capital", text).group(1))
    lookback = re.search(r"throughout a twelve-month period beginning not more than (\w+) years before the day on which the disposal takes place", text).group(1)
    years = {"six": 6}[lookback]
    rows = {
        "minimum_ordinary_share_capital_percent": {"value": share, "unit": "percent", "paragraph": "Sch. 7AC para. 8(1)(a)"},
        "minimum_profits_entitlement_percent": {"value": share, "unit": "percent", "paragraph": "Sch. 7AC para. 8(1)(b)"},
        "minimum_assets_on_winding_up_percent": {"value": share, "unit": "percent", "paragraph": "Sch. 7AC para. 8(1)(c)"},
        "minimum_holding_period_months": {"value": 12, "unit": "months", "paragraph": "Sch. 7AC para. 7", "description": "held throughout a twelve-month period"},
        "holding_period_lookback_years": {"value": years, "unit": "years", "paragraph": "Sch. 7AC para. 7", "description": "the twelve-month period must begin not more than this many years before the disposal"},
    }
    items = [
        doc.cite("paragraph 8(1)(a)", f"{share}%", "percent", f"it holds not less than {share}% of the company’s ordinary share capital"),
        doc.cite("paragraph 7", "twelve-month period", "text", "throughout a twelve-month period beginning not more than"),
        doc.cite("paragraph 7", lookback, "text", "years before the day on which the disposal takes place"),
        doc.cite("paragraph 1(1)", "not a chargeable gain", "text", "is not a chargeable gain if the requirements of this Schedule are met"),
    ]
    return rule(
        "gb-substantial-shareholding-exemption",
        "UK substantial shareholding exemption for corporate share disposals (TCGA 1992 Sch. 7AC): 10% holding for 12 months in the last 6 years",
        "tax",
        "GB",
        "B",
        LEGISLATION_DATE,
        None,
        [*TAGS, "participation-exemption", "substantial-shareholding-exemption", "capital-gains", "exit", "holding-company"],
        ["lbo-modelling", "tax-demo", "valuation-demo", "pe-portfolio-demo"],
        "lookup_table",
        {"rows": rows, "investee_condition": "the company invested in must have been a qualifying (trading) company throughout the relevant period, except where the institutional investor rules apply"},
        [
            vector(lookup("minimum_ordinary_share_capital_percent"), share),
            vector(lookup("holding_period_lookback_years"), years),
            vector(lookup("minimum_holding_period_months"), 12, "derived", "twelve-month period, written in words"),
            vector("minimum_voting_rights_percent", False, "derived", "the schedule sets no separate voting-rights test"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        (
            "A gain (or loss) of a company on a disposal of shares in another company is exempt from corporation tax on "
            "chargeable gains if the investing company held a substantial shareholding (at least 10% of the ordinary share "
            "capital and entitlement to at least 10% of distributable profits and of assets on a winding up) throughout a "
            "twelve-month period beginning no more than six years before the disposal, and the company invested in meets "
            "the trading conditions. It is the UK participation exemption that makes share sales by UK holding companies "
            "tax-free at exit. The text is the version in force on the pinned point-in-time date, which is also used as "
            "valid_from because the schedule's provisions take effect on different dates; the HTML form is cited because "
            "the XML lists unapplied effects for the Act. " + UK_LICENSE_NOTE
        ),
        [
            {"parameter": "valid_from", "value": LEGISLATION_DATE, "method": "derived", "rationale": "Point-in-time date of the cited version; the schedule's paragraphs were inserted and amended at different dates."},
            {"parameter": "rows.minimum_holding_period_months.value", "value": 12, "method": "derived", "rationale": "Paragraph 7 writes 'twelve-month period'; paragraph 28 defines it as ending the day before the first anniversary of its start."},
        ],
    )


def gb_venture_capital_schemes() -> dict:
    eis_rate = legislation("ukpga/2007/3/section/158", "Income Tax Act 2007, section 158, form and amount of EIS relief", "html")
    seis_rate = legislation("ukpga/2007/3/section/257AB", "Income Tax Act 2007, section 257AB, form and amount of SEIS relief", "html")
    annual = legislation("ukpga/2007/3/section/173A", "Income Tax Act 2007, section 173A, maximum amount raised annually", "html")
    lifetime = legislation("ukpga/2007/3/section/173AA", "Income Tax Act 2007, section 173AA, maximum risk finance investments", "html")
    assets = legislation("ukpga/2007/3/section/186", "Income Tax Act 2007, section 186, gross assets requirement", "html")
    seis_assets = legislation("ukpga/2007/3/section/257DI", "Income Tax Act 2007, section 257DI, SEIS gross assets requirement", "html")

    eis = int(re.search(r"the EIS rate.{0,6} means (\d+)%", collapse(eis_rate.plain)).group(1))
    seis = int(re.search(r"the SEIS rate.{0,6} means (\d+)%", collapse(seis_rate.plain)).group(1))
    eis_limit = int(re.search(r"if the qualifying shares do not include any KIC shares: £(\d+) million", collapse(eis_rate.plain)).group(1)) * 1_000_000
    eis_kic_limit = int(re.search(r"is £1 million or more: £(\d+) million", collapse(eis_rate.plain)).group(1)) * 1_000_000
    seis_limit = money(re.search(r"\(b\) if less, (£[\d,]+)", collapse(seis_rate.plain)).group(1))
    annual_kic, annual_std = (int(x) * 1_000_000 for x in re.search(r"knowledge-intensive company \(see section 252A and subsection \(5A\)\) and— \(i\) not a specified Northern Ireland company, £(\d+) million; .*? is not a knowledge-intensive company and— \(i\) not a specified Northern Ireland company, £(\d+) million", collapse(annual.plain)).groups())
    life_kic, life_std = (int(x) * 1_000_000 for x in re.search(r"knowledge-intensive company \(see section 252A\) and— \(i\) not a specified Northern Ireland company, £(\d+) million; .*? is not a knowledge-intensive company and— \(i\) not a specified Northern Ireland company, £(\d+) million", collapse(lifetime.plain)).groups())
    before, after = (int(x) * 1_000_000 for x in re.search(r"must not exceed £(\d+) million immediately before the relevant share issue, and \(b\) must not exceed £(\d+) million immediately afterwards", collapse(assets.plain)).groups())
    seis_gross = money(re.search(r"the value of the company's assets must not exceed (£[\d,]+) immediately before", collapse(seis_assets.plain)).group(1))
    in_force_text = re.search(r"substituted \((\d+\.\d+\.\d{4})\) by Finance Act 2026", collapse(annual.plain)).group(1)
    in_force = datetime.strptime(in_force_text, "%d.%m.%Y").replace(tzinfo=UTC).date().isoformat()
    rows = {
        "eis_income_tax_relief_rate": {"value": eis, "unit": "percent", "section": "ITA 2007 s. 158(2A)"},
        "eis_investor_annual_limit": {"value": eis_limit, "unit": "GBP", "section": "ITA 2007 s. 158(2ZA)(a)"},
        "eis_investor_annual_limit_with_kic_shares": {"value": eis_kic_limit, "unit": "GBP", "section": "ITA 2007 s. 158(2ZA)(b)"},
        "seis_income_tax_relief_rate": {"value": seis, "unit": "percent", "section": "ITA 2007 s. 257AB(3)"},
        "seis_investor_annual_limit": {"value": seis_limit, "unit": "GBP", "section": "ITA 2007 s. 257AB(2)(b)"},
        "eis_company_annual_limit": {"value": annual_std, "unit": "GBP", "section": "ITA 2007 s. 173A(1)(b)(i)"},
        "eis_company_annual_limit_kic": {"value": annual_kic, "unit": "GBP", "section": "ITA 2007 s. 173A(1)(a)(i)"},
        "eis_company_lifetime_limit": {"value": life_std, "unit": "GBP", "section": "ITA 2007 s. 173AA(1)(b)(i)"},
        "eis_company_lifetime_limit_kic": {"value": life_kic, "unit": "GBP", "section": "ITA 2007 s. 173AA(1)(a)(i)"},
        "eis_gross_assets_before_issue": {"value": before, "unit": "GBP", "section": "ITA 2007 s. 186(A1)(a)"},
        "eis_gross_assets_after_issue": {"value": after, "unit": "GBP", "section": "ITA 2007 s. 186(A1)(b)"},
        "seis_gross_assets_before_issue": {"value": seis_gross, "unit": "GBP", "section": "ITA 2007 s. 257DI(1)"},
    }
    items = [
        eis_rate.cite("section 158(2A), the EIS rate", f"{eis}%", "percent", f"{eis}%"),
        eis_rate.cite("section 158(2ZA)(a)", f"£{eis_limit // 1_000_000} million", "currency:GBP", f"if the qualifying shares do not include any KIC shares: £{eis_limit // 1_000_000} million"),
        seis_rate.cite("section 257AB(3)", f"{seis}%", "percent", f"means {seis}%."),
        seis_rate.cite("section 257AB(2)(b)", f"£{seis_limit:,}", "currency:GBP", "in respect of which the individual is eligible for and claims SEIS relief, or"),
        annual.cite("section 173A(1)", f"£{annual_std // 1_000_000} million", "currency:GBP", f"£{annual_kic // 1_000_000} million;"),
        annual.cite("commentary to section 173A(1)", in_force_text, "date", f"substituted ({in_force_text}) by"),
        lifetime.cite("section 173AA(1)", f"£{life_std // 1_000_000} million", "currency:GBP", f"£{life_kic // 1_000_000} million;"),
        assets.cite("section 186(A1)", f"£{after // 1_000_000} million", "currency:GBP", f"must not exceed £{after // 1_000_000} million immediately afterwards"),
        seis_assets.cite("section 257DI(1)", f"£{seis_gross:,}", "currency:GBP", "immediately before the relevant shares are issued."),
    ]
    return rule(
        "gb-eis-seis-relief-rates-and-limits",
        "UK Enterprise Investment Scheme and Seed EIS: income tax relief rates, investor limits and company limits (ITA 2007) from 6 April 2026",
        "tax",
        "GB",
        "B",
        in_force,
        None,
        [*TAGS, "eis", "seis", "venture-capital", "investor-relief", "income-tax"],
        ["deal-sourcing-demo", "tax-demo", "fund-administration-demo", "pe-portfolio-demo"],
        "lookup_table",
        {"currency": "GBP", "rows": rows, "specified_northern_ireland_company": "lower company limits apply to specified Northern Ireland companies; not tabulated"},
        [
            vector(lookup("eis_income_tax_relief_rate"), eis),
            vector(lookup("seis_income_tax_relief_rate"), seis),
            vector(lookup("eis_company_annual_limit"), annual_std),
            vector(lookup("eis_company_lifetime_limit_kic"), life_kic),
            vector(lookup("eis_gross_assets_after_issue"), after),
            vector(lookup("seis_investor_annual_limit"), seis_limit),
            vector("vct_income_tax_relief_rate", False, "derived", "venture capital trusts are not covered"),
        ],
        items,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": life_kic, "tolerance": 0}],
        (
            "The Enterprise Investment Scheme gives individual investors an income tax reduction at the EIS rate on "
            "subscriptions for shares in qualifying unquoted trading companies up to an annual limit (higher where the "
            "excess is in knowledge-intensive companies); the Seed EIS gives a higher rate on a smaller annual amount. "
            "Issuing companies are limited in how much risk finance they can raise in any year and in their lifetime "
            "(higher for knowledge-intensive companies) and must be below gross asset ceilings before and after the "
            "issue. Finance Act 2026 raised the EIS company limits and gross asset ceilings with effect from 6 April 2026, "
            "the date the table takes as valid_from. Shares must be held for at least three years. The HTML form of each "
            "section is cited because the XML lists unapplied effects for the Act. " + UK_LICENSE_NOTE
        ),
        [{"parameter": "rows.*.value", "value": "GBP", "method": "derived", "rationale": "The Act states several limits as '£N million'; the builder converts them to pounds."}],
    )


# --------------------------------------------------------------------------- Netherlands


def nl_earnings_stripping() -> dict:
    url = "https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0002672/2026-01-01_0/xml/BWBR0002672_2026-01-01_0.xml"
    doc = get(KOOP, "Wet op de vennootschapsbelasting 1969, version valid from 1 January 2026 (BWB XML)", url)
    raw = doc.raw.decode("utf-8")
    start = raw.index('<nr status="officieel">15b</nr>')
    opening = raw[raw.rindex("<artikel ", 0, start) : start]
    in_force = re.search(r'inwerking="(\d{4}-\d{2}-\d{2})"', opening).group(1)
    article = strip_markup(raw[start : raw.index("</artikel>", start)])
    ratio_text = re.search(r"a\. ([\d,]+)% van de gecorrigeerde winst;", collapse(article)).group(1)
    floor_text = re.search(r"b\. € ([\d.]+)\.", collapse(article)).group(1)
    ratio = float(ratio_text.replace(",", "."))
    floor = int(floor_text.replace(".", ""))
    parameters = {
        "currency": "EUR",
        "ratio_percent": ratio,
        "base": "gecorrigeerde winst: taxable profit before the limitation plus depreciation, impairments and the net interest balance (a tax EBITDA)",
        "allowance_floor": floor,
        "exemption_threshold": None,
        "gross_receipts_limit": None,
        "carryforward": "non-deductible net interest is carried forward without time limit",
    }
    items = [
        doc.cite("artikel 15b, lid 1, onderdeel a", f"{ratio_text}%", "percent", f"{ratio_text}% van de gecorrigeerde winst;"),
        doc.cite("artikel 15b, lid 1, onderdeel b", f"€ {floor_text}", "currency:EUR", f"€ {floor_text}."),
        doc.cite("artikel 15b, attribute inwerking", in_force, "date", f'inwerking="{in_force}" label="Artikel 15b"'),
        doc.cite("artikel 15b, lid 1", "het hoogste van de volgende bedragen", "text", "niet in aftrek voor zover dat meer bedraagt dan het hoogste van de volgende bedragen:"),
    ]
    return rule(
        "nl-earnings-stripping-rule-article-15b",
        "Netherlands earnings-stripping rule (art. 15b Wet Vpb 1969, ATAD art. 4): net interest capped at 24.5% of tax EBITDA or EUR 1 million",
        "tax",
        "NL",
        "A",
        in_force,
        None,
        [*TAGS, "interest-limitation", "earnings-stripping", "atad", "leverage", "ebitda"],
        ["lbo-modelling", "private-credit-demo", "tax-demo", "valuation-demo"],
        "interest_limitation",
        parameters,
        [
            vector({"earnings": 0, "interest_expense": floor}, floor, "source", "the EUR 1,000,000 amount of art. 15b(1)(b) is deductible whatever the profit"),
            vector({"earnings": 10000000, "interest_expense": 4000000, "interest_income": 500000}, 2950000, "derived", "interest income plus 24.5% of tax EBITDA"),
            vector({"earnings": 10000000, "interest_expense": 4000000, "interest_income": 500000, "output": "disallowed"}, 1050000, "derived", "carried forward"),
            vector({"earnings": 2000000, "interest_expense": 900000}, 900000, "derived", "below the EUR 1 million floor"),
        ],
        items,
        [{"statistic": "ratio_percent", "expected": ratio, "tolerance": 0}, {"statistic": "allowance_floor", "expected": floor, "tolerance": 0}],
        (
            "Article 15b of the Dutch Corporate Income Tax Act, which implements the interest limitation rule of the EU "
            "Anti-Tax Avoidance Directive, denies a deduction for a company's net interest balance on loans to the extent "
            "it exceeds the higher of a percentage of its adjusted profit (a tax EBITDA) and a fixed amount. The percentage "
            "has been 24.5% for years from 2025 (the article's current text took effect on the inwerking date the XML "
            "records); disallowed interest carries forward to later years. " + NL_LICENSE_NOTE
        ),
        [{"parameter": "allowance_floor", "value": floor, "method": "derived", "rationale": "The Act writes the amount as '€ 1.000.000' with Dutch thousands separators; the builder converts it."}],
    )


def main() -> None:
    plaw = public_law_119_21()
    rev_proc = rev_proc_2025_32()
    builders = [
        oecd_statutory_cit,
        oecd_effective_tax_rates,
        oecd_withholding_tax_rates,
        oecd_interest_limitation_rules,
        lambda: us_qsbs(plaw),
        lambda: us_business_interest_limitation(plaw, rev_proc),
        lambda: us_bonus_depreciation(plaw),
        us_carried_interest_holding_period,
        us_net_investment_income_tax,
        lambda: us_qualified_business_income_deduction(plaw, rev_proc),
        regulation_d_accredited_investor,
        regulation_d_rule_506,
        investment_company_act_exclusions,
        qualified_client_thresholds,
        private_fund_adviser_thresholds,
        venture_capital_fund_definition,
        erisa_plan_asset_test,
        gb_business_asset_disposal_relief,
        gb_carried_interest,
        gb_corporate_interest_restriction,
        gb_substantial_shareholding_exemption,
        gb_venture_capital_schemes,
        nl_earnings_stripping,
    ]
    for build in builders:
        write(build())


if __name__ == "__main__":
    main()

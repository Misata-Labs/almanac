"""Regenerate the United States federal tax, payroll, benefit and lending limit entries for 2026.

Sources are the documents the agencies publish for the year: IRS revenue procedures,
notices and publications (static PDFs under www.irs.gov/pub), the Federal Register issue
XML on govinfo for the CMS Medicare and HHS poverty guideline notices, the United States
Code on govinfo, FHFA's county loan limit CSV and HUD's mortgagee letter. Every figure is
parsed from the fetched bytes; a pattern that no longer matches stops the build. Run from
the repository root:

    uv run python tools/build_us_limits.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

ACCESSED = date(2026, 11, 3)
LICENSE = "unstated"
MAX_SNIPPET_WORDS = 24

IRS = "Internal Revenue Service, US Department of the Treasury"
CMS = "Centers for Medicare & Medicaid Services, via the Federal Register (govinfo)"
HHS = "US Department of Health and Human Services, via the Federal Register (govinfo)"
OLRC = "Office of the Law Revision Counsel, US House of Representatives, via govinfo"
FHFA = "Federal Housing Finance Agency"
HUD = "US Department of Housing and Urban Development, Federal Housing Administration"

IRS_DROP = "https://www.irs.gov/pub/irs-drop"
IRS_PDF = "https://www.irs.gov/pub/irs-pdf"
GOVINFO = "https://www.govinfo.gov/content/pkg"

LICENSE_NOTE = (
    "Works of the US federal government carry no copyright in the United States, but the cited documents state "
    "no reuse terms, so the licence is recorded as unstated and the entry held at license-review."
)

TAX_USES = ["tax-demo", "tax-filing-demo", "payroll-demo", "personal-finance"]
PAYROLL_USES = ["payroll-demo", "hr-demo", "tax-demo"]
BENEFIT_USES = ["benefits-demo", "hr-demo", "payroll-demo"]
LENDING_USES = ["lending-demo", "mortgage-origination", "loan-pricing"]
HEALTH_USES = ["benefits-demo", "health-demo", "personal-finance"]


def collapse(text: str) -> str:
    return " ".join(text.split())


def money(text: str) -> int | float:
    """Parse a dollar figure such as ``$1,234`` or ``$206,583.50``."""
    number = text.replace("$", "").replace(",", "").strip()
    value = Decimal(number)
    return int(value) if value == value.to_integral_value() and "." not in number else float(value)


class Source:
    """A fetched resource with the searchable text the verifier will see."""

    def __init__(self, url: str, title: str, publisher: str) -> None:
        self.url, self.title, self.publisher = url, title, publisher
        self.raw = fetch(url)
        if self.raw.startswith(b"%PDF"):
            reader = PdfReader(io.BytesIO(self.raw))
            self.pages = [page.extract_text() or "" for page in reader.pages]
            self.full = "\n".join(self.pages)
        else:
            self.full = self.raw.decode("utf-8", errors="replace")
            self.pages = [self.full]
        self.text = collapse(self.full)

    def section(self, start: str, end: str | None = None) -> str:
        """Collapsed text from the first occurrence of ``start`` up to the next ``end``."""
        begin = self.text.index(start)
        stop = self.text.index(end, begin + len(start)) if end else len(self.text)
        return self.text[begin:stop]

    def match(self, pattern: str, within: str | None = None) -> re.Match[str]:
        found = re.search(pattern, within if within is not None else self.text)
        if found is None:
            raise ValueError(f"{self.url}: pattern {pattern!r} not found")
        return found

    def ev(self, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        snippet = collapse(snippet)
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet too long: {snippet!r}")
        for needle in (snippet, collapse(str(value))):
            if needle not in self.text:
                raise ValueError(f"{self.url}: {needle!r} not in resource")
        item = evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, LICENSE, self.raw, role=role)
        item["accessed_at"] = ACCESSED.isoformat()
        return item


def fact(src: Source, pattern: str, locator: str, within: str | None = None, unit: str = "currency:USD", group: int = 1, parse: Callable[[str], Any] = money, role: str = "primary") -> tuple[Any, dict]:
    """Find ``pattern``; return its parsed group and an evidence item whose snippet is the whole match."""
    found = src.match(pattern, within)
    return parse(found.group(group)), src.ev(locator, found.group(group), unit, found.group(0), role=role)


def percent(text: str) -> float:
    return float(text.rstrip("%"))


def base_entry(entry_id: str, title: str, domain: str, valid_from: str, valid_to: str | None, tags: list[str], use_cases: list[str], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], tests: list[dict], notes: str, assumed: list[dict] | None = None, tier: str = "B") -> dict:
    if len(title) > 140:
        raise ValueError(f"title too long for {entry_id}")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "US",
        "status": "license-review",
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes + " " + LICENSE_NOTE,
    }


class Limits:
    """Accumulates the rows of a lookup-table entry together with their evidence."""

    def __init__(self, src: Source) -> None:
        self.src = src
        self.rows: dict[str, dict] = {}
        self.evidence: list[dict] = []

    def add(self, key: str, pattern: str, locator: str, description: str, within: str | None = None, unit: str = "USD", group: int = 1, extra: dict | None = None, src: Source | None = None, parse: Callable[[str], Any] | None = None) -> Any:
        source = src or self.src
        parse = parse or (percent if unit == "percent" else money)
        evidence_unit = {"percent": "percent", "USD": "currency:USD"}.get(unit, "decimal")
        value, item = fact(source, pattern, locator, within, evidence_unit, group, parse)
        self.rows[key] = {"value": value, "unit": unit, "description": description, **(extra or {})}
        self.evidence.append(item)
        return value

    def vectors(self, absent: str) -> list[dict]:
        found = [{"input": {"key": key, "column": "value"}, "expected": row["value"], "origin": "source"} for key, row in self.rows.items()]
        return [*found, {"input": absent, "expected": False, "origin": "derived", "note": "not a figure this entry covers"}]


# --------------------------------------------------------------------------------------
# Rev. Proc. 2025-32: 2026 inflation-adjusted items
# --------------------------------------------------------------------------------------

BRACKET_STATUSES = [
    ("married-filing-jointly", "married individuals filing joint returns and surviving spouses", "Table 1, section 1(j)(2)(A)"),
    ("head-of-household", "heads of households", "Table 2, section 1(j)(2)(B)"),
    ("single", "unmarried individuals other than surviving spouses and heads of households", "Table 3, section 1(j)(2)(C)"),
    ("married-filing-separately", "married individuals filing separate returns", "Table 4, section 1(j)(2)(D)"),
    ("estates-and-trusts", "estates and trusts", "Table 5, section 1(j)(2)(E)"),
]

ROW = re.compile(
    r"Not over \$(?P<first>[\d,]+) (?P<first_rate>\d+)% of the taxable income"
    r"|Over \$(?P<low>[\d,]+) but not over \$(?P<high>[\d,]+) \$(?P<base>[\d,.]+) plus (?P<rate>\d+)% of the excess over \$(?P<over>[\d,]+)"
    r"|Over \$(?P<top_low>[\d,]+) \$(?P<top_base>[\d,.]+) plus (?P<top_rate>\d+)% of the excess over \$(?P<top_over>[\d,]+)"
)


def rate_tables(src: Source) -> list[list[dict]]:
    """The five section 1 rate tables in document order, each row with its source text."""
    region = src.section(".01 Tax Rate Tables. For taxable years beginning in 2026", ".03 Maximum Capital Gains Rate")
    tables: list[list[dict]] = []
    for found in ROW.finditer(region):
        if found.group("first"):
            tables.append([{"up_to": money(found.group("first")), "rate": int(found.group("first_rate")), "base": 0, "text": found.group(0), "value": f"${found.group('first')}"}])
        elif found.group("low"):
            if money(found.group("low")) != money(found.group("over")):
                raise ValueError(f"row {found.group(0)!r} is not self-consistent")
            tables[-1].append({"up_to": money(found.group("high")), "rate": int(found.group("rate")), "base": money(found.group("base")), "text": found.group(0), "value": f"${found.group('base')}"})
        else:
            tables[-1].append({"up_to": None, "rate": int(found.group("top_rate")), "base": money(found.group("top_base")), "text": found.group(0), "value": f"${found.group('top_base')}"})
    if [len(t) for t in tables] != [7, 7, 7, 7, 4]:
        raise ValueError(f"unexpected rate table shapes {[len(t) for t in tables]}")
    for table in tables:
        lower, tax = Decimal(0), Decimal(0)
        for row, following in zip(table, table[1:]):
            tax += (Decimal(str(row["up_to"])) - lower) * row["rate"] / 100
            lower = Decimal(str(row["up_to"]))
            if tax != Decimal(str(following["base"])):
                raise ValueError(f"cumulative tax {tax} disagrees with stated base {following['base']}")
    return tables


def bracket_entries(src: Source) -> list[dict]:
    entries = []
    for (slug, label, locator), table in zip(BRACKET_STATUSES, rate_tables(src)):
        bands = [{"name": f"rate_{row['rate']}", "up_to": row["up_to"], "rate_percent": row["rate"]} for row in table]
        vectors = [
            {
                "input": {"income": row["up_to"]},
                "expected": f"{Decimal(str(following['base'])):.2f}",
                "origin": "source",
                "note": f"the table states the tax on income over ${row['up_to']:,} as {following['value']} plus {following['rate']}% of the excess",
            }
            for row, following in zip(table, table[1:])
        ]
        top = table[-1]
        probe = int(table[-2]["up_to"]) + 100000
        vectors.append(
            {
                "input": {"income": probe},
                "expected": f"{Decimal(str(top['base'])) + (probe - Decimal(str(table[-2]['up_to']))) * top['rate'] / 100:.2f}",
                "origin": "derived",
                "note": f"top-bracket base plus {top['rate']}% of $100,000",
            }
        )
        vectors.append({"input": {"income": 0}, "expected": "0.00", "origin": "derived", "note": "no taxable income"})
        evidence_items = [src.ev(f"page 10 to 12, section 4.01, {locator}", row["value"], "currency:USD", row["text"]) for row in table]
        evidence_items.append(src.ev("section 5.02, effective date", "applies to taxable years beginning in 2026", "text", "section 4 of this revenue procedure applies to taxable years beginning in 2026", role="supporting"))
        title_label = label[0].upper() + label[1:]
        entries.append(
            base_entry(
                f"us-federal-income-tax-brackets-2026-{slug}",
                f"US federal income tax rate schedule for 2026: {slug.replace('-', ' ')} (Rev. Proc. 2025-32)",
                "tax",
                "2026-01-01",
                "2026-12-31",
                ["tax", "income-tax", "tax-brackets", "limits", "obbba", "rev-proc-2025-32"],
                TAX_USES,
                "almanac.rules.income_tax_bands",
                {
                    "tax_year": "2026",
                    "currency": "USD",
                    "filing_status": slug.replace("-", "_"),
                    "input": "taxable income (after the standard or itemised deduction)",
                    "personal_allowance": 0,
                    "bands": bands,
                },
                vectors,
                evidence_items,
                [
                    {"statistic": "count", "expected": len(bands), "tolerance": 0},
                    {"statistic": f"rate[rate_{top['rate']}]", "expected": top["rate"], "tolerance": 0},
                ],
                (
                    f"{title_label}: the 2026 tax rate table of section 1(j)(2) of the Internal Revenue Code as "
                    "Rev. Proc. 2025-32 adjusts it for inflation, reflecting Public Law 119-21 (commonly known as the "
                    "One, Big, Beautiful Bill Act), which made the seven individual rates permanent. The rule takes "
                    "taxable income, so personal_allowance is zero; subtract the standard deduction "
                    "(us-standard-deduction-2026) or itemised deductions first. Each vector at a bracket ceiling "
                    "reproduces the dollar base the revenue procedure prints for the next bracket. The revenue "
                    "procedure applies to taxable years beginning in 2026; the build checks that every printed base "
                    "equals the cumulative tax of the brackets below it."
                ),
                [
                    {
                        "parameter": "bands[*].up_to",
                        "value": [row["up_to"] for row in table],
                        "method": "derived",
                        "rationale": "The revenue procedure states each bracket as 'Over $X but not over $Y'; the ceiling Y is the band limit and the top bracket has none.",
                    }
                ],
            )
        )
    return entries


def standard_deduction(src: Source) -> dict:
    sec = src.section(".14 Standard Deduction.", ".15 C afeteria Plans")
    lim = Limits(src)
    loc = "page 18, section 4.14"
    lim.add("married_filing_jointly_or_surviving_spouse", r"Married Individuals Filing Joint Returns and Surviving Spouses \(§ 1\(j\)\(2\)\(A\)\) (\$[\d,]+)", f"{loc}(1)", "basic standard deduction, married filing jointly and surviving spouses", sec)
    lim.add("head_of_household", r"Heads of Households \(§ 1\(j\)\(2\)\(B\)\) (\$[\d,]+)", f"{loc}(1)", "basic standard deduction, heads of households", sec)
    lim.add("single", r"Heads of Households\) \(§ 1\(j\)\(2\)\(C\)\) (\$[\d,]+)", f"{loc}(1)", "basic standard deduction, unmarried individuals other than surviving spouses and heads of households", sec)
    lim.add("married_filing_separately", r"Married Individuals Filing Separate Returns \(§ 1\(j\)\(2\)\(D\)\) (\$[\d,]+)", f"{loc}(1)", "basic standard deduction, married filing separately", sec)
    lim.add("dependent_minimum", r"cannot exceed the greater of \(1\) (\$[\d,]+), or \(2\) the sum of \$[\d,]+ and the individual.s earned income", f"{loc}(2)", "standard deduction of a dependent: at least this amount", sec)
    lim.add("dependent_earned_income_addition", r"cannot exceed the greater of \(1\) \$[\d,]+, or \(2\) the sum of (\$[\d,]+) and the individual.s earned income", f"{loc}(2)", "standard deduction of a dependent: or this amount plus earned income, if greater", sec)
    lim.add("additional_aged_or_blind", r"the additional standard deduction amount under § 63\(f\) for the aged or the blind is (\$[\d,]+)", f"{loc}(3)", "additional standard deduction for each of age 65 or over and blindness, married or surviving spouse", sec)
    lim.add("additional_aged_or_blind_unmarried", r"is increased to (\$[\d,]+) if the individual is also unmarried and not a surviving spouse", f"{loc}(3)", "additional standard deduction for each of age 65 or over and blindness, unmarried and not a surviving spouse", sec)
    rows = lim.rows
    return base_entry(
        "us-standard-deduction-2026",
        "US federal standard deduction for 2026 by filing status, with the additional amounts for age or blindness (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "income-tax", "standard-deduction", "limits", "rev-proc-2025-32"],
        TAX_USES,
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": rows},
        lim.vectors("personal_exemption"),
        lim.evidence,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[single,value]", "expected": rows["single"]["value"], "tolerance": 0},
            {"statistic": "max[value]", "expected": rows["married_filing_jointly_or_surviving_spouse"]["value"], "tolerance": 0},
        ],
        (
            "The 2026 basic standard deduction under section 63(c)(2) for each filing status, the limit on a "
            "dependent's standard deduction under section 63(c)(5), and the additional standard deduction under "
            "section 63(f) for a taxpayer who is 65 or older or blind (claimed once for each condition), as Rev. Proc. "
            "2025-32 states them for taxable years beginning in 2026. Public Law 119-21 raised the base amounts from "
            "which these are indexed. A synthetic return subtracts the larger of this deduction and itemised "
            "deductions from adjusted gross income before applying the rate schedule."
        ),
    )


def capital_gains(src: Source) -> dict:
    sec = src.section(".03 Maximum Capital Gains Rate (§ 1(h)", ".04 Adoption Credit.")
    loc = "page 13, section 4.03 table"
    rows, items = {}, []
    labels = [
        ("married_filing_jointly_or_surviving_spouse", "Married Individuals Filing Joint Returns and Surviving Spouse"),
        ("married_filing_separately", "Married Individuals Filing Separate Returns"),
        ("head_of_household", "Heads of Household"),
        ("all_other_individuals", "All Other Individuals"),
        ("estates_and_trusts", "Estates and Trusts"),
    ]
    for key, label in labels:
        found = src.match(re.escape(label) + r" (\$[\d,]+) (\$[\d,]+)", sec)
        rows[key] = {"maximum_zero_rate_amount": money(found.group(1)), "maximum_15_percent_rate_amount": money(found.group(2)), "filing_status": label}
        items.append(src.ev(loc, found.group(1), "currency:USD", found.group(0)))
    vectors = [{"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": "source"} for key in rows for column in ("maximum_zero_rate_amount", "maximum_15_percent_rate_amount")]
    vectors.append({"input": "qualifying_widow", "expected": False, "origin": "derived", "note": "surviving spouses use the joint-return row"})
    return base_entry(
        "us-capital-gains-rate-thresholds-2026",
        "US long-term capital gains and qualified dividends 0% and 15% rate thresholds for 2026 by filing status (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "capital-gains", "qualified-dividends", "limits", "rev-proc-2025-32"],
        TAX_USES,
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rates_percent": [0, 15, 20], "rows": rows},
        vectors,
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[maximum_15_percent_rate_amount]", "expected": max(r["maximum_15_percent_rate_amount"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "Maximum zero rate amount and maximum 15 percent rate amount under section 1(j)(5)(B) for 2026: net "
            "capital gain and qualified dividends fall in the 0% band while taxable income is at or below the first "
            "figure, in the 15% band up to the second, and at 20% above it. Figures as Rev. Proc. 2025-32 adjusts "
            "them; 'All Other Individuals' covers single filers. The 0, 15 and 20 percent rates themselves are those "
            "the section names and are carried for context."
        ),
        [{"parameter": "rates_percent", "value": [0, 15, 20], "method": "derived", "rationale": "The revenue procedure names the zero and 15 percent rate amounts; the 20 percent rate above the second threshold is the statutory maximum capital gains rate of section 1(h) the section heading refers to."}],
    )


def amt(src: Source) -> dict:
    sec = src.section(".10 E xemption Amounts for Alternative Minimum Tax.", ".11 Alternative Minimum Tax Exemption for a Child")
    labels = [
        ("joint_or_surviving_spouse", "Joint Returns or Surviving Spouses"),
        ("unmarried", "Unmarried Individuals (other than Surviving Spouses)"),
        ("married_filing_separately", "Married Individuals Filing Separate Returns"),
        ("estates_and_trusts", "Estates and Trusts"),
    ]
    exemption_block = sec[: sec.index("the excess taxable income above which the 28 percent")]
    phaseout_block = sec[sec.index("to determine the phaseout of the exemption amounts are"):]
    rows, items = {}, []
    for key, label in labels:
        ex = src.match(re.escape(label) + r" (\$[\d,]+)", exemption_block)
        ph = src.match(re.escape(label) + r" (\$[\d,]+) (\$[\d,]+)", phaseout_block)
        rows[key] = {"exemption": money(ex.group(1)), "phaseout_threshold": money(ph.group(1)), "complete_phaseout": money(ph.group(2)), "filing_status": label}
        items.append(src.ev("page 16, section 4.10, exemption amounts under section 55(d)(1)", ex.group(1), "currency:USD", ex.group(0)))
        items.append(src.ev("page 17, section 4.10, phaseout amounts under section 55(d)(2)", ph.group(2), "currency:USD", ph.group(0)))
    mfs28 = src.match(r"Excess taxable income Married Individuals Filing Separate Returns (\$[\d,]+) All Other Taxpayers (\$[\d,]+)", sec)
    items.append(src.ev("page 16, section 4.10, 28 percent rate threshold under section 55(b)(1)", mfs28.group(2), "currency:USD", mfs28.group(0)))
    threshold = {"married_filing_separately": money(mfs28.group(1)), "all_other_taxpayers": money(mfs28.group(2))}
    vectors = [{"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": "source"} for key in rows for column in ("exemption", "phaseout_threshold", "complete_phaseout")]
    vectors.append({"input": "head_of_household", "expected": False, "origin": "derived", "note": "heads of household use the unmarried row"})
    return base_entry(
        "us-alternative-minimum-tax-exemptions-2026",
        "US alternative minimum tax exemptions, phase-out thresholds and 28% rate threshold for 2026 (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "alternative-minimum-tax", "amt", "limits", "rev-proc-2025-32"],
        TAX_USES,
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rate_28_percent_threshold": threshold, "rows": rows},
        vectors,
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[joint_or_surviving_spouse,exemption]", "expected": rows["joint_or_surviving_spouse"]["exemption"], "tolerance": 0},
        ],
        (
            "Alternative minimum tax for 2026: the exemption amount under section 55(d)(1) by filing status, the "
            "alternative minimum taxable income at which it starts to phase out and the amount at which it is fully "
            "phased out (section 55(d)(2)), and the excess taxable income above which the 28 percent AMT rate "
            "applies (section 55(b)(1)), carried in rate_28_percent_threshold. Public Law 119-21 made the higher "
            "exemption and phase-out amounts permanent and held the joint-return threshold of $1,000,000 unindexed "
            "until 2027, as section 2.07 of the revenue procedure explains."
        ),
    )


def eitc(src: Source) -> dict:
    sec = src.section("Number of Qualifying Children Item One Two Three or More None", "(2) Excessive Investment Income")
    columns = ["one_child", "two_children", "three_or_more_children", "no_children"]
    items, table = [], {}
    for field, label in [
        ("earned_income_amount", "Earned Income Amount"),
        ("maximum_credit", "Maximum Amount of Credit"),
        ("threshold_phaseout_joint", "Threshold Phaseout Amount (Married Filing Jointly)"),
        ("completed_phaseout_joint", "Completed Phaseout Amount (Married Filing Jointly)"),
        ("threshold_phaseout_other", "Threshold Phaseout Amount (All other filing statuses)"),
        ("completed_phaseout_other", "Completed Phaseout Amount (All other filing statuses)"),
    ]:
        found = src.match(re.escape(label) + r" (\$[\d,]+) (\$[\d,]+) (\$[\d,]+) (\$[\d,]+)", sec)
        table[field] = [money(found.group(i)) for i in range(1, 5)]
        items.append(src.ev(f"page 15, section 4.06(1) table, row '{label}'", found.group(1), "currency:USD", found.group(0)))
    rows = {column: {field: values[i] for field, values in table.items()} for i, column in enumerate(columns)}
    investment, item = fact(src, r"if the aggregate amount of certain investment income exceeds (\$[\d,]+)", "page 15, section 4.06(2)")
    items.append(item)
    vectors = [{"input": {"key": key, "column": "maximum_credit"}, "expected": rows[key]["maximum_credit"], "origin": "source"} for key in columns]
    vectors += [{"input": {"key": key, "column": "completed_phaseout_joint"}, "expected": rows[key]["completed_phaseout_joint"], "origin": "source"} for key in columns]
    vectors.append({"input": "four_children", "expected": False, "origin": "derived", "note": "four or more children use three_or_more_children"})
    return base_entry(
        "us-earned-income-credit-parameters-2026",
        "US earned income tax credit for 2026: earned income amount, maximum credit and phase-out range by qualifying children (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "earned-income-credit", "eitc", "tax-credit", "limits", "rev-proc-2025-32"],
        [*TAX_USES, "benefits-demo"],
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "investment_income_limit": investment, "rows": rows},
        vectors,
        items,
        [
            {"statistic": "count", "expected": 4, "tolerance": 0},
            {"statistic": "max[maximum_credit]", "expected": max(r["maximum_credit"] for r in rows.values()), "tolerance": 0},
            {"statistic": "value[no_children,earned_income_amount]", "expected": rows["no_children"]["earned_income_amount"], "tolerance": 0},
        ],
        (
            "The section 32(b) amounts for 2026 by number of qualifying children: the earned income at which the "
            "maximum credit is reached, the maximum credit, and the adjusted gross income (or earned income, if "
            "greater) at which the credit starts to phase out and is fully phased out, for joint filers and for all "
            "other filing statuses. The credit is not allowed when investment income exceeds investment_income_limit. "
            "The IRS publishes the credit for each income in the Form 1040 instructions; this entry carries the "
            "table that drives it."
        ),
    )


def credits(src: Source) -> dict:
    lim = Limits(src)
    lim.add("child_tax_credit_per_child", r"the maximum amount of the credit allowed under § 24\(a\) is (\$[\d,]+)", "page 14, section 4.05(1)", "maximum child tax credit per qualifying child")
    lim.add("child_tax_credit_refundable_per_child", r"the amount used in § 24\(d\)\(1\)\(A\) to determine the amount of the credit under § 24 that may be refundable is (\$[\d,]+)", "page 14, section 4.05(2)", "refundable portion of the child tax credit per qualifying child")
    lim.add("adoption_credit_special_needs", r"the credit allowed for an adoption of a child with special needs is (\$[\d,]+)", "page 13, section 4.04(1)", "adoption credit for a child with special needs")
    lim.add("adoption_credit_maximum_expenses", r"the maximum credit allowed for other adoptions is the amount of qualified adoption expenses up to (\$[\d,]+)", "page 13, section 4.04(2)", "maximum adoption credit for other adoptions")
    lim.add("adoption_credit_phaseout_start", r"phase out under § 23\(b\)\(2\)\(A\) for taxpayers with modified adjusted gross income in excess of (\$[\d,]+)", "page 13, section 4.04(2)", "modified AGI above which the adoption credit phases out")
    lim.add("adoption_credit_phaseout_end", r"is completely phased out for taxpayers with modified adjusted gross income of (\$[\d,]+) or more\. See section 4\.18", "page 13, section 4.04(2)", "modified AGI at which the adoption credit is fully phased out")
    lim.add("adoption_credit_refundable_portion", r"the amount used in § 23\(a\)\(4\) to determine the amount of the credit under § 23 that may be refundable is (\$[\d,]+)", "page 14, section 4.04(3)", "refundable portion of the adoption credit")
    return base_entry(
        "us-child-tax-credit-and-adoption-credit-2026",
        "US child tax credit and adoption credit amounts for 2026, including refundable portions and phase-out (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "child-tax-credit", "adoption-credit", "tax-credit", "limits", "obbba", "rev-proc-2025-32"],
        [*TAX_USES, "benefits-demo"],
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": lim.rows},
        lim.vectors("child_and_dependent_care_credit"),
        lim.evidence,
        [{"statistic": "count", "expected": len(lim.rows), "tolerance": 0}, {"statistic": "value[child_tax_credit_per_child,value]", "expected": lim.rows["child_tax_credit_per_child"]["value"], "tolerance": 0}],
        (
            "Credit amounts for 2026 from Rev. Proc. 2025-32: the maximum child tax credit per qualifying child under "
            "section 24(a) and the part that may be refundable under section 24(d)(1)(A); the adoption credit for a "
            "child with special needs and the cap on qualified adoption expenses for other adoptions under section "
            "23, its modified adjusted gross income phase-out range, and the refundable portion that Public Law "
            "119-21 introduced in section 23(a)(4). The child tax credit's own income phase-out thresholds are "
            "statutory and not part of this entry."
        ),
    )


def transfer_tax(src: Source) -> dict:
    lim = Limits(src)
    lim.add("basic_exclusion_amount", r"amends § 2010\(c\)\(3\) by increasing the basic exclusion amount to (\$[\d,]+) for calendar year 2026", "page 8, section 2.14", "estate and gift tax basic exclusion amount (section 2010(c)(3))")
    lim.add("generation_skipping_transfer_exemption", r"the generation-skipping transfer exemption amount under § 2631\(c\) is equal to (\$[\d,]+)", "page 8, section 2.14", "generation-skipping transfer tax exemption (section 2631(c))")
    lim.add("annual_gift_exclusion", r"For calendar year 2026, the first (\$[\d,]+) of gifts to any person", "page 25, section 4.42(1)", "annual exclusion per donee for gifts of present interests (section 2503(b))")
    lim.add("annual_gift_exclusion_noncitizen_spouse", r"For calendar year 2026, the first (\$[\d,]+) \(instead of the amount provided in paragraph \(1\)", "page 26, section 4.42(2)", "annual exclusion for gifts to a spouse who is not a US citizen (section 2523(i)(2))")
    lim.add("special_use_valuation_limit", r"from electing to use § 2032A for purposes of the estate tax cannot exceed (\$[\d,]+)", "page 25, section 4.41", "maximum reduction in value of qualified real property under special use valuation (section 2032A)")
    lim.add("estate_tax_installment_two_percent_portion", r"of the estate tax extended as provided in § 6166 is (\$[\d,]+)", "page 28, section 4.51", "amount defining the 2-percent portion of estate tax deferred under section 6166")
    return base_entry(
        "us-estate-and-gift-tax-exclusions-2026",
        "US estate and gift tax basic exclusion, GST exemption and annual gift exclusions for 2026 (Rev. Proc. 2025-32)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "estate-tax", "gift-tax", "limits", "obbba", "rev-proc-2025-32"],
        ["tax-demo", "financial-planning", "personal-finance"],
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": lim.rows},
        lim.vectors("inheritance_tax_allowance"),
        lim.evidence,
        [{"statistic": "count", "expected": len(lim.rows), "tolerance": 0}, {"statistic": "max[value]", "expected": lim.rows["basic_exclusion_amount"]["value"], "tolerance": 0}],
        (
            "Federal transfer tax amounts for calendar year 2026. Public Law 119-21 set the basic exclusion amount "
            "used for the estate and gift tax applicable credit, and with it the generation-skipping transfer "
            "exemption, for 2026 (section 2.14 of Rev. Proc. 2025-32); the annual per-donee gift exclusion, the "
            "higher annual exclusion for gifts to a non-citizen spouse, the special use valuation cap and the "
            "section 6166 '2-percent portion' amount are the indexed figures of sections 4.41, 4.42 and 4.51."
        ),
    )


def employee_benefits(src: Source) -> dict:
    lim = Limits(src)
    lim.add("health_fsa_salary_reduction", r"spending arrangements is (\$[\d,]+)\. If the cafeteria plan permits", "page 18 to 19, section 4.15", "annual limit on employee salary reductions to a health FSA (section 125(i))")
    lim.add("health_fsa_carryover", r"the maximum carryover amount is (\$[\d,]+)", "page 19, section 4.15", "maximum health FSA carryover of unused amounts")
    lim.add("transit_and_vanpool_monthly", r"transportation in a commuter highway vehicle and any transit pass is (\$[\d,]+)", "page 19, section 4.16", "monthly exclusion for commuter highway vehicle and transit passes (section 132(f)(2)(A))")
    lim.add("qualified_parking_monthly", r"the fringe benefit exclusion amount for qualified parking is (\$[\d,]+)", "page 19, section 4.16", "monthly exclusion for qualified parking (section 132(f)(2)(B))")
    lim.add("adoption_assistance_exclusion", r"furnished pursuant to an adoption assistance program for adoptions by the employee is (\$[\d,]+)", "page 19, section 4.18", "maximum exclusion for employer adoption assistance (section 137(b)(1))")
    lim.add("educational_assistance_exclusion", r"The maximum exclusion amount of (\$[\d,]+) will be adjusted for inflation for taxable years beginning after 2026", "page 7, section 2.09", "annual exclusion for employer educational assistance (section 127); indexed only after 2026")
    lim.add("qsehra_self_only", r"payments and reimbursements for any year cannot exceed (\$[\d,]+) \(\$[\d,]+ for family coverage\)", "page 34, section 4.63", "qualified small employer HRA annual maximum, self-only (section 9831(d))")
    lim.add("qsehra_family", r"payments and reimbursements for any year cannot exceed \$[\d,]+ \((\$[\d,]+) for family coverage\)", "page 34, section 4.63", "qualified small employer HRA annual maximum, family")
    lim.add("small_employer_health_credit_wage_amount", r"the dollar amount in effect under § 45R\(d\)\(3\)\(B\) is (\$[\d,]+)", "page 16, section 4.09", "average annual wage amount for the small employer health insurance credit (section 45R(d)(3)(B))")
    lim.add("long_term_care_per_diem", r"by reason of the death of a chronically ill individual, is (\$[\d,]+)", "page 34, section 4.62", "per diem limitation for periodic long-term care payments (section 7702B(d)(4))")
    ltc = src.section(".27 Eligible Long-Term Care Premiums.", ".28 Medical Savings Accounts.")
    for key, label in [
        ("ltc_premium_age_40_or_less", "40 or less"),
        ("ltc_premium_age_41_to_50", "More than 40 but not more than 50"),
        ("ltc_premium_age_51_to_60", "More than 50 but not more than 60"),
        ("ltc_premium_age_61_to_70", "More than 60 but not more than 70"),
        ("ltc_premium_age_over_70", "More than 70"),
    ]:
        lim.add(key, re.escape(label) + r" (\$[\d,]+)", "page 22, section 4.27 table", f"eligible long-term care premium limit, attained age {label.lower()} (section 213(d)(10))", ltc)
    return base_entry(
        "us-employee-benefit-exclusion-limits-2026",
        "US employee benefit limits for 2026: health FSA, transit and parking, adoption assistance, QSEHRA, long-term care (Rev. Proc. 2025-32)",
        "benefits",
        "2026-01-01",
        "2026-12-31",
        ["benefits", "payroll", "limits", "fsa", "fringe-benefits", "rev-proc-2025-32"],
        BENEFIT_USES,
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": lim.rows},
        lim.vectors("dependent_care_fsa"),
        lim.evidence,
        [{"statistic": "count", "expected": len(lim.rows), "tolerance": 0}, {"statistic": "value[health_fsa_salary_reduction,value]", "expected": lim.rows["health_fsa_salary_reduction"]["value"], "tolerance": 0}],
        (
            "Employer benefit limits for 2026 from Rev. Proc. 2025-32: the health flexible spending arrangement "
            "salary-reduction limit and carryover, the monthly qualified transportation fringe exclusions, the "
            "adoption assistance exclusion, the educational assistance exclusion (unindexed until after 2026), the "
            "qualified small employer HRA maxima, the small employer health credit wage amount, the long-term care "
            "per diem, and the age-banded limits on long-term care premiums treated as medical care. Monthly "
            "amounts are per employee per month; the others are annual. The adoption assistance exclusion phases out "
            "over the same modified AGI range as the adoption credit (us-child-tax-credit-and-adoption-credit-2026)."
        ),
    )


def section_179(src: Source) -> dict:
    lim = Limits(src)
    sec = src.section(".24 Election to Expense Certain Depreciable Assets.", ".25 E nergy")
    lim.add("maximum_deduction", r"elects to treat as an expense cannot exceed (\$[\d,]+)", "page 21, section 4.24", "maximum section 179 expense deduction (section 179(b)(1))", sec)
    lim.add("phaseout_threshold", r"placed in service during the 2026 taxable year exceeds (\$[\d,]+)", "page 21, section 4.24", "cost of section 179 property placed in service above which the maximum is reduced dollar for dollar (section 179(b)(2))", sec)
    lim.add("sport_utility_vehicle_limit", r"the cost of any sport utility vehicle that may be taken into account under § 179 cannot exceed (\$[\d,]+)", "page 21, section 4.24", "cost of a sport utility vehicle that may be taken into account (section 179(b)(5)(A))", sec)
    return base_entry(
        "us-section-179-expensing-limits-2026",
        "US section 179 expensing limits for taxable years beginning in 2026: maximum deduction, phase-out threshold and SUV cap",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "depreciation", "section-179", "limits", "obbba", "rev-proc-2025-32"],
        ["tax-demo", "tax-filing-demo", "accounts-payable", "financial-reporting"],
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": lim.rows},
        lim.vectors("bonus_depreciation_percent"),
        lim.evidence,
        [{"statistic": "count", "expected": len(lim.rows), "tolerance": 0}],
        (
            "Section 179 lets a business expense the cost of qualifying property in the year it is placed in service "
            "instead of depreciating it. For taxable years beginning in 2026 the maximum is reduced dollar for dollar "
            "by the cost of section 179 property placed in service above the phase-out threshold, and the cost of a "
            "sport utility vehicle counts only up to its own cap. Public Law 119-21 raised the base amounts for "
            "property placed in service in taxable years beginning after 2024; Rev. Proc. 2025-32 indexes them."
        ),
    )


# --------------------------------------------------------------------------------------
# Publication 15-T and Publication 15: withholding and payroll taxes
# --------------------------------------------------------------------------------------

WITHHOLDING_LINE = re.compile(
    r"^\$(?P<a>[\d,]+) (?:\$(?P<b>[\d,]+) )?\$(?P<c>[\d,.]+) (?P<d>\d+)% \$(?P<e>[\d,]+) "
    r"\$(?P<a2>[\d,]+) (?:\$(?P<b2>[\d,]+) )?\$(?P<c2>[\d,.]+) (?P<d2>\d+)% \$(?P<e2>[\d,]+)$"
)
SCHEDULE_HEADINGS = {
    "Married Filing Jointly Married Filing Jointly": "married_filing_jointly",
    "Single or Married Filing Separately Single or Married Filing Separately": "single_or_married_filing_separately",
    "Head of Household Head of Household": "head_of_household",
}


def withholding(src: Source) -> dict:
    page = next(p for p in src.pages if "2026 Percentage Method Tables for Automated Payroll Systems" in p and "STANDARD Withholding Rate Schedules" in p)
    schedules: dict[str, dict[str, list[dict]]] = {"standard": {}, "checkbox": {}}
    lines: dict[str, list[str]] = {}
    current = None
    for line in (collapse(raw) for raw in page.splitlines()):
        if line in SCHEDULE_HEADINGS:
            current = SCHEDULE_HEADINGS[line]
            schedules["standard"][current], schedules["checkbox"][current], lines[current] = [], [], []
            continue
        found = WITHHOLDING_LINE.match(line)
        if found and current:
            for name, suffix in (("standard", ""), ("checkbox", "2")):
                upper = found.group("b" + suffix)
                schedules[name][current].append(
                    {
                        "at_least": money(found.group("a" + suffix)),
                        "less_than": money(upper) if upper else None,
                        "base": money(found.group("c" + suffix)),
                        "rate_percent": int(found.group("d" + suffix)),
                        "excess_over": money(found.group("e" + suffix)),
                    }
                )
            lines[current].append(line)
    if sorted(len(rows) for table in schedules.values() for rows in table.values()) != [8] * 6:
        raise ValueError("unexpected withholding schedule shape")
    sheet = src.section("Worksheet 1A. Employer", "Worksheet 1B.")
    adjust = src.match(r"If the box is not checked, enter (\$[\d,]+) if the taxpayer is married filing jointly or (\$[\d,]+) otherwise", sheet)
    allowance = src.match(r"1k Multiply line 1j by (\$[\d,]+)", sheet)
    periods_found = src.match(r"Table 3 Semiannually Quarterly Monthly Semimonthly Biweekly Weekly Daily (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)", sheet)
    names = ["semiannually", "quarterly", "monthly", "semimonthly", "biweekly", "weekly", "daily"]
    pay_periods = {"annually": 1, **{name: int(periods_found.group(i + 1)) for i, name in enumerate(names)}}
    parameters = {
        "tax_year": "2026",
        "currency": "USD",
        "pay_periods": pay_periods,
        "step2_adjustment": {"married_filing_jointly": money(adjust.group(1)), "other": money(adjust.group(2))},
        "allowance_value": money(allowance.group(1)),
        "schedules": schedules,
    }
    items = [
        src.ev("page 10, Worksheet 1A, line 1g", adjust.group(1), "currency:USD", adjust.group(0)),
        src.ev("page 10, Worksheet 1A, line 1k", allowance.group(1), "currency:USD", allowance.group(0)),
        src.ev("page 10, Worksheet 1A, Table 3 (pay periods per year)", periods_found.group(0), "text", periods_found.group(0)),
    ]
    for status, status_lines in lines.items():
        for line in status_lines:
            items.append(src.ev(f"page 12, 2026 Annual Percentage Method tables, {status.replace('_', ' ')} (standard columns A-E, then checkbox columns A-E)", line.split(" ")[0], "currency:USD", line))
    vectors = []
    for name in ("standard", "checkbox"):
        for status, rows in schedules[name].items():
            for row in rows[1:]:
                vectors.append(
                    {
                        "input": {"adjusted_annual_wage": row["at_least"], "filing_status": status, "checkbox": name == "checkbox"},
                        "expected": f"{Decimal(str(row['base'])):.2f}",
                        "origin": "source",
                        "note": f"{name} schedule row starting at ${row['at_least']:,}: column C",
                    }
                )
    # Worked cases built from the parsed tables, independent of the rule's code path.
    single = schedules["standard"]["single_or_married_filing_separately"]
    biweekly = pay_periods["biweekly"]
    annual = Decimal(2000) * biweekly - Decimal(str(parameters["step2_adjustment"]["other"]))
    row = next(r for r in single if r["at_least"] <= annual and (r["less_than"] is None or annual < r["less_than"]))
    expected = (Decimal(str(row["base"])) + (annual - Decimal(str(row["excess_over"]))) * row["rate_percent"] / 100) / biweekly
    vectors.append({"input": {"wages": 2000, "pay_frequency": "biweekly", "filing_status": "single"}, "expected": f"{expected.quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')}", "origin": "derived", "note": "Worksheet 1A: $2,000 biweekly, single, Step 2 not checked, no other W-4 entries"})
    joint = schedules["standard"]["married_filing_jointly"]
    monthly = pay_periods["monthly"]
    annual = Decimal(9000) * monthly - Decimal(str(parameters["step2_adjustment"]["married_filing_jointly"]))
    row = next(r for r in joint if r["at_least"] <= annual and (r["less_than"] is None or annual < r["less_than"]))
    expected = (Decimal(str(row["base"])) + (annual - Decimal(str(row["excess_over"]))) * row["rate_percent"] / 100) / monthly - Decimal(4400) / monthly
    vectors.append({"input": {"wages": 9000, "pay_frequency": "monthly", "filing_status": "married_filing_jointly", "step3": 4400}, "expected": f"{expected.quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')}", "origin": "derived", "note": "Worksheet 1A: $9,000 monthly, married filing jointly, $4,400 of Step 3 credits"})
    vectors.append({"input": {"wages": 300, "pay_frequency": "weekly", "filing_status": "married_filing_jointly"}, "expected": "0.00", "origin": "derived", "note": "annualised wages below the joint 0% row's ceiling once the Step 2 adjustment is subtracted"})
    return base_entry(
        "us-federal-income-tax-withholding-percentage-method-2026",
        "US federal income tax withholding for 2026: Publication 15-T percentage method tables and Worksheet 1A for automated payroll",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "payroll", "withholding", "form-w-4", "limits", "publication-15-t"],
        PAYROLL_USES,
        "almanac.rules.us_fit_withholding",
        parameters,
        vectors,
        items,
        [
            {"statistic": "count", "expected": 48, "tolerance": 0},
            {"statistic": "top_rate[standard,married_filing_jointly]", "expected": schedules["standard"]["married_filing_jointly"][-1]["rate_percent"], "tolerance": 0},
            {"statistic": "rows[checkbox,head_of_household]", "expected": 8, "tolerance": 0},
        ],
        (
            "The 2026 Annual Percentage Method tables of IRS Publication 15-T for automated payroll systems, both the "
            "STANDARD Withholding Rate Schedules (Form W-4 Step 2 not checked, Forms W-4 from 2019 or earlier, and "
            "Forms W-4P) and the Form W-4 Step 2 Checkbox schedules, with the fixed amounts Worksheet 1A uses: the "
            "Step 2 adjustment subtracted when the box is not checked, the value of one allowance on a pre-2020 Form "
            "W-4, and the pay periods per year. The rule implements Worksheet 1A: annualise the period's wages, add "
            "Step 4(a), subtract Step 4(b) and the Step 2 adjustment, look up the row, divide by the pay periods, "
            "subtract Step 3 credits per period and add Step 4(c). It returns cents; Publication 15-T allows "
            "employers to round withholding to whole dollars if they do so consistently. Source vectors are table "
            "rows; worksheet vectors are computed from the parsed tables. The cited URL is the current edition of "
            "the publication, which the IRS replaces with the 2027 edition at the end of 2026."
        ),
    )


def payroll_taxes(p15: Source, futa_rate: Source, futa_base: Source) -> dict:
    lim = Limits(p15)
    lim.add("social_security_wage_base", r"The social security wage base limit is (\$[\d,]+)\. The tax rate for Medicare", "page 29, section 9, Tax rates and the social security wage base limit", "maximum wages subject to social security (OASDI) tax in 2026, employee and employer each")
    lim.add("futa_rate", r"For 2026, the FUTA tax rate is ([\d.]+%)", "page 51, section 14, Figuring FUTA tax", "federal unemployment tax rate before the state credit", unit="percent")
    lim.add("futa_wage_base", r"The tax applies to the first (\$[\d,]+) you pay to each em- ?ployee as wages during the year", "page 51, section 14, Figuring FUTA tax", "FUTA wages per employee per year")
    lim.add("futa_maximum_state_credit", r"The credit may be as much as ([\d.]+%) of FUTA taxable wages", "page 51, section 14, Figuring FUTA tax", "maximum credit for state unemployment contributions", unit="percent")
    lim.add("futa_rate_after_maximum_credit", r"the FUTA tax rate after credit is ([\d.]+%)", "page 51, section 14, Figuring FUTA tax", "FUTA rate after the maximum state credit (no credit reduction)", unit="percent")
    lim.add("supplemental_wage_flat_rate", r"The withholding rate on supplemental wages remains (\d+%) \(37% if supple- ?mental wages", "page 2, What's New, Withholding on supplemental wages", "optional flat withholding rate on supplemental wages up to $1 million in the year", unit="percent")
    lim.add("supplemental_wage_rate_over_1_million", r"the excess is sub- ?ject to withholding at (\d+%) \(or the highest rate of income tax for the year\)", "page 24, section 7", "mandatory withholding rate on supplemental wages above $1 million in the year", unit="percent")
    lim.add("supplemental_wage_mandatory_threshold", r"supplemental wages paid to any one employee during the calendar year exceed (\$[\d,]+ million)", "page 24, section 7", "supplemental wages in the calendar year above which the mandatory rate applies", parse=lambda t: int(Decimal(t.replace("$", "").replace(" million", "")) * 1000000))
    lim.add("backup_withholding_rate", r"The backup withholding rate re- ?mains (\d+%)", "page 2, What's New, Backup withholding", "backup withholding rate", unit="percent")
    lim.add("household_worker_cash_wage_threshold", r"Social security and Medicare taxes apply to the wages of household workers you pay (\$[\d,]+) or more in cash wa- ?ges in 2026", "page 2, What's New", "cash wages to a household worker in 2026 at which social security and Medicare taxes apply")
    lim.add("election_worker_threshold", r"election workers who are paid (\$[\d,]+) or more in cash or an equivalent form of compensation in 2026", "page 2, What's New", "pay to an election worker in 2026 at which social security and Medicare taxes apply")
    rate_value, rate_item = fact(futa_rate, r"equal to (6 percent) of the total wages \(as defined in section 3306\(b\)\) paid by such employer", "26 U.S.C. 3301", unit="percent", parse=lambda t: float(t.split()[0]))
    base_value, base_item = fact(futa_base, r"\(other than remuneration referred to in the succeeding paragraphs of this subsection\) equal to (\$[\d,]+) with respect to employment", "26 U.S.C. 3306(b)(1)")
    if rate_value != lim.rows["futa_rate"]["value"] or base_value != lim.rows["futa_wage_base"]["value"]:
        raise ValueError("Publication 15 and the US Code disagree on FUTA")
    lim.rows["futa_rate"]["statute"] = "26 U.S.C. 3301"
    lim.rows["futa_wage_base"]["statute"] = "26 U.S.C. 3306(b)(1)"
    lim.evidence += [rate_item, base_item]
    return base_entry(
        "us-payroll-tax-wage-bases-and-withholding-rates-2026",
        "US federal payroll tax limits for 2026: social security wage base, FUTA rate and wage base, supplemental and backup withholding",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "payroll", "payroll-tax", "social-security", "futa", "supplemental-wages", "limits", "publication-15"],
        PAYROLL_USES,
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "currency": "USD", "rows": lim.rows},
        lim.vectors("state_unemployment_wage_base"),
        lim.evidence,
        [
            {"statistic": "count", "expected": len(lim.rows), "tolerance": 0},
            {"statistic": "value[social_security_wage_base,value]", "expected": lim.rows["social_security_wage_base"]["value"], "tolerance": 0},
            {"statistic": "value[futa_rate,value]", "expected": lim.rows["futa_rate"]["value"], "tolerance": 0},
        ],
        (
            "Employer payroll figures for 2026 from IRS Publication 15 (Circular E): the social security wage base "
            "(wages above it are free of the 6.2% OASDI tax; Medicare tax has no wage base), the FUTA tax rate, wage "
            "base and maximum credit for state unemployment contributions, the flat and mandatory withholding rates on "
            "supplemental wages, the backup withholding rate, and the cash-pay thresholds for household and "
            "election workers. The FUTA rate and wage base are cross-checked against 26 U.S.C. 3301 and 3306(b)(1). "
            "FICA rates and the Additional Medicare Tax thresholds are in us-fica-tax-rates. The Publication 15 URL "
            "is the current edition, which the IRS replaces each December."
        ),
        [{"parameter": "rows.supplemental_wage_mandatory_threshold.value", "value": 1000000, "method": "derived", "rationale": "Publication 15 writes the threshold as '$1 million'; the row stores it in dollars."}],
    )


def mileage(src: Source) -> dict:
    lim = Limits(src)
    lim.add("business", r"The standard mileage rate for transportation or travel expenses for 2026 is ([\d.]+) cents per mile", "page 3, section 3", "business use, cents per mile", unit="USD cents per mile")
    lim.add("charitable", r"The standard mileage rate is ([\d.]+) cents per mile for use of an automobile in rendering gratuitous services to a charitable organization", "page 4, section 3", "charitable volunteer use, cents per mile (fixed by section 170(i))", unit="USD cents per mile")
    lim.add("medical_and_moving", r"The standard mileage rate for 2026 is ([\d.]+) cents per mile for use of an automobile: \(1\) for medical care", "page 4, section 3", "medical care, and moves deductible under section 217(g), cents per mile", unit="USD cents per mile")
    lim.add("depreciation_component", r"and ([\d.]+) cents per mile for 2026\. See section 4\.04", "page 4, section 4", "portion of the business rate treated as depreciation for basis reduction, cents per mile", unit="USD cents per mile")
    lim.add("favr_maximum_automobile_cost", r"the standard automobile cost may not exceed (\$[\d,]+) for automobiles", "page 5, section 5", "maximum standard automobile cost under a FAVR allowance plan")
    lim.add("employer_vehicle_maximum_value", r"first made available to employees in calendar year 2026 is (\$[\d,]+)", "page 5, section 6", "maximum fair market value of an employer-provided automobile for the fleet-average and cents-per-mile valuation rules")
    return base_entry(
        "us-standard-mileage-rates-2026",
        "US IRS standard mileage rates for 2026: business, charitable, medical and moving, with FAVR and vehicle valuation caps (Notice 2026-10)",
        "tax",
        "2026-01-01",
        "2026-12-31",
        ["tax", "payroll", "mileage", "expenses", "limits", "notice-2026-10"],
        ["payroll-demo", "hr-demo", "tax-demo", "fleet-demo", "accounts-payable"],
        "almanac.rules.lookup_table",
        {"tax_year": "2026", "rows": lim.rows},
        lim.vectors("per_diem_lodging"),
        lim.evidence,
        [{"statistic": "count", "expected": len(lim.rows), "tolerance": 0}, {"statistic": "value[business,value]", "expected": lim.rows["business"]["value"], "tolerance": 0}],
        (
            "Optional standard mileage rates from IRS Notice 2026-10 for costs of operating an automobile from "
            "January 1, 2026: business, charitable (set by statute), and medical or qualifying moving use, in cents "
            "per mile; the depreciation component of the business rate used to reduce basis; the maximum standard "
            "automobile cost for a fixed and variable rate (FAVR) plan; and the maximum value of an employer-provided "
            "automobile first made available in 2026 for the fleet-average and vehicle cents-per-mile valuation "
            "rules. Unreimbursed employee travel remains non-deductible as an itemised deduction except for the "
            "groups the notice lists. Reimbursement up to the business rate is the usual accountable-plan pattern."
        ),
    )


def macrs(src: Source) -> dict:
    page = next(p for p in src.pages if "Table A-1. 3-, 5-, 7-, 10-, 15-, and 20-Year Property" in p)
    block = page[page.index("3-year 5-year 7-year 10-year 15-year 20-year"): page.index("Table A-2.")]
    tokens = block.split()[6:]
    values = [t for t in tokens if "." in t]
    periods = ["3-year", "5-year", "7-year", "10-year", "15-year", "20-year"]
    columns: list[list[str]] = []
    for token in values:
        if token.endswith("%"):
            columns.append([])
        columns[-1].append(token)
    if [len(c) for c in columns] != [4, 6, 8, 11, 16, 21]:
        raise ValueError(f"unexpected Table A-1 shape {[len(c) for c in columns]}")
    rates = {period: [float(t.rstrip("%")) for t in column] for period, column in zip(periods, columns)}
    for period, column in rates.items():
        if abs(sum(column) - 100) > 0.011:
            raise ValueError(f"{period} column sums to {sum(column)}")
    items = [src.ev(f"page 71, Appendix A, Table A-1, {period} column", column[0], "percent", " ".join(column)) for period, column in zip(periods, columns)]
    first = src.match(r"Multiply line 13 by line 14\. This is your MACRS depreciation deduction \.+ (\$[\d,]+)")
    items.append(src.ev("page 41, MACRS Worksheet example (7-year office furniture, $10,000)", first.group(1), "currency:USD", "This is your MACRS depreciation deduction"))
    schedule = src.section("Year Basis Percentage Deduction", "Examples The following examples")
    later = list(re.finditer(r"(\d{4}) \.+ \$?([\d,]+) ([\d.]+)%? \$?([\d,]+)", schedule))
    if len(later) != 7:
        raise ValueError("unexpected MACRS example schedule")
    for found in later:
        items.append(src.ev("page 41, example, deductions for later years", found.group(4), "currency:USD", found.group(0)))
    casualty = src.match(r"your depreciation was (\$[\d,]+) \((\$[\d,]+) ×")
    items.append(src.ev("page 47, example of a casualty loss on 7-year property", casualty.group(1), "currency:USD", f"your depreciation was {casualty.group(1)}"))
    vectors = [{"input": {"basis": 10000, "recovery_period": "7-year", "year": 1}, "expected": money(first.group(1)), "origin": "source", "note": "Publication 946 MACRS Worksheet example, line 15"}]
    for year, found in enumerate(later, start=2):
        vectors.append({"input": {"basis": money(found.group(2)), "recovery_period": "7-year", "year": year}, "expected": money(found.group(4)), "origin": "source", "note": f"example's deduction for recovery year {year} at {found.group(3)}%"})
    vectors.append({"input": {"basis": money(casualty.group(2)), "recovery_period": "7-year", "year": 1}, "expected": money(casualty.group(1)), "origin": "source", "note": "year-one deduction on 7-year property, rounded to the dollar"})
    vectors += [{"input": {"recovery_period": period, "year": 1}, "expected": rates[period][0], "origin": "source", "note": "Table A-1, year 1"} for period in periods]
    vectors.append({"input": {"recovery_period": "20-year", "year": 21}, "expected": rates["20-year"][-1], "origin": "source", "note": "Table A-1, last half-year"})
    vectors.append({"input": {"recovery_period": "5-year", "year": 7}, "expected": 0.0, "origin": "derived", "note": "after the recovery period"})
    return base_entry(
        "us-macrs-gds-half-year-depreciation-rates",
        "US MACRS GDS depreciation percentages, half-year convention, 3- to 20-year property (IRS Publication 946, Table A-1)",
        "tax",
        "1987-01-01",
        None,
        ["tax", "depreciation", "macrs", "fixed-assets", "publication-946"],
        ["tax-demo", "tax-filing-demo", "financial-reporting", "accounts-payable"],
        "almanac.rules.us_macrs_depreciation",
        {"system": "GDS", "method": "200% or 150% declining balance switching to straight line", "convention": "half-year", "rates": rates},
        vectors,
        items,
        [
            {"statistic": "count", "expected": 6, "tolerance": 0},
            {"statistic": "years[7-year]", "expected": 8, "tolerance": 0},
            {"statistic": "total[20-year]", "expected": 100, "tolerance": 0.011},
        ],
        (
            "Table A-1 of IRS Publication 946: the percentage of unadjusted basis deducted in each recovery year for "
            "3-, 5-, 7-, 10-, 15- and 20-year property under the General Depreciation System with the half-year "
            "convention, which applies when no more than 40% of the year's depreciable basis is placed in service in "
            "the last quarter. A recovery period of n years spans n+1 tax years because of the half-year convention. "
            "Multiply the unadjusted basis (after any section 179 deduction and special allowance) by the year's "
            "percentage; the publication's examples round the result to whole dollars. Mid-quarter and real property "
            "tables are separate. The cited URL is the current (2025) edition of the publication; the percentages "
            "apply to property placed in service after 1986."
        ),
        [{"parameter": "valid_from", "value": "1987-01-01", "method": "derived", "rationale": "MACRS applies to property placed in service after 1986, as the publication's scope states; the table itself carries no date."}],
    )


# --------------------------------------------------------------------------------------
# Notice 2025-67, Rev. Proc. 2025-19, Rev. Proc. 2025-25: retirement and health limits
# --------------------------------------------------------------------------------------


def retirement(src: Source) -> dict:
    lim = Limits(src)
    inc = r"is increased from \$[\d,]+ to (\$[\d,]+)"
    lim.add("elective_deferral_402g", r"which includes elective deferrals made to the Thrift Savings Plan, " + inc, "page 1", "401(k), 403(b) and Thrift Savings Plan elective deferral limit (section 402(g)(1))")
    lim.add("governmental_457_deferral", r"state and local governments and tax-exempt organizations " + inc + r"\. The limitation under section 414\(v\)\(2\)\(B\)\(i\)", "page 1", "457(b) deferral limit (section 457(e)(15))")
    lim.add("catch_up_age_50", r"that generally applies for individuals aged 50 or over " + inc + r"\. The limitation under section 414\(v\)\(2\)\(E\)\(i\)", "page 1", "catch-up contribution, age 50 or over, plans other than SIMPLE (section 414(v)(2)(B)(i))")
    lim.add("catch_up_age_60_to_63", r"age 60, 61, 62, or 63 in 2026 remains (\$[\d,]+)\. The Roth catch-up", "page 1 to 2", "catch-up contribution for ages 60 to 63, plans other than SIMPLE (section 414(v)(2)(E)(i))")
    lim.add("roth_catch_up_wage_threshold", r"must be designated as Roth contributions, " + inc, "page 2", "prior-year FICA wages above which catch-up contributions must be Roth (section 414(v)(7)(A))")
    lim.add("simple_deferral", r"elective contributions under a SIMPLE 401\(k\) plan " + inc, "page 2", "SIMPLE IRA and SIMPLE 401(k) salary reduction limit (section 408(p)(2)(E)(i)(III))")
    lim.add("simple_deferral_higher", r"The limitation for certain of those accounts or plans under section 408\(p\)\(2\)\(E\)\(i\)\(I\) or \(II\) " + inc, "page 2", "higher SIMPLE deferral limit for certain plans (section 408(p)(2)(E)(i)(I) or (II))")
    simple_catch_up = src.section("The limitation under section 414(v)(2)(B)(ii)", "The limitation under section 414(v)(2)(E)(ii)")
    lim.add("simple_catch_up_age_50", r"that generally applies for individuals aged 50 or over " + inc, "page 2", "SIMPLE catch-up, age 50 or over (section 414(v)(2)(B)(ii))", simple_catch_up)
    lim.add("simple_catch_up_age_50_certain_plans", r"that generally applies for individuals aged 50 or over remains (\$[\d,]+)", "page 2", "SIMPLE catch-up, age 50 or over, for the accounts or plans of section 414(v)(2)(B)(iii)", src.section("The limitation under section 414(v)(2)(B)(iii)", "The limitation under section 401(k)(16)"))
    lim.add("simple_catch_up_age_60_to_63", r"that applies for individuals who attain age 60, 61, 62, or 63 in 2026 remains (\$[\d,]+)\. The limitation under section 414\(v\)\(2\)\(B\)\(iii\)", "page 2", "SIMPLE catch-up for ages 60 to 63 (section 414(v)(2)(E)(ii))")
    lim.add("defined_contribution_415c", r"The limitation for defined contribution plans under section 415\(c\)\(1\)\(A\) " + inc.replace("is increased from", "is increased in 2026 from"), "page 1", "annual additions limit for defined contribution plans (section 415(c)(1)(A))")
    lim.add("defined_benefit_415b", r"the limitation on the annual benefit under a defined benefit plan under section 415\(b\)\(1\)\(A\) of the Code " + inc, "page 1", "annual benefit limit for defined benefit plans (section 415(b)(1)(A))")
    lim.add("compensation_limit", r"408\(k\)\(3\)\(C\), and 408\(k\)\(6\)\(D\)\(ii\) " + inc, "page 2", "annual compensation limit (section 401(a)(17))")
    lim.add("highly_compensated_employee_threshold", r"under section 414\(q\)\(1\)\(B\) remains (\$[\d,]+)", "page 2", "highly compensated employee compensation threshold (section 414(q)(1)(B))")
    lim.add("key_employee_threshold", r"for top-heavy plan purposes " + inc, "page 2", "key employee officer compensation threshold (section 416(i)(1)(A)(i))")
    lim.add("sep_minimum_compensation", r"regarding simplified employee pensions " + inc, "page 3", "SEP participation compensation threshold (section 408(k)(2)(C))")
    lim.add("ira_contribution", r"which limits the amount of an individual.s deductible qualified retirement contributions for a taxable year " + inc, "page 4", "IRA contribution limit (section 219(b)(5)(A))")
    lim.add("ira_catch_up_age_50", r"for individuals who have attained age 50 before the close of the taxable year " + inc, "page 4", "IRA catch-up contribution, age 50 or over (section 219(b)(5)(B))")
    lim.add("traditional_ira_deduction_phaseout_single_start", r"have adjusted gross incomes \(as defined in section 219\(g\)\(3\)\(A\)\) between (\$[\d,]+) and \$[\d,]+, increased", "page 4", "traditional IRA deduction phase-out start, single or head of household active participant")
    lim.add("traditional_ira_deduction_phaseout_single_end", r"have adjusted gross incomes \(as defined in section 219\(g\)\(3\)\(A\)\) between \$[\d,]+ and (\$[\d,]+), increased", "page 4", "traditional IRA deduction phase-out end, single or head of household active participant")
    lim.add("traditional_ira_deduction_phaseout_joint_start", r"contribution is an active participant, the income phase-out range is between (\$[\d,]+) and", "page 4", "traditional IRA deduction phase-out start, joint filer who is an active participant")
    lim.add("traditional_ira_deduction_phaseout_joint_end", r"contribution is an active participant, the income phase-out range is between \$[\d,]+ and (\$[\d,]+),", "page 4", "traditional IRA deduction phase-out end, joint filer who is an active participant")
    lim.add("roth_ira_phaseout_joint_start", r"making contributions to a Roth IRA is between (\$[\d,]+) and \$[\d,]+ for married couples filing jointly", "page 5", "Roth IRA contribution phase-out start, married filing jointly")
    lim.add("roth_ira_phaseout_joint_end", r"making contributions to a Roth IRA is between \$[\d,]+ and (\$[\d,]+) for married couples filing jointly", "page 5", "Roth IRA contribution phase-out end, married filing jointly")
    lim.add("roth_ira_phaseout_single_start", r"For singles and heads of household, the income phase-out range is between (\$[\d,]+) and \$[\d,]+,", "page 5", "Roth IRA contribution phase-out start, single and head of household")
    lim.add("roth_ira_phaseout_single_end", r"For singles and heads of household, the income phase-out range is between \$[\d,]+ and (\$[\d,]+),", "page 5", "Roth IRA contribution phase-out end, single and head of household")
    lim.add("simple_additional_nonelective", r"to a SIMPLE retirement account or a SIMPLE 401\(k\) plan " + inc, "page 6", "additional nonelective contribution limit for SIMPLE plans (section 408(p)(2)(A)(iv))")
    rows = lim.rows
    return base_entry(
        "us-retirement-plan-limits-2026",
        "US retirement plan and IRA limits for 2026: 401(k), 403(b), 457, catch-up, SIMPLE, 415, compensation and HCE (Notice 2025-67)",
        "pensions",
        "2026-01-01",
        "2026-12-31",
        ["pensions", "retirement", "401k", "ira", "payroll", "benefits", "limits", "notice-2025-67"],
        [*BENEFIT_USES, "pensions", "financial-planning"],
        "almanac.rules.lookup_table",
        {"plan_year": "2026", "currency": "USD", "rows": rows},
        lim.vectors("hsa_contribution"),
        lim.evidence,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[elective_deferral_402g,value]", "expected": rows["elective_deferral_402g"]["value"], "tolerance": 0},
            {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "Cost-of-living adjusted retirement plan limits for 2026 from IRS Notice 2025-67, effective January 1, "
            "2026: elective deferral limits for 401(k), 403(b), the Thrift Savings Plan and governmental 457(b) "
            "plans; catch-up contributions at age 50 and the higher catch-up for those who attain 60 to 63 during "
            "the year; the wage threshold above which catch-ups must be Roth; SIMPLE limits; the section 415 "
            "defined contribution and defined benefit limits; the compensation limit; the highly compensated and key "
            "employee thresholds; the IRA contribution and catch-up limits; and the traditional and Roth IRA "
            "phase-out ranges. The highly compensated employee test compares compensation in the look-back year "
            "with the threshold."
        ),
    )


def hsa(src: Source, revproc: Source) -> dict:
    lim = Limits(src)
    lim.add("hsa_contribution_self_only", r"deductible health plan is (\$[\d,]+)\. For calendar year 2026, the annual limitation on deductions under § 223\(b\)\(2\)\(B\)", "page 1 to 2, section 2.01(1)", "annual HSA contribution limit, self-only coverage (section 223(b)(2)(A))")
    lim.add("hsa_contribution_family", r"for an individual with family coverage under a high deductible health plan is (\$[\d,]+)", "page 2, section 2.01(1)", "annual HSA contribution limit, family coverage (section 223(b)(2)(B))")
    lim.add("hdhp_minimum_deductible_self_only", r"an annual deductible that is not less than (\$[\d,]+) for self-only coverage or \$[\d,]+ for family coverage", "page 2, section 2.01(2)", "HDHP minimum annual deductible, self-only")
    lim.add("hdhp_minimum_deductible_family", r"an annual deductible that is not less than \$[\d,]+ for self-only coverage or (\$[\d,]+) for family coverage", "page 2, section 2.01(2)", "HDHP minimum annual deductible, family")
    lim.add("hdhp_out_of_pocket_maximum_self_only", r"do not exceed (\$[\d,]+) for self-only coverage or \$[\d,]+ for family coverage", "page 2, section 2.01(2)", "HDHP maximum annual out-of-pocket expenses, self-only")
    lim.add("hdhp_out_of_pocket_maximum_family", r"do not exceed \$[\d,]+ for self-only coverage or (\$[\d,]+) for family coverage", "page 2, section 2.01(2)", "HDHP maximum annual out-of-pocket expenses, family")
    lim.add("excepted_benefit_hra_maximum", r"for an excepted benefit HRA under § 54\.9831-1\(c\)\(3\)\(viii\) is (\$[\d,]+)", "page 2, section 2.02", "maximum newly available amount for an excepted benefit HRA, plan years beginning in 2026")
    msa = revproc.section(".28 Medical Savings Accounts. (1)", ".29 Interest on Education Loans.")
    lim.add("msa_hdhp_deductible_self_only_minimum", r"for self-only coverage, a health plan that has an annual deductible that is not less than (\$[\d,]+) and not more than", "Rev. Proc. 2025-32, page 22, section 4.28(1)", "Archer MSA HDHP minimum deductible, self-only (section 220(c)(2)(A))", msa, src=revproc)
    lim.add("msa_hdhp_deductible_self_only_maximum", r"for self-only coverage, a health plan that has an annual deductible that is not less than \$[\d,]+ and not more than (\$[\d,]+)", "Rev. Proc. 2025-32, page 22, section 4.28(1)", "Archer MSA HDHP maximum deductible, self-only", msa, src=revproc)
    lim.add("msa_hdhp_deductible_family_minimum", r"for family coverage, a health plan that has an annual deductible that is not less than (\$[\d,]+) and not more than", "Rev. Proc. 2025-32, page 22, section 4.28(2)", "Archer MSA HDHP minimum deductible, family", msa, src=revproc)
    lim.add("msa_hdhp_deductible_family_maximum", r"for family coverage, a health plan that has an annual deductible that is not less than \$[\d,]+ and not more than (\$[\d,]+)", "Rev. Proc. 2025-32, page 22, section 4.28(2)", "Archer MSA HDHP maximum deductible, family", msa, src=revproc)
    rows = lim.rows
    return base_entry(
        "us-hsa-and-hdhp-limits-2026",
        "US health savings account contribution limits and high deductible health plan thresholds for 2026 (Rev. Proc. 2025-19)",
        "benefits",
        "2026-01-01",
        "2026-12-31",
        ["benefits", "health", "hsa", "hdhp", "payroll", "limits", "rev-proc-2025-19"],
        [*BENEFIT_USES, "health-demo"],
        "almanac.rules.lookup_table",
        {"calendar_year": "2026", "currency": "USD", "rows": rows},
        lim.vectors("hsa_catch_up_age_55"),
        lim.evidence,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[hsa_contribution_family,value]", "expected": rows["hsa_contribution_family"]["value"], "tolerance": 0},
        ],
        (
            "Health savings account amounts for calendar year 2026 from Rev. Proc. 2025-19: the annual contribution "
            "limits for self-only and family HDHP coverage, and the minimum deductible and maximum out-of-pocket "
            "expenses that define a high deductible health plan; plus the maximum an excepted benefit HRA may make "
            "newly available for plan years beginning in 2026. The Archer MSA deductible ranges for 2026 come from "
            "Rev. Proc. 2025-32. The additional HSA contribution for account holders aged 55 or over is statutory "
            "and not part of this entry."
        ),
    )


def aca(src: Source) -> dict:
    sec = src.section(".01 Applicable Percentage Table for 2026.", ".02 Required Contribution Percentage for 2026.")
    bands = [
        ("under_133", "Less than 133%"),
        ("133_to_150", "At least 133% but less than 150%"),
        ("150_to_200", "At least 150% but less than 200%"),
        ("200_to_250", "At least 200% but less than 250%"),
        ("250_to_300", "At least 250% but less than 300%"),
        ("300_to_400", "At least 300% but not more than 400%"),
    ]
    rows, items = {}, []
    for key, label in bands:
        found = src.match(re.escape(label) + r" ([\d.]+%) ([\d.]+%)", sec)
        rows[key] = {"household_income_band": label + " of the Federal poverty line", "initial_percent": percent(found.group(1)), "final_percent": percent(found.group(2))}
        items.append(src.ev("page 2, section 3.01, Applicable Percentage Table", found.group(2), "percent", found.group(0)))
    required, item = fact(src, r"§ 36B\(c\)\(2\)\(C\)\(i\)\(II\) and § 1\.36B-2\(c\)\(3\)\(v\)\(C\) is ([\d.]+%)", "page 2, section 3.02", unit="percent", parse=percent)
    items.append(item)
    rows["required_contribution_percentage"] = {"household_income_band": "employer coverage affordability test", "initial_percent": required, "final_percent": required}
    vectors = [{"input": {"key": key, "column": "final_percent"}, "expected": rows[key]["final_percent"], "origin": "source"} for key in rows]
    vectors.append({"input": {"key": "133_to_150", "column": "initial_percent"}, "expected": rows["133_to_150"]["initial_percent"], "origin": "source"})
    vectors.append({"input": "over_400", "expected": False, "origin": "derived", "note": "no applicable percentage is published above 400% of the poverty line for 2026"})
    return base_entry(
        "us-aca-affordability-and-premium-tax-credit-percentages-2026",
        "US ACA premium tax credit applicable percentage table and employer coverage affordability percentage for 2026 (Rev. Proc. 2025-25)",
        "benefits",
        "2026-01-01",
        "2026-12-31",
        ["benefits", "health", "aca", "affordability", "premium-tax-credit", "limits", "rev-proc-2025-25"],
        [*BENEFIT_USES, "health-demo"],
        "almanac.rules.lookup_table",
        {"year": "2026", "rows": rows},
        vectors,
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[required_contribution_percentage,final_percent]", "expected": required, "tolerance": 0},
            {"statistic": "max[final_percent]", "expected": max(r["final_percent"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "Rev. Proc. 2025-25 for taxable and plan years beginning in 2026. The applicable percentage table of "
            "section 36B(b)(3)(A)(i) gives, for each band of household income as a percentage of the Federal "
            "poverty line, the share of income a household is expected to contribute to benchmark Marketplace "
            "coverage; within a band the percentage rises from the initial to the final figure. The required "
            "contribution percentage is the employer-coverage affordability threshold: an employee's required "
            "contribution for self-only coverage above this share of household income makes the offer unaffordable "
            "for premium tax credit purposes. The 2026 table stops at 400% of the poverty line. Poverty "
            "guidelines are in us-hhs-poverty-guidelines-2026."
        ),
    )


# --------------------------------------------------------------------------------------
# Federal Register: CMS Medicare and HHS poverty guidelines
# --------------------------------------------------------------------------------------


def medicare_part_b(src: Source) -> dict:
    items = []
    standard, item = fact(src, r"The standard monthly Part B premium rate for all enrollees for 2026 is (\$[\d,]+\.\d\d)", "FR Doc. 2025-20251, summary")
    items.append(item)
    deductible, item = fact(src, r"The Part B deductible for 2026 is (\$[\d,]+\.\d\d) for all Part B beneficiaries", "FR Doc. 2025-20251, summary")
    items.append(item)
    immuno, item = fact(src, r"For 2026, the immunosuppressive drug premium is (\$[\d,]+\.\d\d)", "FR Doc. 2025-20251, summary")
    items.append(item)
    start = src.text.index("<TTITLE>Full Part B Coverage</TTITLE>")
    table = src.text[start: src.text.index("</GPOTABLE>", start)]
    row_pattern = re.compile(r"<ENT I=\"01\">(?P<individual>[^<]+)</ENT> <ENT>(?P<joint>[^<]+)</ENT> <ENT>(?P<irmaa>[$\d.,]+)</ENT> <ENT>(?P<total>[$\d.,]+)</ENT>")
    rows: dict[str, dict] = {}
    for index, found in enumerate(row_pattern.finditer(table), start=1):
        rows[f"tier_{index}"] = {
            "individual_return_magi": found.group("individual"),
            "joint_return_magi": found.group("joint"),
            "income_related_monthly_adjustment": money(found.group("irmaa")),
            "total_monthly_premium": money(found.group("total")),
        }
        items.append(src.ev("FR Doc. 2025-20251, section I, table 'Full Part B Coverage'", found.group("total"), "currency:USD", f"{found.group('joint')}</ENT> <ENT>{found.group('irmaa')}</ENT> <ENT>{found.group('total')}</ENT>"))
    if len(rows) != 6:
        raise ValueError("unexpected IRMAA table shape")
    separate_start = src.text.index("beneficiaries with full Part B coverage who are married and lived with their spouses", start)
    separate = src.text[separate_start: src.text.index("</GPOTABLE>", separate_start)]
    sep_pattern = re.compile(r"<ENT I=\"01\">(?P<individual>[^<]+)</ENT> <ENT>(?P<irmaa>[$\d.,]+)</ENT> <ENT>(?P<total>[$\d.,]+)</ENT>")
    for index, found in enumerate(sep_pattern.finditer(separate), start=1):
        rows[f"married_filing_separately_tier_{index}"] = {
            "individual_return_magi": found.group("individual"),
            "joint_return_magi": None,
            "income_related_monthly_adjustment": money(found.group("irmaa")),
            "total_monthly_premium": money(found.group("total")),
        }
        items.append(src.ev("FR Doc. 2025-20251, section I, full Part B coverage for married beneficiaries filing separately who lived with their spouse", found.group("total"), "currency:USD", f"{found.group('individual')}</ENT> <ENT>{found.group('irmaa')}</ENT> <ENT>{found.group('total')}</ENT>"))
    if rows["tier_1"]["total_monthly_premium"] != standard:
        raise ValueError("standard premium disagrees with the IRMAA table")
    vectors = [{"input": {"key": key, "column": "total_monthly_premium"}, "expected": row["total_monthly_premium"], "origin": "source"} for key, row in rows.items()]
    vectors.append({"input": {"key": "tier_2", "column": "individual_return_magi"}, "expected": rows["tier_2"]["individual_return_magi"], "origin": "source"})
    vectors.append({"input": "tier_7", "expected": False, "origin": "derived", "note": "six income tiers"})
    return base_entry(
        "us-medicare-part-b-premiums-and-irmaa-2026",
        "US Medicare Part B 2026 standard premium, deductible and income-related monthly adjustment amounts (IRMAA) by MAGI tier",
        "healthcare",
        "2026-01-01",
        "2026-12-31",
        ["healthcare", "medicare", "medicare-part-b", "irmaa", "premiums", "benefits", "limits"],
        [*HEALTH_USES, "payroll-demo", "pensions"],
        "almanac.rules.lookup_table",
        {"year": "2026", "currency": "USD", "standard_monthly_premium": standard, "annual_deductible": deductible, "immunosuppressive_drug_premium": immuno, "rows": rows},
        vectors,
        items,
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[total_monthly_premium]", "expected": max(r["total_monthly_premium"] for r in rows.values()), "tolerance": 0},
            {"statistic": "value[tier_1,total_monthly_premium]", "expected": standard, "tolerance": 0},
        ],
        (
            "The CMS notice of the 2026 Medicare Part B premium (FR Doc. 2025-20251, 90 FR, November 19, 2025): the "
            "standard monthly premium, the annual deductible, the immunosuppressive-drug-only premium, and the "
            "income-related monthly adjustment amounts for full Part B coverage. Tiers 1 to 6 apply to beneficiaries "
            "filing individual returns (individual_return_magi) or joint returns (joint_return_magi); the "
            "married_filing_separately tiers apply to married beneficiaries who lived with their spouse at any time "
            "in the year and file separately. Each tier keeps the notice's own wording of its MAGI range; Social "
            "Security uses MAGI from the tax return two years earlier. Source is the Federal Register issue XML on "
            "govinfo, which is machine-readable, so the entry is tier A."
        ),
        tier="A",
    )


def medicare_part_a(src: Source) -> dict:
    lim = Limits(src)
    lim.add("inpatient_hospital_deductible", r"For CY 2026, the inpatient hospital deductible will be (\$[\d,]+)\.", "FR Doc. 2025-20249, summary", "inpatient hospital deductible per benefit period")
    lim.add("hospital_coinsurance_days_61_90", r"The daily coinsurance amounts for CY 2026 will be as follows: (\$[\d,]+) for the 61st through 90th day", "FR Doc. 2025-20249, summary", "daily hospital coinsurance, days 61 to 90 of a benefit period")
    lim.add("lifetime_reserve_day_coinsurance", r"(\$[\d,]+) for lifetime reserve days; and", "FR Doc. 2025-20249, summary", "daily coinsurance for lifetime reserve days")
    lim.add("snf_coinsurance_days_21_100", r"and (\$[\d,]+) for the 21st through 100th day of extended care services in a skilled nursing facility", "FR Doc. 2025-20249, summary", "daily skilled nursing facility coinsurance, days 21 to 100")
    lim.add("premium_uninsured_full", r"who have exhausted other entitlement for the 12 months beginning January 1, 2026, is (\$[\d,]+)", "FR Doc. 2025-20250, section III", "monthly Part A premium for enrollees without enough quarters of coverage")
    lim.add("premium_uninsured_reduced", r"subject to the 45 percent reduction in the monthly premium, is (\$[\d,]+)", "FR Doc. 2025-20250, section III", "reduced monthly Part A premium (45 percent reduction, section 1818(d)(4)(B))")
    rows = lim.rows
    return base_entry(
        "us-medicare-part-a-deductible-coinsurance-and-premiums-2026",
        "US Medicare Part A 2026 inpatient deductible, hospital and skilled nursing coinsurance, and premiums for the uninsured",
        "healthcare",
        "2026-01-01",
        "2026-12-31",
        ["healthcare", "medicare", "medicare-part-a", "deductible", "coinsurance", "benefits", "limits"],
        [*HEALTH_USES, "claims-generation", "insurance"],
        "almanac.rules.lookup_table",
        {"year": "2026", "currency": "USD", "rows": rows},
        lim.vectors("part_b_deductible"),
        lim.evidence,
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": rows["inpatient_hospital_deductible"]["value"], "tolerance": 0}],
        (
            "Medicare Part A amounts for calendar year 2026 from two CMS notices published in the Federal Register on "
            "November 19, 2025: the inpatient hospital deductible per benefit period and the daily coinsurance for "
            "hospital days 61 to 90, lifetime reserve days and skilled nursing facility days 21 to 100 (FR Doc. "
            "2025-20249); and the monthly premium for people who buy Part A because they lack enough quarters of "
            "coverage, full and with the 45 percent reduction (FR Doc. 2025-20250). The statute fixes the "
            "coinsurance amounts as one-fourth, one-half and one-eighth of the deductible. Most beneficiaries pay no "
            "Part A premium. Source is the Federal Register issue XML on govinfo (tier A)."
        ),
        tier="A",
    )


def poverty(src: Source) -> dict:
    titles = [
        ("contiguous_states_and_dc", "2026 Poverty Guidelines for the 48 Contiguous States and the District of Columbia"),
        ("alaska", "2026 Poverty Guidelines for Alaska"),
        ("hawaii", "2026 Poverty Guidelines for Hawaii"),
    ]
    areas, items = {}, []
    for key, title in titles:
        start = src.text.index(f"<TTITLE>{title}</TTITLE>")
        table = src.text[start: src.text.index("</GPOTABLE>", start)]
        guidelines = {}
        for found in re.finditer(r"<ROW> <ENT I=\"01\">(\d+)</ENT> <ENT>(\$?[\d,]+)</ENT> </ROW>", table):
            guidelines[int(found.group(1))] = money(found.group(2))
            items.append(src.ev(f"FR Doc. 2026-00755, table '{title}', {found.group(1)} persons", found.group(2), "currency:USD", found.group(0)))
        if sorted(guidelines) != list(range(1, 9)):
            raise ValueError(f"unexpected guideline rows for {title}")
        after = src.text[src.text.index("</GPOTABLE>", start):]
        extra = src.match(r"For families/households with more than 8 persons, add (\$[\d,]+) for each additional person\.", after[:400])
        items.append(src.ev(f"FR Doc. 2026-00755, note under '{title}'", extra.group(1), "currency:USD", extra.group(0)))
        areas[key] = {"guidelines": guidelines, "additional_person": money(extra.group(1))}
    effective, item = fact(src, r"Effective Date:</E> (January \d+, 2026) unless an office administering a program", "FR Doc. 2026-00755, DATES", unit="date", parse=str)
    items.append(item)
    valid_from = date(2026, 1, int(re.search(r"\d+", effective).group(0))).isoformat()
    vectors = []
    for key in areas:
        for persons in (1, 4, 8):
            vectors.append({"input": {"area": key, "persons": persons}, "expected": areas[key]["guidelines"][persons], "origin": "source"})
    contiguous = areas["contiguous_states_and_dc"]
    vectors.append({"input": {"area": "contiguous_states_and_dc", "persons": 10}, "expected": contiguous["guidelines"][8] + 2 * contiguous["additional_person"], "origin": "derived", "note": "eight-person guideline plus two additional persons"})
    four = contiguous["guidelines"][4]
    vectors.append({"input": {"area": "contiguous_states_and_dc", "persons": 4, "income": four * 2}, "expected": "200.00", "origin": "derived", "note": "income at twice the guideline"})
    return base_entry(
        "us-hhs-poverty-guidelines-2026",
        "US HHS poverty guidelines for 2026 by household size: 48 contiguous states and DC, Alaska and Hawaii",
        "benefits",
        valid_from,
        None,
        ["benefits", "poverty-guidelines", "eligibility", "medicaid", "limits", "federal-poverty-level"],
        ["benefits-demo", "health-demo", "household-generation", "lending-demo", "personal-finance"],
        "almanac.rules.us_poverty_guidelines",
        {"year": "2026", "currency": "USD", "unit": "annual income in dollars", "areas": areas},
        vectors,
        items,
        [
            {"statistic": "count", "expected": 3, "tolerance": 0},
            {"statistic": "guideline[contiguous_states_and_dc,4]", "expected": four, "tolerance": 0},
            {"statistic": "additional_person[alaska]", "expected": areas["alaska"]["additional_person"], "tolerance": 0},
        ],
        (
            "The 2026 HHS poverty guidelines (FR Doc. 2026-00755, 91 FR 1797, January 15, 2026), the simplified "
            "version of the Census Bureau poverty thresholds that Medicaid, the Marketplace premium tax credit, SNAP "
            "and many other programmes use to set eligibility, often as a percentage of the guideline (the "
            "'federal poverty level'). Separate tables apply to the 48 contiguous states and DC, to Alaska and to "
            "Hawaii; households over eight persons add a fixed amount per person. The guidelines are effective from "
            "the date the notice gives unless a programme sets its own date, and stay in force until the 2027 "
            "update, so valid_to is open. The rule returns the guideline for a household size and, given an income, "
            "that income as a percentage of the guideline. Source is the Federal Register issue XML (tier A)."
        ),
        [{"parameter": "valid_to", "value": None, "method": "derived", "rationale": "The notice gives an effective date but no end; each year's guidelines are replaced by the next annual update."}],
        tier="A",
    )


# --------------------------------------------------------------------------------------
# FHFA conforming loan limits and HUD FHA forward mortgage limits
# --------------------------------------------------------------------------------------


def conforming_limits(src: Source, faq: Source) -> dict:
    text = src.raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    if [collapse(h) for h in header] != ["FIPS State Code", "FIPS County Code", "County Name", "State", "CBSA Number", "One-Unit Limit", "Two-Unit Limit", "Three-Unit Limit", "Four-Unit Limit"]:
        raise ValueError(f"unexpected CSV header {header}")
    columns = ["one_unit", "two_unit", "three_unit", "four_unit"]
    counties, limits, raw_rows = {}, {}, {}
    for row in reader:
        fips = row[0] + row[1]
        counties[fips] = f"{row[2]}, {row[3]}"
        limits[fips] = {column: money(value) for column, value in zip(columns, row[5:9])}
        raw_rows[fips] = row
    baseline_value, baseline_item = fact(faq, r"the baseline loan limit value being (\$[\d,]+) for a one-unit property", "FAQ 6 (page 3)", role="supporting")
    ceiling_value, ceiling_item = fact(faq, r"below the high-cost ceiling of (\$[\d,]+)\.", "FAQ 6 (page 3)", role="supporting")
    baseline_rows = [l for l in limits.values() if l["one_unit"] == baseline_value]
    baseline = baseline_rows[0]
    if any(l != baseline for l in baseline_rows):
        raise ValueError("baseline counties disagree on multi-unit limits")
    above = {fips: l for fips, l in limits.items() if l != baseline}
    if min(l["one_unit"] for l in limits.values()) != baseline_value:
        raise ValueError("a county is below the stated baseline")
    def line(fips: str) -> str:
        return ",".join(f'"{v}"' if "," in v else v for v in raw_rows[fips])
    samples = ["01001", "06037", "06083", "11001", "15005", "02020", "36061", "53033"]
    items = [baseline_item, ceiling_item]
    for fips in samples:
        items.append(src.ev(f"row for FIPS {fips} ({counties[fips]})", raw_rows[fips][5].strip(), "currency:USD", line(fips)))
    vectors = [{"input": {"fips": fips, "units": units}, "expected": limits[fips][columns[units - 1]], "origin": "source", "note": counties[fips]} for fips in samples for units in (1, 4)]
    vectors.append({"input": {"fips": "06037", "units": 1, "amount": limits["06037"]["one_unit"] + 1}, "expected": False, "origin": "derived", "note": "one dollar over the county limit is a jumbo loan"})
    vectors.append({"input": {"fips": "01001", "units": 1, "amount": baseline_value}, "expected": True, "origin": "derived", "note": "a loan equal to the limit conforms"})
    high_cost = max(l["one_unit"] for fips, l in limits.items() if counties[fips][-2:] not in ("AK", "HI", "GU", "VI"))
    if high_cost != ceiling_value:
        raise ValueError("high-cost ceiling disagrees with the county list")
    return base_entry(
        "us-fhfa-conforming-loan-limits-2026-by-county",
        "US FHFA conforming loan limits for 2026 by county FIPS code and number of units (one to four), with baseline and ceiling",
        "consumer-credit",
        "2026-01-01",
        "2026-12-31",
        ["lending", "mortgage", "conforming-loan-limit", "fhfa", "jumbo-loan", "limits"],
        [*LENDING_USES, "property-demo", "credit-risk"],
        "almanac.rules.us_conforming_loan_limits",
        {
            "year": "2026",
            "currency": "USD",
            "baseline": baseline,
            "high_cost_ceiling_one_unit": ceiling_value,
            "counties": counties,
            "above_baseline": above,
        },
        vectors,
        items,
        [
            {"statistic": "count", "expected": len(counties), "tolerance": 0},
            {"statistic": "above_baseline", "expected": len(above), "tolerance": 0},
            {"statistic": "limit[01001,1]", "expected": baseline_value, "tolerance": 0},
        ],
        (
            "Maximum original principal balance of a mortgage that Fannie Mae or Freddie Mac may acquire in 2026, "
            "for every county and county-equivalent (keyed by the five-digit state and county FIPS code) and for "
            "one- to four-unit properties, from FHFA's FullCountyLoanLimitList2026 file. Most counties carry the "
            "baseline; high-cost areas carry 115% of the local median home value up to the ceiling of 150% of the "
            "baseline, and Alaska, Hawaii, Guam and the US Virgin Islands have higher statutory limits, as FHFA's "
            "2026 FAQ explains. Only counties above the baseline are listed in above_baseline; every other county "
            "in counties takes the baseline row. Loans above the limit are jumbo loans. The county list is a "
            "machine-readable CSV, so the entry is tier A; the FAQ PDF is supporting context for the baseline and "
            "ceiling."
        ),
        [{"parameter": "baseline", "value": baseline, "method": "derived", "rationale": "The CSV gives every county's limits; the baseline row is the one shared by the counties whose one-unit limit equals the baseline FHFA states, and the build checks that they all agree."}],
        tier="A",
    )


def fha_limits(src: Source) -> dict:
    sections = [
        ("low_cost_floor", "The FHA national low-cost area mortgage limits", "(C) High-Cost Area The FHA", "national low-cost area limit (floor), 65 percent of the conforming limit"),
        ("high_cost_ceiling", "The FHA national high-cost area mortgage limits", "(D) Special Exceptions for Alaska, Hawaii, Guam, and the Virgin Islands Mortgage", "national high-cost area limit (ceiling), 150 percent of the conforming limit"),
        ("special_exception_ceiling", "These four special exception areas", "Paperwork Reduction Act", "ceiling for Alaska, Hawaii, Guam and the Virgin Islands"),
    ]
    rows, items = {}, []
    for key, start, end, description in sections:
        block = src.section(start, end)
        row = {"description": description}
        for units, label in enumerate(["One-unit", "Two-unit", "Three-unit", "Four-unit"], start=1):
            found = src.match(re.escape(label) + r": (\$[\d,]+)", block)
            row[["one_unit", "two_unit", "three_unit", "four_unit"][units - 1]] = money(found.group(1))
            items.append(src.ev(f"ML 2025-23, Handbook 4000.1 II.A.2.a.ii, {description}", found.group(1), "currency:USD", found.group(0)))
        rows[key] = row
    conforming, item = fact(src, r"of the national conforming limit of (\$[\d,]+) for a one-unit Property", "ML 2025-23, II.A.2.a.ii(B)")
    items.append(item)
    effective = src.match(r"effective for case numbers assigned on or after (January 1, 2026)")
    items.append(src.ev("ML 2025-23, Effective Date", effective.group(1), "date", effective.group(0), role="supporting"))
    vectors = [{"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": "source"} for key in rows for column in ("one_unit", "four_unit")]
    vectors.append({"input": "reverse_mortgage_claim_limit", "expected": False, "origin": "derived", "note": "HECM limits are in a separate mortgagee letter"})
    return base_entry(
        "us-fha-forward-mortgage-limits-2026",
        "US FHA forward mortgage limits for 2026: national floor, high-cost ceiling and special-exception ceiling by units (ML 2025-23)",
        "consumer-credit",
        "2026-01-01",
        "2026-12-31",
        ["lending", "mortgage", "fha", "loan-limit", "limits"],
        [*LENDING_USES, "property-demo"],
        "almanac.rules.lookup_table",
        {"year": "2026", "currency": "USD", "national_conforming_limit_one_unit": conforming, "rows": rows},
        vectors,
        items,
        [{"statistic": "count", "expected": 3, "tolerance": 0}, {"statistic": "max[four_unit]", "expected": rows["special_exception_ceiling"]["four_unit"], "tolerance": 0}],
        (
            "FHA's 2026 nationwide forward mortgage limits from HUD Mortgagee Letter 2025-23 (December 11, 2025), "
            "effective for FHA case numbers assigned on or after January 1, 2026: the floor that applies in low-cost "
            "areas (65 percent of the national conforming limit), the ceiling in high-cost areas (150 percent), and "
            "the higher ceiling for the special exception areas of Alaska, Hawaii, Guam and the Virgin Islands, each "
            "for one- to four-unit properties. Each county's own FHA limit lies between the floor and the applicable "
            "ceiling; HUD publishes the county list separately. The national conforming limit the percentages refer "
            "to is the FHFA baseline (us-fhfa-conforming-loan-limits-2026-by-county)."
        ),
        tier="B",
    )


def main() -> None:
    revproc = Source(f"{IRS_DROP}/rp-25-32.pdf", "Rev. Proc. 2025-32, 2026 inflation-adjusted items (PDF)", IRS)
    entries = bracket_entries(revproc)
    entries += [standard_deduction(revproc), capital_gains(revproc), amt(revproc), eitc(revproc), credits(revproc), transfer_tax(revproc), employee_benefits(revproc), section_179(revproc)]
    p15t = Source(f"{IRS_PDF}/p15t.pdf", "Publication 15-T (2026), Federal Income Tax Withholding Methods (PDF)", IRS)
    entries.append(withholding(p15t))
    p15 = Source(f"{IRS_PDF}/p15.pdf", "Publication 15 (2026), (Circular E), Employer's Tax Guide (PDF)", IRS)
    futa_rate = Source(f"{GOVINFO}/USCODE-2024-title26/html/USCODE-2024-title26-subtitleC-chap23-sec3301.htm", "26 U.S.C. 3301, Rate of tax (FUTA; United States Code 2024 edition, HTML)", OLRC)
    futa_base = Source(f"{GOVINFO}/USCODE-2024-title26/html/USCODE-2024-title26-subtitleC-chap23-sec3306.htm", "26 U.S.C. 3306, Definitions (FUTA; United States Code 2024 edition, HTML)", OLRC)
    entries.append(payroll_taxes(p15, futa_rate, futa_base))
    entries.append(mileage(Source(f"{IRS_DROP}/n-26-10.pdf", "Notice 2026-10, 2026 Standard Mileage Rates (PDF)", IRS)))
    entries.append(macrs(Source(f"{IRS_PDF}/p946.pdf", "Publication 946 (2025), How To Depreciate Property (PDF)", IRS)))
    entries.append(retirement(Source(f"{IRS_DROP}/n-25-67.pdf", "Notice 2025-67, 2026 Amounts Relating to Retirement Plans and IRAs (PDF)", IRS)))
    entries.append(hsa(Source(f"{IRS_DROP}/rp-25-19.pdf", "Rev. Proc. 2025-19, 2026 HSA inflation adjusted amounts (PDF)", IRS), revproc))
    entries.append(aca(Source(f"{IRS_DROP}/rp-25-25.pdf", "Rev. Proc. 2025-25, 2026 applicable percentage table and required contribution percentage (PDF)", IRS)))
    medicare = Source(f"{GOVINFO}/FR-2025-11-19/xml/FR-2025-11-19.xml", "Federal Register, Vol. 90, November 19, 2025, issue XML (CMS Medicare Part A and Part B notices)", CMS)
    entries += [medicare_part_b(medicare), medicare_part_a(medicare)]
    entries.append(poverty(Source(f"{GOVINFO}/FR-2026-01-15/xml/FR-2026-01-15.xml", "Federal Register, Vol. 91, No. 10, January 15, 2026, issue XML (Annual Update of the HHS Poverty Guidelines)", HHS)))
    fhfa_csv = Source("https://www.fhfa.gov/document/d/cll/fullcountyloanlimitlist2026_hera-based_final_flat.csv", "FHFA Full County Loan Limit List 2026, HERA-based, final (CSV)", FHFA)
    fhfa_faq = Source("https://www.fhfa.gov/document/d/cll/fhfa-cll-faqs-2026.pdf", "FHFA Conforming Loan Limit Values FAQs, updated November 2025 (PDF)", FHFA)
    entries.append(conforming_limits(fhfa_csv, fhfa_faq))
    entries.append(fha_limits(Source("https://www.hud.gov/sites/dfiles/hudclips/documents/2025-23hsgml.pdf", "Mortgagee Letter 2025-23, 2026 Nationwide Forward Mortgage Loan Limits (PDF)", HUD)))
    for entry in entries:
        write(entry)


if __name__ == "__main__":
    main()

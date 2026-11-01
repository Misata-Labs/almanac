"""Regenerate the UK tax rule entries read from the GOV.UK content API.

National Insurance, Scottish Income Tax, dividend and capital gains rates,
Corporation Tax, Stamp Duty Land Tax, the Inheritance Tax nil-rate band and
the personal tax-free allowances are read from the JSON the content API serves
for each GOV.UK page, which is stable between editorial updates. Run from the
repository root:

    uv run python tools/build_gb_govuk_tax.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write  # noqa: E402
from _govuk import Source, body_html, find_table, govuk, html_tables, number, percent  # noqa: E402

HMRC = "HM Revenue & Customs"
TAX_YEAR = {"valid_from": "2026-04-06", "valid_to": "2027-04-05"}
OGL_NOTE = (
    "Source is the GOV.UK content API's JSON for the page, which is stable between editorial updates; "
    "GOV.UK publishes its content under the Open Government Licence v3.0."
)
EMPLOYEE_COLUMNS = ("employee_lel_to_pt_percent", "employee_pt_to_uel_percent", "employee_above_uel_percent")
EMPLOYER_COLUMNS = (
    "employer_st_to_lel_percent",
    "employer_lel_to_fust_percent",
    "employer_fust_to_uel_percent",
    "employer_above_uel_percent",
)
THRESHOLD_KEYS = {
    "Lower earnings limit": "lower_earnings_limit",
    "Primary threshold": "primary_threshold",
    "Secondary threshold": "secondary_threshold",
    "Freeport upper secondary threshold": "freeport_upper_secondary_threshold",
    "Investment Zone upper secondary threshold": "investment_zone_upper_secondary_threshold",
    "Upper secondary threshold (under 21)": "upper_secondary_threshold_under_21",
    "Apprentice upper secondary threshold (apprentice under 25)": "apprentice_upper_secondary_threshold",
    "Veterans upper secondary threshold": "veterans_upper_secondary_threshold",
    "Upper earnings limit": "upper_earnings_limit",
}
STANDARD_PA = 12570
_PERIOD = re.compile(r"£([\d,\.]+) per (week|month|year)")
_UPPER = re.compile(r"to £([\d,\.]+)( million)?")


def entry(**fields) -> dict:
    """An entry with region, status and tier placed after the domain, in the order hand-written entries use."""
    ordered: dict = {}
    for key, value in fields.items():
        if key == "status":
            continue
        ordered[key] = value
        if key == "domain":
            ordered.update({"region": "GB", "status": fields.get("status", "verified"), "tier": "A"})
    return ordered


def rule_tests(*tests: tuple[str, object]) -> list[dict]:
    return [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}] + [
        {"statistic": statistic, "expected": expected, "tolerance": 0} for statistic, expected in tests
    ]


def table_with_cell(source: Source, cell: str) -> list[list[str]]:
    for table in html_tables(body_html(source)):
        if any(cell in row for row in table[1:]):
            return table
    raise LookupError(f"no table in {source.url} with a cell {cell!r}")


def band_upper(text: str) -> int | None:
    """Upper limit of a band described as 'the portion from £X to £Y'; None for an open band."""
    match = _UPPER.search(text)
    if match is None:
        return None if "above" in text or "remaining" in text.lower() else int(number(text))
    value = Decimal(match.group(1).replace(",", ""))
    return int(value * (1_000_000 if match.group(2) else 1))


def tax_due(bands: list[dict], allowance: int, income: int) -> str:
    """Tax on ``income`` under ``bands`` applied to income above ``allowance``, as the rule module reports it."""
    taxable = max(0, income - allowance)
    tax = Decimal(0)
    lower = 0
    for band in bands:
        upper = band["up_to"] if band["up_to"] is not None else taxable
        top = min(taxable, upper)
        if top > lower:
            tax += (Decimal(top) - lower) * Decimal(str(band["rate_percent"])) / 100
        lower = upper
        if band["up_to"] is None or taxable <= upper:
            break
    return f"{tax:.2f}"


def ni_class_1_rates(employers: Source, letters: Source) -> dict:
    tables = html_tables(body_html(employers))
    employee = find_table(tables, "Earnings at or above lower earnings limit")
    employer = find_table(tables, "Earnings above secondary threshold")
    groups = {
        row[0]: row[1] for table in html_tables(body_html(letters)) if table[0][:2] == ["Category letter", "Employee group"] for row in table[1:]
    }
    rows: dict[str, dict] = {}
    for row in employee[1:]:
        letter = row[0][0]
        rows[letter] = {"employee_group": groups[letter], **dict(zip(EMPLOYEE_COLUMNS, map(percent, row[1:])))}
    for row in employer[1:]:
        rows[row[0][0]].update(dict(zip(EMPLOYER_COLUMNS, map(percent, row[1:]))))
    thresholds = find_table(tables, "Class 1 National Insurance thresholds")
    weekly = {THRESHOLD_KEYS[row[0]]: number(row[1]) for row in thresholds[1:]}
    return entry(
        id="gb-national-insurance-class-1-rates-2026-27",
        title="United Kingdom Class 1 National Insurance employee and employer contribution rates by category letter, 2026 to 2027",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["national-insurance", "payroll", "paye", "category-letter"],
        use_cases=["payroll-demo", "hr-analytics", "workforce-planning"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {
                "tax_year": "2026-27",
                "unit": "percent of earnings in the band",
                "band_thresholds_weekly_gbp": {
                    "lower_earnings_limit": weekly["lower_earnings_limit"],
                    "primary_threshold": weekly["primary_threshold"],
                    "secondary_threshold": weekly["secondary_threshold"],
                    "freeport_and_investment_zone_upper_secondary_threshold": weekly["freeport_upper_secondary_threshold"],
                    "upper_earnings_limit": weekly["upper_earnings_limit"],
                },
                "class_1a_and_1b_percent": 15,
                "worked_example": {"category": "A", "weekly_earnings": 1000, "employee_contribution": 58.66},
                "rows": rows,
            },
            "vectors": [
                {"input": {"key": "A", "column": "employee_pt_to_uel_percent"}, "expected": 8, "origin": "source"},
                {"input": {"key": "A", "column": "employee_above_uel_percent"}, "expected": 2, "origin": "source"},
                {"input": {"key": "B", "column": "employee_pt_to_uel_percent"}, "expected": 1.85, "origin": "source"},
                {"input": {"key": "C", "column": "employee_pt_to_uel_percent"}, "expected": 0, "origin": "source", "note": "nil for employees over State Pension age"},
                {"input": {"key": "A", "column": "employer_st_to_lel_percent"}, "expected": 15, "origin": "source"},
                {"input": {"key": "M", "column": "employer_fust_to_uel_percent"}, "expected": 0, "origin": "source", "note": "under 21: employer pays nothing up to the upper secondary threshold"},
                {"input": {"key": "H", "column": "employer_above_uel_percent"}, "expected": 15, "origin": "source"},
                {"input": "X", "expected": False, "origin": "derived", "note": "letter X (no contributions due) has no rates row"},
            ],
        },
        evidence=[
            employers.cite("details.body, 'Employee (primary) contribution rates' table, row A", "<td>8%</td>", "text", "Earnings above primary threshold up to and including upper earnings limit"),
            employers.cite("details.body, 'Employer (secondary) contribution rates' table, row H", "<td>H (apprentice under 25)</td>", "text", "Earnings above secondary threshold up to and including lower earnings limit"),
            employers.cite("details.body, 'Class 1A National Insurance: expenses and benefits'", "rate on expenses and benefits for 2026 to 2027 is 15%", "text", "Class 1A rate on expenses and benefits"),
            employers.cite("details.body, opening sentence", "Unless otherwise stated, the following figures apply from 6 April 2026 to 5 April 2027.", "text", "apply from 6 April 2026 to 5 April 2027"),
            letters.cite("details.parts[0].body, worked example for category A", "This means your National Insurance payment will be £58.66 for the week.", "text", "8% (£58) on your earnings between £242.01 and £967"),
            letters.cite("details.parts[1].body, 'Category letter / Employee group' table, row A", "All employees apart from those in groups B, C, H, J, M, V and Z in this table", "text", "Employee group</th>"),
        ],
        assumed=[
            {
                "parameter": "rows[C|K|S].employee_*_percent",
                "value": 0,
                "method": "derived",
                "rationale": "HMRC prints 'nil' for employees over State Pension age (letters C, K and S) because no employee contribution is due; the rate is recorded as 0 so a payroll generator can apply it directly.",
            }
        ],
        tests=rule_tests(("count", len(rows)), ("value[A,employee_pt_to_uel_percent]", 8), ("value[H,employer_above_uel_percent]", 15), ("max[employer_above_uel_percent]", 15)),
        notes=(
            "Class 1 National Insurance contribution rates for the 2026 to 2027 tax year by category letter, as HMRC's "
            "'Rates and thresholds for employers' guidance publishes them: employee (primary) rates for earnings between the "
            "lower earnings limit and primary threshold, between the primary threshold and upper earnings limit, and above the "
            "upper earnings limit; employer (secondary) rates for earnings between the secondary threshold and lower earnings "
            "limit, up to the Freeport and Investment Zone upper secondary thresholds, up to the upper earnings limit and above "
            "it. Each row carries the employee group GOV.UK gives for the letter. Letter X (no contributions) has no rates row. "
            "The weekly thresholds that delimit the bands are kept beside the rows; the full threshold table is the entry "
            "gb-national-insurance-class-1-thresholds-2026-27. " + OGL_NOTE
        ),
    )


def ni_class_1_thresholds(employers: Source, intro: Source) -> dict:
    table = find_table(html_tables(body_html(employers)), "Class 1 National Insurance thresholds")
    rows = {}
    for label, cell in table[1:]:
        amounts = {period: number(amount) for amount, period in _PERIOD.findall(cell)}
        rows[THRESHOLD_KEYS[label]] = {"label": label, "weekly": amounts["week"], "monthly": amounts["month"], "annual": amounts["year"]}
    return entry(
        id="gb-national-insurance-class-1-thresholds-2026-27",
        title="United Kingdom Class 1 National Insurance earnings thresholds (weekly, monthly and annual), 2026 to 2027",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["national-insurance", "payroll", "paye", "thresholds"],
        use_cases=["payroll-demo", "hr-analytics", "workforce-planning"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"tax_year": "2026-27", "currency": "GBP", "rows": rows},
            "vectors": [
                {"input": {"key": "primary_threshold", "column": "weekly"}, "expected": 242, "origin": "source"},
                {"input": {"key": "upper_earnings_limit", "column": "annual"}, "expected": 50270, "origin": "source"},
                {"input": {"key": "secondary_threshold", "column": "monthly"}, "expected": 417, "origin": "source"},
                {"input": {"key": "lower_earnings_limit", "column": "weekly"}, "expected": 129, "origin": "source"},
                {"input": "lower_profits_limit", "expected": False, "origin": "derived", "note": "a self-employed Class 4 threshold, not a Class 1 row"},
            ],
        },
        evidence=[
            employers.cite("details.body, 'Class 1 National Insurance thresholds' table, row Lower earnings limit", "<td>Lower earnings limit</td>", "text", "£129 per week<br>£559 per month<br>£6,708 per year"),
            employers.cite("details.body, 'Class 1 National Insurance thresholds' table, row Upper earnings limit", "<td>Upper earnings limit</td>", "text", "£967 per week<br>£4,189 per month<br>£50,270 per year"),
            employers.cite("details.body, 'Class 1 National Insurance thresholds' table, row Secondary threshold", "<td>Secondary threshold</td>", "text", "£96 per week<br>£417 per month<br>£5,000 per year"),
            employers.cite("details.body, opening sentence", "Unless otherwise stated, the following figures apply from 6 April 2026 to 5 April 2027.", "text", "apply from 6 April 2026 to 5 April 2027"),
            intro.cite("details.parts[0].body, 'Who pays National Insurance'", "an employee earning more than £242 per week from one job", "text", "an employee earning from £129 to £242 a week from one job"),
        ],
        assumed=[],
        tests=rule_tests(("count", len(rows)), ("value[lower_earnings_limit,annual]", 6708), ("value[primary_threshold,monthly]", 1048), ("max[weekly]", 967)),
        notes=(
            "The nine Class 1 National Insurance earnings thresholds for the 2026 to 2027 tax year as HMRC's 'Rates and "
            "thresholds for employers' guidance states them, each with its weekly, monthly and annual figure: lower earnings "
            "limit, primary threshold, secondary threshold, the Freeport and Investment Zone upper secondary thresholds, the "
            "upper secondary thresholds for under-21s, apprentices and veterans, and the upper earnings limit. The thresholds "
            "delimit the bands whose rates are in gb-national-insurance-class-1-rates-2026-27. " + OGL_NOTE
        ),
    )


def ni_category_letters(letters: Source) -> dict:
    tables = [t for t in html_tables(body_html(letters)) if t[0][:2] == ["Category letter", "Employee group"]]
    standard, freeport, investment_zone = ({row[0]: row[1] for row in table[1:]} for table in tables)
    standard["X"] = "Employees who do not have to pay National Insurance, for example because they’re under 16"
    sets = {"standard": standard, "freeport": freeport, "investment_zone": investment_zone}
    return entry(
        id="gb-national-insurance-category-letters",
        title="United Kingdom National Insurance category letters and the employee groups they denote (standard, Freeport and Investment Zone)",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["national-insurance", "payroll", "category-letter", "code-list"],
        use_cases=["payroll-demo", "hr-analytics", "person-generation"],
        spec={
            "implementation": "almanac.rules.enumeration",
            "parameters": {"sets": sets, "default_letter": "A"},
            "vectors": [
                {"input": {"set": "standard", "value": "A"}, "expected": True, "origin": "source"},
                {"input": {"set": "standard", "value": "X"}, "expected": True, "origin": "source"},
                {"input": {"set": "standard", "value": "M"}, "expected": True, "origin": "source"},
                {"input": {"set": "freeport", "value": "F"}, "expected": True, "origin": "source"},
                {"input": {"set": "investment_zone", "value": "N"}, "expected": True, "origin": "source"},
                {"input": {"set": "standard", "value": "F"}, "expected": False, "origin": "derived", "note": "F is a Freeport letter"},
                {"input": {"set": "freeport", "value": "f"}, "expected": False, "origin": "derived", "note": "letters are upper case"},
                {"input": {"set": "standard", "value": "G"}, "expected": False, "origin": "derived"},
            ],
        },
        evidence=[
            letters.cite("details.parts[1].body, first 'Category letter / Employee group' table, row A", "All employees apart from those in groups B, C, H, J, M, V and Z in this table", "text", "Most employees have category letter A."),
            letters.cite("details.parts[1].body, Freeport table, row F", "All employees who work in a special tax site within a Freeport, apart from those in groups I, L, and S in this table", "text", "Category letters for eligible employees who work in a special tax site within a Freeport"),
            letters.cite("details.parts[1].body, Investment Zone table, row N", "All employees who work in a special tax site within an Investment Zone, apart from those in groups E, D and K in this table", "text", "Category letter X"),
            letters.cite("details.parts[1].body, 'Category letter X'", "Employers use category letter X for employees who do not have to pay National Insurance", "text", "for example because they’re under 16"),
            letters.cite("details.parts[0].body, rates table heading", "This table shows how much employers deduct from employees’ pay from 6 April 2026 to 5 April 2027.", "text", "Employee National Insurance rates"),
        ],
        assumed=[],
        tests=rule_tests(("count[standard]", len(standard)), ("count[freeport]", len(freeport)), ("count[investment_zone]", len(investment_zone))),
        notes=(
            "The National Insurance category letters employers put on payroll, grouped as GOV.UK groups them: the standard "
            "letters (A, B, C, H, J, M, V, Z and X for employees who pay nothing), the Freeport special tax site letters "
            "(F, I, L, S) and the Investment Zone special tax site letters (N, E, D, K), each with GOV.UK's description of the "
            "employee group. The validity window is the 2026 to 2027 tax year whose rate tables list these letters; the "
            "letters themselves are not dated on the page. " + OGL_NOTE
        ),
    )


def ni_self_employed(intro: Source) -> dict:
    bands = [
        {"name": "main", "up_to": 50270 - STANDARD_PA, "rate_percent": 6, "profits_range": "over £12,570 up to £50,270"},
        {"name": "upper", "up_to": None, "rate_percent": 2, "profits_range": "over £50,270"},
    ]
    vectors = [
        {"input": {"income": 12570}, "expected": tax_due(bands, STANDARD_PA, 12570), "origin": "source", "note": "GOV.UK: Class 4 is due only on profits of more than £12,570, so nothing is due at the limit"},
        {"input": {"income": 20000}, "expected": tax_due(bands, STANDARD_PA, 20000), "origin": "derived"},
        {"input": {"income": 50270}, "expected": tax_due(bands, STANDARD_PA, 50270), "origin": "derived", "note": "top of the main rate band"},
        {"input": {"income": 60000}, "expected": tax_due(bands, STANDARD_PA, 60000), "origin": "derived"},
        {"input": {"allowance_for": 150000}, "expected": "12570", "origin": "derived", "note": "the lower profits limit does not taper"},
    ]
    return entry(
        id="gb-national-insurance-self-employed-2026-27",
        title="United Kingdom self-employed National Insurance: Class 4 rates on profits and the Class 2 weekly rate, 2026 to 2027",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["national-insurance", "self-employed", "class-4", "class-2", "self-assessment"],
        use_cases=["tax-filing-demo", "personal-finance", "financial-planning"],
        spec={
            "implementation": "almanac.rules.income_tax_bands",
            "parameters": {
                "tax_year": "2026-27",
                "currency": "GBP",
                "personal_allowance": STANDARD_PA,
                "bands": bands,
                "class_2_weekly_rate": 3.65,
                "small_profits_threshold": 7105,
            },
            "vectors": vectors,
        },
        evidence=[
            intro.cite("details.parts[3].body, 'If you’re self-employed', Class 4 rates list", "<li>6% on profits over £12,570 up to £50,270</li>", "text", "The Class 4 National Insurance rates for tax year 2026 to 2027 are:"),
            intro.cite("details.parts[3].body, 'If you’re self-employed', Class 4 rates list", "<li>2% on profits over £50,270</li>", "text", "you pay Class 4 National Insurance contributions"),
            intro.cite("details.parts[3].body, Class 2 rate sentence", "The Class 2 rate for tax year 2026 to 2027 is £3.65 a week.", "text", "You may choose to pay Class 2 National Insurance contributions."),
            intro.cite("details.parts[0].body, 'Who pays National Insurance'", "self-employed and your profits are £7,105 or more a year", "text", "self-employed and making a profit of more than £12,570 a year"),
        ],
        assumed=[
            {
                "parameter": "personal_allowance and bands[main].up_to",
                "value": "12570 and 37700",
                "method": "derived",
                "rationale": "GOV.UK states Class 4 as 6% on profits over £12,570 up to £50,270 and 2% above; the rule applies bands to profits above a threshold, so the lower profits limit is carried in personal_allowance and the main band ends at £50,270 minus £12,570.",
            }
        ],
        tests=rule_tests(("count", 2), ("rate[main]", 6), ("rate[upper]", 2)),
        notes=(
            "Self-employed National Insurance for the 2026 to 2027 tax year as GOV.UK states it: Class 4 at 6% on profits "
            "over £12,570 up to £50,270 and 2% above, computed by the income_tax_bands rule with the lower profits limit in "
            "the allowance slot; Class 2 is £3.65 a week and voluntary, and profits of £7,105 or more earn Class 2 credit "
            "without payment (small profits threshold). The vectors are arithmetic on the published rates. " + OGL_NOTE
        ),
    )


def scottish_income_tax(employers: Source, scottish: Source, income_tax: Source) -> dict:
    markup = body_html(employers)
    paye = html_tables(markup[markup.index("Scotland</h"):])[0]
    ranges = {row[0].replace(" rate", ""): row[1] for row in find_table(html_tables(body_html(scottish)), "Taxable income", "Scottish tax rate")[1:]}
    bands = []
    for label, rate, span in paye[1:]:
        name = label.replace(" tax rate", "").lower()
        bands.append({"name": name, "up_to": band_upper(span) if "Above" not in span else None, "rate_percent": number(rate), "income_range_with_standard_allowance": ranges[name.capitalize()]})
    for band in bands[:-2]:
        assert band["up_to"] == number(band["income_range_with_standard_allowance"].split(" to ")[1]) - STANDARD_PA
    vectors = [
        {"input": {"income": 12570}, "expected": tax_due(bands, STANDARD_PA, 12570), "origin": "derived", "note": "income equal to the Personal Allowance"},
        {"input": {"income": 16537}, "expected": tax_due(bands, STANDARD_PA, 16537), "origin": "derived", "note": "top of the starter rate band"},
        {"input": {"income": 30000}, "expected": tax_due(bands, STANDARD_PA, 30000), "origin": "derived"},
        {"input": {"income": 50000}, "expected": tax_due(bands, STANDARD_PA, 50000), "origin": "derived"},
        {"input": {"allowance_for": 125140}, "expected": "0", "origin": "source", "note": "no Personal Allowance above £125,140"},
        {"input": {"allowance_for": 110000}, "expected": "7570", "origin": "derived", "note": "£1 off for every £2 above £100,000"},
    ]
    return entry(
        id="gb-scottish-income-tax-bands-2026-27",
        title="Scottish Income Tax rates and bands for the 2026 to 2027 tax year (starter to top rate) with the Personal Allowance taper",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["income-tax", "scotland", "payroll", "paye", "personal-allowance"],
        use_cases=["payroll-demo", "hr-analytics", "personal-finance", "financial-planning"],
        spec={
            "implementation": "almanac.rules.income_tax_bands",
            "parameters": {"tax_year": "2026-27", "currency": "GBP", "personal_allowance": STANDARD_PA, "taper": {"above": 100000, "ratio": 2}, "tax_code_prefix": "S", "bands": bands},
            "vectors": vectors,
        },
        evidence=[
            employers.cite("details.body, Scotland PAYE tax rate table, row Starter tax rate", "<td>Up to £3,967</td>", "text", "Starter tax rate"),
            employers.cite("details.body, Scotland PAYE tax rate table, row Advanced tax rate", "<td>From £62,431 to £125,140</td>", "text", "Advanced tax rate"),
            employers.cite("details.body, Scotland PAYE tax rate table, row Top tax rate", "<td>Above £125,140</td>", "text", "Top tax rate"),
            scottish.cite("details.parts[0].body, 2026 to 2027 table, row Starter rate", "<td>£12,571 to £16,537</td>", "text", "The table shows the 2026 to 2027 Scottish Income Tax rates"),
            scottish.cite("details.parts[0].body, 2026 to 2027 table, row Higher rate", "<td>£43,663 to £75,000</td>", "text", "<td>42%</td>"),
            scottish.cite("details.parts[1].body, tax code", "Your tax code will be S1257L if you pay Scottish Income Tax", "text", "earn over £125,140"),
            income_tax.cite("details.parts[0].body, 'If you earn more than £100,000'", "allowance is zero if your income is £125,140 or above", "text", "goes down by £1 for every £2"),
        ],
        assumed=[
            {
                "parameter": "taper",
                "value": "{above: 100000, ratio: 2}",
                "method": "derived",
                "rationale": "The Scottish page states only that no Personal Allowance is due above £125,140; the taper of £1 for every £2 above £100,000 is the UK-wide rule GOV.UK states on the Income Tax rates page, cited here.",
            },
            {
                "parameter": "bands[advanced].up_to",
                "value": 125140,
                "method": "derived",
                "rationale": "HMRC's PAYE table ends the advanced rate at £125,140 of earnings above the threshold, the point at which the tapered Personal Allowance reaches zero and taxable income equals total income; the GOV.UK range '£75,001 to £125,140' assumes a standard allowance that no longer exists at that level, so the two agree only at the lower end.",
            },
        ],
        tests=rule_tests(("count", len(bands)), ("rate[starter]", 19), ("rate[intermediate]", 21), ("rate[top]", 48)),
        notes=(
            "Scottish Income Tax for the 2026 to 2027 tax year: six bands from the 19% starter rate to the 48% top rate, "
            "with the band limits above the standard Personal Allowance taken from HMRC's 'Rates and thresholds for "
            "employers' PAYE table for Scotland and the income ranges as GOV.UK's Scottish Income Tax page prints them; the "
            "builder checks each limit up to the higher rate equals the printed range minus £12,570 (the advanced rate ends "
            "at £125,140 of taxable income, where the allowance is fully tapered). Dividends and savings interest are taxed at "
            "UK rates and are out of scope. " + OGL_NOTE
        ),
    )


def dividend_rates(dividends: Source) -> dict:
    table = find_table(html_tables(body_html(dividends)), "Tax band", "Tax rate on dividends")
    slabs = {row[0].replace(" rate", "").lower(): number(row[1]) for row in table[1:]}
    return entry(
        id="gb-dividend-tax-rates-2026-27",
        title="United Kingdom tax rates on dividends above the dividend allowance by Income Tax band, 2026 to 2027",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["dividends", "income-tax", "tax-rates", "investment-income"],
        use_cases=["tax-filing-demo", "personal-finance", "financial-planning"],
        spec={
            "implementation": "almanac.rules.rate_schedule",
            "parameters": {
                "tax_year": "2026-27",
                "slabs": slabs,
                "dividend_allowance": 500,
                "worked_example": {"dividends": 3000, "wages": 29570, "taxable_dividends": 2500, "rate_percent": slabs["basic"]},
            },
            "vectors": [
                {"input": 10.75, "expected": True, "origin": "source"},
                {"input": 35.75, "expected": True, "origin": "source"},
                {"input": 39.35, "expected": True, "origin": "source"},
                {"input": 8.75, "expected": False, "origin": "derived", "note": "not a 2026 to 2027 rate"},
                {"input": 20, "expected": False, "origin": "derived", "note": "the basic rate on wages, not dividends"},
            ],
        },
        evidence=[
            dividends.cite("details.parts[0].body, rates table, row Basic rate", "<td>10.75%</td>", "text", "This table shows the rates from 6 April 2026 to 5 April 2027."),
            dividends.cite("details.parts[0].body, rates table, row Higher rate", "<td>35.75%</td>", "text", "Tax rate on dividends over the allowance"),
            dividends.cite("details.parts[0].body, rates table, row Additional rate", "<td>39.35%</td>", "text", "To work out your tax band, add your total dividend income to your other income."),
            dividends.cite("details.parts[0].body, dividend allowance", "You also get a dividend allowance of £500 each year.", "text", "dividend allowance of £500"),
            dividends.cite("details.parts[0].body, worked example", "10.75% tax on £2,500 of dividends", "text", "You get £3,000 in dividends and earn £29,570 in wages in the 2026 to 2027 tax year."),
        ],
        assumed=[],
        tests=rule_tests(("count", 3), ("slab[basic]", slabs["basic"]), ("slab[higher]", slabs["higher"]), ("slab[additional]", slabs["additional"])),
        notes=(
            "Tax on dividend income above the £500 dividend allowance for the 2026 to 2027 tax year: basic rate 10.75%, "
            "higher rate 35.75%, additional rate 39.35%, the band being found by adding dividend income to other income. "
            "Dividends within the Personal Allowance or held in an ISA are untaxed. GOV.UK's worked example is kept in the "
            "parameters. " + OGL_NOTE
        ),
    )


def capital_gains_rates(cgt: Source) -> dict:
    return entry(
        id="gb-capital-gains-tax-rates-2026-27",
        title="United Kingdom Capital Gains Tax rates and Annual Exempt Amount for gains made from 6 April 2026",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["capital-gains-tax", "tax-rates", "investment-income"],
        use_cases=["tax-filing-demo", "personal-finance", "financial-planning", "property-demo"],
        spec={
            "implementation": "almanac.rules.rate_schedule",
            "parameters": {
                "tax_year": "2026-27",
                "slabs": {"basic_rate_taxpayer": 18, "higher_or_additional_rate_taxpayer": 24},
                "annual_exempt_amount": 3000,
                "annual_exempt_amount_trusts": 1500,
                "basic_rate_band": 37700,
                "business_asset_disposal_relief_percent": 18,
                "trustees_and_personal_representatives_percent": 24,
                "worked_examples": [
                    {"taxable_income": 20000, "taxable_gains": 12600, "tax": 1728},
                    {"taxable_income": 20000, "taxable_gains": 52600, "tax": 10842},
                ],
            },
            "vectors": [
                {"input": 18, "expected": True, "origin": "source"},
                {"input": 24, "expected": True, "origin": "source"},
                {"input": 10, "expected": False, "origin": "derived"},
                {"input": 20, "expected": False, "origin": "derived"},
                {"input": 28, "expected": False, "origin": "derived"},
            ],
        },
        evidence=[
            cgt.cite("details.parts[6].body, higher or additional rate taxpayers", "you’ll pay 24% on your gains from 6 April 2026", "text", "or personal representatives of someone who’s died pay tax at 24% from 6 April 2026"),
            cgt.cite("details.parts[6].body, basic rate taxpayers", "you’ll pay 18% on your gains made from 6 April 2026", "text", "For any amount above the basic Income Tax band, you’ll pay 24% on gains made from 6 April 2026."),
            cgt.cite("details.parts[6].body, worked example 1", "This means you’ll pay £1,728 in Capital Gains Tax.", "text", "£37,700 (the basic rate band for the 2026 to 2027 tax year)"),
            cgt.cite("details.parts[6].body, worked example 2", "This means you will pay £10,842.", "text", "you will pay Capital Gains Tax at 18% on £17,700 and then 24% on £31,900"),
            cgt.cite("details.parts[2].body, allowances", "<li>£1,500 for trusts</li>", "text", "<li>£3,000</li>"),
            cgt.cite("details.parts[6].body, Business Asset Disposal Relief", "From 6 April 2026 you’ll pay 18% if you’re a sole trader, partnership or trustee", "text", "Business Asset Disposal Relief"),
        ],
        assumed=[],
        tests=rule_tests(("count", 2), ("slab[basic_rate_taxpayer]", 18), ("slab[higher_or_additional_rate_taxpayer]", 24)),
        notes=(
            "Capital Gains Tax on gains made from 6 April 2026 as GOV.UK states it: 18% for a basic rate taxpayer while "
            "taxable income plus gains stays within the £37,700 basic rate band and 24% above it or for higher and additional "
            "rate taxpayers, after the £3,000 Annual Exempt Amount (£1,500 for trusts). Business Asset Disposal Relief gains "
            "are taxed at 18% and trustees or personal representatives pay 24%. GOV.UK's two worked examples are kept in the "
            "parameters. " + OGL_NOTE
        ),
    )


def corporation_tax_rates(ct: Source) -> dict:
    return entry(
        id="gb-corporation-tax-rates",
        title="United Kingdom Corporation Tax main rate (25%) and small profits rate (19%) with the marginal relief thresholds",
        kind="rule",
        domain="tax",
        valid_from="2023-04-01",
        valid_to=None,
        tags=["corporation-tax", "tax-rates", "company-tax"],
        use_cases=["tax-filing-demo", "financial-reporting", "company-generation", "audit-demo"],
        spec={
            "implementation": "almanac.rules.rate_schedule",
            "parameters": {
                "slabs": {"main": 25, "small_profits": 19},
                "small_profits_rate_up_to": 50000,
                "main_rate_from": 250000,
                "marginal_relief_between": [50000, 250000],
                "thresholds_reduced_by": ["short accounting periods", "number of associated companies"],
            },
            "vectors": [
                {"input": 25, "expected": True, "origin": "source"},
                {"input": 19, "expected": True, "origin": "source"},
                {"input": 20, "expected": False, "origin": "derived"},
                {"input": 26.5, "expected": False, "origin": "derived", "note": "the effective marginal rate between the thresholds is not a published slab"},
            ],
        },
        evidence=[
            ct.cite("details.parts[0].body, opening sentence", "The Corporation Tax rate for company profits is <em>25%</em>", "text", "If your company made more than £250,000 profit, you’ll pay the main rate of Corporation Tax."),
            ct.cite("details.parts[0].body, small profits rate", "‘small profits rate’, which is 19%", "text", "If your company made a profit of £50,000 or less"),
            ct.cite("details.parts[0].body, previous regime", "From 1 April 2015 to 31 March 2023, a", "text", "The rate you pay on profits from before 1 April 2015 depends on the size of your profits."),
            ct.cite("details.parts[2].body, Marginal Relief", "taxable profits from 1 April 2023 are between £50,000 and £250,000", "text", "The £50,000 and £250,000 profit thresholds are proportionately reduced"),
        ],
        assumed=[
            {
                "parameter": "valid_from",
                "value": "2023-04-01",
                "method": "derived",
                "rationale": "GOV.UK states that a single rate applied from 1 April 2015 to 31 March 2023 and that Marginal Relief applies to profits from 1 April 2023, so the two-rate structure starts on 1 April 2023.",
            }
        ],
        tests=rule_tests(("count", 2), ("slab[main]", 25), ("slab[small_profits]", 19)),
        notes=(
            "Corporation Tax as GOV.UK states it: the main rate of 25% on profits over £250,000, the small profits rate of "
            "19% on profits of £50,000 or less, and Marginal Relief between those thresholds, which are reduced for short "
            "accounting periods and shared between associated companies. The structure has applied since 1 April 2023; "
            "valid_to is open. " + OGL_NOTE
        ),
    )


def sdlt_bands(table: list[list[str]]) -> list[dict]:
    """Bands of an SDLT rate table, named by the portion of the price they cover."""
    bands = []
    lower = 0
    for span, rate in table[1:]:
        upper = None if "remaining" in span.lower() else band_upper(span)
        name = f"above_{lower}" if upper is None else ("up_to" if lower == 0 else f"{lower + 1}_to") + f"_{upper}"
        bands.append({"name": name, "up_to": upper, "rate_percent": percent(rate), "portion": span})
        lower = upper if upper is not None else lower
    return bands


def sdlt_residential(sdlt: Source, relief: Source, higher: Source) -> dict:
    bands = sdlt_bands(table_with_cell(sdlt, "Up to £125,000"))
    vectors = [
        {"input": {"income": 295000}, "expected": "4750.00", "origin": "source", "note": "GOV.UK example: a house bought for £295,000"},
        {"input": {"income": 260000}, "expected": "3000.00", "origin": "source", "note": "GOV.UK shared ownership example: £260,000 paid in total"},
        {"input": {"income": 280000}, "expected": "4000.00", "origin": "source", "note": "GOV.UK example: market value £280,000 with SDLT paid on the full value"},
        {"input": {"income": 125000}, "expected": "0.00", "origin": "derived", "note": "the residential threshold"},
        {"input": {"income": 1500000}, "expected": tax_due(bands, 0, 1500000), "origin": "derived", "note": "top of the 10% band"},
    ]
    assert tax_due(bands, 0, 295000) == "4750.00"
    return entry(
        id="gb-stamp-duty-land-tax-residential-rates",
        title="England and Northern Ireland Stamp Duty Land Tax residential property rates (single main residence) from 1 April 2025",
        kind="rule",
        domain="tax",
        valid_from="2025-04-01",
        valid_to=None,
        tags=["stamp-duty", "sdlt", "property", "tax-rates"],
        use_cases=["property-demo", "mortgage-origination", "tax-filing-demo"],
        spec={
            "implementation": "almanac.rules.income_tax_bands",
            "parameters": {
                "currency": "GBP",
                "applies_to": "England and Northern Ireland",
                "personal_allowance": 0,
                "bands": bands,
                "first_time_buyer_relief": {"no_sdlt_up_to": 300000, "rate_percent_to_500000": 5, "max_purchase_price": 500000, "example": {"price": 500000, "sdlt": 10000}},
                "additional_property_surcharge_percent": 5,
                "non_uk_resident_surcharge_percent": 2,
            },
            "vectors": vectors,
        },
        evidence=[
            sdlt.cite("details.parts[1].body, residential rates table, first row", "<td>Up to £125,000</td>", "text", "at these rates if, after buying the property, it is the only residential property you own."),
            sdlt.cite("details.parts[1].body, residential rates table, last row", "<td>The remaining amount (the portion above £1.5 million)</td>", "text", "<td>12%</td>"),
            sdlt.cite("details.parts[1].body, worked example", "= £4,750</li>", "text", "In April 2025 you buy a house for £295,000"),
            sdlt.cite("details.parts[1].body, first-time buyers", "on the portion from £300,001 to £500,000</li>", "text", "up to £300,000</li>"),
            sdlt.cite("details.parts[1].body, additional properties", "You usually pay 5% on top of these rates if you own another residential property.", "text", "You’ll usually pay a 2% surcharge if you’re buying a residential property in England or Northern Ireland."),
            sdlt.cite("details.parts[4].body, shared ownership example", "= £4,000</li>", "text", "You pay £140,000 to buy a 50% share of a property with a market value of £280,000."),
            relief.cite("details.body, first time buyers", "If you bought your first home before 1 April 2025", "text", "the purchase price is no more than £500,000"),
            higher.cite("details.body, 'The higher rates from 1 April 2025'", "The higher rates from 1 April 2025", "text", "with effect from 1 April 2021 the rates increased by 2%."),
        ],
        assumed=[
            {
                "parameter": "valid_from",
                "value": "2025-04-01",
                "method": "derived",
                "rationale": "The Stamp Duty Land Tax guide does not date its table; HMRC dates the higher rates (these rates plus 5%) from 1 April 2025 and states that different first-time buyer relief applied before 1 April 2025, so the standard table is taken to apply from that date.",
            }
        ],
        tests=rule_tests(("count", len(bands)), ("rate[up_to_125000]", 0), ("rate[250001_to_925000]", 5), ("rate[above_1500000]", 12)),
        notes=(
            "Stamp Duty Land Tax on a residential property that will be the buyer's only home, in England and Northern "
            "Ireland: 0% up to £125,000, 2% to £250,000, 5% to £925,000, 10% to £1.5 million and 12% above, charged on each "
            "portion of the price. The income_tax_bands rule computes the duty with a zero allowance; GOV.UK's worked "
            "examples are the test vectors. First-time buyer relief (0% to £300,000, 5% to £500,000, unavailable above "
            "£500,000), the 5% additional-property surcharge and the 2% non-UK-resident surcharge are kept as parameters and "
            "are not applied by the rule. Scotland and Wales levy their own taxes. " + OGL_NOTE
        ),
    )


def sdlt_additional_property(higher: Source) -> dict:
    bands = sdlt_bands(table_with_cell(higher, "Up to £125,000"))
    assert tax_due(bands, 0, 300000) == "20000.00"
    return entry(
        id="gb-stamp-duty-land-tax-additional-property-rates",
        title="England and Northern Ireland Stamp Duty Land Tax higher rates for additional residential properties from 1 April 2025",
        kind="rule",
        domain="tax",
        valid_from="2025-04-01",
        valid_to=None,
        tags=["stamp-duty", "sdlt", "property", "tax-rates", "buy-to-let"],
        use_cases=["property-demo", "mortgage-origination", "tax-filing-demo"],
        spec={
            "implementation": "almanac.rules.income_tax_bands",
            "parameters": {"currency": "GBP", "applies_to": "England and Northern Ireland", "personal_allowance": 0, "bands": bands, "exempt_below": 40000, "surcharge_over_standard_rates_percent": 5},
            "vectors": [
                {"input": {"income": 300000}, "expected": "20000.00", "origin": "source", "note": "HMRC example: an additional property bought for £300,000 on 1 April 2025"},
                {"input": {"income": 125000}, "expected": "6250.00", "origin": "derived", "note": "5% on the whole first band"},
                {"input": {"income": 1000000}, "expected": tax_due(bands, 0, 1000000), "origin": "derived"},
            ],
        },
        evidence=[
            higher.cite("details.body, 'The higher rates from 1 April 2025' table, first row", "5%</td>", "text", "The higher rates from 1 April 2025"),
            higher.cite("details.body, 'The higher rates from 1 April 2025' table, last row", "17%</td>", "text", "The remaining amount (the portion above £1.5 million)"),
            higher.cite("details.body, worked example", "= £20,000</p>", "text", "10% on the final £50,000 = £5,000"),
            higher.cite("details.body, 'Property'", "the property is worth less than £40,000", "text", "The higher rates do not apply to certain people, property and transactions."),
        ],
        assumed=[],
        tests=rule_tests(("count", len(bands)), ("rate[up_to_125000]", 5), ("rate[above_1500000]", 17)),
        notes=(
            "The higher rates of Stamp Duty Land Tax that apply when buying a residential property in England or Northern "
            "Ireland leaves the buyer owning more than one: 5% up to £125,000, 7% to £250,000, 10% to £925,000, 15% to "
            "£1.5 million and 17% above, each the standard rate plus 5 percentage points, in force from 1 April 2025 as HMRC "
            "dates them. Properties worth less than £40,000 are outside the higher rates. HMRC's worked example is the "
            "source vector. " + OGL_NOTE
        ),
    )


def iht_nil_rate_band(thresholds: Source, iht: Source) -> dict:
    tables = html_tables(body_html(thresholds))
    nil_rate = find_table(tables, "Threshold (nil rate band)")
    residence = find_table(tables, "residence nil rate band")
    iso = lambda text: datetime.strptime(text, "%d %B %Y").date().isoformat()  # noqa: E731
    steps = sorted(({"from": iso(start), "to": iso(end), "value": number(amount)} for start, end, amount in nil_rate[1:]), key=lambda s: s["from"])
    residence_steps = sorted(({"from": iso(start), "to": iso(end), "value": number(amount)} for start, end, amount in residence[1:]), key=lambda s: s["from"])
    taper = find_table(html_tables(body_html(iht)), "Years between gift and death")
    return entry(
        id="gb-inheritance-tax-nil-rate-band",
        title="United Kingdom Inheritance Tax nil-rate band by date from 18 March 1986 to 5 April 2031, with the residence nil-rate band and tax rates",
        kind="rule",
        domain="tax",
        valid_from=steps[0]["from"],
        valid_to=steps[-1]["to"],
        tags=["inheritance-tax", "nil-rate-band", "thresholds", "estates"],
        use_cases=["financial-planning", "personal-finance", "tax-filing-demo", "insurance"],
        spec={
            "implementation": "almanac.rules.step_schedule",
            "parameters": {
                "currency": "GBP",
                "steps": steps,
                "residence_nil_rate_band_steps": residence_steps,
                "standard_rate_percent": 40,
                "reduced_rate_percent_with_10_percent_to_charity": 36,
                "gift_taper_relief": [{"years_between_gift_and_death": row[0], "rate_percent": number(row[1])} for row in taper[1:]],
                "annual_gift_exemption": 3000,
            },
            "vectors": [
                {"input": {"on": "2026-06-01"}, "expected": 325000, "origin": "source"},
                {"input": {"on": "2008-06-01"}, "expected": 312000, "origin": "source"},
                {"input": {"on": "1990-01-01"}, "expected": 118000, "origin": "source"},
                {"input": {"on": "1986-03-18"}, "expected": 71000, "origin": "source", "note": "first day of the table"},
                {"input": {"on": "2009-04-05"}, "expected": 312000, "origin": "derived", "note": "last day before the £325,000 band"},
            ],
        },
        evidence=[
            thresholds.cite("details.body, 'Inheritance Tax thresholds' table, row 6 April 2009", "<td>£325,000</td>", "text", "Inheritance Tax thresholds — from 18 March 1986 to 5 April 2031"),
            thresholds.cite("details.body, 'Inheritance Tax thresholds' table, row 18 March 1986", "<td>£71,000</td>", "text", "<td>18 March 1986</td>"),
            thresholds.cite("details.body, 'Inheritance Tax thresholds' table, row 6 April 2008", "<td>£312,000</td>", "text", "<td>6 April 2008</td>"),
            thresholds.cite("details.body, residence nil rate band table, row 6 April 2020", "<td>£175,000</td>", "text", "Inheritance Tax additional threshold (residence nil rate band) — from 6 April 2017"),
            iht.cite("details.parts[0].body, rates", "The standard Inheritance Tax rate is 40%.", "text", "reduced rate of 36%"),
            iht.cite("details.parts[2].body, 'Taper relief' table, row 3 to 4 years", "<td>32%</td>", "text", "Years between gift and death"),
            iht.cite("details.parts[2].body, annual exemption", "You can give away a total of £3,000 worth of gifts each tax year", "text", "This is known as your ‘annual exemption’."),
        ],
        assumed=[],
        tests=rule_tests(("count", len(steps)), ("value[2026-01-01]", 325000), ("value[1999-06-01]", 231000), ("min", 71000), ("max", 325000)),
        notes=(
            "The Inheritance Tax nil-rate band (tax-free threshold) for every period from 18 March 1986, when the tax "
            "replaced Capital Transfer Tax, to 5 April 2031, as HMRC's 'Inheritance Tax thresholds and interest rates' table "
            "lists it; the step_schedule rule answers the threshold in force on a date. The residence nil-rate band steps "
            "from 6 April 2017, the 40% standard and 36% charity-reduced rates, the gift taper relief scale and the £3,000 "
            "annual exemption are kept as parameters from GOV.UK's Inheritance Tax guide. " + OGL_NOTE
        ),
    )


def personal_allowances(employers: Source, marriage: Source, savings: Source, dividends: Source, cgt: Source, isa: Source) -> dict:
    rows = {
        "personal_allowance": {"value": 12570, "unit": "GBP per year", "basis": "standard Personal Allowance"},
        "marriage_allowance_transferable": {"value": 1260, "unit": "GBP per year", "basis": "Personal Allowance a lower-earning spouse or civil partner can transfer"},
        "marriage_allowance_max_tax_reduction": {"value": 252, "unit": "GBP per year", "basis": "largest tax saving from the transfer"},
        "personal_savings_allowance_basic_rate": {"value": 1000, "unit": "GBP per year", "basis": "basic rate taxpayer"},
        "personal_savings_allowance_higher_rate": {"value": 500, "unit": "GBP per year", "basis": "higher rate taxpayer"},
        "personal_savings_allowance_additional_rate": {"value": 0, "unit": "GBP per year", "basis": "additional rate taxpayer"},
        "starting_rate_for_savings": {"value": 5000, "unit": "GBP per year", "basis": "reduced by £1 for every £1 of other income above the Personal Allowance"},
        "starting_rate_for_savings_other_income_limit": {"value": 17570, "unit": "GBP per year", "basis": "other taxable income below which the starting rate applies"},
        "dividend_allowance": {"value": 500, "unit": "GBP per year", "basis": "dividend income taxed at 0%"},
        "capital_gains_annual_exempt_amount": {"value": 3000, "unit": "GBP per year", "basis": "individuals"},
        "capital_gains_annual_exempt_amount_trusts": {"value": 1500, "unit": "GBP per year", "basis": "trusts"},
        "isa_annual_allowance": {"value": 20000, "unit": "GBP per tax year", "basis": "all ISAs combined"},
        "lifetime_isa_annual_limit": {"value": 4000, "unit": "GBP per tax year", "basis": "counts towards the ISA allowance"},
    }
    return entry(
        id="gb-personal-tax-free-allowances-2026-27",
        title="United Kingdom personal tax-free allowances for 2026 to 2027: Personal, Marriage, savings, dividend, capital gains and ISA allowances",
        kind="rule",
        domain="tax",
        **TAX_YEAR,
        tags=["allowances", "income-tax", "savings", "isa", "dividends", "capital-gains-tax"],
        use_cases=["personal-finance", "financial-planning", "tax-filing-demo", "banking-demo"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"tax_year": "2026-27", "currency": "GBP", "rows": rows},
            "vectors": [
                {"input": {"key": "isa_annual_allowance", "column": "value"}, "expected": 20000, "origin": "source"},
                {"input": {"key": "personal_allowance", "column": "value"}, "expected": 12570, "origin": "source"},
                {"input": {"key": "dividend_allowance", "column": "value"}, "expected": 500, "origin": "source"},
                {"input": {"key": "personal_savings_allowance_additional_rate", "column": "value"}, "expected": 0, "origin": "source"},
                {"input": "blind_persons_allowance", "expected": False, "origin": "derived", "note": "not covered by this table"},
            ],
        },
        evidence=[
            employers.cite("details.body, 'England and Northern Ireland' Personal Allowance list", "<li>£12,570 per year</li>", "text", "The standard employee personal allowance for the 2026 to 2027 tax year is:"),
            marriage.cite("details.parts[0].body, opening paragraph", "Marriage Allowance lets you transfer £1,260 of your", "text", "This reduces their tax by up to £252 in the tax year"),
            savings.cite("details.parts[1].body, Personal Savings Allowance table", "<td>£1,000</td>", "text", "This is your Personal Savings Allowance."),
            savings.cite("details.parts[1].body, Personal Savings Allowance table, higher and additional rate rows", "<td>£500</td>", "text", "<td>£0</td>"),
            savings.cite("details.parts[1].body, starting rate for savings", "you can earn up to £5,000 of interest and not have to pay tax on it", "text", "is less than £17,570"),
            dividends.cite("details.parts[0].body, dividend allowance", "You also get a dividend allowance of £500 each year.", "text", "dividend allowance of £500"),
            cgt.cite("details.parts[2].body, allowances", "<li>£1,500 for trusts</li>", "text", "<li>£3,000</li>"),
            isa.cite("details.parts[0].body, overview", "the maximum you can save in ISAs is <em>£20,000</em>", "text", "In the 2026 to 2027 tax year, the maximum you can save in"),
            isa.cite("details.parts[1].body, Lifetime ISA", "£4,000 in a tax year", "text", "The maximum you can pay in is £4,000 in a tax year."),
        ],
        assumed=[
            {
                "parameter": "rows[marriage_allowance_*] and rows[personal_savings_allowance_*, starting_rate_for_savings*]",
                "value": "attributed to the 2026 to 2027 tax year",
                "method": "derived",
                "rationale": "The Marriage Allowance and savings interest pages state current figures without naming the tax year; they were fetched during the 2026 to 2027 tax year, and the Personal Allowance they quote matches the 2026 to 2027 figure HMRC dates.",
            }
        ],
        tests=rule_tests(("count", len(rows)), ("value[personal_allowance,value]", 12570), ("value[isa_annual_allowance,value]", 20000), ("max[value]", 20000)),
        notes=(
            "The tax-free allowances an individual has for the 2026 to 2027 tax year, gathered from the GOV.UK pages that "
            "state each one: the £12,570 Personal Allowance, the £1,260 Marriage Allowance transfer worth up to £252, the "
            "Personal Savings Allowance by band, the £5,000 starting rate for savings, the £500 dividend allowance, the "
            "Capital Gains Annual Exempt Amount and the £20,000 ISA allowance with the £4,000 Lifetime ISA limit. Each row "
            "names its basis. The tapering of the Personal Allowance above £100,000 is in gb-income-tax-bands-2026-27. " + OGL_NOTE
        ),
    )


def main() -> int:
    employers = govuk("guidance/rates-and-thresholds-for-employers-2026-to-2027", HMRC)
    letters = govuk("national-insurance-rates-letters", HMRC)
    intro = govuk("national-insurance", HMRC)
    scottish = govuk("scottish-income-tax", HMRC)
    income_tax = govuk("income-tax-rates", HMRC)
    dividends = govuk("tax-on-dividends", HMRC)
    cgt = govuk("capital-gains-tax", HMRC)
    sdlt = govuk("stamp-duty-land-tax", HMRC)
    relief = govuk("guidance/stamp-duty-land-tax-relief-for-land-or-property-transactions", HMRC)
    higher = govuk("guidance/stamp-duty-land-tax-buying-an-additional-residential-property", HMRC)
    thresholds = govuk("government/publications/rates-and-allowances-inheritance-tax-thresholds-and-interest-rates/inheritance-tax-thresholds-and-interest-rates", HMRC)
    write(ni_class_1_rates(employers, letters))
    write(ni_class_1_thresholds(employers, intro))
    write(ni_category_letters(letters))
    write(ni_self_employed(intro))
    write(scottish_income_tax(employers, scottish, income_tax))
    write(dividend_rates(dividends))
    write(capital_gains_rates(cgt))
    write(corporation_tax_rates(govuk("corporation-tax-rates", HMRC)))
    write(sdlt_residential(sdlt, relief, higher))
    write(sdlt_additional_property(higher))
    write(iht_nil_rate_band(thresholds, govuk("inheritance-tax", HMRC)))
    write(personal_allowances(employers, govuk("marriage-allowance", HMRC), govuk("apply-tax-free-interest-on-savings", HMRC), dividends, cgt, govuk("individual-savings-accounts", HMRC)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build India business-rule entries for payroll, HR, lending, invoicing and compliance demos.

Sources are official texts that are byte-stable when fetched: the Labour
Codes, the Companies Act, 2013 and their subordinate notifications as
published by India Code (the Legislative Department's repository, served
through its DSpace bitstream API), the Ministry of MSME's CMS record of the
revised enterprise classification, the Memorandum to the Finance Bill, 2026
on indiabudget.gov.in, and SEBI's 2017 circular on mutual fund scheme categories. Every
value and snippet is checked against the extracted text before an entry is
written, and each PDF locator names the page the snippet was found on. Run
from the repository root:

    uv run python tools/build_in_rules.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import httpx
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

ACCESSED = "2026-11-03"
UNSTATED = "unstated"

INDIA_CODE = "https://indiacode.gov.in/server/api/core/bitstreams/{}/content"
WAGES_URL = INDIA_CODE.format("7e3863af-0263-4c95-a42a-1bdd0a55a5fc")
SOCIAL_SECURITY_URL = INDIA_CODE.format("0d5654a4-6119-4ef2-98d5-2a2fecd979dc")
INDUSTRIAL_RELATIONS_URL = INDIA_CODE.format("3445e64d-acb1-432d-9684-028ab37cb788")
IR_AMENDMENT_URL = INDIA_CODE.format("9d6c106a-1510-4122-b4f1-9c24bf37666e")
OSH_URL = INDIA_CODE.format("3a7333e5-1f94-4f64-aff7-be67c0e63435")
GRATUITY_CEILING_URL = INDIA_CODE.format("c1e116f5-07c9-4647-bab3-39c7484f3942")
EPF_ADMIN_URL = INDIA_CODE.format("ffba9ade-7ad1-4f0b-a644-095f528d2637")
COMPANIES_ACT_URL = INDIA_CODE.format("95902c38-5947-4457-a431-5062e234cab0")
DEFINITIONS_RULES_2022_URL = INDIA_CODE.format("e14dc377-81a3-4275-9440-d56f6d9fb3ce")
MSME_2020_URL = INDIA_CODE.format("e6bb2cb5-9cac-469f-a5a9-787191ab5e44")
MSME_2025_URL = "https://www.msme.gov.in/cms/wp-json/wp/v2/pages_detailed_data/12332"
MEMO_URL = "https://www.indiabudget.gov.in/doc/memo.pdf"
SEBI_CATEGORISATION_URL = "https://www.sebi.gov.in/sebi_data/attachdocs/oct-2017/1509103633344.pdf"

INDIA_CODE_PUBLISHER = "Legislative Department, Ministry of Law and Justice (India Code)"
MOLE = "Ministry of Labour and Employment, Government of India (via India Code)"
MCA = "Ministry of Corporate Affairs, Government of India (via India Code)"
MSME = "Ministry of Micro, Small and Medium Enterprises, Government of India"
MOF = "Ministry of Finance, Government of India"
SEBI = "Securities and Exchange Board of India"

WAGES_TITLE = "The Code on Wages, 2019 (Act No. 29 of 2019), India Code text as on 21 November 2025"
SS_TITLE = "The Code on Social Security, 2020 (Act No. 36 of 2020), India Code text as on 21 November 2025"
IR_TITLE = "The Industrial Relations Code, 2020 (Act No. 35 of 2020), India Code text as on 1 September 2026"
IR_AMENDMENT_TITLE = "The Industrial Relations Code (Amendment) Act, 2026 (No. 1 of 2026), Gazette of India Extraordinary"
OSH_TITLE = "The Occupational Safety, Health and Working Conditions Code, 2020 (Act No. 37 of 2020), India Code text as on 28 November 2025"
GRATUITY_TITLE = "Notifications S.O. 1419(E) and S.O. 1420(E) of 29 March 2018 under the Payment of Gratuity Act, 1972"
EPF_ADMIN_TITLE = "Notification S.O. 2011(E) of 21 May 2018 fixing EPF administrative charges"
COMPANIES_TITLE = "The Companies Act, 2013 (Act No. 18 of 2013), India Code text as on 1 September 2026"
RULES_2022_TITLE = "G.S.R. 700(E), Companies (Specification of Definitions Details) Amendment Rules, 2022, 15 September 2022"
MSME_2020_TITLE = "Notification S.O. 2119(E) of 26 June 2020 on the classification of micro, small and medium enterprises"
MSME_2025_TITLE = "What's MSME: revised classification applicable from 1 April 2025 (Ministry of MSME website content record)"
MEMO_TITLE = "Memorandum Explaining the Provisions in the Finance Bill, 2026"
SEBI_TITLE = "SEBI circular SEBI/HO/IMD/DF3/CIR/P/2017/114, Categorization and Rationalization of Mutual Fund Schemes, 6 October 2017"

LABOUR_TAGS = ["india", "payroll", "labour-law", "compliance"]
LABOUR_USE_CASES = ["payroll-demo", "hr-demo", "hr-analytics", "compliance-demo"]
COMPANY_USE_CASES = ["company-generation", "kyb-onboarding", "compliance-demo"]
CODES_IN_FORCE = "2025-11-21"

RAW: dict[str, bytes] = {}
TEXT: dict[str, str] = {}
PAGES: dict[str, list[str]] = {}


def collapse(text: str) -> str:
    return " ".join(text.split())


def load(url: str) -> bytes:
    """Fetch a resource once, keeping its bytes, its searchable text and, for a PDF, each page's text."""
    if url not in RAW:
        for attempt in range(3):
            try:
                RAW[url] = fetch(url)
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise
        TEXT[url] = collapse(Resource(url, RAW[url], "").text)
        if RAW[url].startswith(b"%PDF"):
            PAGES[url] = [collapse(page.extract_text() or "") for page in PdfReader(io.BytesIO(RAW[url])).pages]
    return RAW[url]


def page_of(url: str, snippet: str) -> int | None:
    """One-based PDF page holding the snippet, or None when it spans a page break or the resource is not a PDF."""
    target = collapse(snippet)
    return next((index for index, page in enumerate(PAGES.get(url, []), 1) if target in page), None)


def cite(publisher: str, title: str, url: str, where: str, value: Any, snippet: str, role: str = "primary", unit: str = "text") -> dict:
    """Evidence item whose value and snippet are confirmed present in the fetched text, located by PDF page."""
    raw = load(url)
    for label, needle in (("value", str(value)), ("snippet", snippet)):
        if collapse(needle) not in TEXT[url]:
            raise ValueError(f"{label} not found in {url}: {needle!r}")
    if len(snippet.split()) > 24:
        raise ValueError(f"snippet over 24 words: {snippet!r}")
    page = page_of(url, snippet)
    locator = f"PDF page {page}, {where}" if page else where
    item = evidence(publisher, title, url, locator, value, unit, snippet, UNSTATED, raw, role)
    item["accessed_at"] = ACCESSED
    return item


def wages(where: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return cite(MOLE, WAGES_TITLE, WAGES_URL, where, value, snippet, role)


def social(where: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return cite(MOLE, SS_TITLE, SOCIAL_SECURITY_URL, where, value, snippet, role)


def industrial(where: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return cite(MOLE, IR_TITLE, INDUSTRIAL_RELATIONS_URL, where, value, snippet, role)


def osh(where: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return cite(MOLE, OSH_TITLE, OSH_URL, where, value, snippet, role)


def companies(where: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return cite(MCA, COMPANIES_TITLE, COMPANIES_ACT_URL, where, value, snippet, role)


def rule_entry(
    entry_id: str,
    title: str,
    domain: str,
    valid: tuple[str, str | None],
    implementation: str,
    parameters: dict,
    vectors: list[dict],
    evidence_items: list[dict],
    tests: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str],
    assumed: list[dict] | None = None,
) -> dict:
    if len(title) > 140:
        raise ValueError(f"title over 140 characters: {title!r}")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "IN",
        "status": "license-review",
        "tier": "B",
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes,
    }


def vector(value: Any, expected: Any, origin: str, note: str | None = None) -> dict:
    item = {"input": value, "expected": expected, "origin": origin}
    if note:
        item["note"] = note
    return item


def lookup(key: str, column: str, expected: Any, origin: str = "source", note: str | None = None) -> dict:
    return vector({"key": key, "column": column}, expected, origin, note)


def value_tests(rows: dict, column: str) -> list[dict]:
    return [{"statistic": "count", "expected": len(rows), "tolerance": 0}, *({"statistic": f"value[{key},{column}]", "expected": row[column], "tolerance": 0} for key, row in rows.items() if isinstance(row[column], (int, float)))]


def commencement() -> dict:
    rows = {
        "code_on_wages_2019": {"act": "Act No. 29 of 2019", "in_force_from": CODES_IN_FORCE, "notification": "S.O. 5322(E)", "repeals": "Payment of Wages Act, 1936; Minimum Wages Act, 1948; Payment of Bonus Act, 1965; Equal Remuneration Act, 1976"},
        "industrial_relations_code_2020": {"act": "Act No. 35 of 2020", "in_force_from": CODES_IN_FORCE, "notification": "S.O. 5320(E)", "repeals": "Trade Unions Act, 1926; Industrial Employment (Standing Orders) Act, 1946; Industrial Disputes Act, 1947"},
        "code_on_social_security_2020": {"act": "Act No. 36 of 2020", "in_force_from": CODES_IN_FORCE, "notification": "S.O. 5319(E)", "repeals": "nine enactments, among them the Employees' State Insurance Act, 1948, the EPF Act, 1952, the Maternity Benefit Act, 1961 and the Payment of Gratuity Act, 1972"},
        "occupational_safety_health_code_2020": {"act": "Act No. 37 of 2020", "in_force_from": CODES_IN_FORCE, "notification": "S.O. 5321(E)", "repeals": "thirteen enactments, among them the Factories Act, 1948, the Mines Act, 1952 and the Contract Labour (Regulation and Abolition) Act, 1970"},
    }
    return rule_entry(
        "in-labour-codes-commencement-2025",
        "India Labour Codes in force from 21 November 2025: Code on Wages, IR Code, Social Security Code and OSH Code",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("code_on_wages_2019", "notification", "S.O. 5322(E)"),
            lookup("code_on_social_security_2020", "notification", "S.O. 5319(E)"),
            lookup("industrial_relations_code_2020", "in_force_from", CODES_IN_FORCE),
            lookup("occupational_safety_health_code_2020", "act", "Act No. 37 of 2020"),
            vector("code_on_wages_2019", True, "source"),
        ],
        [
            wages("footnote 1 to section 1(3)", "S.O. 5322 (E)", "vide notification no. S.O. 5322 (E), dated 21st November, 2025"),
            social("footnote 1 to section 1(3)", "S.O. 5319 (E)", "vide notification no. S.O. 5319 (E), dated 21st November, 2025"),
            industrial("footnote 1 to section 1(3)", "S.O. 5320(E)", "vide Notifn. No. S.O. 5320(E), dated 21st November"),
            osh("footnote 1 to section 1(3)", "S.O. 5321 (E)", "vide Notifn. No. S.O. 5321 (E), dated 21st day of November, 2025"),
            cite(INDIA_CODE_PUBLISHER, IR_AMENDMENT_TITLE, IR_AMENDMENT_URL, "section 1(2)", "21st day of November, 2025", "It shall be deemed to have come into force from the 21st day of November, 2025."),
            cite(INDIA_CODE_PUBLISHER, IR_AMENDMENT_TITLE, IR_AMENDMENT_URL, "section 2, substituted section 104(1)", "the Industrial Disputes Act, 1947", "the Industrial Employment (Standing Orders) Act, 1946; and", "supporting"),
            social("section 164(1), repeal", "The Payment of Gratuity Act, 1972 (39 of 1972);", "The Employees' Provident Funds and Miscellaneous Provisions Act, 1952 (19 of 1952);", "supporting"),
            wages("section 69(1), repeal", "the Payment of Bonus Act, 1965 (21 of 1965)", "the Payment of Bonus Act, 1965 (21 of 1965) and the Equal Remuneration Act, 1976 (25 of 1976) are hereby repealed.", "supporting"),
            osh("section 143(1), repeal", "(a) The Factories Act, 1948 (63 of 1948);", "(h) The Contract Labour (Regulation and Abolition) Act, 1970 (37 of 1970);", "supporting"),
        ],
        [{"statistic": "count", "expected": 4, "tolerance": 0}],
        "The four Labour Codes, enacted in 2019 and 2020, were brought into force on 21 November 2025 by four notifications of that "
        "date in the Gazette of India: S.O. 5322(E) for the Code on Wages, S.O. 5320(E) for the Industrial Relations Code, S.O. "
        "5319(E) for the Code on Social Security and S.O. 5321(E) for the Occupational Safety, Health and Working Conditions Code. "
        "India Code's consolidated texts record each notification in a footnote to section 1(3). A few provisions came into force "
        "earlier (parts of the Code on Wages on 18 December 2020 and section 142 of the Social Security Code on 3 May 2021) and "
        "some remain to be notified, as the footnotes list. The Industrial Relations Code (Amendment) Act, 2026 is deemed in force "
        "from the same date and restates the repeal of the Trade Unions, Standing Orders and Industrial Disputes Acts. The "
        "'repeals' column names the Acts each Code's repeal section lists (in part, for the two Codes that repeal nine and "
        "thirteen Acts); payroll records dated on or after 21 November 2025 should cite the Codes rather than the repealed Acts. "
        "India Code states no reuse licence.",
        LABOUR_TAGS + ["labour-codes", "commencement"],
        LABOUR_USE_CASES,
        [{"parameter": "rows.*.repeals", "value": "summary of the repeal sections", "method": "derived", "rationale": "Condensed from the repeal provision of each Code (section 69 of the Code on Wages, section 104 of the IR Code as substituted in 2026, section 164 of the Social Security Code, section 143 of the OSH Code) to orient a reader; not used by any vector."}],
    )


def wage_definition() -> dict:
    return rule_entry(
        "in-code-on-wages-wage-definition-50-percent-rule",
        "India Code on Wages s 2(y) wage definition: excluded allowances above half of total remuneration count as wages",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.in_labour_codes",
        {
            "formula": "code_wages",
            "currency": "INR",
            "included_components": ["basic pay", "dearness allowance", "retaining allowance"],
            "excluded_components_counted_against_limit": [
                "statutory bonus not part of the terms of employment",
                "value of house accommodation, light, water, medical attendance or other amenity",
                "employer contribution to pension or provident fund and interest on it",
                "conveyance allowance or travelling concession",
                "sums to defray special expenses of the employment",
                "house rent allowance",
                "remuneration under an award or settlement",
                "overtime allowance",
                "commission",
            ],
            "excluded_components_outside_limit": ["gratuity on termination", "retrenchment compensation, retirement benefit or ex gratia on termination"],
            "excluded_share_limit_percent": 50,
            "in_kind_share_limit_percent": 15,
        },
        [
            vector({"included": 50000, "excluded": 50000}, "50000.00", "source", "excluded payments of exactly one-half of all remuneration are not added back"),
            vector({"included": 40000, "excluded": 60000}, "50000.00", "derived", "₹10,000 of the excluded ₹60,000 lies above half of ₹1,00,000 and is added to wages"),
            vector({"included": 25000, "excluded": 75000}, "50000.00", "derived"),
            vector({"included": 60000, "excluded": 40000}, "60000.00", "derived", "excluded payments below the limit leave wages unchanged"),
            vector({"included": 15000, "excluded": 0}, "15000.00", "derived"),
        ],
        [
            wages("section 2(y)", "(i) basic pay;", "includes, — (i) basic pay; (ii) dearness allowance; and (iii) retaining allowance, if any,"),
            wages("section 2(y), first proviso", "exceeds one-half", "if payments made by the employer to the employee under clauses (a) to (i) exceeds one-half, or such other per cent."),
            wages("section 2(y), first proviso", "shall be deemed as remuneration", "the amount which exceeds such one-half, or the per cent. so notified, shall be deemed as remuneration"),
            wages("section 2(y), Explanation", "fifteen per cent.", "kind which does not exceed fifteen per cent. of the total wages payable to him"),
            wages("section 2(y)(f) and (h)", "(f) house rent allowance;", "(f) house rent allowance;", "supporting"),
        ],
        [{"statistic": "parameter[excluded_share_limit_percent]", "expected": 50, "tolerance": 0}],
        "Section 2(y) of the Code on Wages, 2019, in force from 21 November 2025, defines wages as basic pay, dearness allowance and "
        "retaining allowance, and excludes a list of payments: statutory bonus, amenities, employer provident fund and pension "
        "contributions, conveyance, special-expense reimbursements, house rent allowance, award payments, overtime, commission, "
        "gratuity and retrenchment or retirement payments. The first proviso caps the exclusions: where the payments under clauses "
        "(a) to (i) exceed one-half (or another notified share) of all remuneration, the excess is deemed remuneration and added to "
        "wages. The rule takes the sum of included components and the sum of clause (a) to (i) exclusions and returns the wage. "
        "Wages so computed drive provident fund, gratuity and bonus calculations, so a synthetic salary structure with a low basic "
        "pay and large allowances should be checked here. The Explanation separately counts remuneration in kind up to 15% of total "
        "wages as wages; the second proviso brings conveyance, house rent, award pay and overtime back in for equal-wage and "
        "payment-of-wages purposes. Gratuity and retrenchment payments (clauses (j) and (k)) are outside the cap and should be "
        "left out of ``excluded``.",
        LABOUR_TAGS + ["wages", "salary-structure"],
        LABOUR_USE_CASES,
    )


def bonus() -> dict:
    return rule_entry(
        "in-code-on-wages-bonus-limits",
        "India Code on Wages s 26 statutory bonus: minimum 8 1/3% of wages or ₹100, maximum 20%, paid within eight months",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.in_labour_codes",
        {
            "formula": "bonus",
            "currency": "INR",
            "minimum_rate_fraction": [1, 12],
            "minimum_rate_text": "eight and one-third per cent. of the wages earned",
            "minimum_amount": 100,
            "maximum_percent": 20,
            "minimum_days_worked_in_year": 30,
            "applies_to_establishments_employing": 20,
            "payment_within_months_of_year_end": 8,
            "eligibility_wage_ceiling": None,
        },
        [
            vector({"wages_earned": 1000}, {"minimum": "100.00", "maximum": "200.00"}, "source", "one hundred rupees where higher than 8 1/3% of wages"),
            vector({"wages_earned": 120000}, {"minimum": "10000.00", "maximum": "24000.00"}, "derived"),
            vector({"wages_earned": 216000}, {"minimum": "18000.00", "maximum": "43200.00"}, "derived"),
            vector({"wages_earned": 300}, {"minimum": "100.00", "maximum": "100.00"}, "derived", "the floor exceeds 20% of very low wages"),
        ],
        [
            wages("section 26(1)", "eight and one-third per cent.", "calculated at the rate of eight and one-third per cent. of the wages earned by the employee or one hundred"),
            wages("section 26(1)", "at least thirty days work", "who has put in at least thirty days work in an accounting year, an annual minimum bonus"),
            wages("section 26(3)", "subject to a maximum of twenty per cent. of such wages", "accounting year, subject to a maximum of twenty per cent. of such wages."),
            wages("section 38(2)", "twenty or more persons", "the provisions of this Chapter shall apply to such establishment in which twenty or more persons are employed"),
            wages("section 39(1)", "eight months", "period of eight months from the close of the accounting year:"),
        ],
        [{"statistic": "parameter[maximum_percent]", "expected": 20, "tolerance": 0}, {"statistic": "parameter[minimum_amount]", "expected": 100, "tolerance": 0}],
        "Chapter IV of the Code on Wages, 2019 (successor to the Payment of Bonus Act, 1965, in force from 21 November 2025) requires "
        "every establishment employing twenty or more persons to pay each eligible employee who worked at least thirty days in the "
        "accounting year a minimum bonus of eight and one-third per cent. of wages earned or one hundred rupees, whichever is "
        "higher, regardless of allocable surplus; where the allocable surplus is larger, bonus rises in proportion to wages up to "
        "twenty per cent. Bonus is due within eight months of the close of the accounting year. Eligibility is limited to employees "
        "drawing wages up to an amount the appropriate Government notifies, and bonus for employees above a notified calculation "
        "ceiling is computed as if their wage were that ceiling or the minimum wage; neither amount is stated in the Code, so "
        "``eligibility_wage_ceiling`` is left empty. The rule returns the minimum and maximum bonus for a year's wages.",
        LABOUR_TAGS + ["bonus"],
        LABOUR_USE_CASES,
        [{"parameter": "minimum_rate_fraction", "value": [1, 12], "method": "derived", "rationale": "Eight and one-third per cent. is exactly one-twelfth, which keeps the minimum bonus exact in decimal arithmetic."}],
    )


def wage_payment() -> dict:
    return rule_entry(
        "in-code-on-wages-payment-deadlines-and-deduction-limit",
        "India Code on Wages ss 16-18 wage periods, payment deadlines (monthly by the 7th) and 50% ceiling on deductions",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.in_labour_codes",
        {
            "formula": "wage_payment",
            "maximum_wage_period": "one month",
            "payment_deadlines": {
                "daily": {"due": "at the end of the shift"},
                "weekly": {"due": "on the last working day of the week, before the weekly holiday"},
                "fortnightly": {"days_after_period_end": 2, "due": "before the end of the second day after the end of the fortnight"},
                "monthly": {"day_of_following_month": 7, "due": "before the expiry of the seventh day of the succeeding month"},
            },
            "separation_payment_working_days": 2,
            "deduction_ceiling_percent": 50,
        },
        [
            vector({"wage_period": "monthly", "period_end": "2026-03-31"}, "2026-04-07", "source", "before the expiry of the seventh day of the succeeding month"),
            vector({"wage_period": "monthly", "period_end": "2026-12-31"}, "2027-01-07", "derived"),
            vector({"wage_period": "fortnightly", "period_end": "2026-04-15"}, "2026-04-17", "derived"),
            vector({"wage_period": "daily", "period_end": "2026-04-15"}, "2026-04-15", "derived"),
            vector({"deductions_ceiling_for": 30000}, "15000.00", "source", "deductions shall not exceed fifty per cent. of such wages"),
        ],
        [
            wages("section 16", "no wage period in respect of any employee shall be more than a month", "no wage period in respect of any employee shall be more than a month"),
            wages("section 17(1)(i) to (iii)", "at the end of the shift", "(iii) fortnightly basis, before the end of the second day after the end of the fortnight;"),
            wages("section 17(1)(iv)", "seventh day of the succeeding month", "(iv) monthly basis, before the expiry of the seventh day of the succeeding month."),
            wages("section 17(2)", "within two working days", "the wages payable to him shall be paid within two working days of his removal, dismissal, retrenchment"),
            wages("section 18(3)", "shall not exceed fifty per cent. of such wages", "any wage period from the wages of an employee shall not exceed fifty per cent. of such wages."),
        ],
        [{"statistic": "parameter[deduction_ceiling_percent]", "expected": 50, "tolerance": 0}, {"statistic": "parameter[separation_payment_working_days]", "expected": 2, "tolerance": 0}],
        "Chapter III of the Code on Wages, 2019 (in force from 21 November 2025) fixes how and when wages are paid. The wage period "
        "may be daily, weekly, fortnightly or monthly but never longer than a month (section 16). Wages are due at the end of the "
        "shift for daily workers, on the last working day before the weekly holiday for weekly workers, before the end of the "
        "second day after the fortnight for fortnightly workers, and before the expiry of the seventh day of the next month for "
        "monthly workers (section 17(1)); an employee who is removed, dismissed, retrenched or resigns, or loses work on closure, "
        "is paid within two working days (section 17(2)). The appropriate Government may set other limits. Total authorised "
        "deductions in a wage period may not exceed fifty per cent. of the wages (section 18(3)). The rule returns the last "
        "payment date for a period end (for weekly wages pass the last working day as ``period_end``) and the deduction ceiling "
        "for a wage amount; separation payments need a working-day calendar and are given as a parameter only.",
        LABOUR_TAGS + ["wages", "pay-date"],
        LABOUR_USE_CASES + ["payments-scheduling"],
    )


def working_hours() -> dict:
    rows = {
        "daily_working_hours_max": {"value": 8, "unit": "hours per day", "provision": "OSH Code s 25(1)(a)"},
        "working_days_per_week_max": {"value": 6, "unit": "days per week", "provision": "OSH Code s 26(1)"},
        "motor_transport_consecutive_days_max": {"value": 10, "unit": "days without a whole-day holiday", "provision": "OSH Code s 26(1) proviso"},
        "compensatory_holiday_window_months": {"value": 2, "unit": "months after the month the holiday was due", "provision": "OSH Code s 26(3)"},
        "overtime_rate_multiplier": {"value": 2, "unit": "times the rate of wages", "provision": "OSH Code s 27; Code on Wages s 14"},
        "annual_leave_qualifying_days": {"value": 180, "unit": "days worked in the calendar year", "provision": "OSH Code s 32(1)(i)"},
        "annual_leave_days_worked_per_leave_day": {"value": 20, "unit": "days of work per day of leave", "provision": "OSH Code s 32(1)(ii)"},
        "annual_leave_days_worked_per_leave_day_adolescent": {"value": 15, "unit": "days of work per day of leave", "provision": "OSH Code s 32(1)(ii)"},
        "annual_leave_days_worked_per_leave_day_underground_mine": {"value": 15, "unit": "days of work per day of leave", "provision": "OSH Code s 32(1)(ii)"},
        "rest_between_jobs_in_factory_or_mine_hours": {"value": 12, "unit": "hours", "provision": "OSH Code s 30"},
    }
    return rule_entry(
        "in-osh-code-working-hours-overtime-and-annual-leave",
        "India OSH Code 2020 working hours, weekly holiday, double-rate overtime and annual leave accrual (1 day per 20 worked)",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("daily_working_hours_max", "value", 8),
            lookup("working_days_per_week_max", "value", 6),
            lookup("overtime_rate_multiplier", "value", 2),
            lookup("annual_leave_qualifying_days", "value", 180),
            lookup("annual_leave_days_worked_per_leave_day", "value", 20),
        ],
        [
            osh("section 25(1)(a)", "eight hours in a day", "work, in any establishment or class of establishment for more than— (a) eight hours in a day; and"),
            osh("section 26(1)", "more than six days in any one week", "No worker shall be allowed to work in an establishment for more than six days in any one week:"),
            osh("section 26(1) proviso and 26(3)", "ten days consecutively", "the worker does not work for more than ten days consecutively without a holiday"),
            osh("section 27", "twice the rate of wages", "There shall be paid wages at the rate of twice the rate of wages in respect of overtime work"),
            osh("section 32(1)(i) and (ii)", "one hundred and eighty days or more", "(ii) that he shall be entitled for one -day leave for every twenty days of his work, in the case of"),
            osh("section 30", "preceding twelve hours", "establishment within the preceding twelve hours"),
            wages("section 14", "twice the normal rate of wages", "at the overtime rate which shall not be less than twice the normal rate of wages."),
        ],
        value_tests(rows, "value"),
        "Hours and leave limits of the Occupational Safety, Health and Working Conditions Code, 2020, in force from 21 November 2025: "
        "no worker may work more than eight hours a day (with intervals and spread-over notified by the appropriate Government) or "
        "more than six days a week; motor transport workers may be asked to work a weekly holiday but never more than ten days in a "
        "row; holidays lost to an exemption are given back within the month or the two months after. Overtime, beyond the daily or "
        "weekly hours the appropriate Government prescribes, is paid at twice the rate of wages, needs the worker's consent, and is "
        "counted daily or weekly whichever favours the worker; the Code on Wages separately sets overtime at not less than twice "
        "the normal rate for minimum-wage employees. A worker who has worked 180 days in a calendar year earns one day of annual "
        "leave with wages for every twenty days worked (fifteen for adolescents and below-ground mine workers). Weekly-hour and "
        "overtime-hour caps are left to State and Central rules and are not in this entry.",
        LABOUR_TAGS + ["working-time", "overtime", "annual-leave"],
        LABOUR_USE_CASES + ["workforce-planning"],
    )


def gratuity() -> dict:
    return rule_entry(
        "in-gratuity-code-on-social-security-2020",
        "India gratuity under Code on Social Security s 53: 15 days' wages a year on a 26-day month, 5-year rule, ₹20 lakh ceiling",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.in_labour_codes",
        {
            "formula": "gratuity",
            "currency": "INR",
            "days_per_year": 15,
            "month_divisor": 26,
            "part_year_months_above": 6,
            "qualifying_years": 5,
            "working_journalist_qualifying_years": 3,
            "reasons_without_qualifying_service": ["death", "disablement", "fixed_term_expiry"],
            "fixed_term_qualifying_years": 1,
            "seasonal_days_per_season": 7,
            "ceiling": 2000000,
        },
        [
            vector({"monthly_wage": 26000, "years": 5, "months": 0, "reason": "resignation"}, "75000.00", "source", "monthly wage divided by twenty-six and multiplied by fifteen, for five completed years"),
            vector({"monthly_wage": 52000, "years": 5, "months": 7, "reason": "superannuation"}, "180000.00", "derived", "a part year above six months counts as a year"),
            vector({"monthly_wage": 52000, "years": 5, "months": 6, "reason": "superannuation"}, "150000.00", "derived"),
            vector({"monthly_wage": 52000, "years": 4, "months": 11, "reason": "resignation"}, "0.00", "derived", "below five years of continuous service"),
            vector({"monthly_wage": 26000, "years": 1, "months": 6, "reason": "fixed_term_expiry"}, "22500.00", "derived", "pro rata for a fixed-term employee after one year"),
            vector({"monthly_wage": 26000, "years": 0, "months": 11, "reason": "fixed_term_expiry"}, "0.00", "derived"),
            vector({"monthly_wage": 26000, "years": 2, "months": 3, "reason": "death"}, "33750.00", "derived", "pro rata, no qualifying service on death"),
            vector({"monthly_wage": 500000, "years": 30, "months": 0, "reason": "superannuation"}, "2000000.00", "source", "capped at twenty lakh rupees"),
        ],
        [
            social("section 53(1)", "not less than five years", "after he has rendered continuous service for not less than five years,—"),
            social("section 53(1), second proviso", "expiration of fixed term employment", "the termination of the employment of any employee is due to death or disablement or expiration of fixed term employment"),
            social("section 53(2)", "fifteen days' wages", "the employer shall pay gratuity to an employee at the rate of fifteen days' wages or such number of days as may be notified"),
            social("section 53(2), third proviso", "pro rata basis", "fixed term employment or a deceased employee, the employer shall pay gratuity on pro rata basis."),
            social("section 53, Explanation 3", "dividing the monthly rate of wages last drawn by", "him by twenty-six and multiplying the quotient by fifteen."),
            social("section 53(2), second proviso", "seven days' wages", "the employer shall pay the gratuity at the rate of seven days' wages for each season:"),
            industrial("section 2(o), proviso (c)", "eligible for gratuity", "he shall be eligible for gratuity if he renders service under the contract for a period of one year;"),
            cite(MOLE, GRATUITY_TITLE, GRATUITY_CEILING_URL, "S.O. 1420(E)", "twenty lakh rupees", "under the said Act shall not exceed twenty lakh rupees."),
            social("section 164(2)(a), savings", "notification (including the notifications issued by the States)", "notification (including the notifications issued by the States), scheme, appointment, order", "supporting"),
        ],
        [{"statistic": "parameter[ceiling]", "expected": 2000000, "tolerance": 0}, {"statistic": "parameter[month_divisor]", "expected": 26, "tolerance": 0}],
        "Gratuity under Chapter V of the Code on Social Security, 2020 (in force from 21 November 2025, replacing the Payment of "
        "Gratuity Act, 1972). It is payable on superannuation, retirement, resignation, death, disablement or expiry of a fixed "
        "term after at least five years of continuous service (three for working journalists); the five-year condition does not "
        "apply on death, disablement or expiry of a fixed term, and section 2(o) of the Industrial Relations Code makes a "
        "fixed-term worker eligible after one year under the contract. The amount is fifteen days' wages for every completed year "
        "or part above six months, on the last wages drawn; a monthly-rated employee's fifteen days' wages are the monthly wage "
        "divided by twenty-six and multiplied by fifteen (Explanation 3), seasonal workers get seven days a season, and fixed-term "
        "and deceased employees are paid pro rata. Section 53(3) caps the total at an amount the Central Government notifies; the "
        "cap cited is the twenty lakh rupees notified under the 1972 Act in 2018 (S.O. 1420(E)), which section 164(2) keeps in force "
        "under the Code until replaced. Wages here are wages as defined in the Code (see in-code-on-wages-wage-definition-50-percent-rule).",
        LABOUR_TAGS + ["gratuity", "end-of-service"],
        LABOUR_USE_CASES + ["pensions"],
        [
            {"parameter": "pro_rata_method", "value": "exact months of service divided by twelve", "method": "derived", "rationale": "The Code says fixed-term and deceased employees are paid 'on pro rata basis' without a formula; the rule pro-rates the annual fifteen days by the months served."},
            {"parameter": "ceiling", "value": 2000000, "method": "derived", "rationale": "No ceiling notified under section 53(3) of the Code was found on India Code; the 2018 ceiling under the repealed 1972 Act is carried forward on the strength of the savings clause in section 164(2)."},
        ],
    )


def retrenchment() -> dict:
    return rule_entry(
        "in-retrenchment-and-layoff-compensation-ir-code-2020",
        "India IR Code 2020 retrenchment compensation (15 days' average pay a year), re-skilling fund credit and 50% lay-off pay",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.in_labour_codes",
        {
            "formula": "retrenchment",
            "currency": "INR",
            "qualifying_months": 12,
            "notice": "one month's notice in writing, or wages for the notice period in lieu",
            "days_per_year": 15,
            "part_year_months_above": 6,
            "reskilling_fund_days": 15,
            "reskilling_credit_within_days": 45,
            "layoff_compensation_percent": 50,
            "layoff_days_after_which_compensation_may_stop_by_agreement": 45,
        },
        [
            vector({"component": "compensation", "average_daily_pay": 1000, "years": 1, "months": 0}, "15000.00", "source", "fifteen days' average pay for one completed year"),
            vector({"component": "compensation", "average_daily_pay": 1000, "years": 3, "months": 7}, "60000.00", "derived", "part year above six months counts"),
            vector({"component": "compensation", "average_daily_pay": 1000, "years": 3, "months": 6}, "45000.00", "derived"),
            vector({"component": "compensation", "average_daily_pay": 1000, "years": 0, "months": 11}, "0.00", "derived", "below one year of continuous service"),
            vector({"component": "reskilling_fund", "daily_wage": 800}, "12000.00", "source", "fifteen days wages last drawn"),
            vector({"component": "layoff_daily", "daily_basic_and_dearness": 600}, "300.00", "source", "fifty per cent. of basic wages and dearness allowance"),
        ],
        [
            industrial("section 70", "not less than one year", "who has been in continuous service for not less than one year under an employer shall be retrenched by"),
            industrial("section 70(a)", "one month ’s notice", "the worker has been given one month ’s notice in writing indicating the reasons for"),
            industrial("section 70(b)", "fifteen days' average pay", "to fifteen days' average pay, or average pay of such days as may be notified by the appropriate"),
            industrial("section 70(b)", "in excess of six months", "for every completed year of continuous service or an y part thereof in excess of six"),
            industrial("section 83(3)", "within forty-five days", "The fund shall be utilised by crediting fifteen days wages last drawn by the worker to his account"),
            industrial("section 67", "fifty per cent. of the total of the basic wages and dearness allowance", "fifty per cent. of the total of the basic wages and dearness allowance that would have been payable to him,"),
            industrial("section 67, first proviso", "first forty-five days", "the first forty-five days, if there is an agreement to that effect between the worker and the employer:"),
        ],
        [{"statistic": "parameter[days_per_year]", "expected": 15, "tolerance": 0}, {"statistic": "parameter[layoff_compensation_percent]", "expected": 50, "tolerance": 0}],
        "Exit payments under Chapters IX and XI of the Industrial Relations Code, 2020, in force from 21 November 2025 (replacing the "
        "Industrial Disputes Act, 1947). A worker with at least one year of continuous service may be retrenched only after one "
        "month's written notice (or wages in lieu) and on payment of compensation of fifteen days' average pay for every completed "
        "year of continuous service or part above six months (section 70). The employer also pays fifteen days' wages last drawn "
        "into the worker re-skilling fund, which credits that sum to the worker within forty-five days (section 83). A laid-off "
        "worker with a year's service is paid fifty per cent. of basic wages and dearness allowance for each day of lay-off other "
        "than weekly holidays; by agreement the payment may stop after forty-five days in twelve months (section 67). Sections 67 "
        "to 69 do not apply to establishments averaging fewer than fifty workers or covered by Chapter X (three hundred or more), "
        "see in-labour-code-establishment-size-thresholds. Average pay is defined in the Code and is passed in as a daily amount.",
        LABOUR_TAGS + ["retrenchment", "end-of-service", "lay-off"],
        LABOUR_USE_CASES,
    )


def thresholds() -> dict:
    rows = {
        "provident_fund_chapter": {"threshold": 20, "counts": "employees", "law": "Code on Social Security, First Schedule, Chapter III"},
        "esic_chapter": {"threshold": 10, "counts": "persons (other than a seasonal factory)", "law": "Code on Social Security, First Schedule, Chapter IV"},
        "gratuity_shops_and_establishments": {"threshold": 10, "counts": "employees on any day of the preceding twelve months", "law": "Code on Social Security, First Schedule, Chapter V"},
        "maternity_benefit_shops_and_establishments": {"threshold": 10, "counts": "employees on any day of the preceding twelve months", "law": "Code on Social Security, First Schedule, Chapter VI"},
        "creche_facility": {"threshold": 50, "counts": "employees", "law": "Code on Social Security s 67(1)"},
        "bonus_chapter": {"threshold": 20, "counts": "persons on any day of the accounting year", "law": "Code on Wages s 38(2)"},
        "standing_orders_chapter": {"threshold": 300, "counts": "workers on any day of the preceding twelve months", "law": "Industrial Relations Code s 28(1)"},
        "layoff_retrenchment_closure_permission_chapter": {"threshold": 300, "counts": "workers on average per working day in the preceding twelve months", "law": "Industrial Relations Code s 77(1)"},
        "layoff_compensation_sections": {"threshold": 50, "counts": "workers on average per working day in the preceding calendar month", "law": "Industrial Relations Code s 65(1)(a)"},
        "closure_notice_section": {"threshold": 50, "counts": "workers on any day in the preceding twelve months", "law": "Industrial Relations Code s 74(1) proviso (i)"},
        "supervisor_worker_wage_limit": {"threshold": 18000, "counts": "rupees of wages per month; supervisors above it are not workers", "law": "Industrial Relations Code s 2(zr)(iv)"},
    }
    return rule_entry(
        "in-labour-code-establishment-size-thresholds",
        "India Labour Codes establishment-size thresholds: EPF 20, ESIC 10, gratuity 10, bonus 20, standing orders 300 and more",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("provident_fund_chapter", "threshold", 20),
            lookup("esic_chapter", "threshold", 10),
            lookup("standing_orders_chapter", "threshold", 300),
            lookup("supervisor_worker_wage_limit", "threshold", 18000),
            lookup("creche_facility", "threshold", 50),
        ],
        [
            social("First Schedule, Chapter III", "twenty or more", "Fund Every establishment in which twenty or more employees are employed."),
            social("First Schedule, Chapter IV", "ten or more", "Every establishment in which ten or more persons are employed other than a seasonal factory:"),
            social("First Schedule, Chapters V and VI", "(b) every shop or establishment in which ten or more employees are employed", "(b) every shop or establishment in which ten or more employees are employed, or were employed, on any day of the preceding twelve"),
            social("section 67(1)", "fifty employees", "Every establishment to which this Chapter applies, in which fifty employees"),
            wages("section 38(2)", "twenty or more persons", "the provisions of this Chapter shall apply to such establishment in which twenty or more persons are employed"),
            industrial("section 28(1)", "three hundred or more than three hundred workers", "establishment wherein three hundred or more than three hundred workers, are employed, or were"),
            industrial("section 77(1)", "not less than three hundred workers", "intermittently) in which not less than three hundred workers, or such higher number of workers as may"),
            industrial("section 65(1)(a)", "less than fifty workers", "to industrial establishments in which less than fifty workers on an average per working day"),
            industrial("section 74(1), proviso (i)", "less than fifty workers are employed", "an industrial establishment in which less than fifty workers are employed or were employed"),
            industrial("section 2(zr)(iv)", "eighteen thousand rupees per month", "employed in a supervisory capacity drawing wages exceeding eighteen thousand rupees per month"),
        ],
        value_tests(rows, "threshold"),
        "Headcount and wage thresholds at which the Labour Codes (in force from 21 November 2025) start to apply, for generating "
        "establishments with consistent compliance obligations. Under the Code on Social Security the provident fund chapter covers "
        "establishments employing twenty or more, the ESIC chapter ten or more persons (and any establishment in a notified "
        "hazardous occupation, even with one employee), gratuity and maternity benefit every factory, mine, plantation and every "
        "shop or establishment with ten or more employees, and a crèche is required at fifty employees. Bonus under the Code on "
        "Wages applies at twenty persons. Under the Industrial Relations Code, standing orders are required at three hundred "
        "workers; establishments with three hundred or more need Government permission to lay off, retrench or close (Chapter X); "
        "lay-off compensation and the sixty-day closure notice do not apply below fifty workers; and a supervisor drawing more than "
        "eighteen thousand rupees a month is not a 'worker'. Each Code lets the appropriate Government vary several of these by "
        "notification, and the counting basis differs (employees, persons or workers; any day or a daily average), as the "
        "``counts`` column records.",
        LABOUR_TAGS + ["applicability", "headcount"],
        LABOUR_USE_CASES + ["company-generation"],
    )


def maternity() -> dict:
    rows = {
        "maximum_benefit_weeks": {"value": 26, "provision": "s 60(3)"},
        "maximum_weeks_before_expected_delivery": {"value": 8, "provision": "s 60(3)"},
        "maximum_benefit_weeks_two_or_more_surviving_children": {"value": 12, "provision": "s 60(3) first proviso"},
        "maximum_weeks_before_delivery_two_or_more_children": {"value": 6, "provision": "s 60(3) first proviso"},
        "adoption_or_commissioning_mother_weeks": {"value": 12, "provision": "s 60(4), child below three months"},
        "qualifying_days_worked_in_preceding_twelve_months": {"value": 80, "provision": "s 60(2)"},
        "nursing_breaks_per_day": {"value": 2, "provision": "s 66, until the child is fifteen months old"},
    }
    return rule_entry(
        "in-maternity-benefit-code-on-social-security-2020",
        "India maternity benefit under Code on Social Security 2020: 26 weeks (12 from the third child), 80-day qualifying period",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows, "rate": "average daily wage for the period of actual absence"},
        [
            lookup("maximum_benefit_weeks", "value", 26),
            lookup("qualifying_days_worked_in_preceding_twelve_months", "value", 80),
            lookup("adoption_or_commissioning_mother_weeks", "value", 12),
            lookup("maximum_weeks_before_expected_delivery", "value", 8),
        ],
        [
            social("section 60(1)", "the average daily wage", "the payment of maternity benefit at the rate of the average daily wage for the period of her actual absence,"),
            social("section 60(2)", "not less than eighty days", "of the employer from whom she claims maternity benefit, for a period of not less than eighty days in the"),
            social("section 60(3)", "six weeks of which not more than eight weeks", "six weeks of which not more than eight weeks shall precede the expected date of her delivery:"),
            social("section 60(3), first proviso", "twelve weeks of which not more than six weeks", "surviving children shall be twelve weeks of which not more than six weeks shall precede the date of her"),
            social("section 60(4)", "below the age of three months", "A woman who legally adopts a child below the age of three months or a commissioning mother"),
            social("section 66", "fifteen months", "such duration as may be prescribed by the Central Government, for nursing the child until the child attains"),
        ],
        value_tests(rows, "value"),
        "Maternity benefit under Chapter VI of the Code on Social Security, 2020 (in force from 21 November 2025, replacing the "
        "Maternity Benefit Act, 1961). A woman who has actually worked at least eighty days for the employer in the twelve months "
        "before her expected delivery is paid her average daily wage for up to twenty-six weeks, of which no more than eight may "
        "precede the expected delivery; with two or more surviving children the maximum is twelve weeks, no more than six before "
        "delivery. An adopting mother of a child under three months, or a commissioning mother, gets twelve weeks from hand-over. "
        "On return she is allowed two nursing breaks a day until the child is fifteen months old. The chapter applies to factories, "
        "mines and plantations and to shops and establishments with ten or more employees (see "
        "in-labour-code-establishment-size-thresholds). Establishments covered by the ESIC chapter pay maternity benefit through "
        "ESIC instead.",
        LABOUR_TAGS + ["maternity", "leave"],
        LABOUR_USE_CASES,
    )


def notices() -> dict:
    rows = {
        "strike_or_lockout_notice_window_days": {"value": 60, "provision": "IR Code s 62(1)(a) and (2)(a): notice within sixty days before striking or locking out"},
        "strike_or_lockout_minimum_days_after_notice": {"value": 14, "provision": "IR Code s 62(1)(b) and (2)(b)"},
        "after_conciliation_days": {"value": 7, "provision": "IR Code s 62(1)(d): no strike until seven days after conciliation ends"},
        "after_tribunal_or_arbitration_days": {"value": 60, "provision": "IR Code s 62(1)(e) and (f)"},
        "notice_of_change_days": {"value": 21, "provision": "IR Code s 40: change in Third Schedule conditions"},
        "closure_notice_days": {"value": 60, "provision": "IR Code s 74(1): notice to the appropriate Government"},
        "retrenchment_notice_months": {"value": 1, "provision": "IR Code s 70(a): or wages in lieu"},
        "disciplinary_inquiry_completion_days": {"value": 90, "provision": "IR Code s 38(1): ordinarily from the date of suspension"},
        "subsistence_allowance_first_90_days_percent": {"value": 50, "provision": "IR Code s 38(3)(a)"},
        "subsistence_allowance_after_90_days_percent": {"value": 75, "provision": "IR Code s 38(3)(b): where the delay is not due to the worker"},
    }
    return rule_entry(
        "in-ir-code-notice-periods-and-subsistence-allowance",
        "India IR Code 2020 notice periods: strikes and lock-outs, change of conditions, closure, retrenchment; subsistence allowance",
        "employment",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("strike_or_lockout_notice_window_days", "value", 60),
            lookup("strike_or_lockout_minimum_days_after_notice", "value", 14),
            lookup("notice_of_change_days", "value", 21),
            lookup("subsistence_allowance_first_90_days_percent", "value", 50),
            lookup("subsistence_allowance_after_90_days_percent", "value", 75),
        ],
        [
            industrial("section 62(1)(a) and (b)", "within sixty days", "without giving to the employer notice of strike, as hereinafter provided, within sixty days"),
            industrial("section 62(1)(b)", "within fourteen days of giving such notice", "(b) within fourteen days of giving such notice; or (c) before the expiry of the date of strike specified"),
            industrial("section 62(1)(d)", "seven days after the conclusion", "during the pendency of any conciliation proceedings before a conciliation officer and seven days after the conclusion"),
            industrial("section 40(ii)", "within twenty-one days of giving such notice", "(ii) within twenty-one days of giving such notice:"),
            industrial("section 74(1)", "at least sixty days before", "who intends to close down an undertaking shall serve, at least sixty days before the date on which the"),
            industrial("section 38(1) and (3)", "within a period of ninety days from the date of suspension", "within a period of ninety days from the date of suspension."),
            industrial("section 38(3)(a)", "at the rate of fifty per cent.", "(a) at the rate of fifty per cent. of the wages which the worker was entitled to immediately"),
            industrial("section 38(3)(b)", "seventy-five per cent.", "(b) at the rate of seventy-five per cent. of such wages for the remaining period of suspension,"),
            industrial("section 70(a)", "one month ’s notice", "the worker has been given one month ’s notice in writing indicating the reasons for"),
        ],
        value_tests(rows, "value"),
        "Notice periods and suspension pay under the Industrial Relations Code, 2020 (in force from 21 November 2025). No one in an "
        "industrial establishment may strike, and no employer lock out, without notice given within the sixty days before, within "
        "fourteen days of the notice, before the date the notice names, during conciliation and seven days after it, or during "
        "Tribunal or arbitration proceedings and sixty days after (section 62). A change in the conditions listed in the Third "
        "Schedule needs twenty-one days' notice (section 40); closure of an undertaking needs sixty days' notice to the appropriate "
        "Government (section 74, not below fifty workers); retrenchment needs one month's notice or wages in lieu (section 70). A "
        "suspended worker is paid subsistence allowance of fifty per cent. of wages for the first ninety days and seventy-five per "
        "cent. thereafter unless the delay is the worker's doing; inquiries should ordinarily finish within ninety days "
        "(section 38, for establishments with standing orders).",
        LABOUR_TAGS + ["industrial-relations", "notice-period"],
        LABOUR_USE_CASES + ["event-timestamps"],
    )


def provident_fund() -> dict:
    rows = {
        "employer_contribution_percent": {"value": 10, "basis": "wages payable to each employee", "provision": "Code on Social Security s 16(1)(a)"},
        "employer_contribution_percent_notified_establishments": {"value": 12, "basis": "wages, in establishments the Central Government notifies", "provision": "s 16(1)(a) first proviso"},
        "employee_contribution": {"value": "equal to the employer contribution", "basis": "may voluntarily exceed it", "provision": "s 16(1)(a)"},
        "pension_fund_share_max_percent": {"value": "eight and one-third", "basis": "wages, paid from the employer contribution", "provision": "s 16(1)(b)(i)"},
        "insurance_fund_max_percent": {"value": 1, "basis": "wages, paid by the employer", "provision": "s 16(1)(c)"},
        "insurance_administration_max": {"value": "one-fourth", "basis": "of the employer's insurance fund contribution", "provision": "s 16(1)(c) proviso"},
        "epf_administrative_charges_percent": {"value": 0.5, "basis": "pay, from 1 June 2018", "provision": "S.O. 2011(E), EPF Scheme paragraphs 30 and 38(1)"},
        "epf_administrative_charges_minimum_non_functional": {"value": 75, "basis": "rupees per month per non-functional establishment with no contributory member", "provision": "S.O. 2011(E)"},
        "epf_administrative_charges_minimum_other": {"value": 500, "basis": "rupees per month per establishment", "provision": "S.O. 2011(E)"},
    }
    return rule_entry(
        "in-epf-statutory-contribution-limits",
        "India provident fund contributions under Code on Social Security s 16 (10% or 12%, pension up to 8 1/3%) and EPF admin charges",
        "pensions",
        (CODES_IN_FORCE, None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("employer_contribution_percent", "value", 10),
            lookup("employer_contribution_percent_notified_establishments", "value", 12),
            lookup("pension_fund_share_max_percent", "value", "eight and one-third"),
            lookup("insurance_fund_max_percent", "value", 1),
            lookup("epf_administrative_charges_percent", "value", 0.5),
            lookup("epf_administrative_charges_minimum_other", "value", 500),
        ],
        [
            social("section 16(1)(a)", "ten per cent. of the wages", "the employer to the fund shall be ten per cent. of the wages for the time being payable to each of the"),
            social("section 16(1)(a), first proviso", "twelve per cent.", "the words “twelve per cent.” shall be substituted:"),
            social("section 16(1)(a)", "equal to the contribution payable by the employer", "and the employee's contribution shall be equal to the contribution payable by the employer in respect of him"),
            social("section 16(1)(b)(i)", "eight and one - third per cent.", "such sums from the employer's contribution under clause ( a) not exceeding eight and one - third per cent. of the wages"),
            social("section 16(1)(c)", "one per cent. of the wages", "than one per cent. of the wages or such per cent. of wages as may be notified by the Central Government"),
            social("section 16(1)(c), proviso", "one-fourth of the contribution", "exceeding one-fourth of the contribution which he is required to make under this clause"),
            cite(MOLE, EPF_ADMIN_TITLE, EPF_ADMIN_URL, "S.O. 2011(E), paragraph 1", "0.50 per cent", "Scheme with effect from 1 st June, 2018 at 0.50 per cent (zero point five zero per cent.) of the pay"),
            cite(MOLE, EPF_ADMIN_TITLE, EPF_ADMIN_URL, "S.O. 2011(E), paragraph 1", "five hundred rupees per month", "five hundred rupees per month per establishment for other establishments."),
            social("section 164(2)(a), savings", "notification (including the notifications issued by the States)", "notification (including the notifications issued by the States), scheme, appointment, order", "supporting"),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[employer_contribution_percent_notified_establishments,value]", "expected": 12, "tolerance": 0}],
        "Statutory provident fund contribution rates under section 16 of the Code on Social Security, 2020 (in force from 21 "
        "November 2025, replacing the Employees' Provident Funds and Miscellaneous Provisions Act, 1952): the employer pays ten per "
        "cent. of wages, raised to twelve per cent. in establishments the Central Government notifies, and the employee pays an "
        "equal amount (more if they choose, without obliging the employer). Out of the employer's contribution, up to eight and "
        "one-third per cent. of wages goes to the Pension Fund; the employer also pays up to one per cent. of wages to the "
        "Deposit-Linked Insurance Fund plus up to a quarter of that for its administration. Administrative charges on the EPF are "
        "0.50% of pay from 1 June 2018 with minimums of ₹75 a month for a non-functional establishment and ₹500 for others "
        "(S.O. 2011(E), kept in force by section 164(2)). The operative EPS and EDLI percentages and the wage ceiling are set in "
        "the EPF, EPS and EDLI Schemes, whose current texts could not be fetched from EPFO; this entry holds the statutory limits "
        "only and does not state the wage ceiling. Wages are as defined in the Code on Wages (50% rule).",
        ["india", "payroll", "provident-fund", "pension", "compliance"],
        ["payroll-demo", "hr-demo", "pensions", "compliance-demo"],
    )


def tds() -> dict:
    rows = {
        "work_contract_individual_or_huf": {"rate_percent": 1, "provision": "Income-tax Act, 2025 s 393(1) Table Sl. No. 6(i)", "payee": "individual or Hindu undivided family"},
        "work_contract_other_payee": {"rate_percent": 2, "provision": "s 393(1) Table Sl. No. 6(i)", "payee": "any other person"},
        "fees_technical_services_film_royalty_call_centre": {"rate_percent": 2, "provision": "s 393(1) Table Sl. No. 6(iii)", "payee": "fees for technical services, film royalty, or a payee operating a call centre"},
        "fees_professional_services_other": {"rate_percent": 10, "provision": "s 393(1) Table Sl. No. 6(iii)", "payee": "other professional or technical fees"},
        "individual_or_huf_payer_work_commission_professional": {"rate_percent": 2, "provision": "s 393(1) Table Sl. No. 6(ii)", "payee": "work, commission or brokerage, or professional services paid by an individual or HUF not otherwise covered"},
    }
    return rule_entry(
        "in-tds-contractor-and-professional-fee-rates-2026-27",
        "India TDS on contract work (1%/2%) and professional or technical fees (2%/10%), Income-tax Act 2025 s 393(1), from 2026-27",
        "tax",
        ("2026-04-01", None),
        "almanac.rules.lookup_table",
        {"rows": rows, "supply_of_manpower": "included in 'work' (section 402(47)) from 1 April 2026, so taxed under Sl. No. 6(i)"},
        [
            lookup("work_contract_individual_or_huf", "rate_percent", 1),
            lookup("work_contract_other_payee", "rate_percent", 2),
            lookup("fees_technical_services_film_royalty_call_centre", "rate_percent", 2),
            lookup("fees_professional_services_other", "rate_percent", 10),
            lookup("individual_or_huf_payer_work_commission_professional", "rate_percent", 2),
        ],
        [
            cite(MOF, MEMO_TITLE, MEMO_URL, "'Application of TDS on supply of manpower', paragraph 1", "deduction of 1% when payment is made to individual or HUF and 2% in other cases.", "deduction of 1% when payment is made to individual or HUF and 2% in other cases."),
            cite(MOF, MEMO_TITLE, MEMO_URL, "same section, paragraph 2", "10% in other", "cinematographic films or to the business engaged in operation of call centre and 10% in other"),
            cite(MOF, MEMO_TITLE, MEMO_URL, "same section, paragraph 2", "rate of deduction of 2%", "case of fees paid for professional or technical services. It provides for rate of deduction of 2%"),
            cite(MOF, MEMO_TITLE, MEMO_URL, "same section, paragraph 3", "provides for rate of deduction of 2% for such payments.", "provides for rate of deduction of 2% for such payments."),
            cite(MOF, MEMO_TITLE, MEMO_URL, "same section, paragraphs 5 and 6", "The amendment will take effect from the 1st day of April, 2026.", "it is proposed to include it under the ambit of “work” in section 402(47)"),
        ],
        value_tests(rows, "rate_percent"),
        "Tax deduction at source on payments to resident contractors and for professional or technical fees under section 393(1) "
        "of the Income-tax Act, 2025, which applies from the tax year 2026-27, as the Memorandum to the Finance Bill, 2026 restates "
        "them: work contracts 1% where the payee is an individual or Hindu undivided family and 2% otherwise (Table Sl. No. 6(i)); "
        "fees for technical services, royalty for cinematographic films and payments to call-centre businesses 2%, other "
        "professional fees 10% (Sl. No. 6(iii)); and 2% where an individual or HUF not otherwise required to deduct pays for work, "
        "commission or brokerage or professional services (Sl. No. 6(ii)). The Bill adds supply of manpower to the meaning of "
        "'work' from 1 April 2026, so manpower contracts take the 1%/2% contract rates. Per-payment and annual thresholds, the "
        "higher rate without a PAN and the other TDS heads (interest, rent, commission, purchase of goods, partner payments) are "
        "in the Act's section 393 tables, which could not be fetched, and are not in this entry. The Memorandum states no licence.",
        ["india", "tax", "tds", "income-tax-act-2025", "compliance"],
        ["tax-demo", "tax-filing-demo", "invoicing-demo", "accounts-payable", "compliance-demo"],
    )


def msme() -> dict:
    crore = 10_000_000
    schedules = [
        {
            "from": "2020-07-01",
            "notification": "S.O. 2119(E), 26 June 2020",
            "ceilings": {
                "micro": {"investment": 1 * crore, "turnover": 5 * crore},
                "small": {"investment": 10 * crore, "turnover": 50 * crore},
                "medium": {"investment": 50 * crore, "turnover": 250 * crore},
            },
        },
        {
            "from": "2025-04-01",
            "notification": "S.O. 1364(E), 21 March 2025",
            "ceilings": {
                "micro": {"investment": 25 * crore // 10, "turnover": 10 * crore},
                "small": {"investment": 25 * crore, "turnover": 100 * crore},
                "medium": {"investment": 125 * crore, "turnover": 500 * crore},
            },
        },
    ]
    return rule_entry(
        "in-msme-classification-criteria",
        "India MSME classification by investment and turnover ceilings, 2020 criteria and the revision from 1 April 2025",
        "company",
        ("2020-07-01", None),
        "almanac.rules.in_msme",
        {"currency": "INR", "unit": "rupees", "exports_excluded_from_turnover": True, "schedules": schedules},
        [
            vector({"investment": 25 * crore // 10, "turnover": 10 * crore, "on": "2025-06-30"}, "micro", "source", "at the 2025 micro ceilings of Rs. 2.5 crore and Rs. 10 crore"),
            vector({"investment": 125 * crore, "turnover": 500 * crore, "on": "2025-06-30"}, "medium", "source"),
            vector({"investment": 1 * crore, "turnover": 5 * crore, "on": "2021-01-01"}, "micro", "source", "at the 2020 micro ceilings"),
            vector({"investment": 1 * crore, "turnover": 6 * crore, "on": "2021-01-01"}, "small", "source", "crossing either ceiling moves the enterprise to the next higher category"),
            vector({"investment": 2 * crore, "turnover": 8 * crore, "on": "2025-03-31"}, "small", "derived"),
            vector({"investment": 2 * crore, "turnover": 8 * crore, "on": "2025-04-01"}, "micro", "derived", "the same enterprise under the revised ceilings"),
            vector({"investment": 30 * crore, "turnover": 50 * crore, "on": "2026-01-01"}, "medium", "derived"),
            vector({"investment": 100 * crore, "turnover": 600 * crore, "on": "2026-01-01"}, "not_msme", "derived"),
        ],
        [
            cite(MSME, MSME_2025_TITLE, MSME_2025_URL, "'What's MSME' content, heading", "Revised Classification applicable w.e.f 1st April 2025", "Revised Classification applicable w.e.f 1st April 2025"),
            cite(MSME, MSME_2025_TITLE, MSME_2025_URL, "classification table, Micro column", "Not more than Rs. 2.5 crore and Annual Turnover not more than Rs. 10 crore", "Not more than Rs. 2.5 crore and Annual Turnover not more than Rs. 10 crore"),
            cite(MSME, MSME_2025_TITLE, MSME_2025_URL, "classification table, Small column", "Not more than Rs. 25 crore and Annual Turnover not more than Rs. 100 crore", "Not more than Rs. 25 crore and Annual Turnover not more than Rs. 100 crore"),
            cite(MSME, MSME_2025_TITLE, MSME_2025_URL, "classification table, Medium column", "Not more than Rs. 125 crore and Annual Turnover not more than Rs. 500 crore", "Not more than Rs. 125 crore and Annual Turnover not more than Rs. 500 crore"),
            cite(MSME, MSME_2025_TITLE, MSME_2025_URL, "link to the notification", "Notification-S.O-no-1364-E-dated-21.03.2025", "Notification-S.O-no-1364-E-dated-21.03.2025-Revised-Definition.pdf", "supporting"),
            cite(MSME, MSME_2020_TITLE, MSME_2020_URL, "paragraph 1(i)", "one crore rupees", "exceed one crore rupees and turnover does not exceed five crore rupees;"),
            cite(MSME, MSME_2020_TITLE, MSME_2020_URL, "paragraph 1(ii) and (iii)", "two hundred and fifty crore rupees", "exceed fifty crore rupees and turnover does not exceed two hundred and fifty crore rupees."),
            cite(MSME, MSME_2020_TITLE, MSME_2020_URL, "paragraph 3(2)", "next higher category", "criteria of investment or turnover, it will cease to exist in that category and be placed in the next higher category"),
            cite(MSME, MSME_2020_TITLE, MSME_2020_URL, "paragraph 5(1)", "Exports of goods or services or both", "Exports of goods or services or both, shall be excluded while calculating the turnover of any"),
        ],
        [
            {"statistic": "count", "expected": 2, "tolerance": 0},
            {"statistic": "ceiling[2025-04-01,micro,investment]", "expected": 25000000, "tolerance": 0},
            {"statistic": "ceiling[2025-04-01,medium,turnover]", "expected": 5000000000, "tolerance": 0},
            {"statistic": "ceiling[2020-07-01,small,turnover]", "expected": 500000000, "tolerance": 0},
        ],
        "Classification of enterprises under section 7 of the Micro, Small and Medium Enterprises Development Act, 2006. From 1 July "
        "2020 (S.O. 2119(E)) an enterprise is micro if investment in plant and machinery or equipment does not exceed ₹1 crore and "
        "turnover ₹5 crore, small up to ₹10 crore and ₹50 crore, and medium up to ₹50 crore and ₹250 crore. The Ministry of MSME's "
        "site records the revision applicable from 1 April 2025, citing S.O. 1364(E) of 21 March 2025: micro up to ₹2.5 crore and "
        "₹10 crore, small up to ₹25 crore and ₹100 crore, medium up to ₹125 crore and ₹500 crore. The criteria are composite: an "
        "enterprise exceeding either ceiling of its category moves to the next one, so the rule returns the smallest category whose "
        "ceilings it meets on both, or not_msme above the medium ceilings. Exports are excluded from turnover, and all GSTINs under "
        "one PAN count as one enterprise. The 2025 notification PDF itself is hosted on dcmsme.gov.in, which could not be reached; "
        "the 2025 ceilings are cited from the Ministry's content-management record (JSON), whose text matched on repeated fetches. "
        "Amounts are in rupees (1 crore = 10,000,000).",
        ["india", "msme", "compliance", "company-size"],
        ["company-generation", "kyb-onboarding", "loan-pricing", "credit-risk", "invoicing-demo", "compliance-demo"],
        [{"parameter": "schedules.*.ceilings", "value": "crore amounts converted to rupees", "method": "derived", "rationale": "The sources state ceilings in crore of rupees; the rule stores them in rupees at 1 crore = 10,000,000 so inputs can be plain rupee amounts."}],
    )


def small_company() -> dict:
    crore = 10_000_000
    return rule_entry(
        "in-companies-act-small-company-thresholds",
        "India Companies Act 2013 s 2(85) small company: paid-up capital up to ₹4 crore and turnover up to ₹40 crore (2022 rules)",
        "company",
        ("2022-09-15", None),
        "almanac.rules.in_companies_act",
        {
            "formula": "small_company",
            "currency": "INR",
            "paid_up_capital_ceiling": 4 * crore,
            "turnover_ceiling": 40 * crore,
            "statutory_default_ceilings": {"paid_up_capital": 5_000_000, "turnover": 2 * crore},
            "statutory_maximum_ceilings": {"paid_up_capital": 10 * crore, "turnover": 100 * crore},
            "turnover_basis": "profit and loss account for the immediately preceding financial year",
            "excluded_flags": ["holding_or_subsidiary", "section_8_company", "special_act_company"],
        },
        [
            vector({"paid_up_capital": 4 * crore, "turnover": 40 * crore}, True, "source", "at the ceilings of rupees four crore and forty crore"),
            vector({"paid_up_capital": 4 * crore + 1, "turnover": 10 * crore}, False, "derived"),
            vector({"paid_up_capital": 1 * crore, "turnover": 41 * crore}, False, "derived"),
            vector({"paid_up_capital": 1 * crore, "turnover": 5 * crore, "holding_or_subsidiary": True}, False, "source", "proviso (A): not a holding or subsidiary company"),
            vector({"paid_up_capital": 1 * crore, "turnover": 5 * crore, "public_company": True}, False, "source", "a company other than a public company"),
            vector({"paid_up_capital": 1 * crore, "turnover": 5 * crore, "section_8_company": True}, False, "source"),
        ],
        [
            companies("section 2(85)", "“small company” means a company, other than a public company,—", "“small company” means a company, other than a public company,—"),
            companies("section 2(85)(i)", "fifty lakh rupees", "paid-up share capital of which does not exceed fifty lakh rupees or such higher amount as may"),
            companies("section 2(85)(ii)", "two crore rupees", "does not exceed two crore rupees or such higher amount as may be prescribed which shall not be more than"),
            companies("section 2(85), proviso", "(A) a holding company or a subsidiary company;", "(A) a holding company or a subsidiary company; (B) a company registered under section 8; or"),
            cite(MCA, RULES_2022_TITLE, DEFINITIONS_RULES_2022_URL, "rule 2(1)(t) as substituted", "rupees four crore and rupees forty crore", "paid up capital and turnover of the small company shall not exceed rupees four crore and rupees forty crore"),
        ],
        [{"statistic": "parameter[paid_up_capital_ceiling]", "expected": 40000000, "tolerance": 0}, {"statistic": "parameter[turnover_ceiling]", "expected": 400000000, "tolerance": 0}],
        "Small company test of section 2(85) of the Companies Act, 2013 (India Code text as on 1 September 2026). A company other than "
        "a public company is small if its paid-up share capital does not exceed fifty lakh rupees and its turnover for the "
        "preceding financial year does not exceed two crore rupees, or such higher amounts as are prescribed up to ten crore and "
        "one hundred crore rupees; holding and subsidiary companies, section 8 companies and companies under a special Act are "
        "never small. The Companies (Specification of Definitions Details) Amendment Rules, 2022 (G.S.R. 700(E), 15 September 2022) "
        "prescribe ₹4 crore and ₹40 crore, the latest amendment India Code holds. Any later amendment to rule 2(1)(t) would be "
        "published by the Ministry of Corporate Affairs or the eGazette, neither of which could be reached; check before relying on "
        "these ceilings for dates after 2025. Amounts are in rupees.",
        ["india", "companies-act", "company-size", "compliance"],
        COMPANY_USE_CASES + ["financial-reporting"],
        [{"parameter": "valid_to", "value": None, "method": "derived", "rationale": "Left open because no later amendment of rule 2(1)(t) could be fetched; the ministry and gazette sites that would publish one were unreachable."}],
    )


def csr() -> dict:
    crore = 10_000_000
    return rule_entry(
        "in-companies-act-csr-applicability-and-spend",
        "India Companies Act s 135 CSR: applies at ₹500 crore net worth, ₹1,000 crore turnover or ₹5 crore profit; spend 2%",
        "company",
        ("2021-01-22", None),
        "almanac.rules.in_companies_act",
        {
            "formula": "csr",
            "currency": "INR",
            "applicability_thresholds": {"net_worth": 500 * crore, "turnover": 1000 * crore, "net_profit": 5 * crore},
            "applicability_year": "immediately preceding financial year",
            "spend_percent": 2,
            "averaging_years": 3,
            "committee_exemption_ceiling": 5_000_000,
            "unspent_transfer_to_schedule_vii_fund_months": 6,
            "ongoing_project_unspent_account_transfer_days": 30,
            "penalty": "twice the amount to be transferred or one crore rupees, whichever is less",
        },
        [
            vector({"net_worth": 100 * crore, "turnover": 200 * crore, "net_profit": 5 * crore, "preceding_net_profits": [5 * crore, 4 * crore, 3 * crore]}, {"applies": True, "obligation": "800000.00", "committee_required": False}, "source", "net profit of rupees five crore meets the threshold; 2% of the three-year average"),
            vector({"net_worth": 900 * crore, "turnover": 2000 * crore, "net_profit": 40 * crore, "preceding_net_profits": [40 * crore, 30 * crore, 20 * crore]}, {"applies": True, "obligation": "6000000.00", "committee_required": True}, "derived", "an obligation above fifty lakh needs a CSR committee"),
            vector({"net_worth": 499 * crore, "turnover": 999 * crore, "net_profit": 4 * crore, "preceding_net_profits": [4 * crore, 4 * crore, 4 * crore]}, {"applies": False, "obligation": "0.00", "committee_required": False}, "derived"),
            vector({"net_worth": 600 * crore, "turnover": 100 * crore, "net_profit": 1 * crore, "preceding_net_profits": [1 * crore, 2 * crore, 3 * crore]}, {"applies": True, "obligation": "400000.00", "committee_required": False}, "derived", "obligation up to fifty lakh needs no committee"),
            vector({"net_worth": 10 * crore, "turnover": 1000 * crore, "net_profit": -1 * crore, "preceding_net_profits": [-5 * crore, 1 * crore, 1 * crore]}, {"applies": True, "obligation": "0.00", "committee_required": False}, "derived", "a negative average gives no spend"),
            vector({"net_worth": 600 * crore, "turnover": 100 * crore, "net_profit": 10 * crore, "preceding_net_profits": [10 * crore]}, {"applies": True, "obligation": "2000000.00", "committee_required": False}, "derived", "a company with fewer than three years uses the years it has"),
        ],
        [
            companies("section 135(1)", "net worth of rupees five hundred", "Every company having net worth of rupees five hundred crore or more, or turnover of rupees one thousand crore or more"),
            companies("section 135(1)", "a net profit of rupees five crore or more", "or a net profit of rupees five crore or more"),
            companies("section 135(5)", "at least two per cent. of the average net profits", "in every financial year, at least two per cent. of the average net profits of the company made during the"),
            companies("section 135(5)", "three immediately preceding financial years", "three immediately preceding financial years,"),
            companies("section 135(9)", "fifty lakh", "Where the amount to be spent by a company under sub -section (5) does not exceed fifty lakh"),
            companies("section 135(7)", "one crore rupees, whichever is less", "may be, or one crore rupees, whichever is less, and every officer of the company who is in default shall be"),
            companies("footnote to section 135(7) and (9)", "Ins. by s. 27, ibid. (w.e.f. 22-1-2021).", "Ins. by s. 27, ibid. (w.e.f. 22-1-2021).", "supporting"),
        ],
        [{"statistic": "parameter[spend_percent]", "expected": 2, "tolerance": 0}, {"statistic": "parameter[committee_exemption_ceiling]", "expected": 5000000, "tolerance": 0}],
        "Corporate social responsibility under section 135 of the Companies Act, 2013 (India Code text as on 1 September 2026). A "
        "company with net worth of ₹500 crore or more, turnover of ₹1,000 crore or more or net profit of ₹5 crore or more in the "
        "immediately preceding financial year must spend in each year at least 2% of its average net profits of the three "
        "immediately preceding financial years (or the years since incorporation, if fewer), net profit being computed under "
        "section 198. A CSR committee of the Board is needed unless the amount to be spent does not exceed ₹50 lakh (sub-section "
        "(9), in force from 22 January 2021, which is why the entry starts on that date). Unspent amounts go to a Schedule VII fund "
        "within six months of the year end, or for ongoing projects to an Unspent CSR Account within thirty days; default draws a "
        "penalty of twice the amount or ₹1 crore, whichever is less. The rule returns applicability, the minimum spend (never "
        "negative) and whether a committee is required; amounts in rupees.",
        ["india", "companies-act", "csr", "compliance"],
        COMPANY_USE_CASES + ["financial-reporting", "audit-demo"],
    )


def market_cap() -> dict:
    return rule_entry(
        "in-mutual-fund-market-cap-categories",
        "India SEBI large, mid and small cap definition for mutual funds: ranks 1-100, 101-250 and 251 onwards by market cap",
        "company",
        ("2017-10-06", None),
        "almanac.rules.in_market_cap_category",
        {
            "basis": "full market capitalisation, AMFI list updated every six months on end-June and end-December data",
            "rebalance_within_months": 1,
            "bands": [
                {"name": "large_cap", "from_rank": 1, "to_rank": 100},
                {"name": "mid_cap", "from_rank": 101, "to_rank": 250},
                {"name": "small_cap", "from_rank": 251, "to_rank": None},
            ],
        },
        [
            vector({"rank": 1}, "large_cap", "source"),
            vector({"rank": 100}, "large_cap", "source"),
            vector({"rank": 101}, "mid_cap", "source"),
            vector({"rank": 250}, "mid_cap", "source"),
            vector({"rank": 251}, "small_cap", "source"),
            vector({"rank": 1200}, "small_cap", "derived"),
        ],
        [
            cite(SEBI, SEBI_TITLE, SEBI_CATEGORISATION_URL, "paragraph 7(a)", "Large Cap: 1st -100th company", "a. Large Cap: 1st -100th company in terms of full market capitalization"),
            cite(SEBI, SEBI_TITLE, SEBI_CATEGORISATION_URL, "paragraph 7(b)", "Mid Cap: 101st -250th company", "b. Mid Cap: 101st -250th company in terms of full market capitalization"),
            cite(SEBI, SEBI_TITLE, SEBI_CATEGORISATION_URL, "paragraph 7(c)", "Small Cap: 251st company onwards", "c. Small Cap: 251st company onwards in terms of full market capitalization"),
            cite(SEBI, SEBI_TITLE, SEBI_CATEGORISATION_URL, "paragraph 8(c)", "every six months", "every six months based on the data as on the end of June and December of each"),
            cite(SEBI, SEBI_TITLE, SEBI_CATEGORISATION_URL, "paragraph 9", "within a period of one month", "portfolios (if required) in line with updated list, within a period of one month."),
        ],
        [{"statistic": "count", "expected": 3, "tolerance": 0}, {"statistic": "last_rank[mid_cap]", "expected": 250, "tolerance": 0}],
        "SEBI's definition of the equity investment universe for mutual fund schemes, from section II of the circular on "
        "categorisation and rationalisation of mutual fund schemes dated 6 October 2017: large cap is the 1st to 100th company by "
        "full market capitalisation, mid cap the 101st to 250th and small cap the 251st onwards. Funds use the single list AMFI "
        "prepares every six months from end-June and end-December data, averaging across exchanges where a stock is listed on more "
        "than one, and rebalance within a month of each update. SEBI's Master Circular for Mutual Funds of 20 March 2026 restates "
        "the same ranks in paragraph 3.9 (applying them to entities, so listed REITs are ranked too); that 7 MB file could not be "
        "downloaded reliably within the verifier's time limit, so the 2017 circular is cited. Use the rule to label generated "
        "listed companies or fund holdings. SEBI states no reuse licence for the document.",
        ["india", "sebi", "mutual-funds", "market-cap"],
        ["fintech-demo", "banking-demo", "company-generation", "compliance-demo"],
    )


BUILDERS = (
    commencement,
    wage_definition,
    bonus,
    wage_payment,
    working_hours,
    gratuity,
    retrenchment,
    thresholds,
    maternity,
    notices,
    provident_fund,
    tds,
    msme,
    small_company,
    csr,
    market_cap,
)


def main() -> None:
    for build in BUILDERS:
        write(build())


if __name__ == "__main__":
    main()

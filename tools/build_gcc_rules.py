"""Build Gulf Cooperation Council business-rule entries for payroll, HR, invoicing, tax and banking demos.

Sources are official publications that are byte-stable when fetched: the
Zakat, Tax and Customs Authority's VAT and withholding-tax guidelines, the
Ministry of Human Resources and Social Development's Labour Law and its 2025
awareness guide, the Saudi Central Bank's rulebook and financial stability
report, the UAE Ministry of Finance and Federal Tax Authority's tax
legislation and corporate tax guide, the UAE employment-relationship
Decree-Law, the General Pension and Social Security Authority's published
contribution rates, the IBAN standards of the Central Banks of Bahrain and
Kuwait, the Central Bank of Kuwait's quarterly review, the Central Bank of
Bahrain's monetary policy page and the Oman Tax Authority's VAT and income
tax laws. Every value and snippet is checked against the text the verifier
extracts before an entry is written, and each PDF locator names the page the
snippet was found on. Run from the repository root:

    uv run python tools/build_gcc_rules.py
"""

from __future__ import annotations

import io
import string
import sys
from pathlib import Path
from typing import Any

import httpx
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

ACCESSED = "2026-11-09"
UNSTATED = "unstated"

# Saudi Arabia
ZATCA = "Zakat, Tax and Customs Authority (ZATCA), Kingdom of Saudi Arabia"
ZATCA_VAT15_URL = "https://zatca.gov.sa/ar/HelpCenter/guidelines/Documents/VAT15.pdf"
ZATCA_VAT15_TITLE = "Guideline on the change of the basic VAT rate to 15% (Arabic edition)"
ZATCA_INVOICING_URL = "https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/Guideline-for-Tax-Invoicing-and-Records-under-VAT-Provisions.pdf"
ZATCA_INVOICING_TITLE = "Guideline for Tax Invoicing and Records under VAT Provisions, Version 3, May 2026"
ZATCA_WHT_URL = "https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/General-Guideline-for-Withholding-Tax-In-accordance-with-the-provisions-of-the-Income-Tax-Law-and-its-Implementing-Regulations.pdf"
ZATCA_WHT_TITLE = "General Guideline for Withholding Tax under the Income Tax Law and its Implementing Regulations, Second Version, May 2026"
HRSD = "Ministry of Human Resources and Social Development (HRSD), Kingdom of Saudi Arabia"
HRSD_LAW_URL = "https://www.hrsd.gov.sa/sites/default/files/2023-02/Labor.pdf"
HRSD_LAW_TITLE = "Labor Law, Royal Decree No. M/51 (English translation)"
HRSD_GUIDE_URL = "https://www.hrsd.gov.sa/sites/default/files/2025-12/awareness-guide-on-the-rights-and-duties-of-employers-and-workers---1-.pdf"
HRSD_GUIDE_TITLE = "Awareness Guide on the Rights and Duties of Employers and Workers, First Edition 2025"
SAMA = "Saudi Central Bank (SAMA)"
SAMA_RULEBOOK_URL = "https://rulebook.sama.gov.sa/en/printed-iban-account-formats"
SAMA_RULEBOOK_TITLE = "SAMA Rulebook: Printed IBAN Account Formats"
SAMA_FSR_URL = "https://www.sama.gov.sa/en-US/Publications/FinanceReports/Financial%20Stability%20Report/Financial%20Stability%20Report%202019.pdf"
SAMA_FSR_TITLE = "Financial Stability Report 2019"

# United Arab Emirates
MOF_AE = "Ministry of Finance, United Arab Emirates"
FTA = "Federal Tax Authority, United Arab Emirates"
CD116_URL = "https://mof.gov.ae/wp-content/uploads/2023/04/Cabinet-Decision-No-116-of-2022-on-the-annual-Taxable-Income-subject-to-Corporate-Tax.pdf"
CD116_TITLE = "Cabinet Decision No. 116 of 2022 on the Determination of Annual Income Subject to Corporate Tax"
CT_GUIDE_URL = "https://tax.gov.ae/DataFolder/Files/Guides/CT/CT%20General%20Guide%20-%20EN%20-%2010%2009%202023.pdf"
CT_GUIDE_TITLE = "General Corporate Tax Guide (CTGGCT1), September 2023"
VAT_LAW_AE_URL = "https://tax.gov.ae/Datafolder/Files/Legislation/2025/Federal%20Decree-Law%20No.%208%20of%202017%20and%20amendments%20-%20publishing%2028%2011%202025.pdf"
VAT_LAW_AE_TITLE = "Federal Decree-Law No. 8 of 2017 on Value Added Tax and its amendments (unofficial translation, November 2025)"
VAT_REG_AE_URL = "https://mof.gov.ae/wp-content/uploads/2024/10/Executive-Regulation-of-Federal-Decree-Law-No-8-of-2017.pdf"
VAT_REG_AE_TITLE = "Executive Regulation of Federal Decree-Law No. 8 of 2017 on Value Added Tax (Cabinet Decision No. 52 of 2017 and its amendments)"
DMTT_URL = "https://tax.gov.ae/Datafolder/Files/Legislation/Cabinet-Decision-No-142-of-2024-on-Top-up-Tax-on-MNEs.pdf"
DMTT_TITLE = "Cabinet Decision No. 142 of 2024 on the Imposition of Top-up Tax on Multinational Enterprises, as published in the Official Gazette"
LABOUR_AE_URL = "https://pcfc.ae/en/Rules%20and%20Regulations/Trakhees/Licensing%20Department/Government%20Services/Rules%20&%20Regulations/Federal%20Decree-Law%20No.%20(33)%20of%202021%20Regarding%20the%20Regulation%20of%20Employment%20Relationship%20and%20its%20amendments.pdf"
LABOUR_AE_TITLE = "Federal Decree-Law No. (33) of 2021 Regarding the Regulation of Employment Relationships and its amendments"
LABOUR_AE = "Ministry of Human Resources and Emiratisation, United Arab Emirates (text published by Ports, Customs and Free Zone Corporation, Dubai)"
GPSSA = "General Pension and Social Security Authority (GPSSA), United Arab Emirates"
GPSSA_FAQ_URL = "https://gpssa.gov.ae/pages/en/help/faq/what-distribution-contributions-due-insured-individuals"
GPSSA_FAQ_TITLE = "FAQ: What is the distribution of contributions due from insured individuals?"
GPSSA_LAW57_URL = "https://www.gpssa.gov.ae/pages/en/media-center/news/gpssa-reviews-most-prominent-features-federal-law-no-57-2023"
GPSSA_LAW57_TITLE = "GPSSA reviews the most prominent features of Federal Law No. (57) of 2023"

# Bahrain and Kuwait
CBB = "Central Bank of Bahrain (CBB)"
CBB_IBAN_URL = "https://www.cbb.gov.bh/wp-content/uploads/2018/12/IBAN-Standard-Document-16-02-2011.pdf"
CBB_IBAN_TITLE = "Version 1: ISO IBAN Standard for the Kingdom of Bahrain, 16 February 2011"
CBB_POLICY_URL = "https://www.cbb.gov.bh/monetary-policy/"
CBB_POLICY_TITLE = "Monetary Policy"
CBK = "Central Bank of Kuwait (CBK)"
CBK_IBAN_URL = "https://www.cbk.gov.kw/en/images/iban-9721_v60_tcm10-9721.pdf"
CBK_IBAN_TITLE = "Information about IBAN Implementation in Kuwait, version 1.1"
CBK_REVIEW_URL = "https://www.cbk.gov.kw/en/images/key-indicators-q3-2022-159994_v60_tcm10-159994.pdf"
CBK_REVIEW_TITLE = "Overview of the Key Economic, Monetary and Banking Developments, First Issue, November 2022"

# Oman
OTA = "Tax Authority, Sultanate of Oman"
OM_VAT_URL = "https://tms.taxoman.gov.om/portal/documents/20126/1414820/VAT+Law+.pdf/9cbe8926-066b-d48d-2b7f-14f41b4c19a8?t=1733169733344"
OM_VAT_TITLE = "Value Added Tax Law (Royal Decree No. 121/2020) and Executive Regulations, English translation"
OM_VAT_GUIDE_URL = "https://tms.taxoman.gov.om/portal/documents/20126/1414820/VAT+Taxpayer+Guide+-+VAT+Return+Filing.pdf/fae31d0c-e7e7-0014-9f28-a4c506b36614?t=1733169613409"
OM_VAT_GUIDE_TITLE = "VAT Taxpayer Guide: VAT Return Filing, Version 1, June 2021"
OM_IT_URL = "https://tms.taxoman.gov.om/portal/documents/20126/1455220/income+tax+law+english.pdf"
OM_IT_TITLE = "Income Tax Law promulgated by Royal Decree 28/2009 as amended by Royal Decree 118/2020, consolidated English text"

GCC_TAGS = ["gcc"]
TAX_USE_CASES = ["tax-demo", "invoicing-demo", "invoicing", "tax-filing-demo"]
HR_USE_CASES = ["payroll-demo", "hr-demo", "hr-analytics"]
BANKING_USE_CASES = ["banking-demo", "payments-demo", "kyc-onboarding", "data-quality-validation"]
FX_USE_CASES = ["banking-demo", "treasury-demo", "multi-currency-ledger", "invoicing-demo"]

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


def rule_entry(
    entry_id: str,
    title: str,
    domain: str,
    region: str,
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
    if not any(v["origin"] == "source" for v in vectors):
        raise ValueError(f"{entry_id}: at least one vector must come from the source")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": "license-review",
        "tier": "B",
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": [*GCC_TAGS, *tags],
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


def assume(parameter: str, value: Any, method: str, rationale: str) -> dict:
    return {"parameter": parameter, "value": value, "method": method, "rationale": rationale}


def letter_values() -> dict[str, int]:
    """ISO 13616 letter conversion A=10 to Z=35, the table the Bahrain IBAN standard prints as Table 1."""
    return {letter: index for index, letter in enumerate(string.ascii_uppercase, 10)}


# ---------------------------------------------------------------------------
# Saudi Arabia
# ---------------------------------------------------------------------------


def sa_vat_rate_history() -> dict:
    steps = [{"from": "2018-01-01", "value": 5}, {"from": "2020-07-01", "value": 15}]
    vat15 = lambda where, value, snippet: cite(ZATCA, ZATCA_VAT15_TITLE, ZATCA_VAT15_URL, where, value, snippet, unit="percent")  # noqa: E731
    return rule_entry(
        "sa-vat-standard-rate-history",
        "Saudi Arabia VAT standard (basic) rate by date: 5% from 2018, 15% from 1 July 2020",
        "tax",
        "SA",
        ("2018-01-01", None),
        "almanac.rules.step_schedule",
        {"unit": "percent", "steps": steps},
        [
            vector("2019-06-30", 5, "source", "the guideline: VAT applied from the start of 2018 at a basic rate of 5%"),
            vector("2020-07-01", 15, "source", "the revised basic rate of 15% applies from 1 July 2020"),
            vector("2020-06-30", 5, "source", "supplies up to 30 June 2020 are taxed at 5%"),
            vector("2026-11-09", 15, "derived"),
        ],
        [
            vat15("section 1, Introduction", 5, "على جميع التوريدات وعمليات الاستيراد مع استثناءات محدودة %5 م بنسبة أساسية قدرها 2018"),
            vat15("section 2.2, calculation of tax due", 15, "م، سيتم احتساب الضريبة على التوريدات الخاضعة للضريبة بالنسبة الأساسية 2020 يوليو1 واعتبارًا من"),
            vat15("section 2.2, the period ending 30 June 2020", 5, "على%5 م، يتم احتساب ضريبة القيمة المضافة بنسبة2020 يونيو30 خلال الفترة التي تنتهي في"),
        ],
        [{"statistic": "count", "expected": 2, "tolerance": 0}, {"statistic": "value[2021-01-01]", "expected": 15, "tolerance": 0}],
        "The basic (standard) VAT rate in Saudi Arabia: 5% from the introduction of VAT at the start of 2018, raised to 15% for "
        "supplies made on or after 1 July 2020 under the measures announced by the Ministry of Finance on 11 May 2020. ZATCA's "
        "guideline on the rate change states both rates and the changeover; transitional rules for contracts and invoices dated "
        "before 11 May 2020 are in the same guideline and are not modelled here. The guideline is published in Arabic; the "
        "snippets are its extracted text, which pypdf returns in visual order with digits and Arabic words interleaved.",
        ["tax", "vat", "saudi-arabia", "tax-rate"],
        TAX_USE_CASES,
        [assume("steps[0].from", "2018-01-01", "derived", "The guideline says VAT applied from the beginning of 2018 (بداية عام 2018); the first day of that year is used.")],
    )


def sa_vat_rate_and_thresholds() -> dict:
    inv = lambda where, value, snippet, unit="text": cite(ZATCA, ZATCA_INVOICING_TITLE, ZATCA_INVOICING_URL, where, value, snippet, unit=unit)  # noqa: E731
    return rule_entry(
        "sa-vat-rate-and-registration-thresholds",
        "Saudi Arabia VAT: 15% basic rate, tax computation and the SAR 375,000 and SAR 187,500 registration thresholds",
        "tax",
        "SA",
        ("2020-07-01", None),
        "almanac.rules.consumption_tax",
        {
            "currency": "SAR",
            "slabs": {"standard": 15, "zero": 0},
            "rounding": "0.01",
            "mandatory_registration_threshold": 375000,
            "voluntary_registration_threshold": 187500,
            "threshold_period": "twelve months",
        },
        [
            vector(15, True, "source", "basic rate of 15%"),
            vector({"net": 90, "slab": "standard"}, "13.50", "source", "Example (7): SAR 90 of food plus VAT of SAR 13.50"),
            vector({"net": 10000, "slab": "standard"}, "1500.00", "source", "Example (1): VAT of SAR 1,500, 15% of the SAR 10,000 cost price"),
            vector({"gross": "103.50", "slab": "standard"}, "13.50", "source", "Example (7): total consideration SAR 103.50 includes VAT of SAR 13.50"),
            vector(5, False, "derived", "5% was the basic rate before 1 July 2020 and is not a current slab"),
        ],
        [
            inv("section 4.3, Example (7)", "13.50", "sells food products on a retail basis for an amount of SAR 90, in addition to VAT of SAR 13.50.", "currency:SAR"),
            inv("section 4.3, Example (7)", "103.50", "or issue a simplified tax invoice showing the total consideration due (SAR 103.50)", "currency:SAR"),
            inv("section 3, deemed supplies, Example (1)", "1,500", "for VAT in the amount of SAR 1,500 (15% of the cost price) on the deemed supply", "currency:SAR"),
            inv("section 4.3, simplified tax invoice requirements", "15%", "includes VAT at the basic rate of 15%.", "percent"),
            inv("section 3.2, Mandatory Registration", "375,000", "SAR 375,000 (the “mandatory registration threshold”), that person must register for VAT", "currency:SAR"),
            inv("section 3.3, Voluntary Registration", "187,500", "exceed SAR 187,500 (the “voluntary registration threshold”) during a period of twelve months", "currency:SAR"),
            cite(ZATCA, ZATCA_VAT15_TITLE, ZATCA_VAT15_URL, "section 2.2, calculation of tax due", 15, "م، سيتم احتساب الضريبة على التوريدات الخاضعة للضريبة بالنسبة الأساسية 2020 يوليو1 واعتبارًا من", "supporting", "percent"),
        ],
        [
            {"statistic": "slab[standard]", "expected": 15, "tolerance": 0},
            {"statistic": "tax_fraction[standard]", "expected": 0.13043478260869565, "tolerance": 1e-12},
        ],
        "Saudi VAT as an invoicing system applies it: the basic rate of 15% (zero rate for exports, international transport, "
        "qualifying medicines and other listed supplies; reasons are in the ZATCA e-invoicing code lists), tax on a net amount and "
        "the tax contained in a VAT-inclusive amount, and the registration thresholds measured on taxable supplies over twelve "
        "months: SAR 375,000 mandatory and SAR 187,500 voluntary. The worked examples are ZATCA's own. The 15% rate applies from "
        "1 July 2020 (see sa-vat-standard-rate-history for the 5% period).",
        ["tax", "vat", "saudi-arabia", "invoicing", "registration-threshold"],
        TAX_USE_CASES,
        [assume("tax_fraction[standard]", "3/23", "derived", "15/115 reduced to lowest terms; the guideline's SAR 103.50 example contains SAR 13.50 of tax, which this fraction reproduces.")],
    )


def sa_withholding_tax() -> dict:
    rows = {
        "management_fees": {"label": "Management fees", "rate_percent": 20},
        "royalties": {"label": "Royalties", "rate_percent": 15},
        "dividends": {"label": "Dividends", "rate_percent": 5},
        "rent": {"label": "Rent", "rate_percent": 5},
        "loan_charges": {"label": "Loan charges (income from debt claims)", "rate_percent": 5},
        "insurance_reinsurance": {"label": "Insurance/reinsurance", "rate_percent": 5},
        "technical_consulting_services": {"label": "Technical and consulting services", "rate_percent": 5},
        "air_tickets_air_sea_freight": {"label": "Payments for air tickets or air or sea freight", "rate_percent": 5},
        "international_telecommunications": {"label": "International telecommunications services", "rate_percent": 5},
        "land_transport_within_kingdom": {"label": "Land transport within the Kingdom", "rate_percent": 15},
        "other_payments": {"label": "Any other payments", "rate_percent": 15},
    }
    wht = lambda value, snippet: cite(ZATCA, ZATCA_WHT_TITLE, ZATCA_WHT_URL, "withholding tax rates table", value, snippet, unit="percent")  # noqa: E731
    return rule_entry(
        "sa-withholding-tax-rates-non-residents",
        "Saudi Arabia withholding tax rates on payments to non-residents by payment type (Income Tax Law, Article 68)",
        "tax",
        "SA",
        ("2026-05-01", None),
        "almanac.rules.lookup_table",
        {"unit": "percent", "rows": rows},
        [
            lookup("management_fees", "rate_percent", 20),
            lookup("royalties", "rate_percent", 15),
            lookup("technical_consulting_services", "rate_percent", 5),
            lookup("other_payments", "rate_percent", 15),
            vector("salaries", False, "derived", "not a payment type in the table"),
        ],
        [
            wht("Management fees 20%", "Management fees 20% Royalties 15% Dividends 5% Rent 5%"),
            wht("Technical and consulting services* 5%", "Insurance/reinsurance 5% Technical and consulting services* 5%"),
            wht("International telecommunications services 5%", "Payments for air tickets or air or sea freight 5% International telecommunications services 5%"),
            wht("Any other payments 15%", "Land transport within the Kingdom 15% Any other payments 15%"),
            cite(ZATCA, ZATCA_WHT_TITLE, ZATCA_WHT_URL, "definitions", "M/1", "Income Tax Law issued by Royal Decree No. M/1 dated 15th Muharram 1425H.", "supporting"),
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[rate_percent]", "expected": 20, "tolerance": 0},
            {"statistic": "min[rate_percent]", "expected": 5, "tolerance": 0},
        ],
        "Rates at which a resident payer withholds Saudi income tax from payments to a non-resident with no permanent "
        "establishment, by type of payment, as tabulated in ZATCA's withholding tax guideline under Article 68 of the Income "
        "Tax Law and Article 63 of its Implementing Regulations. Double taxation agreements can reduce these rates, and the "
        "guideline marks technical and consulting services with an asterisk for a treaty note. Related-party royalties and "
        "special zones carry their own treatments that are not modelled.",
        ["tax", "withholding-tax", "saudi-arabia", "cross-border-payments"],
        [*TAX_USE_CASES, "accounts-payable"],
        [assume("valid_from", "2026-05-01", "derived", "The guideline's second version is dated May 2026; the rates applied earlier under the Income Tax Law of 1425H, but the fetched source confirms them only from this edition.")],
    )


def sa_labour_rules() -> dict:
    rows = {
        "daily_working_hours_max": {"value": 8, "unit": "hours", "label": "Number of daily working hours"},
        "weekly_working_hours_max": {"value": 48, "unit": "hours", "label": "Number of working hours per week"},
        "ramadan_daily_working_hours_max": {"value": 6, "unit": "hours", "label": "Daily working hours in Ramadan (Muslim workers)"},
        "ramadan_weekly_working_hours_max": {"value": 36, "unit": "hours", "label": "Weekly working hours in Ramadan (Muslim workers)"},
        "rest_break_after_consecutive_hours": {"value": 5, "unit": "hours", "label": "Consecutive hours of work before a rest break"},
        "rest_break_minimum_minutes": {"value": 30, "unit": "minutes", "label": "Minimum rest break"},
        "overtime_premium_percent_of_basic_hourly_wage": {"value": 50, "unit": "percent", "label": "Overtime: actual hourly wage plus 50% of basic hourly wage"},
        "compensatory_leave_max_days_per_year": {"value": 30, "unit": "days", "label": "Compensatory leave for overtime per year"},
        "annual_leave_min_days": {"value": 21, "unit": "days", "label": "Annual leave"},
        "annual_leave_min_days_after_5_years": {"value": 30, "unit": "days", "label": "Annual leave after 5 consecutive years"},
        "annual_leave_notice_days": {"value": 30, "unit": "days", "label": "Employer notice of leave dates"},
        "maternity_leave_weeks": {"value": 12, "unit": "weeks", "label": "Maternity leave"},
        "probation_max_days": {"value": 180, "unit": "days", "label": "Maximum probation period"},
        "unlawful_termination_compensation_days_per_year": {"value": 15, "unit": "days' pay", "label": "Indefinite contract, per year of service"},
        "unlawful_termination_compensation_min_months": {"value": 2, "unit": "months' wages", "label": "Minimum compensation"},
    }
    guide = lambda where, value, snippet: cite(HRSD, HRSD_GUIDE_TITLE, HRSD_GUIDE_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "sa-labour-law-working-time-leave-and-probation",
        "Saudi Labour Law limits: working hours, Ramadan hours, overtime premium, annual leave, probation and unlawful-termination compensation",
        "employment",
        "SA",
        ("2025-12-01", None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("daily_working_hours_max", "value", 8),
            lookup("ramadan_daily_working_hours_max", "value", 6),
            lookup("probation_max_days", "value", 180),
            lookup("annual_leave_min_days_after_5_years", "value", 30),
            lookup("overtime_premium_percent_of_basic_hourly_wage", "value", 50),
        ],
        [
            guide("section 2, working hours", 48, "Working hours are as follows: 8 hours 48 hours"),
            guide("section 2, working hours in Ramadan", 36, "daily working hours are reduced for Muslims to: 6 hours 36 hours"),
            guide("section 2, rest periods", 30, "A rest period of at least 30 minutes must be granted after every ﬁve consecutive hours of work."),
            guide("section 3, overtime", "50%", "Overtime pay is calculated on the basis of the actual wage plus 50% of the basic hourly wage."),
            guide("section 3, overtime example", "33.33", "25 + (16.67 x 0.5) = 33.33 riyals for each additional hour"),
            guide("section 3, compensatory leave", 30, "The compensatory leave must not exceed 30 days in a year"),
            guide("section 4, annual leave", 30, "Annual leave increases to 30 days if the worker completes 5 consecutive years of service with the employer"),
            guide("section 4, annual leave", 21, "Days 21 Not less than"),
            guide("section 4, maternity leave", 12, "For 12 weeks • Maternity leave"),
            guide("section 5, probation period", 180, "The probation period may not exceed 180 days."),
            guide("section 05, unlawful termination", 15, "Compensation: 15 days' pay for each year of service"),
            guide("section 05, unlawful termination", 2, "The minimum compensation shall not be less than 2 months’ wages."),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[weekly_working_hours_max,value]", "expected": 48, "tolerance": 0}],
        "Statutory limits a Saudi payroll or HR system enforces, as the Ministry of Human Resources and Social Development's "
        "2025 awareness guide states them after the Labour Law amendments: 8 hours a day and 48 a week (6 and 36 for Muslim "
        "workers in Ramadan), a 30-minute break after five consecutive hours, overtime paid at the actual hourly wage plus 50% "
        "of the basic hourly wage (the guide's example: basic 4,000 and actual 6,000 riyals a month give 33.33 riyals an "
        "overtime hour on a 30-day, 8-hour basis), annual leave of at least 21 days rising to 30 after five consecutive years, "
        "probation of at most 180 days, and for an indefinite contract ended without valid reason 15 days' pay per year of "
        "service with a two-month minimum. Notice periods appear in the guide only as an image and are not included; the "
        "pre-amendment Labor Law (Article 75) set 60 days for monthly-paid workers.",
        ["labour-law", "payroll", "working-time", "annual-leave", "saudi-arabia"],
        HR_USE_CASES,
        [assume("valid_from", "2025-12-01", "derived", "The guide is the 2025 first edition, uploaded in December 2025 (URL path); the amended limits applied earlier, but the fetched source confirms them only from this edition.")],
    )


def sa_end_of_service() -> dict:
    parameters = {
        "currency": "SAR",
        "wage_unit": "month",
        "tiers": [{"up_to_years": 5, "per_year": "1/2"}, {"up_to_years": None, "per_year": "1"}],
        "minimum_years": 0,
        "resignation": [
            {"from_years": 2, "from_inclusive": True, "fraction": "1/3"},
            {"from_years": 5, "from_inclusive": False, "fraction": "2/3"},
            {"from_years": 10, "from_inclusive": True, "fraction": "1"},
        ],
        "full_award_exceptions": [
            "worker leaves because of force majeure beyond his control",
            "female worker ends the contract within six months of marriage or three months of giving birth",
        ],
        "wage_basis": "last wage",
    }
    law = lambda where, value, snippet: cite(HRSD, HRSD_LAW_TITLE, HRSD_LAW_URL, where, value, snippet)  # noqa: E731
    guide = lambda where, value, snippet: cite(HRSD, HRSD_GUIDE_TITLE, HRSD_GUIDE_URL, where, value, snippet, "supporting")  # noqa: E731
    return rule_entry(
        "sa-end-of-service-award",
        "Saudi Labour Law end-of-service award: half a month's wage per year for five years, a month thereafter, reduced on resignation",
        "employment",
        "SA",
        ("2005-09-27", None),
        "almanac.rules.gcc_end_of_service",
        parameters,
        [
            vector({"op": "accrual", "year": 5}, "1/2", "source", "Article 84: half-month wage for each of the first five years"),
            vector({"op": "accrual", "year": 6}, "1", "source", "Article 84: one-month wage for each of the following years"),
            vector({"op": "resignation_fraction", "years": 3}, "1/3", "source", "Article 85: one third after two to five years"),
            vector({"op": "resignation_fraction", "years": 7}, "2/3", "source", "Article 85: two thirds after more than five but less than ten years"),
            vector({"op": "resignation_fraction", "years": 10}, "1", "source", "Article 85: the full award after ten years or more"),
            vector({"op": "resignation_fraction", "years": "1.5"}, "0", "derived", "no award is stated for resignation before two years"),
            vector({"monthly_wage": 10000, "years": 10, "reason": "termination"}, "75000.00", "derived", "5 x 0.5 + 5 x 1 = 7.5 months"),
            vector({"monthly_wage": 10000, "years": 3, "reason": "resignation"}, "5000.00", "derived", "1.5 months x 1/3"),
            vector({"monthly_wage": 8000, "years": "7.5", "reason": "resignation"}, "26666.67", "derived", "5 months x 2/3, part year pro rata"),
        ],
        [
            law("Article 84", "half-month wage", "an end-of-service award equivalent to the amount of a half-month wage for each of the first five years and a one-month wage"),
            law("Article 84", "last wage", "award shall be calculated on the basis of the last wage"),
            law("Article 85", "one third", "he shall, in this case, be entitled to one third of the award after service of not less than two consecutive years"),
            law("Article 85", "two thirds", "to two thirds if his service is in excess of five consecutive years but less than 10 years"),
            law("Article 85", "full award", "and to the full award if his service amounts to 10 years or more."),
            law("Article 87", "six months", "if she ends her contract within six months from the date of her marriage or three months from the date of giving birth."),
            law("title page", "September 27, 2005", "Royal Decree No. M/51 September 27, 2005"),
            guide("section 05, end of service award, resignation", "two-thirds", "Service period: more than 5 to less than 10 years Percentage of the end of service award due: two-thirds of the award"),
        ],
        [{"statistic": "tier_count", "expected": 2, "tolerance": 0}, {"statistic": "accrual[1]", "expected": 0.5, "tolerance": 0}],
        "The end-of-service award a Saudi employer pays at the end of the employment relation (Labour Law Articles 84 to 87): "
        "half a month's wage for each of the first five years and a month's wage for each later year, part years pro rata, on "
        "the last wage. On resignation the worker receives one third of the award after two to five years, two thirds after "
        "more than five and less than ten years, and the whole award after ten years; the full award is also due when the worker "
        "leaves for force majeure, or a female worker ends the contract within six months of marriage or three months of giving "
        "birth. The Ministry's 2025 awareness guide restates the same bands after the 2025 amendments. Monetary vectors are "
        "computed from the stated rules; the source publishes no numeric worked example.",
        ["labour-law", "payroll", "end-of-service", "gratuity", "saudi-arabia"],
        HR_USE_CASES,
        [
            assume("valid_from", "2005-09-27", "derived", "Date of Royal Decree M/51 printed on the translation; the law entered into force later, on a date the fetched text does not give."),
            assume("resignation below two years", 0, "derived", "Article 85 grants a share only from two years of service; shorter service on resignation earns no award."),
        ],
    )


def sa_holidays() -> dict:
    parameters = {
        "weekend": ["friday"],
        "holidays": [
            {"name": "Founding Day", "month": 2, "day": 22, "days": 1},
            {"name": "National Day", "month": 9, "day": 23, "days": 1},
        ],
        "hijri_holidays": [
            {"name": "Eid al-Fitr", "calendar": "hijri", "starts": "the day after 29 Ramadan", "days": 4},
            {"name": "Eid al-Adha", "calendar": "hijri", "starts": "the day of standing at Arafat (9 Dhu al-Hijjah)", "days": 4},
        ],
    }
    guide = lambda where, value, snippet: cite(HRSD, HRSD_GUIDE_TITLE, HRSD_GUIDE_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "sa-private-sector-official-holidays",
        "Saudi private-sector official holidays: Founding Day 22 Feb, National Day 23 Sep, Eid al-Fitr and Eid al-Adha four days each",
        "calendar",
        "SA",
        ("2025-12-01", None),
        "almanac.rules.holiday_list",
        parameters,
        [
            vector("2026-09-23", True, "source", "National Day, 23 September"),
            vector("2027-02-22", True, "source", "Founding Day, 22 February"),
            vector("2026-09-24", False, "derived"),
            vector({"op": "is_business_day", "date": "2026-11-13"}, False, "source", "Friday is the weekly rest day"),
        ],
        [
            guide("section 4, official holidays", "February 22", "Founding Day For 1 day February 22"),
            guide("section 4, official holidays", "September 23", "National Day For 1 day September 23"),
            guide("section 4, official holidays", "Starting the day after Ramadan 29", "For 4 days Starting the day after Ramadan 29"),
            guide("section 4, official holidays", "It starts from the day of standing at Arafat", "For 4 days It starts from the day of standing at Arafat"),
            guide("section 2, weekly rest day", "Friday", "Friday is the weekly rest day for all workers unless another day is agreed upon"),
        ],
        [{"statistic": "count", "expected": 2, "tolerance": 0}, {"statistic": "list_length[hijri_holidays]", "expected": 2, "tolerance": 0}],
        "Official holidays a Saudi private-sector worker receives with full pay, as the Ministry of Human Resources and Social "
        "Development's 2025 awareness guide lists them: Founding Day (22 February) and National Day (23 September), one day each, "
        "and Eid al-Fitr and Eid al-Adha, four days each. The Eid holidays follow the Hijri calendar: Eid al-Fitr starts the day "
        "after 29 Ramadan and Eid al-Adha on the day of standing at Arafat. Their Gregorian dates depend on the announced Hijri "
        "month and are held in hijri_holidays rather than as dates, so is_holiday answers only for the fixed Gregorian days. "
        "Friday is the weekly rest day unless another day is agreed with notice to the labour office. Holidays that fall on a "
        "rest day are compensated with a day before or after; National or Founding Day overlapping an Eid is not compensated.",
        ["calendar", "public-holidays", "hijri", "labour-law", "saudi-arabia"],
        [*HR_USE_CASES, "payments-scheduling", "event-timestamps"],
        [assume("valid_from", "2025-12-01", "derived", "Edition date of the awareness guide (uploaded December 2025); the fetched source confirms the list only from then.")],
    )


def sa_iban() -> dict:
    return rule_entry(
        "sa-iban-format",
        "Saudi Arabia IBAN format: 24 characters, SA prefix, MOD 97-10 check digits, printed in groups of four (SAMA)",
        "payments",
        "SA",
        ("2021-05-05", None),
        "almanac.rules.iban",
        {
            "modulus": 97,
            "complement_base": 98,
            "valid_remainder": 1,
            "letter_values": letter_values(),
            "lengths": {"SA": 24},
            "print_format": "groups of four characters separated by a blank space or dashes",
        },
        [
            vector("SA3915000999103143430001", True, "source", "SAMA's electronic IBAN example"),
            vector("SA39 1500 0999 1031 4343 0001", True, "source", "SAMA's printed IBAN example"),
            vector({"country": "SA", "bban": "15000999103143430001"}, "39", "source", "check digits of SAMA's example"),
            vector("SA3815000999103143430001", False, "derived", "one check digit altered"),
            vector("SA391500099910314343000", False, "derived", "23 characters"),
        ],
        [
            cite(SAMA, SAMA_RULEBOOK_TITLE, SAMA_RULEBOOK_URL, "Printed IBAN Account Formats, EXAMPLE", "SA3915000999103143430001", "SA3915000999103143430001"),
            cite(SAMA, SAMA_RULEBOOK_TITLE, SAMA_RULEBOOK_URL, "Printed IBAN Account Formats, EXAMPLE", "SA39 1500 0999 1031 4343 0001", "SA39 1500 0999 1031 4343 0001"),
            cite(SAMA, SAMA_RULEBOOK_TITLE, SAMA_RULEBOOK_URL, "Printed IBAN Account Formats", "groups of four characters", "the IBAN should be printed in groups of four characters and each group should be separated by a blank space or dashes."),
        ],
        [],
        "Saudi International Bank Account Numbers as the Saudi Central Bank's rulebook presents them, citing its document "
        "IBAN Standards in Saudi Arabia: printed in groups of four characters separated by blanks or dashes, and written "
        "electronically without separators. The check digits follow ISO 7064 MOD 97-10 (see global-iban-check-digits-mod97). "
        "The 24-character length is taken from SAMA's example; the structure of the BBAN (bank code and account number) is in "
        "SAMA's IBAN standard document, which was not fetched.",
        ["banking", "payments", "iban", "check-digit", "saudi-arabia"],
        BANKING_USE_CASES,
        [
            assume("lengths.SA", 24, "derived", "Length of SAMA's electronic IBAN example; the rulebook page does not state the length in words."),
            assume("valid_from", "2021-05-05", "derived", "Date of the rulebook's IBAN payment-message rule (7.12, 5/5/2021) in the same rulebook; the format is older."),
            assume("letter_values", "A=10 to Z=35", "derived", "ISO 13616 conversion table, as printed in the Central Bank of Bahrain's IBAN standard (Table 1)."),
        ],
    )


def sa_riyal_peg() -> dict:
    return rule_entry(
        "sa-riyal-us-dollar-peg",
        "Saudi riyal exchange rate regime: pegged to the US dollar at 3.75 riyals per dollar since 1986",
        "currency",
        "SA",
        ("1986-01-01", None),
        "almanac.rules.lookup_table",
        {"rows": {"SAR": {"anchor": "USD", "regime": "fixed peg", "units_per_usd": "3.75", "since": "1986", "minor_units": None}}},
        [lookup("SAR", "units_per_usd", "3.75"), lookup("SAR", "anchor", "USD"), vector("OMR", False, "derived")],
        [cite(SAMA, SAMA_FSR_TITLE, SAMA_FSR_URL, "section 2.3.2, Monetary policy condition", "3.75", "pegged to the US Dollar Since 1986 at the rate 3.75 per USD.", unit="decimal")],
        [{"statistic": "count", "expected": 1, "tolerance": 0}],
        "The Saudi riyal has been pegged to the US dollar at 3.75 riyals per dollar since 1986, as the Saudi Central Bank "
        "restates in its Financial Stability Report. A multi-currency ledger can convert SAR and USD at this rate; market rates "
        "trade in a narrow band around it. Minor units are in global-iso4217-currency-minor-units.",
        ["currency", "exchange-rate", "peg", "saudi-arabia", "banking"],
        FX_USE_CASES,
        [assume("valid_from", "1986-01-01", "derived", "The source gives only the year 1986; the first day of the year is used.")],
    )


# ---------------------------------------------------------------------------
# United Arab Emirates
# ---------------------------------------------------------------------------


def ae_corporate_tax() -> dict:
    guide = lambda where, value, snippet, unit="text": cite(FTA, CT_GUIDE_TITLE, CT_GUIDE_URL, where, value, snippet, unit=unit)  # noqa: E731
    return rule_entry(
        "ae-corporate-tax-rates",
        "UAE Corporate Tax: 0% on taxable income up to AED 375,000 and 9% above, with small business relief at AED 3 million",
        "tax",
        "AE",
        ("2023-06-01", None),
        "almanac.rules.income_tax_bands",
        {
            "currency": "AED",
            "personal_allowance": 0,
            "bands": [
                {"name": "zero_rate", "up_to": 375000, "rate_percent": 0},
                {"name": "standard", "up_to": None, "rate_percent": 9},
            ],
            "qualifying_free_zone_person_qualifying_income_rate_percent": 0,
            "small_business_relief_revenue_threshold": 3000000,
            "small_business_relief_last_period_ending": "2026-12-31",
            "cash_basis_revenue_threshold": 3000000,
        },
        [
            vector(6000000, "506250.00", "source", "General Corporate Tax Guide, Example 1"),
            vector(375000, "0.00", "source", "the portion not exceeding AED 375,000 is taxed at 0%"),
            vector(1000000, "56250.00", "derived"),
        ],
        [
            cite(MOF_AE, CD116_TITLE, CD116_URL, "Article 2", "375,000", "Taxable Income of the Taxable Person not exceeding (375,000) three hundred seventy -five thousand", unit="currency:AED"),
            cite(MOF_AE, CD116_TITLE, CD116_URL, "Article 3", "(9%) nine percent", "shall be subject to Corporate Tax at (9%) nine percent in the relevant Tax Period.", unit="percent"),
            guide("section 4, Example 1", "506,250", "A LLC’s UAE Corporate Tax liability for the Tax Period will be AED 506,250.", "currency:AED"),
            guide("section 4, Example 1", "6,000,000", "(AED 6,000,000 - AED 375,000) x 9% = AED 5,625,000 x", "currency:AED"),
            guide("section 1, introduction", "1 June 2023", "The provisions of the Corporate Tax Law shall apply to Tax Periods commencing on or after 1 June 2023."),
            guide("section 7.2, small business relief", "AED 3,000,000", "Any eligible Taxable Person with Revenue equal to or below AED 3,000,000 in a", "currency:AED"),
            guide("section 7.2, small business relief", "31 December", "relevant Tax Period and all previous Tax Periods (ending on or before 31 December"),
            guide("section 4, Qualifying Free Zone Persons", "0%", "A 0% rate of Corporate Tax applies to Qualifying Income earned by certain Free Zone", "percent"),
        ],
        [{"statistic": "count", "expected": 2, "tolerance": 0}, {"statistic": "rate[standard]", "expected": 9, "tolerance": 0}],
        "UAE Corporate Tax under Federal Decree-Law No. 47 of 2022, for tax periods starting on or after 1 June 2023: taxable "
        "income up to AED 375,000 is taxed at 0% and the excess at 9% (Cabinet Decision No. 116 of 2022). A Qualifying Free Zone "
        "Person pays 0% on its qualifying income. A resident person with revenue of AED 3,000,000 or less in the period and all "
        "earlier periods ending on or before 31 December 2026 may elect small business relief and be treated as having no "
        "taxable income; the same AED 3,000,000 revenue figure allows the cash basis of accounting. The tax computation vector "
        "is the Federal Tax Authority's own Example 1. The domestic minimum top-up tax for large multinational groups is not "
        "modelled.",
        ["tax", "corporate-tax", "uae"],
        [*TAX_USE_CASES, "financial-reporting"],
        [assume("personal_allowance", 0, "assumed", "Corporate tax has no allowance; the 0% band is modelled as the first band.")],
    )


def ae_top_up_tax() -> dict:
    rows = {
        "minimum_rate": {"value": 15, "unit": "percent", "article": "Definitions"},
        "consolidated_revenue_threshold": {"value": 750000000, "unit": "EUR", "article": "1.1.1"},
        "revenue_test_years": {"value": 2, "unit": "of the four preceding fiscal years", "article": "1.1.1"},
    }
    decision = lambda where, value, snippet, unit="text": cite(FTA, DMTT_TITLE, DMTT_URL, where, value, snippet, unit=unit)  # noqa: E731
    return rule_entry(
        "ae-domestic-minimum-top-up-tax",
        "UAE domestic minimum top-up tax on large multinational groups: 15% minimum rate, EUR 750 million revenue threshold, from 2025",
        "tax",
        "AE",
        ("2025-01-01", None),
        "almanac.rules.lookup_table",
        {"rows": rows, "top_up_tax_percentage": "positive difference between the Minimum Rate and the Effective Tax Rate"},
        [
            lookup("minimum_rate", "value", 15),
            lookup("consolidated_revenue_threshold", "value", 750000000),
            lookup("revenue_test_years", "value", 2),
        ],
        [
            decision("Article 18, Definitions", "fifteen percent (15%)", "Minimum Rate : means fifteen percent (15%).", "percent"),
            decision("Article 1.1.1", "EUR 750 million", "Group that has annual revenue of EUR 750 million or more in the Consolidated", "currency:EUR"),
            decision("Article 1.1.1", "at least two of the four", "Financial Statements of the Ultimate Parent Entity in at least two of the four Fiscal"),
            decision("Article 5.2.1", "positive", "5.2.1 The Top-up Tax Percentage for a Fiscal Year shall be the positive"),
            decision("title", "Effective from 1 January 2025", "Cabinet Decision No. 142 of 2024 – Issued 31 December of 2024 – (Effective from 1 January 2025)"),
        ],
        [{"statistic": "count", "expected": 3, "tolerance": 0}],
        "The UAE's domestic minimum top-up tax (Cabinet Decision No. 142 of 2024, effective for fiscal years beginning on or "
        "after 1 January 2025) applies to constituent entities of multinational groups with consolidated revenue of EUR 750 "
        "million or more in at least two of the four preceding fiscal years. The top-up tax percentage is the positive "
        "difference between the 15% minimum rate and the group's effective tax rate in the UAE. The full computation of "
        "the effective tax rate and excess profit is not modelled; the entry holds the thresholds a demo needs to flag "
        "in-scope groups.",
        ["tax", "corporate-tax", "global-minimum-tax", "pillar-two", "uae"],
        [*TAX_USE_CASES, "financial-reporting"],
    )


def ae_vat() -> dict:
    zero_rated = {
        "exports": "Direct or indirect export of goods and services to outside the Implementing States",
        "international_transport": "International transport of passengers and goods, including transport-related services",
        "international_air_passenger_transport": "Air passenger transport in the State that is international carriage",
        "means_of_transport": "Supply or import of air, sea and land means of transport for passengers and goods",
        "means_of_transport_goods_services": "Goods and services for the operation, repair, maintenance or conversion of those means of transport",
        "rescue_craft": "Supply or import of air or sea rescue and assistance aircraft or vessels",
        "goods_consumed_on_board": "Goods and services consumed on board international transport",
        "investment_precious_metals": "Supply or import of investment precious metals",
        "first_supply_residential_buildings": "First supply of residential buildings within 3 years of completion",
        "first_supply_charity_buildings": "First supply of buildings designed for use by charities",
        "first_supply_converted_residential": "First supply of buildings converted from non-residential to residential",
        "crude_oil_natural_gas": "Supply or import of crude oil and natural gas",
        "education": "Educational services and related goods and services for nurseries, schools and government-funded higher education",
        "healthcare": "Preventive and basic healthcare services and related goods and services",
    }
    exempt = {
        "financial_services": "Financial services specified in the Executive Regulation",
        "residential_buildings": "Residential buildings by sale or lease, other than zero-rated first supplies",
        "bare_land": "Bare land",
        "local_passenger_transport": "Local passenger transport",
    }
    law = lambda where, value, snippet, unit="text": cite(MOF_AE, VAT_LAW_AE_TITLE, VAT_LAW_AE_URL, where, value, snippet, unit=unit)  # noqa: E731
    reg = lambda where, value, snippet: cite(MOF_AE, VAT_REG_AE_TITLE, VAT_REG_AE_URL, where, value, snippet, unit="currency:AED")  # noqa: E731
    return rule_entry(
        "ae-vat-rate-thresholds-zero-rated-and-exempt-supplies",
        "UAE VAT: 5% standard rate, AED 375,000 and AED 187,500 registration thresholds, zero-rated and exempt supplies",
        "tax",
        "AE",
        ("2018-01-01", None),
        "almanac.rules.consumption_tax",
        {
            "currency": "AED",
            "slabs": {"standard": 5, "zero": 0},
            "rounding": "0.01",
            "mandatory_registration_threshold": 375000,
            "voluntary_registration_threshold": 187500,
            "registration_application_days": 30,
            "zero_rated_supplies": zero_rated,
            "exempt_supplies": exempt,
        },
        [
            vector(5, True, "source", "Article 3: a standard rate of 5%"),
            vector(0, True, "source", "Article 45: the zero rate"),
            vector({"net": 1000}, "50.00", "derived"),
            vector({"gross": 105}, "5.00", "derived"),
            vector(15, False, "derived"),
        ],
        [
            law("Article 3, Tax Rate", "5%", "a standard rate of 5% Tax shall be imposed on any supply or Import", "percent"),
            law("title page", "Effective from 1 Jan 2018", "Federal Decree-Law No. 8 of 2017 – Issued 23 Aug 2017 (Effective from 1 Jan 2018)"),
            law("Article 45, Goods and Services Subject to Zero Rate", "investment precious metals", "The supply or Import of investment precious metals."),
            law("Article 45, Goods and Services Subject to Zero Rate", "crude oil and natural gas", "The supply or Import of crude oil and natural gas."),
            law("Article 46, Supply Exempt from Tax", "bare land", "Supply of bare land. 4. Supply of local passenger transport."),
            reg("Article 7, Mandatory Registration", "375,000", "Registration Threshold shall be AED 375,000 (three hundred and seventy -five"),
            reg("Article 8, Voluntary Registration", "187,500", "The Voluntary Registration Threshold shall be AED 187,500"),
            cite(MOF_AE, VAT_REG_AE_TITLE, VAT_REG_AE_URL, "Article 7, Mandatory Registration", "30 (thirty) days", "Tax Registration application with the Authority within 30 (thirty) days of being required to register."),
        ],
        [{"statistic": "slab[standard]", "expected": 5, "tolerance": 0}, {"statistic": "count", "expected": 2, "tolerance": 0}],
        "UAE VAT under Federal Decree-Law No. 8 of 2017 as amended (consolidated text published November 2025), in force from "
        "1 January 2018: a standard rate of 5% on supplies and imports (Article 3), the zero-rated supplies of Article 45 and the "
        "exempt supplies of Article 46, held as code lists with labels summarising each clause. The Executive Regulation sets "
        "the mandatory registration threshold at AED 375,000 and the voluntary one at AED 187,500, with 30 days to apply once "
        "registration is required. The executive regulation conditions on each zero-rated or exempt category are not modelled.",
        ["tax", "vat", "uae", "invoicing", "registration-threshold"],
        TAX_USE_CASES,
        [assume("zero_rated_supplies labels", "summaries", "derived", "Each label summarises one clause of Article 45 or 46 in a few words; the clause text is longer.")],
    )


def ae_labour_rules() -> dict:
    rows = {
        "probation_max_months": {"value": 6, "unit": "months", "article": "9"},
        "probation_termination_notice_days": {"value": 14, "unit": "days", "article": "9"},
        "daily_working_hours_max": {"value": 8, "unit": "hours", "article": "17"},
        "weekly_working_hours_max": {"value": 48, "unit": "hours", "article": "17"},
        "consecutive_hours_before_break": {"value": 5, "unit": "hours", "article": "18"},
        "daily_overtime_max_hours": {"value": 2, "unit": "hours", "article": "19"},
        "total_hours_max_per_3_weeks": {"value": 144, "unit": "hours", "article": "19"},
        "overtime_premium_percent": {"value": 25, "unit": "percent of basic wage", "article": "19"},
        "night_overtime_premium_percent": {"value": 50, "unit": "percent of basic wage, 10 pm to 4 am", "article": "19"},
        "weekend_work_premium_percent": {"value": 50, "unit": "percent of basic wage", "article": "19"},
        "annual_leave_days": {"value": 30, "unit": "days per year", "article": "29"},
        "annual_leave_days_per_month_6_to_12_months": {"value": 2, "unit": "days per month", "article": "29"},
        "notice_period_min_days": {"value": 30, "unit": "days", "article": "43"},
        "notice_period_max_days": {"value": 90, "unit": "days", "article": "43"},
    }
    law = lambda where, value, snippet: cite(LABOUR_AE, LABOUR_AE_TITLE, LABOUR_AE_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "ae-labour-law-working-time-leave-and-notice",
        "UAE private-sector labour law limits: probation, working hours, overtime premiums, annual leave and notice periods",
        "employment",
        "AE",
        ("2022-02-02", None),
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            lookup("probation_max_months", "value", 6),
            lookup("weekly_working_hours_max", "value", 48),
            lookup("overtime_premium_percent", "value", 25),
            lookup("notice_period_max_days", "value", 90),
            lookup("annual_leave_days", "value", 30),
        ],
        [
            law("Article 9", 6, "The employer may appoint the worker under a probationary period not exceeding (6) six months"),
            law("Article 9", "fourteen (14) days", "writing fourteen (14) days at least before the date specified for the termination of service."),
            law("Article 17", 48, "The maximum normal working hours for workers shall be (8) eight hours per day or (48) forty-eight hours per week."),
            law("Article 18", 5, "The worker may not work for more than (5) five consecutive hours without a break"),
            law("Article 19", 144, "the total working hours shall not exceed ( 144) one hundred and forty four hours every (3) three weeks."),
            law("Article 19", "25 %", "is calculated according to the basic wage plus an increase of not less than ( 25 %) twenty five percent of that wage."),
            law("Article 19", "between 10 pm and 4 am", "If the work conditions require that the worker works overtime between 10 pm and 4 am,"),
            law("Article 29", "Thirty days", "a. Thirty days for each year of extended service;"),
            law("Article 29", "Two days for each month", "b. Two days for each month if his service term is more than six months and less"),
            law("Article 43", "( 90) ninety days", "such period is not less than ( 30) thirty days and not more than ( 90) ninety days."),
            law("Article 74", "2 February 2022", "shall be enforced as of2 February 2022."),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": 144, "tolerance": 0}],
        "Limits that UAE private-sector payroll and HR systems enforce under Federal Decree-Law No. 33 of 2021 on the Regulation "
        "of Employment Relationships, in force from 2 February 2022: probation of at most six months (14 days' written notice to "
        "end it), 8 hours a day or 48 a week, no more than 5 consecutive hours without a break, overtime of at most 2 hours a day "
        "and 144 hours in any three weeks, overtime paid at the basic wage plus at least 25% (50% between 10 pm and 4 am, and for "
        "weekend work), annual leave of 30 days per year of service (2 days a month between six months and a year), and contract "
        "notice of 30 to 90 days. Ramadan hours are set by the Implementing Regulation, which was not fetched. The text is the "
        "consolidated English translation with amendments, which states that it is not an official translation.",
        ["labour-law", "payroll", "working-time", "annual-leave", "uae"],
        HR_USE_CASES,
    )


def ae_end_of_service() -> dict:
    parameters = {
        "currency": "AED",
        "wage_unit": "day",
        "days_per_month": 30,
        "tiers": [{"up_to_years": 5, "per_year": "21"}, {"up_to_years": None, "per_year": "30"}],
        "minimum_years": 1,
        "cap_months": 24,
        "wage_basis": "last basic wage",
        "applies_to": "full-time foreign workers; nationals receive pension under the pensions and social security legislation",
    }
    law = lambda where, value, snippet: cite(LABOUR_AE, LABOUR_AE_TITLE, LABOUR_AE_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "ae-end-of-service-gratuity",
        "UAE end-of-service gratuity for foreign workers: 21 days' basic wage a year for five years, 30 days thereafter, capped at two years",
        "employment",
        "AE",
        ("2022-02-02", None),
        "almanac.rules.gcc_end_of_service",
        parameters,
        [
            vector({"op": "accrual", "year": 3}, "21", "source", "Article 51(2)(a): 21 days for each of the first five years"),
            vector({"op": "accrual", "year": 6}, "30", "source", "Article 51(2)(b): 30 days for each year exceeding five"),
            vector({"op": "award_months", "years": "0.9"}, "0", "source", "Article 51(2): entitlement requires a year or more of continuous service"),
            vector({"monthly_wage": 10000, "years": 5}, "35000.00", "derived", "5 x 21 days at 10,000 / 30"),
            vector({"monthly_wage": 10000, "years": 10}, "85000.00", "derived", "5 x 21 + 5 x 30 = 255 days"),
            vector({"monthly_wage": 10000, "years": 30}, "240000.00", "derived", "capped at two years' (24 months') wage"),
            vector({"monthly_wage": 9000, "years": "2.5"}, "15750.00", "derived", "52.5 days at 300 a day"),
        ],
        [
            law("Article 51(2)", "completed a year or more", "The full-time foreign worker, who completed a year or more in continuous service,"),
            law("Article 51(2)(a)", "(21) twenty one days", "a. A wage of (21) twenty one days for each year of the first five years of service;"),
            law("Article 51(2)(b)", "(30) thirty days", "b. A wage of (30) thirty days for each year exceeding such period."),
            law("Article 51(3)", "parts of the year", "The foreign worker shall be entitled to a benefit for parts of the year in proportion to"),
            law("Article 51(6)", "two years’ wage", "worker in its entirety does not exceed two years’ wage."),
            law("Article 51(5)", "last basic wage", "calculated according to the last basic wage the worker was entitled to,"),
        ],
        [{"statistic": "tier_count", "expected": 2, "tolerance": 0}, {"statistic": "accrual[6]", "expected": 30, "tolerance": 0}, {"statistic": "cap_months", "expected": 24, "tolerance": 0}],
        "End-of-service benefit for a full-time foreign worker under Article 51 of Federal Decree-Law No. 33 of 2021: after at "
        "least a year of continuous service, 21 days of the last basic wage for each of the first five years and 30 days for each "
        "later year, part years pro rata, unpaid absence excluded, the total capped at two years' wage. The 2021 law makes no "
        "reduction for resignation. UAE nationals are covered by pension legislation instead. The law does not convert a "
        "monthly wage to a daily one in the text fetched; the entry uses 30 days a month, which is an assumption, as is reading "
        "two years' wage as 24 months of basic wage. Monetary vectors are computed from the stated rule.",
        ["labour-law", "payroll", "end-of-service", "gratuity", "uae"],
        HR_USE_CASES,
        [
            assume("days_per_month", 30, "assumed", "The Decree-Law text does not define the daily wage for monthly-paid workers; 30 days a month is assumed."),
            assume("cap_months", 24, "derived", "Article 51(6) caps the benefit at two years' wage, read as 24 months of the basic wage."),
        ],
    )


def ae_gpssa() -> dict:
    rows = {
        "faq_government_sector": {"insured_percent": 5, "employer_percent": 15, "government_percent": 0, "total_percent": 20},
        "faq_private_sector": {"insured_percent": 5, "employer_percent": "12.5", "government_percent": "2.5", "total_percent": 20},
        "federal_law_57_2023": {"insured_percent": 11, "employer_percent": 15, "government_percent": None, "total_percent": 26},
    }
    faq = lambda value, snippet: cite(GPSSA, GPSSA_FAQ_TITLE, GPSSA_FAQ_URL, "FAQ answer", value, snippet, unit="percent")  # noqa: E731
    law57 = lambda value, snippet: cite(GPSSA, GPSSA_LAW57_TITLE, GPSSA_LAW57_URL, "news article, Contribution rates", value, snippet, unit="percent")  # noqa: E731
    return rule_entry(
        "ae-gpssa-pension-contribution-rates",
        "UAE GPSSA pension contributions for Emirati employees: insured, employer and government shares as GPSSA publishes them",
        "pensions",
        "AE",
        ("2024-08-21", None),
        "almanac.rules.lookup_table",
        {"rows": rows, "private_sector_government_support_salary_ceiling_aed": 20000},
        [
            lookup("faq_private_sector", "employer_percent", "12.5"),
            lookup("faq_government_sector", "employer_percent", 15),
            lookup("federal_law_57_2023", "insured_percent", 11),
            lookup("federal_law_57_2023", "total_percent", 26),
        ],
        [
            faq("5%", "Insured in both government and private sectors: 5%- Government sector: Employers contribute 15% of the Contribution Calculation Salary."),
            faq("12.5%", "Private sector: Employers pay 12.5% of the Contribution Calculation Salary."),
            faq("2.5%", "The government contributes by bearing 2.5% of the contribution rate determined for an insured individual employed in the private sector"),
            faq("20%", "The percentage of the total contributions due from an insured individual working in the government or private sector is 20%."),
            law57("26%", "As per the 2023 law, the total contribution rates have become 26%, out of which the insured bears 11%"),
            law57("Dh20,000", "employing Emiratis whose contribution account salaries are less than Dh20,000, by paying 2.5% out of the employers 15% share."),
        ],
        [{"statistic": "count", "expected": 3, "tolerance": 0}],
        "Pension contributions for UAE nationals registered with the General Pension and Social Security Authority, as two GPSSA "
        "pages state them. The FAQ (last updated 21 August 2024) gives 5% from the insured, 15% from a government-sector "
        "employer, and 12.5% from a private-sector employer with the government bearing 2.5%, 20% in total. GPSSA's article on "
        "Federal Law No. 57 of 2023 says that under that law the total is 26%, 11% from the insured and 15% from the employer, "
        "with the government paying 2.5% of the employer share for Emiratis whose contribution salary is below AED 20,000. The "
        "pages do not say which insured persons each schedule covers; the rows are kept separate and named after their source "
        "for a human to reconcile. Abu Dhabi nationals are covered by the Abu Dhabi Pension Fund, whose site could not be "
        "reached.",
        ["pensions", "social-insurance", "payroll", "uae"],
        [*HR_USE_CASES, "pensions"],
        [assume("valid_from", "2024-08-21", "derived", "The FAQ's last-updated date; the rates applied earlier.")],
    )


# ---------------------------------------------------------------------------
# Bahrain and Kuwait
# ---------------------------------------------------------------------------


def bh_iban() -> dict:
    iban = lambda where, value, snippet: cite(CBB, CBB_IBAN_TITLE, CBB_IBAN_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "bh-iban-format",
        "Bahrain IBAN format: 22 characters, BH, check digits, four-letter bank code from the BIC and 14-character account (CBB)",
        "payments",
        "BH",
        ("2011-02-16", None),
        "almanac.rules.iban",
        {
            "modulus": 97,
            "complement_base": 98,
            "valid_remainder": 1,
            "letter_values": letter_values(),
            "lengths": {"BH": 22},
            "structure": {"country_code": "BH", "check_digits": 2, "bank_identifier": "first four letters of the bank's BIC", "account_number": "14 characters, left-padded with zeros"},
        },
        [
            vector("BH50NBOB00001299123456", True, "source", "Example 1"),
            vector("BH89SCBLBHD18123456701", True, "source", "Example 2, alphanumeric account"),
            vector("BH50 NBOB 0000 1299 1234 56", True, "source", "print format of Example 1"),
            vector({"country": "BH", "bban": "NBOB00001299123456"}, "50", "source", "Annexure I check digit generation"),
            vector("BH51NBOB00001299123456", False, "derived"),
        ],
        [
            iban("section 3.2, Length of IBAN", "22 characters", "The IBAN for the Kingdom of Bahrain is fixed in length, 22 characters,"),
            iban("section 3.3, Example 1", "BH50NBOB00001299123456", "IBAN electronic format example: BH50NBOB00001299123456"),
            iban("section 3.3, Example 2", "BH89SCBLBHD18123456701", "IBAN electronic format example: BH89SCBLBHD18123456701"),
            iban("Annexure I, Step 10", "98-48=50", "Subtract this final remainder (48) from 98. (98-48=50)"),
            iban("section 3.1, Table 1", "Z 35", "M 22 Z 35"),
        ],
        [],
        "Bahraini International Bank Account Numbers as the Central Bank of Bahrain's 2011 ISO IBAN standard specifies them: "
        "22 characters made of the country code BH, two MOD 97-10 check digits, the first four letters of the account-holding "
        "bank's BIC, and the 14-character core account number padded with leading zeros. The vectors are the standard's own "
        "examples and its worked check-digit generation (remainder 48, check digits 98 - 48 = 50).",
        ["banking", "payments", "iban", "check-digit", "bahrain"],
        BANKING_USE_CASES,
    )


def bh_dinar_peg() -> dict:
    policy = lambda value, snippet: cite(CBB, CBB_POLICY_TITLE, CBB_POLICY_URL, "Exchange Rate Policy", value, snippet, unit="decimal")  # noqa: E731
    return rule_entry(
        "bh-dinar-us-dollar-peg",
        "Bahraini dinar exchange rate regime: pegged to the US dollar at 0.376 dinars per dollar",
        "currency",
        "BH",
        ("1980-01-01", None),
        "almanac.rules.lookup_table",
        {"rows": {"BHD": {"anchor": "USD", "regime": "fixed peg", "units_per_usd": "0.376", "since": "1980"}}},
        [lookup("BHD", "units_per_usd", "0.376"), lookup("BHD", "anchor", "USD")],
        [
            policy("0.376", "Bahrain maintains an exchange rate peg at 0.376 Bahraini dinars to the US dollar."),
            policy("1980", "The peg has been effectively unchanged since 1980."),
        ],
        [{"statistic": "count", "expected": 1, "tolerance": 0}],
        "The Bahraini dinar is pegged to the US dollar at 0.376 dinars per dollar, a peg the Central Bank of Bahrain describes "
        "as effectively unchanged since 1980. The CBB buys and sells US dollars to retail banks at rates very close to the "
        "official rate.",
        ["currency", "exchange-rate", "peg", "bahrain", "banking"],
        FX_USE_CASES,
        [assume("valid_from", "1980-01-01", "derived", "The source gives only the year 1980; the first day of the year is used.")],
    )


def kw_iban() -> dict:
    iban = lambda where, value, snippet: cite(CBK, CBK_IBAN_TITLE, CBK_IBAN_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "kw-iban-format",
        "Kuwait IBAN format: 30 characters, KW, check digits, four-letter bank code and 22-character account number (CBK)",
        "payments",
        "KW",
        ("2011-01-01", None),
        "almanac.rules.iban",
        {
            "modulus": 97,
            "complement_base": 98,
            "valid_remainder": 1,
            "letter_values": letter_values(),
            "lengths": {"KW": 30},
            "structure": {"country_code": "KW", "check_digits": 2, "bank_code": "four letters", "account_number": "22 alphanumeric characters, left-padded with zeros"},
        },
        [
            vector("KW81CBKU0000000000001234560101", True, "source", "electronic format example"),
            vector("KW81 CBKU 0000 0000 0000 1234 5601 01", True, "source", "print format example"),
            vector({"country": "KW", "bban": "CBKU0000000000001234560101"}, "81", "source", "check digits of the example"),
            vector("KW81CBKU000000000000123456010", False, "derived", "29 characters"),
        ],
        [
            iban("section 2, IBAN Structure in Kuwait", "30 digits", "The IBAN for Kuwait consists of 30 digits (letters and numbers) divided as follows:"),
            iban("section 2, IBAN Electronic format", "KW81CBKU0000000000001234560101", "KW81CBKU0000000000001234560101"),
            iban("section 2, IBAN Print format", "KW81 CBKU 0000 0000 0000 1234 5601 01", "KW81 CBKU 0000 0000 0000 1234 5601 01"),
            iban("section 2, IBAN Structure in Kuwait", "1/1/2011", "register the IBAN format for Kuwait effective from 1/1/2011."),
            iban("section 2, IBAN Structure in Kuwait", "MOD97-", "ISO/IEC 7064 (MOD97-"),
        ],
        [],
        "Kuwaiti International Bank Account Numbers as the Central Bank of Kuwait specifies them, effective 1 January 2011: 30 "
        "characters made of the country code KW, two ISO 7064 MOD 97-10 check digits, a four-letter bank code and a "
        "22-character account number formed by left-padding the bank's existing account number with zeros. The vectors are the "
        "CBK's own example in print and electronic form.",
        ["banking", "payments", "iban", "check-digit", "kuwait"],
        BANKING_USE_CASES,
        [assume("letter_values", "A=10 to Z=35", "derived", "ISO 13616 conversion table, as printed in the Central Bank of Bahrain's IBAN standard (Table 1).")],
    )


def kw_dinar_regime() -> dict:
    review = lambda value, snippet: cite(CBK, CBK_REVIEW_TITLE, CBK_REVIEW_URL, "Kuwaiti dinar exchange rate", value, snippet)  # noqa: E731
    return rule_entry(
        "kw-dinar-currency-basket-peg",
        "Kuwaiti dinar exchange rate regime: pegged since 20 May 2007 to an undisclosed weighted basket of currencies",
        "currency",
        "KW",
        ("2007-05-20", None),
        "almanac.rules.lookup_table",
        {"rows": {"KWD": {"anchor": "undisclosed weighted basket of currencies of Kuwait's major trade and financial partners", "regime": "basket peg", "units_per_usd": None, "since": "2007-05-20", "legal_basis": "Decree No. 147/2007"}}},
        [lookup("KWD", "legal_basis", "Decree No. 147/2007"), lookup("KWD", "regime", "basket peg"), lookup("KWD", "units_per_usd", None)],
        [
            review("May 20, 2007", "we note that since May 20, 2007, by virtue of the Decree No. 147/2007, the Kuwaiti dinar (KWD)"),
            review("basket", "peg the KWD to a special weighted basket of currencies of Kuwait’s major trade and"),
        ],
        [{"statistic": "count", "expected": 1, "tolerance": 0}],
        "Unlike the other Gulf currencies, the Kuwaiti dinar has no fixed US dollar rate: since 20 May 2007, under Decree No. "
        "147/2007, it has been pegged to an undisclosed weighted basket of the currencies of Kuwait's major trade and financial "
        "partners, as the Central Bank of Kuwait restates in its November 2022 review. A generator converting KWD must use "
        "published market rates; the basket weights are not disclosed.",
        ["currency", "exchange-rate", "peg", "kuwait", "banking"],
        FX_USE_CASES,
    )


# ---------------------------------------------------------------------------
# Oman
# ---------------------------------------------------------------------------


def om_vat() -> dict:
    exempt = {
        "financial_services": "Financial Services",
        "healthcare": "Healthcare Services and related Goods and Services",
        "education": "Educational Services and related Goods and Services",
        "bare_land": "Undeveloped land (bare land)",
        "resale_residential": "Resale of residential properties",
        "local_passenger_transport": "Local passenger transport",
        "residential_rental": "Rental of properties for residential purposes",
    }
    zero_rated = {
        "food": "Food items specified by a decision from the Chairman",
        "medicines_medical_equipment": "Medicines and medical equipment",
        "investment_metals": "Investment gold, silver and platinum",
        "international_transport": "International and intra-GCC transport of goods or passengers and connected services",
        "means_of_transport": "Air, sea and land means of transport for commercial carriage, and related goods and services",
        "rescue_craft": "Rescue planes and rescue and assistance boats",
        "oil_gas": "Oil, oil derivatives and natural gas",
        "exports": "Export of goods and services to customers outside the GCC",
    }
    law = lambda where, value, snippet, unit="text": cite(OTA, OM_VAT_TITLE, OM_VAT_URL, where, value, snippet, unit=unit)  # noqa: E731
    return rule_entry(
        "om-vat-rate-zero-rated-and-exempt-supplies",
        "Oman VAT: 5% rate on the taxable value, zero-rated supplies and exempt supplies (Royal Decree 121/2020)",
        "tax",
        "OM",
        ("2021-06-01", None),
        "almanac.rules.consumption_tax",
        {"currency": "OMR", "slabs": {"standard": 5, "zero": 0}, "rounding": "0.001", "prices_inclusive_of_tax": True, "zero_rated_supplies": zero_rated, "exempt_supplies": exempt},
        [
            vector(5, True, "source", "Article 36: five percent of the taxable value"),
            vector(0, True, "source", "Article 51: zero rate"),
            vector({"net": "100.000"}, "5.000", "derived"),
            vector({"gross": "10.500"}, "0.500", "derived"),
        ],
        [
            law("Article 36", "(5%) five percent", "(5%) five percent of the Taxable Value."),
            law("Article 37", "inclusive", "The Taxable Person shall present the prices of Goods and Services inclusive of the Tax."),
            law("Article 47", "Financial Services", "1. Financial Services. 2. Healthcare Services and related Goods and Services."),
            law("Article 47", "Rental of properties", "7. Rental of properties for residential purposes."),
            law("Article 51", "investment gold", "3. The supply of investment gold, silver, and platinum."),
            law("Article 51", "oil derivatives", "The supply of oil, oil derivatives and natural gas."),
            law("Royal Decree, Article Four", "(180)", "shall come into force after (180) one hundred and eighty days from the date of publication."),
            cite(OTA, OM_VAT_GUIDE_TITLE, OM_VAT_GUIDE_URL, "publication information", "June 2021", "Publication info: Version 1 – June 2021", "supporting"),
        ],
        [{"statistic": "slab[standard]", "expected": 5, "tolerance": 0}, {"statistic": "count", "expected": 2, "tolerance": 0}],
        "Oman VAT under the Value Added Tax Law promulgated by Royal Decree 121/2020 (issued 12 October 2020, in force 180 days "
        "after publication in the Official Gazette): 5% of the taxable value (Article 36), with prices shown inclusive of tax "
        "(Article 37). Exempt supplies (Article 47) and zero-rated supplies (Articles 51 and 52) are held as code lists. The "
        "registration thresholds are set by a Chairman's decision that the Tax Authority publishes only as a scanned image, so "
        "they are not included. The Omani rial has three decimal places, used as the rounding step.",
        ["tax", "vat", "oman", "invoicing"],
        TAX_USE_CASES,
        [
            assume("valid_from", "2021-06-01", "derived", "The law came into force 180 days after its gazette publication, a date the fetched text does not give; valid_from is the June 2021 edition date of the Tax Authority's VAT return guide, the earliest date the fetched sources confirm the tax in force."),
            assume("rounding", "0.001", "assumed", "Three decimal places for the Omani rial (ISO 4217); the law does not state a rounding rule."),
        ],
    )


def om_income_tax() -> dict:
    rows = {
        "standard": {"rate_percent": 15, "base": "taxable income of any establishment, Omani company or permanent establishment", "article": "112"},
        "non_resident_withholding": {"rate_percent": 10, "base": "gross amount of income under Article 52", "article": "113"},
        "petroleum": {"rate_percent": 55, "base": "taxable income from the sale of petroleum", "article": "114"},
        "small_enterprise": {"rate_percent": 3, "base": "taxable income of an enterprise meeting Article 159bis", "article": "159bis 15"},
    }
    law = lambda where, value, snippet: cite(OTA, OM_IT_TITLE, OM_IT_URL, where, value, snippet)  # noqa: E731
    return rule_entry(
        "om-income-tax-rates",
        "Oman income tax rates: 15% corporate, 3% small enterprise, 10% withholding on non-residents, 55% petroleum",
        "tax",
        "OM",
        ("2024-12-16", None),
        "almanac.rules.lookup_table",
        {
            "unit": "percent",
            "rows": rows,
            "small_enterprise_conditions": {"max_registered_capital_omr": 50000, "max_gross_income_omr": 100000, "max_average_employees": 15},
        },
        [
            lookup("standard", "rate_percent", 15),
            lookup("small_enterprise", "rate_percent", 3),
            lookup("non_resident_withholding", "rate_percent", 10),
            lookup("petroleum", "rate_percent", 55),
        ],
        [
            law("Article 112", "%15", "The tax stipulated in this Part shall be computed by applying the rate of %15 of the taxable income"),
            law("Article 113", "%10", "The tax rate referred to in Article 52 of this Law shall be %10 of the gross amount."),
            law("Article 114", "%55", "The tax rate for taxpayers engaged in petroleum exploration shall be %55"),
            law("Article 159bis 15", "%3", "The tax stipulated in this chapter shall be calculated by applying a %3 rate on the enterprise’s taxable income"),
            law("Article 159bis", "(50,000)", "shall not exceed (50,000) fifty thousand Omani Rials;"),
            law("Article 159bis", "(100,000)", "The gross income realized at the end of the tax year shall not exceed (100,000) one hundred thousand Omani Rials;"),
            law("Article 159bis", "(15) employees", "The average number of employees during the tax year shall not exceed (15) employees;"),
        ],
        [{"statistic": "count", "expected": 4, "tolerance": 0}, {"statistic": "max[rate_percent]", "expected": 55, "tolerance": 0}],
        "Income tax rates in Oman from the Tax Authority's consolidated English text of the Income Tax Law (Royal Decree 28/2009 "
        "as amended by Royal Decree 118/2020): 15% of the taxable income of establishments, Omani companies and permanent "
        "establishments (Article 112); 10% of the gross amount withheld on the non-resident income listed in Article 52 "
        "(Article 113); 55% on petroleum income (Article 114); and 3% for small enterprises with registered capital up to OMR "
        "50,000, gross income up to OMR 100,000 and at most 15 employees on average, excluding owner-managed enterprises and "
        "those employing at least two Omanis (Article 159bis). The English text is a draft translation for guidance; the "
        "Arabic text prevails.",
        ["tax", "corporate-tax", "withholding-tax", "oman"],
        [*TAX_USE_CASES, "financial-reporting"],
        [assume("valid_from", "2024-12-16", "derived", "Creation date of the Tax Authority's consolidated PDF; the rates applied earlier from amendments the fetched text does not date.")],
    )


BUILDERS = [
    sa_vat_rate_history,
    sa_vat_rate_and_thresholds,
    sa_withholding_tax,
    sa_labour_rules,
    sa_end_of_service,
    sa_holidays,
    sa_iban,
    sa_riyal_peg,
    ae_corporate_tax,
    ae_top_up_tax,
    ae_vat,
    ae_labour_rules,
    ae_end_of_service,
    ae_gpssa,
    bh_iban,
    bh_dinar_peg,
    kw_iban,
    kw_dinar_regime,
    om_vat,
    om_income_tax,
]


def main() -> None:
    for build in BUILDERS:
        write(build())


if __name__ == "__main__":
    main()

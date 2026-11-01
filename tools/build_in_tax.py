"""Build the India tax and macro entries from Union Budget 2026-27, GST Council and Economic Survey documents.

Sources are the Ministry of Finance's budget PDFs (Memorandum, Finance Bill,
Budget at a Glance), the Income Tax Department's e-filing help page, the GST
Council Secretariat's press release and FAQ for the 57th Council meeting, and
the per-table PDFs of the Economic Survey 2025-26 Statistical Appendix. Every
value is read from the fetched text, and each evidence snippet is checked
against the extracted text before the entry is written. Run from the repository
root:

    uv run python tools/build_in_tax.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

ACCESSED = "2026-11-01"

BUDGET = "https://www.indiabudget.gov.in/doc"
MEMO_URL = f"{BUDGET}/memo.pdf"
BILL_URL = f"{BUDGET}/Finance_Bill.pdf"
BAG1_URL = f"{BUDGET}/Budget_at_Glance/bag1.pdf"
BAG2_URL = f"{BUDGET}/Budget_at_Glance/bag2.pdf"
EFILING_URL = "https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-0"
GST = "https://gstcouncil.gov.in/sites/default/files/2026-10"
GST_PR_URL = f"{GST}/press_release_0.pdf"
GST_FAQ_URL = f"{GST}/faqs_on_recommendations_made_in_57th_gst_council_meeting.pdf"
SURVEY = "https://www.indiabudget.gov.in/economicsurvey/doc/stat"

MOF = "Ministry of Finance, Government of India"
ITD = "Income Tax Department, Government of India (e-Filing portal)"
GSTC = "GST Council Secretariat (Press Information Bureau release of the Ministry of Finance)"
UNSTATED = "unstated"
GST_LICENSE = "GST Council copyright policy: reproduction free of charge after permission by email, with acknowledgement"

MEMO_TITLE = "Memorandum Explaining the Provisions in the Finance Bill, 2026"
BILL_TITLE = "Finance Bill, 2026 (Bill No. 16 of 2026, as introduced in Lok Sabha)"
EFILING_TITLE = "Returns and forms applicable for AY 2026-27 (tax slab and surcharge tables), e-Filing help"
PR_TITLE = "Recommendations of the 57th Meeting of the GST Council, New Delhi, 8 October 2026"
FAQ_TITLE = "FAQs on recommendations made in the 57th GST Council meeting"
SURVEY_TITLE = "Economic Survey 2025-26, Statistical Appendix"

INCOME_TAX_TAGS = ["income-tax", "slabs", "payroll", "finance-bill-2026"]
INCOME_TAX_USE_CASES = ["payroll-demo", "hr-analytics", "personal-finance", "tax-filing-demo"]
FY_2026_27 = ("2026-04-01", "2027-03-31")

RAW: dict[str, bytes] = {}
TEXT: dict[str, str] = {}


def load(url: str) -> bytes:
    """Fetch a resource once, keeping its bytes and extracted text for the citation check."""
    if url not in RAW:
        RAW[url] = fetch(url)
        TEXT[url] = " ".join(Resource(url, RAW[url], "").text.split())
    return RAW[url]


def cite(publisher: str, title: str, url: str, locator: str, value: Any, unit: str, snippet: str, license_id: str, role: str = "primary") -> dict:
    """Evidence item whose value and snippet are confirmed present in the fetched text."""
    raw = load(url)
    for label, needle in (("value", str(value)), ("snippet", snippet)):
        if " ".join(needle.split()) not in TEXT[url]:
            raise ValueError(f"{label} not found in {url}: {needle!r}")
    if len(snippet.split()) > 24:
        raise ValueError(f"snippet over 24 words: {snippet!r}")
    item = evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role)
    item["accessed_at"] = ACCESSED
    return item


def memo(locator: str, value: str, snippet: str, role: str = "primary") -> dict:
    return cite(MOF, MEMO_TITLE, MEMO_URL, locator, value, "text", snippet, UNSTATED, role)


def bill(locator: str, value: str, snippet: str, role: str = "primary") -> dict:
    return cite(MOF, BILL_TITLE, BILL_URL, locator, value, "text", snippet, UNSTATED, role)


def efiling(locator: str, value: str, snippet: str) -> dict:
    """Kept for reference: the e-filing help page changes between fetches and is no longer cited."""
    return cite(ITD, EFILING_TITLE, EFILING_URL, locator, value, "text", snippet, UNSTATED, "supporting")


def press(locator: str, value: str, snippet: str) -> dict:
    return cite(GSTC, PR_TITLE, GST_PR_URL, locator, value, "text", snippet, GST_LICENSE)


def faq(locator: str, value: str, snippet: str) -> dict:
    return cite(GSTC, FAQ_TITLE, GST_FAQ_URL, locator, value, "text", snippet, GST_LICENSE)


SURVEY_TABLES = {
    "tab1.1": "Table 1.1: Gross National Income and Net National Income",
    "tab1.6": "Table 1.6: Components of Gross Domestic Product at Current Prices",
    "tab3.6": "Table 3.6: Rupay cards & UPI Payments",
    "tab4.1": "Table 4.1: Index Numbers of Wholesale Prices",
    "tab4.3": "Table 4.3: All India Consumer Price Index Numbers",
    "tab5.1b": "Table 5.1B: Foreign Exchange Reserves (US$ million)",
    "tab5.4": "Table 5.4: Exchange Rate of Rupee vis-a-vis Selected Currencies of the World",
    "tab8.10": "Table 8.10: Labour Force Participation Rate (LFPR)",
    "tab8.11": "Table 8.11: Worker Population Ratio (WPR)",
    "tab8.12": "Table 8.12: Unemployment Rate (UR)",
}


def survey(table: str, locator: str, value: str, snippet: str) -> dict:
    """Evidence from one per-table PDF of the Statistical Appendix, keyed by its file stem."""
    return cite(MOF, f"{SURVEY_TITLE}, {SURVEY_TABLES[table]}", f"{SURVEY}/{table}.pdf", locator, value, "text", snippet, UNSTATED)


def entry(entry_id: str, title: str, domain: str, valid: tuple[str, str | None], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], tests: list[dict], notes: str, tags: list[str], use_cases: list[str], assumed: list[dict] | None = None, status: str = "license-review") -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "IN",
        "status": status,
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


def band(name: str, up_to: int | None, rate: int) -> dict:
    return {"name": name, "up_to": up_to, "rate_percent": rate}


def income(amount: int, tax: str, origin: str, note: str) -> dict:
    return {"input": {"income": amount}, "expected": tax, "origin": origin, "note": note}


def rate_tests(bands: list[dict]) -> list[dict]:
    return [{"statistic": "count", "expected": len(bands), "tolerance": 0}, *({"statistic": f"rate[{b['name']}]", "expected": b["rate_percent"], "tolerance": 0} for b in bands)]


SLAB_ASSUMPTION = {
    "parameter": "personal_allowance",
    "value": 0,
    "method": "derived",
    "rationale": "Indian slabs are stated on total income with a nil-rated first slab rather than a separate allowance, so the basic exemption is modelled as the 0% band and the allowance is zero.",
}


def new_regime() -> dict:
    bands = [band("nil", 400000, 0), band("slab_5", 800000, 5), band("slab_10", 1200000, 10), band("slab_15", 1600000, 15), band("slab_20", 2000000, 20), band("slab_25", 2400000, 25), band("slab_30", None, 30)]
    return entry(
        "in-income-tax-new-regime-slabs-2026-27",
        "India income tax slabs, default (new) regime under section 202 of the Income-tax Act, 2025, tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.income_tax_bands",
        {"tax_year": "2026-27", "regime": "default (section 202 of the Income-tax Act, 2025; section 115BAC(1A) of the Income-tax Act, 1961)", "currency": "INR", "personal_allowance": 0, "taper": None, "bands": bands},
        [
            income(800000, "20000.00", "source", "e-Filing table: ₹ 20,000 + 10% above ₹ 8,00,000"),
            income(1200000, "60000.00", "source", "e-Filing table: ₹ 60,000 + 15% above ₹ 12,00,000"),
            income(1600000, "120000.00", "source", "e-Filing table: ₹ 1,20,000 + 20% above ₹ 16,00,000"),
            income(2000000, "200000.00", "source", "e-Filing table: ₹ 2,00,000 + 25% above ₹ 20,00,000"),
            income(2400000, "300000.00", "source", "e-Filing table: ₹ 3,00,000 + 30% above ₹ 24,00,000"),
            income(400000, "0.00", "derived", "top of the nil slab"),
            income(3000000, "480000.00", "derived", "₹ 3,00,000 plus 30% of ₹ 6,00,000"),
        ],
        [
            memo("PDF page 9, 'Tax rates under Part I-B of the First Schedule applicable for the tax year 2026-27', table rows 1 to 4", "1. Upto ₹ 4,00,000 Nil", "2. From ₹ 4,00,001 to ₹ 8,00,000 5%"),
            memo("PDF page 9, same table, rows 5 to 7", "6. From ₹ 20,00,001 to ₹ 24,00,000 25%", "7. Above ₹ 24,00,000 30%"),
            memo("PDF page 8, paragraph 2 under 'Tax rates under section 202'", "rates specified in section 202 are the default rates", "unless an option is exercised as per provisions of section 202(4)"),
            bill("PDF page 11, clause 2 table of basic exemption amounts, row 4", "Rs. 4,00,000.", "Assessee whose income is chargeable to tax under section 115BAC(1A) of the said Act.", "supporting"),
            efiling("Tax rates table, cumulative tax at the top of each slab", "₹ 3,00,000 + 30% above", "₹ 2,00,000 + 25% above"),
        ],
        rate_tests(bands),
        "Slabs of the default regime for the tax year 1 April 2026 to 31 March 2027 as the Memorandum to the Finance Bill, 2026 "
        "restates them from section 202 of the Income-tax Act, 2025 (the same rates as section 115BAC(1A) of the 1961 Act for "
        "assessment year 2026-27): nil up to ₹4,00,000, then 5%, 10%, 15%, 20% and 25% on successive ₹4,00,000 slices and 30% above "
        "₹24,00,000. The Memorandum states no change from the enacted rates. The rule computes tax on total income only; the "
        "section 87A-style rebate, standard deduction, surcharge (see in-income-tax-surcharge-rates-2026-27) and the 4% Health and "
        "Education Cess are outside it. The e-Filing help page, whose bytes were identical on five fetches, supplies the cumulative "
        "amounts used as test vectors. The budget documents carry no licence statement.",
        INCOME_TAX_TAGS + ["new-regime"],
        INCOME_TAX_USE_CASES,
        [SLAB_ASSUMPTION],
    )


def old_regime() -> dict:
    bands = [band("nil", 250000, 0), band("slab_5", 500000, 5), band("slab_20", 1000000, 20), band("slab_30", None, 30)]
    return entry(
        "in-income-tax-old-regime-slabs-2026-27",
        "India income tax slabs, old regime for individuals below 60 (Paragraph A, Part I-B, First Schedule, Finance Bill 2026), tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.income_tax_bands",
        {"tax_year": "2026-27", "regime": "optional old regime, Paragraph A(I) of Part I-B of the First Schedule (option under section 202(4))", "applies_to": "individuals below sixty, HUF, AOP, BOI and artificial juridical persons", "currency": "INR", "personal_allowance": 0, "taper": None, "bands": bands},
        [
            income(500000, "12500.00", "source", "Finance Bill: ₹ 12500 plus 20% above ₹ 500000"),
            income(1000000, "112500.00", "source", "Finance Bill: ₹ 112500 plus 30% above ₹ 1000000"),
            income(250000, "0.00", "derived", "top of the nil slab"),
            income(1500000, "262500.00", "derived", "₹ 112500 plus 30% of ₹ 500000"),
        ],
        [
            bill("PDF page 119, First Schedule Part I-B Paragraph A item (I), rows (1) to (3)", "5% of the amount by which the total income exceeds ₹ 250000;", "where the total income exceeds ₹ 250000 but does not exceed ₹ 500000"),
            bill("PDF page 120, Paragraph A item (I), row (4)", "₹ 112500 plus 30% of the amount by which the total income exceeds ₹ 1000000.", "₹ 12500 plus 20% of the amount by which the total income exceeds ₹ 500000;"),
            memo("PDF page 9, paragraph 3(i), rates under Paragraph A of Part I-B", "(2) From ₹ 2,50,001 to ₹ 5,00,000 5%", "(3) From ₹ 5,00,001 to ₹ 10,00,000 20%"),
        ],
        rate_tests(bands),
        "Old-regime slabs for the tax year 2026-27 for every individual not covered by the senior-citizen paragraphs, Hindu undivided "
        "families, associations of persons, bodies of individuals and artificial juridical persons, from Paragraph A of Part I-B of "
        "the First Schedule to the Finance Bill, 2026: nil up to ₹2,50,000, 5% to ₹5,00,000, 20% to ₹10,00,000 and 30% above. The "
        "regime applies only when the taxpayer opts out of the default regime under section 202(4). The Bill's cumulative amounts "
        "(₹12,500 at ₹5,00,000 and ₹1,12,500 at ₹10,00,000) are the source test vectors. Surcharge and cess are separate entries. "
        "The Finance Bill PDF is cited by PDF page number; printed page numbers run eight lower.",
        INCOME_TAX_TAGS + ["old-regime"],
        INCOME_TAX_USE_CASES,
        [SLAB_ASSUMPTION],
    )


def senior_regime() -> dict:
    bands = [band("nil", 300000, 0), band("slab_5", 500000, 5), band("slab_20", 1000000, 20), band("slab_30", None, 30)]
    return entry(
        "in-income-tax-old-regime-senior-citizen-slabs-2026-27",
        "India income tax slabs, old regime for resident individuals aged 60 to 79 (Paragraph A(II), Part I-B, Finance Bill 2026), tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.income_tax_bands",
        {"tax_year": "2026-27", "regime": "optional old regime, Paragraph A(II) of Part I-B of the First Schedule", "applies_to": "resident individuals aged sixty or more but less than eighty at any time during the tax year", "currency": "INR", "personal_allowance": 0, "taper": None, "bands": bands},
        [
            income(500000, "10000.00", "source", "Finance Bill: ₹ 10000 plus 20% above ₹ 500000"),
            income(1000000, "110000.00", "source", "Finance Bill: ₹ 110000 plus 30% above ₹ 1000000"),
            income(300000, "0.00", "derived", "top of the nil slab"),
        ],
        [
            bill("PDF page 120, First Schedule Part I-B Paragraph A item (II)", "₹ 10000 plus 20% of the amount by which the total income exceeds ₹ 500000;", "who is of the age of sixty years or more but less than eighty years at any time during the tax year"),
            bill("PDF page 120, Paragraph A item (II), row (4)", "₹ 110000 plus 30% of the amount by which the total income exceeds ₹ 1000000.", "5% of the amount by which the total income exceeds ₹ 300000;"),
            memo("PDF page 10, paragraph 3(ii)", "(1) Upto ₹ 3,00,000 Nil", "(2) From ₹ 3,00,001 to Rs.5,00,000 5%"),
        ],
        rate_tests(bands),
        "Old-regime slabs for resident senior citizens (sixty to seventy-nine) for the tax year 2026-27: nil up to ₹3,00,000, 5% to "
        "₹5,00,000, 20% to ₹10,00,000 and 30% above, from Paragraph A(II) of Part I-B of the First Schedule to the Finance Bill, "
        "2026. Only the basic exemption differs from the general old-regime slabs. Non-residents use the general slabs regardless "
        "of age. Surcharge and cess are separate entries.",
        INCOME_TAX_TAGS + ["old-regime", "senior-citizen"],
        INCOME_TAX_USE_CASES + ["pensions"],
        [SLAB_ASSUMPTION],
    )


def super_senior_regime() -> dict:
    bands = [band("nil", 500000, 0), band("slab_20", 1000000, 20), band("slab_30", None, 30)]
    return entry(
        "in-income-tax-old-regime-super-senior-citizen-slabs-2026-27",
        "India income tax slabs, old regime for resident individuals aged 80 or more (Paragraph A(III), Part I-B, Finance Bill 2026), tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.income_tax_bands",
        {"tax_year": "2026-27", "regime": "optional old regime, Paragraph A(III) of Part I-B of the First Schedule", "applies_to": "resident individuals aged eighty or more at any time during the tax year", "currency": "INR", "personal_allowance": 0, "taper": None, "bands": bands},
        [
            income(1000000, "100000.00", "source", "Finance Bill: ₹ 100000 plus 30% above ₹ 1000000"),
            income(500000, "0.00", "derived", "top of the nil slab"),
            income(750000, "50000.00", "derived", "20% of ₹ 250000"),
        ],
        [
            bill("PDF page 120, First Schedule Part I-B Paragraph A item (III)", "₹ 100000 plus 30% of the amount by which the total income exceeds ₹ 1000000.", "who is of the age of eighty years or more at any time during the tax year"),
            memo("PDF page 10, paragraph 3(iii)", "(1) Upto ₹ 5,00,000 Nil", "(2) From ₹ 5,00,001 to Rs.10,00,000 20%"),
        ],
        rate_tests(bands),
        "Old-regime slabs for resident super senior citizens (eighty or more) for the tax year 2026-27: nil up to ₹5,00,000, 20% to "
        "₹10,00,000 and 30% above, from Paragraph A(III) of Part I-B of the First Schedule to the Finance Bill, 2026. Surcharge and "
        "cess are separate entries.",
        INCOME_TAX_TAGS + ["old-regime", "senior-citizen"],
        INCOME_TAX_USE_CASES + ["pensions"],
        [SLAB_ASSUMPTION],
    )


def surcharge() -> dict:
    rows = {
        "up_to_50_lakh": {"income_above": 0, "income_up_to": 5000000, "old_regime_percent": 0, "new_regime_percent": 0},
        "50_lakh_to_1_crore": {"income_above": 5000000, "income_up_to": 10000000, "old_regime_percent": 10, "new_regime_percent": 10},
        "1_crore_to_2_crore": {"income_above": 10000000, "income_up_to": 20000000, "old_regime_percent": 15, "new_regime_percent": 15},
        "2_crore_to_5_crore": {"income_above": 20000000, "income_up_to": 50000000, "old_regime_percent": 25, "new_regime_percent": 25},
        "above_5_crore": {"income_above": 50000000, "income_up_to": None, "old_regime_percent": 37, "new_regime_percent": 25},
    }
    return entry(
        "in-income-tax-surcharge-rates-2026-27",
        "India surcharge on income tax by total-income band for individuals, HUFs, AOPs and BOIs, old and new regimes, plus 4% cess, tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.lookup_table",
        {
            "tax_year": "2026-27",
            "currency": "INR",
            "basis": "percentage of income tax, by total income band",
            "dividend_and_capital_gains_surcharge_cap_percent": 15,
            "health_and_education_cess_percent": 4,
            "marginal_relief": True,
            "rows": rows,
        },
        [
            {"input": {"key": "50_lakh_to_1_crore", "column": "old_regime_percent"}, "expected": 10, "origin": "source"},
            {"input": {"key": "above_5_crore", "column": "old_regime_percent"}, "expected": 37, "origin": "source"},
            {"input": {"key": "above_5_crore", "column": "new_regime_percent"}, "expected": 25, "origin": "source", "note": "37% surcharge is not applicable under section 202; restricted to 25%"},
            {"input": {"key": "2_crore_to_5_crore", "column": "new_regime_percent"}, "expected": 25, "origin": "source"},
            {"input": "up_to_50_lakh", "expected": True, "origin": "source"},
        ],
        [
            bill("PDF page 122, First Schedule Part I-B Paragraph F, Table 1 row 1, clauses (i) and (ii)", "₹ 5000000 but does not exceed ₹ 10000000, at the rate of 10%;", "Paragraph F Surcharge on income-tax"),
            bill("PDF page 122, Paragraph F Table 1 row 1, clauses (iii) and (iv)", "₹ 50000000, at the rate of 37%;", "exceeds ₹ 20000000 but does not exceed ₹ 50000000, at the rate of 25%;"),
            bill("PDF page 123, Paragraph F Table 1 row 1, clause (vi)", "surcharge on the amount of income -tax computed in respect of that part of income shall not exceed 15%", "where the total income includes any dividend income or capital gains"),
            memo("PDF page 11, paragraph 4.3", "the surcharge shall be restricted to 25%.", "the surcharge at the rate 37% on the income or aggregate of income of such person"),
            memo("PDF page 13, 'Education Cess'", "4% on the amount of income -tax so computed, inclusive of surcharge", "No marginal relief shall be available in respect of such cess."),
        ],
        [
            {"statistic": "count", "expected": 5, "tolerance": 0},
            {"statistic": "value[above_5_crore,old_regime_percent]", "expected": 37, "tolerance": 0},
            {"statistic": "value[above_5_crore,new_regime_percent]", "expected": 25, "tolerance": 0},
            {"statistic": "max[new_regime_percent]", "expected": 25, "tolerance": 0},
        ],
        "Surcharge on the income tax of individuals, Hindu undivided families, associations of persons (other than those made up "
        "only of companies), bodies of individuals and artificial juridical persons for the tax year 2026-27, from Paragraph F of "
        "Part I-B of the First Schedule to the Finance Bill, 2026: 10% of tax where total income exceeds ₹50 lakh up to ₹1 crore, "
        "15% up to ₹2 crore, 25% up to ₹5 crore and 37% above ₹5 crore. Under the default regime of section 202 the 37% rate does "
        "not apply and the surcharge is capped at 25%, and in both regimes the surcharge on dividend income and capital gains under "
        "sections 196 to 198 is capped at 15%. Marginal relief applies at each threshold. The Health and Education Cess of 4% is "
        "charged on tax plus surcharge in all cases. Rows hold band boundaries in rupees; the bands are keyed in lakh and crore as "
        "the documents express them.",
        ["income-tax", "surcharge", "cess", "finance-bill-2026"],
        INCOME_TAX_USE_CASES,
        [{"parameter": "rows.up_to_50_lakh", "value": "0% in both regimes", "method": "derived", "rationale": "The Finance Bill lists surcharge only for incomes above ₹50 lakh; the nil row is added so a lookup covers every income, as the e-Filing table also shows 'Nil' for that band."}],
    )


def corporate() -> dict:
    rows = {
        "domestic_turnover_up_to_400_crore": {"rate_percent": 25, "condition": "total turnover or gross receipts in tax year 2024-25 not exceeding ₹400 crore, section 199 regime", "surcharge_1_to_10_crore_percent": 7, "surcharge_above_10_crore_percent": 12},
        "domestic_other": {"rate_percent": 30, "condition": "every other domestic company under Paragraph E of Part I-B", "surcharge_1_to_10_crore_percent": 7, "surcharge_above_10_crore_percent": 12},
        "domestic_section_200_option": {"rate_percent": 22, "condition": "optional concessional regime of section 200 of the Income-tax Act, 2025", "surcharge_1_to_10_crore_percent": 10, "surcharge_above_10_crore_percent": 10},
        "foreign_company": {"rate_percent": 35, "condition": "company other than a domestic company, income other than that chargeable at special rates", "surcharge_1_to_10_crore_percent": 2, "surcharge_above_10_crore_percent": 5},
    }
    return entry(
        "in-corporate-income-tax-rates-2026-27",
        "India corporate income tax rates and surcharge for domestic and foreign companies (Paragraphs E and F, Part I-B, Finance Bill 2026), tax year 2026-27",
        "tax",
        FY_2026_27,
        "almanac.rules.lookup_table",
        {"tax_year": "2026-27", "currency": "INR", "health_and_education_cess_percent": 4, "marginal_relief": True, "rows": rows},
        [
            {"input": {"key": "domestic_turnover_up_to_400_crore", "column": "rate_percent"}, "expected": 25, "origin": "source"},
            {"input": {"key": "domestic_other", "column": "rate_percent"}, "expected": 30, "origin": "source"},
            {"input": {"key": "domestic_section_200_option", "column": "rate_percent"}, "expected": 22, "origin": "source"},
            {"input": {"key": "foreign_company", "column": "rate_percent"}, "expected": 35, "origin": "source"},
            {"input": {"key": "foreign_company", "column": "surcharge_above_10_crore_percent"}, "expected": 5, "origin": "source"},
            {"input": {"key": "domestic_other", "column": "surcharge_1_to_10_crore_percent"}, "expected": 7, "origin": "source"},
        ],
        [
            bill("PDF page 121, First Schedule Part I-B Paragraph E item I (domestic company)", "25% of the total income;", "where its total turnover or the gross receipt in the tax year 2024-25 does not exceed ₹ 400 crores;"),
            memo("PDF page 12, section E 'Companies', paragraphs 1 and 2", "shall be 35% of the total income, on income other than income chargeable at special rates.", "The rate of income -tax rate is 22% in section 200. Surcharge would be at 10% on such tax."),
            memo("PDF page 12, section E paragraphs 3 and 4 (surcharge)", "Surcharge at the rate of 7% shall continue to be levied in case of a domestic company", "Surcharge at the rate of 5% shall continue to be levied, if the total income of the company other than domestic company"),
            bill("PDF page 123, Paragraph F Table 1 rows 5 and 6", "5. Every domestic company.", "6. Every company, other than a domestic company."),
            bill("PDF page 123, Paragraph F Table 1 row 6 clause (i)", "100000000, at the rate of 2%;", "100000000, at the rate of 5%."),
        ],
        [
            {"statistic": "count", "expected": 4, "tolerance": 0},
            {"statistic": "value[domestic_turnover_up_to_400_crore,rate_percent]", "expected": 25, "tolerance": 0},
            {"statistic": "value[domestic_section_200_option,surcharge_above_10_crore_percent]", "expected": 10, "tolerance": 0},
            {"statistic": "max[rate_percent]", "expected": 35, "tolerance": 0},
        ],
        "Company income tax rates for the tax year 2026-27 from Paragraph E of Part I-B of the First Schedule to the Finance Bill, "
        "2026, as explained in the Memorandum: a domestic company pays 25% where its turnover or gross receipts in tax year 2024-25 "
        "did not exceed ₹400 crore and 30% otherwise, or may opt for 22% under section 200 of the Income-tax Act, 2025 with a 10% "
        "surcharge; a company other than a domestic company pays 35% on income not chargeable at special rates. Surcharge under "
        "Paragraph F is 7% (total income above ₹1 crore up to ₹10 crore) and 12% (above ₹10 crore) for domestic companies outside "
        "the optional regimes, and 2% and 5% for other companies, with marginal relief; the 4% Health and Education Cess applies on "
        "tax plus surcharge. The Memorandum records no change from the previous year. Section 201's regime for new manufacturing "
        "companies is not tabulated in these documents and is omitted.",
        ["corporate-tax", "income-tax", "surcharge", "finance-bill-2026"],
        ["company-generation", "financial-reporting", "tax-filing-demo", "kyb-onboarding"],
    )


def tcs() -> dict:
    rows = {
        "alcoholic_liquor_for_human_consumption": {"current_rate_percent": 1, "proposed_rate_percent": 2, "threshold": None},
        "tendu_leaves": {"current_rate_percent": 5, "proposed_rate_percent": 2, "threshold": None},
        "scrap": {"current_rate_percent": 1, "proposed_rate_percent": 2, "threshold": None},
        "minerals_coal_lignite_iron_ore": {"current_rate_percent": 1, "proposed_rate_percent": 2, "threshold": None},
        "lrs_remittance_education_or_medical": {"current_rate_percent": 5, "proposed_rate_percent": 2, "threshold": "amount or aggregate exceeding ten lakh rupees"},
        "lrs_remittance_other_purposes": {"current_rate_percent": 20, "proposed_rate_percent": 20, "threshold": "amount or aggregate exceeding ten lakh rupees"},
        "overseas_tour_programme_package": {"current_rate_percent": "5 up to ten lakh rupees, 20 above", "proposed_rate_percent": 2, "threshold": "none after the amendment"},
    }
    return entry(
        "in-tcs-rates-rationalised-finance-bill-2026",
        "India TCS rates under section 394(1) of the Income-tax Act, 2025 before and after the Finance Bill 2026 rationalisation, from 1 April 2026",
        "tax",
        ("2026-04-01", None),
        "almanac.rules.lookup_table",
        {"section": "394(1) of the Income-tax Act, 2025", "effective_from": "2026-04-01", "rows": rows},
        [
            {"input": {"key": "alcoholic_liquor_for_human_consumption", "column": "proposed_rate_percent"}, "expected": 2, "origin": "source"},
            {"input": {"key": "tendu_leaves", "column": "current_rate_percent"}, "expected": 5, "origin": "source"},
            {"input": {"key": "lrs_remittance_other_purposes", "column": "proposed_rate_percent"}, "expected": 20, "origin": "source"},
            {"input": {"key": "overseas_tour_programme_package", "column": "proposed_rate_percent"}, "expected": 2, "origin": "source"},
            {"input": "sale_of_motor_vehicle", "expected": False, "origin": "derived", "note": "only the rows the Memorandum tabulates are included"},
        ],
        [
            memo("PDF page 50, 'Rationalisation of TCS rates', paragraph 9 table rows 1 and 2", "1. Sale of alcoholic liquor for human consumption. 1%. 2%.", "2. Sale of tendu leaves. 5%. 2%."),
            memo("PDF page 51, table rows 3 to 5", "(a) 2% for purposes of education or medical treatment;", "(b) 20% for purposes other than education or medical treatment."),
            memo("PDF page 51, table row 6 and paragraph 9 (commencement)", "The amendment will take effect from the 1st day of April, 2026.", "[Clause 73]"),
            memo("PDF page 50, paragraph 8 (overseas tour programme package)", "TCS on sale of overseas tour programme package be collected at 2% irrespective of the amount", "It is further proposed that threshold for applicability of the provision be removed"),
        ],
        [
            {"statistic": "count", "expected": 7, "tolerance": 0},
            {"statistic": "value[scrap,proposed_rate_percent]", "expected": 2, "tolerance": 0},
            {"statistic": "value[lrs_remittance_education_or_medical,current_rate_percent]", "expected": 5, "tolerance": 0},
        ],
        "The TCS rates the Memorandum to the Finance Bill, 2026 tabulates for section 394(1) of the Income-tax Act, 2025, before and "
        "after the rationalisation proposed with effect from 1 April 2026: liquor, scrap and coal, lignite or iron ore move from 1% "
        "to 2%; tendu leaves from 5% to 2%; Liberalised Remittance Scheme remittances above ten lakh rupees for education or medical "
        "treatment from 5% to 2% while other purposes stay at 20%; and overseas tour programme packages move from 5% up to ten lakh "
        "rupees and 20% above to a flat 2% with no threshold. The rows cover only the receipts the Memorandum tabulates, not the whole "
        "TCS schedule. The Memorandum describes the Bill as introduced; whether the Finance Act, 2026 enacted these rates unchanged "
        "is not confirmed by these documents.",
        ["tcs", "withholding", "finance-bill-2026"],
        ["tax-filing-demo", "payments-demo", "accounts-payable", "retail-demo"],
    )


def budget_glance() -> dict:
    def line(actuals: int, be25: int, re25: int, be26: int, pct: float | None = None) -> dict:
        row = {"actuals_2024_25": actuals, "be_2025_26": be25, "re_2025_26": re25, "be_2026_27": be26}
        if pct is not None:
            row["percent_of_gdp_be_2026_27"] = pct
        return row

    rows = {
        "revenue_receipts": line(3036619, 3420409, 3342323, 3533150),
        "tax_revenue_net_to_centre": line(2500039, 2837409, 2674661, 2866922),
        "non_tax_revenue": line(536580, 583000, 667662, 666228),
        "capital_receipts": line(1616249, 1644936, 1622519, 1814165),
        "recovery_of_loans": line(24617, 29000, 30190, 38397),
        "other_receipts": line(17202, 47000, 33837, 80000),
        "borrowings_and_other_liabilities": line(1574431, 1568936, 1558492, 1695768),
        "total_receipts": line(4652867, 5065345, 4964842, 5347315),
        "total_expenditure": line(4652867, 5065345, 4964842, 5347315),
        "revenue_expenditure": line(3600914, 3944255, 3869087, 4125494),
        "interest_payments": line(1115575, 1276338, 1274338, 1403972),
        "grants_in_aid_for_capital_assets": line(272656, 427192, 308151, 492702),
        "capital_expenditure": line(1051953, 1121090, 1095755, 1221821),
        "effective_capital_expenditure": line(1324609, 1548282, 1403906, 1714523),
        "revenue_deficit": line(564296, 523846, 526764, 592344, 1.5),
        "effective_revenue_deficit": line(291640, 96654, 218613, 99642, 0.3),
        "fiscal_deficit": line(1574431, 1568936, 1558492, 1695768, 4.3),
        "primary_deficit": line(458856, 292598, 284154, 291796, 0.7),
    }
    return entry(
        "in-union-budget-2026-27-at-a-glance",
        "India Union Budget 2026-27 at a glance: Central Government receipts, expenditure and deficits in INR crore (Actuals 2024-25 to BE 2026-27)",
        "economy",
        FY_2026_27,
        "almanac.rules.lookup_table",
        {"unit": "INR crore", "gdp_estimate_2026_27_crore": 39300393, "gdp_advance_estimate_2025_26_crore": 35713886, "rows": rows},
        [
            {"input": {"key": "fiscal_deficit", "column": "be_2026_27"}, "expected": 1695768, "origin": "source"},
            {"input": {"key": "fiscal_deficit", "column": "percent_of_gdp_be_2026_27"}, "expected": 4.3, "origin": "source"},
            {"input": {"key": "total_expenditure", "column": "be_2026_27"}, "expected": 5347315, "origin": "source"},
            {"input": {"key": "revenue_receipts", "column": "actuals_2024_25"}, "expected": 3036619, "origin": "source"},
            {"input": {"key": "capital_expenditure", "column": "re_2025_26"}, "expected": 1095755, "origin": "source"},
            {"input": "plan_expenditure", "expected": False, "origin": "derived", "note": "not a line of the table"},
        ],
        [
            cite(MOF, "Budget at a Glance 2026-2027, summary table (bag1.pdf)", BAG1_URL, "PDF page 3, table rows 1 and 8", "1. Revenue Receipts 3036619 3420409 3342323 3533150", "text", "8. Total Receipts (1+4) 4652867 5065345 4964842 5347315", UNSTATED),
            cite(MOF, "Budget at a Glance 2026-2027, summary table (bag1.pdf)", BAG1_URL, "PDF page 3, rows 9 to 14", "13. On Capital Account 1051953 1121090 1095755 1221821", "text", "11. Interest Payments 1115575 1276338 1274338 1403972", UNSTATED),
            cite(MOF, "Budget at a Glance 2026-2027, summary table (bag1.pdf)", BAG1_URL, "PDF page 3, note (i)", "The GDP for FY 2026 -27 is estimated at ₹393,00,393 crore", "text", "which is 10% over the Advance Estimates for FY 2025 -26 of ₹357,13,886 crore released by NSO.", UNSTATED),
            cite(MOF, "Budget at a Glance 2026-2027, deficit statistics (bag2.pdf)", BAG2_URL, "PDF page 1, 'Deficit Statistics' rows 1 to 4 with percentages of GDP in parentheses", "1. Fiscal Deficit 1574431 1568936 1558492 1695768", "text", "4. Primary Deficit 458856 292598 284154 291796", UNSTATED),
            cite(MOF, "Budget at a Glance 2026-2027, deficit statistics (bag2.pdf)", BAG2_URL, "PDF page 1, percentages of GDP under the Fiscal Deficit row", "(4.8) (4.4) (4.4) (4.3)", "text", "Figures in parentheses are as a percentage of GDP", UNSTATED),
            cite(MOF, "Budget at a Glance 2026-2027, summary table (bag1.pdf)", BAG1_URL, "PDF page 2, paragraph 5", "The total expenditure in Budget Estimates (BE) 2026 -27 is estimated at ₹53,47,315 crore", "text", "effective capital expenditure is ₹17,14,523 crore", UNSTATED, "supporting"),
        ],
        [
            {"statistic": "count", "expected": 18, "tolerance": 0},
            {"statistic": "value[total_receipts,be_2026_27]", "expected": 5347315, "tolerance": 0},
            {"statistic": "value[primary_deficit,percent_of_gdp_be_2026_27]", "expected": 0.7, "tolerance": 0},
            {"statistic": "max[be_2026_27]", "expected": 5347315, "tolerance": 0},
        ],
        "Headline aggregates of the Union Budget 2026-27 from the Ministry of Finance's Budget at a Glance: each row is a line of "
        "the summary table in ₹ crore with Actuals 2024-25, Budget Estimates 2025-26, Revised Estimates 2025-26 and Budget "
        "Estimates 2026-27; deficit rows also carry the BE 2026-27 share of GDP from the parentheses. The GDP used for the ratios "
        "is ₹3,93,00,393 crore for 2026-27, 10% over the NSO advance estimate of ₹3,57,13,886 crore for 2025-26. Total receipts "
        "equal total expenditure because borrowings and other liabilities are counted as receipts; the fiscal deficit is "
        "expenditure less receipts excluding borrowings. RE 2025-26 is adjusted by ₹9,084 crore for amounts receivable from States. "
        "Figures are net of States' share of taxes. The document carries no licence statement.",
        ["fiscal", "budget", "public-finance", "macro"],
        ["financial-planning", "market-sizing", "financial-reporting"],
    )


def gst_penalties() -> dict:
    rows = {
        "prosecution_threshold_section_132": {"previous_inr": 10000000, "recommended_inr": 50000000, "basis": "tax evaded; arrest provisions in section 69 to be omitted"},
        "general_penalty_maximum_section_125": {"previous_inr": 25000, "recommended_inr": 10000, "basis": "maximum general penalty"},
        "show_cause_notice_minimum_tax": {"previous_inr": None, "recommended_inr": 10000, "basis": "CGST + SGST + IGST + cess aggregated, sections 73, 74 and 74A; interest, late fee and penalty excluded"},
        "reduced_penalty_non_fraud_percent": {"previous_inr": None, "recommended_inr": None, "percent": 5, "basis": "tax plus interest paid within 30 days (section 73) or 60 days (section 74A) of the adjudication order"},
        "minimum_penalty_non_fraud": {"previous_inr": 10000, "recommended_inr": None, "basis": "condition of a minimum penalty removed in non-fraud cases"},
        "pre_deposit_cap_penalty_only_appeals": {"previous_inr": None, "recommended_inr": 400000000, "basis": "₹20 crore CGST plus ₹20 crore SGST/UTGST, sections 107(6) and 112(8), orders involving penalty only"},
        "refund_minimum_amount_section_54_14": {"previous_inr": 1000, "recommended_inr": 1000, "basis": "applied to the total refund across CGST, SGST/UTGST and IGST together; not applied to exports with payment of tax"},
        "imprisonment_maximum_above_10_crore_years": {"previous_inr": None, "recommended_inr": None, "years": 5, "basis": "imprisonment or fine or both; minimum six months removed"},
        "imprisonment_maximum_5_to_10_crore_years": {"previous_inr": None, "recommended_inr": None, "years": 2, "basis": "imprisonment or fine or both"},
    }
    return entry(
        "in-gst-penalty-and-prosecution-thresholds-57th-council",
        "India GST prosecution, show cause notice, penalty, pre-deposit and refund thresholds recommended by the 57th GST Council meeting, 8 October 2026",
        "tax",
        ("2026-10-08", None),
        "almanac.rules.lookup_table",
        {"meeting": "57th GST Council, New Delhi, 8 October 2026", "currency": "INR", "legal_status": "Council recommendations; amendments to the CGST Act, 2017 and Rules are required before they take effect", "rows": rows},
        [
            {"input": {"key": "prosecution_threshold_section_132", "column": "recommended_inr"}, "expected": 50000000, "origin": "source"},
            {"input": {"key": "prosecution_threshold_section_132", "column": "previous_inr"}, "expected": 10000000, "origin": "source"},
            {"input": {"key": "general_penalty_maximum_section_125", "column": "recommended_inr"}, "expected": 10000, "origin": "source"},
            {"input": {"key": "show_cause_notice_minimum_tax", "column": "recommended_inr"}, "expected": 10000, "origin": "source"},
            {"input": {"key": "pre_deposit_cap_penalty_only_appeals", "column": "recommended_inr"}, "expected": 400000000, "origin": "source"},
            {"input": {"key": "imprisonment_maximum_above_10_crore_years", "column": "years"}, "expected": 5, "origin": "source"},
        ],
        [
            press("PDF page 1, headline bullets", "GST Council recommends raising prosecution threshold from ₹ 1 crore to ₹ 5 crore", "GST Council recommends reduction in general penalty from ₹ 25,000 to ₹ 10,000"),
            press("PDF page 1, dateline", "Posted On: 08 OCT 2026 7:03PM by PIB Delhi", "Meeting of the GST Council was held today in New Delhi"),
            press("PDF page 7, paragraph 7.2 item 1", "minimum threshold of Rs. 10,000/- (CGST + SGST + IGST + Cess) for issuance of show cause notices", "no notices will be issued if the tax amount involved is less than Rs. 10,000/-"),
            press("PDF page 8, paragraph 7.2 items 3 and 4", "reduced penalty of 5% in non-fraud cases", "removal of condition of minimum penalty of Rs. 10,000/-, in non-fraud cases."),
            press("PDF page 8, paragraphs 7.3 and 7.4", "under section 125 of the CGST Act, 2017 from Rs. 25,000/- to Rs. 10,000/-.", "upper limit of ₹ 40 crore (Rs. 20 crore under CGST and Rs. 20 crore under SGST/UTGST)"),
            press("PDF page 7, paragraph 6.2 item 3", "the threshold of Rs. 1000 shall be applicable in respect of total refund amount", "Amendment in section 54(14) of the CGST Act, 2017"),
            faq("PDF page 29, questions 13 to 15 (arrest and prosecution)", "exceeds Rs. 5 crore, as against the present threshold of Rs. 1 crore.", "Prosecution may be launched for offences under section 132(1) where the evaded tax amount"),
            faq("PDF page 30, question 17 (punishment on conviction)", "imprisonment up to five years, or fine, or both;", "where the amount involved exceeds Rs. 5 crore but does not exceed Rs. 10 crore: imprisonment up to two years"),
            faq("PDF page 25, questions 1 to 3 (minimum threshold for show cause notices)", "Interest, late fee and penalty shall not be included for determining whether the threshold is met.", "The minimum threshold of ₹10,000 shall be determined with reference to the aggregate amount of tax involved"),
        ],
        [
            {"statistic": "count", "expected": 9, "tolerance": 0},
            {"statistic": "value[general_penalty_maximum_section_125,previous_inr]", "expected": 25000, "tolerance": 0},
            {"statistic": "value[reduced_penalty_non_fraud_percent,percent]", "expected": 5, "tolerance": 0},
            {"statistic": "max[recommended_inr]", "expected": 400000000, "tolerance": 0},
        ],
        "Monetary thresholds the 57th GST Council meeting of 8 October 2026 recommended for the CGST Act, 2017, from the Council "
        "Secretariat's copy of the Ministry of Finance press release and its FAQ: prosecution only where tax evaded exceeds ₹5 crore "
        "(previously ₹1 crore) with arrest provisions removed and maximum imprisonment of five years above ₹10 crore and two years "
        "between ₹5 crore and ₹10 crore; a minimum of ₹10,000 of tax (all heads together) before a show cause notice under "
        "sections 73, 74 or 74A; the maximum general penalty under section 125 cut from ₹25,000 to ₹10,000; a 5% reduced penalty in "
        "non-fraud cases paid within 30 or 60 days of the order with the ₹10,000 minimum penalty removed; a ₹40 crore cap on "
        "pre-deposits for penalty-only appeals; and the ₹1,000 refund floor applied to the combined refund. valid_from is the "
        "meeting date; these are recommendations that take legal effect only through amending legislation and notifications, "
        "which the press release says will follow, so the entry should be re-dated when they are enacted. The Council's copyright "
        "policy permits reproduction after permission by email, hence license-review.",
        ["gst", "penalties", "prosecution", "thresholds", "gst-council-57"],
        ["invoicing", "audit-demo", "tax-filing-demo"],
        [{"parameter": "valid_from", "value": "2026-10-08", "method": "derived", "rationale": "The date of the Council meeting from the press release dateline; the recommendations require legislative amendment and are not yet in force on that date."}],
    )


def gst_compliance() -> dict:
    rows = {
        "rule_14a_automatic_registration_itc_pass_through_limit": {"amount_inr": 250000, "period": "per month", "scope": "applicant not intending to pass on ITC above the limit; automatic registration without officer intervention"},
        "rule_14b_eco_small_seller_output_tax_limit": {"amount_inr": 250000, "period": "per month", "scope": "simplified registration for sellers supplying goods only through e-commerce operators, declaring the ECO warehouse as principal place of business; stock transfers excluded"},
        "automatic_cancellation_phase_1_itc_limit": {"amount_inr": 250000, "period": "per month", "scope": "cancellation applications in FORM GST REG-16 accepted automatically where ITC passed on never exceeded the limit"},
        "late_fee_waiver_annual_turnover_limit": {"amount_inr": 50000000, "period": "preceding financial year", "scope": "late fee on a section 39(1) return waived if filed by the end of the month in which it was due"},
        "arqp_scheme_aggregate_turnover_limit": {"amount_inr": 50000000, "period": "preceding financial year", "scope": "optional Annual Return Quarterly Payment scheme for taxpayers supplying only unregistered persons (B2C); approved in principle"},
        "e_invoicing_rcm_and_import_of_services_turnover_threshold": {"amount_inr": 50000000, "period": "aggregate annual turnover", "scope": "e-invoicing extended to supplies from unregistered persons under reverse charge and to imports of services for taxpayers at or above the threshold"},
        "zero_rated_goods_turnover_cap_multiple": {"amount_inr": None, "multiple": 1.5, "period": "refund period", "scope": "rule 89(4)(C) restriction of zero-rated goods turnover to 1.5 times the domestic value of like goods is removed"},
    }
    return entry(
        "in-gst-registration-and-compliance-thresholds-57th-council",
        "India GST registration, late-fee, ARQP and e-invoicing turnover thresholds recommended by the 57th GST Council meeting, 8 October 2026",
        "tax",
        ("2026-10-08", None),
        "almanac.rules.lookup_table",
        {"meeting": "57th GST Council, New Delhi, 8 October 2026", "currency": "INR", "legal_status": "Council recommendations; amendments to the CGST Act, 2017 and Rules are required before they take effect", "rows": rows},
        [
            {"input": {"key": "rule_14b_eco_small_seller_output_tax_limit", "column": "amount_inr"}, "expected": 250000, "origin": "source"},
            {"input": {"key": "rule_14a_automatic_registration_itc_pass_through_limit", "column": "amount_inr"}, "expected": 250000, "origin": "source"},
            {"input": {"key": "late_fee_waiver_annual_turnover_limit", "column": "amount_inr"}, "expected": 50000000, "origin": "source"},
            {"input": {"key": "e_invoicing_rcm_and_import_of_services_turnover_threshold", "column": "amount_inr"}, "expected": 50000000, "origin": "source"},
            {"input": {"key": "zero_rated_goods_turnover_cap_multiple", "column": "multiple"}, "expected": 1.5, "origin": "source"},
            {"input": "composition_scheme_turnover_limit", "expected": False, "origin": "derived", "note": "the 57th meeting did not change the composition or registration thresholds of sections 10 and 22"},
        ],
        [
            press("PDF page 3, paragraph 1.1 (rule 14A automatic registration)", "ITC more than ₹ 2.5 lakh per month", "automatic registrations, without officer intervention, are being granted by the portal under rule 14A"),
            press("PDF page 4, paragraph 4.1 (rule 14B simplified registration for ECO sellers)", "they intend to pass on ITC not more than ₹ 2.5 lakh per month, excluding stock", "recommended insertion of rule 14B in the CGST Rules, 2017"),
            press("PDF page 4, paragraph 3.1.1 Phase 1 (automatic cancellation)", "where the taxpayer has not passed on ITC exceeding ₹ 2.5 lakh in any of the months since registration", "accepted automatically by the system, once all pending returns are filed and all dues are paid"),
            press("PDF page 11, paragraph 15 (late fee relief)", "for taxpayers with an annual turnover up to Rs. 5 crore in the preceding financial year", "waiver of late fee on delayed filing of return under section 39(1)"),
            press("PDF page 11, paragraph 17 (ARQP concept note)", "equal to or less than Rs. 5 Crore in the preceding financial year", "optional Annual Return Quarterly Payment (ARQP) scheme"),
            press("PDF page 11, paragraph 18 item 4 (e-invoicing)", "for taxpayers having aggregate annual turnover of Rs. 5 crore and above.", "extending e-invoicing to domestic supplies received from an unregistered person where the tax is payable under reverse charge mechanism"),
            press("PDF page 7, paragraph 6.2 item 2 (rule 89(4)(C))", "as 1.5 times the value of like goods domestically supplied.", "Amendment in rule 89(4)(C) of the CGST Rules, 2017"),
            faq("PDF page 8, 'FAQ on Simplified Registration Schemes for ECO Sellers', question 2", "must not exceed Rs. 2.5 lakh per month.", "The total output tax liability comprising Central tax, State or Union territory tax and integrated tax"),
        ],
        [
            {"statistic": "count", "expected": 7, "tolerance": 0},
            {"statistic": "value[arqp_scheme_aggregate_turnover_limit,amount_inr]", "expected": 50000000, "tolerance": 0},
            {"statistic": "max[amount_inr]", "expected": 50000000, "tolerance": 0},
            {"statistic": "min[amount_inr]", "expected": 250000, "tolerance": 0},
        ],
        "Turnover and tax-liability thresholds in the process reforms the 57th GST Council meeting of 8 October 2026 recommended: "
        "the ₹2.5 lakh per month input tax credit pass-through limit that defines automatic registration under rule 14A, the "
        "proposed rule 14B simplified registration for small sellers on e-commerce platforms (ITC passed on, or output tax liability "
        "to registered persons, not above ₹2.5 lakh a month), Phase 1 automatic cancellation of registration, late-fee waiver and "
        "the in-principle Annual Return Quarterly Payment scheme for turnover up to ₹5 crore, extension of e-invoicing to reverse "
        "charge supplies and imports of services for turnover of ₹5 crore and above, and removal of the 1.5 times cap on zero-rated "
        "goods turnover in refund computations. The meeting changed no GST rate slab (the 56th meeting's structure in "
        "in-gst-rate-structure stands) and did not revise the registration or composition thresholds of sections 22 and 10, which "
        "these documents do not state. valid_from is the meeting date; the measures take effect through later amendments and "
        "notifications. The Council's copyright policy permits reproduction after permission by email, hence license-review.",
        ["gst", "registration", "e-invoicing", "thresholds", "gst-council-57"],
        ["invoicing", "kyb-onboarding", "company-generation", "tax-filing-demo"],
        [{"parameter": "valid_from", "value": "2026-10-08", "method": "derived", "rationale": "The date of the Council meeting from the press release dateline; the recommendations require amendment of the CGST Act and Rules and are not yet in force on that date."}],
    )


def national_income() -> dict:
    rows = {
        "2023-24": {"estimate": "1st RE", "gni_current_crore": 29710786, "gni_constant_crore": 17404638, "nni_current_crore": 26350374, "nni_constant_crore": 15175671, "per_capita_nni_current_inr": 188892, "per_capita_nni_constant_inr": 108786, "gdp_current_crore": 30122956},
        "2024-25": {"estimate": "PE", "gni_current_crore": 32589848, "gni_constant_crore": 18523133, "nni_current_crore": 28909595, "nni_constant_crore": 16151199, "per_capita_nni_current_inr": 205324, "per_capita_nni_constant_inr": 114710, "gdp_current_crore": 33068145},
        "2025-26": {"estimate": "1st AE", "gni_current_crore": 35158997, "gni_constant_crore": 19873388, "nni_current_crore": 31193630, "nni_constant_crore": 17327240, "per_capita_nni_current_inr": 219575, "per_capita_nni_constant_inr": 121968, "gdp_current_crore": 35713886},
    }
    return entry(
        "in-national-income-2023-24-to-2025-26",
        "India gross and net national income, per capita NNI and GDP at current and constant prices, 2023-24 to 2025-26 (Economic Survey 2025-26)",
        "economy",
        ("2025-04-01", "2026-03-31"),
        "almanac.rules.lookup_table",
        {"series": "2011-12", "unit": "INR crore except per capita in INR", "constant_price_base": "2011-12", "rows": rows},
        [
            {"input": {"key": "2025-26", "column": "per_capita_nni_current_inr"}, "expected": 219575, "origin": "source"},
            {"input": {"key": "2024-25", "column": "gni_current_crore"}, "expected": 32589848, "origin": "source"},
            {"input": {"key": "2025-26", "column": "gdp_current_crore"}, "expected": 35713886, "origin": "source"},
            {"input": {"key": "2023-24", "column": "nni_constant_crore"}, "expected": 15175671, "origin": "source"},
            {"input": "2026-27", "expected": False, "origin": "derived", "note": "no estimate published in the appendix"},
        ],
        [
            survey("tab1.1", "PDF page 3, row '2025-26 (1st AE)', columns 2 to 7", "2025-26 (1st AE) 35158997 19873388 31193630 17327240 219575 121968", "Per capita net national income"),
            survey("tab1.1", "PDF page 3, rows '2023-24 (1st RE)' and '2024-25 (PE)'", "2024-25 (PE) 32589848 18523133 28909595 16151199 205324 114710", "2023-24 (1st RE) 29710786 17404638 26350374 15175671 188892 108786"),
            survey("tab1.6", "PDF page 3, rows for 2023-24 to 2025-26, column 10 (GDP)", "2025-26 (1st AE) 21963865 3519836 10711183 516698 576105 7662052 8468883 -766970 35713886", "2024-25 (PE) 20298413 3303119 9886129 497181 500785 6997830 7766863 -648448 33068145"),
        ],
        [
            {"statistic": "count", "expected": 3, "tolerance": 0},
            {"statistic": "value[2025-26,gni_current_crore]", "expected": 35158997, "tolerance": 0},
            {"statistic": "max[per_capita_nni_current_inr]", "expected": 219575, "tolerance": 0},
        ],
        "National income aggregates from Tables 1.1 and 1.6 of the Statistical Appendix to the Economic Survey 2025-26, compiled "
        "by the Ministry of Finance from National Statistical Office estimates in the 2011-12 series: gross and net national income "
        "at current and constant prices, per capita net national income, and GDP at current market prices for 2023-24 (first revised "
        "estimate), 2024-25 (provisional estimate) and 2025-26 (first advance estimate). The validity window is the latest fiscal year "
        "covered. The Survey documents carry no licence statement.",
        ["macro", "national-accounts", "gdp", "economic-survey"],
        ["market-sizing", "financial-planning", "customer-segmentation"],
    )


def price_indices() -> dict:
    def row(cpi_iw: int | None, rural: int, urban: int, combined: int, al: int | None, rl: int | None, wpi: int, note: str) -> dict:
        return {"cpi_iw": cpi_iw, "cpi_ns_rural": rural, "cpi_ns_urban": urban, "cpi_ns_combined": combined, "cpi_al": al, "cpi_rl": rl, "wpi_all_commodities": wpi, "note": note}

    rows = {
        "2022-23": row(131, 176, 174, 175, 1148, 1160, 153, "average of months"),
        "2023-24": row(138, 186, 182, 184, 1229, 1240, 151, "average of months"),
        "2024-25": row(143, 195, 190, 193, 1302, 1311, 155, "average of months"),
        "2025-04": row(144, 194, 191, 193, 1307, 1320, 154, "month"),
        "2025-05": row(144, 194, 192, 193, 1305, 1319, 154, "month"),
        "2025-06": row(145, 196, 193, 194, 134, 134, 154, "month; CPI-AL and CPI-RL on the 2019=100 base from June 2025"),
        "2025-07": row(147, 198, 194, 196, 135, 136, 154, "month"),
        "2025-08": row(147, 199, 195, 197, 136, 137, 155, "month"),
        "2025-09": row(147, 199, 195, 197, 136, 136, 155, "month"),
        "2025-10": row(148, 199, 195, 197, 136, 137, 155, "month"),
        "2025-11": row(148, 200, 196, 198, 137, 137, 156, "month, provisional"),
        "2025-12": row(None, 200, 196, 198, None, None, 157, "month, provisional; CPI-IW, CPI-AL and CPI-RL not yet published"),
    }
    return entry(
        "in-consumer-and-wholesale-price-indices-2025-26",
        "India consumer price indices (IW, new series, AL, RL) and wholesale price index, annual 2022-23 to 2024-25 and monthly April to December 2025",
        "economy",
        ("2025-04-01", "2025-12-31"),
        "almanac.rules.lookup_table",
        {
            "bases": {"cpi_iw": "2016=100", "cpi_ns": "2012=100", "cpi_al_and_rl": "1986-87=100 to May 2025, 2019=100 from June 2025", "wpi": "2011-12=100"},
            "linking_factors": {"cpi_iw_2016_to_2001": 2.88, "cpi_al_2019_to_1986_87": 9.69, "cpi_rl_2019_to_1986_87": 9.78},
            "rows": rows,
        },
        [
            {"input": {"key": "2024-25", "column": "cpi_ns_combined"}, "expected": 193, "origin": "source"},
            {"input": {"key": "2025-11", "column": "cpi_ns_combined"}, "expected": 198, "origin": "source"},
            {"input": {"key": "2025-12", "column": "wpi_all_commodities"}, "expected": 157, "origin": "source"},
            {"input": {"key": "2024-25", "column": "wpi_all_commodities"}, "expected": 155, "origin": "source"},
            {"input": {"key": "2025-06", "column": "cpi_al"}, "expected": 134, "origin": "source", "note": "first month on the 2019=100 base"},
            {"input": "2026-01", "expected": False, "origin": "derived", "note": "beyond the appendix"},
        ],
        [
            survey("tab4.3", "PDF page 1, 'Average of Months', row 2024-25 (columns 1 to 7)", "2024-25 143 195 190 193 1302 1311", "Average of Months"),
            survey("tab4.3", "PDF page 2, 2025-26 monthly rows", "November(P) 148 200 196 198 137 137", "CPI-AL/RL New Series with base 2019=100 was introduced w.e.f. June 2025."),
            survey("tab4.3", "PDF page 2, notes 5, 8 and 9 (linking factors)", "The linking factor of CPI-IW between New Series (base 2016=100) & Old Series (base 2001=100) is 2.88.", "Old Series (base 1986-87=100) is 9.69."),
            survey("tab4.1", "PDF page 2, 'Average of months' row 2024-25, column 14 (All Commodities)", "2024-25 193 205 210 162 229 150 143 172 136 136 140 131 155", "Average of months (2011-12 = 100)"),
            survey("tab4.1", "PDF page 2, 2025-26 monthly rows, column 14", "December(P) 194 207 206 171 257 148 146 178 139 137 137 133 157", "Source : Office of the Economic Adviser, DPIIT"),
        ],
        [
            {"statistic": "count", "expected": 12, "tolerance": 0},
            {"statistic": "value[2025-10,cpi_iw]", "expected": 148, "tolerance": 0},
            {"statistic": "max[wpi_all_commodities]", "expected": 157, "tolerance": 0},
            {"statistic": "min[cpi_ns_rural]", "expected": 176, "tolerance": 0},
        ],
        "Price index levels from Tables 4.3 and 4.1 of the Statistical Appendix to the Economic Survey 2025-26: the Labour Bureau's "
        "CPI for industrial workers (2016=100), agricultural labourers and rural labourers (1986-87=100 until May 2025, 2019=100 "
        "from June 2025, hence the drop in level), the NSO's CPI new series rural, urban and combined (2012=100), and DPIIT's "
        "wholesale price index for all commodities (2011-12=100). Annual rows are averages of months; monthly rows run April to "
        "December 2025 with November and December provisional and December published only for CPI new series and WPI. Inflation "
        "rates are not tabulated in the appendix and should be derived from these levels year on year. The Survey documents "
        "carry no licence statement.",
        ["prices", "inflation", "cpi", "wpi", "economic-survey"],
        ["pricing", "contract-indexation", "financial-planning", "demand-forecasting"],
    )


def exchange_rates() -> dict:
    def row(usd: float, gbp: float, eur: float, jpy: float, sdr: float, note: str) -> dict:
        return {"inr_per_usd": usd, "inr_per_gbp": gbp, "inr_per_eur": eur, "inr_per_jpy": jpy, "inr_per_sdr": sdr, "note": note}

    rows = {
        "2022-23": row(80.363, 96.822, 83.683, 0.594, 106.417, "fiscal year average"),
        "2023-24": row(82.790, 104.047, 89.802, 0.574, 110.234, "fiscal year average"),
        "2024-25": row(84.576, 107.879, 90.760, 0.555, 111.896, "fiscal year average"),
        "2025-04": row(85.561, 112.695, 96.230, 0.595, 115.410, "monthly average, provisional"),
        "2025-05": row(85.190, 113.919, 96.150, 0.589, 115.336, "monthly average, provisional"),
        "2025-06": row(85.903, 116.426, 98.920, 0.595, 117.167, "monthly average, provisional"),
        "2025-07": row(86.115, 116.347, 100.640, 0.587, 117.901, "monthly average, provisional"),
        "2025-08": row(87.518, 117.573, 101.798, 0.593, 119.547, "monthly average, provisional"),
        "2025-09": row(88.323, 119.277, 103.644, 0.597, 121.122, "monthly average, provisional"),
        "2025-10": row(88.416, 118.107, 102.954, 0.584, 120.581, "monthly average, provisional"),
        "2025-11": row(88.826, 116.720, 102.713, 0.572, 120.493, "monthly average, provisional"),
    }
    return entry(
        "in-rupee-exchange-rates-2025-26",
        "Indian rupee per USD, GBP, EUR, JPY and SDR: fiscal year averages 2022-23 to 2024-25 and monthly April to November 2025 (Economic Survey 2025-26)",
        "economy",
        ("2025-04-01", "2025-11-30"),
        "almanac.rules.lookup_table",
        {"unit": "INR per unit of foreign currency", "rate_type": "RBI/FBIL reference rates for USD, GBP, EUR and JPY; FEDAI indicative market rates otherwise", "rows": rows},
        [
            {"input": {"key": "2024-25", "column": "inr_per_usd"}, "expected": 84.576, "origin": "source"},
            {"input": {"key": "2025-11", "column": "inr_per_usd"}, "expected": 88.826, "origin": "source"},
            {"input": {"key": "2025-11", "column": "inr_per_eur"}, "expected": 102.713, "origin": "source"},
            {"input": {"key": "2023-24", "column": "inr_per_gbp"}, "expected": 104.047, "origin": "source"},
            {"input": "2025-12", "expected": False, "origin": "derived", "note": "the appendix ends at November 2025"},
        ],
        [
            survey("tab5.4", "PDF page 2, row 2024-25, columns 2 to 5 and 14", "2024-25 84.576 107.879 90.760 0.555 60.793 2.479 0.005 15.095 4.429 0.061 0.304 2.433 111.896", "Figures of US dollar, Pound sterling, Euro and Japanese yen from May 2012 onwards are RBI's reference rates."),
            survey("tab5.4", "PDF page 2, '2025-26 (P) (Market Rate)' monthly rows, November", "November 88.826 116.720 102.713 0.572 63.200 2.102 0.005 16.641 4.826 0.061 0.316 2.746 120.493", "2025-26 (P) (Market Rate)c"),
            survey("tab5.4", "PDF page 2, rows 2022-23 and 2023-24", "2023-24 82.790 104.047 89.802 0.574 61.451 3.164 0.005 16.781 4.786 0.063 0.291 2.352 110.234", "2022-23 80.363 96.822 83.683 0.594 60.755 4.537 0.005 15.597 4.099 0.062 0.361 2.283 106.417"),
        ],
        [
            {"statistic": "count", "expected": 11, "tolerance": 0},
            {"statistic": "value[2025-09,inr_per_usd]", "expected": 88.323, "tolerance": 0},
            {"statistic": "max[inr_per_usd]", "expected": 88.826, "tolerance": 0},
            {"statistic": "min[inr_per_jpy]", "expected": 0.555, "tolerance": 0},
        ],
        "Rupees per unit of foreign currency from Table 5.4 of the Statistical Appendix to the Economic Survey 2025-26, sourced by "
        "the Ministry of Finance from the Reserve Bank of India: fiscal year averages for 2022-23 to 2024-25 and provisional monthly "
        "averages for April to November 2025, for the US dollar, pound sterling, euro, yen and the IMF's SDR. The table notes that "
        "dollar, sterling, euro and yen figures from May 2012 are RBI reference rates, disseminated by FBIL from July 2018, and other "
        "currencies are FEDAI indicative rates. The Survey documents carry no licence statement.",
        ["exchange-rates", "fx", "inr", "economic-survey"],
        ["multi-currency-ledger", "treasury", "payments-demo", "pricing"],
    )


def forex_reserves() -> dict:
    rows = {
        "2022-23": {"gold": 45200, "reserve_tranche_position": 5165, "sdrs": 18392, "foreign_currency_assets": 509691, "total": 578449, "as_at": "end of fiscal year"},
        "2023-24": {"gold": 52675, "reserve_tranche_position": 4662, "sdrs": 18132, "foreign_currency_assets": 570950, "total": 646419, "as_at": "end of fiscal year"},
        "2024-25": {"gold": 78176, "reserve_tranche_position": 4423, "sdrs": 18169, "foreign_currency_assets": 567557, "total": 668326, "as_at": "end of fiscal year"},
        "2025-12": {"gold": 111262, "reserve_tranche_position": 4781, "sdrs": 18795, "foreign_currency_assets": 552897, "total": 687734, "as_at": "end of December 2025"},
    }
    return entry(
        "in-foreign-exchange-reserves-2025-26",
        "India foreign exchange reserves by component in USD million, end of fiscal years 2022-23 to 2024-25 and end-December 2025 (Economic Survey 2025-26)",
        "economy",
        ("2025-04-01", "2025-12-31"),
        "almanac.rules.lookup_table",
        {"unit": "USD million", "components": "gold, reserve tranche position in the IMF, SDRs, foreign currency assets", "rows": rows},
        [
            {"input": {"key": "2025-12", "column": "total"}, "expected": 687734, "origin": "source"},
            {"input": {"key": "2024-25", "column": "total"}, "expected": 668326, "origin": "source"},
            {"input": {"key": "2025-12", "column": "gold"}, "expected": 111262, "origin": "source"},
            {"input": {"key": "2023-24", "column": "foreign_currency_assets"}, "expected": 570950, "origin": "source"},
            {"input": "2026-03", "expected": False, "origin": "derived", "note": "not yet published"},
        ],
        [
            survey("tab5.1b", "PDF page 2, row 'December-25', columns 2 to 6", "December-25 111262 4781 18795 552897 687734 380 595 ...", "Table 5.1 B. Foreign Exchange Reserves"),
            survey("tab5.1b", "PDF page 2, rows 2022-23 to 2024-25", "2024-25 78176 4423 18169 567557 668326 866 612 ...", "2023-24 52675 4662 18132 570950 646419 756 302 ..."),
            survey("tab5.1b", "PDF page 2, row 2022-23 and source line", "2022-23 45200 5165 18392 509691 578449 84 206 ...", "Source: Reserve Bank of India. SDRs: Special Drawing Rights"),
        ],
        [
            {"statistic": "count", "expected": 4, "tolerance": 0},
            {"statistic": "value[2024-25,gold]", "expected": 78176, "tolerance": 0},
            {"statistic": "max[total]", "expected": 687734, "tolerance": 0},
        ],
        "Foreign exchange reserves from Table 5.1B of the Statistical Appendix to the Economic Survey 2025-26, sourced from the "
        "Reserve Bank of India, in US$ million: gold, the reserve tranche position in the IMF, SDRs, foreign currency assets and "
        "the total at the end of fiscal years 2022-23 to 2024-25 and at end-December 2025. The table's IMF drawal and repurchase "
        "columns are left out. Foreign currency assets exclude IIFC (UK) bonds, SDRs transferred by the Government to the RBI and "
        "SAARC and ACU swap lending, as the table notes. The Survey documents carry no licence statement.",
        ["reserves", "fx", "macro", "economic-survey"],
        ["treasury", "banking-demo", "financial-planning"],
    )


def labour_force() -> dict:
    lfpr = {"Andhra Pradesh": (57.0, 57.4), "Assam": (60.8, 60.4), "Bihar": (48.8, 46.1), "Chhattisgarh": (59.8, 60.9), "Delhi": (43.5, 43.1), "Gujarat": (60.9, 60.9), "Haryana": (47.1, 48.5), "Himachal Pradesh": (70.3, 69.6), "Jammu & Kashmir": (49.4, 51.6), "Jharkhand": (56.1, 57.3), "Karnataka": (50.9, 51.1), "Kerala": (57.2, 59.4), "Madhya Pradesh": (56.3, 56.9), "Maharashtra": (53.7, 59.8), "Odisha": (54.3, 52.9), "Punjab": (59.1, 61.2), "Rajasthan": (58.3, 59.5), "Tamil Nadu": (58.7, 58.6), "Telangana": (51.4, 51.4), "Uttarakhand": (50.2, 47.3), "Uttar Pradesh": (57.0, 56.8), "West Bengal": (58.0, 61.0), "All-India": (55.0, 55.1)}
    wpr = {"Andhra Pradesh": (52.3, 52.7), "Assam": (57.9, 57.2), "Bihar": (46.2, 43.8), "Chhattisgarh": (55.1, 57.5), "Delhi": (40.5, 40.2), "Gujarat": (59.5, 59.6), "Haryana": (44.4, 45.5), "Himachal Pradesh": (65.7, 64.1), "Jammu & Kashmir": (47.3, 49.4), "Jharkhand": (54.6, 55.6), "Karnataka": (46.7, 47.1), "Kerala": (54.8, 57.2), "Madhya Pradesh": (53.1, 54.0), "Maharashtra": (50.3, 57.1), "Odisha": (50.8, 49.5), "Punjab": (53.9, 56.7), "Rajasthan": (54.8, 56.1), "Tamil Nadu": (54.6, 55.3), "Telangana": (48.1, 46.8), "Uttarakhand": (47.7, 44.5), "Uttar Pradesh": (54.9, 54.7), "West Bengal": (54.6, 57.3), "All-India": (52.0, 52.2)}
    ur = {"Andhra Pradesh": (8.3, 8.2), "Assam": (4.8, 5.2), "Bihar": (5.2, 4.8), "Chhattisgarh": (7.9, 5.6), "Delhi": (6.9, 6.6), "Gujarat": (2.2, 2.2), "Haryana": (5.7, 6.2), "Himachal Pradesh": (6.5, 7.9), "Jammu & Kashmir": (4.3, 4.3), "Jharkhand": (2.6, 2.8), "Karnataka": (8.1, 8.0), "Kerala": (4.2, 3.7), "Madhya Pradesh": (5.6, 5.1), "Maharashtra": (6.4, 4.5), "Odisha": (6.5, 6.5), "Punjab": (8.8, 7.4), "Rajasthan": (5.9, 5.7), "Tamil Nadu": (6.9, 5.7), "Telangana": (3.6, 8.9), "Uttarakhand": (4.9, 5.9), "Uttar Pradesh": (3.7, 3.7), "West Bengal": (5.8, 6.1), "All-India": (5.4, 5.2)}
    rows = {
        state: {"lfpr_apr_jun_2025": lfpr[state][0], "lfpr_jul_sep_2025": lfpr[state][1], "wpr_apr_jun_2025": wpr[state][0], "wpr_jul_sep_2025": wpr[state][1], "ur_apr_jun_2025": ur[state][0], "ur_jul_sep_2025": ur[state][1]}
        for state in lfpr
    }
    return entry(
        "in-labour-force-indicators-by-state-2025-26-q2",
        "India LFPR, worker population ratio and unemployment rate (CWS, persons 15+) by state, April-June and July-September 2025 (PLFS via Economic Survey 2025-26)",
        "economy",
        ("2025-07-01", "2025-09-30"),
        "almanac.rules.lookup_table",
        {"unit": "percent", "status": "current weekly status", "population": "persons aged 15 years and above", "source_survey": "quarterly Periodic Labour Force Survey bulletins, MoSPI", "rows": rows},
        [
            {"input": {"key": "All-India", "column": "ur_jul_sep_2025"}, "expected": 5.2, "origin": "source"},
            {"input": {"key": "All-India", "column": "lfpr_jul_sep_2025"}, "expected": 55.1, "origin": "source"},
            {"input": {"key": "All-India", "column": "wpr_jul_sep_2025"}, "expected": 52.2, "origin": "source"},
            {"input": {"key": "Himachal Pradesh", "column": "lfpr_jul_sep_2025"}, "expected": 69.6, "origin": "source", "note": "highest participation"},
            {"input": {"key": "Gujarat", "column": "ur_jul_sep_2025"}, "expected": 2.2, "origin": "source", "note": "lowest unemployment"},
            {"input": "Goa", "expected": False, "origin": "derived", "note": "the tables cover 22 states and the all-India figure"},
        ],
        [
            survey("tab8.10", "PDF page 1, rows Himachal Pradesh and All-India, columns April-June and July-Sept 2025-26", "All-India 55.0 55.1", "Himachal Pradesh 70.3 69.6"),
            survey("tab8.11", "PDF page 1, rows Himachal Pradesh and ALL INDIA", "ALL INDIA 52.0 52.2", "Himachal Pradesh 65.7 64.1"),
            survey("tab8.12", "PDF page 1, rows Gujarat and All-India", "All-India 5.4 5.2", "Gujarat 2.2 2.2"),
        ],
        [
            {"statistic": "count", "expected": 23, "tolerance": 0},
            {"statistic": "value[Bihar,lfpr_jul_sep_2025]", "expected": 46.1, "tolerance": 0},
            {"statistic": "max[lfpr_jul_sep_2025]", "expected": 69.6, "tolerance": 0},
            {"statistic": "max[ur_jul_sep_2025]", "expected": 8.9, "tolerance": 0},
            {"statistic": "min[ur_jul_sep_2025]", "expected": 2.2, "tolerance": 0},
        ],
        "Quarterly labour market indicators for 22 states and all India from Tables 8.10 to 8.12 of the Statistical Appendix to the "
        "Economic Survey 2025-26, which the Ministry of Finance compiles from MoSPI's quarterly Periodic Labour Force Survey "
        "bulletins: labour force participation rate, worker population ratio and unemployment rate in current weekly status for "
        "persons aged 15 and above, for April-June and July-September 2025. Rows are keyed by state name as the tables print it. "
        "The validity window is the later quarter. The Survey documents carry no licence statement.",
        ["labour", "employment", "unemployment", "plfs", "economic-survey"],
        ["hr-analytics", "workforce-planning", "person-generation", "credit-risk"],
    )


def digital_payments() -> dict:
    def row(pos_value: float, ecom_value: float, pos_volume: float, ecom_volume: float, upi_value: int, upi_volume: int, note: str) -> dict:
        return {"rupay_pos_value_inr_billion": pos_value, "rupay_ecom_value_inr_billion": ecom_value, "rupay_pos_volume_million": pos_volume, "rupay_ecom_volume_million": ecom_volume, "upi_value_inr_billion": upi_value, "upi_volume_million": upi_volume, "note": note}

    rows = {
        "2016-17": row(289.95, 59.34, 195.22, 87.56, 70, 18, "full fiscal year"),
        "2017-18": row(488.23, 166.09, 459.55, 208.11, 1098, 915, "full fiscal year"),
        "2018-19": row(808.23, 366.90, 695.02, 432.06, 8770, 5392, "full fiscal year"),
        "2019-20": row(1146.81, 610.40, 822.59, 658.13, 21317, 12519, "full fiscal year"),
        "2020-21": row(1169.38, 926.72, 701.99, 679.68, 41037, 22331, "full fiscal year"),
        "2021-22": row(1487.12, 965.92, 843.90, 672.46, 84176, 45968, "full fiscal year"),
        "2022-23": row(1633.68, 813.59, 861.07, 403.77, 139149, 83714, "full fiscal year"),
        "2023-24": row(1550.16, 897.14, 690.91, 273.34, 199951, 131129, "full fiscal year"),
        "2024-25": row(1642.13, 1337.43, 601.87, 251.24, 260570, 185866, "full fiscal year"),
        "2025-26": row(1248.56, 1195.87, 421.74, 186.20, 229530, 176878, "April to 31 December 2025 only"),
    }
    return entry(
        "in-upi-and-rupay-payments-2016-17-to-2025-26",
        "India UPI and RuPay card payment value and volume by fiscal year, 2016-17 to 2025-26 (April-December) (NPCI via Economic Survey 2025-26)",
        "economy",
        ("2025-04-01", "2025-12-31"),
        "almanac.rules.lookup_table",
        {"units": "value in INR billion, volume in million transactions", "rows": rows},
        [
            {"input": {"key": "2024-25", "column": "upi_value_inr_billion"}, "expected": 260570, "origin": "source"},
            {"input": {"key": "2024-25", "column": "upi_volume_million"}, "expected": 185866, "origin": "source"},
            {"input": {"key": "2025-26", "column": "upi_volume_million"}, "expected": 176878, "origin": "source", "note": "nine months"},
            {"input": {"key": "2016-17", "column": "upi_volume_million"}, "expected": 18, "origin": "source", "note": "first year of UPI"},
            {"input": {"key": "2024-25", "column": "rupay_ecom_value_inr_billion"}, "expected": 1337.43, "origin": "source"},
            {"input": "2015-16", "expected": False, "origin": "derived", "note": "before the table starts"},
        ],
        [
            survey("tab3.6", "PDF page 1, row 2024-25, columns 2 to 7", "2024-25 1642.13 1337.43 601.87 251.24 260570 185866", "Table 3.6: Rupay cards & UPI Payments"),
            survey("tab3.6", "PDF page 1, row 2025-26* and footnote", "2025-26* 1248.56 1195.87 421.74 186.20 229530 176878", "*for FY 2025-26 data is till 31st December '25"),
            survey("tab3.6", "PDF page 1, rows 2016-17 and 2023-24, source line", "2016-17 289.95 59.34 195.22 87.56 70 18", "2023-24 1550.16 897.14 690.91 273.34 199951 131129"),
        ],
        [
            {"statistic": "count", "expected": 10, "tolerance": 0},
            {"statistic": "value[2022-23,upi_value_inr_billion]", "expected": 139149, "tolerance": 0},
            {"statistic": "max[upi_value_inr_billion]", "expected": 260570, "tolerance": 0},
            {"statistic": "max[rupay_pos_volume_million]", "expected": 861.07, "tolerance": 0},
        ],
        "Annual UPI and RuPay card payment totals from Table 3.6 of the Statistical Appendix to the Economic Survey 2025-26, sourced "
        "from NPCI: UPI value in ₹ billion and volume in million transactions, and RuPay card value and volume split between "
        "point-of-sale and e-commerce, for fiscal years 2016-17 to 2024-25 plus April to December 2025. The partial 2025-26 row is "
        "not comparable with full years. Monthly UPI statistics on npci.org.in were not reachable from this environment, so the "
        "Survey table stands in. The Survey documents carry no licence statement.",
        ["upi", "rupay", "payments", "digital-payments", "economic-survey"],
        ["payments-demo", "fintech-demo", "digital-channels", "demand-forecasting"],
    )


def main() -> int:
    builders = [new_regime, old_regime, senior_regime, super_senior_regime, surcharge, corporate, tcs, budget_glance, gst_penalties, gst_compliance, national_income, price_indices, exchange_rates, forex_reserves, labour_force, digital_payments]
    for build in builders:
        write(build())
    return 0


if __name__ == "__main__":
    sys.exit(main())

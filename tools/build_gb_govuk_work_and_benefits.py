"""Regenerate the UK employment, benefit and pension rule entries read from GOV.UK.

Student loan deductions, statutory parental and sick pay, Universal Credit,
Jobseeker's Allowance, State Pension, disability benefits and Child Benefit
rates come from HMRC's employer guidance, the DWP benefit and pension rates
publication and HMRC's Child Benefit rates table, all read as the JSON the
GOV.UK content API serves. Working time limits and holiday entitlement add
the Working Time Regulations 1998 as legislation.gov.uk publishes them in
XML. Run from the repository root:

    uv run python tools/build_gb_govuk_work_and_benefits.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import fetch, write  # noqa: E402
from _govuk import Source, body_html, find_table, govuk, html_tables, number  # noqa: E402

HMRC = "HM Revenue & Customs"
DWP = "Department for Work and Pensions"
LEGISLATION = "https://www.legislation.gov.uk/uksi/1998/1833/regulation"
TAX_YEAR = {"valid_from": "2026-04-06", "valid_to": "2027-04-05"}
TWO_YEARS = {"valid_from": "2025-04-06", "valid_to": "2027-04-05"}
YEAR_COLUMNS = ("weekly_2025_26", "weekly_2026_27")
OGL_NOTE = (
    "Sources are the GOV.UK content API's JSON for each page, stable between editorial updates; GOV.UK publishes "
    "its content under the Open Government Licence v3.0."
)
BENEFIT_YEAR_ASSUMPTION = {
    "parameter": "valid_from and valid_to",
    "value": "tax years 6 April to 5 April",
    "method": "derived",
    "rationale": "The DWP table labels its columns 'Rates 2025/26' and 'Rates 2026/27' without dates; the windows are taken as the tax years. Uprating of individual benefits takes effect in the first full benefit week of April, which can differ from 6 April by a few days.",
}
_PERIOD = re.compile(r"£([\d,\.]+) per (week|month|year)")
_NUMERIC = re.compile(r"[\d,]+(?:\.\d+)?%?")


def entry(**fields) -> dict:
    return {"status": "verified", "tier": "A", "region": "GB"} | fields


def rule_tests(*tests: tuple[str, object]) -> list[dict]:
    return [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}] + [
        {"statistic": statistic, "expected": expected, "tolerance": 0} for statistic, expected in tests
    ]


def tables_between(markup: str, start_id: str, end_id: str | None = None) -> list[list[list[str]]]:
    """Tables that follow the heading with id ``start_id`` and precede the heading with id ``end_id``."""
    start = markup.index(f'id="{start_id}"')
    end = markup.index(f'id="{end_id}"', start) if end_id else len(markup)
    return html_tables(markup[start:end])


def two_year_rows(tables: list[list[list[str]]]) -> dict[str, tuple[float, float]]:
    """Rows of DWP rate tables as label -> (2025/26, 2026/27); labels must be unique across the tables."""
    rows: dict[str, tuple[float, float]] = {}
    for table in tables:
        for row in table[1:]:
            if len(row) == 3 and row[0] and row[0] not in rows and all(_NUMERIC.fullmatch(cell) for cell in row[1:]):
                rows[row[0]] = (number(row[1]), number(row[2]))
    return rows


def legislation_source(regulation: str) -> Source:
    """A regulation as legislation.gov.uk's XML; the XML carries no licence statement, so the licence is unstated."""
    url = f"{LEGISLATION}/{regulation}/data.xml"
    return Source("The National Archives (legislation.gov.uk)", f"The Working Time Regulations 1998, regulation {regulation} (legislation.gov.uk XML)", url, fetch(url), license_id="unstated")


def student_loan_thresholds(employers: Source, loans: Source) -> dict:
    table = find_table(html_tables(body_html(employers)), "Rate or threshold", "2026 to 2027 rate")
    cells = {row[0]: row[1] for row in table[1:]}
    rows = {}
    for label, cell in cells.items():
        match = re.search(r"student loan plan (\d)|(postgraduate) loan", label)
        if match is None:
            continue
        key = f"plan_{match.group(1)}" if match.group(1) else "postgraduate_loan"
        amounts = {period: number(amount) for amount, period in _PERIOD.findall(cell)}
        deduction = cells["Postgraduate loan deductions" if key == "postgraduate_loan" else "Student loan deductions"]
        rows[key] = {"annual_threshold": amounts["year"], "monthly_threshold": amounts["month"], "weekly_threshold": amounts["week"], "deduction_percent": number(deduction)}
    return entry(
        id="gb-student-loan-repayment-thresholds-2026-27",
        title="United Kingdom student loan and postgraduate loan repayment thresholds and deduction rates by plan type, 2026 to 2027",
        kind="rule",
        domain="employment",
        **TAX_YEAR,
        tags=["student-loan", "payroll", "paye", "deductions"],
        use_cases=["payroll-demo", "hr-analytics", "personal-finance", "collections"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {
                "tax_year": "2026-27",
                "currency": "GBP",
                "deduction_basis": "percentage of earnings above the threshold",
                "interest_rates": {"plan_1": 4.1, "plan_4": 4.1, "plan_5": 4.1, "postgraduate_loan": 6, "plan_2": "variable, RPI plus up to 3% capped at 6%"},
                "worked_example": {"plan": "plan_1", "monthly_income": 2750, "monthly_repayment": 45.81},
                "rows": rows,
            },
            "vectors": [
                {"input": {"key": "plan_1", "column": "annual_threshold"}, "expected": 26900, "origin": "source"},
                {"input": {"key": "plan_2", "column": "monthly_threshold"}, "expected": 2448.75, "origin": "source"},
                {"input": {"key": "plan_5", "column": "weekly_threshold"}, "expected": 480.76, "origin": "source"},
                {"input": {"key": "postgraduate_loan", "column": "deduction_percent"}, "expected": 6, "origin": "source"},
                {"input": {"key": "plan_4", "column": "deduction_percent"}, "expected": 9, "origin": "source"},
                {"input": "plan_3", "expected": False, "origin": "derived", "note": "no plan 3 exists"},
            ],
        },
        evidence=[
            employers.cite("details.body, 'Student loan and postgraduate loan recovery' table, plan 1 row", "<td>Employee earnings threshold for student loan plan 1</td>", "text", "£26,900 per year<br>£2,241.66 per month<br>£517.30 per week"),
            employers.cite("details.body, 'Student loan and postgraduate loan recovery' table, postgraduate row", "<td>Employee earnings threshold for postgraduate loan</td>", "text", "£21,000 per year<br>£1,750 per month<br>£403.84 per week"),
            employers.cite("details.body, 'Student loan and postgraduate loan recovery' table, deduction rows", "<td>Student loan deductions</td>", "text", "<td>Postgraduate loan deductions</td>"),
            employers.cite("details.body, opening sentence", "Unless otherwise stated, the following figures apply from 6 April 2026 to 5 April 2027.", "text", "apply from 6 April 2026 to 5 April 2027"),
            loans.cite("details.parts[3].body, 'How much you repay'", "9% of your income over the threshold if you’re on Plan 1, 2, 4 or 5", "text", "6% of your income over the threshold if you’re on a Postgraduate Loan plan"),
            loans.cite("details.parts[3].body, worked example and interest", "9% of £509 = £45.81", "text", "4.1% if you’re on Plan 1"),
        ],
        assumed=[],
        tests=rule_tests(("count", len(rows)), ("value[plan_1,annual_threshold]", 26900), ("value[postgraduate_loan,annual_threshold]", 21000), ("max[deduction_percent]", 9), ("min[annual_threshold]", 21000)),
        notes=(
            "Earnings thresholds above which employers deduct student loan repayments through PAYE in the 2026 to 2027 tax "
            "year, by plan type (Plan 1, 2, 4 and 5 at 9% of earnings above the threshold, Postgraduate Loan at 6%), with "
            "the annual, monthly and weekly figures HMRC gives employers. GOV.UK's borrower guide confirms the rates and "
            "supplies the interest rates and the worked example kept in the parameters. " + OGL_NOTE
        ),
    )


def statutory_payments(employers: Source, dwp: Source, ssp: Source, maternity: Source) -> dict:
    markup = body_html(dwp)
    weekly = {
        key: two_year_rows(tables_between(markup, start, end))
        for key, start, end in (("smp", "statutory-maternity-pay", "statutory-neonatal-pay"), ("ssp", "statutory-sick-pay", "universal-credit-uc-monthly-rates"), ("ma", "maternity-allowance", "pension-credit"))
    }
    standard = weekly["smp"]["Standard rate"][1]
    threshold = weekly["smp"]["Earnings threshold"][1]
    earnings_related = {"weekly_rate": standard, "earnings_percent": 90, "rule": "lower of the weekly rate and 90% of average weekly earnings", "earnings_threshold_weekly": threshold}
    rows = {
        "statutory_maternity_pay": {**earnings_related, "first_weeks_at_90_percent": 6, "max_weeks": 39, "rate_from": "2026-04-05"},
        "statutory_adoption_pay": {**earnings_related, "first_weeks_at_90_percent": 6, "max_weeks": None, "rate_from": "2026-04-06"},
        "statutory_paternity_pay": {**earnings_related, "first_weeks_at_90_percent": 0, "max_weeks": None, "rate_from": "2026-04-06"},
        "statutory_shared_parental_pay": {**earnings_related, "first_weeks_at_90_percent": 0, "max_weeks": None, "rate_from": "2026-04-06"},
        "statutory_parental_bereavement_pay": {**earnings_related, "first_weeks_at_90_percent": 0, "max_weeks": None, "rate_from": "2026-04-06"},
        "statutory_neonatal_care_pay": {**earnings_related, "first_weeks_at_90_percent": 0, "max_weeks": None, "rate_from": "2026-04-06"},
        "statutory_sick_pay": {"weekly_rate": weekly["ssp"]["Standard rate"][1], "earnings_percent": 80, "rule": "lower of the weekly rate and 80% of average weekly earnings", "earnings_threshold_weekly": None, "first_weeks_at_90_percent": 0, "max_weeks": 28, "rate_from": "2026-04-06"},
        "maternity_allowance": {"weekly_rate": weekly["ma"]["Standard rate"][1], "earnings_percent": 90, "rule": "lower of the weekly rate and 90% of average weekly earnings", "earnings_threshold_weekly": weekly["ma"]["Maternity Allowance threshold"][1], "first_weeks_at_90_percent": 0, "max_weeks": None, "rate_from": "2026-04-06"},
    }
    return entry(
        id="gb-statutory-payments-2026-27",
        title="United Kingdom statutory maternity, paternity, adoption, shared parental, bereavement, neonatal care and sick pay weekly rates, 2026 to 2027",
        kind="rule",
        domain="employment",
        **TAX_YEAR,
        tags=["statutory-pay", "maternity-pay", "sick-pay", "payroll", "parental-leave"],
        use_cases=["payroll-demo", "hr-analytics", "workforce-planning", "insurance"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {
                "tax_year": "2026-27",
                "currency": "GBP",
                "unit": "per week",
                "employer_recovery_percent": {"standard": 92, "small_employer": 109, "small_employer_class_1_limit": 45000},
                "rows": rows,
            },
            "vectors": [
                {"input": {"key": "statutory_maternity_pay", "column": "weekly_rate"}, "expected": standard, "origin": "source"},
                {"input": {"key": "statutory_maternity_pay", "column": "max_weeks"}, "expected": 39, "origin": "source"},
                {"input": {"key": "statutory_sick_pay", "column": "weekly_rate"}, "expected": 123.25, "origin": "source"},
                {"input": {"key": "statutory_sick_pay", "column": "earnings_percent"}, "expected": 80, "origin": "source"},
                {"input": {"key": "statutory_sick_pay", "column": "max_weeks"}, "expected": 28, "origin": "source"},
                {"input": {"key": "statutory_paternity_pay", "column": "earnings_threshold_weekly"}, "expected": 129, "origin": "source"},
                {"input": "statutory_redundancy_pay", "expected": False, "origin": "derived", "note": "not a weekly statutory payment"},
            ],
        },
        evidence=[
            employers.cite("details.body, statutory pay table, SMP remaining weeks row", "£194.32 or 90% of the employee’s average weekly earnings, whichever is lower", "text", "weekly rate for remaining weeks"),
            employers.cite("details.body, statutory pay table, SMP first 6 weeks row", "<td>90% of the employee’s average weekly earnings</td>", "text", "weekly rate for first 6 weeks"),
            employers.cite("details.body, statutory pay table, SNCP row", "— weekly rate</td>", "text", "rate applies from 5 April 2026. All other rates apply from 6 April 2026."),
            employers.cite("details.body, 'Statutory Sick Pay (SSP)'", "is £123.25 or 80% of the employee’s average weekly earnings, whichever is lower", "text", "Unrounded daily rates"),
            employers.cite("details.body, 'Statutory payments recovery'", "109% if your total Class 1 National Insurance for the previous tax year is £45,000 or lower", "text", "You cannot recover Statutory Sick Pay"),
            dwp.cite("details.body, 'Statutory Maternity Pay' table, rows Earnings threshold and Standard rate", "<td>194.32</td>", "text", "Earnings threshold</th>"),
            dwp.cite("details.body, 'Statutory Sick Pay' table, row Standard rate", "<td>123.25</td>", "text", "Weekly rates unless otherwise stated."),
            dwp.cite("details.body, 'Maternity Allowance' table", "<td>30.00</td>", "text", "Maternity Allowance threshold"),
            ssp.cite("details.parts[0].body, overview", "It’s paid by your employer for up to 28 weeks.", "text", "You can get up to £123.25 per week Statutory Sick Pay"),
            maternity.cite("details.parts[2].body, 'Pay'", "is paid for up to 39 weeks. You get:", "text", "90% of your average weekly earnings (before tax) for the first 6 weeks"),
            maternity.cite("details.parts[3].body, SMP eligibility", "earn on average at least £129 a week", "text", "Statutory Maternity Leave is 52 weeks."),
        ],
        assumed=[
            {
                "parameter": "rows[*].earnings_threshold_weekly",
                "value": 129,
                "method": "derived",
                "rationale": "DWP prints the £129.00 earnings threshold under each statutory parental payment and GOV.UK states it for SMP; the same figure is carried on every parental payment row. SSP has no earnings threshold in the cited sources and is recorded as null.",
            }
        ],
        tests=rule_tests(("count", len(rows)), ("value[statutory_maternity_pay,weekly_rate]", standard), ("value[statutory_sick_pay,weekly_rate]", 123.25), ("value[maternity_allowance,weekly_rate]", standard), ("max[earnings_percent]", 90)),
        notes=(
            "Weekly statutory payment rates for the 2026 to 2027 tax year: Statutory Maternity, Adoption, Paternity, "
            "Shared Parental, Parental Bereavement and Neonatal Care Pay at £194.32 or 90% of average weekly earnings, "
            "whichever is lower (SMP and SAP pay 90% of earnings for the first 6 weeks; SMP runs up to 39 weeks and the "
            "SMP rate applies from 5 April 2026); Statutory Sick Pay at £123.25 or 80% of average weekly earnings, whichever "
            "is lower, for up to 28 weeks; and Maternity Allowance at the same standard rate with its £30 earnings "
            "threshold. The employer recovery percentages are kept as parameters. " + OGL_NOTE
        ),
    )


def universal_credit(dwp: Source, uc: Source) -> dict:
    markup = body_html(dwp)
    rates = two_year_rows(tables_between(markup, "universal-credit-uc-monthly-rates", "transitional-sdp-element"))
    capital = two_year_rows(tables_between(markup, "capital-limit---universal-credit", "widows-benefit"))
    labels = {
        "standard_allowance_single_under_25": "Single under 25",
        "standard_allowance_single_25_or_over": "Single 25 or over",
        "standard_allowance_couple_both_under_25": "Joint claimants both under 25",
        "standard_allowance_couple_one_or_both_25_or_over": "Joint claimants, one or both 25 or over",
        "child_element_first_child_born_before_6_april_2017": "First child (born prior to 6 April 2017)",
        "child_element": "First child (born on or after 6 April 2017 / second child and subsequent child (where an exception or transitional provision applies))",
        "disabled_child_addition_lower": "Lower rate addition",
        "disabled_child_addition_higher": "Higher rate addition",
        "limited_capability_for_work": "Limited Capability for Work amount",
        "limited_capability_for_work_and_work_related_activity": "Limited Capability for Work and Work-Related Activity amount",
        "limited_capability_for_work_and_work_related_activity_pre_2026_or_severe_conditions": "Limited Capability for Work and Work-Related Activity amount (Pre-2026 claimant, severe conditions criteria claimant or claimant who is terminally ill)",
        "carer_element": "Carer amount",
        "childcare_costs_max_one_child": "Maximum for one child",
        "childcare_costs_max_two_or_more_children": "Maximum for two or more children",
        "non_dependant_housing_cost_contribution": "Non-dependants’ housing cost contributions",
        "work_allowance_higher_no_housing_costs": "Higher work allowance (no housing amount) - One or more dependent children or limited capability for work",
        "work_allowance_lower_with_housing_costs": "Lower work allowance - One or more dependent children or limited capability for work",
    }
    rows = {key: {"monthly_2025_26": rates[label][0], "monthly_2026_27": rates[label][1], "dwp_label": label} for key, label in labels.items()}
    for key, label in (("capital_upper_limit", "Upper limit"), ("capital_disregard", "Amount disregarded")):
        rows[key] = {"monthly_2025_26": capital[label][0], "monthly_2026_27": capital[label][1], "dwp_label": label}
    assumed_income = next(v for k, v in capital.items() if k.startswith("Assumed income from capital"))
    return entry(
        id="gb-universal-credit-rates-2026-27",
        title="Great Britain Universal Credit monthly standard allowances, elements, work allowances and capital limits, 2025/26 and 2026/27",
        kind="rule",
        domain="benefits",
        **TWO_YEARS,
        tags=["universal-credit", "benefits", "welfare", "monthly-rates"],
        use_cases=["personal-finance", "household-generation", "credit-risk", "collections"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {
                "currency": "GBP",
                "unit": "per monthly assessment period",
                "earnings_taper_pence_per_pound": 55,
                "childcare_costs_percent_covered": 85,
                "assumed_income_per_250_of_capital": assumed_income[1],
                "rows": rows,
            },
            "vectors": [
                {"input": {"key": "standard_allowance_single_under_25", "column": "monthly_2026_27"}, "expected": 338.58, "origin": "source"},
                {"input": {"key": "standard_allowance_couple_one_or_both_25_or_over", "column": "monthly_2026_27"}, "expected": 666.97, "origin": "source"},
                {"input": {"key": "standard_allowance_single_25_or_over", "column": "monthly_2025_26"}, "expected": 400.14, "origin": "source"},
                {"input": {"key": "child_element", "column": "monthly_2026_27"}, "expected": 303.94, "origin": "source"},
                {"input": {"key": "work_allowance_lower_with_housing_costs", "column": "monthly_2026_27"}, "expected": 427, "origin": "source"},
                {"input": {"key": "capital_upper_limit", "column": "monthly_2026_27"}, "expected": 16000, "origin": "source"},
                {"input": "housing_element", "expected": False, "origin": "derived", "note": "housing costs depend on rent and are not a fixed rate"},
            ],
        },
        evidence=[
            dwp.cite("details.body, 'UC Amounts - Standard allowance', Single table", "<td>338.58</td>", "text", "<td>Single under 25</td>"),
            dwp.cite("details.body, 'UC Amounts - Standard allowance', Couple table", "<td>666.97</td>", "text", "<td>Joint claimants, one or both 25 or over</td>"),
            dwp.cite("details.body, 'Child amounts' table", "<td>303.94</td>", "text", "<td>351.88</td>"),
            dwp.cite("details.body, LCWRA tables", "<td>217.26</td>", "text", "<td>429.80</td>"),
            dwp.cite("details.body, 'Work allowances' table", "<td>710.00</td>", "text", "<td>427.00</td>"),
            dwp.cite("details.body, 'Capital limit - Universal Credit' table", "<td>16000.00</td>", "text", "<td>4.35</td>"),
            dwp.cite("details.body, heading", "Universal Credit (UC) (monthly rates)", "text", "Rates 2026/27"),
            uc.cite("details.parts[2].body, standard allowance table", "<td>£338.58</td>", "text", "<td>£666.97 (for you both)</td>"),
            uc.cite("details.parts[3].body, earnings taper", "For every £1 you earn from working, your Universal Credit payment goes down by 55p.", "text", "You can claim back up to 85% of your childcare costs if you’re working."),
        ],
        assumed=[BENEFIT_YEAR_ASSUMPTION],
        tests=rule_tests(("count", len(rows)), ("value[standard_allowance_single_under_25,monthly_2026_27]", 338.58), ("value[carer_element,monthly_2026_27]", 209.34), ("max[monthly_2026_27]", 16000)),
        notes=(
            "Universal Credit amounts per monthly assessment period for 2025/26 and 2026/27 as the DWP 'Benefit and "
            "pension rates 2026 to 2027' publication tables them: the four standard allowances by age and couple status, "
            "child elements, disabled child additions, limited capability for work amounts (the LCWRA amount for new "
            "claims from April 2026 is lower than the protected pre-2026 amount), carer and childcare elements, work "
            "allowances and the capital limits with the assumed income per £250 of capital. GOV.UK's Universal Credit "
            "guide confirms the standard allowances and gives the 55p earnings taper and 85% childcare cover. Each row keeps "
            "DWP's label. " + OGL_NOTE
        ),
    )


def jobseekers_allowance(dwp: Source, jsa: Source) -> dict:
    rates = two_year_rows(tables_between(body_html(dwp), "contribution-based-jsa---personal-rates", "income-based-jsa---personal-allowances"))
    bands = [{"name": "Under 25", "max_age": 24}, {"name": "25 or over", "min_age": 25}]
    tables = [
        {"from": "2025-04-06", "rates": {"Under 25": rates["Under 25"][0], "25 or over": rates["25 or over"][0]}},
        {"from": "2026-04-06", "rates": {"Under 25": rates["Under 25"][1], "25 or over": rates["25 or over"][1]}},
    ]
    return entry(
        id="gb-jobseekers-allowance-rates",
        title="Great Britain New Style (contribution-based) Jobseeker's Allowance weekly personal rates by age, 2025/26 and 2026/27",
        kind="rule",
        domain="benefits",
        **TWO_YEARS,
        tags=["jobseekers-allowance", "benefits", "unemployment", "weekly-rates"],
        use_cases=["personal-finance", "household-generation", "credit-risk"],
        spec={
            "implementation": "almanac.rules.age_band_rates",
            "parameters": {"currency": "GBP", "unit": "per week", "max_duration_days": 182, "bands": bands, "categories": [], "tables": tables},
            "vectors": [
                {"input": {"age": 22, "on": "2026-06-01"}, "expected": rates["Under 25"][1], "origin": "source"},
                {"input": {"age": 25, "on": "2026-06-01"}, "expected": rates["25 or over"][1], "origin": "source"},
                {"input": {"age": 40, "on": "2025-06-01"}, "expected": rates["25 or over"][0], "origin": "source"},
                {"input": {"age": 18, "on": "2025-04-06"}, "expected": rates["Under 25"][0], "origin": "source"},
                {"input": {"age": 24, "on": "2026-04-05"}, "expected": rates["Under 25"][0], "origin": "derived", "note": "last day of the 2025/26 table"},
            ],
        },
        evidence=[
            dwp.cite("details.body, 'Contribution based JSA - Personal Rates' table, row Under 25", "<td>75.65</td>", "text", "Contribution based JSA - Personal Rates"),
            dwp.cite("details.body, 'Contribution based JSA - Personal Rates' table, row 25 or over", "<td>95.55</td>", "text", "<td>25 or over</td>"),
            dwp.cite("details.body, heading", "Weekly rates unless otherwise stated.", "text", "Rates 2025/26"),
            jsa.cite("details.parts[0].body, 'What you’ll get' table", "<td>up to £75.65</td>", "text", "<td>up to £95.55</td>"),
            jsa.cite("details.parts[0].body, duration", "for up to 182 days (about 6 months)", "text", "After this you can talk to your work coach about your options."),
        ],
        assumed=[BENEFIT_YEAR_ASSUMPTION],
        tests=rule_tests(("count", 2), ("rate[Under 25,2026-04-06]", rates["Under 25"][1]), ("rate[25 or over,2025-04-06]", rates["25 or over"][0])),
        notes=(
            "Weekly personal rates of New Style (contribution-based) Jobseeker's Allowance by age band for 2025/26 and "
            "2026/27 from the DWP 'Benefit and pension rates 2026 to 2027' publication, confirmed by GOV.UK's JSA guide, "
            "which also gives the 182-day maximum. The age_band_rates rule returns the rate for an age on a date. " + OGL_NOTE
        ),
    )


def state_pension(dwp: Source, pension: Source) -> dict:
    rates = two_year_rows(tables_between(body_html(dwp), "state-pension", "statutory-adoption-pay"))
    labels = {
        "new_state_pension_full_rate": "Full rate",
        "old_state_pension_category_a_or_b_basic": "Category A or B basic pension",
        "old_state_pension_category_b_lower_basic": "Category B (lower) basic pension - spouse or civil partner’s insurance",
        "old_state_pension_category_c_or_d_non_contributory": "Category C or D - non-contributory",
        "maximum_additional_pension": "Maximum additional pension (own and inherited)",
    }
    rows = {key: {YEAR_COLUMNS[0]: rates[label][0], YEAR_COLUMNS[1]: rates[label][1], "dwp_label": label} for key, label in labels.items()}
    return entry(
        id="gb-state-pension-rates",
        title="United Kingdom new State Pension full rate and old State Pension basic rates per week, 2025/26 and 2026/27",
        kind="rule",
        domain="pensions",
        **TWO_YEARS,
        tags=["state-pension", "pensions", "retirement", "weekly-rates"],
        use_cases=["pensions", "personal-finance", "financial-planning", "person-generation"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {
                "currency": "GBP",
                "unit": "per week",
                "qualifying_years_for_full_new_state_pension": 35,
                "deferral_increase_percent_per_year": "just under 5.8",
                "new_state_pension_uprating_percent_2026_27": rates["Transitional rate below full rate"][1],
                "rows": rows,
            },
            "vectors": [
                {"input": {"key": "new_state_pension_full_rate", "column": "weekly_2026_27"}, "expected": 241.30, "origin": "source"},
                {"input": {"key": "new_state_pension_full_rate", "column": "weekly_2025_26"}, "expected": 230.25, "origin": "source"},
                {"input": {"key": "old_state_pension_category_a_or_b_basic", "column": "weekly_2026_27"}, "expected": 184.90, "origin": "source"},
                {"input": {"key": "old_state_pension_category_c_or_d_non_contributory", "column": "weekly_2026_27"}, "expected": 110.75, "origin": "source"},
                {"input": "pension_credit", "expected": False, "origin": "derived", "note": "Pension Credit is a separate benefit"},
            ],
        },
        evidence=[
            dwp.cite("details.body, 'State Pension', New State Pension table, row Full rate", "<td>241.30</td>", "text", "<td>Full rate</td>"),
            dwp.cite("details.body, 'State Pension', Old State Pension table, row Category A or B", "<td>184.90</td>", "text", "Category A or B basic pension"),
            dwp.cite("details.body, 'State Pension', Old State Pension table, rows Category B lower and C or D", "<td>110.75</td>", "text", "Category C or D - non-contributory"),
            dwp.cite("details.body, 'State Pension', additional pension table", "<td>230.54</td>", "text", "Maximum additional pension (own and inherited)"),
            pension.cite("details.change_history, April 2026 note", "The New State Pension rate has changed from £230.25 per week to £241.30 per week.", "text", "you will need 35 qualifying years to get the full rate of new State Pension"),
            pension.cite("details.parts[4].body, deferral", "For every year you delay claiming, your weekly payments increase by just under 5.8%.", "text", "as long as you defer for at least 9 weeks"),
        ],
        assumed=[BENEFIT_YEAR_ASSUMPTION],
        tests=rule_tests(("count", len(rows)), ("value[new_state_pension_full_rate,weekly_2026_27]", 241.30), ("value[old_state_pension_category_a_or_b_basic,weekly_2025_26]", 176.45), ("max[weekly_2026_27]", 241.30)),
        notes=(
            "Weekly State Pension rates for 2025/26 and 2026/27 from the DWP 'Benefit and pension rates 2026 to 2027' "
            "publication: the full rate of the new State Pension (for people reaching State Pension age from 6 April 2016, "
            "normally needing 35 qualifying years), the old basic State Pension by category and the maximum additional "
            "pension. GOV.UK's new State Pension guide records the April 2026 change in its change history and gives the "
            "deferral increase. " + OGL_NOTE
        ),
    )


def disability_and_carer_benefits(dwp: Source) -> dict:
    markup = body_html(dwp)
    attendance = two_year_rows(tables_between(markup, "attendance-allowance", "benefit-cap"))
    carer = two_year_rows(tables_between(markup, "carers-allowance", "deductions"))
    pip_tables = tables_between(markup, "personal-independence-payment", "severe-disablement-allowance")
    components = {table[0][0]: {row[0]: (number(row[1]), number(row[2])) for row in table[1:]} for table in pip_tables}
    sources = {
        "pip_daily_living_enhanced": components["Daily living component"]["Enhanced"],
        "pip_daily_living_standard": components["Daily living component"]["Standard"],
        "pip_mobility_enhanced": components["Mobility component"]["Enhanced"],
        "pip_mobility_standard": components["Mobility component"]["Standard"],
        "attendance_allowance_higher": attendance["Higher rate"],
        "attendance_allowance_lower": attendance["Lower rate"],
        "carers_allowance": carer["Carer’s Allowance"],
    }
    rows = {key: {YEAR_COLUMNS[0]: values[0], YEAR_COLUMNS[1]: values[1]} for key, values in sources.items()}
    return entry(
        id="gb-disability-and-carer-benefit-rates",
        title="Great Britain Personal Independence Payment, Attendance Allowance and Carer's Allowance weekly rates, 2025/26 and 2026/27",
        kind="rule",
        domain="benefits",
        **TWO_YEARS,
        tags=["pip", "attendance-allowance", "carers-allowance", "benefits", "disability", "weekly-rates"],
        use_cases=["health-demo", "insurance", "personal-finance", "household-generation"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"currency": "GBP", "unit": "per week", "rows": rows},
            "vectors": [
                {"input": {"key": "pip_daily_living_enhanced", "column": "weekly_2026_27"}, "expected": 114.60, "origin": "source"},
                {"input": {"key": "pip_mobility_standard", "column": "weekly_2026_27"}, "expected": 30.30, "origin": "source"},
                {"input": {"key": "attendance_allowance_lower", "column": "weekly_2025_26"}, "expected": 73.90, "origin": "source"},
                {"input": {"key": "carers_allowance", "column": "weekly_2026_27"}, "expected": 86.45, "origin": "source"},
                {"input": "disability_living_allowance", "expected": False, "origin": "derived", "note": "not included in this table"},
            ],
        },
        evidence=[
            dwp.cite("details.body, 'Personal Independence Payment', daily living table", "<td>114.60</td>", "text", "Daily living component"),
            dwp.cite("details.body, 'Personal Independence Payment', mobility table", "<td>80.00</td>", "text", "Mobility component"),
            dwp.cite("details.body, 'Attendance Allowance' table", "<td>76.70</td>", "text", "Attendance Allowance"),
            dwp.cite("details.body, 'Carer’s Allowance' table", "<td>86.45</td>", "text", "Carer’s Allowance"),
            dwp.cite("details.body, heading", "Weekly rates unless otherwise stated.", "text", "Rates 2026/27"),
        ],
        assumed=[BENEFIT_YEAR_ASSUMPTION],
        tests=rule_tests(("count", len(rows)), ("value[pip_daily_living_enhanced,weekly_2026_27]", 114.60), ("value[carers_allowance,weekly_2025_26]", 83.30), ("max[weekly_2026_27]", 114.60)),
        notes=(
            "Weekly rates of Personal Independence Payment (daily living and mobility components at standard and enhanced "
            "rates), Attendance Allowance (higher and lower rates) and Carer's Allowance for 2025/26 and 2026/27, read from "
            "the DWP 'Benefit and pension rates 2026 to 2027' publication. The enhanced daily living and higher Attendance "
            "Allowance rates coincide, as do the standard daily living and lower Attendance Allowance rates. " + OGL_NOTE
        ),
    )


def child_benefit(hmrc_rates: Source, child: Source) -> dict:
    tables = html_tables(body_html(hmrc_rates))
    benefit = find_table(tables, "Eldest or only child")
    guardians = find_table(tables, "Guardian’s Allowance")
    def year_key(label: str) -> str:
        start, end = label.lower().replace("tax year ", "").split(" to ")
        return f"{start}-{end[2:]}"

    rows = {}
    for row in benefit[1:]:
        if row[0]:
            rows[year_key(row[0])] = {"eldest_or_only_child_weekly": number(row[1]), "other_children_weekly": number(row[2])}
    for row in guardians[1:]:
        rows[year_key(row[0])]["guardians_allowance_weekly"] = number(row[1])
    assert rows["2026-27"]["eldest_or_only_child_weekly"] == 27.05
    return entry(
        id="gb-child-benefit-rates",
        title="United Kingdom Child Benefit and Guardian's Allowance weekly rates by tax year, 2024/25 to 2026/27",
        kind="rule",
        domain="benefits",
        valid_from="2024-04-06",
        valid_to="2027-04-05",
        tags=["child-benefit", "benefits", "families", "weekly-rates"],
        use_cases=["household-generation", "personal-finance", "financial-planning"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"currency": "GBP", "unit": "per week", "tax_year_runs": "6 April to 5 April", "rows": rows},
            "vectors": [
                {"input": {"key": "2026-27", "column": "eldest_or_only_child_weekly"}, "expected": 27.05, "origin": "source"},
                {"input": {"key": "2026-27", "column": "other_children_weekly"}, "expected": 17.90, "origin": "source"},
                {"input": {"key": "2025-26", "column": "eldest_or_only_child_weekly"}, "expected": 26.05, "origin": "source"},
                {"input": {"key": "2024-25", "column": "guardians_allowance_weekly"}, "expected": 21.75, "origin": "source"},
                {"input": "2023-24", "expected": False, "origin": "derived", "note": "earlier years are not tabled by HMRC on this page"},
            ],
        },
        evidence=[
            hmrc_rates.cite("details.body, 'Child Benefit rates' table, row Tax year 2026 to 2027", "<td>£27.05", "text", "<td>Tax year 2026 to 2027</td>"),
            hmrc_rates.cite("details.body, 'Child Benefit rates' table, row Tax year 2025 to 2026", "<td>£26.05</td>", "text", "<td>£17.25</td>"),
            hmrc_rates.cite("details.body, 'Child Benefit rates' table, row Tax year 2024 to 2025", "<td>£25.60</td>", "text", "<td>£16.95</td>"),
            hmrc_rates.cite("details.body, 'Guardian’s Allowance rates' table", "<td>£22.95", "text", "Guardian’s Allowance rates"),
            hmrc_rates.cite("details.body, introduction", "These tables show rates and allowances for Child Benefit and Guardian’s Allowance by tax year (6 April to 5 April).", "text", "rates are shown in the following table."),
            child.cite("details.parts[1].body, 'What you’ll get' table", "<td>£27.05</td>", "text", "<td>£17.90 per child</td>"),
        ],
        assumed=[],
        tests=rule_tests(("count", len(rows)), ("value[2026-27,eldest_or_only_child_weekly]", 27.05), ("value[2026-27,other_children_weekly]", 17.90), ("value[2025-26,guardians_allowance_weekly]", 22.10)),
        notes=(
            "Weekly Child Benefit rates for the eldest or only child and for each other child, and the weekly Guardian's "
            "Allowance, for the tax years 2024 to 2025, 2025 to 2026 and 2026 to 2027, read from HMRC's rates and allowances "
            "table and confirmed for 2026 to 2027 by GOV.UK's Child Benefit guide. Rows are keyed by tax year so a "
            "generator can date a payment. The High Income Child Benefit Charge is out of scope. " + OGL_NOTE
        ),
    )


def working_hours(hours: Source, reg4: Source, reg5a: Source) -> dict:
    return entry(
        id="gb-maximum-weekly-working-hours",
        status="license-review",
        title="United Kingdom maximum average weekly working time: 48 hours for adult workers and 40 hours for workers under 18 (Working Time Regulations 1998)",
        kind="rule",
        domain="employment",
        valid_from="1998-10-01",
        valid_to=None,
        tags=["working-time", "working-hours", "employment-law", "young-workers"],
        use_cases=["hr-analytics", "workforce-planning", "payroll-demo", "capacity-planning"],
        spec={
            "implementation": "almanac.rules.age_band_rates",
            "parameters": {
                "unit": "hours per week",
                "bands": [{"name": "Young worker (under 18)", "max_age": 17}, {"name": "Adult worker (18 and over)", "min_age": 18}],
                "categories": [],
                "tables": [{"from": "1998-10-01", "rates": {"Young worker (under 18)": 40, "Adult worker (18 and over)": 48}}],
                "adult_reference_period_weeks": 17,
                "adult_reference_period_max_weeks_by_agreement": 52,
                "adult_opt_out_available": True,
                "young_worker_daily_limit_hours": 8,
                "young_worker_hours_averaged": False,
            },
            "vectors": [
                {"input": {"age": 30, "on": "2026-06-01"}, "expected": 48, "origin": "source"},
                {"input": {"age": 18, "on": "2026-06-01"}, "expected": 48, "origin": "source"},
                {"input": {"age": 17, "on": "2026-06-01"}, "expected": 40, "origin": "source"},
                {"input": {"age": 16, "on": "2010-01-01"}, "expected": 40, "origin": "source"},
            ],
        },
        evidence=[
            hours.cite("details.parts[0].body, overview", "You cannot work more than 48 hours a week on average - normally", "text", "If you’re under 18, you cannot work more than 8 hours a day or 40 hours a week."),
            hours.cite("details.parts[1].body, reference period", "The 17 week period can be extended to a maximum of 52 weeks", "text", "You cannot work more than 40 hours in any one week."),
            reg4.cite("regulation 4(1), maximum weekly working time", "shall not exceed an average of 48 hours for each seven days", "text", "any period of 17 weeks"),
            reg4.cite("ukm:SecondaryMetadata, ComingIntoForce", 'Date="1998-10-01"', "text", 'Made Date="1998-07-30"'),
            reg5a.cite("regulation 5A(1), maximum working time for young workers", "40 hours a week.", "text", "eight hours a day"),
        ],
        assumed=[
            {
                "parameter": "valid_from",
                "value": "1998-10-01",
                "method": "derived",
                "rationale": "The date is when the Working Time Regulations 1998 came into force, as legislation.gov.uk records; regulation 5A for young workers was inserted by a later amendment whose commencement date is not recorded here, so the young worker limit may postdate valid_from.",
            }
        ],
        tests=rule_tests(("count", 1), ("rate[Adult worker (18 and over),2026-01-01]", 48), ("rate[Young worker (under 18),2026-01-01]", 40)),
        notes=(
            "The statutory limit on working time in Great Britain: an adult worker's working time, including overtime, may "
            "not exceed an average of 48 hours for each seven days over a 17-week reference period (extendable to 52 weeks "
            "by agreement, and adults may opt out in writing); a young worker under 18 may not work more than 8 hours a day "
            "or 40 hours a week, with no averaging. Values come from GOV.UK's guide and from regulations 4 and 5A of the "
            "Working Time Regulations 1998 as legislation.gov.uk publishes them in XML. The age_band_rates rule returns "
            "the weekly limit for an age. Exceptions for particular occupations are not modelled. The entry stays at "
            "license-review because the legislation.gov.uk XML carries no licence statement, although the site publishes "
            "legislation under the Open Government Licence v3.0. " + OGL_NOTE
        ),
    )


def holiday_entitlement(holiday: Source, reg13: Source, reg13a: Source) -> dict:
    rows = {
        "statutory_leave_weeks": {"value": 5.6, "unit": "weeks per leave year", "basis": "regulation 13 (4 weeks) plus regulation 13A (1.6 weeks)"},
        "basic_leave_weeks": {"value": 4, "unit": "weeks per leave year", "basis": "regulation 13"},
        "additional_leave_weeks": {"value": 1.6, "unit": "weeks per leave year", "basis": "regulation 13A, leave years beginning on or after 1 April 2009"},
        "maximum_statutory_days": {"value": 28, "unit": "days per leave year", "basis": "cap on the aggregate of regulations 13 and 13A; a 5-day week gives 28 days"},
        "irregular_hours_accrual_percent": {"value": 12.07, "unit": "percent of hours worked in a pay period", "basis": "irregular-hours and part-year workers, leave years from 1 April 2024"},
        "basic_rate_weeks": {"value": 1.6, "unit": "weeks per leave year", "basis": "regular-hours workers: paid at basic rather than normal pay"},
    }
    return entry(
        id="gb-statutory-holiday-entitlement",
        status="license-review",
        title="United Kingdom statutory paid holiday entitlement: 5.6 weeks a year capped at 28 days, with the 12.07% accrual rate for irregular hours",
        kind="rule",
        domain="employment",
        valid_from="2009-04-01",
        valid_to=None,
        tags=["holiday-entitlement", "annual-leave", "employment-law", "working-time"],
        use_cases=["hr-analytics", "workforce-planning", "payroll-demo", "capacity-planning"],
        spec={
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"rows": rows, "worked_example": {"hours_worked_in_pay_period": 30, "accrued_hours_before_rounding": 3.621, "accrued_hours": 4}},
            "vectors": [
                {"input": {"key": "statutory_leave_weeks", "column": "value"}, "expected": 5.6, "origin": "source"},
                {"input": {"key": "maximum_statutory_days", "column": "value"}, "expected": 28, "origin": "source"},
                {"input": {"key": "irregular_hours_accrual_percent", "column": "value"}, "expected": 12.07, "origin": "source"},
                {"input": {"key": "basic_leave_weeks", "column": "value"}, "expected": 4, "origin": "source"},
                {"input": "bank_holidays", "expected": False, "origin": "derived", "note": "bank holidays can count towards the 5.6 weeks but are not a separate entitlement"},
            ],
        },
        evidence=[
            holiday.cite("details.parts[0].body, entitlement", "are legally entitled to 5.6 weeks’ paid holiday a year (known as statutory leave entitlement or annual leave).", "text", "Most workers who work a 5-day week must receive at least 28 days’ paid annual leave a year."),
            holiday.cite("details.parts[1].body, irregular-hours accrual", "Their entitlement will be 12.07% of the hours they worked in a pay period.", "text", "they’ll have earned 4 hours leave (30 × 12.07 ÷ 100 = 3.621)"),
            holiday.cite("details.parts[2].body, holiday pay", "the remaining 1.6 weeks at a ‘basic’ rate of pay", "text", "at least 4 weeks of the worker’s statutory entitlement at their ‘normal’ rate of pay"),
            reg13.cite("regulation 13(1), entitlement to annual leave", "a worker is entitled to four weeks' annual leave in each leave year", "text", "Entitlement to annual leave"),
            reg13a.cite("regulation 13A(2)(e) and 13A(3), additional annual leave", "in any leave year beginning on or after 1st April 2009, 1.6 weeks.", "text", "is subject to a maximum of 28 days."),
        ],
        assumed=[
            {
                "parameter": "valid_from",
                "value": "2009-04-01",
                "method": "derived",
                "rationale": "Regulation 13A gives 1.6 weeks of additional leave for leave years beginning on or after 1 April 2009, the date from which the 5.6-week total applies; the 12.07% accrual method for irregular-hours workers applies only to leave years beginning on or after 1 April 2024, as its row states.",
            }
        ],
        tests=rule_tests(("count", len(rows)), ("value[statutory_leave_weeks,value]", 5.6), ("value[maximum_statutory_days,value]", 28), ("max[value]", 28)),
        notes=(
            "Statutory paid annual leave in Great Britain: 4 weeks under regulation 13 of the Working Time Regulations 1998 "
            "plus 1.6 weeks under regulation 13A, 5.6 weeks in all, capped at 28 days, so a five-day-week worker gets 28 days "
            "and a part-timer gets 5.6 times their working days. Irregular-hours and part-year workers accrue 12.07% of the "
            "hours worked in each pay period, rounded up from half an hour, for leave years from 1 April 2024. Values are "
            "read from GOV.UK's holiday entitlement guide and from the regulations as legislation.gov.uk publishes them. "
            "The entry is a reference table; it does not compute an individual's entitlement. It stays at license-review "
            "because the legislation.gov.uk XML carries no licence statement, although the site publishes legislation "
            "under the Open Government Licence v3.0. " + OGL_NOTE
        ),
    )


def main() -> int:
    employers = govuk("guidance/rates-and-thresholds-for-employers-2026-to-2027", HMRC)
    dwp = govuk("government/publications/benefit-and-pension-rates-2026-to-2027/proposed-benefit-and-pension-rates-2026-to-2027", DWP, "DWP 'Benefit and pension rates 2026 to 2027' HTML publication (GOV.UK content API JSON)")
    write(student_loan_thresholds(employers, govuk("repaying-your-student-loan", "Student Loans Company")))
    write(statutory_payments(employers, dwp, govuk("statutory-sick-pay", HMRC), govuk("maternity-pay-leave", "Department for Business and Trade")))
    write(universal_credit(dwp, govuk("universal-credit", DWP)))
    write(jobseekers_allowance(dwp, govuk("jobseekers-allowance", DWP)))
    write(state_pension(dwp, govuk("new-state-pension", DWP)))
    write(disability_and_carer_benefits(dwp))
    write(child_benefit(govuk("government/publications/rates-and-allowances-tax-credits-child-benefit-and-guardians-allowance/tax-credits-child-benefit-and-guardians-allowance", HMRC, "HMRC 'Child Benefit, Guardian's Allowance and tax credits rates and allowances' HTML publication (GOV.UK content API JSON)"), govuk("child-benefit", HMRC)))
    write(working_hours(govuk("maximum-weekly-working-hours", "Department for Business and Trade"), legislation_source("4"), legislation_source("5A")))
    write(holiday_entitlement(govuk("holiday-entitlement-rights", "Department for Business and Trade"), legislation_source("13"), legislation_source("13A")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

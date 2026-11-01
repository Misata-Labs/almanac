"""Regenerate the United States Code statutory threshold entries read from govinfo.

govinfo serves each section of the 2023 edition of the US Code as a byte-stable HTML
page, so these entries are tier B. Covered: the federal minimum wage schedule
(29 U.S.C. 206), FICA tax rates (26 U.S.C. 3101 and 3111) and the Fair Credit
Reporting Act time limits on adverse information (15 U.S.C. 1681c). Run from the
repository root:

    uv run python tools/build_us_code_statutes.py
"""

from __future__ import annotations

import html
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

GOVINFO = "https://www.govinfo.gov/content/pkg"
PUBLISHER = "Office of the Law Revision Counsel, US House of Representatives, via govinfo"
LICENSE = "unstated"
LICENSE_NOTE = (
    "US federal statutes carry no copyright, but the govinfo page states no reuse terms, so the licence is "
    "recorded as unstated and the entry held at license-review; the HTML form of the source makes the entry tier B."
)
WORD_NUMBERS = {"seven": 7, "ten": 10}


def section_url(title: int, path: str) -> str:
    return f"{GOVINFO}/USCODE-2023-title{title}/html/USCODE-2023-title{title}-{path}.htm"


def text_of(raw: bytes) -> str:
    """Visible text of a govinfo section page, one line per paragraph, whitespace collapsed."""
    markup = raw.decode("utf-8", errors="replace")
    markup = re.sub(r"<(script|style).*?</\1>", "", markup, flags=re.S)
    markup = re.sub(r"</p>|<br\s*/?>|</h\d>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip())


def first(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"pattern {pattern!r} not found")
    return match.group(1)


def money(text: str) -> int | float:
    number = text.replace("$", "").replace(",", "")
    return float(number) if "." in number else int(number)


def base_entry(entry_id: str, title: str, domain: str, valid_from: str, tags: list[str], use_cases: list[str], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], assumed: list[dict], tests: list[dict], notes: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "US",
        "status": "license-review",
        "tier": "B",
        "valid_from": valid_from,
        "valid_to": None,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed,
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes + " " + LICENSE_NOTE,
    }


def minimum_wage(raw: bytes) -> dict:
    url = section_url(29, "chap8-sec206")
    text = text_of(raw)
    title = "29 U.S.C. 206, Minimum wage (United States Code 2023 edition, HTML)"
    first_rate = money(first(r"\(A\) \$([\d.]+) an hour, beginning on the 60th day after", text))
    enacted = datetime.strptime(first(r"an hour, beginning on the 60th day after (\w+ \d+, \d{4});", text), "%B %d, %Y").date()
    second_rate = money(first(r"\(B\) \$([\d.]+) an hour, beginning 12 months after that 60th day", text))
    third_rate = money(first(r"\(C\) \$([\d.]+) an hour, beginning 24 months after that 60th day", text))
    youth_rate = money(first(r"a wage which is not less than \$([\d.]+) an hour", text))
    youth_days = int(first(r"during the first (\d+) consecutive calendar days after such employee is initially employed", text))
    day_sixty = enacted + timedelta(days=60)
    steps = [
        {"from": day_sixty.isoformat(), "value": first_rate},
        {"from": day_sixty.replace(year=day_sixty.year + 1).isoformat(), "value": second_rate},
        {"from": day_sixty.replace(year=day_sixty.year + 2).isoformat(), "value": third_rate},
    ]
    return base_entry(
        "us-federal-minimum-wage",
        "United States federal minimum wage under the Fair Labor Standards Act, 29 U.S.C. 206(a)(1), steps since 2007",
        "employment",
        steps[0]["from"],
        ["minimum-wage", "flsa", "step-schedule", "29-usc-206"],
        ["payroll-demo", "hr-analytics", "workforce-planning"],
        "almanac.rules.step_schedule",
        {
            "currency": "USD",
            "unit": "USD per hour",
            "youth_opportunity_wage_usd_per_hour": youth_rate,
            "youth_opportunity_wage_max_days": youth_days,
            "steps": steps,
        },
        [
            {"input": {"on": steps[-1]["from"]}, "expected": third_rate, "origin": "source"},
            {"input": {"on": steps[1]["from"]}, "expected": second_rate, "origin": "source"},
            {"input": {"on": "2026-10-29"}, "expected": third_rate, "origin": "derived", "note": "no later step is enacted in the 2023 edition"},
        ],
        [
            evidence(PUBLISHER, title, url, "subsection (a)(1)(C)", f"${third_rate:.2f}", "currency:USD", f"${third_rate:.2f} an hour, beginning 24 months after that 60th day", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (a)(1)(A)", f"${first_rate:.2f}", "currency:USD", f"${first_rate:.2f} an hour, beginning on the 60th day after {enacted.strftime('%B %d, %Y')}", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (g)(1)", f"${youth_rate:.2f}", "currency:USD", f"a wage which is not less than ${youth_rate:.2f} an hour", LICENSE, raw),
        ],
        [
            {
                "parameter": "steps[*].from",
                "value": [s["from"] for s in steps],
                "method": "derived",
                "rationale": "The statute dates the steps relative to its enactment: the 60th day after the enactment date printed in subsection (a)(1)(A), then 12 and 24 months after that day. The builder computes the calendar dates.",
            }
        ],
        [
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": f"value[{steps[-1]['from']}]", "expected": third_rate, "tolerance": 0},
            {"statistic": "max", "expected": third_rate, "tolerance": 0},
        ],
        (
            "The federal minimum hourly wage for employees covered by section 6(a)(1) of the Fair Labor Standards Act "
            "as the Fair Minimum Wage Act of 2007 set it in three steps, the last of which remains in force in the 2023 "
            "edition of the United States Code. The parameters also carry the youth opportunity wage of subsection "
            "(g)(1) that may be paid for a limited number of days after hiring. States and territories may set higher "
            "or, for the territories named in the section, different rates."
        ),
    )


def fica_rates(employee_raw: bytes, employer_raw: bytes) -> dict:
    employee_url = section_url(26, "subtitleC-chap21-subchapA-sec3101")
    employer_url = section_url(26, "subtitleC-chap21-subchapB-sec3111")
    employee = text_of(employee_raw)
    employer = text_of(employer_raw)
    employee_title = "26 U.S.C. 3101, Rate of tax (employee FICA; United States Code 2023 edition, HTML)"
    employer_title = "26 U.S.C. 3111, Rate of tax (employer FICA; United States Code 2023 edition, HTML)"
    employee_oasdi = float(first(r"a tax equal to ([\d.]+) percent of the wages \(as defined in section 3121\(a\)\) received by the individual", employee))
    employee_hi = float(first(r"a tax equal to ([\d.]+) percent of the wages \(as defined in section 3121\(a\)\) received by him", employee))
    additional = float(first(r"a tax equal to ([\d.]+) percent of wages which are received with respect to employment", employee))
    joint = money(first(r"\(A\) in the case of a joint return, \$([\d,]+)", employee))
    other = money(first(r"\(C\) in any other case, \$([\d,]+)", employee))
    separate_text = first(r"\(B\) in the case of a married taxpayer \(as defined in section 7703\) filing a separate return, (.+?), and", employee)
    employer_oasdi = float(first(r"equal to ([\d.]+) percent of the wages \(as defined in section 3121\(a\)\) paid by the employer with respect to employment", employer))
    employer_hi = float(first(r"\(b\) Hospital insurance\s*In addition to the tax imposed by the preceding subsection, there is hereby imposed on every employer an excise tax, with respect to having individuals in his employ, equal to ([\d.]+) percent", employer.replace("\n", " ")))
    effective_text = first(r"Amendment by Pub\. L\. 113.295 effective (\w+\. \d+, \d{4}), subject to a savings provision", employee)
    effective = datetime.strptime(effective_text, "%b. %d, %Y").date().isoformat()
    rows = {
        "employee_oasdi": {"rate_percent": employee_oasdi, "payer": "employee", "section": "3101(a)", "threshold_usd": None},
        "employee_hospital_insurance": {"rate_percent": employee_hi, "payer": "employee", "section": "3101(b)(1)", "threshold_usd": None},
        "employee_additional_hospital_insurance_joint_return": {"rate_percent": additional, "payer": "employee", "section": "3101(b)(2)(A)", "threshold_usd": joint},
        "employee_additional_hospital_insurance_married_filing_separately": {"rate_percent": additional, "payer": "employee", "section": "3101(b)(2)(B)", "threshold_usd": joint // 2, "threshold_rule": separate_text},
        "employee_additional_hospital_insurance_other": {"rate_percent": additional, "payer": "employee", "section": "3101(b)(2)(C)", "threshold_usd": other},
        "employer_oasdi": {"rate_percent": employer_oasdi, "payer": "employer", "section": "3111(a)", "threshold_usd": None},
        "employer_hospital_insurance": {"rate_percent": employer_hi, "payer": "employer", "section": "3111(b)", "threshold_usd": None},
    }
    return base_entry(
        "us-fica-tax-rates",
        "United States FICA payroll tax rates: Social Security and Medicare, employee and employer, 26 U.S.C. 3101 and 3111",
        "tax",
        effective,
        ["fica", "payroll-tax", "social-security", "medicare", "26-usc-3101"],
        ["payroll-demo", "tax-filing-demo", "hr-analytics"],
        "almanac.rules.lookup_table",
        {"currency": "USD", "rows": rows},
        [
            {"input": {"key": "employee_oasdi", "column": "rate_percent"}, "expected": employee_oasdi, "origin": "source"},
            {"input": {"key": "employer_hospital_insurance", "column": "rate_percent"}, "expected": employer_hi, "origin": "source"},
            {"input": {"key": "employee_additional_hospital_insurance_other", "column": "threshold_usd"}, "expected": other, "origin": "source"},
            {"input": "employee_additional_hospital_insurance_joint_return", "expected": True, "origin": "source"},
            {"input": "self_employment_oasdi", "expected": False, "origin": "derived", "note": "self-employment tax is in 26 U.S.C. 1401, not covered here"},
        ],
        [
            evidence(PUBLISHER, employee_title, employee_url, "subsection (a)", f"{employee_oasdi} percent", "percent", f"a tax equal to {employee_oasdi} percent of the wages", LICENSE, employee_raw),
            evidence(PUBLISHER, employee_title, employee_url, "subsection (b)(1)", f"{employee_hi} percent", "percent", f"a tax equal to {employee_hi} percent of the wages", LICENSE, employee_raw),
            evidence(PUBLISHER, employee_title, employee_url, "subsection (b)(2)", f"{additional} percent", "percent", f"a tax equal to {additional} percent of wages which are received with respect to employment", LICENSE, employee_raw),
            evidence(PUBLISHER, employee_title, employee_url, "subsection (b)(2)(A)", f"${joint:,}", "currency:USD", f"in the case of a joint return, ${joint:,}", LICENSE, employee_raw),
            evidence(PUBLISHER, employer_title, employer_url, "subsection (a)", f"{employer_oasdi} percent", "percent", f"equal to {employer_oasdi} percent of the wages (as defined in section 3121(a)) paid by the employer", LICENSE, employer_raw),
            evidence(PUBLISHER, employer_title, employer_url, "subsection (b)", f"{employer_hi} percent", "percent", f"equal to {employer_hi} percent of the wages (as defined in section 3121(a)) paid by the employer", LICENSE, employer_raw),
            evidence(PUBLISHER, employee_title, employee_url, "Effective Date of 2014 Amendment note", effective_text, "text", f"effective {effective_text}, subject to a savings provision", LICENSE, employee_raw, role="supporting"),
        ],
        [
            {
                "parameter": "rows.employee_additional_hospital_insurance_married_filing_separately.threshold_usd",
                "value": joint // 2,
                "method": "derived",
                "rationale": "Subparagraph (B) states the threshold as half of the joint-return amount rather than as a figure; threshold_rule keeps the statutory wording.",
            },
            {
                "parameter": "valid_from",
                "value": effective,
                "method": "derived",
                "rationale": "The current wording of the rate subsections dates from the 2014 amendment whose effective date the section's notes give; the rates themselves have applied since earlier years, and the additional Medicare tax since taxable years beginning after December 31, 2012.",
            }
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[employee_oasdi,rate_percent]", "expected": employee_oasdi, "tolerance": 0},
            {"statistic": "max[threshold_usd]", "expected": joint, "tolerance": 0},
        ],
        (
            "The Federal Insurance Contributions Act rates: the old-age, survivors and disability insurance (Social "
            "Security) and hospital insurance (Medicare) taxes on wages paid by the employee (26 U.S.C. 3101) and by "
            "the employer (26 U.S.C. 3111), and the additional hospital insurance tax on an employee's wages above a "
            "filing-status threshold. The statute states no wage base for the Social Security tax; the annual "
            "contribution and benefit base is set under 42 U.S.C. 430 and published by the Social Security "
            "Administration, and is not part of this entry. The married-filing-separately threshold is stated in the "
            "statute as half of the joint-return amount; threshold_rule carries that wording and threshold_usd the result."
        ),
    )


def fcra_time_limits(raw: bytes) -> dict:
    url = section_url(15, "chap41-subchapIII-sec1681c")
    text = text_of(raw)
    title = "15 U.S.C. 1681c, Requirements relating to information contained in consumer reports (United States Code 2023 edition, HTML)"

    def years(pattern: str) -> int:
        word = first(pattern, text)
        return int(word) if word.isdigit() else WORD_NUMBERS[word]

    rows = {
        "bankruptcy_cases": {"max_years": years(r"\(1\) Cases under title 11 or under the Bankruptcy Act that, .*? antedate the report by more than (\w+) years"), "section": "1681c(a)(1)"},
        "civil_suits_judgments_and_arrest_records": {"max_years": years(r"\(2\) Civil suits, civil judgments, and records of arrest that, from date of entry, antedate the report by more than (\w+) years"), "section": "1681c(a)(2)", "note": "or the governing statute of limitations if longer"},
        "paid_tax_liens": {"max_years": years(r"\(3\) Paid tax liens which, from date of payment, antedate the report by more than (\w+) years"), "section": "1681c(a)(3)"},
        "collection_and_charged_off_accounts": {"max_years": years(r"\(4\) Accounts placed for collection or charged to profit and loss which antedate the report by more than (\w+) years"), "section": "1681c(a)(4)"},
        "other_adverse_items": {"max_years": years(r"\(5\) Any other adverse item of information, other than records of convictions of crimes which antedates the report by more than (\w+) years"), "section": "1681c(a)(5)"},
    }
    exemptions = {
        "credit_transaction_principal_usd": money(first(r"\(1\) a credit transaction involving, or which may reasonably be expected to involve, a principal amount of \$([\d,]+) or more", text)),
        "life_insurance_face_amount_usd": money(first(r"\(2\) the underwriting of life insurance involving, or which may reasonably be expected to involve, a face amount of \$([\d,]+) or more", text)),
        "employment_annual_salary_usd": money(first(r"at an annual salary which equals, or which may reasonably be expected to equal \$([\d,]+), or more", text)),
    }
    bankruptcy = rows["bankruptcy_cases"]["max_years"]
    act_text = first(r"\(A\) 3 years after (\w+ \d+, \d{4}), with respect to any cash register", text)
    act_date = datetime.strptime(act_text, "%B %d, %Y").date().isoformat()
    return base_entry(
        "us-fcra-adverse-information-time-limits",
        "United States Fair Credit Reporting Act time limits on adverse information in consumer reports, 15 U.S.C. 1681c(a) and (b)",
        "consumer-credit",
        act_date,
        ["fcra", "credit-reports", "credit-bureau", "retention-limits", "15-usc-1681c"],
        ["credit-risk", "collections", "kyc-onboarding", "banking-demo"],
        "almanac.rules.lookup_table",
        {"exemption_thresholds": exemptions, "rows": rows},
        [
            {"input": {"key": "bankruptcy_cases", "column": "max_years"}, "expected": bankruptcy, "origin": "source"},
            {"input": {"key": "collection_and_charged_off_accounts", "column": "max_years"}, "expected": rows["collection_and_charged_off_accounts"]["max_years"], "origin": "source"},
            {"input": "other_adverse_items", "expected": True, "origin": "source"},
            {"input": "criminal_convictions", "expected": False, "origin": "derived", "note": "records of convictions are excluded from the seven-year limit"},
        ],
        [
            evidence(PUBLISHER, title, url, "subsection (a)(1)", f"{bankruptcy} years", "text", f"antedate the report by more than {bankruptcy} years", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (a)(4)", "seven years", "text", "Accounts placed for collection or charged to profit and loss which antedate the report by more than seven years", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (b)(1)", f"${exemptions['credit_transaction_principal_usd']:,}", "currency:USD", f"a principal amount of ${exemptions['credit_transaction_principal_usd']:,} or more", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (b)(3)", f"${exemptions['employment_annual_salary_usd']:,}", "currency:USD", f"reasonably be expected to equal ${exemptions['employment_annual_salary_usd']:,}, or more", LICENSE, raw),
            evidence(PUBLISHER, title, url, "subsection (g)(3)(A)", act_text, "text", f"3 years after {act_text}, with respect to any cash register", LICENSE, raw, role="supporting"),
        ],
        [
            {
                "parameter": "valid_from",
                "value": act_date,
                "method": "derived",
                "rationale": "The section's amendment history shows its most recent substantive amendment in the 2003 Act (Pub. L. 108-159), whose enactment date subsection (g)(3)(A) states; the seven-year and ten-year limits themselves date from earlier amendments, and the exemption amounts from the 1996 amendment.",
            }
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[bankruptcy_cases,max_years]", "expected": bankruptcy, "tolerance": 0},
            {"statistic": "max[max_years]", "expected": bankruptcy, "tolerance": 0},
        ],
        (
            "How long each category of adverse information may stay in a consumer report under section 605 of the "
            "Fair Credit Reporting Act: the longer limit for bankruptcy cases and the common limit for civil "
            "judgments, paid tax liens, collection accounts and other adverse items, measured from the dates the "
            "statute names. The exemption_thresholds carry the transaction sizes above which subsection (b) lifts "
            "these limits. Useful for ageing out tradelines and public records in synthetic credit files."
        ),
    )


def main() -> int:
    write(minimum_wage(fetch(section_url(29, "chap8-sec206"))))
    write(fica_rates(fetch(section_url(26, "subtitleC-chap21-subchapA-sec3101")), fetch(section_url(26, "subtitleC-chap21-subchapB-sec3111"))))
    write(fcra_time_limits(fetch(section_url(15, "chap41-subchapIII-sec1681c"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

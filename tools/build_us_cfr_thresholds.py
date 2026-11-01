"""Regenerate the US federal regulation threshold entries read from the eCFR API.

Each entry takes its numbers from one part of the Code of Federal Regulations as
published by the eCFR point-in-time API (XML), and its validity date from the
eCFR versions endpoint for the section concerned. The parts covered are the FLSA
exemption salary levels (29 CFR 541), Regulation CC dollar amounts (12 CFR 229),
Regulation Z thresholds and their inflation histories (12 CFR 1026), Regulation E
liability limits (12 CFR 1005), the HIPAA safe-harbour identifiers (45 CFR 164),
OSHA recordkeeping thresholds (29 CFR 1904), FMLA eligibility (29 CFR 825), the
FDA daily values for nutrition labelling (21 CFR 101) and Social Security full
retirement age (20 CFR 404). Run from the repository root:

    uv run python tools/build_us_cfr_thresholds.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

CFR_DATE = "2026-10-29"
API = "https://www.ecfr.gov/api/versioner/v1"
ECFR = "via the eCFR API"
LICENSE = "unstated"
LICENSE_NOTE = (
    "US federal government works carry no copyright, but neither the eCFR API nor the regulation text states "
    "reuse terms, so the licence is recorded as unstated and the entry held at license-review."
)
WORD_NUMBERS = {"one": 1, "two": 2, "seven": 7, "eight": 8, "ten": 10, "twelve": 12, "thirty": 30}


def part_url(title: int, part: int | str) -> str:
    return f"{API}/full/{CFR_DATE}/title-{title}.xml?part={part}"


def versions_url(title: int, section: str) -> str:
    return f"{API}/versions/title-{title}.json?section={section}"


def strip_tags(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def section(raw: bytes, number: str) -> str:
    """Raw XML of one section (DIV8) of a part."""
    match = re.search(rf'<DIV8 N="{re.escape(number)}".*?</DIV8>', raw.decode("utf-8"), re.S)
    if match is None:
        raise ValueError(f"section {number} not found")
    return match.group(0)


def paragraphs(markup: str) -> list[str]:
    """Text of every <P> element in document order, whitespace collapsed."""
    return [re.sub(r"\s+", " ", strip_tags(m.group(0))) for m in re.finditer(r"<P[^>]*>.*?</P>", markup, re.S)]


def tables(markup: str) -> list[list[list[str]]]:
    """Every <TABLE> as rows of cell texts."""
    out = []
    for block in re.findall(r"<TABLE.*?</TABLE>", markup, re.S):
        rows = []
        for row in re.findall(r"<TR>(.*?)</TR>", block, re.S):
            rows.append([strip_tags(cell) for cell in re.findall(r"<T[DH][^>]*>(.*?)</T[DH]>", row, re.S)])
        out.append(rows)
    return out


def money(text: str) -> int | float:
    number = text.replace("$", "").replace(",", "")
    return float(number) if "." in number else int(number)


def long_date(text: str) -> str:
    return datetime.strptime(text, "%B %d, %Y").date().isoformat()


def latest_version(raw: bytes) -> str:
    """Date of the most recent version of a section, from the eCFR versions endpoint."""
    versions = json.loads(raw)["content_versions"]
    return max(v["date"] for v in versions)


def version_evidence(title: int, section_number: str, raw: bytes) -> dict:
    day = latest_version(raw)
    return evidence(
        f"Office of the Federal Register {ECFR}",
        f"eCFR versions of {title} CFR {section_number} (JSON)",
        versions_url(title, section_number),
        "content_versions[*].date, latest",
        day,
        "date",
        f'"date":"{day}"',
        LICENSE,
        raw,
        role="supporting",
    )


def anchor_index(paras: list[str], anchor: str) -> int:
    """Index of the first paragraph containing ``anchor``."""
    return next(i for i, p in enumerate(paras) if anchor in p)


def first(pattern: str, text: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if match is None:
        raise ValueError(f"pattern {pattern!r} not found")
    return match.group(1)


def lookup_entry(entry_id: str, title: str, domain: str, valid_from: str, tags: list[str], use_cases: list[str], parameters: dict, vectors: list[dict], evidence_items: list[dict], assumed: list[dict], tests: list[dict], notes: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": valid_from,
        "valid_to": None,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": "almanac.rules.lookup_table", "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed,
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes + " " + LICENSE_NOTE,
    }


# ---------------------------------------------------------------- 29 CFR 541: FLSA exemption salary levels


def flsa_salary(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(29, 541)
    text_600 = " ".join(paragraphs(section(raw, "541.600")))
    text_601 = " ".join(paragraphs(section(raw, "541.601")))
    publisher = f"US Department of Labor, Wage and Hour Division {ECFR}"
    title = f"29 CFR part 541, Defining and Delimiting the Exemptions for Executive, Administrative, Professional, Computer and Outside Sales Employees, as of {CFR_DATE} (XML)"
    weekly = first(r"not less than \$([\d,]+) per week \(or", text_600)
    territories = first(r"or \$([\d,]+) per week if employed in the Commonwealth of the Northern Mariana Islands", text_600)
    samoa = first(r"or \$([\d,]+) per week if employed in American Samoa", text_600)
    biweekly = first(r"biweekly on a salary basis of not less than \$([\d,]+)", text_600)
    semimonthly = first(r"semimonthly on a salary basis of not less than \$([\d,]+)", text_600)
    monthly = first(r"monthly on a salary basis of not less than \$([\d,]+)", text_600)
    computer = first(r"hourly basis at a rate not less than \$([\d.]+) an hour", text_600)
    hce = first(r"total annual compensation of at least \$([\d,]+) is deemed exempt", text_601)
    rows = {
        "standard_salary_weekly": {"amount_usd": money(weekly), "period": "week", "section": "541.600(a)"},
        "territories_salary_weekly": {"amount_usd": money(territories), "period": "week", "section": "541.600(a)", "scope": "Northern Mariana Islands, Guam, Puerto Rico and US Virgin Islands, non-federal employers"},
        "american_samoa_salary_weekly": {"amount_usd": money(samoa), "period": "week", "section": "541.600(a)", "scope": "American Samoa, non-federal employers"},
        "standard_salary_biweekly": {"amount_usd": money(biweekly), "period": "two weeks", "section": "541.600(b)"},
        "standard_salary_semimonthly": {"amount_usd": money(semimonthly), "period": "half month", "section": "541.600(b)"},
        "standard_salary_monthly": {"amount_usd": money(monthly), "period": "month", "section": "541.600(b)"},
        "computer_employee_hourly": {"amount_usd": money(computer), "period": "hour", "section": "541.600(d)"},
        "highly_compensated_annual": {"amount_usd": money(hce), "period": "year", "section": "541.601(a)(1)"},
    }
    return lookup_entry(
        "us-flsa-exemption-salary-levels",
        "United States FLSA executive, administrative and professional exemption salary levels, 29 CFR 541.600 and 541.601",
        "employment",
        latest_version(versions_raw),
        ["flsa", "overtime", "exempt-employees", "salary-threshold", "29-cfr-541"],
        ["payroll-demo", "hr-analytics", "workforce-planning"],
        {"currency": "USD", "rows": rows},
        [
            {"input": {"key": "standard_salary_weekly", "column": "amount_usd"}, "expected": money(weekly), "origin": "source"},
            {"input": {"key": "computer_employee_hourly", "column": "amount_usd"}, "expected": money(computer), "origin": "source"},
            {"input": {"key": "highly_compensated_annual", "column": "amount_usd"}, "expected": money(hce), "origin": "source"},
            {"input": "standard_salary_monthly", "expected": True, "origin": "source"},
            {"input": "standard_salary_daily", "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, "section 541.600(a)", f"${weekly}", "currency:USD", f"salary basis at a rate of not less than ${weekly} per week", LICENSE, raw),
            evidence(publisher, title, url, "section 541.600(b)", f"${monthly}", "currency:USD", f"monthly on a salary basis of not less than ${monthly}", LICENSE, raw),
            evidence(publisher, title, url, "section 541.600(d)", f"${computer}", "currency:USD", f"hourly basis at a rate not less than ${computer} an hour", LICENSE, raw),
            evidence(publisher, title, url, "section 541.601(a)(1)", f"${hce}", "currency:USD", f"total annual compensation of at least ${hce} is deemed exempt", LICENSE, raw),
            version_evidence(29, "541.600", versions_raw),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[standard_salary_weekly,amount_usd]", "expected": money(weekly), "tolerance": 0},
            {"statistic": "max[amount_usd]", "expected": money(hce), "tolerance": 0},
        ],
        (
            "The minimum salary an employee must be paid to qualify for the executive, administrative or professional "
            "exemption from overtime under section 13(a)(1) of the Fair Labor Standards Act, as 29 CFR 541.600 states it "
            f"in the eCFR text as of {CFR_DATE}: the standard weekly level, the lower levels for the territories, the "
            "equivalent biweekly, semimonthly and monthly amounts, the hourly rate for computer employees and the total "
            "annual compensation level for the highly compensated employee test of 541.601. valid_from is the date of "
            "the latest version of 541.600 in the eCFR versions endpoint."
        ),
    )


# ---------------------------------------------------------------- 12 CFR 229: Regulation CC dollar amounts


def reg_cc_amounts(raw: bytes, versions_raw: bytes) -> list[dict]:
    url = part_url(12, 229)
    paras = paragraphs(section(raw, "229.11"))
    publisher = f"Board of Governors of the Federal Reserve System {ECFR}"
    title = f"12 CFR part 229, Availability of Funds and Collection of Checks (Regulation CC), as of {CFR_DATE} (XML)"
    anchors = {
        "next_day": ("(1) For purposes of § 229.10(c)(1)(vii)", "229.10(c)(1)(vii)"),
        "cash_withdrawal": ("(2) For purposes of § 229.12(d)", "229.12(d)"),
        "exception": ("(3) For purposes of §§ 229.13(a), (b), and (d)", "229.13(a), (b) and (d)"),
    }
    schedules: dict[str, dict] = {}
    for name, (anchor, label) in anchors.items():
        start = anchor_index(paras, anchor)
        prior = None
        steps = []
        for p in paras[start + 1 :]:
            if re.match(r"\(\d\) For purposes", p):
                break
            if m := re.match(r"\([ivx]+\) Prior to (\w+ \d+, \d{4}), the amount is \$([\d,]+)\.", p):
                prior = money(m.group(2))
            elif m := re.match(r"\([ivx]+\) From (\w+ \d+, \d{4}), through \w+ \d+, \d{4},.*? the amount is \$([\d,]+)\.", p):
                steps.append({"from": long_date(m.group(1)), "value": money(m.group(2))})
            elif m := re.match(r"\([ivx]+\) Effective (\w+ \d+, \d{4}), the amount is \$([\d,]+)\.", p):
                steps.append({"from": long_date(m.group(1)), "value": money(m.group(2))})
            else:
                raise ValueError(f"unrecognised amount paragraph: {p}")
        schedules[name] = {"prior": prior, "steps": steps, "label": label}
    common_tags = ["regulation-cc", "funds-availability", "deposits", "step-schedule", "12-cfr-229"]
    common_use_cases = ["banking-demo", "payments-scheduling", "payments-demo"]
    version = version_evidence(12, "229.11", versions_raw)
    valid_from_note = "The first step is the first period the regulation dates; the amount before it sits in before_first_step."

    def entry(entry_id: str, name: str, title_text: str, section_label: str, notes: str) -> dict:
        sched = schedules[name]
        steps = sched["steps"]
        last = steps[-1]
        return {
            "id": entry_id,
            "title": title_text,
            "kind": "rule",
            "domain": "banking",
            "region": "US",
            "status": "license-review",
            "tier": "A",
            "valid_from": steps[0]["from"],
            "valid_to": None,
            "tags": common_tags,
            "use_cases": common_use_cases,
            "spec": {
                "implementation": "almanac.rules.step_schedule",
                "parameters": {"currency": "USD", "section": section_label, "before_first_step": sched["prior"], "steps": steps},
                "vectors": [
                    {"input": {"on": last["from"]}, "expected": last["value"], "origin": "source"},
                    {"input": {"on": steps[-2]["from"]}, "expected": steps[-2]["value"], "origin": "source"},
                    {"input": {"on": "2026-10-29"}, "expected": last["value"], "origin": "derived", "note": "eCFR snapshot date"},
                ],
            },
            "evidence": [
                evidence(publisher, title, url, f"section 229.11(c), {section_label}", f"${last['value']:,}", "currency:USD", f"the amount is ${last['value']:,}.", LICENSE, raw),
                evidence(publisher, title, url, f"section 229.11(c), {section_label}", f"${steps[-2]['value']:,}", "currency:USD", f"the amount is ${steps[-2]['value']:,}.", LICENSE, raw),
                version,
            ],
            "assumed": [],
            "tests": [
                {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
                {"statistic": "count", "expected": len(steps), "tolerance": 0},
                {"statistic": "max", "expected": last["value"], "tolerance": 0},
            ],
            "notes": notes + " " + valid_from_note + " " + LICENSE_NOTE,
        }

    return [
        entry(
            "us-regulation-cc-next-day-availability-amount",
            "next_day",
            "United States Regulation CC next-day availability amount for check deposits, 12 CFR 229.10(c)(1)(vii)",
            "229.10(c)(1)(vii)",
            (
                "The portion of a day's check deposits a depositary bank must make available on the next business day "
                "regardless of check type, as indexed to the CPI-W every five years under 12 CFR 229.11 and listed by "
                f"period in 229.11(c)(1) of the eCFR text as of {CFR_DATE}."
            ),
        ),
        entry(
            "us-regulation-cc-cash-withdrawal-amount",
            "cash_withdrawal",
            "United States Regulation CC cash withdrawal amount for check deposits, 12 CFR 229.12(d)",
            "229.12(d)",
            (
                "The amount of check deposits a depositary bank must make available for withdrawal by cash or similar "
                "means by 5:00 p.m. on the day the funds become available, when it extends the availability schedule "
                f"by one business day, as listed by period in 229.11(c)(2) of the eCFR text as of {CFR_DATE}."
            ),
        ),
        entry(
            "us-regulation-cc-exception-hold-threshold",
            "exception",
            "United States Regulation CC large deposit, new account and repeated overdraft threshold, 12 CFR 229.13(a), (b) and (d)",
            "229.13(a), (b) and (d)",
            (
                "The dollar threshold shared by the new-account, large-deposit and repeated-overdraft exceptions to the "
                "funds availability schedule: amounts above it may be held longer, and the overdraft exception counts "
                f"days the account was negative by at least this amount. Listed by period in 229.11(c)(3) as of {CFR_DATE}."
            ),
        ),
    ]


# ---------------------------------------------------------------- 12 CFR 1026: Regulation Z


def threshold_steps(paras: list[str], anchor: str) -> tuple[int | None, list[dict]]:
    """Parse a Supplement I threshold history that follows ``anchor``: a prior amount and dated steps."""
    start = anchor_index(paras, anchor)
    prior = None
    steps = []
    for p in paras[start + 1 :]:
        if m := re.match(r"[ivxl]+\. Prior to (\w+ \d+, \d{4}), the threshold amount is \$([\d,]+)\.", p):
            prior = money(m.group(2))
        elif m := re.match(r"[ivxl]+\. From (\w+ \d+, \d{4}), through \w+ \d+, \d{4}, the threshold amount is \$([\d,]+)\.", p):
            steps.append({"from": long_date(m.group(1)), "value": money(m.group(2))})
        else:
            break
    if not steps:
        raise ValueError(f"no threshold steps after {anchor!r}")
    return prior, steps


def reg_z_step_entry(entry_id: str, title_text: str, section_label: str, anchor: str, raw: bytes, versions_raw: bytes, version_section: str, tags: list[str], use_cases: list[str], notes: str) -> dict:
    url = part_url(12, 1026)
    publisher = f"Consumer Financial Protection Bureau {ECFR}"
    title = f"12 CFR part 1026, Truth in Lending (Regulation Z), as of {CFR_DATE} (XML)"
    prior, steps = threshold_steps(paragraphs(raw.decode("utf-8")), anchor)
    last, previous = steps[-1], steps[-2]
    last_year = last["from"][:4]
    return {
        "id": entry_id,
        "title": title_text,
        "kind": "rule",
        "domain": "consumer-credit",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": steps[0]["from"],
        "valid_to": f"{last_year}-12-31",
        "tags": tags,
        "use_cases": use_cases,
        "spec": {
            "implementation": "almanac.rules.step_schedule",
            "parameters": {"currency": "USD", "section": section_label, "before_first_step": prior, "steps": steps},
            "vectors": [
                {"input": {"on": last["from"]}, "expected": last["value"], "origin": "source"},
                {"input": {"on": previous["from"]}, "expected": previous["value"], "origin": "source"},
                {"input": {"on": steps[0]["from"]}, "expected": steps[0]["value"], "origin": "source"},
            ],
        },
        "evidence": [
            evidence(publisher, title, url, f"Supplement I, comment {section_label}", f"${last['value']:,}", "currency:USD", f"From January 1, {last_year}, through December 31, {last_year}, the threshold amount is ${last['value']:,}", LICENSE, raw),
            evidence(publisher, title, url, f"Supplement I, comment {section_label}", f"${steps[0]['value']:,}", "currency:USD", f"the threshold amount is ${steps[0]['value']:,}.", LICENSE, raw),
            version_evidence(12, version_section, versions_raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": "max", "expected": max(s["value"] for s in steps), "tolerance": 0},
        ],
        "notes": notes + f" The commentary lists the amount for each calendar year; the last listed year is {last_year}, which sets valid_to. " + LICENSE_NOTE,
    }


def reg_z_exemption_threshold(raw: bytes, versions_raw: bytes) -> dict:
    return reg_z_step_entry(
        "us-regulation-z-exemption-threshold",
        "United States Regulation Z consumer credit exemption threshold amount, 12 CFR 1026.3(b)",
        "3(b)-3",
        "3. Threshold. For purposes of § 1026.3(b)",
        raw,
        versions_raw,
        "1026.3",
        ["regulation-z", "truth-in-lending", "exemption-threshold", "step-schedule", "12-cfr-1026"],
        ["loan-pricing", "banking-demo", "credit-risk"],
        (
            "The amount above which an extension of consumer credit not secured by real property or a dwelling is "
            "exempt from Regulation Z (12 CFR 1026.3(b)), adjusted each January 1 by the change in the CPI-W, as the "
            f"official interpretation (comment 3(b)-3) lists it by period in the eCFR text as of {CFR_DATE}."
        ),
    )


def reg_z_appraisal_threshold(raw: bytes, versions_raw: bytes) -> dict:
    return reg_z_step_entry(
        "us-regulation-z-hpml-appraisal-exemption-threshold",
        "United States Regulation Z higher-priced mortgage loan appraisal exemption threshold, 12 CFR 1026.35(c)(2)(ii)",
        "35(c)(2)(ii)-3",
        "3. Threshold. For purposes of § 1026.35(c)(2)(ii)",
        raw,
        versions_raw,
        "1026.35",
        ["regulation-z", "mortgage", "appraisal", "step-schedule", "12-cfr-1026"],
        ["mortgage-origination", "loan-pricing", "banking-demo"],
        (
            "The loan amount at or below which a higher-priced mortgage loan is exempt from the appraisal requirements "
            "of 12 CFR 1026.35(c), adjusted each January 1 by the change in the CPI-W, as the official interpretation "
            f"(comment 35(c)(2)(ii)-3) lists it by period in the eCFR text as of {CFR_DATE}."
        ),
    )


def hoepa_thresholds(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(12, 1026)
    publisher = f"Consumer Financial Protection Bureau {ECFR}"
    title = f"12 CFR part 1026, Truth in Lending (Regulation Z), as of {CFR_DATE} (XML)"
    paras = paragraphs(raw.decode("utf-8"))
    rule = " ".join(paragraphs(section(raw, "1026.32")))

    def yearly(anchor: str) -> dict[int, int]:
        start = anchor_index(paras, anchor)
        values = {}
        for p in paras[start + 1 :]:
            if m := re.match(r"[ivxl]+\. For (\d{4}), \$([\d,]+), reflecting", p):
                values[int(m.group(1))] = money(m.group(2))
            else:
                break
        if not values:
            raise ValueError(f"no yearly amounts after {anchor!r}")
        return values

    caps = yearly("1. Annual adjustment of $1,000 amount.")
    thresholds = yearly("3. Applicable threshold.")
    if caps.keys() != thresholds.keys():
        raise ValueError("HOEPA cap and threshold years differ")
    rows = {str(year): {"loan_amount_threshold_usd": thresholds[year], "points_and_fees_cap_below_threshold_usd": caps[year]} for year in sorted(caps)}
    percent_large = int(first(r"\(A\) (\d+) percent of the total loan amount for a transaction with a loan amount of \$20,000 or more", rule))
    percent_small = int(first(r"\(B\) The lesser of (\d+) percent of the total loan amount or \$1,000", rule))
    apr_first = float(first(r"\(A\) ([\d.]+) percentage points for a first-lien transaction, other than", rule))
    apr_subordinate = float(first(r"\(C\) ([\d.]+) percentage points for a subordinate-lien transaction", rule))
    prepayment_months = int(first(r"more than (\d+) months after consummation", rule))
    prepayment_percent = int(first(r"exceed, in total, more than (\d+) percent of the amount prepaid", rule))
    last = max(caps)
    first_year = min(caps)
    return lookup_entry(
        "us-regulation-z-hoepa-points-and-fees-thresholds",
        f"United States Regulation Z high-cost mortgage (HOEPA) points-and-fees thresholds by year, 12 CFR 1026.32(a)(1)(ii), {first_year} to {last}",
        "consumer-credit",
        f"{first_year}-01-01",
        ["regulation-z", "hoepa", "high-cost-mortgage", "points-and-fees", "12-cfr-1026"],
        ["mortgage-origination", "loan-pricing", "credit-risk"],
        {
            "currency": "USD",
            "points_and_fees_percent_at_or_above_threshold": percent_large,
            "points_and_fees_percent_below_threshold": percent_small,
            "apr_trigger_first_lien_percentage_points": apr_first,
            "apr_trigger_subordinate_lien_percentage_points": apr_subordinate,
            "prepayment_penalty_max_months": prepayment_months,
            "prepayment_penalty_max_percent": prepayment_percent,
            "rows": rows,
        },
        [
            {"input": {"key": str(last), "column": "loan_amount_threshold_usd"}, "expected": thresholds[last], "origin": "source"},
            {"input": {"key": str(last), "column": "points_and_fees_cap_below_threshold_usd"}, "expected": caps[last], "origin": "source"},
            {"input": {"key": str(first_year), "column": "loan_amount_threshold_usd"}, "expected": thresholds[first_year], "origin": "source"},
            {"input": str(first_year - 1), "expected": False, "origin": "derived", "note": "years before the current adjustment series are not listed"},
        ],
        [
            evidence(publisher, title, url, "section 1026.32(a)(1)(ii)(A)", f"{percent_large} percent", "percent", f"{percent_large} percent of the total loan amount for a transaction with a loan amount of $20,000 or more", LICENSE, raw),
            evidence(publisher, title, url, "Supplement I, comment 32(a)(1)(ii)-1", f"${caps[last]:,}", "currency:USD", f"For {last}, ${caps[last]:,}, reflecting", LICENSE, raw),
            evidence(publisher, title, url, "Supplement I, comment 32(a)(1)(ii)-3", f"${thresholds[last]:,}", "currency:USD", f"For {last}, ${thresholds[last]:,}, reflecting", LICENSE, raw),
            version_evidence(12, "1026.32", versions_raw),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{last},loan_amount_threshold_usd]", "expected": thresholds[last], "tolerance": 0},
            {"statistic": "max[points_and_fees_cap_below_threshold_usd]", "expected": max(caps.values()), "tolerance": 0},
        ],
        (
            "The points-and-fees coverage test for high-cost mortgages under the Home Ownership and Equity Protection "
            "Act as implemented in 12 CFR 1026.32(a)(1)(ii): a loan is high-cost when points and fees exceed a fixed "
            "percentage of the loan amount at or above the indexed loan-amount threshold, or the lesser of a higher "
            "percentage and an indexed dollar cap below it. The rows give the two indexed figures for each calendar "
            f"year as the official interpretation lists them in the eCFR text as of {CFR_DATE}; the percentages, the "
            "APR triggers and the prepayment penalty limits come from the regulation text itself."
        ),
    )


def qm_points_and_fees(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(12, 1026)
    publisher = f"Consumer Financial Protection Bureau {ECFR}"
    title = f"12 CFR part 1026, Truth in Lending (Regulation Z), as of {CFR_DATE} (XML)"
    paras = paragraphs(raw.decode("utf-8"))
    start = anchor_index(paras, "Paragraph 43(e)(3)(ii).")
    rows: dict[str, dict] = {}
    percents: set[tuple[int, int, int]] = set()
    year = None
    for p in paras[start + 1 :]:
        if m := re.match(r"[ivxl]+\. For (\d{4}), reflecting", p):
            year = m.group(1)
            rows[year] = {}
        elif year is None:
            continue
        elif m := re.match(r"A\. For a loan amount greater than or equal to \$([\d,]+): (\d+) percent of the total loan amount", p):
            rows[year]["tier_a_min_loan_usd"] = money(m.group(1))
            pa = int(m.group(2))
        elif m := re.match(r"B\. For a loan amount greater than or equal to \$([\d,]+) but less than \$([\d,]+): \$([\d,]+)", p):
            rows[year]["tier_b_min_loan_usd"] = money(m.group(1))
            rows[year]["tier_b_cap_usd"] = money(m.group(3))
        elif m := re.match(r"C\. For a loan amount greater than or equal to \$([\d,]+) but less than \$([\d,]+): (\d+) percent of the total loan amount", p):
            rows[year]["tier_c_min_loan_usd"] = money(m.group(1))
            pc = int(m.group(3))
        elif m := re.match(r"D\. For a loan amount greater than or equal to \$([\d,]+) but less than \$([\d,]+)[:;] \$([\d,]+)", p):
            rows[year]["tier_d_min_loan_usd"] = money(m.group(1))
            rows[year]["tier_d_cap_usd"] = money(m.group(3))
        elif m := re.match(r"E\. For a loan amount less than \$([\d,]+): (\d+) percent of the total loan amount", p):
            pe = int(m.group(2))
            percents.add((pa, pc, pe))
        else:
            break
    rows = {y: r for y, r in rows.items() if len(r) == 6}
    if len(percents) != 1 or not rows:
        raise ValueError(f"unexpected QM commentary shape: {percents}, {len(rows)} years")
    (pa, pc, pe), = percents
    years = sorted(rows)
    last, first_year = years[-1], years[0]
    return lookup_entry(
        "us-regulation-z-qualified-mortgage-points-and-fees-limits",
        f"United States Regulation Z qualified mortgage points-and-fees limits by loan amount tier and year, 12 CFR 1026.43(e)(3), {first_year} to {last}",
        "consumer-credit",
        f"{first_year}-01-01",
        ["regulation-z", "qualified-mortgage", "ability-to-repay", "points-and-fees", "12-cfr-1026"],
        ["mortgage-origination", "loan-pricing", "credit-risk"],
        {
            "currency": "USD",
            "tier_a_percent_of_loan": pa,
            "tier_c_percent_of_loan": pc,
            "tier_e_percent_of_loan": pe,
            "rows": rows,
        },
        [
            {"input": {"key": last, "column": "tier_a_min_loan_usd"}, "expected": rows[last]["tier_a_min_loan_usd"], "origin": "source"},
            {"input": {"key": last, "column": "tier_b_cap_usd"}, "expected": rows[last]["tier_b_cap_usd"], "origin": "source"},
            {"input": {"key": last, "column": "tier_d_cap_usd"}, "expected": rows[last]["tier_d_cap_usd"], "origin": "source"},
            {"input": {"key": first_year, "column": "tier_a_min_loan_usd"}, "expected": rows[first_year]["tier_a_min_loan_usd"], "origin": "source"},
            {"input": str(int(first_year) - 1), "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, f"Supplement I, comment 43(e)(3)(ii)-1.{len(years)}.A", f"${rows[last]['tier_a_min_loan_usd']:,}", "currency:USD", f"For a loan amount greater than or equal to ${rows[last]['tier_a_min_loan_usd']:,}: {pa} percent of the total loan amount", LICENSE, raw),
            evidence(publisher, title, url, f"Supplement I, comment 43(e)(3)(ii)-1.{len(years)}.B", f"${rows[last]['tier_b_cap_usd']:,}", "currency:USD", f"but less than ${rows[last]['tier_a_min_loan_usd']:,}: ${rows[last]['tier_b_cap_usd']:,}", LICENSE, raw),
            evidence(publisher, title, url, f"Supplement I, comment 43(e)(3)(ii)-1.{len(years)}.D", f"${rows[last]['tier_d_cap_usd']:,}", "currency:USD", f"but less than ${rows[last]['tier_c_min_loan_usd']:,}: ${rows[last]['tier_d_cap_usd']:,}", LICENSE, raw),
            version_evidence(12, "1026.43", versions_raw),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{last},tier_a_min_loan_usd]", "expected": rows[last]["tier_a_min_loan_usd"], "tolerance": 0},
            {"statistic": "max[tier_b_cap_usd]", "expected": max(r["tier_b_cap_usd"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "The points-and-fees limits a covered mortgage must stay within to be a qualified mortgage under 12 CFR "
            "1026.43(e)(3): five tiers by loan amount, with a percentage of the loan amount in tiers A, C and E and a "
            "dollar cap in tiers B and D. Tier A applies at or above tier_a_min_loan_usd, tier B from tier_b_min_loan_usd "
            "up to it, tier C from tier_c_min_loan_usd, tier D from tier_d_min_loan_usd, and tier E below that. The rows "
            "give the inflation-adjusted figures for each calendar year as the official interpretation (comment "
            f"43(e)(3)(ii)-1) lists them in the eCFR text as of {CFR_DATE}; the percentages are the same in every year."
        ),
    )


# ---------------------------------------------------------------- 12 CFR 1005: Regulation E liability limits


def reg_e_liability(raw: bytes, versions_raw: bytes, statute_raw: bytes) -> dict:
    url = part_url(12, 1005)
    publisher = f"Consumer Financial Protection Bureau {ECFR}"
    title = f"12 CFR part 1005, Electronic Fund Transfers (Regulation E), as of {CFR_DATE} (XML)"
    text = " ".join(paragraphs(section(raw, "1005.6")))
    timely_cap = money(first(r"shall not exceed the lesser of \$(\d+) or the amount of unauthorized transfers that occur before notice", text))
    late_cap = money(first(r"shall not exceed the lesser of \$(\d+) or the sum of", text))
    window = WORD_NUMBERS[first(r"notifies the financial institution within (\w+) business days after learning of the loss", text)]
    statement_days = int(first(r"within (\d+) days of the financial institution's transmittal of the statement", text))
    statute_url = "https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap41-subchapVI-sec1693g.htm"
    rows = {
        "timely_notice_liability_cap_usd": {"value": timely_cap, "unit": "USD", "section": "1005.6(b)(1)"},
        "late_notice_liability_cap_usd": {"value": late_cap, "unit": "USD", "section": "1005.6(b)(2)"},
        "notice_window_business_days": {"value": window, "unit": "business days after learning of loss or theft", "section": "1005.6(b)(1)"},
        "periodic_statement_reporting_days": {"value": statement_days, "unit": "days after transmittal of the statement", "section": "1005.6(b)(3)"},
    }
    return lookup_entry(
        "us-regulation-e-unauthorized-transfer-liability-limits",
        "United States Regulation E consumer liability limits for unauthorized electronic fund transfers, 12 CFR 1005.6(b)",
        "banking",
        latest_version(versions_raw),
        ["regulation-e", "electronic-fund-transfers", "fraud-liability", "debit-cards", "12-cfr-1005"],
        ["banking-demo", "payments-demo", "fintech-demo", "collections"],
        {"rows": rows},
        [
            {"input": {"key": "timely_notice_liability_cap_usd", "column": "value"}, "expected": timely_cap, "origin": "source"},
            {"input": {"key": "late_notice_liability_cap_usd", "column": "value"}, "expected": late_cap, "origin": "source"},
            {"input": {"key": "periodic_statement_reporting_days", "column": "value"}, "expected": statement_days, "origin": "source"},
            {"input": "notice_window_business_days", "expected": True, "origin": "source"},
            {"input": "chargeback_window_days", "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, "section 1005.6(b)(1)", f"${timely_cap}", "currency:USD", f"shall not exceed the lesser of ${timely_cap} or the amount of unauthorized transfers that occur before notice", LICENSE, raw),
            evidence(publisher, title, url, "section 1005.6(b)(2)", f"${late_cap}", "currency:USD", f"shall not exceed the lesser of ${late_cap} or the sum of", LICENSE, raw),
            evidence(publisher, title, url, "section 1005.6(b)(3)", statement_days, "integer", f"within {statement_days} days of the financial institution's transmittal of the statement", LICENSE, raw),
            version_evidence(12, "1005.6", versions_raw),
            evidence("Office of the Law Revision Counsel, US House of Representatives, via govinfo", "15 U.S.C. 1693g, Consumer liability (United States Code 2023 edition, HTML)", statute_url, "subsection (a)(1)", f"${timely_cap}", "currency:USD", f"${timely_cap}; or", LICENSE, statute_raw, role="supporting"),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[late_notice_liability_cap_usd,value]", "expected": late_cap, "tolerance": 0},
            {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "How much a consumer can be held liable for after an unauthorized electronic fund transfer under "
            "Regulation E, 12 CFR 1005.6(b): the cap when the institution is told within the notice window after the "
            "consumer learns of a lost or stolen access device, the higher cap when it is not, and the number of days "
            "after a periodic statement is sent within which an unauthorized transfer must be reported to avoid "
            f"liability for later transfers. Read from the eCFR text as of {CFR_DATE}, with the statutory source "
            "(15 U.S.C. 1693g) cited as supporting evidence. valid_from is the date of the latest version of 1005.6 "
            "in the eCFR versions endpoint."
        ),
    )


# ---------------------------------------------------------------- 45 CFR 164: HIPAA safe-harbour identifiers


def hipaa_identifiers(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(45, 164)
    publisher = f"US Department of Health and Human Services, Office for Civil Rights {ECFR}"
    title = f"45 CFR part 164, Security and Privacy, as of {CFR_DATE} (XML)"
    paras = paragraphs(section(raw, "164.514"))
    start = anchor_index(paras, "(2)(i) The following identifiers of the individual")
    full: dict[str, str] = {}
    for p in paras[start + 1 :]:
        if m := re.match(r"\(([A-R])\) (.+)$", p):
            full[m.group(1)] = m.group(2)
        elif p.startswith("(ii) The covered entity does not have actual knowledge"):
            break
    if list(full) != [chr(c) for c in range(ord("A"), ord("R") + 1)]:
        raise ValueError(f"unexpected identifier letters {list(full)}")
    labels = {}
    for letter, text in full.items():
        label = re.split(r", including|, except|;", text, maxsplit=1)[0]
        labels[letter] = label.rstrip(".").removesuffix(" and").strip()
    joined = " ".join(paras)
    zip_population = money(first(r"contains more than ([\d,]+) people", joined))
    age_limit = int(first(r"all ages over (\d+) and all elements of dates", joined))
    return {
        "id": "us-hipaa-safe-harbor-identifiers",
        "title": "United States HIPAA de-identification safe harbor: the eighteen identifiers of 45 CFR 164.514(b)(2)",
        "kind": "rule",
        "domain": "privacy",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": latest_version(versions_raw),
        "valid_to": None,
        "tags": ["hipaa", "de-identification", "phi", "safe-harbor", "code-list", "45-cfr-164"],
        "use_cases": ["health-demo", "clinical-records", "claims-generation", "person-generation"],
        "spec": {
            "implementation": "almanac.rules.enumeration",
            "parameters": {
                "zip_code_three_digit_population_threshold": zip_population,
                "age_aggregation_threshold_years": age_limit,
                "sets": {"identifiers": labels},
            },
            "vectors": [
                {"input": {"set": "identifiers", "value": "A"}, "expected": True, "origin": "source", "note": labels["A"]},
                {"input": {"set": "identifiers", "value": "G"}, "expected": True, "origin": "source", "note": labels["G"]},
                {"input": {"set": "identifiers", "value": "R"}, "expected": True, "origin": "source", "note": labels["R"]},
                {"input": {"set": "identifiers", "value": "S"}, "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(publisher, title, url, "section 164.514(b)(2)(i)(A)", "Names", "text", "(A) Names;", LICENSE, raw),
            evidence(publisher, title, url, "section 164.514(b)(2)(i)(G)", "Social security numbers", "text", "(G) Social security numbers;", LICENSE, raw),
            evidence(publisher, title, url, "section 164.514(b)(2)(i)(B)(1)", f"{zip_population:,}", "count", f"contains more than {zip_population:,} people", LICENSE, raw),
            evidence(publisher, title, url, "section 164.514(b)(2)(i)(C)", age_limit, "integer", f"all ages over {age_limit} and all elements of dates", LICENSE, raw),
            version_evidence(45, "164.514", versions_raw),
        ],
        "assumed": [
            {
                "parameter": "sets.identifiers[*]",
                "value": "label cut at the first qualifying clause",
                "method": "derived",
                "rationale": "Each label is the identifier's paragraph text up to the first ', including', ', except' or semicolon, so the long geographic and date paragraphs keep only their head clause; the regulation text is the authority for the full scope.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count[identifiers]", "expected": len(labels), "tolerance": 0},
        ],
        "notes": (
            "The identifiers a covered entity must remove from health information about an individual (and the "
            "individual's relatives, employers and household members) for the information to be de-identified under "
            "the safe harbor method of 45 CFR 164.514(b)(2), keyed by the paragraph letter A to R. The parameters "
            "also carry the population threshold below which the first three digits of a zip code must be replaced by "
            f"000 and the age above which ages must be aggregated. Read from the eCFR text as of {CFR_DATE}; valid_from "
            "is the date of the latest version of 164.514 in the eCFR versions endpoint. " + LICENSE_NOTE
        ),
    }


# ---------------------------------------------------------------- 29 CFR 1904: OSHA recordkeeping thresholds


def osha_recordkeeping(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(29, 1904)
    publisher = f"Occupational Safety and Health Administration {ECFR}"
    title = f"29 CFR part 1904, Recording and Reporting Occupational Injuries and Illnesses, as of {CFR_DATE} (XML)"
    t1 = " ".join(paragraphs(section(raw, "1904.1")))
    t39 = " ".join(paragraphs(section(raw, "1904.39")))
    t41 = " ".join(paragraphs(section(raw, "1904.41")))
    rows = {
        "size_exemption_max_employees": {"value": int(first(r"If your company had (\d+) or fewer employees at all times", t1)), "unit": "employees at all times during the last calendar year", "section": "1904.1(a)(1)"},
        "fatality_report_hours": {"value": int(first(r"Within \w+ \((\d+)\) hours after the death of any employee", t39)), "unit": "hours", "section": "1904.39(a)(1)"},
        "hospitalization_amputation_eye_loss_report_hours": {"value": int(first(r"Within [\w-]+ \((\d+)\) hours after the in-patient hospitalization", t39)), "unit": "hours", "section": "1904.39(a)(2)"},
        "fatality_reportable_days_after_incident": {"value": int(first(r"report a fatality to OSHA if the fatality occurs within \w+ \((\d+)\) days of the work-related incident", t39)), "unit": "days", "section": "1904.39(b)(6)"},
        "hospitalization_reportable_hours_after_incident": {"value": int(first(r"report the event to OSHA if it occurs within [\w-]+ \((\d+)\) hours of the work-related incident", t39)), "unit": "hours", "section": "1904.39(b)(6)"},
        "electronic_300a_min_employees_designated_industries": {"value": int(first(r"If your establishment had (\d+)-\d+ employees at any time during the previous calendar year, and your establishment is classified in an industry listed in appendix A", t41)), "unit": "employees", "section": "1904.41(a)(1)(i)"},
        "electronic_300a_max_employees_designated_industries": {"value": int(first(r"If your establishment had \d+-(\d+) employees at any time during the previous calendar year, and your establishment is classified in an industry listed in appendix A", t41)), "unit": "employees", "section": "1904.41(a)(1)(i)"},
        "electronic_300a_min_employees_all_covered_industries": {"value": int(first(r"If your establishment had (\d+) or more employees at any time during the previous calendar year, and this part requires your establishment to keep records", t41)), "unit": "employees", "section": "1904.41(a)(1)(ii)"},
        "electronic_300_and_301_min_employees_designated_industries": {"value": int(first(r"If your establishment had (\d+) or more employees at any time during the previous calendar year, and your establishment is classified in an industry listed in append", t41)), "unit": "employees", "section": "1904.41(a)(2)"},
    }
    return lookup_entry(
        "us-osha-recordkeeping-thresholds",
        "United States OSHA injury and illness recordkeeping and reporting thresholds, 29 CFR 1904",
        "employment",
        latest_version(versions_raw),
        ["osha", "workplace-safety", "recordkeeping", "incident-reporting", "29-cfr-1904"],
        ["hr-analytics", "workforce-planning", "sla-calculation", "event-timestamps"],
        {"rows": rows},
        [
            {"input": {"key": "fatality_report_hours", "column": "value"}, "expected": rows["fatality_report_hours"]["value"], "origin": "source"},
            {"input": {"key": "size_exemption_max_employees", "column": "value"}, "expected": rows["size_exemption_max_employees"]["value"], "origin": "source"},
            {"input": {"key": "electronic_300a_min_employees_all_covered_industries", "column": "value"}, "expected": rows["electronic_300a_min_employees_all_covered_industries"]["value"], "origin": "source"},
            {"input": "hospitalization_amputation_eye_loss_report_hours", "expected": True, "origin": "source"},
            {"input": "near_miss_report_hours", "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, "section 1904.1(a)(1)", rows["size_exemption_max_employees"]["value"], "integer", "If your company had 10 or fewer employees at all times during the last calendar year", LICENSE, raw),
            evidence(publisher, title, url, "section 1904.39(a)(1)", rows["fatality_report_hours"]["value"], "integer", "Within eight (8) hours after the death of any employee", LICENSE, raw),
            evidence(publisher, title, url, "section 1904.39(a)(2)", rows["hospitalization_amputation_eye_loss_report_hours"]["value"], "integer", "Within twenty-four (24) hours after the in-patient hospitalization", LICENSE, raw),
            evidence(publisher, title, url, "section 1904.41(a)(1)(ii)", rows["electronic_300a_min_employees_all_covered_industries"]["value"], "integer", "If your establishment had 250 or more employees at any time during the previous calendar year", LICENSE, raw),
            version_evidence(29, "1904.41", versions_raw),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[fatality_report_hours,value]", "expected": rows["fatality_report_hours"]["value"], "tolerance": 0},
            {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "The numeric thresholds of OSHA's injury and illness recordkeeping rule: the company size below which "
            "routine recordkeeping is not required (1904.1), the hours within which a work-related fatality and an "
            "in-patient hospitalization, amputation or loss of an eye must be reported and how long after the incident "
            "each remains reportable (1904.39), and the establishment sizes that trigger annual electronic submission "
            f"of the Form 300A summary and of the Form 300 and 301 case data (1904.41). Read from the eCFR text as of "
            f"{CFR_DATE}; valid_from is the date of the latest version of 1904.41, the most recently amended of the "
            "three sections."
        ),
    )


# ---------------------------------------------------------------- 29 CFR 825: FMLA eligibility and entitlement


def fmla_thresholds(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(29, 825)
    publisher = f"US Department of Labor, Wage and Hour Division {ECFR}"
    title = f"29 CFR part 825, The Family and Medical Leave Act of 1993, as of {CFR_DATE} (XML)"
    t104 = " ".join(paragraphs(section(raw, "825.104")))
    t110 = " ".join(paragraphs(section(raw, "825.110")))
    t200 = " ".join(paragraphs(section(raw, "825.200")))
    rows = {
        "employer_coverage_min_employees": {"value": int(first(r"who employs (\d+) or more employees for each working day", t104)), "unit": "employees for each working day", "section": "825.104(a)"},
        "employer_coverage_min_workweeks": {"value": int(first(r"during each of (\d+) or more calendar workweeks", t104)), "unit": "calendar workweeks in the current or preceding calendar year", "section": "825.104(a)"},
        "employee_min_months_employed": {"value": int(first(r"Has been employed by the employer for at least (\d+) months", t110)), "unit": "months", "section": "825.110(a)(1)"},
        "employee_min_hours_of_service": {"value": money(first(r"Has been employed for at least ([\d,]+) hours of service during the 12-month period", t110)), "unit": "hours in the preceding 12 months", "section": "825.110(a)(2)"},
        "worksite_min_employees": {"value": int(first(r"Is employed at a worksite where (\d+) or more employees are employed", t110)), "unit": "employees", "section": "825.110(a)(3)"},
        "worksite_radius_miles": {"value": int(first(r"employed by the employer within (\d+) miles of that worksite", t110)), "unit": "miles", "section": "825.110(a)(3)"},
        "break_in_service_years_not_counted": {"value": WORD_NUMBERS[first(r"prior to a break in service of (\w+) years or more need not be counted", t110)], "unit": "years", "section": "825.110(b)(1)"},
        "leave_entitlement_workweeks": {"value": int(first(r"limited to a total of (\d+) workweeks of leave during any 12-month period", t200)), "unit": "workweeks per 12-month period", "section": "825.200(a)"},
        "servicemember_caregiver_leave_workweeks": {"value": int(first(r"limited to a total of (\d+) workweeks of leave during a single 12-month period to care for a covered servicemember", t200)), "unit": "workweeks in a single 12-month period", "section": "825.200(f)"},
    }
    return lookup_entry(
        "us-fmla-eligibility-and-leave-thresholds",
        "United States FMLA employer coverage, employee eligibility and leave entitlement thresholds, 29 CFR 825",
        "employment",
        latest_version(versions_raw),
        ["fmla", "leave", "eligibility", "hr-policy", "29-cfr-825"],
        ["hr-analytics", "workforce-planning", "payroll-demo"],
        {"rows": rows},
        [
            {"input": {"key": "employee_min_hours_of_service", "column": "value"}, "expected": rows["employee_min_hours_of_service"]["value"], "origin": "source"},
            {"input": {"key": "leave_entitlement_workweeks", "column": "value"}, "expected": rows["leave_entitlement_workweeks"]["value"], "origin": "source"},
            {"input": {"key": "employer_coverage_min_employees", "column": "value"}, "expected": rows["employer_coverage_min_employees"]["value"], "origin": "source"},
            {"input": "servicemember_caregiver_leave_workweeks", "expected": True, "origin": "source"},
            {"input": "paid_leave_workweeks", "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, "section 825.104(a)", rows["employer_coverage_min_employees"]["value"], "integer", "who employs 50 or more employees for each working day", LICENSE, raw),
            evidence(publisher, title, url, "section 825.110(a)(2)", "1,250", "integer", "Has been employed for at least 1,250 hours of service", LICENSE, raw),
            evidence(publisher, title, url, "section 825.110(a)(3)", rows["worksite_radius_miles"]["value"], "integer", "Is employed at a worksite where 50 or more employees are employed by the employer within 75 miles", LICENSE, raw),
            evidence(publisher, title, url, "section 825.200(a)", rows["leave_entitlement_workweeks"]["value"], "integer", "limited to a total of 12 workweeks of leave during any 12-month period", LICENSE, raw),
            version_evidence(29, "825.110", versions_raw),
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[employee_min_hours_of_service,value]", "expected": rows["employee_min_hours_of_service"]["value"], "tolerance": 0},
            {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "The thresholds that decide whether an employer is covered by the Family and Medical Leave Act, whether "
            "an employee is eligible for leave, and how much leave the Act provides, as 29 CFR 825.104, 825.110 and "
            f"825.200 state them in the eCFR text as of {CFR_DATE}. valid_from is the date of the latest version of "
            "825.110 in the eCFR versions endpoint."
        ),
    )


# ---------------------------------------------------------------- 21 CFR 101.9: nutrition labelling daily values


def daily_values(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(21, 101)
    publisher = f"US Food and Drug Administration {ECFR}"
    title = f"21 CFR part 101, Food Labeling, as of {CFR_DATE} (XML)"
    sec = section(raw, "101.9")
    all_tables = tables(sec)
    rdi = next(t for t in all_tables if any(row[:1] == ["Nutrient"] for row in t))
    drv = next(t for t in all_tables if any(row[:1] == ["Food component"] for row in t))
    groups = ["adults_and_children_4_plus", "infants_through_12_months", "children_1_through_3", "pregnant_and_lactating"]

    def number(cell: str) -> float | int | None:
        cell = cell.strip()
        if cell == "N/A":
            return None
        # A leading footnote number precedes the value in some cells ("1 78"); keep the value.
        value = cell.split()[-1]
        return money(value)

    def clean(cell: str) -> str:
        return re.sub(r"\s\d+(?=\s|$)", "", cell).strip()

    rows: dict[str, dict] = {}
    for table, basis in ((rdi, "RDI"), (drv, "DRV")):
        for row in table:
            if len(row) != 6 or row[0] in ("Nutrient", "Food component"):
                continue
            name = clean(row[0])
            values = {group: number(cell) for group, cell in zip(groups, row[2:])}
            if name in rows:
                existing = rows[name]
                for group, value in values.items():
                    if value is not None:
                        if existing[group] is not None:
                            raise ValueError(f"conflicting values for {name} {group}")
                        existing[group] = value
                existing["basis"] = f"{existing['basis']} and {basis}"
                continue
            rows[name] = {"basis": basis, "unit": clean(row[1]), **values}
    if "Protein" not in rows or rows["Protein"]["basis"] != "RDI and DRV":
        raise ValueError("protein rows did not merge as expected")
    return lookup_entry(
        "us-fda-nutrition-label-daily-values",
        f"United States nutrition label daily values (RDI and DRV) by population group, 21 CFR 101.9(c)(8)(iv) and (c)(9) ({len(rows)} nutrients)",
        "healthcare",
        latest_version(versions_raw),
        ["nutrition", "food-labelling", "daily-values", "fda", "reference-table", "21-cfr-101"],
        ["retail-demo", "health-demo", "pricing"],
        {"rows": rows},
        [
            {"input": {"key": "Sodium", "column": "adults_and_children_4_plus"}, "expected": rows["Sodium"]["adults_and_children_4_plus"], "origin": "source"},
            {"input": {"key": "Calcium", "column": "infants_through_12_months"}, "expected": rows["Calcium"]["infants_through_12_months"], "origin": "source"},
            {"input": {"key": "Vitamin D", "column": "unit"}, "expected": rows["Vitamin D"]["unit"], "origin": "source"},
            {"input": {"key": "Protein", "column": "adults_and_children_4_plus"}, "expected": rows["Protein"]["adults_and_children_4_plus"], "origin": "source", "note": "DRV table"},
            {"input": {"key": "Protein", "column": "infants_through_12_months"}, "expected": rows["Protein"]["infants_through_12_months"], "origin": "source", "note": "RDI table"},
            {"input": "Added Sugars", "expected": True, "origin": "source"},
            {"input": "Caffeine", "expected": False, "origin": "derived"},
        ],
        [
            evidence(publisher, title, url, "section 101.9(c)(8)(iv), RDI table, Calcium row", "1,300", "integer", "Calcium", LICENSE, raw),
            evidence(publisher, title, url, "section 101.9(c)(9), DRV table, Sodium row", "2,300", "integer", "Sodium", LICENSE, raw),
            evidence(publisher, title, url, "section 101.9(c)(9), DRV table, footnote 1", "2,000", "integer", "Based on the reference caloric intake of 2,000 calories for adults and children aged 4 years and older", LICENSE, raw),
            version_evidence(21, "101.9", versions_raw),
        ],
        [
            {
                "parameter": "rows[*]",
                "value": "footnote markers removed; Protein rows merged",
                "method": "derived",
                "rationale": "Table cells carry footnote numbers before some values and after some names and units (for example '1 78' and 'Folate 6'); the builder keeps the value and drops the marker. Protein appears in both tables with complementary N/A cells, so its RDI (infants, pregnant and lactating) and DRV (adults, children 1 through 3) figures are merged into one row. N/A becomes null.",
            }
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[Sodium,adults_and_children_4_plus]", "expected": rows["Sodium"]["adults_and_children_4_plus"], "tolerance": 0},
            {"statistic": "max[adults_and_children_4_plus]", "expected": max(r["adults_and_children_4_plus"] for r in rows.values() if r["adults_and_children_4_plus"] is not None), "tolerance": 0},
        ],
        (
            "The Reference Daily Intakes for vitamins and minerals and the Daily Reference Values for food components "
            "on which the percent Daily Value of a US Nutrition Facts label is based, for the four population groups "
            "the regulation distinguishes, keyed by nutrient as the two tables in 21 CFR 101.9(c)(8)(iv) and (c)(9) "
            f"print it in the eCFR text as of {CFR_DATE}. Adult values rest on a 2,000-calorie reference intake and "
            "the children 1 through 3 values on 1,000 calories. valid_from is the date of the latest version of 101.9 "
            "in the eCFR versions endpoint."
        ),
    )


# ---------------------------------------------------------------- 20 CFR 404.409: Social Security full retirement age


def full_retirement_age(raw: bytes, versions_raw: bytes) -> dict:
    url = part_url(20, 404)
    publisher = f"Social Security Administration {ECFR}"
    title = f"20 CFR part 404, Federal Old-Age, Survivors and Disability Insurance, as of {CFR_DATE} (XML)"
    sec = section(raw, "404.409")
    table = tables(sec)[0]

    def mdy(text: str) -> str:
        return datetime.strptime(text, "%m/%d/%Y").date().isoformat()

    rows: dict[str, dict] = {}
    for row in table:
        if len(row) != 2 or row[0].startswith("If your birth date"):
            continue
        label, age = row
        years = int(first(r"(\d+) years", age))
        months = int(first(r"and (\d+) months", age)) if "months" in age else 0
        if m := re.match(r"Before (\d+/\d+/\d{4})$", label):
            born_from, born_to = None, (date.fromisoformat(mdy(m.group(1))).toordinal() - 1)
            born_to = date.fromordinal(born_to).isoformat()
        elif m := re.match(r"(\d+/\d+/\d{4})—(\d+/\d+/\d{4})$", label):
            born_from, born_to = mdy(m.group(1)), mdy(m.group(2))
        elif m := re.match(r"(\d+/\d+/\d{4}) and later$", label):
            born_from, born_to = mdy(m.group(1)), None
        else:
            raise ValueError(f"unrecognised birth date range {label!r}")
        key = f"{born_from or 'min'}/{born_to or 'max'}"
        rows[key] = {"born_from": born_from, "born_to": born_to, "years": years, "months": months, "age_in_months": years * 12 + months, "source_label": label}
    keys = list(rows)
    return lookup_entry(
        "us-social-security-full-retirement-age",
        f"United States Social Security full retirement age for old-age, wife's and husband's benefits by date of birth, 20 CFR 404.409(a) ({len(rows)} birth-date ranges)",
        "pensions",
        latest_version(versions_raw),
        ["social-security", "retirement-age", "pensions", "reference-table", "20-cfr-404"],
        ["pensions", "hr-analytics", "financial-planning", "person-generation"],
        {"rows": rows},
        [
            {"input": {"key": keys[0], "column": "years"}, "expected": rows[keys[0]]["years"], "origin": "source", "note": rows[keys[0]]["source_label"]},
            {"input": {"key": keys[-1], "column": "years"}, "expected": rows[keys[-1]]["years"], "origin": "source", "note": rows[keys[-1]]["source_label"]},
            {"input": {"key": "1955-01-02/1956-01-01", "column": "age_in_months"}, "expected": rows["1955-01-02/1956-01-01"]["age_in_months"], "origin": "source", "note": rows["1955-01-02/1956-01-01"]["source_label"]},
            {"input": "1943-01-02/1955-01-01", "expected": True, "origin": "source"},
            {"input": "1960-01-02/1961-01-01", "expected": False, "origin": "derived", "note": "the last range is open-ended"},
        ],
        [
            evidence(publisher, title, url, "section 404.409(a), table row '1/2/1960 and later'", "67 years", "text", "1/2/1960 and later", LICENSE, raw),
            evidence(publisher, title, url, "section 404.409(a), table row '1/2/1955—1/1/1956'", "66 years and 2 months", "text", "66 years and 2 months", LICENSE, raw),
            evidence(publisher, title, url, "section 404.409(a), table row 'Before 1/2/1938'", "65 years", "text", "Before 1/2/1938", LICENSE, raw),
            version_evidence(20, "404.409", versions_raw),
        ],
        [
            {
                "parameter": "rows[*].born_from, rows[*].born_to, rows[*].age_in_months",
                "value": "ISO dates and total months",
                "method": "derived",
                "rationale": "The table gives birth-date ranges as m/d/yyyy pairs; the builder converts them to ISO dates (the open ends become null and the first range ends the day before its printed bound) and adds years times twelve plus months.",
            }
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"value[{keys[-1]},age_in_months]", "expected": rows[keys[-1]]["age_in_months"], "tolerance": 0},
            {"statistic": "min[age_in_months]", "expected": min(r["age_in_months"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "The age at which unreduced old-age, wife's or husband's Social Security benefits are payable, by the "
            "beneficiary's date of birth, as the table in 20 CFR 404.409(a) prints it in the eCFR text as of "
            f"{CFR_DATE}. Rows are keyed by the ISO birth-date range (min and max for the open ends) and carry the "
            "years and months separately and as a total in months. The separate widow's and widower's table in "
            "404.409(b) is not included. valid_from is the date of the latest version of 404.409 in the eCFR versions "
            "endpoint."
        ),
    )


def main() -> int:
    write(flsa_salary(fetch(part_url(29, 541)), fetch(versions_url(29, "541.600"))))
    for entry in reg_cc_amounts(fetch(part_url(12, 229)), fetch(versions_url(12, "229.11"))):
        write(entry)
    reg_z = fetch(part_url(12, 1026))
    write(reg_z_exemption_threshold(reg_z, fetch(versions_url(12, "1026.3"))))
    write(reg_z_appraisal_threshold(reg_z, fetch(versions_url(12, "1026.35"))))
    write(hoepa_thresholds(reg_z, fetch(versions_url(12, "1026.32"))))
    write(qm_points_and_fees(reg_z, fetch(versions_url(12, "1026.43"))))
    write(reg_e_liability(fetch(part_url(12, 1005)), fetch(versions_url(12, "1005.6")), fetch("https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap41-subchapVI-sec1693g.htm")))
    write(hipaa_identifiers(fetch(part_url(45, 164)), fetch(versions_url(45, "164.514"))))
    write(osha_recordkeeping(fetch(part_url(29, 1904)), fetch(versions_url(29, "1904.41"))))
    write(fmla_thresholds(fetch(part_url(29, 825)), fetch(versions_url(29, "825.110"))))
    write(daily_values(fetch(part_url(21, 101)), fetch(versions_url(21, "101.9"))))
    write(full_retirement_age(fetch(part_url(20, 404)), fetch(versions_url(20, "404.409"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

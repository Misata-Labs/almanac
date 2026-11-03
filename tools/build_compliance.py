"""Regenerate the anti-money-laundering, consumer-protection and data-protection rule entries.

Each entry reads its thresholds, deadlines and code lists from the regulation or
statute that sets them, fetched from an official publisher and pinned to a date:

* the eCFR point-in-time API (XML) for the Bank Secrecy Act rules in 31 CFR
  chapter X, Form 8300 (26 CFR 1.6050I-1), deposit and share insurance (12 CFR
  330 and 745), Regulation F (12 CFR 1006), the TCPA rules (47 CFR 64.1200) and
  the FTC Cooling-Off, Mail Order and CAN-SPAM rules (16 CFR 429, 435, 316);
* govinfo's 2023 edition of the US Code (HTML) for the CAN-SPAM Act itself;
* legislation.gov.uk point-in-time XML (HTML where the XML is not byte-stable) for the Money Laundering Regulations
  2017, the UK GDPR and Data Protection Act 2018, the Consumer Contracts
  Regulations 2013, the Payment Services Regulations 2017, the Late Payment of
  Commercial Debts (Interest) Act 1998 and its rate order, and the PSD2
  strong customer authentication standard (EU) 2018/389 as adopted;
* the GOV.UK content API (JSON) for HM Treasury's advisory notice on
  high-risk third countries, with country codes from the World Bank API.

Every resource is fetched twice and must return identical bytes; every snippet
and value is checked against the fetched text before an entry is written. Run
from the repository root:

    uv run python tools/build_compliance.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write  # noqa: E402

ACCESSED = date(2026, 11, 3)
CFR_DATE = "2026-10-29"
LEG_DATE = "2026-10-29"
MLR_BEFORE_STERLING = "2026-06-29"
ECFR_API = "https://www.ecfr.gov/api/versioner/v1"
LEGISLATION = "https://www.legislation.gov.uk"
GOVINFO = "https://www.govinfo.gov/content/pkg"
WORLD_BANK_COUNTRIES = "https://api.worldbank.org/v2/country?format=json&per_page=400"
HMT_NOTICE = "https://www.gov.uk/api/content/government/publications/money-laundering-advisory-notice-high-risk-third-countries--2/money-laundering-advisory-notice-high-risk-third-countries--2"

UNSTATED = "unstated"
ECFR_LICENSE_NOTE = (
    "US federal government works carry no copyright, but neither the eCFR API nor the regulation text states reuse "
    "terms, so the licence is recorded as unstated and the entry held at license-review."
)
GOVINFO_LICENSE_NOTE = (
    "US federal statutes carry no copyright, but the govinfo page states no reuse terms, so the licence is recorded "
    "as unstated and the entry held at license-review."
)
LEGISLATION_LICENSE_NOTE = (
    "The legislation.gov.uk resource carries no licence statement, although the site publishes legislation under the Open "
    "Government Licence v3.0, so the licence is recorded as unstated and the entry held at license-review."
)
HTML_NOTE = (
    "Provisions are cited in legislation.gov.uk's HTML rendering, which makes the entry tier B: the XML rendering of "
    "these versions lists unapplied effects whose attributes are reordered on every render, so its bytes do not stay fixed."
)
ECFR_DATE_NOTE = (
    "valid_from is the latest version date the eCFR versions endpoint lists for the sections cited; the eCFR history "
    "starts in late 2016, so a date at that start marks the beginning of the record rather than of the rule."
)

AML_TAGS = ["compliance", "aml"]
COMPLIANCE_USE_CASES = ["aml-demo", "fraud-detection-demo", "kyc-onboarding", "banking-demo"]

_cache: dict[str, bytes] = {}


# ---------------------------------------------------------------- fetching and evidence


def get(url: str) -> bytes:
    """Fetch ``url`` twice and return its bytes, refusing a resource whose bytes differ between fetches."""
    if url not in _cache:
        first, second = fetch(url), fetch(url)
        if sha(first) != sha(second):
            raise RuntimeError(f"{url} returned different bytes on consecutive fetches")
        _cache[url] = first
    return _cache[url]


def collapse(text: str) -> str:
    return " ".join(text.split())


def ev(publisher: str, title: str, url: str, locator: str, value: Any, unit: str, snippet: str, license_id: str, role: str = "primary") -> dict:
    """An evidence item whose snippet and value are confirmed in the fetched text the way the verifier searches it."""
    raw = get(url)
    text = collapse(raw.decode("utf-8", errors="replace"))
    for label, needle in (("snippet", snippet), ("value", str(value))):
        if collapse(needle) not in text:
            raise ValueError(f"{label} {needle!r} not found in {url}")
    if len(snippet.split()) > 24:
        raise ValueError(f"snippet too long: {snippet!r}")
    item = evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role=role)
    item["accessed_at"] = ACCESSED.isoformat()
    return item


def first(pattern: str, text: str) -> re.Match:
    match = re.search(pattern, text, re.S)
    if match is None:
        raise ValueError(f"pattern {pattern!r} not found")
    return match


def money(text: str) -> int:
    return int(text.replace("$", "").replace("£", "").replace(",", ""))


WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7, "ten": 10, "thirty": 30, "fifty": 50, "third": 3, "fifth": 5}


def number(text: str) -> int:
    word = text.lower()
    return WORDS[word] if word in WORDS else int(word)


def base_rule(entry_id: str, title: str, domain: str, region: str, tier: str, status: str, valid_from: str, tags: list[str], use_cases: list[str], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], assumed: list[dict], tests: list[dict], notes: str) -> dict:
    if len(title) > 140:
        raise ValueError(f"title too long for {entry_id}")
    rendered = any(item["role"] == "primary" and is_html(item["url"]) for item in evidence_items)
    tier = "B" if rendered else tier
    if any("legislation.gov.uk" in item["url"] and is_html(item["url"]) for item in evidence_items):
        notes += " " + HTML_NOTE
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": None,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed,
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes,
    }


def lookup_vectors(rows: dict, picks: list[str], absent: str) -> list[dict]:
    """Source vectors reading the value column of selected rows, plus a membership check on each and one absent key."""
    vectors = [{"input": {"key": key, "column": "value"}, "expected": rows[key]["value"], "origin": "source"} for key in picks]
    vectors.append({"input": picks[0], "expected": True, "origin": "source"})
    vectors.append({"input": absent, "expected": False, "origin": "derived"})
    return vectors


# ---------------------------------------------------------------- eCFR


def part_url(title: int, part: int | str, section_number: str | None = None) -> str:
    url = f"{ECFR_API}/full/{CFR_DATE}/title-{title}.xml?part={part}"
    return url + (f"&section={section_number}" if section_number else "")


def versions_url(title: int, section_number: str) -> str:
    return f"{ECFR_API}/versions/title-{title}.json?section={section_number}"


def strip_tags(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def section_text(raw: bytes, number_: str) -> str:
    """Whitespace-collapsed text of one section (DIV8), one paragraph per line."""
    match = re.search(rf'<DIV8 N="{re.escape(number_)}".*?</DIV8>', raw.decode("utf-8"), re.S)
    if match is None:
        raise ValueError(f"section {number_} not found")
    paras = re.finditer(r"<(P|FP|PSPACE)(?:\s[^>]*)?>.*?</\1>", match.group(0), re.S)
    return "\n".join(collapse(strip_tags(p.group(0))) for p in paras)


def latest_version(title: int, section_number: str) -> tuple[str, dict]:
    """Latest eCFR version date of a section, with its supporting evidence item."""
    url = versions_url(title, section_number)
    raw = get(url)
    day = max(v["date"] for v in json.loads(raw)["content_versions"] if v["date"] <= CFR_DATE)
    item = ev(
        "Office of the Federal Register via the eCFR API",
        f"eCFR versions of {title} CFR {section_number} (JSON)",
        url,
        "content_versions[*].date, latest",
        day,
        "date",
        f'"date":"{day}"',
        UNSTATED,
        role="supporting",
    )
    return day, item


def cfr_source(title: int, part: int | str, publisher: str, part_title: str, section_number: str | None = None) -> Callable[..., dict]:
    """A factory of evidence items citing one eCFR part (or section) as of CFR_DATE."""
    url = part_url(title, part, section_number)
    label = f"{title} CFR {'section ' + section_number if section_number else 'part ' + str(part)}, {part_title}, as of {CFR_DATE} (XML)"

    def make(locator: str, value: Any, unit: str, snippet: str) -> dict:
        return ev(f"{publisher} via the eCFR API", label, url, locator, value, unit, snippet, UNSTATED)

    make.url = url  # type: ignore[attr-defined]
    return make


def newest(dates: list[tuple[str, dict]]) -> str:
    return max(d for d, _ in dates)


# ---------------------------------------------------------------- 31 CFR chapter X and 26 CFR 1.6050I-1: BSA thresholds


FINCEN = "Financial Crimes Enforcement Network"


def bsa_reporting_thresholds() -> dict:
    p1010 = cfr_source(31, 1010, FINCEN, "General Provisions (Bank Secrecy Act)")
    p1020 = cfr_source(31, 1020, FINCEN, "Rules for Banks")
    p1021 = cfr_source(31, 1021, FINCEN, "Rules for Casinos and Card Clubs")
    p1022 = cfr_source(31, 1022, FINCEN, "Rules for Money Services Businesses")
    p8300 = cfr_source(26, 1, "Internal Revenue Service", "Returns relating to cash in excess of $10,000 received in a trade or business", "1.6050I-1")
    r1010, r1020, r1021, r1022 = (get(part_url(31, p)) for p in (1010, 1020, 1021, 1022))
    r8300 = get(p8300.url)  # type: ignore[attr-defined]

    s311 = section_text(r1010, "1010.311")
    s313 = section_text(r1010, "1010.313")
    s306 = section_text(r1010, "1010.306")
    s340 = section_text(r1010, "1010.340")
    s410 = section_text(r1010, "1010.410")
    s415 = section_text(r1010, "1010.415")
    s430 = section_text(r1010, "1010.430")
    s230 = section_text(r1010, "1010.230")
    s100 = section_text(r1010, "1010.100")
    b410 = section_text(r1020, "1020.410")
    c311 = section_text(r1021, "1021.311")
    c313 = section_text(r1021, "1021.313")
    m380 = section_text(r1022, "1022.380")
    f8300 = section_text(r8300, "1.6050I-1")

    ctr = first(r"transaction in currency of more than (\$\d(?:[\d,]*\d)?)", s311)
    ctr_days = first(r"within (\d+) days following the day on which the reportable transaction occurred", s306)
    agg = first(r"cash in or cash out totaling more than (\$\d(?:[\d,]*\d)?) during any one business day", s313)
    cmir = first(r"monetary instruments in an aggregate amount exceeding (\$\d(?:[\d,]*\d)?) at one time from the United States", s340)
    cmir_days = first(r"1010\.340\(b\) shall be filed within (\d+) days after receipt", s306)
    fbar = first(r"foreign financial accounts exceeding (\$\d(?:[\d,]*\d)?) maintained during the previous calendar year", s306)
    credit = first(r"extension of credit in an amount in excess of (\$\d(?:[\d,]*\d)?)", s410)
    abroad = first(r"credit, of more than (\$\d(?:[\d,]*\d)?) to or from any person, account, or place outside the United States", s410)
    nonbank = first(r"with respect to a transmittal of funds in the amount of (\$\d(?:[\d,]*\d)?) or more", s410)
    travel = first(r"shall include in any transmittal order for a transmittal of funds in the amount of (\$\d(?:[\d,]*\d)?) or more", s410)
    bank_ft = first(r"with respect to a funds transfer in the amount of (\$\d(?:[\d,]*\d)?) or more", b410)
    mi = first(r"involves currency in amounts of (\$\d(?:[\d,]*\d)?)-(\$\d(?:[\d,]*\d)?) inclusive", s415)
    retention = first(r"required to be retained by this chapter shall be retained for a period of (\w+) years", s430)
    bo = first(r"owns (\d+) percent or more of the equity interests of a legal entity customer", s230)
    msb_day = first(r"sold in an amount greater than (\$\d(?:[\d,]*\d)?) to any person on any day in one or more transactions", s100)
    casino = first(r"transaction in currency, involving either cash in or cash out, of more than (\$\d(?:[\d,]*\d)?)", c311)
    casino_agg = first(r"cash in or cash out totaling more than (\$\d(?:[\d,]*\d)?) during any gaming day", c313)
    msb_initial = first(r"on or before the end of the (\d+)-day period beginning on the day following the date the business is established", m380)
    msb_period = first(r"The initial registration period is the (\w+)-calendar-year period", m380)
    msb_transfer = first(r"transfer of more than (\d+) percent of the voting power or equity interests", m380)
    f_cash = first(r"receives cash in excess of (\$\d(?:[\d,]*\d)?) in 1 transaction", f8300)
    f_days = first(r"the recipient must report the initial payment within (\d+) days of its receipt", f8300)
    f_statement = first(r"furnished to an identified person on or before (January \d+) of the year following", f8300)
    f_keep = first(r"must keep a copy of each return filed for (\w+) years from the date of filing", f8300)

    def row(value: Any, unit: str, section_: str, meaning: str) -> dict:
        return {"value": value, "unit": unit, "section": section_, "meaning": meaning}

    rows = {
        "ctr_currency_transaction_over_usd": row(money(ctr.group(1)), "USD, strictly more than", "31 CFR 1010.311", "Currency Transaction Report for a deposit, withdrawal, exchange or other payment or transfer in currency"),
        "ctr_aggregation_per_business_day_over_usd": row(money(agg.group(1)), "USD cash in or cash out per business day", "31 CFR 1010.313(b)", "Multiple currency transactions by or for one person treated as one when known to the institution"),
        "ctr_filing_days": row(number(ctr_days.group(1)), "days after the transaction", "31 CFR 1010.306(a)(1)", "Deadline to file a Currency Transaction Report"),
        "casino_ctr_currency_transaction_over_usd": row(money(casino.group(1)), "USD, strictly more than", "31 CFR 1021.311", "Casino Currency Transaction Report, cash in or cash out"),
        "casino_aggregation_per_gaming_day_over_usd": row(money(casino_agg.group(1)), "USD cash in or cash out per gaming day", "31 CFR 1021.313", "Casino aggregation of multiple currency transactions"),
        "cmir_transport_over_usd": row(money(cmir.group(1)), "USD at one time, strictly more than", "31 CFR 1010.340(a)", "Report of international transportation of currency or monetary instruments (CMIR)"),
        "cmir_receipt_filing_days": row(number(cmir_days.group(1)), "days after receipt", "31 CFR 1010.306(b)(2)", "Deadline for the recipient of unreported currency shipped from abroad"),
        "fbar_aggregate_accounts_over_usd": row(money(fbar.group(1)), "USD, strictly more than", "31 CFR 1010.306(c)", "Report of foreign financial accounts (FBAR)"),
        "credit_extension_record_over_usd": row(money(credit.group(1)), "USD, strictly more than", "31 CFR 1010.410(a)", "Record of an extension of credit not secured by real property"),
        "cross_border_transfer_record_over_usd": row(money(abroad.group(1)), "USD, strictly more than", "31 CFR 1010.410(b)", "Record of an instruction to transfer value to or from a place outside the United States"),
        "bank_funds_transfer_record_min_usd": row(money(bank_ft.group(1)), "USD, at least", "31 CFR 1020.410(a)", "Bank recordkeeping for a funds transfer"),
        "nonbank_funds_transmittal_record_min_usd": row(money(nonbank.group(1)), "USD, at least", "31 CFR 1010.410(e)", "Recordkeeping for a transmittal of funds by a financial institution other than a bank"),
        "travel_rule_min_usd": row(money(travel.group(1)), "USD, at least", "31 CFR 1010.410(f)", "Information that must travel with a transmittal order (travel rule)"),
        "monetary_instrument_cash_purchase_min_usd": row(money(mi.group(1)), "USD in currency, inclusive", "31 CFR 1010.415(a)", "Record of a cash purchase of a bank check, cashier's check, money order or traveler's check, lower bound"),
        "monetary_instrument_cash_purchase_max_usd": row(money(mi.group(2)), "USD in currency, inclusive", "31 CFR 1010.415(a)", "Upper bound of the monetary instrument recordkeeping band"),
        "msb_money_order_daily_activity_over_usd": row(money(msb_day.group(1)), "USD per person per day, strictly more than", "31 CFR 1010.100(ff)(3)(i)", "Daily amount above which an issuer or seller of traveler's checks or money orders is a money services business"),
        "record_retention_years": row(number(retention.group(1)), "years", "31 CFR 1010.430(d)", "Retention of every record the Bank Secrecy Act rules require"),
        "beneficial_owner_equity_percent": row(int(bo.group(1)), "percent of equity interests, at least", "31 CFR 1010.230(d)(1)", "Ownership prong of the beneficial owner definition for legal entity customers"),
        "msb_initial_registration_days": row(number(msb_initial.group(1)), "days after the business is established", "31 CFR 1022.380(b)(3)", "Deadline for a money services business to register with FinCEN"),
        "msb_registration_period_years": row(number(msb_period.group(1)), "calendar years", "31 CFR 1022.380(b)(2)", "Length of each registration and renewal period"),
        "msb_reregistration_transfer_over_percent": row(int(msb_transfer.group(1)), "percent of voting power or equity, strictly more than", "31 CFR 1022.380(b)(4)", "Transfer of control that requires re-registration"),
        "form_8300_cash_over_usd": row(money(f_cash.group(1)), "USD in one or related transactions, strictly more than", "26 CFR 1.6050I-1(a)(1)", "Return of cash received in a trade or business (Form 8300)"),
        "form_8300_filing_days": row(number(f_days.group(1)), "days after receipt", "26 CFR 1.6050I-1(b)(1)", "Deadline to file Form 8300"),
        "form_8300_statement_due": row(f_statement.group(1), "day of the following year", "26 CFR 1.6050I-1(f)(3)", "Annual statement to each person named in a Form 8300"),
        "form_8300_retention_years": row(number(f_keep.group(1)), "years from filing", "26 CFR 1.6050I-1(e)(3)(iii)", "Retention of a copy of each Form 8300"),
    }

    versions = [latest_version(31, s) for s in ("1010.311", "1010.313", "1010.306", "1010.340", "1010.410", "1010.415", "1010.430", "1010.230", "1020.410", "1021.311", "1021.313", "1022.380")]
    versions.append(latest_version(26, "1.6050I-1"))
    items = [
        p1010("section 1010.311", ctr.group(1), "currency:USD", ctr.group(0)),
        p1010("section 1010.313(b)", agg.group(1), "currency:USD", agg.group(0)),
        p1010("section 1010.306(a)(1)", ctr_days.group(1), "integer", ctr_days.group(0)),
        p1010("section 1010.340(a)", cmir.group(1), "currency:USD", f"in an aggregate amount exceeding {cmir.group(1)} at one time"),
        p1010("section 1010.306(c)", fbar.group(1), "currency:USD", fbar.group(0)),
        p1010("section 1010.410(e)", nonbank.group(1), "currency:USD", nonbank.group(0)),
        p1010("section 1010.410(f)", travel.group(1), "currency:USD", travel.group(0)),
        p1010("section 1010.415(a)", mi.group(1), "currency:USD", mi.group(0)),
        p1010("section 1010.430(d)", retention.group(1), "text", retention.group(0)),
        p1010("section 1010.230(d)(1)", bo.group(1), "integer", bo.group(0)),
        p1010("section 1010.100(ff)(3)(i)", msb_day.group(1), "currency:USD", msb_day.group(0)),
        p1020("section 1020.410(a)", bank_ft.group(1), "currency:USD", bank_ft.group(0)),
        p1021("section 1021.311", casino.group(1), "currency:USD", casino.group(0)),
        p1021("section 1021.313", casino_agg.group(1), "currency:USD", casino_agg.group(0)),
        p1022("section 1022.380(b)(3)", msb_initial.group(1), "integer", f"on or before the end of the {msb_initial.group(1)}-day period beginning on the day following"),
        p1022("section 1022.380(b)(4)", msb_transfer.group(1), "integer", msb_transfer.group(0)),
        p8300("section 1.6050I-1(a)(1)", f_cash.group(1), "currency:USD", f_cash.group(0)),
        p8300("section 1.6050I-1(b)(1)", f_days.group(1), "integer", f_days.group(0)),
        p8300("section 1.6050I-1(f)(3)", f_statement.group(1), "text", f_statement.group(0)),
        *[item for _, item in versions],
    ]
    picks = ["ctr_currency_transaction_over_usd", "travel_rule_min_usd", "beneficial_owner_equity_percent", "form_8300_cash_over_usd", "msb_initial_registration_days"]
    return base_rule(
        "us-bsa-reporting-thresholds",
        "United States Bank Secrecy Act reporting and recordkeeping thresholds: CTR, CMIR, FBAR, travel rule, beneficial ownership and Form 8300",
        "compliance",
        "US",
        "A",
        "license-review",
        newest(versions),
        [*AML_TAGS, "bank-secrecy-act", "currency-transaction-report", "travel-rule", "beneficial-ownership", "form-8300", "31-cfr-1010"],
        [*COMPLIANCE_USE_CASES, "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"currency": "USD", "rows": rows},
        lookup_vectors(rows, picks, "ctr_currency_transaction_at_least_usd"),
        items,
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[ctr_currency_transaction_over_usd,value]", "expected": rows["ctr_currency_transaction_over_usd"]["value"], "tolerance": 0},
            {"statistic": "value[travel_rule_min_usd,value]", "expected": rows["travel_rule_min_usd"]["value"], "tolerance": 0},
        ],
        (
            "The dollar thresholds, filing deadlines and retention periods that transaction-monitoring and AML systems "
            "enforce under the Bank Secrecy Act rules in 31 CFR chapter X, and the parallel IRS rule for cash received in "
            "a trade or business (26 CFR 1.6050I-1, Form 8300), read from the eCFR text as of "
            f"{CFR_DATE}. Each row names its section; the unit says whether the threshold is 'more than' or 'at least', "
            "which matters at the boundary (a CTR is due for $10,000.01 but not for exactly $10,000; the travel rule "
            "applies from exactly $3,000). Suspicious activity report thresholds differ by institution type and sit in "
            "their own entry, us-bsa-sar-thresholds-by-institution; the instalment rule for Form 8300 is executable in "
            "us-form-8300-installment-reporting. The FBAR row is the account-balance threshold only; the filing date in "
            "the regulation text is not reproduced because the statutory due date has since moved. "
            + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


SAR_INSTITUTIONS = [
    ("bank", 1020, "Rules for Banks", "bank"),
    ("casino_or_card_club", 1021, "Rules for Casinos and Card Clubs", "casino"),
    ("money_services_business", 1022, "Rules for Money Services Businesses", "money services business"),
    ("broker_dealer", 1023, "Rules for Brokers or Dealers in Securities", "broker-dealer"),
    ("mutual_fund", 1024, "Rules for Mutual Funds", "mutual fund"),
    ("insurance_company", 1025, "Rules for Insurance Companies", "insurance company"),
    ("futures_commission_merchant_or_introducing_broker", 1026, "Rules for Futures Commission Merchants and Introducing Brokers in Commodities", "FCM or IB-C"),
    ("loan_or_finance_company", 1029, "Rules for Loan or Finance Companies", "loan or finance company"),
    ("housing_gse", 1030, "Rules for Housing Government Sponsored Enterprises", "housing government sponsored enterprise"),
]


def bsa_sar_thresholds() -> dict:
    rows: dict[str, dict] = {}
    items: list[dict] = []
    versions: list[tuple[str, dict]] = []
    for key, part, part_title, _label in SAR_INSTITUTIONS:
        source = cfr_source(31, part, FINCEN, part_title)
        text = section_text(get(part_url(31, part)), f"{part}.320")
        threshold = first(r"(?:aggregates|involves or aggregates)(?: funds or other assets of)? at least (\$\d(?:[\d,]*\d)?)", text)
        deadline = first(r"no later than (\d+) calendar days after the date of (?:the )?initial detection", text)
        extension = re.search(r"in no case shall reporting be delayed more than (\d+) calendar days", text, re.I)
        retention = first(r"for a period of (\w+) years from the date of filing", text)
        rows[key] = {
            "threshold_usd": money(threshold.group(1)),
            "filing_deadline_days": int(deadline.group(1)),
            "max_deadline_without_suspect_days": int(extension.group(1)) if extension else None,
            "retention_years": number(retention.group(1)),
            "section": f"31 CFR {part}.320",
        }
        items.append(source(f"section {part}.320(a)(2)", threshold.group(1), "currency:USD", f"at least {threshold.group(1)}"))
        if key in ("bank", "money_services_business"):
            items.append(source(f"section {part}.320(b)(3)", deadline.group(1), "integer", deadline.group(0)))
        if key == "bank" and extension:
            items.append(source(f"section {part}.320(b)(3)", extension.group(1), "integer", extension.group(0)))
        versions.append(latest_version(31, f"{part}.320"))
    msb = section_text(get(part_url(31, 1022)), "1022.320")
    issuer = first(r"issuer of money orders or traveler's checks shall only be required to report a transaction or pattern of transactions that involves or aggregates funds or other assets of at least (\$\d(?:[\d,]*\d)?)", msb)
    rows["money_order_or_travelers_check_issuer_clearance_review"] = {
        "threshold_usd": money(issuer.group(1)),
        "filing_deadline_days": rows["money_services_business"]["filing_deadline_days"],
        "max_deadline_without_suspect_days": None,
        "retention_years": rows["money_services_business"]["retention_years"],
        "section": "31 CFR 1022.320(a)(3)",
    }
    items.append(cfr_source(31, 1022, FINCEN, "Rules for Money Services Businesses")("section 1022.320(a)(3)", issuer.group(1), "currency:USD", f"involves or aggregates funds or other assets of at least {issuer.group(1)}"))
    items.extend(item for _, item in versions)
    vectors = [
        {"input": {"key": "bank", "column": "threshold_usd"}, "expected": rows["bank"]["threshold_usd"], "origin": "source"},
        {"input": {"key": "money_services_business", "column": "threshold_usd"}, "expected": rows["money_services_business"]["threshold_usd"], "origin": "source"},
        {"input": {"key": "bank", "column": "max_deadline_without_suspect_days"}, "expected": rows["bank"]["max_deadline_without_suspect_days"], "origin": "source"},
        {"input": {"key": "money_services_business", "column": "max_deadline_without_suspect_days"}, "expected": None, "origin": "source", "note": "1022.320 has no extension for an unidentified suspect"},
        {"input": {"key": "insurance_company", "column": "filing_deadline_days"}, "expected": rows["insurance_company"]["filing_deadline_days"], "origin": "source"},
        {"input": "credit_union", "expected": False, "origin": "derived", "note": "credit unions file under the bank rule in part 1020"},
    ]
    return base_rule(
        "us-bsa-sar-thresholds-by-institution",
        "United States suspicious activity report thresholds, filing deadlines and retention by institution type, 31 CFR 1020-1030",
        "compliance",
        "US",
        "A",
        "license-review",
        newest(versions),
        [*AML_TAGS, "bank-secrecy-act", "suspicious-activity-report", "transaction-monitoring", "31-cfr-chapter-x"],
        [*COMPLIANCE_USE_CASES, "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"currency": "USD", "rows": rows},
        vectors,
        items,
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "min[threshold_usd]", "expected": min(r["threshold_usd"] for r in rows.values()), "tolerance": 0},
            {"statistic": "max[filing_deadline_days]", "expected": max(r["filing_deadline_days"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "The amount at which a known or suspected suspicious transaction, or pattern of transactions, must be reported "
            "on a SAR, the number of calendar days after initial detection within which it must be filed, the longest delay "
            "allowed when no suspect has been identified, and how long the SAR and its supporting documents must be kept, "
            "for each institution type with a SAR rule in 31 CFR chapter X, read from the eCFR text as of "
            f"{CFR_DATE}. Money services businesses have a lower threshold and no extension for an unidentified suspect; "
            "an issuer of money orders or traveler's checks reviewing clearance records reports only from the higher "
            "amount in its own row. Credit unions and other depository institutions file under the bank rule. Thresholds "
            "are 'at least' amounts and include aggregated transactions. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


def form_8300_installments() -> dict:
    source = cfr_source(26, 1, "Internal Revenue Service", "Returns relating to cash in excess of $10,000 received in a trade or business", "1.6050I-1")
    text = section_text(get(source.url), "1.6050I-1")  # type: ignore[attr-defined]
    threshold = first(r"receives cash in excess of (\$\d(?:[\d,]*\d)?) in 1 transaction", text)
    days = first(r"the recipient must report the initial payment within (\d+) days of its receipt", text)
    window = first(r"previously unreportable payments made within a (\d+)-month period", text)
    example = first(
        r"On (January \d+, \d{4}), M receives an initial cash payment of (\$\d(?:[\d,]*\d)?) with respect to a transaction\. "
        r"M receives subsequent cash payments with respect to the same transaction of (\$\d(?:[\d,]*\d)?) on (\w+ \d+), \d{4}, "
        r"(\$\d(?:[\d,]*\d)?) on (\w+ \d+), \d{4}, and (\$\d(?:[\d,]*\d)?) on (\w+ \d+), (\d{4})\. M must make a report with respect to the "
        r"payment received on \w+ \d+, \d{4}, by (\w+ \d+, \d{4})\..*?This report must be made by (\w+ \d+, \d{4})",
        text,
    )
    year = example.group(9)

    def day(text_: str) -> str:
        return datetime.strptime(text_ if "," in text_ else f"{text_}, {year}", "%B %d, %Y").date().isoformat()

    payments = [
        {"date": day(example.group(1)), "amount": money(example.group(2))},
        {"date": day(example.group(4)), "amount": money(example.group(3))},
        {"date": day(example.group(6)), "amount": money(example.group(5))},
        {"date": day(example.group(8)), "amount": money(example.group(7))},
    ]
    later = sum(p["amount"] for p in payments[1:])
    expected = [
        {"triggered_on": payments[0]["date"], "due_by": day(example.group(10)), "amount": payments[0]["amount"]},
        {"triggered_on": payments[3]["date"], "due_by": day(example.group(11)), "amount": later},
    ]
    totals = first(r"report with respect to the payments totalling (\$\d(?:[\d,]*\d)?)", text)
    if money(totals.group(1)) != later:
        raise ValueError("the worked example's total does not match its payments")
    parameters = {
        "currency": "USD",
        "threshold": money(threshold.group(1)),
        "report_within_days": int(days.group(1)),
        "aggregation_window_months": int(window.group(1)),
        "related_transactions_window_hours": int(first(r"recipient of cash in a (\d+)-hour period", text).group(1)),
        "section": "26 CFR 1.6050I-1(b)",
    }
    versions = latest_version(26, "1.6050I-1")
    return base_rule(
        "us-form-8300-installment-reporting",
        "United States Form 8300 reporting of cash received in instalments: twelve-month aggregation and fifteen-day deadline, 26 CFR 1.6050I-1(b)",
        "compliance",
        "US",
        "A",
        "license-review",
        versions[0],
        [*AML_TAGS, "form-8300", "cash-reporting", "aggregation", "26-cfr-1-6050i-1"],
        [*COMPLIANCE_USE_CASES, "retail-demo", "invoicing"],
        "almanac.rules.us_form_8300",
        parameters,
        [
            {"input": {"payments": payments}, "expected": expected, "origin": "source", "note": "worked example in 26 CFR 1.6050I-1(b)(4)"},
            {"input": {"amount": payments[0]["amount"]}, "expected": True, "origin": "source"},
            {"input": {"amount": parameters["threshold"]}, "expected": False, "origin": "derived", "note": "the threshold must be exceeded"},
            {"input": {"payments": [{"date": "2026-01-05", "amount": 6000}, {"date": "2027-01-05", "amount": 6000}]}, "expected": [], "origin": "derived", "note": "the second payment falls on the first anniversary, outside the window"},
            {"input": {"payments": [{"date": "2026-01-05", "amount": 6000}, {"date": "2027-01-04", "amount": 6000}]}, "expected": [{"triggered_on": "2027-01-04", "due_by": "2027-01-19", "amount": 12000}], "origin": "derived"},
        ],
        [
            source("section 1.6050I-1(a)(1)", threshold.group(1), "currency:USD", threshold.group(0)),
            source("section 1.6050I-1(b)(1)", days.group(1), "integer", days.group(0)),
            source("section 1.6050I-1(b)(3)", window.group(1), "integer", window.group(0)),
            source("section 1.6050I-1(b)(4), example", example.group(10), "text", f"M must make a report with respect to the payment received on {example.group(1)}, by {example.group(10)}"),
            source("section 1.6050I-1(b)(4), example", example.group(11), "text", f"This report must be made by {example.group(11)}"),
            versions[1],
        ],
        [
            {
                "parameter": "window boundary",
                "value": "a payment on the first anniversary of the earliest unreported payment falls outside the window",
                "method": "derived",
                "rationale": "The regulation says 'within one year of the initial payment' and 'within a 12-month period' without fixing the boundary day; the rule treats the anniversary itself as outside, and the two derived vectors exercise that choice.",
            }
        ],
        [
            {"statistic": "threshold", "expected": parameters["threshold"], "tolerance": 0},
            {"statistic": "report_within_days", "expected": parameters["report_within_days"], "tolerance": 0},
        ],
        (
            "Executable form of the multiple-payment rule for Form 8300 (26 U.S.C. 6050I): a business receiving cash for one "
            "transaction, or related transactions, reports within the stated number of days once the cash exceeds the "
            "threshold, and again each time later unreported payments received within a twelve-month window exceed it. "
            "Replaying the payment history returns each report with the day it was triggered, its due date and the amount "
            "it covers. The first vector is the regulation's own worked example: an initial payment above the threshold, "
            "then three smaller payments that cross it together. The option to combine several reports falling due within "
            "one filing period is not modelled. 'Related transactions' are those between the same payer and recipient within "
            "the stated number of hours, or a longer series the recipient knows to be connected; grouping payments into one "
            "transaction is left to the caller. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- 12 CFR 330 and 745: deposit and share insurance


def joint_example(text: str) -> list[dict]:
    """The three co-owner outcomes of the joint account example, with each co-owner's interests."""
    out = []
    for owner in ("A", "B", "C"):
        match = first(rf"{owner}'s combined ownership interest in all qualifying joint accounts would be (\$\d(?:[\d,]*\d)?) \(([^)]*)\); therefore, {owner}'s interest would be (fully insured|insured in the amount of (\$\d(?:[\d,]*\d)?) and uninsured in the amount of (\$\d(?:[\d,]*\d)?))", text)
        interests = [money(m) for m in re.findall(r"\$\d(?:[\d,]*\d)?", match.group(2))]
        total = money(match.group(1))
        if sum(interests) != total:
            raise ValueError("joint example components do not add up")
        insured = total if match.group(3) == "fully insured" else money(match.group(4))
        uninsured = 0 if match.group(3) == "fully insured" else money(match.group(5))
        out.append({"owner": owner, "interests": interests, "insured": insured, "uninsured": uninsured})
    return out


def fdic_coverage() -> dict:
    source = cfr_source(12, 330, "Federal Deposit Insurance Corporation", "Deposit Insurance Coverage")
    raw = get(source.url)  # type: ignore[attr-defined]
    s1 = section_text(raw, "330.1")
    s9 = section_text(raw, "330.9")
    s10 = section_text(raw, "330.10")
    s14 = section_text(raw, "330.14")
    smdia = first(r"Standard maximum deposit insurance amount, referred to as the “SMDIA” hereafter, means (\$\d(?:[\d,]*\d)?) adjusted", s1)
    cap = first(r"multiplied by the total number of beneficiaries identified by each grantor, up to a maximum of (\d+) beneficiaries", s10)
    retirement = first(r"aggregated and insured in the amount of up to (\$\d(?:[\d,]*\d)?) per participant", s14)
    joint = joint_example(s9)
    limit = money(smdia.group(1))
    if money(retirement.group(1)) != limit:
        raise ValueError("certain retirement account limit differs from the SMDIA")
    parameters = {
        "currency": "USD",
        "insurer": "FDIC",
        "standard_maximum": limit,
        "trust_rule": {"method": "per_beneficiary_capped", "max_beneficiaries": int(cap.group(1)), "section": "12 CFR 330.10(b)(1)"},
        "categories": {
            "single": {"basis": "aggregate", "section": "12 CFR 330.6", "scope": "individual, sole proprietorship, single-name community property and decedent accounts"},
            "joint": {"basis": "aggregate", "section": "12 CFR 330.9", "scope": "each co-owner's interests in all qualifying joint accounts"},
            "trust": {"basis": "per_beneficiary", "section": "12 CFR 330.10", "scope": "informal and formal revocable trusts and irrevocable trusts, aggregated per grantor"},
            "business": {"basis": "aggregate", "section": "12 CFR 330.11", "scope": "corporation, partnership or unincorporated association engaged in an independent activity"},
            "certain_retirement": {"basis": "aggregate", "section": "12 CFR 330.14(b)(2)", "scope": "IRAs and the other self-directed retirement accounts listed, per participant"},
            "employee_benefit_plan": {"basis": "aggregate", "section": "12 CFR 330.14(a)", "scope": "pass-through coverage of each participant's non-contingent interest"},
            "government": {"basis": "aggregate", "section": "12 CFR 330.15", "scope": "per official custodian; time and savings deposits and demand deposits are insured separately"},
        },
    }
    joint_vectors = [
        {"input": {"category": "joint", "interests": j["interests"]}, "expected": {"insured": j["insured"], "uninsured": j["uninsured"]}, "origin": "source", "note": f"co-owner {j['owner']} in the 12 CFR 330.9(b) example"}
        for j in joint
    ]
    beneficiaries = parameters["trust_rule"]["max_beneficiaries"]
    versions = [latest_version(12, s) for s in ("330.1", "330.9", "330.10")]
    return base_rule(
        "us-fdic-deposit-insurance-coverage",
        "United States FDIC deposit insurance coverage by ownership category, 12 CFR 330",
        "banking",
        "US",
        "A",
        "license-review",
        newest(versions),
        ["compliance", "deposit-insurance", "fdic", "ownership-categories", "12-cfr-330"],
        ["banking-demo", "customer-service-demo", "data-quality-validation", "personal-finance"],
        "almanac.rules.us_deposit_insurance",
        parameters,
        [
            *joint_vectors,
            {"input": {"category": "trust", "beneficiaries": 3, "balance": 900000}, "expected": {"coverage": 3 * limit, "insured": 3 * limit, "uninsured": 900000 - 3 * limit}, "origin": "derived"},
            {"input": {"category": "trust", "beneficiaries": beneficiaries + 2}, "expected": {"coverage": beneficiaries * limit}, "origin": "derived", "note": "beneficiaries beyond the cap add no coverage"},
            {"input": {"category": "single", "interests": [limit]}, "expected": {"insured": limit, "uninsured": 0}, "origin": "source"},
        ],
        [
            source("section 330.1(o)", smdia.group(1), "currency:USD", f"means {smdia.group(1)} adjusted pursuant to subparagraph (F)"),
            source("section 330.10(b)(1)", cap.group(1), "integer", f"up to a maximum of {cap.group(1)} beneficiaries"),
            source("section 330.9(b), example", "$50,000", "currency:USD", "A's interest would be insured in the amount of $250,000 and uninsured in the amount of $50,000"),
            source("section 330.14(b)(2)", retirement.group(1), "currency:USD", retirement.group(0)),
            *[item for _, item in versions],
        ],
        [],
        [
            {"statistic": "standard_maximum", "expected": limit, "tolerance": 0},
            {"statistic": "count", "expected": len(parameters["categories"]), "tolerance": 0},
        ],
        (
            "How much of a depositor's money the FDIC insures at one bank: the standard maximum deposit insurance amount "
            "(SMDIA) applies separately to each ownership category, aggregating a depositor's interests within it; trust "
            "deposits are insured at the SMDIA per eligible beneficiary up to a cap on beneficiaries per grantor, under the "
            "simplified trust rule effective in 2024. The joint account vectors are the regulation's own example. Government "
            "deposits are insured per official custodian, with demand deposits and time and savings deposits counted "
            "separately; pass the relevant subset as interests. Read from the eCFR text as of "
            f"{CFR_DATE}. The NCUA's share insurance rules for credit unions are in us-ncua-share-insurance-coverage and "
            "differ for trusts. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


def ncua_coverage() -> dict:
    source = cfr_source(12, 745, "National Credit Union Administration", "Share Insurance and Appendix")
    raw = get(source.url)  # type: ignore[attr-defined]
    s1 = section_text(raw, "745.1")
    s4 = section_text(raw, "745.4")
    s8 = section_text(raw, "745.8")
    smsia = first(r"“standard maximum share insurance amount,” referred to as the “SMSIA” hereafter, means (\$\d(?:[\d,]*\d)?) adjusted", s1)
    limit = money(smsia.group(1))
    ex_a1 = first(r"living trust account with (\w+) different beneficiaries named in the trust\. A has no other revocable trust accounts at the same NCUA-insured credit union\. The maximum insurance coverage would be (\$\d(?:[\d,]*\d)?)", s4)
    ex_a3 = first(r"living trust account with a balance of (\$\d(?:[\d,]*\d)?), naming his two children “B” and “C” as beneficiaries\. A also establishes, at the same NCUA-insured credit union, a payable-on-death account, with a balance of (\$\d(?:[\d,]*\d)?), also naming his children B and C as beneficiaries\. The maximum coverage available to A is (\$\d(?:[\d,]*\d)?).*?A is uninsured in the amount of (\$\d(?:[\d,]*\d)?)", s4)
    ex_e1 = first(r"A's aggregated balance of (\$\d(?:[\d,]*\d)? million) is more than five times the SMDIA, A names only (\w+) different beneficiaries.*?A is insured in the amount of (\$\d(?:[\d,]*\d)? million) \(4 beneficiaries times the SMSIA\), and uninsured for the remaining (\$\d(?:[\d,]*\d)? million)", s4)
    ex_e2 = first(r"living trust account with a balance of (\$\d(?:[\d,]*\d)?)\. Under the terms of the trust, upon A's death, A's three children are each entitled to (\$\d(?:[\d,]*\d)?), A's friend is entitled to (\$\d(?:[\d,]*\d)?), and a designated charity is entitled to (\$\d(?:[\d,]*\d)?)\. The trust also provides that the remainder of the trust assets shall belong to A's spouse\..*?spouse's (\$\d(?:[\d,]*\d)?) is subject to.*?the maximum coverage afforded to the account owner would be (\$\d(?:[\d,]*\d)?), the greater of", s4)
    ex_f1 = first(r"The maximum coverage afforded to A and B would be (\$\d(?:[\d,]*\d)?), determined by multiplying the number of owners \((\d+)\) times the SMSIA \(\$\d(?:[\d,]*\d)?\) times the number of different beneficiaries \((\d+)\)", s4)
    floor = first(r"naming more than (\w+) different beneficiaries and whose aggregate balance is more than five times the SMSIA", s4)

    def millions(text_: str) -> int:
        return int(float(text_.replace("$", "").replace(" million", "").replace(",", "")) * 1_000_000)

    joint = joint_example(s8)
    child, friend, charity, spouse = (money(ex_e2.group(i)) for i in (2, 3, 4, 5))
    parameters = {
        "currency": "USD",
        "insurer": "NCUA",
        "standard_maximum": limit,
        "trust_rule": {"method": "per_beneficiary_with_floor", "floor_beneficiaries": number(floor.group(1)), "section": "12 CFR 745.4(a) and (e)"},
        "categories": {
            "single": {"basis": "aggregate", "section": "12 CFR 745.3", "scope": "individual accounts and accounts held by agents or nominees"},
            "joint": {"basis": "aggregate", "section": "12 CFR 745.8", "scope": "each co-owner's interests in all qualifying joint accounts"},
            "trust": {"basis": "per_beneficiary", "section": "12 CFR 745.4", "scope": "revocable trust accounts, including payable-on-death and living trust accounts"},
            "business": {"basis": "aggregate", "section": "12 CFR 745.6", "scope": "corporation, partnership or unincorporated association engaged in an independent activity"},
            "employee_benefit_plan": {"basis": "aggregate", "section": "12 CFR 745.9-2", "scope": "pass-through coverage of each participant's non-contingent interest"},
            "government": {"basis": "aggregate", "section": "12 CFR 745.10", "scope": "per official custodian"},
        },
    }
    vectors = [
        *[
            {"input": {"category": "joint", "interests": j["interests"]}, "expected": {"insured": j["insured"], "uninsured": j["uninsured"]}, "origin": "source", "note": f"co-owner {j['owner']} in the 12 CFR 745.8(b) example"}
            for j in joint
        ],
        {"input": {"category": "trust", "beneficiaries": number(ex_a1.group(1))}, "expected": {"coverage": money(ex_a1.group(2))}, "origin": "source", "note": "745.4(a) example 1"},
        {
            "input": {"category": "trust", "beneficiaries": 2, "balance": money(ex_a3.group(1)) + money(ex_a3.group(2))},
            "expected": {"coverage": money(ex_a3.group(3)), "insured": money(ex_a3.group(3)), "uninsured": money(ex_a3.group(4))},
            "origin": "source",
            "note": "745.4(a) example 3",
        },
        {
            "input": {"category": "trust", "beneficiaries": number(ex_e1.group(2)), "balance": millions(ex_e1.group(1))},
            "expected": {"coverage": millions(ex_e1.group(3)), "insured": millions(ex_e1.group(3)), "uninsured": millions(ex_e1.group(4))},
            "origin": "source",
            "note": "745.4(e) example 1: more than five times the SMSIA but only four beneficiaries",
        },
        {
            "input": {"category": "trust", "beneficiary_interests": [child, child, child, friend, charity, spouse], "balance": money(ex_e2.group(1))},
            "expected": {"coverage": money(ex_e2.group(6)), "insured": money(ex_e2.group(6)), "uninsured": money(ex_e2.group(1)) - money(ex_e2.group(6))},
            "origin": "source",
            "note": "745.4(e) example 2: six beneficiaries, floor of five times the SMSIA applies",
        },
        {"input": {"category": "trust", "beneficiaries": int(ex_f1.group(3)), "owners": int(ex_f1.group(2))}, "expected": {"coverage": money(ex_f1.group(1))}, "origin": "source", "note": "745.4(f) example 1: co-owned account"},
    ]
    versions = [latest_version(12, s) for s in ("745.1", "745.4", "745.8")]
    return base_rule(
        "us-ncua-share-insurance-coverage",
        "United States NCUA share insurance coverage by ownership category for federally insured credit unions, 12 CFR 745",
        "banking",
        "US",
        "A",
        "license-review",
        newest(versions),
        ["compliance", "deposit-insurance", "share-insurance", "credit-unions", "ncua", "12-cfr-745"],
        ["banking-demo", "customer-service-demo", "data-quality-validation", "personal-finance"],
        "almanac.rules.us_deposit_insurance",
        parameters,
        vectors,
        [
            source("section 745.1(e)", smsia.group(1), "currency:USD", f"means {smsia.group(1)} adjusted pursuant to subparagraph (F)"),
            source("section 745.4(a), example 1", ex_a1.group(2), "currency:USD", f"The maximum insurance coverage would be {ex_a1.group(2)}, determined by multiplying 4 times"),
            source("section 745.4(e), example 2", ex_e2.group(6), "currency:USD", f"the maximum coverage afforded to the account owner would be {ex_e2.group(6)}, the greater of"),
            source("section 745.4(f), example 1", ex_f1.group(1), "currency:USD", f"The maximum coverage afforded to A and B would be {ex_f1.group(1)}"),
            *[item for _, item in versions],
        ],
        [],
        [
            {"statistic": "standard_maximum", "expected": limit, "tolerance": 0},
            {"statistic": "count", "expected": len(parameters["categories"]), "tolerance": 0},
        ],
        (
            "How much of a member's shares the NCUA insures at one federally insured credit union: the standard maximum "
            "share insurance amount (SMSIA) applies separately to each ownership category. Revocable trust accounts are "
            "insured at the SMSIA per different beneficiary, per owner; when more than five beneficiaries are named and an "
            "owner's trust balance exceeds five times the SMSIA, coverage is the greater of five times the SMSIA and the sum "
            "of each beneficiary's interest capped at the SMSIA. Every vector is one of the regulation's own examples. Read "
            f"from the eCFR text as of {CFR_DATE}. Unlike the FDIC's trust rule (us-fdic-deposit-insurance-coverage), the "
            "number of beneficiaries is not capped. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- 12 CFR 1006: Regulation F call frequency


def regulation_f() -> dict:
    source = cfr_source(12, 1006, "Consumer Financial Protection Bureau", "Debt Collection Practices (Regulation F)")
    raw = get(source.url)  # type: ignore[attr-defined]
    s14 = section_text(raw, "1006.14")
    s6 = section_text(raw, "1006.6")
    s34 = section_text(raw, "1006.34")
    markup = raw.decode("utf-8")
    supplement = collapse(html.unescape(re.sub(r"<[^>]+>", " ", markup[markup.find("Supplement I to Part 1006") :])))
    calls = first(r"More than (\w+) times within (\w+) consecutive days", s14)
    after = first(r"Within a period of (\w+) consecutive days after having had a telephone conversation", s14)
    hours = first(r"a time before (\d+):00 a\.m\. and after (\d+):00 p\.m\. local time at the consumer's location is inconvenient", s6)
    validation = first(r"ending (\d+) days after the consumer receives or is assumed to receive the validation information", s34)
    receipt = first(r"on any date that is at least (\w+) days \(excluding legal public holidays", s34)
    first(r"On Wednesday, April 1, a debt collector first attempts to communicate with a consumer in connection with the collection of a credit card debt", supplement)
    bad_i = first(r"The debt collector has placed a total of (\w+) telephone calls to the consumer about the debt during the seven-day period starting Wednesday, April 1", supplement)
    bad_ii = first(r"if the debt collector places a telephone call to the consumer in connection with the collection of that debt again prior to Friday, August (\d+)", supplement)
    ok_ii = first(r"does not place a telephone call to the consumer in connection with the collection of that debt again prior to Thursday, August (\d+)", supplement)
    parameters = {
        "max_calls_in_window": number(calls.group(1)),
        "call_window_days": number(calls.group(2)),
        "post_conversation_days": number(after.group(1)),
        "convenient_from": f"{int(hours.group(1)):02d}:00",
        "convenient_until": f"{int(hours.group(2)) + 12:02d}:00",
        "validation_period_days_after_receipt": int(validation.group(1)),
        "assumed_receipt_business_days": number(receipt.group(1)),
        "sections": {"call_frequency": "12 CFR 1006.14(b)(2)", "inconvenient_times": "12 CFR 1006.6(b)(1)(i)", "validation_period": "12 CFR 1006.34(b)(5)"},
    }
    april = [f"2026-04-0{d}" for d in range(1, 8)]
    vectors = [
        {"input": {"calls": april[:6], "proposed": april[6]}, "expected": True, "origin": "source", "note": "comment 14(b)(2)(i)-1.i: the seventh call within seven days"},
        {"input": {"calls": april, "proposed": "2026-04-08"}, "expected": True, "origin": "source", "note": "comment 14(b)(2)(i)-1.i: the next call on April 8"},
        {
            "input": {"calls": ["2026-04-01", "2026-04-02", "2026-04-02", "2026-04-03", "2026-04-03", "2026-04-06", "2026-04-06"], "proposed": "2026-04-07"},
            "expected": False,
            "origin": "source",
            "note": f"comment 14(b)(2)(ii)-1.i: {bad_i.group(1)} calls in the seven days from April 1",
        },
        {"input": {"calls": ["2026-08-11", "2026-08-14"], "conversations": ["2026-08-14"], "proposed": f"2026-08-{int(bad_ii.group(1)) - 1}"}, "expected": False, "origin": "source", "note": "comment 14(b)(2)(ii)-1.ii: a call before Friday, August 21"},
        {"input": {"calls": ["2026-08-11", "2026-08-14"], "conversations": ["2026-08-14"], "proposed": f"2026-08-{bad_ii.group(1)}"}, "expected": True, "origin": "source", "note": "comment 14(b)(2)(ii)-1.ii: the first day after the seven-day period"},
        {"input": {"conversations": ["2026-08-13"], "proposed": f"2026-08-{ok_ii.group(1)}"}, "expected": True, "origin": "source", "note": "comment 14(b)(2)(i)-1.ii: consumer-initiated conversation on Thursday, August 13"},
        {"input": {"local_time": "07:59"}, "expected": True, "origin": "derived"},
        {"input": {"local_time": "21:00"}, "expected": False, "origin": "derived", "note": "only times after 9:00 p.m. are presumed inconvenient"},
        {"input": {"local_time": "21:01"}, "expected": True, "origin": "derived"},
    ]
    versions = [latest_version(12, s) for s in ("1006.14", "1006.6", "1006.34")]
    return base_rule(
        "us-regulation-f-call-frequency",
        "United States Regulation F debt collection call frequency presumptions and inconvenient calling times, 12 CFR 1006.14 and 1006.6",
        "compliance",
        "US",
        "A",
        "license-review",
        newest(versions),
        ["compliance", "consumer-protection", "regulation-f", "fdcpa", "debt-collection", "call-frequency", "12-cfr-1006"],
        ["collections", "customer-service-demo", "crm-demo", "data-quality-validation"],
        "almanac.rules.us_regf_call_frequency",
        parameters,
        vectors,
        [
            source("section 1006.14(b)(2)(i)(A)", calls.group(1), "text", calls.group(0)),
            source("section 1006.14(b)(2)(i)(B)", after.group(1), "text", after.group(0)),
            source("section 1006.6(b)(1)(i)", f"{hours.group(1)}:00 a.m.", "text", f"a time before {hours.group(1)}:00 a.m. and after {hours.group(2)}:00 p.m. local time"),
            source("section 1006.34(b)(5)", validation.group(1), "integer", validation.group(0)),
            source("Supplement I, comment 14(b)(2)(ii)-1.i", bad_i.group(1), "text", f"The debt collector has placed a total of {bad_i.group(1)} telephone calls to the consumer about the debt"),
            source("Supplement I, comment 14(b)(2)(ii)-1.ii", f"August {bad_ii.group(1)}", "text", f"again prior to Friday, August {bad_ii.group(1)}"),
            *[item for _, item in versions],
        ],
        [
            {
                "parameter": "vector dates",
                "value": "2026",
                "method": "derived",
                "rationale": "The official interpretation's examples give weekdays and days of the month but no year; 2026 is a year in which every weekday named (Wednesday, April 1; Thursday, August 13; Friday, August 14) matches. Where an example says only that six calls were placed between April 2 and April 7, one call a day is assumed.",
            }
        ],
        [
            {"statistic": "max_calls_in_window", "expected": parameters["max_calls_in_window"], "tolerance": 0},
            {"statistic": "post_conversation_days", "expected": parameters["post_conversation_days"], "tolerance": 0},
        ],
        (
            "Regulation F presumes a debt collector complies with the ban on repeated or continuous calls when, for one "
            "person and one debt, it places no more than the stated number of calls within any run of consecutive days, and "
            "no call within the run of days starting on the day of a telephone conversation; exceeding either presumes a "
            "violation. The rule answers whether one more call on a given day stays inside the presumption, given the dates "
            "of earlier counted calls and conversations; leave out calls the regulation excludes (made with the person's "
            "direct prior consent, not connected, or to the persons listed in 1006.6(d)). It also says whether a local time "
            "is presumed inconvenient. The parameters record the validation period: it ends the stated number of days after "
            "the consumer receives the validation information, which may be assumed to happen a set number of business days "
            "after it is provided. Most vectors are the CFPB's own examples from Supplement I to part 1006. "
            + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- 47 CFR 64.1200: TCPA


FCC = "Federal Communications Commission"


def tcpa() -> tuple[dict, dict]:
    source = cfr_source(47, 64, FCC, "Delivery restrictions (Telephone Consumer Protection Act rules)", "64.1200")
    raw = get(source.url)  # type: ignore[attr-defined]
    text = section_text(raw, "64.1200")
    hours = first(r"before the hour of (\d+) a\.m\. or after (\d+) p\.m\. \(local time at the called party's location\)", text)
    dnc = first(r"This period may not exceed (\w+) \((\d+)\) business days from the receipt of such request", text)
    revoke = first(r"must be honored within a reasonable time not to exceed (\w+) business days from receipt of such request", text)
    registry = first(r"obtained from the administrator of the registry no more than (\d+) days prior to the date any call is made", text)
    abandon = first(r"Abandon more than (\w+) percent of all telemarketing calls that are answered live by a person, as measured over a (\d+)-day period", text)
    ring = first(r"Disconnect an unanswered telemarketing call prior to at least (\d+) seconds or (\w+) \((\d+)\) rings", text)
    connect = first(r"within (\w+) \((\d+)\) seconds after the called person's completed greeting", text)
    residential = first(r"Is not made for a commercial purpose and the caller makes no more than (\w+) calls within any consecutive (\d+)-day period", text)
    fax = first(r"must honor that request within the shortest reasonable time from the date of such request, not to exceed (\d+) days", text)
    keywords_match = first(r"using the words (.*?) sent in reply to an incoming text message", text)
    keywords = re.findall(r"“([^”]+?),?”", keywords_match.group(1))

    def row(value: Any, unit: str, section_: str) -> dict:
        return {"value": value, "unit": unit, "section": section_}

    rows = {
        "calling_window_start_hour": row(int(hours.group(1)), "hour, local time at the called party", "47 CFR 64.1200(c)(1)"),
        "calling_window_end_hour": row(int(hours.group(2)) + 12, "hour, local time at the called party (24-hour clock)", "47 CFR 64.1200(c)(1)"),
        "do_not_call_request_honor_business_days": row(int(dnc.group(2)), "business days from receipt", "47 CFR 64.1200(d)(3)"),
        "consent_revocation_honor_business_days": row(number(revoke.group(1)), "business days from receipt", "47 CFR 64.1200(a)(10)"),
        "national_registry_max_age_days": row(int(registry.group(1)), "days before the call", "47 CFR 64.1200(c)(2)(i)(D)"),
        "abandonment_rate_max_percent": row(number(abandon.group(1)), "percent of live-answered calls per campaign", "47 CFR 64.1200(a)(7)"),
        "abandonment_measurement_days": row(int(abandon.group(2)), "days", "47 CFR 64.1200(a)(7)"),
        "unanswered_call_min_ring_seconds": row(int(ring.group(1)), "seconds", "47 CFR 64.1200(a)(6)"),
        "unanswered_call_min_rings": row(int(ring.group(3)), "rings", "47 CFR 64.1200(a)(6)"),
        "live_agent_connect_max_seconds": row(int(connect.group(2)), "seconds after the called person's greeting", "47 CFR 64.1200(a)(7)(i)"),
        "noncommercial_residential_max_calls": row(number(residential.group(1)), f"calls per consecutive {residential.group(2)}-day period", "47 CFR 64.1200(a)(3)(ii)"),
        "fax_opt_out_honor_days": row(int(fax.group(1)), "days", "47 CFR 64.1200(a)(4)(v)"),
    }
    day, version_item = latest_version(47, "64.1200")
    items = [
        source("section 64.1200(c)(1)", f"{hours.group(1)} a.m.", "text", hours.group(0)),
        source("section 64.1200(d)(3)", dnc.group(2), "integer", dnc.group(0)),
        source("section 64.1200(a)(10)", revoke.group(1), "text", revoke.group(0)),
        source("section 64.1200(c)(2)(i)(D)", registry.group(1), "integer", f"no more than {registry.group(1)} days prior to the date any call is made"),
        source("section 64.1200(a)(7)", abandon.group(1), "text", f"Abandon more than {abandon.group(1)} percent of all telemarketing calls"),
        source("section 64.1200(a)(6)", ring.group(1), "integer", ring.group(0)),
        version_item,
    ]
    limits = base_rule(
        "us-tcpa-calling-limits",
        "United States TCPA telemarketing limits: calling hours, do-not-call and revocation deadlines, abandonment rate, 47 CFR 64.1200",
        "compliance",
        "US",
        "A",
        "license-review",
        day,
        ["compliance", "consumer-protection", "tcpa", "telemarketing", "do-not-call", "47-cfr-64"],
        ["customer-service-demo", "crm-demo", "collections", "telecom-demo", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        lookup_vectors(rows, ["calling_window_start_hour", "do_not_call_request_honor_business_days", "abandonment_rate_max_percent"], "calling_window_weekend_rule"),
        items,
        [
            {
                "parameter": "calling_window_end_hour",
                "value": rows["calling_window_end_hour"]["value"],
                "method": "derived",
                "rationale": "The regulation says 9 p.m.; the row restates it on a 24-hour clock.",
            }
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[calling_window_end_hour,value]", "expected": rows["calling_window_end_hour"]["value"], "tolerance": 0},
        ],
        (
            "The numeric limits the FCC's Telephone Consumer Protection Act rules set for telephone solicitation and "
            "telemarketing, read from 47 CFR 64.1200 as of "
            f"{CFR_DATE}: no telephone solicitation to a residential subscriber before the window opens or after it closes "
            "(local time at the called party's location), the business days within which a company-specific do-not-call "
            "request and a revocation of consent must be honoured, how fresh a copy of the national do-not-call registry "
            "must be, the maximum abandoned-call rate per calling campaign and the period over which it is measured, how "
            "long an unanswered call must ring, how quickly a live agent or message must follow the called person's greeting, "
            "the call limit for exempt non-commercial calls to a residential line, and the fax opt-out deadline. Each limit "
            "has conditions and exemptions in the section it cites. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )
    words = {k: k for k in keywords}
    keyword_rule = base_rule(
        "us-tcpa-consent-revocation-keywords",
        "United States TCPA reply words that revoke consent to robocalls and robotexts per se, 47 CFR 64.1200(a)(10)",
        "compliance",
        "US",
        "A",
        "license-review",
        day,
        ["compliance", "consumer-protection", "tcpa", "opt-out", "sms", "47-cfr-64"],
        ["customer-service-demo", "crm-demo", "digital-channels", "data-quality-validation"],
        "almanac.rules.enumeration",
        {"sets": {"per_se_revocation_words": words}, "honor_within_business_days": number(revoke.group(1)), "section": "47 CFR 64.1200(a)(10)"},
        [
            {"input": {"set": "per_se_revocation_words", "value": "stop"}, "expected": True, "origin": "source"},
            {"input": {"set": "per_se_revocation_words", "value": "unsubscribe"}, "expected": True, "origin": "source"},
            {"input": {"set": "per_se_revocation_words", "value": "opt out"}, "expected": True, "origin": "source"},
            {"input": {"set": "per_se_revocation_words", "value": "STOP"}, "expected": False, "origin": "derived", "note": "the set holds the words in the regulation's lower case; normalise case before testing"},
            {"input": {"set": "per_se_revocation_words", "value": "pause"}, "expected": False, "origin": "derived"},
        ],
        [
            source("section 64.1200(a)(10)", "unsubscribe", "text", "sent in reply to an incoming text message; or pursuant to a website or telephone number designated by the caller"),
            source("section 64.1200(a)(10)", revoke.group(1), "text", revoke.group(0)),
            version_item,
        ],
        [],
        [{"statistic": "count[per_se_revocation_words]", "expected": len(words), "tolerance": 0}],
        (
            "The words that, sent in reply to an incoming text message, revoke prior express consent to robocalls and "
            "robotexts per se under the FCC's TCPA rules, read from 47 CFR 64.1200(a)(10) as of "
            f"{CFR_DATE}. Other replies must still be treated as revocation when a reasonable person would understand them "
            "that way, and any reasonable method of revoking counts; the list is the set a caller can never refuse. "
            "Revocations must be honoured within the business days recorded in the parameters. Matching should ignore case "
            "and surrounding whitespace. valid_from is the latest version of 64.1200 in the eCFR versions endpoint, not the "
            "date the paragraph was added. " + ECFR_LICENSE_NOTE
        ),
    )
    return limits, keyword_rule


# ---------------------------------------------------------------- 16 CFR 429, 435 and 316; 15 U.S.C. 7704


FTC = "Federal Trade Commission"


def cooling_off() -> dict:
    source = cfr_source(16, 429, FTC, "Rule Concerning Cooling-Off Period for Sales Made at Homes or at Certain Other Locations")
    raw = get(source.url)  # type: ignore[attr-defined]
    s0 = section_text(raw, "429.0")
    s1 = section_text(raw, "429.1")
    prices = first(r"purchase price of (\$\d+) or more if the sale is made at the buyer's residence or a purchase price of (\$\d+) or more if the sale is made at locations other than the buyer's residence", s0)
    cancel = first(r"prior to midnight of the (\w+) business day after the date of this transaction", s1)
    refund = first(r"Fail or refuse to honor any valid notice of cancellation by a buyer and within (\d+) business days after the receipt of such notice", s1)
    assign = first(r"prior to midnight of the (\w+) business day following the day the contract was signed", s1)
    goods = first(r"Fail, within (\d+) business days of receipt of the buyer's notice of cancellation, to notify the buyer whether the seller intends to repossess", s1)
    rows = {
        "residence_sale_min_price_usd": {"value": money(prices.group(1)), "unit": "USD, at least", "section": "16 CFR 429.0(a)"},
        "other_location_sale_min_price_usd": {"value": money(prices.group(2)), "unit": "USD, at least", "section": "16 CFR 429.0(a)"},
        "cancellation_business_days": {"value": number(cancel.group(1)), "unit": "business days after the transaction, until midnight", "section": "16 CFR 429.1(a)"},
        "refund_business_days": {"value": int(refund.group(1)), "unit": "business days after the cancellation notice", "section": "16 CFR 429.1(g)"},
        "goods_disposition_notice_business_days": {"value": int(goods.group(1)), "unit": "business days after the cancellation notice", "section": "16 CFR 429.1(i)"},
        "note_assignment_earliest_business_day": {"value": number(assign.group(1)), "unit": "business day after signing, from midnight", "section": "16 CFR 429.1(h)"},
    }
    versions = [latest_version(16, s) for s in ("429.0", "429.1")]
    return base_rule(
        "us-ftc-cooling-off-rule",
        "United States FTC Cooling-Off Rule: price thresholds for door-to-door sales and the three-day cancellation right, 16 CFR 429",
        "compliance",
        "US",
        "A",
        "license-review",
        newest(versions),
        ["compliance", "consumer-protection", "cooling-off", "door-to-door-sales", "cancellation", "16-cfr-429"],
        ["retail-demo", "customer-service-demo", "invoicing", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"currency": "USD", "rows": rows},
        lookup_vectors(rows, ["residence_sale_min_price_usd", "other_location_sale_min_price_usd", "cancellation_business_days"], "online_sale_min_price_usd"),
        [
            source("section 429.0(a)", prices.group(1), "currency:USD", f"which has a purchase price of {prices.group(1)} or more if the sale is made at the buyer's residence"),
            source("section 429.0(a)", prices.group(2), "currency:USD", f"a purchase price of {prices.group(2)} or more if the sale is made at locations other than the buyer's residence"),
            source("section 429.1(a)", cancel.group(1), "text", cancel.group(0)),
            source("section 429.1(g)", refund.group(1), "integer", f"within {refund.group(1)} business days after the receipt of such notice"),
            *[item for _, item in versions],
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[other_location_sale_min_price_usd,value]", "expected": rows["other_location_sale_min_price_usd"]["value"], "tolerance": 0},
        ],
        (
            "The FTC Cooling-Off Rule gives a buyer the right to cancel a door-to-door sale, which includes sales at the "
            "buyer's home and at temporary locations such as hotel rooms, convention centres and fairgrounds, until midnight "
            "of the third business day after the transaction, when the price reaches the threshold for where the sale was "
            "made. The seller must then refund and return trade-ins within the stated business days and may not assign the "
            "buyer's note before the stated business day. Read from 16 CFR 429 as of "
            f"{CFR_DATE}. Exclusions (emergency repairs the buyer waives in writing, sales after negotiation at the seller's "
            "permanent premises, and others) are in 429.0(a). " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


def mail_order() -> dict:
    source = cfr_source(16, 435, FTC, "Mail, Internet, or Telephone Order Merchandise")
    raw = get(source.url)  # type: ignore[attr-defined]
    s1 = section_text(raw, "435.1")
    s2 = section_text(raw, "435.2")
    text = s1 + "\n" + s2
    ship = first(r"If no time is clearly and conspicuously stated, within (\w+) \((\d+)\) days after receipt of a properly completed order from the buyer", text)
    credit = first(r"the seller shall have (\w+) \((\d+)\) days, rather than thirty \(30\) days", text)
    refund = first(r"first class mail within (\w+) \((\d+)\) working days of the date on which the buyer's right to refund vests", text)
    cycle = first(r"first class mail within (\w+) \((\d+)\) billing cycle from the date on which the buyer's right to refund vests", text)
    delay = first(r"definite revised shipping date which is (\w+) \((\d+)\) days or less later than the applicable time", text)
    rows = {
        "default_shipment_days": {"value": int(ship.group(2)), "unit": "days after a properly completed order", "section": "16 CFR 435.2(a)(1)(ii)"},
        "credit_application_shipment_days": {"value": int(credit.group(2)), "unit": "days after the order when the buyer applies for credit", "section": "16 CFR 435.2(a)(1)(ii)"},
        "refund_working_days": {"value": int(refund.group(2)), "unit": "working days after the right to a refund vests", "section": "16 CFR 435.1(b)(1)"},
        "credit_refund_billing_cycles": {"value": int(cycle.group(2)), "unit": "billing cycles after the right to a refund vests", "section": "16 CFR 435.1(b)(2)"},
        "deemed_consent_delay_max_days": {"value": int(delay.group(2)), "unit": "days beyond the original shipment time", "section": "16 CFR 435.2(b)(1)(ii)"},
    }
    versions = [latest_version(16, s) for s in ("435.1", "435.2")]
    return base_rule(
        "us-ftc-mail-order-rule-time-limits",
        "United States FTC Mail, Internet or Telephone Order Rule shipment and refund time limits, 16 CFR 435",
        "compliance",
        "US",
        "A",
        "license-review",
        newest(versions),
        ["compliance", "consumer-protection", "mail-order", "e-commerce", "shipping", "refunds", "16-cfr-435"],
        ["retail-demo", "logistics", "customer-service-demo", "sla-calculation", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        lookup_vectors(rows, ["default_shipment_days", "credit_application_shipment_days", "refund_working_days"], "return_window_days"),
        [
            source("section 435.2(a)(1)(ii)", ship.group(2), "integer", ship.group(0)),
            source("section 435.2(a)(1)(ii)", credit.group(2), "integer", f"the seller shall have {credit.group(1)} ({credit.group(2)}) days"),
            source("section 435.1(b)(1)", refund.group(2), "integer", f"within {refund.group(1)} ({refund.group(2)}) working days of the date on which the buyer's right to refund vests"),
            source("section 435.1(b)(2)", cycle.group(2), "integer", f"within {cycle.group(1)} ({cycle.group(2)}) billing cycle from the date"),
            *[item for _, item in versions],
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0},
        ],
        (
            "Time limits the FTC Mail, Internet, or Telephone Order Merchandise Rule sets for remote sales, read from 16 CFR "
            f"435 as of {CFR_DATE}: a seller that states no shipping time must ship within the default number of days, or the "
            "longer period when the buyer applies to the seller for credit; a delay beyond that requires offering the buyer "
            "the option to cancel, with consent deemed given only for a short revised delay; refunds are due within the "
            "stated working days, or one billing cycle when the refund is a credit to a credit account. Useful for order, "
            "shipment and refund timestamps that stay within the rule. " + ECFR_DATE_NOTE + " " + ECFR_LICENSE_NOTE
        ),
    )


def can_spam() -> dict:
    url = f"{GOVINFO}/USCODE-2023-title15/html/USCODE-2023-title15-chap103-sec7704.htm"
    raw = get(url)
    text = collapse(strip_tags(raw.decode("utf-8")))
    honor = first(r"more than (\d+) business days after the receipt of such request", text)
    mechanism = first(r"remains capable of receiving such messages or communications for no less than (\d+) days after the transmission of the original message", text)
    effective = first(r"Section effective (Jan\. 1, 2004)", text)
    cfr = cfr_source(16, 316, FTC, "CAN-SPAM Rule")
    s4 = section_text(get(cfr.url), "316.4")  # type: ignore[attr-defined]
    label = first(r"include in the subject heading the phrase “(SEXUALLY-EXPLICIT: )” in capital letters as the first (\w+) \((\d+)\) characters", s4)
    rows = {
        "opt_out_honor_business_days": {"value": int(honor.group(1)), "unit": "business days after the opt-out request", "section": "15 U.S.C. 7704(a)(4)(A)"},
        "opt_out_mechanism_min_days": {"value": int(mechanism.group(1)), "unit": "days after the message is sent", "section": "15 U.S.C. 7704(a)(3)(A)(ii)"},
        "sexually_explicit_subject_prefix": {"value": label.group(1), "unit": "exact text, first characters of the subject line", "section": "16 CFR 316.4(a)(1)"},
        "sexually_explicit_prefix_length": {"value": int(label.group(3)), "unit": "characters", "section": "16 CFR 316.4(a)(1)"},
    }
    if len(rows["sexually_explicit_subject_prefix"]["value"]) != rows["sexually_explicit_prefix_length"]["value"]:
        raise ValueError("CAN-SPAM label length does not match the stated character count")
    statute = "Office of the Law Revision Counsel, US House of Representatives, via govinfo"
    statute_title = "15 U.S.C. 7704, Other protections for users of commercial electronic mail (United States Code 2023 edition, HTML)"
    version_day, version_item = latest_version(16, "316.4")
    return base_rule(
        "us-can-spam-opt-out-requirements",
        "United States CAN-SPAM Act opt-out deadlines and the sexually explicit subject label, 15 U.S.C. 7704 and 16 CFR 316.4",
        "compliance",
        "US",
        "B",
        "license-review",
        datetime.strptime(effective.group(1), "%b. %d, %Y").date().isoformat(),
        ["compliance", "consumer-protection", "can-spam", "email-marketing", "opt-out", "15-usc-7704"],
        ["digital-channels", "crm-demo", "customer-service-demo", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        lookup_vectors(rows, ["opt_out_honor_business_days", "opt_out_mechanism_min_days", "sexually_explicit_subject_prefix"], "double_opt_in_days"),
        [
            ev(statute, statute_title, url, "subsection (a)(4)(A)(i)", honor.group(1), "integer", honor.group(0), UNSTATED),
            ev(statute, statute_title, url, "subsection (a)(3)(A)(ii)", mechanism.group(1), "integer", mechanism.group(0), UNSTATED),
            ev(statute, statute_title, url, "Effective Date note", effective.group(1), "text", f"Section effective {effective.group(1)}", UNSTATED),
            cfr("section 316.4(a)(1)", label.group(3), "integer", f"in capital letters as the first {label.group(2)} ({label.group(3)}) characters"),
            version_item,
        ],
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[opt_out_honor_business_days,value]", "expected": rows["opt_out_honor_business_days"]["value"], "tolerance": 0},
        ],
        (
            "The CAN-SPAM Act's deadlines for commercial email: a sender may not send further commercial email to a recipient "
            "more than the stated business days after receiving an opt-out request, and the opt-out mechanism in each "
            "message must keep working for at least the stated number of days after it is sent. The FTC's rule adds the exact "
            "label that must open the subject line of a message containing sexually explicit material (with its trailing "
            "space). The statute is read from govinfo's HTML of the 2023 US Code, which makes the entry tier B; valid_from is "
            f"the section's effective date as the Code's note records it. The FTC rule text is as of {CFR_DATE}, and its "
            f"latest eCFR version is {version_day}. " + GOVINFO_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- legislation.gov.uk


TNA = "The National Archives (legislation.gov.uk)"


def leg_url(path: str, on: str = LEG_DATE, rendering: str = "data.html") -> str:
    """The stable rendering of a provision: XML, or HTML when the XML carries unapplied effects.

    legislation.gov.uk writes the attributes of each ukm:UnappliedEffect element in a different order every time it
    renders a document, so an XML response listing unapplied effects keeps its bytes only while a cached copy
    lasts. The HTML renderings of the same version are deterministic and one is cited instead: ``data.html`` by
    default, ``data.xht`` where the former omits tables.
    """
    xml = f"{LEGISLATION}/{path}/{on}/data.xml"
    return xml.replace("data.xml", rendering) if b"UnappliedEffect" in get(xml) else xml


def is_html(url: str) -> bool:
    return url.endswith((".html", ".htm", ".xht"))


def leg_text(raw: bytes) -> str:
    """Provision text from legislation.gov.uk XML or HTML, whitespace collapsed, without commentary or note markers."""
    markup = raw.decode("utf-8")
    if markup.lstrip().startswith("<?xml") and "<Legislation" in markup[:2000]:
        start = min(i for i in (markup.find(tag) for tag in ("<Body", "<EUBody", "<Schedules")) if i >= 0)
        end = markup.find("<Commentaries")
        markup = markup[start : end if end > 0 else None]
    else:
        markup = re.sub(r"<a class=\"noteRef[^\"]*\"[^>]*>[^<]*</a>", "", markup)
        markup = re.sub(r"<(script|style|head)\b.*?</\1>", " ", markup, flags=re.S)
    return collapse(html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def provision_start(url: str, raw: bytes) -> tuple[str, str]:
    """Start date of the provision's current version and the markup that states it."""
    pattern = r'data-x-restrict-start-date="(\d{4}-\d{2}-\d{2})"' if is_html(url) else r'P1group[^>]*RestrictStartDate="(\d{4}-\d{2}-\d{2})"'
    match = first(pattern, raw.decode("utf-8"))
    return match.group(1), match.group(0)


def leg_source(path: str, title: str, on: str = LEG_DATE, rendering: str = "data.html") -> Callable[..., dict]:
    url = leg_url(path, on, rendering)
    version = {"made": "as made", "adopted": "as adopted"}.get(on, f"version of {on}")
    label = f"{title} (legislation.gov.uk {'HTML' if is_html(url) else 'XML'}, {version})"

    def make(locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        return ev(TNA, label, url, locator, value, unit, snippet, UNSTATED, role=role)

    def start() -> tuple[str, dict]:
        day, markup = provision_start(url, get(url))
        return day, make("restrict start date of the provision (start of its current version)", day, "date", markup, role="supporting")

    make.url = url  # type: ignore[attr-defined]
    make.start = start  # type: ignore[attr-defined]
    return make


def lead_in(match: re.Match) -> str:
    """The words of a match that precede its first group: text that locates an amount without crossing its markup."""
    words = match.group(0)[: match.start(1) - match.start(0)].replace("£", "").split()
    return " ".join(words[-16:])


def leg_number(text: str) -> int:
    return int(text.replace(",", ""))


MLR = "The Money Laundering, Terrorist Financing and Transfer of Funds (Information on the Payer) Regulations 2017"


def mlr_thresholds() -> dict:
    now = leg_source("uksi/2017/692/regulation/27", f"{MLR}, regulation 27")
    before = leg_source("uksi/2017/692/regulation/27", f"{MLR}, regulation 27", MLR_BEFORE_STERLING)
    r40 = leg_source("uksi/2017/692/regulation/40", f"{MLR}, regulation 40")
    t_now = leg_text(get(now.url))  # type: ignore[attr-defined]
    t_before = leg_text(get(before.url))  # type: ignore[attr-defined]
    t40 = leg_text(get(r40.url))  # type: ignore[attr-defined]
    patterns = {
        "transfer_of_funds_over": (r"transfer of funds within the meaning of Article 3\.9 of the funds transfer regulation exceeding {amount}", "27(1)(b)", "Occasional transaction that is a transfer of funds, strictly more than"),
        "occasional_transaction": (r"carries out an occasional transaction that amounts to {amount} or more, whether the transaction is executed in a single operation", "27(2)", "Occasional transaction by any relevant person other than those with their own threshold, at least"),
        "high_value_dealer_cash": (r"carries out an occasional transaction in cash that amounts to {amount} or more", "27(3)", "High value dealer cash transaction, at least"),
        "casino": (r"any transaction within paragraph \(6\) that amounts to {amount} or more", "27(5)", "Casino stake or collection of winnings, at least"),
        "letting_agent_monthly_rent": (r"equivalent to, a monthly rent of {amount} or more", "27(7A)", "Letting agent: monthly rent, at least"),
        "art_market_transaction": (r"whose value amounts to {amount} or more;", "27(7C)(a)", "Art market participant trade in a work of art, at least"),
        "freeport_art_storage": (r"stored for a person, or series of linked persons, amounts to {amount} or more", "27(7C)(b)", "Freeport operator storing works of art, at least"),
        "cryptoasset_transfer": (r"equal to or exceeds the equivalent in cryptoassets of {amount} in value", "27(7E)", "Cryptoasset transfer, at least"),
    }
    gbp, eur = r"£(\d(?:[\d,]*\d)?) ?", r"([\d,]+) euros"
    rows: dict[str, dict] = {}
    items: list[dict] = []
    for key, (pattern, paragraph, meaning) in patterns.items():
        new = first(pattern.format(amount=gbp), t_now)
        old = first(pattern.format(amount=eur), t_before)
        rows[key] = {"value": leg_number(new.group(1)), "currency": "GBP", "before_2026_06_30_value": leg_number(old.group(1)), "before_2026_06_30_currency": "EUR", "regulation": paragraph, "meaning": meaning}
        if key in ("occasional_transaction", "high_value_dealer_cash", "casino", "transfer_of_funds_over"):
            items.append(now(f"regulation {paragraph}", f"£{new.group(1)}", "currency:GBP", lead_in(new)))
            items.append(before(f"regulation {paragraph}", f"{old.group(1)} euros", "currency:EUR", lead_in(old)))
    keep = first(r"the period is (\w+) years beginning on the date on which the relevant person knows", t40)
    cap = first(r"is not required to keep the records referred to in paragraph \(3\)\(b\)\(i\) for more than (\d+) years", t40)
    rows["record_retention_years"] = {"value": number(keep.group(1)), "currency": None, "before_2026_06_30_value": None, "before_2026_06_30_currency": None, "regulation": "40(3)", "meaning": "Years after the business relationship or occasional transaction ends"}
    rows["record_retention_max_years"] = {"value": int(cap.group(1)), "currency": None, "before_2026_06_30_value": None, "before_2026_06_30_currency": None, "regulation": "40(4)", "meaning": "Longest period records of the business relationship need be kept"}
    raw_now = get(now.url).decode("utf-8")  # type: ignore[attr-defined]
    substituted = first(r"substituted \((\d+\.\d+\.\d{4})\) by", raw_now)
    if substituted.group(1) != "30.6.2026":
        raise ValueError("unexpected substitution date for the sterling thresholds")
    start_day, start_item = now.start()  # type: ignore[attr-defined]
    items.extend(
        [
            r40("regulation 40(3)", keep.group(1), "text", keep.group(0)),
            r40("regulation 40(4)", cap.group(1), "integer", f"for more than {cap.group(1)} years"),
            now("commentary on the substituted sums", substituted.group(1), "text", substituted.group(0), role="supporting"),
            start_item,
        ]
    )
    vectors = [
        {"input": {"key": "occasional_transaction", "column": "value"}, "expected": rows["occasional_transaction"]["value"], "origin": "source"},
        {"input": {"key": "high_value_dealer_cash", "column": "value"}, "expected": rows["high_value_dealer_cash"]["value"], "origin": "source"},
        {"input": {"key": "casino", "column": "value"}, "expected": rows["casino"]["value"], "origin": "source"},
        {"input": {"key": "occasional_transaction", "column": "before_2026_06_30_value"}, "expected": rows["occasional_transaction"]["before_2026_06_30_value"], "origin": "source"},
        {"input": "record_retention_years", "expected": True, "origin": "source"},
        {"input": "politically_exposed_person", "expected": False, "origin": "derived"},
    ]
    return base_rule(
        "gb-mlr-2017-cdd-thresholds",
        "United Kingdom Money Laundering Regulations 2017 customer due diligence thresholds and record retention, sterling from 30 June 2026",
        "compliance",
        "GB",
        "A",
        "license-review",
        start_day,
        [*AML_TAGS, "kyc", "customer-due-diligence", "money-laundering-regulations", "high-value-dealer", "casino"],
        [*COMPLIANCE_USE_CASES, "kyb-onboarding", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        vectors,
        items,
        [],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[occasional_transaction,value]", "expected": rows["occasional_transaction"]["value"], "tolerance": 0},
            {"statistic": "value[cryptoasset_transfer,value]", "expected": rows["cryptoasset_transfer"]["value"], "tolerance": 0},
        ],
        (
            "The transaction sizes at which a business regulated by the UK Money Laundering Regulations 2017 must apply "
            "customer due diligence to an occasional transaction (regulation 27), and how long it must keep due diligence "
            "and transaction records (regulation 40). The Money Laundering and Terrorist Financing (Amendment) Regulations "
            "2026 replaced the euro amounts with sterling amounts from 30 June 2026; each row gives the sterling value now "
            "in force and the euro value it replaced, read from legislation.gov.uk's point-in-time versions of regulation 27 "
            f"as of {LEG_DATE} and {MLR_BEFORE_STERLING}. Linked transactions count together. Regulation 27(7D) applies due "
            "diligence to every transaction at a cryptoasset exchange machine regardless of amount. valid_from is the start "
            "of regulation 27's current version. " + LEGISLATION_LICENSE_NOTE
        ),
    )


def mlr_emoney() -> dict:
    now = leg_source("uksi/2017/692/regulation/38", f"{MLR}, regulation 38")
    before = leg_source("uksi/2017/692/regulation/38", f"{MLR}, regulation 38", MLR_BEFORE_STERLING)
    t_now, t_before = leg_text(get(now.url)), leg_text(get(before.url))  # type: ignore[attr-defined]
    patterns = {
        "max_stored_value": (r"the maximum amount which can be stored electronically is {amount}", "38(1)(a)", "Largest amount the instrument can hold"),
        "reloadable_monthly_limit": (r"maximum limit on monthly payment transactions of {amount} which can only be used in the United Kingdom", "38(1)(b)(ii)", "Monthly payment limit for a reloadable instrument used only in the UK"),
        "cash_redemption_over": (r"the amount redeemed exceeds {amount}; or", "38(2)(a)", "Cash redemption or withdrawal above which the exemption does not apply"),
        "remote_redemption_per_transaction_over": (r"the amount redeemed exceeds {amount} per transaction", "38(2)(b)", "Remote payment redemption per transaction above which the exemption does not apply"),
    }
    gbp, eur = r"£(\d+) ?", r"(\d+) euros ?"
    rows: dict[str, dict] = {}
    items: list[dict] = []
    for key, (pattern, paragraph, meaning) in patterns.items():
        new = first(pattern.format(amount=gbp), t_now)
        old = first(pattern.format(amount=eur), t_before)
        rows[key] = {"value": int(new.group(1)), "currency": "GBP", "before_2026_06_30_value": int(old.group(1)), "before_2026_06_30_currency": "EUR", "regulation": paragraph, "meaning": meaning}
        if key in ("max_stored_value", "cash_redemption_over"):
            items.append(now(f"regulation {paragraph}", f"£{new.group(1)}", "currency:GBP", lead_in(new)))
            items.append(before(f"regulation {paragraph}", f"{old.group(1)} euros", "currency:EUR", lead_in(old)))
    start_day, start_item = now.start()  # type: ignore[attr-defined]
    items.append(start_item)
    return base_rule(
        "gb-mlr-2017-electronic-money-due-diligence-exemption",
        "United Kingdom electronic money limits for the customer due diligence exemption, Money Laundering Regulations 2017 regulation 38",
        "compliance",
        "GB",
        "A",
        "license-review",
        start_day,
        [*AML_TAGS, "kyc", "electronic-money", "prepaid-cards", "simplified-due-diligence"],
        ["kyc-onboarding", "payments-demo", "fintech-demo", "aml-demo"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        [
            {"input": {"key": "max_stored_value", "column": "value"}, "expected": rows["max_stored_value"]["value"], "origin": "source"},
            {"input": {"key": "cash_redemption_over", "column": "value"}, "expected": rows["cash_redemption_over"]["value"], "origin": "source"},
            {"input": {"key": "max_stored_value", "column": "before_2026_06_30_value"}, "expected": rows["max_stored_value"]["before_2026_06_30_value"], "origin": "source"},
            {"input": "reloadable_monthly_limit", "expected": True, "origin": "source"},
            {"input": "annual_limit", "expected": False, "origin": "derived"},
        ],
        items,
        [],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0}],
        (
            "Conditions under which an issuer of electronic money need not apply customer due diligence under regulation 38 "
            "of the UK Money Laundering Regulations 2017: the instrument holds no more than the stored-value limit, is not "
            "reloadable or has the monthly limit and works only in the UK, is used only to buy goods or services and cannot "
            "be funded with anonymous e-money; the exemption does not cover cash redemptions or remote redemptions above the "
            "stated amounts. Sterling amounts replaced euro amounts from 30 June 2026; each row records both, read from "
            f"legislation.gov.uk's point-in-time versions as of {LEG_DATE} and {MLR_BEFORE_STERLING}. " + LEGISLATION_LICENSE_NOTE
        ),
    )


def uk_gdpr_time_limits() -> dict:
    a33 = leg_source("eur/2016/679/article/33", "UK GDPR (Regulation (EU) 2016/679 as retained), Article 33")
    a12a = leg_source("eur/2016/679/article/12A.", "UK GDPR (Regulation (EU) 2016/679 as retained), Article 12A")
    a8 = leg_source("eur/2016/679/article/8", "UK GDPR (Regulation (EU) 2016/679 as retained), Article 8")
    t33, t12a, t8 = (leg_text(get(s.url)) for s in (a33, a12a, a8))  # type: ignore[attr-defined]
    breach = first(r"not later than (\d+) hours after having become aware of it", t33)
    month = first(r"means the period of (\w+) month beginning with the relevant time", t12a)
    extend = first(r"extend the applicable time period by (\w+) further months", t12a)
    child = first(r"lawful where the child is at least (\d+) years old", t8)
    rows = {
        "breach_notification_hours": {"value": int(breach.group(1)), "unit": "hours after becoming aware, where feasible", "article": "33(1)"},
        "subject_request_response_months": {"value": number(month.group(1)), "unit": "month beginning with the relevant time", "article": "12A(1)"},
        "subject_request_extension_months": {"value": number(extend.group(1)), "unit": "further months, on notice", "article": "12A(3)"},
        "child_consent_min_age_years": {"value": int(child.group(1)), "unit": "years, for information society services", "article": "8(1)"},
    }
    starts = [s.start() for s in (a33, a12a, a8)]  # type: ignore[attr-defined]
    return base_rule(
        "gb-uk-gdpr-time-limits",
        "United Kingdom UK GDPR time limits: 72-hour breach notification, subject request response period and child consent age",
        "privacy",
        "GB",
        "A",
        "license-review",
        max(d for d, _ in starts),
        ["privacy", "compliance", "uk-gdpr", "data-breach", "subject-access-request", "data-protection"],
        ["customer-service-demo", "kyc-onboarding", "sla-calculation", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        lookup_vectors(rows, ["breach_notification_hours", "subject_request_response_months", "child_consent_min_age_years"], "erasure_response_days"),
        [
            a33("Article 33(1)", breach.group(1), "integer", breach.group(0)),
            a12a("Article 12A(1)", month.group(1), "text", month.group(0)),
            a12a("Article 12A(3)", extend.group(1), "text", extend.group(0)),
            a8("Article 8(1)", child.group(1), "integer", f"{child.group(1)} years old"),
            *[item for _, item in starts],
        ],
        [],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[breach_notification_hours,value]", "expected": rows["breach_notification_hours"]["value"], "tolerance": 0}],
        (
            "Deadlines in the UK GDPR as amended by the Data (Use and Access) Act 2025, read from legislation.gov.uk's "
            f"point-in-time versions as of {LEG_DATE}: a controller notifies the Information Commissioner of a personal data "
            "breach without undue delay and, where feasible, within the stated hours of becoming aware of it, unless the "
            "breach is unlikely to result in a risk; it responds to a data subject's request within one month beginning with "
            "the relevant time (the latest of receiving the request, any identifying information asked for and any fee), "
            "extendable by two further months for complex or numerous requests on notice given within the first month; and a "
            "child can consent to an information society service from the stated age. Article 12A, which holds the response "
            "period since 5 February 2026, is published at a URL ending in '12A.'. valid_from is the latest start date of the "
            "three provisions' current versions; earlier versions carried the same figures under different wording. "
            + LEGISLATION_LICENSE_NOTE
        ),
    )


def dpa_penalties() -> dict:
    s157 = leg_source("ukpga/2018/12/section/157", "Data Protection Act 2018, section 157")
    text = leg_text(get(s157.url))  # type: ignore[attr-defined]
    tiers = list(re.finditer(r"in the case of an undertaking, £(\d(?:[\d,]*\d)?) or (\d+)% of the undertaking's total annual worldwide turnover", text))
    if len(tiers) != 2 or text.find("higher maximum amount ” is") > tiers[0].start() or text.find("standard maximum amount ” is") > tiers[1].start():
        raise ValueError("section 157 no longer reads as two tiers, higher then standard")
    higher, standard = tiers
    parameters = {
        "currency": "GBP",
        "tiers": {
            "higher": {"fixed_gbp": leg_number(higher.group(1)), "turnover_percent": int(higher.group(2)), "section": "157(5)"},
            "standard": {"fixed_gbp": leg_number(standard.group(1)), "turnover_percent": int(standard.group(2)), "section": "157(6)"},
        },
        "turnover_basis": "total annual worldwide turnover in the preceding financial year",
    }
    h, s = parameters["tiers"]["higher"], parameters["tiers"]["standard"]
    big = 1_000_000_000
    start_day, start_item = s157.start()  # type: ignore[attr-defined]
    return base_rule(
        "gb-dpa-2018-penalty-maximum",
        "United Kingdom data protection maximum penalties: higher and standard maximum amounts, Data Protection Act 2018 section 157",
        "privacy",
        "GB",
        "A",
        "license-review",
        start_day,
        ["privacy", "compliance", "uk-gdpr", "penalties", "data-protection-act-2018"],
        ["audit-demo", "data-quality-validation", "financial-reporting"],
        "almanac.rules.gb_dpa_penalty_maximum",
        parameters,
        [
            {"input": {"tier": "higher"}, "expected": h["fixed_gbp"], "origin": "source"},
            {"input": {"tier": "standard"}, "expected": s["fixed_gbp"], "origin": "source"},
            {"input": {"tier": "higher", "undertaking": True, "turnover": big}, "expected": big * h["turnover_percent"] // 100, "origin": "derived"},
            {"input": {"tier": "standard", "undertaking": True, "turnover": 100_000_000}, "expected": s["fixed_gbp"], "origin": "derived", "note": "the fixed sum is higher than the turnover share"},
        ],
        [
            s157("section 157(5)(a)", f"£{higher.group(1)}", "currency:GBP", f"or {higher.group(2)}% of the undertaking's total annual worldwide turnover in the preceding financial year"),
            s157("section 157(6)(a)", f"£{standard.group(1)}", "currency:GBP", f"or {standard.group(2)}% of the undertaking's total annual worldwide turnover in the preceding financial year"),
            start_item,
        ],
        [],
        [{"statistic": "count", "expected": 2, "tolerance": 0}, {"statistic": "value[higher,fixed_gbp]", "expected": h["fixed_gbp"], "tolerance": 0}],
        (
            "The ceilings on a penalty notice under the UK data protection regime, from section 157 of the Data Protection "
            f"Act 2018 as legislation.gov.uk publishes it at {LEG_DATE}. For an undertaking the maximum is the fixed sum or the "
            "stated percentage of total annual worldwide turnover in the preceding financial year, whichever is higher; for "
            "anyone else it is the fixed sum. Which tier applies depends on the provision infringed: section 157 and Article "
            "83 of the UK GDPR assign them. valid_from is the start of the section's current version. "
            + LEGISLATION_LICENSE_NOTE
        ),
    )


def consumer_contracts() -> dict:
    title = "The Consumer Contracts (Information, Cancellation and Additional Charges) Regulations 2013"
    r30 = leg_source("uksi/2013/3134/regulation/30", f"{title}, regulation 30")
    r31 = leg_source("uksi/2013/3134/regulation/31", f"{title}, regulation 31")
    r34 = leg_source("uksi/2013/3134/regulation/34", f"{title}, regulation 34")
    t30, t31, t34 = (leg_text(get(s.url)) for s in (r30, r31, r34))  # type: ignore[attr-defined]
    service = first(r"the cancellation period ends at the end of (\d+) days after the day on which the contract is entered into", t30)
    goods = first(r"the cancellation period ends at the end of (\d+) days after the day on which the goods come into the physical possession of", t30)
    extended = first(r"Otherwise the cancellation period ends at the end of (\d+) months after the day on which it would have ended under regulation 30", t31)
    refund = first(r"Otherwise, the time is the end of (\d+) days after the day on which the trader is informed of the consumer's decision", t34)
    refund_goods = first(r"has not offered to collect the goods, the time is the end of (\d+) days after", t34)
    rows = {
        "service_or_digital_cancellation_days": {"value": int(service.group(1)), "unit": "days after the contract is entered into", "regulation": "30(2)"},
        "goods_cancellation_days": {"value": int(goods.group(1)), "unit": "days after the goods come into the consumer's physical possession", "regulation": "30(3)"},
        "extended_cancellation_months": {"value": int(extended.group(1)), "unit": "months after the normal period would have ended, when cancellation information was not given", "regulation": "31(3)"},
        "refund_days": {"value": int(refund.group(1)), "unit": "days after the trader is told of the cancellation", "regulation": "34(6)"},
        "refund_days_goods_not_collected": {"value": int(refund_goods.group(1)), "unit": "days after the trader receives the goods back or evidence of return, if earlier", "regulation": "34(5)"},
    }
    starts = [s.start() for s in (r30, r31, r34)]  # type: ignore[attr-defined]
    return base_rule(
        "gb-consumer-contracts-cancellation-periods",
        "United Kingdom distance and off-premises contract cancellation and refund periods, Consumer Contracts Regulations 2013",
        "compliance",
        "GB",
        "A",
        "license-review",
        max(d for d, _ in starts),
        ["compliance", "consumer-protection", "cancellation", "refunds", "distance-selling", "consumer-contracts-regulations"],
        ["retail-demo", "customer-service-demo", "sla-calculation", "invoicing", "data-quality-validation"],
        "almanac.rules.lookup_table",
        {"rows": rows},
        lookup_vectors(rows, ["service_or_digital_cancellation_days", "goods_cancellation_days", "extended_cancellation_months", "refund_days"], "restocking_fee_percent"),
        [
            r30("regulation 30(2)", service.group(1), "integer", service.group(0)),
            r30("regulation 30(3)", goods.group(1), "integer", goods.group(0)),
            r31("regulation 31(3)", extended.group(1), "integer", extended.group(0)),
            r34("regulation 34(6)", refund.group(1), "integer", f"Otherwise, the time is the end of {refund.group(1)} days after the day on which the trader is informed"),
            *[item for _, item in starts],
        ],
        [],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "max[value]", "expected": max(r["value"] for r in rows.values()), "tolerance": 0}],
        (
            "The consumer's right to cancel a distance or off-premises contract in Great Britain and Northern Ireland: the "
            "cancellation period ends the stated number of days after the contract for services and digital content, or after "
            "the goods arrive for sales contracts (the last item for split deliveries, the first for regular deliveries), and "
            "is extended by up to twelve months when the trader fails to give the cancellation information. The trader must "
            "refund within the stated days of being told, or, for goods it has not offered to collect, of getting them back "
            f"or evidence of their return. Read from legislation.gov.uk's versions as of {LEG_DATE}; valid_from is the latest "
            "start of the three regulations' current versions. " + LEGISLATION_LICENSE_NOTE
        ),
    )


def payment_services() -> dict:
    title = "The Payment Services Regulations 2017"
    r74 = leg_source("uksi/2017/752/regulation/74", f"{title}, regulation 74")
    r76 = leg_source("uksi/2017/752/regulation/76", f"{title}, regulation 76")
    r77 = leg_source("uksi/2017/752/regulation/77", f"{title}, regulation 77")
    t74, t76, t77 = (leg_text(get(s.url)) for s in (r74, r76, r77))  # type: ignore[attr-defined]
    notify = first(r"no later than (\d+) months after the debit date", t74)
    refund = first(r"no later than the end of the (business day following) the day on which it becomes aware of the unauthorised transaction", t76)
    cap = first(r"the payer is liable up to a maximum of £(\d+) for any losses incurred in respect of unauthorised payment transactions", t77)
    rows = {
        "unauthorised_refund_deadline": {"value": refund.group(0), "unit": "deadline as the regulation states it", "regulation": "76(2)"},
        "unauthorised_refund_business_days": {"value": 1, "unit": "business days after the day the provider becomes aware, at the end of that day", "regulation": "76(2)"},
        "payer_liability_cap_gbp": {"value": int(cap.group(1)), "unit": "GBP, lost or stolen or misappropriated instrument", "regulation": "77(1)"},
        "notification_limit_months": {"value": int(notify.group(1)), "unit": "months after the debit date", "regulation": "74(1)"},
    }
    starts = [s.start() for s in (r74, r76, r77)]  # type: ignore[attr-defined]
    return base_rule(
        "gb-payment-services-unauthorised-transactions",
        "United Kingdom unauthorised payment refund deadline, £35 payer liability cap and 13-month notice, Payment Services Regulations 2017",
        "payments",
        "GB",
        "A",
        "license-review",
        max(d for d, _ in starts),
        ["compliance", "consumer-protection", "fraud", "unauthorised-transactions", "payment-services-regulations"],
        ["fraud-detection-demo", "payments-demo", "banking-demo", "customer-service-demo", "sla-calculation"],
        "almanac.rules.lookup_table",
        {"currency": "GBP", "rows": rows},
        lookup_vectors(rows, ["payer_liability_cap_gbp", "notification_limit_months"], "chargeback_window_days"),
        [
            r76("regulation 76(2)", refund.group(1), "text", refund.group(0)),
            r77("regulation 77(1)", f"£{cap.group(1)}", "currency:GBP", f"liable up to a maximum of £{cap.group(1)}"),
            r74("regulation 74(1)", notify.group(1), "integer", notify.group(0)),
            *[item for _, item in starts],
        ],
        [
            {
                "parameter": "unauthorised_refund_business_days",
                "value": 1,
                "method": "derived",
                "rationale": "Regulation 76(2) says 'no later than the end of the business day following the day on which it becomes aware'; the row restates that as one business day.",
            }
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}, {"statistic": "value[payer_liability_cap_gbp,value]", "expected": rows["payer_liability_cap_gbp"]["value"], "tolerance": 0}],
        (
            "Rules a UK payment service provider applies to an unauthorised payment transaction under the Payment Services "
            f"Regulations 2017, read from legislation.gov.uk's versions as of {LEG_DATE}: it refunds the payer by the end of "
            "the business day after it becomes aware of the transaction (unless it reasonably suspects fraud and notifies the "
            "appropriate authority); it may hold the payer liable for no more than the stated cap for losses from a lost, "
            "stolen or misappropriated instrument (with exceptions for fraud, gross negligence and losses the payer could not "
            "detect); and the payer must notify within the stated months of the debit date to be entitled to redress. "
            "valid_from is the latest start of the three regulations' current versions. " + LEGISLATION_LICENSE_NOTE
        ),
    )


def late_payment() -> dict:
    s5a = leg_source("ukpga/1998/20/section/5A", "Late Payment of Commercial Debts (Interest) Act 1998, section 5A")
    order_source = leg_source("uksi/2002/1675", "The Late Payment of Commercial Debts (Rate of Interest) (No. 3) Order 2002", "made")
    order_url = order_source.url  # type: ignore[attr-defined]
    text = leg_text(get(s5a.url))  # type: ignore[attr-defined]
    order = leg_text(get(order_url))
    low = first(r"for a debt less than £(\d+), the sum of £(\d+);", text)
    mid = first(r"for a debt of £(\d+) or more, but less than £(\d(?:[\d,]*\d)?), the sum of £(\d+);", text)
    high = first(r"for a debt of £(\d(?:[\d,]*\d)?) or more, the sum of £(\d+)\.", text)
    margin = first(r"shall be (\d+) per cent per annum over the official dealing rate in force on the 30th June", order)
    if leg_number(low.group(1)) != leg_number(mid.group(1)) or leg_number(mid.group(2)) != leg_number(high.group(1)):
        raise ValueError("section 5A bands are not contiguous")
    parameters = {
        "currency": "GBP",
        "fixed_sums": [
            {"below": leg_number(low.group(1)), "sum": int(low.group(2))},
            {"below": leg_number(mid.group(2)), "sum": int(mid.group(3))},
            {"below": None, "sum": int(high.group(2))},
        ],
        "margin_percent": int(margin.group(1)),
        "reference_days": {"interest_starting_1_jan_to_30_jun": "31 December before", "interest_starting_1_jul_to_31_dec": "30 June before"},
        "sections": {"fixed_sums": "1998 c. 20 s. 5A(2)", "rate": "S.I. 2002/1675 art. 4"},
    }
    sums = parameters["fixed_sums"]
    start_day, start_item = s5a.start()  # type: ignore[attr-defined]
    return base_rule(
        "gb-late-payment-compensation-and-interest",
        "United Kingdom late commercial payment fixed sums by debt band and statutory interest at 8 per cent over Bank Rate",
        "compliance",
        "GB",
        "A",
        "license-review",
        start_day,
        ["compliance", "late-payment", "statutory-interest", "debt-recovery", "b2b"],
        ["invoicing", "accounts-payable", "collections", "credit-risk", "payments-scheduling"],
        "almanac.rules.gb_late_payment",
        parameters,
        [
            {"input": {"debt": sums[0]["below"] - 0.01}, "expected": sums[0]["sum"], "origin": "source"},
            {"input": {"debt": sums[0]["below"]}, "expected": sums[1]["sum"], "origin": "source"},
            {"input": {"debt": sums[1]["below"]}, "expected": sums[2]["sum"], "origin": "source"},
            {"input": {"interest_starts": "2026-07-01"}, "expected": "2026-06-30", "origin": "source"},
            {"input": {"interest_starts": "2026-06-30"}, "expected": "2025-12-31", "origin": "source"},
            {"input": {"official_dealing_rate": 4.0}, "expected": 12.0, "origin": "derived"},
        ],
        [
            s5a("section 5A(2)(a)", f"£{low.group(2)}", "currency:GBP", low.group(0)),
            s5a("section 5A(2)(b)", f"£{mid.group(3)}", "currency:GBP", mid.group(0)),
            s5a("section 5A(2)(c)", f"£{high.group(2)}", "currency:GBP", high.group(0)),
            order_source("article 4", margin.group(1), "integer", f"shall be {margin.group(1)} per cent per annum over the official dealing rate"),
            order_source("article 4", "31st December", "text", "or the 31st December (in respect of interest which starts to run between 1st January and 30th June)"),
            start_item,
        ],
        [],
        [{"statistic": "count", "expected": len(sums), "tolerance": 0}, {"statistic": "margin_percent", "expected": parameters["margin_percent"], "tolerance": 0}],
        (
            "What a supplier can claim when a business customer pays a qualifying commercial debt late in England, Wales and "
            "Northern Ireland: a fixed sum per debt, banded by the size of the debt (section 5A of the Late Payment of "
            "Commercial Debts (Interest) Act 1998), plus statutory interest at the stated margin over the Bank of England's "
            "official dealing rate (Bank Rate) in force on the reference day: 30 June for interest starting from 1 July to "
            "31 December, 31 December for interest starting from 1 January to 30 June (article 4 of S.I. 2002/1675, cited as "
            "made because legislation.gov.uk holds no revised version). The rule returns the fixed sum, the reference day, "
            "and the statutory rate for a given Bank Rate; Bank Rate itself is a separate series. Scotland has its own order. "
            "valid_from is the start of section 5A's current version. " + LEGISLATION_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- PSD2 strong customer authentication (EU) 2018/389


def sca_exemptions() -> dict:
    title = "Commission Delegated Regulation (EU) 2018/389 (strong customer authentication RTS)"

    def adopted(article: str) -> tuple[str, Callable[..., dict]]:
        rendering = "data.xht" if article == "annex" else "data.html"
        source = leg_source(f"eur/2018/389/{article}", f"{title}, {article.replace('/', ' ')}", "adopted", rendering)
        return source.url, source  # type: ignore[attr-defined]

    u11, a11 = adopted("article/11")
    u16, a16 = adopted("article/16")
    uan, annex = adopted("annex")
    u38, a38 = adopted("article/38")
    t11, t16, tan, t38 = (leg_text(get(u)) for u in (u11, u16, uan, u38))
    c_single = first(r"the individual amount of the contactless electronic payment transaction does not exceed EUR (\d+)", t11)
    c_cumulative = first(r"from the date of the last application of strong customer authentication does not exceed EUR (\d+)", t11)
    c_count = first(r"since the last application of strong customer authentication does not exceed (\w+)\.", t11)
    r_single = first(r"the amount of the remote electronic payment transaction does not exceed EUR (\d+)", t16)
    r_cumulative = first(r"initiated by the payer since the last application of strong customer authentication does not exceed EUR (\d+)", t16)
    r_count = first(r"does not exceed (\w+) consecutive individual remote electronic payment transactions", t16)
    applies = first(r"This Regulation shall apply from (\d+ \w+ \d{4})", t38)
    bands = []
    for etv, card, transfer in re.findall(r"EUR (\d+) (\d+,\d+) (\d+,\d+)", tan):
        bands.append({"etv_eur": int(etv), "card_reference_fraud_rate_percent": float(card.replace(",", ".")), "credit_transfer_reference_fraud_rate_percent": float(transfer.replace(",", "."))})
    if len(bands) != 3:
        raise ValueError("expected three rows in the Annex table")
    parameters = {
        "currency": "EUR",
        "contactless": {"max_amount_eur": int(c_single.group(1)), "max_cumulative_eur": int(c_cumulative.group(1)), "max_consecutive": number(c_count.group(1)), "article": "11"},
        "low_value_remote": {"max_amount_eur": int(r_single.group(1)), "max_cumulative_eur": int(r_cumulative.group(1)), "max_consecutive": number(r_count.group(1)), "article": "16"},
        "tra_bands": bands,
        "tra_article": "18 and Annex",
    }
    top, middle, bottom = sorted(bands, key=lambda b: -b["etv_eur"])
    vectors = [
        {"input": {"exemption": "contactless", "amount": parameters["contactless"]["max_amount_eur"], "previous_cumulative": parameters["contactless"]["max_cumulative_eur"], "previous_count": 9}, "expected": True, "origin": "source"},
        {"input": {"exemption": "contactless", "amount": parameters["contactless"]["max_amount_eur"] + 1}, "expected": False, "origin": "derived"},
        {"input": {"exemption": "contactless", "amount": 20, "previous_cumulative": 200, "previous_count": parameters["contactless"]["max_consecutive"]}, "expected": True, "origin": "source", "note": "count limit met although the cumulative limit is exceeded"},
        {"input": {"exemption": "contactless", "amount": 20, "previous_cumulative": 200, "previous_count": parameters["contactless"]["max_consecutive"] + 1}, "expected": False, "origin": "derived"},
        {"input": {"exemption": "low_value_remote", "amount": parameters["low_value_remote"]["max_amount_eur"], "previous_cumulative": 0, "previous_count": 0}, "expected": True, "origin": "source"},
        {"input": {"exemption": "low_value_remote", "amount": 10, "previous_cumulative": 101, "previous_count": 6}, "expected": False, "origin": "derived"},
        {"input": {"exemption": "tra_threshold", "payment_type": "card", "fraud_rate_percent": top["card_reference_fraud_rate_percent"]}, "expected": top["etv_eur"], "origin": "source"},
        {"input": {"exemption": "tra_threshold", "payment_type": "card", "fraud_rate_percent": middle["card_reference_fraud_rate_percent"]}, "expected": middle["etv_eur"], "origin": "source"},
        {"input": {"exemption": "tra_threshold", "payment_type": "credit_transfer", "fraud_rate_percent": bottom["credit_transfer_reference_fraud_rate_percent"]}, "expected": bottom["etv_eur"], "origin": "source"},
        {"input": {"exemption": "tra_threshold", "payment_type": "card", "fraud_rate_percent": 0.2}, "expected": None, "origin": "derived", "note": "fraud rate above every reference rate"},
        {"input": {"exemption": "tra", "payment_type": "card", "fraud_rate_percent": 0.05, "amount": 300}, "expected": False, "origin": "derived"},
    ]
    annex_row = first(r"EUR 500 \d+,\d+ \d+,\d+", tan).group(0)
    return base_rule(
        "eu-psd2-sca-exemption-thresholds",
        "European Union PSD2 strong customer authentication exemptions: contactless, low-value remote and transaction risk analysis limits",
        "payments",
        "EU",
        "A",
        "license-review",
        datetime.strptime(applies.group(1), "%d %B %Y").date().isoformat(),
        ["compliance", "fraud", "psd2", "strong-customer-authentication", "card-payments", "3ds"],
        ["fraud-detection-demo", "payments-demo", "fintech-demo", "data-quality-validation"],
        "almanac.rules.eu_sca_exemptions",
        parameters,
        vectors,
        [
            a11("Article 11(a)", f"EUR {c_single.group(1)}", "currency:EUR", c_single.group(0)),
            a11("Article 11(b)", f"EUR {c_cumulative.group(1)}", "currency:EUR", f"does not exceed EUR {c_cumulative.group(1)}; or"),
            a16("Article 16(a)", f"EUR {r_single.group(1)}", "currency:EUR", r_single.group(0)),
            a16("Article 16(b)", f"EUR {r_cumulative.group(1)}", "currency:EUR", f"does not exceed EUR {r_cumulative.group(1)}; or"),
            annex("Annex, table, first row", "0,005", "decimal", "EUR 500"),
            a38("Article 38(2)", applies.group(1), "text", applies.group(0)),
        ],
        [
            {
                "parameter": "tra_bands",
                "value": annex_row,
                "method": "derived",
                "rationale": "The Annex writes reference fraud rates with decimal commas (for example 0,01); the parameters restate them as decimal numbers in percent.",
            },
            {
                "parameter": "previous_cumulative and previous_count",
                "value": "payments since the last strong customer authentication, excluding the payment being tested",
                "method": "derived",
                "rationale": "Article 11(b) and 16(b) speak of 'previous' transactions; Article 11(c) does not say whether the current one counts, and the rule reads both limits the same way.",
            },
        ],
        [{"statistic": "count", "expected": len(bands), "tolerance": 0}, {"statistic": "max[etv_eur]", "expected": top["etv_eur"], "tolerance": 0}],
        (
            "When a payment service provider in the European Union may skip strong customer authentication under the PSD2 "
            "regulatory technical standards: a contactless payment at the point of sale or a low-value remote payment "
            "within its single-payment limit, provided either the cumulative amount or the count of payments since the last "
            "authentication stays within its limit; or a remote payment the provider's real-time transaction risk analysis "
            "rates low risk, up to the exemption threshold value its fraud rate for the payment type qualifies for. The text "
            "is the regulation as adopted, published by legislation.gov.uk because EUR-Lex could not be reached; later EU "
            "amendments, which changed other articles, could not be checked against the consolidated text. The UK has its "
            "own version under the FCA and is not covered here. " + LEGISLATION_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- HM Treasury: FATF lists as high-risk third countries


WB_ALIASES = {
    "Côte d’Ivoire": "Cote d'Ivoire",
    "Democratic Republic of the Congo": "Congo, Dem. Rep.",
    "Democratic People’s Republic of Korea": "Korea, Dem. People's Rep.",
    "Iran": "Iran, Islamic Rep.",
    "Syria": "Syrian Arab Republic",
    "Venezuela": "Venezuela, RB",
    "Vietnam": "Viet Nam",
    "Yemen": "Yemen, Rep.",
}


def high_risk_countries() -> dict:
    raw = get(HMT_NOTICE)
    body = json.loads(raw)["details"]["body"]
    countries = {c["name"]: c["iso2Code"] for c in json.loads(get(WORLD_BANK_COUNTRIES))[1]}

    def listed(heading_id: str) -> list[str]:
        block = first(rf'<h4 id="{heading_id}">.*?</h4>\s*<ul>(.*?)</ul>', body).group(1)
        return [html.unescape(name).strip() for name in re.findall(r"<li>(.*?)</li>", block)]

    sanctions_block = first(r"also subject to financial sanctions measures at the time of publication of this notice.*?<ul>(.*?)</ul>", body).group(1)
    sets = {
        "call_for_action": listed("high-risk-jurisdictions-subject-to-a-call-for-action"),
        "increased_monitoring": listed("jurisdictions-under-increased-monitoring"),
        "also_under_uk_financial_sanctions": [html.unescape(n).strip() for n in re.findall(r"<li>(.*?)</li>", sanctions_block)],
    }

    def code(name: str) -> str:
        return countries[WB_ALIASES.get(name, name)]

    coded = {key: {code(n): n for n in names} for key, names in sets.items()}
    published = first(r"On (\d+ \w+ \d{4}), the FATF published the most recent update", body)
    hmt = "HM Treasury (GOV.UK content API)"
    hmt_title = "Money Laundering Advisory Notice: High Risk Third Countries, June 2026 (GOV.UK content API JSON)"
    wb_title = "World Bank API, country list (JSON)"
    alias_text = "; ".join(f"{k} = {v}" for k, v in WB_ALIASES.items())
    return base_rule(
        "gb-hm-treasury-high-risk-third-countries",
        "FATF high-risk and increased-monitoring jurisdictions as HM Treasury lists them for UK enhanced due diligence, June 2026",
        "compliance",
        "GB",
        "A",
        "verified",
        datetime.strptime(published.group(1), "%d %B %Y").date().isoformat(),
        [*AML_TAGS, "kyc", "fatf", "high-risk-third-countries", "enhanced-due-diligence", "country-risk"],
        ["kyc-onboarding", "kyb-onboarding", "aml-demo", "fraud-detection-demo", "data-quality-validation"],
        "almanac.rules.enumeration",
        {"sets": coded, "code_system": "ISO 3166-1 alpha-2 as the World Bank API gives it"},
        [
            {"input": {"set": "call_for_action", "value": code(sets["call_for_action"][0])}, "expected": True, "origin": "source"},
            {"input": {"set": "increased_monitoring", "value": code(sets["increased_monitoring"][0])}, "expected": True, "origin": "source"},
            {"input": {"set": "call_for_action", "value": code(sets["increased_monitoring"][0])}, "expected": False, "origin": "source"},
            {"input": {"set": "also_under_uk_financial_sanctions", "value": code(sets["also_under_uk_financial_sanctions"][0])}, "expected": True, "origin": "source"},
            {"input": {"set": "increased_monitoring", "value": "GB"}, "expected": False, "origin": "derived"},
        ],
        [
            ev(hmt, hmt_title, HMT_NOTICE, "details.body, Jurisdictions under Increased Monitoring", sets["increased_monitoring"][0], "text", f"<li>{sets['increased_monitoring'][0]}</li>", "OGL-UK-3.0"),
            ev(hmt, hmt_title, HMT_NOTICE, "details.body, High-Risk Jurisdictions subject to a Call for Action", sets["call_for_action"][0], "text", f"<li>{sets['call_for_action'][0]}</li>", "OGL-UK-3.0"),
            ev(hmt, hmt_title, HMT_NOTICE, "details.body, FATF public statement", published.group(1), "date", published.group(0), "OGL-UK-3.0"),
            ev("World Bank", wb_title, WORLD_BANK_COUNTRIES, "[1][*], id PRK", "KP", "text", '"id":"PRK","iso2Code":"KP"', "CC-BY-4.0", role="supporting"),
        ],
        [
            {
                "parameter": "sets (country codes)",
                "value": alias_text,
                "method": "derived",
                "rationale": "HM Treasury names the jurisdictions; each name is matched to its ISO 3166-1 alpha-2 code through the World Bank country list, with these spelling differences mapped by hand. The labels keep HM Treasury's names.",
            }
        ],
        [{"statistic": f"count[{key}]", "expected": len(names), "tolerance": 0} for key, names in coded.items()],
        (
            "The jurisdictions the Financial Action Task Force lists as High-Risk Jurisdictions subject to a Call for Action "
            "and as Jurisdictions under Increased Monitoring, as HM Treasury's advisory notice of June 2026 reproduces them "
            f"after the FATF update of {published.group(1)}, keyed by ISO 3166-1 alpha-2 code, with the subset HM Treasury "
            "notes is also under UK financial sanctions. Under the UK Money Laundering Regulations 2017 a high-risk third "
            "country is one on either FATF list; from 30 June 2026 the mandatory enhanced due diligence of regulation 33(1)(b) "
            "applies only to the call-for-action list, while increased monitoring remains a geographic risk factor. FATF "
            "updates the lists after each plenary (February, June and October); this entry is the June 2026 notice, the "
            "latest HM Treasury had published on GOV.UK when it was built, and should be replaced when a later notice "
            "appears. The FATF's own pages could not be fetched (they sit behind a browser challenge)."
        ),
    )


def main() -> None:
    for build in (
        bsa_reporting_thresholds,
        bsa_sar_thresholds,
        form_8300_installments,
        fdic_coverage,
        ncua_coverage,
        regulation_f,
        cooling_off,
        mail_order,
        can_spam,
        mlr_thresholds,
        mlr_emoney,
        high_risk_countries,
        uk_gdpr_time_limits,
        dpa_penalties,
        consumer_contracts,
        payment_services,
        late_payment,
        sca_exemptions,
    ):
        write(build())
    for entry in tcpa():
        write(entry)


if __name__ == "__main__":
    main()

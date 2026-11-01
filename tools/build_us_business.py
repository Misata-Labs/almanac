"""Regenerate the US financial and business value-pool entries built from four federal publishers.

* FDIC BankFind Suite API (``api.fdic.gov/banks/financials``): industry-wide quarterly aggregates
  and derived performance ratios, institutions by asset-size class, charter class and state, and
  the largest banks by assets.
* IRS Statistics of Income: corporation returns by industrial sector (Table 1 of the Corporation
  Complete Report) and individual returns by size of adjusted gross income (Historic Table 2).
* Federal Reserve Data Download Program: G.19 consumer credit levels and terms, and the
  charge-off and delinquency rates of the CHGDEL release.
* Census Bureau Quarterly Financial Report: after-tax profit per dollar of sales by industry.

All four publishers are US federal bodies whose pages carry no licence statement, so every entry
records ``source_license: unstated`` and stays at ``license-review``. Run from the repository root:

    uv run python tools/build_us_business.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

LICENSE = "unstated"
STATUS = "license-review"
LICENSE_NOTE = (
    "The publisher is a US federal body and the resource carries no licence statement, so the licence is "
    "recorded as unstated and the entry held at license-review."
)

FDIC = "FDIC"
FDIC_API = "https://api.fdic.gov/banks/financials"
FDIC_SCHEMA_URL = "https://api.fdic.gov/banks/docs/risview_properties.yaml"
FDIC_LATEST = "20260630"
FDIC_FIRST = "20240930"
FDIC_SUM_FIELDS = ["ASSET", "DEP", "EQ", "LNLSGR", "NCLNLS", "ERNAST", "NETINCQ", "NIMQ", "EINTXQ", "NONIIQ", "NONIXQ", "ELNATQ", "NTLNLSQ"]
FDIC_SUM_COLUMNS = {
    "DEP": "total_deposits_usd_thousands",
    "EQ": "equity_capital_usd_thousands",
    "LNLSGR": "loans_and_leases_usd_thousands",
    "NCLNLS": "noncurrent_loans_and_leases_usd_thousands",
    "ERNAST": "earning_assets_usd_thousands",
    "NETINCQ": "net_income_quarter_usd_thousands",
    "NIMQ": "net_interest_income_quarter_usd_thousands",
    "EINTXQ": "interest_expense_quarter_usd_thousands",
    "NONIIQ": "noninterest_income_quarter_usd_thousands",
    "NONIXQ": "noninterest_expense_quarter_usd_thousands",
    "ELNATQ": "provision_for_credit_losses_quarter_usd_thousands",
    "NTLNLSQ": "net_charge_offs_quarter_usd_thousands",
}
# Asset-size classes of the FDIC Quarterly Banking Profile, expressed as filters on ASSET (thousands of dollars).
FDIC_SIZE_CLASSES = [
    ("under_100m", "Less than $100 million", "[* TO 99999]"),
    ("100m_to_1b", "$100 million to $1 billion", "[100000 TO 999999]"),
    ("1b_to_10b", "$1 billion to $10 billion", "[1000000 TO 9999999]"),
    ("10b_to_250b", "$10 billion to $250 billion", "[10000000 TO 249999999]"),
    ("250b_and_over", "$250 billion or more", "[250000000 TO *]"),
]

IRS = "Internal Revenue Service, Statistics of Income Division"
IRS_CORP_URL = "https://www.irs.gov/pub/irs-soi/23co01ccr.xlsx"
IRS_INDIVIDUAL_URL = "https://www.irs.gov/pub/irs-soi/23in54us.xlsx"
IRS_CORP_COLUMNS = [
    "returns",
    "returns_with_net_income",
    "total_receipts_usd_thousands",
    "total_receipts_with_net_income_usd_thousands",
    "business_receipts_usd_thousands",
    "cost_of_goods_sold_usd_thousands",
    "net_income_usd_thousands",
    "deficit_usd_thousands",
    "income_subject_to_tax_usd_thousands",
    "income_tax_before_credits_usd_thousands",
    "income_tax_after_credits_usd_thousands",
    "total_assets_usd_thousands",
    "net_worth_usd_thousands",
    "depreciable_assets_usd_thousands",
    "depreciation_deduction_usd_thousands",
]
IRS_INDIVIDUAL_ITEMS = {
    "Number of returns [1]": "returns",
    "Number of single returns": "single_returns",
    "Number of joint returns": "joint_returns",
    "Number of head of household returns": "head_of_household_returns",
    "Number of elderly returns [5]": "elderly_returns",
    "Adjusted gross income (AGI) [6]": "agi_usd_thousands",
    "Salaries and wages in AGI:  Number": "salaries_and_wages_returns",
    "Taxable interest:  Number": "taxable_interest_returns",
    "Ordinary dividends:  Number": "ordinary_dividends_returns",
}
IRS_INDIVIDUAL_AMOUNTS = {
    "Salaries and wages in AGI:  Number": "salaries_and_wages_usd_thousands",
    "Taxable interest:  Number": "taxable_interest_usd_thousands",
    "Ordinary dividends:  Number": "ordinary_dividends_usd_thousands",
}

FED = "Board of Governors of the Federal Reserve System"
FED_DDP = "https://www.federalreserve.gov/datadownload/Output.aspx"
G19_LEVELS_PACKAGE = "696245eb361e0a8bc89b8e5b01cc971b"
G19_TERMS_PACKAGE = "10264fd36110a9c4906bd99f1daccf29"
CHGDEL_CHARGEOFF_PACKAGE = "929faaa8d5e6bf375839d7fc2b7760fe"
CHGDEL_DELINQUENCY_PACKAGE = "e77af32404312ad2d45dd60dfa36477a"

CENSUS = "US Census Bureau"
QFR_URL = "https://www.census.gov/econ/qfr/mmws/current/qfr_tabs_f.xlsx"
QFR_QUARTER = "2026Q2"
QFR_MANUFACTURING_TABLES = range(1, 34)
QFR_NONMANUFACTURING_TABLES = range(82, 92)


def fed_package_url(release: str, package: str, start: str, end: str) -> str:
    return (
        f"{FED_DDP}?rel={release}&series={package}&lastobs=&from={start}&to={end}"
        "&filetype=csv&label=include&layout=seriescolumn&type=package"
    )


def fdic_url(filters: str, fields: str, **params: str | int) -> str:
    query = "&".join([f"filters={quote(filters, safe='')}", f"fields={fields}"] + [f"{k}={quote(str(v), safe='')}" for k, v in params.items()] + ["format=json"])
    return f"{FDIC_API}?{query}"


def fdic_aggregate_url(filters: str, agg_by: str, agg_limit: int) -> str:
    return fdic_url(filters, "REPDTE", agg_by=agg_by, agg_sum_fields=",".join(FDIC_SUM_FIELDS), agg_limit=agg_limit, limit=1)


def iso_date(repdte: str) -> str:
    return f"{repdte[:4]}-{repdte[4:6]}-{repdte[6:]}"


def pct(numerator: float, denominator: float, annualise: bool = False) -> float:
    return round(100 * numerator * (4 if annualise else 1) / denominator, 4)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def self_check(entry: dict, resources: dict[str, bytes]) -> None:
    """Fail fast when an evidence snippet or value would not be found by the verifier."""
    for item in entry["evidence"]:
        text = " ".join(Resource(item["url"], resources[item["url"]], "").text.split())
        for label, needle in (("snippet", item["snippet"]), ("value", str(item["value"]))):
            if " ".join(needle.split()) not in text:
                raise ValueError(f"{entry['id']}: {label} {needle!r} not found in {item['url']}")
        if len(item["snippet"].split()) > 24:
            raise ValueError(f"{entry['id']}: snippet too long: {item['snippet']!r}")


def finish(entry: dict, resources: dict[str, bytes]) -> None:
    self_check(entry, resources)
    write(entry)


# ----------------------------------------------------------------------------------------------
# FDIC
# ----------------------------------------------------------------------------------------------


def fdic_buckets(raw: bytes) -> list[dict]:
    return [bucket["data"] for bucket in json.loads(raw)["data"]]


def fdic_ratios(bucket: dict) -> dict[str, float]:
    """Industry ratios from summed call-report items; quarterly flows are annualised against end-of-quarter balances."""
    return {
        "return_on_assets_percent": pct(bucket["sum_NETINCQ"], bucket["sum_ASSET"], annualise=True),
        "net_interest_margin_percent": pct(bucket["sum_NIMQ"], bucket["sum_ERNAST"], annualise=True),
        "efficiency_ratio_percent": pct(bucket["sum_NONIXQ"], bucket["sum_NIMQ"] + bucket["sum_NONIIQ"]),
        "noncurrent_loan_ratio_percent": pct(bucket["sum_NCLNLS"], bucket["sum_LNLSGR"]),
        "net_charge_off_rate_percent": pct(bucket["sum_NTLNLSQ"], bucket["sum_LNLSGR"], annualise=True),
        "cost_of_funding_earning_assets_percent": pct(bucket["sum_EINTXQ"], bucket["sum_ERNAST"], annualise=True),
        "provision_to_loans_percent": pct(bucket["sum_ELNATQ"], bucket["sum_LNLSGR"], annualise=True),
        "equity_to_assets_percent": pct(bucket["sum_EQ"], bucket["sum_ASSET"]),
        "loans_to_deposits_percent": pct(bucket["sum_LNLSGR"], bucket["sum_DEP"]),
    }


FDIC_RATIO_ASSUMPTIONS = [
    {"parameter": "return_on_assets_percent", "value": "100 * 4 * sum_NETINCQ / sum_ASSET", "method": "derived", "rationale": "Quarterly net income annualised by four over end-of-quarter total assets; the FDIC's own ROA uses average assets, which the aggregation endpoint does not return."},
    {"parameter": "net_interest_margin_percent", "value": "100 * 4 * sum_NIMQ / sum_ERNAST", "method": "derived", "rationale": "Quarterly net interest income annualised over end-of-quarter earning assets."},
    {"parameter": "efficiency_ratio_percent", "value": "100 * sum_NONIXQ / (sum_NIMQ + sum_NONIIQ)", "method": "derived", "rationale": "Quarterly noninterest expense over quarterly net interest income plus noninterest income."},
    {"parameter": "noncurrent_loan_ratio_percent", "value": "100 * sum_NCLNLS / sum_LNLSGR", "method": "derived", "rationale": "Noncurrent loans and leases over gross loans and leases, both end-of-quarter balances."},
    {"parameter": "net_charge_off_rate_percent", "value": "100 * 4 * sum_NTLNLSQ / sum_LNLSGR", "method": "derived", "rationale": "Quarterly net charge-offs annualised over end-of-quarter gross loans and leases."},
    {"parameter": "cost_of_funding_earning_assets_percent", "value": "100 * 4 * sum_EINTXQ / sum_ERNAST", "method": "derived", "rationale": "Quarterly interest expense annualised over end-of-quarter earning assets."},
    {"parameter": "provision_to_loans_percent", "value": "100 * 4 * sum_ELNATQ / sum_LNLSGR", "method": "derived", "rationale": "Quarterly provision for credit losses annualised over end-of-quarter gross loans and leases."},
    {"parameter": "equity_to_assets_percent", "value": "100 * sum_EQ / sum_ASSET", "method": "derived", "rationale": "Equity capital over total assets."},
    {"parameter": "loans_to_deposits_percent", "value": "100 * sum_LNLSGR / sum_DEP", "method": "derived", "rationale": "Gross loans and leases over total deposits."},
]


def fdic_quarterly_aggregates(raw: bytes, url: str) -> dict:
    buckets = sorted(fdic_buckets(raw), key=lambda b: b["REPDTE"])
    series = [
        {"period": iso_date(b["REPDTE"]), "value": b["sum_ASSET"], "institutions": b["count"], **{column: b[f"sum_{field}"] for field, column in FDIC_SUM_COLUMNS.items()}}
        for b in buckets
    ]
    first, last = buckets[0], buckets[-1]
    return {
        "id": "us-fdic-insured-institutions-quarterly-aggregates-2024q3-2026q2",
        "title": "FDIC-insured institutions, industry totals by quarter: assets, deposits, loans, income items, 2024Q3 to 2026Q2",
        "kind": "temporal",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": series[0]["period"], "end": series[-1]["period"]},
        "tags": ["banking", "fdic", "call-report", "quarterly-series", "balance-sheet", "income-statement"],
        "use_cases": ["banking-demo", "financial-reporting", "treasury", "market-sizing"],
        "spec": {
            "variable": "total_assets_usd_thousands",
            "unit": "currency:USD",
            "frequency": "quarterly",
            "columns": ["institutions"] + list(FDIC_SUM_COLUMNS.values()),
            "series": series,
        },
        "evidence": [
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].sum_ASSET', last["sum_ASSET"], "currency:USD", f'"REPDTE":"{last["REPDTE"]}","count":{last["count"]},"sum_ASSET":{last["sum_ASSET"]}', LICENSE, raw),
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={first["REPDTE"]}].sum_NETINCQ', first["sum_NETINCQ"], "currency:USD", f'"sum_NETINCQ":{first["sum_NETINCQ"]}', LICENSE, raw),
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].count', last["count"], "count", f'"count":{last["count"]}', LICENSE, raw),
            evidence(FDIC, "FDIC financials API field dictionary (risview_properties.yaml)", FDIC_SCHEMA_URL, "properties.data.properties.NETINCQ.title", "Net income - quarterly", "text", "title: Net income - quarterly", LICENSE, RESOURCES[FDIC_SCHEMA_URL], role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 0},
            {"statistic": f"value[{series[0]['period']}]", "expected": series[0]["value"], "tolerance": 0},
            {"statistic": f"column[net_income_quarter_usd_thousands,{series[-1]['period']}]", "expected": series[-1]["net_income_quarter_usd_thousands"], "tolerance": 0},
            {"statistic": f"column[institutions,{series[-1]['period']}]", "expected": series[-1]["institutions"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Sums over every institution filing a quarterly report with the FDIC for each of the eight report dates "
            f"from {series[0]['period']} to {series[-1]['period']}, from the BankFind Suite financials endpoint with "
            "agg_by=REPDTE and agg_sum_fields over the listed call-report items. Money is in thousands of US dollars as "
            "the API publishes it; items ending in _quarter are single-quarter flows (the API's Q-suffixed fields), the "
            "rest are end-of-quarter balances. The institution count is the number of filers aggregated for that date. "
            "Figures are revised when institutions amend their reports, so the content hash tracks the FDIC index "
            "version. " + LICENSE_NOTE
        ),
    }


def fdic_quarterly_ratios(raw: bytes, url: str) -> dict:
    buckets = sorted(fdic_buckets(raw), key=lambda b: b["REPDTE"])
    ratios = {iso_date(b["REPDTE"]): fdic_ratios(b) for b in buckets}
    columns = [name for name in next(iter(ratios.values())) if name != "return_on_assets_percent"]
    series = [{"period": period, "value": r["return_on_assets_percent"], **{c: r[c] for c in columns}} for period, r in ratios.items()]
    last = buckets[-1]
    return {
        "id": "us-fdic-insured-institutions-quarterly-performance-ratios-2024q3-2026q2",
        "title": "FDIC-insured institutions, industry performance ratios by quarter (ROA, NIM, efficiency, noncurrent, charge-off, cost of funds), 2024Q3 to 2026Q2",
        "kind": "temporal",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": series[0]["period"], "end": series[-1]["period"]},
        "tags": ["banking", "fdic", "performance-ratios", "quarterly-series", "credit-risk", "profitability"],
        "use_cases": ["banking-demo", "credit-risk", "financial-reporting", "loan-pricing"],
        "spec": {
            "variable": "return_on_assets_percent",
            "unit": "percent",
            "frequency": "quarterly",
            "columns": columns,
            "series": series,
        },
        "evidence": [
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].sum_NETINCQ', last["sum_NETINCQ"], "currency:USD", f'"sum_NETINCQ":{last["sum_NETINCQ"]}', LICENSE, raw),
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].sum_ASSET', last["sum_ASSET"], "currency:USD", f'"sum_ASSET":{last["sum_ASSET"]}', LICENSE, raw),
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].sum_NCLNLS', last["sum_NCLNLS"], "currency:USD", f'"sum_NCLNLS":{last["sum_NCLNLS"]}', LICENSE, raw),
            evidence(FDIC, "BankFind Suite financials API, sums by report date", url, f'data[REPDTE={last["REPDTE"]}].sum_LNLSGR', last["sum_LNLSGR"], "currency:USD", f'"sum_LNLSGR":{last["sum_LNLSGR"]}', LICENSE, raw),
            evidence(FDIC, "FDIC financials API field dictionary (risview_properties.yaml)", FDIC_SCHEMA_URL, "properties.data.properties.ROA.description", "Net income after taxes and extraordinary items (annualized) as a percent of average total assets.", "text", "Net income after taxes and extraordinary items (annualized) as a percent of average total assets.", LICENSE, RESOURCES[FDIC_SCHEMA_URL], role="supporting"),
        ],
        "assumed": FDIC_RATIO_ASSUMPTIONS,
        "tests": [
            {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 0.0001},
            {"statistic": f"column[noncurrent_loan_ratio_percent,{series[-1]['period']}]", "expected": series[-1]["noncurrent_loan_ratio_percent"], "tolerance": 0.0001},
            {"statistic": f"column[net_interest_margin_percent,{series[0]['period']}]", "expected": series[0]["net_interest_margin_percent"], "tolerance": 0.0001},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Industry-wide ratios for all FDIC-insured institutions, computed from the same summed call-report items as "
            "us-fdic-insured-institutions-quarterly-aggregates-2024q3-2026q2 with the formulas listed in assumed[]. "
            "Every ratio is exact arithmetic on published sums, but the definitions differ from the FDIC Quarterly "
            "Banking Profile in using end-of-quarter balances rather than averages as denominators, so the levels are "
            "close to but not identical with the FDIC's published industry ratios. Percent values are rounded to four "
            "decimals. " + LICENSE_NOTE
        ),
    }


def fdic_size_classes(responses: dict[str, tuple[str, bytes]]) -> dict:
    rows: dict[str, dict] = {}
    for key, name, filter_range in FDIC_SIZE_CLASSES:
        url, raw = responses[key]
        bucket = fdic_buckets(raw)[0]
        rows[key] = {
            "name": name,
            "asset_filter": f"ASSET:{filter_range}",
            "institutions": bucket["count"],
            "total_assets_usd_thousands": bucket["sum_ASSET"],
            **{column: bucket[f"sum_{field}"] for field, column in FDIC_SUM_COLUMNS.items()},
            **fdic_ratios(bucket),
        }
    total_count = sum(r["institutions"] for r in rows.values())
    total_assets = sum(r["total_assets_usd_thousands"] for r in rows.values())
    for r in rows.values():
        r["share_of_institutions"] = round(r["institutions"] / total_count, 6)
        r["share_of_assets"] = round(r["total_assets_usd_thousands"] / total_assets, 6)
    items = []
    for key, _, _ in FDIC_SIZE_CLASSES:
        url, raw = responses[key]
        bucket = fdic_buckets(raw)[0]
        items.append(evidence(FDIC, f"BankFind Suite financials API, {rows[key]['name']}, report date {FDIC_LATEST}", url, "data[0].count", bucket["count"], "count", f'"count":{bucket["count"]},"sum_ASSET":{bucket["sum_ASSET"]}', LICENSE, raw))
    return {
        "id": "us-fdic-insured-institutions-by-asset-size-class-2026q2",
        "title": "FDIC-insured institutions by asset-size class, 2026Q2: counts, balance-sheet totals and performance ratios",
        "kind": "rule",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "valid_from": iso_date(FDIC_LATEST),
        "valid_to": iso_date(FDIC_LATEST),
        "tags": ["banking", "fdic", "asset-size", "reference-table", "market-structure"],
        "use_cases": ["banking-demo", "company-generation", "market-sizing", "credit-risk"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"report_date": iso_date(FDIC_LATEST), "money_unit": "thousands of US dollars", "rows": rows},
            "vectors": [
                {"input": {"key": "under_100m", "column": "institutions"}, "expected": rows["under_100m"]["institutions"], "origin": "source"},
                {"input": {"key": "250b_and_over", "column": "total_assets_usd_thousands"}, "expected": rows["250b_and_over"]["total_assets_usd_thousands"], "origin": "source"},
                {"input": {"key": "1b_to_10b", "column": "name"}, "expected": "$1 billion to $10 billion", "origin": "source"},
                {"input": "10b_to_250b", "expected": True, "origin": "source"},
                {"input": "over_1t", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": items,
        "assumed": [
            {"parameter": "share_of_institutions", "value": "institutions / sum over classes", "method": "derived", "rationale": "Shares are computed from the five class counts, which together cover every filer at the report date."},
            {"parameter": "share_of_assets", "value": "total_assets_usd_thousands / sum over classes", "method": "derived", "rationale": "Asset shares are computed from the five class sums."},
            *FDIC_RATIO_ASSUMPTIONS,
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[under_100m,institutions]", "expected": rows["under_100m"]["institutions"], "tolerance": 0},
            {"statistic": "max[total_assets_usd_thousands]", "expected": max(r["total_assets_usd_thousands"] for r in rows.values()), "tolerance": 0},
        ],
        "notes": (
            f"Every FDIC-insured institution filing for the report date {iso_date(FDIC_LATEST)}, grouped into the five "
            "asset-size classes the FDIC Quarterly Banking Profile uses, with one aggregation query per class (the "
            "ASSET filter is recorded in each row; ASSET is in thousands of dollars). Each row carries the number of "
            "institutions, summed balance-sheet and single-quarter income items, the derived performance ratios of "
            "us-fdic-insured-institutions-quarterly-performance-ratios-2024q3-2026q2 and the class's share of "
            "institutions and of assets. " + LICENSE_NOTE
        ),
    }


def fdic_charter_classes(raw: bytes, url: str, schema_raw: bytes) -> dict:
    description = yaml.safe_load(schema_raw)["properties"]["data"]["properties"]["BKCLASS"]["description"]
    names = {code: text.strip() for code, text in re.findall(r"([A-Z]{1,2}) [-–] ([^;]+)", description)}
    buckets = sorted(fdic_buckets(raw), key=lambda b: -b["count"])
    total = sum(b["count"] for b in buckets)
    counts = {b["BKCLASS"]: b["count"] for b in buckets}
    assets = {b["BKCLASS"]: b["sum_ASSET"] for b in buckets}
    largest = buckets[0]
    return {
        "id": "us-fdic-insured-institutions-by-charter-class-2026q2",
        "title": "FDIC-insured institutions by charter class (BKCLASS), 2026Q2",
        "kind": "marginal",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": iso_date(FDIC_LATEST), "end": iso_date(FDIC_LATEST)},
        "tags": ["banking", "fdic", "charter-class", "market-structure", "categorical"],
        "use_cases": ["banking-demo", "company-generation", "kyb-onboarding"],
        "spec": {
            "variable": "charter_class",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {
                    "shares": {code: round(count / total, 6) for code, count in counts.items()},
                    "counts": counts,
                    "total": total,
                    "total_assets_usd_thousands": assets,
                    "names": {code: names.get(code, "") for code in counts},
                },
            },
        },
        "evidence": [
            evidence(FDIC, f"BankFind Suite financials API, count by BKCLASS, report date {FDIC_LATEST}", url, f'data[BKCLASS={largest["BKCLASS"]}].count', largest["count"], "count", f'"BKCLASS":"{largest["BKCLASS"]}","count":{largest["count"]}', LICENSE, raw),
            evidence(FDIC, f"BankFind Suite financials API, count by BKCLASS, report date {FDIC_LATEST}", url, "totals.count", total, "count", f'"totals":{{"count":{total}', LICENSE, raw),
            evidence(FDIC, "FDIC financials API field dictionary (risview_properties.yaml)", FDIC_SCHEMA_URL, "properties.data.properties.BKCLASS.description", "NM", "text", "NM - Commercial bank, state charter, Fed non-member, and supervised by the Federal Deposit Insurance Corporation (FDIC)", LICENSE, schema_raw),
        ],
        "assumed": [
            {"parameter": "shares", "value": "count / total", "method": "derived", "rationale": "Shares are the API counts divided by the total number of filers at the report date."},
        ],
        "tests": [
            {"statistic": f"share[{largest['BKCLASS']}]", "expected": round(largest["count"] / total, 6), "tolerance": 0.003},
            {"statistic": f"share[{buckets[-1]['BKCLASS']}]", "expected": round(buckets[-1]["count"] / total, 6), "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            f"Institutions filing with the FDIC for the report date {iso_date(FDIC_LATEST)} by charter class code, from "
            "the financials endpoint aggregated by BKCLASS. Codes follow the FDIC's definitions in the field dictionary "
            "(N national commercial bank, NM state non-member commercial bank, SM state member commercial bank, SB "
            "federal savings bank, SI state stock savings bank, SL state savings and loan association, OI insured US "
            "branch of a foreign bank, NC non-insured non-deposit commercial bank or trust company); the names map in "
            "the parameters carries the full text. Counts and total assets by class sit beside the shares. " + LICENSE_NOTE
        ),
    }


def fdic_states(raw: bytes, url: str) -> dict:
    buckets = [b for b in fdic_buckets(raw) if b["STNAME"]]
    unnamed = sum(b["count"] for b in fdic_buckets(raw) if not b["STNAME"])
    buckets.sort(key=lambda b: (-b["count"], b["STNAME"]))
    total = sum(b["count"] for b in buckets)
    counts = {b["STNAME"]: b["count"] for b in buckets}
    largest, smallest = buckets[0], buckets[-1]
    return {
        "id": "us-fdic-insured-institutions-by-state-2026q2",
        "title": f"FDIC-insured institutions by state of headquarters, 2026Q2 ({len(counts)} states and territories)",
        "kind": "marginal",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": iso_date(FDIC_LATEST), "end": iso_date(FDIC_LATEST)},
        "tags": ["banking", "fdic", "by-state", "market-structure", "categorical"],
        "use_cases": ["banking-demo", "company-generation", "address-generation"],
        "spec": {
            "variable": "headquarters_state",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {
                    "shares": {name: round(count / total, 6) for name, count in counts.items()},
                    "counts": counts,
                    "total": total,
                    "total_assets_usd_thousands": {b["STNAME"]: b["sum_ASSET"] for b in buckets},
                },
            },
        },
        "evidence": [
            evidence(FDIC, f"BankFind Suite financials API, count by STNAME, report date {FDIC_LATEST}", url, f'data[STNAME={largest["STNAME"]}].count', largest["count"], "count", f'"STNAME":"{largest["STNAME"]}","count":{largest["count"]}', LICENSE, raw),
            evidence(FDIC, f"BankFind Suite financials API, count by STNAME, report date {FDIC_LATEST}", url, f'data[STNAME={smallest["STNAME"]}].count', smallest["count"], "count", f'"STNAME":"{smallest["STNAME"]}","count":{smallest["count"]}', LICENSE, raw),
            evidence(FDIC, f"BankFind Suite financials API, count by STNAME, report date {FDIC_LATEST}", url, "totals.count", total + unnamed, "count", f'"totals":{{"count":{total + unnamed}', LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "shares", "value": "count / total of named states", "method": "derived", "rationale": f"Shares are the API counts divided by the filers with a state name; {unnamed} record(s) with an empty STNAME are left out of the categories and of the total."},
        ],
        "tests": [
            {"statistic": f"share[{largest['STNAME']}]", "expected": round(largest["count"] / total, 6), "tolerance": 0.003},
            {"statistic": f"share[{smallest['STNAME']}]", "expected": round(smallest["count"] / total, 6), "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            f"Institutions filing with the FDIC for the report date {iso_date(FDIC_LATEST)} by the state or territory "
            "of their headquarters (the API's STNAME field, in the upper-case form the API returns), from the financials "
            "endpoint aggregated by STNAME. Categories are ordered from the most to the fewest institutions. Summed "
            "total assets by state sit beside the counts for weighting by size rather than by number. " + LICENSE_NOTE
        ),
    }


def fdic_largest_banks(raw: bytes, url: str) -> dict:
    data = [r["data"] for r in json.loads(raw)["data"]]
    ratio_fields = {"ROA": "return_on_assets_percent", "ROAQ": "quarterly_return_on_assets_percent", "NIMY": "net_interest_margin_percent", "EEFFR": "efficiency_ratio_percent", "NCLNLSR": "noncurrent_loan_ratio_percent", "NTLNLSR": "net_charge_off_rate_percent", "INTEXPY": "cost_of_funding_earning_assets_percent", "EQV": "equity_to_assets_percent"}
    rows: dict[str, dict] = {}
    for rank, r in enumerate(data, 1):
        rows[str(r["CERT"])] = {
            "rank": rank,
            "name": r["NAME"],
            "state": r["STNAME"],
            "charter_class": r["BKCLASS"],
            "total_assets_usd_thousands": r["ASSET"],
            "total_deposits_usd_thousands": r["DEP"],
            "equity_capital_usd_thousands": r["EQ"],
            **{column: r.get(field) for field, column in ratio_fields.items()},
        }
    top, second = data[0], data[1]
    top_key = str(top["CERT"])
    return {
        "id": "us-fdic-largest-banks-by-assets-2026q2",
        "title": f"Largest {len(rows)} FDIC-insured institutions by total assets with performance ratios, 2026Q2",
        "kind": "rule",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "valid_from": iso_date(FDIC_LATEST),
        "valid_to": iso_date(FDIC_LATEST),
        "tags": ["banking", "fdic", "largest-banks", "reference-table", "performance-ratios"],
        "use_cases": ["banking-demo", "company-generation", "credit-risk", "kyb-onboarding"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"report_date": iso_date(FDIC_LATEST), "key": "FDIC certificate number", "money_unit": "thousands of US dollars", "rows": rows},
            "vectors": [
                {"input": {"key": top_key, "column": "name"}, "expected": top["NAME"], "origin": "source"},
                {"input": {"key": top_key, "column": "total_assets_usd_thousands"}, "expected": top["ASSET"], "origin": "source"},
                {"input": {"key": str(second["CERT"]), "column": "rank"}, "expected": 2, "origin": "derived", "note": "rank is the position in the API's ASSET-descending sort"},
                {"input": top_key, "expected": True, "origin": "source"},
                {"input": "0", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(FDIC, f"BankFind Suite financials API, top institutions by ASSET, report date {FDIC_LATEST}", url, f"data[CERT={top['CERT']}].ASSET", top["ASSET"], "currency:USD", f'"ASSET":{top["ASSET"]}', LICENSE, raw),
            evidence(FDIC, f"BankFind Suite financials API, top institutions by ASSET, report date {FDIC_LATEST}", url, f"data[CERT={top['CERT']}].NAME", top["NAME"], "text", f'"NAME":"{top["NAME"]}"', LICENSE, raw),
            evidence(FDIC, f"BankFind Suite financials API, top institutions by ASSET, report date {FDIC_LATEST}", url, f"data[CERT={top['CERT']}].ROA", top["ROA"], "percent", f'"ROA":{top["ROA"]}', LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "rank", "value": "1..N in ASSET-descending order", "method": "derived", "rationale": "The API sorts by ASSET descending; the rank column records that order."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[total_assets_usd_thousands]", "expected": top["ASSET"], "tolerance": 0},
            {"statistic": f"value[{top_key},net_interest_margin_percent]", "expected": top["NIMY"], "tolerance": 0},
        ],
        "notes": (
            f"The {len(rows)} FDIC-insured institutions with the largest total assets at the report date "
            f"{iso_date(FDIC_LATEST)}, keyed by FDIC certificate number, with deposits, equity and the FDIC's own "
            "per-institution ratios as published (annualised ROA and NIM, efficiency ratio, noncurrent loans to gross "
            "loans, net charge-offs to loans, interest expense to earning assets, equity to assets), unrounded. These "
            "are bank-level charters, not holding companies. " + LICENSE_NOTE
        ),
    }


# ----------------------------------------------------------------------------------------------
# IRS Statistics of Income
# ----------------------------------------------------------------------------------------------


def number(cell: Any) -> int | float | None:
    """Numeric cell value; the SOI tables write 'd' where a figure is suppressed for disclosure."""
    return cell if isinstance(cell, (int, float)) else None


def irs_corporation_sectors(raw: bytes) -> tuple[dict[str, dict], dict]:
    """Bold rows of Table 1 are the industrial sectors; the first row is the all-industry total."""
    ws = load_workbook(io.BytesIO(raw))["CRTAB01"]
    rows: dict[str, dict] = {}
    total: dict = {}
    for r in range(8, ws.max_row + 1):
        cell = ws.cell(r, 1)
        if not cell.value or not cell.font.b:
            continue
        values = [number(ws.cell(r, c).value) for c in range(2, 17)]
        record = dict(zip(IRS_CORP_COLUMNS, values))
        if record["total_receipts_usd_thousands"] and record["net_income_usd_thousands"] is not None:
            record["net_income_to_total_receipts_percent"] = pct(record["net_income_usd_thousands"], record["total_receipts_usd_thousands"])
        if record["business_receipts_usd_thousands"] and record["cost_of_goods_sold_usd_thousands"] is not None:
            record["cost_of_goods_sold_to_business_receipts_percent"] = pct(record["cost_of_goods_sold_usd_thousands"], record["business_receipts_usd_thousands"])
        name = " ".join(str(cell.value).split())
        if name.startswith("Total returns"):
            total = {"name": name, **record}
        else:
            rows[name] = record
    return rows, total


def irs_corporation_lookup(raw: bytes, rows: dict[str, dict], total: dict) -> dict:
    manufacturing = rows["Manufacturing"]
    return {
        "id": "us-irs-corporation-returns-by-sector-2023",
        "title": f"US corporation income tax returns by industrial sector, tax year 2023: returns, receipts, cost of goods sold, net income, assets ({len(rows)} sectors)",
        "kind": "rule",
        "domain": "business",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "valid_from": "2023-01-01",
        "valid_to": "2023-12-31",
        "tags": ["business", "corporations", "irs", "statistics-of-income", "by-sector", "reference-table", "profit-margin"],
        "use_cases": ["company-generation", "financial-reporting", "market-sizing", "tax-filing-demo", "sales-generation"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"tax_year": 2023, "money_unit": "thousands of US dollars", "all_sectors": total, "rows": rows},
            "vectors": [
                {"input": {"key": "Manufacturing", "column": "returns"}, "expected": manufacturing["returns"], "origin": "source"},
                {"input": {"key": "Manufacturing", "column": "total_receipts_usd_thousands"}, "expected": manufacturing["total_receipts_usd_thousands"], "origin": "source"},
                {"input": {"key": "Retail trade", "column": "cost_of_goods_sold_usd_thousands"}, "expected": rows["Retail trade"]["cost_of_goods_sold_usd_thousands"], "origin": "source"},
                {"input": "Mining", "expected": True, "origin": "source"},
                {"input": "Agricultural production", "expected": False, "origin": "derived", "note": "minor industries below the sector level are not rows"},
            ],
        },
        "evidence": [
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, "CRTAB01!B8 (Total returns of active corporations, number of returns)", total["returns"], "count", "Total returns of active corporations", LICENSE, raw),
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, "CRTAB01 row Manufacturing, column 1 (number of returns)", manufacturing["returns"], "count", "<t>Manufacturing</t>", LICENSE, raw),
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, "CRTAB01 row Manufacturing, column 3 (total receipts)", manufacturing["total_receipts_usd_thousands"], "currency:USD", f"<v>{manufacturing['total_receipts_usd_thousands']}</v>", LICENSE, raw),
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, "CRTAB01!A3 (units note)", "money amounts are in thousands of dollars", "text", "money amounts are in thousands of dollars", LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "net_income_to_total_receipts_percent", "value": "100 * net income / total receipts", "method": "derived", "rationale": "Net income (less deficit) of all returns in the sector over total receipts of all returns, both from Table 1."},
            {"parameter": "cost_of_goods_sold_to_business_receipts_percent", "value": "100 * cost of goods sold / business receipts", "method": "derived", "rationale": "Cost of goods sold over business receipts, both from Table 1; business receipts exclude investment income so this is the gross-margin complement."},
            {"parameter": "rows", "value": "bold rows of Table 1", "method": "derived", "rationale": "Sector rows are identified by the bold font the IRS uses for sector headings; the unbolded rows beneath each are minor industries and are left out."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[Manufacturing,net_income_usd_thousands]", "expected": manufacturing["net_income_usd_thousands"], "tolerance": 0},
            {"statistic": "max[total_receipts_usd_thousands]", "expected": max(r["total_receipts_usd_thousands"] for r in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Table 1 of the IRS Statistics of Income Corporation Complete Report for tax year 2023 (returns of active "
            "corporations), one row per industrial sector with the fifteen published columns renamed to snake_case "
            "and two derived margins. Money amounts are in thousands of dollars and all figures are sample-based "
            "estimates, as the table's own note says. Cells the IRS suppresses to avoid disclosure ('d') are null. "
            "The all-sector total row is kept under parameters.all_sectors. " + LICENSE_NOTE
        ),
    }


def irs_corporation_marginal(raw: bytes, rows: dict[str, dict], column: str, entry_id: str, title: str, variable: str, unit: str, locator_column: str, tags: list[str], use_cases: list[str], what: str) -> dict:
    counts = {name: r[column] for name, r in rows.items()}
    total = sum(counts.values())
    shares = {name: round(c / total, 6) for name, c in counts.items()}
    largest = max(counts, key=counts.get)
    smallest = min(counts, key=counts.get)
    return {
        "id": entry_id,
        "title": title,
        "kind": "marginal",
        "domain": "business",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {
            "variable": variable,
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total}},
        },
        "evidence": [
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, f"CRTAB01 row {largest}, {locator_column}", counts[largest], unit, f"<v>{counts[largest]}</v>", LICENSE, raw),
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, f"CRTAB01 row {smallest}, {locator_column}", counts[smallest], unit, f"<v>{counts[smallest]}</v>", LICENSE, raw),
            evidence(IRS, "Corporation Complete Report 2023, Table 1 (23co01ccr.xlsx)", IRS_CORP_URL, "CRTAB01!A4 (row heading)", "Minor industry", "text", "Minor industry", LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "shares", "value": f"{column} / sum over sectors", "method": "derived", "rationale": f"Shares are each sector's {what} divided by the sum over the {len(rows)} sectors; the sum differs slightly from the table's all-industry total because of rounding in the published estimates."},
        ],
        "tests": [
            {"statistic": f'share["{largest}"]', "expected": shares[largest], "tolerance": 0.003},
            {"statistic": f'share["{smallest}"]', "expected": shares[smallest], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            f"Distribution of {what} across the industrial sectors of Table 1 of the IRS Corporation Complete Report "
            "for tax year 2023, with the published sector figures beside the derived shares. Sector names are the "
            "IRS headings. " + LICENSE_NOTE
        ),
    }


def irs_individual_table(raw: bytes) -> tuple[list[str], dict[str, dict[str, int | float]]]:
    """AGI brackets of Historic Table 2 (United States) with the selected items keyed by bracket."""
    ws = load_workbook(io.BytesIO(raw), read_only=True)["Sheet1"]
    rows = list(ws.iter_rows(values_only=True, max_col=12))
    brackets = [" ".join(str(h).split()) for h in rows[4][2:12]]
    labels = {(" ".join(str(r[0]).split()) if r[0] else ""): i for i, r in enumerate(rows[:80])}
    table = {b: {} for b in brackets}
    all_returns: dict[str, int | float] = {}
    for label, column in IRS_INDIVIDUAL_ITEMS.items():
        index = labels[" ".join(label.split())]
        for b, value in zip(brackets, rows[index][2:12]):
            table[b][column] = value
        all_returns[column] = rows[index][1]
        if label in IRS_INDIVIDUAL_AMOUNTS:
            amount_column = IRS_INDIVIDUAL_AMOUNTS[label]
            for b, value in zip(brackets, rows[index + 1][2:12]):
                table[b][amount_column] = value
            all_returns[amount_column] = rows[index + 1][1]
    for b in brackets:
        table[b]["average_agi_usd"] = round(1000 * table[b]["agi_usd_thousands"] / table[b]["returns"], 2)
    all_returns["average_agi_usd"] = round(1000 * all_returns["agi_usd_thousands"] / all_returns["returns"], 2)
    return brackets, {"all_returns": all_returns, **table}


def irs_individual_marginal(raw: bytes, brackets: list[str], table: dict[str, dict]) -> dict:
    counts = {b: table[b]["returns"] for b in brackets}
    total = sum(counts.values())
    shares = {b: round(c / total, 6) for b, c in counts.items()}
    largest = max(counts, key=counts.get)
    return {
        "id": "us-irs-individual-returns-by-agi-size-2023",
        "title": "US individual income tax returns by size of adjusted gross income, tax year 2023",
        "kind": "marginal",
        "domain": "income",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": "2023-01-01", "end": "2023-12-31"},
        "tags": ["income", "irs", "statistics-of-income", "adjusted-gross-income", "income-bands", "categorical"],
        "use_cases": ["person-generation", "household-generation", "customer-segmentation", "personal-finance", "credit-risk", "tax-filing-demo"],
        "spec": {
            "variable": "agi_bracket",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total, "published_total": table["all_returns"]["returns"]}},
        },
        "evidence": [
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, f"Sheet1 row 'Number of returns [1]', column '{largest}'", counts[largest], "count", f"<v>{counts[largest]}</v>", LICENSE, raw),
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, "Sheet1 row 'Number of returns [1]', column 'All returns'", table["all_returns"]["returns"], "count", "<t>Number of returns [1]</t>", LICENSE, raw),
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, "Sheet1 row 5, last bracket heading", "$1,000,000 or more", "text", "$1,000,000 or more", LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "shares", "value": "returns / sum over brackets", "method": "derived", "rationale": "Shares are each bracket's number of returns divided by the sum over the ten brackets; the published all-returns total is kept beside it and differs only by rounding of the estimates."},
        ],
        "tests": [
            {"statistic": f'share["{largest}"]', "expected": shares[largest], "tolerance": 0.003},
            {"statistic": f'share["{brackets[-1]}"]', "expected": shares[brackets[-1]], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001},
        ],
        "notes": (
            "Number of individual income tax returns filed for tax year 2023 in each of the ten adjusted gross income "
            "brackets of the IRS Statistics of Income Historic Table 2 (United States file), with derived shares. The "
            "'Under $1' bracket holds returns with zero or negative AGI. Bracket labels are the IRS column headings with "
            "their line breaks collapsed. " + LICENSE_NOTE
        ),
    }


def irs_individual_lookup(raw: bytes, brackets: list[str], table: dict[str, dict]) -> dict:
    rows = {b: {"bracket_order": i, **table[b]} for i, b in enumerate(brackets, 1)}
    top = brackets[-1]
    return {
        "id": "us-irs-individual-income-by-agi-size-2023",
        "title": "US individual income tax returns by size of adjusted gross income, tax year 2023: returns by filing status, AGI, average AGI, wages, interest and dividends",
        "kind": "rule",
        "domain": "income",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "valid_from": "2023-01-01",
        "valid_to": "2023-12-31",
        "tags": ["income", "irs", "statistics-of-income", "adjusted-gross-income", "income-bands", "reference-table"],
        "use_cases": ["person-generation", "household-generation", "customer-segmentation", "personal-finance", "payroll-demo", "tax-filing-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"tax_year": 2023, "money_unit": "thousands of US dollars except average_agi_usd", "all_returns": table["all_returns"], "rows": rows},
            "vectors": [
                {"input": {"key": top, "column": "returns"}, "expected": rows[top]["returns"], "origin": "source"},
                {"input": {"key": brackets[0], "column": "agi_usd_thousands"}, "expected": rows[brackets[0]]["agi_usd_thousands"], "origin": "source"},
                {"input": {"key": top, "column": "average_agi_usd"}, "expected": rows[top]["average_agi_usd"], "origin": "derived"},
                {"input": brackets[3], "expected": True, "origin": "source"},
                {"input": "$10,000,000 or more", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, f"Sheet1 row 'Number of returns [1]', column '{top}'", rows[top]["returns"], "count", f"<v>{rows[top]['returns']}</v>", LICENSE, raw),
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, f"Sheet1 row 'Adjusted gross income (AGI) [6]', column '{top}'", rows[top]["agi_usd_thousands"], "currency:USD", f"<v>{rows[top]['agi_usd_thousands']}</v>", LICENSE, raw),
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, "Sheet1 row 'Adjusted gross income (AGI) [6]', column 'All returns'", table["all_returns"]["agi_usd_thousands"], "currency:USD", "<t>Adjusted gross income (AGI) [6]</t>", LICENSE, raw),
            evidence(IRS, "SOI Historic Table 2, tax year 2023, United States (23in54us.xlsx)", IRS_INDIVIDUAL_URL, "Sheet1!A2 (units note)", "Money amounts are in thousands of dollars", "text", "Money amounts are in thousands of dollars", LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "average_agi_usd", "value": "1000 * agi_usd_thousands / returns", "method": "derived", "rationale": "Mean AGI per return in whole dollars, from the bracket's total AGI (thousands) and number of returns; rounded to cents."},
            {"parameter": "bracket_order", "value": "1..10", "method": "derived", "rationale": "Position of the bracket from lowest to highest AGI, as the IRS orders the columns."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f'value["{top}",returns]', "expected": rows[top]["returns"], "tolerance": 0},
            {"statistic": "max[average_agi_usd]", "expected": max(r["average_agi_usd"] for r in rows.values()), "tolerance": 0.01},
        ],
        "notes": (
            "Selected items of the IRS Statistics of Income Historic Table 2 for tax year 2023 (United States file) by "
            "size of adjusted gross income: returns in total and by filing status, elderly returns, total AGI, and the "
            "number and amount of salaries and wages, taxable interest and ordinary dividends, with a derived average AGI "
            "per return. Money amounts are in thousands of dollars as published; the 'Under $1' bracket has negative "
            "total AGI. The all-returns column is kept under parameters.all_returns. " + LICENSE_NOTE
        ),
    }


# ----------------------------------------------------------------------------------------------
# Federal Reserve Data Download Program
# ----------------------------------------------------------------------------------------------


def ddp_table(raw: bytes) -> tuple[list[str], list[str], list[list[str]]]:
    """Series descriptions, series codes and data rows of a DDP CSV package in series-column layout."""
    reader = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    descriptions = reader[0][1:]
    header_index = next(i for i, row in enumerate(reader) if row and row[0] == "Time Period")
    codes = reader[header_index][1:]
    data = [row for row in reader[header_index + 1 :] if row and row[0] and not row[0].startswith("Time Period")]
    return descriptions, codes, data


def ddp_value(text: str) -> float | None:
    return float(text) if text not in ("", "ND", "NA", "NC") else None


def g19_consumer_credit(raw: bytes, url: str) -> dict:
    descriptions, codes, data = ddp_table(raw)
    columns = {
        "DTCTLR.M": "revolving_usd_millions",
        "DTCTLN.M": "nonrevolving_usd_millions",
        "DTCTL_@%A_BA.M": "total_percent_change_annual_rate",
        "DTCTLR_@%A_BA.M": "revolving_percent_change_annual_rate",
        "DTCTLN_@%A_BA.M": "nonrevolving_percent_change_annual_rate",
        "DTCTL_XDF_BA.M": "total_flow_usd_millions",
    }
    index = {code: i for i, code in enumerate(codes)}
    series = [{"period": row[0], "value": ddp_value(row[1 + index["DTCTL.M"]]), **{name: ddp_value(row[1 + index[code]]) for code, name in columns.items()}} for row in data]
    last, first = data[-1], data[0]
    total_description = descriptions[index["DTCTL.M"]]
    return {
        "id": "us-consumer-credit-outstanding-monthly-2025",
        "title": "US consumer credit outstanding, seasonally adjusted, total, revolving and nonrevolving, monthly 2025 (G.19)",
        "kind": "temporal",
        "domain": "consumer-credit",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": f"{first[0]}-01", "end": "2025-12-31"},
        "tags": ["consumer-credit", "federal-reserve", "g19", "monthly-series", "revolving-credit", "nonrevolving-credit"],
        "use_cases": ["banking-demo", "credit-risk", "market-sizing", "financial-planning", "collections"],
        "spec": {
            "variable": "total_consumer_credit_usd_millions",
            "unit": "currency:USD",
            "frequency": "monthly",
            "columns": list(columns.values()),
            "series": series,
        },
        "evidence": [
            evidence(FED, "Data Download Program, G.19 package Consumer Credit Outstanding (S.A.), 2025", url, f"row {last[0]}, column DTCTL.M", last[1 + index["DTCTL.M"]], "currency:USD", f"{last[0]},{','.join(last[1:7])}", LICENSE, raw),
            evidence(FED, "Data Download Program, G.19 package Consumer Credit Outstanding (S.A.), 2025", url, f"row {first[0]}, column DTCTLR.M", first[1 + index["DTCTLR.M"]], "currency:USD", f"{first[0]},{','.join(first[1:7])}", LICENSE, raw),
            evidence(FED, "Data Download Program, G.19 package Consumer Credit Outstanding (S.A.), 2025", url, "Series Description, column DTCTL.M", total_description, "text", total_description, LICENSE, raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last[0]}]", "expected": series[-1]["value"], "tolerance": 0.01},
            {"statistic": f"column[revolving_usd_millions,{first[0]}]", "expected": series[0]["revolving_usd_millions"], "tolerance": 0.01},
            {"statistic": f"column[nonrevolving_usd_millions,{last[0]}]", "expected": series[-1]["nonrevolving_usd_millions"], "tolerance": 0.01},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
            {"statistic": "max", "expected": max(p["value"] for p in series), "tolerance": 0.01},
        ],
        "notes": (
            "Seasonally adjusted consumer credit owned and securitised, in millions of dollars at each month end of "
            "2025, from the Federal Reserve G.19 release through the Data Download Program's preformatted package "
            "(series DTCTL.M, DTCTLR.M, DTCTLN.M), with the percent changes at a seasonally adjusted annual rate and the "
            "monthly flow the same package carries. The package CSV carries no generation timestamp, so the content "
            "hash changes only when the Board revises the series. " + LICENSE_NOTE
        ),
    }


def g19_terms_of_credit(raw: bytes, url: str, codes_wanted: dict[str, str], value_code: str, entry_id: str, title: str, variable: str, unit: str, what: str, tags: list[str]) -> dict:
    descriptions, codes, data = ddp_table(raw)
    index = {code: i for i, code in enumerate(codes)}
    rows = [row for row in data if ddp_value(row[1 + index[value_code]]) is not None]
    series = [{"period": row[0], "value": ddp_value(row[1 + index[value_code]]), **{name: ddp_value(row[1 + index[code]]) for code, name in codes_wanted.items()}} for row in rows]
    last, first = rows[-1], rows[0]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "consumer-credit",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": f"{first[0]}-01", "end": "2025-12-31"},
        "tags": tags,
        "use_cases": ["loan-pricing", "banking-demo", "automotive-demo", "personal-finance", "credit-risk"],
        "spec": {
            "variable": variable,
            "unit": unit,
            "frequency": "quarterly",
            "columns": list(codes_wanted.values()),
            "series": series,
        },
        "evidence": [
            evidence(FED, "Data Download Program, G.19 package Terms of Credit, 2025", url, f"row {last[0]}, column {value_code}", last[1 + index[value_code]], unit, f"{last[0]},{','.join(last[1:7])}", LICENSE, raw),
            evidence(FED, "Data Download Program, G.19 package Terms of Credit, 2025", url, f"row {first[0]}, column {value_code}", first[1 + index[value_code]], unit, f"{first[0]},{','.join(first[1:7])}", LICENSE, raw),
            evidence(FED, "Data Download Program, G.19 package Terms of Credit, 2025", url, f"Series Description, column {value_code}", descriptions[index[value_code]], "text", descriptions[index[value_code]], LICENSE, raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{last[0]}]", "expected": series[-1]["value"], "tolerance": 0.001},
            {"statistic": f"value[{first[0]}]", "expected": series[0]["value"], "tolerance": 0.001},
            {"statistic": f"column[{list(codes_wanted.values())[0]},{last[0]}]", "expected": series[-1][list(codes_wanted.values())[0]], "tolerance": 0.001},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"{what} from the Federal Reserve G.19 release through the Data Download Program's Terms of Credit package. "
            "The series is quarterly: the Board surveys once a quarter and publishes the figure in the month shown, "
            "leaving the other months as ND, so the period labels are the months in which the observations fall. "
            "Not seasonally adjusted. " + LICENSE_NOTE
        ),
    }


def chgdel_rates(raw: bytes, url: str, entry_id: str, title: str, what: str, tags: list[str], use_cases: list[str]) -> dict:
    descriptions, codes, data = ddp_table(raw)
    seasonal = [(i, d) for i, d in enumerate(descriptions) if "Seasonally adjusted" in d]
    prefix = re.match(r"(\w+(?:-\w+)? rate on )", descriptions[0]).group(1)
    names = {i: slug(d[len(prefix) :].split("; All commercial banks")[0]) for i, d in seasonal}
    value_index = seasonal[0][0]
    columns = [names[i] for i, _ in seasonal[1:]]
    series = [{"period": row[0], "value": ddp_value(row[1 + value_index]), **{names[i]: ddp_value(row[1 + i]) for i, _ in seasonal[1:]}} for row in data]
    last, first = data[-1], data[0]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "banking",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "observed_period": {"start": "2024-01-01", "end": "2025-12-31"},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {
            "variable": names[value_index],
            "unit": "percent",
            "frequency": "quarterly",
            "columns": columns,
            "series": series,
        },
        "evidence": [
            evidence(FED, f"Data Download Program, CHGDEL package {what} rates, all commercial banks, 2024 to 2025", url, f"row {last[0]}, column {codes[value_index]}", last[1 + value_index], "percent", f"{last[0]},{','.join(last[1:6])}", LICENSE, raw),
            evidence(FED, f"Data Download Program, CHGDEL package {what} rates, all commercial banks, 2024 to 2025", url, f"row {first[0]}, column {codes[value_index]}", first[1 + value_index], "percent", f"{first[0]},{','.join(first[1:6])}", LICENSE, raw),
            evidence(FED, f"Data Download Program, CHGDEL package {what} rates, all commercial banks, 2024 to 2025", url, f"Series Description, column {codes[value_index]}", descriptions[value_index], "text", descriptions[value_index], LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "columns", "value": "seasonally adjusted series only", "method": "derived", "rationale": "The package carries each loan category twice, seasonally adjusted and not; the adjusted series are kept and the column names are slugs of the Board's category descriptions."},
        ],
        "tests": [
            {"statistic": f"value[{last[0]}]", "expected": series[-1]["value"], "tolerance": 0.001},
            {"statistic": f"value[{first[0]}]", "expected": series[0]["value"], "tolerance": 0.001},
            {"statistic": f"column[{columns[-1]},{last[0]}]", "expected": series[-1][columns[-1]], "tolerance": 0.001},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"Seasonally adjusted {what} rates on loans at all US commercial banks by loan category, quarterly from "
            "2024Q1 to 2025Q4, from the Federal Reserve's Charge-off and Delinquency Rates release (CHGDEL) through the "
            "Data Download Program package for all banks. Rates are percent of loans, annualised for charge-offs; the "
            "all-loans series is the entry's value and each category is a column. Figures are revised as banks amend "
            "their reports. " + LICENSE_NOTE
        ),
    }


# ----------------------------------------------------------------------------------------------
# Census Bureau Quarterly Financial Report
# ----------------------------------------------------------------------------------------------


def qfr_blocks(ws, table: int) -> list[dict]:
    """Industry blocks of one QFR income-statement sheet: header, NAICS scope, net sales and after-tax margin by quarter."""
    rows = list(ws.iter_rows(values_only=True))
    title = " ".join(str(rows[1][0]).split())
    scope = re.search(r"For Corporations in (.*?), ", title + ", ").group(1)
    quarters = [re.sub(r"\s+", "", str(q)).replace("_", "") for q in rows[4][1:6]]
    quarters = [f"{q[2:]}Q{q[0]}" for q in quarters]
    percent_start = next(i for i, r in enumerate(rows) if r[1] == "(percent of net sales)")
    sales_row = next(r for r in rows[6:percent_start] if r[0] and str(r[0]).strip().startswith("Net sales"))
    after_tax_dollars = next(r for r in rows[6:percent_start] if r[0] and "after income taxes" in str(r[0]))
    after_tax_percent = next(r for r in rows[percent_start:] if r[0] and "after income taxes" in str(r[0]))
    blocks = []
    for start in (1, 6):
        header = rows[3][start] if len(rows[3]) > start else None
        if not header:
            continue
        name = " ".join(str(header).split())
        name = re.sub(r"\s+\d$", "", name)
        blocks.append({
            "header": name,
            "table": f"Table {table}.0",
            "scope": scope,
            "quarters": quarters,
            "net_sales": [sales_row[start + i] for i in range(5)],
            "after_tax_income": [after_tax_dollars[start + i] for i in range(5)],
            "after_tax_margin": [after_tax_percent[start + i] for i in range(5)],
        })
    return blocks


def qfr_rows(raw: bytes, tables: range, suffix: str) -> dict[str, dict]:
    wb = load_workbook(io.BytesIO(raw), read_only=True)
    rows: dict[str, dict] = {}
    for table in tables:
        for block in qfr_blocks(wb[f"T{table:02d}_0-{QFR_QUARTER}"], table):
            if not block["header"].endswith(suffix):
                continue
            key = re.sub(r"\s+\d$", "", block["header"][: -len(suffix)]).strip()
            if key in rows:
                continue
            record = {"table": block["table"], "naics_scope": block["scope"], "column_heading": block["header"]}
            for q, margin in zip(block["quarters"], block["after_tax_margin"]):
                record[f"after_tax_income_percent_of_sales_{q}"] = margin
            latest = block["quarters"][-1]
            record[f"net_sales_usd_millions_{latest}"] = block["net_sales"][-1]
            record[f"after_tax_income_usd_millions_{latest}"] = block["after_tax_income"][-1]
            rows[key] = record
    return rows


def qfr_entry(raw: bytes, rows: dict[str, dict], entry_id: str, title: str, coverage: str, sample_key: str, tags: list[str]) -> dict:
    latest = f"after_tax_income_percent_of_sales_{QFR_QUARTER}"
    sales = f"net_sales_usd_millions_{QFR_QUARTER}"
    sample = rows[sample_key]
    highest = max(rows, key=lambda k: rows[k][latest])
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "business",
        "region": "US",
        "status": STATUS,
        "tier": "A",
        "valid_from": "2026-04-01",
        "valid_to": "2026-06-30",
        "tags": tags,
        "use_cases": ["company-generation", "financial-reporting", "sales-generation", "market-sizing", "pricing"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"release": "Quarterly Financial Report, second quarter 2026", "coverage": coverage, "rows": rows},
            "vectors": [
                {"input": {"key": sample_key, "column": latest}, "expected": sample[latest], "origin": "source"},
                {"input": {"key": sample_key, "column": sales}, "expected": sample[sales], "origin": "source"},
                {"input": {"key": highest, "column": latest}, "expected": rows[highest][latest], "origin": "source", "note": "highest margin in the latest quarter"},
                {"input": sample_key, "expected": True, "origin": "source"},
                {"input": "Legal Services", "expected": False, "origin": "derived", "note": "the QFR excludes legal services"},
            ],
        },
        "evidence": [
            evidence(CENSUS, "Quarterly Financial Report, financial data tables workbook (qfr_tabs_f.xlsx), 2026Q2 release", QFR_URL, f"{sample['table']}, column '{sample['column_heading']}', income after income taxes as percent of net sales, 2Q 2026", sample[latest], "percent", sample["column_heading"], LICENSE, raw),
            evidence(CENSUS, "Quarterly Financial Report, financial data tables workbook (qfr_tabs_f.xlsx), 2026Q2 release", QFR_URL, f"{sample['table']}, column '{sample['column_heading']}', net sales 2Q 2026 (million dollars)", sample[sales], "currency:USD", f"<v>{sample[sales]}</v>", LICENSE, raw),
            evidence(CENSUS, "Quarterly Financial Report, financial data tables workbook (qfr_tabs_f.xlsx), 2026Q2 release", QFR_URL, f"{rows[highest]['table']}, column '{rows[highest]['column_heading']}', income after income taxes as percent of net sales, 2Q 2026", rows[highest][latest], "percent", rows[highest]["column_heading"], LICENSE, raw),
            evidence(CENSUS, "Quarterly Financial Report, financial data tables workbook (qfr_tabs_f.xlsx), 2026Q2 release", QFR_URL, "finHead!A1", "FINANCIAL DATA TABLES", "text", "This workbook consist of 170 financial tables - 85 income and 85 balance sheets.", LICENSE, raw, role="supporting"),
        ],
        "assumed": [
            {"parameter": "rows", "value": "one row per industry column heading", "method": "derived", "rationale": "Row keys are the Census column headings with the asset-size qualifier removed; the NAICS scope comes from each table's title."},
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f'value["{sample_key}",{latest}]', "expected": sample[latest], "tolerance": 0},
            {"statistic": f"max[{latest}]", "expected": rows[highest][latest], "tolerance": 0},
        ],
        "notes": (
            "After-tax profit per dollar of sales (income after income taxes as a percent of net sales, receipts and "
            "operating revenues) for the five quarters from 2Q 2025 to 2Q 2026, with the latest quarter's net sales and "
            "after-tax income in millions of dollars, from the income-statement tables of the Census Bureau Quarterly "
            f"Financial Report workbook for the second quarter of 2026. Coverage: {coverage}. The workbook sits at a "
            "'current' URL that the Census Bureau overwrites each quarter, so the content hash is expected to change "
            "at the next release; figures for earlier quarters are also revised. " + LICENSE_NOTE
        ),
    }


# ----------------------------------------------------------------------------------------------


RESOURCES: dict[str, bytes] = {}


def get(url: str) -> bytes:
    """Fetch once per run, keeping the bytes for the evidence self-check."""
    if url not in RESOURCES:
        RESOURCES[url] = fetch(url)
    return RESOURCES[url]


def main() -> int:
    get(FDIC_SCHEMA_URL)

    quarterly_url = fdic_aggregate_url(f"REPDTE:[{FDIC_FIRST} TO {FDIC_LATEST}]", "REPDTE", 8)
    quarterly_raw = get(quarterly_url)
    finish(fdic_quarterly_aggregates(quarterly_raw, quarterly_url), RESOURCES)
    finish(fdic_quarterly_ratios(quarterly_raw, quarterly_url), RESOURCES)

    size_responses = {}
    for key, _, filter_range in FDIC_SIZE_CLASSES:
        url = fdic_aggregate_url(f"REPDTE:{FDIC_LATEST} AND ASSET:{filter_range}", "REPDTE", 1)
        size_responses[key] = (url, get(url))
    finish(fdic_size_classes(size_responses), RESOURCES)

    class_url = fdic_url(f"REPDTE:{FDIC_LATEST}", "REPDTE", agg_by="BKCLASS", agg_sum_fields="ASSET", agg_limit=20, limit=1)
    finish(fdic_charter_classes(get(class_url), class_url, RESOURCES[FDIC_SCHEMA_URL]), RESOURCES)

    state_url = fdic_url(f"REPDTE:{FDIC_LATEST}", "REPDTE", agg_by="STNAME", agg_sum_fields="ASSET", agg_limit=100, limit=1)
    finish(fdic_states(get(state_url), state_url), RESOURCES)

    top_url = fdic_url(f"REPDTE:{FDIC_LATEST}", "CERT,NAME,STNAME,BKCLASS,REPDTE,ASSET,DEP,EQ,ROA,ROAQ,NIMY,EEFFR,NCLNLSR,NTLNLSR,INTEXPY,EQV", sort_by="ASSET", sort_order="DESC", limit=25)
    finish(fdic_largest_banks(get(top_url), top_url), RESOURCES)

    corp_raw = get(IRS_CORP_URL)
    sectors, total = irs_corporation_sectors(corp_raw)
    finish(irs_corporation_lookup(corp_raw, sectors, total), RESOURCES)
    finish(irs_corporation_marginal(corp_raw, sectors, "returns", "us-irs-corporation-returns-share-by-sector-2023", "US corporation income tax returns by industrial sector, tax year 2023 (share of returns)", "sector", "count", "column 1 (number of returns)", ["business", "corporations", "irs", "statistics-of-income", "by-sector", "categorical"], ["company-generation", "kyb-onboarding", "customer-segmentation"], "corporation returns"), RESOURCES)
    finish(irs_corporation_marginal(corp_raw, sectors, "business_receipts_usd_thousands", "us-irs-corporation-business-receipts-share-by-sector-2023", "US corporation business receipts by industrial sector, tax year 2023 (share of receipts)", "sector", "currency:USD", "column 5 (business receipts)", ["business", "corporations", "irs", "statistics-of-income", "by-sector", "categorical", "revenue"], ["sales-generation", "market-sizing", "company-generation", "invoicing"], "corporation business receipts"), RESOURCES)

    individual_raw = get(IRS_INDIVIDUAL_URL)
    brackets, table = irs_individual_table(individual_raw)
    finish(irs_individual_marginal(individual_raw, brackets, table), RESOURCES)
    finish(irs_individual_lookup(individual_raw, brackets, table), RESOURCES)

    levels_url = fed_package_url("G19", G19_LEVELS_PACKAGE, "01/01/2025", "12/31/2025")
    finish(g19_consumer_credit(get(levels_url), levels_url), RESOURCES)
    terms_url = fed_package_url("G19", G19_TERMS_PACKAGE, "01/01/2025", "12/31/2025")
    terms_raw = get(terms_url)
    finish(g19_terms_of_credit(terms_raw, terms_url, {"RIFSPBCICCI_N.M": "credit_card_rate_accounts_assessed_interest_percent", "RIFLPBCIANM72_N.M": "new_auto_loan_72_month_rate_percent", "RIFLPBCIANM60_N.M": "new_auto_loan_60_month_rate_percent", "RIFLPBCIANM48_N.M": "new_auto_loan_48_month_rate_percent", "RIFLPBCIPLM24_N.M": "personal_loan_24_month_rate_percent"}, "RIFSPBCICC_N.M", "us-commercial-bank-consumer-loan-rates-2025", "US commercial bank interest rates on credit card plans, new auto loans and personal loans, quarterly 2025 (G.19 terms of credit)", "credit_card_rate_all_accounts_percent", "percent", "Interest rates on credit card plans (all accounts and accounts assessed interest), new-auto instalment loans of 48, 60 and 72 months and 24-month personal loans at commercial banks", ["consumer-credit", "federal-reserve", "g19", "interest-rates", "credit-cards", "auto-loans", "quarterly-series"]), RESOURCES)
    finish(g19_terms_of_credit(terms_raw, terms_url, {"DTCTLVENM_N.M": "average_maturity_months", "DTCTLVENA_N.M": "average_amount_financed_usd"}, "RIELPCFAN_N.M", "us-finance-company-new-car-loan-terms-2025", "US new car loans at finance companies: average finance rate, maturity and amount financed, quarterly 2025 (G.19 terms of credit)", "average_finance_rate_percent", "percent", "Amount-weighted average finance rate, average maturity and average amount financed for new car loans at finance companies", ["consumer-credit", "federal-reserve", "g19", "auto-loans", "interest-rates", "quarterly-series"]), RESOURCES)

    chargeoff_url = fed_package_url("CHGDEL", CHGDEL_CHARGEOFF_PACKAGE, "01/01/2024", "12/31/2025")
    finish(chgdel_rates(get(chargeoff_url), chargeoff_url, "us-commercial-bank-charge-off-rates-2024-2025", "US commercial bank net charge-off rates by loan category, seasonally adjusted, quarterly 2024 to 2025", "charge-off", ["banking", "federal-reserve", "charge-offs", "credit-risk", "quarterly-series", "by-loan-category"], ["credit-risk", "collections", "banking-demo", "loan-pricing"]), RESOURCES)
    delinquency_url = fed_package_url("CHGDEL", CHGDEL_DELINQUENCY_PACKAGE, "01/01/2024", "12/31/2025")
    finish(chgdel_rates(get(delinquency_url), delinquency_url, "us-commercial-bank-delinquency-rates-2024-2025", "US commercial bank delinquency rates by loan category, seasonally adjusted, quarterly 2024 to 2025", "delinquency", ["banking", "federal-reserve", "delinquency", "credit-risk", "quarterly-series", "by-loan-category"], ["credit-risk", "collections", "banking-demo", "mortgage-origination"]), RESOURCES)

    qfr_raw = get(QFR_URL)
    manufacturing = qfr_rows(qfr_raw, QFR_MANUFACTURING_TABLES, " All Total Asset Sizes")
    finish(qfr_entry(qfr_raw, manufacturing, "us-qfr-manufacturing-after-tax-margin-by-industry-2026q2", f"US manufacturing corporations, after-tax profit per dollar of sales by NAICS industry, 2Q 2025 to 2Q 2026 ({len(manufacturing)} industries, all asset sizes)", "manufacturing corporations of all asset sizes", "All Manufacturing", ["business", "census", "quarterly-financial-report", "profit-margin", "manufacturing", "by-industry", "reference-table"]), RESOURCES)
    nonmanufacturing = qfr_rows(qfr_raw, QFR_NONMANUFACTURING_TABLES, " Total Assets $50 Million and Over")
    finish(qfr_entry(qfr_raw, nonmanufacturing, "us-qfr-nonmanufacturing-after-tax-margin-by-industry-2026q2", f"US nonmanufacturing corporations with $50 million or more in assets, after-tax profit per dollar of sales by industry, 2Q 2025 to 2Q 2026 ({len(nonmanufacturing)} industries)", "mining, wholesale trade, retail trade, information and professional and technical services corporations with total assets of $50 million and over", "All Retail Trade", ["business", "census", "quarterly-financial-report", "profit-margin", "retail", "wholesale", "information", "by-industry", "reference-table"]), RESOURCES)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Regenerate the US financial-services, lending, claims and customer-service value-pool entries.

Nine federal publishers, every value read from a resource fetched twice in the same run (the two
fetches must hash identically, or the build stops):

* CFPB Consumer Complaint Database public search API: complaints received in 2025 by product,
  issue, company response, submission channel, timeliness, state, company and month, plus issue and
  company-response mixes given product. The API's ``_meta.license`` field states CC0.
* FDIC BankFind Suite failures API: failed institutions since 2000 as a keyed table, per year and
  by state.
* FEMA OpenFEMA: disaster declarations by fiscal year, incident type and state, and the Individuals
  and Households Program amount approved per disaster.
* FFIEC/CFPB HMDA data browser API: 2024 loan/application records by action taken, loan purpose
  and loan type, with the Filing Instructions Guide as the code list.
* FHFA purchase-only House Price Index by state (quarterly) and by census division (monthly).
* Federal Reserve Bank of New York Household Debt and Credit Report data workbook.
* Federal Reserve Board Survey of Consumer Finances 2025 summary tables.
* US Treasury daily par yield curve for 2025.
* Federal Reserve Payments Study 2025 (calendar-year 2024 data) noncash payments table.

Only the CFPB resource states a licence, so the other entries record ``unstated`` and stay at
``license-review``. Run from the repository root:

    uv run python tools/build_usfinance.py              # every group with hash-stable sources
    uv run python tools/build_usfinance.py fdic hmda    # selected groups
    uv run python tools/build_usfinance.py cfpb         # on-demand groups (see ON_DEMAND)
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

UNSTATED = "unstated"
REVIEW = "license-review"
FEDERAL_NOTE = (
    "The publisher is a US federal body and the resource carries no licence statement, so the licence is "
    "recorded as unstated and the entry held at license-review."
)

RESOURCES: dict[str, bytes] = {}


def get(url: str) -> bytes:
    """Fetch ``url`` twice and keep the bytes only when both fetches agree, so every citation is byte-stable.

    A cold query to a caching API can answer once from its database and then from its cache; one further
    pair of fetches is allowed so that such a URL is accepted only once its answers have settled.
    """
    if url not in RESOURCES:
        for attempt in range(2):
            first, second = fetch(url), fetch(url)
            if sha(first) == sha(second):
                break
            print(f"note: first pair of fetches differed, retrying once: {url}")
        else:
            raise RuntimeError(f"unstable resource, cannot be cited: {url}")
        RESOURCES[url] = first
    return RESOURCES[url]


def text_of(url: str) -> str:
    return " ".join(Resource(url, RESOURCES[url], "").text.split())


def self_check(entry: dict) -> None:
    """Fail fast when an evidence snippet or value would not be found by the verifier."""
    for item in entry["evidence"]:
        text = text_of(item["url"])
        for label, needle in (("snippet", item["snippet"]), ("value", str(item["value"]))):
            if " ".join(needle.split()) not in text:
                raise ValueError(f"{entry['id']}: {label} {needle!r} not found in {item['url']}")
        if len(item["snippet"].split()) > 24:
            raise ValueError(f"{entry['id']}: snippet too long: {item['snippet']!r}")
    if len(entry["title"]) > 140:
        raise ValueError(f"{entry['id']}: title too long")


def finish(entry: dict) -> None:
    self_check(entry)
    write(entry)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def share_of(count: float, total: float) -> float:
    return round(count / total, 6)


STORED_NUMBERS: dict[str, dict[float, str]] = {}


def xml_cell(url: str, value: Any) -> tuple[str, str]:
    """The number text a workbook stores for ``value`` and its ``<v>…</v>`` cell markup, as the verifier searches it.

    Sheet XML writes numbers with up to 17 significant digits, so the stored text is looked up by the float
    it parses to rather than re-formatted.
    """
    if url not in STORED_NUMBERS:
        STORED_NUMBERS[url] = {float(t): t for t in re.findall(r"<v>([-+0-9.Ee]+)</v>", text_of(url))}
    stored = STORED_NUMBERS[url].get(float(value))
    if stored is None:
        raise ValueError(f"cell value {value!r} not found as XML text in {url}")
    return stored, f"<v>{stored}</v>"


def cell_evidence(publisher: str, title: str, url: str, locator: str, value: Any, unit: str, role: str = "primary") -> dict:
    """Evidence for one numeric workbook cell; the value is recorded in the form the sheet XML stores it."""
    stored, snippet = xml_cell(url, value)
    return evidence(publisher, title, url, locator, stored, unit, snippet, UNSTATED, RESOURCES[url], role=role)


def period_quarter(label: Any) -> str:
    """Normalise the NY Fed quarter labels ('03:Q1', '99:Q2' or a datetime) to YYYY-Qn."""
    if isinstance(label, datetime):
        return f"{label.year}-Q{(label.month - 1) // 3 + 1}"
    match = re.fullmatch(r"(\d{2}):Q([1-4])", str(label).strip())
    if not match:
        raise ValueError(f"unexpected quarter label {label!r}")
    yy, q = int(match.group(1)), match.group(2)
    return f"{1900 + yy if yy >= 90 else 2000 + yy}-Q{q}"


def quarter_bounds(period: str) -> tuple[str, str]:
    year, q = int(period[:4]), int(period[-1])
    first_month = 3 * (q - 1) + 1
    last_month = first_month + 2
    return f"{year}-{first_month:02d}-01", f"{year}-{last_month:02d}-{calendar.monthrange(year, last_month)[1]:02d}"


def marginal_tests(shares: dict[str, float]) -> list[dict]:
    """Share tests for the largest and smallest categories plus the share total."""
    ordered = sorted(shares, key=shares.get, reverse=True)
    largest, smallest = ordered[0], ordered[-1]
    tests = [{"statistic": f'share["{largest}"]', "expected": shares[largest], "tolerance": 0.003}]
    if smallest != largest:
        tests.append({"statistic": f'share["{smallest}"]', "expected": shares[smallest], "tolerance": 0.002})
    tests.append({"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001})
    return tests


def marginal_entry(
    *,
    entry_id: str,
    title: str,
    domain: str,
    variable: str,
    counts: dict[str, int | float],
    period: tuple[str, str],
    evidence_items: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str],
    status: str,
    extra_parameters: dict[str, Any] | None = None,
    assumed: list[dict] | None = None,
    count_key: str = "counts",
    share_rationale: str = "Shares are the published counts divided by their sum over the listed categories.",
) -> dict:
    total = sum(counts.values())
    shares = {k: share_of(v, total) for k, v in counts.items()}
    parameters = {"shares": shares, count_key: counts, "total": total, **(extra_parameters or {})}
    return {
        "id": entry_id,
        "title": title,
        "kind": "marginal",
        "domain": domain,
        "region": "US",
        "status": status,
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": parameters}},
        "evidence": evidence_items,
        "assumed": [{"parameter": "shares", "value": f"{count_key} / total", "method": "derived", "rationale": share_rationale}, *(assumed or [])],
        "tests": marginal_tests(shares),
        "notes": notes,
    }


def temporal_entry(
    *,
    entry_id: str,
    title: str,
    domain: str,
    variable: str,
    unit: str,
    frequency: str,
    series: list[dict],
    columns: list[str],
    evidence_items: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str],
    status: str,
    assumed: list[dict] | None = None,
    tests: list[dict] | None = None,
    period: tuple[str, str] | None = None,
) -> dict:
    first, last = series[0], series[-1]
    default_tests = [
        {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
        {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "US",
        "status": status,
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]} if period else None,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": default_tests + (tests or []),
        "notes": notes,
    }


def lookup_entry(
    *,
    entry_id: str,
    title: str,
    domain: str,
    rows: dict[str, dict],
    parameters: dict[str, Any],
    vectors: list[dict],
    valid: tuple[str, str],
    evidence_items: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str],
    status: str,
    assumed: list[dict] | None = None,
    tests: list[dict] | None = None,
) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "US",
        "status": status,
        "tier": "A",
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": "almanac.rules.lookup_table", "parameters": {**parameters, "rows": rows}, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            *(tests or []),
        ],
        "notes": notes,
    }


# ----------------------------------------------------------------------------------------------
# CFPB Consumer Complaint Database
# ----------------------------------------------------------------------------------------------

CFPB = "Consumer Financial Protection Bureau"
CFPB_API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
CFPB_LICENSE = "CC0-1.0"
CFPB_STATUS = "verified"
CFPB_YEAR = ("2025-01-01", "2025-12-31")
CFPB_TAGS = ["complaints", "cfpb", "customer-service", "consumer-finance"]
CFPB_USE_CASES = ["customer-service-demo", "banking-demo", "crm-demo", "collections"]
CFPB_NOTE = (
    "Counts come from the Consumer Complaint Database search API with size=0, which returns only the "
    "aggregations over complaints received between the two dates. The API has no pinned or versioned form and "
    "the database grows as companies respond and new complaints are published, so counts for a closed period "
    "still move and the content hash tracks the day's index: re-indexed daily; rebuild before release. The API's "
    "_meta block states the data licence as CC0 and is cited as supporting evidence."
)


def cfpb_url(start: str, end: str, product: str | None = None) -> str:
    url = f"{CFPB_API}?size=0&date_received_min={start}&date_received_max={end}"
    return url + (f"&product={quote(product, safe='')}" if product else "")


def cfpb_total(raw: bytes) -> int:
    return json.loads(raw)["hits"]["total"]["value"]


def cfpb_buckets(raw: bytes, field: str) -> list[tuple[str, int]]:
    buckets = json.loads(raw)["aggregations"][field][field]["buckets"]
    return [(b["key"], b["doc_count"]) for b in buckets]


def cfpb_snippet(key: str, count: int) -> str:
    return f'{{"key":{json.dumps(key, ensure_ascii=False)},"doc_count":{count}'


def cfpb_evidence(url: str, field: str, key: str, count: int, title: str) -> dict:
    return evidence(CFPB, title, url, f"aggregations.{field}.{field}.buckets[key={key}].doc_count", count, "count", cfpb_snippet(key, count), CFPB_LICENSE, RESOURCES[url])


def cfpb_license_evidence(url: str, title: str) -> dict:
    return evidence(CFPB, title, url, "_meta.license", "CC0", "text", '"license":"CC0"', CFPB_LICENSE, RESOURCES[url], role="supporting")


def cfpb_total_evidence(url: str, title: str) -> dict:
    total = cfpb_total(RESOURCES[url])
    return evidence(CFPB, title, url, "hits.total.value", total, "count", f'"total":{{"value":{total}', CFPB_LICENSE, RESOURCES[url])


def cfpb_simple_marginal(url: str, field: str, entry_id: str, title: str, variable: str, what: str, extra_tags: list[str], use_cases: list[str], extra_note: str = "") -> dict:
    counts = dict(cfpb_buckets(RESOURCES[url], field))
    total = cfpb_total(RESOURCES[url])
    api_title = "Consumer Complaint Database search API, complaints received in 2025"
    largest, smallest = max(counts, key=counts.get), min(counts, key=counts.get)
    items = [
        cfpb_evidence(url, field, largest, counts[largest], api_title),
        cfpb_evidence(url, field, smallest, counts[smallest], api_title),
        cfpb_total_evidence(url, api_title),
        cfpb_license_evidence(url, api_title),
    ]
    uncategorised = total - sum(counts.values())
    return marginal_entry(
        entry_id=entry_id,
        title=title,
        domain="complaints",
        variable=variable,
        counts=counts,
        period=CFPB_YEAR,
        evidence_items=items,
        notes=(
            f"Complaints received by the CFPB in calendar 2025 by {what}, from the {field} aggregation of the search "
            f"API. The categories carry the API's own labels. {uncategorised} of the {total} complaints have no value "
            f"for this field and are left out of the shares. {extra_note}{CFPB_NOTE}"
        ).replace("  ", " "),
        tags=CFPB_TAGS + extra_tags,
        use_cases=use_cases,
        status=CFPB_STATUS,
        extra_parameters={"complaints_in_period": total},
        share_rationale=f"Shares are bucket counts divided by their sum; {uncategorised} complaints without a {field} value are excluded.",
    )


def cfpb_top_n_marginal(url: str, field: str, n: int, other_label: str, entry_id: str, title: str, variable: str, what: str, extra_tags: list[str], use_cases: list[str]) -> dict:
    buckets = cfpb_buckets(RESOURCES[url], field)
    total = cfpb_total(RESOURCES[url])
    top = dict(buckets[:n])
    remainder = total - sum(top.values())
    counts = {**top, other_label: remainder}
    api_title = "Consumer Complaint Database search API, complaints received in 2025"
    first_key, nth_key = buckets[0][0], buckets[n - 1][0]
    items = [
        cfpb_evidence(url, field, first_key, top[first_key], api_title),
        cfpb_evidence(url, field, nth_key, top[nth_key], api_title),
        cfpb_total_evidence(url, api_title),
        cfpb_license_evidence(url, api_title),
    ]
    entry = marginal_entry(
        entry_id=entry_id,
        title=title,
        domain="complaints",
        variable=variable,
        counts=counts,
        period=CFPB_YEAR,
        evidence_items=items,
        notes=(
            f"Complaints received by the CFPB in calendar 2025 by {what}: the {n} most frequent values of the API's "
            f"{field} aggregation, in the API's descending order, with every other value folded into "
            f"'{other_label}' so the shares sum to one over all {total} complaints. The API returned "
            f"{len(buckets)} distinct values in all. {CFPB_NOTE}"
        ),
        tags=CFPB_TAGS + extra_tags,
        use_cases=use_cases,
        status=CFPB_STATUS,
        extra_parameters={"complaints_in_period": total, "distinct_values_in_source": len(buckets)},
        assumed=[{"parameter": other_label, "value": f"total - sum of top {n}", "method": "derived", "rationale": f"The remainder category is the total complaint count less the {n} listed buckets."}],
    )
    return entry


def cfpb_monthly(urls: dict[str, str], annual_url: str) -> dict:
    series = [{"period": month, "value": cfpb_total(RESOURCES[url])} for month, url in sorted(urls.items())]
    annual = cfpb_total(RESOURCES[annual_url])
    if sum(p["value"] for p in series) != annual:
        raise ValueError("monthly complaint counts do not sum to the annual total")
    api_title = "Consumer Complaint Database search API, complaints received in the month"
    items = [cfpb_total_evidence(url, f"{api_title} {month}") for month, url in sorted(urls.items())]
    items.append(cfpb_total_evidence(annual_url, "Consumer Complaint Database search API, complaints received in 2025"))
    items.append(cfpb_license_evidence(annual_url, "Consumer Complaint Database search API, complaints received in 2025"))
    peak = max(series, key=lambda p: p["value"])
    return temporal_entry(
        entry_id="us-cfpb-consumer-complaints-received-by-month-2025",
        title="CFPB consumer complaints received per month, 2025",
        domain="complaints",
        variable="complaints_received",
        unit="count",
        frequency="monthly",
        series=series,
        columns=[],
        evidence_items=items,
        notes=(
            "Number of complaints the CFPB received in each month of 2025, one search-API query per month with "
            "size=0 and date_received_min/max set to the first and last day of the month. The twelve monthly "
            f"counts sum exactly to the annual query's total of {annual}, which confirms both bounds are inclusive. "
            f"The busiest month was {peak['period']}. {CFPB_NOTE}"
        ),
        tags=CFPB_TAGS + ["monthly-series", "seasonality"],
        use_cases=CFPB_USE_CASES + ["event-timestamps", "capacity-planning"],
        status=CFPB_STATUS,
        tests=[{"statistic": f"value[{peak['period']}]", "expected": peak["value"], "tolerance": 0}],
        period=CFPB_YEAR,
    )


def cfpb_conditional(product_urls: dict[str, str], annual_url: str, field: str, top_n: int | None, other_label: str | None, entry_id: str, title: str, variable: str, what: str, use_cases: list[str]) -> dict:
    product_counts = dict(cfpb_buckets(RESOURCES[annual_url], "product"))
    distributions: dict[str, dict] = {}
    items: list[dict] = []
    for product, url in product_urls.items():
        raw = RESOURCES[url]
        total = cfpb_total(raw)
        if total != product_counts[product]:
            raise ValueError(f"product filter {product!r} returned {total}, expected {product_counts[product]}")
        buckets = cfpb_buckets(raw, field)
        if top_n is not None and other_label is not None:
            head = dict(buckets[:top_n])
            counts = {**head, other_label: total - sum(head.values())} if len(buckets) > top_n else head
        else:
            counts = dict(buckets)
        shares = {k: share_of(v, total) for k, v in counts.items()}
        distributions[product] = {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total}}
        key, count = buckets[0]
        items.append(cfpb_evidence(url, field, key, count, f"Consumer Complaint Database search API, product {product}, 2025"))
    items.append(cfpb_license_evidence(annual_url, "Consumer Complaint Database search API, complaints received in 2025"))
    tests = []
    for product, dist in distributions.items():
        shares = dist["parameters"]["shares"]
        top = max(shares, key=shares.get)
        tests.append({"statistic": f'share["{product}","{top}"]', "expected": shares[top], "tolerance": 0.003})
        tests.append({"statistic": f'sum_of_shares["{product}"]', "expected": 1, "tolerance": 0.0001})
    assumed = [{"parameter": "shares", "value": "counts / total", "method": "derived", "rationale": "Shares are the product-filtered bucket counts divided by the product's complaint total."}]
    if other_label:
        assumed.append({"parameter": other_label, "value": f"total - sum of top {top_n}", "method": "derived", "rationale": f"Values beyond the {top_n} most frequent are folded into one remainder category per product."})
    return {
        "id": entry_id,
        "title": title,
        "kind": "conditional",
        "domain": "complaints",
        "region": "US",
        "status": CFPB_STATUS,
        "tier": "A",
        "observed_period": {"start": CFPB_YEAR[0], "end": CFPB_YEAR[1]},
        "tags": CFPB_TAGS + ["by-product", "conditional"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": "ratio", "given": "product", "distributions": distributions},
        "evidence": items,
        "assumed": assumed,
        "tests": tests,
        "notes": (
            f"Distribution of {what} given the product a complaint is about, for complaints received in 2025: one "
            f"search-API query per product (the product filter), reading the {field} aggregation. Each conditional "
            "total equals the product's bucket count in the unfiltered query, which the builder checks. Product and "
            f"category labels are the API's own. {CFPB_NOTE}"
        ),
    }


def build_cfpb() -> None:
    annual = cfpb_url(*CFPB_YEAR)
    get(annual)
    finish(cfpb_simple_marginal(annual, "product", "us-cfpb-consumer-complaints-by-product-2025", "CFPB consumer complaints by product, 2025", "product", "financial product", ["by-product"], CFPB_USE_CASES + ["customer-segmentation"]))
    finish(cfpb_simple_marginal(annual, "company_response", "us-cfpb-consumer-complaints-by-company-response-2025", "CFPB consumer complaints by company response to the consumer, 2025", "company_response", "the company's response", ["company-response", "outcomes"], CFPB_USE_CASES + ["sla-calculation"]))
    finish(cfpb_simple_marginal(annual, "submitted_via", "us-cfpb-consumer-complaints-by-submission-channel-2025", "CFPB consumer complaints by submission channel, 2025", "submission_channel", "the channel the complaint was submitted through", ["channel", "digital-channels"], CFPB_USE_CASES + ["digital-channels"]))
    finish(cfpb_simple_marginal(annual, "timely", "us-cfpb-consumer-complaints-timely-response-2025", "CFPB consumer complaints: share answered by the company in a timely manner, 2025", "timely_response", "whether the company responded within the CFPB's 15-day window (the API's timely field)", ["timeliness", "sla"], CFPB_USE_CASES + ["sla-calculation"]))
    finish(cfpb_simple_marginal(annual, "state", "us-cfpb-consumer-complaints-by-state-2025", "CFPB consumer complaints by consumer state or territory, 2025", "state", "the consumer's state, territory or military post code", ["by-state", "geography"], CFPB_USE_CASES + ["address-generation", "customer-segmentation"], "Categories are the two-letter codes the API returns, including territories, military post codes and one spelled-out outlying-islands value. "))
    finish(cfpb_top_n_marginal(annual, "issue", 20, "Other issues", "us-cfpb-consumer-complaints-by-issue-top-20-2025", "CFPB consumer complaints by issue, twenty most frequent issues and remainder, 2025", "issue", "the issue the consumer selected", ["by-issue", "top-20"], CFPB_USE_CASES + ["customer-segmentation"]))
    finish(cfpb_top_n_marginal(annual, "company", 20, "All other companies", "us-cfpb-consumer-complaints-by-company-top-20-2025", "CFPB consumer complaints by company, twenty most complained-about companies and remainder, 2025", "company", "the company the complaint was sent to", ["by-company", "top-20"], CFPB_USE_CASES + ["company-generation"]))

    months = {}
    for month in range(1, 13):
        last = calendar.monthrange(2025, month)[1]
        months[f"2025-{month:02d}"] = cfpb_url(f"2025-{month:02d}-01", f"2025-{month:02d}-{last:02d}")
    for url in months.values():
        get(url)
    finish(cfpb_monthly(months, annual))

    product_urls = {product: cfpb_url(*CFPB_YEAR, product=product) for product, _ in cfpb_buckets(RESOURCES[annual], "product")}
    for url in product_urls.values():
        get(url)
    finish(cfpb_conditional(product_urls, annual, "issue", 10, "Other issues", "us-cfpb-consumer-complaint-issue-given-product-2025", "CFPB consumer complaint issue given product, ten most frequent issues per product and remainder, 2025", "issue", "the issue the consumer selected", CFPB_USE_CASES + ["customer-segmentation"]))
    finish(cfpb_conditional(product_urls, annual, "company_response", None, None, "us-cfpb-consumer-complaint-company-response-given-product-2025", "CFPB company response to the consumer given product, 2025", "company_response", "the company's response to the consumer", CFPB_USE_CASES + ["sla-calculation"]))


# ----------------------------------------------------------------------------------------------
# FDIC bank failures
# ----------------------------------------------------------------------------------------------

FDIC = "FDIC"
FDIC_FAILURES = "https://api.fdic.gov/banks/failures"
FDIC_FAILURE_SCHEMA = "https://api.fdic.gov/banks/docs/failure_properties.yaml"
FDIC_FILTER = quote("FAILYR:[2000 TO 2026]", safe="")
FDIC_LIST_URL = f"{FDIC_FAILURES}?filters={FDIC_FILTER}&fields=NAME,CITYST,PSTALP,CERT,FAILDATE,FAILYR,QBFASSET,QBFDEP,COST,RESTYPE,CHCLASS1,SAVR&limit=1000&sort_by=FAILDATE&sort_order=ASC&format=json"
FDIC_YEAR_URL = f"{FDIC_FAILURES}?filters={FDIC_FILTER}&fields=FAILYR&agg_by=FAILYR&agg_limit=100&limit=1&format=json"
FDIC_STATE_URL = f"{FDIC_FAILURES}?filters={FDIC_FILTER}&fields=PSTALP&agg_by=PSTALP&agg_limit=100&limit=1&format=json"
FDIC_TAGS = ["banking", "fdic", "bank-failures", "failure-events"]
FDIC_USE_CASES = ["banking-demo", "credit-risk", "company-generation", "event-timestamps"]


def fdic_rows(raw: bytes) -> list[dict]:
    return [r["data"] for r in json.loads(raw)["data"]]


def fdic_agg(raw: bytes, field: str) -> dict[str, int]:
    return {b["data"][field]: b["data"]["count"] for b in json.loads(raw)["data"]}


def iso_from_us(text: str) -> str:
    return datetime.strptime(text, "%m/%d/%Y").date().isoformat()


def fdic_failed_banks() -> dict:
    raw = RESOURCES[FDIC_LIST_URL]
    records = fdic_rows(raw)
    rows: dict[str, dict] = {}
    for r in records:
        key = str(r["CERT"])
        if key in rows:
            raise ValueError(f"duplicate certificate {key}")
        rows[key] = {
            "name": r["NAME"],
            "city_state": r["CITYST"],
            "state": r["PSTALP"],
            "failure_date": iso_from_us(r["FAILDATE"]),
            "failure_year": int(r["FAILYR"]),
            "total_assets_usd_thousands": r.get("QBFASSET"),
            "total_deposits_usd_thousands": r.get("QBFDEP"),
            "estimated_loss_usd_thousands": r.get("COST"),
            "resolution_type": r.get("RESTYPE"),
            "charter_class": r.get("CHCLASS1"),
            "insurance_fund": r.get("SAVR"),
        }
    first, last = records[0], records[-1]
    largest = max(records, key=lambda r: r.get("QBFASSET") or 0)
    schema = RESOURCES[FDIC_FAILURE_SCHEMA]
    items = [
        evidence(FDIC, "BankFind Suite failures API, failures since 2000", FDIC_LIST_URL, f"data[CERT={largest['CERT']}].QBFASSET", largest["QBFASSET"], "currency:USD", f'"QBFASSET":{largest["QBFASSET"]}', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, failures since 2000", FDIC_LIST_URL, f"data[CERT={largest['CERT']}].NAME", largest["NAME"], "text", f'"NAME":"{largest["NAME"]}"', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, failures since 2000", FDIC_LIST_URL, f"data[CERT={last['CERT']}].FAILDATE", last["FAILDATE"], "text", f'"FAILDATE":"{last["FAILDATE"]}"', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, failures since 2000", FDIC_LIST_URL, "meta.total", len(records), "count", f'"total":{len(records)}', UNSTATED, raw),
        evidence(FDIC, "FDIC failures API field dictionary (failure_properties.yaml)", FDIC_FAILURE_SCHEMA, "properties.data.properties.QBFASSET.x-number-unit", "Thousands of US Dollars", "text", "x-number-unit: Thousands of US Dollars", UNSTATED, schema, role="supporting"),
    ]
    return lookup_entry(
        entry_id="us-fdic-failed-banks-since-2000",
        title=f"FDIC failed and assisted institutions since 2000 ({len(rows)} events): date, state, assets, deposits, estimated loss",
        domain="banking",
        rows=rows,
        parameters={"key": "FDIC certificate number", "money_unit": "thousands of US dollars", "first_failure_date": rows[str(first["CERT"])]["failure_date"], "last_failure_date": rows[str(last["CERT"])]["failure_date"]},
        vectors=[
            {"input": {"key": str(largest["CERT"]), "column": "name"}, "expected": largest["NAME"], "origin": "source"},
            {"input": {"key": str(largest["CERT"]), "column": "total_assets_usd_thousands"}, "expected": largest["QBFASSET"], "origin": "source"},
            {"input": {"key": str(first["CERT"]), "column": "failure_date"}, "expected": rows[str(first["CERT"])]["failure_date"], "origin": "derived", "note": "FAILDATE restated from m/d/yyyy to ISO 8601"},
            {"input": str(last["CERT"]), "expected": True, "origin": "source"},
            {"input": "0", "expected": False, "origin": "derived"},
        ],
        valid=("2000-01-01", rows[str(last["CERT"])]["failure_date"]),
        evidence_items=items,
        notes=(
            "Every bank failure or assistance transaction the FDIC records from 2000 onward, keyed by the FDIC "
            "certificate number, from the BankFind Suite failures endpoint sorted by failure date. Columns are the "
            "API's fields: total assets and total deposits at the last quarterly report before failure (QBFASSET, "
            "QBFDEP) and the estimated loss to the insurance fund (COST), all in thousands of US dollars and null where "
            "the FDIC has not published them; resolution type, charter class and the insurance fund as the API codes "
            "them. The failure date is restated from the API's m/d/yyyy form to ISO 8601. The list is updated when "
            "institutions fail, so the hash tracks the FDIC index version. " + FEDERAL_NOTE
        ),
        tags=FDIC_TAGS + ["reference-table"],
        use_cases=FDIC_USE_CASES + ["kyb-onboarding"],
        status=REVIEW,
        assumed=[{"parameter": "failure_date", "value": "ISO 8601 of FAILDATE", "method": "derived", "rationale": "The API returns dates as m/d/yyyy; they are restated as yyyy-mm-dd."}],
        tests=[{"statistic": "max[total_assets_usd_thousands]", "expected": largest["QBFASSET"], "tolerance": 0}],
    )


def fdic_failures_by_year() -> dict:
    raw = RESOURCES[FDIC_YEAR_URL]
    counts = fdic_agg(raw, "FAILYR")
    series = [{"period": str(year), "value": counts.get(str(year), 0)} for year in range(2000, 2026)]
    zero_years = [p["period"] for p in series if p["value"] == 0]
    peak = max(series, key=lambda p: p["value"])
    items = [
        evidence(FDIC, "BankFind Suite failures API, count by FAILYR", FDIC_YEAR_URL, f"data[FAILYR={peak['period']}].count", peak["value"], "count", f'"FAILYR":"{peak["period"]}","count":{peak["value"]}', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, count by FAILYR", FDIC_YEAR_URL, "data[FAILYR=2025].count", counts["2025"], "count", f'"FAILYR":"2025","count":{counts["2025"]}', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, count by FAILYR", FDIC_YEAR_URL, "totals.count", sum(counts.values()), "count", f'"totals":{{"count":{sum(counts.values())}', UNSTATED, raw),
    ]
    return temporal_entry(
        entry_id="us-fdic-bank-failures-per-year-2000-2025",
        title="FDIC-insured institution failures per year, 2000 to 2025",
        domain="banking",
        variable="bank_failures",
        unit="count",
        frequency="annual",
        series=series,
        columns=[],
        evidence_items=items,
        notes=(
            "Number of FDIC-insured institutions that failed or received assistance in each calendar year from 2000 "
            "to 2025, from the failures endpoint aggregated by FAILYR. The aggregation omits years with no failures, "
            f"so {', '.join(zero_years)} are written as zero. The query's filter also covers 2026, whose partial count "
            f"is left out of the series because the year is not complete. The peak year was {peak['period']}. " + FEDERAL_NOTE
        ),
        tags=FDIC_TAGS + ["annual-series"],
        use_cases=FDIC_USE_CASES,
        status=REVIEW,
        assumed=[{"parameter": "zero years", "value": zero_years, "method": "derived", "rationale": "Years absent from the FAILYR aggregation had no failures and are written as 0."}],
        tests=[{"statistic": f"value[{peak['period']}]", "expected": peak["value"], "tolerance": 0}, {"statistic": "max", "expected": peak["value"], "tolerance": 0}],
        period=("2000-01-01", "2025-12-31"),
    )


def fdic_failures_by_state() -> dict:
    raw = RESOURCES[FDIC_STATE_URL]
    counts = dict(sorted(fdic_agg(raw, "PSTALP").items(), key=lambda kv: (-kv[1], kv[0])))
    largest, smallest = next(iter(counts)), list(counts)[-1]
    items = [
        evidence(FDIC, "BankFind Suite failures API, count by PSTALP", FDIC_STATE_URL, f"data[PSTALP={largest}].count", counts[largest], "count", f'"PSTALP":"{largest}","count":{counts[largest]}', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, count by PSTALP", FDIC_STATE_URL, f"data[PSTALP={smallest}].count", counts[smallest], "count", f'"PSTALP":"{smallest}","count":{counts[smallest]}', UNSTATED, raw),
        evidence(FDIC, "BankFind Suite failures API, count by PSTALP", FDIC_STATE_URL, "totals.count", sum(counts.values()), "count", f'"totals":{{"count":{sum(counts.values())}', UNSTATED, raw),
    ]
    return marginal_entry(
        entry_id="us-fdic-bank-failures-by-state-2000-2026",
        title=f"FDIC-insured institution failures by state, 2000 to 2026 ({len(counts)} states)",
        domain="banking",
        variable="state",
        counts=counts,
        period=("2000-01-01", "2026-10-31"),
        evidence_items=items,
        notes=(
            "Failures and assistance transactions since 2000 by the state of the failed institution (the API's "
            "PSTALP postal abbreviation), from the failures endpoint aggregated by PSTALP, ordered from most to fewest. "
            "The observed period ends at the build date because 2026 failures to that date are included. " + FEDERAL_NOTE
        ),
        tags=FDIC_TAGS + ["by-state"],
        use_cases=FDIC_USE_CASES + ["address-generation"],
        status=REVIEW,
    )


def build_fdic() -> None:
    for url in (FDIC_LIST_URL, FDIC_YEAR_URL, FDIC_STATE_URL, FDIC_FAILURE_SCHEMA):
        get(url)
    finish(fdic_failed_banks())
    finish(fdic_failures_by_year())
    finish(fdic_failures_by_state())


# ----------------------------------------------------------------------------------------------
# FEMA OpenFEMA
# ----------------------------------------------------------------------------------------------

FEMA = "Federal Emergency Management Agency"
FEMA_API = "https://www.fema.gov/api/open"
FEMA_DECLARATION_FIELDS = "femaDeclarationString,disasterNumber,state,declarationType,declarationDate,fyDeclared,incidentType"
FEMA_WEB_FIELDS = "disasterNumber,totalNumberIaApproved,totalAmountIhpApproved,totalAmountHaApproved"


def fema_declarations_url(fiscal_years: str) -> str:
    """Disaster Declarations Summaries for a closed fiscal-year filter, reduced to the columns the entries read.

    Selecting columns drops the per-row refresh timestamp and hash, and the sort makes the row order
    reproducible; rows of one declaration share every selected column, so ties cannot reorder the bytes.
    """
    return (
        f"{FEMA_API}/v2/DisasterDeclarationsSummaries?$select={FEMA_DECLARATION_FIELDS}"
        f"&$filter={quote(fiscal_years, safe='')}&$orderby=femaDeclarationString&$format=csv&$allrecords=true"
    )


FEMA_DECLARATIONS_URL = fema_declarations_url("fyDeclared le 2025")
FEMA_RECENT_URL = fema_declarations_url("fyDeclared ge 2024 and fyDeclared le 2026")
FEMA_WEB_URL = (
    f"{FEMA_API}/v1/FemaWebDisasterSummaries?$select={FEMA_WEB_FIELDS}"
    f"&$filter={quote('totalAmountIhpApproved gt 0', safe='')}&$orderby=disasterNumber&$format=csv&$allrecords=true"
)
FEMA_TAGS = ["claims", "fema", "disasters", "insurance"]
FEMA_USE_CASES = ["insurance-demo", "claims-generation", "event-timestamps", "capacity-planning"]
FEMA_NOTE = (
    "The OpenFEMA query is pinned to closed fiscal years, a fixed column list and an explicit sort, but OpenFEMA "
    "refreshes its tables daily as amendments add designated areas and assistance totals grow, so the content hash "
    "tracks the day's data: re-indexed daily; rebuild before release. " + FEDERAL_NOTE
)


def csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def distinct_disasters(rows: Iterable[dict], key: str) -> dict[str, int]:
    seen: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        seen[r[key]].add(r["disasterNumber"])
    return {k: len(v) for k, v in seen.items()}


def fema_row_snippet(r: dict) -> str:
    return ",".join([r["femaDeclarationString"], r["disasterNumber"], r["state"], r["declarationType"], r["declarationDate"], r["fyDeclared"], r["incidentType"]])


def fema_declarations_by_year() -> dict:
    raw = RESOURCES[FEMA_DECLARATIONS_URL]
    rows = csv_rows(raw)
    by_year = distinct_disasters(rows, "fyDeclared")
    by_year_type: dict[str, Counter] = defaultdict(Counter)
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if (r["fyDeclared"], r["disasterNumber"]) not in seen:
            seen.add((r["fyDeclared"], r["disasterNumber"]))
            by_year_type[r["fyDeclared"]][r["declarationType"]] += 1
    area_rows = Counter(r["fyDeclared"] for r in rows)
    years = sorted(y for y in by_year if 1953 <= int(y) <= 2025)
    series = [
        {
            "period": y,
            "value": by_year[y],
            "major_disaster_declarations": by_year_type[y].get("DR", 0),
            "emergency_declarations": by_year_type[y].get("EM", 0),
            "fire_management_declarations": by_year_type[y].get("FM", 0),
            "designated_area_rows": area_rows[y],
        }
        for y in years
    ]
    peak = max(series, key=lambda p: p["value"])
    sample = next(r for r in rows if r["fyDeclared"] == "2025" and r["declarationType"] == "DR")
    items = [
        evidence(FEMA, "OpenFEMA Disaster Declarations Summaries v2, fyDeclared <= 2025 (CSV)", FEMA_DECLARATIONS_URL, f"row femaDeclarationString={sample['femaDeclarationString']}", sample["disasterNumber"], "text", fema_row_snippet(sample), UNSTATED, raw),
        evidence(FEMA, "OpenFEMA Disaster Declarations Summaries v2, fyDeclared <= 2025 (CSV)", FEMA_DECLARATIONS_URL, "header row", "fyDeclared", "text", FEMA_DECLARATION_FIELDS, UNSTATED, raw),
    ]
    return temporal_entry(
        entry_id="us-fema-disaster-declarations-per-fiscal-year-1953-2025",
        title="FEMA disaster declarations per federal fiscal year, 1953 to 2025, by declaration type",
        domain="insurance",
        variable="disaster_declarations",
        unit="count",
        frequency="annual",
        series=series,
        columns=["major_disaster_declarations", "emergency_declarations", "fire_management_declarations", "designated_area_rows"],
        evidence_items=items,
        notes=(
            "Distinct disaster numbers declared in each federal fiscal year (fyDeclared), counted from the OpenFEMA "
            "Disaster Declarations Summaries for fiscal years to 2025, which have one row per declared disaster and designated area. The "
            "columns split the count by declaration type (DR major disaster, EM emergency, FM fire management) and "
            "give the number of designated-area rows in the year. Fiscal years run from 1 October to 30 September. "
            f"The query stops at FY2025. The busiest year was FY{peak['period']}. " + FEMA_NOTE
        ),
        tags=FEMA_TAGS + ["annual-series"],
        use_cases=FEMA_USE_CASES,
        status=REVIEW,
        assumed=[
            {"parameter": "value", "value": "count of distinct disasterNumber per fyDeclared", "method": "derived", "rationale": "The file lists one row per designated area; disasters are counted once."},
            {"parameter": "declaration type columns", "value": "distinct disasters per declarationType", "method": "derived", "rationale": "Each disaster carries one declaration type."},
        ],
        tests=[{"statistic": f"value[{peak['period']}]", "expected": peak["value"], "tolerance": 0}, {"statistic": f"column[designated_area_rows,{peak['period']}]", "expected": peak["designated_area_rows"], "tolerance": 0}],
        period=("1952-10-01", "2025-09-30"),
    )


def fema_recent_marginal(key: str, entry_id: str, title: str, variable: str, what: str, tags: list[str], use_cases: list[str]) -> dict:
    raw = RESOURCES[FEMA_RECENT_URL]
    rows = csv_rows(raw)
    counts = dict(sorted(distinct_disasters(rows, key).items(), key=lambda kv: (-kv[1], kv[0])))
    largest = next(iter(counts))
    sample = next(r for r in rows if r[key] == largest)
    items = [
        evidence(FEMA, "OpenFEMA Disaster Declarations Summaries v2, fyDeclared 2024 to 2026 (CSV)", FEMA_RECENT_URL, f"row femaDeclarationString={sample['femaDeclarationString']}", sample["disasterNumber"], "text", fema_row_snippet(sample), UNSTATED, raw),
        evidence(FEMA, "OpenFEMA Disaster Declarations Summaries v2, fyDeclared 2024 to 2026 (CSV)", FEMA_RECENT_URL, "header row", key, "text", FEMA_DECLARATION_FIELDS, UNSTATED, raw),
    ]
    years = sorted({r["fyDeclared"] for r in rows})
    return marginal_entry(
        entry_id=entry_id,
        title=title,
        domain="insurance",
        variable=variable,
        counts=counts,
        period=("2023-10-01", "2026-09-30"),
        evidence_items=items,
        notes=(
            f"Distinct disasters declared in fiscal years {years[0]} to {years[-1]} by {what}, counted from the "
            "OpenFEMA Disaster Declarations Summaries filtered to fiscal years 2024 to 2026 (one row per designated area, "
            f"disasters counted once). A disaster spanning several {what} values is counted under each. " + FEMA_NOTE
        ),
        tags=FEMA_TAGS + tags,
        use_cases=use_cases,
        status=REVIEW,
        count_key="disasters",
        share_rationale="Shares are distinct disaster counts divided by their sum over the listed categories.",
    )


def fema_ihp_amounts() -> dict:
    raw = RESOURCES[FEMA_WEB_URL]
    declared = {}
    for r in csv_rows(RESOURCES[FEMA_DECLARATIONS_URL]):
        declared.setdefault(r["disasterNumber"], r["fyDeclared"])
    rows = [r for r in csv_rows(raw) if r["totalAmountIhpApproved"] and float(r["totalAmountIhpApproved"]) > 0 and declared.get(r["disasterNumber"], "0") >= "2015" and declared[r["disasterNumber"]] <= "2025"]
    rows.sort(key=lambda r: int(r["disasterNumber"]))
    values = [round(float(r["totalAmountIhpApproved"]), 2) for r in rows]
    registrants = [int(float(r["totalNumberIaApproved"])) if r["totalNumberIaApproved"] else None for r in rows]
    top = max(rows, key=lambda r: float(r["totalAmountIhpApproved"]))
    ordered = sorted(values)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    p90 = ordered[int(round(0.9 * (len(ordered) - 1)))]
    items = [
        evidence(FEMA, "OpenFEMA FEMA Web Disaster Summaries v1, totalAmountIhpApproved > 0 (CSV)", FEMA_WEB_URL, f"row disasterNumber={top['disasterNumber']}, totalAmountIhpApproved", top["totalAmountIhpApproved"], "currency:USD", f"{top['disasterNumber']},{top['totalNumberIaApproved']},{top['totalAmountIhpApproved']}", UNSTATED, raw),
        evidence(FEMA, "OpenFEMA FEMA Web Disaster Summaries v1, totalAmountIhpApproved > 0 (CSV)", FEMA_WEB_URL, "header row", "totalAmountIhpApproved", "text", FEMA_WEB_FIELDS, UNSTATED, raw),
        evidence(FEMA, "OpenFEMA Disaster Declarations Summaries v2, fyDeclared <= 2025 (CSV)", FEMA_DECLARATIONS_URL, "header row", "fyDeclared", "text", FEMA_DECLARATION_FIELDS, UNSTATED, RESOURCES[FEMA_DECLARATIONS_URL], role="supporting"),
    ]
    return {
        "id": "us-fema-individuals-and-households-program-amount-per-disaster-fy2015-fy2025",
        "title": f"FEMA Individuals and Households Program amount approved per disaster, FY2015 to FY2025 ({len(values)} disasters)",
        "kind": "marginal",
        "domain": "insurance",
        "region": "US",
        "status": REVIEW,
        "tier": "A",
        "observed_period": {"start": "2014-10-01", "end": "2025-09-30"},
        "tags": FEMA_TAGS + ["claim-severity", "empirical", "value-pool"],
        "use_cases": FEMA_USE_CASES + ["insurance"],
        "spec": {
            "variable": "ihp_amount_approved_usd",
            "unit": "currency:USD",
            "distribution": {"family": "empirical", "parameters": {"values": values, "disaster_numbers": [r["disasterNumber"] for r in rows], "individual_assistance_approvals": registrants}},
        },
        "evidence": items,
        "assumed": [
            {"parameter": "values", "value": "totalAmountIhpApproved for disasters declared FY2015-FY2025 with a positive amount", "method": "derived", "rationale": "Disasters are selected by joining the summaries to the declarations file on disasterNumber for the fiscal year; disasters without Individual Assistance have no amount and are left out."},
        ],
        "tests": [
            {"statistic": "max", "expected": max(values), "tolerance": 0},
            {"statistic": "median", "expected": median, "tolerance": round(0.08 * median, 2)},
            {"statistic": "quantile[0.9]", "expected": p90, "tolerance": round(0.1 * p90, 2)},
        ],
        "notes": (
            "Total dollars approved under FEMA's Individuals and Households Program for each disaster declared in "
            "fiscal years 2015 to 2025 that has a positive amount in the FEMA Web Disaster Summaries dataset: an "
            "empirical distribution of claim-programme severity per event, with the disaster numbers and the number "
            "of approved Individual Assistance registrants in parallel lists. Amounts are cumulative to the file date "
            "and continue to grow for recent events. The median and 90th-percentile tests allow for sampling noise "
            "around the published values. " + FEMA_NOTE
        ),
    }


def build_fema() -> None:
    for url in (FEMA_DECLARATIONS_URL, FEMA_RECENT_URL):
        get(url)
    finish(fema_declarations_by_year())
    finish(fema_recent_marginal("incidentType", "us-fema-disaster-declarations-by-incident-type-fy2024-fy2026", "FEMA disaster declarations by incident type, FY2024 to FY2026", "incident_type", "incident type", ["by-incident-type"], FEMA_USE_CASES))
    finish(fema_recent_marginal("state", "us-fema-disaster-declarations-by-state-fy2024-fy2026", "FEMA disaster declarations by state or territory, FY2024 to FY2026", "state", "state or territory", ["by-state"], FEMA_USE_CASES + ["address-generation"]))


def build_fema_ihp() -> None:
    for url in (FEMA_DECLARATIONS_URL, FEMA_WEB_URL):
        get(url)
    finish(fema_ihp_amounts())


# ----------------------------------------------------------------------------------------------
# HMDA data browser
# ----------------------------------------------------------------------------------------------

HMDA = "Federal Financial Institutions Examination Council (HMDA data browser, CFPB)"
HMDA_API = "https://ffiec.cfpb.gov/v2/data-browser-api/view/nationwide/aggregations"
HMDA_FIG_URL = "https://ffiec.cfpb.gov/documentation/fig/2024/overview"
HMDA_YEAR = "2024"
# API parameter -> (variable, codes, field name, the FIG instruction sentence that introduces the field's code list)
HMDA_FIELDS = {
    "actions_taken": ("action_taken", ["1", "2", "3", "4", "5", "6", "7", "8"], "Action Taken", "Indicate the action taken on the covered loan or application"),
    "loan_purposes": ("loan_purpose", ["1", "2", "31", "32", "4", "5"], "Loan Purpose", "Indicate the purpose of the covered loan or application"),
    "loan_types": ("loan_type", ["1", "2", "3", "4"], "Loan Type", "Indicate the type of covered loan or application"),
}
HMDA_TAGS = ["lending", "mortgage", "hmda", "loan-sizes"]
HMDA_USE_CASES = ["lending-demo", "mortgage-origination", "loan-pricing", "credit-risk"]


def hmda_url(parameter: str, code: str) -> str:
    return f"{HMDA_API}?years={HMDA_YEAR}&{parameter}={code}"


def hmda_labels(parameter: str, codes: list[str], instruction: str) -> dict[str, str]:
    """Code descriptions from the Filing Instructions Guide: the 'Code N—…' paragraphs that follow the field's instruction."""
    text = text_of(HMDA_FIG_URL)
    start = text.find(f"<p>{instruction}")
    if start < 0:
        raise ValueError(f"FIG instruction for {parameter} not found")
    block = re.match(r"<p>[^<]+</p>((?:<p>Code [0-9]+—[^<]+</p>)+)", text[start:])
    if block is None:
        raise ValueError(f"FIG code list for {parameter} not found")
    found = dict(re.findall(r"<p>Code ([0-9]+)—([^<]+)</p>", block.group(1)))
    if list(found) != codes:
        raise ValueError(f"FIG codes for {parameter} are {list(found)}, expected {codes}")
    return {code: found[code].strip() for code in codes}


def hmda_marginal(parameter: str) -> dict:
    variable, codes, field_name, instruction = HMDA_FIELDS[parameter]
    labels = hmda_labels(parameter, codes, instruction)
    counts, sums, items = {}, {}, []
    for code in codes:
        url = hmda_url(parameter, code)
        (bucket,) = json.loads(RESOURCES[url])["aggregations"]
        if bucket[parameter] != code:
            raise ValueError(f"unexpected bucket {bucket}")
        key = f"{code} {labels[code]}"
        counts[key], sums[key] = bucket["count"], bucket["sum"]
        # The sum is cited as the API writes it (scientific notation), so the snippet is lifted from the raw text.
        snippet = re.search(rf'\{{"count":{bucket["count"]},"sum":[^,]+,"{parameter}":"{code}"\}}', RESOURCES[url].decode()).group(0)
        items.append(evidence(HMDA, f"HMDA data browser API, nationwide aggregation, {HMDA_YEAR}, {parameter}={code}", url, "aggregations[0].count", bucket["count"], "count", snippet, UNSTATED, RESOURCES[url]))
    sample_code = codes[0]
    items.append(evidence(HMDA, "HMDA Filing Instructions Guide for data collected in 2024", HMDA_FIG_URL, f"Data specifications, {field_name}, code list", labels[sample_code], "text", f"Code {sample_code}—{labels[sample_code]}", UNSTATED, RESOURCES[HMDA_FIG_URL], role="supporting"))
    means = {k: round(sums[k] / counts[k], 2) for k in counts}
    what = field_name.lower()
    return marginal_entry(
        entry_id=f"us-hmda-loan-applications-by-{variable.replace('_', '-')}-{HMDA_YEAR}",
        title=f"HMDA {HMDA_YEAR} loan and application records by {what}, with loan-amount sums and means",
        domain="consumer-credit",
        variable=variable,
        counts=counts,
        period=(f"{HMDA_YEAR}-01-01", f"{HMDA_YEAR}-12-31"),
        evidence_items=items,
        notes=(
            f"Loan/application register records reported under HMDA for {HMDA_YEAR}, nationwide, by {what}: one data "
            f"browser aggregation query per code, giving the record count and the sum of the loan amount field in "
            f"dollars. Category labels are '<code> <description>' with descriptions from the {HMDA_YEAR} Filing "
            "Instructions Guide. mean_loan_amount_usd is the sum divided by the count. " + FEDERAL_NOTE
        ),
        tags=HMDA_TAGS + [f"by-{variable.replace('_', '-')}"],
        use_cases=HMDA_USE_CASES,
        status=REVIEW,
        extra_parameters={"loan_amount_sum_usd": sums, "mean_loan_amount_usd": means, "labels": labels},
        assumed=[{"parameter": "mean_loan_amount_usd", "value": "loan_amount_sum_usd / counts", "method": "derived", "rationale": "The API returns count and sum; the mean is their quotient."}],
    )


def build_hmda() -> None:
    get(HMDA_FIG_URL)
    for parameter, (_, codes, _, _) in HMDA_FIELDS.items():
        for code in codes:
            get(hmda_url(parameter, code))
        finish(hmda_marginal(parameter))


# ----------------------------------------------------------------------------------------------
# FHFA House Price Index
# ----------------------------------------------------------------------------------------------

FHFA = "Federal Housing Finance Agency"
FHFA_STATE_URL = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_po_state.csv"
FHFA_MONTHLY_URL = "https://www.fhfa.gov/hpi/download/monthly/hpi_po_monthly_hist.xls"
FHFA_TAGS = ["property", "house-prices", "fhfa", "hpi", "index"]
FHFA_USE_CASES = ["property-demo", "mortgage-origination", "contract-indexation", "insurance-demo"]
FHFA_FROM_YEAR = 2015


def sheet_rows(url: str, sheet: str | None = None) -> list[tuple]:
    workbook = load_workbook(io.BytesIO(RESOURCES[url]), read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook[workbook.sheetnames[0]]
    return [tuple(r) for r in worksheet.iter_rows(values_only=True)]


def fhfa_state_quarterly() -> dict:
    rows = sheet_rows(FHFA_STATE_URL)
    header = rows[0]
    if header[:5] != ("state", "yr", "qtr", "index_nsa", "index_sa"):
        raise ValueError(f"unexpected FHFA state header {header}")
    by_period: dict[str, dict[str, float]] = defaultdict(dict)
    for state, yr, qtr, nsa, sa, *_ in rows[1:]:
        if state and yr and int(yr) >= FHFA_FROM_YEAR:
            by_period[f"{int(yr)}-Q{int(qtr)}"][f"{state.lower()}_sa"] = sa
            by_period[f"{int(yr)}-Q{int(qtr)}"][f"{state.lower()}_nsa"] = nsa
    states = sorted({r[0].lower() for r in rows[1:] if r[0]})
    columns = [f"{s}_sa" for s in states] + [f"{s}_nsa" for s in states]
    series = []
    for period in sorted(by_period):
        values = by_period[period]
        if set(values) != set(columns):
            raise ValueError(f"incomplete quarter {period}")
        series.append({"period": period, "value": round(sum(values[f"{s}_sa"] for s in states) / len(states), 2), **values})
    last = series[-1]
    sample_state = "ca"
    items = [
        cell_evidence(FHFA, "FHFA purchase-only HPI by state, quarterly (hpi_po_state)", FHFA_STATE_URL, f"row state={sample_state.upper()}, yr={last['period'][:4]}, qtr={last['period'][-1]}, index_sa", last[f"{sample_state}_sa"], "decimal"),
        cell_evidence(FHFA, "FHFA purchase-only HPI by state, quarterly (hpi_po_state)", FHFA_STATE_URL, f"row state={sample_state.upper()}, yr={series[0]['period'][:4]}, qtr={series[0]['period'][-1]}, index_nsa", series[0][f"{sample_state}_nsa"], "decimal"),
        evidence(FHFA, "FHFA purchase-only HPI by state, quarterly (hpi_po_state)", FHFA_STATE_URL, "header row", "index_sa", "text", "<t>index_sa</t>", UNSTATED, RESOURCES[FHFA_STATE_URL], role="supporting"),
    ]
    start, end = quarter_bounds(series[0]["period"])[0], quarter_bounds(last["period"])[1]
    return temporal_entry(
        entry_id=f"us-fhfa-purchase-only-house-price-index-by-state-quarterly-{series[0]['period'].lower().replace('-', '')}-{last['period'].lower().replace('-', '')}",
        title=f"FHFA purchase-only House Price Index by state, quarterly, {series[0]['period']} to {last['period']} (1991Q1 = 100)",
        domain="property",
        variable="mean_of_state_indexes_sa",
        unit="decimal",
        frequency="quarterly",
        series=series,
        columns=columns,
        evidence_items=items,
        notes=(
            "Seasonally adjusted (_sa) and not seasonally adjusted (_nsa) purchase-only house price index, columns named by lower-case state postal code, for each of "
            f"the {len(states)} states and the District of Columbia, 1991Q1 = 100, from the FHFA quarterly state file "
            f"(served as a workbook despite its .csv name), from {series[0]['period']} onward. The headline value is "
            "the unweighted mean of the state SA indexes, a convenience for plotting rather than an FHFA statistic; "
            "the state columns are the published figures. Some small states carry FHFA's note that they have fewer "
            "than 15,000 transactions over the latest ten years. " + FEDERAL_NOTE
        ),
        tags=FHFA_TAGS + ["by-state", "quarterly-series"],
        use_cases=FHFA_USE_CASES,
        status=REVIEW,
        assumed=[{"parameter": "value", "value": "mean of the state index_sa values", "method": "derived", "rationale": "A temporal entry needs one headline value; the unweighted state mean is used and documented, the per-state columns are as published."}],
        tests=[{"statistic": f"column[{sample_state}_sa,{last['period']}]", "expected": last[f"{sample_state}_sa"], "tolerance": 0}, {"statistic": f"column[tx_nsa,{series[0]['period']}]", "expected": series[0]["tx_nsa"], "tolerance": 0}],
        period=(start, end),
    )


def fhfa_monthly() -> dict:
    rows = sheet_rows(FHFA_MONTHLY_URL)
    header_index = next(i for i, r in enumerate(rows) if r[0] == "Month")
    header = [" ".join(str(c).split()) if c else "" for c in rows[header_index]]
    names = {}
    for i, h in enumerate(header[1:], 1):
        match = re.fullmatch(r"(.+?) \((NSA|SA)\)", h)
        if match:
            names[i] = f"{slug(match.group(1))}_{match.group(2).lower()}"
    value_column = next(i for i, n in names.items() if n == "usa_sa")
    columns = [n for i, n in names.items() if i != value_column]
    series = []
    for r in rows[header_index + 1:]:
        if isinstance(r[0], datetime) and r[0].year >= FHFA_FROM_YEAR:
            series.append({"period": r[0].strftime("%Y-%m"), "value": r[value_column], **{n: r[i] for i, n in names.items() if i != value_column}})
    last, first = series[-1], series[0]
    items = [
        cell_evidence(FHFA, "FHFA monthly purchase-only HPI for census divisions and U.S. (hpi_po_monthly_hist)", FHFA_MONTHLY_URL, f"row Month={last['period']}, USA (SA)", last["value"], "decimal"),
        cell_evidence(FHFA, "FHFA monthly purchase-only HPI for census divisions and U.S. (hpi_po_monthly_hist)", FHFA_MONTHLY_URL, f"row Month={first['period']}, Pacific (NSA)", first["pacific_nsa"], "decimal"),
        evidence(FHFA, "FHFA monthly purchase-only HPI for census divisions and U.S. (hpi_po_monthly_hist)", FHFA_MONTHLY_URL, "title cell", "Purchase-Only Index", "text", "Purchase-Only Index (Only Index available with Monthly Frequency)", UNSTATED, RESOURCES[FHFA_MONTHLY_URL], role="supporting"),
    ]
    end_year, end_month = int(last["period"][:4]), int(last["period"][5:])
    return temporal_entry(
        entry_id=f"us-fhfa-purchase-only-house-price-index-monthly-{first['period'].replace('-', '')}-{last['period'].replace('-', '')}",
        title=f"FHFA purchase-only House Price Index, US and nine census divisions, monthly, {first['period']} to {last['period']} (Jan 1991 = 100)",
        domain="property",
        variable="usa_sa",
        unit="decimal",
        frequency="monthly",
        series=series,
        columns=columns,
        evidence_items=items,
        notes=(
            "Monthly purchase-only house price index for the United States (headline value, seasonally adjusted) and "
            "for the nine census divisions, seasonally adjusted (_sa) and not (_nsa), January 1991 = 100, from "
            f"{first['period']} onward as published in FHFA's monthly history workbook (served as .xlsx despite its "
            ".xls name). " + FEDERAL_NOTE
        ),
        tags=FHFA_TAGS + ["monthly-series", "census-divisions"],
        use_cases=FHFA_USE_CASES,
        status=REVIEW,
        tests=[{"statistic": f"column[pacific_nsa,{first['period']}]", "expected": first["pacific_nsa"], "tolerance": 0}, {"statistic": f"column[usa_nsa,{last['period']}]", "expected": last["usa_nsa"], "tolerance": 0}],
        period=(f"{first['period']}-01", f"{end_year}-{end_month:02d}-{calendar.monthrange(end_year, end_month)[1]:02d}"),
    )


def build_fhfa() -> None:
    get(FHFA_STATE_URL)
    get(FHFA_MONTHLY_URL)
    finish(fhfa_state_quarterly())
    finish(fhfa_monthly())


# ----------------------------------------------------------------------------------------------
# Federal Reserve Bank of New York, Household Debt and Credit Report
# ----------------------------------------------------------------------------------------------

NYFED = "Federal Reserve Bank of New York"
NYFED_QUARTER = "2026Q2"
NYFED_URL = f"https://www.newyorkfed.org/medialibrary/interactives/householdcredit/data/xls/HHD_C_Report_{NYFED_QUARTER}.xlsx"
NYFED_TAGS = ["consumer-credit", "household-debt", "new-york-fed", "consumer-credit-panel"]
NYFED_USE_CASES = ["lending-demo", "credit-risk", "collections", "banking-demo", "personal-finance"]
NYFED_NOTE = (
    "Source: the Quarterly Report on Household Debt and Credit data workbook, built from the New York Fed Consumer "
    "Credit Panel / Equifax, a nationally representative 5 percent sample of credit-report data. " + FEDERAL_NOTE
)


def nyfed_table(sheet: str) -> tuple[list[str], list[tuple[str, tuple]]]:
    """Header labels and (period, values) rows of one 'Page N Data' sheet, periods normalised to YYYY-Qn."""
    rows = sheet_rows(NYFED_URL, sheet)
    header_index = next(i for i, r in enumerate(rows) if r and r[0] in (None, "quarter") and sum(1 for c in r[1:] if isinstance(c, str)) >= 2)
    header = [" ".join(str(c).split()) for c in rows[header_index][1:] if c is not None and str(c).strip()]
    data = []
    for r in rows[header_index + 1:]:
        if r[0] is None or (isinstance(r[0], str) and not re.fullmatch(r"\d{2}:Q[1-4]", r[0].strip())) and not isinstance(r[0], datetime):
            continue
        data.append((period_quarter(r[0]), tuple(r[1 : 1 + len(header)])))
    return header, data


def nyfed_cell_evidence(sheet: str, locator: str, value: Any) -> dict:
    return cell_evidence(NYFED, f"Household Debt and Credit Report {NYFED_QUARTER} data workbook, sheet '{sheet}'", NYFED_URL, locator, value, "decimal")


def nyfed_label_evidence(sheet: str, label: str) -> dict:
    return evidence(NYFED, f"Household Debt and Credit Report {NYFED_QUARTER} data workbook, sheet '{sheet}'", NYFED_URL, "sheet title cell", label.strip(), "text", label.strip(), UNSTATED, RESOURCES[NYFED_URL], role="supporting")


def nyfed_temporal(sheet: str, entry_id: str, title: str, variable: str, unit: str, headline: Callable[[dict[str, float]], float] | str, column_names: dict[str, str], notes: str, tags: list[str], use_cases: list[str], assumed: list[dict] | None = None, title_label: str | None = None) -> dict:
    header, data = nyfed_table(sheet)
    index = {h: i for i, h in enumerate(header)}
    missing = [h for h in column_names if h not in index]
    if missing:
        raise ValueError(f"{sheet}: columns {missing} not in header {header}")
    series = []
    for period, values in data:
        point = {column_names[h]: (round(values[index[h]], 6) if isinstance(values[index[h]], (int, float)) else None) for h in column_names}
        value = point[headline] if isinstance(headline, str) else headline(point)
        series.append({"period": period, "value": value, **{k: v for k, v in point.items() if k != headline}})
    columns = [v for v in column_names.values() if v != headline]
    last = series[-1]
    last_raw = data[-1][1]
    evidence_columns = [h for h in column_names if isinstance(last_raw[index[h]], (int, float))][:2]
    items = [nyfed_cell_evidence(sheet, f"row {data[-1][0]} ({sheet.replace(' Data', '')}), column {h}", last_raw[index[h]]) for h in evidence_columns]
    items.append(nyfed_label_evidence(sheet, title_label or header[0]))
    start, end = quarter_bounds(series[0]["period"])[0], quarter_bounds(last["period"])[1]
    tests = [{"statistic": f"column[{column_names[h]},{last['period']}]", "expected": series[-1][column_names[h]], "tolerance": 0} for h in evidence_columns if column_names[h] != headline]
    return temporal_entry(
        entry_id=entry_id,
        title=title,
        domain="consumer-credit",
        variable=variable,
        unit=unit,
        frequency="quarterly",
        series=series,
        columns=columns,
        evidence_items=items,
        notes=notes + " " + NYFED_NOTE,
        tags=NYFED_TAGS + tags,
        use_cases=use_cases,
        status=REVIEW,
        assumed=assumed,
        tests=tests,
        period=(start, end),
    )


def nyfed_balances() -> dict:
    names = {"Mortgage": "mortgage", "HE Revolving": "home_equity_revolving", "Auto Loan": "auto_loan", "Credit Card": "credit_card", "Student Loan": "student_loan", "Other": "other", "Total": "total"}
    return nyfed_temporal(
        "Page 3 Data",
        "us-nyfed-household-debt-balance-by-type-quarterly-2003q1-2026q2",
        "Household debt balance by loan type, trillions of US dollars, quarterly, 2003Q1 to 2026Q2 (New York Fed)",
        "total_household_debt_usd_trillions",
        "currency:USD",
        "total",
        names,
        "Outstanding household debt in trillions of US dollars at the end of each quarter, split into mortgage, home equity revolving, auto loan, credit card, student loan and other balances (the report's 'Total Debt Balance and Its Composition' page). The headline value is the workbook's Total column, a SUM formula over the six components read as its cached result; a few component cells are themselves stored as formulas and are read the same way.",
        ["balances", "quarterly-series", "by-loan-type"],
        NYFED_USE_CASES + ["market-sizing"],
        title_label="Total Debt Balance and Its Composition",
    )


def nyfed_delinquency_status() -> dict:
    names = {"Current": "current", "30 days late": "late_30_days", "60 days late": "late_60_days", "90 days late": "late_90_days", "120+ days late": "late_120_plus_days", "Severely Derogatory": "severely_derogatory"}
    return nyfed_temporal(
        "Page 11 Data",
        "us-nyfed-household-debt-balance-by-delinquency-status-quarterly-2003q1-2026q2",
        "Share of household debt balance by delinquency status, percent, quarterly, 2003Q1 to 2026Q2 (New York Fed)",
        "current_percent",
        "percent",
        "current",
        names,
        "Percent of total household debt balance that is current, 30, 60, 90 or 120+ days late, or severely derogatory at the end of each quarter (the report's 'Total Balance by Delinquency Status' page). The headline value is the current share; the other statuses are columns and the six sum to 100.",
        ["delinquency", "quarterly-series", "credit-risk"],
        NYFED_USE_CASES,
        title_label="Total Balance by Delinquency Status",
    )


def nyfed_serious_delinquency_by_type() -> dict:
    names = {"MORTGAGE": "mortgage", "HELOC": "home_equity_line", "AUTO": "auto_loan", "CC": "credit_card", "STUDENT LOAN": "student_loan", "OTHER": "other", "ALL": "all_loans"}
    return nyfed_temporal(
        "Page 12 Data",
        "us-nyfed-household-debt-90-plus-days-delinquent-by-loan-type-quarterly-2003q1-2026q2",
        "Percent of household debt balance 90+ days delinquent by loan type, quarterly, 2003Q1 to 2026Q2 (New York Fed)",
        "all_loans_percent",
        "percent",
        "all_loans",
        names,
        "Percent of outstanding balance that is 90 or more days delinquent, for all loans (headline value) and for mortgage, home equity line of credit, auto loan, credit card, student loan and other balances (the report's 'Percent of Balance 90+ Days Delinquent by Loan Type' page). Student loan delinquency reflects the reporting pauses and resumptions of recent years.",
        ["delinquency", "quarterly-series", "by-loan-type", "credit-risk"],
        NYFED_USE_CASES,
        title_label="Percent of Balance 90+ Days Delinquent by Loan Type ",
    )


def nyfed_serious_delinquency_by_age() -> dict:
    names = {"18-29": "age_18_29", "30-39": "age_30_39", "40-49": "age_40_49", "50-59": "age_50_59", "60-69": "age_60_69", "70+": "age_70_plus", "all": "all_ages"}
    header, _ = nyfed_table("Page 24 Data")
    all_label = next(h for h in header if h.lower() in ("all", "total", "all ages"))
    names = {**{k: v for k, v in names.items() if k != "all"}, all_label: "all_ages"}
    return nyfed_temporal(
        "Page 24 Data",
        "us-nyfed-transition-into-serious-delinquency-by-age-quarterly-2000q3-2026q2",
        "Percent of household debt balance transitioning into 90+ days delinquency by borrower age, quarterly (New York Fed)",
        "all_ages_percent",
        "percent",
        "all_ages",
        names,
        "Four-quarter flow into serious (90+ days) delinquency as a percent of balance, by age group of the borrower and for all ages (headline value), from the report's 'Transition into Serious Delinquency (90+) by Age' page.",
        ["delinquency", "quarterly-series", "by-age", "credit-risk"],
        NYFED_USE_CASES + ["customer-segmentation"],
        title_label="Transition into Serious Delinquency (90+) by Age",
    )


def nyfed_credit_scores() -> dict:
    """Median, 25th and 10th percentile credit scores of mortgage and auto loan originations, from two pages."""
    mortgage_header, mortgage = nyfed_table("Page 7 Data")
    auto_header, auto = nyfed_table("Page 9 Data")
    for header in (mortgage_header, auto_header):
        if header[:3] != ["Median", "25th percentile", "10th percentile"]:
            raise ValueError(f"unexpected credit score header {header}")
    auto_by_period = {p: v for p, v in auto}
    series = []
    for period, m in mortgage:
        if period in auto_by_period and all(isinstance(x, (int, float)) for x in m[:3]):
            a = auto_by_period[period]
            series.append({"period": period, "value": m[0], "mortgage_p25": m[1], "mortgage_p10": m[2], "auto_median": a[0], "auto_p25": a[1], "auto_p10": a[2]})
    last = series[-1]
    items = [
        nyfed_cell_evidence("Page 7 Data", f"row {last['period']} (Page 7), Median", last["value"]),
        nyfed_cell_evidence("Page 9 Data", f"row {last['period']} (Page 9), 10th percentile", last["auto_p10"]),
        nyfed_label_evidence("Page 7 Data", "Distribution of Riskscore of Mortgage Originations"),
    ]
    start, end = quarter_bounds(series[0]["period"])[0], quarter_bounds(last["period"])[1]
    return temporal_entry(
        entry_id="us-nyfed-credit-score-of-mortgage-and-auto-originations-quarterly-1999q2-2026q2",
        title="Median, 25th and 10th percentile credit score of mortgage and auto loan originations, quarterly (New York Fed)",
        domain="consumer-credit",
        variable="mortgage_origination_median_score",
        unit="decimal",
        frequency="quarterly",
        series=series,
        columns=["mortgage_p25", "mortgage_p10", "auto_median", "auto_p25", "auto_p10"],
        evidence_items=items,
        notes=(
            "Credit score at origination for newly originated first-lien mortgages (headline value is the median; "
            "25th and 10th percentiles as columns) and for auto loans, from the report's 'Distribution of Riskscore' "
            "pages. The workbook notes the score is VantageScore 4.0 from 2026Q1 and Equifax Riskscore 3.0 before, "
            "so the series has a definitional break at 2026Q1. " + NYFED_NOTE
        ),
        tags=NYFED_TAGS + ["credit-score", "originations", "quarterly-series"],
        use_cases=NYFED_USE_CASES + ["person-generation"],
        status=REVIEW,
        tests=[{"statistic": f"column[auto_p10,{last['period']}]", "expected": last["auto_p10"], "tolerance": 0}],
        period=(start, end),
    )


def nyfed_product_mix_by_age() -> dict:
    rows = sheet_rows(NYFED_URL, "Page 21 Data")
    header_index = next(i for i, r in enumerate(rows) if r[0] is None and r[1] == "18-29")
    ages = [str(c) for c in rows[header_index][1:] if c]
    products: dict[str, list[float]] = {}
    for r in rows[header_index + 1:]:
        if isinstance(r[0], str) and r[0].strip() and all(isinstance(c, (int, float)) for c in r[1 : 1 + len(ages)]):
            products[r[0].strip()] = list(r[1 : 1 + len(ages)])
    if "Mortgage" not in products:
        raise ValueError(f"unexpected product rows {list(products)}")
    distributions = {}
    for j, age in enumerate(ages):
        balances = {slug(p): v[j] for p, v in products.items()}
        total = sum(balances.values())
        distributions["age_" + slug(age.replace("+", "_plus"))] = {"family": "categorical", "parameters": {"shares": {k: share_of(v, total) for k, v in balances.items()}, "balance_usd_trillions": balances, "total_usd_trillions": round(total, 4)}}
    sample_age = ages[2]
    items = [
        nyfed_cell_evidence("Page 21 Data", f"row Mortgage, column {sample_age}", products["Mortgage"][2]),
        nyfed_cell_evidence("Page 21 Data", f"row Credit Card, column {ages[0]}", products["Credit Card"][0]),
        nyfed_label_evidence("Page 21 Data", rows[0][0]),
    ]
    tests = []
    for key, dist in distributions.items():
        shares = dist["parameters"]["shares"]
        tests.append({"statistic": f"share[{key},mortgage]", "expected": shares["mortgage"], "tolerance": 0.003})
        tests.append({"statistic": f"sum_of_shares[{key}]", "expected": 1, "tolerance": 0.0001})
    start, end = quarter_bounds(f"{NYFED_QUARTER[:4]}-Q{NYFED_QUARTER[-1]}")
    return {
        "id": "us-nyfed-household-debt-product-mix-given-borrower-age-2026q2",
        "title": "Household debt balance mix by loan product given borrower age group, 2026Q2 (New York Fed)",
        "kind": "conditional",
        "domain": "consumer-credit",
        "region": "US",
        "status": REVIEW,
        "tier": "A",
        "observed_period": {"start": start, "end": end},
        "tags": NYFED_TAGS + ["by-age", "by-loan-type", "conditional"],
        "use_cases": NYFED_USE_CASES + ["customer-segmentation", "person-generation"],
        "spec": {"variable": "loan_product", "unit": "ratio", "given": "age_group", "distributions": distributions},
        "evidence": items,
        "assumed": [{"parameter": "shares", "value": "balance / total within age group", "method": "derived", "rationale": "The page publishes balances in trillions of dollars by product and age; shares divide each product by the age group's total."}],
        "tests": tests,
        "notes": (
            "Composition of outstanding household debt by loan product within each borrower age group at 2026Q2, from "
            "the report's 'Debt Share by Product Type and Age' page, which publishes balances in trillions of US "
            "dollars. Balances are kept beside the shares. Use it to assign a product mix to a synthetic borrower of "
            "a given age. " + NYFED_NOTE
        ),
    }


def nyfed_per_capita_by_state() -> dict:
    rows = sheet_rows(NYFED_URL, "Page 33 Data")
    header_index = next(i for i, r in enumerate(rows) if r[0] in (None, "state", "State") and isinstance(r[1], str) and r[1].strip())
    header = [" ".join(str(c).split()) for c in rows[header_index][1:] if c]
    table: dict[str, dict] = {}
    for r in rows[header_index + 1:]:
        if isinstance(r[0], str) and re.fullmatch(r"[A-Z]{2}", r[0].strip()) and isinstance(r[1], (int, float)):
            table[r[0].strip()] = {slug(h) + "_usd_thousands": r[1 + i] for i, h in enumerate(header)}
    if len(table) < 12 or "US" not in table:
        raise ValueError(f"unexpected Page 33 rows {list(table)}")
    first_column = next(iter(next(iter(table.values()))))
    top_state = max(table, key=lambda s: table[s][first_column])
    items = [
        nyfed_cell_evidence("Page 33 Data", f"row {top_state}, column {header[0]}", table[top_state][first_column]),
        nyfed_cell_evidence("Page 33 Data", f"row CA, column {header[-1]}", table["CA"][slug(header[-1]) + "_usd_thousands"]),
        nyfed_label_evidence("Page 33 Data", rows[0][0]),
    ]
    start, end = quarter_bounds(f"{NYFED_QUARTER[:4]}-Q{NYFED_QUARTER[-1]}")
    return lookup_entry(
        entry_id="us-nyfed-household-debt-per-capita-by-product-selected-states-2026q2",
        title=f"Household debt per capita by loan product, {len(table) - 1} selected states and the US, thousands of US dollars, 2026Q2 (New York Fed)",
        domain="consumer-credit",
        rows=table,
        parameters={"key": "state postal abbreviation, or US for the national figure", "money_unit": "thousands of US dollars per capita", "quarter": NYFED_QUARTER, "columns_in_source_order": [slug(h) + "_usd_thousands" for h in header]},
        vectors=[
            {"input": {"key": top_state, "column": first_column}, "expected": table[top_state][first_column], "origin": "source"},
            {"input": {"key": "CA", "column": slug(header[-1]) + "_usd_thousands"}, "expected": table["CA"][slug(header[-1]) + "_usd_thousands"], "origin": "source"},
            {"input": "CA", "expected": True, "origin": "source"},
            {"input": "ZZ", "expected": False, "origin": "derived"},
        ],
        valid=(start, end),
        evidence_items=items,
        notes=(
            "Debt balance per capita (per person with a credit report) at 2026Q2 for the eleven states the report "
            f"follows ({', '.join(k for k in table if k != 'US')}) and the US as a whole, split by loan product as the "
            "report's 'Composition of Debt Balance per Capita by State' page publishes it, in thousands of US dollars. "
            f"Columns in the page's order: {', '.join(header)}. " + NYFED_NOTE
        ),
        tags=NYFED_TAGS + ["by-state", "selected-states", "reference-table", "per-capita"],
        use_cases=NYFED_USE_CASES + ["address-generation", "customer-segmentation"],
        status=REVIEW,
        tests=[{"statistic": f"max[{first_column}]", "expected": table[top_state][first_column], "tolerance": 0}],
    )


def build_nyfed() -> None:
    get(NYFED_URL)
    finish(nyfed_balances())
    finish(nyfed_delinquency_status())
    finish(nyfed_serious_delinquency_by_type())
    finish(nyfed_serious_delinquency_by_age())
    finish(nyfed_credit_scores())
    finish(nyfed_product_mix_by_age())
    finish(nyfed_per_capita_by_state())


# ----------------------------------------------------------------------------------------------
# Federal Reserve Board, Survey of Consumer Finances 2025
# ----------------------------------------------------------------------------------------------

FRB = "Board of Governors of the Federal Reserve System"
SCF_URL = "https://www.federalreserve.gov/econres/files/scf2025_tables_public_nominal_historical.xlsx"
SCF_YEAR = 2025
SCF_TAGS = ["income", "wealth", "survey-of-consumer-finances", "households", "value-pool"]
SCF_USE_CASES = ["personal-finance", "household-generation", "customer-segmentation", "lending-demo", "financial-planning"]
SCF_NOTE = (
    "The Survey of Consumer Finances is a triennial household survey; figures are nominal thousands of US dollars "
    "for the 2025 survey (income refers to the previous calendar year). " + FEDERAL_NOTE
)


def scf_table(sheet: str, columns: dict[int, str]) -> tuple[dict[str, dict], int]:
    """Rows of an SCF summary sheet for the survey year, keyed 'group/characteristic', with the year's column offset."""
    rows = sheet_rows(SCF_URL, sheet)
    year_row = next(r for r in rows if r[0] == "Family characteristic")
    offset = next(i for i, c in enumerate(year_row) if c == SCF_YEAR)
    table: dict[str, dict] = {}
    group = "all"
    for r in rows[rows.index(year_row) + 1:]:
        label = r[0]
        if not isinstance(label, str) or not label.strip() or label.strip().startswith(("NOTE", "†", "*")):
            continue
        label = " ".join(label.replace("–", "-").split())
        values = {name: r[offset + i] for i, name in columns.items()}
        if all(v is None or v == "" for v in values.values()):
            group = slug(label)
            continue
        key = "all_families" if label == "All families" else f"{group}/{slug(label)}"
        table[key] = {"characteristic": label, **{k: (v if isinstance(v, (int, float)) else None) for k, v in values.items()}}
    return table, offset


def scf_entry(sheet: str, columns: dict[int, str], entry_id: str, title: str, what: str, tags: list[str], first_column: str) -> dict:
    table, _ = scf_table(sheet, columns)
    all_families = table["all_families"]
    by_age = [k for k in table if k.startswith("age_of_reference_person")]
    young = by_age[0]
    sheet_title = next(r[0] for r in sheet_rows(SCF_URL, sheet) if isinstance(r[0], str) and r[0].strip().startswith(("1.", "4.")))
    items = [
        cell_evidence(FRB, f"Survey of Consumer Finances 2025, historical tables workbook, sheet '{sheet}'", SCF_URL, f"row All families, {SCF_YEAR} {first_column}", all_families[first_column], "currency:USD"),
        cell_evidence(FRB, f"Survey of Consumer Finances 2025, historical tables workbook, sheet '{sheet}'", SCF_URL, f"row {table[young]['characteristic']}, {SCF_YEAR} mean", table[young]["mean_usd_thousands"], "currency:USD"),
        evidence(FRB, f"Survey of Consumer Finances 2025, historical tables workbook, sheet '{sheet}'", SCF_URL, "table title cell", "Thousands of dollars", "text", "Thousands of dollars", UNSTATED, RESOURCES[SCF_URL], role="supporting"),
    ]
    groups = sorted({k.split("/")[0] for k in table if "/" in k})
    return lookup_entry(
        entry_id=entry_id,
        title=title,
        domain="income",
        rows=table,
        parameters={"key": "group/characteristic", "survey_year": SCF_YEAR, "money_unit": "thousands of US dollars, nominal", "groups": groups, "source_table": " ".join(sheet_title.split())},
        vectors=[
            {"input": {"key": "all_families", "column": first_column}, "expected": all_families[first_column], "origin": "source"},
            {"input": {"key": young, "column": "mean_usd_thousands"}, "expected": table[young]["mean_usd_thousands"], "origin": "source"},
            {"input": "all_families", "expected": True, "origin": "source"},
            {"input": "age_of_reference_person_years/less_than_18", "expected": False, "origin": "derived"},
        ],
        valid=(f"{SCF_YEAR}-01-01", f"{SCF_YEAR}-12-31"),
        evidence_items=items,
        notes=(
            f"{what} for the 2025 survey by family characteristic, from the Federal Reserve's SCF historical tables "
            f"workbook ({' '.join(sheet_title.split())}). Rows are keyed 'group/characteristic' using the table's own "
            f"group headings ({', '.join(groups)}); 'all_families' is the overall row. " + SCF_NOTE
        ),
        tags=SCF_TAGS + tags,
        use_cases=SCF_USE_CASES,
        status=REVIEW,
        tests=[{"statistic": f"max[{first_column}]", "expected": max(v[first_column] for v in table.values() if v[first_column] is not None), "tolerance": 0}],
    )


def build_scf() -> None:
    get(SCF_URL)
    finish(scf_entry("Table 1 01-25", {0: "median_usd_thousands", 1: "mean_usd_thousands", 2: "percent_of_families_that_saved", 3: "percent_of_families"}, "us-scf-2025-before-tax-family-income-by-family-characteristic", "Survey of Consumer Finances 2025: median and mean before-tax family income, share that saved and share of families, by characteristic", "Median and mean before-tax family income, the percentage of families that saved and the percentage of families in each group", ["family-income", "by-income-percentile", "by-age"], "median_usd_thousands"))
    finish(scf_entry("Table 4", {0: "median_usd_thousands", 1: "mean_usd_thousands"}, "us-scf-2025-family-net-worth-by-family-characteristic", "Survey of Consumer Finances 2025: median and mean family net worth by family characteristic", "Median and mean family net worth", ["net-worth", "by-income-percentile", "by-age"], "median_usd_thousands"))


# ----------------------------------------------------------------------------------------------
# US Treasury daily par yield curve
# ----------------------------------------------------------------------------------------------

TREASURY = "US Department of the Treasury"
TREASURY_YEAR = "2025"
TREASURY_URL = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{TREASURY_YEAR}/all?type=daily_treasury_yield_curve&field_tdr_date_value={TREASURY_YEAR}&page&_format=csv"
TREASURY_COLUMNS = {"1 Mo": "m1", "2 Mo": "m2", "3 Mo": "m3", "4 Mo": "m4", "6 Mo": "m6", "1 Yr": "y1", "2 Yr": "y2", "3 Yr": "y3", "5 Yr": "y5", "7 Yr": "y7", "10 Yr": "y10", "20 Yr": "y20", "30 Yr": "y30"}


def treasury_yield_curve() -> dict:
    raw = RESOURCES[TREASURY_URL]
    rows = csv_rows(raw)
    missing = [c for c in TREASURY_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError(f"missing Treasury columns {missing}")
    series = []
    for r in sorted(rows, key=lambda r: datetime.strptime(r["Date"], "%m/%d/%Y")):
        point = {"period": datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()}
        for source, name in TREASURY_COLUMNS.items():
            if r[source] in ("", "N/A"):
                raise ValueError(f"blank {source} rate on {r['Date']}")
            point[name] = float(r[source])
        point["value"] = point.pop("y10")
        series.append(point)
    columns = [n for n in TREASURY_COLUMNS.values() if n != "y10"]
    last_row = max(rows, key=lambda r: datetime.strptime(r["Date"], "%m/%d/%Y"))
    first_row = min(rows, key=lambda r: datetime.strptime(r["Date"], "%m/%d/%Y"))
    line = lambda r: ",".join(r[c] for c in rows[0].keys())  # noqa: E731
    items = [
        evidence(TREASURY, f"Daily Treasury Par Yield Curve Rates {TREASURY_YEAR} (CSV)", TREASURY_URL, f"row Date={last_row['Date']}, 10 Yr", last_row["10 Yr"], "percent", line(last_row), UNSTATED, raw),
        evidence(TREASURY, f"Daily Treasury Par Yield Curve Rates {TREASURY_YEAR} (CSV)", TREASURY_URL, f"row Date={first_row['Date']}, 30 Yr", first_row["30 Yr"], "percent", line(first_row), UNSTATED, raw),
        evidence(TREASURY, f"Daily Treasury Par Yield Curve Rates {TREASURY_YEAR} (CSV)", TREASURY_URL, "header row", "10 Yr", "text", '"6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"', UNSTATED, raw, role="supporting"),
    ]
    peak = max(series, key=lambda p: p["value"])
    low = min(series, key=lambda p: p["value"])
    return temporal_entry(
        entry_id=f"us-treasury-par-yield-curve-daily-{TREASURY_YEAR}",
        title=f"US Treasury daily par yield curve rates, 1 month to 30 years, every trading day of {TREASURY_YEAR}",
        domain="rates",
        variable="y10",
        unit="percent",
        frequency="daily",
        series=series,
        columns=columns,
        evidence_items=items,
        notes=(
            f"Par yield curve rates in percent for every business day of {TREASURY_YEAR} from the Treasury's "
            "interest-rate resource centre CSV export: the 10-year rate is the headline value and the other tenors "
            "(1, 2, 3, 4, 6 months; 1, 2, 3, 5, 7, 20 and 30 years) are columns. The file's 1.5-month column is "
            f"published for only part of the year and is left out. The 10-year high was "
            f"{peak['value']} on {peak['period']} and the low {low['value']} on {low['period']}. " + FEDERAL_NOTE
        ),
        tags=["rates", "treasury", "yield-curve", "daily-series", "interest-rates"],
        use_cases=["capital-markets-demo", "treasury", "loan-pricing", "financial-planning"],
        status=REVIEW,
        tests=[{"statistic": "max", "expected": peak["value"], "tolerance": 0}, {"statistic": f"column[y30,{series[0]['period']}]", "expected": series[0]["y30"], "tolerance": 0}],
        period=(series[0]["period"], series[-1]["period"]),
    )


def build_treasury() -> None:
    get(TREASURY_URL)
    finish(treasury_yield_curve())


# ----------------------------------------------------------------------------------------------
# Federal Reserve Payments Study
# ----------------------------------------------------------------------------------------------

FRPS_URL = "https://www.federalreserve.gov/publications/images/FRPS_CY2024_IDR_data.xlsx"
# Row keys of Table 1 in sheet order; the builder checks each label against the sheet before using it.
FRPS_ROWS = [
    ("total", "Total"),
    ("cards", "Cards"),
    ("cards/debit", "Debit cards"),
    ("cards/debit/non_prepaid", "Non-prepaid"),
    ("cards/debit/prepaid", "Prepaid"),
    ("cards/debit/prepaid/general_purpose", "General purpose"),
    ("cards/debit/prepaid/private_label", "Private label"),
    ("cards/debit/prepaid/ebt", "Electronic benefits transfer (EBT)"),
    ("cards/credit", "Credit cards"),
    ("cards/credit/general_purpose", "General purpose"),
    ("cards/credit/private_label", "Private label"),
    ("ach", "Automated clearinghouse (ACH)"),
    ("ach/credit_transfers", "Credit transfers"),
    ("ach/debit_transfers", "Debit transfers"),
    ("ach/network", "Network"),
    ("ach/network/credit_transfers", "Credit transfers"),
    ("ach/network/debit_transfers", "Debit transfers"),
    ("ach/on_us", "On-us"),
    ("ach/on_us/credit_transfers", "Credit transfers"),
    ("ach/on_us/debit_transfers", "Debit transfers"),
    ("checks", "Checks"),
    ("checks/interbank", "Interbank"),
    ("checks/on_us", "On-us"),
    ("additional/checks_written", "Checks written"),
    ("additional/checks_converted_to_ach", "Checks converted to ACH"),
    ("additional/atm_cash_withdrawals", "ATM cash withdrawals"),
]


def frps_table() -> dict:
    rows = sheet_rows(FRPS_URL, "Table 1")
    year_row = next(r for r in rows if r[1] == "Noncash payment type")
    years = {int(c): i for i, c in enumerate(year_row) if isinstance(c, (int, float))}
    data_rows = [r for r in rows[rows.index(year_row) + 1:] if isinstance(r[1], str) and isinstance(r[2], (int, float))]
    if [r[1] for r in data_rows] != [label for _, label in FRPS_ROWS]:
        raise ValueError(f"Table 1 rows changed: {[r[1] for r in data_rows]}")
    table = {}
    for (key, label), r in zip(FRPS_ROWS, data_rows):
        row = {"payment_type": label}
        for year, i in years.items():
            row[f"number_billions_{year}"] = round(r[i], 6)
            row[f"value_usd_trillions_{year}"] = round(r[i + 1], 6)
            row[f"average_usd_{year}"] = round(r[i + 2], 4)
        table[key] = row
    latest = max(years)
    total = data_rows[0]
    ach = next(r for r in data_rows if r[1] == "Automated clearinghouse (ACH)")
    items = [
        cell_evidence(FRB, "Federal Reserve Payments Study, 2025 initial data release workbook, Table 1", FRPS_URL, f"row Total, {latest} Number (billions)", total[years[latest]], "count"),
        cell_evidence(FRB, "Federal Reserve Payments Study, 2025 initial data release workbook, Table 1", FRPS_URL, f"row Automated clearinghouse (ACH), {latest} Value ($ trillions)", ach[years[latest] + 1], "currency:USD"),
        evidence(FRB, "Federal Reserve Payments Study, 2025 initial data release workbook, Table 1", FRPS_URL, "table title", "Table 1. Noncash payments, 2015, 2018, 2021, and 2024", "text", "Table 1. Noncash payments, 2015, 2018, 2021, and 2024", UNSTATED, RESOURCES[FRPS_URL], role="supporting"),
    ]
    return lookup_entry(
        entry_id="us-fed-payments-study-noncash-payments-by-type-2015-2024",
        title="Federal Reserve Payments Study: noncash payments by type, number, value and average payment, 2015, 2018, 2021 and 2024",
        domain="payments",
        rows=table,
        parameters={"key": "payment type path", "years": sorted(years), "units": {"number": "billions of payments", "value": "trillions of US dollars", "average": "US dollars per payment"}},
        vectors=[
            {"input": {"key": "total", "column": f"number_billions_{latest}"}, "expected": table["total"][f"number_billions_{latest}"], "origin": "source"},
            {"input": {"key": "ach", "column": f"value_usd_trillions_{latest}"}, "expected": table["ach"][f"value_usd_trillions_{latest}"], "origin": "source"},
            {"input": "cards/credit/general_purpose", "expected": True, "origin": "source"},
            {"input": "wire", "expected": False, "origin": "derived"},
        ],
        valid=(f"{latest}-01-01", f"{latest}-12-31"),
        evidence_items=items,
        notes=(
            "Table 1 of the Federal Reserve Payments Study's 2025 initial data release: number (billions), value "
            "(trillions of US dollars) and average value (dollars) of noncash payments by instrument for the calendar "
            "years 2015, 2018, 2021 and 2024. Rows are keyed by a path that follows the table's nesting (cards, debit "
            "and credit, prepaid types; ACH credit and debit transfers, network and on-us; interbank and on-us checks; "
            "additional estimates). Figures are the study's estimates, unrounded. " + FEDERAL_NOTE
        ),
        tags=["payments", "federal-reserve", "payments-study", "cards", "ach", "checks", "value-pool"],
        use_cases=["payments-demo", "fintech-demo", "banking-demo", "market-sizing", "fraud-detection-demo"],
        status=REVIEW,
        tests=[{"statistic": f"max[average_usd_{latest}]", "expected": max(r[f"average_usd_{latest}"] for r in table.values()), "tolerance": 0}],
    )


def build_frps() -> None:
    get(FRPS_URL)
    finish(frps_table())


BUILDERS = {
    "fdic": build_fdic,
    "fema": build_fema,
    "hmda": build_hmda,
    "fhfa": build_fhfa,
    "nyfed": build_nyfed,
    "scf": build_scf,
    "treasury": build_treasury,
    "frps": build_frps,
}


# Sources whose responses change within hours even when the published figures do not (an index
# timestamp and a growing all-time record count in every CFPB response, hourly re-exports of the
# FEMA web summaries), so their evidence cannot hold a content hash. They run only when named.
ON_DEMAND = {
    "cfpb": build_cfpb,
    "fema-ihp": build_fema_ihp,
}


def main(argv: list[str]) -> None:
    groups = {**BUILDERS, **ON_DEMAND}
    for name in argv or list(BUILDERS):
        groups[name]()


if __name__ == "__main__":
    main(sys.argv[1:])

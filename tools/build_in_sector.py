"""Build the India telecom, insurance, pensions and insolvency entries.

Sources are official PDFs and spreadsheets from the Telecom Regulatory
Authority of India (monthly subscription press releases and the quarterly
performance indicators report), the Insurance Regulatory and Development
Authority of India (annual report and motor third-party data), the Pension
Fund Regulatory and Development Authority (handbook of NPS statistics) and
the Insolvency and Bankruptcy Board of India (quarterly newsletter workbook).
Every number is parsed or transcribed from the fetched document, and every
evidence item is checked against the document text with the same rules the
verifier applies before the entry is written. Run from the repository root:

    uv run python tools/build_in_sector.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

TRAI = "Telecom Regulatory Authority of India"
IRDAI = "Insurance Regulatory and Development Authority of India"
PFRDA = "Pension Fund Regulatory and Development Authority"
IBBI = "Insolvency and Bankruptcy Board of India"
UNSTATED = "unstated"

TRAI_FILES = "https://www.trai.gov.in/sites/default/files/"
PR_SEP_2026 = TRAI_FILES + "2026-10/PR_No140of2026.pdf"
PR_SEP_2026_TITLE = "Press Release No. 140/2026, Highlights of Telecom Subscription Data as on 30th September 2026"
QPIR = TRAI_FILES + "2026-10/QPIR_12102026.pdf"
QPIR_TITLE = "The Indian Telecom Services Performance Indicators, April-June 2026 (released 12 October 2026)"
IRDAI_DOCS = "https://irdai.gov.in/documents/37343/"
IRDAI_ANNUAL_REPORT = (
    IRDAI_DOCS + "366637/%E0%A4%86%E0%A4%88%E0%A4%86%E0%A4%B0%E0%A4%A1%E0%A5%80%E0%A4%8F%E0%A4%86%E0%A4%88+%E0%A4%B5%E0%A4%BE%E0%A4%B0"
    "%E0%A5%8D%E0%A4%B7%E0%A4%BF%E0%A4%95+%E0%A4%B0%E0%A4%BF%E0%A4%AA%E0%A5%8B%E0%A4%B0%E0%A5%8D%E0%A4%9F+_+IRDAI+Annual+Report+2024-25.pdf/"
    "06f02832-66a3-6308-a16f-f46a6640fc93?version=2.0&t=1767598639163&download=true"
)
IRDAI_ANNUAL_REPORT_TITLE = "IRDAI Annual Report 2024-25"
IRDAI_MOTOR_TP = (
    IRDAI_DOCS + "672777/%E0%A4%B5%E0%A4%BF%E0%A4%A4%E0%A5%8D%E0%A4%A4%E0%A5%80%E0%A4%AF+%E0%A4%B5%E0%A4%B0%E0%A5%8D%E0%A4%B7+2023-24+"
    "%E0%A4%95%E0%A5%87+%E0%A4%B2%E0%A4%BF%E0%A4%8F+%E0%A4%AE%E0%A5%8B%E0%A4%9F%E0%A4%B0+%E0%A4%A4%E0%A5%83%E0%A4%A4%E0%A5%80%E0%A4%AF+"
    "%E0%A4%AA%E0%A4%95%E0%A5%8D%E0%A4%B7+%E0%A4%A6%E0%A4%BE%E0%A4%AF%E0%A4%BF%E0%A4%A4%E0%A5%8D%E0%A4%B5+%E0%A4%95%E0%A5%80+"
    "%E0%A4%97%E0%A4%A3%E0%A4%A8%E0%A4%BE+%E0%A4%95%E0%A5%87+%E0%A4%B2%E0%A4%BF%E0%A4%8F+%E0%A4%86%E0%A4%81%E0%A4%95%E0%A5%9C%E0%A5%87+_+"
    "DATA+FOR+CALCULATION+OF+MOTOR+TP+OBLIGATION+FOR+FY+2023-24.pdf/ce5746c4-23ec-62ae-a8de-872e171b1f4b?version=1.0&t=1700731791057&download=true"
)
IRDAI_MOTOR_TP_TITLE = "Data for calculation of Motor TP obligation for FY 2023-24 (audited figures for FY 2022-23)"
PFRDA_HANDBOOK = "https://www.pfrda.org.in/documents/33652/203559/HoNPSS+2024-25.pdf"
PFRDA_HANDBOOK_TITLE = "Handbook of National Pension System Statistics 2025"
IBBI_NEWSLETTER = "https://ibbi.gov.in/uploads/publication/18054eb85bc0e7388537b05326192072.xlsx"
IBBI_NEWSLETTER_TITLE = "IBBI Quarterly Newsletter for April-June 2026 (data workbook)"

# Monthly TRAI subscription press releases for 2025, oldest first. The
# December 2025 release (PR 19/2026) is an image-only PDF and is left out.
MONTHLY_2025 = [
    ("2025-01", "2025-04/TSD-Jan_25_English_1.pdf", "Press Release No.27/2025", "31st January, 2025"),
    ("2025-02", "2025-04/TSD-Feb_25_English_0.pdf", "Press Release No.31/2025", "28th February, 2025"),
    ("2025-03", "2025-05/PR_No.35of2025_0.pdf", "Press Release No.35/2025", "31st March, 2025"),
    ("2025-04", "2025-05/PR_No.44of2025_0.pdf", "Press Release No.44/2025", "30th April 2025"),
    ("2025-05", "2025-06/PR_No.51of2025_0.pdf", "Press Release No. 51/2025", "31st May 2025"),
    ("2025-06", "2025-07/PR_No.64of2025_0.pdf", "Press Release No. 64/2025", "30th June 2025"),
    ("2025-07", "2025-08/PR_No.83of2025_0.pdf", "Press Release No. 83/2025", "31st July 2025"),
    ("2025-08", "2025-10/PR_No.104of2025_0.pdf", "Press Release No104/2025", "31st August 2025"),
    ("2025-09", "2025-10/PR_No.120of2025_0.pdf", "Press Release No.120/2025", "30th September 2025"),
    ("2025-10", "2025-11/PR_No.141of2025_0.pdf", "Press Release No. 141/2025", "31st October 2025"),
    ("2025-11", "2025-12/English%20Press%20Release%20of%20Telecom%20Subscription%20Data-November-25_English-31.12.2025_1815-sd_0.pdf", "Press Release No.156/2025", "30th November 2025"),
]

# TRAI licensed service areas: the spellings the two documents use, keyed by slug.
SERVICE_AREAS = {
    "andhra-pradesh": ("Andhra Pradesh", "AP"),
    "assam": ("Assam",),
    "bihar": ("Bihar",),
    "delhi": ("Delhi",),
    "gujarat": ("Gujarat",),
    "haryana": ("Haryana",),
    "himachal-pradesh": ("Himachal Pradesh", "HP"),
    "jammu-and-kashmir": ("J & K", "Jammu & Kashmir", "J&K"),
    "karnataka": ("Karnataka",),
    "kerala": ("Kerala",),
    "kolkata": ("Kolkata",),
    "madhya-pradesh": ("Madhya Pradesh", "MP"),
    "maharashtra": ("Maharashtra", "Maharashtr a", "MH"),
    "mumbai": ("Mumbai",),
    "north-east": ("North East", "NE"),
    "odisha": ("Odisha", "Orissa"),
    "punjab": ("Punjab",),
    "rajasthan": ("Rajasthan",),
    "tamil-nadu": ("Tamil Nadu", "TN (incl. Chennai)"),
    "uttar-pradesh-east": ("U.P.(E)", "U.P.(East)", "UP(E)"),
    "uttar-pradesh-west": ("U.P.(W)", "U.P.(West)", "UP(W)"),
    "west-bengal": ("West Bengal", "WB"),
}
AREA_BY_NAME = {name: slug for slug, names in SERVICE_AREAS.items() for name in names}
AREA_PATTERN = "|".join(sorted((re.escape(n) for n in AREA_BY_NAME), key=len, reverse=True))


@dataclass(frozen=True)
class Source:
    publisher: str
    title: str
    url: str
    raw: bytes

    @property
    def text(self) -> str:
        return Resource(url=self.url, content=self.raw, content_type="").text

    @property
    def pages(self) -> list[str]:
        from io import BytesIO

        from pypdf import PdfReader

        return [page.extract_text() or "" for page in PdfReader(BytesIO(self.raw)).pages]


_SOURCES: dict[str, Source] = {}


def source(publisher: str, title: str, url: str) -> Source:
    if url not in _SOURCES:
        _SOURCES[url] = Source(publisher, title, url, fetch(url))
    return _SOURCES[url]


def collapse(text: str) -> str:
    return " ".join(text.split())


def item(src: Source, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
    """An evidence item whose snippet and value are confirmed in the source text before use."""
    text = collapse(src.text)
    if collapse(snippet) not in text:
        raise ValueError(f"snippet not in {src.title}: {snippet!r}")
    if collapse(str(value)) not in text:
        raise ValueError(f"value not in {src.title}: {value!r}")
    if len(snippet.split()) >= 25:
        raise ValueError(f"snippet too long: {snippet!r}")
    return evidence(src.publisher, src.title, src.url, locator, value, unit, snippet, UNSTATED, src.raw, role)


def number(token: str) -> float:
    return float(token.replace(",", "").replace("(", "-").replace(")", "").rstrip("*$%"))


def share_table(counts: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, 6) for k, v in counts.items()}


def marginal(entry_id: str, title: str, domain: str, variable: str, counts: dict[str, float], count_unit: str, period: tuple[str, str], evidence_items: list[dict], notes: str, tags: list[str], use_cases: list[str], tier: str = "B", shares: dict[str, float] | None = None, assumed: list[dict] | None = None, extra: dict | None = None) -> dict:
    """A categorical marginal whose shares are derived from published counts (or taken as published)."""
    derived = shares is None
    shares = shares or share_table(counts)
    ranked = sorted(shares, key=shares.get, reverse=True)
    tests = [{"statistic": f'share["{c}"]' if "," in c else f"share[{c}]", "expected": shares[c], "tolerance": 0.004} for c in ranked[:3]]
    tests.append({"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.002})
    assumptions = list(assumed or [])
    if derived:
        assumptions.insert(0, {
            "parameter": "distribution.parameters.shares",
            "value": "count / total, rounded to six decimals",
            "method": "derived",
            "rationale": f"The source publishes counts ({count_unit}); each share is the category count divided by the sum of the listed counts ({sum(counts.values()):g}). The counts are kept in distribution.parameters.counts.",
        })
    parameters = {"shares": shares, "counts": counts, **(extra or {})}
    return {
        "id": entry_id,
        "title": title,
        "kind": "marginal",
        "domain": domain,
        "region": "IN",
        "status": "license-review",
        "tier": tier,
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": parameters}},
        "evidence": evidence_items,
        "assumed": assumptions,
        "tests": tests,
        "notes": notes,
    }


def lookup(entry_id: str, title: str, domain: str, rows: dict[str, dict], valid_from: str, valid_to: str | None, vectors: list[dict], tests: list[dict], evidence_items: list[dict], notes: str, tags: list[str], use_cases: list[str], tier: str = "B", assumed: list[dict] | None = None, extra: dict | None = None) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": "IN",
        "status": "license-review",
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {**(extra or {}), "rows": rows},
            "vectors": vectors + [{"input": next(iter(rows)), "expected": True, "origin": "source"}, {"input": "no-such-key", "expected": False, "origin": "derived", "note": "keys outside the table are absent"}],
        },
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, {"statistic": "count", "expected": len(rows), "tolerance": 0}] + tests,
        "notes": notes,
    }


def temporal(entry_id: str, title: str, domain: str, variable: str, unit: str, frequency: str, series: list[dict], columns: list[str], period: tuple[str, str], evidence_items: list[dict], notes: str, tags: list[str], use_cases: list[str], tier: str = "B", assumed: list[dict] | None = None) -> dict:
    values = [p["value"] for p in series]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "IN",
        "status": "license-review",
        "tier": tier,
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [
            {"statistic": f"value[{series[0]['period']}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
            {"statistic": "max", "expected": max(values), "tolerance": 1e-9},
        ],
        "notes": notes,
    }


TRAI_NOTE = "TRAI's website carries no licence statement for its press releases and reports, so the entry stays at license-review."
IRDAI_NOTE = "IRDAI publishes the document without a licence statement, so the entry stays at license-review."


# --- TRAI monthly press release, September 2026 ---------------------------------------------------


def build_subscribers_and_teledensity(pr: Source) -> dict:
    rows = {
        "wireless": {"subscribers_million": 1319.19, "urban_subscribers_million": 764.35, "rural_subscribers_million": 554.84, "net_addition_million": 6.94, "monthly_growth_percent": 0.53, "urban_share_percent": 57.94, "rural_share_percent": 42.06, "teledensity_percent": 92.12, "urban_teledensity_percent": 147.47, "rural_teledensity_percent": 60.72, "teledensity_without_m2m_percent": 82.00, "broadband_subscribers_million": 1058.79, "broadband_subscribers_without_m2m_million": 964.98},
        "wireline": {"subscribers_million": 48.74, "urban_subscribers_million": 43.43, "rural_subscribers_million": 5.32, "net_addition_million": 0.29, "monthly_growth_percent": 0.60, "urban_share_percent": 89.09, "rural_share_percent": 10.91, "teledensity_percent": 3.40, "urban_teledensity_percent": 8.38, "rural_teledensity_percent": 0.58, "teledensity_without_m2m_percent": 3.40, "broadband_subscribers_million": 48.89, "broadband_subscribers_without_m2m_million": 48.89},
        "total": {"subscribers_million": 1367.93, "urban_subscribers_million": 807.78, "rural_subscribers_million": 560.16, "net_addition_million": 7.23, "monthly_growth_percent": 0.53, "urban_share_percent": 59.05, "rural_share_percent": 40.95, "teledensity_percent": 95.52, "urban_teledensity_percent": 155.85, "rural_teledensity_percent": 61.30, "teledensity_without_m2m_percent": 85.41, "broadband_subscribers_million": 1107.68, "broadband_subscribers_without_m2m_million": 1013.87},
    }
    return lookup(
        "in-telecom-subscribers-and-teledensity-2026-09",
        "India telephone subscribers, urban/rural split and tele-density by segment, end of September 2026 (TRAI)",
        "telecom", rows, "2026-09-30", None,
        [
            {"input": {"key": "wireless", "column": "subscribers_million"}, "expected": 1319.19, "origin": "source"},
            {"input": {"key": "total", "column": "teledensity_percent"}, "expected": 95.52, "origin": "source"},
            {"input": {"key": "wireline", "column": "urban_share_percent"}, "expected": 89.09, "origin": "source"},
        ],
        [{"statistic": "value[total,subscribers_million]", "expected": 1367.93, "tolerance": 0}, {"statistic": "value[wireless,rural_teledensity_percent]", "expected": 60.72, "tolerance": 0}],
        [
            item(pr, "page 1, highlights table, row Total Telephone Subscribers (Million)", "1319.19", "count", "Total Telephone Subscribers (Million) 1319.19 48.74 1367.93"),
            item(pr, "page 1, highlights table, row Overall Tele-density with M2M", "95.52%", "percent", "Overall Tele-density @ with M2M cellular mobile connections 92.12% 3.40% 95.52%"),
            item(pr, "page 1, highlights table, row Urban Tele-density", "147.47%", "percent", "Urban Tele-density@ 147.47% 8.38% 155.85%"),
            item(pr, "page 1, highlights table, row Share of Urban Subscribers", "57.94%", "percent", "Share of Urban Subscribers 57.94% 89.09% 59.05%"),
            item(pr, "page 1, highlights table, row Broadband Subscribers with M2M", "1,107.68", "count", "Broadband Subscribers with M2M cellular mobile connections (Million) 1,058.79 48.89 1,107.68"),
            item(pr, "page 16, active subscribers", "1212.80", "count", "1212.80 million wireless (mobile) subscribers were active on the date of peak VLR"),
        ],
        "The highlights table on page 1 of TRAI's monthly subscription press release for September 2026, keyed by segment "
        "(wireless, wireline, total). Wireless comprises mobile subscribers including M2M cellular connections plus fixed "
        "wireless access; tele-density uses the 2011-2036 population projections of the Technical Group on Population "
        "Projections. Extra parameters record the active (VLR) wireless base and the month's MNP requests. " + TRAI_NOTE,
        ["telecom", "subscribers", "teledensity", "trai", "reference-table"], ["telecom-demo", "market-sizing", "customer-segmentation"],
        extra={"as_on": "2026-09-30", "active_wireless_subscribers_peak_vlr_million": 1212.80, "mnp_requests_in_month_million": 16.77, "reporting_operators": 1596},
    )


def build_connection_types(pr: Source) -> dict:
    counts = {"consumer_sim": 1155.15, "m2m_sim": 144.85, "fixed_wireless_access": 19.19, "wireline": 48.74}
    return marginal(
        "in-telephone-subscribers-by-connection-type-2026-09",
        "India telephone subscribers by connection type (consumer SIM, M2M SIM, FWA, wireline), end of September 2026",
        "telecom", "connection_type", counts, "million subscribers", ("2026-09-30", "2026-09-30"),
        [
            item(pr, "page 13, table Telephone subscriber base at the end of September 2026, row Consumer SIM", "1,155.15", "count", "Wireless Consumer SIM 1,155.15"),
            item(pr, "page 13, same table, row M2M SIM", "144.85", "count", "M2M SIM 144.85"),
            item(pr, "page 13, same table, row FWA", "19.19", "count", "FWA 19.19"),
            item(pr, "page 13, same table, rows Wireline and Total", "1,367.93", "count", "Wireline 48.74 5. Total 1,367.93"),
        ],
        "Composition of India's 1,367.93 million telephone connections at the end of September 2026 from the summary table on "
        "page 13 of TRAI's press release: consumer mobile SIMs, machine-to-machine SIMs, fixed wireless access and wireline. "
        "Shares are the published counts (in millions) divided by their sum. " + TRAI_NOTE,
        ["telecom", "subscribers", "m2m", "fwa", "trai"], ["telecom-demo", "customer-segmentation"],
    )


def build_broadband_by_provider(pr: Source) -> dict:
    counts = {"reliance-jio": 541.17, "bharti-airtel": 388.86, "vodafone-idea": 131.00, "bsnl": 28.55, "atria-convergence": 2.50}
    counts["others"] = round(1107.68 - sum(counts.values()), 2)
    return marginal(
        "in-broadband-subscribers-by-provider-2026-09",
        "India broadband subscribers by service provider (top five and others), end of September 2026",
        "telecom", "broadband_provider", counts, "million subscribers", ("2026-09-30", "2026-09-30"),
        [
            item(pr, "page 2, table Top five Broadband Service providers, row 1", "541.17", "count", "Reliance Jio Infocomm Ltd. 541.17"),
            item(pr, "page 2, same table, row 2", "388.86", "count", "Bharti Airtel Ltd. 388.86"),
            item(pr, "page 2, same table, row 3", "131.00", "count", "Vodafone Idea Ltd. 131.00"),
            item(pr, "page 2, same table, row 4", "28.55", "count", "Bharat Sanchar Nigam Ltd. 28.55"),
            item(pr, "page 2, same table, row 5", "2.50", "count", "Atria Convergence Technologies Ltd. 2.50"),
            item(pr, "page 2, same table, market share of top five", "98.59%", "percent", "Market Share of Top Five Broadband (Wired & Wireless) Service Providers 98.59%"),
            item(pr, "page 2, paragraph I", "1107.68", "count", "1107.68 million at the end of September 2026 with a monthly growth rate of 0.59%"),
        ],
        "Wired plus wireless broadband subscribers of the five largest providers at the end of September 2026 (page 2 of the TRAI "
        "press release) with the remainder of the 1,107.68 million total assigned to 'others'. The release states the top five "
        "hold 98.59% of the market, which the derived shares reproduce. " + TRAI_NOTE,
        ["telecom", "broadband", "market-share", "trai"], ["telecom-demo", "market-sizing", "customer-segmentation"],
        assumed=[{"parameter": "counts.others", "value": counts["others"], "method": "derived", "rationale": "Total broadband subscribers (1,107.68 million) minus the five listed providers."}],
    )


def build_wireless_by_operator(pr: Source) -> dict:
    page = pr.pages[19]
    totals = [t for t in re.search(r"^Total ([\d, ]+)$", page, re.M).group(1).split()]
    tokens = [int(t.replace(",", "")) for t in totals]
    # Annexure-II lists August and September pairs for six operators, then the grand total pair and net addition.
    september = tokens[1:13:2]
    counts = dict(zip(["bharti-airtel", "reliance-communications", "vodafone-idea", "bsnl", "mtnl", "reliance-jio"], september))
    grand_total = tokens[13]
    if sum(counts.values()) != grand_total:
        raise ValueError("operator counts do not add up to the Annexure-II total")
    psu_share = (counts["bsnl"] + counts["mtnl"]) / grand_total
    if round(psu_share * 100, 2) != 7.26:
        raise ValueError(f"PSU share check failed: {psu_share}")
    return marginal(
        "in-wireless-mobile-subscribers-by-operator-2026-09",
        "India wireless (mobile) subscribers by access service provider, end of September 2026",
        "telecom", "mobile_operator", counts, "subscribers", ("2026-09-30", "2026-09-30"),
        [
            item(pr, "page 20, Annexure-II Wireless (Mobile) Subscriber Base, row Total, September 2026 columns", "1,299,999,801", "count", "Total 491,599,117 494,291,213 32 23 199,569,351 200,119,470"),
            item(pr, "page 20, Annexure-II, row Total, Reliance Jio September 2026", "511,144,537", "count", "508,431,905 511,144,537 1,293,425,958 1,299,999,801"),
            item(pr, "page 20, Annexure-II, row Total, BSNL and MTNL September 2026", "94,296,332", "count", "93,670,699 94,296,332 154,854 148,226"),
            item(pr, "page 8, market share paragraph", "7.26%", "percent", "BSNL and MTNL together held a market share of 7.26%"),
            item(pr, "page 11, M2M paragraph", "88.58", "count", "Bharti Airtel Limited has the highest number of M2M cellular mobile connections of 88.58 million"),
        ],
        "Wireless (mobile) subscribers, including M2M cellular connections, of each access service provider at the end of September "
        "2026 from the 'Total' row of Annexure-II (page 20) of the TRAI press release; FWA subscribers are excluded. Shares are the "
        "counts divided by the 1,299,999,801 total and reproduce the 92.74%/7.26% private/PSU split stated on page 8. " + TRAI_NOTE,
        ["telecom", "mobile", "market-share", "operators", "trai"], ["telecom-demo", "customer-segmentation", "market-sizing"],
        assumed=[{
            "parameter": "column assignment",
            "value": "Bharti Airtel, Reliance Communications, Vodafone Idea, BSNL, MTNL, Reliance Jio",
            "method": "derived",
            "rationale": "pypdf flattens the Annexure-II header, so operator columns were identified from the body: the MTNL column equals the Delhi plus Mumbai cells, the private/PSU split matches page 8, and the order agrees with Annexure 1.1 of TRAI's quarterly performance indicators report.",
        }],
    )


def build_wireless_by_service_area(pr: Source) -> dict:
    page = pr.pages[19]
    counts: dict[str, int] = {}
    for line in page.splitlines():
        match = re.match(rf"^\s*({AREA_PATTERN})\s+((?:[\d,]+\s+)+[\d,]+)\s*$", line)
        if match:
            tokens = [int(t.replace(",", "")) for t in match.group(2).split()]
            counts[AREA_BY_NAME[match.group(1)]] = tokens[-2]
    if len(counts) != 22 or sum(counts.values()) != 1_299_999_801:
        raise ValueError(f"service-area parse failed: {len(counts)} areas, sum {sum(counts.values())}")
    counts = dict(sorted(counts.items()))
    return marginal(
        "in-wireless-mobile-subscribers-by-service-area-2026-09",
        "India wireless (mobile) subscribers by licensed service area (22 LSAs), end of September 2026",
        "telecom", "service_area", counts, "subscribers", ("2026-09-30", "2026-09-30"),
        [
            item(pr, "page 20, Annexure-II, row Uttar Pradesh (East), total September 2026", "112,699,737", "count", "112,120,701 112,699,737 579,036"),
            item(pr, "page 20, Annexure-II, row Himachal Pradesh, total September 2026", "9,504,254", "count", "9,450,851 9,504,254 53,403"),
            item(pr, "page 20, Annexure-II, row Delhi, total September 2026", "79,440,979", "count", "78,365,095 79,440,979 1,075,884"),
            item(pr, "page 20, Annexure-II, row Total", "1,299,999,801", "count", "1,293,425,958 1,299,999,801 6,573,843"),
            item(pr, "page 14, note 3 on Delhi coverage", "Ghaziabad & Noida", "text", "Telephone subscriber data for Delhi, includes, apart from the data for the State of Delhi"),
        ],
        "Wireless (mobile) subscribers in each of TRAI's 22 licensed service areas at the end of September 2026, taken from the "
        "'Total' column of Annexure-II (page 20). Service areas are not states: Delhi includes Ghaziabad, Noida, Gurgaon and "
        "Faridabad, Mumbai and Kolkata are separate from Maharashtra and West Bengal, Uttar Pradesh is split East/West, and "
        "North East covers six states (page 14 notes). Shares are counts divided by the 1,299,999,801 total. " + TRAI_NOTE,
        ["telecom", "mobile", "service-area", "geography", "trai"], ["telecom-demo", "address-generation", "customer-segmentation"],
    )


def build_mnp_by_service_area(pr: Source) -> dict:
    text = collapse(pr.pages[17])
    counts: dict[str, int] = {}
    for match in re.finditer(rf"({AREA_PATTERN}) ([\d,]+) ([\d,]+)", text):
        counts[AREA_BY_NAME[match.group(1)]] = int(match.group(3).replace(",", ""))
    if len(counts) != 22 or sum(counts.values()) != 16_769_016:
        raise ValueError(f"MNP parse failed: {len(counts)} areas, sum {sum(counts.values())}")
    counts = dict(sorted(counts.items()))
    return marginal(
        "in-mnp-porting-requests-by-service-area-2026-09",
        "India mobile number portability requests by licensed service area, September 2026",
        "telecom", "service_area", counts, "porting requests", ("2026-09-01", "2026-09-30"),
        [
            item(pr, "page 18, table Licensed Service Area Wise MNP Status, row Total (Zone-I + Zone-II)", "16,769,016", "count", "Total (Zone-I + Zone-II) 15,829,976 16,769,016"),
            item(pr, "page 18, same table, row U.P.(East) September-26", "2,493,562", "count", "U.P.(East) 2,227,586 2,493,562"),
            item(pr, "page 18, same table, row Bihar September-26", "1,530,124", "count", "Bihar 1,469,902 1,530,124"),
            item(pr, "page 17, section VIII", "16.77", "count", "about 16.77 million subscribers submitted their requests for MNP"),
        ],
        "Number of mobile number portability requests submitted in September 2026 in each licensed service area, from the LSA-wise "
        "MNP status table on page 18 of the TRAI press release (Zone-I covers northern and western India, Zone-II southern and "
        "eastern). Shares are counts divided by the 16,769,016 total and give a churn-by-circle pattern for telecom generators. " + TRAI_NOTE,
        ["telecom", "mnp", "churn", "service-area", "trai"], ["telecom-demo", "customer-segmentation", "crm-demo"],
    )


def build_monthly_wireless_2025() -> dict:
    series: list[dict] = []
    items: list[dict] = []
    for period, path, release, as_on in MONTHLY_2025:
        src = source(TRAI, f"{release}, Highlights of Telecom Subscription Data as on {as_on}", TRAI_FILES + path)
        page = src.pages[0]
        match = re.search(r"Total Telephone Subscribers \(Million\)\s+([\d.]+)[*$]?\s+([\d.]+)[*$]?\s+([\d.]+)", page)
        if not match or f"as on {as_on}" not in collapse(page):
            raise ValueError(f"could not read {release}")
        wireless, wireline, total = (float(match.group(i)) for i in (1, 2, 3))
        series.append({"period": period, "value": wireless, "wireline_million": wireline, "total_million": total})
        items.append(item(src, "page 1, highlights table, row Total Telephone Subscribers (Million), wireless column", match.group(1), "count", f"Highlights of Telecom Subscription Data as on {as_on}"))
    return temporal(
        "in-wireless-subscribers-monthly-2025",
        "India wireless telephone subscribers, monthly January to November 2025 (TRAI press releases)",
        "telecom", "wireless_subscribers_million", "count", "monthly", series, ["wireline_million", "total_million"], ("2025-01-01", "2025-11-30"), items,
        "End-of-month wireless, wireline and total telephone subscribers (millions) from the highlights table of each monthly TRAI "
        "subscription press release for 2025; one evidence item per release. The December 2025 release (PR 19/2026) is an "
        "image-only PDF and is omitted. The releases footnote that wireless includes 5G fixed wireless access subscriptions, and "
        "from mid-2025 the wireline column is noticeably higher than in the earlier months, so treat the series as published "
        "rather than strictly like-for-like. " + TRAI_NOTE,
        ["telecom", "subscribers", "monthly", "time-series", "trai"], ["telecom-demo", "demand-forecasting", "market-sizing"],
    )


# --- TRAI quarterly performance indicators, quarter ending June 2026 ---------------------------------


def build_qpir_indicators(q: Source) -> dict:
    rows = {
        "arpu_blended": {"value": 187.12, "unit": "currency:INR", "description": "Monthly average revenue per user, wireless, all India"},
        "arpu_prepaid": {"value": 200.72, "unit": "currency:INR", "description": "Monthly ARPU, prepaid segment"},
        "arpu_postpaid": {"value": 114.26, "unit": "currency:INR", "description": "Monthly ARPU, postpaid segment"},
        "arpu_private_operators": {"value": 194.90, "unit": "currency:INR", "description": "Monthly ARPU, all private service providers"},
        "arpu_psu_operators": {"value": 87.99, "unit": "currency:INR", "description": "Monthly ARPU, public sector operators"},
        "mou_per_subscriber_per_month": {"value": 933, "unit": "integer", "description": "Minutes of usage per subscriber per month, blended"},
        "mou_prepaid": {"value": 1055, "unit": "integer", "description": "Minutes of usage per prepaid subscriber per month"},
        "mou_postpaid": {"value": 279, "unit": "integer", "description": "Minutes of usage per postpaid subscriber per month"},
        "incoming_mou_per_subscriber": {"value": 466.37, "unit": "decimal", "description": "Incoming minutes per subscriber per month"},
        "outgoing_mou_per_subscriber": {"value": 466.91, "unit": "decimal", "description": "Outgoing minutes per subscriber per month"},
        "outgoing_sms_per_subscriber": {"value": 8.79, "unit": "decimal", "description": "Outgoing SMS per subscriber per month"},
        "prepaid_share_percent": {"value": 83.88, "unit": "percent", "description": "Prepaid subscribers as a share of wireless subscribers"},
        "data_usage_gb_per_subscriber_per_month": {"value": 28.39, "unit": "decimal", "description": "Average wireless data usage per wireless data subscriber per month, GB"},
        "revenue_per_gb": {"value": 7.13, "unit": "currency:INR", "description": "Average revenue realisation per GB of wireless data"},
        "wireless_data_subscribers_million": {"value": 1045.55, "unit": "count", "description": "Wireless (mobile) data subscribers at quarter end, millions"},
        "wireless_data_usage_petabytes": {"value": 84424, "unit": "count", "description": "Total wireless (mobile) data usage during the quarter, PB"},
        "internet_subscribers_million": {"value": 1114.17, "unit": "count", "description": "Total internet subscribers at quarter end, millions"},
        "broadband_subscribers_million": {"value": 1087.50, "unit": "count", "description": "Broadband internet subscribers, millions"},
        "narrowband_subscribers_million": {"value": 26.67, "unit": "count", "description": "Narrowband internet subscribers, millions"},
        "internet_subscribers_per_100": {"value": 77.94, "unit": "decimal", "description": "Internet subscribers per 100 population"},
        "urban_internet_subscribers_per_100": {"value": 129.03, "unit": "decimal", "description": "Urban internet subscribers per 100 population"},
        "rural_internet_subscribers_per_100": {"value": 49.07, "unit": "decimal", "description": "Rural internet subscribers per 100 population"},
        "gross_revenue_crore": {"value": 106797, "unit": "currency:INR", "description": "Gross revenue of the telecom service sector in the quarter, INR crore"},
        "adjusted_gross_revenue_crore": {"value": 88796, "unit": "currency:INR", "description": "Adjusted gross revenue in the quarter, INR crore"},
        "licence_fee_crore": {"value": 7103, "unit": "currency:INR", "description": "Licence fee in the quarter, INR crore"},
        "pay_dth_subscribers_million": {"value": 48.56, "unit": "count", "description": "Active subscribers of pay DTH operators, millions"},
    }
    return lookup(
        "in-wireless-revenue-and-usage-indicators-2026q2",
        "India telecom key indicators for the quarter ending June 2026: ARPU, minutes of usage, data usage, internet subscribers, sector revenue (TRAI)",
        "telecom", rows, "2026-04-01", "2026-06-30",
        [
            {"input": {"key": "arpu_blended", "column": "value"}, "expected": 187.12, "origin": "source"},
            {"input": {"key": "mou_prepaid", "column": "value"}, "expected": 1055, "origin": "source"},
            {"input": {"key": "data_usage_gb_per_subscriber_per_month", "column": "value"}, "expected": 28.39, "origin": "source"},
        ],
        [{"statistic": "value[arpu_postpaid,value]", "expected": 114.26, "tolerance": 0}, {"statistic": "value[revenue_per_gb,value]", "expected": 7.13, "tolerance": 0}],
        [
            item(q, "PDF page 6 (snapshot), Revenue & Usage Parameters", "187.12", "currency:INR", "Monthly ARPU of Wireless Service"),
            item(q, "PDF page 8 (executive summary), paragraph 7", "200.72", "currency:INR", "The ARPU per month for the pre-paid segment is"),
            item(q, "PDF page 8, paragraph 9", "1055", "integer", "Prepaid MOU per subscriber is 1055 and Postpaid MOU per subscriber"),
            item(q, "PDF page 6, Revenue & Usage Parameters", "28.39 GB", "decimal", "Average Wireless Data Usage per wireless data subscriber per month 28.39 GB"),
            item(q, "PDF page 88 (Table 2.1), row Share of Prepaid", "83.88%", "percent", "Share of Prepaid (%) 83.88% 84.67% 87.74%"),
            item(q, "PDF page 88 (Table 2.1), rows Incoming and Outgoing MOU", "466.37", "decimal", "Incoming MOU per subscriber per month. 466.37 479.13 489.39"),
            item(q, "PDF page 5 (snapshot), Internet/Broadband Subscribers", "1,114.17", "count", "Total Internet Subscribers 1,114.17 million"),
            item(q, "PDF page 5, Internet subscribers per 100 population", "77.94", "decimal", "Total Internet Subscribers per 100 population 77.94"),
            item(q, "PDF page 8, paragraph 11", "1045.55", "count", "1045.55 million at the end of June 2026 with quarterly rate of growth of 1.86%"),
            item(q, "PDF page 97 (Table 3.1), rows GR, AGR and LF for the quarter ending June 2026", "88,796", "currency:INR", "Adjusted Gross Revenue (AGR) ₹81,325 ₹86,716 ₹88,796"),
            item(q, "PDF page 6, Broadcasting", "48.56", "count", "Number of total active subscribers with pay DTH operators 48.56 million"),
        ],
        "Headline indicators for the quarter ending 30 June 2026 from TRAI's Indian Telecom Services Performance Indicators report "
        "(snapshot, executive summary, Table 2.1, Table 3.1), one row per indicator with its unit. ARPU is TRAI's regulatory "
        "measure: quarterly revenue net of interconnect and roaming settlement divided by average subscribers, which the report "
        "notes is lower than operators' own ARPU. Crore values are as printed (1 crore = 10 million). " + TRAI_NOTE,
        ["telecom", "arpu", "usage", "data", "internet", "revenue", "trai", "reference-table"], ["telecom-demo", "pricing", "market-sizing", "financial-reporting"],
        extra={"quarter_ending": "2026-06-30"},
    )


def build_prepaid_postpaid(q: Source) -> dict:
    shares = {"prepaid": 0.8388, "postpaid": 0.1612}
    return marginal(
        "in-wireless-prepaid-postpaid-split-2026q2",
        "India wireless subscribers by payment mode (prepaid vs postpaid), end of June 2026",
        "telecom", "payment_mode", {"prepaid": 83.88, "postpaid": 16.12}, "percent", ("2026-06-30", "2026-06-30"),
        [
            item(q, "PDF page 88 (Table 2.1), row Share of Prepaid, June 2026", "83.88%", "percent", "Share of Prepaid (%) 83.88% 84.67% 87.74%"),
            item(q, "PDF page 89, paragraph 2.3", "83.88%", "percent", "decreased from 84.67% at the end of March 2026 to 83.88% at the end of June 2026"),
        ],
        "Prepaid subscribers as a share of total wireless subscribers on the last day of the quarter ending June 2026 (TRAI Table 2.1), "
        "with postpaid as the complement. Annexure 2.1 of the same report gives the split by service area, carried in a separate entry. " + TRAI_NOTE,
        ["telecom", "prepaid", "postpaid", "trai"], ["telecom-demo", "customer-segmentation", "invoicing"],
        shares=shares,
        assumed=[{"parameter": "shares.postpaid", "value": 0.1612, "method": "derived", "rationale": "100% minus the published prepaid share of 83.88%."}],
    )


def build_arpu_composition(q: Source) -> dict:
    percent = {"rental": 0.53, "calls": 7.12, "sms": 0.16, "data_usage": 85.52, "other_vas": 0.61, "other_revenue": 4.33, "outroamers": 1.75}
    inr = {"rental": 1.02, "calls": 13.70, "sms": 0.30, "data_usage": 164.65, "other_vas": 1.17, "other_revenue": 8.33, "outroamers": 3.36}
    shares = {k: round(v / 100, 4) for k, v in percent.items()}
    return marginal(
        "in-wireless-revenue-per-subscriber-composition-2026q2",
        "India wireless revenue per subscriber per month by component (rental, calls, SMS, data, VAS, roaming), quarter ending June 2026",
        "telecom", "revenue_component", inr, "INR per subscriber per month", ("2026-04-01", "2026-06-30"),
        [
            item(q, "PDF page 90 (Table 2.3), row 1.4 Revenue from data usage", "164.65", "currency:INR", "Revenue from data usage 164.65 85.52"),
            item(q, "PDF page 90 (Table 2.3), row 1.2 Revenue from calls", "13.70", "currency:INR", "Revenue from calls 13.70 7.12"),
            item(q, "PDF page 90 (Table 2.3), row 1.1 Rental Revenue", "1.02", "currency:INR", "Rental Revenue 1.02 0.53"),
            item(q, "PDF page 90 (Table 2.3), row 2.1 Revenue from outroamers", "3.36", "currency:INR", "Revenue from outroamers 3.36 1.75"),
            item(q, "PDF page 90 (Table 2.3), row 3 total revenue from home subscribers", "192.53", "currency:INR", "Total revenue from home subscribers (A+B) 192.53 100.00"),
        ],
        "Composition of the INR 192.53 monthly revenue per wireless subscriber from home subscribers in the quarter ending June 2026 "
        "(TRAI Table 2.3): rental, calls, SMS, data usage, other value-added services and other revenue from the home service area, "
        "plus revenue from out-roamers. Shares are the published percentages divided by 100 (they sum to 100.02 because of "
        "rounding); the INR amounts are kept as counts. Revenue from in-roamers and interconnect is excluded from the base. " + TRAI_NOTE,
        ["telecom", "arpu", "billing", "revenue-mix", "trai"], ["telecom-demo", "invoicing", "pricing"],
        shares=shares,
        assumed=[{"parameter": "distribution.parameters.shares", "value": "published percentage / 100", "method": "derived", "rationale": "The report prints each component's share of revenue per subscriber to two decimals; dividing by 100 gives ratios that sum to 1.0002."}],
    )


def build_quarterly_indicators(q: Source) -> dict:
    arpu = [181.47, 183.13, 184.98, 184.91, 187.12]
    per_gb = [8.51, 8.27, 7.87, 7.51, 7.13]
    mou = [978, 963, 962, 959, 933]
    sms = [9.93, 10.58, 9.43, 8.40, 8.79]
    periods = ["2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]
    series = [{"period": p, "value": a, "revenue_per_gb_inr": g, "mou_per_subscriber_per_month": m, "outgoing_sms_per_subscriber_per_month": s} for p, a, g, m, s in zip(periods, arpu, per_gb, mou, sms)]
    return temporal(
        "in-wireless-arpu-quarterly-2025q2-2026q2",
        "India wireless ARPU, revenue per GB, minutes of usage and SMS per subscriber, quarterly June 2025 to June 2026 (TRAI)",
        "telecom", "arpu_inr_per_month", "currency:INR", "quarterly", series, ["revenue_per_gb_inr", "mou_per_subscriber_per_month", "outgoing_sms_per_subscriber_per_month"], ("2025-04-01", "2026-06-30"),
        [
            item(q, "PDF page 95 (Table 2.7), row 1 ARPU", "181.47 183.13 184.98 184.91 187.12", "currency:INR", "1. ARPU (₹ Per month) 181.47 183.13 184.98 184.91 187.12"),
            item(q, "PDF page 95 (Table 2.7), row 2 revenue per GB", "8.51 8.27 7.87 7.51 7.13", "currency:INR", "8.51 8.27 7.87 7.51 7.13"),
            item(q, "PDF page 95 (Table 2.7), row 3 MOU", "978 963 962 959 933", "integer", "month 978 963 962 959 933"),
            item(q, "PDF page 95 (Table 2.7), row 5 outgoing SMS", "9.93 10.58 9.43 8.40 8.79", "decimal", "per subscriber per month 9.93 10.58 9.43 8.40 8.79"),
        ],
        "Trend of key wireless parameters over the five quarters ending June 2025 to June 2026 from Table 2.7 of TRAI's performance "
        "indicators report: monthly ARPU (the series value), average revenue realisation per GB of wireless data, total minutes of "
        "usage per subscriber per month and outgoing SMS per subscriber per month. Period labels name the calendar quarter in "
        "which each quarter ends. " + TRAI_NOTE,
        ["telecom", "arpu", "usage", "quarterly", "time-series", "trai"], ["telecom-demo", "pricing", "demand-forecasting"],
    )


def build_service_area_revenue_usage(q: Source) -> dict:
    text = "\n".join(q.pages[142:144])
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        match = re.match(rf"^\s*({AREA_PATTERN})\s+([\d.]+)%\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", line)
        if match:
            rows[AREA_BY_NAME[match.group(1)]] = {
                "prepaid_share_percent": float(match.group(2)),
                "arpu_inr_per_month": int(match.group(3)),
                "outgoing_sms_per_subscriber_per_month": int(match.group(4)),
                "outgoing_mou_per_subscriber_per_month": int(match.group(5)),
                "incoming_mou_per_subscriber_per_month": int(match.group(6)),
                "total_mou_per_subscriber_per_month": int(match.group(7)),
            }
    if len(rows) != 22:
        raise ValueError(f"Annexure 2.1 parse found {sorted(rows)}")
    rows = dict(sorted(rows.items()))
    return lookup(
        "in-wireless-service-area-revenue-and-usage-2026q2",
        "India wireless prepaid share, ARPU, SMS and minutes of usage by licensed service area, quarter ending June 2026 (TRAI)",
        "telecom", rows, "2026-04-01", "2026-06-30",
        [
            {"input": {"key": "delhi", "column": "arpu_inr_per_month"}, "expected": rows["delhi"]["arpu_inr_per_month"], "origin": "source"},
            {"input": {"key": "bihar", "column": "total_mou_per_subscriber_per_month"}, "expected": rows["bihar"]["total_mou_per_subscriber_per_month"], "origin": "source"},
            {"input": {"key": "jammu-and-kashmir", "column": "prepaid_share_percent"}, "expected": rows["jammu-and-kashmir"]["prepaid_share_percent"], "origin": "source"},
        ],
        [{"statistic": "max[arpu_inr_per_month]", "expected": max(r["arpu_inr_per_month"] for r in rows.values()), "tolerance": 0}, {"statistic": "min[prepaid_share_percent]", "expected": min(r["prepaid_share_percent"] for r in rows.values()), "tolerance": 0}],
        [
            item(q, "PDF page 143 (Annexure 2.1), category-A table, row AP", "225", "currency:INR", "AP 87.38% 225 6 484 479 963"),
            item(q, "PDF page 143 (Annexure 2.1), category-B table, row UP(E)", "1152", "integer", "UP(E) 91.47% 165 7 571 581 1152"),
            item(q, "PDF page 143 (Annexure 2.1), category-C table, row J&K", "30.61%", "percent", "J&K 30.61% 199 13 569 554 1123"),
            item(q, "PDF page 144 (Annexure 2.1), category-Metro table, row Delhi", "52.51%", "percent", "Delhi 52.51% 128 4 367 324 691"),
        ],
        "Per-service-area wireless parameters for the quarter ending June 2026 from Annexure 2.1 of TRAI's performance indicators "
        "report: prepaid subscribers as a share of total, monthly ARPU in rupees, and outgoing SMS, outgoing, incoming and total "
        "minutes of usage per subscriber per month (usage from and outside the home service area). Rows are keyed by the slug of "
        "the licensed service area; Tamil Nadu includes Chennai. " + TRAI_NOTE,
        ["telecom", "arpu", "usage", "prepaid", "service-area", "trai", "reference-table"], ["telecom-demo", "pricing", "customer-segmentation"],
        extra={"quarter_ending": "2026-06-30"},
    )


def build_dth_by_operator(q: Source) -> dict:
    counts = {"tata-play": 14839575, "bharti-telemedia": 13581317, "sun-direct": 10932020, "dish-tv": 9205100}
    if sum(counts.values()) != 48558012:
        raise ValueError("DTH counts do not match the published total")
    return marginal(
        "in-pay-dth-subscribers-by-operator-2026q2",
        "India pay DTH active subscribers by operator, 30 June 2026 (TRAI)",
        "telecom", "dth_operator", counts, "active subscribers", ("2026-06-30", "2026-06-30"),
        [
            item(q, "PDF page 124 (Table 5.7), row 1", "14,839,575", "count", "Tata Play Ltd. 14,839,575"),
            item(q, "PDF page 124 (Table 5.7), row 2", "13,581,317", "count", "Bharti Telemedia Ltd. 13,581,317"),
            item(q, "PDF page 124 (Table 5.7), row 3", "10,932,020", "count", "Sun Direct TV Pvt. Ltd. 10,932,020"),
            item(q, "PDF page 124 (Table 5.7), row 4 and total", "48,558,012", "count", "Dish TV India Ltd. 9,205,100 Total 48,558,012"),
        ],
        "Total active subscriber base of the four pay direct-to-home operators as reported to TRAI for 30 June 2026 (Table 5.7 of the "
        "performance indicators report). DD Free Dish subscribers are not included. Shares are counts divided by the 48,558,012 total. " + TRAI_NOTE,
        ["telecom", "broadcasting", "dth", "market-share", "trai"], ["telecom-demo", "market-sizing", "customer-segmentation"],
    )


# --- IRDAI ---------------------------------------------------------------------------------------


def build_registered_insurers(ar: Source) -> dict:
    rows = {
        "life": {"public_sector": 1, "private_sector": 25, "total": 26},
        "general": {"public_sector": 4, "private_sector": 21, "total": 25},
        "specialized": {"public_sector": 2, "private_sector": 0, "total": 2},
        "health": {"public_sector": 0, "private_sector": 8, "total": 8},
        "reinsurer": {"public_sector": 1, "private_sector": 12, "total": 13},
        "total": {"public_sector": 8, "private_sector": 66, "total": 74},
    }
    return lookup(
        "in-registered-insurers-by-type-2025-03",
        "India registered insurers and reinsurers by type and ownership, 31 March 2025 (IRDAI)",
        "insurance", rows, "2025-03-31", None,
        [
            {"input": {"key": "life", "column": "total"}, "expected": 26, "origin": "source"},
            {"input": {"key": "health", "column": "private_sector"}, "expected": 8, "origin": "source"},
            {"input": {"key": "total", "column": "total"}, "expected": 74, "origin": "source"},
        ],
        [{"statistic": "value[general,public_sector]", "expected": 4, "tolerance": 0}],
        [
            item(ar, "PDF page 257 (printed page 25), Table I.18, row Life", "26", "integer", "Life 1 25 26"),
            item(ar, "PDF page 257, Table I.18, row General", "25", "integer", "General 4 21 25"),
            item(ar, "PDF page 257, Table I.18, rows Specialized, Health and Reinsurer", "13", "integer", "Specialized 2 - 2 Health - 8 8 Reinsurer 1 12 13"),
            item(ar, "PDF page 257, Table I.18, row Total", "74", "integer", "Total 8 66 74"),
            item(ar, "PDF page 257, paragraph I.3.1", "74", "integer", "the total number of registered insurers and reinsurers is 74"),
        ],
        "Number of registered insurers and reinsurers in India as at 31 March 2025 from Table I.18 of the IRDAI Annual Report 2024-25, "
        "by type (life, general, specialized, stand-alone health, reinsurer) and ownership. The table's own note says the count "
        "includes Reliance Health Insurance (directed to stop selling new policies in 2019) and Sahara India Life (business "
        "transferred to SBI Life in 2023); the narrative in paragraph I.3.1 groups the two specialized insurers with general "
        "insurers (27). " + IRDAI_NOTE,
        ["insurance", "insurers", "regulator", "irdai", "reference-table"], ["insurance", "company-generation", "market-sizing"],
    )


def build_death_claims(ar: Source) -> dict:
    shares = {"paid": 0.9782, "repudiated": 0.0101, "rejected": 0.0066, "unclaimed": 0.0002, "pending_at_year_end": 0.0048}
    counts = {"paid": 1011880, "repudiated": 10494, "rejected": 6839, "unclaimed": 243, "pending_at_year_end": 4999}
    return marginal(
        "in-life-insurance-individual-death-claims-outcomes-2024-25",
        "India life insurance individual death claims by outcome (paid, repudiated, rejected, unclaimed, pending), FY 2024-25 (IRDAI)",
        "insurance", "claim_outcome", counts, "policies", ("2024-04-01", "2025-03-31"),
        [
            item(ar, "PDF page 250 (printed page 18), Table I.11, Individual Business, number of policies", "10,11,880", "count", "Individual Number of Policies 10,34,455 10,11,880 10,494 6,839 243 4,999"),
            item(ar, "PDF page 250, Table I.11, Individual Business, per cent", "97.82", "percent", "Business In Per cent 100 97.82 1.01 0.66 0.02 0.48"),
            item(ar, "PDF page 250, Table I.11, Group Business, number of lives", "16,28,641", "count", "Group Number of Lives 16,33,833 16,28,641 3,880 275 - 1,037"),
        ],
        "Outcome of individual-business death claims handled by Indian life insurers in FY 2024-25 from Table I.11 of the IRDAI Annual "
        "Report 2024-25: of 10,34,455 claims (Indian digit grouping, 1,034,455), the shares paid, repudiated (section 45 of the "
        "Insurance Act), rejected on policy terms, unclaimed and pending at year end are the published percentages divided by 100 "
        "(they sum to 0.9999). The policy counts and the group-business figures (16,33,833 lives, 99.68% paid) are kept in parameters. "
        "Sahara India Life is excluded by the source. " + IRDAI_NOTE,
        ["insurance", "life-insurance", "claims", "irdai"], ["insurance", "claims-generation"],
        shares=shares,
        assumed=[{"parameter": "distribution.parameters.shares", "value": "published percentage / 100", "method": "derived", "rationale": "Table I.11 prints each outcome as a percentage of total claims; the ratios are those percentages divided by 100."}],
        extra={"total_individual_claims": 1034455, "group_business": {"total_lives": 1633833, "paid": 1628641, "repudiated": 3880, "rejected": 275, "pending_at_year_end": 1037, "paid_percent": 99.68}},
    )


def build_life_premium_by_segment(ar: Source) -> dict:
    counts = {"life": 715056.32, "pension": 128238.32, "annuity": 38926.48, "others": 2645.19, "health": 905.42}
    if round(sum(counts.values()), 2) != 885771.73:
        raise ValueError("life premium segments do not add up")
    return marginal(
        "in-life-insurance-premium-by-segment-2024-25",
        "India life insurers' total premium by segment (life, pension, annuity, health, others), FY 2024-25 (IRDAI)",
        "insurance", "premium_segment", counts, "INR crore", ("2024-04-01", "2025-03-31"),
        [
            item(ar, "PDF page 247 (printed page 15), Table I.9, row 4(c) Life, 2024-25 total", "7,15,056.32", "currency:INR", "4(c) Life 1,06,459.45 5,56,474.15 6,62,933.60 1,42,519.40 5,72,536.92 7,15,056.32"),
            item(ar, "PDF page 247, Table I.9, row 4(d) Pension, 2024-25 total", "1,28,238.32", "currency:INR", "4(d) Pension 14,878.13 1,12,566.13 1,27,444.26 16,214.90 1,12,023.41 1,28,238.32"),
            item(ar, "PDF page 247, Table I.9, row 4(a) Annuity, 2024-25 total", "38,926.48", "currency:INR", "4(a) Annuity - 36,378.09 36,378.09 - 38,926.48 38,926.48"),
            item(ar, "PDF page 247, Table I.9, rows 4(b) Health and 4(e) Others, 2024-25 totals", "905.42", "currency:INR", "4(b) Health 132.22 551.54 683.76 403.29 502.13 905.42"),
            item(ar, "PDF page 247, Table I.9, row 4(f) Total, 2024-25", "8,85,771.73", "currency:INR", "4(f) Total 1,21,469.80 7,08,459.66 8,29,929.46 1,59,137.60 7,26,634.13 8,85,771.73"),
        ],
        "Segment-wise total premium underwritten by Indian life insurers in FY 2024-25 (linked plus non-linked) from Table I.9 of the "
        "IRDAI Annual Report 2024-25, in INR crore with Indian digit grouping in the source (7,15,056.32 crore = 715,056.32 crore). "
        "Shares are each segment divided by the 8,85,771.73 crore total. " + IRDAI_NOTE,
        ["insurance", "life-insurance", "premium", "product-mix", "irdai"], ["insurance", "financial-reporting", "market-sizing"],
    )


def build_motor_tp_market_share(ar: Source) -> dict:
    page = ar.pages[393]
    shares: dict[str, float] = {}
    gdp: dict[str, str] = {}
    for line in page.splitlines():
        match = re.match(r"^\d+\.\s+(.+?)\s+([\d, ]+)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s*$", line)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            shares[slug] = round(float(match.group(3)) / 100, 4)
            gdp[slug] = match.group(2).strip()
    if len(shares) != 25:
        raise ValueError(f"motor TP table parse found {len(shares)} insurers")
    counts = {k: round(v * 100, 2) for k, v in shares.items()}
    return marginal(
        "in-motor-third-party-premium-market-share-by-insurer-2024-25",
        "India motor third-party insurance market share by general insurer, FY 2024-25 (IRDAI, 25 insurers)",
        "insurance", "insurer", counts, "percent of motor TP gross direct premium", ("2024-04-01", "2025-03-31"),
        [
            item(ar, "PDF page 394 (printed page 162), Annexure 3, row 23", "11.28", "percent", "The New India Assurance Co. Ltd. 6,652 11.28 5.00"),
            item(ar, "PDF page 394, Annexure 3, row 7", "8.96", "percent", "ICICI Lombard General Insurance Co. Ltd. 5,282 8.96 7.50"),
            item(ar, "PDF page 394, Annexure 3, row 18", "8.50", "percent", "Tata AIG General Insurance Co. Ltd. 5,012 8.50 7.50"),
            item(ar, "PDF page 394, Annexure 3, row 9", "0.00", "percent", "Kshema General Insurance Ltd. 0 0.00 12.50"),
            item(ar, "PDF page 394, Annexure 3, grand total", "58,958", "currency:INR", "Grand total 58,958 100"),
        ],
        "Market share of each general insurer in motor third-party gross direct premium for FY 2024-25 from Annexure 3 of the IRDAI "
        "Annual Report 2024-25, the table IRDAI uses to set motor TP obligations for FY 2025-26 (premium total 58,958 crore). Shares "
        "are the published percentages divided by 100; the premium column in crore is kept in parameters exactly as pypdf reads it, "
        "and four cells there (Magma, Royal Sundaram, Universal Sompo, Oriental) are split by a stray space in the extracted text. "
        "Kshema General Insurance has a zero share. " + IRDAI_NOTE,
        ["insurance", "motor-insurance", "third-party", "market-share", "irdai"], ["insurance", "automotive-demo", "market-sizing", "company-generation"],
        shares=shares,
        assumed=[{"parameter": "distribution.parameters.shares", "value": "published market share / 100", "method": "derived", "rationale": "Annexure 3 prints each insurer's share of motor TP gross direct premium to two decimals; the ratios are those percentages divided by 100."}],
        extra={"gross_direct_premium_crore_as_printed": gdp, "total_gross_direct_premium_crore": 58958},
    )


def build_motor_premium_by_insurer(mt: Source) -> dict:
    rows: dict[str, dict] = {}
    for line in mt.pages[0].splitlines():
        match = re.search(r"([A-Za-z][A-Za-z .&]*?)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s*$", line)
        if match and "Total" not in match.group(1):
            name = match.group(1).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            rows[slug] = {"insurer": name, "motor_own_damage_crore": number(match.group(2)), "motor_third_party_crore": number(match.group(3)), "total_motor_crore": number(match.group(4)), "total_gross_direct_premium_crore": number(match.group(5))}
    if len(rows) != 24:
        raise ValueError(f"motor premium parse found {sorted(rows)}")
    totals = {c: round(sum(r[c] for r in rows.values()), 2) for c in ("motor_own_damage_crore", "motor_third_party_crore", "total_motor_crore", "total_gross_direct_premium_crore")}
    if totals["motor_third_party_crore"] != 49497.03 or totals["total_gross_direct_premium_crore"] != 214833.09:
        raise ValueError(f"motor premium totals differ from the published grand total: {totals}")
    return lookup(
        "in-motor-insurance-gross-direct-premium-by-insurer-2022-23",
        "India motor own-damage, motor third-party and total gross direct premium by general insurer, FY 2022-23 (IRDAI audited figures)",
        "insurance", rows, "2022-04-01", "2023-03-31",
        [
            {"input": {"key": "new-india", "column": "motor_third_party_crore"}, "expected": 5821.70, "origin": "source"},
            {"input": {"key": "icici-lombard", "column": "total_gross_direct_premium_crore"}, "expected": 21025.09, "origin": "source"},
            {"input": {"key": "acko", "column": "motor_own_damage_crore"}, "expected": 215.66, "origin": "source"},
        ],
        [{"statistic": "max[motor_third_party_crore]", "expected": 5821.70, "tolerance": 0}, {"statistic": "min[total_gross_direct_premium_crore]", "expected": 70.59, "tolerance": 0}],
        [
            item(mt, "page 1, row New India", "5,821.70", "currency:INR", "New India 3,152.90 5,821.70 8,974.60 34,484.10"),
            item(mt, "page 1, row ICICI Lombard", "21,025.09", "currency:INR", "ICICI Lombard 4,151.38 4,430.89 8,582.27 21,025.09"),
            item(mt, "page 1, row Acko", "215.66", "currency:INR", "Acko 215.66 444.30 659.96 1,509.41"),
            item(mt, "page 1, row Grand Total", "49,497.03", "currency:INR", "Grand Total 31,782.95 49,497.03 81,279.98 2,14,833.09"),
            item(mt, "page 1, title", "FY 2023-24", "text", "DATA FOR CALCULATION OF MOTOR TP OBLIGATION FOR FY 2023-24 (AUDITED FIGS.)"),
        ],
        "Audited FY 2022-23 gross direct premium (INR crore) of 24 general insurers split into motor own damage, motor third party, "
        "total motor and total premium, published by IRDAI as the basis for FY 2023-24 motor third-party obligations. Rows are keyed "
        "by the insurer's short name as printed; the parsed columns reproduce the printed grand totals (31,782.95 / 49,497.03 / "
        "81,279.98 / 2,14,833.09, the last in Indian digit grouping). A more recent market-share table for FY 2024-25 is carried in "
        "a separate entry from the IRDAI annual report. " + IRDAI_NOTE,
        ["insurance", "motor-insurance", "premium", "irdai", "reference-table"], ["insurance", "automotive-demo", "company-generation", "financial-reporting"],
        extra={"financial_year": "2022-23", "unit": "currency:INR crore", "column_totals": totals},
    )


# --- PFRDA -----------------------------------------------------------------------------------------


def build_nps_intermediaries(hb: Source) -> dict:
    funds = {
        "aditya-birla-pf": "Aditya Birla Sun life Pension Management Limited",
        "axis-pf": "Axis Pension Fund",
        "dsp-pf": "DSP Pension Fund Managers Private Limited",
        "hdfc-pf": "HDFC Pension Management Company Limited",
        "icici-pf": "ICICI Prudential Pension Funds Management Company Limited",
        "kotak-pf": "Kotak Mahindra Pension Fund Limited",
        "lic-pf": "LIC Pension Fund Limited",
        "max-life-pf": "Max Life Pension Fund Management Limited",
        "sbi-pf": "SBI Pension Funds Private Limited",
        "tata-pf": "TATA Pension Management Limited",
        "uti-pf": "UTI Retirement Solution Limited",
    }
    cras = {"pcra": "Protean eGov Technologies Limited", "kfin": "KFin Technologies Limited", "cams": "Computer Age Management Services Limited"}
    rows = {**{k: {"name": v, "role": "pension_fund"} for k, v in funds.items()}, **{k: {"name": v, "role": "central_recordkeeping_agency"} for k, v in cras.items()}}
    return lookup(
        "in-nps-pension-funds-and-recordkeeping-agencies-2025-03",
        "India National Pension System pension funds and central recordkeeping agencies registered with PFRDA, 31 March 2025",
        "pensions", rows, "2025-03-31", None,
        [
            {"input": {"key": "sbi-pf", "column": "name"}, "expected": funds["sbi-pf"], "origin": "source"},
            {"input": {"key": "cams", "column": "role"}, "expected": "central_recordkeeping_agency", "origin": "source"},
            {"input": {"key": "hdfc-pf", "column": "role"}, "expected": "pension_fund", "origin": "source"},
        ],
        [],
        [
            item(hb, "PDF page 6, Table 2 (list of pension funds), row SBI PF", "SBI Pension Funds Private Limited", "text", "SBI PF SBI Pension Funds Private Limited"),
            item(hb, "PDF page 6, Table 2, row UTI PF and caption", "UTI Retirement Solution Limited", "text", "Table 2: List of Pension Funds registered with PFRDA as on 31st March 2025"),
            item(hb, "PDF page 6, Table 3 (list of CRAs), row CAMS and caption", "Computer Age Management Services Limited", "text", "Table 3: List of CRAs registered with PFRDA as on 31st March 2025"),
            item(hb, "PDF page 18, Overview of NPS Architecture, paragraph (c)", "Ten Pension Fund Managers", "text", "Ten Pension Fund Managers are registered with PFRDA."),
            item(hb, "PDF page 19, paragraph (f)", "fifteen ASPs", "text", "Currently, there are fifteen ASPs registered with PFRDA.", role="supporting"),
        ],
        "The pension fund managers (Table 2) and central recordkeeping agencies (Table 3) registered with PFRDA as on 31 March 2025, "
        "from the Handbook of National Pension System Statistics 2025, keyed by the handbook's own acronyms. Table 2 lists eleven "
        "pension funds while the architecture overview on page 18 says ten are registered; both statements are in the same "
        "document and the discrepancy is left for the reader. The handbook names Axis Bank as NPS Trustee Bank and says fifteen "
        "annuity service providers are registered. PFRDA states no licence for the handbook, so the entry stays at license-review.",
        ["pensions", "nps", "pension-funds", "pfrda", "reference-table"], ["pensions", "financial-planning", "company-generation"],
        extra={"trustee_bank": "Axis Bank Ltd.", "annuity_service_providers_registered": 15},
    )


# --- IBBI ------------------------------------------------------------------------------------------


def build_cirp_status(nl: Source) -> dict:
    counts = {"withdrawn_under_section_12a": 1333, "closed_on_appeal_review_or_settled": 1410, "resolution_plan_approved": 1484, "liquidation_ordered": 3074, "ongoing": 1865}
    if sum(counts.values()) != 9166:
        raise ValueError("CIRP status counts do not add up to admitted CIRPs")
    return marginal(
        "in-cirp-status-2026-06",
        "India corporate insolvency resolution processes by status (withdrawn, settled, resolved, liquidated, ongoing), cumulative to 30 June 2026 (IBBI)",
        "company", "cirp_status", counts, "CIRPs", ("2016-12-01", "2026-06-30"),
        [
            item(nl, "sheet Table 1, row Admitted", "9166", "count", "Table 1: Details of CIRP cases as on June 30, 2026"),
            item(nl, "sheet Table 1, row Withdrawn under section 12A", "1333", "count", "Withdrawn under section 12A"),
            item(nl, "sheet Table 1, row Resolution plans approved", "1484", "count", "Resolution plans approved"),
            item(nl, "sheet Table 1, row Liquidation orders passed", "3074", "count", "Liquidation orders passed"),
            item(nl, "sheet Table 1, row Ongoing CIRP cases", "1865", "count", "Ongoing CIRP cases"),
        ],
        "Status of the 9,166 corporate insolvency resolution processes admitted under the Insolvency and Bankruptcy Code from its "
        "commencement to 30 June 2026, from Table 1 of the data workbook behind IBBI's quarterly newsletter for April-June 2026: "
        "closed by withdrawal under section 12A, closed on appeal, review or settlement, closed by an approved resolution plan, "
        "closed by a liquidation order, or still ongoing. Shares are counts divided by 9,166. The workbook is an .xlsx file, so the "
        "entry is tier A; IBBI states no licence, so it stays at license-review.",
        ["insolvency", "cirp", "ibc", "corporate-distress", "ibbi"], ["company-generation", "credit-risk", "collections", "kyb-onboarding"],
        tier="A",
    )


def build_cirp_by_sector(nl: Source) -> dict:
    counts = {"manufacturing": 3342, "real-estate-renting-and-business-activities": 1996, "construction": 1129, "wholesale-and-retail-trade": 910, "hotels-and-restaurants": 182, "electricity-and-others": 246, "transport-storage-and-communications": 256, "others": 1105}
    if sum(counts.values()) != 9166:
        raise ValueError("sector counts do not add up to admitted CIRPs")
    return marginal(
        "in-cirp-admitted-by-sector-2026-06",
        "India corporate insolvency resolution processes admitted by sector of the corporate debtor, cumulative to 30 June 2026 (IBBI)",
        "company", "sector", counts, "CIRPs admitted", ("2016-12-01", "2026-06-30"),
        [
            item(nl, "sheet Table 3, row Manufacturing, column Admitted", "3342", "count", "Table 3: Sectoral Distribution of CIRPs as on June 30, 2026"),
            item(nl, "sheet Table 3, row Construction, column Admitted", "1129", "count", "Construction"),
            item(nl, "sheet Table 3, row Hotels, column Admitted", "182", "count", "Hotels"),
            item(nl, "sheet Table 3, row Total, column Admitted", "9166", "count", "Total"),
        ],
        "Sector of the corporate debtor for the 9,166 CIRPs admitted up to 30 June 2026, from Table 3 of IBBI's April-June 2026 "
        "newsletter workbook. Only the eight top-level sector groups are used; the workbook also splits manufacturing and real "
        "estate/business activities into sub-sectors. IBBI bases the classification on the debtor's corporate identification "
        "number. Shares are counts divided by 9,166. Tier A (.xlsx); no licence stated, so license-review.",
        ["insolvency", "cirp", "sector", "ibc", "ibbi"], ["company-generation", "credit-risk", "customer-segmentation"],
        tier="A",
    )


def build_cirp_outcomes_by_initiator(nl: Source) -> dict:
    rows = {
        "financial_creditors": {"appeal_review_settled": 466, "withdrawal_section_12a": 429, "resolution_plan_approved": 934, "liquidation_commenced": 1469, "ongoing": 1134, "total": 4432, "realisation_percent_of_liquidation_value": 177.52, "realisation_percent_of_claims": 30.58, "average_days_to_closure_of_cirp": 765},
        "operational_creditors": {"appeal_review_settled": 930, "withdrawal_section_12a": 893, "resolution_plan_approved": 452, "liquidation_commenced": 1271, "ongoing": 616, "total": 4162, "realisation_percent_of_liquidation_value": 148.82, "realisation_percent_of_claims": 24.78, "average_days_to_closure_of_cirp": 766},
        "corporate_debtors": {"appeal_review_settled": 14, "withdrawal_section_12a": 11, "resolution_plan_approved": 94, "liquidation_commenced": 334, "ongoing": 114, "total": 567, "realisation_percent_of_liquidation_value": 147.19, "realisation_percent_of_claims": 17.99, "average_days_to_closure_of_cirp": 632},
        "financial_service_providers": {"appeal_review_settled": 0, "withdrawal_section_12a": 0, "resolution_plan_approved": 4, "liquidation_commenced": 0, "ongoing": 1, "total": 5, "realisation_percent_of_liquidation_value": 134.94, "realisation_percent_of_claims": 41.41, "average_days_to_closure_of_cirp": 677},
        "total": {"appeal_review_settled": 1410, "withdrawal_section_12a": 1333, "resolution_plan_approved": 1484, "liquidation_commenced": 3074, "ongoing": 1865, "total": 9166, "realisation_percent_of_liquidation_value": 166.58, "realisation_percent_of_claims": 30.52, "average_days_to_closure_of_cirp": 757},
    }
    for key, row in rows.items():
        if sum(row[c] for c in ("appeal_review_settled", "withdrawal_section_12a", "resolution_plan_approved", "liquidation_commenced", "ongoing")) != row["total"]:
            raise ValueError(f"row {key} does not add up")
    return lookup(
        "in-cirp-outcomes-by-initiator-2026-06",
        "India CIRP outcomes and creditor realisation by who initiated the process (financial creditors, operational creditors, corporate debtors), cumulative to 30 June 2026 (IBBI)",
        "company", rows, "2026-06-30", None,
        [
            {"input": {"key": "financial_creditors", "column": "resolution_plan_approved"}, "expected": 934, "origin": "source"},
            {"input": {"key": "operational_creditors", "column": "total"}, "expected": 4162, "origin": "source"},
            {"input": {"key": "total", "column": "realisation_percent_of_claims"}, "expected": 30.52, "origin": "source"},
        ],
        [{"statistic": "value[corporate_debtors,liquidation_commenced]", "expected": 334, "tolerance": 0}, {"statistic": "max[average_days_to_closure_of_cirp]", "expected": 766, "tolerance": 0}],
        [
            item(nl, "sheet Table 4, row Closure by Approval of Resolution Plan", "934", "count", "Outcome of CIRPs initiated Stakeholder-wise"),
            item(nl, "sheet Table 4, row Total", "4432", "count", "CIRPs initiated by"),
            item(nl, "sheet Table 4, row Realisation by creditors as % of their Claims, Total column", "30.52", "percent", "Realisation by creditors as % of their Claims"),
            item(nl, "sheet Table 4, row Average time taken for Closure of CIRP, Total column", "757", "integer", "Average time taken for Closure of CIRP"),
        ],
        "Outcome of the 9,166 CIRPs admitted up to 30 June 2026 by the class of applicant that initiated them, from Table 4 of IBBI's "
        "April-June 2026 newsletter workbook, with the realisation by creditors in resolved cases as a percentage of liquidation "
        "value and of admitted claims, and the average days from commencement to closure. Rows are keyed by initiator; 'total' "
        "is the all-India row. Tier A (.xlsx); no licence stated, so license-review.",
        ["insolvency", "cirp", "recovery", "ibc", "ibbi", "reference-table"], ["credit-risk", "collections", "company-generation", "loan-pricing"],
        tier="A", extra={"as_on": "2026-06-30"},
    )


def build_cirp_annual(nl: Source) -> dict:
    data = [
        ("2016-17", 0, 37, 1, 0, 0, 0, 36),
        ("2017-18", 36, 707, 96, 0, 18, 91, 538),
        ("2018-19", 538, 1157, 162, 97, 73, 305, 1058),
        ("2019-20", 1058, 1992, 349, 221, 130, 537, 1813),
        ("2020-21", 1813, 538, 92, 168, 119, 348, 1624),
        ("2021-22", 1624, 892, 131, 204, 141, 339, 1701),
        ("2022-23", 1701, 1262, 196, 231, 186, 405, 1945),
        ("2023-24", 1945, 1002, 165, 168, 257, 441, 1916),
        ("2024-25", 1916, 734, 126, 89, 257, 293, 1885),
        ("2025-26", 1885, 668, 82, 132, 234, 261, 1844),
    ]
    series = []
    for fy, opening, admitted, settled, withdrawn, resolved, liquidated, closing in data:
        if opening + admitted - settled - withdrawn - resolved - liquidated != closing:
            raise ValueError(f"CIRP flow for {fy} does not balance")
        series.append({"period": fy, "value": admitted, "cirps_at_start": opening, "closed_appeal_review_settled": settled, "closed_withdrawal_section_12a": withdrawn, "closed_resolution_plan_approved": resolved, "closed_liquidation_commenced": liquidated, "cirps_at_end": closing})
    return temporal(
        "in-cirp-admissions-and-closures-annual-2016-17-to-2025-26",
        "India corporate insolvency resolution processes admitted and closed per financial year, 2016-17 to 2025-26 (IBBI)",
        "company", "cirps_admitted", "count", "annual", series, ["cirps_at_start", "closed_appeal_review_settled", "closed_withdrawal_section_12a", "closed_resolution_plan_approved", "closed_liquidation_commenced", "cirps_at_end"], ("2016-04-01", "2026-03-31"),
        [
            item(nl, "sheet Table 2, row 2019 - 20, column Admitted", "1992", "count", "Table 2: Corporate Insolvency Resolution Process"),
            item(nl, "sheet Table 2, row 2025-26, column Admitted", "668", "count", "CIRPs at the beginning of the Period"),
            item(nl, "sheet Table 2, row 2017 - 18, column Commencement of Liquidation", "91", "count", "Commencement of Liquidation"),
            item(nl, "sheet Table 2, row Total, column Admitted", "9166", "count", "CIRPs at the end of the Period"),
        ],
        "Flow of corporate insolvency resolution processes per Indian financial year (April to March) from Table 2 of IBBI's "
        "April-June 2026 newsletter workbook: CIRPs open at the start, admitted during the year (the series value), closed by "
        "appeal/review/settlement, by withdrawal under section 12A, by approval of a resolution plan or by commencement of "
        "liquidation, and open at the end. 2016-17 covers December 2016 to March 2017; the April-June 2026 quarter in the source "
        "is omitted as a partial year. Each year's flows balance. Tier A (.xlsx); no licence stated, so license-review.",
        ["insolvency", "cirp", "annual", "time-series", "ibc", "ibbi"], ["credit-risk", "company-generation", "demand-forecasting"],
        tier="A",
    )


def main() -> None:
    pr = source(TRAI, PR_SEP_2026_TITLE, PR_SEP_2026)
    qpir = source(TRAI, QPIR_TITLE, QPIR)
    ar = source(IRDAI, IRDAI_ANNUAL_REPORT_TITLE, IRDAI_ANNUAL_REPORT)
    mt = source(IRDAI, IRDAI_MOTOR_TP_TITLE, IRDAI_MOTOR_TP)
    hb = source(PFRDA, PFRDA_HANDBOOK_TITLE, PFRDA_HANDBOOK)
    nl = source(IBBI, IBBI_NEWSLETTER_TITLE, IBBI_NEWSLETTER)
    for entry in (
        build_subscribers_and_teledensity(pr),
        build_connection_types(pr),
        build_broadband_by_provider(pr),
        build_wireless_by_operator(pr),
        build_wireless_by_service_area(pr),
        build_mnp_by_service_area(pr),
        build_monthly_wireless_2025(),
        build_qpir_indicators(qpir),
        build_prepaid_postpaid(qpir),
        build_arpu_composition(qpir),
        build_quarterly_indicators(qpir),
        build_service_area_revenue_usage(qpir),
        build_dth_by_operator(qpir),
        build_registered_insurers(ar),
        build_death_claims(ar),
        build_life_premium_by_segment(ar),
        build_motor_tp_market_share(ar),
        build_motor_premium_by_insurer(mt),
        build_nps_intermediaries(hb),
        build_cirp_status(nl),
        build_cirp_by_sector(nl),
        build_cirp_outcomes_by_initiator(nl),
        build_cirp_annual(nl),
    ):
        write(entry)


if __name__ == "__main__":
    main()

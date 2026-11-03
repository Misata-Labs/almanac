"""Regenerate the US healthcare value pools behind synthetic claims, EHR, payer and pharma data.

The entries cover the MS-DRG relative weights and lengths of stay, Medicare
inpatient, outpatient, physician and drug utilisation and spending, the HCPCS
Level II code sections, physician fee schedule RVUs for office visits, the
Hospital Readmissions Reduction Program and hospital-acquired condition
results, Medicare enrolment, Medicare-enrolled hospitals, the FDA drug
directory, recall and Orange Book mixes, CDC births and leading causes of
death, and the HCUP inpatient and emergency department cost tables. Every
number is read from the fetched resource; shares, sums and rankings are
declared as derived. Run from the repository root:

    uv run python tools/build_ushealth.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

CMS = "Centers for Medicare & Medicaid Services"
FDA = "U.S. Food and Drug Administration"
CDC = "Centers for Disease Control and Prevention, National Center for Health Statistics"
AHRQ = "Agency for Healthcare Research and Quality"
UNSTATED = "unstated"
CC0 = "CC0-1.0"

CMS_API = "https://data.cms.gov/data-api/v1/dataset"
URLS = {
    "table5": "https://www.cms.gov/files/zip/fy2026-ipps-fr-table-5.zip",
    "inp_geo": "https://data.cms.gov/sites/default/files/2026-04/4517a6a1-adeb-4345-9f3d-a95391a470db/MUP_INP_RY26_P03_V10_DY24_Geo.CSV",
    "inp_prv": "https://data.cms.gov/sites/default/files/2026-04/d9525c59-002b-45b3-af22-c81061a62dcd/mup_inp_ry26_p04_v10_dy24_prv.csv",
    "out_geo": "https://data.cms.gov/sites/default/files/2026-06/32491150-3e8f-4feb-95e4-3f66a355951a/MUP_OUT_RY26_P04_V10_DY24_Geo.csv",
    "hcpcs": "https://www.cms.gov/files/zip/october-2026-alpha-numeric-hcpcs-file.zip",
    "rvu": "https://www.cms.gov/files/zip/rvu26d-updated-08-26-2026.zip",
    "part_d": "https://data.cms.gov/sites/default/files/2026-06/98218f98-166c-4723-8438-c344a4ef96a6/DSD_PTD_RY26_P04_V10_DY24_BGM.csv",
    "part_b": "https://data.cms.gov/sites/default/files/2026-06/6616fc91-eb70-404c-9f27-1448e47a3a73/DSD_PTB_RY26_P06_V10_DYT24_HCPCS-%20260602.csv",
    "hrrp": "https://www.cms.gov/files/zip/fy2026-hospital-readmissions-reduction-program-supplemental-data-file.zip",
    "hosp_enr": "https://data.cms.gov/sites/default/files/2026-10/961708ac-2136-43cb-9587-ac64af23b6ab/Hospital_Enrollments_2026.09.29.csv",
    "hosp_dict": "https://data.cms.gov/sites/default/files/2026-07/Hospital_Enrollments_Data_Dictionary.pdf",
    "enrollment": f"{CMS_API}/d7fabe1e-d19b-4333-9eff-e80e0643f2fd/data?filter%5BYEAR%5D=2026&filter%5BMONTH%5D=July&filter%5BBENE_COUNTY_DESC%5D=Total&size=500",
    "orange_book": "https://www.fda.gov/media/76860/download",
    "fda_license": "https://open.fda.gov/license/",
    "hcup_sb316": "https://hcup-us.ahrq.gov/reports/statbriefs/sb316-most-expensive-conditions-by-payer-2022.pdf",
    "hcup_sb311": "https://hcup-us.ahrq.gov/reports/statbriefs/sb311-ED-visit-costs-2021.pdf",
}
PHYSICIAN_PAGES = [f"{CMS_API}/6fea9d79-0129-4e4c-b1b8-23cd86a4f435/data?filter%5BRndrng_Prvdr_Geo_Lvl%5D=National&size=5000&offset={offset}" for offset in (0, 5000, 10000)]
HAC_PAGES = [f"{CMS_API}/01edb62e-5c45-4f43-8c91-16cba21cbb74/data?size=5000&offset={offset}" for offset in (0, 5000, 10000)]
OPENFDA = "https://api.fda.gov/drug"
CDC_RESOURCE = "https://data.cdc.gov/resource"

CMS_NOTE = " data.cms.gov and cms.gov publish these files without a licence statement, so the entry is held at license-review."
OPENFDA_NOTE = " openFDA states that its data is public domain under a CC0 1.0 Universal dedication (supporting evidence)."
RECALL_WINDOW = ("2012-01-01", "2025-12-31")
RECALL_SEARCH = f"search=report_date:%5B{RECALL_WINDOW[0].replace('-', '')}+TO+{RECALL_WINDOW[1].replace('-', '')}%5D"
RECALL_FIELDS = {"classification": "classification.exact", "report_date": "report_date"}
OPENFDA_REFRESH_NOTE = (
    " The query is pinned to enforcement reports dated in a closed window, but openFDA refreshes the endpoint weekly and"
    " every response carries the refresh date in meta.last_updated, so the content hash moves with each refresh and"
    " late-classified reports can still shift the counts: re-indexed weekly; rebuild before release."
)
CDC_NOTE = (
    " data.cdc.gov labels these datasets Public Domain U.S. Government only in view metadata that carries live view and"
    " download counters, so the statement cannot be pinned by a content hash and the licence is recorded as unstated."
)
USE_CASES = ["healthcare-demo", "claims-test-data", "payer-demo"]
PHARMA_USE_CASES = ["healthcare-demo", "pharma-demo", "claims-test-data"]

_TEXT_CACHE: dict[str, str] = {}


def collapse(text: str) -> str:
    return " ".join(text.split())


def text_of(raw: bytes) -> str:
    """The resource as the verifier will search it: PDF text, ZIP text members or decoded bytes, whitespace collapsed."""
    key = hashlib.sha256(raw).hexdigest()
    if key not in _TEXT_CACHE:
        _TEXT_CACHE[key] = collapse(Resource(url="", content=raw, content_type="").text)
    return _TEXT_CACHE[key]


def cite(publisher: str, title: str, url: str, locator: str, value: Any, unit: str, snippet: str, license_id: str, raw: bytes, role: str = "primary") -> dict:
    """Build an evidence item after confirming the snippet and value are present in the fetched bytes."""
    text = text_of(raw)
    shown = ("true" if value else "false") if isinstance(value, bool) else str(value)
    for needle in (snippet, shown):
        if collapse(needle) not in text:
            raise ValueError(f"{url}: {needle!r} not found in resource")
    if len(snippet.split()) > 24:
        raise ValueError(f"snippet too long: {snippet!r}")
    return evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role=role)


def stat(name: str, *args: str) -> str:
    """Format a test statistic, quoting arguments that carry commas or brackets."""
    quoted = [f'"{a}"' if any(ch in a for ch in ',[]') else a for a in args]
    return f"{name}[{','.join(quoted)}]" if args else name


def rows_of(raw: bytes, encoding: str = "utf-8-sig", delimiter: str = ",") -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode(encoding, errors="replace")), delimiter=delimiter))


def member(raw: bytes, name: str) -> bytes:
    return zipfile.ZipFile(io.BytesIO(raw)).read(name)


def pdf_lines(raw: bytes) -> list[str]:
    return [collapse(line) for line in Resource(url="", content=raw, content_type="").text.splitlines()]


def marginal(entry_id: str, title: str, variable: str, counts: dict[str, int], period: tuple[str, str], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str], status: str, tier: str = "A", count_label: str = "counts") -> dict:
    total = sum(counts.values())
    shares = {k: round(v / total, 6) for k, v in counts.items()}
    leading = sorted(counts, key=lambda k: -counts[k])[:3]
    return {
        "id": entry_id,
        "title": title,
        "kind": "marginal",
        "domain": "healthcare",
        "region": "US",
        "status": status,
        "tier": tier,
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, count_label: counts, "total": total}}},
        "evidence": items,
        "assumed": assumed + [{"parameter": "distribution.parameters.shares", "value": f"{count_label} / total", "method": "derived", "rationale": "Shares are each category's count over the sum of all categories in the table."}],
        "tests": [{"statistic": stat("share", k), "expected": shares[k], "tolerance": 0.004} for k in leading] + [{"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4}],
        "notes": notes,
    }


def lookup(entry_id: str, title: str, rows: dict[str, dict], extra: dict, vectors: list[dict], tests: list[dict], validity: tuple[str, str | None], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str], status: str, tier: str = "A") -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "healthcare",
        "region": "US",
        "status": status,
        "tier": tier,
        "valid_from": validity[0],
        "valid_to": validity[1],
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": "almanac.rules.lookup_table", "parameters": {**extra, "rows": rows}, "vectors": vectors},
        "evidence": items,
        "assumed": assumed,
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, {"statistic": "count", "expected": len(rows), "tolerance": 0}] + tests,
        "notes": notes,
    }


def vector(key: str, column: str, rows: dict[str, dict], note: str | None = None) -> dict:
    item = {"input": {"key": key, "column": column}, "expected": rows[key][column], "origin": "source"}
    return {**item, "note": note} if note else item


def extreme(rows: dict[str, dict], column: str, largest: bool = True) -> str:
    return (max if largest else min)(rows, key=lambda k: rows[k][column])


def temporal(entry_id: str, title: str, variable: str, unit: str, frequency: str, series: list[dict], columns: list[str], period: tuple[str, str], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str], status: str, tier: str = "A") -> dict:
    values = [p["value"] for p in series]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": "healthcare",
        "region": "US",
        "status": status,
        "tier": tier,
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": items,
        "assumed": assumed,
        "tests": [
            {"statistic": stat("value", series[0]["period"]), "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": stat("value", series[-1]["period"]), "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": "max", "expected": max(values), "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": notes,
    }


def number(text: str) -> float | None:
    text = text.strip()
    return None if text in ("", ".") else float(text)


def integer(text: str) -> int:
    return int(float(text)) if text.strip() else 0


def numeric(text: str) -> int | float:
    """A count that CMS sometimes publishes with a fractional part (anaesthesia units, partial services)."""
    value = float(text)
    return int(value) if value.is_integer() else value


# ---------------------------------------------------------------------------
# MS-DRG Table 5 (FY 2026 IPPS final rule)


def drg_weights(raw: bytes) -> dict:
    text = member(raw, "CMS-1833-F Table 5.txt").decode("cp1252")
    rows: dict[str, dict] = {}
    for parts in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(parts) < 10 or not re.fullmatch(r"\d{3}", parts[0].strip()):
            continue
        weight = number(parts[7])
        if weight is None:
            continue
        rows[parts[0].strip()] = {
            "title": collapse(parts[5]),
            "mdc": parts[3].strip() or None,
            "type": parts[4].strip(),
            "post_acute": parts[1].strip() == "Yes",
            "special_pay": parts[2].strip() == "Yes",
            "relative_weight": weight,
            "relative_weight_before_cap": number(parts[6]),
            "geometric_mean_los": number(parts[8]),
            "arithmetic_mean_los": number(parts[9]),
        }
    heaviest = extreme(rows, "relative_weight")
    lightest = extreme(rows, "relative_weight", largest=False)
    first = "001"
    return lookup(
        "us-ms-drg-fy2026-relative-weights",
        f"MS-DRG FY2026 relative weights and geometric and arithmetic mean length of stay (IPPS final rule Table 5, {len(rows)} groups)",
        rows,
        {"fiscal_year": 2026, "source_table": "CMS-1833-F Table 5", "weight_unit": "ratio", "los_unit": "days"},
        [
            vector(first, "relative_weight", rows),
            vector(first, "geometric_mean_los", rows),
            vector(first, "arithmetic_mean_los", rows),
            vector("470", "title", rows),
            vector(heaviest, "relative_weight", rows, "largest weight"),
            vector(lightest, "relative_weight", rows, "smallest weight"),
            {"input": "999", "expected": False, "origin": "derived", "note": "UNGROUPABLE carries no weight and is left out"},
        ],
        [{"statistic": "max[relative_weight]", "expected": rows[heaviest]["relative_weight"], "tolerance": 0}, {"statistic": "max[geometric_mean_los]", "expected": max(r["geometric_mean_los"] for r in rows.values()), "tolerance": 0}],
        ("2025-10-01", "2026-09-30"),
        [
            cite(CMS, "FY 2026 IPPS final rule Table 5, MS-DRGs, relative weighting factors and mean length of stay (CMS-1833-F Table 5.txt)", URLS["table5"], "CMS-1833-F Table 5.txt, row MS-DRG 001, Weights - 10% Cap Applied", rows[first]["relative_weight"], "ratio", "001 No No PRE SURG HEART TRANSPLANT OR IMPLANT OF HEART ASSIST SYSTEM WITH MCC 28.0239 28.0239 25.8 36.2", UNSTATED, raw),
            cite(CMS, "FY 2026 IPPS final rule Table 5 (CMS-1833-F Table 5.txt)", URLS["table5"], "CMS-1833-F Table 5.txt, column headings", "Geometric mean LOS", "text", "Weights - Before Cap Weights - 10% Cap Applied Geometric mean LOS Arithmetic mean LOS", UNSTATED, raw),
        ],
        [{"parameter": "rows", "value": "weighted MS-DRGs only", "method": "derived", "rationale": "MS-DRGs 998 and 999 carry no weight or length of stay in Table 5 and are left out; every other row is copied unchanged."}],
        "Every MS-DRG of the inpatient prospective payment system for the fiscal year beginning 1 October 2025, with its title, major diagnostic category, surgical or medical type, post-acute and special-pay flags, the relative weight as published after the 10 percent cap on weight reductions (relative_weight) and before it (relative_weight_before_cap), and the geometric and arithmetic mean lengths of stay in days, read from the tab-delimited text member of the Table 5 archive. A synthetic inpatient claim can draw its DRG, expected length of stay and payment weight from this table." + CMS_NOTE,
        ["healthcare", "claims", "hospitals", "ms-drg", "ipps", "reference-table"],
        USE_CASES + ["claims-generation", "clinical-records"],
        "license-review",
    )


# ---------------------------------------------------------------------------
# Medicare inpatient utilisation by DRG and by state (calendar 2024)


def inpatient_drg_utilisation(raw: bytes) -> dict:
    national = [r for r in rows_of(raw) if r["Rndrng_Prvdr_Geo_Lvl"] == "National"]
    rows = {
        r["DRG_Cd"]: {
            "title": r["DRG_Desc"],
            "discharges": int(r["Tot_Dschrgs"]),
            "avg_submitted_covered_charge_usd": float(r["Avg_Submtd_Cvrd_Chrg"]),
            "avg_total_payment_usd": float(r["Avg_Tot_Pymt_Amt"]),
            "avg_medicare_payment_usd": float(r["Avg_Mdcr_Pymt_Amt"]),
        }
        for r in national
    }
    busiest = extreme(rows, "discharges")
    total = sum(r["discharges"] for r in rows.values())
    first = national[0]
    return lookup(
        "us-medicare-inpatient-drg-utilisation-2024",
        f"Medicare fee-for-service inpatient discharges and average charges and payments by MS-DRG, 2024 ({len(rows)} DRGs)",
        rows,
        {"year": 2024, "total_discharges": total},
        [vector("001", "discharges", rows), vector("001", "avg_medicare_payment_usd", rows), vector(busiest, "discharges", rows, "most discharges"), {"input": busiest, "expected": True, "origin": "source"}],
        [{"statistic": "max[discharges]", "expected": rows[busiest]["discharges"], "tolerance": 0}, {"statistic": "max[avg_medicare_payment_usd]", "expected": max(r["avg_medicare_payment_usd"] for r in rows.values()), "tolerance": 0}],
        ("2024-01-01", "2024-12-31"),
        [
            cite(CMS, "Medicare Inpatient Hospitals - by Geography and Service, 2024 (national rows)", URLS["inp_geo"], f"Rndrng_Prvdr_Geo_Lvl=National, DRG_Cd={first['DRG_Cd']}, Tot_Dschrgs", int(first["Tot_Dschrgs"]), "count", f"National,,National,{first['DRG_Cd']},{first['DRG_Desc']},{first['Tot_Dschrgs']}", UNSTATED, raw),
            cite(CMS, "Medicare Inpatient Hospitals - by Geography and Service, 2024 (column headings)", URLS["inp_geo"], "header row", "Avg_Mdcr_Pymt_Amt", "text", "DRG_Cd,DRG_Desc,Tot_Dschrgs,Avg_Submtd_Cvrd_Chrg,Avg_Tot_Pymt_Amt,Avg_Mdcr_Pymt_Amt", UNSTATED, raw),
        ],
        [{"parameter": "total_discharges", "value": total, "method": "derived", "rationale": "Sum of Tot_Dschrgs over the national rows; CMS publishes the per-DRG counts."}],
        "National Medicare fee-for-service inpatient discharges in calendar 2024 by MS-DRG with the average submitted covered charge, average total payment and average Medicare payment per discharge, from the CMS Medicare Inpatient Hospitals by Geography and Service public use file. The discharge counts are the natural weights for drawing a DRG on a synthetic inpatient claim and the averages anchor the charge and payment amounts. DRGs with fewer than eleven discharges are suppressed by CMS and absent." + CMS_NOTE,
        ["healthcare", "claims", "hospitals", "ms-drg", "medicare", "utilisation", "reference-table"],
        USE_CASES + ["claims-generation"],
        "license-review",
    )


def inpatient_discharges_by_state(raw: bytes) -> dict:
    rows = rows_of(raw)
    counts: Counter[str] = Counter()
    for r in rows:
        if r["Rndrng_Prvdr_Geo_Lvl"] == "State":
            counts[r["Rndrng_Prvdr_Geo_Desc"]] += int(r["Tot_Dschrgs"])
    first = next(r for r in rows if r["Rndrng_Prvdr_Geo_Lvl"] == "State")
    return marginal(
        "us-medicare-inpatient-discharges-by-state-2024",
        f"Medicare fee-for-service inpatient discharges by state of the hospital, 2024 ({len(counts)} states and territories)",
        "hospital_state",
        dict(sorted(counts.items())),
        ("2024-01-01", "2024-12-31"),
        [cite(CMS, "Medicare Inpatient Hospitals - by Geography and Service, 2024 (state rows)", URLS["inp_geo"], f"Rndrng_Prvdr_Geo_Lvl=State, Rndrng_Prvdr_Geo_Desc={first['Rndrng_Prvdr_Geo_Desc']}, DRG_Cd={first['DRG_Cd']}, Tot_Dschrgs", int(first["Tot_Dschrgs"]), "count", f"State,{first['Rndrng_Prvdr_Geo_Cd']},{first['Rndrng_Prvdr_Geo_Desc']},{first['DRG_Cd']},{first['DRG_Desc']},{first['Tot_Dschrgs']}", UNSTATED, raw)],
        [{"parameter": "distribution.parameters.counts", "value": "sum of Tot_Dschrgs over DRG rows per state", "method": "derived", "rationale": "The file lists discharges per state and DRG; the state totals are their sums and omit DRG rows CMS suppressed for fewer than eleven discharges."}],
        "Where Medicare fee-for-service inpatient discharges in calendar 2024 took place, by the state or territory of the rendering hospital, summed from the state and DRG rows of the CMS Medicare Inpatient Hospitals by Geography and Service file. Use it to weight the hospital state on synthetic inpatient claims." + CMS_NOTE,
        ["healthcare", "claims", "hospitals", "medicare", "by-state"],
        USE_CASES + ["claims-generation", "address-generation"],
        "license-review",
    )


def inpatient_beneficiary_mix(raw: bytes) -> list[dict]:
    rows = rows_of(raw)
    first = rows[0]
    groups = {
        "age_band": {"under_65": "Bene_Age_LT_65_Cnt", "65_to_74": "Bene_Age_65_74_Cnt", "75_to_84": "Bene_Age_75_84_Cnt", "85_and_over": "Bene_Age_GT_84_Cnt"},
        "race": {"white": "Bene_Race_Wht_Cnt", "black": "Bene_Race_Black_Cnt", "asian_pacific_islander": "Bene_Race_API_Cnt", "hispanic": "Bene_Race_Hspnc_Cnt", "native_american": "Bene_Race_NatInd_Cnt", "other": "Bene_Race_Othr_Cnt"},
    }
    entries = []
    for variable, columns in groups.items():
        counts = {label: sum(integer(r[col]) for r in rows) for label, col in columns.items()}
        suppressed = sum(1 for r in rows for col in columns.values() if not r[col].strip())
        entries.append(marginal(
            f"us-medicare-inpatient-beneficiaries-by-{variable.replace('_', '-')}-2024",
            f"Medicare fee-for-service inpatient beneficiaries by {variable.replace('_', ' ')}, summed over {len(rows)} hospitals, 2024",
            variable,
            counts,
            ("2024-01-01", "2024-12-31"),
            [
                cite(CMS, "Medicare Inpatient Hospitals - by Provider, 2024", URLS["inp_prv"], f"Rndrng_Prvdr_CCN={first['Rndrng_Prvdr_CCN']}, Tot_Benes", int(first["Tot_Benes"]), "count", f"{first['Rndrng_Prvdr_CCN']},{first['Rndrng_Prvdr_Org_Name']},{first['Rndrng_Prvdr_St']},{first['Rndrng_Prvdr_City']},{first['Rndrng_Prvdr_Zip5']},{first['Rndrng_Prvdr_State_Abrvtn']}", UNSTATED, raw),
                cite(CMS, "Medicare Inpatient Hospitals - by Provider, 2024 (column headings)", URLS["inp_prv"], "header row", next(iter(columns.values())), "text", ",".join(columns.values()), UNSTATED, raw),
            ],
            [{"parameter": "distribution.parameters.counts", "value": "column sums over all hospitals", "method": "derived", "rationale": f"CMS publishes the counts per hospital; {suppressed} hospital cells are blank (suppressed for fewer than eleven beneficiaries) and count as zero."}],
            f"The {variable.replace('_', ' ')} mix of beneficiaries with a Medicare fee-for-service inpatient stay in calendar 2024, summed over every hospital in the CMS Medicare Inpatient Hospitals by Provider file. A beneficiary admitted to two hospitals is counted at each, so the totals describe hospital-beneficiary pairs rather than unique people." + CMS_NOTE,
            ["healthcare", "claims", "hospitals", "medicare", "patient-mix", variable.replace("_", "-")],
            USE_CASES + ["person-generation", "clinical-records"],
            "license-review",
        ))
    return entries


# ---------------------------------------------------------------------------
# Medicare outpatient, physician and drug value pools (2024)


def outpatient_top_apcs(raw: bytes) -> dict:
    rows = rows_of(raw)
    apcs = [r for r in rows if r["Rndrng_Prvdr_Geo_Lvl"] == "National" and r["Srvc_Lvl"] == "APC"]
    apcs.sort(key=lambda r: -int(r["CAPC_Srvcs"]))
    top = {
        r["APC_Cd"]: {
            "description": r["APC_Desc"],
            "beneficiaries": int(r["Bene_Cnt"]),
            "services": int(r["CAPC_Srvcs"]),
            "avg_submitted_charges_usd": float(r["Avg_Tot_Sbmtd_Chrgs"]),
            "avg_allowed_amount_usd": float(r["Avg_Mdcr_Alowd_Amt"]),
            "avg_payment_usd": float(r["Avg_Mdcr_Pymt_Amt"]),
            "outlier_services": integer(r["Outlier_Srvcs"]),
        }
        for r in apcs
    }
    first, busiest = apcs[0], extreme(top, "services")
    return lookup(
        "us-medicare-outpatient-apcs-2024",
        f"Medicare outpatient hospital services by comprehensive ambulatory payment classification, with average payments, 2024 ({len(top)} APCs)",
        top,
        {"year": 2024, "service_level": "APC"},
        [vector(first["APC_Cd"], "services", top), vector(first["APC_Cd"], "avg_payment_usd", top), vector(busiest, "description", top)],
        [{"statistic": "max[services]", "expected": top[busiest]["services"], "tolerance": 0}],
        ("2024-01-01", "2024-12-31"),
        [cite(CMS, "Medicare Outpatient Hospitals - by Geography and Service, 2024 (national APC rows)", URLS["out_geo"], f"Rndrng_Prvdr_Geo_Lvl=National, Srvc_Lvl=APC, APC_Cd={first['APC_Cd']}, CAPC_Srvcs", int(first["CAPC_Srvcs"]), "count", f"National,,National,APC,{first['APC_Cd']},{first['APC_Desc']},,,{first['Bene_Cnt']},{first['CAPC_Srvcs']}", UNSTATED, raw)],
        [],
        "Every comprehensive ambulatory payment classification reported nationally for Medicare fee-for-service outpatient hospital services in calendar 2024, with beneficiaries, services, average submitted charges, average allowed amount, average Medicare payment and outlier services, from the national rows of the CMS Medicare Outpatient Hospitals by Geography and Service file. The service counts weight an APC draw on a synthetic outpatient claim and the averages anchor its amounts." + CMS_NOTE,
        ["healthcare", "claims", "hospitals", "medicare", "apc", "outpatient", "reference-table"],
        USE_CASES + ["claims-generation"],
        "license-review",
    )


def physician_top_services(pages: list[bytes]) -> dict:
    records = [r for raw in pages for r in json.loads(raw)]
    records.sort(key=lambda r: -float(r["Tot_Srvcs"]))
    top: dict[str, dict] = {}
    for r in records[:200]:
        code = r["HCPCS_Cd"]
        row = {
            "hcpcs_code": code,
            "place_of_service": r["Place_Of_Srvc"],
            "drug_indicator": r["HCPCS_Drug_Ind"] == "Y",
            "providers": int(r["Tot_Rndrng_Prvdrs"]),
            "beneficiaries": int(r["Tot_Benes"]),
            "services": numeric(r["Tot_Srvcs"]),
            "avg_submitted_charge_usd": float(r["Avg_Sbmtd_Chrg"]),
            "avg_allowed_amount_usd": float(r["Avg_Mdcr_Alowd_Amt"]),
            "avg_payment_usd": float(r["Avg_Mdcr_Pymt_Amt"]),
        }
        if code[0].isalpha() and code[0] != "D":
            row["description"] = r["HCPCS_Desc"]
        top[f"{code}-{r['Place_Of_Srvc']}"] = row
    busiest = next(iter(top))
    items = []
    for url, raw in zip(PHYSICIAN_PAGES, pages):
        first = json.loads(raw)[0]
        items.append(cite(CMS, "Medicare Physician & Other Practitioners - by Geography and Service, 2024, national rows (API page)", url, f"first record, HCPCS_Cd={first['HCPCS_Cd']}, Place_Of_Srvc={first['Place_Of_Srvc']}, Tot_Srvcs", numeric(first["Tot_Srvcs"]), "count", f'"HCPCS_Cd":"{first["HCPCS_Cd"]}"', UNSTATED, raw))
    page_index = next(i for i, raw in enumerate(pages) if any(r["HCPCS_Cd"] == top[busiest]["hcpcs_code"] and r["Place_Of_Srvc"] == top[busiest]["place_of_service"] for r in json.loads(raw)))
    items.append(cite(CMS, "Medicare Physician & Other Practitioners - by Geography and Service, 2024, national rows (API page)", PHYSICIAN_PAGES[page_index], f"HCPCS_Cd={top[busiest]['hcpcs_code']}, Place_Of_Srvc={top[busiest]['place_of_service']}, Tot_Srvcs", top[busiest]["services"], "count", f'"HCPCS_Cd":"{top[busiest]["hcpcs_code"]}"', UNSTATED, pages[page_index]))
    return lookup(
        "us-medicare-physician-top-200-services-2024",
        "Medicare physician and supplier services: the 200 HCPCS code and place-of-service pairs with most services, with payments, 2024",
        top,
        {"year": 2024, "ranked_by": "services", "place_of_service_codes": {"F": "facility", "O": "non-facility (office)"}, "national_rows_in_source": len(records)},
        [vector(busiest, "services", top, "most services"), vector(busiest, "avg_payment_usd", top), vector(busiest, "providers", top), {"input": "99999-X", "expected": False, "origin": "derived"}],
        [{"statistic": "max[services]", "expected": top[busiest]["services"], "tolerance": 0}, {"statistic": "min[services]", "expected": min(r["services"] for r in top.values()), "tolerance": 0}],
        ("2024-01-01", "2024-12-31"),
        items,
        [{"parameter": "rows", "value": "top 200 national rows by Tot_Srvcs", "method": "derived", "rationale": "The national rows, fetched in three API pages of 5000, are ranked by services and the first two hundred kept with their values unchanged; descriptions are kept only for HCPCS Level II codes because CPT descriptors are copyrighted by the American Medical Association."}],
        "The two hundred HCPCS code and place-of-service pairs with the most Medicare fee-for-service physician and supplier services in calendar 2024, with rendering providers, beneficiaries, services, and the average submitted charge, allowed amount and Medicare payment per service, from the national rows of the CMS Medicare Physician & Other Practitioners by Geography and Service dataset read through the data.cms.gov API. Service counts weight the procedure code on a synthetic professional claim; the averages anchor its charge and payment. Descriptions of CPT codes (numeric codes) are omitted for copyright reasons." + CMS_NOTE,
        ["healthcare", "claims", "medicare", "hcpcs", "procedures", "reference-table"],
        USE_CASES + ["claims-generation"],
        "license-review",
    )


def part_d_top_drugs(raw: bytes) -> dict:
    rows = rows_of(raw)
    overall = [r for r in rows if r["Mftr_Name"] == "Overall" and r["Tot_Spndng_2024"].strip()]
    overall.sort(key=lambda r: -float(r["Tot_Spndng_2024"]))
    top: dict[str, dict] = {}
    for r in overall[:100]:
        key = r["Brnd_Name"] if r["Brnd_Name"] not in top else f"{r['Brnd_Name']} ({r['Gnrc_Name']})"
        top[key] = {
            "generic_name": r["Gnrc_Name"],
            "manufacturers": int(r["Tot_Mftr"]),
            "total_spending_usd": float(r["Tot_Spndng_2024"]),
            "dosage_units": float(r["Tot_Dsg_Unts_2024"]),
            "claims": int(r["Tot_Clms_2024"]),
            "beneficiaries": int(r["Tot_Benes_2024"]),
            "avg_spending_per_claim_usd": float(r["Avg_Spnd_Per_Clm_2024"]),
            "avg_spending_per_beneficiary_usd": float(r["Avg_Spnd_Per_Bene_2024"]),
            "outlier_flag": r["Outlier_Flag_2024"] == "1",
        }
    first = overall[0]
    top_key = next(iter(top))
    return lookup(
        "us-medicare-part-d-top-100-drugs-2024",
        "Medicare Part D: the 100 drugs with highest total spending, with claims, beneficiaries and spending per claim, 2024",
        top,
        {"year": 2024, "ranked_by": "total_spending_usd", "drugs_in_source": len(overall)},
        [vector(top_key, "total_spending_usd", top, "highest spending"), vector(top_key, "beneficiaries", top), vector(top_key, "avg_spending_per_claim_usd", top), vector(top_key, "generic_name", top)],
        [{"statistic": "max[total_spending_usd]", "expected": top[top_key]["total_spending_usd"], "tolerance": 0}, {"statistic": "max[claims]", "expected": max(r["claims"] for r in top.values()), "tolerance": 0}],
        ("2024-01-01", "2024-12-31"),
        [
            cite(CMS, "Medicare Part D Spending by Drug, 2024 (overall rows)", URLS["part_d"], f"Brnd_Name={first['Brnd_Name']}, Mftr_Name=Overall, Tot_Spndng_2024", first["Tot_Spndng_2024"], "currency:USD", f"{first['Brnd_Name']},{first['Gnrc_Name']},{first['Tot_Mftr']},Overall,", UNSTATED, raw),
            cite(CMS, "Medicare Part D Spending by Drug, 2024 (column headings)", URLS["part_d"], "header row", "Avg_Spnd_Per_Clm_2024", "text", "Tot_Spndng_2024,Tot_Dsg_Unts_2024,Tot_Clms_2024,Tot_Benes_2024", UNSTATED, raw),
        ],
        [{"parameter": "rows", "value": "top 100 overall rows by Tot_Spndng_2024", "method": "derived", "rationale": "The rows labelled Overall (all manufacturers combined) are ranked by 2024 total spending and the first hundred kept with their values unchanged; a brand appearing twice is keyed with its generic name."}],
        "The hundred brand-name or generic drugs with the highest Medicare Part D spending in calendar 2024, with the generic name, number of manufacturers, total spending, dosage units, claims, beneficiaries, average spending per claim and per beneficiary, and the CMS outlier flag, from the Medicare Part D Spending by Drug public use file. Spending weights a drug draw for a synthetic prescription claim and the per-claim averages anchor its cost. Spending is gross drug cost before rebates." + CMS_NOTE,
        ["healthcare", "drugs", "claims", "medicare", "part-d", "pharmacy", "reference-table"],
        PHARMA_USE_CASES + ["payer-demo", "claims-generation"],
        "license-review",
    )


def part_b_top_drugs(raw: bytes) -> dict:
    rows = [r for r in rows_of(raw) if r["Tot_Spndng_2024"].strip()]
    rows.sort(key=lambda r: -float(r["Tot_Spndng_2024"]))
    top = {
        r["HCPCS_Cd"]: {
            "description": r["HCPCS_Desc"],
            "brand_name": r["Brnd_Name"],
            "generic_name": r["Gnrc_Name"],
            "total_spending_usd": float(r["Tot_Spndng_2024"]),
            "dosage_units": float(r["Tot_Dsg_Unts_2024"]),
            "claims": int(r["Tot_Clms_2024"]),
            "beneficiaries": int(r["Tot_Benes_2024"]),
            "avg_spending_per_dosage_unit_usd": float(r["Avg_Spndng_Per_Dsg_Unt_2024"]),
            "avg_spending_per_claim_usd": float(r["Avg_Spndng_Per_Clm_2024"]),
            "avg_spending_per_beneficiary_usd": float(r["Avg_Spndng_Per_Bene_2024"]),
        }
        for r in rows[:50]
    }
    first = rows[0]
    return lookup(
        "us-medicare-part-b-top-50-drugs-2024",
        "Medicare Part B: the 50 drug HCPCS codes with highest total spending, with claims, beneficiaries and spending per claim, 2024",
        top,
        {"year": 2024, "ranked_by": "total_spending_usd", "codes_in_source": len(rows)},
        [vector(first["HCPCS_Cd"], "total_spending_usd", top, "highest spending"), vector(first["HCPCS_Cd"], "brand_name", top), vector(first["HCPCS_Cd"], "avg_spending_per_claim_usd", top)],
        [{"statistic": "max[total_spending_usd]", "expected": top[first["HCPCS_Cd"]]["total_spending_usd"], "tolerance": 0}],
        ("2024-01-01", "2024-12-31"),
        [cite(CMS, "Medicare Part B Spending by Drug, 2024", URLS["part_b"], f"HCPCS_Cd={first['HCPCS_Cd']}, Tot_Spndng_2024", first["Tot_Spndng_2024"], "currency:USD", f"{first['HCPCS_Cd']},\"{first['HCPCS_Desc']}\",{first['Brnd_Name']},{first['Gnrc_Name']}", UNSTATED, raw)],
        [{"parameter": "rows", "value": "top 50 rows by Tot_Spndng_2024", "method": "derived", "rationale": "Rows with 2024 spending are ranked and the first fifty kept with their values unchanged."}],
        "The fifty HCPCS codes for physician-administered drugs with the highest Medicare Part B spending in calendar 2024, with the HCPCS description, brand and generic names, total spending, dosage units, claims, beneficiaries and average spending per dosage unit, claim and beneficiary, from the Medicare Part B Spending by Drug public use file. Spending weights a drug code draw for synthetic infusion and injection claims." + CMS_NOTE,
        ["healthcare", "drugs", "claims", "medicare", "part-b", "hcpcs", "reference-table"],
        PHARMA_USE_CASES + ["payer-demo", "claims-generation"],
        "license-review",
    )


# ---------------------------------------------------------------------------
# HCPCS Level II and the physician fee schedule


def hcpcs_entries(raw: bytes) -> list[dict]:
    lines = member(raw, "HCPC2026_OCT_ANWEB_09232026.txt").decode("latin-1").splitlines()
    records = [line for line in lines if len(line) >= 293 and line[10] == "3" and line[:5].strip() and not line[:3].isspace()]
    sections: dict[str, dict] = {}
    coverage: Counter[str] = Counter()
    active = 0
    for line in records:
        code, letter = line[:5], line[0]
        terminated = bool(line[284:292].strip())
        section = sections.setdefault(letter, {"codes": 0, "active_codes": 0, "first_code": code, "first_code_description": collapse(line[11:91])})
        section["codes"] += 1
        if not terminated:
            section["active_codes"] += 1
            coverage[line[229]] += 1
            active += 1
    sections = dict(sorted(sections.items()))
    first = records[0]
    coverage_labels = {"C": "carrier_judgment", "D": "special_coverage_instructions", "I": "not_payable_by_medicare", "M": "non_covered_by_medicare", "S": "non_covered_by_statute"}
    layout_items = [
        cite(CMS, "HCPCS October 2026 quarterly update archive, record layout (HCPC2026_recordlayout.txt)", URLS["hcpcs"], "HCPC2026_recordlayout.txt, field 16 HCPCS Coverage Code", "C = Carrier judgment", "text", "C = Carrier judgment", UNSTATED, raw, role="supporting"),
        cite(CMS, "HCPCS October 2026 quarterly update archive, record layout (HCPC2026_recordlayout.txt)", URLS["hcpcs"], "HCPC2026_recordlayout.txt, field 29 HCPCS Termination Date", "Last date for which a procedure or modifier code may be used by Medicare providers", "text", "Last date for which a procedure or modifier code may be used by Medicare providers", UNSTATED, raw, role="supporting"),
    ]
    code_item = cite(CMS, "HCPCS October 2026 quarterly update archive, alpha-numeric file (HCPC2026_OCT_ANWEB_09232026.txt)", URLS["hcpcs"], "HCPC2026_OCT_ANWEB_09232026.txt, first procedure record", first[:5], "text", first[:91].rstrip(), UNSTATED, raw)
    section_entry = lookup(
        "us-hcpcs-level-ii-2026q4-sections",
        f"HCPCS Level II alpha-numeric sections with code counts, October 2026 quarterly update ({len(sections)} sections, {active} active codes)",
        sections,
        {"release": "October 2026", "code_pattern": "^[A-V][0-9]{4}$", "active_codes": active, "codes": len(records)},
        [vector("A", "first_code", sections), vector("J", "codes", sections, "drugs administered other than oral method"), {"input": "D", "expected": False, "origin": "derived", "note": "dental D codes are not in the CMS file"}],
        [{"statistic": "max[codes]", "expected": max(s["codes"] for s in sections.values()), "tolerance": 0}],
        ("2026-10-01", "2026-12-31"),
        [code_item] + layout_items[1:],
        [
            {"parameter": "rows[*].codes and rows[*].active_codes", "value": "counts of procedure records per leading letter", "method": "derived", "rationale": "Counted from the first-line procedure records (record identification code 3); a code is active when its termination date is blank."},
            {"parameter": "code_pattern", "value": "^[A-V][0-9]{4}$", "method": "derived", "rationale": "Shape observed across every procedure record in the file; the layout describes Level II codes as five-position alpha-numeric codes."},
        ],
        "The alphabetic sections of HCPCS Level II as released in the October 2026 quarterly update, with the number of codes in each section, how many have no termination date, and the first code and its long description, read from the fixed-width alpha-numeric file in the CMS archive. The file holds the CMS-maintained Level II codes (A to V) and not the AMA's CPT Level I codes or the ADA's dental codes. A synthetic claim generator can use the section counts to spread supply, drug and service codes realistically." + CMS_NOTE,
        ["healthcare", "claims", "hcpcs", "code-list", "procedures", "supplies"],
        USE_CASES + ["claims-generation"],
        "license-review",
    )
    coverage_entry = marginal(
        "us-hcpcs-level-ii-2026q4-coverage-codes",
        f"HCPCS Level II active codes by Medicare coverage code, October 2026 quarterly update ({active} codes)",
        "coverage_code",
        {coverage_labels[k]: v for k, v in sorted(coverage.items())},
        ("2026-10-01", "2026-10-31"),
        [code_item, layout_items[0]],
        [{"parameter": "distribution.parameters.counts", "value": "codes per coverage code among codes without a termination date", "method": "derived", "rationale": "Counted from position 230 of the first-line procedure records whose termination date is blank; labels follow the record layout's code list."}],
        "How active HCPCS Level II codes split by the Medicare coverage code carried in the October 2026 alpha-numeric file: carrier judgment, special coverage instructions, not payable by Medicare, non-covered by Medicare, and non-covered by statute. Useful for deciding whether a synthetic line item is payable." + CMS_NOTE,
        ["healthcare", "claims", "hcpcs", "coverage", "medicare"],
        USE_CASES + ["claims-generation"],
        "license-review",
    )
    return [section_entry, coverage_entry]


def office_visit_rvus(raw: bytes) -> dict:
    text = member(raw, "PPRRVU2026_Oct_nonQPP.csv").decode("latin-1")
    wanted = {f"992{n:02d}" for n in (2, 3, 4, 5, 11, 12, 13, 14, 15)}
    rows: dict[str, dict] = {}
    factor: float | None = None
    for parts in csv.reader(io.StringIO(text)):
        if len(parts) < 26 or parts[0] not in wanted or parts[1]:
            continue
        factor = float(parts[25])
        work, nonfac_pe, fac_pe, mp = (float(parts[i]) for i in (5, 6, 8, 10))
        rows[parts[0]] = {
            "status_code": parts[3],
            "work_rvu": work,
            "nonfacility_pe_rvu": nonfac_pe,
            "facility_pe_rvu": fac_pe,
            "malpractice_rvu": mp,
            "nonfacility_total_rvu": float(parts[11]),
            "facility_total_rvu": float(parts[12]),
            "global_period": parts[14],
            "nonfacility_national_payment_usd": round(float(parts[11]) * factor, 2),
            "facility_national_payment_usd": round(float(parts[12]) * factor, 2),
        }
    assert factor is not None and len(rows) == len(wanted)
    rows = dict(sorted(rows.items()))
    return lookup(
        "us-pfs-2026-office-visit-rvus",
        "Medicare physician fee schedule relative value units and national payment for office visit codes 99202 to 99215, October 2026 release",
        rows,
        {"release": "RVU26D (October 2026)", "conversion_factor_usd": factor, "payment_formula": "total RVU x conversion factor, before geographic adjustment"},
        [vector("99213", "work_rvu", rows), vector("99213", "nonfacility_total_rvu", rows), vector("99214", "malpractice_rvu", rows), vector("99205", "facility_pe_rvu", rows), {"input": "99201", "expected": False, "origin": "derived", "note": "deleted code, not in the subset"}],
        [{"statistic": "max[work_rvu]", "expected": max(r["work_rvu"] for r in rows.values()), "tolerance": 0}, {"statistic": "min[work_rvu]", "expected": min(r["work_rvu"] for r in rows.values()), "tolerance": 0}],
        ("2026-10-01", "2026-12-31"),
        [
            cite(CMS, "RVU26D national physician fee schedule relative value file, October 2026 release (PPRRVU2026_Oct_nonQPP.csv)", URLS["rvu"], "PPRRVU2026_Oct_nonQPP.csv, row HCPCS 99213, WORK RVU", rows["99213"]["work_rvu"], "ratio", "99213,,Office o/p est low 20 min,A,,1.30,1.46,,0.33,,0.09,2.85,1.72", UNSTATED, raw),
            cite(CMS, "RVU26D national physician fee schedule relative value file, October 2026 release (PPRRVU2026_Oct_nonQPP.csv)", URLS["rvu"], "PPRRVU2026_Oct_nonQPP.csv, CONV FACTOR column", factor, "currency:USD", "RELEASED 08/26/2026", UNSTATED, raw),
        ],
        [{"parameter": "rows[*].nonfacility_national_payment_usd and rows[*].facility_national_payment_usd", "value": "total RVU x conversion factor, rounded to cents", "method": "derived", "rationale": "The file carries the RVUs and the conversion factor; the national payment amount is their product before the geographic practice cost index adjustment, which the fee schedule applies per locality."}],
        "Work, practice expense (facility and non-facility), malpractice and total relative value units for the new and established patient office or outpatient visit codes 99202 to 99215 from the RVU26D release of the Medicare physician fee schedule relative value file, with the conversion factor from the same file and the national payment amounts derived from them. Descriptions are omitted because CPT descriptors are copyrighted by the American Medical Association; the codes themselves anchor the most common professional claim lines." + CMS_NOTE,
        ["healthcare", "claims", "medicare", "physician-fee-schedule", "rvu", "evaluation-and-management"],
        USE_CASES + ["claims-generation", "pricing"],
        "license-review",
    )


# ---------------------------------------------------------------------------
# Readmissions and hospital-acquired conditions


def hrrp_entries(raw: bytes) -> list[dict]:
    lines = member(raw, "FR FY 2026.txt").decode("utf-8", errors="replace").splitlines()
    header = [h.strip() for h in lines[1].split("\t")]
    records = [dict(zip(header, (v.strip() for v in line.split("\t")))) for line in lines[2:] if re.match(r"^\d{6}\t", line)]
    factors = Counter(float(r["Payment adjustment factor"]) for r in records)
    values = sorted(factors)
    penalised = sum(1 for r in records if float(r["Payment adjustment factor"]) < 1)
    first = records[0]
    row_snippet = f"{first['Hospital CCN']} {first['Payment adjustment factor']} {first['Payment reduction percentage']} {first['Dual proportion']} {first['Peer group assignment']} {first['Neutrality modifier']}"
    mean = sum(v * n for v, n in factors.items()) / len(records)
    factor_entry = {
        "id": "us-hrrp-fy2026-payment-adjustment-factors",
        "title": f"Hospital Readmissions Reduction Program FY2026 payment adjustment factors across {len(records)} hospitals",
        "kind": "marginal",
        "domain": "healthcare",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2021-07-01", "end": "2024-06-30"},
        "tags": ["healthcare", "hospitals", "readmissions", "hrrp", "medicare", "payment-adjustment"],
        "use_cases": USE_CASES + ["claims-generation"],
        "spec": {"variable": "payment_adjustment_factor", "unit": "ratio", "distribution": {"family": "empirical", "parameters": {"values": values, "weights": [factors[v] for v in values], "hospitals": len(records), "penalised_hospitals": penalised, "penalised_share": round(penalised / len(records), 6)}}},
        "evidence": [
            cite(CMS, "FY 2026 HRRP supplemental data file (FR FY 2026.txt)", URLS["hrrp"], f"FR FY 2026.txt, Hospital CCN {first['Hospital CCN']}, Payment adjustment factor", first["Payment adjustment factor"], "ratio", row_snippet, UNSTATED, raw),
            cite(CMS, "FY 2026 HRRP supplemental data file, variable descriptions (Variable Description.txt)", URLS["hrrp"], "Variable Description.txt, Payment adjustment factor", "0.97", "ratio", "The minimum payment adjustment factor is 0.97 (that is, 3 percent maximum payment reduction)", UNSTATED, raw, role="supporting"),
        ],
        "assumed": [{"parameter": "distribution.parameters.weights", "value": "hospitals per distinct factor value", "method": "derived", "rationale": "The file lists one factor per hospital; the empirical distribution weights each distinct value by how many hospitals carry it, and penalised_share is the fraction of hospitals with a factor below 1."}],
        "tests": [
            {"statistic": "mean", "expected": round(mean, 6), "tolerance": 0.0002},
            {"statistic": "min", "expected": values[0], "tolerance": 0},
            {"statistic": "max", "expected": values[-1], "tolerance": 0},
        ],
        "notes": "The payment adjustment factor applied to each hospital's base operating DRG payments in fiscal 2026 under the Hospital Readmissions Reduction Program, based on discharges from July 2021 to June 2024; 1.0 means no penalty and 0.97 the maximum three percent reduction. Drawing a factor from this distribution gives a synthetic hospital a realistic readmission penalty." + CMS_NOTE,
    }
    conditions = ["AMI", "COPD", "HF", "pneumonia", "CABG", "THA/TKA"]
    rows: dict[str, dict] = {}
    for cond in conditions:
        measured = [r for r in records if r[f"ERR for {cond}"] not in ("", ".")]
        errs = sorted(float(r[f"ERR for {cond}"]) for r in measured)
        medians = {r["Peer group assignment"]: float(r[f"Peer group median ERR for {cond}"]) for r in measured if r["Peer group assignment"]}
        penalties = sum(1 for r in measured if r[f"Penalty indicator for {cond}"] == "Y")
        rows[cond] = {
            "hospitals_with_err": len(measured),
            "mean_err": round(sum(errs) / len(errs), 4),
            "median_err": errs[len(errs) // 2],
            "min_err": errs[0],
            "max_err": errs[-1],
            "penalised_hospitals": penalties,
            "penalised_share": round(penalties / len(measured), 4),
            **{f"peer_group_{g}_median_err": medians[g] for g in sorted(medians)},
        }
    condition_entry = lookup(
        "us-hrrp-fy2026-excess-readmission-by-condition",
        "Hospital Readmissions Reduction Program FY2026 excess readmission ratios by condition: hospitals, mean, penalty share and peer-group medians",
        rows,
        {"fiscal_year": 2026, "data_period": "July 2021 to June 2024", "conditions": {"AMI": "acute myocardial infarction", "COPD": "chronic obstructive pulmonary disease", "HF": "heart failure", "pneumonia": "pneumonia", "CABG": "coronary artery bypass graft surgery", "THA/TKA": "elective primary total hip or knee arthroplasty"}},
        [vector("AMI", f"peer_group_{first['Peer group assignment']}_median_err", rows), vector("HF", "hospitals_with_err", rows), {"input": "stroke", "expected": False, "origin": "derived"}],
        [{"statistic": "max[hospitals_with_err]", "expected": max(r["hospitals_with_err"] for r in rows.values()), "tolerance": 0}],
        ("2025-10-01", "2026-09-30"),
        [
            cite(CMS, "FY 2026 HRRP supplemental data file (FR FY 2026.txt)", URLS["hrrp"], f"FR FY 2026.txt, Hospital CCN {first['Hospital CCN']}, Peer group median ERR for AMI", first["Peer group median ERR for AMI"], "ratio", f"{first['Number of eligible discharges for AMI']} {first['ERR for AMI']} {first['Peer group median ERR for AMI']} {first['Penalty indicator for AMI']} {first['DRG payment ratio for AMI']}", UNSTATED, raw),
            cite(CMS, "FY 2026 HRRP supplemental data file (FR FY 2026.txt)", URLS["hrrp"], "FR FY 2026.txt, column headings", "ERR for THA/TKA", "text", "Number of eligible discharges for THA/TKA ERR for THA/TKA Peer group median ERR for THA/TKA", UNSTATED, raw),
            cite(CMS, "FY 2026 HRRP supplemental data file, variable descriptions (Variable Description.txt)", URLS["hrrp"], "Variable Description.txt, ERR", "excess readmission ratio", "text", "The ratio of the predicted readmission rate to the expected readmission rate for a given measure", UNSTATED, raw, role="supporting"),
        ],
        [{"parameter": "rows[*].hospitals_with_err, mean_err, median_err, min_err, max_err, penalised_hospitals, penalised_share", "value": "summaries over hospitals with a reported ERR", "method": "derived", "rationale": "Computed from the hospital rows of the supplemental file; the peer group median ERR columns are copied from the file, where every hospital in a peer group carries the same value."}],
        "For each of the six Hospital Readmissions Reduction Program measures, how many hospitals had an excess readmission ratio (ERR) in the fiscal 2026 program, the mean, median and range of those ratios, the share of hospitals penalised on the measure, and the peer-group median ERR thresholds CMS used for the five dual-eligibility peer groups, from the final rule supplemental data file. ERR is predicted over expected readmissions, so 1.0 is average performance." + CMS_NOTE,
        ["healthcare", "hospitals", "readmissions", "hrrp", "medicare", "quality"],
        USE_CASES + ["clinical-records"],
        "license-review",
    )
    return [factor_entry, condition_entry]


def hac_rates(pages: list[bytes]) -> dict:
    records = [r for raw in pages for r in json.loads(raw)]
    by_measure: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_measure[r["Measure"]].append(r)
    rows: dict[str, dict] = {}
    for measure, items in by_measure.items():
        rates = [float(r["Rate"]) for r in items if r["Rate"].strip()]
        rows[measure.split(" (")[0]] = {
            "measure": measure,
            "hospitals": len(items),
            "hospitals_with_rate": len(rates),
            "mean_rate": round(sum(rates) / len(rates), 4),
            "max_rate": max(rates),
            "share_with_zero_rate": round(sum(1 for v in rates if v == 0) / len(rates), 4),
            "footnoted": sum(1 for r in items if r["Footnote"].strip()),
        }
    first = records[0]
    items = [cite(CMS, "Deficit Reduction Act Hospital-Acquired Condition Measures, 2025 (API page)", url, f"first record, Provider_ID={json.loads(raw)[0]['Provider_ID']}, Rate", json.loads(raw)[0]["Rate"], "decimal", f'"Provider_ID":"{json.loads(raw)[0]["Provider_ID"]}","Measure":"{json.loads(raw)[0]["Measure"]}"', UNSTATED, raw) for url, raw in zip(HAC_PAGES, pages)]
    return lookup(
        "us-hac-dra-measure-rates-2025",
        "Deficit Reduction Act hospital-acquired condition measures: hospitals, mean and maximum rate and share with a zero rate, 2025 release",
        rows,
        {"measurement_period": f"{first['Start_Quarter']} to {first['End_Quarter']}", "rate_unit": "as published in the Rate column", "hospital_rows": len(records)},
        [vector("Falls and Trauma", "hospitals", rows), vector("Air Embolism", "measure", rows), {"input": "Pressure Ulcer", "expected": False, "origin": "derived"}],
        [{"statistic": "max[mean_rate]", "expected": max(r["mean_rate"] for r in rows.values()), "tolerance": 0}],
        ("2022-07-01", "2024-06-30"),
        items,
        [{"parameter": "rows[*].mean_rate, max_rate, share_with_zero_rate, hospitals, hospitals_with_rate, footnoted", "value": "summaries over hospital rows per measure", "method": "derived", "rationale": "The dataset lists one rate per hospital and measure, fetched in three API pages; the entry summarises them and keeps the measure names unchanged."}],
        "The four Deficit Reduction Act hospital-acquired condition measures that CMS reports per hospital (foreign object retained after surgery, air embolism, blood incompatibility, and falls and trauma) with the number of hospitals, the mean and maximum rate and the share of hospitals with a zero rate over the measurement period, from the 2025 release of the Deficit Reduction Act Hospital-Acquired Condition Measures dataset on data.cms.gov. Rates are kept in the unit CMS publishes them in; the dataset's dictionary page renders in the browser and its unit could not be confirmed from a stable resource, so check it before labelling rates. The high share of zero rates gives a synthetic hospital quality profile realistic sparsity." + CMS_NOTE,
        ["healthcare", "hospitals", "quality", "hospital-acquired-conditions", "medicare"],
        USE_CASES + ["clinical-records"],
        "license-review",
    )


# ---------------------------------------------------------------------------
# Medicare enrolment and Medicare-enrolled hospitals


def enrollment_entries(raw: bytes) -> list[dict]:
    records = json.loads(raw)
    national = next(r for r in records if r["BENE_GEO_LVL"] == "National")
    states = [r for r in records if r["BENE_GEO_LVL"] == "State"]
    columns = {"total": "TOT_BENES", "original_medicare": "ORGNL_MDCR_BENES", "medicare_advantage_and_other": "MA_AND_OTH_BENES", "aged": "AGED_TOT_BENES", "disabled": "DSBLD_TOT_BENES", "male": "MALE_TOT_BENES", "female": "FEMALE_TOT_BENES", "dual_eligible": "DUAL_TOT_BENES", "part_d": "PRSCRPTN_DRUG_TOT_BENES"}
    rows = {r["BENE_STATE_ABRVTN"]: {"state": r["BENE_STATE_DESC"], **{k: int(r[c]) for k, c in columns.items()}} for r in sorted(states, key=lambda r: r["BENE_STATE_ABRVTN"])}
    national_snippet = '"YEAR":"2026","MONTH":"July","BENE_GEO_LVL":"National","BENE_STATE_ABRVTN":"US"'
    largest = extreme(rows, "total")
    by_state = lookup(
        "us-medicare-enrollment-by-state-2026-07",
        f"Medicare beneficiaries by state, July 2026: total, Original Medicare and Medicare Advantage, aged, disabled, sex, dual and Part D ({len(rows)} states)",
        rows,
        {"month": "2026-07", "national": {k: int(national[c]) for k, c in columns.items()}},
        [vector("CA", "total", rows), vector("AL", "medicare_advantage_and_other", rows), vector(largest, "total", rows, "largest state"), {"input": "US", "expected": False, "origin": "derived", "note": "the national row sits in parameters.national"}],
        [{"statistic": "max[total]", "expected": rows[largest]["total"], "tolerance": 0}],
        ("2026-07-01", "2026-07-31"),
        [
            cite(CMS, "Medicare Monthly Enrollment, July 2026 (API, state and national totals)", URLS["enrollment"], "BENE_GEO_LVL=National, TOT_BENES", int(national["TOT_BENES"]), "count", national_snippet, UNSTATED, raw),
            cite(CMS, "Medicare Monthly Enrollment, July 2026 (API, state and national totals)", URLS["enrollment"], "BENE_STATE_ABRVTN=AL, TOT_BENES", rows["AL"]["total"], "count", '"BENE_GEO_LVL":"State","BENE_STATE_ABRVTN":"AL","BENE_STATE_DESC":"Alabama"', UNSTATED, raw),
        ],
        [],
        "Medicare enrolment in July 2026 by state or territory of residence, with the split between Original Medicare and Medicare Advantage and other plans, aged and disabled entitlement, sex, dual eligibility for Medicaid and Part D drug coverage, from the CMS Medicare Monthly Enrollment dataset read through the data.cms.gov API with the month and county-total filters in the URL. The national totals sit in parameters.national. Use the state totals to place synthetic beneficiaries and the splits to assign coverage type." + CMS_NOTE,
        ["healthcare", "medicare", "enrollment", "by-state", "payer", "reference-table"],
        USE_CASES + ["person-generation", "market-sizing"],
        "license-review",
    )
    ages = {"under_25": "AGE_LT_25_BENES", "25_to_44": "AGE_25_TO_44_BENES", "45_to_64": "AGE_45_TO_64_BENES", "65_to_69": "AGE_65_TO_69_BENES", "70_to_74": "AGE_70_TO_74_BENES", "75_to_79": "AGE_75_TO_79_BENES", "80_to_84": "AGE_80_TO_84_BENES", "85_to_89": "AGE_85_TO_89_BENES", "90_to_94": "AGE_90_TO_94_BENES", "95_and_over": "AGE_GT_94_BENES"}
    age_entry = marginal(
        "us-medicare-beneficiaries-by-age-band-2026-07",
        "Medicare beneficiaries by age band, July 2026 (national)",
        "age_band",
        {label: int(national[c]) for label, c in ages.items()},
        ("2026-07-01", "2026-07-31"),
        [
            cite(CMS, "Medicare Monthly Enrollment, July 2026 (API, state and national totals)", URLS["enrollment"], "BENE_GEO_LVL=National, AGE_65_TO_69_BENES", int(national["AGE_65_TO_69_BENES"]), "count", national_snippet, UNSTATED, raw),
            cite(CMS, "Medicare Monthly Enrollment, July 2026 (API, state and national totals)", URLS["enrollment"], "BENE_GEO_LVL=National, AGE_LT_25_BENES", int(national["AGE_LT_25_BENES"]), "count", f'"AGE_LT_25_BENES":"{national["AGE_LT_25_BENES"]}"', UNSTATED, raw),
        ],
        [],
        "The age of Medicare beneficiaries in July 2026 in the ten bands CMS publishes nationally in the Medicare Monthly Enrollment dataset. Beneficiaries under 65 are entitled through disability or end-stage renal disease; the bands weight the age of a synthetic Medicare member." + CMS_NOTE,
        ["healthcare", "medicare", "enrollment", "age", "payer"],
        USE_CASES + ["person-generation"],
        "license-review",
    )
    return [by_state, age_entry]


def hospital_enrollment_entries(raw: bytes, dictionary: bytes) -> list[dict]:
    records = rows_of(raw, encoding="cp1252")
    first = records[0]
    header_snippet = '"ENROLLMENT ID","ENROLLMENT STATE","PROVIDER TYPE CODE","PROVIDER TYPE TEXT"'
    row_snippet = f"{first['ENROLLMENT ID']},{first['ENROLLMENT STATE']},{first['PROVIDER TYPE CODE']},{first['PROVIDER TYPE TEXT']}"
    base_items = [
        cite(CMS, "Hospital Enrollments, extract of 29 September 2026", URLS["hosp_enr"], f"row ENROLLMENT ID {first['ENROLLMENT ID']}, PROVIDER TYPE TEXT", first["PROVIDER TYPE TEXT"], "text", row_snippet, UNSTATED, raw),
        cite(CMS, "Hospital Enrollments, extract of 29 September 2026 (column headings)", URLS["hosp_enr"], "header row", "PROPRIETARY NONPROFIT", "text", header_snippet, UNSTATED, raw),
    ]
    dictionary_item = cite(CMS, "Hospital Enrollments data dictionary", URLS["hosp_dict"], "PROPRIETARY NONPROFIT", "if registered as nonprofit", "text", "if registered as nonprofit", UNSTATED, dictionary, role="supporting")
    period = ("2026-09-29", "2026-09-29")
    by_state = marginal(
        "us-hospital-enrollments-by-state-2026",
        f"Medicare-enrolled hospital practice locations by state, September 2026 ({len(records)} enrolment records)",
        "state",
        dict(sorted(Counter(r["STATE"] for r in records).items())),
        period,
        base_items,
        [{"parameter": "distribution.parameters.counts", "value": "enrolment records per practice-location state", "method": "derived", "rationale": "Counted from the STATE column of the extract; a hospital with several practice locations contributes one record per location."}],
        "Where the hospitals, critical access hospitals and rural emergency hospitals enrolled in Medicare are located, counted from the CMS Hospital Enrollments extract of 29 September 2026 by the state of the practice location. The file holds one record per enrolment and practice location, so multi-site systems weigh more than once. Use it to place synthetic providers." + CMS_NOTE,
        ["healthcare", "hospitals", "medicare", "enrollment", "by-state", "providers"],
        USE_CASES + ["address-generation", "company-generation"],
        "license-review",
    )
    type_labels = {"PART A PROVIDER - HOSPITAL": "hospital", "PART A PROVIDER - CRITICAL ACCESS HOSPITAL": "critical_access_hospital", "PART A PROVIDER - RURAL EMERGENCY HOSPITAL (REH)": "rural_emergency_hospital"}
    by_type = marginal(
        "us-hospital-enrollments-by-provider-type-2026",
        "Medicare-enrolled hospital records by provider type: hospital, critical access hospital, rural emergency hospital, September 2026",
        "provider_type",
        {type_labels[k]: v for k, v in sorted(Counter(r["PROVIDER TYPE TEXT"] for r in records).items())},
        period,
        base_items,
        [{"parameter": "distribution.parameters.counts", "value": "enrolment records per PROVIDER TYPE TEXT", "method": "derived", "rationale": "Counted from the extract; labels shorten the file's Part A provider type texts."}],
        "How Medicare hospital enrolment records split between general hospitals, critical access hospitals and rural emergency hospitals in the CMS Hospital Enrollments extract of 29 September 2026. Gives a synthetic provider directory the right mix of facility types." + CMS_NOTE,
        ["healthcare", "hospitals", "medicare", "enrollment", "provider-type"],
        USE_CASES + ["company-generation"],
        "license-review",
    )
    status_labels = {"N": "nonprofit", "P": "proprietary", "D": "code_d_undocumented"}
    distributions: dict[str, dict] = {}
    by_state_status: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        by_state_status[r["STATE"]][status_labels[r["PROPRIETARY NONPROFIT"]]] += 1
    for state in sorted(by_state_status):
        counts = {label: by_state_status[state].get(label, 0) for label in status_labels.values()}
        total = sum(counts.values())
        distributions[state] = {"family": "categorical", "parameters": {"shares": {k: round(v / total, 6) for k, v in counts.items()}, "counts": counts, "total": total}}
    overall = Counter(r["PROPRIETARY NONPROFIT"] for r in records)
    conditional = {
        "id": "us-hospital-profit-status-by-state-2026",
        "title": "Medicare-enrolled hospital records: proprietary or nonprofit registration given the state, September 2026",
        "kind": "conditional",
        "domain": "healthcare",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": ["healthcare", "hospitals", "medicare", "enrollment", "ownership", "by-state"],
        "use_cases": USE_CASES + ["company-generation"],
        "spec": {"variable": "profit_status", "unit": "ratio", "given": "state", "distributions": distributions},
        "evidence": base_items + [dictionary_item],
        "assumed": [{"parameter": "distributions[*].parameters.shares", "value": "records per PROPRIETARY NONPROFIT code within each state", "method": "derived", "rationale": f"Counted from the extract. The dictionary documents P (proprietor) and N (nonprofit); the code D appears on {overall['D']} records without a published meaning and is kept under its own label."}],
        "tests": [
            {"statistic": stat("share", "TX", "proprietary"), "expected": distributions["TX"]["parameters"]["shares"]["proprietary"], "tolerance": 0.004},
            {"statistic": stat("share", "NY", "nonprofit"), "expected": distributions["NY"]["parameters"]["shares"]["nonprofit"], "tolerance": 0.004},
            {"statistic": stat("sum_of_shares", "CA"), "expected": 1, "tolerance": 1e-4},
        ],
        "notes": "For each state or territory, the share of Medicare hospital enrolment records registered with the IRS as proprietary (for-profit) versus nonprofit, from the PROPRIETARY NONPROFIT flag of the CMS Hospital Enrollments extract of 29 September 2026. Ownership varies strongly by state, so draw it conditionally when generating a synthetic hospital." + CMS_NOTE,
    }
    return [by_state, by_type, conditional]


# ---------------------------------------------------------------------------
# FDA: openFDA counts, recalls and the Orange Book


def openfda_counts(field: str, endpoint: str, raw: bytes) -> tuple[dict[str, int], dict]:
    payload = json.loads(raw)
    key = "term" if "term" in payload["results"][0] else "time"
    counts = {str(r[key]): int(r["count"]) for r in payload["results"]}
    return counts, payload["meta"]


def recall_url(name: str) -> str:
    """openFDA drug enforcement count query over the reports dated inside RECALL_WINDOW."""
    return f"{OPENFDA}/enforcement.json?{RECALL_SEARCH}&count={RECALL_FIELDS[name]}&limit=1000"


def openfda_license_item(license_raw: bytes) -> dict:
    return cite(FDA, "openFDA licence statement", URLS["fda_license"], "License section", "CC0", "text", "related materials on openFDA is public domain and made available with a", CC0, license_raw, role="supporting")


def openfda_ndc_entries(license_raw: bytes, ndc: dict[str, bytes]) -> list[dict]:
    license_item = openfda_license_item(license_raw)
    entries = []
    ndc_fields = {
        "dosage_form": ("dosage_form.exact", "dosage form"),
        "route": ("route.exact", "route of administration"),
        "marketing_category": ("marketing_category", "marketing category (application type)"),
        "product_type": ("product_type.exact", "product type"),
    }
    for variable, (field, label) in ndc_fields.items():
        raw = ndc[variable]
        counts, meta = openfda_counts(field, "ndc", raw)
        url = f"{OPENFDA}/ndc.json?count={field}&limit=1000"
        top = next(iter(counts))
        entries.append(marginal(
            f"us-fda-ndc-{variable.replace('_', '-')}-mix-2026",
            f"FDA National Drug Code directory products by {label}, openFDA snapshot of {meta['last_updated']} ({len(counts)} categories)",
            variable,
            counts,
            (meta["last_updated"], meta["last_updated"]),
            [
                cite(FDA, f"openFDA drug NDC endpoint, count of {field}", url, f"results[term={top}].count", counts[top], "count", f'"term": "{top}",', CC0, raw),
                cite(FDA, f"openFDA drug NDC endpoint, count of {field}", url, "meta.last_updated", meta["last_updated"], "date", '"last_updated":', CC0, raw),
                license_item,
            ],
            [],
            f"How the product listings in the FDA National Drug Code directory split by {label}, counted by the openFDA drug NDC endpoint's count query over its snapshot of {meta['last_updated']}. A product listed with several values of the field counts once under each. The counts weight the {label} of a synthetic drug product; openFDA refreshes the snapshot regularly, so re-run the builder to track it." + OPENFDA_NOTE,
            ["healthcare", "drugs", "ndc", "fda", variable.replace("_", "-")],
            PHARMA_USE_CASES + ["clinical-records"],
            "verified",
        ))
    return entries


def openfda_recall_entries(license_raw: bytes, recalls: dict[str, bytes]) -> list[dict]:
    license_item = openfda_license_item(license_raw)
    first_year, last_year = RECALL_WINDOW[0][:4], RECALL_WINDOW[1][:4]
    weekly, _ = openfda_counts("report_date", "enforcement", recalls["report_date"])
    first_day = next(iter(weekly))
    first_report = f"{first_day[:4]}-{first_day[4:6]}-{first_day[6:]}"
    entries = []
    counts, meta = openfda_counts("classification.exact", "enforcement", recalls["classification"])
    url = recall_url("classification")
    top = next(iter(counts))
    entries.append(marginal(
        "us-fda-drug-recall-classification-mix",
        f"FDA drug enforcement reports by recall classification, {first_year} to {last_year} ({sum(counts.values())} reports)",
        "recall_classification",
        counts,
        RECALL_WINDOW,
        [
            cite(FDA, "openFDA drug enforcement endpoint, count of classification", url, f"results[term={top}].count", counts[top], "count", f'"term": "{top}",', CC0, recalls["classification"]),
            cite(FDA, "openFDA drug enforcement endpoint, count of classification", url, "meta.last_updated", meta["last_updated"], "date", '"last_updated":', CC0, recalls["classification"]),
            license_item,
        ],
        [],
        f"How FDA drug recalls in the enforcement reports dated {RECALL_WINDOW[0]} to {RECALL_WINDOW[1]} split between Class I (reasonable probability of serious harm), Class II and Class III, counted by the openFDA drug enforcement endpoint as of {meta['last_updated']}; the earliest report date in the window is {first_report}. Each count is one product on one recall event. The split gives synthetic recall records a realistic severity mix." + OPENFDA_REFRESH_NOTE + OPENFDA_NOTE,
        ["healthcare", "drugs", "recalls", "fda", "enforcement"],
        PHARMA_USE_CASES,
        "verified",
    ))
    meta = json.loads(recalls["report_date"])["meta"]
    yearly: Counter[str] = Counter()
    for day, n in weekly.items():
        yearly[day[:4]] += n
    years = [y for y in sorted(yearly) if first_year < y <= last_year]
    url = recall_url("report_date")
    entries.append(temporal(
        "us-fda-drug-recalls-by-year",
        f"FDA drug enforcement report entries per year, {years[0]} to {years[-1]}",
        "enforcement_reports",
        "count",
        "annual",
        [{"period": y, "value": float(yearly[y])} for y in years],
        [],
        (f"{years[0]}-01-01", RECALL_WINDOW[1]),
        [
            cite(FDA, "openFDA drug enforcement endpoint, count of report_date", url, f"results[time={first_day}].count", weekly[first_day], "count", f'"time": "{first_day}",', CC0, recalls["report_date"]),
            cite(FDA, "openFDA drug enforcement endpoint, count of report_date", url, "meta.last_updated", meta["last_updated"], "date", '"last_updated":', CC0, recalls["report_date"]),
            license_item,
        ],
        [{"parameter": "series", "value": "sum of weekly report_date counts per calendar year", "method": "derived", "rationale": f"openFDA counts entries per weekly enforcement report date inside the query window; the entry sums them by year and drops {first_year}, whose reports start on {first_report}."}],
        f"The number of drug product entries in FDA weekly enforcement reports per calendar year, summed from the openFDA drug enforcement endpoint's per-date counts as of {meta['last_updated']}. A synthetic pharmacovigilance or recall feed can use it to set annual volume." + OPENFDA_REFRESH_NOTE + OPENFDA_NOTE,
        ["healthcare", "drugs", "recalls", "fda", "time-series"],
        PHARMA_USE_CASES + ["capacity-planning"],
        "verified",
    ))
    return entries


def orange_book_entries(raw: bytes) -> list[dict]:
    products = rows_of(member(raw, "products.txt"), encoding="latin-1", delimiter="~")
    first = products[0]
    snippet = "~".join(first[k] for k in ("Ingredient", "DF;Route", "Trade_Name", "Applicant", "Strength", "Appl_Type", "Appl_No", "Product_No", "TE_Code"))
    items = [
        cite(FDA, "Orange Book data files (products.txt)", URLS["orange_book"], "products.txt, first product row, DF;Route", first["DF;Route"], "text", snippet, UNSTATED, raw),
        cite(FDA, "Orange Book data files (products.txt)", URLS["orange_book"], "products.txt, header row", "TE_Code", "text", "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name", UNSTATED, raw),
    ]
    period = ("2026-10-09", "2026-10-09")
    df_route = marginal(
        "us-fda-orange-book-dosage-form-route-mix-2026",
        f"FDA Orange Book approved drug products by dosage form and route, October 2026 ({len(products)} products)",
        "dosage_form_route",
        dict(sorted(Counter(r["DF;Route"] for r in products).items())),
        period,
        items,
        [{"parameter": "distribution.parameters.counts", "value": "products per DF;Route value", "method": "derived", "rationale": "Counted over every row of products.txt, including discontinued products."}],
        "The dosage form and route combinations of every product in the FDA Orange Book data files published in October 2026, counted over the products table, which lists approved prescription, over-the-counter and discontinued drug products with therapeutic equivalence evaluations. Weight a synthetic prescription's form and route with it. The Orange Book files are republished monthly, so the content hash moves with each edition; the FDA states no licence on the download." ,
        ["healthcare", "drugs", "orange-book", "fda", "dosage-form", "route"],
        PHARMA_USE_CASES + ["clinical-records"],
        "license-review",
    )
    te_counts = Counter(r["TE_Code"] or "not_rated" for r in products)
    te = marginal(
        "us-fda-orange-book-te-code-mix-2026",
        f"FDA Orange Book products by therapeutic equivalence code, October 2026 ({len(products)} products)",
        "te_code",
        dict(sorted(te_counts.items())),
        period,
        items,
        [{"parameter": "distribution.parameters.counts", "value": "products per TE_Code value", "method": "derived", "rationale": "Counted over every row of products.txt; a blank code (discontinued or single-source products) is labelled not_rated."}],
        "How the products in the October 2026 FDA Orange Book split by therapeutic equivalence code (AB, AP, AA and so on, with not_rated for blank codes). Useful for synthetic formulary and generic-substitution data. The files are republished monthly and carry no licence statement.",
        ["healthcare", "drugs", "orange-book", "fda", "therapeutic-equivalence", "generics"],
        PHARMA_USE_CASES,
        "license-review",
    )
    return [df_route, te]


# ---------------------------------------------------------------------------
# CDC NCHS births and causes of death


MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], start=1)}


def births_by_month(raw: bytes) -> dict:
    url = f"{CDC_RESOURCE}/hmz2-vwda.csv?$limit=100000&$order=:id"
    rows = [r for r in rows_of(raw) if r["state"] == "UNITED STATES" and r["period"] == "Monthly"]
    by_period: dict[str, dict[str, float]] = defaultdict(dict)
    labels = {"Number of Live Births": "value", "Number of Deaths": "deaths", "Number of Infant Deaths": "infant_deaths"}
    for r in rows:
        by_period[f"{r['year']}-{MONTHS[r['month']]:02d}"][labels[r["indicator"]]] = float(r["data_value"])
    series = [{"period": p, **by_period[p]} for p in sorted(by_period)]
    first = next(r for r in rows if r["indicator"] == "Number of Live Births")
    return temporal(
        "us-live-births-by-month-2023-2024",
        f"United States provisional live births, deaths and infant deaths by month, {series[0]['period']} to {series[-1]['period']} (NCHS VSRR)",
        "live_births",
        "count",
        "monthly",
        series,
        ["deaths", "infant_deaths"],
        (f"{series[0]['period']}-01", "2024-06-30"),
        [
            cite(CDC, "VSRR State and National Provisional Counts for Live Births, Deaths, and Infant Deaths (Socrata CSV export)", url, f"state=UNITED STATES, year={first['year']}, month={first['month']}, indicator=Number of Live Births, data_value", int(first["data_value"]), "count", f'"UNITED STATES","{first["year"]}","{first["month"]}","Monthly","Number of Live Births","{first["data_value"]}"', UNSTATED, raw),
        ],
        [],
        "Provisional monthly counts of live births, deaths and infant deaths for the United States from the NCHS Vital Statistics Rapid Release, read from the data.cdc.gov export of the state and national provisional counts with a fixed row order. Counts are rounded by NCHS. The month-to-month shape sets the seasonality of synthetic birth and death events." + CDC_NOTE,
        ["healthcare", "births", "deaths", "vital-statistics", "cdc", "time-series", "seasonality"],
        USE_CASES + ["person-generation", "event-timestamps", "clinical-records"],
        "license-review",
    )


def births_by_year(raw: bytes) -> dict:
    url = f"{CDC_RESOURCE}/e6fc-ccez.csv?$limit=100000&$order=:id"
    rows = sorted(rows_of(raw), key=lambda r: r["year"])
    series = [{"period": r["year"], "value": float(r["birth_number"]), "general_fertility_rate": float(r["general_fertility_rate"]), "crude_birth_rate": float(r["crude_birth_rate"])} for r in rows]
    first = rows[0]
    return temporal(
        "us-births-by-year-1909-2018",
        f"United States births, general fertility rate and crude birth rate by year, {rows[0]['year']} to {rows[-1]['year']} (NCHS)",
        "births",
        "count",
        "annual",
        series,
        ["general_fertility_rate", "crude_birth_rate"],
        (f"{rows[0]['year']}-01-01", f"{rows[-1]['year']}-12-31"),
        [
            cite(CDC, "NCHS Births and General Fertility Rates: United States (Socrata CSV export)", url, f"year={first['year']}, birth_number", int(first["birth_number"]), "count", f'"{first["year"]}","{first["birth_number"]}","{first["general_fertility_rate"]}","{first["crude_birth_rate"]}"', UNSTATED, raw),
        ],
        [],
        "Annual births in the United States with the general fertility rate (births per 1,000 women aged 15 to 44) and the crude birth rate (per 1,000 population) from the NCHS national vital statistics series on data.cdc.gov. A long run of official birth counts for ageing a synthetic population or back-filling birth years." + CDC_NOTE,
        ["healthcare", "births", "fertility", "vital-statistics", "cdc", "time-series"],
        USE_CASES + ["person-generation", "household-generation"],
        "license-review",
    )


def leading_causes(raw: bytes) -> dict:
    url = f"{CDC_RESOURCE}/bi63-dtpu.csv?$limit=100000&$order=:id"
    rows = rows_of(raw)
    latest = max(r["year"] for r in rows)
    national = [r for r in rows if r["state"] == "United States" and r["year"] == latest]
    all_causes = next(r for r in national if r["cause_name"] == "All causes")
    named = {r["cause_name"]: int(r["deaths"]) for r in national if r["cause_name"] != "All causes"}
    counts = {**dict(sorted(named.items(), key=lambda kv: -kv[1])), "Other causes": int(all_causes["deaths"]) - sum(named.values())}
    first = next(r for r in national if r["cause_name"] != "All causes")
    return marginal(
        f"us-leading-causes-of-death-{latest}",
        f"United States deaths by leading cause, {latest} (NCHS, ten leading causes and all other causes)",
        "cause_of_death",
        counts,
        (f"{latest}-01-01", f"{latest}-12-31"),
        [
            cite(CDC, "NCHS Leading Causes of Death: United States (Socrata CSV export)", url, f"year={latest}, cause_name={first['cause_name']}, state=United States, deaths", int(first["deaths"]), "count", f'"{latest}","{first["_113_cause_name"]}","{first["cause_name"]}","United States","{first["deaths"]}","{first["aadr"]}"', UNSTATED, raw),
            cite(CDC, "NCHS Leading Causes of Death: United States (Socrata CSV export)", url, f"year={latest}, cause_name=All causes, state=United States, deaths", int(all_causes["deaths"]), "count", f'"{latest}","All Causes","All causes","United States","{all_causes["deaths"]}"', UNSTATED, raw),
        ],
        [{"parameter": "distribution.parameters.counts[Other causes]", "value": "all causes minus the ten named causes", "method": "derived", "rationale": "NCHS publishes the ten leading causes and the all-cause total; the remainder is their difference."}],
        f"Deaths in the United States in {latest} by the ten leading causes NCHS publishes in its leading causes of death series, with every other cause collected into one remainder, so the shares sum to all deaths. {latest} is the last year in the data.cdc.gov series. The cause weights give synthetic mortality or claims data a realistic diagnosis mix." + CDC_NOTE,
        ["healthcare", "deaths", "causes-of-death", "vital-statistics", "cdc"],
        USE_CASES + ["insurance", "clinical-records"],
        "license-review",
    )


# ---------------------------------------------------------------------------
# AHRQ HCUP statistical briefs (tier B)


def hcup_expensive_conditions(raw: bytes) -> dict:
    lines = pdf_lines(raw)
    pattern = re.compile(r"^(\d+) ([A-Z]{3}\d{3}): (.+?) ([\d,]+) ([\d.]+) ([\d,]+) ([\d.]+)$")
    rows: dict[str, dict] = {}
    for line in lines:
        m = pattern.match(line)
        if m and int(m.group(1)) not in {int(r["rank"]) for r in rows.values()} and len(rows) < 20:
            rows[m.group(2)] = {"rank": int(m.group(1)), "condition": m.group(3).rstrip("*"), "aggregate_cost_usd_millions": int(m.group(4).replace(",", "")), "national_cost_percent": float(m.group(5)), "stays_thousands": int(m.group(6).replace(",", "")), "stays_percent": float(m.group(7))}
    totals = next(line for line in lines if line.startswith("Total for all stays"))
    t = re.findall(r"[\d,]+\.?\d*", totals)
    first_key = next(iter(rows))
    first_line = next(line for line in lines if pattern.match(line))
    return lookup(
        "us-hcup-most-expensive-inpatient-conditions-2022",
        "The 20 most expensive conditions treated in US hospitals by aggregate cost, all payers, 2022 (HCUP Statistical Brief 316, Table 1)",
        rows,
        {"year": 2022, "classification": "CCSR for ICD-10-CM principal diagnosis", "all_stays": {"aggregate_cost_usd_millions": int(t[0].replace(",", "")), "stays_thousands": int(t[2].replace(",", ""))}},
        [vector(first_key, "aggregate_cost_usd_millions", rows), vector(first_key, "stays_thousands", rows), vector("CIR019", "condition", rows), {"input": "XXX000", "expected": False, "origin": "derived"}],
        [{"statistic": "max[aggregate_cost_usd_millions]", "expected": rows[first_key]["aggregate_cost_usd_millions"], "tolerance": 0}],
        ("2022-01-01", "2022-12-31"),
        [
            cite(AHRQ, "HCUP Statistical Brief 316: National Inpatient Hospital Costs, the Most Expensive Conditions by Payer, 2022", URLS["hcup_sb316"], "page 3, Table 1, rank 1", f"{rows[first_key]['aggregate_cost_usd_millions']:,}", "currency:USD", first_line, UNSTATED, raw),
            cite(AHRQ, "HCUP Statistical Brief 316: National Inpatient Hospital Costs, the Most Expensive Conditions by Payer, 2022", URLS["hcup_sb316"], "page 3, Table 1, total for all stays", t[0], "currency:USD", totals, UNSTATED, raw),
        ],
        [{"parameter": "all_stays", "value": "totals row of Table 1", "method": "derived", "rationale": "Aggregate cost in millions of dollars and stays in thousands are copied from the table's final row; the PDF is read by text extraction."}],
        "Table 1 of AHRQ's HCUP Statistical Brief 316: the twenty CCSR principal diagnosis categories with the highest aggregate hospital costs across all payers in 2022, with each one's aggregate cost in millions of dollars, share of national inpatient costs, number of stays in thousands and share of stays, from the National Inpatient Sample. Costs are hospital costs, not charges or payments. The table is the natural weight for the principal diagnosis of a synthetic inpatient stay. The brief is a PDF, so the entry is tier B; AHRQ states no licence on the file.",
        ["healthcare", "hospitals", "claims", "diagnoses", "ccsr", "hcup", "costs"],
        USE_CASES + ["claims-generation", "clinical-records"],
        "license-review",
        tier="B",
    )


def hcup_ed_costs(raw: bytes) -> dict:
    lines = pdf_lines(raw)
    start = lines.index(next(line for line in lines if line.startswith("Total 80.3")))
    groups = {"Age group, years": "age_group", "Sex": "sex", "Primary expected payer": "payer", "Community-level income": "community_income", "Location of patient": "residence", "Discharge status": "discharge_status"}
    pattern = re.compile(r"^(.+?) ([\d.]+) ([\d.]+) ([\d,]+) ([\d.]+) ([\d.]+)$")
    rows: dict[str, dict] = {}
    group = "all"
    for line in lines[start:start + 40]:
        for heading, name in groups.items():
            if line.startswith(heading):
                group = name
        m = pattern.match(line)
        if not m:
            continue
        label = m.group(1).rstrip("*†").strip()
        key = re.sub(r"[^a-z0-9]+", "_", label.lower().replace("–", "-")).strip("_")
        rows[key] = {"group": group, "label": label, "aggregate_cost_usd_billions": float(m.group(2)), "cost_percent": float(m.group(3)), "average_cost_per_visit_usd": int(m.group(4).replace(",", "")), "visits_millions": float(m.group(5)), "visits_percent": float(m.group(6))}
        if group == "discharge_status" and key.startswith("all_other"):
            break
    medicare_line = next(line for line in lines if line.startswith("Medicare 22.5"))
    return lookup(
        "us-hcup-ed-visit-costs-by-patient-characteristic-2021",
        "Treat-and-release emergency department visits: aggregate cost, average cost per visit and visits by age, sex, payer, income, residence and disposition, 2021",
        rows,
        {"year": 2021, "source_table": "HCUP Statistical Brief 311, Table 1", "groups": sorted(set(groups.values()) | {"all"})},
        [vector("total", "average_cost_per_visit_usd", rows), vector("medicare", "average_cost_per_visit_usd", rows), vector("medicare", "visits_percent", rows), vector("65", "aggregate_cost_usd_billions", rows), {"input": "tricare", "expected": False, "origin": "derived"}],
        [{"statistic": "max[average_cost_per_visit_usd]", "expected": max(r["average_cost_per_visit_usd"] for r in rows.values()), "tolerance": 0}],
        ("2021-01-01", "2021-12-31"),
        [
            cite(AHRQ, "HCUP Statistical Brief 311: Costs of Treat-and-Release Emergency Department Visits in the United States, 2021", URLS["hcup_sb311"], "page 3, Table 1, Total row", rows["total"]["average_cost_per_visit_usd"], "currency:USD", lines[start], UNSTATED, raw),
            cite(AHRQ, "HCUP Statistical Brief 311: Costs of Treat-and-Release Emergency Department Visits in the United States, 2021", URLS["hcup_sb311"], "page 3, Table 1, Medicare row", "1,040", "currency:USD", medicare_line, UNSTATED, raw),
        ],
        [{"parameter": "rows[*].group", "value": "table section each row sits under", "method": "derived", "rationale": "Table 1 groups its rows under headings; the group column records the heading and the keys are lower-cased labels."}],
        "Table 1 of AHRQ's HCUP Statistical Brief 311: aggregate costs in billions of dollars, share of costs, average cost per visit, visits in millions and share of visits for treat-and-release emergency department visits in 2021, by patient age group, sex, primary expected payer, community income quartile, residence location and discharge status, from the Nationwide Emergency Department Sample. Costs are hospital costs rather than charges. The payer and age rows weight and price synthetic ED encounters. The brief is a PDF, so the entry is tier B; AHRQ states no licence on the file.",
        ["healthcare", "emergency-department", "claims", "costs", "hcup", "payer-mix"],
        USE_CASES + ["claims-generation", "clinical-records"],
        "license-review",
        tier="B",
    )


# ---------------------------------------------------------------------------


def main() -> int:
    write(drg_weights(fetch(URLS["table5"])))
    inp_geo = fetch(URLS["inp_geo"])
    write(inpatient_drg_utilisation(inp_geo))
    write(inpatient_discharges_by_state(inp_geo))
    for entry in inpatient_beneficiary_mix(fetch(URLS["inp_prv"])):
        write(entry)
    write(outpatient_top_apcs(fetch(URLS["out_geo"])))
    write(physician_top_services([fetch(url) for url in PHYSICIAN_PAGES]))
    write(part_d_top_drugs(fetch(URLS["part_d"])))
    write(part_b_top_drugs(fetch(URLS["part_b"])))
    for entry in hcpcs_entries(fetch(URLS["hcpcs"])):
        write(entry)
    write(office_visit_rvus(fetch(URLS["rvu"])))
    for entry in hrrp_entries(fetch(URLS["hrrp"])):
        write(entry)
    write(hac_rates([fetch(url) for url in HAC_PAGES]))
    for entry in enrollment_entries(fetch(URLS["enrollment"])):
        write(entry)
    for entry in hospital_enrollment_entries(fetch(URLS["hosp_enr"]), fetch(URLS["hosp_dict"])):
        write(entry)
    ndc = {variable: fetch(f"{OPENFDA}/ndc.json?count={field}&limit=1000") for variable, field in [("dosage_form", "dosage_form.exact"), ("route", "route.exact"), ("marketing_category", "marketing_category"), ("product_type", "product_type.exact")]}
    recalls = {name: fetch(recall_url(name)) for name in RECALL_FIELDS}
    fda_license = fetch(URLS["fda_license"])
    for entry in [*openfda_ndc_entries(fda_license, ndc), *openfda_recall_entries(fda_license, recalls)]:
        write(entry)
    for entry in orange_book_entries(fetch(URLS["orange_book"])):
        write(entry)
    write(births_by_month(fetch(f"{CDC_RESOURCE}/hmz2-vwda.csv?$limit=100000&$order=:id")))
    write(births_by_year(fetch(f"{CDC_RESOURCE}/e6fc-ccez.csv?$limit=100000&$order=:id")))
    write(leading_causes(fetch(f"{CDC_RESOURCE}/bi63-dtpu.csv?$limit=100000&$order=:id")))
    write(hcup_expensive_conditions(fetch(URLS["hcup_sb316"])))
    write(hcup_ed_costs(fetch(URLS["hcup_sb311"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

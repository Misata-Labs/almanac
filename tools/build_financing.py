"""Regenerate the financing entries: the reference rates, curves, spreads, leverage and lending
conditions that leveraged-buyout models, private credit pricing and valuation discount rates use.

Sources, all official and fetched from pinned URLs:

* Federal Reserve Bank of New York reference rates API: SOFR, the SOFR averages and index, EFFR,
  OBFR, TGCR and BGCR, daily for 2025 and month-end for January to October 2026.
* US Treasury HQM corporate bond yield curve, monthly average spot rates (Excel workbooks).
* Federal Reserve Board: H.15 selected interest rates and the Senior Loan Officer Opinion Survey
  through the Data Download Program, and the Z.1 Financial Accounts CSV archive of one release.
* Bank of England Database: SONIA and Bank Rate, and effective rates on new sterling loans to
  private non-financial corporations and SMEs.
* ECB Data Portal: Euribor monthly averages and bank interest rates on new loans to non-financial
  corporations by loan size and country.
* BIS Data Portal: debt service ratios of non-financial corporations and credit-to-GDP gaps.

The HQM workbooks are legacy Excel (BIFF) files, read with xlrd, which is not a project dependency.
Run from the repository root:

    uv run --with xlrd python tools/build_financing.py
"""

from __future__ import annotations

import copy
import csv
import io
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

TAGS = ["rates", "financing"]
USE_CASES = ["lbo-modelling", "private-credit-demo", "valuation-demo"]

UNSTATED = "unstated"
US_FEDERAL_NOTE = (
    "The publisher is a US federal body and the resource carries no licence statement, so the licence is "
    "recorded as unstated and the entry held at license-review."
)

# Each fetched resource is downloaded once per run, so every entry citing it records the same hash.
_CACHE: dict[str, bytes] = {}


def get(url: str) -> bytes:
    if url not in _CACHE:
        _CACHE[url] = fetch(url)
    return _CACHE[url]


def text_of(raw: bytes, encoding: str = "utf-8") -> str:
    return raw.decode(encoding)


def csv_rows(raw: bytes, encoding: str = "utf-8") -> list[list[str]]:
    return list(csv.reader(io.StringIO(text_of(raw, encoding))))


def csv_dicts(raw: bytes, encoding: str = "utf-8") -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text_of(raw, encoding))))


def num(text: str) -> float:
    return float(text)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def temporal(
    *,
    entry_id: str,
    title: str,
    domain: str,
    region: str,
    status: str,
    start: str,
    end: str,
    variable: str,
    unit: str,
    frequency: str,
    series: list[dict[str, Any]],
    evidence_items: list[dict],
    tags: list[str],
    use_cases: list[str],
    notes: str,
    assumed: list[dict] | None = None,
    extra_tests: list[dict] | None = None,
) -> dict:
    """A temporal entry whose first series column is ``value`` and whose other keys are named columns."""
    columns = [key for key in series[0] if key not in ("period", "value")]
    first, last = series[0], series[-1]
    tests = [
        {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
        {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    if columns:
        tests.append({"statistic": f"column[{columns[-1]},{last['period']}]", "expected": last[columns[-1]], "tolerance": 1e-9})
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": "A",
        "observed_period": {"start": start, "end": end},
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": tests + (extra_tests or []),
        "notes": notes,
    }


def step_rule(
    *,
    entry_id: str,
    title: str,
    region: str,
    status: str,
    steps: list[dict],
    year_end: str,
    evidence_items: list[dict],
    tags: list[str],
    use_cases: list[str],
    notes: str,
    assumed: list[dict],
    series_label: str,
) -> dict:
    # Vectors hold copies so the YAML carries plain values rather than anchors shared with the steps.
    vectors = [{"input": {"on": s["from"]}, "expected": copy.deepcopy(s["value"]), "origin": "source"} for s in steps]
    vectors.append({"input": {"on": year_end}, "expected": copy.deepcopy(steps[-1]["value"]), "origin": "derived", "note": "last step still in force at year end"})
    tests = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(steps), "tolerance": 0},
    ]
    if not isinstance(steps[0]["value"], dict):
        tests.append({"statistic": f"value[{year_end}]", "expected": steps[-1]["value"], "tolerance": 1e-9})
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "rates",
        "region": region,
        "status": status,
        "tier": "A",
        "valid_from": steps[0]["from"],
        "valid_to": None,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {
            "implementation": "almanac.rules.step_schedule",
            "parameters": {"series": series_label, "unit": "percent", "steps": steps},
            "vectors": vectors,
        },
        "evidence": evidence_items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def change_points(days: Iterable[tuple[str, Any]]) -> list[dict]:
    """The first day of a sequence and every later day whose value differs from the day before."""
    steps: list[dict] = []
    for day, value in days:
        if not steps or steps[-1]["value"] != value:
            steps.append({"from": day, "value": value})
    return steps


# ----------------------------------------------------------------------------------------------
# Federal Reserve Bank of New York reference rates
# ----------------------------------------------------------------------------------------------

NYFED = "Federal Reserve Bank of New York"
NYFED_API = "https://markets.newyorkfed.org/api/rates/all/search.csv"
NYFED_2025 = f"{NYFED_API}?startDate=2025-01-01&endDate=2025-12-31"
NYFED_2026 = f"{NYFED_API}?startDate=2026-01-01&endDate=2026-10-31"
NYFED_TITLE_2025 = "Reference rates API, all rates, 2025-01-01 to 2025-12-31 (CSV)"
NYFED_TITLE_2026 = "Reference rates API, all rates, 2026-01-01 to 2026-10-31 (CSV)"
NYFED_TAGS = TAGS + ["reference-rates", "money-market", "daily-series", "new-york-fed"]
NYFED_USE_CASES = USE_CASES + ["treasury-demo", "banking-demo", "loan-pricing"]
NYFED_NOTE = (
    "Rates are published by the New York Fed each business day for the previous business day; dates are the "
    "effective dates of the rates. The API's terms of use are on an HTML page that is not byte-stable, so the "
    "licence is recorded as unstated and the entry held at license-review."
)


def nyfed_rows(raw: bytes) -> dict[str, list[list[str]]]:
    """Rows of the all-rates CSV grouped by rate type, oldest first, with ISO dates in column 0."""
    rows = csv_rows(raw)[1:]
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows:
        if not row:
            continue
        iso = datetime.strptime(row[0], "%m/%d/%Y").date().isoformat()
        grouped[row[1]].append([iso] + row[1:])
    for rows_of_type in grouped.values():
        rows_of_type.sort(key=lambda r: r[0])
    return grouped


def us_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%m/%d/%Y")


def nyfed_line(row: list[str]) -> str:
    return ",".join([us_date(row[0])] + row[1:])


def nyfed_ev(raw: bytes, url: str, title: str, row: list[str], column: int, label: str, unit: str = "percent") -> dict:
    return evidence(NYFED, title, url, f"row Effective Date={us_date(row[0])}, Rate Type={row[1]}, {label}", row[column], unit, nyfed_line(row), UNSTATED, raw)


def sofr_daily() -> dict:
    raw = get(NYFED_2025)
    rows = nyfed_rows(raw)["SOFR"]
    series = [
        {
            "period": r[0],
            "value": num(r[2]),
            "percentile_1": num(r[3]),
            "percentile_25": num(r[4]),
            "percentile_75": num(r[5]),
            "percentile_99": num(r[6]),
            "volume_usd_billions": num(r[7]),
        }
        for r in rows
    ]
    return temporal(
        entry_id="us-nyfed-sofr-daily-2025",
        title="Secured Overnight Financing Rate (SOFR) with percentiles and volume, every business day of 2025",
        domain="rates", region="US", status="license-review", start=rows[0][0], end=rows[-1][0],
        variable="sofr_percent", unit="percent", frequency="daily", series=series,
        evidence_items=[
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows[0], 2, "Rate (%)"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows[-1], 6, "99th Percentile (%)"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows[-1], 7, "Volume ($Billions)", "decimal"),
        ],
        tags=NYFED_TAGS + ["sofr", "secured-funding"], use_cases=NYFED_USE_CASES,
        notes=(
            "SOFR, the New York Fed's secured overnight reference rate for borrowing against Treasury collateral, for each business day "
            "of 2025, with the 1st, 25th, 75th and 99th volume-weighted percentiles and the underlying volume in "
            "billions of US dollars, from the New York Fed reference rates API. SOFR is the base rate for most new "
            "US dollar floating-rate loans, including leveraged and private credit loans priced at SOFR plus a "
            "spread. " + NYFED_NOTE
        ),
    )


def sofr_averages() -> dict:
    raw = get(NYFED_2025)
    rows = nyfed_rows(raw)["SOFRAI"]
    series = [
        {"period": r[0], "value": num(r[13]), "average_90_day": num(r[14]), "average_180_day": num(r[15]), "sofr_index": num(r[16])}
        for r in rows
    ]
    return temporal(
        entry_id="us-nyfed-sofr-averages-and-index-daily-2025",
        title="SOFR 30-, 90- and 180-day averages and SOFR Index, every business day of 2025",
        domain="rates", region="US", status="license-review", start=rows[0][0], end=rows[-1][0],
        variable="sofr_30_day_average_percent", unit="percent", frequency="daily", series=series,
        evidence_items=[
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows[0], 13, "30-Day Average SOFR"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows[-1], 16, "SOFR Index", "decimal"),
            evidence(NYFED, NYFED_TITLE_2025, NYFED_2025, "header row", "SOFR Index", "text", "30-Day Average SOFR,90-Day Average SOFR,180-Day Average SOFR,SOFR Index", UNSTATED, raw, role="supporting"),
        ],
        tags=NYFED_TAGS + ["sofr", "compounded-rates"], use_cases=NYFED_USE_CASES,
        notes=(
            "Compounded averages of SOFR over rolling 30, 90 and 180 calendar days, in percent, and the SOFR Index "
            "(a cumulative compounding index), for each publication day of 2025, "
            "from the New York Fed reference rates API (rate type SOFRAI). Loan agreements that compound SOFR in "
            "arrears use the index ratio between two dates. " + NYFED_NOTE
        ),
    )


def effr_obfr() -> dict:
    raw = get(NYFED_2025)
    grouped = nyfed_rows(raw)
    effr, obfr = grouped["EFFR"], {r[0]: r for r in grouped["OBFR"]}
    series = []
    for r in effr:
        o = obfr[r[0]]
        series.append({
            "period": r[0],
            "value": num(r[2]),
            "effr_percentile_1": num(r[3]),
            "effr_percentile_99": num(r[6]),
            "effr_volume_usd_billions": num(r[7]),
            "target_range_lower": num(r[8]),
            "target_range_upper": num(r[9]),
            "obfr": num(o[2]),
            "obfr_percentile_1": num(o[3]),
            "obfr_percentile_99": num(o[6]),
            "obfr_volume_usd_billions": num(o[7]),
        })
    return temporal(
        entry_id="us-nyfed-effr-and-obfr-daily-2025",
        title="Effective federal funds rate and overnight bank funding rate with target range, every business day of 2025",
        domain="rates", region="US", status="license-review", start=effr[0][0], end=effr[-1][0],
        variable="effr_percent", unit="percent", frequency="daily", series=series,
        evidence_items=[
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, effr[0], 2, "Rate (%)"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, effr[-1], 9, "Target Rate To (%)"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, grouped["OBFR"][-1], 7, "Volume ($Billions)", "decimal"),
        ],
        tags=NYFED_TAGS + ["fed-funds", "unsecured-funding", "policy-rate"], use_cases=NYFED_USE_CASES,
        notes=(
            "The effective federal funds rate (EFFR) and the overnight bank funding rate (OBFR), the New York Fed's "
            "unsecured overnight reference rates, for each business day of 2025, with their 1st and 99th "
            "percentiles, volumes in billions of US dollars, and the FOMC target range in force that day. "
            + NYFED_NOTE
        ),
    )


def tgcr_bgcr() -> dict:
    raw = get(NYFED_2025)
    grouped = nyfed_rows(raw)
    tgcr, bgcr = grouped["TGCR"], {r[0]: r for r in grouped["BGCR"]}
    series = []
    for r in tgcr:
        b = bgcr[r[0]]
        series.append({
            "period": r[0],
            "value": num(r[2]),
            "tgcr_percentile_1": num(r[3]),
            "tgcr_percentile_99": num(r[6]),
            "tgcr_volume_usd_billions": num(r[7]),
            "bgcr": num(b[2]),
            "bgcr_percentile_1": num(b[3]),
            "bgcr_percentile_99": num(b[6]),
            "bgcr_volume_usd_billions": num(b[7]),
        })
    return temporal(
        entry_id="us-nyfed-tgcr-and-bgcr-daily-2025",
        title="Tri-party general collateral rate (TGCR) and broad general collateral rate (BGCR), every business day of 2025",
        domain="rates", region="US", status="license-review", start=tgcr[0][0], end=tgcr[-1][0],
        variable="tgcr_percent", unit="percent", frequency="daily", series=series,
        evidence_items=[
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, tgcr[0], 2, "Rate (%)"),
            nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, grouped["BGCR"][-1], 7, "Volume ($Billions)", "decimal"),
        ],
        tags=NYFED_TAGS + ["repo", "secured-funding"], use_cases=NYFED_USE_CASES,
        notes=(
            "TGCR (overnight Treasury general collateral repo in the tri-party market) and BGCR (TGCR plus GCF repo "
            "transactions) for each business day of 2025, with 1st and 99th percentiles and volumes in billions of "
            "US dollars. Together with SOFR they describe secured overnight funding costs. " + NYFED_NOTE
        ),
    )


def nyfed_month_end_2026() -> dict:
    raw = get(NYFED_2026)
    grouped = nyfed_rows(raw)

    def month_end(rate: str) -> dict[str, list[str]]:
        last: dict[str, list[str]] = {}
        for r in grouped[rate]:
            last[r[0][:7]] = r
        return last

    sofr, effr, obfr, tgcr, bgcr, avg = (month_end(t) for t in ("SOFR", "EFFR", "OBFR", "TGCR", "BGCR", "SOFRAI"))
    months = sorted(sofr)
    series = [
        {
            "period": m,
            "value": num(sofr[m][2]),
            "effr": num(effr[m][2]),
            "obfr": num(obfr[m][2]),
            "tgcr": num(tgcr[m][2]),
            "bgcr": num(bgcr[m][2]),
            "sofr_30_day_average": num(avg[m][13]),
            "sofr_index": num(avg[m][16]),
            "target_range_upper": num(effr[m][9]),
        }
        for m in months
    ]
    last_month = months[-1]
    return temporal(
        entry_id="us-nyfed-reference-rates-month-end-2026-01-to-2026-10",
        title="US overnight reference rates at each month end, January to October 2026 (SOFR, EFFR, OBFR, TGCR, BGCR)",
        domain="rates", region="US", status="license-review", start="2026-01-01", end="2026-10-31",
        variable="sofr_percent", unit="percent", frequency="monthly", series=series,
        evidence_items=[
            nyfed_ev(raw, NYFED_2026, NYFED_TITLE_2026, sofr[months[0]], 2, "Rate (%)"),
            nyfed_ev(raw, NYFED_2026, NYFED_TITLE_2026, sofr[last_month], 2, "Rate (%)"),
            nyfed_ev(raw, NYFED_2026, NYFED_TITLE_2026, avg[last_month], 16, "SOFR Index", "decimal"),
            nyfed_ev(raw, NYFED_2026, NYFED_TITLE_2026, effr[last_month], 9, "Target Rate To (%)"),
        ],
        assumed=[{
            "parameter": "series",
            "value": "last published business day of each month",
            "method": "derived",
            "rationale": "The API publishes daily values; each month's row takes, rate by rate, the value for the last effective date in that month in the pinned January to October 2026 download.",
        }],
        tags=NYFED_TAGS + ["sofr", "fed-funds", "month-end"], use_cases=NYFED_USE_CASES + ["financial-reporting"],
        notes=(
            "Month-end values of the New York Fed's five overnight reference rates, the 30-day SOFR average, the "
            "SOFR Index and the upper bound of the FOMC target range for January to October 2026, taken from one "
            "pinned API download covering those ten closed months. Month-end rates are what loan interest periods, "
            "fund NAV statements and valuation dates usually reference. " + NYFED_NOTE
        ),
    )


def fed_funds_target_range() -> dict:
    raw = get(NYFED_2025)
    effr = nyfed_rows(raw)["EFFR"]
    steps = change_points((r[0], {"lower": num(r[8]), "upper": num(r[9])}) for r in effr)
    rows_by_day = {r[0]: r for r in effr}
    items = [nyfed_ev(raw, NYFED_2025, NYFED_TITLE_2025, rows_by_day[s["from"]], 9, "Target Rate To (%)") for s in steps]
    return step_rule(
        entry_id="us-fomc-federal-funds-target-range-changes-2025",
        title="FOMC federal funds target range in force through 2025, with the first effective date of each change",
        region="US", status="license-review", steps=steps, year_end="2025-12-31", evidence_items=items,
        tags=NYFED_TAGS + ["fed-funds", "policy-rate", "step-schedule"], use_cases=NYFED_USE_CASES,
        series_label="FOMC target range for the federal funds rate (lower and upper bound, percent)",
        assumed=[{
            "parameter": "steps",
            "value": "change dates read from the daily target-range columns",
            "method": "derived",
            "rationale": "The schedule starts at the first EFFR publication of 2025 and adds a step on each effective date whose target range differs from the previous business day's, as recorded alongside EFFR in the New York Fed API.",
        }],
        notes=(
            "The FOMC's target range for the federal funds rate as a step schedule over 2025: the range in force on "
            "the first business day of the year and each later change, dated by the first effective date on which "
            "the New York Fed records the new range alongside EFFR. Each step's value carries the lower and upper "
            "bound in percent. " + NYFED_NOTE
        ),
    )


# ----------------------------------------------------------------------------------------------
# US Treasury HQM corporate bond yield curve
# ----------------------------------------------------------------------------------------------

TREASURY = "US Department of the Treasury"
HQM_BASE = "https://home.treasury.gov/system/files/226"
HQM_MATURITIES = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 75.0, 100.0]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def hqm_curve(raw: bytes, years: range) -> list[dict]:
    """Monthly average spot rates for the kept maturities, one series point per month in ``years``."""
    import xlrd  # legacy .xls reader, supplied with `uv run --with xlrd`

    sheet = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
    year_row, month_row = sheet.row_values(3), sheet.row_values(4)
    columns: dict[str, int] = {}
    year = None
    for col in range(2, sheet.ncols):
        if str(year_row[col]).strip():
            year = int(float(year_row[col]))
        if year in years and month_row[col] in MONTHS:
            columns[f"{year}-{MONTHS.index(month_row[col]) + 1:02d}"] = col
    maturity_rows = {float(sheet.cell_value(r, 0)): r for r in range(6, sheet.nrows) if isinstance(sheet.cell_value(r, 0), float)}
    series = []
    for period, col in columns.items():
        values = {m: sheet.cell_value(maturity_rows[m], col) for m in HQM_MATURITIES}
        if any(v == "" for v in values.values()):
            continue
        point: dict[str, Any] = {"period": period, "value": float(values[10.0])}
        for m in HQM_MATURITIES:
            if m != 10.0:
                point[f"y{str(m).rstrip('0').rstrip('.').replace('.', '_')}"] = float(values[m])
        series.append(point)
    return series


def hqm(file_name: str, years: range, entry_id: str, drift_note: str) -> dict:
    url = f"{HQM_BASE}/{file_name}"
    raw = get(url)
    series = hqm_curve(raw, years)
    title = f"HQM Corporate Bond Yield Curve Spot Rates workbook {file_name} (Excel)"
    return temporal(
        entry_id=entry_id,
        title=f"US Treasury HQM corporate bond spot yield curve, monthly averages {years[0]}-{years[-1]}, 6 months to 100 years",
        domain="rates", region="US", status="license-review",
        start=f"{years[0]}-01-01", end=f"{years[-1]}-12-31",
        variable="hqm_spot_rate_10y_percent", unit="percent", frequency="monthly", series=series,
        evidence_items=[
            evidence(TREASURY, title, url, "sheet 1, cell A1", "The Treasury High Quality Market (HQM) Corporate Bond Yield Curve", "text", "The Treasury High Quality Market (HQM) Corporate Bond Yield Curve", UNSTATED, raw),
            evidence(TREASURY, title, url, "sheet 1, cell A2", "Monthly Average Spot Rates, Percent", "text", "Monthly Average Spot Rates, Percent", UNSTATED, raw),
        ],
        assumed=[{
            "parameter": "columns",
            "value": "maturities 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 75 and 100 years",
            "method": "derived",
            "rationale": "The workbook lists every half year from 0.5 to 100 years; sixteen standard maturities are kept to size the entry. Intermediate maturities can be read from the cited workbook.",
        }],
        tags=TAGS + ["discount-rates", "yield-curve", "corporate-bonds", "treasury"],
        use_cases=USE_CASES + ["pensions", "financial-reporting", "treasury-demo"],
        notes=(
            "Monthly average spot (zero-coupon) rates of the Treasury's High Quality Market (HQM) corporate bond "
            "yield curve, which the Treasury publishes alongside its papers on the corporate bond yield curve and "
            "the Pension Protection Act. The value is the 10-year spot rate; columns y<n> carry the n-year spot rate "
            "(y0_5 is six months). It is the official discount curve for high-quality US corporate cash flows. The workbook is a legacy binary Excel file, so the verifier confirms its "
            "identity by hash and its labels by text, while the rates were read cell by cell with xlrd. "
            + drift_note + " " + US_FEDERAL_NOTE
        ),
        extra_tests=[{"statistic": "column[y30,%s]" % series[0]["period"], "expected": series[0]["y30"], "tolerance": 1e-9}],
    )


# ----------------------------------------------------------------------------------------------
# Federal Reserve Board: H.15, SLOOS (Data Download Program) and Z.1 Financial Accounts
# ----------------------------------------------------------------------------------------------

FED = "Board of Governors of the Federal Reserve System"
FED_DDP = "https://www.federalreserve.gov/datadownload/Output.aspx"
H15_URL = f"{FED_DDP}?rel=H15&series=d7e27b7b09a3a7feae95b9c61781fcd8&from=01/01/2025&to=12/31/2025&filetype=csv&label=include&layout=seriescolumn&type=package"
SLOOS_URL = f"{FED_DDP}?rel=SLOOS&series=e64f07187815f0e7ed89237d8cb91eeb&lastobs=&from=&to=&filetype=csv&label=include&layout=seriescolumn&type=package"
DDP_NOTE = (
    "The Board has announced that the Data Download Program's preformatted packages are withdrawn on 31 March 2027 "
    "and the DDP pages on 1 July 2027, after which this URL will stop resolving."
)

H15_COLUMNS = {
    "RIFSPFF_N.M": "effr",
    "RIFSPPNAAD30_N.M": "cp_nonfinancial_aa_30d",
    "RIFSPPNAAD60_N.M": "cp_nonfinancial_aa_60d",
    "RIFSPPNAAD90_N.M": "cp_nonfinancial_aa_90d",
    "RIFSPPFAAD30_N.M": "cp_financial_aa_30d",
    "RIFSPPFAAD60_N.M": "cp_financial_aa_60d",
    "RIFSPPFAAD90_N.M": "cp_financial_aa_90d",
    "RIFSPBLP_N.M": "prime",
    "RIFSRP_F02_N.M": "primary_credit",
    "RIFSGFSW04_N.M": "tbill_4w_discount",
    "RIFSGFSM03_N.M": "tbill_3m_discount",
    "RIFSGFSM06_N.M": "tbill_6m_discount",
    "RIFSGFSY01_N.M": "tbill_1y_discount",
    "RIFLGFCM01_N.M": "cmt_1m",
    "RIFLGFCM03_N.M": "cmt_3m",
    "RIFLGFCM06_N.M": "cmt_6m",
    "RIFLGFCY01_N.M": "cmt_1y",
    "RIFLGFCY02_N.M": "cmt_2y",
    "RIFLGFCY03_N.M": "cmt_3y",
    "RIFLGFCY05_N.M": "cmt_5y",
    "RIFLGFCY07_N.M": "cmt_7y",
    "RIFLGFCY10_N.M": "cmt_10y",
    "RIFLGFCY20_N.M": "cmt_20y",
    "RIFLGFCY30_N.M": "cmt_30y",
    "RIFLGFCY05_XII_N.M": "tips_5y",
    "RIFLGFCY07_XII_N.M": "tips_7y",
    "RIFLGFCY10_XII_N.M": "tips_10y",
    "RIFLGFCY20_XII_N.M": "tips_20y",
    "RIFLGFCY30_XII_N.M": "tips_30y",
    "RIFLGFL_XII_N.M": "tips_long_term_average",
}


def ddp_table(raw: bytes) -> tuple[list[str], list[str], list[list[str]]]:
    """Series descriptions, series codes and data rows of a Data Download Program package CSV."""
    rows = csv_rows(raw)
    header_end = next(i for i, r in enumerate(rows) if r and r[0] == "Time Period")
    return rows[0], rows[header_end], [r for r in rows[header_end + 1:] if r]


def h15() -> dict:
    raw = get(H15_URL)
    descriptions, codes, data = ddp_table(raw)
    index = {code: i for i, code in enumerate(codes)}
    value_code = "RIFSPBLP_N.M"
    # A series with any "ND" (no data) month is left out, because every series point must carry every column.
    gaps = [code for code in H15_COLUMNS if any(row[index[code]] == "ND" for row in data)]
    series = []
    for row in data:
        point: dict[str, Any] = {"period": row[0], "value": num(row[index[value_code]])}
        for code, name in H15_COLUMNS.items():
            if code != value_code and code not in gaps:
                point[name] = num(row[index[code]])
        series.append(point)
    assumed = [{
        "parameter": "columns",
        "value": ", ".join(H15_COLUMNS[code] for code in gaps),
        "method": "derived",
        "rationale": "These series report ND (no data) for at least one month of 2025 in the package and are left out so every month carries the same columns.",
    }] if gaps else []
    first, last = data[0], data[-1]
    title = "Data Download Program, H.15 Selected Interest Rates, monthly averages package, 2025 (CSV)"
    return temporal(
        entry_id="us-h15-selected-interest-rates-monthly-2025",
        title="US H.15 selected interest rates, monthly averages 2025: prime, commercial paper, bills, constant maturities, TIPS",
        domain="rates", region="US", status="license-review", start="2025-01-01", end="2025-12-31",
        variable="bank_prime_loan_rate_percent", unit="percent", frequency="monthly", series=series, assumed=assumed,
        evidence_items=[
            evidence(FED, title, H15_URL, f"row {first[0]}, column {value_code}", first[index[value_code]], "percent", ",".join(first[:9]), UNSTATED, raw),
            evidence(FED, title, H15_URL, f"row {last[0]}, column RIFLGFCY30_N.M", last[index["RIFLGFCY30_N.M"]], "percent", ",".join(last[:6]), UNSTATED, raw),
            evidence(FED, title, H15_URL, f"Series Description, column {value_code}", "Average majority prime rate charged by banks", "text", "Average majority prime rate charged by banks", UNSTATED, raw, role="supporting"),
            evidence(FED, title, H15_URL, "Series Description, column RIFSPPNAAD90_N.M", "90-Day AA Nonfinancial Commercial Paper Interest Rate", "text", "90-Day AA Nonfinancial Commercial Paper Interest Rate", UNSTATED, raw, role="supporting"),
        ],
        tags=TAGS + ["prime-rate", "commercial-paper", "yield-curve", "treasury", "h15"],
        use_cases=USE_CASES + ["treasury-demo", "banking-demo", "loan-pricing"],
        notes=(
            "Monthly averages for 2025 of the series in the Federal Reserve's H.15 monthly package: the bank "
            "prime loan rate (the value), the effective federal funds rate, AA nonfinancial and financial commercial "
            "paper at 30, 60 and 90 days, the discount window primary credit rate, Treasury bill rates on a "
            "discount basis, nominal Treasury constant maturities from 1 month to 30 years, and TIPS real constant "
            "maturities from 5 to 30 years with their long-term average. Columns are named from the Board's series "
            "codes (cmt_ for nominal constant maturity, tips_ for inflation-indexed); a series with a month of no data "
            "is left out (see assumed). " + DDP_NOTE + " " + US_FEDERAL_NOTE
        ),
    )


SLOOS_DESCRIPTIONS = {
    "standards_ci_large_middle_market": "tightening standards for C&I loans to large and middle-market firms",
    "standards_ci_small_firms": "tightening standards for C&I loans to small firms",
    "spreads_ci_large_middle_market": "increasing spreads of loan rates over banks' cost of funds to large and middle-market firms",
    "spreads_ci_small_firms": "increasing spreads of loan rates over banks' cost of funds to small firms",
    "demand_ci_large_middle_market": "reporting stronger demand for C&I loans from large and middle-market firms",
    "demand_ci_small_firms": "reporting stronger demand for C&I loans from small firms",
    "standards_cre_construction_land": "tightening standards for commercial real estate loans with construction & land development purposes",
    "standards_cre_nonfarm_nonresidential": "tightening standards for commercial real estate loans secured by nonfarm nonresidential structures",
    "standards_cre_multifamily": "tightening standards for commercial real estate loans secured by multifamily residential structures",
}


def sloos() -> dict:
    raw = get(SLOOS_URL)
    descriptions, codes, data = ddp_table(raw)
    # Resolve each column by its published description, so the mapping cannot drift from the codes.
    by_description = {d.removeprefix("Net percentage of domestic banks ").strip(): i for i, d in enumerate(descriptions)}
    index = {name: by_description[text] for name, text in SLOOS_DESCRIPTIONS.items()}
    kept = [r for r in data if r[0] >= "2015Q1"]
    value_name = "standards_ci_large_middle_market"
    series = []
    for row in kept:
        point: dict[str, Any] = {"period": row[0], "value": num(row[index[value_name]])}
        for name in SLOOS_DESCRIPTIONS:
            if name != value_name:
                point[name] = num(row[index[name]])
        series.append(point)
    first, last = kept[0], kept[-1]
    title = "Data Download Program, Senior Loan Officer Opinion Survey, all chart data package (CSV)"
    value_code = codes[index[value_name]]
    return temporal(
        entry_id="us-sloos-business-lending-standards-spreads-demand-quarterly-2015q1-2026q4",
        title="US Senior Loan Officer Survey: net shares of banks tightening C&I and CRE standards, raising spreads, seeing demand, 2015-2026",
        domain="economy", region="US", status="license-review", start="2015-01-01", end="2026-10-31",
        variable="net_percent_tightening_ci_standards_large_middle_market", unit="percent", frequency="quarterly", series=series,
        assumed=[{
            "parameter": "observed_period.end",
            "value": "2026-10-31",
            "method": "derived",
            "rationale": "The package's last period is 2026Q4 while the Board's SLOOS page lists the October 2026 survey as the latest, so each quarter label is read as the survey conducted in that quarter and the period is closed at the end of October 2026 rather than at the end of the quarter.",
        }],
        evidence_items=[
            evidence(FED, title, SLOOS_URL, f"row {first[0]}, column {value_code}", first[index[value_name]], "percent", ",".join(first[:8]), UNSTATED, raw),
            evidence(FED, title, SLOOS_URL, f"row {last[0]}, column {value_code}", last[index[value_name]], "percent", ",".join(last[:8]), UNSTATED, raw),
            evidence(FED, title, SLOOS_URL, f"Series Description, column {value_code}", "Net percentage of domestic banks tightening standards for C&I loans to large and middle-market firms", "text", "tightening standards for C&I loans to large and middle-market firms", UNSTATED, raw, role="supporting"),
            evidence(FED, title, SLOOS_URL, "Series Description", "increasing spreads of loan rates over banks' cost of funds to small firms", "text", "increasing spreads of loan rates over banks' cost of funds to small firms", UNSTATED, raw, role="supporting"),
        ],
        tags=TAGS + ["credit", "lending-standards", "leading-indicator", "sloos"],
        use_cases=USE_CASES + ["banking-demo", "credit-risk"],
        notes=(
            "Net percentages of domestic banks in the Federal Reserve's Senior Loan Officer Opinion Survey that "
            "tightened standards on commercial and industrial loans (to large and middle-market firms, the value, "
            "and to small firms), increased spreads of loan rates over their cost of funds, reported stronger C&I "
            "loan demand, and tightened standards on three kinds of commercial real estate loans, quarterly from "
            "2015Q1 to 2026Q4. Each quarter label is read as the survey conducted in that quarter (2026Q4 is the "
            "October 2026 survey, the latest listed on the Board's SLOOS page); a positive net percentage means more banks tightened, raised spreads or saw "
            "stronger demand than the reverse. The package holds all observations, so it changes when the next "
            "survey is published and the hash then needs refreshing. " + DDP_NOTE + " "
            + US_FEDERAL_NOTE
        ),
    )


Z1_RELEASE = "20260911"
Z1_URL = f"https://www.federalreserve.gov/releases/z1/{Z1_RELEASE}/z1_csv_files.zip"
Z1_TITLE = "Financial Accounts of the United States (Z.1), release of 11 September 2026, CSV archive"
Z1_NOTE = (
    "Figures come from the CSV archive of the Z.1 release of 11 September 2026, pinned by its dated URL, which "
    "covers data to 2026Q2; later releases revise history and live at their own dated URLs."
)


def z1_table(raw: bytes, member: str) -> tuple[list[str], dict[str, list[str]]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = list(csv.reader(io.StringIO(archive.read(member).decode("utf-8"))))
    return rows[0], {r[0]: r for r in rows[1:] if r}


def z1_series(raw: bytes, member: str, value_code: str, columns: dict[str, str], keep: Callable[[str], bool]) -> tuple[list[dict], list[str], dict[str, list[str]]]:
    """Series points for the kept periods of one Z.1 table, with the table's header and rows by period."""
    header, rows = z1_table(raw, member)
    index: dict[str, int] = {}
    for i, code in enumerate(header):
        index.setdefault(code, i)
    series = []
    for period in (p for p in rows if keep(p)):
        row = rows[period]
        point: dict[str, Any] = {"period": period.replace(":", "-"), "value": num(row[index[value_code]])}
        for code, name in columns.items():
            point[name] = num(row[index[code]])
        series.append(point)
    return series, header, rows


def z1_quarterly(p: str) -> bool:
    return bool(re.fullmatch(r"\d{4}:Q[1-4]", p)) and p >= "2015:Q1"


def z1_ev(raw: bytes, member: str, row: list[str], code: str, header: list[str], unit: str) -> dict:
    i = header.index(code)
    return evidence(FED, Z1_TITLE, Z1_URL, f"{member}, row {row[0]}, column {code}", row[i], unit, ",".join(row[:4]), UNSTATED, raw)


def z1_corporate() -> dict:
    raw = get(Z1_URL)
    member = "csv/S11_1_b.csv"
    columns = {
        "FL102000005.Q": "total_assets_usd_millions",
        "FL104190005.Q": "total_liabilities_usd_millions",
        "FL104122005.Q": "debt_securities_usd_millions",
        "FL103163005.Q": "corporate_bonds_usd_millions",
        "FL103169100.Q": "commercial_paper_usd_millions",
        "FL104135005.Q": "loans_usd_millions",
        "FL103168005.Q": "depository_institution_loans_usd_millions",
        "FL103167205.Q": "private_credit_loans_usd_millions",
        "FL103165005.Q": "mortgages_usd_millions",
        "LM103164105.Q": "corporate_equities_market_value_usd_millions",
        "FL102090005.Q": "net_worth_usd_millions",
        "FL104104016.Q": "debt_percent_of_equities_market_value",
        "FL103164106.Q": "equities_percent_of_net_worth",
    }
    value_code = "FL104104006.Q"
    series, header, rows = z1_series(raw, member, value_code, columns, z1_quarterly)
    first, last = rows[series[0]["period"].replace("-", ":")], rows[series[-1]["period"].replace("-", ":")]
    return temporal(
        entry_id="us-z1-nonfinancial-corporate-balance-sheet-leverage-quarterly-2015q1-2026q2",
        title="US nonfinancial corporate business balance sheet and leverage, quarterly 2015Q1-2026Q2 (Z.1 S.11.1.b)",
        domain="economy", region="US", status="license-review", start="2015-01-01", end="2026-06-30",
        variable="debt_percent_of_net_worth_market_value", unit="percent", frequency="quarterly", series=series,
        evidence_items=[
            z1_ev(raw, member, first, value_code, header, "percent"),
            z1_ev(raw, member, last, value_code, header, "percent"),
            z1_ev(raw, member, last, "FL103167205.Q", header, "currency:USD"),
            evidence(FED, Z1_TITLE, Z1_URL, "data_dictionary/S11_1_b.txt, line 50", "debt as a percentage of net worth (market value)", "text", "Nonfinancial corporate business; debt as a percentage of net worth (market value)", UNSTATED, raw, role="supporting"),
            evidence(FED, Z1_TITLE, Z1_URL, "data_dictionary/S11_1_b.txt, line 37", "private credit loans; liability", "text", "Nonfinancial corporate business; private credit loans; liability", UNSTATED, raw, role="supporting"),
        ],
        tags=TAGS + ["leverage", "credit", "corporate-debt", "flow-of-funds", "z1"],
        use_cases=USE_CASES + ["credit-risk", "synthetic-companies"],
        notes=(
            "Balance sheet of the US nonfinancial corporate business sector (Z.1 table S.11.1.b), end of quarter, "
            "not seasonally adjusted, 2015Q1 to 2026Q2: the value is debt as a percentage of net worth at market "
            "value; columns carry total assets and liabilities, debt securities (corporate bonds, commercial paper), "
            "loans (depository institution loans, private credit loans, mortgages), corporate equities at market "
            "value and net worth in millions of US dollars, and the Board's debt-to-equity and equity-to-net-worth "
            "percentages. Debt here is debt securities plus loans. " + Z1_NOTE + " " + US_FEDERAL_NOTE
        ),
    )


def z1_noncorporate() -> dict:
    raw = get(Z1_URL)
    member = "csv/S11_2_b.csv"
    columns = {
        "FL112000005.Q": "total_assets_usd_millions",
        "FL114190005.Q": "total_liabilities_usd_millions",
        "FL114135005.Q": "loans_usd_millions",
        "FL113168005.Q": "depository_institution_loans_usd_millions",
        "FL113167205.Q": "private_credit_loans_usd_millions",
        "FL113165005.Q": "mortgages_usd_millions",
        "FL113169005.Q": "other_loans_usd_millions",
        "FL112090005.Q": "net_worth_usd_millions",
    }
    value_code = "FL114104006.Q"
    series, header, rows = z1_series(raw, member, value_code, columns, z1_quarterly)
    first, last = rows[series[0]["period"].replace("-", ":")], rows[series[-1]["period"].replace("-", ":")]
    return temporal(
        entry_id="us-z1-nonfinancial-noncorporate-balance-sheet-quarterly-2015q1-2026q2",
        title="US nonfinancial noncorporate business balance sheet and debt to net worth, quarterly 2015Q1-2026Q2 (Z.1 S.11.2.b)",
        domain="economy", region="US", status="license-review", start="2015-01-01", end="2026-06-30",
        variable="debt_percent_of_net_worth", unit="percent", frequency="quarterly", series=series,
        evidence_items=[
            z1_ev(raw, member, first, value_code, header, "percent"),
            z1_ev(raw, member, last, value_code, header, "percent"),
            z1_ev(raw, member, last, "FL113167205.Q", header, "currency:USD"),
            evidence(FED, Z1_TITLE, Z1_URL, "data_dictionary/S11_2_b.txt, line 45", "debt as a percentage of net worth", "text", "Nonfinancial noncorporate business; debt as a percentage of net worth", UNSTATED, raw, role="supporting"),
        ],
        tags=TAGS + ["leverage", "credit", "small-business", "flow-of-funds", "z1"],
        use_cases=USE_CASES + ["credit-risk", "synthetic-companies"],
        notes=(
            "Balance sheet of the US nonfinancial noncorporate business sector (unincorporated businesses; "
            "Z.1 table S.11.2.b), end of quarter, not seasonally adjusted, 2015Q1 to 2026Q2: the "
            "value is debt as a percentage of net worth; columns carry total assets and liabilities, loans by kind "
            "(depository institution, private credit, mortgages, other) and net worth in millions of US dollars. "
            + Z1_NOTE + " " + US_FEDERAL_NOTE
        ),
    )


def z1_income() -> dict:
    raw = get(Z1_URL)
    member = "csv/S11_1_i_a.csv"
    columns = {
        "FU106902501.A": "gross_value_added_usd_millions",
        "FU106300003.A": "consumption_of_fixed_capital_usd_millions",
        "FU106402101.A": "net_operating_surplus_usd_millions",
        "FU106130101.A": "interest_received_usd_millions",
        "FU106121001.A": "dividends_paid_usd_millions",
        "FU106220001.A": "current_taxes_on_income_usd_millions",
    }
    value_code = "FU106130001.A"
    series, header, rows = z1_series(raw, member, value_code, columns, lambda p: p.isdigit() and "2015" <= p <= "2025")
    first, last = rows[series[0]["period"]], rows[series[-1]["period"]]
    return temporal(
        entry_id="us-z1-nonfinancial-corporate-interest-paid-and-operating-surplus-annual-2015-2025",
        title="US nonfinancial corporate business interest paid, operating surplus and value added, annual 2015-2025 (Z.1 S.11.1.i)",
        domain="economy", region="US", status="license-review", start="2015-01-01", end="2025-12-31",
        variable="interest_paid_usd_millions", unit="currency:USD", frequency="annual", series=series,
        evidence_items=[
            z1_ev(raw, member, first, value_code, header, "currency:USD"),
            z1_ev(raw, member, last, value_code, header, "currency:USD"),
            evidence(FED, Z1_TITLE, Z1_URL, "data_dictionary/S11_1_i_a.txt, line 16", "interest paid", "text", "Nonfinancial corporate business; interest paid", UNSTATED, raw, role="supporting"),
        ],
        tags=TAGS + ["interest-coverage", "credit", "corporate-income", "flow-of-funds", "z1"],
        use_cases=USE_CASES + ["credit-risk", "synthetic-companies"],
        notes=(
            "Annual income account of the US nonfinancial corporate business sector (Z.1 table S.11.1.i, annual), "
            "2015 to 2025, in millions of US dollars: interest paid (the value), gross value added, consumption of "
            "fixed capital, net operating surplus, interest received, dividends paid and current taxes on income. "
            "Net operating surplus plus interest received over interest paid gives a sector-wide interest coverage "
            "benchmark; the Z.1 publishes interest flows only annually. " + Z1_NOTE + " " + US_FEDERAL_NOTE
        ),
    )


# ----------------------------------------------------------------------------------------------
# Bank of England Database
# ----------------------------------------------------------------------------------------------

BOE = "Bank of England"
BOE_DB = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
BOE_DAILY_URL = f"{BOE_DB}&Datefrom=01/Jan/2025&Dateto=31/Dec/2025&SeriesCodes=IUDSOIA,IUDBEDR&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
BOE_LOANS_CODES = ["CFMBJ82", "CFMBJ83", "CFMBJ84", "CFMZ6LD", "CFMZJ3L", "CFMZJ3M", "CFMZJ3Q", "CFMZJ3U", "CFMZJ3V", "CFMZJ3W", "CFMZJ3X"]
BOE_LOANS_URL = f"{BOE_DB}&Datefrom=01/Jan/2024&Dateto=30/Sep/2026&SeriesCodes={','.join(BOE_LOANS_CODES)}&CSVF=TT&UsingCodes=Y&VPD=Y&VFD=N"
BOE_LICENSE = "OGL-UK-3.0"
BOE_NOTE = (
    "The Bank of England's legal notice states that reproduction of data in its Statistical Interactive Database "
    "is subject to the UK Open Government Licence; that page is not byte-stable, so the statement is not cited "
    "as evidence and the entry is held at license-review until the clause is confirmed."
)
BOE_TAGS = TAGS + ["bank-of-england", "sterling"]


def boe_date(text: str) -> str:
    return datetime.strptime(text, "%d %b %Y").date().isoformat()


def boe_table(raw: bytes) -> tuple[list[str], list[list[str]], dict[str, str]]:
    """Header and data rows of a Bank of England database CSV, with series titles when present."""
    lines = text_of(raw, "latin-1").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("DATE,"))
    titles = {}
    for line in lines[:start]:
        if "," in line and not line.startswith("SERIES,"):
            code, title = line.split(",", 1)
            titles[code] = title
    rows = [r for r in csv.reader(lines[start:]) if r]
    return rows[0], rows[1:], titles


def sonia_daily() -> dict:
    raw = get(BOE_DAILY_URL)
    header, rows, _ = boe_table(raw)
    sonia, bank_rate = header.index("IUDSOIA"), header.index("IUDBEDR")
    series = [{"period": boe_date(r[0]), "value": num(r[sonia]), "bank_rate": num(r[bank_rate])} for r in rows]
    title = "Bank of England Database, series IUDSOIA and IUDBEDR, daily 2025 (CSV)"
    return temporal(
        entry_id="gb-sonia-daily-2025",
        title="Sterling Overnight Index Average (SONIA) with Bank Rate, every London business day of 2025",
        domain="rates", region="GB", status="license-review", start=series[0]["period"], end=series[-1]["period"],
        variable="sonia_percent", unit="percent", frequency="daily", series=series,
        evidence_items=[
            evidence(BOE, title, BOE_DAILY_URL, f"row DATE={rows[0][0]}, IUDSOIA", rows[0][sonia], "percent", ",".join(rows[0]), BOE_LICENSE, raw),
            evidence(BOE, title, BOE_DAILY_URL, f"row DATE={rows[-1][0]}, IUDSOIA", rows[-1][sonia], "percent", ",".join(rows[-1]), BOE_LICENSE, raw),
            evidence(BOE, title, BOE_DAILY_URL, "header row", "IUDSOIA", "text", "DATE,IUDSOIA,IUDBEDR", BOE_LICENSE, raw, role="supporting"),
        ],
        tags=BOE_TAGS + ["sonia", "reference-rates", "daily-series"],
        use_cases=USE_CASES + ["treasury-demo", "banking-demo", "loan-pricing"],
        notes=(
            "SONIA (series IUDSOIA), the risk-free overnight reference rate for sterling loans and derivatives, and "
            "Bank Rate (series IUDBEDR) for each London business day of 2025, in percent, from the Bank of England "
            "Database. Sterling floating-rate corporate loans are commonly priced at compounded SONIA plus a margin. "
            + BOE_NOTE
        ),
    )


def bank_rate_changes() -> dict:
    raw = get(BOE_DAILY_URL)
    header, rows, _ = boe_table(raw)
    column = header.index("IUDBEDR")
    steps = change_points((boe_date(r[0]), num(r[column])) for r in rows)
    by_day = {boe_date(r[0]): r for r in rows}
    title = "Bank of England Database, series IUDSOIA and IUDBEDR, daily 2025 (CSV)"
    items = [
        evidence(BOE, title, BOE_DAILY_URL, f"row DATE={by_day[s['from']][0]}, IUDBEDR", by_day[s["from"]][column], "percent", ",".join(by_day[s["from"]]), BOE_LICENSE, raw)
        for s in steps
    ]
    return step_rule(
        entry_id="gb-bank-rate-changes-2025",
        title="Bank of England Bank Rate in force through 2025, with the effective date of each change",
        region="GB", status="license-review", steps=steps, year_end="2025-12-31", evidence_items=items,
        tags=BOE_TAGS + ["policy-rate", "step-schedule"], use_cases=USE_CASES + ["treasury-demo", "banking-demo", "loan-pricing"],
        series_label="IUDBEDR (Official Bank Rate, daily)",
        assumed=[{
            "parameter": "steps",
            "value": "change dates read from the daily Bank Rate series",
            "method": "derived",
            "rationale": "The schedule starts at the first business day of 2025 and adds a step on each business day whose Bank Rate differs from the previous business day's in the daily IUDBEDR series.",
        }],
        notes=(
            "Bank of England Bank Rate as a step schedule over 2025: the rate on the first business day of the year "
            "and each later change, dated by the first business day on which the daily series IUDBEDR shows the new "
            "rate. " + BOE_NOTE
        ),
    )


BOE_LOAN_COLUMNS = {
    "CFMBJ83": "pnfc_floating",
    "CFMBJ84": "pnfc_fixed",
    "CFMZ6LD": "sme",
    "CFMZJ3L": "sme_floating",
    "CFMZJ3M": "sme_floating_bank_rate_linked",
    "CFMZJ3Q": "sme_floating_sonia_linked",
    "CFMZJ3U": "sme_fixed",
    "CFMZJ3V": "sme_fixed_up_to_1y",
    "CFMZJ3W": "sme_fixed_1y_to_5y",
    "CFMZJ3X": "sme_fixed_over_5y",
}


def boe_new_loans() -> dict:
    raw = get(BOE_LOANS_URL)
    header, rows, _ = boe_table(raw)
    index = {code: header.index(code) for code in BOE_LOANS_CODES}
    series = []
    for r in rows:
        point: dict[str, Any] = {"period": boe_date(r[0])[:7], "value": num(r[index["CFMBJ82"]])}
        for code, name in BOE_LOAN_COLUMNS.items():
            point[name] = num(r[index[code]])
        series.append(point)
    title = "Bank of England Database, effective interest rates on new sterling loans to PNFCs and SMEs, monthly (CSV)"
    last = rows[-1]
    return temporal(
        entry_id="gb-pnfc-and-sme-new-loan-interest-rates-monthly-2024-01-to-2026-09",
        title="UK effective interest rates on new sterling loans to private non-financial corporations and SMEs, monthly 2024-2026",
        domain="rates", region="GB", status="license-review", start="2024-01-01", end="2026-09-30",
        variable="pnfc_new_loans_rate_percent", unit="percent", frequency="monthly", series=series,
        evidence_items=[
            evidence(BOE, title, BOE_LOANS_URL, f"row DATE={rows[0][0]}, CFMBJ82", rows[0][index["CFMBJ82"]], "percent", ",".join(rows[0]), BOE_LICENSE, raw),
            evidence(BOE, title, BOE_LOANS_URL, f"row DATE={last[0]}, CFMZ6LD", last[index["CFMZ6LD"]], "percent", ",".join(last), BOE_LICENSE, raw),
            evidence(BOE, title, BOE_LOANS_URL, "series title, CFMBJ82", "other loans - new advances to private non-financial corporations", "text", "Weighted average interest rate - other loans - new advances to private non-financial corporations (in percent)", BOE_LICENSE, raw, role="supporting"),
        ],
        tags=BOE_TAGS + ["lending-rates", "corporate-loans", "sme"],
        use_cases=USE_CASES + ["banking-demo", "loan-pricing"],
        notes=(
            "Monthly weighted average interest rates charged by UK monetary financial institutions on new sterling "
            "loans (other than overdrafts) to private non-financial corporations, January 2024 to September 2026, in "
            "percent, from the Bank of England Database: all PNFCs (CFMBJ82, the value), floating and fixed rate "
            "(CFMBJ83, CFMBJ84), and small and medium-sized PNFCs in total (CFMZ6LD), floating rate (CFMZJ3L, of "
            "which Bank Rate linked CFMZJ3M and SONIA linked CFMZJ3Q) and fixed rate (CFMZJ3U, by initial fixation "
            "up to 1 year, 1 to 5 years and over 5 years: CFMZJ3V, CFMZJ3W, CFMZJ3X). The series by loan size "
            "(CFMBJ88, CFMBJ89, CFMBJ92) and by fixation for all PNFCs return no observations for this period and "
            "are not included. Recent months can be revised in later releases. " + BOE_NOTE
        ),
    )


# ----------------------------------------------------------------------------------------------
# ECB Data Portal
# ----------------------------------------------------------------------------------------------

ECB = "European Central Bank"
ECB_API = "https://data-api.ecb.europa.eu/service/data"
ECB_LICENSE = "ECB-free-use-with-attribution"
ECB_NOTE = (
    "The ECB's website disclaimer states that users may make free use of information obtained from it provided it is "
    "reproduced accurately and the ECB is cited as the source; the clause is carried by the licence identifier "
    "ECB-free-use-with-attribution documented in CONTRIBUTING.md."
)
EURIBOR_URL = f"{ECB_API}/FM/M.U2.EUR.RT.MM.EURIBOR1MD_+EURIBOR3MD_+EURIBOR6MD_+EURIBOR1YD_.HSTA?startPeriod=2015-01&endPeriod=2025-12&format=csvdata"
MIR_SIZE_URL = f"{ECB_API}/MIR/M..B.A2A.A.R.0+1.2240.EUR.N?startPeriod=2025-01&endPeriod=2025-12&format=csvdata"


def euribor() -> dict:
    raw = get(EURIBOR_URL)
    rows = csv_dicts(raw)
    by_tenor: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        by_tenor[r["PROVIDER_FM_ID"]][r["TIME_PERIOD"]] = r["OBS_VALUE"]
    periods = sorted(by_tenor["EURIBOR3MD_"])
    series = [
        {
            "period": p,
            "value": num(by_tenor["EURIBOR3MD_"][p]),
            "euribor_1m": num(by_tenor["EURIBOR1MD_"][p]),
            "euribor_6m": num(by_tenor["EURIBOR6MD_"][p]),
            "euribor_12m": num(by_tenor["EURIBOR1YD_"][p]),
        }
        for p in periods
    ]
    three = [r for r in rows if r["PROVIDER_FM_ID"] == "EURIBOR3MD_"]
    title = "ECB Data Portal, Euribor 1, 3, 6 and 12 months, monthly averages (SDMX CSV)"
    return temporal(
        entry_id="eu-euribor-monthly-averages-2015-2025",
        title="Euribor 1-, 3-, 6- and 12-month rates, monthly averages 2015-2025",
        domain="rates", region="EU", status="license-review", start="2015-01-01", end="2025-12-31",
        variable="euribor_3m_percent", unit="percent", frequency="monthly", series=series,
        evidence_items=[
            evidence(ECB, title, EURIBOR_URL, f"KEY={three[0]['KEY']}, TIME_PERIOD={three[0]['TIME_PERIOD']}, OBS_VALUE", three[0]["OBS_VALUE"], "percent", f"{three[0]['TIME_PERIOD']},{three[0]['OBS_VALUE']}", ECB_LICENSE, raw),
            evidence(ECB, title, EURIBOR_URL, f"KEY={three[-1]['KEY']}, TIME_PERIOD={three[-1]['TIME_PERIOD']}, OBS_VALUE", three[-1]["OBS_VALUE"], "percent", f"{three[-1]['TIME_PERIOD']},{three[-1]['OBS_VALUE']}", ECB_LICENSE, raw),
            evidence(ECB, title, EURIBOR_URL, "TITLE_COMPL", "provided by Refinitiv", "text", "Euribor 3-month - Historical close, average of observations through period", ECB_LICENSE, raw, role="supporting"),
        ],
        tags=TAGS + ["euribor", "money-market", "ecb", "euro-area"],
        use_cases=USE_CASES + ["treasury-demo", "banking-demo", "loan-pricing"],
        notes=(
            "Monthly averages of daily Euribor fixings at 1, 3, 6 and 12 months (3 months is the value), January "
            "2015 to December 2025, in percent, from the ECB Data Portal's financial market dataset. Euribor is the "
            "usual base rate of euro-denominated floating-rate corporate loans. The ECB's series titles state that "
            "the data are provided by Refinitiv and Euribor is a third-party benchmark, so "
            "redistribution may be subject to third-party terms beyond the ECB's free-use clause; the entry is held "
            "at license-review for that reason. The ECB series was preferred to Eurostat's irt_st_m because "
            "Eurostat's CSV embeds a last-update timestamp that changes every month. " + ECB_NOTE
        ),
    )


def mir_by_size() -> dict:
    raw = get(MIR_SIZE_URL)
    rows = csv_dicts(raw)
    values: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        if r["OBS_VALUE"]:
            values[f"{r['REF_AREA']}.{r['AMOUNT_CAT']}"][r["TIME_PERIOD"]] = r["OBS_VALUE"]
    periods = sorted(values["U2.0"])
    complete = sorted(key for key, by_period in values.items() if all(p in by_period for p in periods))
    areas = sorted({key.split(".")[0] for key in complete if f"{key.split('.')[0]}.0" in complete and f"{key.split('.')[0]}.1" in complete} - {"U2"})
    size = {"0": "up_to_1m", "1": "over_1m"}
    series = []
    for p in periods:
        point: dict[str, Any] = {"period": p, "value": num(values["U2.0"][p]), "u2_over_1m": num(values["U2.1"][p])}
        for area in areas:
            for cat in ("0", "1"):
                point[f"{area.lower()}_{size[cat]}"] = num(values[f"{area}.{cat}"][p])
        series.append(point)
    first = next(r for r in rows if r["REF_AREA"] == "U2" and r["AMOUNT_CAT"] == "0" and r["TIME_PERIOD"] == periods[0])
    last = next(r for r in rows if r["REF_AREA"] == "U2" and r["AMOUNT_CAT"] == "1" and r["TIME_PERIOD"] == periods[-1])
    title = "ECB Data Portal, MFI interest rate statistics, loans to corporations by amount, new business (SDMX CSV)"
    return temporal(
        entry_id="eu-nfc-new-loan-rates-by-size-and-country-monthly-2025",
        title="Euro area bank interest rates on new loans to corporations up to and over EUR 1 million, by country, monthly 2025",
        domain="rates", region="EU", status="verified", start="2025-01-01", end="2025-12-31",
        variable="u2_up_to_1m_percent", unit="percent", frequency="monthly", series=series,
        evidence_items=[
            evidence(ECB, title, MIR_SIZE_URL, f"KEY={first['KEY']}, TIME_PERIOD={periods[0]}, OBS_VALUE", first["OBS_VALUE"], "percent", f"{first['KEY']},", ECB_LICENSE, raw),
            evidence(ECB, title, MIR_SIZE_URL, f"KEY={last['KEY']}, TIME_PERIOD={periods[-1]}, OBS_VALUE", last["OBS_VALUE"], "percent", f"{last['KEY']},", ECB_LICENSE, raw),
            evidence(ECB, title, MIR_SIZE_URL, "TITLE", "Bank interest rates on loans to corporations of up to EUR 1M (new business)", "text", "Bank interest rates on loans to corporations of up to EUR 1M (new business)", ECB_LICENSE, raw),
            evidence(ECB, title, MIR_SIZE_URL, "TITLE", "Bank interest rates on loans to corporations of over EUR 1M (new business)", "text", "Bank interest rates on loans to corporations of over EUR 1M (new business)", ECB_LICENSE, raw),
        ],
        tags=TAGS + ["lending-rates", "corporate-loans", "sme", "ecb", "euro-area"],
        use_cases=USE_CASES + ["banking-demo", "loan-pricing"],
        notes=(
            "Annualised agreed rates charged by euro area banks on new euro loans to non-financial corporations, "
            "split by loan amount: up to EUR 1 million, a proxy for SME "
            "lending, and over EUR 1 million, monthly for 2025, for the euro area (u2, the value is up to EUR 1 "
            f"million) and the {len(areas)} countries in the dataset with both series complete for the year. Columns are "
            "<country>_up_to_1m and <country>_over_1m in percent; the gap between them is the size premium small "
            "borrowers pay. " + ECB_NOTE
        ),
    )


# ----------------------------------------------------------------------------------------------
# BIS Data Portal
# ----------------------------------------------------------------------------------------------

BIS = "Bank for International Settlements"
BIS_LICENSE = "BIS terms and conditions (statistics subject to 'About BIS statistics' terms)"
BIS_DSR_URL = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_DSR/1.0/Q..N?startPeriod=2015-Q1&endPeriod=2025-Q4&format=csv&labels=both"
BIS_GAP_URL = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CREDIT_GAP/1.0/Q..P.A.C?startPeriod=2015-Q1&endPeriod=2025-Q4&format=csv&labels=both"
BIS_NOTE = (
    "The BIS terms and conditions allow use of statistics from the BIS Data Portal under the terms on its 'About "
    "BIS statistics' page, which is not an SPDX licence, so the entry is held at license-review. BIS revises "
    "history when it adds a quarter, so the pinned query can change after a release."
)


def bis_panel(raw: bytes, value_area: str) -> tuple[list[dict], list[dict], list[str]]:
    rows = csv_dicts(raw)
    values: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        if r["OBS_VALUE"] not in ("", "NaN"):
            values[r["BORROWERS_CTY"]][r["TIME_PERIOD"]] = r["OBS_VALUE"]
    periods = sorted(values[value_area])
    areas = sorted(a for a, by_period in values.items() if a != value_area and all(p in by_period for p in periods))
    series = []
    for p in periods:
        point: dict[str, Any] = {"period": p, "value": num(values[value_area][p])}
        for area in areas:
            point[area.lower()] = num(values[area][p])
        series.append(point)
    return series, rows, areas


def bis_line(raw: bytes, row: dict) -> str:
    """The raw CSV line of one country and quarter, used as a verbatim snippet."""
    prefix, period = f"Q,Quarterly,{row['BORROWERS_CTY']},", f",{row['TIME_PERIOD']},"
    return next(line for line in text_of(raw).splitlines() if line.startswith(prefix) and period in line)


def bis_dsr() -> dict:
    raw = get(BIS_DSR_URL)
    series, rows, areas = bis_panel(raw, "US")
    first = next(r for r in rows if r["BORROWERS_CTY"] == "US" and r["TIME_PERIOD"] == series[0]["period"])
    last = next(r for r in rows if r["BORROWERS_CTY"] == "US" and r["TIME_PERIOD"] == series[-1]["period"])
    title = "BIS Data Portal, dataflow WS_DSR (debt service ratios), non-financial corporations (CSV with labels)"
    return temporal(
        entry_id="global-bis-debt-service-ratio-nonfinancial-corporations-quarterly-2015-2025",
        title="Debt service ratio of non-financial corporations, quarterly 2015-2025, seventeen economies (BIS)",
        domain="economy", region="global", status="license-review", start="2015-01-01", end="2025-12-31",
        variable="us_dsr_percent", unit="percent", frequency="quarterly", series=series,
        evidence_items=[
            evidence(BIS, title, BIS_DSR_URL, f"BORROWERS_CTY=US, TIME_PERIOD={first['TIME_PERIOD']}, OBS_VALUE", first["OBS_VALUE"], "percent", bis_line(raw, first), BIS_LICENSE, raw),
            evidence(BIS, title, BIS_DSR_URL, f"BORROWERS_CTY=US, TIME_PERIOD={last['TIME_PERIOD']}, OBS_VALUE", last["OBS_VALUE"], "percent", bis_line(raw, last), BIS_LICENSE, raw),
        ],
        tags=TAGS + ["leverage", "credit", "debt-service", "bis"],
        use_cases=USE_CASES + ["credit-risk", "banking-demo"],
        notes=(
            "The BIS debt service ratio for the non-financial corporate sector, in per cent of income, quarterly from 2015Q1 to 2025Q4, for the United States (the value) and "
            f"{len(areas)} other economies (columns named by lower-case ISO country code). It benchmarks how much "
            "of corporate income goes to servicing debt across countries. " + BIS_NOTE
        ),
    )


def bis_gap() -> dict:
    raw = get(BIS_GAP_URL)
    series, rows, areas = bis_panel(raw, "US")
    first = next(r for r in rows if r["BORROWERS_CTY"] == "US" and r["TIME_PERIOD"] == series[0]["period"])
    last = next(r for r in rows if r["BORROWERS_CTY"] == "US" and r["TIME_PERIOD"] == series[-1]["period"])
    title = "BIS Data Portal, dataflow WS_CREDIT_GAP (credit-to-GDP gaps), private non-financial sector (CSV with labels)"
    return temporal(
        entry_id="global-bis-credit-to-gdp-gap-quarterly-2015-2025",
        title="Credit-to-GDP gap of the private non-financial sector, quarterly 2015-2025, forty-four economies (BIS)",
        domain="economy", region="global", status="license-review", start="2015-01-01", end="2025-12-31",
        variable="us_credit_to_gdp_gap_points", unit="percent", frequency="quarterly", series=series,
        evidence_items=[
            evidence(BIS, title, BIS_GAP_URL, f"BORROWERS_CTY=US, TIME_PERIOD={first['TIME_PERIOD']}, OBS_VALUE", first["OBS_VALUE"], "percent", bis_line(raw, first), BIS_LICENSE, raw),
            evidence(BIS, title, BIS_GAP_URL, f"BORROWERS_CTY=US, TIME_PERIOD={last['TIME_PERIOD']}, OBS_VALUE", last["OBS_VALUE"], "percent", bis_line(raw, last), BIS_LICENSE, raw),
            evidence(BIS, title, BIS_GAP_URL, "CG_DTYPE label", "Credit-to-GDP gaps (actual-trend)", "text", "C,Credit-to-GDP gaps (actual-trend)", BIS_LICENSE, raw, role="supporting"),
        ],
        tags=TAGS + ["credit", "credit-cycle", "leading-indicator", "bis"],
        use_cases=USE_CASES + ["credit-risk", "banking-demo"],
        notes=(
            "The BIS credit-to-GDP gap: total credit to the private non-financial sector as a percentage of GDP "
            "minus its long-run trend (HP filter), in percentage points of GDP, quarterly 2015Q1 to "
            f"2025Q4, for the United States (the value) and {len(areas)} other economies (columns named by "
            "lower-case BIS area code). A large positive gap means credit has grown faster than its trend. " + BIS_NOTE
        ),
    )


BUILDERS: list[Callable[[], dict]] = [
    sofr_daily,
    sofr_averages,
    effr_obfr,
    tgcr_bgcr,
    nyfed_month_end_2026,
    fed_funds_target_range,
    lambda: hqm("hqm_19_23.xls", range(2020, 2024), "us-treasury-hqm-corporate-spot-curve-monthly-2020-2023",
                "The 2019-2023 workbook is closed and unchanged since January 2024."),
    lambda: hqm("hqm_24_28.xls", range(2024, 2026), "us-treasury-hqm-corporate-spot-curve-monthly-2024-2025",
                "The 2024-2028 workbook gains a month each month until 2028, so its hash changes monthly and the entry must be rebuilt to re-verify."),
    h15,
    sloos,
    z1_corporate,
    z1_noncorporate,
    z1_income,
    sonia_daily,
    bank_rate_changes,
    boe_new_loans,
    euribor,
    mir_by_size,
    bis_dsr,
    bis_gap,
]


def main() -> int:
    for build in BUILDERS:
        write(build())
    return 0


if __name__ == "__main__":
    sys.exit(main())

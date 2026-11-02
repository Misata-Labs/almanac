"""Regenerate the transport entries: fatal-crash marginals from NHTSA FARS, recalls from the NHTSA
Socrata dataset, EPA fuel-economy marginals for the latest model year, FAA aircraft-registry and
airport (NASR) distributions, BTS border crossings, DVLA licensed-vehicle and registration tables,
DfT road traffic and STATS19 collision marginals, DVSA MOT results, ORR rail journeys, CAA airport
passengers and Eurostat car-age, rail and maritime series. Run from the repository root:

    uv run python tools/build_transport.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from xml.etree import ElementTree as ET

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402
from build_eurostat_extended import (  # noqa: E402
    GEO_KEY,
    LICENSE as EUROSTAT_LICENSE,
    LICENSE_NOTE as EUROSTAT_NOTE,
    PUBLISHER as EUROSTAT,
    codelist,
    data_url,
    dataflow_title,
    flag_sentence,
    flagged_cells,
    rows_of,
)

OGL = "OGL-UK-3.0"
UNSTATED = "unstated"
US_LICENSE_NOTE = (
    "The publisher states no licence on the file itself, so the licence is recorded as unstated and the entry "
    "held at license-review even though US federal publications are normally free to reuse."
)
SOCRATA_NOTE = (
    "The dataset's Socrata metadata declares the licence as Public Domain, which has no SPDX identifier in this "
    "repository, so the licence is recorded as unstated and the entry held at license-review."
)
MAX_SNIPPET_WORDS = 25

NHTSA = "National Highway Traffic Safety Administration"
EPA = "US Environmental Protection Agency and US Department of Energy (fueleconomy.gov)"
FAA = "Federal Aviation Administration"
BTS = "Bureau of Transportation Statistics"
DFT = "Department for Transport"
DVSA = "Driver and Vehicle Standards Agency"
ORR = "Office of Rail and Road"
CAA = "UK Civil Aviation Authority"

FARS_YEAR = 2023
FARS_URL = f"https://static.nhtsa.gov/nhtsa/downloads/FARS/{FARS_YEAR}/National/FARS{FARS_YEAR}NationalCSV.zip"
RECALLS_YEAR = 2024
RECALLS_API = "https://data.transportation.gov/resource/6axg-epim.csv"
EPA_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip"
EPA_MODEL_YEAR = "2025"
FAA_REGISTRY_YEAR = 2025
FAA_REGISTRY_URL = f"https://registry.faa.gov/database/yearly/ReleasableAircraft.{FAA_REGISTRY_YEAR}.zip"
FAA_LAYOUT_URL = "https://registry.faa.gov/database/ardata.pdf"
NASR_CYCLE = date(2026, 10, 29)
NASR_URL = f"https://nfdc.faa.gov/webContent/28DaySub/extra/{NASR_CYCLE:%d_%b_%Y}_APT_CSV.zip"
BORDER_YEAR = 2024
BORDER_API = "https://data.bts.gov/resource/keg4-3bc2.csv"
VEH0120_URL = "https://assets.publishing.service.gov.uk/media/6aad4b12ce3f006bd4346ccf/df_VEH0120_GB.csv"
VEH0160_URL = "https://assets.publishing.service.gov.uk/media/6aad4b1d086ce7c57b8186f4/df_VEH0160_GB.csv"
DVLA_QUARTER = "2026 Q2"
DVLA_REGISTRATIONS_FROM = "2024 Q1"
TRA0101_URL = "https://assets.publishing.service.gov.uk/media/6a0b7b9ec75cc34a8ff8f481/tra0101-miles-by-vehicle-type.ods"
TRA0104_URL = "https://assets.publishing.service.gov.uk/media/6a0b7be9f7c2e79c33db9143/tra0104-miles-by-vehicle-and-road-type.ods"
STATS19_YEAR = 2024
COLLISION_URL = f"https://data.dft.gov.uk/road-accidents-safety-data/dft-road-casualty-statistics-collision-{STATS19_YEAR}.csv"
VEHICLE_URL = f"https://data.dft.gov.uk/road-accidents-safety-data/dft-road-casualty-statistics-vehicle-{STATS19_YEAR}.csv"
STATS20_URL = "https://assets.publishing.service.gov.uk/media/6925a35433d088f6d5da2cf0/STATS20_2024_specification.pdf"
MOT_FINANCIAL_YEAR = "2024 to 2025"
MOT_RESULTS_URL = "https://assets.publishing.service.gov.uk/media/6a6cbc31cceb23e8678977c3/dvsa-mot-01-mot-test-results-by-class-of-vehicle.csv"
MOT_DEFECTS_URL = "https://assets.publishing.service.gov.uk/media/6a6cbc4c8319ab05f7caa2e7/dvsa-mot-03-mot-class-3-and-4-vehicles-initial-failures-by-defect-category.csv"
ORR_URL = "https://dataportal.orr.gov.uk/media/1652/table-1220-passenger-journeys.ods"
CAA_URL = "https://www.caa.co.uk/Documents/Download/24007/87fb7670-4e10-4aeb-942d-509238aa25a1/17551"
CAA_YEAR = "2025"

_cache: dict[str, bytes] = {}


def get(url: str) -> bytes:
    """Fetch a resource once per run; several entries share the larger archives."""
    if url not in _cache:
        _cache[url] = fetch(url)
    return _cache[url]


def zip_member(raw: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return archive.read(name).decode("utf-8-sig", errors="replace")


def csv_rows(text: str, keep: Iterable[str] | None = None) -> list[dict[str, str]]:
    """Rows of a CSV text; ``keep`` restricts each row to the named columns so large files stay small in memory."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    if keep is None:
        return [dict(zip(header, row)) for row in reader]
    positions = [(name, header.index(name)) for name in keep]
    return [{name: row[i] for name, i in positions} for row in reader if row]


def first_line(text: str, predicate: Callable[[str], bool]) -> str:
    return next(line for line in text.splitlines() if predicate(line))


def snippet(text: str, words: int = MAX_SNIPPET_WORDS) -> str:
    """Trim free text to the snippet word limit so the evidence item passes the verifier."""
    trimmed = " ".join(text.split()[:words])
    if len(trimmed.split()) > MAX_SNIPPET_WORDS:
        raise ValueError(f"snippet too long: {trimmed!r}")
    return trimmed


def fields_prefix(line: str, count: int) -> str:
    """The first ``count`` comma-separated fields of a CSV line, as they appear in the file."""
    return ",".join(line.split(",")[:count])


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def shares_of(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, 6) for k, v in counts.items()}


def ordered(counter: Counter, key: Callable[[str], Any] | None = None) -> dict[str, int]:
    if key is None:
        return dict(counter.most_common())
    return {k: counter[k] for k in sorted(counter, key=key)}


def pdf_text(raw: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages]


def pdf_codes(pages: list[str], heading: str, stop: str) -> tuple[dict[str, str], int, str]:
    """Code-to-label pairs listed between ``heading`` and ``stop`` in a PDF, the page they sit on and the first code's line."""
    for number, text in enumerate(pages, start=1):
        start = text.find(heading)
        if start < 0:
            continue
        end = text.find(stop, start + len(heading))
        block = text[start + len(heading) : end if end > 0 else None]
        codes, first = {}, ""
        for line in block.splitlines():
            match = re.match(r"^\s*(\d{1,2}|[A-Z])(?:\.\s*|\s+)(?:[-\u2013]\s*)?([A-Z][^\n]*?)\s*$", line) or re.search(r"(?:^|\s)(\d{1,2}|[A-Z])\s*[-\u2013]\s*([A-Z0-9][^\n]*?)\s*$", line)
            if match:
                codes[match.group(1).lstrip("0") or "0"] = match.group(2).rstrip(" .")
                first = first or snippet(line.strip())
        if codes:
            return codes, number, first
    raise ValueError(f"no code list under {heading!r}")


# ---------------------------------------------------------------- entry constructors


def base(entry_id: str, title: str, kind: str, domain: str, region: str, status: str, tags: list[str], use_cases: list[str]) -> dict:
    return {"id": entry_id, "title": title, "kind": kind, "domain": domain, "region": region, "status": status, "tier": "A", "tags": tags, "use_cases": use_cases}


def marginal(entry_id: str, title: str, domain: str, region: str, status: str, period: tuple[str, str], variable: str, counts: dict[str, int], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str], labels: dict[str, str] | None = None) -> dict:
    shares = shares_of(counts)
    top = max(shares, key=shares.get)
    parameters: dict[str, Any] = {"shares": shares, "counts": counts, "total": sum(counts.values())}
    if labels:
        parameters["labels"] = labels
    entry = base(entry_id, title, "marginal", domain, region, status, tags, use_cases)
    entry.update(
        observed_period={"start": period[0], "end": period[1]},
        spec={"variable": variable, "unit": "ratio", "distribution": {"family": "categorical", "parameters": parameters}},
        evidence=items,
        assumed=assumed,
        tests=[
            {"statistic": f'share["{top}"]', "expected": shares[top], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        notes=notes,
    )
    return entry


def empirical(entry_id: str, title: str, domain: str, region: str, status: str, period: tuple[str, str], variable: str, unit: str, counts: dict[int, int], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str]) -> dict:
    values = sorted(counts)
    weights = [counts[v] for v in values]
    expanded = [v for v in values for _ in range(counts[v])]
    entry = base(entry_id, title, "marginal", domain, region, status, tags, use_cases)
    entry.update(
        observed_period={"start": period[0], "end": period[1]},
        spec={"variable": variable, "unit": unit, "distribution": {"family": "empirical", "parameters": {"values": values, "weights": weights}}},
        evidence=items,
        assumed=assumed,
        tests=[
            {"statistic": "median", "expected": median(expanded), "tolerance": max(1.0, 0.01 * median(expanded))},
            {"statistic": "mean", "expected": round(mean(expanded), 3), "tolerance": max(0.5, 0.01 * mean(expanded))},
        ],
        notes=notes,
    )
    return entry


def conditional(entry_id: str, title: str, domain: str, region: str, status: str, period: tuple[str, str], variable: str, given: str, groups: dict[str, dict[str, int]], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str], extra: dict[str, dict] | None = None) -> dict:
    distributions = {}
    for name, counts in groups.items():
        parameters: dict[str, Any] = {"shares": shares_of(counts), "counts": counts, "total": sum(counts.values())}
        if extra and name in extra:
            parameters.update(extra[name])
        distributions[name] = {"family": "categorical", "parameters": parameters}
    first, last = next(iter(groups)), list(groups)[-1]
    tests = []
    for name in (first, last):
        shares = distributions[name]["parameters"]["shares"]
        top = max(shares, key=shares.get)
        tests.append({"statistic": f'share[{name},"{top}"]', "expected": shares[top], "tolerance": 0.005})
        tests.append({"statistic": f"sum_of_shares[{name}]", "expected": 1, "tolerance": 1e-4})
    entry = base(entry_id, title, "conditional", domain, region, status, tags, use_cases)
    entry.update(observed_period={"start": period[0], "end": period[1]}, spec={"variable": variable, "unit": "ratio", "given": given, "distributions": distributions}, evidence=items, assumed=assumed, tests=tests, notes=notes)
    return entry


def lookup(entry_id: str, title: str, domain: str, region: str, status: str, valid: tuple[str, str | None], parameters: dict, rows: dict[str, dict], vector_keys: tuple[str, str], column: str, items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str]) -> dict:
    vectors = [{"input": {"key": k, "column": column}, "expected": rows[k][column], "origin": "source"} for k in vector_keys]
    vectors.append({"input": "XX", "expected": False, "origin": "derived"})
    entry = base(entry_id, title, "rule", domain, region, status, tags, use_cases)
    entry.update(
        valid_from=valid[0],
        valid_to=valid[1],
        spec={"implementation": "almanac.rules.lookup_table", "parameters": {**parameters, "rows": rows}, "vectors": vectors},
        evidence=items,
        assumed=assumed,
        tests=[
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": f"max[{column}]", "expected": max(float(r[column]) for r in rows.values() if r[column] is not None), "tolerance": 1e-9},
        ],
        notes=notes,
    )
    return entry


def temporal(entry_id: str, title: str, domain: str, region: str, status: str, period: tuple[str, str], variable: str, unit: str, frequency: str, series: list[dict], items: list[dict], assumed: list[dict], notes: str, tags: list[str], use_cases: list[str]) -> dict:
    columns = [k for k in series[0] if k not in ("period", "value")]
    tests = [
        {"statistic": f"value[{series[0]['period']}]", "expected": series[0]["value"], "tolerance": 1e-9},
        {"statistic": f"value[{series[-1]['period']}]", "expected": series[-1]["value"], "tolerance": 1e-9},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    if columns:
        tests.insert(2, {"statistic": f"column[{columns[0]},{series[-1]['period']}]", "expected": series[-1][columns[0]], "tolerance": 1e-9})
    entry = base(entry_id, title, "temporal", domain, region, status, tags, use_cases)
    entry.update(observed_period={"start": period[0], "end": period[1]}, spec={"variable": variable, "unit": unit, "frequency": frequency, "columns": columns, "series": series}, evidence=items, assumed=assumed, tests=tests, notes=notes)
    return entry


def derived(parameter: str, value: str, rationale: str) -> dict:
    return {"parameter": parameter, "value": value, "method": "derived", "rationale": rationale}


# ---------------------------------------------------------------- NHTSA FARS

FARS_TAGS = ["fars", "nhtsa", "road-safety", "fatal-crashes", "transport", "telematics"]
FARS_USES = ["telematics-demo", "insurance-demo", "claims-generation", "event-timestamps", "fleet-demo"]


def fars_entries() -> Iterable[dict]:
    raw = get(FARS_URL)
    text = zip_member(raw, f"FARS{FARS_YEAR}NationalCSV/accident.csv")
    rows = csv_rows(text)
    first = first_line(text, lambda line: line.startswith("1,Alabama,"))
    period = (f"{FARS_YEAR}-01-01", f"{FARS_YEAR}-12-31")
    title = f"FARS {FARS_YEAR} National CSV (accident.csv), Fatality Analysis Reporting System"

    def item(column: str) -> dict:
        return evidence(NHTSA, title, FARS_URL, f"accident.csv, record ST_CASE={rows[0]['ST_CASE']}, column {column}", rows[0][column], "text", fields_prefix(first, 16), UNSTATED, raw)

    def count_note(column: str) -> str:
        return f"Each record of accident.csv is one fatal crash; counts are records grouped by {column}, shares are counts over the number of crashes kept."

    common = (
        f"Fatal motor-vehicle crashes in the United States in {FARS_YEAR} from the NHTSA Fatality Analysis Reporting System National CSV release "
        f"(accident.csv, one record per crash). The published counts sit beside the derived shares. "
    )

    by_month = Counter(r["MONTHNAME"] for r in rows)
    month_order = {r["MONTHNAME"]: int(r["MONTH"]) for r in rows}
    yield marginal(
        f"us-fars-fatal-crashes-by-month-{FARS_YEAR}", f"United States fatal crashes by month of the year, {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period, "crash_month",
        ordered(by_month, month_order.get), [item("MONTHNAME")], [derived("distribution.parameters.counts", "records grouped by MONTHNAME", count_note("MONTHNAME"))],
        common + "Categories are the MONTHNAME values of the file in calendar order. " + US_LICENSE_NOTE, FARS_TAGS + ["seasonality", "by-month"], FARS_USES,
    )

    by_dow = Counter(r["DAY_WEEKNAME"] for r in rows)
    dow_order = {r["DAY_WEEKNAME"]: int(r["DAY_WEEK"]) for r in rows}
    yield marginal(
        f"us-fars-fatal-crashes-by-day-of-week-{FARS_YEAR}", f"United States fatal crashes by day of the week, {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period, "crash_day_of_week",
        ordered(by_dow, dow_order.get), [item("DAY_WEEKNAME")], [derived("distribution.parameters.counts", "records grouped by DAY_WEEKNAME", count_note("DAY_WEEKNAME"))],
        common + "Categories are the DAY_WEEKNAME values of the file, Sunday first as FARS codes them (DAY_WEEK 1 to 7). " + US_LICENSE_NOTE, FARS_TAGS + ["by-day-of-week"], FARS_USES,
    )

    hours = Counter(r["HOUR"] for r in rows if r["HOUR"] != "99")
    unknown_hours = sum(1 for r in rows if r["HOUR"] == "99")
    hour_labels = {r["HOUR"]: r["HOURNAME"] for r in rows if r["HOUR"] != "99"}
    yield marginal(
        f"us-fars-fatal-crashes-by-hour-of-day-{FARS_YEAR}", f"United States fatal crashes by hour of the day, {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period, "crash_hour",
        ordered(hours, int), [item("HOUR")], [derived("distribution.parameters.counts", "records grouped by HOUR, code 99 (unknown) dropped", count_note("HOUR") + f" {unknown_hours} crashes with HOUR 99 (unknown) are excluded.")],
        common + "Categories are the HOUR codes 0 to 23; the labels mapping carries the HOURNAME text for each code. " + US_LICENSE_NOTE, FARS_TAGS + ["by-hour", "time-of-day"], FARS_USES,
        labels={k: hour_labels[k] for k in ordered(hours, int)},
    )

    weather = Counter(r["WEATHERNAME"] for r in rows)
    yield marginal(
        f"us-fars-fatal-crashes-by-weather-{FARS_YEAR}", f"United States fatal crashes by atmospheric conditions at the crash, {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period, "weather_condition",
        ordered(weather), [item("WEATHERNAME")], [derived("distribution.parameters.counts", "records grouped by WEATHERNAME", count_note("WEATHERNAME"))],
        common + "Categories are the WEATHERNAME values of the file, including the not-reported and reported-as-unknown codes. " + US_LICENSE_NOTE, FARS_TAGS + ["weather"], FARS_USES,
    )

    light = Counter(r["LGT_CONDNAME"] for r in rows)
    yield marginal(
        f"us-fars-fatal-crashes-by-light-condition-{FARS_YEAR}", f"United States fatal crashes by light condition at the crash, {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period, "light_condition",
        ordered(light), [item("LGT_CONDNAME")], [derived("distribution.parameters.counts", "records grouped by LGT_CONDNAME", count_note("LGT_CONDNAME"))],
        common + "Categories are the LGT_CONDNAME values of the file. " + US_LICENSE_NOTE, FARS_TAGS + ["light-conditions"], FARS_USES,
    )

    states: dict[str, dict] = {}
    for r in rows:
        record = states.setdefault(r["STATE"], {"name": r["STATENAME"], "fatal_crashes": 0, "fatalities": 0})
        record["fatal_crashes"] += 1
        record["fatalities"] += int(r["FATALS"])
    states = dict(sorted(states.items(), key=lambda kv: int(kv[0])))
    for record in states.values():
        record["fatalities_per_crash"] = round(record["fatalities"] / record["fatal_crashes"], 4)
    yield lookup(
        f"us-fars-fatal-crashes-and-fatalities-by-state-{FARS_YEAR}", f"United States fatal crashes and fatalities by state (FIPS code), {FARS_YEAR} (NHTSA FARS)", "transport", "US", "license-review", period,
        {"source": "FARS National CSV accident.csv", "year": FARS_YEAR}, states, ("6", "48"), "fatal_crashes",
        [item("STATENAME"), evidence(NHTSA, title, FARS_URL, f"accident.csv, record ST_CASE={rows[0]['ST_CASE']}, column FATALS", rows[0]["FATALS"], "count", fields_prefix(first, 16), UNSTATED, raw)],
        [derived("rows[*].fatal_crashes and rows[*].fatalities", "records grouped by STATE; fatalities is the sum of FATALS", "Each accident.csv record is one fatal crash carrying its FATALS count; both columns are aggregates over the records of a state."), derived("rows[*].fatalities_per_crash", "fatalities / fatal_crashes", "Ratio of the two aggregates.")],
        common + "Rows are keyed by the two-digit FARS state code (state FIPS code) and carry the STATENAME text. " + US_LICENSE_NOTE, FARS_TAGS + ["by-state", "reference-table"], FARS_USES + ["address-generation"],
    )


# ---------------------------------------------------------------- NHTSA recalls (Socrata)


def soql(select: str, group: str, order: str, where: str) -> str:
    query = f"$select={select}&$group={group}&$order={order}&$where={where}"
    return RECALLS_API + "?" + query.replace(" ", "%20").replace("'", "%27")


def recalls_entries() -> Iterable[dict]:
    window = f"report_received_date between '{RECALLS_YEAR}-01-01T00:00:00' and '{RECALLS_YEAR}-12-31T23:59:59'"
    title = "NHTSA Recalls Data, Socrata dataset 6axg-epim on data.transportation.gov (SoQL CSV export)"
    period = (f"{RECALLS_YEAR}-01-01", f"{RECALLS_YEAR}-12-31")

    url = soql("component,count(nhtsa_id),sum(potentially_affected)", "component", "component", window + " AND recall_type='Vehicle'")
    raw = get(url)
    rows = csv_rows(raw.decode("utf-8-sig"))
    table = {r["component"]: {"recalls": int(r["count_nhtsa_id"]), "potentially_affected_units": int(r["sum_potentially_affected"])} for r in rows}
    total_recalls = sum(r["recalls"] for r in table.values())
    for record in table.values():
        record["share_of_recalls"] = round(record["recalls"] / total_recalls, 6)
    lead = rows[0]
    yield lookup(
        f"us-nhtsa-vehicle-recalls-by-component-{RECALLS_YEAR}", f"United States vehicle safety recalls by component, report received in {RECALLS_YEAR}: campaigns and units potentially affected (NHTSA)", "automotive", "US", "license-review", period,
        {"dataset": "6axg-epim", "query": url.split("?", 1)[1], "year": RECALLS_YEAR}, table, (rows[0]["component"], rows[-1]["component"]), "recalls",
        [evidence(NHTSA, title, url, f"row component={lead['component']}, count_nhtsa_id", lead["count_nhtsa_id"], "count", first_line(raw.decode("utf-8-sig"), lambda line: line.startswith(f'"{lead["component"]}"')), UNSTATED, raw)],
        [derived("rows[*].share_of_recalls", "recalls / sum of recalls over components", "The query returns counts per component; the share is each count over their sum.")],
        f"Vehicle recall campaigns (recall_type Vehicle) whose Part 573 report NHTSA received in {RECALLS_YEAR}, grouped by the affected component, with the number of campaigns and the sum of units potentially affected, "
        "from a SoQL aggregate query on the NHTSA Recalls Data dataset. A campaign naming several components is counted under each. Rows are keyed by the component text exactly as the dataset spells it. " + SOCRATA_NOTE,
        ["recalls", "nhtsa", "vehicle-safety", "components", "reference-table", "transport", "vehicles"], ["fleet-demo", "automotive-demo", "insurance-demo", "claims-generation"],
    )

    url = soql("date_trunc_ym(report_received_date) as month,recall_type,count(nhtsa_id),sum(potentially_affected)", "month,recall_type", "month,recall_type", window)
    raw = get(url)
    rows = csv_rows(raw.decode("utf-8-sig"))
    by_month: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        by_month[r["month"][:7]][slug(r["recall_type"])] = int(r["count_nhtsa_id"])
        by_month[r["month"][:7]][slug(r["recall_type"]) + "_units"] = int(r["sum_potentially_affected"])
    types = sorted({slug(r["recall_type"]) for r in rows})
    series = []
    for month in sorted(by_month):
        point = {"period": month, "value": sum(by_month[month].get(t, 0) for t in types)}
        for t in types:
            point[t] = by_month[month].get(t, 0)
            point[t + "_units"] = by_month[month].get(t + "_units", 0)
        series.append(point)
    lead = rows[0]
    yield temporal(
        f"us-nhtsa-recalls-monthly-{RECALLS_YEAR}", f"United States safety recall campaigns received by NHTSA per month and type, {RECALLS_YEAR}, with units potentially affected", "automotive", "US", "license-review", period,
        "recall_campaigns", "count", "monthly", series,
        [evidence(NHTSA, title, url, f"row month={lead['month']}, recall_type={lead['recall_type']}, count_nhtsa_id", lead["count_nhtsa_id"], "count", first_line(raw.decode("utf-8-sig"), lambda line: line.startswith(f'"{lead["month"]}","{lead["recall_type"]}"')), UNSTATED, raw)],
        [derived("series[*].value", "sum of the per-type counts of the month", "The query returns one row per month and recall type; the series value is their sum, the columns keep each type and its units potentially affected.")],
        f"Recall campaigns by the month NHTSA received the Part 573 report in {RECALLS_YEAR}, split by recall type (vehicle, equipment, tire, child seat), each with the sum of units potentially affected, "
        "from a SoQL aggregate query on the NHTSA Recalls Data dataset. " + SOCRATA_NOTE,
        ["recalls", "nhtsa", "vehicle-safety", "by-month", "transport", "vehicles"], ["fleet-demo", "automotive-demo", "event-timestamps", "claims-generation"],
    )


# ---------------------------------------------------------------- EPA fuel economy

EPA_TAGS = ["fuel-economy", "epa", "vehicles", "model-year", "transport"]
EPA_USES = ["fleet-demo", "automotive-demo", "telematics-demo", "insurance-demo"]


def epa_entries() -> Iterable[dict]:
    raw = get(EPA_URL)
    text = zip_member(raw, "vehicles.csv")
    rows = [r for r in csv_rows(text, ("id", "make", "model", "year", "fuelType", "VClass", "drive", "comb08")) if r["year"] == EPA_MODEL_YEAR]
    lead = rows[0]
    line = first_line(text, lambda l: f",{lead['make']},{lead['model']}," in l and f",{EPA_MODEL_YEAR}," in l)
    title = "fueleconomy.gov EPA vehicle data, vehicles.csv (all model years, zip)"
    period = (f"{EPA_MODEL_YEAR}-01-01", f"{EPA_MODEL_YEAR}-12-31")
    common = (
        f"Model year {EPA_MODEL_YEAR} vehicles listed in the EPA fuel economy dataset (vehicles.csv, one row per vehicle configuration tested for the fuel economy label). "
        "Counts are rows, not sales, so the shares describe the model line-up rather than the fleet. "
    )

    def item(column: str) -> dict:
        return evidence(EPA, title, EPA_URL, f"vehicles.csv, row id={lead['id']} ({lead['make']} {lead['model']}), column {column}", lead[column], "text", snippet(line[line.index(f",{lead['make']},") + 1 :][:120].rsplit(",", 1)[0]), UNSTATED, raw)

    fuel = Counter(r["fuelType"] for r in rows)
    yield marginal(
        f"us-epa-vehicle-configurations-by-fuel-type-my{EPA_MODEL_YEAR}", f"United States model year {EPA_MODEL_YEAR} vehicle configurations by fuel type (EPA fuel economy data)", "automotive", "US", "license-review", period, "fuel_type",
        ordered(fuel), [item("fuelType")], [derived("distribution.parameters.counts", f"rows with year={EPA_MODEL_YEAR} grouped by fuelType", "Counts are rows of vehicles.csv for the model year grouped by the fuelType column.")],
        common + "Categories are the fuelType values of the file (Regular, Premium, Electricity, Diesel and the plug-in hybrid combinations). " + US_LICENSE_NOTE, EPA_TAGS + ["fuel-type"], EPA_USES,
    )

    vclass = Counter(r["VClass"] for r in rows)
    yield marginal(
        f"us-epa-vehicle-configurations-by-class-my{EPA_MODEL_YEAR}", f"United States model year {EPA_MODEL_YEAR} vehicle configurations by EPA vehicle class (fuel economy data)", "automotive", "US", "license-review", period, "epa_vehicle_class",
        ordered(vclass), [item("VClass")], [derived("distribution.parameters.counts", f"rows with year={EPA_MODEL_YEAR} grouped by VClass", "Counts are rows of vehicles.csv for the model year grouped by the VClass column.")],
        common + "Categories are the VClass values of the file (EPA size classes, with 2WD and 4WD variants for SUVs and pickups). " + US_LICENSE_NOTE, EPA_TAGS + ["vehicle-class"], EPA_USES,
    )

    drive = Counter(r["drive"] for r in rows if r["drive"])
    yield marginal(
        f"us-epa-vehicle-configurations-by-drive-type-my{EPA_MODEL_YEAR}", f"United States model year {EPA_MODEL_YEAR} vehicle configurations by drive type (EPA fuel economy data)", "automotive", "US", "license-review", period, "drive_type",
        ordered(drive), [item("drive")], [derived("distribution.parameters.counts", f"rows with year={EPA_MODEL_YEAR} grouped by drive, blank drive dropped", "Counts are rows of vehicles.csv for the model year grouped by the drive column.")],
        common + "Categories are the drive values of the file. " + US_LICENSE_NOTE, EPA_TAGS + ["drive-type"], EPA_USES,
    )

    classes: dict[str, dict] = {}
    for name in sorted(vclass):
        subset = [r for r in rows if r["VClass"] == name]
        conventional = [int(r["comb08"]) for r in subset if r["fuelType"] != "Electricity"]
        electric = [int(r["comb08"]) for r in subset if r["fuelType"] == "Electricity"]
        classes[name] = {
            "configurations": len(subset),
            "conventional_configurations": len(conventional),
            "electric_configurations": len(electric),
            "combined_mpg_mean": round(mean(conventional), 2) if conventional else None,
            "combined_mpg_median": float(median(conventional)) if conventional else None,
            "combined_mpg_min": min(conventional) if conventional else None,
            "combined_mpg_max": max(conventional) if conventional else None,
            "electric_combined_mpge_mean": round(mean(electric), 2) if electric else None,
        }
    yield lookup(
        f"us-epa-combined-fuel-economy-by-vehicle-class-my{EPA_MODEL_YEAR}", f"United States model year {EPA_MODEL_YEAR} combined fuel economy (MPG) summary by EPA vehicle class (fuel economy data)", "automotive", "US", "license-review", period,
        {"source": "vehicles.csv", "model_year": int(EPA_MODEL_YEAR), "field": "comb08"}, classes, (lead["VClass"], max(vclass, key=vclass.get)), "combined_mpg_mean",
        [item("VClass"), evidence(EPA, title, EPA_URL, f"vehicles.csv, row id={lead['id']} ({lead['make']} {lead['model']}), column comb08", lead["comb08"], "integer", snippet(line[line.index(f",{lead['make']},") + 1 :][:120].rsplit(",", 1)[0]), UNSTATED, raw)],
        [derived("rows[*].combined_mpg_*", "mean, median, min and max of comb08 over the class's rows with fuelType other than Electricity", "comb08 is the combined label fuel economy of each configuration; the conventional group includes hybrids and plug-in hybrids, which raise the class maxima. Battery electric vehicles report MPG-equivalent and are summarised separately as electric_combined_mpge_mean.")],
        common + "Rows are keyed by the EPA VClass text and summarise the comb08 (combined) rating of the class's configurations. " + US_LICENSE_NOTE, EPA_TAGS + ["mpg", "reference-table", "vehicle-class"], EPA_USES + ["pricing"],
    )


# ---------------------------------------------------------------- FAA aircraft registry

FAA_TAGS = ["aviation", "aircraft", "faa", "registry", "transport"]
FAA_USES = ["travel-demo", "fleet-demo", "insurance-demo", "logistics-demo"]


def faa_registry_entries() -> Iterable[dict]:
    raw = get(FAA_REGISTRY_URL)
    text = zip_member(raw, "MASTER.txt")
    header, *data = csv.reader(io.StringIO(text))
    keep = {name: [h.strip() for h in header].index(name) for name in ("N-NUMBER", "TYPE REGISTRANT", "STATE", "COUNTRY", "TYPE AIRCRAFT", "TYPE ENGINE")}
    records = [{name: row[i].strip() for name, i in keep.items()} for row in data if row]
    lead = records[0]
    line = first_line(text, lambda l: l.startswith(lead["N-NUMBER"] + " ") or l.startswith(lead["N-NUMBER"] + ","))
    layout_raw = get(FAA_LAYOUT_URL)
    pages = pdf_text(layout_raw)
    aircraft_types, aircraft_page, aircraft_line = pdf_codes(pages, "Type Aircraft", "Type Engine")
    engine_types, engine_page, engine_line = pdf_codes(pages, "Type Engine", "Status Code")
    registrant_types, registrant_page, registrant_line = pdf_codes(pages, "Type Registrant", "Registrant")
    title = f"FAA Releasable Aircraft Database, yearly archive {FAA_REGISTRY_YEAR} (MASTER.txt in ReleasableAircraft.{FAA_REGISTRY_YEAR}.zip)"
    layout_title = "FAA Aircraft Registration Database record layout (ardata.pdf)"
    period = (f"{FAA_REGISTRY_YEAR}-12-31", f"{FAA_REGISTRY_YEAR}-12-31")
    common = (
        f"Aircraft on the FAA civil aircraft registry at the end of {FAA_REGISTRY_YEAR}, from the yearly archive of the Releasable Aircraft Database (MASTER.txt, one record per registered aircraft). "
    )

    def item(column: str) -> dict:
        return evidence(FAA, title, FAA_REGISTRY_URL, f"MASTER.txt, record N-NUMBER={lead['N-NUMBER']}, column {column}", lead[column], "text", snippet(",".join(f.strip() for f in line.split(",")[2:7])), UNSTATED, raw)

    def layout(codes: dict[str, str], page: int, line: str, heading: str) -> dict:
        return evidence(FAA, layout_title, FAA_LAYOUT_URL, f"page {page}, {heading}", next(iter(codes.values())), "text", line, UNSTATED, layout_raw, role="supporting")

    def labelled(counter: Counter, codes: dict[str, str]) -> dict[str, int]:
        return {codes.get(code, f"code {code}"): n for code, n in counter.most_common()}

    yield marginal(
        f"us-faa-registered-aircraft-by-type-{FAA_REGISTRY_YEAR}", f"United States registered civil aircraft by aircraft type, end of {FAA_REGISTRY_YEAR} (FAA registry)", "transport", "US", "license-review", period, "aircraft_type",
        labelled(Counter(r["TYPE AIRCRAFT"] for r in records), aircraft_types), [item("TYPE AIRCRAFT"), layout(aircraft_types, aircraft_page, aircraft_line, "Type Aircraft")],
        [derived("distribution.parameters.counts", "MASTER.txt records grouped by TYPE AIRCRAFT, labelled from the record layout", "Each record is one registered aircraft; the code labels come from the Type Aircraft list in ardata.pdf.")],
        common + "Categories are the Type Aircraft labels of the FAA record layout. " + US_LICENSE_NOTE, FAA_TAGS + ["aircraft-type"], FAA_USES,
    )
    yield marginal(
        f"us-faa-registered-aircraft-by-engine-type-{FAA_REGISTRY_YEAR}", f"United States registered civil aircraft by engine type, end of {FAA_REGISTRY_YEAR} (FAA registry)", "transport", "US", "license-review", period, "engine_type",
        labelled(Counter(r["TYPE ENGINE"] for r in records), engine_types), [item("TYPE ENGINE"), layout(engine_types, engine_page, engine_line, "Type Engine")],
        [derived("distribution.parameters.counts", "MASTER.txt records grouped by TYPE ENGINE, labelled from the record layout", "Each record is one registered aircraft; the code labels come from the Type Engine list in ardata.pdf.")],
        common + "Categories are the Type Engine labels of the FAA record layout. " + US_LICENSE_NOTE, FAA_TAGS + ["engine-type"], FAA_USES,
    )
    registrants = Counter(r["TYPE REGISTRANT"] for r in records if r["TYPE REGISTRANT"])
    yield marginal(
        f"us-faa-registered-aircraft-by-registrant-type-{FAA_REGISTRY_YEAR}", f"United States registered civil aircraft by registrant type, end of {FAA_REGISTRY_YEAR} (FAA registry)", "transport", "US", "license-review", period, "registrant_type",
        labelled(registrants, registrant_types), [item("TYPE REGISTRANT"), layout(registrant_types, registrant_page, registrant_line, "Type Registrant")],
        [derived("distribution.parameters.counts", "MASTER.txt records grouped by TYPE REGISTRANT, blank dropped, labelled from the record layout", "Each record is one registered aircraft; the code labels come from the Type Registrant list in ardata.pdf.")],
        common + "Categories are the Type Registrant labels of the FAA record layout (individual, partnership, corporation, co-owned, government, LLC, non-citizen corporation, non-citizen co-owned). " + US_LICENSE_NOTE, FAA_TAGS + ["registrant-type", "ownership"], FAA_USES + ["company-generation"],
    )
    states: dict[str, dict] = {}
    for r in records:
        if r["COUNTRY"] != "US" or not r["STATE"]:
            continue
        record = states.setdefault(r["STATE"], {"aircraft": 0, "fixed_wing_single_engine": 0, "rotorcraft": 0})
        record["aircraft"] += 1
        record["fixed_wing_single_engine"] += r["TYPE AIRCRAFT"] == "4"
        record["rotorcraft"] += r["TYPE AIRCRAFT"] == "6"
    states = dict(sorted(states.items()))
    yield lookup(
        f"us-faa-registered-aircraft-by-state-{FAA_REGISTRY_YEAR}", f"United States registered civil aircraft by registrant state, end of {FAA_REGISTRY_YEAR} (FAA registry)", "transport", "US", "license-review", period,
        {"source": "MASTER.txt", "filter": "COUNTRY=US"}, states, ("TX", "CA"), "aircraft",
        [item("STATE"), layout(aircraft_types, aircraft_page, aircraft_line, "Type Aircraft")],
        [derived("rows[*]", "MASTER.txt records with COUNTRY US grouped by STATE; type columns count TYPE AIRCRAFT codes 4 and 6", "Each record is one registered aircraft at the registrant's address; codes 4 and 6 are Fixed wing single engine and Rotorcraft in the record layout.")],
        common + "Rows are keyed by the registrant's two-letter state or territory code (records with COUNTRY US only). " + US_LICENSE_NOTE, FAA_TAGS + ["by-state", "reference-table"], FAA_USES + ["address-generation"],
    )


# ---------------------------------------------------------------- FAA NASR airports

NASR_TAGS = ["aviation", "airports", "faa", "nasr", "transport", "infrastructure"]
NASR_USES = ["travel-demo", "logistics-demo", "fleet-demo", "address-generation"]


def nasr_entries() -> Iterable[dict]:
    raw = get(NASR_URL)
    base_text = zip_member(raw, "APT_BASE.csv")
    airports = csv_rows(base_text)
    lead = airports[0]
    base_line = first_line(base_text, lambda l: f'"{lead["SITE_NO"]}"' in l and f'"{lead["ARPT_ID"]}"' in l)
    rwy_text = zip_member(raw, "APT_RWY.csv")
    runways = csv_rows(rwy_text)
    rwy_lead = runways[0]
    rwy_line = first_line(rwy_text, lambda l: f'"{rwy_lead["SITE_NO"]}"' in l and f'"{rwy_lead["RWY_ID"]}"' in l)
    title = f"FAA NASR 28-day subscription, airport CSV extract effective {NASR_CYCLE.isoformat()} (APT_BASE.csv and APT_RWY.csv)"
    period = (NASR_CYCLE.isoformat(), NASR_CYCLE.isoformat())
    us = [a for a in airports if a["COUNTRY_CODE"] == "US"]
    common = (
        f"Landing facilities in the FAA National Airspace System Resources (NASR) airport file for the 28-day cycle effective {NASR_CYCLE.isoformat()}. "
    )

    def base_item(column: str) -> dict:
        return evidence(FAA, title, NASR_URL, f"APT_BASE.csv, record SITE_NO={lead['SITE_NO']} ({lead['ARPT_ID']}), column {column}", lead[column], "text", snippet(fields_prefix(base_line, 10)), UNSTATED, raw)

    site_types = Counter(a["SITE_TYPE_CODE"] for a in us)
    ownership = Counter(a["OWNERSHIP_TYPE_CODE"] for a in us)
    use = Counter(a["FACILITY_USE_CODE"] for a in us)
    yield conditional(
        f"us-faa-landing-facilities-ownership-by-site-type-{NASR_CYCLE:%Y-%m}", f"United States landing facilities: ownership code given NASR site type, cycle effective {NASR_CYCLE.isoformat()} (FAA)", "transport", "US", "license-review", period,
        "ownership_type_code", "site_type_code", {code: ordered(Counter(a["OWNERSHIP_TYPE_CODE"] for a in us if a["SITE_TYPE_CODE"] == code)) for code, _ in site_types.most_common()},
        [base_item("SITE_TYPE_CODE"), base_item("OWNERSHIP_TYPE_CODE")],
        [derived("distributions[*].parameters.counts", "APT_BASE.csv records with COUNTRY_CODE US grouped by SITE_TYPE_CODE then OWNERSHIP_TYPE_CODE", "Each APT_BASE.csv record is one landing facility; the codes are kept as published (site type A airport, H heliport, C seaplane base, G gliderport, U ultralight, B balloonport; ownership PU publicly owned, PR privately owned, MA Air Force, MN Navy, MR Army, CG Coast Guard, as the APT DATA LAYOUT PDF inside the same archive defines them).")],
        common + "Site type codes condition the ownership-type distribution; facility counts per site type are carried as site_type_facilities. Codes are the NASR codes as published; the layout PDF inside the archive defines them. " + US_LICENSE_NOTE,
        NASR_TAGS + ["ownership", "site-type"], NASR_USES, extra={code: {"site_type_facilities": n, "public_use_facilities": sum(1 for a in us if a["SITE_TYPE_CODE"] == code and a["FACILITY_USE_CODE"] == "PU")} for code, n in site_types.items()},
    )

    states: dict[str, dict] = {}
    for a in us:
        record = states.setdefault(a["STATE_CODE"], {"name": a["STATE_NAME"], "facilities": 0, "airports": 0, "heliports": 0, "public_use": 0, "publicly_owned": 0})
        record["facilities"] += 1
        record["airports"] += a["SITE_TYPE_CODE"] == "A"
        record["heliports"] += a["SITE_TYPE_CODE"] == "H"
        record["public_use"] += a["FACILITY_USE_CODE"] == "PU"
        record["publicly_owned"] += a["OWNERSHIP_TYPE_CODE"] == "PU"
    states = dict(sorted(states.items()))
    yield lookup(
        f"us-faa-landing-facilities-by-state-{NASR_CYCLE:%Y-%m}", f"United States landing facilities by state: airports, heliports, public use and public ownership, cycle effective {NASR_CYCLE.isoformat()} (FAA NASR)", "transport", "US", "license-review", period,
        {"source": "APT_BASE.csv", "effective": NASR_CYCLE.isoformat(), "filter": "COUNTRY_CODE=US"}, states, ("TX", "CA"), "facilities",
        [base_item("STATE_CODE"), base_item("FACILITY_USE_CODE")],
        [derived("rows[*]", "APT_BASE.csv records with COUNTRY_CODE US grouped by STATE_CODE; columns count SITE_TYPE_CODE A and H, FACILITY_USE_CODE PU and OWNERSHIP_TYPE_CODE PU", "Each record is one landing facility; the column counts apply the published codes.")],
        common + f"Rows are keyed by the NASR STATE_CODE and carry the state name; the {sum(use.values())} US facilities split {use['PU']} public use and {use['PR']} private use, {ownership['PU']} publicly owned. " + US_LICENSE_NOTE,
        NASR_TAGS + ["by-state", "reference-table"], NASR_USES,
    )

    airport_sites = {a["SITE_NO"] for a in us if a["SITE_TYPE_CODE"] == "A"}
    lengths = Counter(int(r["RWY_LEN"]) for r in runways if r["RWY_LEN"] and int(r["RWY_LEN"]) > 0 and r["SITE_NO"] in airport_sites)
    yield empirical(
        f"us-faa-airport-runway-length-{NASR_CYCLE:%Y-%m}", f"United States airport runway length in feet, cycle effective {NASR_CYCLE.isoformat()} (FAA NASR runway file)", "transport", "US", "license-review", period,
        "runway_length_feet", "integer", dict(lengths),
        [evidence(FAA, title, NASR_URL, f"APT_RWY.csv, record SITE_NO={rwy_lead['SITE_NO']} ({rwy_lead['ARPT_ID']}) runway {rwy_lead['RWY_ID']}, column RWY_LEN", rwy_lead["RWY_LEN"], "integer", snippet(fields_prefix(rwy_line, 11)), UNSTATED, raw)],
        [derived("distribution.parameters.values and weights", "distinct RWY_LEN values of APT_RWY.csv for US airports (site type A) with their record counts", "Each APT_RWY.csv record is one runway; zero or blank lengths are dropped and the empirical distribution weights each distinct length by its number of runways.")],
        common + "The distribution covers runways at facilities of site type A (airport) in the United States; heliport pads and seaplane lanes are excluded. " + US_LICENSE_NOTE,
        NASR_TAGS + ["runways"], NASR_USES + ["capacity-planning"],
    )


# ---------------------------------------------------------------- BTS border crossings


def border_url(select: str, group: str, order: str) -> str:
    where = f"date>='{BORDER_YEAR}-01-01T00:00:00' AND date<'{BORDER_YEAR + 1}-01-01T00:00:00'"
    query = f"$select={select}&$group={group}&$order={order}&$where={where}"
    return BORDER_API + "?" + query.replace(" ", "%20").replace("'", "%27").replace(">", "%3E").replace("<", "%3C")


def border_entries() -> Iterable[dict]:
    title = "BTS Border Crossing Entry Data, Socrata dataset keg4-3bc2 on data.bts.gov (SoQL CSV export)"
    period = (f"{BORDER_YEAR}-01-01", f"{BORDER_YEAR}-12-31")
    note = (
        f"Inbound crossings at US land ports of entry in {BORDER_YEAR} as published by BTS from US Customs and Border Protection counts, "
        "queried with a SoQL aggregate on the Border Crossing Entry Data dataset. Measures count vehicles, containers and people separately "
        "(for example Trucks and Personal Vehicle Passengers), so they are not additive across measures. "
    )
    tags = ["border-crossings", "bts", "logistics", "customs", "transport", "mobility"]
    uses = ["logistics-demo", "travel-demo", "demand-forecasting", "fleet-demo"]

    url = border_url("border,measure,sum(value)", "border,measure", "border,measure")
    raw = get(url)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text)
    groups = {slug(b): {r["measure"]: int(r["sum_value"]) for r in rows if r["border"] == b} for b in sorted({r["border"] for r in rows})}
    lead = rows[0]
    yield conditional(
        f"us-bts-border-crossings-by-measure-given-border-{BORDER_YEAR}", f"United States inbound border crossings by measure given border (Canada or Mexico), {BORDER_YEAR} (BTS)", "transport", "US", "license-review", period,
        "measure", "border", groups,
        [evidence(BTS, title, url, f"row border={lead['border']}, measure={lead['measure']}, sum_value", lead["sum_value"], "count", first_line(text, lambda l: l.startswith(f'"{lead["border"]}","{lead["measure"]}"')), UNSTATED, raw)],
        [derived("distributions[*].parameters.shares", "sum_value of a measure / sum over the measures of the border", "The query returns annual totals per border and measure; shares are each measure over the sum of all measures at that border, which mixes vehicle, container and person counts and is meant as a mix of record types rather than a physical ratio.")],
        note + "Conditioning keys are us_canada_border and us_mexico_border. " + SOCRATA_NOTE, tags, uses,
    )

    url = border_url("border,measure,date,sum(value)", "border,measure,date", "date,border,measure")
    raw = get(url)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text)
    by_month: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        by_month[r["date"][:7]][slug(r["measure"]) + "_" + slug(r["border"]).replace("_border", "")] = int(r["sum_value"])
    columns = sorted({c for v in by_month.values() for c in v})
    series = [{"period": m, "value": by_month[m]["trucks_us_mexico"], **{c: by_month[m].get(c, 0) for c in columns if c != "trucks_us_mexico"}} for m in sorted(by_month)]
    lead = rows[0]
    yield temporal(
        f"us-bts-border-crossings-monthly-{BORDER_YEAR}", f"United States inbound border crossings per month by measure and border, {BORDER_YEAR} (BTS); value is trucks at the Mexico border", "transport", "US", "license-review", period,
        "truck_crossings_us_mexico", "count", "monthly", series,
        [evidence(BTS, title, url, f"row border={lead['border']}, measure={lead['measure']}, date={lead['date'][:10]}, sum_value", lead["sum_value"], "count", first_line(text, lambda l: l.startswith(f'"{lead["border"]}","{lead["measure"]}","{lead["date"]}"')), UNSTATED, raw)],
        [],
        note + "The series value is the Trucks measure at the US-Mexico border; every other measure and border rides along as a column named measure_border. " + SOCRATA_NOTE, tags + ["by-month", "seasonality"], uses + ["event-timestamps"],
    )


# ---------------------------------------------------------------- DVLA vehicle licensing

DVLA_TAGS = ["vehicles", "dvla", "vehicle-licensing", "transport"]
DVLA_USES = ["fleet-demo", "insurance-demo", "telematics-demo", "automotive-demo"]
DVLA_NOTE = "Published under the Open Government Licence v3.0 (GOV.UK). "


def quarter_bounds(label: str) -> tuple[str, str]:
    year, quarter = label.split(" Q")
    starts = {"1": "01-01", "2": "04-01", "3": "07-01", "4": "10-01"}
    ends = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}
    return f"{year}-{starts[quarter]}", f"{year}-{ends[quarter]}"


def cell_int(value: str) -> int | None:
    return int(value) if value.strip().lstrip("-").isdigit() else None


def dvla_entries() -> Iterable[dict]:
    raw = get(VEH0120_URL)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text, ("BodyType", "Make", "GenModel", "Model", "Fuel", "LicenceStatus", DVLA_QUARTER))
    lead = next(r for r in rows if r["BodyType"] == "Cars" and r["LicenceStatus"] == "Licensed" and cell_int(r[DVLA_QUARTER]))
    line = first_line(text, lambda l: l.startswith(f"{lead['BodyType']},{lead['Make']},{lead['GenModel']},{lead['Model']},{lead['Fuel']},{lead['LicenceStatus']},"))
    title = "DfT vehicle licensing statistics data file VEH0120_GB: licensed and SORN vehicles by body type, make, model and fuel, quarterly"
    start, end = quarter_bounds(DVLA_QUARTER)
    period = (end, end)
    licensed = [r for r in rows if r["LicenceStatus"] == "Licensed"]
    suppressed = sum(1 for r in licensed if cell_int(r[DVLA_QUARTER]) is None)

    def value(r: dict[str, str]) -> int:
        return cell_int(r[DVLA_QUARTER]) or 0

    def item(column: str) -> dict:
        return evidence(DFT, title, VEH0120_URL, f"row {lead['BodyType']} / {lead['Make']} / {lead['Model']} / {lead['Fuel']} / {lead['LicenceStatus']}, column {column}", lead[column], "count" if column == DVLA_QUARTER else "text", fields_prefix(line, 7), OGL, raw)

    suppression = f" {suppressed} licensed rows carry a suppression marker instead of a count for {DVLA_QUARTER} and contribute nothing." if suppressed else ""
    common = f"Vehicles licensed in Great Britain at the end of {DVLA_QUARTER} from the DfT and DVLA vehicle licensing statistics data file VEH0120_GB (rows per body type, make, model and fuel; SORN rows excluded).{suppression} "

    body = Counter()
    for r in licensed:
        body[r["BodyType"]] += value(r)
    yield marginal(
        f"gb-licensed-vehicles-by-body-type-{DVLA_QUARTER.replace(' ', '').lower()}", f"Great Britain licensed vehicles by body type, end of {DVLA_QUARTER} (DfT/DVLA VEH0120)", "automotive", "GB", "verified", period, "body_type",
        ordered(body), [item(DVLA_QUARTER), item("BodyType")], [derived("distribution.parameters.counts", f"sum of the {DVLA_QUARTER} column over licensed rows grouped by BodyType", "The file lists vehicle counts per make and model; the body-type totals are their sums.")],
        common + DVLA_NOTE, DVLA_TAGS + ["body-type"], DVLA_USES,
    )

    fuel_by_body: dict[str, Counter] = defaultdict(Counter)
    for r in licensed:
        fuel_by_body[r["BodyType"]][r["Fuel"]] += value(r)
    groups = {slug(b): ordered(fuel_by_body[b]) for b, _ in body.most_common()}
    yield conditional(
        f"gb-licensed-vehicles-fuel-given-body-type-{DVLA_QUARTER.replace(' ', '').lower()}", f"Great Britain licensed vehicles by fuel type given body type, end of {DVLA_QUARTER} (DfT/DVLA VEH0120)", "automotive", "GB", "verified", period,
        "fuel_type", "body_type", groups, [item(DVLA_QUARTER), item("Fuel")],
        [derived("distributions[*].parameters.counts", f"sum of the {DVLA_QUARTER} column over licensed rows grouped by BodyType then Fuel", "The file lists vehicle counts per make, model and fuel; the fuel totals within a body type are their sums.")],
        common + "Conditioning keys are the body types in snake case (cars, light_goods_vehicles, motorcycles, other_vehicles, heavy_goods_vehicles, buses_and_coaches). " + DVLA_NOTE, DVLA_TAGS + ["fuel-type", "body-type"], DVLA_USES + ["utilities-demo"],
    )

    makes = Counter()
    for r in licensed:
        if r["BodyType"] == "Cars":
            makes[r["Make"]] += value(r)
    cars_total = sum(makes.values())
    top = {make: {"rank": rank, "licensed_cars": n, "share_of_licensed_cars": round(n / cars_total, 6)} for rank, (make, n) in enumerate(makes.most_common(20), start=1)}
    yield lookup(
        f"gb-licensed-cars-top-20-makes-{DVLA_QUARTER.replace(' ', '').lower()}", f"Great Britain licensed cars, top 20 makes by number licensed at the end of {DVLA_QUARTER} (DfT/DVLA VEH0120)", "automotive", "GB", "verified", (start, end),
        {"source": "VEH0120_GB", "quarter": DVLA_QUARTER, "licensed_cars_total": cars_total}, top, tuple(list(top)[:2]), "licensed_cars",
        [item(DVLA_QUARTER), item("Make")],
        [derived("rows", f"sum of the {DVLA_QUARTER} column over licensed Cars rows grouped by Make, top 20 by count", "The file lists counts per make and model; make totals are their sums and the share divides by the total of all licensed cars.")],
        common + "Rows are keyed by the make exactly as DVLA spells it (upper case) and carry rank, count and share of all licensed cars. " + DVLA_NOTE, DVLA_TAGS + ["makes", "cars", "reference-table"], DVLA_USES,
    )

    raw = get(VEH0160_URL)
    text = raw.decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(text)))
    quarters = sorted((q for q in header if re.fullmatch(r"\d{4} Q[1-4]", q) and q >= DVLA_REGISTRATIONS_FROM), key=lambda q: (q[:4], q[-1]))
    rows = csv_rows(text, ("BodyType", "Make", "GenModel", "Model", "Fuel", *quarters))
    cars = [r for r in rows if r["BodyType"] == "Cars"]
    lead = next(r for r in cars if r["Fuel"] == "Battery electric" and cell_int(r[quarters[-1]]))
    line = first_line(text, lambda l: l.startswith(f"{lead['BodyType']},{lead['Make']},{lead['GenModel']},{lead['Model']},{lead['Fuel']},"))
    title = "DfT vehicle licensing statistics data file VEH0160_GB: vehicles registered for the first time by body type, make, model and fuel, quarterly"
    fuels = sorted({r["Fuel"] for r in cars})
    series = []
    for q in quarters:
        by_fuel = {slug(f): sum(cell_int(r[q]) or 0 for r in cars if r["Fuel"] == f) for f in fuels}
        series.append({"period": q.replace(" ", "-"), "value": sum(by_fuel.values()), **by_fuel})
    yield temporal(
        f"gb-new-car-registrations-by-fuel-quarterly-{quarters[0][:4]}-{quarters[-1][:4]}", f"Great Britain cars registered for the first time per quarter by fuel type, {quarters[0]} to {quarters[-1]} (DfT/DVLA VEH0160)", "automotive", "GB", "verified", (quarter_bounds(quarters[0])[0], quarter_bounds(quarters[-1])[1]),
        "new_car_registrations", "count", "quarterly", series,
        [evidence(DFT, title, VEH0160_URL, f"row {lead['BodyType']} / {lead['Make']} / {lead['Model']} / {lead['Fuel']}, column {quarters[-1]}", lead[quarters[-1]], "count", fields_prefix(line, 6), OGL, raw)],
        [derived("series[*]", "sum of each quarter column over Cars rows, in total and grouped by Fuel", "The file lists first registrations per make, model and fuel; quarter totals and fuel columns are their sums, with suppression markers counted as zero.")],
        f"Cars registered for the first time in Great Britain per quarter from DfT and DVLA data file VEH0160_GB, in total (value) and by fuel type (columns in snake case). " + DVLA_NOTE,
        DVLA_TAGS + ["new-registrations", "fuel-type", "cars", "by-quarter"], DVLA_USES + ["demand-forecasting", "sales-generation"],
    )


# ---------------------------------------------------------------- ODS reading

ODS_NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0", "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}


def ods_sheets(raw: bytes) -> dict[str, list[list[tuple[str | None, str]]]]:
    """Every sheet of an ODS workbook as rows of (office:value attribute, cell text) pairs."""
    root = ET.fromstring(zip_member(raw, "content.xml"))
    sheets = {}
    for table in root.iter(f"{{{ODS_NS['table']}}}table"):
        rows = []
        for row in table.iter(f"{{{ODS_NS['table']}}}table-row"):
            cells = []
            for cell in row.iter(f"{{{ODS_NS['table']}}}table-cell"):
                text = "".join(p.text or "" for p in cell.iter(f"{{{ODS_NS['text']}}}p"))
                repeat = int(cell.get(f"{{{ODS_NS['table']}}}number-columns-repeated") or 1)
                cells.extend([(cell.get(f"{{{ODS_NS['office']}}}value"), text)] * min(repeat, 64))
            rows.append(cells)
        sheets[table.get(f"{{{ODS_NS['table']}}}name")] = rows
    return sheets


def ods_item(publisher: str, title: str, url: str, raw: bytes, locator: str, cell: tuple[str | None, str], unit: str, license_id: str) -> dict:
    value_attr = cell[0]
    return evidence(publisher, title, url, locator, value_attr if value_attr is not None else cell[1], unit, f'office:value="{value_attr}"' if value_attr is not None else cell[1], license_id, raw)


# ---------------------------------------------------------------- DfT road traffic

TRAFFIC_TAGS = ["road-traffic", "vehicle-miles", "dft", "transport", "telematics"]
TRAFFIC_USES = ["telematics-demo", "fleet-demo", "logistics-demo", "capacity-planning"]


def traffic_entries() -> Iterable[dict]:
    raw = get(TRA0101_URL)
    sheet = ods_sheets(raw)["TRA0101"]
    header_index = next(i for i, row in enumerate(sheet) if row and row[0][1] == "Year")
    header = [c[1] for c in sheet[header_index]]
    data = [row for row in sheet[header_index + 1 :] if row and row[0][1].strip().isdigit()]
    columns = {slug(re.sub(r"\[note \d+\]", "", h)): i for i, h in enumerate(header) if i >= 3 and h}
    recent = [row for row in data if int(row[0][1]) >= 2000]
    series = []
    for row in recent:
        point = {"period": row[0][1], "value": float(row[columns["all_motor_vehicles"]][0])}
        for name, index in columns.items():
            if name != "all_motor_vehicles":
                point[name] = float(row[index][0])
        series.append(point)
    last = recent[-1]
    title = "DfT road traffic statistics table TRA0101: road traffic (vehicle miles) by vehicle type in Great Britain, annual (ODS)"
    yield temporal(
        f"gb-road-traffic-by-vehicle-type-annual-{recent[0][0][1]}-{last[0][1]}", f"Great Britain road traffic in billion vehicle miles per year by vehicle type, {recent[0][0][1]} to {last[0][1]} (DfT TRA0101)", "transport", "GB", "verified", (f"{recent[0][0][1]}-01-01", f"{last[0][1]}-12-31"),
        "billion_vehicle_miles", "decimal", "annual", series,
        [ods_item(DFT, title, TRA0101_URL, raw, f"sheet TRA0101, row Year={last[0][1]}, column All Motor Vehicles", last[columns["all_motor_vehicles"]], "decimal", OGL), ods_item(DFT, title, TRA0101_URL, raw, f"sheet TRA0101, row Year={last[0][1]}, column Cars and Taxis", last[columns["cars_and_taxis"]], "decimal", OGL)],
        [],
        f"Annual motor vehicle traffic on Great Britain's roads in billion vehicle miles from DfT table TRA0101 (National Road Traffic Survey), total (value) and by vehicle type as columns, for {recent[0][0][1]} onwards. "
        "The table's note markers flag years affected by the 2000 fuel protest, foot and mouth disease in 2001 and the coronavirus pandemic. " + DVLA_NOTE,
        TRAFFIC_TAGS + ["by-vehicle-type", "annual"], TRAFFIC_USES,
    )

    raw = get(TRA0104_URL)
    sheet = ods_sheets(raw)["TRA0104"]
    header_index = next(i for i, row in enumerate(sheet) if row and row[0][1] == "Road Type")
    header = [c[1] for c in sheet[header_index]]
    years = [h for h in header if h.strip().isdigit()]
    latest = years[-1]
    column = header.index(latest)
    rows: dict[str, dict] = {}
    cells: dict[str, tuple[str | None, str]] = {}
    for row in sheet[header_index + 1 :]:
        if len(row) <= column or not row[0][1] or row[1][1] != "All":
            continue
        key = slug(f"{row[0][1]} {row[2][1]}")
        rows.setdefault(key, {"road_type": row[0][1], "rural_urban": row[2][1]})
        rows[key][slug(row[3][1])] = float(row[column][0])
        cells[(key, slug(row[3][1]))] = row[column]
    title = "DfT road traffic statistics table TRA0104: road traffic (vehicle miles) by vehicle type and road class in Great Britain, annual (ODS)"
    yield lookup(
        f"gb-road-traffic-by-road-type-and-vehicle-{latest}", f"Great Britain road traffic in billion vehicle miles by road type, rural or urban, and vehicle type, {latest} (DfT TRA0104)", "transport", "GB", "verified", (f"{latest}-01-01", f"{latest}-12-31"),
        {"source": "TRA0104", "year": int(latest), "unit": "billion vehicle miles"}, rows, ("motorway_all", "all_roads_all"), "all_motor_vehicles",
        [ods_item(DFT, title, TRA0104_URL, raw, f"sheet TRA0104, row Motorway / All / All / All Motor Vehicles, column {latest}", cells[("motorway_all", "all_motor_vehicles")], "decimal", OGL), ods_item(DFT, title, TRA0104_URL, raw, f"sheet TRA0104, row All Roads / All / All / Cars and Taxis, column {latest}", cells[("all_roads_all", "cars_and_taxis")], "decimal", OGL)],
        [],
        f"Motor vehicle traffic in {latest} in billion vehicle miles by road type (motorway, rural and urban A roads and minor roads, all roads) and vehicle type from DfT table TRA0104, rows with Road Management All. "
        "Rows are keyed by road type and rural-urban classification in snake case; vehicle types are columns. " + DVLA_NOTE,
        TRAFFIC_TAGS + ["road-type", "reference-table"], TRAFFIC_USES,
    )


# ---------------------------------------------------------------- DfT STATS19 collisions

STATS19_TAGS = ["road-safety", "collisions", "stats19", "dft", "transport", "telematics"]
STATS19_USES = ["telematics-demo", "insurance-demo", "claims-generation", "event-timestamps", "fleet-demo"]
STATS19_NOTE = (
    "Personal-injury road collisions reported to the police in Great Britain in {year} from the DfT road safety open data (STATS19) collision file, one record per collision. "
)


def stats19_entries() -> Iterable[dict]:
    raw = get(COLLISION_URL)
    text = raw.decode("utf-8")
    rows = csv_rows(text, ("collision_index", "collision_severity", "date", "time", "speed_limit", "light_conditions", "weather_conditions"))
    lead = rows[0]
    line = first_line(text, lambda l: l.startswith(lead["collision_index"] + ","))
    stats20 = get(STATS20_URL)
    pages = pdf_text(stats20)
    severity_codes, severity_page, severity_line = pdf_codes(pages, "1.4a LEGACY COLLISION SEVERITY", "NOTES")
    light_codes, light_page, light_line = pdf_codes(pages, "1.21 LIGHT CONDITIONS", "NOTES")
    weather_codes, weather_page, weather_line = pdf_codes(pages, "1.22 WEATHER", "NOTES")
    title = f"DfT road safety data: dft-road-casualty-statistics-collision-{STATS19_YEAR}.csv (STATS19 collisions, Great Britain)"
    stats20_title = "DfT STATS20 2024 specification: instructions for the completion of road collision reports (PDF)"
    period = (f"{STATS19_YEAR}-01-01", f"{STATS19_YEAR}-12-31")
    note = STATS19_NOTE.format(year=STATS19_YEAR)

    def item(column: str) -> dict:
        return evidence(DFT, title, COLLISION_URL, f"record collision_index={lead['collision_index']}, column {column}", lead[column], "text", fields_prefix(line, 14), OGL, raw)

    def stats20_item(codes: dict[str, str], page: int, line: str, section: str) -> dict:
        return evidence(DFT, stats20_title, STATS20_URL, f"page {page}, {section}", next(iter(codes.values())), "text", line, OGL, stats20, role="supporting")

    def labelled(column: str, codes: dict[str, str]) -> dict[str, int]:
        counter = Counter(r[column] for r in rows if r[column] in codes)
        return {codes[code]: counter[code] for code in codes if counter[code]}

    yield marginal(
        f"gb-road-collisions-by-severity-{STATS19_YEAR}", f"Great Britain reported road collisions by severity (fatal, serious, slight), {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "collision_severity",
        labelled("collision_severity", severity_codes), [item("collision_severity"), stats20_item(severity_codes, severity_page, severity_line, "1.4a Legacy collision severity")],
        [derived("distribution.parameters.counts", "records grouped by collision_severity, labelled from STATS20 section 1.4a", "Each record is one collision; severity codes 1, 2 and 3 are Fatal, Serious and Slight in the STATS20 specification.")],
        note + "Categories are the legacy severity labels. " + DVLA_NOTE, STATS19_TAGS + ["severity"], STATS19_USES,
    )

    months = Counter(datetime.strptime(r["date"], "%d/%m/%Y").strftime("%B") for r in rows)
    month_order = {datetime.strptime(r["date"], "%d/%m/%Y").strftime("%B"): datetime.strptime(r["date"], "%d/%m/%Y").month for r in rows}
    yield marginal(
        f"gb-road-collisions-by-month-{STATS19_YEAR}", f"Great Britain reported road collisions by month of the year, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "collision_month",
        ordered(months, month_order.get), [item("date")], [derived("distribution.parameters.counts", "records grouped by the month of the date column (dd/mm/yyyy)", "Each record is one collision dated in the date column; months are read from that date.")],
        note + "Categories are English month names in calendar order. " + DVLA_NOTE, STATS19_TAGS + ["seasonality", "by-month"], STATS19_USES,
    )

    weekdays = Counter(datetime.strptime(r["date"], "%d/%m/%Y").strftime("%A") for r in rows)
    weekday_order = {datetime.strptime(r["date"], "%d/%m/%Y").strftime("%A"): datetime.strptime(r["date"], "%d/%m/%Y").isoweekday() for r in rows}
    yield marginal(
        f"gb-road-collisions-by-day-of-week-{STATS19_YEAR}", f"Great Britain reported road collisions by day of the week, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "collision_day_of_week",
        ordered(weekdays, weekday_order.get), [item("date")], [derived("distribution.parameters.counts", "records grouped by the weekday of the date column", "Each record is one collision dated in the date column; the weekday is computed from that calendar date rather than read from the day_of_week code.")],
        note + "Categories are English weekday names, Monday first. " + DVLA_NOTE, STATS19_TAGS + ["by-day-of-week"], STATS19_USES,
    )

    hours = Counter(r["time"][:2] for r in rows if re.fullmatch(r"\d{2}:\d{2}", r["time"]))
    yield marginal(
        f"gb-road-collisions-by-hour-of-day-{STATS19_YEAR}", f"Great Britain reported road collisions by hour of the day, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "collision_hour",
        ordered(hours, int), [item("time")], [derived("distribution.parameters.counts", "records grouped by the hour of the time column (hh:mm)", f"Each record is one collision with a time of day; {len(rows) - sum(hours.values())} records without a well-formed time are excluded.")],
        note + "Categories are the two-digit hour of the 24-hour clock. " + DVLA_NOTE, STATS19_TAGS + ["by-hour", "time-of-day"], STATS19_USES,
    )

    yield marginal(
        f"gb-road-collisions-by-light-conditions-{STATS19_YEAR}", f"Great Britain reported road collisions by light conditions, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "light_conditions",
        labelled("light_conditions", light_codes), [item("light_conditions"), stats20_item(light_codes, light_page, light_line, "1.21 Light conditions")],
        [derived("distribution.parameters.counts", "records grouped by light_conditions, labelled from STATS20 section 1.21; records with codes outside the list (missing) dropped", "Each record is one collision; the code labels come from the STATS20 specification.")],
        note + DVLA_NOTE, STATS19_TAGS + ["light-conditions"], STATS19_USES,
    )

    yield marginal(
        f"gb-road-collisions-by-weather-{STATS19_YEAR}", f"Great Britain reported road collisions by weather conditions, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "weather_conditions",
        labelled("weather_conditions", weather_codes), [item("weather_conditions"), stats20_item(weather_codes, weather_page, weather_line, "1.22 Weather")],
        [derived("distribution.parameters.counts", "records grouped by weather_conditions, labelled from STATS20 section 1.22", "Each record is one collision; the code labels come from the STATS20 specification.")],
        note + DVLA_NOTE, STATS19_TAGS + ["weather"], STATS19_USES,
    )

    speed_by_severity: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["speed_limit"].isdigit() and r["collision_severity"] in severity_codes:
            speed_by_severity[severity_codes[r["collision_severity"]]][r["speed_limit"]] += 1
    yield conditional(
        f"gb-road-collisions-speed-limit-given-severity-{STATS19_YEAR}", f"Great Britain reported road collisions: speed limit of the road given collision severity, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period,
        "speed_limit_mph", "collision_severity", {sev: ordered(speed_by_severity[sev], int) for sev in severity_codes.values()}, [item("speed_limit"), item("collision_severity"), stats20_item(severity_codes, severity_page, severity_line, "1.4a Legacy collision severity")],
        [derived("distributions[*].parameters.counts", "records grouped by collision_severity then speed_limit; records with a missing speed limit dropped", "Each record is one collision on a road with the stated speed limit in miles per hour.")],
        note + "Conditioning keys are Fatal, Serious and Slight; categories are the speed limit in mph. " + DVLA_NOTE, STATS19_TAGS + ["speed-limit", "severity"], STATS19_USES,
    )

    raw = get(VEHICLE_URL)
    text = raw.decode("utf-8")
    vehicles = csv_rows(text, ("collision_index", "vehicle_reference", "vehicle_type", "age_of_driver", "age_of_vehicle"))
    lead = vehicles[0]
    line = first_line(text, lambda l: l.startswith(lead["collision_index"] + ","))
    vehicle_codes, vehicle_page, vehicle_line = pdf_codes(pages, "2.5 TYPE OF VEHICLE", "NOTES")
    title = f"DfT road safety data: dft-road-casualty-statistics-vehicle-{STATS19_YEAR}.csv (STATS19 vehicles involved, Great Britain)"
    vehicle_note = f"Vehicles involved in personal-injury road collisions reported to the police in Great Britain in {STATS19_YEAR}, from the DfT road safety open data (STATS19) vehicle file, one record per vehicle. "

    def vehicle_item(column: str) -> dict:
        return evidence(DFT, title, VEHICLE_URL, f"record collision_index={lead['collision_index']}, vehicle_reference={lead['vehicle_reference']}, column {column}", lead[column], "text", fields_prefix(line, 8), OGL, raw)

    counter = Counter(v["vehicle_type"] for v in vehicles if v["vehicle_type"] in vehicle_codes)
    yield marginal(
        f"gb-vehicles-in-road-collisions-by-type-{STATS19_YEAR}", f"Great Britain vehicles involved in reported road collisions by vehicle type, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "vehicle_type",
        {vehicle_codes[code]: n for code, n in counter.most_common()}, [vehicle_item("vehicle_type"), stats20_item(vehicle_codes, vehicle_page, vehicle_line, "2.5 Type of vehicle")],
        [derived("distribution.parameters.counts", "records grouped by vehicle_type, labelled from STATS20 section 2.5; codes outside the list dropped", "Each record is one vehicle involved in a collision; the code labels come from the STATS20 specification.")],
        vehicle_note + DVLA_NOTE, STATS19_TAGS + ["vehicle-type"], STATS19_USES + ["automotive-demo"],
    )

    ages = Counter(int(v["age_of_driver"]) for v in vehicles if v["age_of_driver"].isdigit())
    yield empirical(
        f"gb-drivers-in-road-collisions-age-{STATS19_YEAR}", f"Great Britain age of drivers and riders involved in reported road collisions, {STATS19_YEAR} (DfT STATS19)", "transport", "GB", "verified", period, "driver_age_years", "integer", dict(ages),
        [vehicle_item("age_of_driver")],
        [derived("distribution.parameters.values and weights", "distinct age_of_driver values with their record counts; missing ages (-1) dropped", "Each record is one vehicle with the age of its driver or rider in years; the empirical distribution weights each age by its number of records.")],
        vehicle_note + "Ages are the age_of_driver values in whole years. " + DVLA_NOTE, STATS19_TAGS + ["driver-age", "age"], STATS19_USES + ["person-generation"],
    )

    vehicle_ages = Counter(int(v["age_of_vehicle"]) for v in vehicles if v["age_of_vehicle"].isdigit())
    yield empirical(
        f"gb-vehicles-in-road-collisions-age-{STATS19_YEAR}", f"Great Britain age in years of vehicles involved in reported road collisions, {STATS19_YEAR} (DfT STATS19)", "automotive", "GB", "verified", period, "vehicle_age_years", "integer", dict(vehicle_ages),
        [vehicle_item("age_of_vehicle")],
        [derived("distribution.parameters.values and weights", "distinct age_of_vehicle values with their record counts; missing ages (-1) dropped", "Each record is one vehicle with its age in years at the collision; the empirical distribution weights each age by its number of records.")],
        vehicle_note + "Vehicle age is the age_of_vehicle value in whole years, so the distribution describes the vehicles that get into collisions rather than the licensed fleet. " + DVLA_NOTE, STATS19_TAGS + ["vehicle-age"], STATS19_USES + ["automotive-demo"],
    )


# ---------------------------------------------------------------- DVSA MOT


def number(text: str) -> float | int | None:
    cleaned = text.replace(",", "").replace("%", "").strip()
    if not cleaned:
        return None
    return float(cleaned) if "." in cleaned else int(cleaned)


def mot_entries() -> Iterable[dict]:
    raw = get(MOT_RESULTS_URL)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text)
    latest = MOT_FINANCIAL_YEAR
    year_rows = [r for r in rows if r["Period"].strip() == "Total" and r["Financial year"].strip() == latest]
    lead = year_rows[0]
    table = {}
    for r in year_rows:
        table[r["Class"].split(":")[0].strip()] = {
            "class_description": r["Class"],
            "tests": number(r["Tests"]),
            "pass_after_rectification": number(r["Pass after rectification at MOT test station"]),
            "fails": number(r["Fails"]),
            "initial_fail_rate_percent": number(r["Initial fail rate"]),
            "final_fail_rate_percent": number(r["Final fail rate"]),
            "tests_failed_with_dangerous_item": number(r["Tests failed with at least one dangerous item"]),
            "initial_fail_rate_dangerous_item_percent": number(r["Initial fail rate for tests with at least one dangerous item"]),
        }
    start_year, end_year = latest.split(" to ")
    title = "DVSA MOT testing data for Great Britain, table 01: MOT test results by class of vehicle (CSV)"
    yield lookup(
        f"gb-mot-test-results-by-vehicle-class-{start_year}-{end_year[-2:]}", f"Great Britain MOT test results by class of vehicle, financial year {latest}: tests, fails and fail rates (DVSA)", "automotive", "GB", "verified", (f"{start_year}-04-01", f"{end_year}-03-31"),
        {"source": "dvsa-mot-01", "financial_year": latest, "period": "Total"}, table, tuple(list(table)[:2]), "tests",
        [evidence(DVSA, title, MOT_RESULTS_URL, f"row {latest} / Total / {lead['Class']}, column Initial fail rate", number(lead["Initial fail rate"]), "percent", f"{lead['Financial year']},{lead['Period']},", OGL, raw), evidence(DVSA, title, MOT_RESULTS_URL, f"row {latest} / Total / {lead['Class']}, column Tests", lead["Tests"], "text", f'"{lead["Tests"]}"', OGL, raw)],
        [derived("rows[*].tests, fails and pass_after_rectification", "published figures with thousands separators removed", "Counts are published as quoted strings with comma separators; they are stored as integers.")],
        f"MOT test outcomes for the financial year {latest} (rows with Period Total) by test class from DVSA table 01: tests conducted, passes after rectification at the test station, fails, the initial and final fail rates in percent, "
        "and the tests failed with at least one dangerous item. "
        "The table also carries 2025 to 2026, but its Total rows there do not reconcile with the sum of its quarters and its dangerous-item columns exceed the test counts for some classes, so the last internally consistent financial year is used. Rows are keyed by the class label (Classes 1 & 2, Classes 3 & 4, Class 5, Class 7) and carry the full class description. " + DVLA_NOTE,
        ["mot", "dvsa", "vehicle-inspection", "pass-rate", "reference-table", "transport", "vehicles"], ["fleet-demo", "automotive-demo", "insurance-demo", "telematics-demo"],
    )

    raw = get(MOT_DEFECTS_URL)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text)
    year_rows = [r for r in rows if r["Financial year"].strip() == latest and r["Period"].strip() == "Total"]
    lead = max(year_rows, key=lambda r: number(r["Overall % of defects"]) or 0)
    defects = {r["Defect category"]: number(r["Overall % of defects"]) for r in year_rows if number(r["Overall % of defects"]) is not None}
    shares = {k: round(v / sum(defects.values()), 6) for k, v in defects.items()}
    title = "DVSA MOT testing data for Great Britain, table 03: MOT class 3 and 4 vehicles, initial failures by defect category (CSV)"
    top = max(shares, key=shares.get)
    entry = base(f"gb-mot-initial-failure-defects-by-category-classes-3-4-{start_year}-{end_year[-2:]}", f"Great Britain MOT initial failure defects by category, classes 3 and 4 (cars and vans), financial year {latest} (DVSA)", "marginal", "automotive", "GB", "verified", ["mot", "dvsa", "vehicle-inspection", "defects", "transport", "vehicles"], ["fleet-demo", "automotive-demo", "claims-generation", "insurance-demo"])
    entry.update(
        observed_period={"start": f"{start_year}-04-01", "end": f"{end_year}-03-31"},
        spec={"variable": "defect_category", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "published_percent_of_defects": defects, "percent_of_tests": {r["Defect category"]: number(r["Overall % of tests"]) for r in year_rows}}}},
        evidence=[evidence(DVSA, title, MOT_DEFECTS_URL, f"row {latest} / Total / {lead['Defect category']}, column Overall % of defects", number(lead["Overall % of defects"]), "percent", f'{lead["Financial year"]},{lead["Period"]},"{lead["Defect category"]}"' if "," in lead["Defect category"] else f"{lead['Financial year']},{lead['Period']},{lead['Defect category']}", OGL, raw)],
        assumed=[derived("distribution.parameters.shares", "Overall % of defects / sum over categories", "DVSA publishes the percentage of all defects falling in each category; the shares renormalise those percentages to sum to one.")],
        tests=[{"statistic": f'share["{top}"]', "expected": shares[top], "tolerance": 0.005}, {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4}],
        notes=f"Defects recorded at initial MOT failures of class 3 and 4 vehicles (cars, vans and passenger vehicles with up to 12 seats) in financial year {latest} by defect category from DVSA table 03, "
        "with the published percentage of defects and percentage of tests beside the derived shares. " + DVLA_NOTE,
    )
    yield entry


# ---------------------------------------------------------------- ORR rail and CAA airports


def orr_entry() -> dict:
    raw = get(ORR_URL)
    sheet = ods_sheets(raw)["1220_Passenger_journeys"]
    series = []
    cells = {}
    for row in sheet:
        if len(row) < 2 or not row[0][1].startswith("Apr ") or row[1][0] is None:
            continue
        match = re.match(r"Apr (\d{4}) to Mar (\d{4})", row[0][1])
        period = f"{match.group(1)}/{match.group(2)[-2:]}"
        series.append({"period": period, "value": round(float(row[1][0]), 3), "provisional": 1 if "[p]" in row[0][1] else 0})
        cells[period] = row[1]
    recent = [p for p in series if int(p["period"][:4]) >= 2000]
    title = "ORR data portal table 1220: passenger journeys, Great Britain (ODS)"
    first, last = recent[0], recent[-1]
    return temporal(
        f"gb-rail-passenger-journeys-annual-{first['period'][:4]}-{last['period'][-2:]}", f"Great Britain national rail passenger journeys in millions per financial year, {first['period']} to {last['period']} (ORR table 1220)", "transport", "GB", "license-review", (f"{first['period'][:4]}-04-01", f"{int(last['period'][:4]) + 1}-03-31"),
        "rail_passenger_journeys_million", "decimal", "annual", recent,
        [ods_item(ORR, title, ORR_URL, raw, f"sheet 1220_Passenger_journeys, row {last['period']}, Passenger journeys (million)", cells[last["period"]], "decimal", UNSTATED), ods_item(ORR, title, ORR_URL, raw, f"sheet 1220_Passenger_journeys, row {first['period']}, Passenger journeys (million)", cells[first["period"]], "decimal", UNSTATED)],
        [derived("series[*].value", "published value rounded to three decimals", "The workbook stores unrounded floating-point values and displays one decimal; three decimals are kept."), derived("series[*].provisional", "1 where the row label carries [p]", "ORR marks provisional years with [p] in the period label.")],
        "Passenger journeys on Great Britain's national rail network (franchised and open access operators, excluding Eurostar, Underground and light rail) per financial year April to March from ORR table 1220, "
        "from the 2000/01 financial year. The provisional column flags years ORR marks [p]. The ORR data portal page and workbook carry no licence statement, so the licence is recorded as unstated and the entry held at license-review.",
        ["rail", "passenger-journeys", "orr", "transport", "mobility"], ["travel-demo", "demand-forecasting", "capacity-planning"],
    )


def caa_entry() -> dict:
    raw = get(CAA_URL)
    text = raw.decode("utf-8-sig")
    rows = csv_rows(text)
    rows = [r for r in rows if r.get("this_period") == CAA_YEAR]
    table = {}
    for r in rows:
        table[r["rpt_apt_name"]] = {
            "airport_group": r["rpt_apt_grp_name"],
            "total_passengers": int(r["total_pax_tp"]),
            "terminal_passengers": int(r["term_pax_tp"]),
            "transit_passengers": int(r["tran_pax_tp"]),
            "total_passengers_previous_year": int(r["total_pax_lp"]),
            "change_percent": round(float(r["total_pax_pc"]), 2) if re.fullmatch(r"-?\d+(\.\d+)?", r["total_pax_pc"]) else None,
        }
    table = dict(sorted(table.items()))
    lead = max(rows, key=lambda r: int(r["total_pax_tp"]))
    title = f"UK Civil Aviation Authority airport data {CAA_YEAR}, annual Table 09: terminal and transit passengers (CSV)"
    return lookup(
        f"gb-airport-passengers-{CAA_YEAR}", f"United Kingdom airport passengers by airport, {CAA_YEAR}: total, terminal and transit passengers with the change on {int(CAA_YEAR) - 1} (CAA Table 09)", "transport", "GB", "license-review", (f"{CAA_YEAR}-01-01", f"{CAA_YEAR}-12-31"),
        {"source": "CAA airport data Table 09", "year": int(CAA_YEAR)}, table, (lead["rpt_apt_name"], rows[0]["rpt_apt_name"]), "total_passengers",
        [evidence(CAA, title, CAA_URL, f"row rpt_apt_name={lead['rpt_apt_name']}, column total_pax_tp", lead["total_pax_tp"], "count", f"{lead['rpt_apt_grp_name']},{lead['rpt_apt_name']},{lead['total_pax_tp']},{lead['total_pax_lp']}", UNSTATED, raw)],
        [derived("rows[*].change_percent", "total_pax_pc rounded to two decimals", "The CSV carries the percentage change with nine decimals.")],
        f"Terminal and transit passengers at UK airports reporting to the CAA in {CAA_YEAR}, with the previous year's total and the percentage change, from the annual airport statistics Table 09. "
        "Rows are keyed by the airport name as the CAA spells it (upper case) and carry the reporting group (London area or other UK airports). The CAA download carries no licence statement, so the licence is recorded as unstated and the entry held at license-review.",
        ["aviation", "airports", "passengers", "caa", "reference-table", "transport"], ["travel-demo", "demand-forecasting", "capacity-planning", "logistics-demo"],
    )


# ---------------------------------------------------------------- Eurostat


def eurostat_entries() -> Iterable[dict]:
    names = codelist("GEO")
    flags = codelist("OBS_FLAG")

    url = data_url("road_eqs_carage", f"A.NR..{GEO_KEY}", "2024", "2024")
    raw = get(url)
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    age_labels = codelist("AGE")
    groups: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: (r["geo"], r["age"])):
        if not r["OBS_VALUE"]:
            continue
        if r["age"] == "TOTAL":
            totals[r["geo"]] = int(float(r["OBS_VALUE"]))
        else:
            groups.setdefault(r["geo"], {})[age_labels.get(r["age"], r["age"])] = int(float(r["OBS_VALUE"]))
    groups = {geo: counts for geo, counts in groups.items() if len(counts) > 1}
    de = next(r for r in rows if r["geo"] == "DE" and r["age"] == "TOTAL")
    yield conditional(
        f"eu-passenger-car-stock-by-age-given-country-{year}", f"Passenger cars in use by age of vehicle given country, {year}, member states reported by Eurostat (road_eqs_carage)", "automotive", "EU", "verified", (f"{year}-12-31", f"{year}-12-31"),
        "vehicle_age_band", "country", groups,
        [evidence(EUROSTAT, dataflow_title("road_eqs_carage", "passenger cars by age"), url, f"geo=DE, age=TOTAL, TIME_PERIOD={year}, OBS_VALUE", de["OBS_VALUE"], "count", f"TOTAL,DE,{year},{de['OBS_VALUE']}", EUROSTAT_LICENSE, raw)],
        [derived("distributions[*].parameters.shares", "count of an age band / sum over the published age bands", "Eurostat publishes the number of cars per age band and a total; shares divide by the sum of the bands actually published for the country, which can differ from the total when a band is missing.")],
        f"Stock of passenger cars at the end of {year} by age of vehicle for the ten member states in the Almanac's Eurostat set that report the breakdown, from dataflow road_eqs_carage. Age bands carry the English labels of the AGE codelist; each distribution also carries the country name and the published_total."
        + flag_sentence(flagged_cells([r for r in rows if r["geo"] in groups], lambda r: f"{r['geo']} {r['age']}"), flags) + " " + EUROSTAT_NOTE,
        ["vehicles", "cars", "vehicle-age", "eurostat", "by-country"], ["fleet-demo", "insurance-demo", "automotive-demo", "telematics-demo"],
        extra={geo: {"name": names.get(geo, geo), "published_total": totals.get(geo)} for geo in groups},
    )

    url = data_url("rail_pa_quartal", f"Q.MIO_PKM+THS_PAS.{GEO_KEY}", "2024-Q1", "2025-Q4")
    raw = get(url)
    rows = rows_of(raw)
    by_period: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        if r["OBS_VALUE"]:
            by_period[r["TIME_PERIOD"]][f"{r['geo'].lower()}_{'passenger_km_million' if r['unit'] == 'MIO_PKM' else 'passengers_thousand'}"] = float(r["OBS_VALUE"])
    periods = sorted(by_period)
    complete = sorted(c for c in {c for v in by_period.values() for c in v} if all(c in by_period[p] for p in periods))
    series = [{"period": p, "value": by_period[p]["de_passengers_thousand"], **{c: by_period[p][c] for c in complete if c != "de_passengers_thousand"}} for p in periods]
    de = next(r for r in rows if r["geo"] == "DE" and r["unit"] == "THS_PAS" and r["TIME_PERIOD"] == periods[0])
    yield temporal(
        f"eu-rail-passengers-quarterly-{periods[0][:4]}-{periods[-1][:4]}", f"Rail passengers carried and passenger-kilometres per quarter, {periods[0]} to {periods[-1]}, member states reported by Eurostat (rail_pa_quartal)", "transport", "EU", "verified", (f"{periods[0][:4]}-01-01", f"{periods[-1][:4]}-12-31"),
        "rail_passengers_thousand_de", "decimal", "quarterly", series,
        [evidence(EUROSTAT, dataflow_title("rail_pa_quartal", "rail passenger transport, quarterly data"), url, f"geo=DE, unit=THS_PAS, TIME_PERIOD={periods[0]}, OBS_VALUE", de["OBS_VALUE"], "decimal", f"THS_PAS,DE,{periods[0]},{de['OBS_VALUE']}", EUROSTAT_LICENSE, raw)],
        [],
        f"Quarterly rail passengers (thousands) and passenger-kilometres (millions) from Eurostat dataflow rail_pa_quartal for the member states of the Almanac's Eurostat set that publish every quarter of the window; "
        "Germany's passengers in thousands is the series value and the other country-unit pairs ride along as columns named geo_unit. Countries with confidential or missing quarters (shown in the SDMX response as empty values) are omitted."
        + flag_sentence(flagged_cells([r for r in rows if any(c.startswith(r["geo"].lower()) for c in complete)], lambda r: f"{r['geo']} {r['unit']} {r['TIME_PERIOD']}"), flags) + " " + EUROSTAT_NOTE,
        ["rail", "passengers", "eurostat", "by-country", "by-quarter", "transport"], ["travel-demo", "demand-forecasting", "capacity-planning"],
    )

    url = data_url("mar_go_qm", "Q.TOTAL.TOTAL.THS_T." + "+".join(g for g in GEO_KEY.split("+") if g != "AT"), "2024-Q1", "2025-Q4")
    raw = get(url)
    rows = [{**r, "geo": r["rep_mar"]} for r in rows_of(raw)]
    by_period = defaultdict(dict)
    for r in rows:
        if r["OBS_VALUE"]:
            by_period[r["TIME_PERIOD"]][r["geo"].lower()] = float(r["OBS_VALUE"])
    periods = sorted(by_period)
    complete = sorted(c for c in {c for v in by_period.values() for c in v} if all(c in by_period[p] for p in periods))
    series = [{"period": p, "value": by_period[p]["de"], **{c: by_period[p][c] for c in complete if c != "de"}} for p in periods]
    de = next(r for r in rows if r["geo"] == "DE" and r["TIME_PERIOD"] == periods[0])
    yield temporal(
        f"eu-maritime-port-freight-quarterly-{periods[0][:4]}-{periods[-1][:4]}", f"Gross weight of goods handled in main ports per quarter in thousand tonnes, {periods[0]} to {periods[-1]}, member states reported by Eurostat (mar_go_qm)", "transport", "EU", "verified", (f"{periods[0][:4]}-01-01", f"{periods[-1][:4]}-12-31"),
        "port_freight_thousand_tonnes_de", "decimal", "quarterly", series,
        [evidence(EUROSTAT, dataflow_title("mar_go_qm", "gross weight of goods handled in main ports, quarterly data"), url, f"rep_mar=DE, TIME_PERIOD={periods[0]}, OBS_VALUE", de["OBS_VALUE"], "decimal", f"THS_T,DE,{periods[0]},{de['OBS_VALUE']}", EUROSTAT_LICENSE, raw)],
        [],
        f"Quarterly gross weight of goods handled in main ports (all directions, national and international traffic, thousand tonnes) from Eurostat dataflow mar_go_qm for the maritime member states of the Almanac's Eurostat set "
        "with every quarter of the window published; Germany is the series value and the other countries ride along as columns keyed by the lower-case reporting-country code (dimension rep_mar). Austria is not a reporting country of the dataflow (the API rejects its code), so it is left out."
        + flag_sentence(flagged_cells([r for r in rows if r["geo"].lower() in complete], lambda r: f"{r['geo']} {r['TIME_PERIOD']}"), flags) + " " + EUROSTAT_NOTE,
        ["maritime", "ports", "freight", "shipping", "logistics", "eurostat", "by-country", "by-quarter", "transport"], ["logistics-demo", "demand-forecasting", "capacity-planning"],
    )


BUILDERS: dict[str, Callable[[], Iterable[dict]]] = {
    "fars": fars_entries,
    "recalls": recalls_entries,
    "epa": epa_entries,
    "faa-registry": faa_registry_entries,
    "nasr": nasr_entries,
    "border": border_entries,
    "dvla": dvla_entries,
    "traffic": traffic_entries,
    "stats19": stats19_entries,
    "mot": mot_entries,
    "orr": lambda: [orr_entry()],
    "caa": lambda: [caa_entry()],
    "eurostat": eurostat_entries,
}


def main(argv: list[str]) -> int:
    """Rebuild every source group, or only the groups named on the command line."""
    selected = argv or list(BUILDERS)
    unknown = sorted(set(selected) - set(BUILDERS))
    if unknown:
        print(f"unknown source group(s): {', '.join(unknown)}; choose from {', '.join(BUILDERS)}", file=sys.stderr)
        return 2
    for name in selected:
        for entry in BUILDERS[name]():
            write(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

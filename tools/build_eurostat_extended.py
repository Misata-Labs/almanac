"""Regenerate the extended Eurostat entries: cross-country reference tables for the latest reported
period (minimum wages, employment, GDP per capita, income, housing costs, energy prices, digital
indicators, car registrations, life expectancy, fertility, marriage and household size), monthly
series for youth unemployment and tourism nights, household composition by country, and single-year
age distributions for eight further member states. Run from the repository root:

    uv run python tools/build_eurostat_extended.py
"""

from __future__ import annotations

import csv
import io
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write

API = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1"
PUBLISHER = "Eurostat"
LICENSE = "CC-BY-4.0"
GEOS = ["DE", "FR", "IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"]
GEO_KEY = "+".join(GEOS)
LICENSE_NOTE = (
    "Eurostat's copyright notice states that its data are released under the Creative Commons Attribution 4.0 "
    "International licence; the notice page renders dynamically and is referenced rather than hashed."
)
SDMX_STRUCTURE = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}"
SDMX_COMMON = "{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def rows_of(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def data_url(dataflow: str, key: str, start: str, end: str) -> str:
    return f"{API}/data/{dataflow}/{key}?startPeriod={start}&endPeriod={end}&format=SDMX-CSV"


def codelist(name: str) -> dict[str, str]:
    """Return the English labels of an Eurostat SDMX codelist keyed by code."""
    root = ET.fromstring(fetch(f"{API}/codelist/ESTAT/{name}"))
    labels = {}
    for code in root.iter(f"{SDMX_STRUCTURE}Code"):
        english = next((n.text or "" for n in code.findall(f"{SDMX_COMMON}Name") if n.get(XML_LANG) == "en"), None)
        if english is not None:
            labels[code.get("id")] = english.strip()
    return labels


def dataflow_title(dataflow: str, description: str) -> str:
    return f"Eurostat SDMX 2.1 API, dataflow {dataflow} ({description}), SDMX-CSV"


def half_year_bounds(period: str) -> tuple[str, str]:
    year, half = period.split("-S")
    return (f"{year}-01-01", f"{year}-06-30") if half == "1" else (f"{year}-07-01", f"{year}-12-31")


def flagged_cells(rows: list[dict[str, str]], describe: Callable[[dict[str, str]], str]) -> list[tuple[str, str]]:
    """Pair a description of each flagged observation with its OBS_FLAG code."""
    return [(describe(r), r["OBS_FLAG"]) for r in rows if r["OBS_FLAG"] and r["OBS_VALUE"]]


def flag_sentence(cells: list[tuple[str, str]], flags: dict[str, str]) -> str:
    """Spell out the flagged observations so a reader knows which cells Eurostat qualifies."""
    if not cells:
        return ""
    return " Observation flags published with the data: " + "; ".join(f"{where} {flags.get(code, code)}" for where, code in cells) + "."


def cell_evidence(dataflow: str, description: str, url: str, raw: bytes, cell: dict[str, str], column: Column, unit: str) -> dict:
    """Cite one observation of a table through the geo, the selecting dimension codes and the period."""
    dims = ", ".join(f"{d}={c}" for d, c in column.match.items())
    return evidence(PUBLISHER, dataflow_title(dataflow, description), url, f"geo={cell['geo']}, {dims}, TIME_PERIOD={cell['TIME_PERIOD']}, OBS_VALUE", cell["OBS_VALUE"], unit, f"{cell['geo']},{cell['TIME_PERIOD']},{cell['OBS_VALUE']}", LICENSE, raw)


@dataclass(frozen=True)
class Column:
    """One named column of a reference table, selected by the dimension codes its rows carry."""

    name: str
    match: dict[str, str]
    cast: Callable[[str], float | int] = float

    def selects(self, row: dict[str, str]) -> bool:
        return all(row.get(dim) == code for dim, code in self.match.items())


@dataclass(frozen=True)
class Table:
    """A reference table keyed by geo code, built from SDMX-CSV rows and the columns to keep."""

    rows: dict[str, dict]
    period: str
    source_rows: list[dict[str, str]]

    @classmethod
    def build(cls, raw: bytes, columns: list[Column], names: dict[str, str], require: str | None = None) -> Table:
        source = rows_of(raw)
        table: dict[str, dict] = {}
        for r in source:
            column = next((c for c in columns if c.selects(r)), None)
            if column is None:
                continue
            record = table.setdefault(r["geo"], {"name": names.get(r["geo"], r["geo"])})
            record[column.name] = column.cast(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
        if require is not None:
            table = {geo: rec for geo, rec in table.items() if rec.get(require) is not None}
        for record in table.values():
            for column in columns:
                record.setdefault(column.name, None)
        return cls(dict(sorted(table.items())), source[0]["TIME_PERIOD"], source)

    def cell(self, geo: str, column: Column) -> dict[str, str]:
        return next(r for r in self.source_rows if r["geo"] == geo and column.selects(r) and r["OBS_VALUE"])

    def vectors(self, column: Column, geos: tuple[str, str] = ("DE", "FR")) -> list[dict]:
        vectors = [{"input": {"key": g, "column": column.name}, "expected": self.rows[g][column.name], "origin": "source"} for g in geos if g in self.rows]
        return vectors + [{"input": "XX", "expected": False, "origin": "derived"}]

    def row_flags(self, columns: list[Column]) -> list[tuple[str, str]]:
        kept = [r for r in self.source_rows if any(c.selects(r) for c in columns) and r["geo"] in self.rows]
        return flagged_cells(kept, lambda r: f"{r['geo']} {next(c.name for c in columns if c.selects(r))}")


@dataclass(frozen=True)
class JoinSpec:
    """Where a supplementary column comes from: a second dataflow queried for the same period."""

    dataflow: str
    description: str
    key: str
    column: Column
    unit: str
    evidence_geo: str

    def fetch(self, start: str, end: str) -> Join:
        url = data_url(self.dataflow, self.key, start, end)
        return Join(self, url, fetch(url))


@dataclass(frozen=True)
class Join:
    """A supplementary column, fetched, ready to attach to an existing table by geo code."""

    spec: JoinSpec
    url: str
    raw: bytes

    def apply(self, table: Table, parameters: dict, vectors: list[dict], items: list[dict]) -> list[tuple[str, str]]:
        column, geo = self.spec.column, self.spec.evidence_geo
        rows = [r for r in rows_of(self.raw) if r["geo"] in table.rows]
        by_geo = {r["geo"]: r for r in rows if r["OBS_VALUE"] and column.selects(r)}
        for code, record in table.rows.items():
            record[column.name] = column.cast(by_geo[code]["OBS_VALUE"]) if code in by_geo else None
        parameters[f"{column.name}_dataflow"] = self.spec.dataflow
        parameters[f"{column.name}_key"] = self.spec.key
        vectors.insert(-1, {"input": {"key": geo, "column": column.name}, "expected": table.rows[geo][column.name], "origin": "source"})
        items.append(cell_evidence(self.spec.dataflow, self.spec.description, self.url, self.raw, by_geo[geo], column, self.spec.unit))
        return flagged_cells(rows, lambda r: f"{r['geo']} {column.name}")


@dataclass(frozen=True)
class LookupEntry:
    """Everything that distinguishes one cross-country lookup table from another."""

    entry_id: str
    title: str
    domain: str
    dataflow: str
    description: str
    key: str
    columns: list[Column]
    unit: str
    tags: list[str]
    use_cases: list[str]
    note: str
    valid: tuple[str, str]
    evidence_geos: tuple[str, str] = ("DE", "FR")
    require: str | None = None
    assumed: list[dict] = field(default_factory=list)
    derive: Callable[[dict], None] | None = None
    joins: tuple[JoinSpec, ...] = ()

    def build(self, url: str, raw: bytes, names: dict[str, str], flags: dict[str, str], joins: tuple[Join, ...] = ()) -> dict:
        table = Table.build(raw, self.columns, names, self.require)
        lead = self.columns[0]
        items = [cell_evidence(self.dataflow, self.description, url, raw, table.cell(geo, lead), lead, self.unit) for geo in self.evidence_geos]
        vectors = table.vectors(lead, self.evidence_geos)
        parameters = {"dataflow": self.dataflow, "key": self.key, "period": table.period, "rows": table.rows}
        flagged = table.row_flags(self.columns)
        for join in joins:
            flagged += join.apply(table, parameters, vectors, items)
        if self.derive is not None:
            for record in table.rows.values():
                self.derive(record)
        numeric = [c.name for c in self.columns if table.rows["DE"].get(c.name) is not None]
        return {
            "id": self.entry_id,
            "title": self.title,
            "kind": "rule",
            "domain": self.domain,
            "region": "EU",
            "status": "verified",
            "tier": "A",
            "valid_from": self.valid[0],
            "valid_to": self.valid[1],
            "tags": self.tags + ["eurostat", "reference-table", "by-country"],
            "use_cases": self.use_cases,
            "spec": {
                "implementation": "almanac.rules.lookup_table",
                "parameters": parameters,
                "vectors": vectors,
            },
            "evidence": items,
            "assumed": self.assumed,
            "tests": [
                {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
                {"statistic": "count", "expected": len(table.rows), "tolerance": 0},
                {"statistic": f"max[{numeric[0]}]", "expected": max(r[numeric[0]] for r in table.rows.values() if r[numeric[0]] is not None), "tolerance": 0},
            ],
            "notes": self.note + " Rows are keyed by the Eurostat geo code and carry the English country name from the GEO codelist." + flag_sentence(flagged, flags) + " " + LICENSE_NOTE,
        }


def monthly_by_geo(entry_id: str, title: str, domain: str, dataflow: str, description: str, url: str, raw: bytes, variable: str, unit: str, tags: list[str], use_cases: list[str], note: str, flags: dict[str, str]) -> dict:
    rows = rows_of(raw)
    by_period: dict[str, dict[str, float]] = {}
    for r in rows:
        by_period.setdefault(r["TIME_PERIOD"], {})[r["geo"]] = float(r["OBS_VALUE"])
    periods = sorted(by_period)
    year = periods[0][:4]
    columns = [g.lower() for g in GEOS if g != "DE"]
    series = [{"period": p, "value": by_period[p]["DE"], **{g.lower(): by_period[p][g] for g in GEOS if g != "DE"}} for p in periods]
    de_first = next(r for r in rows if r["geo"] == "DE" and r["TIME_PERIOD"] == periods[0])
    fr_last = next(r for r in rows if r["geo"] == "FR" and r["TIME_PERIOD"] == periods[-1])
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": tags + ["eurostat", "by-country"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER, dataflow_title(dataflow, description), url, f"geo=DE, TIME_PERIOD={periods[0]}, OBS_VALUE", de_first["OBS_VALUE"], unit, f"DE,{periods[0]},{de_first['OBS_VALUE']}", LICENSE, raw),
            evidence(PUBLISHER, dataflow_title(dataflow, description), url, f"geo=FR, TIME_PERIOD={periods[-1]}, OBS_VALUE", fr_last["OBS_VALUE"], unit, f"FR,{periods[-1]},{fr_last['OBS_VALUE']}", LICENSE, raw),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{periods[0]}]", "expected": series[0]["value"], "tolerance": 1e-9},
            {"statistic": f"column[fr,{periods[-1]}]", "expected": series[-1]["fr"], "tolerance": 1e-9},
            {"statistic": "max", "expected": max(p["value"] for p in series), "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " Germany is the primary series; the other nine member states ride along as columns keyed by their two-letter geo code." + flag_sentence(flagged_cells(rows, lambda r: f"{r['geo']} {r['TIME_PERIOD']}"), flags) + " " + LICENSE_NOTE,
    }


HOUSEHOLD_TYPES = {
    "A1_CH": "one_adult_with_children",
    "A1_NCH": "one_adult_without_children",
    "CPL_CH": "couple_with_children",
    "CPL_NCH": "couple_without_children",
    "OTH_CH": "other_with_children",
    "OTH_NCH": "other_without_children",
}


def household_composition(url: str, raw: bytes, names: dict[str, str]) -> dict:
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    thousands: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["phhcomp"] in HOUSEHOLD_TYPES:
            thousands.setdefault(r["geo"], {})[HOUSEHOLD_TYPES[r["phhcomp"]]] = float(r["OBS_VALUE"])
    distributions = {}
    for geo in sorted(thousands):
        counts = thousands[geo]
        total = sum(counts.values())
        shares = {k: round(v / total, 6) for k, v in counts.items()}
        distributions[geo] = {"family": "categorical", "parameters": {"shares": shares, "thousand_households": counts, "name": names.get(geo, geo)}}
    de = next(r for r in rows if r["geo"] == "DE" and r["phhcomp"] == "CPL_CH")
    fr = next(r for r in rows if r["geo"] == "FR" and r["phhcomp"] == "A1_NCH")
    return {
        "id": f"eu-household-composition-by-country-{year}",
        "title": f"Private households by type, given country, {year}, ten member states (Eurostat lfst_hhnhtych)",
        "kind": "conditional",
        "domain": "demographics",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": ["households", "household-composition", "eurostat", "by-country"],
        "use_cases": ["household-generation", "person-generation", "customer-segmentation", "market-sizing"],
        "spec": {"variable": "household_type", "unit": "ratio", "given": "country", "distributions": distributions},
        "evidence": [
            evidence(PUBLISHER, dataflow_title("lfst_hhnhtych", "number of private households by household composition"), url, f"geo=DE, phhcomp=CPL_CH, TIME_PERIOD={year}, OBS_VALUE", de["OBS_VALUE"], "decimal", f"CPL_CH,THS_HH,DE,{year},{de['OBS_VALUE']}", LICENSE, raw),
            evidence(PUBLISHER, dataflow_title("lfst_hhnhtych", "number of private households by household composition"), url, f"geo=FR, phhcomp=A1_NCH, TIME_PERIOD={year}, OBS_VALUE", fr["OBS_VALUE"], "decimal", f"A1_NCH,THS_HH,FR,{year},{fr['OBS_VALUE']}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "distributions[*].parameters.shares", "value": "thousand households of a type / sum over the six types", "method": "derived", "rationale": "Eurostat publishes household counts in thousands per composition type; shares are each type over the sum of the six mutually exclusive types, so the published TOTAL (which also covers households of unknown type) is not used as the denominator."},
        ],
        "tests": [
            {"statistic": "share[DE,couple_with_children]", "expected": distributions["DE"]["parameters"]["shares"]["couple_with_children"], "tolerance": 0.005},
            {"statistic": "share[FR,one_adult_without_children]", "expected": distributions["FR"]["parameters"]["shares"]["one_adult_without_children"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[DE]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[IE]", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            f"Private households in {year} by composition for ten member states from Eurostat dataflow lfst_hhnhtych (EU Labour Force Survey, all ages of children, any number of children, thousands of households). "
            "Six mutually exclusive types are kept: one adult, couple, or other household, each with or without children (Eurostat codes A1_CH, A1_NCH, CPL_CH, CPL_NCH, OTH_CH, OTH_NCH). "
            "Each distribution keeps the published thousands beside the derived shares. " + LICENSE_NOTE
        ),
    }


def age_marginal(geo: str, name: str, url: str, raw: bytes) -> dict:
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    counts: dict[str, int] = {}
    for r in rows:
        age = r["age"]
        if age in ("TOTAL", "UNK"):
            continue
        label = {"Y_LT1": "0", "Y_OPEN": "100+"}.get(age, age[1:])
        counts[label] = int(float(r["OBS_VALUE"]))
    counts = dict(sorted(counts.items(), key=lambda kv: (kv[0] == "100+", int(kv[0].rstrip("+")))))
    total = sum(counts.values())
    shares = {k: round(v / total, 6) for k, v in counts.items()}
    return {
        "id": f"{geo.lower()}-population-by-single-year-of-age-{year}",
        "title": f"{name} population on 1 January {year} by single year of age (Eurostat demo_pjan)",
        "kind": "marginal",
        "domain": "demographics",
        "region": geo,
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-01-01"},
        "tags": ["population", "age", "eurostat"],
        "use_cases": ["person-generation", "customer-segmentation", "insurance", "pensions"],
        "spec": {"variable": "age", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total}}},
        "evidence": [
            evidence(PUBLISHER, dataflow_title("demo_pjan", "population on 1 January by age and sex"), url, f"geo={geo}, age=Y_LT1, TIME_PERIOD={year}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["age"] == "Y_LT1"), "count", f"Y_LT1,T,{geo},{year}", LICENSE, raw),
            evidence(PUBLISHER, dataflow_title("demo_pjan", "population on 1 January by age and sex"), url, f"geo={geo}, age=TOTAL, TIME_PERIOD={year}, OBS_VALUE", next(r["OBS_VALUE"] for r in rows if r["age"] == "TOTAL"), "count", f"TOTAL,T,{geo},{year}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "distribution.parameters.shares", "value": "count / sum of counts over known ages", "method": "derived", "rationale": "Eurostat publishes counts per single year of age; the TOTAL and UNK rows are dropped and shares are counts over the sum of the known ages. Y_LT1 is labelled 0 and Y_OPEN 100+."},
        ],
        "tests": [
            {"statistic": 'share["0"]', "expected": shares["0"], "tolerance": 0.002},
            {"statistic": 'share["100+"]', "expected": shares["100+"], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": f"{name} population on 1 January {year} by single year of age, both sexes, from Eurostat dataflow demo_pjan. " + LICENSE_NOTE,
    }


def battery_electric_share(record: dict) -> None:
    record["battery_electric_share"] = round(record["battery_electric"] / record["total"], 6)


CAR_COLUMNS = [
    Column("total", {"mot_nrg": "TOTAL"}, int),
    Column("petrol_excluding_hybrids", {"mot_nrg": "PET_X_HYB"}, int),
    Column("diesel_excluding_hybrids", {"mot_nrg": "DIE_X_HYB"}, int),
    Column("battery_electric", {"mot_nrg": "ELC"}, int),
    Column("hybrid_petrol", {"mot_nrg": "ELC_PET_HYB"}, int),
    Column("plug_in_hybrid_petrol", {"mot_nrg": "ELC_PET_PI"}, int),
    Column("hybrid_diesel", {"mot_nrg": "ELC_DIE_HYB"}, int),
    Column("plug_in_hybrid_diesel", {"mot_nrg": "ELC_DIE_PI"}, int),
    Column("lpg", {"mot_nrg": "LPG"}, int),
    Column("natural_gas", {"mot_nrg": "GAS"}, int),
    Column("hydrogen_fuel_cell", {"mot_nrg": "HYD_FCELL"}, int),
    Column("other", {"mot_nrg": "OTH"}, int),
]

LOOKUPS: list[tuple[LookupEntry, str, str]] = [
    (
        LookupEntry(
            "eu-statutory-monthly-minimum-wages-2026s2", "Statutory monthly minimum wages, second half of 2026, all countries reported by Eurostat", "employment",
            "earn_mw_cur", "monthly minimum wages, bi-annual data", "S.EUR+NAC+PPS.",
            [Column("eur", {"currency": "EUR"}, int), Column("national_currency", {"currency": "NAC"}, int), Column("pps", {"currency": "PPS"}, int)],
            "currency:EUR", ["minimum-wage", "wages", "labour"], ["payroll-demo", "hr-analytics", "personal-finance"],
            "Gross monthly statutory minimum wages in force on 1 July 2026 from Eurostat dataflow earn_mw_cur, in euro, in national currency and in purchasing power standards, for every country Eurostat reports a value for (EU member states plus candidate countries and the United States). "
            "Countries Eurostat lists without a value for the period are omitted. valid_from and valid_to bound the half-year the figures describe.",
            half_year_bounds("2026-S2"), ("DE", "FR"), "eur",
        ),
        "2026-S2", "2026-S2",
    ),
    (
        LookupEntry(
            "eu-employment-rate-20-64-2025", "Employment rate of people aged 20 to 64, 2025, ten member states", "employment",
            "lfsi_emp_a", "employment and activity by sex and age, annual data", f"A.EMP_LFS.T+F+M.Y20-64.PC_POP.{GEO_KEY}",
            [Column("total", {"sex": "T"}), Column("female", {"sex": "F"}), Column("male", {"sex": "M"})],
            "percent", ["employment", "labour", "sex"], ["hr-analytics", "workforce-planning", "person-generation", "market-sizing"],
            "Employment rate in 2025 (employed persons aged 20 to 64 as a percentage of the population of the same age, EU Labour Force Survey) for ten member states, total and by sex, from Eurostat dataflow lfsi_emp_a.",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-gdp-per-capita-2025", "GDP per capita in euro, in purchasing power standards and as an index of the EU average, 2025, ten member states", "economy",
            "nama_10_pc", "main GDP aggregates per capita", f"A.CP_EUR_HAB+CP_PPS_EU27_2020_HAB+PC_EU27_2020_HAB_MPPS_CP.B1GQ.{GEO_KEY}",
            [Column("eur_per_inhabitant", {"unit": "CP_EUR_HAB"}, int), Column("pps_per_inhabitant", {"unit": "CP_PPS_EU27_2020_HAB"}), Column("pps_index_eu27", {"unit": "PC_EU27_2020_HAB_MPPS_CP"})],
            "currency:EUR", ["gdp", "national-accounts", "purchasing-power"], ["market-sizing", "customer-segmentation", "financial-planning", "pricing"],
            "Gross domestic product at current market prices per inhabitant in 2025 for ten member states from Eurostat dataflow nama_10_pc: in euro, in purchasing power standards (PPS, EU27 from 2020) and as a percentage of the EU27 average per inhabitant in PPS.",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-equivalised-net-income-2025", "Median and mean equivalised net income, 2025 survey year, ten member states", "income",
            "ilc_di03", "mean and median income by age and sex, EU-SILC survey", f"A.TOTAL.T.MED_EI+MEAN_EI.EUR.{GEO_KEY}",
            [Column("median_eur", {"statinfo": "MED_EI"}, int), Column("mean_eur", {"statinfo": "MEAN_EI"}, int)],
            "currency:EUR", ["income", "eu-silc", "living-conditions"], ["personal-finance", "customer-segmentation", "credit-risk", "household-generation"],
            "Median and mean equivalised net income in euro for the whole population, EU-SILC survey year 2025, ten member states, from Eurostat dataflow ilc_di03. "
            "EU-SILC income refers to the calendar year before the survey year; valid_from and valid_to bound the survey year under which Eurostat files the figures.",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-housing-cost-overburden-rate-2025", "Housing cost overburden rate, 2025 survey year, ten member states", "income",
            "ilc_lvho07a", "housing cost overburden rate by age, sex and poverty status, EU-SILC survey", f"A.PC.TOTAL.TOTAL.T.{GEO_KEY}",
            [Column("percent_of_population", {"rskpovth": "TOTAL"})],
            "percent", ["housing", "housing-costs", "eu-silc", "living-conditions"], ["credit-risk", "mortgage-origination", "property-demo", "household-generation"],
            "Share of the population living in households where total housing costs exceed 40 percent of disposable income, EU-SILC survey year 2025, ten member states, from Eurostat dataflow ilc_lvho07a (all ages, both sexes, whole population).",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-household-gas-prices-2026s1", "Household natural gas prices including taxes, consumption band 20 to 199 GJ, 2026-S1, nine member states", "energy",
            "nrg_pc_202", "gas prices for household consumers", f"S.G3000.GJ20-199.KWH.I_TAX.EUR.{GEO_KEY}",
            [Column("eur_per_kwh", {"tax": "I_TAX"})],
            "decimal", ["gas", "energy-prices", "utilities"], ["utilities-demo", "pricing", "household-generation"],
            "Natural gas prices for household consumers, all taxes and levies included, consumption band D2 (20 to 199 GJ per year), in euro per kWh for the half-year 2026-S1, from Eurostat dataflow nrg_pc_202. "
            "Poland is omitted because Eurostat publishes its observation as confidential (CONF_STATUS C) with no value. valid_from and valid_to bound the half-year the prices describe.",
            half_year_bounds("2026-S1"), ("DE", "FR"), "eur_per_kwh",
        ),
        "2026-S1", "2026-S1",
    ),
    (
        LookupEntry(
            "eu-non-household-electricity-prices-2026s1", "Non-household electricity prices, consumption band 500 to 1 999 MWh, 2026-S1, ten member states", "energy",
            "nrg_pc_205", "electricity prices for non-household consumers", f"S.E7000.MWH500-1999.KWH.I_TAX+X_TAX.EUR.{GEO_KEY}",
            [Column("eur_per_kwh_including_taxes", {"tax": "I_TAX"}), Column("eur_per_kwh_excluding_taxes", {"tax": "X_TAX"})],
            "decimal", ["electricity", "energy-prices", "utilities", "business"], ["utilities-demo", "pricing", "company-generation"],
            "Electricity prices for non-household consumers, consumption band IC (500 to 1 999 MWh per year), in euro per kWh for the half-year 2026-S1, from Eurostat dataflow nrg_pc_205, "
            "both including all taxes and levies and excluding taxes and levies. valid_from and valid_to bound the half-year the prices describe.",
            half_year_bounds("2026-S1"),
        ),
        "2026-S1", "2026-S1",
    ),
    (
        LookupEntry(
            "eu-online-purchases-by-individuals-2025", "Individuals who bought or ordered goods or services online, 2025, ten member states", "digital",
            "isoc_ec_ib20", "internet purchases by individuals", f"A.IND_TOTAL.I_BUY3+I_BLT12.PC_IND.{GEO_KEY}",
            [Column("last_3_months_percent", {"indic_is": "I_BUY3"}), Column("last_12_months_percent", {"indic_is": "I_BLT12"})],
            "percent", ["e-commerce", "internet", "digital"], ["digital-channels", "retail-demo", "customer-segmentation", "sales-generation"],
            "Percentage of all individuals who bought or ordered goods or services over the internet for private use in the last three months and in the last twelve months, 2025, ten member states, from Eurostat dataflow isoc_ec_ib20 (ICT usage in households and by individuals survey).",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-internet-use-by-individuals-2025", "Internet use by individuals, 2025, ten member states", "digital",
            "isoc_ci_ifp_iu", "individuals, internet use", f"A.I_IU3+I_IUEVR+I_IUX.PC_IND.IND_TOTAL.{GEO_KEY}",
            [Column("last_3_months_percent", {"indic_is": "I_IU3"}), Column("ever_used_percent", {"indic_is": "I_IUEVR"}), Column("never_used_percent", {"indic_is": "I_IUX"})],
            "percent", ["internet", "digital", "connectivity"], ["digital-channels", "telecom-demo", "customer-segmentation", "market-sizing"],
            "Percentage of all individuals who used the internet in the last three months, who have ever used it, and who have never used it, 2025, ten member states, from Eurostat dataflow isoc_ci_ifp_iu (ICT usage in households and by individuals survey).",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-new-passenger-car-registrations-by-motor-energy-2025", "New passenger car registrations by motor energy, 2025, ten member states", "automotive",
            "road_eqr_carpda", "new registrations of passenger cars by type of motor energy", f"A.NR.TOTAL+PET_X_HYB+DIE_X_HYB+ELC+ELC_PET_HYB+ELC_PET_PI+ELC_DIE_HYB+ELC_DIE_PI+LPG+GAS+HYD_FCELL+OTH.{GEO_KEY}",
            CAR_COLUMNS, "count", ["vehicles", "cars", "registrations", "electric-vehicles"], ["automotive-demo", "fleet-demo", "insurance", "market-sizing"],
            "New registrations of passenger cars in 2025 for ten member states from Eurostat dataflow road_eqr_carpda, in number of vehicles: the total and the Eurostat motor energy categories petrol excluding hybrids, diesel excluding hybrids, "
            "electricity (battery electric), hybrid electric-petrol, plug-in hybrid petrol-electric, hybrid diesel-electric, plug-in hybrid diesel-electric, LPG, natural gas, hydrogen and fuel cells, and other. "
            "The categories kept do not necessarily sum to the total because Eurostat also publishes aggregates and categories not carried here.",
            ("2025-01-01", "2025-12-31"), ("DE", "FR"), None,
            [{"parameter": "rows[*].battery_electric_share", "value": "battery_electric / total", "method": "derived", "rationale": "Eurostat publishes the counts; the share of battery electric cars in all new registrations is their ratio."}],
            battery_electric_share,
        ),
        "2025", "2025",
    ),
    (
        LookupEntry(
            "eu-life-expectancy-at-birth-2024", "Life expectancy at birth by sex, 2024, ten member states", "demographics",
            "demo_mlexpec", "life expectancy by age and sex", f"A.YR.T+F+M.Y_LT1.{GEO_KEY}",
            [Column("total_years", {"sex": "T"}), Column("female_years", {"sex": "F"}), Column("male_years", {"sex": "M"})],
            "decimal", ["life-expectancy", "mortality", "sex"], ["insurance", "pensions", "health-demo", "person-generation"],
            "Life expectancy at birth in years for 2024, total and by sex, for ten member states from Eurostat dataflow demo_mlexpec (age less than 1 year).",
            ("2024-01-01", "2024-12-31"),
        ),
        "2024", "2024",
    ),
    (
        LookupEntry(
            "eu-fertility-indicators-2024", "Total fertility rate and mean and median age of women at childbirth, 2024, ten member states", "demographics",
            "demo_find", "fertility indicators", f"A.TOTFERRT+AGEMOTH+AGEMOTH1+MEDAGEMOTH.{GEO_KEY}",
            [Column("total_fertility_rate", {"indic_de": "TOTFERRT"}), Column("mean_age_at_childbirth", {"indic_de": "AGEMOTH"}), Column("mean_age_at_first_birth", {"indic_de": "AGEMOTH1"}), Column("median_age_at_childbirth", {"indic_de": "MEDAGEMOTH"})],
            "decimal", ["fertility", "births", "age"], ["person-generation", "household-generation", "health-demo", "insurance"],
            "Total fertility rate (live births per woman), mean age of women at childbirth, mean age of women at birth of first child and median age of women at childbirth for 2024, ten member states, from Eurostat dataflow demo_find.",
            ("2024-01-01", "2024-12-31"),
        ),
        "2024", "2024",
    ),
    (
        LookupEntry(
            "eu-crude-marriage-and-divorce-rates-2023", "Crude marriage and divorce rates, 2023, member states reported by Eurostat", "demographics",
            "demo_nind", "marriage indicators", f"A.GNUPRT.{GEO_KEY}",
            [Column("marriages_per_1000", {"indic_de": "GNUPRT"})],
            "decimal", ["marriage", "divorce", "households"], ["person-generation", "household-generation", "insurance", "crm-demo"],
            "Crude marriage rate (marriages per 1 000 persons) for 2023 from Eurostat dataflow demo_nind, with the crude divorce rate (divorces per 1 000 persons) for the same year from dataflow demo_ndivind carried as a second column where Eurostat reports it. "
            "Countries without a published 2023 marriage rate are omitted and a missing divorce rate is stored as null.",
            ("2023-01-01", "2023-12-31"), ("DE", "FR"), "marriages_per_1000",
            joins=(JoinSpec("demo_ndivind", "divorce indicators", f"A.GDIVRT.{GEO_KEY}", Column("divorces_per_1000", {"indic_de": "GDIVRT"}), "decimal", "ES"),),
        ),
        "2023", "2023",
    ),
    (
        LookupEntry(
            "eu-average-household-size-2025", "Average number of persons per private household, 2025 survey year, ten member states", "demographics",
            "ilc_lvph01", "average household size, EU-SILC survey", f"A.AVG.{GEO_KEY}",
            [Column("persons_per_household", {"unit": "AVG"})],
            "decimal", ["households", "household-size", "eu-silc"], ["household-generation", "person-generation", "market-sizing", "utilities-demo"],
            "Average number of persons per private household, EU-SILC survey year 2025, ten member states, from Eurostat dataflow ilc_lvph01.",
            ("2025-01-01", "2025-12-31"),
        ),
        "2025", "2025",
    ),
]


def main() -> int:
    names = codelist("GEO")
    flags = codelist("OBS_FLAG")

    for spec, start, end in LOOKUPS:
        url = data_url(spec.dataflow, spec.key, start, end)
        write(spec.build(url, fetch(url), names, flags, tuple(join.fetch(start, end) for join in spec.joins)))

    url = data_url("une_rt_m", f"M.SA.Y_LT25.PC_ACT.T.{GEO_KEY}", "2025-01", "2025-12")
    write(monthly_by_geo("eu-youth-unemployment-rate-monthly-2025", "Youth unemployment rate (under 25), seasonally adjusted, monthly 2025, ten member states", "employment", "une_rt_m", "unemployment by sex and age, monthly data", url, fetch(url), "youth_unemployment_rate_percent", "percent", ["unemployment", "youth", "labour"], ["hr-analytics", "workforce-planning", "credit-risk", "market-sizing"], "Monthly seasonally adjusted unemployment rate of people under 25 (percent of the active population of that age, both sexes) for 2025 from Eurostat dataflow une_rt_m.", flags))

    url = data_url("tour_occ_nim", f"M.TOTAL.NR.I551-I553.{GEO_KEY}", "2025-01", "2025-12")
    write(monthly_by_geo("eu-tourism-nights-spent-monthly-2025", "Nights spent at tourist accommodation establishments, monthly 2025, ten member states", "tourism", "tour_occ_nim", "nights spent at tourist accommodation establishments, monthly data", url, fetch(url), "nights_spent", "count", ["tourism", "accommodation", "seasonality"], ["demand-forecasting", "capacity-planning", "retail-demo", "sales-generation"], "Monthly nights spent by residents and non-residents at hotels, holiday and other short-stay accommodation, camping grounds, recreational vehicle parks and trailer parks (NACE Rev. 2 I55.1 to I55.3) for 2025 from Eurostat dataflow tour_occ_nim. The series carries the seasonal profile of tourism demand.", flags))

    url = data_url("lfst_hhnhtych", f"A.TOTAL.TOTAL.A1_CH+A1_NCH+CPL_CH+CPL_NCH+OTH_CH+OTH_NCH.THS_HH.{GEO_KEY}", "2025", "2025")
    write(household_composition(url, fetch(url), names))

    for code in ("IT", "ES", "NL", "PL", "SE", "BE", "AT", "IE"):
        url = data_url("demo_pjan", f"A.NR..T.{code}", "2024", "2024")
        write(age_marginal(code, names[code], url, fetch(url)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

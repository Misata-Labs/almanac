"""Regenerate the Eurostat business value-pool entries: enterprise accounts by NACE activity for ten
member states, hourly labour cost by activity, enterprise births, deaths and survival, household
consumption structure, hospital activity, comparative price levels, hourly earnings by sex and
occupation group, the gender pay gap, house prices, housing cost burden, enterprise e-commerce, road
freight and monthly air passengers. Run from the repository root:

    uv run python tools/build_eurostat_business.py

Every URL is fetched twice and kept only when both responses hash alike, so an entry can never cite
bytes that drift between requests.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write
from build_eurostat_extended import (
    GEO_KEY,
    GEOS,
    LICENSE,
    LICENSE_NOTE,
    PUBLISHER,
    Column,
    codelist,
    data_url,
    dataflow_title,
    monthly_by_geo,
    rows_of,
)

Record = dict[str, object]
Row = dict[str, str]


def fetch_stable(url: str) -> bytes:
    """Fetch a URL twice and return its bytes only when both responses hash alike."""
    first, second = fetch(url), fetch(url)
    if sha(first) != sha(second):
        raise RuntimeError(f"unstable bytes at {url}")
    return first


def count(value: str) -> int:
    """Read a published count, which Eurostat may serialise with a decimal part such as 1369571.00."""
    return int(float(value))


def ratio(numerator: object, denominator: object, scale: float = 1, digits: int = 6) -> float | None:
    """Divide two published figures, or return None when either is missing or the denominator is zero."""
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) * scale / float(denominator), digits)


def slug(code: str) -> str:
    """Turn an Eurostat code such as B-S_X_O into a column-name fragment such as b_s_x_o."""
    return code.lower().replace("-", "_")


def published_counts(table: dict[str, Record], columns: Iterable[str]) -> dict[str, int]:
    """Count, per row, how many of the named columns carry a published value."""
    names = list(columns)
    return {key: sum(record.get(name) is not None for name in names) for key, record in table.items()}


def flag_summary(cells: Iterable[tuple[str, str, str]], flags: dict[str, str], published: dict[str, int]) -> str:
    """Summarise flagged cells by flag code and row, collapsing rows where every published column carries the flag."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for key, column, code in cells:
        grouped.setdefault(code, {}).setdefault(key, []).append(column)
    if not grouped:
        return ""
    parts = []
    for code, keys in sorted(grouped.items()):
        where = "; ".join(f"{key} ({'all published columns' if len(cols) >= published[key] else ', '.join(cols)})" for key, cols in sorted(keys.items()))
        parts.append(f"{flags.get(code, code)} ({code}): {where}")
    return " Observation flags published with the data: " + ". ".join(parts) + "."


@dataclass(frozen=True)
class Source:
    """One SDMX-CSV query contributing named columns to a table keyed by geo code."""

    dataflow: str
    description: str
    key: str
    columns: tuple[Column, ...]
    unit: str
    start: str
    end: str | None = None

    @property
    def url(self) -> str:
        return data_url(self.dataflow, self.key, self.start, self.end or self.start)

    def fetch(self) -> Fetched:
        return Fetched(self, fetch_stable(self.url))


@dataclass(frozen=True)
class Fetched:
    """A source with its bytes, able to fill table rows, cite cells and list flagged observations."""

    source: Source
    raw: bytes

    @cached_property
    def rows(self) -> list[Row]:
        return rows_of(self.raw)

    @property
    def period(self) -> str:
        return self.rows[0]["TIME_PERIOD"]

    def column_of(self, row: Row) -> Column | None:
        return next((c for c in self.source.columns if c.selects(row)), None)

    def apply(self, table: dict[str, Record]) -> None:
        for row in self.rows:
            column = self.column_of(row)
            if column is not None and row["geo"] in table:
                table[row["geo"]][column.name] = column.cast(row["OBS_VALUE"]) if row["OBS_VALUE"] else None

    def cell(self, geo: str, column: Column) -> Row:
        return next(r for r in self.rows if r["geo"] == geo and column.selects(r) and r["OBS_VALUE"])

    def evidence(self, geo: str, column: Column) -> dict:
        cell = self.cell(geo, column)
        dims = ", ".join(f"{d}={c}" for d, c in column.match.items())
        return evidence(PUBLISHER, dataflow_title(self.source.dataflow, self.source.description), self.source.url, f"geo={geo}, {dims}, TIME_PERIOD={cell['TIME_PERIOD']}, OBS_VALUE", cell["OBS_VALUE"], self.source.unit, f"{geo},{cell['TIME_PERIOD']},{cell['OBS_VALUE']}", LICENSE, self.raw)

    def flagged(self, keys: Iterable[str]) -> list[tuple[str, str, str]]:
        """List (geo, column, flag) for every kept observation Eurostat qualifies with a flag."""
        wanted = set(keys)
        cells = []
        for row in self.rows:
            column = self.column_of(row)
            if column is not None and row["geo"] in wanted and row["OBS_FLAG"] and row["OBS_VALUE"]:
                cells.append((row["geo"], column.name, row["OBS_FLAG"]))
        return cells


@dataclass(frozen=True)
class GeoLookup:
    """A cross-country reference table assembled from one or more sources, one row per member state."""

    entry_id: str
    title: str
    domain: str
    sources: tuple[Source, ...]
    tags: list[str]
    use_cases: list[str]
    note: str
    valid: tuple[str, str]
    evidence_geos: tuple[str, str] = ("DE", "FR")
    assumed: list[dict] = field(default_factory=list)
    derive: Callable[[Record], None] | None = None

    def build(self, fetched: tuple[Fetched, ...], names: dict[str, str], flags: dict[str, str]) -> dict:
        columns = [c.name for part in fetched for c in part.source.columns]
        table: dict[str, Record] = {geo: {"name": names[geo], **dict.fromkeys(columns)} for geo in sorted(GEOS)}
        flagged: list[tuple[str, str, str]] = []
        for part in fetched:
            part.apply(table)
            flagged += part.flagged(table)
        if self.derive is not None:
            for record in table.values():
                self.derive(record)
        lead = fetched[0].source.columns[0]
        items = [fetched[0].evidence(geo, lead) for geo in self.evidence_geos]
        items += [part.evidence(self.evidence_geos[0], part.source.columns[0]) for part in fetched[1:]]
        vectors = [{"input": {"key": geo, "column": lead.name}, "expected": table[geo][lead.name], "origin": "source"} for geo in self.evidence_geos]
        vectors.append({"input": "XX", "expected": False, "origin": "derived"})
        present = [float(r[lead.name]) for r in table.values() if r[lead.name] is not None]
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
                "parameters": {
                    "dataflow": fetched[0].source.dataflow,
                    "key": fetched[0].source.key,
                    "period": fetched[0].period,
                    "sources": [{"dataflow": p.source.dataflow, "key": p.source.key, "columns": [c.name for c in p.source.columns]} for p in fetched],
                    "rows": table,
                },
                "vectors": vectors,
            },
            "evidence": items,
            "assumed": self.assumed,
            "tests": [
                {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
                {"statistic": "count", "expected": len(table), "tolerance": 0},
                {"statistic": f"max[{lead.name}]", "expected": max(present), "tolerance": 0},
            ],
            "notes": self.note + " Rows are keyed by the Eurostat geo code and carry the English country name from the GEO codelist; a cell Eurostat does not publish is stored as null." + flag_summary(flagged, flags, published_counts(table, columns)) + " " + LICENSE_NOTE,
        }


# Structural business statistics: NACE Rev. 2 sections and divisions covered by sbs_ovw_act.
SBS_DIVISIONS: dict[str, Iterable[int]] = {
    "B": range(5, 10), "C": range(10, 34), "D": (35,), "E": range(36, 40), "F": range(41, 44), "G": range(45, 48),
    "H": range(49, 54), "I": (55, 56), "J": range(58, 64), "K": range(64, 67), "L": (68,), "M": range(69, 76),
    "N": range(77, 83), "P": (85,), "Q": range(86, 89), "R": range(90, 94), "S": (95, 96),
}
SBS_AGGREGATE = "B-S_X_O_S94"
SBS_SECTIONS = [s for s in SBS_DIVISIONS if s != "S"]
SBS_NACE_KEY = "+".join([SBS_AGGREGATE, *SBS_SECTIONS, *(f"{s}{d:02d}" for s, ds in SBS_DIVISIONS.items() for d in ds)])
SBS_INDICATORS: dict[str, tuple[str, Callable[[str], float | int]]] = {
    "ENT_NR": ("enterprises", count),
    "EMP_NR": ("persons_employed", count),
    "NETTUR_MEUR": ("net_turnover_meur", float),
    "AV_MEUR": ("value_added_meur", float),
    "GOS_MEUR": ("gross_operating_surplus_meur", float),
    "EXPN_SAL_BEN_MEUR": ("employee_benefits_expense_meur", float),
    "GOR_PC": ("gross_operating_rate_percent", float),
}
SBS_DESCRIPTION = "enterprises by detailed NACE Rev. 2 activity and special aggregates"
SBS_ASSUMED = [
    {"parameter": "rows[*].gross_operating_surplus_to_turnover", "value": "gross_operating_surplus_meur / net_turnover_meur", "method": "derived", "rationale": "An operating-margin proxy: the ratio of the published gross operating surplus to the published net turnover. Eurostat's own gross_operating_rate_percent is the same ratio in percent and is kept beside it."},
    {"parameter": "rows[*].employee_benefits_share_of_turnover", "value": "employee_benefits_expense_meur / net_turnover_meur", "method": "derived", "rationale": "Personnel costs as a share of turnover, from the two published aggregates."},
    {"parameter": "rows[*].value_added_per_person_employed_teur", "value": "value_added_meur * 1000 / persons_employed", "method": "derived", "rationale": "Apparent labour productivity in thousand euro per person employed, from the published value added and headcount."},
    {"parameter": "rows[*].net_turnover_per_enterprise_teur", "value": "net_turnover_meur * 1000 / enterprises", "method": "derived", "rationale": "Average enterprise size in thousand euro of turnover, from the published turnover and enterprise count."},
]


def nace_level(code: str) -> str:
    return "aggregate" if code == SBS_AGGREGATE else "section" if len(code) == 1 else "division"


def enterprise_accounts(geo: str, name: str, url: str, raw: bytes, nace: dict[str, str], flags: dict[str, str]) -> dict:
    """Build one member state's enterprise accounts keyed by NACE code, with the derived operating ratios."""
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    columns = [name for name, _ in SBS_INDICATORS.values()]
    table: dict[str, Record] = {}
    for r in rows:
        column, cast = SBS_INDICATORS[r["indic_sbs"]]
        record = table.setdefault(r["nace_r2"], {"label": nace[r["nace_r2"]], "level": nace_level(r["nace_r2"]), **dict.fromkeys(columns)})
        record[column] = cast(r["OBS_VALUE"]) if r["OBS_VALUE"] else None
    for record in table.values():
        record["gross_operating_surplus_to_turnover"] = ratio(record["gross_operating_surplus_meur"], record["net_turnover_meur"])
        record["employee_benefits_share_of_turnover"] = ratio(record["employee_benefits_expense_meur"], record["net_turnover_meur"])
        record["value_added_per_person_employed_teur"] = ratio(record["value_added_meur"], record["persons_employed"], 1000, 3)
        record["net_turnover_per_enterprise_teur"] = ratio(record["net_turnover_meur"], record["enterprises"], 1000, 3)
    table = dict(sorted(table.items(), key=lambda kv: (kv[0] != SBS_AGGREGATE, kv[0])))

    def cell(code: str, indicator: str) -> Row:
        return next(r for r in rows if r["nace_r2"] == code and r["indic_sbs"] == indicator)

    total, manufacturing = cell(SBS_AGGREGATE, "NETTUR_MEUR"), cell("C", "GOR_PC")
    confidential = sorted({r["nace_r2"] for r in rows if not r["OBS_VALUE"]})
    flagged = [(r["nace_r2"], SBS_INDICATORS[r["indic_sbs"]][0], r["OBS_FLAG"]) for r in rows if r["OBS_FLAG"] and r["OBS_VALUE"]]
    rates = [r["gross_operating_rate_percent"] for r in table.values() if r["gross_operating_rate_percent"] is not None]
    return {
        "id": f"{geo.lower()}-enterprise-accounts-by-nace-{year}",
        "title": f"{name} enterprise accounts by NACE Rev. 2 section and division with derived operating ratios, {year} (Eurostat sbs_ovw_act)",
        "kind": "rule",
        "domain": "business",
        "region": geo,
        "status": "verified",
        "tier": "A",
        "valid_from": f"{year}-01-01",
        "valid_to": f"{year}-12-31",
        "tags": ["structural-business-statistics", "nace", "turnover", "value-added", "operating-margin", "enterprises", "eurostat", "reference-table"],
        "use_cases": ["company-generation", "financial-reporting", "market-sizing", "kyb-onboarding", "sales-generation", "credit-risk"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"dataflow": "sbs_ovw_act", "key": f"A.{SBS_NACE_KEY}.{'+'.join(SBS_INDICATORS)}.{geo}", "period": year, "rows": table},
            "vectors": [
                {"input": {"key": SBS_AGGREGATE, "column": "net_turnover_meur"}, "expected": table[SBS_AGGREGATE]["net_turnover_meur"], "origin": "source"},
                {"input": {"key": "C", "column": "gross_operating_rate_percent"}, "expected": table["C"]["gross_operating_rate_percent"], "origin": "source"},
                {"input": {"key": "C", "column": "net_turnover_per_enterprise_teur"}, "expected": table["C"]["net_turnover_per_enterprise_teur"], "origin": "derived", "note": "net_turnover_meur * 1000 / enterprises for manufacturing"},
                {"input": "A", "expected": False, "origin": "derived", "note": "agriculture is outside structural business statistics"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, dataflow_title("sbs_ovw_act", SBS_DESCRIPTION), url, f"nace_r2={SBS_AGGREGATE}, indic_sbs=NETTUR_MEUR, geo={geo}, TIME_PERIOD={year}, OBS_VALUE", total["OBS_VALUE"], "currency:EUR", f"{SBS_AGGREGATE},NETTUR_MEUR,{geo},{year},{total['OBS_VALUE']}", LICENSE, raw),
            evidence(PUBLISHER, dataflow_title("sbs_ovw_act", SBS_DESCRIPTION), url, f"nace_r2=C, indic_sbs=GOR_PC, geo={geo}, TIME_PERIOD={year}, OBS_VALUE", manufacturing["OBS_VALUE"], "percent", f"C,GOR_PC,{geo},{year},{manufacturing['OBS_VALUE']}", LICENSE, raw),
        ],
        "assumed": SBS_ASSUMED,
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(table), "tolerance": 0},
            {"statistic": "value[C,gross_operating_rate_percent]", "expected": table["C"]["gross_operating_rate_percent"], "tolerance": 0},
            {"statistic": "max[gross_operating_rate_percent]", "expected": max(rates), "tolerance": 0},
        ],
        "notes": (
            f"Structural business statistics for {name} in {year} from Eurostat dataflow sbs_ovw_act, one row per NACE Rev. 2 section (B to R, excluding O) and division (B05 to S96) "
            f"plus the business economy aggregate {SBS_AGGREGATE} (industry, construction and market services except public administration, defence, compulsory social security and membership organisations). "
            "Published columns: number of enterprises, persons employed, net turnover, value added, gross operating surplus and employee benefits expense (Eurostat's personnel-costs concept) in million euro, and the gross operating rate in percent. "
            "Derived columns give the operating-surplus and personnel-cost shares of turnover, value added per person employed and turnover per enterprise; every derived column is null where an input is missing. "
            "Each row carries the English NACE label and its level (aggregate, section or division)."
            + (f" Cells Eurostat withholds as confidential (no value) occur in: {', '.join(confidential)}." if confidential else "")
            + flag_summary(flagged, flags, published_counts(table, columns)) + " " + LICENSE_NOTE
        ),
    }


def consumption_structure(url: str, raw: bytes, names: dict[str, str], coicop: dict[str, str], flags: dict[str, str]) -> dict:
    """Household consumption shares by COICOP division, one categorical distribution per country."""
    rows = rows_of(raw)
    year = rows[0]["TIME_PERIOD"]
    per_mille: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["OBS_VALUE"]:
            per_mille.setdefault(r["geo"], {})[r["coicop"]] = float(r["OBS_VALUE"])
    distributions = {}
    for geo in sorted(per_mille):
        published = dict(sorted(per_mille[geo].items()))
        total = sum(published.values())
        distributions[geo] = {
            "family": "categorical",
            "parameters": {
                "shares": {code: round(value / total, 6) for code, value in published.items()},
                "per_mille": published,
                "labels": {code: coicop[code] for code in published},
                "name": names[geo],
            },
        }
    de = next(r for r in rows if r["geo"] == "DE" and r["coicop"] == "CP04")
    fr = next(r for r in rows if r["geo"] == "FR" and r["coicop"] == "CP01")
    flagged = sorted({(r["geo"], r["OBS_FLAG"]) for r in rows if r["OBS_FLAG"] and r["OBS_VALUE"]})
    title = dataflow_title("hbs_str_t211", "structure of consumption expenditure by COICOP consumption purpose")
    return {
        "id": f"eu-household-consumption-structure-by-coicop-{year}",
        "title": f"Household consumption expenditure by COICOP division, given country, {year} wave, nine member states (Eurostat hbs_str_t211)",
        "kind": "conditional",
        "domain": "income",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "tags": ["household-budget-survey", "consumption", "coicop", "spending", "eurostat", "by-country"],
        "use_cases": ["household-generation", "personal-finance", "retail-demo", "customer-segmentation", "market-sizing"],
        "spec": {"variable": "coicop_division", "unit": "ratio", "given": "country", "distributions": distributions},
        "evidence": [
            evidence(PUBLISHER, title, url, f"geo=DE, coicop=CP04, TIME_PERIOD={year}, OBS_VALUE", de["OBS_VALUE"], "decimal", f"CP04,PM,DE,{year},{de['OBS_VALUE']}", LICENSE, raw),
            evidence(PUBLISHER, title, url, f"geo=FR, coicop=CP01, TIME_PERIOD={year}, OBS_VALUE", fr["OBS_VALUE"], "decimal", f"CP01,PM,FR,{year},{fr['OBS_VALUE']}", LICENSE, raw),
        ],
        "assumed": [
            {"parameter": "distributions[*].parameters.shares", "value": "per mille of a division / sum of the twelve divisions' per mille", "method": "derived", "rationale": "Eurostat publishes the structure in per mille of total consumption expenditure, rounded so the twelve divisions sum to between 999 and 1002; shares are renormalised over the published divisions so each distribution sums to one. The published per mille values are kept beside them."},
        ],
        "tests": [
            {"statistic": "share[DE,CP04]", "expected": distributions["DE"]["parameters"]["shares"]["CP04"], "tolerance": 0.005},
            {"statistic": "share[FR,CP01]", "expected": distributions["FR"]["parameters"]["shares"]["CP01"], "tolerance": 0.005},
            {"statistic": "sum_of_shares[DE]", "expected": 1, "tolerance": 1e-4},
            {"statistic": "sum_of_shares[PL]", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            f"Structure of household consumption expenditure in the {year} wave of the Household Budget Survey from Eurostat dataflow hbs_str_t211, as a categorical distribution over the twelve COICOP divisions CP01 to CP12 for each country. "
            "Each distribution carries the published per mille values, the derived shares, the English COICOP labels and the country name. "
            "Sweden is absent because Eurostat publishes no 2020 wave for it, so nine of the ten usual member states are covered. "
            + ("Observation flags published with the data: " + "; ".join(f"{geo} {flags.get(code, code)} ({code}, all divisions)" for geo, code in flagged) + ". " if flagged else "")
            + LICENSE_NOTE
        ),
    }


def labour_cost_columns() -> tuple[Column, ...]:
    activities = ["B-S_X_O", "B-E", "B-N", "G-N", "P-S", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S"]
    totals = tuple(Column(f"eur_per_hour_{slug(code)}", {"lcstruct": "D1_D4_MD5", "nace_r2": code}) for code in activities)
    structure = (
        Column("wages_eur_per_hour_b_s_x_o", {"lcstruct": "D11", "nace_r2": "B-S_X_O"}),
        Column("non_wage_eur_per_hour_b_s_x_o", {"lcstruct": "D12_D4_MD5", "nace_r2": "B-S_X_O"}),
        Column("non_wage_share_percent_b_s_x_o", {"lcstruct": "D2-D4_MD5_RAT", "nace_r2": "B-S_X_O"}),
    )
    return totals + structure


def derive_wage_share(record: Record) -> None:
    record["wage_share_b_s_x_o"] = ratio(record["wages_eur_per_hour_b_s_x_o"], record["eur_per_hour_b_s_x_o"])


def derive_zero_employee_share(record: Record) -> None:
    record["zero_employee_share_of_active_enterprises"] = ratio(record["active_enterprises_0_employees"], record["active_enterprises"])


def derive_discharge_rates(record: Record) -> None:
    record["discharges_per_100000_inhabitants"] = ratio(record["discharges"], record["average_population"], 100_000, 1)
    record["somatic_discharges_per_100000_inhabitants"] = ratio(record["somatic_discharges"], record["average_population"], 100_000, 1)


def derive_freight_ratios(record: Record) -> None:
    record["empty_running_share_of_vehicle_km"] = ratio(record["vehicle_km_million_empty"], record["vehicle_km_million_total"])
    record["international_share_of_tonne_km"] = ratio(record["tonne_km_million_international"], record["tonne_km_million_total"])
    record["average_load_tonnes_per_loaded_vehicle_km"] = ratio(record["tonne_km_million_total"], record["vehicle_km_million_loaded"], 1, 3)


SIZE_CLASSES = {"0": "0_employees", "1-4": "1_4_employees", "5-9": "5_9_employees", "GE10": "10_plus_employees"}
OCCUPATION_GROUPS = {"TOTAL": "all_occupations", "OC1-5": "non_manual", "OC6-8": "skilled_manual", "OC7-9": "manual"}
SEXES = {"T": "total", "F": "female", "M": "male"}
PRICE_LEVEL_CATEGORIES = {
    "E011": "household_final_consumption", "A0101": "food_and_non_alcoholic_beverages", "A0102": "alcohol_tobacco_and_narcotics",
    "A0103": "clothing_and_footwear", "A0104": "housing_water_electricity_gas_and_fuels", "A0105": "household_furnishings_and_equipment",
    "A0106": "health", "A0107": "transport", "A0108": "communication", "A0109": "recreation_and_culture", "A0110": "education",
    "A0111": "restaurants_and_hotels", "A0112": "miscellaneous_goods_and_services", "GDP": "gross_domestic_product",
}
PAY_GAP_ACTIVITIES = ["B-S_X_O", "B-S", "B-N", "C", "F", "G", "H", "I", "J", "K", "L", "M", "N", "P", "Q", "R", "S"]
HOSPITAL_CARE = {"TOTAL": "", "SOM": "somatic_", "PSY": "psychiatric_"}
HOSPITAL_INDICATORS = {"ALOS": "average_length_of_stay_days", "DISCH": "discharges", "DAY_HOSP": "bed_days"}

LOOKUPS: list[GeoLookup] = [
    GeoLookup(
        "eu-hourly-labour-cost-by-nace-section-2024", "Hourly labour cost by NACE Rev. 2 section and its wage and non-wage split, 2024, ten member states", "employment",
        (Source("lc_lci_lev", "labour cost levels by NACE Rev. 2 activity", f"A.EUR.D1_D4_MD5+D11+D12_D4_MD5+D2-D4_MD5_RAT..{GEO_KEY}", labour_cost_columns(), "currency:EUR", "2024"),),
        ["labour-cost", "wages", "nace", "labour"], ["payroll-demo", "hr-analytics", "workforce-planning", "pricing", "company-generation"],
        "Hourly labour cost in euro for 2024 from Eurostat dataflow lc_lci_lev (labour cost for the labour cost index: compensation of employees plus taxes minus subsidies), "
        "for the whole economy except public administration (B-S_X_O), the aggregates industry except construction (B-E), business economy (B-N), services of the business economy (G-N) and non-market services (P-S), and each NACE section B to S. "
        "For B-S_X_O the table also carries the wages-and-salaries and the non-wage components in euro per hour and Eurostat's published share of non-wage costs in percent; the derived wage share is their complement expressed as a ratio. "
        "Belgium reports 2024 as its latest year, which is why the table is built on 2024 rather than the provisional 2025 figures.",
        ("2024-01-01", "2024-12-31"),
        assumed=[{"parameter": "rows[*].wage_share_b_s_x_o", "value": "wages_eur_per_hour_b_s_x_o / eur_per_hour_b_s_x_o", "method": "derived", "rationale": "The wage share of hourly labour cost is the published wages-and-salaries component over the published total for B-S_X_O."}],
        derive=derive_wage_share,
    ),
    GeoLookup(
        "eu-enterprise-births-deaths-and-survival-2024", "Enterprise birth, death, churn and survival rates, total and by employee size class, 2024, ten member states", "business",
        (
            Source("bd_size", "business demography by size class and NACE Rev. 2 activity", f"A.TOTAL.TOTAL.ENT_NR+ENT_BRTH_NR+ENT_DTH_NR+ENT_BRTHR_PC+ENT_DTHR_PC+ENT_BRTHR_DTHR_PC.{SBS_AGGREGATE}.{GEO_KEY}", (
                Column("birth_rate_percent", {"indic_sbs": "ENT_BRTHR_PC"}), Column("death_rate_percent", {"indic_sbs": "ENT_DTHR_PC"}), Column("churn_rate_percent", {"indic_sbs": "ENT_BRTHR_DTHR_PC"}),
                Column("active_enterprises", {"indic_sbs": "ENT_NR"}, count), Column("enterprise_births", {"indic_sbs": "ENT_BRTH_NR"}, count), Column("enterprise_deaths", {"indic_sbs": "ENT_DTH_NR"}, count),
            ), "percent", "2024"),
            Source("bd_size", "business demography by size class and NACE Rev. 2 activity", f"A.Y1+Y2+Y3.TOTAL.ENT_SRVLR_BRTH_PC.{SBS_AGGREGATE}.{GEO_KEY}", tuple(Column(f"survival_rate_{n}_year_percent", {"age": f"Y{n}"}) for n in (1, 2, 3)), "percent", "2024"),
            Source("bd_size", "business demography by size class and NACE Rev. 2 activity", f"A.TOTAL.0+1-4+5-9+GE10.ENT_BRTHR_PC+ENT_DTHR_PC+ENT_NR.{SBS_AGGREGATE}.{GEO_KEY}", tuple(
                Column(f"{name}_{suffix}", {"sizeclas": code, "indic_sbs": indic}, count if indic == "ENT_NR" else float)
                for code, suffix in SIZE_CLASSES.items() for indic, name in (("ENT_BRTHR_PC", "birth_rate_percent"), ("ENT_DTHR_PC", "death_rate_percent"), ("ENT_NR", "active_enterprises"))
            ), "percent", "2024"),
        ),
        ["business-demography", "enterprise-births", "enterprise-deaths", "survival-rate", "churn", "size-class"], ["company-generation", "kyb-onboarding", "credit-risk", "market-sizing", "crm-demo"],
        f"Business demography for 2024 from Eurostat dataflow bd_size for the business economy aggregate {SBS_AGGREGATE}: the population of active enterprises, enterprise births and deaths, "
        "the birth rate, death rate and churn rate (births plus deaths over active enterprises, in percent), the survival rates of enterprises born one, two and three years earlier (survivors over the births of the birth year, in percent; "
        "Eurostat publishes no four- or five-year survival in this flow), and the birth rate, death rate and active population for the four employee size classes zero, 1 to 4, 5 to 9 and 10 or more. "
        "Size-class birth and death rates relate the births or deaths in a class to the active enterprises of the same class, so the class counts, not the rates, add up to the totals.",
        ("2024-01-01", "2024-12-31"),
        assumed=[{"parameter": "rows[*].zero_employee_share_of_active_enterprises", "value": "active_enterprises_0_employees / active_enterprises", "method": "derived", "rationale": "The share of the active enterprise population with no employees, from the two published counts."}],
        derive=derive_zero_employee_share,
    ),
    GeoLookup(
        "eu-hospital-discharges-and-length-of-stay-2023", "Hospital in-patient discharges, bed-days and average length of stay, total, somatic and psychiatric care, 2023, ten member states", "healthcare",
        (
            Source("hlth_co_inpagg", "hospital discharges and length of stay for inpatient curative care", f"A.TOTAL+SOM+PSY.ALOS+DISCH+DAY_HOSP.NR.{GEO_KEY}", tuple(
                Column(f"{prefix}{name}", {"hlthcare": care, "indic_he": indic}, float if indic == "ALOS" else count)
                for indic, name in HOSPITAL_INDICATORS.items() for care, prefix in HOSPITAL_CARE.items()
            ), "decimal", "2023"),
            Source("demo_gind", "population change, demographic balance and crude rates at national level", f"A.AVG.{GEO_KEY}", (Column("average_population", {"indic_de": "AVG"}, count),), "count", "2023"),
        ),
        ["hospital", "length-of-stay", "discharges", "health"], ["health-demo", "claims-generation", "clinical-records", "capacity-planning", "insurance"],
        "Hospital in-patient activity for 2023 from Eurostat dataflow hlth_co_inpagg: average length of stay in days, number of discharges and bed-days for all in-patient curative care and separately for somatic and psychiatric care, "
        "with the 2023 average population from dataflow demo_gind and the derived discharges per 100 000 inhabitants. "
        "The Netherlands reports somatic care only and France reports somatic care as its total, so their psychiatric cells (and the Dutch totals) are null.",
        ("2023-01-01", "2023-12-31"),
        assumed=[
            {"parameter": "rows[*].discharges_per_100000_inhabitants", "value": "discharges * 100000 / average_population", "method": "derived", "rationale": "Eurostat's historical per-100 000 series stops at 2021; the rate is rebuilt from the published discharge count and the average population of the same year."},
            {"parameter": "rows[*].somatic_discharges_per_100000_inhabitants", "value": "somatic_discharges * 100000 / average_population", "method": "derived", "rationale": "Same construction for somatic care, which is the comparable series for countries that exclude psychiatric care."},
        ],
        derive=derive_discharge_rates,
    ),
    GeoLookup(
        "eu-comparative-price-levels-2024", "Comparative price levels of household consumption by purpose and of GDP, EU27 = 100, 2024, ten member states", "economy",
        (Source("prc_ppp_ind", "purchasing power parities, price level indices, nominal and real expenditures by analytical categories", f"A.PLI_EU27_2020.{'+'.join(PRICE_LEVEL_CATEGORIES)}.{GEO_KEY}", tuple(Column(name, {"ppp_cat": code}) for code, name in PRICE_LEVEL_CATEGORIES.items()), "decimal", "2024"),),
        ["price-levels", "purchasing-power-parities", "prices", "cost-of-living"], ["pricing", "market-sizing", "customer-segmentation", "retail-demo", "financial-planning"],
        "Price level indices for 2024 from Eurostat dataflow prc_ppp_ind (PLI_EU27_2020, EU27 average = 100) for household final consumption expenditure, "
        "each of its twelve COICOP purposes (food, alcohol and tobacco, clothing, housing and energy, furnishings, health, transport, communication, recreation, education, restaurants and hotels, miscellaneous) and gross domestic product. "
        "A value above 100 means the country is more expensive than the EU average for that basket.",
        ("2024-01-01", "2024-12-31"),
    ),
    GeoLookup(
        "eu-hourly-earnings-by-sex-and-occupation-group-2022", "Mean and median gross hourly earnings by sex and occupation group, 2022, ten member states", "employment",
        (Source("earn_ses_hourly", "structure of earnings survey, hourly earnings", f"A.B-S_X_O..TOTAL.TOTAL.T+F+M.MEAN_E_EUR+MED_E_EUR.{GEO_KEY}", tuple(
            Column(f"{stat}_hourly_eur_{sex_name}_{group_name}", {"indic_se": indic, "sex": sex, "isco08": group})
            for indic, stat in (("MEAN_E_EUR", "mean"), ("MED_E_EUR", "median")) for sex, sex_name in SEXES.items() for group, group_name in OCCUPATION_GROUPS.items()
        ), "currency:EUR", "2022"),),
        ["earnings", "wages", "sex", "occupation", "structure-of-earnings-survey"], ["payroll-demo", "hr-analytics", "person-generation", "personal-finance", "workforce-planning"],
        "Mean and median gross hourly earnings in euro from the 2022 Structure of Earnings Survey (Eurostat dataflow earn_ses_hourly), for industry, construction and services except public administration (NACE B to S excluding O), "
        "all working-time arrangements and ages, by sex (total, female, male) and by the ISCO-08 occupation groups Eurostat publishes for this wave: all occupations, non-manual workers (major groups 1 to 5), skilled manual workers (6 to 8) and manual workers (7 to 9). "
        "The survey is four-yearly; 2022 is the latest wave.",
        ("2022-01-01", "2022-12-31"),
    ),
    GeoLookup(
        "eu-gender-pay-gap-by-nace-section-2024", "Unadjusted gender pay gap by NACE Rev. 2 section, 2024, ten member states", "employment",
        (Source("earn_gr_gpgr2", "gender pay gap in unadjusted form by NACE Rev. 2 activity", f"A.PC.{'+'.join(PAY_GAP_ACTIVITIES)}.{GEO_KEY}", tuple(Column(f"gap_percent_{slug(code)}", {"nace_r2": code}) for code in PAY_GAP_ACTIVITIES), "percent", "2024"),),
        ["gender-pay-gap", "earnings", "sex", "nace"], ["hr-analytics", "payroll-demo", "person-generation", "workforce-planning"],
        "Unadjusted gender pay gap for 2024 from Eurostat dataflow earn_gr_gpgr2: the difference between the average gross hourly earnings of men and of women as a percentage of men's, "
        "for industry, construction and services except public administration (B-S_X_O), the whole of B to S, the business economy (B-N) and each section from C to S that Eurostat publishes. "
        "Ireland reports only the three aggregates, so its section cells are null.",
        ("2024-01-01", "2024-12-31"),
    ),
    GeoLookup(
        "eu-house-price-index-2025", "House price index, annual average rate of change and level (2015 = 100), total, new and existing dwellings, 2025, ten member states", "property",
        (Source("prc_hpi_a", "house price index, annual data", f"A.TOTAL+DW_NEW+DW_EXST.RCH_A_AVG+I15_A_AVG.{GEO_KEY}", (
            Column("annual_rate_of_change_percent", {"purchase": "TOTAL", "unit": "RCH_A_AVG"}), Column("annual_rate_of_change_percent_new_dwellings", {"purchase": "DW_NEW", "unit": "RCH_A_AVG"}), Column("annual_rate_of_change_percent_existing_dwellings", {"purchase": "DW_EXST", "unit": "RCH_A_AVG"}),
            Column("index_2015_100", {"purchase": "TOTAL", "unit": "I15_A_AVG"}), Column("index_2015_100_new_dwellings", {"purchase": "DW_NEW", "unit": "I15_A_AVG"}), Column("index_2015_100_existing_dwellings", {"purchase": "DW_EXST", "unit": "I15_A_AVG"}),
        ), "percent", "2025"),),
        ["house-prices", "housing", "property-prices"], ["property-demo", "mortgage-origination", "insurance", "financial-planning"],
        "House price index for 2025 from Eurostat dataflow prc_hpi_a: the annual average rate of change in percent and the annual average index level (2015 = 100) for all dwellings, newly built dwellings and existing dwellings purchased by households.",
        ("2025-01-01", "2025-12-31"),
    ),
    GeoLookup(
        "eu-housing-cost-share-of-disposable-income-2025", "Share of housing costs in disposable household income, all households and by poverty status, 2025 survey year, ten member states", "income",
        (Source("ilc_mded01", "share of housing costs in disposable household income, by type of household and income group, EU-SILC survey", f"A.TOTAL.TOTAL+A_60+B_60.PC.{GEO_KEY}", (
            Column("housing_cost_share_percent", {"rskpovth": "TOTAL"}), Column("housing_cost_share_percent_below_60_median_income", {"rskpovth": "B_60"}), Column("housing_cost_share_percent_above_60_median_income", {"rskpovth": "A_60"}),
        ), "percent", "2025"),),
        ["housing-costs", "rent", "eu-silc", "living-conditions"], ["household-generation", "personal-finance", "credit-risk", "mortgage-origination", "property-demo"],
        "Mean share of total housing costs in disposable household income, EU-SILC survey year 2025, from Eurostat dataflow ilc_mded01, "
        "for all households and separately for people below and above 60 percent of the median equivalised income (the at-risk-of-poverty threshold). "
        "EU-SILC income refers to the calendar year before the survey year; valid_from and valid_to bound the survey year under which Eurostat files the figures.",
        ("2025-01-01", "2025-12-31"),
    ),
    GeoLookup(
        "eu-enterprise-e-commerce-sales-2025", "Enterprises with e-commerce and web sales and the share of turnover they earn online, enterprises with ten or more employees, 2025, ten member states", "digital",
        (
            Source("isoc_ec_eseln2", "e-commerce sales of enterprises by NACE Rev. 2 activity", f"A.GE10.C10-S951_X_K.E_AESELL+E_ESELL+E_AWSELL+E_AWS_B2BG+E_AWSFOR.PC_ENT.{GEO_KEY}", (
                Column("enterprises_with_e_commerce_sales_percent", {"indic_is": "E_AESELL"}), Column("enterprises_with_e_commerce_sales_of_at_least_1_percent_of_turnover_percent", {"indic_is": "E_ESELL"}),
                Column("enterprises_with_web_sales_percent", {"indic_is": "E_AWSELL"}), Column("enterprises_with_b2b_or_b2g_web_sales_percent", {"indic_is": "E_AWS_B2BG"}), Column("enterprises_with_web_sales_to_foreign_countries_percent", {"indic_is": "E_AWSFOR"}),
            ), "percent", "2025"),
            Source("isoc_ec_evaln2", "value of e-commerce sales by NACE Rev. 2 activity", f"A.GE10.C10-S951_X_K.E_AWSVAL+E_AWSVAL_B2C+E_AWSVAL_B2BG+E_AWSVAL_COWN+E_AWSVAL_CMP.PC_TURN+PC_AWSVAL.{GEO_KEY}", (
                Column("web_sales_share_of_turnover_percent", {"indic_is": "E_AWSVAL", "unit": "PC_TURN"}), Column("b2c_share_of_web_sales_percent", {"indic_is": "E_AWSVAL_B2C", "unit": "PC_AWSVAL"}),
                Column("b2b_or_b2g_share_of_web_sales_percent", {"indic_is": "E_AWSVAL_B2BG", "unit": "PC_AWSVAL"}), Column("own_website_or_app_share_of_web_sales_percent", {"indic_is": "E_AWSVAL_COWN", "unit": "PC_AWSVAL"}),
                Column("marketplace_share_of_web_sales_percent", {"indic_is": "E_AWSVAL_CMP", "unit": "PC_AWSVAL"}),
            ), "percent", "2025"),
        ),
        ["e-commerce", "web-sales", "enterprises", "digital"], ["digital-channels", "sales-generation", "retail-demo", "company-generation", "market-sizing"],
        "Enterprise e-commerce for 2025 from the ICT usage in enterprises survey (Eurostat dataflows isoc_ec_eseln2 and isoc_ec_evaln2), enterprises with ten or more employees in manufacturing and services (NACE C10 to S95.1 excluding K): "
        "the percentage of enterprises with any e-commerce sales, with e-commerce sales of at least one percent of turnover, with web sales (websites, apps or marketplaces), with B2B or B2G web sales and with web sales to other countries; "
        "and, from the value flow, the share of total turnover earned through web sales and how web sales split between B2C and B2B or B2G customers and between own websites or apps and marketplaces. "
        "France withholds the foreign web sales cell as unreliable, so it is null.",
        ("2025-01-01", "2025-12-31"),
    ),
    GeoLookup(
        "eu-road-freight-transport-2025", "Road freight transport: tonne-kilometres, vehicle-kilometres, tonnes and derived load factors, 2025, ten member states", "transport",
        (Source("road_go_ta_tott", "road freight transport by type of operation and type of transport", f"A.TOTAL.TOTAL+LOADED+EMPTY+LNAT+LINTL.MIO_TKM+MIO_VKM+THS_T.{GEO_KEY}", (
            Column("tonne_km_million_total", {"tra_oper": "TOTAL", "unit": "MIO_TKM"}), Column("tonne_km_million_national", {"tra_oper": "LNAT", "unit": "MIO_TKM"}), Column("tonne_km_million_international", {"tra_oper": "LINTL", "unit": "MIO_TKM"}),
            Column("vehicle_km_million_total", {"tra_oper": "TOTAL", "unit": "MIO_VKM"}), Column("vehicle_km_million_loaded", {"tra_oper": "LOADED", "unit": "MIO_VKM"}), Column("vehicle_km_million_empty", {"tra_oper": "EMPTY", "unit": "MIO_VKM"}),
            Column("tonnes_thousand_total", {"tra_oper": "TOTAL", "unit": "THS_T"}),
        ), "decimal", "2025"),),
        ["road-freight", "logistics", "tonne-kilometres", "load-factor"], ["logistics", "fleet-demo", "capacity-planning", "demand-forecasting"],
        "Road freight transport in 2025 reported by each country to Eurostat dataflow road_go_ta_tott (hire-or-reward and own-account operations together): "
        "million tonne-kilometres in total and split into national and international transport, million vehicle-kilometres in total and split into loaded and empty running, and thousand tonnes carried. "
        "Derived columns give the empty-running share of vehicle-kilometres, the international share of tonne-kilometres and the average load per loaded vehicle-kilometre. "
        "Italy publishes no empty-running figures, so its empty cells and the empty-running share are null.",
        ("2025-01-01", "2025-12-31"),
        assumed=[
            {"parameter": "rows[*].empty_running_share_of_vehicle_km", "value": "vehicle_km_million_empty / vehicle_km_million_total", "method": "derived", "rationale": "Share of all vehicle-kilometres driven empty, from the two published figures."},
            {"parameter": "rows[*].international_share_of_tonne_km", "value": "tonne_km_million_international / tonne_km_million_total", "method": "derived", "rationale": "Share of freight work performed in international transport."},
            {"parameter": "rows[*].average_load_tonnes_per_loaded_vehicle_km", "value": "tonne_km_million_total / vehicle_km_million_loaded", "method": "derived", "rationale": "Mean payload in tonnes while laden, since tonne-kilometres accrue only on loaded journeys."},
        ],
        derive=derive_freight_ratios,
    ),
]


def main() -> int:
    names = codelist("GEO")
    flags = codelist("OBS_FLAG")
    nace = codelist("NACE_R2")
    coicop = codelist("COICOP")

    for geo in GEOS:
        url = data_url("sbs_ovw_act", f"A.{SBS_NACE_KEY}.{'+'.join(SBS_INDICATORS)}.{geo}", "2024", "2024")
        write(enterprise_accounts(geo, names[geo], url, fetch_stable(url), nace, flags))

    for spec in LOOKUPS:
        write(spec.build(tuple(source.fetch() for source in spec.sources), names, flags))

    url = data_url("hbs_str_t211", f"A.CP01+CP02+CP03+CP04+CP05+CP06+CP07+CP08+CP09+CP10+CP11+CP12.PM.{GEO_KEY}", "2020", "2020")
    write(consumption_structure(url, fetch_stable(url), names, coicop, flags))

    url = data_url("avia_paoc", f"M.PAS.PAS_CRD.TOTAL.TOTAL.{GEO_KEY}", "2025-01", "2025-12")
    write(monthly_by_geo("eu-air-passengers-carried-monthly-2025", "Air passengers carried, all airports, monthly 2025, ten member states", "transport", "avia_paoc", "air passenger transport by type of schedule, transport coverage and country", url, fetch_stable(url), "passengers_carried", "count", ["aviation", "air-passengers", "seasonality", "transport"], ["demand-forecasting", "capacity-planning", "logistics", "sales-generation"], "Monthly passengers carried on commercial flights (scheduled and non-scheduled, national and international, arrivals and departures) at each country's reporting airports for 2025 from Eurostat dataflow avia_paoc. The series carries the seasonal profile of air travel demand.", flags))
    return 0


if __name__ == "__main__":
    sys.exit(main())

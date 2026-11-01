"""Regenerate the extended World Bank indicator reference tables (one lookup entry per indicator).

A companion to ``build_world_indicators.py`` covering income and macro, health,
demographics, infrastructure, education, finance, labour and environment
indicators from the World Development Indicators API. Each indicator becomes
a rule entry implemented by ``lookup_table``: rows are keyed by ISO 3166-1
alpha-3 code and hold the indicator value for the chosen year, with regional
and income aggregates removed. The year is the most recent one whose coverage
is close to the indicator's best recent year. Run from the repository root:

    uv run python tools/build_world_indicators_extended.py [INDICATOR_CODE ...]
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, sha, write  # noqa: E402

API = "https://api.worldbank.org/v2"
COUNTRIES_URL = f"{API}/country?format=json&per_page=400"
LICENSE_URL = "https://datacatalog.worldbank.org/public-licenses"
PUBLISHER = "World Bank"
LICENSE = "CC-BY-4.0"
PREFERRED_SAMPLE = "IND"


@dataclass(frozen=True)
class Indicator:
    """One World Development Indicators series and how its entry is filed."""

    code: str
    year: int
    entry_id: str
    variable: str
    unit: str
    domain: str
    tags: tuple[str, ...]
    use_cases: tuple[str, ...]


INDICATORS: tuple[Indicator, ...] = (
    # Income and macro
    Indicator("NY.GNP.PCAP.CD", 2024, "global-gni-per-capita-atlas-2024", "gni_per_capita_usd", "currency:USD", "economy", ("macro", "income"), ("market-sizing", "customer-segmentation", "credit-risk")),
    Indicator("NY.GDP.MKTP.KD.ZG", 2024, "global-gdp-growth-2024", "gdp_growth_percent", "percent", "economy", ("macro", "growth"), ("market-sizing", "demand-forecasting", "financial-planning")),
    Indicator("NY.GDP.PCAP.PP.CD", 2024, "global-gdp-per-capita-ppp-2024", "gdp_per_capita_ppp_intl_dollars", "decimal", "economy", ("macro", "income", "ppp"), ("market-sizing", "customer-segmentation", "pricing")),
    Indicator("NE.EXP.GNFS.ZS", 2024, "global-exports-share-of-gdp-2024", "exports_percent_gdp", "percent", "economy", ("macro", "trade"), ("market-sizing", "logistics")),
    Indicator("BX.KLT.DINV.WD.GD.ZS", 2024, "global-fdi-net-inflows-share-of-gdp-2024", "fdi_net_inflows_percent_gdp", "percent", "economy", ("macro", "investment"), ("market-sizing", "treasury")),
    Indicator("GC.TAX.TOTL.GD.ZS", 2023, "global-tax-revenue-share-of-gdp-2023", "tax_revenue_percent_gdp", "percent", "economy", ("macro", "tax", "public-finance"), ("tax-filing-demo", "market-sizing")),
    Indicator("NY.GNS.ICTR.ZS", 2024, "global-gross-savings-share-of-gdp-2024", "gross_savings_percent_gdp", "percent", "economy", ("macro", "savings"), ("personal-finance", "banking-demo")),
    Indicator("NE.CON.PRVT.ZS", 2024, "global-household-consumption-share-of-gdp-2024", "household_consumption_percent_gdp", "percent", "economy", ("macro", "consumption"), ("retail-demo", "market-sizing", "demand-forecasting")),
    Indicator("NV.AGR.TOTL.ZS", 2024, "global-agriculture-value-added-share-2024", "agriculture_value_added_percent_gdp", "percent", "economy", ("macro", "sector-mix", "agriculture"), ("company-generation", "market-sizing")),
    Indicator("NV.IND.TOTL.ZS", 2024, "global-industry-value-added-share-2024", "industry_value_added_percent_gdp", "percent", "economy", ("macro", "sector-mix", "industry"), ("company-generation", "market-sizing")),
    Indicator("NV.SRV.TOTL.ZS", 2024, "global-services-value-added-share-2024", "services_value_added_percent_gdp", "percent", "economy", ("macro", "sector-mix", "services"), ("company-generation", "market-sizing")),
    Indicator("PA.NUS.FCRF", 2024, "global-official-exchange-rate-lcu-per-usd-2024", "lcu_per_usd_period_average", "decimal", "economy", ("exchange-rates", "fx", "currency"), ("multi-currency-ledger", "financial-reporting", "treasury")),
    Indicator("PA.NUS.PPP", 2024, "global-ppp-conversion-factor-2024", "lcu_per_international_dollar", "decimal", "economy", ("ppp", "prices", "currency"), ("pricing", "market-sizing", "multi-currency-ledger")),
    Indicator("FP.CPI.TOTL", 2024, "global-consumer-price-index-2024", "cpi_index_2010_base", "decimal", "economy", ("prices", "cpi", "inflation"), ("pricing", "contract-indexation", "financial-planning")),
    Indicator("TG.VAL.TOTL.GD.ZS", 2024, "global-merchandise-trade-share-of-gdp-2024", "merchandise_trade_percent_gdp", "percent", "economy", ("trade", "macro"), ("logistics", "market-sizing")),
    # Finance and banking
    Indicator("FS.AST.PRVT.GD.ZS", 2024, "global-domestic-credit-to-private-sector-2024", "private_credit_percent_gdp", "percent", "economy", ("banking", "credit", "financial-depth"), ("banking-demo", "credit-risk", "loan-pricing")),
    Indicator("BX.TRF.PWKR.DT.GD.ZS", 2024, "global-remittances-received-share-of-gdp-2024", "remittances_received_percent_gdp", "percent", "economy", ("remittances", "payments", "cross-border"), ("payments-demo", "fintech-demo", "market-sizing")),
    Indicator("FB.ATM.TOTL.P5", 2024, "global-atms-per-100k-adults-2024", "atms_per_100k_adults", "ratio", "economy", ("banking", "financial-inclusion", "atm"), ("banking-demo", "digital-channels", "capacity-planning")),
    Indicator("FB.CBK.BRCH.P5", 2024, "global-bank-branches-per-100k-adults-2024", "bank_branches_per_100k_adults", "ratio", "economy", ("banking", "financial-inclusion", "branches"), ("banking-demo", "capacity-planning", "address-generation")),
    Indicator("FB.AST.NPER.ZS", 2024, "global-bank-nonperforming-loans-2024", "nonperforming_loans_percent", "percent", "economy", ("banking", "credit", "npl"), ("credit-risk", "collections", "banking-demo")),
    Indicator("IC.BUS.NDNS.ZS", 2024, "global-new-business-density-2024", "new_registrations_per_1000_adults", "ratio", "economy", ("business-registration", "entrepreneurship"), ("company-generation", "kyb-onboarding", "market-sizing")),
    Indicator("FR.INR.LEND", 2024, "global-lending-interest-rate-2024", "lending_rate_percent", "percent", "rates", ("interest-rates", "lending", "banking"), ("loan-pricing", "banking-demo", "credit-risk")),
    Indicator("FR.INR.DPST", 2024, "global-deposit-interest-rate-2024", "deposit_rate_percent", "percent", "rates", ("interest-rates", "deposits", "banking"), ("banking-demo", "personal-finance", "treasury")),
    # Health
    Indicator("SH.XPD.CHEX.PC.CD", 2023, "global-health-expenditure-per-capita-2023", "health_expenditure_per_capita_usd", "currency:USD", "healthcare", ("health", "health-spending"), ("health-demo", "claims-generation", "insurance")),
    Indicator("SH.XPD.CHEX.GD.ZS", 2023, "global-health-expenditure-share-of-gdp-2023", "health_expenditure_percent_gdp", "percent", "healthcare", ("health", "health-spending", "macro"), ("health-demo", "market-sizing")),
    Indicator("SH.XPD.OOPC.CH.ZS", 2023, "global-out-of-pocket-health-expenditure-share-2023", "out_of_pocket_percent_health_expenditure", "percent", "healthcare", ("health", "health-spending", "out-of-pocket"), ("claims-generation", "insurance", "health-demo")),
    Indicator("SH.MED.PHYS.ZS", 2022, "global-physicians-per-1000-2022", "physicians_per_1000", "ratio", "healthcare", ("health", "workforce", "physicians"), ("health-demo", "capacity-planning", "clinical-records")),
    Indicator("SH.MED.BEDS.ZS", 2022, "global-hospital-beds-per-1000-2022", "hospital_beds_per_1000", "ratio", "healthcare", ("health", "hospitals", "capacity"), ("health-demo", "capacity-planning", "clinical-records")),
    Indicator("SH.MED.NUMW.P3", 2022, "global-nurses-and-midwives-per-1000-2022", "nurses_and_midwives_per_1000", "ratio", "healthcare", ("health", "workforce", "nursing"), ("health-demo", "capacity-planning", "hr-analytics")),
    Indicator("SP.DYN.IMRT.IN", 2024, "global-infant-mortality-rate-2024", "infant_deaths_per_1000_live_births", "ratio", "healthcare", ("health", "mortality", "infants"), ("health-demo", "clinical-records", "insurance")),
    Indicator("SH.DYN.MORT", 2024, "global-under-5-mortality-rate-2024", "under_5_deaths_per_1000_live_births", "ratio", "healthcare", ("health", "mortality", "children"), ("health-demo", "clinical-records", "insurance")),
    Indicator("SP.DYN.CBRT.IN", 2024, "global-crude-birth-rate-2024", "births_per_1000_people", "ratio", "healthcare", ("health", "demographics", "births"), ("person-generation", "household-generation", "health-demo")),
    Indicator("SP.DYN.CDRT.IN", 2024, "global-crude-death-rate-2024", "deaths_per_1000_people", "ratio", "healthcare", ("health", "demographics", "mortality"), ("insurance", "pensions", "health-demo")),
    Indicator("SH.PRV.SMOK", 2024, "global-tobacco-use-prevalence-2024", "tobacco_use_percent_adults", "percent", "healthcare", ("health", "risk-factors", "tobacco"), ("insurance", "health-demo", "person-generation")),
    Indicator("SH.STA.DIAB.ZS", 2024, "global-diabetes-prevalence-2024", "diabetes_percent_ages_20_79", "percent", "healthcare", ("health", "chronic-disease", "diabetes"), ("claims-generation", "clinical-records", "insurance")),
    Indicator("SP.DYN.LE00.FE.IN", 2024, "global-life-expectancy-female-2024", "female_life_expectancy_years", "decimal", "healthcare", ("health", "demographics", "life-expectancy"), ("insurance", "pensions", "person-generation")),
    Indicator("SP.DYN.LE00.MA.IN", 2024, "global-life-expectancy-male-2024", "male_life_expectancy_years", "decimal", "healthcare", ("health", "demographics", "life-expectancy"), ("insurance", "pensions", "person-generation")),
    # Demographics
    Indicator("EN.POP.DNST", 2024, "global-population-density-2024", "people_per_sq_km", "decimal", "demographics", ("demographics", "population", "density"), ("address-generation", "logistics", "market-sizing")),
    Indicator("SP.POP.DPND", 2024, "global-age-dependency-ratio-2024", "dependents_per_100_working_age", "percent", "demographics", ("demographics", "age-structure"), ("pensions", "household-generation", "workforce-planning")),
    Indicator("SP.POP.65UP.TO.ZS", 2024, "global-population-65-and-above-share-2024", "population_65_plus_percent", "percent", "demographics", ("demographics", "age-structure", "ageing"), ("pensions", "insurance", "person-generation")),
    Indicator("SP.POP.0014.TO.ZS", 2024, "global-population-0-14-share-2024", "population_0_14_percent", "percent", "demographics", ("demographics", "age-structure", "children"), ("household-generation", "person-generation", "customer-segmentation")),
    Indicator("SM.POP.NETM", 2024, "global-net-migration-2024", "net_migrants", "integer", "demographics", ("demographics", "migration"), ("person-generation", "workforce-planning", "market-sizing")),
    Indicator("SP.POP.GROW", 2024, "global-population-growth-2024", "population_growth_percent", "percent", "demographics", ("demographics", "population", "growth"), ("market-sizing", "demand-forecasting", "capacity-planning")),
    Indicator("SP.POP.BRTH.MF", 2024, "global-sex-ratio-at-birth-2024", "male_births_per_female_birth", "ratio", "demographics", ("demographics", "sex", "births"), ("person-generation", "clinical-records")),
    # Energy and infrastructure
    Indicator("EG.ELC.ACCS.ZS", 2024, "global-access-to-electricity-2024", "electricity_access_percent", "percent", "energy", ("electricity", "access", "utilities"), ("utilities-demo", "market-sizing", "household-generation")),
    Indicator("EG.CFT.ACCS.ZS", 2024, "global-access-to-clean-cooking-fuels-2024", "clean_cooking_access_percent", "percent", "energy", ("energy", "access", "households"), ("utilities-demo", "household-generation")),
    Indicator("EG.USE.ELEC.KH.PC", 2024, "global-electricity-consumption-per-capita-2024", "kwh_per_capita", "decimal", "energy", ("electricity", "consumption", "utilities"), ("utilities-demo", "demand-forecasting", "capacity-planning")),
    Indicator("EG.FEC.RNEW.ZS", 2021, "global-renewable-energy-consumption-share-2021", "renewable_percent_final_energy", "percent", "energy", ("energy", "renewables"), ("utilities-demo", "financial-reporting")),
    Indicator("EG.ELC.RNEW.ZS", 2021, "global-renewable-electricity-output-share-2021", "renewable_percent_electricity_output", "percent", "energy", ("electricity", "renewables", "utilities"), ("utilities-demo", "financial-reporting")),
    Indicator("IT.NET.BBND.P2", 2023, "global-fixed-broadband-subscriptions-per-100-2023", "fixed_broadband_per_100", "ratio", "telecom", ("telecom", "broadband", "digital"), ("telecom-demo", "digital-channels", "market-sizing")),
    Indicator("IT.NET.SECR.P6", 2024, "global-secure-internet-servers-per-million-2024", "secure_servers_per_million", "ratio", "telecom", ("digital", "internet", "security"), ("digital-channels", "telecom-demo")),
    Indicator("SH.H2O.BASW.ZS", 2024, "global-basic-drinking-water-access-2024", "basic_water_access_percent", "percent", "infrastructure", ("water", "access", "utilities"), ("utilities-demo", "household-generation")),
    Indicator("IS.AIR.PSGR", 2023, "global-air-passengers-carried-2023", "air_passengers", "count", "infrastructure", ("transport", "aviation", "travel"), ("logistics", "capacity-planning", "market-sizing")),
    Indicator("LP.LPI.OVRL.XQ", 2022, "global-logistics-performance-index-2022", "lpi_score_1_to_5", "decimal", "infrastructure", ("logistics", "transport", "index"), ("logistics", "sla-calculation")),
    # Education
    Indicator("SE.TER.ENRR", 2023, "global-tertiary-enrollment-ratio-2023", "tertiary_gross_enrollment_percent", "percent", "education", ("education", "tertiary", "enrollment"), ("person-generation", "hr-analytics", "workforce-planning")),
    Indicator("SE.SEC.ENRR", 2023, "global-secondary-enrollment-ratio-2023", "secondary_gross_enrollment_percent", "percent", "education", ("education", "secondary", "enrollment"), ("person-generation", "household-generation")),
    Indicator("SE.XPD.TOTL.GD.ZS", 2022, "global-education-expenditure-share-of-gdp-2022", "education_expenditure_percent_gdp", "percent", "education", ("education", "public-finance"), ("market-sizing", "financial-planning")),
    # Labour
    Indicator("SL.EMP.TOTL.SP.ZS", 2024, "global-employment-to-population-ratio-2024", "employment_to_population_percent", "percent", "employment", ("labour", "employment"), ("hr-analytics", "workforce-planning", "person-generation")),
    Indicator("SL.TLF.CACT.FE.ZS", 2024, "global-female-labour-force-participation-2024", "female_participation_percent", "percent", "employment", ("labour", "gender", "participation"), ("hr-analytics", "workforce-planning", "person-generation")),
    Indicator("SL.UEM.1524.ZS", 2024, "global-youth-unemployment-rate-2024", "youth_unemployment_percent", "percent", "employment", ("labour", "unemployment", "youth"), ("hr-analytics", "credit-risk", "person-generation")),
    Indicator("SL.EMP.SELF.ZS", 2024, "global-self-employment-share-2024", "self_employed_percent", "percent", "employment", ("labour", "self-employment"), ("person-generation", "kyc-onboarding", "credit-risk")),
    Indicator("SL.AGR.EMPL.ZS", 2024, "global-employment-in-agriculture-share-2024", "agriculture_employment_percent", "percent", "employment", ("labour", "sector-mix", "agriculture"), ("person-generation", "hr-analytics", "workforce-planning")),
    Indicator("SL.IND.EMPL.ZS", 2024, "global-employment-in-industry-share-2024", "industry_employment_percent", "percent", "employment", ("labour", "sector-mix", "industry"), ("person-generation", "hr-analytics", "workforce-planning")),
    Indicator("SL.SRV.EMPL.ZS", 2024, "global-employment-in-services-share-2024", "services_employment_percent", "percent", "employment", ("labour", "sector-mix", "services"), ("person-generation", "hr-analytics", "workforce-planning")),
    # Environment
    Indicator("EN.GHG.CO2.PC.CE.AR5", 2024, "global-co2-emissions-per-capita-2024", "co2_tonnes_per_capita", "decimal", "environment", ("emissions", "co2", "climate"), ("financial-reporting", "utilities-demo", "logistics")),
    Indicator("EN.ATM.PM25.MC.M3", 2023, "global-pm25-air-pollution-exposure-2023", "pm25_micrograms_per_m3", "decimal", "environment", ("air-quality", "pollution", "health"), ("health-demo", "insurance", "claims-generation")),
    Indicator("AG.LND.TOTL.K2", 2024, "global-land-area-2024", "land_area_sq_km", "decimal", "environment", ("geography", "land-area"), ("address-generation", "logistics", "market-sizing")),
)


def fetch_stable(url: str) -> bytes:
    """Fetch a URL twice and return its bytes only when both responses hash identically."""
    first, second = fetch(url), fetch(url)
    if sha(first) != sha(second):
        raise RuntimeError(f"unstable content at {url}")
    return first


def economies(countries_raw: bytes) -> dict[str, dict]:
    return {c["id"]: c for c in json.loads(countries_raw)[1] if c["region"]["value"] != "Aggregates"}


def metadata_locator(info: dict, meta_raw: bytes) -> tuple[str, str]:
    """Return the metadata field cited as evidence: the name when the raw JSON carries it verbatim, else the id.

    The API escapes solidus characters in names (``\\/``), so a name containing one cannot be matched
    byte-for-byte against the resource; the indicator id is then the field whose value is cited.
    """
    name = info["name"]
    if name.encode("utf-8") in meta_raw:
        return "name", name
    return "id", info["id"]


def build(spec: Indicator, data_raw: bytes, meta_raw: bytes, countries: dict[str, dict], countries_raw: bytes, license_raw: bytes) -> dict:
    meta, rows_raw = json.loads(data_raw)
    info = json.loads(meta_raw)[1][0]
    meta_field, meta_value = metadata_locator(info, meta_raw)
    rows: dict[str, dict] = {}
    for r in rows_raw:
        code = r["countryiso3code"]
        if code in countries and r["value"] is not None:
            rows[code] = {"name": r["country"]["value"], "value": r["value"]}
    rows = dict(sorted(rows.items()))
    values = [r["value"] for r in rows.values()]
    sample_code = PREFERRED_SAMPLE if PREFERRED_SAMPLE in rows else next(iter(rows))
    sample = rows[sample_code]
    high = max(rows, key=lambda k: rows[k]["value"])
    low = min(rows, key=lambda k: rows[k]["value"])
    data_url = f"{API}/country/all/indicator/{spec.code}?date={spec.year}&format=json&per_page=400"
    series_title = f"World Development Indicators API, {spec.code} ({info['name']}), {spec.year}"
    return {
        "id": spec.entry_id,
        "title": f"{info['name']}, by economy, {spec.year} (World Bank, {len(rows)} economies)",
        "kind": "rule",
        "domain": spec.domain,
        "region": "global",
        "status": "verified",
        "tier": "A",
        "valid_from": f"{spec.year}-01-01",
        "valid_to": f"{spec.year}-12-31",
        "tags": [*spec.tags, "world-bank", "reference-table"],
        "use_cases": list(spec.use_cases),
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"indicator": spec.code, "year": spec.year, "variable": spec.variable, "unit": spec.unit, "rows": rows},
            "vectors": [
                {"input": {"key": sample_code, "column": "value"}, "expected": sample["value"], "origin": "source"},
                {"input": {"key": high, "column": "value"}, "expected": rows[high]["value"], "origin": "source", "note": "largest value"},
                {"input": {"key": low, "column": "value"}, "expected": rows[low]["value"], "origin": "source", "note": "smallest value"},
                {"input": sample_code, "expected": True, "origin": "source"},
                {"input": "WLD", "expected": False, "origin": "derived", "note": "aggregates are excluded"},
            ],
        },
        "evidence": [
            evidence(PUBLISHER, series_title, data_url, f"rows[countryiso3code={sample_code}].value", sample["value"], spec.unit, f'"countryiso3code":"{sample_code}"', LICENSE, data_raw),
            evidence(PUBLISHER, series_title, data_url, "lastupdated", meta["lastupdated"], "date", '"lastupdated":', LICENSE, data_raw),
            evidence(PUBLISHER, f"World Bank indicator metadata, {spec.code}", f"{API}/indicator/{spec.code}?format=json", meta_field, meta_value, "text", f'"id":"{spec.code}"', LICENSE, meta_raw),
            evidence(PUBLISHER, "World Bank country API (region classification used to exclude aggregates)", COUNTRIES_URL, "country[id=IND].region.value", "South Asia", "text", '"id":"IND"', LICENSE, countries_raw),
            evidence(PUBLISHER, "World Bank Data Catalog public licenses", LICENSE_URL, "Data Access And Licensing", "Creative Commons Attribution 4.0 International license", "text", "The World Bank Group makes data publicly available according to open data standards", LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "rows",
                "value": "economies only",
                "method": "derived",
                "rationale": "Rows whose region is 'Aggregates' in the World Bank country API, and rows without a value for the year, are dropped; everything else is copied unchanged.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[value]", "expected": max(values), "tolerance": 0},
            {"statistic": "min[value]", "expected": min(values), "tolerance": 0},
        ],
        "notes": (
            f"{info['name']} for {spec.year} from the World Development Indicators API (indicator {spec.code}, data last "
            f"updated {meta['lastupdated']}), one row per economy keyed by ISO 3166-1 alpha-3 code, with regional and "
            f"income aggregates removed. {spec.year} is the most recent year whose coverage is close to the series' best "
            f"recent year. Source note from the World Bank: {(info.get('sourceNote') or '').strip()[:400]} "
            "The World Bank licenses its datasets under CC BY 4.0."
        ),
    }


def main(argv: list[str]) -> int:
    """Rebuild every indicator, or only the indicator codes given on the command line."""
    selected = [spec for spec in INDICATORS if not argv or spec.code in argv]
    unknown = set(argv) - {spec.code for spec in selected}
    if unknown:
        raise SystemExit(f"unknown indicator codes: {', '.join(sorted(unknown))}")
    countries_raw = fetch_stable(COUNTRIES_URL)
    license_raw = fetch_stable(LICENSE_URL)
    countries = economies(countries_raw)
    for spec in selected:
        data_raw = fetch_stable(f"{API}/country/all/indicator/{spec.code}?date={spec.year}&format=json&per_page=400")
        meta_raw = fetch_stable(f"{API}/indicator/{spec.code}?format=json")
        write(build(spec, data_raw, meta_raw, countries, countries_raw, license_raw))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

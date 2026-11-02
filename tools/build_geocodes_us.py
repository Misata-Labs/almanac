"""Regenerate the United States geographic and industry code entries from US Census Bureau static files: state and
county FIPS codes, the 2024 Gazetteer counties, core based statistical areas and ZIP Code Tabulation Areas, 2020
places, the July 2023 CBSA delineation list and the 2022 NAICS code list. Run from the repository root:

    uv run python tools/build_geocodes_us.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ACCESSED, evidence, write
from _geocodes import (
    accessed_assumption,
    column_vector,
    csv_rows,
    lookup_tests,
    membership_vectors,
    rule_entry,
    set_tests,
    set_vectors,
    sheet_rows,
    stable,
    vintage_assumption,
    zip_member,
)

CENSUS = "United States Census Bureau"
LICENSE = "unstated"
STATUS = "license-review"
LICENSE_NOTE = "The Census Bureau publishes the file without a licence statement, so the licence is recorded as unstated and the entry held at license-review."

STATE_URL = "https://www2.census.gov/geo/docs/reference/state.txt"
COUNTY_URL = "https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt"
PLACE_URL = "https://www2.census.gov/geo/docs/reference/codes2020/national_place2020.txt"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
GAZ_COUNTIES_URL = GAZ + "2024_Gaz_counties_national.zip"
GAZ_CBSA_URL = GAZ + "2024_Gaz_cbsa_national.zip"
GAZ_ZCTA_URL = GAZ + "2024_Gaz_zcta_national.zip"
CBSA_LIST_URL = "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx"
NAICS_URL = "https://www.census.gov/naics/2022NAICS/2-6%20digit_2022_Codes.xlsx"

ZCTA_PREFIX_RANGE = ("100", "149")
PLACE_STATE = "CA"


def collapse(text: str) -> str:
    return " ".join(text.split())


def line_with(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return collapse(line)
    raise LookupError(f"no line contains {needle!r}")


def number(text: str) -> float | int:
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


# ---------------------------------------------------------------- FIPS code lists ----------------------------------------------------------------


def states(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    rows = {r["STUSAB"]: {"fips": r["STATE"], "name": r["STATE_NAME"], "gnis": r["STATENS"]} for r in csv_rows(text, "|")}
    title = "State FIPS codes (state.txt)"
    return rule_entry(
        "us-census-state-fips-codes",
        "United States state, District of Columbia and outlying area FIPS codes, USPS abbreviations, names and GNIS identifiers",
        "geography",
        "US",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.lookup_table",
        parameters={"key": "USPS state abbreviation", "rows": rows},
        vectors=membership_vectors(["AL", "CA", "PR"], "ZZ") + [column_vector("AL", "fips", "01"), column_vector("CA", "name", rows["CA"]["name"])],
        evidence_items=[
            evidence(CENSUS, title, STATE_URL, "row AL", "01", "text", line_with(text, "|AL|"), LICENSE, raw),
            evidence(CENSUS, title, STATE_URL, "row CA", rows["CA"]["name"], "text", line_with(text, "|CA|"), LICENSE, raw),
        ],
        tests=lookup_tests(rows, [("AL", "fips"), ("CA", "fips"), ("PR", "name")]),
        notes=(
            "The Census Bureau's state.txt lists the two-digit FIPS state code, USPS abbreviation, name and GNIS (ANSI) identifier for "
            "the states, the District of Columbia and the outlying areas. Rows are keyed by the USPS abbreviation. "
            + LICENSE_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status=STATUS,
        tags=["fips", "states", "census", "code-list"],
        use_cases=["address-generation", "customer-segmentation"],
        assumed=[accessed_assumption()],
    )


def counties(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    rows = {
        r["STATEFP"] + r["COUNTYFP"]: {"state": r["STATE"], "name": r["COUNTYNAME"], "class": r["CLASSFP"], "funcstat": r["FUNCSTAT"]}
        for r in csv_rows(text, "|")
    }
    title = "2020 national county and county-equivalent codes (national_county2020.txt)"
    return rule_entry(
        "us-census-county-fips-codes-2020",
        "United States counties and county equivalents, 2020 vintage: five-digit FIPS code, state, name, class and functional status",
        "geography",
        "US",
        valid_from="2020-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "five-digit state plus county FIPS code", "rows": rows},
        vectors=membership_vectors(["01001", "06037", "72001"], "99999") + [column_vector("01001", "name", "Autauga County"), column_vector("06037", "state", "CA")],
        evidence_items=[
            evidence(CENSUS, title, COUNTY_URL, "row AL|01|001", "Autauga County", "text", line_with(text, "AL|01|001|"), LICENSE, raw),
            evidence(CENSUS, title, COUNTY_URL, "row CA|06|037", rows["06037"]["name"], "text", line_with(text, "CA|06|037|"), LICENSE, raw),
        ],
        tests=lookup_tests(rows, [("01001", "name"), ("06037", "name"), ("72001", "state")]),
        notes=(
            "Every county and county equivalent (parishes, boroughs, independent cities, municipios) in the Census Bureau's 2020 national "
            "county code file, keyed by the five-digit state-plus-county FIPS code, with the USPS state, name, FIPS class code and "
            "functional status as published; the GNIS identifier column is left out to keep the entry compact. " + LICENSE_NOTE + " " + vintage_assumption("2020-01-01", "2020")["rationale"]
        ),
        status=STATUS,
        tags=["fips", "counties", "census", "code-list"],
        use_cases=["address-generation", "customer-segmentation", "insurance"],
        assumed=[vintage_assumption("2020-01-01", "codes2020")],
    )


# ---------------------------------------------------------------- 2024 Gazetteer ----------------------------------------------------------------


def gazetteer_counties(raw: bytes) -> dict:
    member = "2024_Gaz_counties_national.txt"
    text = zip_member(raw, member)
    rows = {
        r["GEOID"]: {"land_sqmi": number(r["ALAND_SQMI"]), "latitude": number(r["INTPTLAT"]), "longitude": number(r["INTPTLONG"])}
        for r in csv_rows(text, "\t")
    }
    title = "2024 Gazetteer Files, counties (ZIP with tab-delimited text)"
    return rule_entry(
        "us-census-gazetteer-2024-counties",
        "United States counties, 2024 Gazetteer: land area in square miles and internal point coordinates by five-digit FIPS code",
        "geography",
        "US",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "five-digit state plus county FIPS code", "source_member": member, "rows": rows},
        vectors=membership_vectors(["01001", "06037"], "99999") + [column_vector("01001", "land_sqmi", rows["01001"]["land_sqmi"]), column_vector("06037", "latitude", rows["06037"]["latitude"])],
        evidence_items=[
            evidence(CENSUS, title, GAZ_COUNTIES_URL, f"{member}, row GEOID 01001, ALAND_SQMI", rows["01001"]["land_sqmi"], "decimal", line_with(text, "01001\t"), LICENSE, raw),
            evidence(CENSUS, title, GAZ_COUNTIES_URL, f"{member}, row GEOID 06037, INTPTLAT", rows["06037"]["latitude"], "decimal", line_with(text, "06037\t"), LICENSE, raw),
        ],
        tests=lookup_tests(rows, [("01001", "land_sqmi"), ("06037", "longitude")]) + [{"statistic": "max[land_sqmi]", "expected": max(r["land_sqmi"] for r in rows.values()), "tolerance": 0}],
        notes=(
            "The 2024 Gazetteer county file gives, for every county and county equivalent, the land area in square miles and the "
            "latitude and longitude of an internal point. Only those three columns are copied, to keep the entry compact: the key is the "
            "same five-digit FIPS code as the county code entry, which carries the state and name, and the square-mile values are the "
            "Census Bureau's own. " + LICENSE_NOTE + " " + vintage_assumption("2024-01-01", "2024")["rationale"]
        ),
        status=STATUS,
        tags=["gazetteer", "counties", "census", "coordinates", "land-area"],
        use_cases=["address-generation", "logistics", "insurance"],
        assumed=[vintage_assumption("2024-01-01", "2024 Gazetteer")],
    )


def gazetteer_cbsas(raw: bytes) -> dict:
    member = "2024_Gaz_cbsa_national.txt"
    text = zip_member(raw, member)
    rows = {}
    for r in csv_rows(text, "\t"):
        kind = "metropolitan" if r["NAME"].endswith("Metro Area") else "micropolitan" if r["NAME"].endswith("Micro Area") else None
        rows[r["GEOID"]] = {"name": r["NAME"], "cbsa_type": r["CBSA_TYPE"], "type": kind, "csa": r["CSAFP"] or None, "land_sqmi": number(r["ALAND_SQMI"]), "latitude": number(r["INTPTLAT"]), "longitude": number(r["INTPTLONG"])}
    title = "2024 Gazetteer Files, core based statistical areas (ZIP with tab-delimited text)"
    metro = sum(1 for r in rows.values() if r["type"] == "metropolitan")
    return rule_entry(
        "us-census-gazetteer-2024-cbsas",
        "United States core based statistical areas, 2024 Gazetteer: name, metro or micro type, CSA, land area and coordinates",
        "geography",
        "US",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "five-digit CBSA code", "source_member": member, "rows": rows},
        vectors=membership_vectors(["10180", "35620"], "00000") + [column_vector("10180", "name", rows["10180"]["name"]), column_vector("10180", "type", "metropolitan")],
        evidence_items=[
            evidence(CENSUS, title, GAZ_CBSA_URL, f"{member}, row GEOID 10180", rows["10180"]["name"], "text", line_with(text, "\t10180\t"), LICENSE, raw),
            evidence(CENSUS, title, GAZ_CBSA_URL, f"{member}, row GEOID 35620", rows["35620"]["name"], "text", line_with(text, "\t35620\t"), LICENSE, raw),
        ],
        tests=lookup_tests(rows, [("10180", "cbsa_type"), ("35620", "land_sqmi")]),
        notes=(
            "The 2024 Gazetteer CBSA file lists every metropolitan and micropolitan statistical area with its combined statistical area "
            "code, land area in square miles and internal point. cbsa_type is the file's own code; type is read off the name suffix "
            f"(Metro Area or Micro Area), which gives {metro} metropolitan areas. " + LICENSE_NOTE + " " + vintage_assumption("2024-01-01", "2024")["rationale"]
        ),
        status=STATUS,
        tags=["gazetteer", "cbsa", "metropolitan-areas", "census", "coordinates"],
        use_cases=["address-generation", "market-sizing", "customer-segmentation"],
        assumed=[
            vintage_assumption("2024-01-01", "2024 Gazetteer"),
            {"parameter": "rows[*].type", "value": "metropolitan when NAME ends in Metro Area, micropolitan when it ends in Micro Area", "method": "derived", "rationale": "The file's NAME column carries the area type as a suffix; CBSA_TYPE is kept untouched beside it."},
        ],
    )


def gazetteer_zctas(raw: bytes) -> tuple[dict, dict]:
    member = "2024_Gaz_zcta_national.txt"
    text = zip_member(raw, member)
    records = csv_rows(text, "\t")
    low, high = ZCTA_PREFIX_RANGE
    subset = {
        r["GEOID"]: {"land_sqmi": number(r["ALAND_SQMI"]), "water_sqmi": number(r["AWATER_SQMI"]), "latitude": number(r["INTPTLAT"]), "longitude": number(r["INTPTLONG"])}
        for r in records
        if low <= r["GEOID"][:3] <= high
    }
    summary: dict[str, dict] = {}
    for r in records:
        row = summary.setdefault(r["GEOID"][:3], {"zcta_count": 0, "land_sqmi": 0.0, "water_sqmi": 0.0, "first": r["GEOID"], "last": r["GEOID"]})
        row["zcta_count"] += 1
        row["land_sqmi"] = round(row["land_sqmi"] + float(r["ALAND_SQMI"]), 3)
        row["water_sqmi"] = round(row["water_sqmi"] + float(r["AWATER_SQMI"]), 3)
        row["last"] = r["GEOID"]
    title = "2024 Gazetteer Files, ZIP Code Tabulation Areas (ZIP with tab-delimited text)"
    first_key = next(iter(subset))
    common_evidence = [
        evidence(CENSUS, title, GAZ_ZCTA_URL, f"{member}, row GEOID 00601, ALAND_SQMI", number(next(r["ALAND_SQMI"] for r in records if r["GEOID"] == "00601")), "decimal", line_with(text, "00601\t"), LICENSE, raw),
        evidence(CENSUS, title, GAZ_ZCTA_URL, f"{member}, row GEOID {first_key}, ALAND_SQMI", subset[first_key]["land_sqmi"], "decimal", line_with(text, first_key + "\t"), LICENSE, raw),
    ]
    detail = rule_entry(
        f"us-census-zcta-2024-gazetteer-prefixes-{low}-{high}",
        f"United States ZIP Code Tabulation Areas with three-digit prefixes {low} to {high}, 2024 Gazetteer: area and coordinates",
        "geography",
        "US",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "five-digit ZCTA", "prefix_range": [low, high], "source_member": member, "rows": subset},
        vectors=membership_vectors([first_key, "10001"], "00601") + [column_vector(first_key, "land_sqmi", subset[first_key]["land_sqmi"]), column_vector("10001", "latitude", subset["10001"]["latitude"])],
        evidence_items=common_evidence + [evidence(CENSUS, title, GAZ_ZCTA_URL, f"{member}, row GEOID 10001, INTPTLAT", subset["10001"]["latitude"], "decimal", line_with(text, "10001\t"), LICENSE, raw)],
        tests=lookup_tests(subset, [(first_key, "land_sqmi"), ("10001", "longitude")]),
        notes=(
            f"The national ZCTA Gazetteer holds {len(records)} ZIP Code Tabulation Areas; this entry keeps the well-defined subset whose "
            f"first three digits fall between {low} and {high} inclusive, with land and water area in square miles and the internal point. "
            "ZCTAs are the Census Bureau's generalised representation of USPS ZIP Code service areas, not the ZIP Codes themselves. "
            + LICENSE_NOTE + " " + vintage_assumption("2024-01-01", "2024")["rationale"]
        ),
        status=STATUS,
        tags=["gazetteer", "zcta", "zip-codes", "census", "coordinates"],
        use_cases=["address-generation", "logistics"],
        assumed=[vintage_assumption("2024-01-01", "2024 Gazetteer")],
    )
    prefix = rule_entry(
        "us-census-zcta-2024-gazetteer-prefix-summary",
        "United States ZIP Code Tabulation Areas, 2024 Gazetteer, summarised by three-digit prefix: count, land and water area",
        "geography",
        "US",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "three-digit ZCTA prefix", "source_member": member, "rows": summary},
        vectors=membership_vectors(["006", "100"], "000") + [column_vector("006", "first", "00601"), column_vector("100", "zcta_count", summary["100"]["zcta_count"])],
        evidence_items=common_evidence,
        tests=lookup_tests(summary, [("006", "first"), ("100", "zcta_count")]),
        notes=(
            "Every ZCTA in the 2024 Gazetteer grouped by its first three digits: how many ZCTAs share the prefix, their summed land and "
            "water area in square miles, and the first and last ZCTA in file order. The counts are the natural weights for drawing a "
            "ZIP prefix when generating addresses; the companion entry carries the individual ZCTAs for one prefix range. "
            + LICENSE_NOTE + " " + vintage_assumption("2024-01-01", "2024")["rationale"]
        ),
        status=STATUS,
        tags=["gazetteer", "zcta", "zip-codes", "census", "weights"],
        use_cases=["address-generation", "logistics", "market-sizing"],
        assumed=[
            vintage_assumption("2024-01-01", "2024 Gazetteer"),
            {"parameter": "rows[*]", "value": "count and sums of ALAND_SQMI and AWATER_SQMI over ZCTAs sharing the first three digits", "method": "derived", "rationale": "The Gazetteer lists individual ZCTAs; the per-prefix figures are counts and sums of its rows, rounded to three decimals."},
        ],
    )
    return detail, prefix


# ---------------------------------------------------------------- 2020 places ----------------------------------------------------------------


def places(raw: bytes) -> tuple[dict, dict]:
    text = raw.decode("utf-8")
    records = csv_rows(text, "|")
    state_rows = {
        r["STATEFP"] + r["PLACEFP"]: {"name": r["PLACENAME"], "type": r["TYPE"], "class": r["CLASSFP"], "funcstat": r["FUNCSTAT"], "counties": r["COUNTIES"]}
        for r in records
        if r["STATE"] == PLACE_STATE
    }
    by_state: dict[str, dict] = {}
    for r in records:
        row = by_state.setdefault(r["STATE"], {"fips": r["STATEFP"], "places": 0, "incorporated_places": 0, "census_designated_places": 0})
        row["places"] += 1
        if r["TYPE"] == "INCORPORATED PLACE":
            row["incorporated_places"] += 1
        elif r["TYPE"] == "CENSUS DESIGNATED PLACE":
            row["census_designated_places"] += 1
    types = Counter(r["TYPE"] for r in records)
    title = "2020 national place codes (national_place2020.txt)"
    la = next(key for key, row in state_rows.items() if row["name"] == "Los Angeles city")
    items = [
        evidence(CENSUS, title, PLACE_URL, f"row CA|06|{la[2:]}", "Los Angeles city", "text", line_with(text, f"CA|06|{la[2:]}|"), LICENSE, raw),
        evidence(CENSUS, title, PLACE_URL, "row AL|01|00124", "Abbeville city", "text", line_with(text, "AL|01|00124|"), LICENSE, raw),
    ]
    detail = rule_entry(
        f"us-census-places-2020-{PLACE_STATE.lower()}",
        "California places, 2020 vintage: seven-digit FIPS code, name, incorporated or census designated type, class and counties",
        "geography",
        "US",
        valid_from="2020-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "seven-digit state plus place FIPS code", "state": PLACE_STATE, "rows": state_rows},
        vectors=membership_vectors([la], "0100124") + [column_vector(la, "name", "Los Angeles city"), column_vector(la, "type", state_rows[la]["type"])],
        evidence_items=items,
        tests=lookup_tests(state_rows, [(la, "name"), (la, "counties")]),
        notes=(
            f"The Census Bureau's 2020 national place file holds {len(records)} incorporated places and census designated places; this "
            f"entry keeps the rows for {PLACE_STATE}, keyed by the seven-digit state-plus-place FIPS code, with the name (which includes "
            "the legal descriptor such as city, town or CDP), type, FIPS class code, functional status and the counties the place lies in. "
            + LICENSE_NOTE + " " + vintage_assumption("2020-01-01", "2020")["rationale"]
        ),
        status=STATUS,
        tags=["fips", "places", "cities", "census", "code-list"],
        use_cases=["address-generation", "customer-segmentation"],
        assumed=[vintage_assumption("2020-01-01", "codes2020")],
    )
    by_state = dict(sorted(by_state.items()))
    summary = rule_entry(
        "us-census-places-2020-by-state",
        "Number of 2020-vintage places per state, split into incorporated places and census designated places",
        "geography",
        "US",
        valid_from="2020-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "USPS state abbreviation", "place_types": dict(sorted(types.items())), "rows": by_state},
        vectors=membership_vectors(["CA", "AL"], "ZZ") + [column_vector("CA", "places", by_state["CA"]["places"]), column_vector("AL", "fips", "01")],
        evidence_items=items,
        tests=lookup_tests(by_state, [("CA", "places"), ("AL", "incorporated_places")]),
        notes=(
            "Counts of rows in the Census Bureau's 2020 national place file per state, with the split between INCORPORATED PLACE and "
            "CENSUS DESIGNATED PLACE rows; place_types records every TYPE value in the file with its national count. The counts give a "
            "generator the weight of each state when choosing a place at random. " + LICENSE_NOTE + " " + vintage_assumption("2020-01-01", "2020")["rationale"]
        ),
        status=STATUS,
        tags=["places", "census", "weights", "by-state"],
        use_cases=["address-generation", "market-sizing"],
        assumed=[
            vintage_assumption("2020-01-01", "codes2020"),
            {"parameter": "rows[*] and place_types", "value": "row counts of national_place2020.txt grouped by STATE and TYPE", "method": "derived", "rationale": "The file lists individual places; the per-state figures are counts of its rows."},
        ],
    )
    return detail, summary


# ---------------------------------------------------------------- CBSA delineations ----------------------------------------------------------------


def cbsa_delineations(raw: bytes) -> dict:
    rows = sheet_rows(raw, "List 1")
    header_index = next(i for i, r in enumerate(rows) if r[0] == "CBSA Code")
    banner = str(rows[header_index - 1][0])
    areas: dict[str, dict] = {}
    for r in rows[header_index + 1 :]:
        if not r[0] or not str(r[0]).strip().isdigit():
            continue
        code = str(r[0]).strip()
        area = areas.setdefault(code, {"title": r[3], "category": r[4], "csa_code": str(r[2]).strip() if r[2] else None, "csa_title": r[6] or None, "states": [], "counties": [], "central_counties": 0, "divisions": {}})
        fips = f"{str(r[9]).zfill(2)}{str(r[10]).zfill(3)}"
        area["counties"].append(fips)
        if r[11] == "Central":
            area["central_counties"] += 1
        if r[8] not in area["states"]:
            area["states"].append(r[8])
        if r[1]:
            area["divisions"][str(r[1]).strip()] = r[5]
    title = "Core based statistical areas, metropolitan divisions and combined statistical areas, July 2023 delineation file, List 1 (XLSX)"
    return rule_entry(
        "us-cbsa-delineations-2023",
        "United States core based statistical areas, July 2023 delineations: title, category, CSA, member counties and divisions",
        "geography",
        "US",
        valid_from="2023-07-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "five-digit CBSA code", "rows": areas},
        vectors=membership_vectors(["10100", "35620"], "00000") + [column_vector("10100", "title", "Aberdeen, SD"), column_vector("10100", "counties", areas["10100"]["counties"])],
        evidence_items=[
            evidence(CENSUS, title, CBSA_LIST_URL, "sheet List 1, first data row, CBSA Title", "Aberdeen, SD", "text", "Aberdeen, SD", LICENSE, raw),
            evidence(CENSUS, title, CBSA_LIST_URL, "sheet List 1, row for CBSA 35620, CBSA Title", areas["35620"]["title"], "text", areas["35620"]["title"], LICENSE, raw),
            evidence(CENSUS, title, CBSA_LIST_URL, "sheet List 1, banner row", banner, "text", banner, LICENSE, raw, role="supporting"),
        ],
        tests=lookup_tests(areas, [("10100", "category"), ("35620", "csa_code")]),
        notes=(
            "The delineation file lists one row per county in each core based statistical area; this entry folds those rows into one "
            "record per CBSA with the title, the metropolitan or micropolitan category, the combined statistical area it belongs to, the "
            "member counties as five-digit FIPS codes, how many of them are central, the states they lie in and any metropolitan "
            "divisions. The workbook's banner names the July 2023 vintage, which sets valid_from. " + LICENSE_NOTE
        ),
        status=STATUS,
        tags=["cbsa", "metropolitan-areas", "counties", "census", "omb"],
        use_cases=["address-generation", "market-sizing", "customer-segmentation"],
        assumed=[
            vintage_assumption("2023-07-01", "JULY 2023, as the workbook banner states"),
            {"parameter": "rows[*].counties, states, central_counties, divisions", "value": "aggregated from the county rows of List 1", "method": "derived", "rationale": "The source is one row per county; the per-CBSA lists and counts are those rows regrouped by CBSA code."},
        ],
    )


# ---------------------------------------------------------------- NAICS 2022 ----------------------------------------------------------------


def naics(raw: bytes) -> dict:
    levels = {"sector": {}, "subsector": {}, "industry_group": {}, "naics_industry": {}, "national_industry": {}}
    for r in sheet_rows(raw):
        if r[0] is None or not isinstance(r[0], (int, float)):
            continue
        code, title = str(r[1]).strip(), str(r[2]).strip()
        digits = 2 if "-" in code else len(code)
        name = {2: "sector", 3: "subsector", 4: "industry_group", 5: "naics_industry", 6: "national_industry"}[digits]
        levels[name][code] = title
    return rule_entry(
        "us-naics-2022-codes",
        "NAICS 2022 code list: sectors, subsectors, industry groups, NAICS industries and national industries with titles",
        "business",
        "US",
        valid_from="2022-01-01",
        implementation="almanac.rules.enumeration",
        parameters={"sets": levels},
        vectors=set_vectors(levels, "999999") + [{"input": {"set": "sector", "value": "31-33"}, "expected": True, "origin": "source"}, {"input": {"set": "national_industry", "value": "111110"}, "expected": True, "origin": "source"}],
        evidence_items=[
            evidence(CENSUS, "2022 NAICS 2-6 digit codes (XLSX)", NAICS_URL, "row with code 111, 2022 NAICS US Title", "Crop Production", "text", "Crop Production", LICENSE, raw),
            evidence(CENSUS, "2022 NAICS 2-6 digit codes (XLSX)", NAICS_URL, "row with code 111110, 2022 NAICS US Title", levels["national_industry"]["111110"], "text", levels["national_industry"]["111110"], LICENSE, raw),
            evidence(CENSUS, "2022 NAICS 2-6 digit codes (XLSX)", NAICS_URL, "row with code 31-33, 2022 NAICS US Title", levels["sector"]["31-33"], "text", levels["sector"]["31-33"], LICENSE, raw),
        ],
        tests=set_tests(levels),
        notes=(
            "The North American Industry Classification System 2022 as the Census Bureau's two-to-six-digit code workbook lists it, "
            "sorted into one enumeration set per level by code length: two-digit sectors (three of which are published as ranges, "
            "31-33, 44-45 and 48-49), three-digit subsectors, four-digit industry groups, five-digit NAICS industries and six-digit "
            "national industries. Titles ending in T in the workbook keep that marker. Snippets are matched against the workbook's "
            "sharedStrings member. " + LICENSE_NOTE + " " + vintage_assumption("2022-01-01", "2022")["rationale"]
        ),
        status=STATUS,
        tags=["naics", "industry-codes", "census", "code-list", "classification"],
        use_cases=["company-generation", "kyb-onboarding", "customer-segmentation"],
        assumed=[vintage_assumption("2022-01-01", "NAICS 2022")],
    )


def main() -> None:
    write(states(stable(STATE_URL)))
    write(counties(stable(COUNTY_URL)))
    write(gazetteer_counties(stable(GAZ_COUNTIES_URL)))
    write(gazetteer_cbsas(stable(GAZ_CBSA_URL)))
    for entry in gazetteer_zctas(stable(GAZ_ZCTA_URL)):
        write(entry)
    for entry in places(stable(PLACE_URL)):
        write(entry)
    write(cbsa_delineations(stable(CBSA_LIST_URL)))
    write(naics(stable(NAICS_URL)))


if __name__ == "__main__":
    main()

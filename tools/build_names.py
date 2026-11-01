"""Regenerate the personal-name frequency entries: first names and surnames from national statistical
offices (US Census Bureau, ONS, NRS Scotland, INSEE, CSO Ireland, Statbel, INE and Statistics Norway).

Every entry carries the published counts beside the derived shares so a generator can draw realistic
names by sex, region or birth cohort and a reader can re-derive the weights. Run from the repository root:

    uv run python tools/build_names.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

SHARE_DIGITS = 8
TAGS = ["names", "people", "demographics"]
USE_CASES = ["synthetic-customers", "kyc-onboarding", "hr-demo", "healthcare-demo", "person-generation"]

CENSUS_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
CENSUS_PAPER_URL = "https://www2.census.gov/topics/genealogy/2010surnames/surnames.pdf"
ONS_BASE = "https://www.ons.gov.uk/file?uri=/peoplepopulationandcommunity/birthsdeathsandmarriages/livebirths/datasets"
ONS_BOYS_URL = f"{ONS_BASE}/babynamesenglandandwalesbabynamesstatisticsboys/2024/boysnames2024.xlsx"
ONS_GIRLS_URL = f"{ONS_BASE}/babynamesenglandandwalesbabynamesstatisticsgirls/2024/girlsnames2024.xlsx"
ONS_LICENSE_URL = "https://api.beta.ons.gov.uk/v1/datasets/mid-year-pop-est"
NRS_URL = "https://www.nrscotland.gov.uk/media/q1epi2ni/full-list-2024.xlsx"
INSEE_URL = "https://www.insee.fr/fr/statistiques/fichier/8595130/prenoms-2025-nat_csv.zip"
INSEE_DOC_URL = "https://www.insee.fr/fr/statistiques/8595130"
INSEE_LICENSE_URL = "https://www.insee.fr/fr/information/2008466"
CSO_BOYS_URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/VSA50/CSV/1.0/en"
CSO_GIRLS_URL = "https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/VSA60/CSV/1.0/en"
CSO_LICENSE_URL = "https://data.gov.ie/api/3/action/package_show?id=vsa50-boys-names-in-ireland-with-3-or-more-occurrences"
STATBEL_BASE = "https://statbel.fgov.be/sites/default/files/files/documents/bevolking/5.10%20Namen%20en%20voornamen"
STATBEL_BOYS_URL = f"{STATBEL_BASE}/5.10.%203%20Voornamen%20meisjes%20en%20jongens/Firstnames_Boys_1995-.xlsx"
STATBEL_GIRLS_URL = f"{STATBEL_BASE}/5.10.%203%20Voornamen%20meisjes%20en%20jongens/Firstnames_Girls_1995-.xlsx"
STATBEL_POP_URL = f"{STATBEL_BASE}/5.10.2%20Voornamen%20van%20vrouwen%20en%20mannen/First_names_Pop_STATBEL_2026_en.xlsx"
STATBEL_SURNAMES_URL = f"{STATBEL_BASE}/5.10.1%20Familienamen/Family_names_2026.xlsx"
STATBEL_LICENSE_URL = "https://statbel.fgov.be/en/open-data"
INE_URL = "https://www.ine.es/daco/daco42/nombyapel/nombres_por_edad_media.xlsx"
INE_LEGAL_URL = "https://www.ine.es/ss/Satellite?L=es_ES&c=Page&cid=1254735849170&p=1254735849170&pagename=Ayuda%2FINELayout"
SSB_API = "https://data.ssb.no/api/pxwebapi/v2/tables"
SSB_GIRLS_URL = f"{SSB_API}/10467/data?lang=en&outputFormat=json-stat2&codelist[Fornavn]=vs_NavnJenter02&valueCodes[Fornavn]=*&valueCodes[ContentsCode]=*&valueCodes[Tid]=2025"
SSB_BOYS_URL = f"{SSB_API}/10467/data?lang=en&outputFormat=json-stat2&codelist[Fornavn]=vs_NavnGutter02&valueCodes[Fornavn]=*&valueCodes[ContentsCode]=*&valueCodes[Tid]=2025"
SSB_SURNAMES_URL = f"{SSB_API}/12891/data?lang=en&outputFormat=json-stat2&valueCodes[Etternavn]=*&valueCodes[ContentsCode]=*&valueCodes[Tid]=2025"
SSB_LICENSE_URL = "https://www.ssb.no/en/diverse/lisens"
SSB_CONFIG_URL = f"{SSB_API[: -len('/tables')]}/config?lang=en"

OGL = "OGL-UK-3.0"
CC_BY = "CC-BY-4.0"
ETALAB = "etalab-2.0"
UNSTATED = "unstated"


# --- spreadsheet reading -------------------------------------------------------------------------

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


def sheet_rows(raw: bytes, sheet: str) -> list[dict[str, str]]:
    """Return the rows of one worksheet of an .xlsx file as column-letter keyed dicts of cell text.

    Only the workbook, its relationships, the shared-string table and the requested sheet are read,
    so the builder does not depend on a spreadsheet library.
    """
    archive = zipfile.ZipFile(io.BytesIO(raw))
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    targets = {rel.get("Id"): rel.get("Target") for rel in ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
    target = next(targets[s.get(_REL_ID)] for s in workbook.find("m:sheets", _NS) if s.get("name") == sheet)
    member = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
    strings: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            strings.append("".join(t.text or "" for t in item.iter(f"{{{_NS['m']}}}t")))
    rows = []
    for row in ElementTree.fromstring(archive.read(member)).iter(f"{{{_NS['m']}}}row"):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", _NS):
            value = cell.find("m:v", _NS)
            if value is None:
                inline = cell.find("m:is", _NS)
                text = "".join(t.text or "" for t in inline.iter(f"{{{_NS['m']}}}t")) if inline is not None else ""
            elif cell.get("t") == "s":
                text = strings[int(value.text)]
            else:
                text = value.text or ""
            cells[_CELL_REF.match(cell.get("r")).group(1)] = text.strip()
        rows.append(cells)
    return rows


def ranked_block(rows: Iterable[dict[str, str]], name_col: str, count_col: str, top: int) -> dict[str, int]:
    """Top ``top`` (name, count) pairs from a ranked table, largest count first, blank cells skipped."""
    pairs = []
    for row in rows:
        name, count = row.get(name_col, ""), row.get(count_col, "")
        if name and count.isdigit():
            pairs.append((name, int(count)))
    pairs.sort(key=lambda pair: (-pair[1], pair[0]))
    return dict(pairs[:top])


# --- distribution helpers -------------------------------------------------------------------------


def categorical(counts: dict[str, int], **extra) -> dict:
    """A categorical distribution with shares derived from the counts, both kept side by side."""
    total = sum(counts.values())
    shares = {name: round(count / total, SHARE_DIGITS) for name, count in counts.items()}
    return {"family": "categorical", "parameters": {"shares": shares, "counts": counts, "total": total, **extra}}


def top_of(distribution: dict) -> tuple[str, float]:
    shares = distribution["parameters"]["shares"]
    name = next(iter(shares))
    return name, shares[name]


def share_test(category: str, expected: float, given: str | None = None) -> dict:
    args = f'"{given}","{category}"' if given is not None else f'"{category}"'
    return {"statistic": f"share[{args}]", "expected": expected, "tolerance": 0.005}


def sum_test(given: str | None = None) -> dict:
    statistic = f'sum_of_shares["{given}"]' if given is not None else "sum_of_shares"
    return {"statistic": statistic, "expected": 1, "tolerance": 0.0001}


def shares_assumption(scope: str) -> dict:
    return {
        "parameter": "shares",
        "value": "count / sum of counts over the listed names",
        "method": "derived",
        "rationale": f"The source publishes counts; the shares are each count over the total of the {scope}, so they sum to one and a generator can draw from them directly.",
    }


def entry(entry_id: str, title: str, region: str, period: tuple[str, str], spec: dict, evidence_items: list[dict], assumed: list[dict], tests: list[dict], notes: str, extra_tags: list[str], status: str = "verified") -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": spec["kind"],
        "domain": "demographics",
        "region": region,
        "status": status,
        "tier": "A",
        "observed_period": {"start": period[0], "end": period[1]},
        "tags": TAGS + extra_tags,
        "use_cases": USE_CASES,
        "spec": {k: v for k, v in spec.items() if k != "kind"},
        "evidence": evidence_items,
        "assumed": assumed,
        "tests": tests,
        "notes": notes,
    }


def marginal(variable: str, distribution: dict) -> dict:
    return {"kind": "marginal", "variable": variable, "unit": "ratio", "distribution": distribution}


def conditional(variable: str, given: str, distributions: dict[str, dict]) -> dict:
    return {"kind": "conditional", "variable": variable, "unit": "ratio", "given": given, "distributions": distributions}


def conditional_tests(distributions: dict[str, dict]) -> list[dict]:
    tests = []
    for given, distribution in distributions.items():
        name, share = top_of(distribution)
        tests.append(share_test(name, share, given))
        tests.append(sum_test(given))
    return tests


# --- United States: Census Bureau surnames -------------------------------------------------------

CENSUS_ETHNICITY = {
    "pctwhite": "white",
    "pctblack": "black",
    "pctapi": "asian_pacific_islander",
    "pctaian": "american_indian_alaska_native",
    "pct2prace": "two_or_more_races",
    "pcthispanic": "hispanic",
}
CENSUS_NOTE = (
    "The Census Bureau's 2010 surname file lists every surname reported by 100 or more people in the 2010 Census with "
    "its count, frequency per 100,000 people and the percentage of holders in each race and Hispanic-origin group. "
    "census.gov carries no licence statement at a byte-stable URL, so the licence is recorded as unstated pending review."
)


def census_rows(raw: bytes) -> list[dict[str, str]]:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.DictReader(io.StringIO(archive.read("Names_2010Census.csv").decode("utf-8"))))


def us_surnames(raw: bytes, paper: bytes, top: int) -> dict:
    rows = census_rows(raw)
    population = sum(int(r["count"]) for r in rows)
    ranked = sorted((r for r in rows if r["name"] != "ALL OTHER NAMES"), key=lambda r: int(r["rank"]))[:top]
    counts = {r["name"]: int(r["count"]) for r in ranked}
    per_100k = {r["name"]: float(r["prop100k"]) for r in ranked}
    distribution = categorical(counts, per_100k=per_100k, population_total=population, coverage=round(sum(counts.values()) / population, SHARE_DIGITS))
    first, last = ranked[0], ranked[-1]
    other = next(r for r in rows if r["name"] == "ALL OTHER NAMES")
    return entry(
        f"us-census-2010-surnames-top-{top}",
        f"United States surnames, top {top} by frequency, Census 2010 (Census Bureau)",
        "US",
        ("2010-01-01", "2010-12-31"),
        marginal("surname", distribution),
        [
            evidence("United States Census Bureau", "Frequently Occurring Surnames from the 2010 Census (Names_2010Census.csv)", CENSUS_URL, f"Names_2010Census.csv, row name={first['name']}, count", int(first["count"]), "count", f"{first['name']},{first['rank']},{first['count']}", UNSTATED, raw),
            evidence("United States Census Bureau", "Frequently Occurring Surnames from the 2010 Census (Names_2010Census.csv)", CENSUS_URL, f"Names_2010Census.csv, row name={last['name']}, count", int(last["count"]), "count", f"{last['name']},{last['rank']},{last['count']}", UNSTATED, raw),
            evidence("United States Census Bureau", "Frequently Occurring Surnames from the 2010 Census (Names_2010Census.csv)", CENSUS_URL, "Names_2010Census.csv, row name=ALL OTHER NAMES, count", int(other["count"]), "count", f"ALL OTHER NAMES,0,{other['count']}", UNSTATED, raw),
            evidence("United States Census Bureau", "Demographic Aspects of Surnames from Census 2010 (methodology paper)", CENSUS_PAPER_URL, "section on the public file", "all with a frequency of 100 or more", "text", "The publicly released table of surnames includes all with a frequency of 100 or more.", UNSTATED, paper, role="supporting"),
        ],
        [
            shares_assumption(f"top {top} surnames"),
            {"parameter": "coverage", "value": "sum of the listed counts / population_total", "method": "derived", "rationale": "population_total is the sum of every count in the file including the ALL OTHER NAMES row, so coverage is the share of the 2010 Census population carrying one of the listed surnames."},
        ],
        [share_test(first["name"], distribution["parameters"]["shares"][first["name"]]), share_test(last["name"], distribution["parameters"]["shares"][last["name"]]), sum_test()],
        f"The {top} most frequent surnames in the 2010 Census with their published counts and frequency per 100,000 people "
        f"(per_100k), shares renormalised within the list, and the share of the whole population the list covers. {CENSUS_NOTE}",
        ["surnames", "census", "us-census-bureau"],
        status="license-review",
    )


def us_surname_ethnicity(raw: bytes, paper: bytes, top: int) -> dict:
    rows = sorted((r for r in census_rows(raw) if r["name"] != "ALL OTHER NAMES"), key=lambda r: int(r["rank"]))[:top]
    distributions = {}
    for r in rows:
        if any(r[column] == "(S)" for column in CENSUS_ETHNICITY):
            raise ValueError(f"suppressed ethnicity share for {r['name']}")
        percent = {label: float(r[column]) for column, label in CENSUS_ETHNICITY.items()}
        shares = {label: round(value / 100, 4) for label, value in percent.items()}
        distributions[r["name"]] = {"family": "categorical", "parameters": {"shares": shares, "published_percent": percent, "count": int(r["count"]), "rank": int(r["rank"])}}
    first = rows[0]
    tests = []
    for r in (rows[0], rows[1], rows[-1]):
        shares = distributions[r["name"]]["parameters"]["shares"]
        largest = max(shares, key=shares.get)
        tests.append({"statistic": f'share["{r["name"]}","{largest}"]', "expected": shares[largest], "tolerance": 0.005})
        tests.append({"statistic": f'sum_of_shares["{r["name"]}"]', "expected": 1, "tolerance": 0.005})
    return entry(
        f"us-census-2010-surname-ethnicity-top-{top}",
        f"Race and Hispanic origin given surname, top {top} United States surnames, Census 2010 (Census Bureau)",
        "US",
        ("2010-01-01", "2010-12-31"),
        conditional("race_ethnicity", "surname", distributions),
        [
            evidence("United States Census Bureau", "Frequently Occurring Surnames from the 2010 Census (Names_2010Census.csv)", CENSUS_URL, f"Names_2010Census.csv, row name={first['name']}, pctwhite", float(first["pctwhite"]), "percent", f"{first['name']},{first['rank']},{first['count']},{first['prop100k']},{first['cum_prop100k']},{first['pctwhite']}", UNSTATED, raw),
            evidence("United States Census Bureau", "Frequently Occurring Surnames from the 2010 Census (Names_2010Census.csv)", CENSUS_URL, "Names_2010Census.csv, header row", "pctwhite", "text", "name,rank,count,prop100k,cum_prop100k,pctwhite,pctblack,pctapi,pctaian,pct2prace,pcthispanic", UNSTATED, raw),
            evidence("United States Census Bureau", "Demographic Aspects of Surnames from Census 2010 (methodology paper)", CENSUS_PAPER_URL, "section on the public file", "all with a frequency of 100 or more", "text", "The publicly released table of surnames includes all with a frequency of 100 or more.", UNSTATED, paper, role="supporting"),
        ],
        [{"parameter": "shares", "value": "published percentage / 100", "method": "derived", "rationale": "The file publishes the percentage of each surname's holders by race and Hispanic origin to two decimals; the shares are those percentages divided by 100 and sum to one within rounding."}],
        tests,
        f"For each of the {top} most frequent 2010 Census surnames, the published percentage of holders who are non-Hispanic "
        "white, non-Hispanic black, non-Hispanic Asian and Pacific Islander, non-Hispanic American Indian and Alaska Native, "
        f"non-Hispanic two or more races, and Hispanic, with the surname's count and rank. {CENSUS_NOTE}",
        ["surnames", "ethnicity", "census", "us-census-bureau"],
        status="license-review",
    )


# --- England and Wales: ONS baby names --------------------------------------------------------------

ONS_NOTE = (
    "Baby name statistics are compiled by the Office for National Statistics from first names recorded at birth "
    "registration in England and Wales for live births in the calendar year, counting each exact spelling separately. "
    "ONS publishes its datasets under the Open Government Licence v3.0."
)


def ons_evidence(url: str, raw: bytes, sex: str, license_raw: bytes) -> list[dict]:
    top = sheet_rows(raw, "Table_1")[5]
    cover = sheet_rows(raw, "Cover_sheet")
    released = next(row["A"] for row in cover if row.get("A", "").startswith("Released:"))
    return [
        evidence("Office for National Statistics", f"Baby names for {sex} in England and Wales: 2024 (XLSX), Table_1", url, "Table_1, row 6 (rank 1): Name, Count", int(top["C"]), "count", top["B"], OGL, raw),
        evidence("Office for National Statistics", f"Baby names for {sex} in England and Wales: 2024 (XLSX), cover sheet", url, "Cover_sheet, cell A4", released, "text", released, OGL, raw),
        evidence("Office for National Statistics", "ONS dataset metadata, Population Estimates (licence statement)", ONS_LICENSE_URL, "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', OGL, license_raw, role="supporting"),
    ]


def ons_top_names(url: str, raw: bytes, sex: str, license_raw: bytes, top: int) -> dict:
    rows = sheet_rows(raw, "Table_6")[5:]
    full_list = ranked_block(rows, "B", "C", len(rows))
    counts = dict(list(full_list.items())[:top])
    full_total = sum(full_list.values())
    distribution = categorical(counts, full_list_total=full_total, coverage=round(sum(counts.values()) / full_total, SHARE_DIGITS))
    first, last = next(iter(counts)), list(counts)[-1]
    label = {"boys": "male", "girls": "female"}[sex]
    return entry(
        f"gb-baby-names-{sex}-2024-top-{top}",
        f"England and Wales baby names for {sex}, top {top} of 2024 births (ONS)",
        "GB",
        ("2024-01-01", "2024-12-31"),
        marginal(f"{label}_first_name", distribution),
        ons_evidence(url, raw, sex, license_raw),
        [
            shares_assumption(f"top {top} names"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": "full_list_total is the sum of counts over every name in Table_6 (names with three or more occurrences), so coverage is the share of those births given one of the listed names."},
        ],
        [share_test(first, distribution["parameters"]["shares"][first]), share_test(last, distribution["parameters"]["shares"][last]), sum_test()],
        f"The {top} most common first names given to {sex} born in England and Wales in 2024, from Table_6 (the full list of "
        f"names with three or more occurrences) of the ONS baby names dataset, with published counts and shares renormalised within the list. {ONS_NOTE}",
        ["first-names", "baby-names", "ons", label],
    )


def ons_by_region(url: str, raw: bytes, sex: str, license_raw: bytes) -> dict:
    rows = sheet_rows(raw, "Table_4")[5:]
    regions: dict[str, dict] = {}
    for row in rows:
        region = regions.setdefault(row["B"], {"code": row["A"], "counts": {}})
        if row["C"] == "All ranks":
            region["all_names_total"] = int(row["E"])
        elif row["E"].isdigit():
            region["counts"][row["D"]] = int(row["E"])
    distributions = {}
    for name, region in regions.items():
        counts = dict(sorted(region["counts"].items(), key=lambda kv: (-kv[1], kv[0])))
        distributions[name] = categorical(counts, region_code=region["code"], all_names_total=region["all_names_total"], coverage=round(sum(counts.values()) / region["all_names_total"], SHARE_DIGITS))
    label = {"boys": "male", "girls": "female"}[sex]
    first_region = rows[0]["B"]
    first_name = rows[1]
    return entry(
        f"gb-baby-names-{sex}-by-region-2024-top-10",
        f"England and Wales baby names for {sex} given region of usual residence, top 10 of 2024 births (ONS)",
        "GB",
        ("2024-01-01", "2024-12-31"),
        conditional(f"{label}_first_name", "region", distributions),
        [
            evidence("Office for National Statistics", f"Baby names for {sex} in England and Wales: 2024 (XLSX), Table_4", url, f"Table_4, row 7 ({first_region}, rank 1): Name, Count", int(first_name["E"]), "count", first_name["D"], OGL, raw),
            evidence("Office for National Statistics", f"Baby names for {sex} in England and Wales: 2024 (XLSX), Table_4", url, f"Table_4, row 6 ({first_region}, All ranks): Count", regions[first_region]["all_names_total"], "count", rows[0]["A"], OGL, raw),
        ]
        + ons_evidence(url, raw, sex, license_raw)[1:],
        [
            shares_assumption("ten names listed for the region"),
            {"parameter": "coverage", "value": "sum of the ten counts / all_names_total", "method": "derived", "rationale": "Table_4 gives the count of all named births in the region on its 'All ranks' row; coverage is the share of those births given one of the ten listed names."},
        ],
        conditional_tests(distributions),
        f"The ten most common first names given to {sex} born in 2024 in each English region and in Wales, by the mother's usual "
        f"residence, from Table_4 of the ONS baby names dataset. Keys are the ONS region names; region_code holds the "
        f"ONS geography code and all_names_total the region's count of named births. {ONS_NOTE}",
        ["first-names", "baby-names", "ons", "by-region", label],
    )


# --- Scotland: NRS baby names -------------------------------------------------------------------------


def nrs_by_sex(raw: bytes, top: int) -> dict:
    distributions = {}
    for sheet, label in (("Boys", "male"), ("Girls", "female")):
        rows = sheet_rows(raw, sheet)[4:]
        full_list = ranked_block(rows, "B", "C", len(rows))
        counts = dict(list(full_list.items())[:top])
        full_total = sum(full_list.values())
        distributions[label] = categorical(counts, full_list_total=full_total, coverage=round(sum(counts.values()) / full_total, SHARE_DIGITS))
    boys_top = sheet_rows(raw, "Boys")[4]
    girls_top = sheet_rows(raw, "Girls")[4]
    cover = [row.get("A", "") for row in sheet_rows(raw, "Cover")]
    period = cover[cover.index("Time period") + 1]
    return entry(
        f"gb-scotland-baby-names-2024-top-{top}-by-sex",
        f"Scotland baby names given sex, top {top} of 2024 births (National Records of Scotland)",
        "GB",
        (f"{period}-01-01", f"{period}-12-31"),
        conditional("first_name", "sex", distributions),
        [
            evidence("National Records of Scotland", "Babies' first names 2024, full list (XLSX), sheet Boys", NRS_URL, "Boys, row 5 (rank 1): Name, Number", int(boys_top["C"]), "count", boys_top["B"], OGL, raw),
            evidence("National Records of Scotland", "Babies' first names 2024, full list (XLSX), sheet Girls", NRS_URL, "Girls, row 5 (rank 1): Name, Number", int(girls_top["C"]), "count", girls_top["B"], OGL, raw),
            evidence("National Records of Scotland", "Babies' first names 2024, full list (XLSX), cover sheet", NRS_URL, "Cover, cell A8 (Time period)", period, "text", "Time period", OGL, raw),
            evidence("National Records of Scotland", "Babies' first names 2024, full list (XLSX), cover sheet", NRS_URL, "Cover, cell A23 (Copyright and reproduction)", "under the terms of the Open Government Licence", "text", "under the terms of the Open Government Licence", OGL, raw, role="supporting"),
        ],
        [
            shares_assumption(f"top {top} names of that sex"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": "full_list_total is the sum of counts over every name on the sheet (names with three or more babies), so coverage is the share of those births given one of the listed names."},
        ],
        conditional_tests(distributions),
        f"The {top} most common first names registered for boys and for girls born in Scotland in {period}, from the National "
        "Records of Scotland full list of baby names, with published counts and shares renormalised within each list. Names with "
        "a count of two or fewer are suppressed by NRS. The spreadsheet states that its content is Crown copyright and may be re-used "
        f"under the terms of the Open Government Licence; the licence line is cited as supporting evidence. Licence identifier {OGL} "
        "assumes the current (third) version linked from the sheet.",
        ["first-names", "baby-names", "nrs", "scotland", "by-sex"],
    )


# --- France: INSEE fichier des prénoms -------------------------------------------------------------

INSEE_NOTE = (
    "The INSEE 'Fichier des prénoms' (2025 edition) gives, for each first name, sex and year of birth, the number of births "
    "registered in France; its documentation page states that sexe 1 is masculin and 2 féminin. INSEE publishes under "
    "the Licence Ouverte / Open Licence version 2.0 (Etalab), recorded with the identifier etalab-2.0 pending licence review."
)
INSEE_SEX = {"1": "male", "2": "female"}


def insee_rows(raw: bytes) -> list[dict[str, str]]:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    text = archive.read("prenoms-2025-nat.csv").decode("utf-8")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def insee_counts(rows: list[dict[str, str]], sex: str, year: str, top: int) -> dict[str, int]:
    pairs = sorted(((r["prenom"], int(r["valeur"])) for r in rows if r["sexe"] == sex and r["periode"] == year), key=lambda p: (-p[1], p[0]))
    return dict(pairs[:top])


def insee_evidence(raw: bytes, rows: list[dict[str, str]], doc_raw: bytes, license_raw: bytes, sex: str, year: str) -> list[dict]:
    first = next(r for r in rows if r["sexe"] == sex and r["periode"] == year and r["rang"] == "1")
    line = ";".join(first[k] for k in ("sexe", "prenom", "periode", "valeur", "rang"))
    return [
        evidence("Institut national de la statistique et des études économiques", "Fichier des prénoms, édition 2025, fichier national (prenoms-2025-nat.csv)", INSEE_URL, f"prenoms-2025-nat.csv, row sexe={sex} prenom={first['prenom']} periode={year}, valeur", int(first["valeur"]), "count", line, ETALAB, raw),
        evidence("Institut national de la statistique et des études économiques", "Fichier des prénoms, édition 2025, fichier national (prenoms-2025-nat.csv)", INSEE_URL, "prenoms-2025-nat.csv, header row", "sexe;prenom;periode;valeur;rang", "text", "sexe;prenom;periode;valeur;rang", ETALAB, raw),
        evidence("Institut national de la statistique et des études économiques", "Fichier des prénoms, documentation page", INSEE_DOC_URL, "Dictionnaire des variables, sexe", "1 : masculin", "text", "1 : masculin", ETALAB, doc_raw, role="supporting"),
        evidence("Institut national de la statistique et des études économiques", "Mentions légales et crédits (licence statement)", INSEE_LICENSE_URL, "Licence", "Licence Ouverte / Open Licence version 2.0 (Etalab)", "text", "sous la Licence Ouverte / Open Licence version 2.0 (Etalab).", ETALAB, license_raw, role="supporting"),
    ]


def insee_by_sex(raw: bytes, doc_raw: bytes, license_raw: bytes, year: str, top: int) -> dict:
    rows = insee_rows(raw)
    distributions = {}
    for code, label in INSEE_SEX.items():
        pairs = insee_counts(rows, code, year, len(rows))
        counts = dict(list(pairs.items())[:top])
        total = sum(pairs.values())
        distributions[label] = categorical(counts, full_list_total=total, coverage=round(sum(counts.values()) / total, SHARE_DIGITS))
    return entry(
        f"fr-first-names-{year}-top-{top}-by-sex",
        f"France first names given sex, top {top} of {year} births (INSEE fichier des prénoms)",
        "FR",
        (f"{year}-01-01", f"{year}-12-31"),
        conditional("first_name", "sex", distributions),
        insee_evidence(raw, rows, doc_raw, license_raw, "1", year)[:1] + insee_evidence(raw, rows, doc_raw, license_raw, "2", year),
        [
            shares_assumption(f"top {top} names of that sex"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": f"full_list_total is the sum of valeur over every name of that sex for periode {year} in the national file, so coverage is the share of those births given one of the listed names."},
        ],
        conditional_tests(distributions),
        f"The {top} most given first names for boys and for girls born in France in {year}, from the national file of the INSEE "
        f"fichier des prénoms, with published counts and shares renormalised within each list. Names are in the upper-case, "
        f"accented form INSEE publishes. {INSEE_NOTE}",
        ["first-names", "baby-names", "insee", "by-sex"],
        status="license-review",
    )


def insee_by_cohort(raw: bytes, doc_raw: bytes, license_raw: bytes, years: list[str], top: int) -> dict:
    rows = insee_rows(raw)
    distributions = {}
    for year in years:
        for code, label in INSEE_SEX.items():
            pairs = insee_counts(rows, code, year, len(rows))
            counts = dict(list(pairs.items())[:top])
            total = sum(pairs.values())
            distributions[f"{label}:{year}"] = categorical(counts, sex=label, birth_year=int(year), full_list_total=total, coverage=round(sum(counts.values()) / total, SHARE_DIGITS))
    items = insee_evidence(raw, rows, doc_raw, license_raw, "1", years[0])[:1] + insee_evidence(raw, rows, doc_raw, license_raw, "2", years[-1])
    return entry(
        f"fr-first-names-by-birth-cohort-top-{top}",
        f"France first names given sex and year of birth, top {top} for {years[0]} to {years[-1]} by decade (INSEE)",
        "FR",
        (f"{years[0]}-01-01", f"{years[-1]}-12-31"),
        conditional("first_name", "sex_and_birth_year", distributions),
        items,
        [
            shares_assumption(f"top {top} names of that sex and birth year"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": "full_list_total is the sum of valeur over every name of that sex and year in the national file, so coverage is the share of those births given one of the listed names."},
        ],
        conditional_tests(distributions),
        f"The {top} most given first names for each sex and each birth year {', '.join(years)}, keyed as sex:year (for example "
        "male:1980), so a generator can pick a first name consistent with a person's sex and date of birth. Counts are the "
        f"published births for the name in that year; names are in the upper-case, accented form INSEE publishes. {INSEE_NOTE}",
        ["first-names", "insee", "by-sex", "by-birth-year", "cohort"],
        status="license-review",
    )


# --- Ireland: CSO baby names ------------------------------------------------------------------------


def cso_counts(raw: bytes, statistic: str, year: str) -> dict[str, int]:
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    name_column = next(c for c in rows.fieldnames if c.endswith("Names"))
    pairs = [(r[name_column], int(r["VALUE"])) for r in rows if r["STATISTIC"] == statistic and r["Year"] == year and r["VALUE"]]
    pairs.sort(key=lambda p: (-p[1], p[0]))
    return dict(pairs)


def cso_top_line(raw: bytes, statistic: str, year: str, name: str) -> str:
    for line in raw.decode("utf-8-sig").splitlines():
        if line.startswith(f'"{statistic}"') and f'"{year}","{year}"' in line and f'"{name}"' in line:
            return line[line.index(f'"{year}","{year}"'):]
    raise ValueError(f"no line for {name} in {year}")


def cso_by_sex(boys_raw: bytes, girls_raw: bytes, license_raw: bytes, year: str, top: int) -> dict:
    sources = {"male": ("VSA50", CSO_BOYS_URL, boys_raw, "Boys"), "female": ("VSA60", CSO_GIRLS_URL, girls_raw, "Girls")}
    distributions, items = {}, []
    for label, (table, url, raw, word) in sources.items():
        full_list = cso_counts(raw, f"{table}C01", year)
        counts = dict(list(full_list.items())[:top])
        total = sum(full_list.values())
        distributions[label] = categorical(counts, full_list_total=total, coverage=round(sum(counts.values()) / total, SHARE_DIGITS))
        first = next(iter(counts))
        items.append(evidence("Central Statistics Office", f"PxStat table {table}, {word} Names in Ireland with 3 or More Occurrences (CSV)", url, f"STATISTIC={table}C01, Year={year}, {word} Names={first}, VALUE", counts[first], "count", cso_top_line(raw, f"{table}C01", year, first), CC_BY, raw))
    items.append(evidence("Government of Ireland open data portal (data.gov.ie)", "CKAN package metadata for CSO table VSA50 (licence statement)", CSO_LICENSE_URL, "result.license_id", "CC-BY-4.0", "text", '"license_id": "CC-BY-4.0"', CC_BY, license_raw, role="supporting"))
    return entry(
        f"ie-baby-names-{year}-top-{top}-by-sex",
        f"Ireland baby names given sex, top {top} of {year} registrations (CSO PxStat VSA50 and VSA60)",
        "IE",
        (f"{year}-01-01", f"{year}-12-31"),
        conditional("first_name", "sex", distributions),
        items,
        [
            shares_assumption(f"top {top} names of that sex"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": f"full_list_total is the sum of the published counts over every name with a value for {year} (names with three or more occurrences), so coverage is the share of those births given one of the listed names."},
        ],
        conditional_tests(distributions),
        f"The {top} most common first names registered for boys (table VSA50) and girls (table VSA60) in Ireland in {year}, with "
        "the published counts and shares renormalised within each list. The CSO publishes names with three or more occurrences; "
        "the whole PxStat cube from 1964 is the cited resource because the API serves no per-year slice at a stable URL. "
        "The data.gov.ie catalogue record for the table states the CC BY 4.0 licence.",
        ["first-names", "baby-names", "cso", "by-sex"],
    )


# --- Belgium: Statbel ---------------------------------------------------------------------------------

STATBEL_NOTE = "Statbel's open data page states that its open data are published under the Creative Commons Attribution 4.0 licence."
STATBEL_BLOCKS = ("A", "D", "G", "J")


def statbel_blocks(rows: list[dict[str, str]], top: int) -> dict[str, dict[str, int]]:
    """Regions laid out side by side in three-column blocks (rank, name, count), each headed by the region name."""
    header = rows[0]
    blocks = {}
    for start in STATBEL_BLOCKS:
        name_col, count_col = chr(ord(start) + 1), chr(ord(start) + 2)
        blocks[header[start]] = ranked_block(rows[1:], name_col, count_col, top)
    return blocks


def statbel_babies(url: str, raw: bytes, license_raw: bytes, sex: str, year: str, top: int) -> dict:
    rows = sheet_rows(raw, year)
    distributions = {region: categorical(counts) for region, counts in statbel_blocks(rows, top).items()}
    label = {"boys": "male", "girls": "female"}[sex]
    first = rows[1]
    return entry(
        f"be-baby-names-{sex}-{year}-by-region-top-{top}",
        f"Belgium baby names for {sex} given region, top {top} of {year} births (Statbel)",
        "BE",
        (f"{year}-01-01", f"{year}-12-31"),
        conditional(f"{label}_first_name", "region", distributions),
        [
            evidence("Statbel", f"First names of newborn {sex} 1995 onwards (XLSX), sheet {year}", url, f"sheet {year}, row 2 (Belgium, rank 1): name, count", int(first["C"]), "count", first["B"], CC_BY, raw),
            evidence("Statbel", f"First names of newborn {sex} 1995 onwards (XLSX), sheet {year}", url, f"sheet {year}, row 1 (block headers)", rows[0]["J"], "text", rows[0]["J"], CC_BY, raw),
            evidence("Statbel", "Statbel open data (licence statement)", STATBEL_LICENSE_URL, "Open data, licence paragraph", "Creative Commons Attribution 4.0 license", "text", "Creative Commons Attribution 4.0 license", CC_BY, license_raw, role="supporting"),
        ],
        [shares_assumption(f"top {top} names for the region")],
        conditional_tests(distributions),
        f"The {top} most given first names for {sex} born in {year} in Belgium as a whole and in Flanders, Wallonia and Brussels, "
        f"from the {year} sheet of Statbel's first-names workbook, with published counts and shares renormalised within each list. "
        f"Keys are the region headings of the sheet. {STATBEL_NOTE}",
        ["first-names", "baby-names", "statbel", "by-region", label],
    )


def statbel_surnames(raw: bytes, license_raw: bytes, year: str, top: int) -> dict:
    rows = sheet_rows(raw, f"top10000_{year}")
    distributions = {region: categorical(counts) for region, counts in statbel_blocks(rows, top).items()}
    first = rows[1]
    return entry(
        f"be-surnames-{year}-by-region-top-{top}",
        f"Belgium surnames given region, top {top} of the {year} population (Statbel)",
        "BE",
        (f"{year}-01-01", f"{year}-01-01"),
        conditional("surname", "region", distributions),
        [
            evidence("Statbel", f"Family names {year} (XLSX), sheet top10000_{year}", STATBEL_SURNAMES_URL, f"top10000_{year}, row 2 (Belgium, rank 1): name, count", int(first["C"]), "count", first["B"], CC_BY, raw),
            evidence("Statbel", f"Family names {year} (XLSX), sheet top10000_{year}", STATBEL_SURNAMES_URL, f"top10000_{year}, row 1 (block headers)", rows[0]["J"], "text", rows[0]["J"], CC_BY, raw),
            evidence("Statbel", "Statbel open data (licence statement)", STATBEL_LICENSE_URL, "Open data, licence paragraph", "Creative Commons Attribution 4.0 license", "text", "Creative Commons Attribution 4.0 license", CC_BY, license_raw, role="supporting"),
        ],
        [
            shares_assumption(f"top {top} surnames for the region"),
            {"parameter": "observed_period", "value": f"{year}-01-01", "method": "assumed", "rationale": f"The workbook is labelled {year} without a day; Statbel's population tables refer to 1 January of the year, so the reference date is taken as 1 January {year}."},
        ],
        conditional_tests(distributions),
        f"The {top} most common surnames in the {year} population of Belgium as a whole and of the Flemish, Walloon and "
        f"Brussels-Capital Regions, from Statbel's top-10,000 family names workbook, with published counts and shares renormalised "
        f"within each list. {STATBEL_NOTE}",
        ["surnames", "statbel", "by-region"],
    )


def statbel_population_first_names(raw: bytes, license_raw: bytes, sex: str, year: str, top: int) -> dict:
    sheet = {"women": "F", "men": "M"}[sex] + f"_PROV{year}"
    rows = sheet_rows(raw, sheet)
    by_province: dict[str, dict[str, int]] = {}
    for row in rows[2:]:
        if row.get("F", "").isdigit():
            by_province.setdefault(row["D"], {})[row["E"]] = int(row["F"])
    distributions = {}
    for province, counts in by_province.items():
        ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top])
        nuts2 = next(r["C"] for r in rows[2:] if r.get("D") == province)
        distributions[province] = categorical(ordered, nuts2=nuts2)
    label = {"women": "female", "men": "male"}[sex]
    first = rows[2]
    return entry(
        f"be-first-names-{sex}-{year}-by-province-top-{top}",
        f"Belgium first names of {sex} given province or region, top {top} of the {year} population (Statbel)",
        "BE",
        (f"{year}-01-01", f"{year}-01-01"),
        conditional(f"{label}_first_name", "province_or_region", distributions),
        [
            evidence("Statbel", f"Most common first names of {sex} in {year} by province and region (XLSX), sheet {sheet}", STATBEL_POP_URL, f"{sheet}, row 3 ({first['D']}, rank 1): Firstname, Number", int(first["F"]), "count", first["E"], CC_BY, raw),
            evidence("Statbel", f"Most common first names of {sex} in {year} by province and region (XLSX), sheet {sheet}", STATBEL_POP_URL, f"{sheet}, cell A1", rows[0]["A"], "text", rows[0]["A"], CC_BY, raw),
            evidence("Statbel", "Statbel open data (licence statement)", STATBEL_LICENSE_URL, "Open data, licence paragraph", "Creative Commons Attribution 4.0 license", "text", "Creative Commons Attribution 4.0 license", CC_BY, license_raw, role="supporting"),
        ],
        [
            shares_assumption(f"top {top} names for the province or region"),
            {"parameter": "observed_period", "value": f"{year}-01-01", "method": "assumed", "rationale": f"The workbook is labelled {year} without a day; Statbel's population tables refer to 1 January of the year, so the reference date is taken as 1 January {year}."},
        ],
        conditional_tests(distributions),
        f"The {top} most common first names of {sex} living in each Belgian province and in the Brussels-Capital Region in {year}, "
        f"from Statbel's workbook of first names of the population, with published counts and shares renormalised within each "
        f"list. Keys are the province and region names of the sheet; nuts2 holds the NUTS 2 code. The workbook has no national "
        f"total, so no Belgium-wide distribution is given. {STATBEL_NOTE}",
        ["first-names", "statbel", "by-province", label],
    )


# --- Spain: INE first names of the population ----------------------------------------------------


def ine_by_sex(raw: bytes, legal_raw: bytes, top: int) -> dict:
    distributions, items = {}, []
    reference = None
    for sheet, label in (("Hombres", "male"), ("Mujeres", "female")):
        rows = sheet_rows(raw, sheet)
        reference = rows[1]["A"]
        data = [r for r in rows[7:] if r.get("C", "").isdigit()]
        ordered = sorted(data, key=lambda r: (-int(r["C"]), r["B"]))[:top]
        counts = {r["B"]: int(r["C"]) for r in ordered}
        mean_age = {r["B"]: round(float(r["D"]), 1) for r in ordered}
        full_total = sum(int(r["C"]) for r in data)
        distributions[label] = categorical(counts, mean_age=mean_age, full_list_total=full_total, coverage=round(sum(counts.values()) / full_total, SHARE_DIGITS))
        first = ordered[0]
        items.append(evidence("Instituto Nacional de Estadística", f"Nombres por edad media (XLSX), sheet {sheet}", INE_URL, f"{sheet}, row 8 (Orden 1): Nombre, Frecuencia", int(first["C"]), "count", first["B"], UNSTATED, raw))
    items.append(evidence("Instituto Nacional de Estadística", "Nombres por edad media (XLSX), sheet Hombres", INE_URL, "Hombres, cell A2 (reference date)", reference, "text", reference, UNSTATED, raw))
    items.append(evidence("Instituto Nacional de Estadística", "Aviso legal (conditions of reuse)", INE_LEGAL_URL, "Condiciones de reutilización", "Debe citarse la fuente", "text", "Debe citarse la fuente", UNSTATED, legal_raw, role="supporting"))
    day, month, year = re.search(r"(\d{2})/(\d{2})/(\d{4})", reference).groups()
    iso = f"{year}-{month}-{day}"
    return entry(
        f"es-first-names-{year}-top-{top}-by-sex",
        f"Spain first names of residents given sex, top {top} with mean age, population census at {reference[-10:]} (INE)",
        "ES",
        (iso, iso),
        conditional("first_name", "sex", distributions),
        items,
        [
            shares_assumption(f"top {top} names of that sex"),
            {"parameter": "coverage", "value": "sum of the listed counts / full_list_total", "method": "derived", "rationale": "full_list_total is the sum of Frecuencia over every name on the sheet (names held by 20 or more residents), so coverage is the share of those residents carrying one of the listed names."},
        ],
        conditional_tests(distributions),
        f"The {top} most frequent first names of men and of women resident in Spain at the reference date of the annual population "
        f"census ({reference}), with the published frequency and the mean age of the people holding the name (mean_age, years), "
        "which lets a generator pair a name with a plausible age. Names are in the upper-case form INE publishes. INE's legal "
        "notice permits reuse with citation of the source but names no standard licence, so the licence is recorded as unstated pending review.",
        ["first-names", "ine", "by-sex", "mean-age"],
        status="license-review",
    )


# --- Norway: Statistics Norway ------------------------------------------------------------------------

SSB_NOTE = (
    "Statistics Norway's licence page, which the PxWeb API configuration names as the licence for its data, states that "
    "it uses the Creative Commons Attribution 4.0 International licence; the page renders with session-specific markup and is "
    "referenced rather than hashed, so the API configuration is cited as supporting evidence instead."
)


def jsonstat_values(raw: bytes, dimension: str) -> tuple[dict, dict[str, dict[str, float | None]]]:
    """Map each category label of ``dimension`` to its values by content code from a JSON-stat 2.0 response."""
    doc = json.loads(raw.decode("utf-8"))
    names = doc["dimension"][dimension]["category"]
    contents = doc["dimension"]["ContentsCode"]["category"]["index"]
    order = sorted(names["index"], key=names["index"].get)
    values = doc["value"]
    width = len(contents)
    table = {}
    for position, code in enumerate(order):
        table[names["label"][code]] = {content: values[position * width + offset] for content, offset in contents.items()}
    return doc, table


def ssb_first_names(girls_raw: bytes, boys_raw: bytes, license_raw: bytes, year: str, top: int) -> dict:
    distributions, items = {}, []
    for label, url, raw in (("female", SSB_GIRLS_URL, girls_raw), ("male", SSB_BOYS_URL, boys_raw)):
        doc, table = jsonstat_values(raw, "Fornavn")
        published = {name: v for name, v in table.items() if v["Personer"] is not None}
        ordered = sorted(published.items(), key=lambda kv: (-kv[1]["Personer"], kv[0]))[:top]
        counts = {name: int(v["Personer"]) for name, v in ordered}
        percent = {name: v["PersonerProsent"] for name, v in ordered}
        distributions[label] = categorical(counts, published_percent=percent, published_names=len(published), published_total=sum(int(v["Personer"]) for v in published.values()))
        first_name = ordered[0][0]
        first_code = next(code for code, text in doc["dimension"]["Fornavn"]["category"]["label"].items() if text == first_name)
        items.append(evidence("Statistics Norway", f"PxWeb API table 10467, born persons by {'girls' if label == 'female' else 'boys'}' name, {year} (JSON-stat 2.0)", url, f"dimension Fornavn label {first_code}; value for ContentsCode Personer", counts[first_name], "count", f'"{first_code}":"{first_name}"', CC_BY, raw))
        items.append(evidence("Statistics Norway", f"PxWeb API table 10467, born persons by {'girls' if label == 'female' else 'boys'}' name, {year} (JSON-stat 2.0)", url, "note", "Figures under 4 persons are not published.", "text", "Figures under 4 persons are not published.", CC_BY, raw))
    items.append(evidence("Statistics Norway", "PxWeb API 2.0 configuration (licence reference)", SSB_CONFIG_URL, "license", SSB_LICENSE_URL, "text", f'"license":"{SSB_LICENSE_URL}"', CC_BY, license_raw, role="supporting"))
    return entry(
        f"no-first-names-born-{year}-top-{top}-by-sex",
        f"Norway first names given sex, top {top} of persons named in {year} (Statistics Norway table 10467)",
        "NO",
        (f"{year}-01-01", f"{year}-12-31"),
        conditional("first_name", "sex", distributions),
        items,
        [
            shares_assumption(f"top {top} names of that sex with a published count"),
            {"parameter": "published_total", "value": "sum of counts over names with a published figure", "method": "derived", "rationale": "Statistics Norway suppresses counts under four and lists only names used by at least 200 persons the previous year, so published_total covers the published names only."},
        ],
        conditional_tests(distributions),
        f"The {top} most common first names given to girls and to boys named in Norway in {year}, from the girls' and boys' "
        "value sets of Statistics Norway table 10467, with the published count, the published percentage of born persons "
        f"(published_percent) and shares renormalised within each list. {SSB_NOTE}",
        ["first-names", "baby-names", "ssb", "by-sex"],
    )


def ssb_surnames(raw: bytes, license_raw: bytes, year: str, top: int) -> dict:
    doc, table = jsonstat_values(raw, "Etternavn")
    published = {name: int(v["Personer"]) for name, v in table.items() if v["Personer"] is not None}
    ordered = dict(sorted(published.items(), key=lambda kv: (-kv[1], kv[0]))[:top])
    distribution = categorical(ordered, published_names=len(published), published_total=sum(published.values()), coverage=round(sum(ordered.values()) / sum(published.values()), SHARE_DIGITS))
    first = next(iter(ordered))
    first_code = next(code for code, text in doc["dimension"]["Etternavn"]["category"]["label"].items() if text == first)
    return entry(
        f"no-surnames-{year}-top-{top}",
        f"Norway surnames, top {top} of surnames used by 200 persons or more, {year} (Statistics Norway table 12891)",
        "NO",
        (f"{year}-01-01", f"{year}-12-31"),
        marginal("surname", distribution),
        [
            evidence("Statistics Norway", f"PxWeb API table 12891, last names used by 200 persons or more, {year} (JSON-stat 2.0)", SSB_SURNAMES_URL, f"dimension Etternavn label {first_code}; value for ContentsCode Personer", ordered[first], "count", f'"{first_code}":"{first}"', CC_BY, raw),
            evidence("Statistics Norway", f"PxWeb API table 12891, last names used by 200 persons or more, {year} (JSON-stat 2.0)", SSB_SURNAMES_URL, "label", doc["label"], "text", doc["label"], CC_BY, raw),
            evidence("Statistics Norway", "PxWeb API 2.0 configuration (licence reference)", SSB_CONFIG_URL, "license", SSB_LICENSE_URL, "text", f'"license":"{SSB_LICENSE_URL}"', CC_BY, license_raw, role="supporting"),
        ],
        [
            shares_assumption(f"top {top} surnames"),
            {"parameter": "coverage", "value": "sum of the listed counts / published_total", "method": "derived", "rationale": "published_total is the sum of counts over every surname in the table (those used by 200 persons or more), so coverage is the share of those persons carrying one of the listed surnames."},
        ],
        [share_test(first, distribution["parameters"]["shares"][first]), sum_test()],
        f"The {top} most common surnames in Norway in {year} from Statistics Norway table 12891, which covers surnames used by "
        f"200 persons or more, with published counts and shares renormalised within the list. {SSB_NOTE}",
        ["surnames", "ssb"],
    )


# --- main ----------------------------------------------------------------------------------------------


def main() -> int:
    census_raw, census_paper = fetch(CENSUS_URL), fetch(CENSUS_PAPER_URL)
    write(us_surnames(census_raw, census_paper, 1000))
    write(us_surname_ethnicity(census_raw, census_paper, 50))

    ons_license = fetch(ONS_LICENSE_URL)
    for url, sex in ((ONS_BOYS_URL, "boys"), (ONS_GIRLS_URL, "girls")):
        raw = fetch(url)
        write(ons_top_names(url, raw, sex, ons_license, 200))
        write(ons_by_region(url, raw, sex, ons_license))

    write(nrs_by_sex(fetch(NRS_URL), 100))

    insee_raw, insee_doc, insee_license = fetch(INSEE_URL), fetch(INSEE_DOC_URL), fetch(INSEE_LICENSE_URL)
    write(insee_by_sex(insee_raw, insee_doc, insee_license, "2025", 200))
    write(insee_by_cohort(insee_raw, insee_doc, insee_license, [str(y) for y in range(1960, 2021, 10)], 50))

    write(cso_by_sex(fetch(CSO_BOYS_URL), fetch(CSO_GIRLS_URL), fetch(CSO_LICENSE_URL), "2025", 100))

    statbel_license = fetch(STATBEL_LICENSE_URL)
    for url, sex in ((STATBEL_BOYS_URL, "boys"), (STATBEL_GIRLS_URL, "girls")):
        write(statbel_babies(url, fetch(url), statbel_license, sex, "2025", 100))
    write(statbel_surnames(fetch(STATBEL_SURNAMES_URL), statbel_license, "2026", 300))
    statbel_pop = fetch(STATBEL_POP_URL)
    for sex in ("women", "men"):
        write(statbel_population_first_names(statbel_pop, statbel_license, sex, "2026", 50))

    write(ine_by_sex(fetch(INE_URL), fetch(INE_LEGAL_URL), 300))

    ssb_license = fetch(SSB_CONFIG_URL)
    write(ssb_first_names(fetch(SSB_GIRLS_URL), fetch(SSB_BOYS_URL), ssb_license, "2025", 200))
    write(ssb_surnames(fetch(SSB_SURNAMES_URL), ssb_license, "2025", 500))
    return 0


if __name__ == "__main__":
    sys.exit(main())

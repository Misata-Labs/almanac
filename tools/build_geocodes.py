"""Regenerate the global reference code lists: ISO 639-2 languages (Library of Congress), the IANA time zone
database zone and country tables, UN M49 geographic areas (UNSD SDG API), ISO 3166 country codes as published
in INSEE's Code officiel géographique, and the UN ISIC Rev.4, ISIC Rev.5, COICOP 2018 and COFOG structures.
Run from the repository root:

    uv run python tools/build_geocodes.py
"""

from __future__ import annotations

import json
import re
import sys
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

LOC = "Library of Congress (ISO 639-2 Registration Authority)"
IANA = "Internet Assigned Numbers Authority (Time Zone Database)"
UNSD = "United Nations Statistics Division"
INSEE = "Institut national de la statistique et des études économiques (INSEE)"

ISO639_URL = "https://www.loc.gov/standards/iso639-2/ISO-639-2_utf-8.txt"
TZ_VERSION = "2026f"
TZ_BASE = f"https://data.iana.org/time-zones/tzdb-{TZ_VERSION}/"
M49_LIST_URL = "https://unstats.un.org/SDGAPI/v1/sdg/GeoArea/List"
M49_TREE_URL = "https://unstats.un.org/SDGAPI/v1/sdg/GeoArea/Tree"
COG_ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/8377162/cog_ensemble_2025_csv.zip"
INSEE_LICENCE_URL = "https://www.insee.fr/fr/information/2008466"
ISIC4_URL = "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_4_english_structure.Txt"
ISIC5_URL = "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC_Rev_5_english_structure.csv"
COICOP_URL = "https://unstats.un.org/unsd/classifications/Econ/Download/COICOP_2018_English_structure.xlsx"
COFOG_URL = "https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/COFOG_english_structure.txt"

UNSTATED_NOTE = "The publisher states no licence on the file, so the licence is recorded as unstated and the entry held at license-review."
INSEE_LICENCE = "etalab-2.0"
INSEE_NOTE = (
    "INSEE's conditions-of-use page states that its data are released under the Licence Ouverte / Open Licence 2.0 (Etalab); "
    "that identifier is not on the verifier's permissive list, so the entry is held at license-review."
)


def collapse(text: str) -> str:
    return " ".join(text.split())


def line_with(text: str, needle: str) -> str:
    """The whitespace-collapsed line of ``text`` that contains ``needle``; the builder's own check that a snippet exists."""
    for line in text.splitlines():
        if needle in line:
            return collapse(line)
    raise LookupError(f"no line contains {needle!r}")


# ---------------------------------------------------------------- ISO 639-2 ----------------------------------------------------------------


def iso639(raw: bytes) -> dict:
    text = raw.decode("utf-8").lstrip("﻿")
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        bibliographic, terminology, alpha2, english, french = line.split("|")
        rows[bibliographic] = {"terminology": terminology or None, "alpha2": alpha2 or None, "english": english, "french": french}
    title = "ISO 639-2 language code list (UTF-8 text)"
    return rule_entry(
        "global-iso-639-2-language-codes",
        "ISO 639-2 three-letter language codes with ISO 639-1 two-letter equivalents and English and French names",
        "language",
        "global",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.lookup_table",
        parameters={"key": "ISO 639-2 bibliographic code", "rows": rows},
        vectors=membership_vectors(["eng", "fre", "jpn"], "xxx") + [column_vector("eng", "alpha2", "en"), column_vector("fre", "terminology", "fra"), column_vector("ger", "terminology", "deu")],
        evidence_items=[
            evidence(LOC, title, ISO639_URL, "line beginning eng|", "en", "text", line_with(text, "eng||en|"), "unstated", raw),
            evidence(LOC, title, ISO639_URL, "line beginning fre|", "fra", "text", line_with(text, "fre|fra|"), "unstated", raw),
        ],
        tests=lookup_tests(rows, [("eng", "alpha2"), ("fre", "terminology"), ("jpn", "english")]),
        notes=(
            "The Library of Congress is the ISO 639-2 Registration Authority and publishes the code list as a pipe-delimited UTF-8 text "
            "file: bibliographic three-letter code, terminology code where it differs (for example fre/fra), ISO 639-1 two-letter code "
            "where one exists, then English and French names. Rows are keyed by the bibliographic code; empty fields become null. "
            + UNSTATED_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["iso-639", "language-codes", "code-list"],
        use_cases=["person-generation", "digital-channels"],
        assumed=[accessed_assumption()],
    )


# ---------------------------------------------------------------- IANA tzdb ----------------------------------------------------------------


def tz_tables(zone_raw: bytes, iso_raw: bytes, news_raw: bytes, licence_raw: bytes) -> tuple[dict, dict]:
    zone_text, iso_text, news_text = zone_raw.decode("utf-8"), iso_raw.decode("utf-8"), news_raw.decode("utf-8")
    zones: dict[str, dict] = {}
    for line in zone_text.splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        codes, coordinates, name = fields[0].split(","), fields[1], fields[2]
        zones[name] = {"country_codes": codes, "coordinates": coordinates, "comments": fields[3] if len(fields) > 3 else None}
    countries: dict[str, dict] = {}
    for line in iso_text.splitlines():
        if line and not line.startswith("#"):
            code, name = line.split("\t")
            countries[code] = {"name": name, "zones": []}
    for name, zone in zones.items():
        for code in zone["country_codes"]:
            countries[code]["zones"].append(name)
    release = re.search(rf"^Release {TZ_VERSION} - (\d{{4}}-\d{{2}}-\d{{2}})", news_text, re.MULTILINE)
    if release is None:
        raise LookupError("release line not found in NEWS")
    valid_from = release.group(1)
    news_item = evidence(IANA, f"tzdb {TZ_VERSION} NEWS", TZ_BASE + "NEWS", f"line beginning Release {TZ_VERSION}", valid_from, "date", f"Release {TZ_VERSION} - {valid_from}", "public-domain", news_raw)
    licence_item = evidence(IANA, f"tzdb {TZ_VERSION} LICENSE", TZ_BASE + "LICENSE", "first paragraph", "public domain", "text", "are in the public domain", "public-domain", licence_raw, role="supporting")
    licence_note = (
        f"The IANA Time Zone Database release {TZ_VERSION} is cited from its versioned, uncompressed directory on data.iana.org, so the "
        "bytes never move under the hash. Its LICENSE file places the code and data in the public domain. valid_from is the release "
        f"date on the NEWS file's first Release line; valid_to is null until a later release is cited."
    )
    zone_entry = rule_entry(
        f"global-iana-tzdb-{TZ_VERSION}-zones",
        f"IANA Time Zone Database {TZ_VERSION}: zone1970.tab zones with overlapping ISO 3166 country codes and principal coordinates",
        "calendar",
        "global",
        valid_from=valid_from,
        implementation="almanac.rules.lookup_table",
        parameters={"release": TZ_VERSION, "key": "TZ identifier", "rows": zones},
        vectors=membership_vectors(["Europe/Andorra", "America/New_York", "Asia/Tokyo"], "Mars/Olympus_Mons")
        + [column_vector("Europe/Andorra", "coordinates", zones["Europe/Andorra"]["coordinates"]), column_vector("Asia/Tokyo", "country_codes", zones["Asia/Tokyo"]["country_codes"])],
        evidence_items=[
            evidence(IANA, f"tzdb {TZ_VERSION} zone1970.tab", TZ_BASE + "zone1970.tab", "row Europe/Andorra", "Europe/Andorra", "text", line_with(zone_text, "Europe/Andorra"), "public-domain", zone_raw),
            evidence(IANA, f"tzdb {TZ_VERSION} zone1970.tab", TZ_BASE + "zone1970.tab", "row Asia/Tokyo", "Asia/Tokyo", "text", line_with(zone_text, "Asia/Tokyo"), "public-domain", zone_raw),
            evidence(IANA, f"tzdb {TZ_VERSION} zone1970.tab", TZ_BASE + "zone1970.tab", "header comment", "public domain", "text", "This file is in the public domain.", "public-domain", zone_raw, role="supporting"),
            news_item,
            licence_item,
        ],
        tests=lookup_tests(zones, [("Europe/Andorra", "coordinates"), ("Asia/Tokyo", "coordinates")]),
        notes=(
            "zone1970.tab lists one row per timezone whose civil clocks have agreed since 1970: the ISO 3166 alpha-2 codes of the countries "
            "that overlap it (most populous first), the principal location in ISO 6709 sign-degrees-minutes form, the TZ identifier and, "
            "for countries with several zones, a comment. Rows are keyed by the TZ identifier and country_codes is kept as a list. "
            + licence_note
        ),
        status="verified",
        tags=["time-zones", "tzdb", "iana", "country-codes"],
        use_cases=["event-timestamps", "address-generation", "sla-calculation"],
    )
    country_entry = rule_entry(
        f"global-iana-tzdb-{TZ_VERSION}-countries",
        f"IANA Time Zone Database {TZ_VERSION}: ISO 3166 alpha-2 country codes with names and the tzdb zones that overlap each",
        "calendar",
        "global",
        valid_from=valid_from,
        implementation="almanac.rules.lookup_table",
        parameters={"release": TZ_VERSION, "key": "ISO 3166-1 alpha-2 code", "rows": countries},
        vectors=membership_vectors(["AD", "GB", "JP"], "ZZ") + [column_vector("AD", "name", countries["AD"]["name"]), column_vector("JP", "zones", countries["JP"]["zones"])],
        evidence_items=[
            evidence(IANA, f"tzdb {TZ_VERSION} iso3166.tab", TZ_BASE + "iso3166.tab", "row AD", countries["AD"]["name"], "text", line_with(iso_text, "AD\t"), "public-domain", iso_raw),
            evidence(IANA, f"tzdb {TZ_VERSION} iso3166.tab", TZ_BASE + "iso3166.tab", "row JP", countries["JP"]["name"], "text", line_with(iso_text, "JP\t"), "public-domain", iso_raw),
            evidence(IANA, f"tzdb {TZ_VERSION} zone1970.tab", TZ_BASE + "zone1970.tab", "row Asia/Tokyo", "Asia/Tokyo", "text", line_with(zone_text, "Asia/Tokyo"), "public-domain", zone_raw),
            news_item,
            licence_item,
        ],
        tests=lookup_tests(countries, [("AD", "name"), ("JP", "name")]),
        notes=(
            "iso3166.tab gives the two-letter country code and the usual English name tzdb uses for it (which sometimes departs from the "
            "ISO-listed name, as the file's own header explains). The zones column is derived by inverting zone1970.tab: every zone whose "
            "country list names the code, in file order. Codes with no zone row in zone1970.tab keep an empty list. " + licence_note
        ),
        status="verified",
        tags=["time-zones", "tzdb", "iana", "country-codes", "iso-3166"],
        use_cases=["event-timestamps", "address-generation"],
        assumed=[{"parameter": "rows[*].zones", "value": "zones of zone1970.tab whose country-code column lists the code", "method": "derived", "rationale": "zone1970.tab maps each zone to its countries; the per-country zone list is that mapping inverted."}],
    )
    return zone_entry, country_entry


# ---------------------------------------------------------------- UN M49 ----------------------------------------------------------------


def m49(list_raw: bytes, tree_raw: bytes) -> dict:
    names = {str(item["geoAreaCode"]): item["geoAreaName"] for item in json.loads(list_raw)}
    roots = {root["geoAreaName"]: root for root in json.loads(tree_raw)}
    continental = roots["World (total) by continental regions"]
    rows: dict[str, dict] = {}

    def walk(node: dict, ancestors: list[dict]) -> None:
        code = str(node["geoAreaCode"])
        regions = [a for a in ancestors if a["type"] == "Region" and a is not continental]
        rows[code.zfill(3)] = {
            "m49": int(code),
            "name": names.get(code, node["geoAreaName"]),
            "type": node["type"],
            "region": regions[0]["geoAreaName"] if regions else None,
            "sub_region": regions[1]["geoAreaName"] if len(regions) > 1 else None,
            "intermediate_region": regions[2]["geoAreaName"] if len(regions) > 2 else None,
            "ldc": False,
            "lldc": False,
            "sids": False,
        }
        for child in node["children"] or []:
            walk(child, ancestors + [node])

    walk(continental, [])

    def flag(root_name: str, column: str) -> None:
        def mark(node: dict) -> None:
            key = str(node["geoAreaCode"]).zfill(3)
            if node["type"] == "Country" and key in rows:
                rows[key][column] = True
            for child in node["children"] or []:
                mark(child)

        mark(roots[root_name])

    flag("Least Developed Countries (LDC)", "ldc")
    flag("Land Locked Developing Countries (LLDC)", "lldc")
    flag("Small Island Developing States (SIDS)", "sids")
    rows = dict(sorted(rows.items()))
    list_text, tree_text = list_raw.decode("utf-8"), tree_raw.decode("utf-8")
    afg_list = '"geoAreaCode":"4","geoAreaName":"Afghanistan"'
    afg_tree = '"geoAreaCode":4,"geoAreaName":"Afghanistan","type":"Country"'
    for snippet, text in ((afg_list, list_text), (afg_tree, tree_text)):
        if snippet not in text:
            raise LookupError(f"snippet {snippet!r} not in resource")
    return rule_entry(
        "global-un-m49-geo-areas",
        "UN M49 geographic area codes with continental region, sub-region and intermediate region, and LDC, LLDC and SIDS flags",
        "geography",
        "global",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.lookup_table",
        parameters={"key": "M49 code, zero-padded to three digits", "rows": rows},
        vectors=membership_vectors(["004", "826", "002"], "999") + [column_vector("004", "name", rows["004"]["name"]), column_vector("004", "region", rows["004"]["region"]), column_vector("004", "ldc", True)],
        evidence_items=[
            evidence(UNSD, "SDG Global Database API, GeoArea/List (JSON)", M49_LIST_URL, "element geoAreaCode 4", "Afghanistan", "text", afg_list, "unstated", list_raw),
            evidence(UNSD, "SDG Global Database API, GeoArea/Tree (JSON)", M49_TREE_URL, "node geoAreaCode 4 under World (total) by continental regions", "Afghanistan", "text", afg_tree, "unstated", tree_raw),
            evidence(UNSD, "SDG Global Database API, GeoArea/Tree (JSON)", M49_TREE_URL, "root node", "World (total) by continental regions", "text", '"geoAreaName":"World (total) by continental regions"', "unstated", tree_raw),
        ],
        tests=lookup_tests(rows, [("004", "name"), ("826", "sub_region"), ("001", "type")]),
        notes=(
            "The UN Statistics Division's SDG Global Database API exposes the M49 geographic areas: GeoArea/List gives every code and "
            "name, GeoArea/Tree nests them under several roots. Rows are taken from the 'World (total) by continental regions' root, "
            "with the ancestor Region names recorded as region, sub_region and intermediate_region, and the LDC, LLDC and SIDS roots "
            "set the three flags. The API returns codes without leading zeros; keys are zero-padded to the three-digit M49 form and the "
            "raw integer is kept in m49. " + UNSTATED_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["un-m49", "country-codes", "regions", "code-list"],
        use_cases=["address-generation", "customer-segmentation", "market-sizing"],
        assumed=[
            accessed_assumption(),
            {"parameter": "rows keys", "value": "M49 code zero-padded to three digits", "method": "derived", "rationale": "The API serialises codes as integers; M49 codes are conventionally written with three digits."},
            {"parameter": "rows[*].ldc, lldc, sids", "value": "membership of the LDC, LLDC and SIDS tree roots", "method": "derived", "rationale": "Each flag is true when the country appears under that root of GeoArea/Tree."},
        ],
    )


# ---------------------------------------------------------------- ISO 3166 via INSEE COG ----------------------------------------------------------------


def iso3166_cog(zip_raw: bytes, licence_raw: bytes) -> dict:
    member = "v_pays_territoire_2025.csv"
    text = zip_member(zip_raw, member)
    rows: dict[str, dict] = {}
    for r in csv_rows(text):
        if not r["CODEISO2"]:
            continue
        rows[r["CODEISO2"]] = {
            "iso3": r["CODEISO3"],
            "numeric": r["CODENUM3"],
            "cog": r["COG"],
            "name_fr": r["LIBCOG"],
            "official_name_fr": r["LIBENR"],
            "actual": r["ACTUAL"],
            "attached_to": r["CRPAY"] or None,
        }
    rows = dict(sorted(rows.items()))
    return rule_entry(
        "global-iso-3166-country-codes-cog-2025",
        "ISO 3166-1 alpha-2, alpha-3 and numeric country codes with French names, from INSEE's Code officiel géographique 2025",
        "geography",
        "global",
        valid_from="2025-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "ISO 3166-1 alpha-2 code", "source_member": member, "rows": rows},
        vectors=membership_vectors(["FR", "DK", "JP"], "ZZ") + [column_vector("FR", "iso3", "FRA"), column_vector("FR", "numeric", "250"), column_vector("DK", "cog", rows["DK"]["cog"])],
        evidence_items=[
            evidence(INSEE, "Code officiel géographique 2025, ensemble des fichiers CSV (ZIP)", COG_ZIP_URL, f"{member}, row COG 99100", "FRA", "text", line_with(text, '"99100"'), INSEE_LICENCE, zip_raw),
            evidence(INSEE, "Code officiel géographique 2025, ensemble des fichiers CSV (ZIP)", COG_ZIP_URL, f"{member}, row COG 99101", "DNK", "text", line_with(text, '"99101"'), INSEE_LICENCE, zip_raw),
            evidence(INSEE, "Conditions générales d'utilisation du site insee.fr", INSEE_LICENCE_URL, "section Réutilisation des informations publiques", "Licence Ouverte / Open Licence version 2.0", "text", "Licence Ouverte / Open Licence version 2.0 (Etalab).", INSEE_LICENCE, licence_raw, role="supporting"),
        ],
        tests=lookup_tests(rows, [("FR", "iso3"), ("JP", "numeric"), ("DK", "name_fr")]),
        notes=(
            "INSEE's Code officiel géographique ships a countries-and-territories table (v_pays_territoire_2025.csv) that carries, next "
            "to INSEE's own 991xx country code, the ISO 3166-1 alpha-2, alpha-3 and numeric codes and the short and official French "
            "names. Rows with no ISO alpha-2 code are dropped; the actual and attached_to (CRPAY) columns are INSEE's own status and "
            "attachment fields, kept as published. The COG describes the situation on 1 January of its year, which sets valid_from. "
            + INSEE_NOTE
        ),
        status="license-review",
        tags=["iso-3166", "country-codes", "insee", "code-list"],
        use_cases=["address-generation", "kyc-onboarding", "multi-currency-ledger"],
        assumed=[vintage_assumption("2025-01-01", "COG 2025, the geography in force on 1 January 2025")],
    )


# ---------------------------------------------------------------- UN economic classifications ----------------------------------------------------------------


def levelled_sets(codes: list[tuple[str, str]], levels: list[tuple[str, re.Pattern[str]]]) -> dict[str, dict[str, str]]:
    sets: dict[str, dict[str, str]] = {name: {} for name, _ in levels}
    for code, title in codes:
        for name, pattern in levels:
            if pattern.fullmatch(code):
                sets[name][code] = title
                break
        else:
            raise ValueError(f"code {code!r} matches no level")
    return sets


ISIC_LEVELS = [("section", re.compile(r"[A-Z]")), ("division", re.compile(r"\d{2}")), ("group", re.compile(r"\d{3}")), ("class", re.compile(r"\d{4}"))]
DOTTED_LEVELS = [("division", re.compile(r"\d{2}")), ("group", re.compile(r"\d{2}\.\d")), ("class", re.compile(r"\d{2}\.\d\.\d")), ("subclass", re.compile(r"\d{2}\.\d\.\d\.\d")), ("item", re.compile(r"\d{2}\.\d\.\d\.\d\.\d{1,2}"))]


def isic(raw: bytes, url: str, revision: int, title: str) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # The Rev.5 file is Latin-1 with a few non-breaking spaces inside titles; they become ordinary spaces.
        text = raw.decode("latin-1").replace("\xa0", " ")
    rows = [(r[0], r[1]) for r in (list(row.values()) for row in csv_rows(text))]
    sets = levelled_sets(rows, ISIC_LEVELS)
    return rule_entry(
        f"global-isic-rev{revision}-structure",
        f"UN ISIC Rev.{revision} structure: sections, divisions, groups and classes with titles",
        "business",
        "global",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.enumeration",
        parameters={"sets": sets},
        vectors=set_vectors(sets, "9999") + [{"input": {"set": "class", "value": "0111"}, "expected": True, "origin": "source"}],
        evidence_items=[
            evidence(UNSD, title, url, "row 0111", "0111", "text", line_with(text, '"0111"'), "unstated", raw),
            evidence(UNSD, title, url, "row A", "A", "text", line_with(text, '"A",'), "unstated", raw),
        ],
        tests=set_tests(sets),
        notes=(
            f"The International Standard Industrial Classification of All Economic Activities, Revision {revision}, as the UN Statistics "
            "Division's structure file lists it: one-letter sections, two-digit divisions, three-digit groups and four-digit classes, "
            "each with its English title, sorted into one enumeration set per level. Non-breaking spaces inside titles are written as "
            "ordinary spaces. " + UNSTATED_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["isic", "industry-codes", "code-list", "classification"],
        use_cases=["company-generation", "kyb-onboarding", "customer-segmentation"],
        assumed=[accessed_assumption()],
    )


def coicop(raw: bytes) -> dict:
    rows = sheet_rows(raw, "COICOP_2018")
    codes = [(str(r[0]).strip(), str(r[1]).strip()) for r in rows[1:] if r[0]]
    sets = levelled_sets(codes, DOTTED_LEVELS)
    return rule_entry(
        "global-coicop-2018-structure",
        "UN COICOP 2018 structure: divisions, groups, classes, subclasses and items of household consumption with titles",
        "business",
        "global",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.enumeration",
        parameters={"sets": sets},
        vectors=set_vectors(sets, "99") + [{"input": {"set": "subclass", "value": "01.1.1.1"}, "expected": True, "origin": "source"}],
        evidence_items=[
            evidence(UNSD, "COICOP 2018 English structure (XLSX), sheet COICOP_2018", COICOP_URL, "row with code 01.1.1.1, column title", sets["subclass"]["01.1.1.1"], "text", sets["subclass"]["01.1.1.1"], "unstated", raw),
            evidence(UNSD, "COICOP 2018 English structure (XLSX), sheet COICOP_2018", COICOP_URL, "row with code 01, column title", sets["division"]["01"], "text", sets["division"]["01"], "unstated", raw),
        ],
        tests=set_tests(sets),
        notes=(
            "The Classification of Individual Consumption According to Purpose, 2018 revision, from the UN Statistics Division's "
            "structure workbook: two-digit divisions and dotted groups, classes, subclasses and a fifth dotted level recorded here as "
            "item, titles only (the workbook's "
            "explanatory columns are not copied). Titles end in the durability markers the classification uses, such as (ND) or (S). "
            "Snippets are matched against the workbook's sharedStrings member, which the verifier reads as XML. "
            + UNSTATED_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["coicop", "consumption", "code-list", "classification"],
        use_cases=["retail-demo", "pricing", "customer-segmentation"],
        assumed=[accessed_assumption()],
    )


COFOG_LEVELS = [("division", re.compile(r"\d{2}")), ("group", re.compile(r"\d{2}\.\d")), ("class", re.compile(r"\d{2}\.\d\.\d"))]


def cofog(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig")
    codes = []
    for line in text.splitlines()[1:]:
        if line.strip():
            code, title = line.split(None, 1)
            codes.append((code, collapse(title)))
    sets = levelled_sets(codes, COFOG_LEVELS)
    return rule_entry(
        "global-cofog-structure",
        "UN COFOG structure: divisions, groups and classes of government functions with titles",
        "business",
        "global",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.enumeration",
        parameters={"sets": sets},
        vectors=set_vectors(sets, "99") + [{"input": {"set": "class", "value": "01.1.1"}, "expected": True, "origin": "source"}],
        evidence_items=[
            evidence(UNSD, "COFOG English structure (text)", COFOG_URL, "row 01.1.1", "01.1.1", "text", line_with(text, "01.1.1 "), "unstated", raw),
            evidence(UNSD, "COFOG English structure (text)", COFOG_URL, "row 01", "01", "text", line_with(text, "01            General"), "unstated", raw),
        ],
        tests=set_tests(sets),
        notes=(
            "The Classification of the Functions of Government as the UN Statistics Division's structure file lists it: two-digit "
            "divisions, dotted groups and classes, with titles; class titles keep the (CS) or (IS) marker for collective or individual "
            "services. " + UNSTATED_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["cofog", "public-sector", "code-list", "classification"],
        use_cases=["financial-reporting", "audit-demo"],
        assumed=[accessed_assumption()],
    )


def main() -> None:
    write(iso639(stable(ISO639_URL)))
    zone_raw, iso_raw, news_raw, licence_raw = (stable(TZ_BASE + name) for name in ("zone1970.tab", "iso3166.tab", "NEWS", "LICENSE"))
    for entry in tz_tables(zone_raw, iso_raw, news_raw, licence_raw):
        write(entry)
    write(m49(stable(M49_LIST_URL), stable(M49_TREE_URL)))
    write(iso3166_cog(stable(COG_ZIP_URL), stable(INSEE_LICENCE_URL)))
    write(isic(stable(ISIC4_URL), ISIC4_URL, 4, "ISIC Rev.4 English structure (text)"))
    write(isic(stable(ISIC5_URL), ISIC5_URL, 5, "ISIC Rev.5 English structure (CSV)"))
    write(coicop(stable(COICOP_URL)))
    write(cofog(stable(COFOG_URL)))


if __name__ == "__main__":
    main()

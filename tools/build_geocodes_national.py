"""Regenerate the national geographic code entries outside the United States: INSEE's Code officiel géographique
2025 (regions, départements, communes of Île-de-France and commune counts by département), Eurostat's NUTS 2024
codes and NUTS-3 typologies, the ABS 2021 postal areas and Japan Post's postal code file (prefecture summary and
two central Tokyo wards). Run from the repository root:

    uv run python tools/build_geocodes_national.py
"""

from __future__ import annotations

import csv
import io
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

INSEE = "Institut national de la statistique et des études économiques (INSEE)"
EUROSTAT = "Eurostat"
ABS = "Australian Bureau of Statistics"
JAPAN_POST = "Japan Post Co., Ltd."

COG_ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/8377162/cog_ensemble_2025_csv.zip"
INSEE_LICENCE_URL = "https://www.insee.fr/fr/information/2008466"
NUTS_URL = "https://ec.europa.eu/eurostat/documents/345175/629341/NUTS2021-NUTS2024.xlsx"
POA_URL = "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/correspondences/CG_POA_2016_POA_2021.csv"
KEN_ALL_URL = "https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
KEN_ALL_README_URL = "https://www.post.japanpost.jp/service/search/zipcode/download/readme.html"

INSEE_LICENCE = "etalab-2.0"
INSEE_NOTE = (
    "INSEE's conditions-of-use page states that its data are released under the Licence Ouverte / Open Licence 2.0 (Etalab); "
    "that identifier is not on the verifier's permissive list, so the entry is held at license-review."
)
COG_NOTE = "The Code officiel géographique describes the geography in force on 1 January of its year, which sets valid_from."
EUROSTAT_NOTE = "Eurostat's copyright notice releases its data under the Creative Commons Attribution 4.0 International licence."
ABS_NOTE = (
    "The ABS website copyright page states that, unless otherwise noted, its content is licensed under Creative Commons Attribution 4.0 "
    "International; that page renders with varying bytes between fetches, so it is referenced rather than hashed and the entry is held "
    "at license-review until the licence of this file is confirmed."
)
JP_NOTE = (
    "Japan Post's readme states that it claims no copyright over the postal code data and that it may be distributed freely; that "
    "is not an SPDX licence, so the licence is recorded as unstated and the entry held at license-review."
)
COG_ZIP_TITLE = "Code officiel géographique 2025, ensemble des fichiers CSV (ZIP)"
IDF_REGION = "11"
TOKYO_WARDS = ("13101", "13102")


def collapse(text: str) -> str:
    return " ".join(text.split())


def line_with(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle in line:
            return collapse(line)
    raise LookupError(f"no line contains {needle!r}")


def insee_licence_item(raw: bytes) -> dict:
    return evidence(INSEE, "Conditions générales d'utilisation du site insee.fr", INSEE_LICENCE_URL, "section Réutilisation des informations publiques", "Licence Ouverte / Open Licence version 2.0", "text", "Licence Ouverte / Open Licence version 2.0 (Etalab).", INSEE_LICENCE, raw, role="supporting")


# ---------------------------------------------------------------- INSEE COG 2025 ----------------------------------------------------------------


def cog_regions(zip_raw: bytes, licence_raw: bytes) -> dict:
    member = "v_region_2025.csv"
    text = zip_member(zip_raw, member)
    rows = {r["REG"]: {"name": r["LIBELLE"], "chef_lieu": r["CHEFLIEU"], "tncc": r["TNCC"]} for r in csv_rows(text)}
    return rule_entry(
        "fr-insee-cog-2025-regions",
        "France régions in the Code officiel géographique 2025: region code, name, chef-lieu commune code and name-type code",
        "geography",
        "FR",
        valid_from="2025-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "REG region code", "source_member": member, "rows": rows},
        vectors=membership_vectors(["01", "11", "84"], "99") + [column_vector("11", "name", rows["11"]["name"]), column_vector("01", "chef_lieu", "97105")],
        evidence_items=[
            evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row REG 01", "Guadeloupe", "text", line_with(text, '"01","97105"'), INSEE_LICENCE, zip_raw),
            evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row REG 11", rows["11"]["name"], "text", line_with(text, '"11",'), INSEE_LICENCE, zip_raw),
            insee_licence_item(licence_raw),
        ],
        tests=lookup_tests(rows, [("11", "name"), ("84", "chef_lieu")]),
        notes=(
            "The 18 régions of the Code officiel géographique 2025 (13 metropolitan and 5 overseas), keyed by the two-character REG "
            "code, with the name as INSEE writes it (LIBELLE), the commune code of the chef-lieu and INSEE's TNCC article code, which "
            "says which article and apostrophe the name takes. " + COG_NOTE + " " + INSEE_NOTE
        ),
        status="license-review",
        tags=["insee", "cog", "regions", "code-list", "france"],
        use_cases=["address-generation", "customer-segmentation"],
        assumed=[vintage_assumption("2025-01-01", "COG 2025")],
    )


def cog_departements(zip_raw: bytes, licence_raw: bytes) -> dict:
    member = "v_departement_2025.csv"
    text = zip_member(zip_raw, member)
    rows = {r["DEP"]: {"region": r["REG"], "name": r["LIBELLE"], "chef_lieu": r["CHEFLIEU"], "tncc": r["TNCC"]} for r in csv_rows(text)}
    return rule_entry(
        "fr-insee-cog-2025-departements",
        "France départements in the Code officiel géographique 2025: department code, region, name and chef-lieu commune code",
        "geography",
        "FR",
        valid_from="2025-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "DEP department code", "source_member": member, "rows": rows},
        vectors=membership_vectors(["01", "2A", "75", "974"], "00") + [column_vector("01", "name", "Ain"), column_vector("75", "region", rows["75"]["region"])],
        evidence_items=[
            evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row DEP 01", "Ain", "text", line_with(text, '"01","84"'), INSEE_LICENCE, zip_raw),
            evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row DEP 75", rows["75"]["name"], "text", line_with(text, '"75",'), INSEE_LICENCE, zip_raw),
            insee_licence_item(licence_raw),
        ],
        tests=lookup_tests(rows, [("01", "name"), ("2A", "name"), ("974", "region")]),
        notes=(
            "The départements of the Code officiel géographique 2025, keyed by the DEP code (two digits, 2A and 2B for Corsica, three "
            "digits overseas), with the region code, the name as INSEE writes it, the chef-lieu commune code and the TNCC article code. "
            + COG_NOTE + " " + INSEE_NOTE
        ),
        status="license-review",
        tags=["insee", "cog", "departements", "code-list", "france"],
        use_cases=["address-generation", "customer-segmentation", "insurance"],
        assumed=[vintage_assumption("2025-01-01", "COG 2025")],
    )


def cog_communes(zip_raw: bytes, licence_raw: bytes) -> tuple[dict, dict]:
    member = "v_commune_2025.csv"
    text = zip_member(zip_raw, member)
    records = csv_rows(text)
    idf = {
        r["COM"]: {"type": r["TYPECOM"], "dep": r["DEP"], "arr": r["ARR"] or None, "canton": r["CAN"] or None, "name": r["LIBELLE"], "parent": r["COMPARENT"] or None}
        for r in records
        if r["REG"] == IDF_REGION
    }
    by_dep: dict[str, dict] = {}
    for r in records:
        dep = r["DEP"] or r["COMPARENT"][:2]
        row = by_dep.setdefault(dep, {"COM": 0, "COMD": 0, "COMA": 0, "ARM": 0})
        row[r["TYPECOM"]] += 1
    by_dep = dict(sorted(by_dep.items()))
    paris = "75056"
    items = [
        evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row COM 75056", "Paris", "text", line_with(text, f'"{paris}","{IDF_REGION}"'), INSEE_LICENCE, zip_raw),
        evidence(INSEE, COG_ZIP_TITLE, COG_ZIP_URL, f"{member}, row COM 01001", "L'Abergement-Clémenciat", "text", line_with(text, '"01001"'), INSEE_LICENCE, zip_raw),
        insee_licence_item(licence_raw),
    ]
    detail = rule_entry(
        "fr-insee-cog-2025-communes-ile-de-france",
        "Communes of Île-de-France in the Code officiel géographique 2025: commune code, type, département, arrondissement and name",
        "geography",
        "FR",
        valid_from="2025-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "COM commune code", "region": IDF_REGION, "source_member": member, "rows": idf},
        vectors=membership_vectors([paris, "92012"], "01001") + [column_vector(paris, "name", "Paris"), column_vector(paris, "type", idf[paris]["type"])],
        evidence_items=items,
        tests=lookup_tests(idf, [(paris, "name"), ("92012", "dep")]),
        notes=(
            f"The national commune file holds {len(records)} rows across communes (COM), delegated communes (COMD), associated communes "
            "(COMA) and municipal arrondissements (ARM); this entry keeps the rows whose region is 11, Île-de-France, keyed by the "
            "five-character commune code, with the TYPECOM type, département, arrondissement, canton, the name as INSEE writes it and, "
            "for non-COM rows, the parent commune. Empty fields become null. " + COG_NOTE + " " + INSEE_NOTE
        ),
        status="license-review",
        tags=["insee", "cog", "communes", "code-list", "france", "ile-de-france"],
        use_cases=["address-generation", "customer-segmentation"],
        assumed=[vintage_assumption("2025-01-01", "COG 2025")],
    )
    summary = rule_entry(
        "fr-insee-cog-2025-communes-by-departement",
        "Number of communes, delegated and associated communes and municipal arrondissements per département, COG 2025",
        "geography",
        "FR",
        valid_from="2025-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "DEP department code", "source_member": member, "rows": by_dep},
        vectors=membership_vectors(["01", "75"], "00") + [column_vector("75", "ARM", by_dep["75"]["ARM"]), column_vector("01", "COM", by_dep["01"]["COM"])],
        evidence_items=items,
        tests=lookup_tests(by_dep, [("01", "COM"), ("75", "ARM")]),
        notes=(
            "Counts of rows in the COG 2025 commune file per département and TYPECOM: COM communes, COMD delegated communes, COMA "
            "associated communes and ARM municipal arrondissements (Paris, Lyon and Marseille). Rows without a département of their "
            "own (COMD, COMA and ARM) are counted under the département of their parent commune. The COM count is the weight of each "
            "département when drawing a commune at random. " + COG_NOTE + " " + INSEE_NOTE
        ),
        status="license-review",
        tags=["insee", "cog", "communes", "weights", "france", "by-departement"],
        use_cases=["address-generation", "market-sizing"],
        assumed=[
            vintage_assumption("2025-01-01", "COG 2025"),
            {"parameter": "rows[*]", "value": "row counts of v_commune_2025.csv grouped by département and TYPECOM", "method": "derived", "rationale": "The file lists individual communes; the per-département figures are counts of its rows, with COMD, COMA and ARM rows attributed to their parent's département."},
        ],
    )
    return detail, summary


# ---------------------------------------------------------------- Eurostat NUTS 2024 ----------------------------------------------------------------


def nuts_codes(raw: bytes) -> dict:
    rows = {}
    for r in sheet_rows(raw, "NUTS2024")[1:]:
        if r[1]:
            rows[str(r[1]).strip()] = {"country": r[0], "label": str(r[2]).strip(), "level": int(r[3])}
    levels = Counter(row["level"] for row in rows.values())
    title = "NUTS 2021 to NUTS 2024 correspondence workbook (XLSX), sheet NUTS2024"
    return rule_entry(
        "eu-nuts-2024-codes",
        "Eurostat NUTS 2024 classification: every NUTS 1, 2 and 3 code with its country and label",
        "geography",
        "EU",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "NUTS code", "rows": rows, "codes_per_level": {str(k): v for k, v in sorted(levels.items())}},
        vectors=membership_vectors(["BE1", "BE10", "BE100", "FR101"], "XX999") + [column_vector("BE2", "label", "Vlaams Gewest"), column_vector("BE100", "level", 3)],
        evidence_items=[
            evidence(EUROSTAT, title, NUTS_URL, "row with NUTS Code BE2, NUTS label", "Vlaams Gewest", "text", "Vlaams Gewest", "CC-BY-4.0", raw),
            evidence(EUROSTAT, title, NUTS_URL, "row with NUTS Code BE100, NUTS label", rows["BE100"]["label"], "text", rows["BE100"]["label"], "CC-BY-4.0", raw),
            evidence(EUROSTAT, title, NUTS_URL, "row with NUTS Code FR101, NUTS label", rows["FR101"]["label"], "text", rows["FR101"]["label"], "CC-BY-4.0", raw),
        ],
        tests=lookup_tests(rows, [("BE2", "label"), ("FR101", "country")]),
        notes=(
            "The NUTS2024 sheet of Eurostat's NUTS 2021 to NUTS 2024 workbook lists every region of the Nomenclature of Territorial "
            "Units for Statistics, 2024 version: the country code, the NUTS code, the label in the national language as Eurostat "
            "writes it and the level (1 to 3). codes_per_level counts the rows at each level. Snippets are matched against the "
            "workbook's sharedStrings member, which the verifier reads as XML. valid_from is the first day of the 2024 vintage the "
            "sheet is named after. " + EUROSTAT_NOTE
        ),
        status="verified",
        tags=["nuts", "eurostat", "regions", "code-list", "by-country"],
        use_cases=["address-generation", "customer-segmentation", "market-sizing"],
        assumed=[vintage_assumption("2024-01-01", "NUTS 2024")],
    )


def nuts3_typologies(raw: bytes) -> dict:
    rows = {}
    for r in sheet_rows(raw, "NUTS-3 Typologies")[1:]:
        if not r[1]:
            continue
        rows[str(r[1]).strip()] = {
            "urban_rural": r[3] or None,
            "remoteness": r[4] or None,
            "coastal": r[5] or None,
            "metropolitan": r[6] or None,
            "metro_id": r[7] or None,
            "border": r[9] or None,
            "island": r[10] or None,
            "mountain": r[11] or None,
        }
    typology = Counter(row["urban_rural"] for row in rows.values())
    title = "NUTS 2021 to NUTS 2024 correspondence workbook (XLSX), sheet NUTS-3 Typologies"
    return rule_entry(
        "eu-nuts-2024-nuts3-typologies",
        "Eurostat NUTS 2024 level-3 regions with urban-rural, remoteness, coastal, metropolitan, border, island and mountain typologies",
        "geography",
        "EU",
        valid_from="2024-01-01",
        implementation="almanac.rules.lookup_table",
        parameters={"key": "NUTS 3 code", "rows": rows, "urban_rural_counts": {k: v for k, v in sorted(typology.items(), key=lambda kv: str(kv[0]))}},
        vectors=membership_vectors(["BE100", "BE213"], "XX999") + [column_vector("BE100", "urban_rural", "predominantly urban"), column_vector("BE213", "urban_rural", "intermediate")],
        evidence_items=[
            evidence(EUROSTAT, title, NUTS_URL, "row with NUTS-3 Code BE213, Urban-Rural typology", "intermediate", "text", "Arr. Turnhout", "CC-BY-4.0", raw),
            evidence(EUROSTAT, title, NUTS_URL, "row with NUTS-3 Code BE100, Metropolitan regions", "capital city metropolitan region", "text", "capital city metropolitan region", "CC-BY-4.0", raw),
        ],
        tests=lookup_tests(rows, [("BE213", "remoteness"), ("BE100", "metro_id")]),
        notes=(
            "The NUTS-3 Typologies sheet of Eurostat's NUTS 2024 workbook tags every level-3 region with the territorial typologies "
            "Eurostat maintains: urban-rural typology, remoteness, coastal and metropolitan status (with the metropolitan region id), "
            "border, island and mountainous flags. Values are the sheet's own strings; empty cells become null. The label, country, "
            "metropolitan name and capital-region columns are left out to keep the entry compact; the label and country sit in the "
            "NUTS 2024 code entry under the same key. "
            "urban_rural_counts counts the regions in each urban-rural class, the natural weights for drawing a region type. "
            "Snippets are matched against the workbook's sharedStrings member. valid_from is the first day of the 2024 vintage. " + EUROSTAT_NOTE
        ),
        status="verified",
        tags=["nuts", "eurostat", "regions", "urban-rural", "typology", "by-country"],
        use_cases=["address-generation", "customer-segmentation", "market-sizing", "logistics"],
        assumed=[
            vintage_assumption("2024-01-01", "NUTS 2024"),
            {"parameter": "urban_rural_counts", "value": "count of rows per Urban-Rural typology value", "method": "derived", "rationale": "The sheet tags each region; the counts are a tally of those tags."},
        ],
    )


# ---------------------------------------------------------------- ABS postal areas 2021 ----------------------------------------------------------------


def abs_postal_areas(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig")
    records = csv_rows(text)
    sets = {
        "poa_2021": dict(sorted({r["POA_CODE_2021"]: r["POA_NAME_2021"] for r in records}.items())),
        "poa_2016": dict(sorted({r["POA_CODE_2016"]: r["POA_NAME_2016"] for r in records}.items())),
    }
    unchanged = sum(1 for r in records if r["POA_CODE_2016"] == r["POA_CODE_2021"] and r["RATIO_FROM_TO"] == "1")
    title = "ASGS Edition 3 correspondence, Postal Areas 2016 to Postal Areas 2021 (CSV)"
    return rule_entry(
        "au-abs-postal-areas-2021",
        "Australia Postal Areas (POA) 2021 and 2016 code lists from the ABS ASGS Edition 3 correspondence file",
        "geography",
        "AU",
        valid_from="2021-07-01",
        valid_to="2026-06-30",
        implementation="almanac.rules.enumeration",
        parameters={"sets": sets, "unchanged_one_to_one": unchanged},
        vectors=set_vectors(sets, "0000") + [{"input": {"set": "poa_2021", "value": "2000"}, "expected": True, "origin": "source"}],
        evidence_items=[
            evidence(ABS, title, POA_URL, "row POA_CODE_2016 0800", "0800", "text", line_with(text, "0800,0800,0800,0800"), "CC-BY-4.0", raw),
            evidence(ABS, title, POA_URL, "row POA_CODE_2016 2000", "2000", "text", line_with(text, "2000,2000,2000,2000"), "CC-BY-4.0", raw),
        ],
        tests=set_tests(sets) + [{"statistic": "count[poa_2021]", "expected": len(sets["poa_2021"]), "tolerance": 0}],
        notes=(
            "Postal Areas are the ABS approximation of Australia Post postcodes in the Australian Statistical Geography Standard. The "
            "2016-to-2021 correspondence file names every POA of both editions, so its two code columns give the complete 2021 and 2016 "
            "lists; the POA name is the four-digit code itself. unchanged_one_to_one counts the rows that map a 2016 POA to the same "
            "2021 code with ratio 1. The validity window is the ASGS Edition 3 period the file's URL names (July 2021 to June 2026). "
            + ABS_NOTE
        ),
        status="license-review",
        tags=["postcodes", "postal-areas", "asgs", "abs", "code-list", "australia"],
        use_cases=["address-generation", "logistics"],
        assumed=[
            {"parameter": "valid_from and valid_to", "value": "2021-07-01 to 2026-06-30", "method": "assumed", "rationale": "The file sits under the ASGS Edition 3 path named july-2021-june-2026; the window is read from that path."},
            {"parameter": "unchanged_one_to_one", "value": unchanged, "method": "derived", "rationale": "Count of correspondence rows whose 2016 and 2021 codes are equal with RATIO_FROM_TO 1."},
        ],
    )


# ---------------------------------------------------------------- Japan Post postal codes ----------------------------------------------------------------


def japan_post(zip_raw: bytes, readme_raw: bytes) -> tuple[dict, dict]:
    member = "utf_ken_all.csv"
    text = zip_member(zip_raw, member)
    records = list(csv.reader(io.StringIO(text)))
    prefectures: dict[str, dict] = {}
    seen_codes: dict[str, set] = {}
    seen_munis: dict[str, set] = {}
    for r in records:
        key = r[0][:2]
        row = prefectures.setdefault(key, {"prefecture": r[6], "prefecture_kana": r[3], "rows": 0, "postal_codes": 0, "municipalities": 0})
        row["rows"] += 1
        seen_codes.setdefault(key, set()).add(r[2])
        seen_munis.setdefault(key, set()).add(r[0])
    for key, row in prefectures.items():
        row["postal_codes"] = len(seen_codes[key])
        row["municipalities"] = len(seen_munis[key])
    wards: dict[str, dict] = {}
    for r in records:
        if r[0] not in TOKYO_WARDS:
            continue
        row = wards.setdefault(r[2], {"jis_code": r[0], "city": r[7], "city_kana": r[4], "towns": []})
        row["towns"].append({"town": r[8], "kana": r[5]})
    chiyoda = next(r for r in records if r[0] == TOKYO_WARDS[0])
    chuo = next(r for r in records if r[0] == TOKYO_WARDS[1])
    readme_snippet = "郵便番号データに限っては日本郵便株式会社は著作権を主張しません"
    if readme_snippet not in collapse(readme_raw.decode("utf-8", errors="replace")):
        raise LookupError("readme snippet not found")
    items = [
        evidence(JAPAN_POST, "Postal code data, all prefectures, UTF-8 (utf_ken_all.zip)", KEN_ALL_URL, f"{member}, first row for JIS code 13101", chiyoda[2], "text", line_with(text, f'{chiyoda[0]},"{chiyoda[1]}","{chiyoda[2]}"'), "unstated", zip_raw),
        evidence(JAPAN_POST, "Postal code data, all prefectures, UTF-8 (utf_ken_all.zip)", KEN_ALL_URL, f"{member}, first row", records[0][2], "text", line_with(text, f'{records[0][0]},"{records[0][1]}","{records[0][2]}"'), "unstated", zip_raw),
        evidence(JAPAN_POST, "Postal code data download readme", KEN_ALL_README_URL, "section 使用・再配布・移植・改良について", "著作権を主張しません", "text", readme_snippet, "unstated", readme_raw, role="supporting"),
    ]
    summary = rule_entry(
        "jp-japanpost-postal-codes-by-prefecture",
        "Japan Post postal code file summarised by prefecture: prefecture names, rows, distinct seven-digit codes and municipalities",
        "geography",
        "JP",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.lookup_table",
        parameters={"key": "two-digit prefecture JIS code", "source_member": member, "rows": prefectures},
        vectors=membership_vectors(["01", "13", "47"], "48") + [column_vector("13", "prefecture", prefectures["13"]["prefecture"]), column_vector("01", "prefecture_kana", prefectures["01"]["prefecture_kana"])],
        evidence_items=items,
        tests=lookup_tests(prefectures, [("13", "prefecture"), ("01", "rows")]),
        notes=(
            f"Japan Post's utf_ken_all.csv lists {len(records)} rows of town-level postal codes, one per town area, with the "
            "all-Japan local government (JIS X0401/X0402) code, the seven-digit postal code and the prefecture, municipality and town "
            "names in half-width katakana and in kanji. This entry groups the rows by the first two digits of the JIS code (the "
            "prefecture): the prefecture's kanji and katakana names, the number of rows, of distinct postal codes and of distinct "
            "municipality codes. The companion entry keeps the full rows for two central Tokyo wards. " + JP_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["postal-codes", "japan-post", "prefectures", "weights", "japan"],
        use_cases=["address-generation", "logistics", "market-sizing"],
        assumed=[
            accessed_assumption(),
            {"parameter": "rows[*]", "value": "row, distinct postal code and distinct municipality counts per prefecture", "method": "derived", "rationale": "The file lists individual town rows; the per-prefecture figures are counts over rows sharing the first two JIS digits."},
        ],
    )
    detail = rule_entry(
        "jp-japanpost-postal-codes-tokyo-central-wards",
        "Japan Post seven-digit postal codes of Chiyoda and Chuo wards, Tokyo, with ward and town names in kanji and kana",
        "geography",
        "JP",
        valid_from=ACCESSED.isoformat(),
        implementation="almanac.rules.lookup_table",
        parameters={"key": "seven-digit postal code", "jis_codes": list(TOKYO_WARDS), "source_member": member, "rows": wards},
        vectors=membership_vectors([chiyoda[2], chuo[2]], "0600000") + [column_vector(chiyoda[2], "city", chiyoda[7]), column_vector(chuo[2], "jis_code", TOKYO_WARDS[1])],
        evidence_items=items,
        tests=lookup_tests(wards, [(chiyoda[2], "city"), (chuo[2], "jis_code")]),
        notes=(
            "The rows of Japan Post's utf_ken_all.csv whose local government code is 13101 or 13102 (Chiyoda-ku and Chuo-ku in "
            "Tokyo), regrouped by seven-digit postal code: the JIS code, the ward name in kanji and half-width katakana, and "
            "the list of town areas (kanji and kana) the code covers. Rows the file splits because a town name exceeds its field width "
            "appear as separate towns, as published. Flag columns are not copied. " + JP_NOTE + " " + accessed_assumption()["rationale"]
        ),
        status="license-review",
        tags=["postal-codes", "japan-post", "tokyo", "code-list", "japan"],
        use_cases=["address-generation", "logistics"],
        assumed=[accessed_assumption()],
    )
    return summary, detail


def main() -> None:
    cog, insee_licence = stable(COG_ZIP_URL), stable(INSEE_LICENCE_URL)
    write(cog_regions(cog, insee_licence))
    write(cog_departements(cog, insee_licence))
    for entry in cog_communes(cog, insee_licence):
        write(entry)
    nuts = stable(NUTS_URL)
    write(nuts_codes(nuts))
    write(nuts3_typologies(nuts))
    write(abs_postal_areas(stable(POA_URL)))
    for entry in japan_post(stable(KEN_ALL_URL), stable(KEN_ALL_README_URL)):
        write(entry)


if __name__ == "__main__":
    main()

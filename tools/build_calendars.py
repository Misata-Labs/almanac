"""Regenerate the public holiday calendar entries from their official sources.

Each entry is a ``almanac.rules.holiday_list`` rule: a dated list read from a
government feed (Japan, France, Hong Kong, Australia, Singapore, Spain, India)
or a recurring list read from a statute or ministry page (Mexico, Belgium,
Ireland). Every date comes from the fetched resource; nothing is typed in.
Run from the repository root:

    uv run python tools/build_calendars.py
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ACCESSED, evidence, fetch, write  # noqa: E402

TAGS = ["calendar", "holidays", "business-days"]
USE_CASES = ["payroll-demo", "settlement-calendar", "scheduling-demo", "logistics-demo"]
IMPLEMENTATION = "almanac.rules.holiday_list"

JP_CSV = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
JP_TERMS = "https://www.cao.go.jp/notice/rule.html"
FR_API = "https://calendrier.api.gouv.fr/jours-feries/{zone}.json"
FR_OPENAPI = "https://calendrier.api.gouv.fr/jours-feries/openapi.yml"
FR_OVERSEAS_ZONES = ("guadeloupe", "guyane", "la-reunion", "martinique", "mayotte", "saint-barthelemy", "saint-martin")
HK_JSON = "https://www.1823.gov.hk/common/ical/en.json"
HK_TERMS = "https://data.gov.hk/en/terms-and-conditions"
AU_CSV = "https://data.gov.au/data/dataset/b1bc6077-dadd-4f61-9f8c-002ab2cdff10/resource/33673aca-0857-42e5-b8f0-9981b4755686/download/australian-public-holidays-combined-2021-2025.csv"
AU_PACKAGE = "https://data.gov.au/data/api/3/action/package_show?id=australian-holidays-machine-readable-dataset"
SG_API = "https://data.gov.sg/api/action/datastore_search?resource_id=d_8ef23381f9417e4d4254ee8b4dcdb176&limit=500"
SG_METADATA = "https://api-production.data.gov.sg/v2/public/api/datasets/d_8ef23381f9417e4d4254ee8b4dcdb176/metadata"
ES_XML = "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2025-21667"
ES_PDF = "https://www.boe.es/boe/dias/2025/10/28/pdfs/BOE-A-2025-21667.pdf"
ES_INHABILES_XML = "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2025-23702"
IN_PDF = "https://cag.gov.in/uploads/media/Holiday-List-2026-069521fe6f358d0-89936988.pdf"
MX_PDF = "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf"
BE_FR = "https://emploi.belgique.be/fr/themes/jours-feries-et-conges/jours-feries"
BE_NL = "https://werk.belgie.be/nl/themas/feestdagen-en-verloven/feestdagen"
IE_ACT = "https://revisedacts.lawreform.ie/eli/1997/act/20/revised/en/html"
IE_SI = "https://www.irishstatutebook.ie/eli/2022/si/50/made/en/html"

UNSTATED = "unstated"


# --- resource text and snippet checks -------------------------------------------------------------


def resource_text(raw: bytes) -> str:
    """The text the verifier searches: pypdf extraction for a PDF, UTF-8 decoding otherwise."""
    if raw.startswith(b"%PDF"):
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    return raw.decode("utf-8", errors="replace")


def collapse(text: str) -> str:
    return " ".join(text.split())


def checked(item: dict[str, Any], raw: bytes) -> dict[str, Any]:
    """Fail early when an evidence value or snippet would not be found by the verifier."""
    text = collapse(resource_text(raw))
    for field in ("value", "snippet"):
        needle = collapse(str(item[field]))
        if needle not in text:
            raise ValueError(f"{field} {needle!r} not found in {item['url']}")
    if len(item["snippet"].split()) > 24:
        raise ValueError(f"snippet too long for {item['url']}")
    return item


def html_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.S)
    return collapse(html.unescape(re.sub(r"<[^>]+>", " ", text)))


# --- shared entry shape ---------------------------------------------------------------------------


def year_span(records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    years = sorted({int(r["date"][:4]) for r in records})
    return years[0], years[-1]


def merge_by_date(rows: Iterable[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Collapse (date, name, region) rows into one record per date and name carrying the regions."""
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for day, name, region in rows:
        grouped[(day, name)].add(region)
    return [{"date": day, "name": name, "regions": sorted(regions)} for (day, name), regions in sorted(grouped.items())]


def first(records: list[dict[str, Any]], year: int, **match: Any) -> dict[str, Any]:
    """The first record of ``year`` whose fields equal ``match`` (``name_contains`` tests a substring)."""
    for record in records:
        if not record["date"].startswith(f"{year}-"):
            continue
        if "name_contains" in match and match["name_contains"] not in record["name"]:
            continue
        if all(record.get(k) == v for k, v in match.items() if k != "name_contains"):
            return record
    raise LookupError(f"no {match} record in {year}")


def year_count_tests(records: list[dict[str, Any]], years: Iterable[int], region: str | None = None) -> list[dict[str, Any]]:
    tests = []
    for year in years:
        dates = {r["date"] for r in records if r["date"].startswith(f"{year}-") and (region is None or region in r.get("regions", [region]))}
        label = f"count[{region},{year}]" if region else f"count[{year}]"
        tests.append({"statistic": label, "expected": len(dates), "tolerance": 0})
    return tests


def entry(**fields: Any) -> dict[str, Any]:
    """Assemble one holiday-list rule entry with the shared tags, use cases and test skeleton."""
    tests = [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *fields.pop("tests", [])]
    parameters = fields.pop("parameters")
    return {
        "id": fields.pop("id"),
        "title": fields.pop("title"),
        "kind": "rule",
        "domain": "calendar",
        "region": fields.pop("region"),
        "status": fields.pop("status", "license-review"),
        "tier": fields.pop("tier"),
        "valid_from": fields.pop("valid_from"),
        "valid_to": fields.pop("valid_to"),
        "tags": TAGS + fields.pop("extra_tags", []),
        "use_cases": USE_CASES,
        "spec": {"implementation": IMPLEMENTATION, "parameters": parameters, "vectors": fields.pop("vectors")},
        "evidence": fields.pop("evidence"),
        "assumed": fields.pop("assumed", []),
        "tests": tests,
        "notes": fields.pop("notes"),
        **fields,
    }


def business_day_vectors(records: list[dict[str, Any]], year: int, region: str | None = None) -> list[dict[str, Any]]:
    """Vectors exercising the weekend and holiday arithmetic around the last published holiday of ``year``."""
    from almanac.rules import holiday_list

    parameters = {"holidays": records}
    last = max(r["date"] for r in records if r["date"].startswith(f"{year}-") and (region is None or region in r.get("regions", [region])))
    day = date.fromisoformat(last)
    region_key = {"region": region} if region else {}
    following = holiday_list.next_business_day(parameters, day, region).isoformat()
    return [
        {"input": {"op": "is_business_day", "date": last, **region_key}, "expected": False, "origin": "derived", "note": "a listed holiday is not a business day"},
        {"input": {"op": "next_business_day", "date": last, **region_key}, "expected": following, "origin": "derived", "note": "first weekday after the holiday that is not itself listed"},
    ]


# --- Japan ----------------------------------------------------------------------------------------


def build_japan(csv_raw: bytes, terms_raw: bytes) -> dict[str, Any]:
    rows = csv_raw.decode("cp932").splitlines()[1:]
    records = []
    for row in rows:
        day, name = row.split(",", 1)
        records.append({"date": datetime.strptime(day, "%Y/%m/%d").date().isoformat(), "name": name, "source_date": day})
    start, end = year_span(records)
    last = records[-1]
    may_2026 = [r for r in records if r["date"].startswith("2026-05")]
    vectors = [
        {"input": last["date"], "expected": True, "origin": "source", "note": f"{last['name']}, the last row of the file"},
        {"input": records[0]["date"], "expected": True, "origin": "source", "note": "the first row of the file"},
        *[{"input": r["date"], "expected": True, "origin": "source", "note": r["name"]} for r in may_2026],
        {"input": "2026-05-02", "expected": False, "origin": "derived", "note": "a Saturday between the May holidays, not listed"},
        *business_day_vectors(records, 2027),
    ]
    tests = year_count_tests(records, range(2024, end + 1)) + [{"statistic": "count", "expected": len(records), "tolerance": 0}]
    return entry(
        id="jp-public-holidays",
        title=f"Japan national holidays and substitute holidays (Cabinet Office list), {start} to {end}",
        region="JP",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["public-holidays"],
        parameters={"holidays": [{"date": r["date"], "name": r["name"]} for r in records]},
        vectors=vectors,
        evidence=[
            checked(evidence("Cabinet Office, Government of Japan (内閣府)", "国民の祝日・休日 CSV (syukujitsu.csv), 1955 to 2027", JP_CSV, f"row {last['source_date']}", last["source_date"], "date", f"{last['source_date']},", UNSTATED, csv_raw), csv_raw),
            checked(evidence("Cabinet Office, Government of Japan (内閣府)", "国民の祝日・休日 CSV (syukujitsu.csv), 1955 to 2027", JP_CSV, f"row {records[0]['source_date']}", records[0]["source_date"], "date", f"{records[0]['source_date']},", UNSTATED, csv_raw), csv_raw),
            checked(evidence("Cabinet Office, Government of Japan (内閣府)", "内閣府ホームページ利用規約 (website terms of use)", JP_TERMS, "コンテンツの利用ルールについて", "公共データ利用規約（第1.0版）", "text", "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0", UNSTATED, terms_raw, role="supporting"), terms_raw),
        ],
        tests=tests,
        notes=(
            f"Every row of the Cabinet Office CSV of 国民の祝日・休日 (national holidays and the substitute and bridge holidays "
            f"that the Act on National Holidays creates), {len(records)} dates from {start} to {end}, with the Japanese names "
            "as published. The file is Shift-JIS encoded; the builder decodes it and converts the YYYY/M/D dates to ISO. "
            "Future years are republished each February after the vernal and autumnal equinox days are fixed, so the file "
            "grows by one year at a time; re-run the builder when it does. The Cabinet Office terms page says its content "
            "falls under the Digital Agency's Public Data Terms of Use v1.0 unless marked otherwise; that is not an SPDX "
            "licence, so the licence is recorded as unstated and the entry held for review."
        ),
    )


# --- France ---------------------------------------------------------------------------------------


def fr_records(raw: bytes) -> list[dict[str, Any]]:
    return [{"date": day, "name": name} for day, name in sorted(json.loads(raw).items())]


def fr_evidence(zone: str, raw: bytes, record: dict[str, Any]) -> dict[str, Any]:
    return checked(
        evidence("Direction interministérielle du numérique (DINUM), API jours fériés (calendrier.api.gouv.fr)", f"Jours fériés, zone {zone} (JSON)", FR_API.format(zone=zone), f'key "{record["date"]}"', record["date"], "date", f'"{record["date"]}": "{record["name"]}"', UNSTATED, raw),
        raw,
    )


def fr_openapi_evidence(raw: bytes) -> dict[str, Any]:
    return checked(
        evidence("Direction interministérielle du numérique (DINUM), API jours fériés (calendrier.api.gouv.fr)", "API jours fériés OpenAPI description", FR_OPENAPI, "paths./{zone}.json.get.summary", "20 ans dans le passé et 5 ans dans le futur", "text", "Liste les jours fériés pour une zone, 20 ans dans le passé et 5 ans dans le futur", UNSTATED, raw, role="supporting"),
        raw,
    )


FR_NOTE = (
    "The API serves the list that Etalab maintains from the Code du travail (article L3133-1) and the specific "
    "provisions for each zone, twenty years back and five ahead. Names are the French labels the API returns. "
    "No licence is stated by the API itself, so the licence is recorded as unstated and the entry held for review."
)


def build_france(zone: str, entry_id: str, title: str, raw: bytes, openapi_raw: bytes, notes: str) -> dict[str, Any]:
    records = fr_records(raw)
    start, end = year_span(records)
    easter_monday = first(records, 2026, name="Lundi de Pâques")
    vectors = [
        {"input": easter_monday["date"], "expected": True, "origin": "source", "note": "Lundi de Pâques 2026"},
        {"input": first(records, 2027, name="Lundi de Pâques")["date"], "expected": True, "origin": "source", "note": "Lundi de Pâques 2027"},
        {"input": first(records, 2026, name="14 juillet")["date"], "expected": True, "origin": "source"},
        {"input": "2026-04-05", "expected": False, "origin": "derived", "note": "Easter Sunday itself is not listed"},
        *business_day_vectors(records, 2026),
    ]
    named = [first(records, 2026, name=n) for n in ("Vendredi saint", "2ème jour de Noël") if any(r["name"] == n for r in records)]
    return entry(
        id=entry_id,
        title=f"{title}, {start} to {end}",
        region="FR",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["jours-feries"],
        parameters={"holidays": records},
        vectors=vectors,
        evidence=[fr_evidence(zone, raw, easter_monday), *[fr_evidence(zone, raw, r) for r in named], fr_openapi_evidence(openapi_raw)],
        tests=year_count_tests(records, range(2024, 2029)) + [{"statistic": "count", "expected": len(records), "tolerance": 0}],
        notes=notes + " " + FR_NOTE,
    )


def build_france_overseas(zone_raws: dict[str, bytes], openapi_raw: bytes, metropole_raw: bytes) -> dict[str, Any]:
    metropole = {(r["date"], r["name"]) for r in fr_records(metropole_raw)}
    rows = [(r["date"], r["name"], zone) for zone, raw in zone_raws.items() for r in fr_records(raw)]
    records = merge_by_date(rows)
    start, end = year_span(records)
    local = [r for r in records if (r["date"], r["name"]) not in metropole and r["date"].startswith("2026-")]
    items = []
    for zone, raw in zone_raws.items():
        own = next(r for r in local if zone in r["regions"])
        items.append(fr_evidence(zone, raw, {"date": own["date"], "name": own["name"]}))
    vectors = [
        *[{"input": {"date": r["date"], "region": r["regions"][0]}, "expected": True, "origin": "source", "note": f"{r['name']} ({r['regions'][0]})"} for r in local],
        {"input": {"date": local[0]["date"], "region": "guyane"} if local[0]["regions"] != ["guyane"] else {"date": local[1]["date"], "region": "guyane"}, "expected": False, "origin": "derived", "note": "a commemoration specific to another zone"},
        {"input": {"date": "2026-07-14", "region": "mayotte"}, "expected": True, "origin": "source"},
        *business_day_vectors(records, 2026, "la-reunion"),
    ]
    tests = [t for zone in zone_raws for t in year_count_tests(records, [2026], zone)]
    return entry(
        id="fr-jours-feries-outre-mer",
        title=f"France: jours fériés in the overseas departments and collectivities with their own list, {start} to {end}",
        region="FR",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["jours-feries", "outre-mer"],
        parameters={"holidays": records, "regions": list(zone_raws)},
        vectors=vectors,
        evidence=[*items, fr_openapi_evidence(openapi_raw)],
        tests=tests,
        notes=(
            "One record per date and name with the zones it applies to, merged from the API's per-zone lists for "
            + ", ".join(zone_raws)
            + ". These zones add their own commemorations (chiefly the abolition of slavery, on a different date in each) "
            "to the metropolitan list. The API also accepts nouvelle-caledonie, polynesie-francaise, saint-pierre-et-miquelon "
            "and wallis-et-futuna but returns the metropolitan list byte for byte for them, so they are left out here; use "
            "fr-jours-feries-metropole for those. " + FR_NOTE
        ),
    )


# --- Hong Kong -------------------------------------------------------------------------------------


def build_hong_kong(raw: bytes, terms_raw: bytes) -> dict[str, Any]:
    events = json.loads(raw.decode("utf-8-sig"))["vcalendar"][0]["vevent"]
    records = []
    for event in events:
        stamp = event["dtstart"][0]
        records.append({"date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}", "name": event["summary"], "uid": event["uid"]})
    start, end = year_span(records)
    new_year_2026 = first(records, 2026, name="The first day of January")
    lunar = [r for r in records if r["date"].startswith("2026-") and "Lunar New Year" in r["name"]]
    vectors = [
        {"input": new_year_2026["date"], "expected": True, "origin": "source"},
        *[{"input": r["date"], "expected": True, "origin": "source", "note": r["name"]} for r in lunar],
        {"input": first(records, 2027, name="Christmas Day")["date"], "expected": True, "origin": "source"},
        {"input": "2026-02-16", "expected": False, "origin": "derived", "note": "the day before Lunar New Year 2026 is not listed"},
        *business_day_vectors(records, 2026),
    ]
    return entry(
        id="hk-public-holidays",
        title=f"Hong Kong public holidays (1823 government calendar feed), {start} to {end}",
        region="HK",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["public-holidays", "general-holidays"],
        parameters={"holidays": [{"date": r["date"], "name": r["name"]} for r in records]},
        vectors=vectors,
        evidence=[
            checked(evidence("1823, Government of the Hong Kong Special Administrative Region", "Hong Kong Public Holidays iCalendar feed (JSON rendering)", HK_JSON, f'vevent uid {new_year_2026["uid"]}', new_year_2026["uid"], "text", f'"uid": "{new_year_2026["uid"]}"', UNSTATED, raw), raw),
            checked(evidence("1823, Government of the Hong Kong Special Administrative Region", "Hong Kong Public Holidays iCalendar feed (JSON rendering)", HK_JSON, "vcalendar[0].x-wr-calname", "Hong Kong Public Holidays", "text", '"x-wr-calname": "Hong Kong Public Holidays"', UNSTATED, raw), raw),
            checked(evidence("Digital Policy Office, Government of the Hong Kong Special Administrative Region", "DATA.GOV.HK Terms and Conditions of Use", HK_TERMS, "Use of Data on DATA.GOV.HK", "for both commercial and non-commercial purposes on a free-of-charge basis", "text", "You are allowed to browse, download, distribute, reproduce, hyperlink to, and print the Data", UNSTATED, terms_raw, role="supporting"), terms_raw),
        ],
        tests=year_count_tests(records, range(start, end + 1)) + [{"statistic": "count", "expected": len(records), "tolerance": 0}],
        notes=(
            "Every all-day event in the public holidays calendar that the 1823 contact centre publishes for the Government "
            f"of Hong Kong, {len(records)} dates from {start} to {end}, with the English summaries as published (the feed "
            "is also listed on DATA.GOV.HK). General holidays are gazetted under the General Holidays Ordinance (Cap. 149) "
            "each year, so a new year appears in the feed only once gazetted. The DATA.GOV.HK terms allow free reuse with "
            "attribution but are not an SPDX licence; the entry is held for licence review."
        ),
    )


# --- Australia -------------------------------------------------------------------------------------


def build_australia(csv_raw: bytes, package_raw: bytes) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_raw.decode("utf-8-sig")))
    rows, undated = [], []
    for row in reader:
        stamp = row["Date"].strip()
        if not re.fullmatch(r"\d{8}", stamp):
            undated.append(f"{row['Holiday Name'].strip()} ({row['Jurisdiction'].strip().lower()})")
            continue
        rows.append((f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}", row["Holiday Name"].strip(), row["Jurisdiction"].strip().lower()))
    records = merge_by_date(rows)
    jurisdictions = sorted({region for _, _, region in rows})
    start, end = year_span(records)
    package = json.loads(package_raw)["result"]
    christmas_2025 = first(records, 2025, name="Christmas Day")
    melbourne_cup = first(records, 2025, name_contains="Melbourne Cup")
    vectors = [
        {"input": {"date": christmas_2025["date"], "region": "nsw"}, "expected": True, "origin": "source"},
        {"input": {"date": melbourne_cup["date"], "region": melbourne_cup["regions"][0]}, "expected": True, "origin": "source", "note": melbourne_cup["name"]},
        {"input": {"date": melbourne_cup["date"], "region": "nsw"}, "expected": False, "origin": "derived", "note": "a Victorian holiday is not a New South Wales holiday"},
        {"input": {"date": first(records, 2025, name_contains="Anzac")["date"], "region": "wa"}, "expected": True, "origin": "source"},
        *business_day_vectors(records, 2025, "qld"),
    ]
    tests = [t for region in jurisdictions for t in year_count_tests(records, [2025], region)]
    return entry(
        id="au-public-holidays",
        title=f"Australian public holidays by state and territory (data.gov.au combined dataset), {start} to {end}",
        region="AU",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["public-holidays"],
        parameters={"holidays": records, "regions": jurisdictions},
        vectors=vectors,
        evidence=[
            checked(evidence("Department of the Prime Minister and Cabinet (data.gov.au)", "Australian public holidays combined (2021-2025), CSV", AU_CSV, f"row Date={christmas_2025['date'].replace('-', '')}, Jurisdiction=nsw", christmas_2025["date"].replace("-", ""), "date", f"{christmas_2025['date'].replace('-', '')},Christmas Day", "CC-BY-3.0-AU", csv_raw), csv_raw),
            checked(evidence("Department of the Prime Minister and Cabinet (data.gov.au)", "Australian public holidays combined (2021-2025), CSV", AU_CSV, "header row", "ID,Date,Holiday Name,Information,More Information,Jurisdiction", "text", "ID,Date,Holiday Name,Information,More Information,Jurisdiction", "CC-BY-3.0-AU", csv_raw), csv_raw),
            checked(evidence("Department of the Prime Minister and Cabinet (data.gov.au)", "CKAN package metadata for the Australian holidays machine-readable dataset", AU_PACKAGE, "result.license_title", package["license_title"], "text", '"license_title": "Creative Commons Attribution 3.0 Australia"', "CC-BY-3.0-AU", package_raw, role="supporting"), package_raw),
        ],
        tests=tests + [{"statistic": "count", "expected": len(records), "tolerance": 0}],
        notes=(
            "Every row of the combined 2021 to 2025 CSV in the Australian public holidays dataset on data.gov.au, merged into "
            "one record per date and holiday name carrying the jurisdictions it applies to (" + ", ".join(jurisdictions) + "). "
            "Names are the published names, which include the observed and additional days each jurisdiction gazettes. "
            "The dataset's CKAN record states Creative Commons Attribution 3.0 Australia; that licence is not in the "
            "verifier's permissive list, so the entry is held for review. The publisher has not released a 2026 file in "
            "this dataset at the time of building, so the entry stops at the end of 2025."
            + (f" {len(undated)} row(s) carry no date in the file and are left out: " + "; ".join(undated) + "." if undated else "")
        ),
    )


# --- Singapore -------------------------------------------------------------------------------------


def build_singapore(api_raw: bytes, metadata_raw: bytes) -> dict[str, Any]:
    result = json.loads(api_raw)["result"]
    records = [{"date": r["date"], "name": r["holiday"]} for r in sorted(result["records"], key=lambda r: r["date"])]
    if len(records) != result["total"]:
        raise ValueError("Singapore datastore page does not hold every record")
    start, end = year_span(records)
    metadata = json.loads(metadata_raw)["data"]
    new_year_2026 = first(records, 2026, name_contains="New Year")
    observed = [r for r in records if r["date"].startswith("2027-") and "Observed" in r["name"]]
    vectors = [
        {"input": new_year_2026["date"], "expected": True, "origin": "source"},
        *[{"input": r["date"], "expected": True, "origin": "source", "note": r["name"]} for r in observed],
        {"input": first(records, 2027, name="Deepavali")["date"], "expected": True, "origin": "source"},
        {"input": "2026-01-02", "expected": False, "origin": "derived"},
        *business_day_vectors(records, 2027),
    ]
    return entry(
        id="sg-public-holidays",
        title=f"Singapore public holidays (Ministry of Manpower list on data.gov.sg), {start} to {end}",
        region="SG",
        tier="A",
        valid_from=f"{start}-01-01",
        valid_to=f"{end}-12-31",
        extra_tags=["public-holidays"],
        parameters={"holidays": records},
        vectors=vectors,
        evidence=[
            checked(evidence("Ministry of Manpower via data.gov.sg (Government Technology Agency)", "Singapore Public Holidays (consolidated), datastore_search API", SG_API, f'records[date="{new_year_2026["date"]}"]', new_year_2026["date"], "date", f'"date":"{new_year_2026["date"]}","day":"Thursday"', UNSTATED, api_raw), api_raw),
            checked(evidence("Ministry of Manpower via data.gov.sg (Government Technology Agency)", "Singapore Public Holidays (consolidated), datastore_search API", SG_API, "result.total", result["total"], "count", f'"total":{result["total"]}', UNSTATED, api_raw), api_raw),
            checked(evidence("Ministry of Manpower via data.gov.sg (Government Technology Agency)", "Dataset metadata for Singapore Public Holidays (consolidated)", SG_METADATA, "data.managedBy", metadata["managedBy"], "text", '"managedBy":"Ministry of Manpower"', UNSTATED, metadata_raw, role="supporting"), metadata_raw),
        ],
        tests=year_count_tests(records, range(start, end + 1)) + [{"statistic": "count", "expected": len(records), "tolerance": 0}],
        notes=(
            f"Every record of the consolidated public holidays dataset the Ministry of Manpower manages on data.gov.sg, {len(records)} "
            f"dates from {start} to {end}, read through the CKAN datastore API. Names are as published; a holiday falling on a "
            "Sunday is followed by a separate '(Observed)' record for the Monday, which the Holidays Act provides. The dataset "
            "metadata says it is refreshed annually when the next year's list is released. data.gov.sg content is offered under "
            "the Singapore Open Data Licence, which is not an SPDX licence; the entry is held for review."
        ),
    )


# --- Spain -----------------------------------------------------------------------------------------

ES_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
ES_KINDS = {"*": "national", "**": "national-substitutable", "***": "regional"}
ES_REGIONS = {
    "headerAndalucia": "andalucia", "headerAragon": "aragon", "headerAsturias": "asturias", "headerBaleares": "illes-balears",
    "headerCanarias": "canarias", "headerCantabria": "cantabria", "headerCastillaLM": "castilla-la-mancha", "headerCastillaYL": "castilla-y-leon",
    "headerCataluna": "cataluna", "headerExtremadura": "extremadura", "headerGalicia": "galicia", "headerMadrid": "madrid", "headerMurcia": "murcia",
    "headerNavarra": "navarra", "headerPaisVasco": "pais-vasco", "headerRioja": "la-rioja", "headerValencia": "comunitat-valenciana",
    "headerCeuta": "ceuta", "headerMelilla": "melilla",
}


def parse_spain(xml_raw: bytes) -> tuple[int, list[dict[str, Any]], list[str]]:
    text = xml_raw.decode("utf-8")
    year = int(re.search(r"fiestas laborales para el año (\d{4})", text).group(1))
    table = text[text.index("<table") : text.index("</table>")]
    header_ids = re.findall(r'<th axis="comunidad"[^>]*id="(header\w+)"', table)
    regions = [ES_REGIONS[h] for h in header_ids]
    records, month = [], 0
    for row in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        cells = [html.unescape(re.sub("<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not cells:
            continue
        label, markers = cells[0], cells[1:]
        if label.lower() in ES_MONTHS:
            month = ES_MONTHS[label.lower()]
            continue
        day, name = label.split(" ", 1)
        by_kind: dict[str, list[str]] = defaultdict(list)
        for region, marker in zip(regions, markers):
            if marker:
                by_kind[ES_KINDS[marker]].append(region)
        for kind, kind_regions in by_kind.items():
            records.append({"date": date(year, month, int(day)).isoformat(), "name": name.rstrip("."), "regions": kind_regions, "kind": kind})
    return year, sorted(records, key=lambda r: (r["date"], r["kind"], r["name"])), regions


def build_spain(xml_raw: bytes, pdf_raw: bytes, inhabiles_raw: bytes) -> dict[str, Any]:
    year, records, regions = parse_spain(xml_raw)
    national = [r for r in records if r["kind"] == "national"]
    sant_jordi = first(records, year, name="San Jorge/Día de Aragón")
    easter_monday = first(records, year, name="Lunes de Pascua")
    vectors = [
        {"input": {"date": national[0]["date"], "region": "madrid"}, "expected": True, "origin": "source", "note": national[0]["name"]},
        {"input": {"date": sant_jordi["date"], "region": "aragon"}, "expected": True, "origin": "source", "note": sant_jordi["name"]},
        {"input": {"date": sant_jordi["date"], "region": "madrid"}, "expected": False, "origin": "derived", "note": "the regional holiday of Aragón is not a Madrid holiday"},
        {"input": {"date": easter_monday["date"], "region": "cataluna"}, "expected": True, "origin": "source"},
        {"input": {"date": easter_monday["date"], "region": "andalucia"}, "expected": False, "origin": "derived", "note": "Andalucía took Jueves Santo instead of Lunes de Pascua"},
        *business_day_vectors(records, year, "galicia"),
    ]
    tests = [t for region in regions for t in year_count_tests(records, [year], region)]
    return entry(
        id=f"es-fiestas-laborales-{year}",
        title=f"Spain: national and autonomous-community public holidays (fiestas laborales) {year}, from the BOE resolution",
        region="ES",
        tier="A",
        valid_from=f"{year}-01-01",
        valid_to=f"{year}-12-31",
        extra_tags=["fiestas-laborales", "comunidades-autonomas"],
        parameters={"holidays": records, "regions": regions},
        vectors=vectors,
        evidence=[
            checked(evidence("Ministerio de Trabajo y Economía Social, via Agencia Estatal Boletín Oficial del Estado", f"Resolución de 17 de octubre de 2025, relación de fiestas laborales para el año {year} (BOE-A-2025-21667, XML)", ES_XML, "metadatos/identificador", "BOE-A-2025-21667", "text", f"relación de fiestas laborales para el año {year}", UNSTATED, xml_raw), xml_raw),
            checked(evidence("Ministerio de Trabajo y Economía Social, via Agencia Estatal Boletín Oficial del Estado", f"Resolución de 17 de octubre de 2025, relación de fiestas laborales para el año {year} (BOE-A-2025-21667, XML)", ES_XML, "texto/table (Distribución de las fiestas nacionales y autonómicas)", "Fiesta Nacional no sustituible (*)", "text", "Fiesta de Comunidad Autónoma (***)", UNSTATED, xml_raw), xml_raw),
            checked(evidence("Ministerio de Trabajo y Economía Social, via Agencia Estatal Boletín Oficial del Estado", f"Resolución de 17 de octubre de 2025, relación de fiestas laborales para el año {year} (BOE-A-2025-21667, PDF)", ES_PDF, "page 1, title", "BOE-A-2025-21667", "text", "Fiesta Nacional no sustituible", UNSTATED, pdf_raw, role="supporting"), pdf_raw),
            checked(evidence("Secretaría de Estado de Función Pública, via Agencia Estatal Boletín Oficial del Estado", f"Resolución de 18 de noviembre de 2025, calendario de días inhábiles de la AGE para {year} (BOE-A-2025-23702, XML)", ES_INHABILES_XML, "texto, Enero", "Día 1: Inhábil en todo el territorio nacional.", "text", "Día 6: Inhábil en todo el territorio nacional.", UNSTATED, inhabiles_raw, role="supporting"), inhabiles_raw),
        ],
        tests=tests,
        notes=(
            f"The {year} table of fiestas laborales published in the Boletín Oficial del Estado, read from the BOE's XML "
            "rendering of the resolution: one record per date, name and kind, with the autonomous communities and the "
            "cities of Ceuta and Melilla it applies to. kind is 'national' for the non-substitutable national holidays "
            "(marked * in the table), 'national-substitutable' for national holidays the community chose to keep (**) and "
            "'regional' for the community's own holidays (***). Island and local holidays in the resolution's notes "
            "(Canarias by island, Arán) and municipal holidays are not included. The AGE días inhábiles resolution is "
            "cited as corroboration of the national dates. The BOE states no SPDX licence; held for licence review."
        ),
    )


# --- India -----------------------------------------------------------------------------------------

IN_ROW = re.compile(r"(\d+) (.+?) (\d{2}/\d{2}/\d{4}) ([A-Z][a-z]+day)")


def parse_india(pdf_raw: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages = [collapse(page.extract_text() or "") for page in PdfReader(io.BytesIO(pdf_raw)).pages]
    lists = []
    for page in pages:
        rows = []
        body = page.split("Holiday Date Day", 1)[-1]
        for number, name, day, _weekday in IN_ROW.findall(body):
            rows.append({"date": datetime.strptime(day, "%d/%m/%Y").date().isoformat(), "name": collapse(name).replace("’", "'"), "source_date": day})
        if rows:
            lists.append(rows)
    return lists[0], lists[1]


def build_india(pdf_raw: bytes) -> dict[str, Any]:
    gazetted, restricted = parse_india(pdf_raw)
    year = int(gazetted[0]["date"][:4])
    republic_day = next(r for r in gazetted if r["name"] == "Republic Day")
    christmas = next(r for r in gazetted if r["name"] == "Christmas Day")
    new_year = next(r for r in restricted if "New Year" in r["name"])
    holidays = [{"date": r["date"], "name": r["name"]} for r in gazetted]
    vectors = [
        {"input": republic_day["date"], "expected": True, "origin": "source"},
        {"input": christmas["date"], "expected": True, "origin": "source"},
        {"input": next(r for r in gazetted if r["name"] == "Diwali (Deepavali)")["date"], "expected": True, "origin": "source"},
        {"input": new_year["date"], "expected": False, "origin": "source", "note": "a restricted holiday is optional and not a closed day"},
        *business_day_vectors(holidays, year),
    ]
    return entry(
        id=f"in-central-government-holidays-{year}-karnataka",
        title=f"India: closed and restricted holidays for Central Government offices in Karnataka, {year} (CAG office list)",
        region="IN",
        tier="B",
        valid_from=f"{year}-01-01",
        valid_to=f"{year}-12-31",
        extra_tags=["gazetted-holidays", "restricted-holidays", "central-government"],
        parameters={"holidays": holidays, "restricted_holidays": [{"date": r["date"], "name": r["name"]} for r in restricted]},
        vectors=vectors,
        evidence=[
            checked(evidence("Office of the Comptroller and Auditor General of India (cag.gov.in)", f"Holiday List {year}: holidays to be observed in Central Government offices in Karnataka", IN_PDF, "page 1, Annexure I", republic_day["source_date"], "date", f"HOLIDAYS TO BE OBSERVED IN CENTRAL GOVERNMENT OFFICES IN KARNATAKA DURING THE YEAR {year}", UNSTATED, pdf_raw), pdf_raw),
            checked(evidence("Office of the Comptroller and Auditor General of India (cag.gov.in)", f"Holiday List {year}: holidays to be observed in Central Government offices in Karnataka", IN_PDF, "page 2, Annexure II", new_year["source_date"], "date", f"LIST OF RESTRICTED HOLIDAYS FOR THE CALENDAR YEAR {year}", UNSTATED, pdf_raw), pdf_raw),
        ],
        tests=[
            {"statistic": f"count[{year}]", "expected": len({r["date"] for r in holidays}), "tolerance": 0},
            {"statistic": "list_length[restricted_holidays]", "expected": len(restricted), "tolerance": 0},
        ],
        notes=(
            f"The {len(holidays)} closed (gazetted) holidays in Annexure I and the {len(restricted)} restricted holidays in "
            f"Annexure II of the {year} holiday list published by the Comptroller and Auditor General of India for Central "
            "Government offices in Karnataka. Central Government holiday lists derive from the Department of Personnel and "
            "Training office memorandum for the year (fourteen compulsory holidays plus three chosen by the Central Government "
            "Employees Welfare Coordination Committee of each state), and the DoPT circular host was unreachable when this "
            "entry was built, so this office list stands in for it and the regional choices are Karnataka's. Only the "
            "closed holidays enter the business-day rule; restricted holidays are kept under restricted_holidays. Dates for "
            "Id-ul-Fitr, Id-ul-Zuha, Muharram and Id-e-Milad can move with the lunar sighting."
        ),
    )


# --- Mexico ----------------------------------------------------------------------------------------

MX_HOLIDAYS = [
    {"name": "1o. de enero", "month": 1, "day": 1, "fraction": "I"},
    {"name": "Primer lunes de febrero (5 de febrero)", "month": 2, "weekday": "monday", "ordinal": "first", "fraction": "II"},
    {"name": "Tercer lunes de marzo (21 de marzo)", "month": 3, "weekday": "monday", "ordinal": "third", "fraction": "III"},
    {"name": "1o. de mayo", "month": 5, "day": 1, "fraction": "IV"},
    {"name": "16 de septiembre", "month": 9, "day": 16, "fraction": "V"},
    {"name": "Tercer lunes de noviembre (20 de noviembre)", "month": 11, "weekday": "monday", "ordinal": "third", "fraction": "VI"},
    {"name": "25 de diciembre", "month": 12, "day": 25, "fraction": "VIII"},
]


def build_mexico(pdf_raw: bytes) -> dict[str, Any]:
    pages = [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_raw)).pages]
    page_number = next(i for i, text in enumerate(pages, start=1) if "Artículo 74." in text)
    article = collapse(pages[page_number - 1])
    reform = re.search(r"Fracción reformada DOF (\d{2})-(\d{2})-(\d{4})", article)
    reform_date = date(int(reform.group(3)), int(reform.group(2)), int(reform.group(1))).isoformat()
    last_reform = re.search(r"Última Reforma DOF (\d{2})-(\d{2})-(\d{4})", collapse(pages[0])).group(0)
    for phrase in ("El 1o. de enero", "El primer lunes de febrero en conmemoración del 5 de febrero", "El tercer lunes de marzo en conmemoración del 21 de marzo", "El 1o. de mayo", "El 16 de septiembre", "El tercer lunes de noviembre en conmemoración del 20 de noviembre", "El 25 de diciembre"):
        if phrase not in article:
            raise ValueError(f"article 74 text changed: {phrase!r} missing")
    from almanac.rules import holiday_list

    parameters = {"holidays": MX_HOLIDAYS}
    computed = {r["fraction"]: r["date"] for r in holiday_list.holidays_in(parameters, 2026)}
    vectors = [
        {"input": {"year": 2026}, "expected": [{"date": r["date"], "name": r["name"]} for r in holiday_list.holidays_in(parameters, 2026)], "origin": "derived", "note": "article 74 applied to 2026"},
        {"input": computed["II"], "expected": True, "origin": "derived", "note": "first Monday of February 2026"},
        {"input": "2026-02-05", "expected": False, "origin": "derived", "note": "5 February itself is commemorated on the Monday"},
        {"input": computed["VI"], "expected": True, "origin": "derived", "note": "third Monday of November 2026"},
        {"input": "2026-09-16", "expected": True, "origin": "source"},
        {"input": {"op": "next_business_day", "date": "2026-12-25"}, "expected": "2026-12-28", "origin": "derived", "note": "25 December 2026 is a Friday"},
    ]
    return entry(
        id="mx-dias-de-descanso-obligatorio",
        title="Mexico: statutory rest days (días de descanso obligatorio) under article 74 of the Ley Federal del Trabajo",
        region="MX",
        tier="B",
        valid_from=reform_date,
        valid_to=None,
        extra_tags=["ley-federal-del-trabajo", "descanso-obligatorio"],
        parameters=parameters,
        vectors=vectors,
        evidence=[
            checked(evidence("Cámara de Diputados del H. Congreso de la Unión (Leyes Biblio)", f"Ley Federal del Trabajo, texto vigente ({last_reform})", MX_PDF, f"page {page_number}, Artículo 74", "Son días de descanso obligatorio", "text", "El tercer lunes de noviembre en conmemoración del 20 de noviembre", UNSTATED, pdf_raw), pdf_raw),
            checked(evidence("Cámara de Diputados del H. Congreso de la Unión (Leyes Biblio)", f"Ley Federal del Trabajo, texto vigente ({last_reform})", MX_PDF, f"page {page_number}, Artículo 74, fracción II", "El primer lunes de febrero en conmemoración del 5 de febrero", "text", "El tercer lunes de marzo en conmemoración del 21 de marzo", UNSTATED, pdf_raw), pdf_raw),
            checked(evidence("Cámara de Diputados del H. Congreso de la Unión (Leyes Biblio)", f"Ley Federal del Trabajo, texto vigente ({last_reform})", MX_PDF, f"page {page_number}, Artículo 74, fracción VII", reform.group(0), "text", "de cada seis años, cuando corresponda a la transmisión del Poder Ejecutivo", UNSTATED, pdf_raw), pdf_raw),
        ],
        assumed=[
            {"parameter": "holidays", "value": "fractions VII and IX omitted", "method": "derived", "rationale": "Fraction VII (1 October every six years when the federal executive changes) and fraction IX (election days set by electoral law) depend on events outside the statute's own text, so the rule models only the seven fixed and ordinal-weekday rest days."},
            {"parameter": "valid_from", "value": reform_date, "method": "derived", "rationale": "The date of the most recent reform of article 74 printed in the consolidated text; the seven modelled fractions predate it."},
        ],
        tests=[{"statistic": "count[2026]", "expected": len(MX_HOLIDAYS), "tolerance": 0}, {"statistic": "count[2027]", "expected": len(MX_HOLIDAYS), "tolerance": 0}],
        notes=(
            "Article 74 of the Ley Federal del Trabajo lists the days of obligatory rest: 1 January, the first Monday of "
            "February (for 5 February), the third Monday of March (for 21 March), 1 May, 16 September, the third Monday of "
            "November (for 20 November), 25 December, plus 1 October every six years at the change of federal executive and "
            "election days. The builder reads the consolidated text the Chamber of Deputies publishes and checks every "
            "modelled fraction's wording before writing the entry. The weekend is the default Saturday and Sunday; the law "
            "itself sets one rest day per six of work (article 69) rather than a weekend."
        ),
    )


# --- Belgium ---------------------------------------------------------------------------------------

BE_HOLIDAYS = [
    {"name": "1er janvier", "month": 1, "day": 1},
    {"name": "Lundi de Pâques", "easter_offset": 1},
    {"name": "1er mai (Fête du travail)", "month": 5, "day": 1},
    {"name": "Ascension", "easter_offset": 39},
    {"name": "Lundi de Pentecôte", "easter_offset": 50},
    {"name": "21 juillet (Fête nationale)", "month": 7, "day": 21},
    {"name": "15 août (Assomption)", "month": 8, "day": 15},
    {"name": "1er novembre (Toussaint)", "month": 11, "day": 1},
    {"name": "11 novembre (Armistice)", "month": 11, "day": 11},
    {"name": "25 décembre (Noël)", "month": 12, "day": 25},
]
EASTER_ASSUMPTION = {
    "parameter": "easter_offset",
    "value": "Easter Sunday from the Gregorian computus; Easter Monday +1, Ascension +39, Whit Monday +50",
    "method": "derived",
    "rationale": "The source names the movable feasts without dates. The rule computes Easter Sunday with the standard Gregorian algorithm, and the offsets reproduce every Lundi de Pâques, Ascension and Lundi de Pentecôte date in the etalab jours fériés list for 2006 to 2031 (checked by the builder and by tests/test_calendars.py).",
}


def check_easter_offsets(metropole_raw: bytes) -> None:
    """Confirm the computus and offsets against the published French dates before any entry relies on them."""
    from almanac.rules import holiday_list

    published = json.loads(metropole_raw)
    offsets = {"Lundi de Pâques": 1, "Ascension": 39, "Lundi de Pentecôte": 50}
    for day, name in published.items():
        if name in offsets:
            expected = holiday_list.easter(int(day[:4])) + holiday_list.timedelta(days=offsets[name])
            if expected.isoformat() != day:
                raise ValueError(f"computus disagrees with the published {name} {day}")


def build_belgium(fr_raw: bytes, nl_raw: bytes) -> dict[str, Any]:
    fr_text, nl_text = html_text(fr_raw), html_text(nl_raw)
    fr_list = re.search(r"Quels sont les jours fériés légaux \? (.*?) Dans certaines branches", fr_text).group(1)
    nl_list = re.search(r"Welke zijn de wettelijke feestdagen \? (.*?) In sommige bedrijfstakken", nl_text).group(1)
    for phrase in ("1er janvier", "lundi de Pâques", "1er mai", "L'Ascension", "lundi de Pentecôte", "21 juillet", "15 août", "1er novembre", "11 novembre", "25 décembre"):
        if phrase not in fr_list:
            raise ValueError(f"Belgian list changed: {phrase!r} missing")
    if len(re.findall(r",|\.", fr_list)) < len(BE_HOLIDAYS) or nl_list.count(",") + 1 != len(BE_HOLIDAYS):
        raise ValueError("Belgian list no longer has ten entries")
    from almanac.rules import holiday_list

    parameters = {"holidays": BE_HOLIDAYS}
    by_name = {r["name"]: r["date"] for r in holiday_list.holidays_in(parameters, 2026)}
    vectors = [
        {"input": {"year": 2026}, "expected": [{"date": r["date"], "name": r["name"]} for r in holiday_list.holidays_in(parameters, 2026)], "origin": "derived", "note": "the ten legal holidays applied to 2026"},
        {"input": by_name["Ascension"], "expected": True, "origin": "derived", "note": "Ascension 2026, the Thursday 39 days after Easter Sunday"},
        {"input": by_name["Lundi de Pentecôte"], "expected": True, "origin": "derived"},
        {"input": "2026-07-21", "expected": True, "origin": "source"},
        {"input": "2026-04-03", "expected": False, "origin": "derived", "note": "Good Friday is not a Belgian legal holiday"},
        {"input": {"op": "next_business_day", "date": "2026-05-01"}, "expected": "2026-05-04", "origin": "derived", "note": "1 May 2026 is a Friday"},
    ]
    return entry(
        id="be-jours-feries-legaux",
        title="Belgium: the ten legal public holidays (jours fériés légaux / wettelijke feestdagen)",
        region="BE",
        tier="B",
        valid_from=ACCESSED.isoformat(),
        valid_to=None,
        extra_tags=["jours-feries", "feestdagen"],
        parameters=parameters,
        vectors=vectors,
        evidence=[
            checked(evidence("SPF Emploi, Travail et Concertation sociale (Federal Public Service Employment, Labour and Social Dialogue)", "Jours fériés (thème Jours fériés et congés)", BE_FR, "section 'Quels sont les jours fériés légaux ?'", "Le lundi de Pentecôte", "text", "Le 21 juillet (Fête nationale)", UNSTATED, fr_raw), fr_raw),
            checked(evidence("FOD Werkgelegenheid, Arbeid en Sociaal Overleg (Federal Public Service Employment, Labour and Social Dialogue)", "Feestdagen (thema Feestdagen en verloven)", BE_NL, "section 'Welke zijn de wettelijke feestdagen ?'", "Pinkstermaandag", "text", "21 juli (nationale feestdag)", UNSTATED, nl_raw), nl_raw),
        ],
        assumed=[
            EASTER_ASSUMPTION,
            {"parameter": "valid_from", "value": ACCESSED.isoformat(), "method": "assumed", "rationale": "The ministry page states the list without an effective date; valid_from records the day the page was fetched. The underlying Royal Decree of 18 April 1974 is not cited here."},
        ],
        tests=[{"statistic": "count[2026]", "expected": len(BE_HOLIDAYS), "tolerance": 0}, {"statistic": "count[2027]", "expected": len(BE_HOLIDAYS), "tolerance": 0}],
        notes=(
            "The ten legal public holidays as the Federal Public Service Employment lists them in French and Dutch: 1 January, "
            "Easter Monday, 1 May, Ascension, Whit Monday, 21 July, 15 August, 1 November, 11 November and 25 December. "
            "Replacement days for holidays falling on a Sunday or a non-working day, which the same pages describe, are "
            "decided per sector or employer and are not modelled. The builder re-reads the lists on each run and stops if "
            "any of the ten entries is missing."
        ),
    )


# --- Ireland ---------------------------------------------------------------------------------------

IE_HOLIDAYS = [
    {"name": "New Year's Day (the 1st day of January)", "month": 1, "day": 1, "paragraph": "1(f)"},
    {"name": "St. Brigid's Day (first Monday in February, or 1 February when a Friday)", "month": 2, "weekday": "monday", "ordinal": "first", "fixed_if_weekday": {"day": 1, "weekday": "friday"}, "paragraph": "1(g), S.I. No. 50/2022"},
    {"name": "St. Patrick's Day", "month": 3, "day": 17, "paragraph": "1(c)"},
    {"name": "Easter Monday", "easter_offset": 1, "paragraph": "1(d)"},
    {"name": "First Monday in May", "month": 5, "weekday": "monday", "ordinal": "first", "paragraph": "1(d)"},
    {"name": "First Monday in June", "month": 6, "weekday": "monday", "ordinal": "first", "paragraph": "1(d)"},
    {"name": "First Monday in August", "month": 8, "weekday": "monday", "ordinal": "first", "paragraph": "1(d)"},
    {"name": "Last Monday in October", "month": 10, "weekday": "monday", "ordinal": "last", "paragraph": "1(e)"},
    {"name": "Christmas Day", "month": 12, "day": 25, "paragraph": "1(a)"},
    {"name": "St. Stephen's Day", "month": 12, "day": 26, "paragraph": "1(b)"},
]


def build_ireland(act_raw: bytes, si_raw: bytes) -> dict[str, Any]:
    act_text, si_text = html_text(act_raw), html_text(si_raw)
    schedule = act_text[act_text.rindex("SECOND SCHEDULE Public Holidays") :]
    for phrase in ("Christmas Day", "St. Stephen’s Day", "St. Patrick’s Day", "Easter Monday, the first Monday in May, the first Monday in June and the first Monday in August", "the last Monday in October", "the 1st day of January"):
        if phrase not in schedule:
            raise ValueError(f"Irish schedule changed: {phrase!r} missing")
    first_brigid = re.search(r"The first such public holiday will be Monday (\d+)\w* February (\d{4})", si_text)
    valid_from = date(int(first_brigid.group(2)), 1, 1).isoformat()
    from almanac.rules import holiday_list

    parameters = {"holidays": IE_HOLIDAYS}
    vectors = [
        {"input": {"year": 2026}, "expected": [{"date": r["date"], "name": r["name"]} for r in holiday_list.holidays_in(parameters, 2026)], "origin": "derived", "note": "the schedule applied to 2026"},
        {"input": f"{first_brigid.group(2)}-02-{int(first_brigid.group(1)):02d}", "expected": True, "origin": "source", "note": "the first St. Brigid's Day holiday named in the regulations"},
        {"input": "2030-02-01", "expected": True, "origin": "derived", "note": "1 February 2030 is a Friday, so the fixed date applies"},
        {"input": "2030-02-04", "expected": False, "origin": "derived", "note": "the first Monday of February 2030 is not a holiday because the Friday rule applied"},
        {"input": "2026-04-06", "expected": True, "origin": "derived", "note": "Easter Monday 2026"},
        {"input": "2026-04-03", "expected": False, "origin": "derived", "note": "Good Friday is not a public holiday under the Act"},
        {"input": {"op": "next_business_day", "date": "2026-12-25"}, "expected": "2026-12-28", "origin": "derived", "note": "St. Stephen's Day 2026 is a Saturday; the Monday is the next business day"},
    ]
    return entry(
        id="ie-public-holidays",
        title="Ireland: public holidays under the Organisation of Working Time Act 1997 Second Schedule and S.I. No. 50/2022",
        region="IE",
        tier="B",
        valid_from=valid_from,
        valid_to=None,
        extra_tags=["public-holidays", "working-time"],
        parameters=parameters,
        vectors=vectors,
        evidence=[
            checked(evidence("Law Reform Commission of Ireland (Revised Acts)", "Organisation of Working Time Act 1997, revised, Second Schedule: Public Holidays", IE_ACT, "Second Schedule, paragraph 1(d) and 1(e)", "the last Monday in October", "text", "Easter Monday, the first Monday in May, the first Monday in June and the first Monday in August", UNSTATED, act_raw), act_raw),
            checked(evidence("Law Reform Commission of Ireland (Revised Acts)", "Organisation of Working Time Act 1997, revised, Second Schedule: Public Holidays", IE_ACT, "Second Schedule, paragraph 1(f) and 1(g)", "the 1st day of January", "text", "any other day or days prescribed for the purposes of this paragraph", UNSTATED, act_raw), act_raw),
            checked(evidence("Office of the Attorney General, electronic Irish Statute Book", "S.I. No. 50/2022, Organisation of Working Time Act 1997 (Public Holiday) Regulations 2022, explanatory note", IE_SI, "explanatory note", "the first Monday in every February", "text", "except where the 1st day of February happens to fall on a Friday", UNSTATED, si_raw), si_raw),
        ],
        assumed=[
            EASTER_ASSUMPTION,
            {"parameter": "holidays", "value": "25 December, 26 December and 17 March", "method": "assumed", "rationale": "The schedule names Christmas Day, St. Stephen's Day and St. Patrick's Day without calendar dates; the rule uses the dates on which those feasts are kept."},
            {"parameter": "holidays", "value": "once-off 18 March 2022 holiday omitted", "method": "derived", "rationale": "S.I. No. 50/2022 also prescribed a single public holiday on 18 March 2022; a recurring list cannot carry it, and it predates valid_from."},
        ],
        tests=[{"statistic": "count[2026]", "expected": len(IE_HOLIDAYS), "tolerance": 0}, {"statistic": "count[2030]", "expected": len(IE_HOLIDAYS), "tolerance": 0}],
        notes=(
            "The nine public holidays of the Second Schedule to the Organisation of Working Time Act 1997 as revised by the "
            "Law Reform Commission, plus St. Brigid's Day prescribed under paragraph 1(g) by S.I. No. 50/2022: the first "
            "Monday in February, or 1 February when that is a Friday. valid_from is the start of the year of the first "
            "St. Brigid's Day holiday the regulations name. The Church-holiday substitution an employer may make under "
            "paragraph 3 is not modelled."
        ),
    )


# --- main ------------------------------------------------------------------------------------------


def main() -> int:
    fr_openapi = fetch(FR_OPENAPI)
    fr_metropole = fetch(FR_API.format(zone="metropole"))
    check_easter_offsets(fr_metropole)
    fr_alsace = fetch(FR_API.format(zone="alsace-moselle"))
    overseas = {zone: fetch(FR_API.format(zone=zone)) for zone in FR_OVERSEAS_ZONES}

    write(build_japan(fetch(JP_CSV), fetch(JP_TERMS)))
    write(build_france("metropole", "fr-jours-feries-metropole", "France: jours fériés in metropolitan France (etalab list)", fr_metropole, fr_openapi, "The eleven jours fériés of metropolitan France for every year the API serves."))
    write(build_france("alsace-moselle", "fr-jours-feries-alsace-moselle", "France: jours fériés in Alsace-Moselle (etalab list)", fr_alsace, fr_openapi, "The metropolitan list plus Vendredi saint and the 26 December second Christmas day kept by local law in the departments of Bas-Rhin, Haut-Rhin and Moselle."))
    write(build_france_overseas(overseas, fr_openapi, fr_metropole))
    write(build_hong_kong(fetch(HK_JSON), fetch(HK_TERMS)))
    write(build_australia(fetch(AU_CSV), fetch(AU_PACKAGE)))
    write(build_singapore(fetch(SG_API), fetch(SG_METADATA)))
    write(build_spain(fetch(ES_XML), fetch(ES_PDF), fetch(ES_INHABILES_XML)))
    write(build_india(fetch(IN_PDF)))
    write(build_mexico(fetch(MX_PDF)))
    write(build_belgium(fetch(BE_FR), fetch(BE_NL)))
    write(build_ireland(fetch(IE_ACT), fetch(IE_SI)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

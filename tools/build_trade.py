"""Regenerate the tariff, customs and consumption-tax entries.

Sources, all fetched live:

- US Harmonized Tariff Schedule (USITC): the table of contents of the pinned
  revision (PDF) for sections and chapters, and the JSON export of the current
  revision for headings and for the rate lines of the apparel, footwear,
  machinery, electrical, furniture and toy chapters.
- US customs entry and exemption thresholds from 19 CFR parts 10, 143, 145 and
  148, as published by the eCFR point-in-time API (XML).
- UK Integrated Online Tariff via the Trade Tariff API (JSON): sections,
  chapters, and the third-country duty and import VAT of the declarable
  commodities under a set of consumer-goods headings.
- EU Combined Nomenclature 2026 from the Eurostat Comext classification files
  (tab-separated text).
- OECD Consumption Tax Trends annex tables (XLSX): VAT/GST standard and reduced
  rates, and VAT/GST registration thresholds.
- National consumption-tax rates from the legislation publisher or tax
  authority: Australia, Switzerland, Japan, Singapore and Norway.

Run from the repository root:

    uv run python tools/build_trade.py
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence as _evidence
from _common import fetch, write

from almanac.fetch import Resource

ACCESSED = date(2026, 11, 3)

TAGS = ["trade", "customs", "tariffs"]
TAX_TAGS = ["vat", "tax", "consumption-tax"]
TRADE_USES = ["ecommerce-demo", "logistics-demo", "procurement-demo", "invoicing-demo"]
TAX_USES = ["invoicing-demo", "tax-demo", "ecommerce-demo", "invoicing", "accounts-payable"]

_texts: dict[str, str] = {}


def searchable(url: str, raw: bytes) -> str:
    """The resource as the verifier searches it, whitespace collapsed."""
    if url not in _texts:
        _texts[url] = " ".join(Resource(url=url, content=raw, content_type="").text.split())
    return _texts[url]


def ev(publisher: str, title: str, url: str, locator: str, value: Any, unit: str, snippet: str, license_id: str, raw: bytes, role: str = "primary") -> dict:
    """An evidence item, refusing to build one whose snippet or value is absent from the resource."""
    text = searchable(url, raw)
    for label, needle in (("snippet", snippet), ("value", value)):
        rendered = ("true" if needle else "false") if isinstance(needle, bool) else str(needle)
        if " ".join(rendered.split()) not in text:
            raise ValueError(f"{label} {rendered!r} not found in {url}")
    item = _evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role)
    item["accessed_at"] = ACCESSED.isoformat()
    return item


def rule(entry_id: str, title: str, domain: str, region: str, *, status: str, tier: str, valid_from: str, valid_to: str | None, tags: list[str], use_cases: list[str], implementation: str, parameters: dict, vectors: list[dict], evidence_items: list[dict], tests: list[dict], notes: str, assumed: list[dict] | None = None) -> dict:
    if len(title) > 140:
        raise ValueError(f"title of {entry_id} is {len(title)} characters")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": tags,
        "use_cases": use_cases,
        "spec": {"implementation": f"almanac.rules.{implementation}", "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": " ".join(notes.split()),
    }


def exact(tests: Iterable[tuple[str, Any]]) -> list[dict]:
    return [{"statistic": name, "expected": value, "tolerance": 0} for name, value in tests]


def pdf_text(raw: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages]


def number(text: Any) -> int | float:
    value = float(str(text).replace(",", ""))
    return int(value) if value.is_integer() else value


# ---------------------------------------------------------------- US Harmonized Tariff Schedule

HTS_REVISION = "2026HTSRev22"
HTS_API = "https://hts.usitc.gov/reststop"
HTS_PUBLISHER = "United States International Trade Commission"
HTS_LICENSE = "unstated"
HTS_LICENSE_NOTE = (
    "The USITC publishes the HTS as a US government work but states no reuse licence in the files cited, so the "
    "licence is recorded as unstated and the entry held at license-review."
)
HTS_CHAPTERS = {
    "61": ("apparel-knitted", "articles of apparel and clothing accessories, knitted or crocheted"),
    "62": ("apparel-woven", "articles of apparel and clothing accessories, not knitted or crocheted"),
    "64": ("footwear", "footwear, gaiters and the like"),
    "84": ("machinery", "nuclear reactors, boilers, machinery and mechanical appliances"),
    "85": ("electrical", "electrical machinery and equipment"),
    "94": ("furniture", "furniture, bedding, luminaires and prefabricated buildings"),
    "95": ("toys", "toys, games and sports equipment"),
}


def export_url(start: str, end: str) -> str:
    return f"{HTS_API}/exportList?from={start}&to={end}&format=JSON&styles=false"


def toc_url() -> str:
    return f"{HTS_API}/file?release={HTS_REVISION}&filename=Table%20of%20Contents"


def release_url() -> str:
    return f"{HTS_API}/releaseDetails?release={HTS_REVISION}"


def hts_release() -> tuple[str, dict]:
    """The start date of the pinned revision, and the supporting evidence for it; fails if it is no longer current."""
    current = json.loads(fetch(f"{HTS_API}/currentRelease"))
    if current["name"] != HTS_REVISION:
        raise RuntimeError(f"the current HTS release is {current['name']}, not {HTS_REVISION}; update HTS_REVISION")
    raw = fetch(release_url())
    start = json.loads(raw)["reldetail"]["releaseStartDate"]
    item = ev(HTS_PUBLISHER, f"HTS release details for {HTS_REVISION} (JSON)", release_url(), "reldetail.releaseStartDate", start, "text",
              f'"releaseStartDate" : "{start}"', HTS_LICENSE, raw, role="supporting")
    return datetime.strptime(start, "%m/%d/%Y").date().isoformat(), item


def hts_toc(raw: bytes) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Sections, chapters and the section of each chapter, parsed from the table of contents."""
    lines = [line.strip() for line in "\n".join(pdf_text(raw)).splitlines()]
    start = lines.index("SECTION I")
    sections: dict[str, str] = {}
    chapters: dict[str, str] = {}
    chapter_section: dict[str, str] = {}
    numeral = ""
    in_title = False
    buffer: list[str] = []
    expected = 1
    for line in lines[start:]:
        if line.startswith("Chemical Appendix"):
            break
        if m := re.fullmatch(r"SECTION ([IVXL]+)", line):
            numeral, in_title, buffer = m.group(1), True, []
            sections[numeral] = ""
            continue
        if line == "Section Notes":
            in_title = False
            continue
        if in_title and line == line.upper() and re.search(r"[A-Z]", line):
            sections[numeral] = f"{sections[numeral]} {line}".strip()
            continue
        in_title = False
        if line.isdigit() and not buffer:
            continue  # page number
        m = re.fullmatch(r"(.*?)(?:Chapter )?(\d{1,2})", line)
        if m and int(m.group(2)) == expected:
            text = " ".join([*buffer, m.group(1)]).strip()
            code = f"{expected:02d}"
            chapters[code] = " ".join(text.split())
            chapter_section[code] = numeral
            buffer, expected = [], expected + 1
        else:
            buffer.append(line)
    if expected != 100 or len(sections) != 22:
        raise ValueError(f"parsed {expected - 1} chapters and {len(sections)} sections from the table of contents")
    return sections, chapters, chapter_section


def us_hts_chapters(release_item: dict, valid_from: str) -> dict:
    raw = fetch(toc_url())
    sections, chapters, chapter_section = hts_toc(raw)
    title = f"Harmonized Tariff Schedule of the United States, {HTS_REVISION}, Table of Contents (PDF)"
    items = [
        ev(HTS_PUBLISHER, title, toc_url(), "Section I, Chapter 1", chapters["01"], "text", f"{chapters['01']}Chapter 1", HTS_LICENSE, raw),
        ev(HTS_PUBLISHER, title, toc_url(), "Section XI, Chapter 61", chapters["61"], "text", f"{chapters['61']}61", HTS_LICENSE, raw),
        ev(HTS_PUBLISHER, title, toc_url(), "Section XVI, Chapter 84", chapters["84"], "text", f"{chapters['84']}Chapter 84", HTS_LICENSE, raw),
        ev(HTS_PUBLISHER, title, toc_url(), "Section XXII, Chapter 98", chapters["98"], "text", f"{chapters['98']}Chapter 98", HTS_LICENSE, raw),
        release_item,
    ]
    return rule(
        "us-hts-2026-sections-and-chapters",
        f"US Harmonized Tariff Schedule 2026 sections and chapters with titles ({HTS_REVISION.replace('2026HTSRev', 'Revision ')})",
        "trade", "US", status="license-review", tier="B", valid_from=valid_from, valid_to=None,
        tags=[*TAGS, "hts", "harmonized-system", "code-list"], use_cases=TRADE_USES,
        implementation="enumeration",
        parameters={"revision": HTS_REVISION, "sets": {"section": sections, "chapter": chapters}, "chapter_section": chapter_section},
        vectors=[
            {"input": {"set": "chapter", "value": "61"}, "expected": True, "origin": "source"},
            {"input": {"set": "chapter", "value": "77"}, "expected": True, "origin": "source", "note": "listed as reserved for possible future use"},
            {"input": {"set": "section", "value": "XXII"}, "expected": True, "origin": "source"},
            {"input": {"set": "chapter", "value": "00"}, "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count[chapter]", len(chapters)), ("count[section]", len(sections))]),
        notes=(
            f"The 22 sections and 99 chapters of the Harmonized Tariff Schedule of the United States as listed in the table of "
            f"contents of {HTS_REVISION}, the revision current when the entry was built (release start date sets valid_from). "
            "Section titles are upper case as printed; chapter titles are as printed, with line wraps joined. Chapters 1 to 97 "
            "follow the international Harmonized System; chapter 77 is reserved, and chapters 98 and 99 are US-only special "
            "classification provisions and temporary legislation, including the chapter 99 headings that carry additional "
            "duties. The table of contents is fetched for the pinned revision, so its bytes do not move when a later revision "
            "is published; the supporting release-details record does change at that point. " + HTS_LICENSE_NOTE
        ),
    )


def hts_rows(raw: bytes) -> list[dict]:
    return json.loads(raw)


def us_hts_headings(release_item: dict, valid_from: str) -> dict:
    url = export_url("0101", "9799")
    raw = fetch(url)
    headings: dict[str, str] = {}
    source_line: dict[str, str] = {}
    for row in hts_rows(raw):
        code = (row["htsno"] or "").replace(".", "")[:4]
        if len(code) == 4 and row["indent"] == "0" and code not in headings:
            headings[code] = " ".join(row["description"].split()).rstrip(":").strip()
            source_line[code] = row["htsno"]
    title = f"Harmonized Tariff Schedule export, chapters 1 to 97, current revision ({HTS_REVISION}) (JSON)"
    items = [
        ev(HTS_PUBLISHER, title, url, f"row htsno {source_line[code]}", headings[code], "text", f'"htsno" : "{source_line[code]}"', HTS_LICENSE, raw)
        for code in ("0101", "0409", "6109", "8471", "9503")
    ]
    items.append(release_item)
    return rule(
        "us-hts-2026-headings",
        f"US Harmonized Tariff Schedule 2026 four-digit headings with descriptions, chapters 1 to 97 ({HTS_REVISION.replace('2026HTSRev', 'Revision ')})",
        "trade", "US", status="license-review", tier="A", valid_from=valid_from, valid_to=None,
        tags=[*TAGS, "hts", "harmonized-system", "code-list"], use_cases=[*TRADE_USES, "product-catalogue"],
        implementation="enumeration",
        parameters={"revision": HTS_REVISION, "sets": {"heading": headings}},
        vectors=[
            {"input": {"set": "heading", "value": "6109"}, "expected": True, "origin": "source"},
            {"input": {"set": "heading", "value": "8471"}, "expected": True, "origin": "source"},
            {"input": {"set": "heading", "value": "6100"}, "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count[heading]", len(headings))]),
        notes=(
            "Every four-digit heading of chapters 1 to 97 of the Harmonized Tariff Schedule of the United States, with its "
            f"description, from the USITC JSON export of the current revision ({HTS_REVISION}). A heading is the first "
            "zero-indent line whose number starts with the four digits; headings without subdivisions appear in the export "
            "only as a full tariff line (for example 0409.00.00) and take that line's description. A trailing colon, which "
            "marks a heading with subdivisions, is dropped. Chapters 98 and 99 (US special provisions and temporary "
            "modifications) are left out. The export always serves the current revision, so this entry must be rebuilt when "
            "the USITC publishes the next one. " + HTS_LICENSE_NOTE
        ),
    )


def hts_lines(rows: list[dict]) -> dict[str, dict]:
    """Rate-bearing tariff lines keyed by eight-digit subheading, with the descriptions of their superior lines."""
    lines: dict[str, dict] = {}
    stack: dict[int, str] = {}
    units: dict[str, set[str]] = {}
    for row in rows:
        indent = int(row["indent"])
        description = " ".join(row["description"].split()).rstrip(":").strip()
        stack = {level: text for level, text in stack.items() if level < indent}
        number = row["htsno"] or ""
        key = number[:10]
        if len(key) == 10 and key in lines:
            units[key].update(row.get("units") or [])
        general = (row.get("general") or "").strip()
        if general and len(number) >= 10:
            footnotes = [" ".join(f["value"].split()) for f in (row.get("footnotes") or []) if f.get("value", "").strip()]
            line = {
                "description": description,
                "heading": number[:4],
                "context": " > ".join(stack[level] for level in sorted(stack) if level > 0),
                "general_rate": general,
                "special_rate": " ".join((row.get("special") or "").split()),
                "column2_rate": (row.get("other") or "").strip(),
            }
            if footnotes:
                line["footnotes"] = footnotes
            lines[key] = line
            units[key] = set(row.get("units") or [])
        stack[indent] = description
    for key, line in lines.items():
        if units[key]:
            line["units"] = sorted(units[key])
        for column in ("context", "special_rate"):
            if not line[column]:
                del line[column]
    return lines


def us_hts_chapter_lines(chapter: str, release_item: dict, valid_from: str) -> dict:
    slug, label = HTS_CHAPTERS[chapter]
    url = export_url(f"{chapter}01", f"{chapter}99")
    raw = fetch(url)
    lines = hts_lines(hts_rows(raw))
    keys = list(lines)
    picks = [keys[0], keys[len(keys) // 2], keys[-1]]
    title = f"Harmonized Tariff Schedule export, chapter {chapter}, current revision ({HTS_REVISION}) (JSON)"
    items = []
    for key in picks:
        full = next(r["htsno"] for r in hts_rows(raw) if (r["htsno"] or "")[:10] == key and (r.get("general") or "").strip())
        items.append(ev(HTS_PUBLISHER, title, url, f"row htsno {full}, column general", lines[key]["general_rate"], "text", f'"htsno" : "{full}"', HTS_LICENSE, raw))
    items.append(release_item)
    first = picks[0]
    rates = [line["general_rate"] for line in lines.values()]
    return rule(
        f"us-hts-2026-chapter-{chapter}-{slug}-duty-rates",
        f"US HTS 2026 chapter {chapter} ({slug.replace('-', ' ')}) eight-digit subheadings with general, special and column 2 duty rates",
        "trade", "US", status="license-review", tier="A", valid_from=valid_from, valid_to=None,
        tags=[*TAGS, "hts", "duty-rates", "import-duty", slug],
        use_cases=[*TRADE_USES, "product-catalogue", "pricing"],
        implementation="lookup_table",
        parameters={"revision": HTS_REVISION, "chapter": chapter, "rows": lines},
        vectors=[
            {"input": {"key": first, "column": "general_rate"}, "expected": lines[first]["general_rate"], "origin": "source"},
            {"input": {"key": picks[-1], "column": "column2_rate"}, "expected": lines[picks[-1]]["column2_rate"], "origin": "source"},
            {"input": picks[1], "expected": True, "origin": "source"},
            {"input": f"{chapter}00.00.00", "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", len(lines)), (f"value[{first},general_rate]", lines[first]["general_rate"])]),
        assumed=[{
            "parameter": "rows[*].context",
            "value": "descriptions of the superior lines below the heading, joined with ' > '",
            "method": "derived",
            "rationale": "HTS line descriptions are often relative ('Other', 'Of cotton'); the superior lines are read from "
                         "the export's indent levels so each line can be read with its heading, whose description is in "
                         "us-hts-2026-headings.",
        }],
        notes=(
            f"The rate-bearing tariff lines of chapter {chapter} ({label}) of the Harmonized Tariff Schedule of the United "
            f"States, from the USITC JSON export of the current revision ({HTS_REVISION}), keyed by eight-digit subheading. "
            "Each row carries the line's own description, its four-digit heading, the descriptions of its superior lines "
            "below the heading (the heading descriptions are in us-hts-2026-headings), the column 1 general rate "
            "(most-favoured-nation), the column 1 special rate with the programme indicators in brackets (free trade "
            "agreements and preference programmes, see General Notes 3 to 36), the column 2 rate (General Note 3(b) "
            "countries), the units of quantity of the line and its statistical suffixes, and footnotes. Rates are "
            "strings exactly as published: ad valorem (a percentage), specific (cents per unit) or compound. Additional "
            "duties under chapter 99 (for example trade-remedy or emergency measures) are not in these columns; footnotes "
            f"that point to chapter 99 are kept. Of the {len(rates)} lines, {sum(1 for r in rates if r == 'Free')} have a "
            "general rate of Free. The export always serves the current revision, so this entry must be rebuilt when the "
            "USITC publishes the next one. " + HTS_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- US customs thresholds (eCFR)

CFR_DATE = "2026-10-29"
ECFR = "https://www.ecfr.gov/api/versioner/v1"
CBP = "US Customs and Border Protection via the eCFR API"
CFR_LICENSE_NOTE = (
    "US federal government works carry no copyright, but neither the eCFR API nor the regulation text states reuse "
    "terms, so the licence is recorded as unstated and the entry held at license-review."
)


def cfr_section_url(section: str) -> str:
    return f"{ECFR}/full/{CFR_DATE}/title-19.xml?section={section}"


def cfr_text(raw: bytes) -> str:
    text = re.sub(r"<[^>]+>", " ", raw.decode("utf-8"))
    return " ".join(text.replace("&#xA7;", "§").replace("&#x2014;", "-").split())


def us_customs_thresholds() -> dict:
    sections = ["10.151", "10.152", "143.21", "145.31", "148.33", "148.41", "148.64"]
    raw = {s: fetch(cfr_section_url(s)) for s in sections}
    text = {s: cfr_text(raw[s]) for s in sections}
    versions = {s: fetch(f"{ECFR}/versions/title-19.json?section={s}") for s in ("10.151", "145.31")}
    latest = {s: max(v["date"] for v in json.loads(versions[s])["content_versions"]) for s in versions}

    def grab(section: str, pattern: str) -> str:
        m = re.search(pattern, text[section])
        if m is None:
            raise ValueError(f"pattern {pattern!r} not found in {section}")
        return m.group(1)

    de_minimis = grab("10.151", r"in the country of shipment not exceeding \$(\d{1,3}(?:,\d{3})*)")
    suspension = grab("10.151", r"\[(CBP Dec\. [^\]]+)\]")
    gift = grab("10.152", r"does not exceed \$(\d{1,3}(?:,\d{3})*) or, in the case of articles sent from a person in the Virgin Islands")
    gift_islands = grab("10.152", r"Guam, and American Samoa, \$(\d{1,3}(?:,\d{3})*)\.")
    informal = grab("143.21", r"Shipments of merchandise not exceeding \$(\d{1,3}(?:,\d{3})*) in value")
    ch99 = grab("143.21", r"except for articles valued in excess of \$(\d{1,3}(?:,\d{3})*) classified in Chapter 99")
    returned = grab("143.21", r"aggregate value of the shipment does not exceed \$(\d{1,3}(?:,\d{3})*)")
    postal = grab("145.31", r"aggregate fair retail value in the country of shipment of not over \$(\d{1,3}(?:,\d{3})*)")
    resident = grab("148.33", r"must not exceed: \(1\) \$(\d{1,3}(?:,\d{3})*), and provided that the articles accompany")
    resident_islands = grab("148.33", r"\(3\) \$(\d{1,3}(?:,\d{3})*) in the case of a direct or indirect arrival from American Samoa")
    transit = grab("148.41", r"articles not exceeding \$(\d{1,3}(?:,\d{3})*) in aggregate value")
    administrative = grab("148.64", r"does not exceed \$(\d{1,3}(?:,\d{3})*)")
    rows = {
        "de_minimis_shipment": {"amount_usd": number(de_minimis), "section": "10.151(a)", "suspended": True,
                                "scope": "shipment imported by one person on one day, fair retail value in the country of shipment",
                                "suspension": "10.151(b): suspended for all modes other than the international postal network",
                                "authority": suspension},
        "de_minimis_postal": {"amount_usd": number(postal), "section": "145.31(a)", "suspended": True,
                              "scope": "packages arriving through the international postal network",
                              "suspension": "145.31(b): suspended for merchandise arriving through the international postal network"},
        "bona_fide_gift": {"amount_usd": number(gift), "section": "10.152", "suspended": False,
                           "scope": "aggregate fair retail value received by one person on one day"},
        "bona_fide_gift_from_insular_possessions": {"amount_usd": number(gift_islands), "section": "10.152", "suspended": False,
                                                    "scope": "gifts sent from a person in the Virgin Islands, Guam or American Samoa"},
        "informal_entry_limit": {"amount_usd": number(informal), "section": "143.21(a)", "suspended": False,
                                 "scope": "shipments of merchandise eligible for informal entry"},
        "informal_entry_chapter_99_article_limit": {"amount_usd": number(ch99), "section": "143.21(a)", "suspended": False,
                                                    "scope": "articles above this value classified in Chapter 99, Subchapters III and IV, HTSUS, are excluded from informal entry"},
        "informal_entry_us_goods_returned": {"amount_usd": number(returned), "section": "143.21(k)", "suspended": False,
                                             "scope": "products of the United States returned for repair or alteration, or rejected by the foreign purchaser"},
        "returning_resident_exemption": {"amount_usd": number(resident), "section": "148.33", "suspended": False,
                                         "scope": "articles acquired abroad accompanying a returning resident"},
        "returning_resident_exemption_insular_possessions": {"amount_usd": number(resident_islands), "section": "148.33", "suspended": False,
                                                             "scope": "arrival from American Samoa, Guam, the Northern Mariana Islands or the US Virgin Islands"},
        "nonresident_in_transit": {"amount_usd": number(transit), "section": "148.41", "suspended": False,
                                   "scope": "articles a nonresident in transit carries through US Customs territory"},
        "administrative_exemption": {"amount_usd": number(administrative), "section": "148.64", "suspended": False,
                                     "scope": "articles not otherwise entitled to an exemption, section 321(a)(2)(B) Tariff Act of 1930"},
    }
    def title(section: str) -> str:
        return f"19 CFR {section} as of {CFR_DATE}, eCFR point-in-time API (XML)"

    items = [
        ev(CBP, title("10.151"), cfr_section_url("10.151"), "section 10.151(a)", f"${de_minimis}", "currency:USD", f"in the country of shipment not exceeding ${de_minimis}", "unstated", raw["10.151"]),
        ev(CBP, title("10.151"), cfr_section_url("10.151"), "section 10.151(b)", suspension, "text", "is suspended for merchandise arriving via all modes other than through the international postal network", "unstated", raw["10.151"]),
        ev(CBP, title("145.31"), cfr_section_url("145.31"), "section 145.31(b)", f"${postal}", "currency:USD", "is suspended for merchandise arriving through the international postal network", "unstated", raw["145.31"]),
        ev(CBP, title("10.152"), cfr_section_url("10.152"), "section 10.152", f"${gift}", "currency:USD", f"does not exceed ${gift} or, in the case of articles sent from a person in the Virgin Islands", "unstated", raw["10.152"]),
        ev(CBP, title("143.21"), cfr_section_url("143.21"), "section 143.21(a)", f"${informal}", "currency:USD", f"Shipments of merchandise not exceeding ${informal} in value", "unstated", raw["143.21"]),
        ev(CBP, title("148.33"), cfr_section_url("148.33"), "section 148.33(b)", f"${resident_islands}", "currency:USD", f"${resident_islands} in the case of a direct or indirect arrival from American Samoa", "unstated", raw["148.33"]),
        ev(CBP, title("148.41"), cfr_section_url("148.41"), "section 148.41", f"${transit}", "currency:USD", f"articles not exceeding ${transit} in aggregate value", "unstated", raw["148.41"]),
        ev(CBP, title("148.64"), cfr_section_url("148.64"), "section 148.64(a)", f"${administrative}", "currency:USD", "the aggregate fair retail value of all articles not otherwise entitled to an exemption does not exceed", "unstated", raw["148.64"]),
    ]
    for s, versions_raw in versions.items():
        items.append(ev(CBP, f"eCFR versions of 19 CFR {s} (JSON)", f"{ECFR}/versions/title-19.json?section={s}", "content_versions[*].date, latest",
                        latest[s], "date", f'"date":"{latest[s]}"', "unstated", versions_raw, role="supporting"))
    return rule(
        "us-customs-de-minimis-and-informal-entry-thresholds",
        "United States customs de minimis, gift, informal entry and traveller exemption thresholds, 19 CFR parts 10, 143, 145 and 148",
        "trade", "US", status="license-review", tier="A", valid_from=max(latest.values()), valid_to=None,
        tags=[*TAGS, "de-minimis", "informal-entry", "duty-free", "19-cfr"],
        use_cases=[*TRADE_USES, "parcel-shipping"],
        implementation="lookup_table",
        parameters={"currency": "USD", "cfr_date": CFR_DATE, "rows": rows},
        vectors=[
            {"input": {"key": "informal_entry_limit", "column": "amount_usd"}, "expected": number(informal), "origin": "source"},
            {"input": {"key": "de_minimis_shipment", "column": "suspended"}, "expected": True, "origin": "source"},
            {"input": {"key": "returning_resident_exemption", "column": "amount_usd"}, "expected": number(resident), "origin": "source"},
            {"input": {"key": "bona_fide_gift", "column": "amount_usd"}, "expected": number(gift), "origin": "source"},
            {"input": "formal_entry_limit", "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", len(rows)), ("value[de_minimis_shipment,amount_usd]", number(de_minimis)), ("max[amount_usd]", number(returned))]),
        notes=(
            f"US customs dollar thresholds for low-value shipments and travellers, read from 19 CFR as of {CFR_DATE}. "
            "The de minimis administrative exemption of 19 U.S.C. 1321 (10.151 for commercial modes, 145.31 for mail) "
            "keeps its dollar amount in the text but is suspended by paragraph (b) of both sections, for every mode of "
            f"arrival, by {suspension}; the suspension holds until CBP announces otherwise in the Federal Register, so a "
            "generator should treat no low-value shipment as duty-free under de minimis. The bona fide gift exemption "
            "(10.152), the informal entry ceiling (143.21), the returning resident exemption for articles acquired abroad "
            "(148.33), the nonresident in-transit allowance (148.41) and the administrative exemption for travellers "
            "(148.64) are not suspended. valid_from is the latest eCFR version date of 10.151 and 145.31, the sections the "
            "suspension amended. " + CFR_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- UK Trade Tariff

UK_API = "https://www.trade-tariff.service.gov.uk/api/v2"
UK_PUBLISHER = "HM Revenue & Customs and Department for Business and Trade, UK Trade Tariff service"
UK_LICENSE = "OGL-UK-3.0"
UK_HEADINGS = ["6109", "6110", "6203", "6204", "6403", "6404", "8471", "8517", "8528", "9403", "9503"]


def uk_sections_and_chapters() -> dict:
    sections_raw = fetch(f"{UK_API}/sections")
    chapters_raw = fetch(f"{UK_API}/chapters")
    sections = {}
    ranges = {}
    for item in json.loads(sections_raw)["data"]:
        a = item["attributes"]
        sections[a["numeral"]] = a["title"]
        ranges[a["numeral"]] = [a["chapter_from"], a["chapter_to"]]
    chapters = {}
    for item in json.loads(chapters_raw)["data"]:
        a = item["attributes"]
        chapters[a["goods_nomenclature_item_id"][:2]] = a["formatted_description"]
    if any("<" in text for text in chapters.values()):
        raise ValueError("chapter descriptions carry markup")
    items = [
        ev(UK_PUBLISHER, "Trade Tariff API v2 sections (JSON)", f"{UK_API}/sections", "data[numeral=XI]", sections["XI"], "text",
           f'"numeral":"XI","title":"{sections["XI"]}"', UK_LICENSE, sections_raw),
        ev(UK_PUBLISHER, "Trade Tariff API v2 sections (JSON)", f"{UK_API}/sections", "data[numeral=XVI]", sections["XVI"], "text",
           '"numeral":"XVI","title":"' + " ".join(sections["XVI"].split()[:8]), UK_LICENSE, sections_raw),
        ev(UK_PUBLISHER, "Trade Tariff API v2 chapters (JSON)", f"{UK_API}/chapters", "data[goods_nomenclature_item_id=6100000000]", chapters["61"], "text",
           '"goods_nomenclature_item_id":"6100000000"', UK_LICENSE, chapters_raw),
        ev(UK_PUBLISHER, "Trade Tariff API v2 chapters (JSON)", f"{UK_API}/chapters", "data[goods_nomenclature_item_id=8500000000]", chapters["85"], "text",
           '"goods_nomenclature_item_id":"8500000000"', UK_LICENSE, chapters_raw),
    ]
    return rule(
        "gb-trade-tariff-sections-and-chapters",
        "UK Integrated Online Tariff sections and chapters with titles (Trade Tariff API)",
        "trade", "GB", status="verified", tier="A", valid_from=ACCESSED.isoformat(), valid_to=None,
        tags=[*TAGS, "uk-global-tariff", "harmonized-system", "code-list"], use_cases=TRADE_USES,
        implementation="enumeration",
        parameters={"sets": {"section": sections, "chapter": chapters}, "section_chapters": ranges},
        vectors=[
            {"input": {"set": "section", "value": "XI"}, "expected": True, "origin": "source"},
            {"input": {"set": "chapter", "value": "85"}, "expected": True, "origin": "source"},
            {"input": {"set": "chapter", "value": "77"}, "expected": "77" in chapters, "origin": "source"},
            {"input": {"set": "section", "value": "XXII"}, "expected": "XXII" in sections, "origin": "source"},
        ],
        evidence_items=items,
        tests=exact([("count[section]", len(sections)), ("count[chapter]", len(chapters))]),
        notes=(
            "The sections (by Roman numeral, with the first and last chapter of each) and chapters (two-digit code) of the UK "
            "Integrated Online Tariff, the goods classification the UK applies to imports and exports, from the Trade Tariff "
            "service API. The API serves the tariff in force on the day of the request, so valid_from is the day the entry "
            "was built. Chapter titles are the service's formatted descriptions, checked to carry no markup. The Trade "
            "Tariff is a GOV.UK service and its content is published under the Open Government Licence v3.0."
        ),
    )


def uk_commodity_duties() -> dict:
    rows: dict[str, dict] = {}
    items = []
    for heading in UK_HEADINGS:
        url = f"{UK_API}/headings/{heading}"
        raw = fetch(url)
        doc = json.loads(raw)
        included = {(i["type"], i["id"]): i for i in doc["included"]}
        commodities = [i for i in doc["included"] if i["type"] == "commodity"]
        by_sid = {c["attributes"]["goods_nomenclature_sid"]: c for c in commodities}
        cited = False
        for commodity in commodities:
            a = commodity["attributes"]
            if not a.get("leaf") or not a.get("declarable"):
                continue
            duties, vat = [], []
            for ref in commodity["relationships"].get("overview_measures", {}).get("data", []):
                measure = included[("measure", ref["id"])]
                base = included[("duty_expression", measure["relationships"]["duty_expression"]["data"]["id"])]["attributes"]["base"]
                kind = measure["relationships"]["measure_type"]["data"]["id"]
                if kind == "103":
                    duties.append((ref["id"], base))
                elif measure["attributes"].get("vat"):
                    vat.append(base)
            if len(duties) != 1:
                raise ValueError(f"{a['goods_nomenclature_item_id']}: expected one third-country duty, found {len(duties)}")
            context, parent = [], a.get("parent_sid")
            while parent in by_sid:
                context.insert(0, by_sid[parent]["attributes"]["description_plain"])
                parent = by_sid[parent]["attributes"].get("parent_sid")
            code = a["goods_nomenclature_item_id"]
            rows[code] = {
                "description": a["description_plain"],
                "context": " > ".join([doc["data"]["attributes"]["description_plain"], *context]),
                "heading": heading,
                "third_country_duty": duties[0][1],
                "import_vat_rates": sorted(set(vat), key=lambda v: float(v.split()[0])) if vat else [],
            }
            if not cited:
                measure_id, base = duties[0]
                items.append(ev(UK_PUBLISHER, f"Trade Tariff API v2 heading {heading} (JSON)", url,
                                f"included duty_expression {measure_id}-duty_expression, commodity {code}", base, "text",
                                f'"{measure_id}-duty_expression","type":"duty_expression","attributes":{{"base":"{base}"',
                                UK_LICENSE, raw))
                cited = True
    first = next(iter(rows))
    return rule(
        "gb-uk-global-tariff-third-country-duty-consumer-goods",
        "UK Global Tariff third-country duty and import VAT for apparel, footwear, computers, phones, TVs, furniture and toys",
        "trade", "GB", status="verified", tier="A", valid_from=ACCESSED.isoformat(), valid_to=None,
        tags=[*TAGS, "uk-global-tariff", "duty-rates", "import-duty", "vat"],
        use_cases=[*TRADE_USES, "product-catalogue", "pricing"],
        implementation="lookup_table",
        parameters={"headings": UK_HEADINGS, "rows": rows},
        vectors=[
            {"input": {"key": first, "column": "third_country_duty"}, "expected": rows[first]["third_country_duty"], "origin": "source"},
            {"input": first, "expected": True, "origin": "source"},
            {"input": "0000000000", "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", len(rows)), (f"value[{first},third_country_duty]", rows[first]["third_country_duty"])]),
        assumed=[{
            "parameter": "rows[*].context",
            "value": "heading description and the descriptions of the commodity's ancestors, joined with ' > '",
            "method": "derived",
            "rationale": "Leaf descriptions are often relative ('Other'); the ancestors are followed through parent_sid in "
                         "the same response so each code reads on its own.",
        }],
        notes=(
            "Declarable ten-digit UK commodity codes under eleven consumer-goods headings (T-shirts, jerseys, suits and "
            "trousers, leather and textile footwear, computers, telephones, monitors and televisions, furniture and toys), "
            "each with the third-country duty (measure type 103, the rate charged on imports from countries without a "
            "preference) and the import VAT rates shown in the heading overview, exactly as the Trade Tariff API states "
            "them. Preferential rates, quotas, suspensions and trade remedies are not included. The API serves the tariff "
            "in force on the day of the request, so valid_from is the day the entry was built and the entry should be "
            "rebuilt when the UK Global Tariff changes. Published under the Open Government Licence v3.0."
        ),
    )


# ---------------------------------------------------------------- EU Combined Nomenclature 2026 (Eurostat Comext)

COMEXT = "https://ec.europa.eu/eurostat/api/dissemination/files/?sort=1&downfile=comext%2FCOMEXT_METADATA%2FCLASSIFICATIONS_AND_RELATIONS%2FCLASSIFICATIONS%2FENGLISH%2F"
EUROSTAT = "Eurostat (Comext)"
CN_YEAR_START, CN_YEAR_END = date(2026, 1, 1), date(2026, 12, 31)


def comext(name: str) -> tuple[str, bytes]:
    url = COMEXT + name
    return url, fetch(url)


def cn_records(raw: bytes) -> list[tuple[str, date, date, str]]:
    out = []
    for line in raw.decode("utf-8").splitlines():
        code, start, end, label = line.rstrip("\r").split("\t")
        out.append((code, datetime.strptime(start, "%d/%m/%Y").date(), datetime.strptime(end, "%d/%m/%Y").date(), label))
    return out


def cn_2026(raw: bytes) -> list[tuple[str, date, date, str]]:
    """Numeric codes in force for the whole of 2026."""
    return [r for r in cn_records(raw) if r[0].isdigit() and r[1] <= CN_YEAR_START and r[2] >= CN_YEAR_END]


def cn_line(record: tuple[str, date, date, str]) -> str:
    code, start, end, label = record
    return f"{code} {start:%d/%m/%Y} {end:%d/%m/%Y} {label}"


def eu_cn_sections_and_chapters(cn_url: str, cn_raw: bytes) -> dict:
    sec_url, sec_raw = comext("CN_SECTIONS.txt")
    sections = {
        code: label
        for code, label in (line.rstrip("\r").split("\t") for line in sec_raw.decode("utf-8").splitlines() if line.strip())
        if code.isdigit()
    }
    records = [r for r in cn_2026(cn_raw) if len(r[0]) == 2]
    chapters = {r[0]: r[3] for r in records}
    by_code = {r[0]: r for r in records}
    items = [
        ev(EUROSTAT, "Comext classification file CN_SECTIONS.txt (tab-separated text)", sec_url, "row 11", sections["11"], "text", f"11 {sections['11']}", "CC-BY-4.0", sec_raw),
        ev(EUROSTAT, "Comext classification file CN.txt (tab-separated text)", cn_url, "row 61", chapters["61"], "text", cn_line(by_code["61"]), "CC-BY-4.0", cn_raw),
        ev(EUROSTAT, "Comext classification file CN.txt (tab-separated text)", cn_url, "row 85", chapters["85"], "text", cn_line(by_code["85"])[:120].rsplit(" ", 1)[0], "CC-BY-4.0", cn_raw),
    ]
    return rule(
        "eu-combined-nomenclature-2026-sections-and-chapters",
        "EU Combined Nomenclature 2026 sections and chapters with titles (Eurostat Comext)",
        "trade", "EU", status="verified", tier="A", valid_from=CN_YEAR_START.isoformat(), valid_to=CN_YEAR_END.isoformat(),
        tags=[*TAGS, "combined-nomenclature", "harmonized-system", "code-list"], use_cases=TRADE_USES,
        implementation="enumeration",
        parameters={"sets": {"section": sections, "chapter": chapters}},
        vectors=[
            {"input": {"set": "chapter", "value": "61"}, "expected": True, "origin": "source"},
            {"input": {"set": "section", "value": "11"}, "expected": True, "origin": "source"},
            {"input": {"set": "chapter", "value": "77"}, "expected": "77" in chapters, "origin": "source"},
        ],
        evidence_items=items,
        tests=exact([("count[section]", len(sections)), ("count[chapter]", len(chapters))]),
        notes=(
            "The sections and two-digit chapters of the EU Combined Nomenclature as Eurostat's Comext database carries them. "
            "Chapters are the numeric two-digit codes of CN.txt whose validity window covers all of 2026 (start on or before "
            "1 January, end on or after 31 December); Comext's statistical aggregates (codes with XX, the total TO) are "
            "dropped from both the chapters and the sections. Chapter titles are upper case as Comext stores them; Comext's chapter 99 groups special statistical "
            "codes and is not part of the Harmonized System. Section titles come from CN_SECTIONS.txt, numbered 01 to 21, and "
            "follow the wording Comext stores, which may lag the latest Harmonized System edition. Eurostat publishes under "
            "CC BY 4.0."
        ),
    )


def eu_cn_headings(cn_url: str, cn_raw: bytes) -> dict:
    records = [r for r in cn_2026(cn_raw) if len(r[0]) == 4]
    headings = {r[0]: r[3] for r in records}
    by_code = {r[0]: r for r in records}
    items = [
        ev(EUROSTAT, "Comext classification file CN.txt (tab-separated text)", cn_url, f"row {code}", headings[code], "text",
           " ".join(cn_line(by_code[code]).split()[:20]), "CC-BY-4.0", cn_raw)
        for code in ("0101", "6109", "8471", "9503")
    ]
    return rule(
        "eu-combined-nomenclature-2026-headings",
        "EU Combined Nomenclature 2026 four-digit headings with descriptions (Eurostat Comext)",
        "trade", "EU", status="verified", tier="A", valid_from=CN_YEAR_START.isoformat(), valid_to=CN_YEAR_END.isoformat(),
        tags=[*TAGS, "combined-nomenclature", "harmonized-system", "code-list"], use_cases=[*TRADE_USES, "product-catalogue"],
        implementation="enumeration",
        parameters={"sets": {"heading": headings}},
        vectors=[
            {"input": {"set": "heading", "value": "6109"}, "expected": True, "origin": "source"},
            {"input": {"set": "heading", "value": "8471"}, "expected": True, "origin": "source"},
            {"input": {"set": "heading", "value": "6100"}, "expected": False, "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count[heading]", len(headings))]),
        notes=(
            "Every four-digit heading of the EU Combined Nomenclature in force throughout 2026, with Eurostat's English "
            "description, from the Comext classification file CN.txt: numeric four-digit codes whose validity window starts "
            "on or before 1 January 2026 and ends on or after 31 December 2026. Comext descriptions are its own "
            "self-contained wording (with 'excl.' and 'incl.' qualifiers), which differs from the legal text of Annex I to "
            "Regulation (EEC) No 2658/87. Codes of Comext chapter 99 (special statistical codes) are included where they "
            "are four-digit and numeric. Eurostat publishes under CC BY 4.0."
        ),
    )


def eu_cn_changes() -> dict:
    new_url, new_raw = comext("CN_New_2026.txt")
    closed_url, closed_raw = comext("CN_Close_2026.txt")
    new = {r[0]: r[3] for r in cn_records(new_raw)}
    closed = {r[0]: r[3] for r in cn_records(closed_raw)}
    first_new = cn_records(new_raw)[0]
    first_closed = cn_records(closed_raw)[0]
    items = [
        ev(EUROSTAT, "Comext classification file CN_New_2026.txt (tab-separated text)", new_url, f"row {first_new[0]}", first_new[0], "text",
           " ".join(cn_line(first_new).split()[:12]), "CC-BY-4.0", new_raw),
        ev(EUROSTAT, "Comext classification file CN_Close_2026.txt (tab-separated text)", closed_url, f"row {first_closed[0]}", first_closed[0], "text",
           " ".join(cn_line(first_closed).split()[:12]), "CC-BY-4.0", closed_raw),
    ]
    return rule(
        "eu-combined-nomenclature-2026-new-and-closed-codes",
        "EU Combined Nomenclature eight-digit codes opened on 1 January 2026 and closed at the end of 2025 (Eurostat Comext)",
        "trade", "EU", status="verified", tier="A", valid_from=CN_YEAR_START.isoformat(), valid_to=CN_YEAR_END.isoformat(),
        tags=[*TAGS, "combined-nomenclature", "code-list", "code-changes"], use_cases=[*TRADE_USES, "data-quality-validation"],
        implementation="enumeration",
        parameters={"sets": {"opened_2026": new, "closed_2025": closed}},
        vectors=[
            {"input": {"set": "opened_2026", "value": first_new[0]}, "expected": True, "origin": "source"},
            {"input": {"set": "closed_2025", "value": first_closed[0]}, "expected": True, "origin": "source"},
            {"input": {"set": "opened_2026", "value": first_closed[0]}, "expected": False, "origin": "source"},
        ],
        evidence_items=items,
        tests=exact([("count[opened_2026]", len(new)), ("count[closed_2025]", len(closed))]),
        notes=(
            "The eight-digit Combined Nomenclature codes Eurostat lists as new in CN 2026 (validity starting 1 January 2026) "
            "and as closed (validity ending 31 December 2025), from the Comext files CN_New_2026.txt and CN_Close_2026.txt. "
            "Useful for testing that records dated before and after the 2026 changeover carry codes valid on their date. "
            "Eurostat publishes under CC BY 4.0."
        ),
    )


# ---------------------------------------------------------------- OECD Consumption Tax Trends tables

OECD_CTT = "https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/consumption-tax-trends/"
OECD = "OECD Centre for Tax Policy and Administration"
OECD_AREA = "https://sdmx.oecd.org/public/rest/codelist/OECD/CL_AREA/1.12"
OECD_LICENSE_NOTE = (
    "No licence statement was found in the OECD file or in a byte-stable OECD document, so the licence is recorded as "
    "unstated and the entry held at license-review."
)
OECD_NAME_ALIASES = {"Czech Republic": "CZE"}


def oecd_area_codes() -> tuple[dict[str, str], bytes]:
    raw = fetch(OECD_AREA)
    text = raw.decode("utf-8")
    codes = {}
    for m in re.finditer(r'<structure:Code id="([A-Z]{3})">.*?<common:Name xml:lang="en">([^<]*)</common:Name>', text, re.DOTALL):
        codes.setdefault(m.group(2), m.group(1))
    return codes, raw


def oecd_iso3(name: str, codes: dict[str, str]) -> str:
    clean = re.sub(r"[\d*]+$", "", name).strip()
    if clean in OECD_NAME_ALIASES:
        return OECD_NAME_ALIASES[clean]
    return codes[clean]


def xlsx_cell(raw: bytes, ref: str) -> tuple[str, str]:
    """The raw XML of one cell of the first worksheet, and its stored value."""
    sheet = zipfile.ZipFile(io.BytesIO(raw)).read("xl/worksheets/sheet1.xml").decode("utf-8")
    m = re.search(rf'<c r="{ref}"[^>]*><v>([^<]*)</v></c>', sheet)
    if m is None:
        raise ValueError(f"cell {ref} not found")
    return m.group(0), m.group(1)


def rate_list(text: Any) -> list[float]:
    """Published rates as numbers; dashes mean none, brackets mark temporary rates and are left out."""
    if text is None:
        return []
    value = re.sub(r"\(.*?\)", "", str(text)).strip()
    if value in ("", "-"):
        return []
    return [number(part) for part in re.split(r"[/ ]+", value) if part.strip()]


def global_oecd_vat_rates(codes: dict[str, str], area_raw: bytes) -> dict:
    url = OECD_CTT + "vat-gst-rates-ctt-trends.xlsx"
    raw = fetch(url)
    sheet = openpyxl.load_workbook(io.BytesIO(raw)).worksheets[0]
    table = [row for row in sheet.iter_rows(values_only=True) if any(cell is not None for cell in row)]
    header = next(row for row in table if 2005 in row)
    year_cols = {i: str(v) for i, v in enumerate(header) if isinstance(v, int)}
    reduced_col = next(i for i, v in enumerate(header) if isinstance(v, str) and v.startswith("Reduced rates"))
    regional_col = next(i for i, v in enumerate(header) if v == "Regional rates")
    rows: dict[str, dict] = {}
    for line in table[table.index(header) + 1:]:
        name = line[0]
        if not isinstance(name, str) or name.startswith(("Unweighted", "Source")):
            break
        standard = {year: number(line[i]) for i, year in year_cols.items() if isinstance(line[i], (int, float))}
        rows[oecd_iso3(name, codes)] = {
            "country": re.sub(r"[\d*]+$", "", name).strip(),
            "standard_rate_by_year": standard,
            "standard_rate_2023": standard.get("2023"),
            "reduced_rates_2023": rate_list(line[reduced_col]),
            "reduced_rates_published": str(line[reduced_col]).strip() if line[reduced_col] is not None else None,
            "regional_rates_published": str(line[regional_col]).strip() if line[regional_col] is not None else None,
        }
    france = next(i for i, line in enumerate(sheet.iter_rows(values_only=True), start=1) if line[0] == "France*")
    france_cell = xlsx_cell(raw, f"B{france}")
    items = [
        ev(OECD, "Consumption Tax Trends, Annex Table 2.A.1 VAT rates (XLSX)", url, "sheet 1, title", "Annex Table 2.A.1. VAT rates", "text", "Annex Table 2.A.1. VAT rates", "unstated", raw),
        ev(OECD, "Consumption Tax Trends, Annex Table 2.A.1 VAT rates (XLSX)", url, "sheet 1, source line", "position as at 1 September 2023", "text", "Source: National delegates - position as at 1 September 2023", "unstated", raw),
        ev(OECD, "Consumption Tax Trends, Annex Table 2.A.1 VAT rates (XLSX)", url, "sheet 1, row Belgium, reduced rates", rows["BEL"]["reduced_rates_published"], "text", rows["BEL"]["reduced_rates_published"], "unstated", raw),
        ev(OECD, "Consumption Tax Trends, Annex Table 2.A.1 VAT rates (XLSX)", url, f"sheet 1, cell B{france} (France, 2005)", france_cell[1], "decimal", france_cell[0], "unstated", raw),
        ev(OECD, "OECD SDMX codelist CL_AREA version 1.12 (XML)", OECD_AREA, "Code JPN", "JPN", "text", '<structure:Code id="JPN">', "unstated", area_raw, role="supporting"),
    ]
    return rule(
        "global-oecd-vat-gst-rates-2005-2023",
        "VAT/GST standard rates by country and year 2005 to 2023, with reduced and regional rates (OECD Consumption Tax Trends)",
        "tax", "global", status="license-review", tier="A", valid_from="2005-01-01", valid_to="2023-09-01",
        tags=[*TAX_TAGS, "oecd", "reference-table", "by-country"], use_cases=[*TAX_USES, "multi-currency-ledger"],
        implementation="lookup_table",
        parameters={"key": "ISO 3166-1 alpha-3, as OECD codelist CL_AREA", "rows": rows},
        vectors=[
            {"input": {"key": "JPN", "column": "standard_rate_2023"}, "expected": rows["JPN"]["standard_rate_2023"], "origin": "source"},
            {"input": {"key": "BEL", "column": "reduced_rates_published"}, "expected": rows["BEL"]["reduced_rates_published"], "origin": "source"},
            {"input": "DEU", "expected": True, "origin": "source"},
            {"input": "USA", "expected": False, "origin": "source", "note": "the United States levies no VAT and is absent from the table"},
        ],
        evidence_items=items,
        tests=exact([("count", len(rows)), ("value[GBR,standard_rate_2023]", rows["GBR"]["standard_rate_2023"]), ("max[standard_rate_2023]", max(r["standard_rate_2023"] for r in rows.values()))]),
        assumed=[
            {"parameter": "rows (keys)", "value": "OECD CL_AREA alpha-3 code matched on the English country name",
             "method": "derived", "rationale": "The table names countries only. Names are matched to the OECD area codelist "
             "after removing note markers; 'Czech Republic', the older name the table uses, is matched to CZE."},
            {"parameter": "rows[*].reduced_rates_2023", "value": "published reduced-rate string split on '/' and spaces",
             "method": "derived", "rationale": "The table prints reduced rates as one string such as 0.0/6.0/12.0; temporary "
             "rates the table puts in brackets are left out of the list and kept in reduced_rates_published."},
        ],
        notes=(
            "Standard VAT/GST rates of the OECD member countries from Annex Table 2.A.1 of OECD Consumption Tax Trends, "
            "keyed by ISO alpha-3 code: the rate applicable on 1 January of each year from 2005 to 2022 and as at "
            "1 September 2023, with the reduced rates (including domestic zero rates) and regional rates applicable at "
            "1 September 2023. The table does not record changes after 1 September 2023, so valid_to is that date; the "
            "table's country notes describe later announced changes, which are not applied here. 2006 is not a column of "
            "the table, and its columns of temporary standard-rate reductions during 2021 to 2023 are not copied. Rates "
            "are percentages. Of the EU member states, Bulgaria, Croatia, Cyprus, Malta and Romania are "
            "not OECD members and are not covered. " + OECD_LICENSE_NOTE
        ),
    )


def global_oecd_vat_thresholds(codes: dict[str, str]) -> dict:
    url = OECD_CTT + "vat-gst-annual-turnover-concessions-ctt-trends.xlsx"
    raw = fetch(url)
    sheet = openpyxl.load_workbook(io.BytesIO(raw))["2023"]
    table = [row for row in sheet.iter_rows(values_only=True) if any(cell is not None for cell in row)]
    units_row = next(i for i, row in enumerate(table) if row[3] == "Nat. curr.")
    rows: dict[str, dict] = {}
    last = None
    for line in table[units_row + 1:]:
        name, currency, kind, general, _, other = line[:6]
        if isinstance(name, str) and name.startswith("Source"):
            break
        if name is None:
            if last and other not in (None, "None") and str(other).replace(".", "").isdigit():
                rows[last]["other_thresholds"].append(number(other))
            continue
        code = oecd_iso3(name, codes)
        def numeric(v: Any) -> int | float | None:
            return number(v) if v not in (None, "None") and str(v).replace(".", "").isdigit() else None
        rows[code] = {
            "country": re.sub(r"[\d*]+$", "", name).strip(),
            "currency": currency,
            "threshold_type": {"R": "registration", "C": "collection"}.get(str(kind).strip()),
            "general_threshold": numeric(general),
            "other_thresholds": [x for x in [numeric(other)] if x is not None],
            "voluntary_registration": {"Yes": True, "No": False}.get(str(line[7]).strip()) if line[7] else None,
            "minimum_registration_period": None if line[8] in (None, "None") else str(line[8]).strip(),
        }
        last = code
    items = [
        ev(OECD, "Consumption Tax Trends, Annex Table 2.5 annual turnover concessions for VAT/GST registration (XLSX)", url, "sheet 2023, title",
           "Annual turnover concessions for VAT/GST registration and collection", "text", "Annex Table 2.5. Annual turnover concessions for VAT/GST registration and collection", "unstated", raw),
        ev(OECD, "Consumption Tax Trends, Annex Table 2.5 annual turnover concessions for VAT/GST registration (XLSX)", url, "sheet 2023, source line",
           "position as at 1 September 2023", "text", "Source: National delegates - position as at 1 September 2023", "unstated", raw),
        ev(OECD, "Consumption Tax Trends, Annex Table 2.5 annual turnover concessions for VAT/GST registration (XLSX)", url, "sheet 2023, row United Kingdom",
           str(rows["GBR"]["general_threshold"]), "integer", str(rows["GBR"]["general_threshold"]), "unstated", raw),
    ]
    with_threshold = {k: v for k, v in rows.items() if v["general_threshold"] is not None}
    return rule(
        "global-oecd-vat-gst-registration-thresholds-2023",
        "VAT/GST registration and collection turnover thresholds by OECD country, position at 1 September 2023 (OECD)",
        "tax", "global", status="license-review", tier="A", valid_from="2023-09-01", valid_to="2023-09-01",
        tags=[*TAX_TAGS, "oecd", "registration-threshold", "small-business", "by-country"], use_cases=[*TAX_USES, "kyb-onboarding", "company-generation"],
        implementation="lookup_table",
        parameters={"key": "ISO 3166-1 alpha-3, as OECD codelist CL_AREA", "amounts": "national currency, annual turnover", "rows": rows},
        vectors=[
            {"input": {"key": "GBR", "column": "general_threshold"}, "expected": rows["GBR"]["general_threshold"], "origin": "source"},
            {"input": {"key": "JPN", "column": "currency"}, "expected": rows["JPN"]["currency"], "origin": "source"},
            {"input": "USA", "expected": False, "origin": "source"},
        ],
        evidence_items=items,
        tests=exact([("count", len(rows)), ("value[GBR,general_threshold]", rows["GBR"]["general_threshold"])]),
        assumed=[{"parameter": "rows (keys)", "value": "OECD CL_AREA alpha-3 code matched on the English country name",
                  "method": "derived", "rationale": "As for the OECD VAT rate table; 'Czech Republic' is matched to CZE."}],
        notes=(
            "Annual turnover thresholds below which domestic businesses need not register for, or collect, VAT/GST, from "
            "Annex Table 2.5 of OECD Consumption Tax Trends (sheet 2023, position as at 1 September 2023): the national "
            "currency, whether the threshold governs registration or collection, the general threshold, any other "
            "thresholds the table lists for special sectors (explained in the table's country notes), whether voluntary "
            f"registration is allowed and the minimum registration period. {len(with_threshold)} of the {len(rows)} countries "
            "have a numeric general threshold; the rest have none or one the table describes only in a country note. "
            "The USD columns of the table are formulas and are not copied. " + OECD_LICENSE_NOTE
        ),
    )


# ---------------------------------------------------------------- National consumption-tax rates


def au_gst() -> dict:
    url = "https://www.legislation.gov.au/C2004A00446/2026-01-01/2026-01-01/text/original/pdf/1"
    raw = fetch(url)
    pages = pdf_text(raw)
    page = next(i for i, t in enumerate(pages) if "9-70  The amount of GST on taxable supplies" in t)
    text = " ".join(pages[page].split())
    rate = number(re.search(r"The amount of GST on a \*taxable supply is (\d+)% of the \*value of", text).group(1))
    compilation = re.search(r"Compilation No\. (\d+) Compilation date: (\d{2}/\d{2}/\d{4})", " ".join(pages[0].split()) + " " + text)
    compiled = datetime.strptime(compilation.group(2), "%d/%m/%Y").date().isoformat()
    title = f"A New Tax System (Goods and Services Tax) Act 1999, Compilation No. {compilation.group(1)}, volume 1 (PDF)"
    publisher = "Office of Parliamentary Counsel, Federal Register of Legislation (Australia)"
    items = [
        ev(publisher, title, url, f"page {page + 1}, section 9-70", f"{rate}% of the *value of", "text", "The amount of GST on a *taxable supply is", "unstated", raw),
        ev(publisher, title, url, f"page {page + 1}, header", compilation.group(2), "date", f"Compilation No. {compilation.group(1)} Compilation date: {compilation.group(2)}", "unstated", raw, role="supporting"),
    ]
    return rule(
        "au-gst-rate",
        "Australia GST rate on taxable supplies, A New Tax System (Goods and Services Tax) Act 1999 s 9-70",
        "tax", "AU", status="license-review", tier="B", valid_from=compiled, valid_to=None,
        tags=[*TAX_TAGS, "gst"], use_cases=TAX_USES,
        implementation="consumption_tax",
        parameters={"slabs": {"standard": rate}, "rounding": "0.01", "section": "9-70", "compilation": compilation.group(1)},
        vectors=[
            {"input": rate, "expected": True, "origin": "source"},
            {"input": {"gross": 110, "slab": "standard"}, "expected": "10.00", "origin": "derived", "note": "s 9-75 values a supply at price x 10/11"},
            {"input": {"net": 100, "slab": "standard"}, "expected": "10.00", "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", 1), ("slab[standard]", rate)]),
        notes=(
            "Section 9-70 of the A New Tax System (Goods and Services Tax) Act 1999 sets the GST on a taxable supply as a "
            "percentage of its value, and section 9-75 values a supply at the GST-inclusive price times 10/11, so the GST "
            "inside a GST-inclusive price is one eleventh of it. GST-free and input-taxed supplies carry no GST and are not "
            "slabs. The text is the authorised compilation in force from the compilation date, which sets valid_from (the "
            "rate itself is older). The Federal Register of Legislation PDF for a compilation does not change once "
            "registered. Its licence is not stated in the document, so the licence is unstated and the entry held at "
            "license-review."
        ),
    )


def ch_vat() -> dict:
    url = "https://fedlex.data.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/2009/615/20250331/en/xml/fedlex-data-admin-ch-eli-cc-2009-615-20250331-en-xml-3.xml"
    raw = fetch(url)
    text = raw.decode("utf-8")
    article = text[text.index('eId="art_25"'):text.index('eId="art_26"')]
    standard = re.search(r"The tax rate is ([\d.]+) per cent \(standard rate\)", article).group(1)
    reduced = re.search(r"The reduced tax rate of ([\d.]+) per cent applies to", article).group(1)
    special = re.search(r"The tax on accommodation services is ([\d.]+) per cent \(special rate\)", article).group(1)
    in_force = re.search(r"in force since (\d+ \w+\.? \d{4})", article).group(1)
    valid_from = datetime.strptime(in_force.replace(".", ""), "%d %b %Y").date().isoformat()
    publisher = "Swiss Federal Chancellery, Fedlex"
    title = "Federal Act on Value Added Tax (VAT Act) SR 641.20, consolidated version of 31 March 2025, English (XML)"
    items = [
        ev(publisher, title, url, "Art. 25 para. 1", f"{standard} per cent", "text", f"The tax rate is {standard} per cent (standard rate)", "unstated", raw),
        ev(publisher, title, url, "Art. 25 para. 2", f"{reduced} per cent", "text", f"The reduced tax rate of {reduced} per cent applies to", "unstated", raw),
        ev(publisher, title, url, "Art. 25 para. 4", f"{special} per cent", "text", f"The tax on accommodation services is {special} per cent (special rate)", "unstated", raw),
        ev(publisher, title, url, "Art. 25 para. 1, note", in_force, "text", f"in force since {in_force}", "unstated", raw, role="supporting"),
    ]
    return rule(
        "ch-vat-rates",
        "Switzerland VAT rates: standard, reduced and accommodation special rate (VAT Act SR 641.20, Art. 25)",
        "tax", "CH", status="license-review", tier="A", valid_from=valid_from, valid_to=None,
        tags=[*TAX_TAGS, "mwst"], use_cases=TAX_USES,
        implementation="consumption_tax",
        parameters={"slabs": {"standard": number(standard), "reduced": number(reduced), "accommodation": number(special)}, "rounding": "0.01", "currency": "CHF"},
        vectors=[
            {"input": number(standard), "expected": True, "origin": "source"},
            {"input": number(reduced), "expected": True, "origin": "source"},
            {"input": number(special), "expected": True, "origin": "source"},
            {"input": {"net": 100, "slab": "standard"}, "expected": f"{number(standard):.2f}", "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", 3), ("slab[standard]", number(standard)), ("slab[reduced]", number(reduced))]),
        notes=(
            "Article 25 of the Swiss Federal Act on Value Added Tax: the standard rate, the reduced rate (tap water, "
            "foodstuffs other than alcohol, livestock, seeds and plants, animal feed, medication, printed matter and other "
            "items listed in paragraph 2) and the special rate for accommodation services, which paragraph 4 limits in time "
            "(see the text). The standard and reduced rates are in force since the date the amending note gives, which sets "
            "valid_from. The source is the Fedlex XML of the consolidated version of 31 March 2025, the latest English "
            "version in Fedlex's SPARQL index when the entry was built; English is not an official language of Swiss law, "
            "so the German text prevails. Fedlex states no licence in the file, so the licence is unstated and the entry "
            "held at license-review."
        ),
    )


def jp_consumption_tax() -> dict:
    url = "https://www.nta.go.jp/english/taxes/consumption_tax/01.htm"
    raw = fetch(url)
    text = raw.decode("utf-8")
    table = text[text.index("No.10"):text.index("No.11")]
    cells = re.findall(r'<td class="center"[^>]*>([\d.]+)％', table)
    if len(cells) != 9:
        raise ValueError(f"expected 9 rate cells in the NTA table, found {len(cells)}")
    national, local, total = cells[0:3], cells[3:6], cells[6:9]
    threshold = re.search(r"equal to or less than (\d+)million yen", text).group(1)
    publisher = "National Tax Agency, Japan"
    title = "Consumption Tax basic knowledge, National Tax Agency English site (HTML)"
    items = [
        ev(publisher, title, url, "No.10, table row Total", f"{total[1]}％", "percent", '<th colspan="2" scope="col">From October 1,2019</th>', "unstated", raw),
        ev(publisher, title, url, "No.10, table row National Consumption Tax rate", f"{national[2]}％", "percent", "National Consumption<br>Tax rate", "unstated", raw),
        ev(publisher, title, url, "No.10, table row Local Consumption Tax rate", f"{local[1]}％", "percent", "Local Consumption<br>Tax rate", "unstated", raw),
        ev(publisher, title, url, "No.7 Exemption threshold for business", f"{threshold}million yen", "text", "if its taxable sales in the Base Period for the Taxable Period are equal to or less than", "unstated", raw),
    ]
    return rule(
        "jp-consumption-tax-rates",
        "Japan consumption tax rates from 1 October 2019: standard and reduced, with national and local components (NTA)",
        "tax", "JP", status="license-review", tier="B", valid_from="2019-10-01", valid_to=None,
        tags=[*TAX_TAGS, "japan-consumption-tax"], use_cases=TAX_USES,
        implementation="consumption_tax",
        parameters={
            "slabs": {"standard": number(total[1]), "reduced": number(total[2])},
            "rounding": "1",
            "currency": "JPY",
            "components": {
                "standard": {"national": number(national[1]), "local": number(local[1])},
                "reduced": {"national": number(national[2]), "local": number(local[2])},
            },
            "previous_rate_until_2019_09_30": {"total": number(total[0]), "national": number(national[0]), "local": number(local[0])},
            "reduced_rate_items": ["food and drink excluding alcoholic drink and dining out", "newspapers issued twice a week or more, by subscription"],
            "exemption_threshold_base_period_taxable_sales_jpy": int(threshold) * 1_000_000,
        },
        vectors=[
            {"input": number(total[1]), "expected": True, "origin": "source"},
            {"input": number(total[2]), "expected": True, "origin": "source"},
            {"input": {"net": 1000, "slab": "reduced"}, "expected": str(int(1000 * number(total[2]) / 100)), "origin": "derived"},
        ],
        evidence_items=items,
        tests=exact([("count", 2), ("slab[standard]", number(total[1])), ("slab[reduced]", number(total[2]))]),
        assumed=[{"parameter": "exemption_threshold_base_period_taxable_sales_jpy", "value": int(threshold) * 1_000_000,
                  "method": "derived", "rationale": f"The NTA states the threshold as '{threshold}million yen'; it is written out in yen."}],
        notes=(
            "Japan's consumption tax as the National Tax Agency's English guidance states it: from 1 October 2019 a standard "
            "rate and a reduced rate (food and drink other than alcohol and dining out, and subscription newspapers issued "
            "at least twice a week), each split into a national consumption tax and a local consumption tax; the combined "
            "rate before that date is kept for history. A business whose taxable sales in the base period do not exceed the "
            "stated threshold is in principle exempt. Rounding to whole yen is a convenience for demos, not a rule from the "
            "source. The NTA page is static HTML and byte-stable; it states no licence, so the entry is held at "
            "license-review."
        ),
    )


def sg_gst() -> dict:
    url = "https://www.iras.gov.sg/docs/default-source/e-tax/etaxguide_gst_gst-general-guide-for-businesses(1).pdf?sfvrsn=8a66716d_110"
    raw = fetch(url)
    text = " ".join(" ".join(pdf_text(raw)).split())
    since, rate = re.search(r"Since (\d+ \w+ \d{4}), the GST rate is (\d+)%", text).groups()
    zero = re.search(r"Zero-rated Supply GST is charged at (\d+)%", text).group(1)
    value, tax, total = re.search(r"The value of supply is \$(\d+)\. The GST will be \d+% of the value of supply, which is \$ ?(\d+\.\d+)\. The consideration in money will be the addition of the value of supply and the GST which is \$(\d+\.\d+)", text).groups()
    publisher = "Inland Revenue Authority of Singapore"
    title = "IRAS e-Tax Guide, GST: General Guide for Businesses (PDF)"
    items = [
        ev(publisher, title, url, "paragraph 2.1", f"the GST rate is {rate}%", "text", f"Since {since}, the GST rate is {rate}%", "unstated", raw),
        ev(publisher, title, url, "paragraph 4.2", f"GST is charged at {zero}%", "text", "There are two categories of zero -rated supply", "unstated", raw),
        ev(publisher, title, url, "paragraph 5.5.2, example", f"which is $ {tax}", "text", "The value of supply is $40", "unstated", raw),
    ]
    valid_from = datetime.strptime(since, "%d %b %Y").date().isoformat()
    return rule(
        "sg-gst-rates",
        "Singapore GST standard rate and zero rate with the IRAS tax-exclusive worked example",
        "tax", "SG", status="license-review", tier="B", valid_from=valid_from, valid_to=None,
        tags=[*TAX_TAGS, "gst"], use_cases=TAX_USES,
        implementation="consumption_tax",
        parameters={"slabs": {"standard": number(rate), "zero": number(zero)}, "rounding": "0.01", "currency": "SGD"},
        vectors=[
            {"input": number(rate), "expected": True, "origin": "source"},
            {"input": {"net": number(value), "slab": "standard"}, "expected": tax, "origin": "source", "note": "paragraph 5.5.2 example"},
            {"input": {"gross": total, "slab": "standard"}, "expected": tax, "origin": "derived", "note": "tax fraction of paragraph 5.5.4"},
        ],
        evidence_items=items,
        tests=exact([("count", 2), ("slab[standard]", number(rate))]),
        notes=(
            "Singapore's goods and services tax as the IRAS general guide for businesses states it: the standard rate since "
            "the date in paragraph 2.1 (valid_from), the zero rate for exports of goods and international services "
            "(paragraph 4.2), and the guide's own worked example of tax on a tax-exclusive price (paragraph 5.5.2); the "
            "guide gives the tax fraction for tax-inclusive amounts in paragraph 5.5.4. Exempt and out-of-scope supplies "
            "carry no GST and are not slabs. The guide's URL carries IRAS's document version, so it is pinned to this "
            "edition; the HTML rate page is not cited because its links carry version suffixes. IRAS states no licence in "
            "the guide, so the entry is held at license-review."
        ),
    )


def no_vat() -> dict:
    year = 2026
    url = f"https://www.skatteetaten.no/en/rates/value-added-tax/?year={year}"
    raw = fetch(url)
    text = raw.decode("utf-8")
    if f'<option selected value="{year}">' not in text:
        raise ValueError(f"the Skatteetaten page did not select {year}")
    table = text[text.index("<table"):text.index("</table>")]
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td>\s*(.*?)\s*</td>", table, re.DOTALL)]
    pairs = dict(zip(cells[0::2], cells[1::2]))
    names = {"Normal rate": "standard", "Foodstuffs": "foodstuffs", "Water and wastewater services": "water_and_wastewater",
             "Passenger transport, cinema tickets, letting of rooms*": "passenger_transport_cinema_accommodation"}
    slabs = {names[label]: number(value.rstrip(" %")) for label, value in pairs.items()}
    publisher = "Norwegian Tax Administration (Skatteetaten)"
    title = f"VAT rates for {year}, Skatteetaten English site (HTML)"
    items = [ev(publisher, title, url, f"rates table, row '{label}'", f"<p>{value}</p>", "text", f"<p>{label}</p>", "unstated", raw) for label, value in pairs.items()]
    items.append(ev(publisher, title, url, "year picker", str(year), "text", f'<option selected value="{year}">{year}</option>', "unstated", raw, role="supporting"))
    return rule(
        f"no-vat-rates-{year}",
        f"Norway VAT (merverdiavgift) rates for {year}: general, foodstuffs, water and transport/accommodation (Skatteetaten)",
        "tax", "NO", status="license-review", tier="B", valid_from=f"{year}-01-01", valid_to=f"{year}-12-31",
        tags=[*TAX_TAGS, "mva"], use_cases=TAX_USES,
        implementation="consumption_tax",
        parameters={"slabs": slabs, "rounding": "0.01", "currency": "NOK", "year": year},
        vectors=[
            {"input": slabs["standard"], "expected": True, "origin": "source"},
            {"input": slabs["foodstuffs"], "expected": True, "origin": "source"},
            {"input": slabs["passenger_transport_cinema_accommodation"], "expected": True, "origin": "source"},
        ],
        evidence_items=items,
        tests=exact([("count", len(slabs)), ("slab[standard]", slabs["standard"])]),
        notes=(
            f"Norway's VAT rates for {year} as the Norwegian Tax Administration lists them on its English rates page, pinned "
            f"to {year} with the page's year parameter: the general rate, the rate for foodstuffs, the rate for water and "
            "wastewater services, and the low rate for passenger transport, accommodation, public broadcasting and entry to "
            "cinemas, sporting events, amusement parks and activity centres. Supplies that are zero-rated or outside the "
            "scope of VAT are not listed. The page states no licence, so the entry is held at license-review."
        ),
    )


# ---------------------------------------------------------------- main


def main() -> None:
    valid_from, release_item = hts_release()
    write(us_hts_chapters(release_item, valid_from))
    write(us_hts_headings(release_item, valid_from))
    for chapter in HTS_CHAPTERS:
        write(us_hts_chapter_lines(chapter, release_item, valid_from))
    write(us_customs_thresholds())
    write(uk_sections_and_chapters())
    write(uk_commodity_duties())
    cn_url, cn_raw = comext("CN.txt")
    write(eu_cn_sections_and_chapters(cn_url, cn_raw))
    write(eu_cn_headings(cn_url, cn_raw))
    write(eu_cn_changes())
    codes, area_raw = oecd_area_codes()
    write(global_oecd_vat_rates(codes, area_raw))
    write(global_oecd_vat_thresholds(codes))
    write(au_gst())
    write(ch_vat())
    write(jp_consumption_tax())
    write(sg_gst())
    write(no_vat())


if __name__ == "__main__":
    main()

"""Build the Oman statistics entries from the Monthly Statistical Bulletin of the National Centre for
Statistics and Information (NCSI), October 2026 issue, which carries September 2026 figures.

Registered population by governorate and nationality, workers by sector and nationality, expatriate
workers by country of nationality, the consumer price index by group with its weights, guests of
three- to five-star hotels by nationality group, and registered vehicles by registration type. Values
are read from the PDF's extracted text, the same text the verifier searches. Run from the repository
root:

    uv run python tools/build_gulf4_om.py
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, write  # noqa: E402
from _gulf4 import categorical, fetch_patiently, marginal_tests, share_tests, shares_assumption  # noqa: E402

BULLETIN = "https://api.ncsi.gov.om/uploads/pdfs/monthly_statistical_bulletin__october_2026_1792489912.pdf"
BULLETIN_TITLE = "NCSI Monthly Statistical Bulletin, October 2026 (PDF)"
LICENCE_PDF = "https://www.ncsi.gov.om/assets/docs/gov_license.pdf"
PUBLISHER = "National Centre for Statistics and Information, Sultanate of Oman"
LICENSE = "Open Government License - Sultanate of Oman"
TAGS = ["oman", "gcc", "ncsi"]
LICENSE_NOTE = (
    "NCSI data are published under the Open Government License of the Sultanate of Oman, whose general provisions say "
    "it is compatible with Creative Commons Attribution 4.0; it is not itself an SPDX licence, so the entry stays at "
    "license-review."
)
NUMBER = r"(-?[\d,]+(?:\.\d+)?)"

GOVERNORATES = {
    "Muscat": r"Muscat",
    "Dhofar": r"Dhofar",
    "Musandam": r"Musandam",
    "Al Buraymi": r"Al Buraymi -",
    "Ad Dakhiliyah": r"AdDakhliyah",
    "North Al Batinah": r"Al BatinahNorth",
    "South Al Batinah": r"Al Batinah South",
    "South Ash Sharqiyah": r"Ash Sharqiah South",
    "North Ash Sharqiyah": r"Ash Sharqiah North",
    "Adh Dhahirah": r"Adh Dhahirah",
    "Al Wusta": r"Al Wusta",
}
SECTORS = ["Government", "Private", "Family", "Communal", "Other"]
EXPAT_NATIONALITIES = ["Bangladeshis", "Indians", "Pakistanis", "Egyptians", "Philipinos", "Myanmar", "Sri Lankans", "Sudanese", "Tanzanian", "Other Nationalities"]
CPI_GROUPS = {
    "01": ("Food and non-alcoholic beverages", r"1\. Foods & non-alcoholic beverages"),
    "02": ("Tobacco", r"2\. Tobacco"),
    "03": ("Clothing and footwear", r"3\. Clothing & Footwear"),
    "04": ("Housing, water, electricity, gas and other fuels", r"4\. Housing, water, electricity, gas and other fuels"),
    "05": ("Furnishings, household equipment and routine household maintenance", r"5\. Furnishings, household equipment & routing household maintenance"),
    "06": ("Health", r"6\. Health"),
    "07": ("Transport", r"7\. Transport"),
    "08": ("Communication", r"8\. Communication"),
    "09": ("Recreation and culture", r"9\. Recreation and Culture"),
    "10": ("Education", r"10\. Education"),
    "11": ("Restaurants and hotels", r"11\. Resturants and Hotels"),
    "12": ("Miscellaneous goods and services", r"12\. Miscellaneous goods and services"),
    "00": ("General index", r"General Index"),
}
GUEST_GROUPS = ["Omani", "G.C.C.", "Other Arab", "Africans", "Asians", "Europeans", "Americans", "Oceanian", "Not Stated"]
VEHICLE_TYPES = {
    "Private": r"Private",
    "Commercial": r"Commercial",
    "Rental": r"Rental",
    "Taxi": r"Taxi",
    "Motorbikes": r"Motorbikes",
    "Diplomatic": r"Diplomatic",
    "Government": r"Government ¹",
    "Tractors": r"Tractors",
    "Driving School": r"Driving School",
    "Temporary": r"Temporary²",
}


def to_number(text: str) -> float:
    return float(text.replace(",", ""))


class Bulletin:
    """The bulletin's pages as whitespace-collapsed text, matching how the verifier searches a PDF."""

    def __init__(self, raw: bytes) -> None:
        reader = PdfReader(io.BytesIO(raw))
        self.raw = raw
        self.pages = [" ".join((page.extract_text() or "").split()) for page in reader.pages]

    def row(self, page: int, label: str, count: int) -> tuple[list[str], str]:
        """The ``count`` numbers after ``label`` on ``page``, and the matched text for use as a snippet."""
        pattern = label + "".join(r" " + NUMBER for _ in range(count))
        match = re.search(pattern, self.pages[page - 1])
        if match is None:
            raise LookupError(f"page {page}: no row {label!r} with {count} numbers")
        return list(match.groups()), match.group(0)

    def require(self, page: int, text: str) -> None:
        if text not in self.pages[page - 1]:
            raise LookupError(f"page {page}: {text!r} not found")


def item(bulletin: Bulletin, page: int, table: str, label: str, value: str, snippet: str, unit: str = "count") -> dict:
    return evidence(PUBLISHER, BULLETIN_TITLE, BULLETIN, f"page {page}, {table}, row {label}", value, unit, snippet, LICENSE, bulletin.raw)


def licence_item(raw: bytes) -> dict:
    return evidence(
        "Sultanate of Oman (published by the National Centre for Statistics and Information)",
        "Open Government Data License of the Sultanate of Oman (PDF, Arabic)",
        LICENCE_PDF,
        "page 1, Article 6 (general provisions), clause 2: compatibility with Creative Commons",
        "CC BY",
        "text",
        "CREATIVE COMMONS",
        LICENSE,
        raw,
        role="supporting",
    )


def population(b: Bulletin, licence: bytes) -> dict:
    counts: dict[str, dict[str, int]] = {"Omani": {}, "Expatriate": {}}
    first_snippet = ""
    for name, pattern in GOVERNORATES.items():
        cells, matched = b.row(3, pattern, 9)
        total, expatriate, omani = (int(to_number(c)) for c in cells[2:5])
        if expatriate + omani != total:
            raise ValueError(f"{name}: September 2026 columns do not add up")
        counts["Omani"][name] = omani
        counts["Expatriate"][name] = expatriate
        if name == "Muscat":
            muscat = cells
            first_snippet = " ".join(matched.split()[:6])
    total_cells, total_text = b.row(3, "Total Population", 9)
    if round(int(to_number(muscat[4])) / int(to_number(muscat[2])) * 100, 1) != 39.0:
        raise ValueError("Muscat Omani share does not match the bulletin's 39.0% callout; column order changed")
    b.require(3, "39.0% Omanis of the registered Total Population in Muscat")
    dists = {k: categorical(v) for k, v in counts.items()}
    return {
        "id": "om-registered-population-by-governorate-and-nationality-2026-09",
        "title": "Oman registered population by governorate given nationality (Omani, expatriate), September 2026",
        "kind": "conditional",
        "domain": "demographics",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-09-30", "end": "2026-09-30"},
        "tags": TAGS + ["population", "governorate", "nationality", "expatriates", "monthly-bulletin"],
        "use_cases": ["synthetic-customers", "address-generation", "person-generation", "customer-segmentation", "banking-demo", "retail-demo"],
        "spec": {"variable": "governorate", "unit": "ratio", "given": "nationality", "distributions": dists},
        "evidence": [
            item(b, 3, "Table 1 (total population registered by governorate and nationality)", "Muscat", muscat[2], first_snippet),
            item(b, 3, "Table 1, September 2026 Omani column", "Total Population", total_cells[4], " ".join(total_text.split()[:7])),
            item(b, 3, "callout beside Table 1", "Muscat Omani share", "39.0%", "39.0% Omanis of the registered Total Population in Muscat", "text"),
            licence_item(licence),
        ],
        "assumed": [
            shares_assumption("distributions.*.parameters.shares", ""),
            {
                "parameter": "column order",
                "value": "change %, Sep 2025 total, Sep 2026 total, Sep 2026 expatriate, Sep 2026 Omani, Aug 2026 total, Aug 2026 expatriate, Aug 2026 Omani, end-2025 total",
                "method": "derived",
                "rationale": "The PDF's bilingual header extracts out of order. The September 2026 total equals the September 2025 total grown by the printed change; expatriate plus Omani equals the total; and the Omani column gives Muscat the 39.0% Omani share and the country the 56.44% Omani share that the bulletin prints beside the table.",
            },
        ],
        "tests": share_tests(dists, 2),
        "notes": (
            "Population registered in Oman at the end of September 2026 by governorate (11 governorates) for Omanis and "
            "expatriates, from Table 1 of the NCSI Monthly Statistical Bulletin (October 2026 issue). Group totals give the "
            f"nationality split (Omani {sum(counts['Omani'].values()):,}, expatriate {sum(counts['Expatriate'].values()):,}). "
            "Governorate names are normalised; the bulletin spells some differently (AdDakhliyah, Al BatinahNorth, "
            "Ash Sharqiah). " + LICENSE_NOTE
        ),
    }


def workers_by_sector(b: Bulletin, licence: bytes) -> dict:
    counts: dict[str, dict[str, int]] = {"Omani": {}, "Expatriate": {}}
    snippets = {}
    for nationality, page in (("Omani", 20), ("Expatriate", 21)):
        for sector in SECTORS:
            cells, matched = b.row(page, sector, 4)
            counts[nationality][sector] = int(to_number(cells[1]))
            if sector == "Private":
                snippets[nationality] = (cells[1], matched)
        total_cells, _ = b.row(page, "Total Workers", 4)
        if sum(counts[nationality].values()) != int(to_number(total_cells[1])):
            raise ValueError(f"{nationality} sectors do not add up to the total")
    dists = {k: categorical(v) for k, v in counts.items()}
    return {
        "id": "om-workers-by-sector-and-nationality-2026-09",
        "title": "Oman workers by sector (government, private, family) given nationality, September 2026",
        "kind": "conditional",
        "domain": "employment",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-09-30", "end": "2026-09-30"},
        "tags": TAGS + ["employment", "workforce", "sector", "nationality", "expatriates", "domestic-workers", "monthly-bulletin"],
        "use_cases": ["synthetic-employees", "hr-demo", "workforce-planning", "hr-analytics", "payroll-demo"],
        "spec": {"variable": "sector", "unit": "ratio", "given": "nationality", "distributions": dists},
        "evidence": [
            item(b, 20, "Table 17 (Omani workers), by sector", "Private", snippets["Omani"][0], snippets["Omani"][1]),
            item(b, 21, "Table 18 (expatriate workers), by sector", "Private", snippets["Expatriate"][0], snippets["Expatriate"][1]),
            licence_item(licence),
        ],
        "assumed": [
            shares_assumption("distributions.*.parameters.shares", ""),
            {
                "parameter": "column order",
                "value": "change %, Sep 2026, Aug 2026, 2025",
                "method": "derived",
                "rationale": "Tables 17 and 18 use the bulletin's three-period layout; on Table 24 (vehicles), whose pie chart prints shares for September 2026, the first count column reproduces those shares, so the first column is read as September 2026 here too.",
            },
        ],
        "tests": share_tests(dists, 2),
        "notes": (
            "Workers in Oman at the end of September 2026 by sector of employment, for Omanis (Table 17) and expatriates "
            "(Table 18) of the NCSI Monthly Statistical Bulletin (October 2026 issue). 'Family' is employment by households "
            "(domestic workers); 'Communal' is the civil-society sector. The two groups together give the nationality-by-"
            "sector table for synthetic employees. " + LICENSE_NOTE
        ),
    }


def expatriate_nationalities(b: Bulletin, licence: bytes) -> dict:
    counts = {}
    for nationality in EXPAT_NATIONALITIES:
        cells, matched = b.row(21, nationality, 4)
        counts[nationality] = int(to_number(cells[1]))
        if nationality == "Indians":
            indians = (cells[1], matched)
    dist = categorical(counts)
    return {
        "id": "om-expatriate-workers-by-nationality-2026-09",
        "title": "Oman expatriate workers by country of nationality, September 2026",
        "kind": "marginal",
        "domain": "employment",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-09-30", "end": "2026-09-30"},
        "tags": TAGS + ["employment", "expatriates", "migrant-workers", "nationality", "monthly-bulletin"],
        "use_cases": ["synthetic-employees", "hr-demo", "person-generation", "workforce-planning"],
        "spec": {"variable": "expatriate_worker_nationality", "unit": "ratio", "distribution": dist},
        "evidence": [item(b, 21, "Table 18 (expatriate workers), by nationality", "Indians", indians[0], indians[1]), licence_item(licence)],
        "assumed": [shares_assumption("distribution.parameters.shares", "Column order as for Table 18 by sector (first count column is September 2026).")],
        "tests": marginal_tests(dist),
        "notes": (
            "Expatriate workers in Oman at the end of September 2026 by country of nationality: the nine largest groups as "
            "the bulletin lists them (Bangladeshis, Indians, Pakistanis, Egyptians, Philipinos as spelt, Myanmar, Sri Lankans, "
            "Sudanese, Tanzanian) and 'Other Nationalities'. Pair with om-workers-by-sector-and-nationality-2026-09 for the "
            "sector split. " + LICENSE_NOTE
        ),
    }


def cpi(b: Bulletin, licence: bytes) -> dict:
    rows = {}
    for code, (name, pattern) in CPI_GROUPS.items():
        cells, matched = b.row(16, pattern, 7)
        avg, yoy, mom, sep26, aug26, sep25, weight = (float(c) for c in cells)
        if abs((sep26 / sep25 - 1) * 100 - yoy) > 0.15 or abs((sep26 / aug26 - 1) * 100 - mom) > 0.15:
            raise ValueError(f"CPI group {code}: index columns do not reproduce the printed changes")
        rows[code] = {
            "label": name,
            "weight": weight,
            "index_2026_09": sep26,
            "index_2026_08": aug26,
            "index_2025_09": sep25,
            "change_pct_2026_09_on_2025_09": yoy,
            "change_pct_2026_09_on_2026_08": mom,
            "change_pct_jan_sep_2026_average": avg,
        }
        if code == "01":
            food = (cells, matched)
    _, general_text = b.row(16, CPI_GROUPS["00"][1], 7)
    return {
        "id": "om-cpi-by-group-with-weights-2026-09",
        "title": "Oman consumer price index by expenditure group with basket weights, September 2026 (base 2018)",
        "kind": "rule",
        "domain": "economy",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "valid_from": "2026-09-01",
        "valid_to": "2026-09-30",
        "tags": TAGS + ["cpi", "inflation", "prices", "coicop", "basket-weights", "reference-table"],
        "use_cases": ["retail-demo", "pricing", "contract-indexation", "household-generation", "banking-demo"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"base": "average prices of January to December 2018 = 100", "rows": rows},
            "vectors": [
                {"input": {"key": "01", "column": "weight"}, "expected": rows["01"]["weight"], "origin": "source"},
                {"input": {"key": "00", "column": "index_2026_09"}, "expected": rows["00"]["index_2026_09"], "origin": "source"},
                {"input": {"key": "07", "column": "index_2025_09"}, "expected": rows["07"]["index_2025_09"], "origin": "source"},
                {"input": "13", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            item(b, 16, "Table 13 (Sultanate of Oman consumer price index)", "1. Foods & non-alcoholic beverages", food[0][6], " ".join(food[1].split()[-7:]), "decimal"),
            item(b, 16, "Table 13", "General Index", rows["00"]["index_2026_09"], general_text, "decimal"),
            item(b, 16, "Table 13 footnote", "base period", "2018", "Base Price = Average Price of Jan - Dec 2018", "text"),
            licence_item(licence),
        ],
        "assumed": [
            {
                "parameter": "column order",
                "value": "Jan-Sep average change %, Sep/Sep change %, Sep/Aug change %, Sep 2026 index, Aug 2026 index, Sep 2025 index, weight",
                "method": "derived",
                "rationale": "The bilingual header extracts out of order; the builder checks that the three index columns reproduce the printed year-on-year and month-on-month changes within rounding for every group.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[weight]", "expected": max(r["weight"] for r in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Oman's consumer price index for September 2026 by the twelve COICOP expenditure groups and the general index "
            "(key 00), with each group's basket weight (weights sum to 100, the general index row carries 100.0), the index "
            "for September 2026, August 2026 and September 2025, and the changes the bulletin prints. Base: average prices "
            "of January to December 2018. Group labels are normalised (the bulletin prints 'Resturants' and 'routing'). "
            "Weights give a ready household spending mix. " + LICENSE_NOTE
        ),
    }


def hotel_guests(b: Bulletin, licence: bytes) -> dict:
    counts = {}
    for group in GUEST_GROUPS:
        cells, matched = b.row(34, re.escape(group), 7)
        change, ytd26, ytd25 = float(cells[0]), to_number(cells[1]), to_number(cells[2])
        if abs((ytd26 / ytd25 - 1) * 100 - change) > 0.15:
            raise ValueError(f"{group}: January-September columns do not reproduce the printed change")
        counts[group] = int(ytd26)
        if group == "Omani":
            omani = (cells[1], matched)
    total_cells, total_text = b.row(34, r"Total No\. of Guests", 7)
    if sum(counts.values()) != int(to_number(total_cells[1])):
        raise ValueError("guest groups do not add up to the total")
    dist = categorical(counts)
    return {
        "id": "om-hotel-guests-by-nationality-jan-sep-2026",
        "title": "Oman guests of three- to five-star hotels by nationality group, January to September 2026",
        "kind": "marginal",
        "domain": "tourism",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-01-01", "end": "2026-09-30"},
        "tags": TAGS + ["tourism", "hotels", "hotel-guests", "nationality", "monthly-bulletin"],
        "use_cases": ["tourism-demo", "synthetic-customers", "retail-demo", "customer-segmentation"],
        "spec": {"variable": "hotel_guest_nationality_group", "unit": "ratio", "distribution": dist},
        "evidence": [
            item(b, 34, "Table 30 (main indicators for hotels classified 3 to 5 stars)", "Omani", omani[0], " ".join(omani[1].split()[:4])),
            item(b, 34, "Table 30", "Total No. of Guests", total_cells[1], " ".join(total_text.split()[:7])),
            licence_item(licence),
        ],
        "assumed": [
            shares_assumption("distribution.parameters.shares", ""),
            {
                "parameter": "column order",
                "value": "Jan-Sep change %, Jan-Sep 2026, Jan-Sep 2025, Sep, Aug, Jul 2026, full-year 2025",
                "method": "derived",
                "rationale": "The builder checks that the first two count columns reproduce each printed January-September change; the monthly total row matches the bar chart above the table (September 157,929).",
            },
        ],
        "tests": marginal_tests(dist),
        "notes": (
            "Cumulative guests of hotels classified three to five stars in Oman from January to September 2026 by nationality "
            "group (Omani, GCC, other Arab, African, Asian, European, American, Oceanian, not stated), from Table 30 of the "
            "NCSI Monthly Statistical Bulletin (October 2026 issue); 2026 figures are preliminary. " + LICENSE_NOTE
        ),
    }


def vehicles(b: Bulletin, licence: bytes) -> dict:
    counts = {}
    for name, pattern in VEHICLE_TYPES.items():
        cells, matched = b.row(28, re.escape(pattern), 4)
        counts[name] = int(to_number(cells[1]))
        if name == "Private":
            private = (cells[1], matched)
    total_cells, _ = b.row(28, "-Total", 4)
    if sum(counts.values()) != int(to_number(total_cells[1])):
        raise ValueError("vehicle types do not add up to the total")
    if round(counts["Private"] / sum(counts.values()) * 100, 1) != 79.1:
        raise ValueError("private share does not match the pie chart; column order changed")
    b.require(28, "79.1%")
    dist = categorical(counts)
    return {
        "id": "om-registered-vehicles-by-registration-type-2026-09",
        "title": "Oman registered vehicles by registration type, end of September 2026",
        "kind": "marginal",
        "domain": "automotive",
        "region": "OM",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-09-30", "end": "2026-09-30"},
        "tags": TAGS + ["vehicles", "vehicle-registrations", "fleet", "monthly-bulletin"],
        "use_cases": ["automotive-demo", "fleet-demo", "insurance", "synthetic-customers"],
        "spec": {"variable": "vehicle_registration_type", "unit": "ratio", "distribution": dist},
        "evidence": [
            item(b, 28, "Table 24 (total registered vehicles by registered type)", "Private", private[0], " ".join(private[1].split()[:4])),
            licence_item(licence),
        ],
        "assumed": [
            shares_assumption("distribution.parameters.shares", ""),
            {
                "parameter": "column order",
                "value": "change %, Sep 2026, Aug 2026, 2025",
                "method": "derived",
                "rationale": "The first count column reproduces the pie chart's 79.1% private and 15.0% commercial shares for September 2026.",
            },
        ],
        "tests": marginal_tests(dist),
        "notes": (
            "Vehicles registered in Oman at the end of September 2026 by registration type (private, commercial, rental, taxi, "
            "motorbikes, diplomatic, government, tractors, driving school, temporary), from Table 24 of the NCSI Monthly "
            "Statistical Bulletin; the source is the Royal Oman Police. Government excludes military vehicles; temporary "
            "plates cover vehicles under inspection and export or import. " + LICENSE_NOTE
        ),
    }


BUILDERS = [population, workers_by_sector, expatriate_nationalities, cpi, hotel_guests, vehicles]


def build() -> list[Path]:
    bulletin = Bulletin(fetch_patiently(BULLETIN))
    licence = fetch_patiently(LICENCE_PDF)
    return [write(builder(bulletin, licence)) for builder in BUILDERS]


if __name__ == "__main__":
    build()

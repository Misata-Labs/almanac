"""Regenerate the identifier-format and check-digit entries for the world's major economies.

Every rule is read from the body that issues the identifier (business
register, population register, tax authority, gazette or law publisher) or
from the OECD tax identification number sheets that governments supply, and
the vectors are the worked examples those sources print. Run from the
repository root:

    uv run python tools/build_worldids.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import ACCESSED, evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402
from almanac.rules import luhn  # noqa: E402

OECD = "https://www.oecd.org/content/dam/oecd/en/topics/policy-issue-focus/aeoi/{slug}-tin.pdf"
OECD_PUBLISHER = "OECD Global Forum on Transparency and Exchange of Information for Tax Purposes"
CFR_DATE = "2026-10-29"
URLS = {
    "abr": "https://abr.business.gov.au/Help/AbnFormat",
    "pesel": "https://www.gov.pl/web/gov/czym-jest-numer-pesel",
    "cpr": "https://www.cpr.dk/media/12066/personnummeret-i-cpr.pdf",
    "elster": "https://download.elster.de/download/schnittstellen/Pruefung_der_Steuer_und_Steueridentifikatsnummer.pdf",
    "be_ti000": "https://www.rijksregister.fgov.be/sites/default/files/documents/fr/registre-national/instructions/liste-TI/TI000_Numero-identification.pdf",
    "be_rn": "https://www.ibz.rrn.fgov.be/sites/default/files/documents/fr/registre-national/fichier-rn/fichier-RN.pdf",
    "rvig_test": "https://www.rvig.nl/sites/default/files/2023-05/Aansluiting%20testen%20en%20toetsen%20BSN.pdf",
    "rvig_uc27": "https://rvig.nl/sites/default/files/2023-05/uc27-genereren-nummers.pdf",
    "poms": "https://secure.ssa.gov/poms.nsf/lnx/0110201035",
    "cfr": f"https://www.ecfr.gov/api/versioner/v1/full/{CFR_DATE}/title-26.xml?section=301.6109-1",
    "egov": "https://laws.e-gov.go.jp/api/1/lawdata/426M60000008085",
    "scb": "https://www.scb.se/contentassets/8d9d985ca9c84c6e8d879cc89a8ae479/ov9999_2016a01_br_be96br1601.pdf",
    "brreg": "https://www.brreg.no/om-oss/registrene-vare/om-enhetsregisteret/organisasjonsnummeret/",
    "insee_siren": "https://www.insee.fr/fr/metadonnees/definition/c2047",
    "insee_siret": "https://www.insee.fr/fr/metadonnees/definition/c1841",
    "fedlex": "https://fedlex.data.admin.ch/filestore/fedlex.data.admin.ch/eli/cc/63/1185_1183_1185/20250101/de/xml/fedlex-data-admin-ch-eli-cc-63-1185_1183_1185-20250101-de-xml-1.xml",
}
for slug in ("australia", "poland", "germany", "netherlands", "united-states", "sweden", "south-africa", "india", "norway", "lithuania", "france", "switzerland", "ireland", "finland"):
    URLS[f"oecd_{slug}"] = OECD.format(slug=slug)

TAGS = ["identifiers", "check-digit", "kyc"]
PERSON_USES = ["kyc-onboarding", "person-generation", "payroll-demo", "data-quality-validation"]
BUSINESS_USES = ["kyb-onboarding", "company-generation", "invoicing", "data-quality-validation"]


class Source:
    """One fetched resource with the text the verifier will search."""

    def __init__(self, url: str, raw: bytes) -> None:
        self.url = url
        self.raw = raw
        self.text = Resource(url, raw, "").text
        self.collapsed = " ".join(self.text.split())

    def contains(self, needle: str) -> bool:
        return " ".join(str(needle).split()) in self.collapsed

    def find(self, pattern: str, flags: int = 0) -> str:
        match = re.search(pattern, self.text, flags)
        if match is None:
            raise ValueError(f"{pattern!r} not found in {self.url}")
        return match.group(1)

    def find_all(self, pattern: str, flags: int = 0) -> list[Any]:
        return re.findall(pattern, self.text, flags)


def item(source: Source, publisher: str, title: str, locator: str, value: Any, snippet: str, unit: str = "text", role: str = "primary", license_id: str = "unstated") -> dict:
    """An evidence item whose snippet and value are confirmed present in the fetched text."""
    shown = str(value).lower() if isinstance(value, bool) else str(value)
    missing = [name for name, needle in (("snippet", snippet), ("value", shown)) if not source.contains(needle)]
    if missing:
        raise ValueError(f"{', '.join(missing)} not found in {source.url}: {snippet!r} / {value!r}")
    return evidence(publisher, title, source.url, locator, value, unit, snippet, license_id, source.raw, role=role)


def oecd_item(source: Source, country: str, locator: str, value: Any, snippet: str, role: str = "primary") -> dict:
    return item(source, OECD_PUBLISHER, f"{country}: Information on Tax Identification Numbers (PDF)", locator, value, snippet, role=role)


def table_rows(markup: str) -> list[list[str]]:
    """Cells of every row of the first HTML table in ``markup``, tags stripped."""
    block = re.search(r"<table.*?</table>", markup, re.S)
    if block is None:
        raise ValueError("no table found")
    rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", block.group(0), re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        rows.append([html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells])
    return rows


def base(entry_id: str, title: str, region: str, implementation: str, parameters: dict, vectors: list[dict], items: list[dict], notes: str, *, uses: list[str], tier: str = "B", valid_from: str, assumed: list[dict] | None = None, extra_tags: list[str] | None = None) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "identifiers",
        "region": region,
        "status": "license-review",
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": None,
        "tags": TAGS + (extra_tags or []),
        "use_cases": uses,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": items,
        "assumed": assumed or [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "vector_count", "expected": len(vectors), "tolerance": 0},
        ],
        "notes": notes,
    }


def vector(value: Any, expected: Any, origin: str, note: str | None = None) -> dict:
    result = {"input": value, "expected": expected, "origin": origin}
    if note:
        result["note"] = note
    return result


def build_au_abn(abr: Source, oecd: Source) -> dict:
    rows = table_rows(abr.raw.decode("utf-8"))
    weights = [int(row[2]) for row in rows[1:] if row[1].isdigit()]
    total = abr.find(r"Sum \(Digit \* weight\) to give a total of (\d+)")
    parameters = {"weights": weights, "modulus": int(abr.find(r"Divide the sum total by (\d+)")), "first_digit_offset": 1}
    return base(
        "au-abn-check-digits",
        "Australian Business Number (ABN) modulus 89 check digits",
        "AU",
        "almanac.rules.au_abn",
        parameters,
        [
            vector("51 824 753 556", True, "source", f"ABR worked example: weighted sum {total}, divisible by 89"),
            vector("51824753556", True, "source", "same example without spaces"),
            vector({"identifier": "824753556"}, "51", "derived", "leading check digits recovered for the worked example's identifier"),
            vector("52 824 753 556", False, "derived", "first check digit altered"),
            vector("5182475355", False, "derived", "ten digits"),
        ],
        [
            item(abr, "Australian Business Register (Australian Taxation Office)", "Format of the ABN (ABN Lookup help)", "verification steps", "modulus 89", "The leading check digits are derived using a modulus 89 (remainder after dividing by 89) calculation."),
            item(abr, "Australian Business Register (Australian Taxation Office)", "Format of the ABN (ABN Lookup help)", "table 'Validate ABN example', Weighting column", total, "Divide 534 by 89 giving 6 with zero remainder."),
            oecd_item(oecd, "Australia", "Section II, TIN structure", "XX XXX XXX XXX", "The ABN is a unique 11 digit number formed from a nine digit unique identifier and two prefix check", role="supporting"),
        ],
        "The Australian Business Register's own description of the ABN: eleven digits, two leading check digits over a "
        "nine-digit identifier. Verification subtracts 1 from the first digit, weights the eleven digits by the "
        "position weights in the register's example table and requires the sum to be divisible by 89. The weights are "
        "read from that table and the worked example 51 824 753 556 supplies the source vectors. Issuing check digits "
        "for a new identifier means searching the pairs from 10 upwards for the one that satisfies the rule, which the "
        "derived vector exercises. The page states no date or licence, so valid_from is the access date and the entry "
        "is held at license-review.",
        uses=BUSINESS_USES,
        valid_from=ACCESSED.isoformat(),
        extra_tags=["abn", "abr"],
        assumed=[
            {"parameter": "first_digit_offset", "value": 1, "method": "derived", "rationale": "The page says to subtract 1 from the first digit; stored as an offset so the generator can apply it."},
        ],
    )


def build_pl_pesel(gov: Source, oecd: Source) -> dict:
    january = re.search(r"Styczeń(.*?)Luty", gov.raw.decode("utf-8"), re.S)
    if january is None:
        raise ValueError("month table not found")
    codes = re.findall(r">\s*(\d{2})\s*<", january.group(1))
    centuries = [1800, 1900, 2000, 2100, 2200]
    offsets = {str(int(code) - 1): century for code, century in zip(codes, centuries)}
    weights = [int(w) for w in gov.find(r"odpowiednią wagę: ([\d-]+)").split("-")]
    parameters = {
        "check_digit": {"weights": weights, "modulus": 10, "check": "complement", "remainder_map": {"0": 0}},
        "month_offsets": offsets,
    }
    return base(
        "pl-pesel-check-digit",
        "Poland PESEL number: century-coded birth month, sex digit and check digit",
        "PL",
        "almanac.rules.pl_pesel",
        parameters,
        [
            vector({"body": "0207080362"}, "8", "source", "gov.pl worked example: weighted last digits sum to 32, 10 - 2 = 8"),
            vector("02070803628", True, "source", "the full number the worked example produces"),
            vector({"birth_date_of": "02070803628"}, "1902-07-08", "source", "OECD sheet: a person born on the 8 of July 1902"),
            vector({"sex_of": "02070803628"}, "female", "source", "OECD sheet: sex female"),
            vector("02070803627", False, "derived", "check digit altered"),
            vector({"birth_date_of": "02270803620"}, "2002-07-08", "derived", "month field 27 decodes to July 2000-2099 per the month table"),
        ],
        [
            item(gov, "Ministerstwo Cyfryzacji (gov.pl)", "Czym jest numer PESEL", "section 'W jaki sposób obliczysz cyfrę kontrolną'", "1-3-7-9-1-3-7-9-1-3", "Jako przykład posłuży nam numer 0207080362."),
            item(gov, "Ministerstwo Cyfryzacji (gov.pl)", "Czym jest numer PESEL", "section on month coding, month table", "2000-2099", "przyjęto następującą metodę oznaczania miesiąca urodzenia"),
            oecd_item(oecd, "Poland", "Section II, 2.1 PESEL structure, sample", "02070803628", "1. A person born on the 8 of July 1902, sex – female;"),
        ],
        "PESEL as the Polish government describes it: eleven digits RRMMDDPPPPK with the birth month raised by a "
        "century offset (read from the gov.pl month table: 80 for the 1800s, 20 for 2000 to 2099, 40, 60 for the two "
        "centuries after), a serial whose last digit is even for women and odd for men, and a check digit equal to 10 "
        "minus the last digit of the sum of the weighted digits' last digits, which is the same as the weighted sum "
        "modulo 10 subtracted from 10. The gov.pl worked example and the OECD sheet's decoded sample supply the "
        "vectors. Neither page carries a date or licence, so valid_from is the access date and the entry is held at "
        "license-review.",
        uses=PERSON_USES,
        valid_from=ACCESSED.isoformat(),
        extra_tags=["pesel"],
        assumed=[
            {"parameter": "check_digit", "value": "weighted sum modulo 10, complement, 10 written 0", "method": "derived", "rationale": "gov.pl sums only the last digit of each product and subtracts the last digit of the total from 10; that equals 10 minus the full weighted sum modulo 10, and a result of 10 must be written as the single digit 0."},
            {"parameter": "month_offsets", "value": offsets, "method": "derived", "rationale": "Each offset is the January code of a century column in the gov.pl table minus 1."},
        ],
    )


def build_pl_nip(oecd: Source) -> dict:
    block = re.search(r"2\.2\. TIN structure(.*?)Syntax: SAMPLE", oecd.text, re.S)
    if block is None:
        raise ValueError("NIP rule not found")
    weights = [int(w) for w in re.findall(r"C\d \n?(\d)", block.group(1))]
    parameters = {"weights": weights, "modulus": int(block.group(0).split("Get modulo ")[1].split()[0]), "check": "remainder", "remainder_map": {"10": None}}
    return base(
        "pl-nip-check-digit",
        "Poland tax identification number (NIP) modulus 11 check digit",
        "PL",
        "almanac.rules.weighted_modulus",
        parameters,
        [
            vector("2234567895", True, "source", "OECD sheet sample: weighted sum 236, 236 % 11 = 5"),
            vector({"body": "223456789"}, "5", "source"),
            vector("2234567896", False, "derived", "check digit altered"),
            vector({"body": "900000000"}, None, "derived", "weighted sum 54 leaves remainder 10, so no valid number exists"),
        ],
        [
            oecd_item(oecd, "Poland", "Section II, 2.2 TIN structure, rule", "2234567895", "4. Check digit = remainder (if remainder = 10, the TIN is"),
            oecd_item(oecd, "Poland", "Section II, 2.2 TIN structure, sample", "236% 11=5;", "12+10+21+8+15+24+35+48+63=236;"),
        ],
        "The ten-digit Polish tax identification number (NIP) as Poland describes it in its OECD tax identification "
        "number sheet: nine digits weighted 6 5 7 2 3 4 5 6 7, summed and reduced modulo 11; the remainder is the "
        "check digit and a remainder of 10 means the number is not valid. Weights are read from the sheet and its "
        "sample 2234567895 supplies the source vectors. The sheet carries no date or licence statement, so "
        "valid_from is the access date and the entry is held at license-review.",
        uses=BUSINESS_USES,
        valid_from=ACCESSED.isoformat(),
        extra_tags=["nip", "tax-identifier"],
    )


def build_dk_cpr(cpr: Source) -> dict:
    weights = [int(w) for w in cpr.find(r"hver deres værdi\s+((?:\d\s+){8}\d)").split()]
    collapsed = cpr.collapsed
    rows = []
    dash = r" ?[-–] ?"
    pattern = rf"0?1{dash}31 0?1{dash}12 (\d{{2}}){dash}(\d{{2}}) (\d)\d{{3}}{dash}\d{{4}} ulige ciffer = mænd lige ciffer = kvinder (\d{{4}}){dash}\d{{4}}"
    for year_from, year_to, serial, start in re.findall(pattern, collapsed):
        rows.append({"serial_first_digit": serial, "year_from": int(year_from), "year_to": int(year_to), "century": int(start) - int(year_from)})
    if len(rows) < 10:
        raise ValueError(f"century table incomplete: {rows}")
    parameters = {"weights": weights, "modulus": int(cpr.find(r"149 delt med (\d+) giver")), "centuries": rows}
    return base(
        "dk-cpr-number",
        "Denmark CPR number (personnummer): birth date, century from serial, modulus 11 control",
        "DK",
        "almanac.rules.dk_cpr",
        parameters,
        [
            vector({"body": "070761428"}, "5", "source", "CPR-kontoret worked example: products sum to 149, remainder 6, 11 - 6 = 5"),
            vector({"modulus_check": "0707614285"}, True, "source", "control calculation: weighted sum 154 divides by 11"),
            vector("070761-4285", True, "source", "the example written with its hyphen"),
            vector({"birth_date_of": "0707614285"}, "1961-07-07", "derived", "serial 4xxx with year 61 falls in the 1937-1999 row"),
            vector({"sex_of": "0707614285"}, "male", "derived", "odd last digit"),
            vector({"modulus_check": "0707614286"}, False, "derived", "last digit altered"),
            vector({"birth_date_of": "0101205002"}, "2020-01-01", "derived", "serial 5xxx with year 20 falls in the 2000-2057 row"),
        ],
        [
            item(cpr, "CPR-kontoret (Danish Civil Registration System office)", "Personnummeret i CPR-systemet (PDF, 1 July 2008)", "page 10, Bilag: Beregning af kontrolciffer", "07 07 61-428 5", "149 delt med 11 giver 13 med en rest på 6"),
            item(cpr, "CPR-kontoret (Danish Civil Registration System office)", "Personnummeret i CPR-systemet (PDF, 1 July 2008)", "page 10, Kontrolberegning af et nummer med kontrolciffer", "154 delt med 11 giver 14 og ingen rest.", "Kontrolberegning af et nummer med kontrolciffer"),
            item(cpr, "CPR-kontoret (Danish Civil Registration System office)", "Personnummeret i CPR-systemet (PDF, 1 July 2008)", "pages 5 to 7, century table", "2000 - 2057", "Personnummerets opbygning"),
            item(cpr, "CPR-kontoret (Danish Civil Registration System office)", "Personnummeret i CPR-systemet (PDF, 1 July 2008)", "page 3, numbers without control digit", "Personnumre til kvinder uden kontrolciffer", "Hvis der fremkom-", role="supporting"),
        ],
        "The Danish personal identification number as the CPR office describes it: DDMMYY, then a four-digit serial whose "
        "last digit is even for women and odd for men; the serial's first digit together with the two-digit year fixes "
        "the century (the table rows are read from the PDF). Numbers were first assigned so that the ten digits weighted "
        "4 3 2 7 6 5 4 3 2 1 sum to a multiple of 11, and a remainder of 1 leaves no usable control digit. Once those "
        "ran out for a birth date, the office assigns numbers without the control digit, so the default evaluation "
        "checks only that the date and century resolve; the modulus check is exposed separately for generators that "
        "want the older construction. valid_from is the document date; the PDF states no licence, so the entry is "
        "held at license-review.",
        uses=PERSON_USES,
        valid_from="2008-07-01",
        extra_tags=["cpr", "personnummer"],
        assumed=[
            {"parameter": "centuries[].century", "value": "first year of the table's year range minus the two-digit year it starts from", "method": "derived", "rationale": "The table gives year ranges such as 1858 - 1899 for the two-digit years 58 - 99; the century offset is their difference."},
        ],
    )


def build_de_idnr(elster: Source, oecd: Source) -> dict:
    block = re.search(r"Tabelle 2-1(.*?)HINWEISE", elster.text, re.S)
    if block is None:
        raise ValueError("example table not found")
    examples = re.findall(r"(\d{11})", block.group(1))
    if len(examples) != 6:
        raise ValueError(f"expected six examples, got {examples}")
    test_id, real_ids = examples[0], examples[1:]
    parameters = {
        "check_digit": {"modulus": int(elster.find(r"const int n = (\d+);")), "radix": int(elster.find(r"const int m = (\d+);")), "body_length": 10},
        "repeat_counts": [2, 3],
        "allow_leading_zero": False,
    }
    vectors = [vector({"body": number[:10]}, number[10], "source", "Tabelle 2-1 example") for number in examples]
    vectors += [vector(number, True, "source") for number in real_ids]
    vectors += [
        vector(test_id, False, "derived", "test identification number: leading zero is reserved for test numbers"),
        vector("12345678903", False, "derived", "no repeated digit in the first ten"),
        vector("86095742718", False, "derived", "check digit altered"),
        vector("11123456780", False, "derived", "a digit repeated three times in consecutive positions"),
    ]
    return base(
        "de-steuer-id-check-digit",
        "Germany steuerliche Identifikationsnummer (IdNr): structure rules and ISO 7064 check digit",
        "DE",
        "almanac.rules.de_steuer_id",
        parameters,
        vectors,
        [
            item(elster, "ELSTER (Bayerisches Landesamt für Steuern)", "Prüfung der Steuer- und Steueridentifikationsnummer (PDF, Stand 2 September 2026)", "page 6, section 2.2 Aufbau der Steueridentifikationsnummer", "Prüfziffer", "In den ersten 10 Stellen der Identifikationsnummer muss genau eine Ziffer doppelt"),
            item(elster, "ELSTER (Bayerisches Landesamt für Steuern)", "Prüfung der Steuer- und Steueridentifikationsnummer (PDF, Stand 2 September 2026)", "page 7, Tabelle 2-1", "86095742719", "Beispiel für eine Steueridentifikationsnummer"),
            item(elster, "ELSTER (Bayerisches Landesamt für Steuern)", "Prüfung der Steuer- und Steueridentifikationsnummer (PDF, Stand 2 September 2026)", "page 8, Algorithmus zur Berechnung der Prüfziffer", "const int n = 11;", "Algorithmus zur Berechnung der Prüfziffer:"),
            oecd_item(oecd, "Germany", "Section II, TIN structure", "10 digits plus one check digit", "TINs are comprised of 11 digits: 10 digits plus one check digit.", role="supporting"),
        ],
        "The German tax identification number as the ELSTER interface documentation specifies it: eleven digits, no "
        "leading zero outside test numbers, exactly one digit in the first ten occurring twice or three times, and an "
        "eleventh check digit from the ISO 7064 MOD 11,10 fold printed in the document (moduli read from its code). "
        "All six examples of Tabelle 2-1 are vectors; the first is a test number with a leading zero. The document is "
        "dated 2 September 2026, which is valid_from, and states that all rights are reserved, so the entry is held at "
        "license-review; only facts and the publisher's examples are restated.",
        uses=PERSON_USES,
        valid_from="2026-09-02",
        extra_tags=["steuer-id", "idnr", "iso-7064"],
        assumed=[
            {"parameter": "repeat_rule", "value": "three equal digits may not stand in three consecutive positions", "method": "derived", "rationale": "The document says three equal digits may never stand in directly consecutive positions, yet its own example 65929970489 has two of its three 9s side by side; the rule is read as forbidding a run of three, which every published example satisfies."},
        ],
    )


def build_be_nn(ti000: Source, rn: Source) -> dict:
    modulus = int(ti000.find(r"numéro d'ordre par (\d+) ;"))
    prefix = rn.find(r"juxtaposition\s+du\s+chiffre\s+(\d)\s*,")
    parameters = {"modulus": modulus, "prefix_by_birth_period": {"1800-1999": "", "2000-": prefix}}
    return base(
        "be-national-register-number",
        "Belgium national register number: birth date, order number and modulus 97 control number",
        "BE",
        "almanac.rules.be_national_number",
        parameters,
        [
            vector({"body": "420122051", "period": "1800-1999"}, "81", "source", "TI000 example 42.01.22.051-81"),
            vector("42.01.22.051-81", True, "source"),
            vector("40 00 01 001-33", True, "source", "TI000 example for an incomplete birth date"),
            vector({"sex_of": "42.01.22.051-81"}, "male", "source", "TI000: homme, né le 22 janvier 1942"),
            vector({"body": "010203001", "period": "2000-"}, f"{97 - int('2010203001') % 97:02d}", "derived", "2 prefixed for a birth in 2001"),
            vector({"birth_period_of": f"010203001{97 - int('2010203001') % 97:02d}"}, "2000-", "derived"),
            vector("42.01.22.051-82", False, "derived", "control number altered"),
        ],
        [
            item(ti000, "Registre national (SPF Intérieur)", "TI000 Numéro d'identification (PDF, version 15.05.2016)", "page 1, composition of the number", "42.01.22.051-81", "on divise le nombre de neuf chiffres constitué par juxtaposition de la date de naissance et du"),
            item(ti000, "Registre national (SPF Intérieur)", "TI000 Numéro d'identification (PDF, version 15.05.2016)", "page 2, incomplete birth date", "40 00 01 001-33", "Date de naissance incomplète"),
            item(rn, "Registre national (SPF Intérieur)", "Le fichier RN (PDF)", "chapter IV, calcul du nombre de contrôle", "pour les personnes nées en 20xx", "Division par 97 du nombre de 10 chiffres constitué par la juxtaposition du chiffre 2"),
        ],
        "The Belgian national register number as the National Register describes it: YYMMDD, a three-digit order number "
        "(odd for men, even for women) and a control number equal to 97 minus the remainder of the nine digits divided "
        "by 97; for people born from 2000 the digit 2 is put in front before dividing. Because the control number "
        "depends on the birth period, the rule reports which period reproduces it. TI000 also prints the example "
        "40 00 00 955-81, which the stated arithmetic does not reproduce, so it is not used as a vector. valid_from "
        "is the TI000 version date; neither PDF states a licence, so the entry is held at license-review.",
        uses=PERSON_USES,
        valid_from="2016-05-15",
        extra_tags=["rijksregisternummer", "national-number"],
    )


def build_nl_bsn(oecd: Source, rvig_test: Source, rvig_uc27: Source) -> dict:
    formula = oecd.find(r"(\(\(N1\*9\).*?modulo 11)")
    weights = [int(w) for w in re.findall(r"N\d\*(\d)", formula)]
    parameters = {"weights": weights, "modulus": int(oecd.find(r"modulo (\d+)")), "check": "remainder", "remainder_map": {"10": None}}
    test_bsns = sorted(set(re.findall(r"BSN\s+(9999\d{5})", rvig_test.text)))
    vectors = [
        vector("123456789", False, "source", "RvIG test A.1: Nummer is geen BSN"),
        vector("999990068", True, "source", "RvIG test A.2: Nummer is een BSN"),
    ]
    vectors += [vector(bsn, True, "source", "BSN of an RvIG test person") for bsn in test_bsns if bsn != "999990068"]
    vectors += [
        vector({"body": "99999006"}, "8", "derived"),
        vector("999990069", False, "derived", "check digit altered"),
        vector({"body": "60000000"}, None, "derived", "weighted sum 54 leaves remainder 10, so no BSN exists"),
    ]
    return base(
        "nl-bsn-elfproef",
        "Netherlands citizen service number (BSN) eleven test (elfproef)",
        "NL",
        "almanac.rules.weighted_modulus",
        parameters,
        vectors,
        [
            oecd_item(oecd, "Netherlands", "Section II, validation rule and check digit", "If remainder = 10, the TIN is not valid.", "Check digit (N9) = remainder from above algorithm"),
            item(rvig_test, "Rijksdienst voor Identiteitsgegevens (RvIG)", "Aansluiting testen en toetsen BSN (PDF, version 1.5, 13-12-2019)", "page 12, Bijlage A, tests A.1 and A.2", "999990068", "Nummer is geen BSN"),
            item(rvig_uc27, "Rijksdienst voor Identiteitsgegevens (RvIG)", "Beheervoorziening BSN, Use Case Specificatie 27: Genereren nummers (PDF)", "section 1.2.3 Genereer nieuw nummer", "elfproef", "In 1 op 11 gevallen is dit niet", role="supporting"),
        ],
        "The nine-digit Dutch BSN: the first eight digits weighted 9 down to 2 and summed, the remainder modulo 11 is "
        "the ninth digit, and a remainder of 10 means no BSN can be formed (the Dutch OECD sheet). RvIG, which issues "
        "the numbers, generates eight random digits and appends the ninth so that the eleven test holds, retrying "
        "in the 1 in 11 cases where that is impossible. The source vectors are RvIG's connection-test cases and the "
        "BSNs of its test persons. valid_from is the test document's date; no source states a licence, so the entry "
        "is held at license-review.",
        uses=PERSON_USES,
        valid_from="2019-12-13",
        extra_tags=["bsn", "elfproef"],
    )


def build_no_orgnr(brreg: Source, oecd: Source) -> dict:
    weights = [int(w) for w in re.findall(r"\d", brreg.find(r"Etter dette blir vektene ([\d, og]+) regnet fra første siffer"))]
    own = brreg.find(r"Organisasjonsnummer:.*?(\d{3} \d{3} \d{3})", re.S)
    parameters = {"weights": weights, "modulus": int(brreg.find(r"kontrollsiffer beregnet med egne vekter, modulus (\d+)")), "check": "complement", "remainder_map": {"0": 0, "1": None}}
    return base(
        "no-organisasjonsnummer-check-digit",
        "Norway organisation number (organisasjonsnummer) modulus 11 check digit",
        "NO",
        "almanac.rules.weighted_modulus",
        parameters,
        [
            vector(own.replace(" ", ""), True, "source", "the Brønnøysund Register Centre's own organisation number as printed on the page"),
            vector({"body": own.replace(" ", "")[:8]}, own[-1], "derived"),
            vector({"body": "10000004"}, "0", "derived", "weighted sum 11 divides evenly, so the check digit is 0"),
            vector({"body": "10000013"}, None, "derived", "remainder 1 would need check digit 10, so the number is invalid"),
            vector(own.replace(" ", "")[:8] + "4", False, "derived", "check digit altered"),
        ],
        [
            item(brreg, "Brønnøysundregistrene", "Om organisasjonsnummeret", "section Teknisk oppbygging av organisasjonsnummeret", "974 760 673", "Etter dette blir vektene 3, 2, 7, 6, 5, 4, 3 og 2 regnet fra første siffer."),
            item(brreg, "Brønnøysundregistrene", "Om organisasjonsnummeret", "section Modulus 11", "Hvis kontrollsifferet blir 10 (rest = 1) er organisasjonsnummeret ugyldig.", "Hvis divisjonen går opp (rest = 0) blir kontrollsifferet 0."),
            oecd_item(oecd, "Norway", "Section II, legal entities", "modulus 11 check digit", "The organisation number (TIN) is a nine digit number.", role="supporting"),
        ],
        "The nine-digit Norwegian organisation number as the Brønnøysund Register Centre describes it: eight digits "
        "weighted 3 2 7 6 5 4 3 2 from the first digit, the sum divided by 11 and the remainder subtracted from 11; a "
        "remainder of 0 gives check digit 0 and a remainder of 1 means the number is invalid. The page's worked "
        "example shows only its totals and also says the weights run from right to left, which contradicts the "
        "preceding sentence; reading them from the first digit reproduces the register's own number printed on the "
        "page, which is the source vector, and matches Norway's OECD sheet. valid_from is the page's last-updated date; "
        "no licence is stated, so the entry is held at license-review.",
        uses=BUSINESS_USES,
        valid_from="2023-12-13",
        extra_tags=["organisasjonsnummer", "brreg"],
    )


def _lt_weights(block: str) -> list[int]:
    """Weights of a Lithuanian weight table, printed as five positions, five weights, five positions, five weights."""
    numbers = re.findall(r"^(\d)\s*$", block, re.M)
    if len(numbers) != 10:
        raise ValueError(f"expected ten weights, got {numbers}")
    return [int(n) for n in numbers]


def build_lt_personal_code(oecd: Source) -> dict:
    first = re.search(r"1\. Multiply the values of each position by the\s+corresponding weight:(.*?)2\. Add up", oecd.text, re.S)
    second = re.search(r"5\. If remainder is 10, calculate a new check digit\s+with over corresponding weight:(.*?)6\. Add up", oecd.text, re.S)
    if first is None or second is None:
        raise ValueError("Lithuanian weight tables not found")
    parameters = {
        "weights": _lt_weights(first.group(1)),
        "fallback_weights": _lt_weights(second.group(1)),
        "retry_remainder": 10,
        "modulus": int(oecd.find(r"Get modulo (\d+) of the result")),
        "check": "remainder",
        "remainder_map": {"10": 0},
    }
    return base(
        "lt-personal-code-check-digit",
        "Lithuania personal code (asmens kodas) two-pass modulus 11 check digit",
        "LT",
        "almanac.rules.weighted_modulus",
        parameters,
        [
            vector({"body": "3330924006"}, "4", "source", "OECD sheet sample: first pass 109 mod 11 = 10, second pass 169 mod 11 = 4"),
            vector("33309240064", True, "source"),
            vector("10101010005", True, "source", "structure sample in the OECD sheet"),
            vector("33309240065", False, "derived", "check digit altered"),
        ],
        [
            oecd_item(oecd, "Lithuania", "Section II, natural persons, check digit rule", "if remainder is 10, control number C11 = 0.", "5. If remainder is 10, calculate a new check digit"),
            oecd_item(oecd, "Lithuania", "Section II, natural persons, sample calculation", "33309240064", "169 MOD 11 = 4 (i.e. C11)"),
            oecd_item(oecd, "Lithuania", "Section II, natural persons, structure sample", "10101010005", "C1 Can only take the value 1 to 6."),
        ],
        "The eleven-digit Lithuanian personal code, which Lithuania uses as its tax identification number: ten digits "
        "weighted 1 to 9 then 1 and reduced modulo 11; if the remainder is 10 the digits are reweighted 3 to 9 then 1 "
        "to 3, and a second remainder of 10 gives check digit 0. The weight tables and the worked sample come from "
        "Lithuania's OECD tax identification number sheet. It carries no date or licence statement, so valid_from is "
        "the access date and the entry is held at license-review.",
        uses=PERSON_USES,
        valid_from=ACCESSED.isoformat(),
        extra_tags=["asmens-kodas"],
    )


def build_se_personnummer(scb: Source, oecd: Source) -> dict:
    return base(
        "se-personnummer-check-digit",
        "Sweden personnummer: birth date, birth number and modulus 10 check digit",
        "SE",
        "almanac.rules.se_personnummer",
        {"luhn": {}},
        [
            vector({"body": "640823323"}, "4", "source", "SCB worked example: digit sum 36, 10 - 6 = 4"),
            vector("640823-3234", True, "source"),
            vector("196408233234", True, "source", "the twelve-digit register form of the same example"),
            vector("640823-3235", False, "derived", "check digit altered"),
            vector("640823+3234", True, "derived", "the plus separator the OECD sheet lists"),
            vector("6408233234", True, "derived", "ten digits without separator"),
        ],
        [
            item(scb, "Statistiska centralbyrån (Statistics Sweden)", "Personnummer, Bakgrundsfakta 2016:1 (PDF)", "section 1.4.3 Kontrollsiffra", "640823-3234", "Kontrollsiffran bestäms enligt den s.k. modulus-10-metoden med vikterna 1 och 2."),
            item(scb, "Statistiska centralbyrån (Statistics Sweden)", "Personnummer, Bakgrundsfakta 2016:1 (PDF)", "section 1.4.2, register storage", "196408233234", "lagras på följande sätt:"),
            oecd_item(oecd, "Sweden", "Section II, TIN structure", "999999+9999", "natural person who is or has been resident in Sweden", role="supporting"),
        ],
        "The Swedish personal identity number as Statistics Sweden documents it: YYMMDD, a three-digit birth number and "
        "a check digit introduced in 1967. The nine digits are multiplied alternately by 2 and 1, the digits of the "
        "products are added, and the check digit is 10 minus the last digit of that sum (0 when the result is 10), "
        "which is the Luhn formula. Registers store the twelve-digit form with the century. SCB notes that its example "
        "is fictitious. valid_from is the start of the year the check digit was introduced; the PDF states no licence, "
        "so the entry is held at license-review.",
        uses=PERSON_USES,
        valid_from="1967-01-01",
        extra_tags=["personnummer", "luhn"],
        assumed=[
            {"parameter": "valid_from", "value": "1967-01-01", "method": "derived", "rationale": "SCB gives only the year 1967 for the introduction of the check digit; the first day of that year is used."},
            {"parameter": "luhn", "value": "standard Luhn over the nine digits", "method": "derived", "rationale": "Alternate weights 2 and 1 starting from the first of nine digits, with product digits summed and the result subtracted from 10, is exactly the Luhn computation the shared luhn rule implements."},
        ],
    )


def build_za_id(oecd: Source) -> dict:
    female = re.search(r"Females are assigned numbers in the range\s+(\d{4})-(\d{4})", oecd.text)
    male = re.search(r"males from (\d{4})-(\d{4})", oecd.text)
    codes = re.findall(r"(\d) (?:\n)?denoting (South African citizen|permanent resident|refugee)", oecd.text, re.I)
    if female is None or male is None or len(codes) != 3:
        raise ValueError("South African structure not found")
    parameters = {
        "sex_ranges": {"female": [int(female.group(1)), int(female.group(2))], "male": [int(male.group(1)), int(male.group(2))]},
        "citizenship_codes": dict(codes),
        "luhn": {},
    }
    body = "940510500108"
    check = luhn.check_digit(body, {})
    return base(
        "za-identity-number",
        "South Africa identity number: birth date, sex range, citizenship digit and Luhn check digit",
        "ZA",
        "almanac.rules.za_id",
        parameters,
        [
            vector({"encode_birth_date": "1994-05-10"}, "940510", "source", "OECD sheet: 10 May 1994 is displayed as 940510"),
            vector({"sex_of": body + check}, "male", "derived", "sequence 5001 is in the male range"),
            vector({"sex_of": "9405104999083"}, "female", "derived", "sequence 4999 is in the female range"),
            vector({"citizenship_of": body + check}, "South African Citizen", "derived"),
            vector({"body": body}, check, "derived", "Luhn over the first twelve digits"),
            vector(body + check, True, "derived"),
            vector(body + str((int(check) + 1) % 10), False, "derived", "check digit altered"),
            vector("9405105001381", False, "derived", "citizenship digit 3 is not defined"),
        ],
        [
            oecd_item(oecd, "South Africa", "Section II, 1. The South African Identity Number", "YYMMDDSSSSCAZ:", "The first 6 digits (YYMMDD) are the date of birth. 10 May 1994 is displayed as 940510."),
            oecd_item(oecd, "South Africa", "Section II, sequence digits", "0000-4999", "Females are assigned numbers in the range"),
            oecd_item(oecd, "South Africa", "Section II, citizenship digit", "2 denoting refugee", "The next digit (C) indicates the South African citizen status with 0 denoting South African Citizen."),
            oecd_item(oecd, "South Africa", "Section II, check digit", "Luhn algorithm", "The last digit (Z) is a checksum digit"),
        ],
        "The thirteen-digit South African identity number as South Africa describes it in its OECD tax identification "
        "number sheet: YYMMDD, four sequence digits whose range encodes sex, a citizenship digit, one further digit "
        "the sheet labels A without explaining, and a Luhn check digit. The sheet prints no complete number, so beyond "
        "the date-encoding example every vector is derived by applying the stated rules to a constructed number. It "
        "carries no date or licence statement, so valid_from is the access date and the entry is held at "
        "license-review.",
        uses=PERSON_USES,
        valid_from=ACCESSED.isoformat(),
        extra_tags=["luhn", "national-id"],
    )


def build_us_ssn(poms: Source, cfr: Source) -> dict:
    markup = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", poms.raw.decode("utf-8"))).split())
    areas = re.search(r"former area number\) as (.*?) series", markup)
    group = re.search(r"former group number\) as \W(\d+)", markup)
    serial = re.search(r"former serial number\) as \W(\d+)", markup)
    if areas is None or group is None or serial is None:
        raise ValueError("never-assigned values not found in POMS")
    exact = re.findall(r"(\d{3})\W", areas.group(1).split(" or ")[0])
    series = re.search(r"in the (\d)00$", areas.group(1))
    if len(exact) != 2 or series is None:
        raise ValueError(f"unexpected area wording: {areas.group(1)!r}")
    digit = series.group(1)
    parameters = {
        "area_forbidden": exact,
        "area_forbidden_ranges": [[f"{digit}00", f"{digit}99"]],
        "group_forbidden": [group.group(1)],
        "serial_forbidden": [serial.group(1)],
    }
    cfr_title = f"26 CFR 301.6109-1, Identifying numbers, as of {CFR_DATE} (XML)"
    return base(
        "us-ssn-format",
        "United States Social Security number: 000-00-0000 form and never-assigned values",
        "US",
        "almanac.rules.us_tin_format",
        parameters,
        [
            vector({"area": "000"}, False, "source", "POMS RM 10201.035: area 000"),
            vector({"area": "666"}, False, "source", "POMS RM 10201.035: area 666"),
            vector({"area": "900"}, False, "source", "POMS RM 10201.035: the 900 series"),
            vector("234-00-5678", False, "source", "group 00 is never assigned"),
            vector("234-56-0000", False, "source", "serial 0000 is never assigned"),
            vector({"area": "987"}, False, "derived", "inside the 900 series"),
            vector("234-56-7890", True, "derived", "no never-assigned group"),
            vector("234567890", True, "derived", "the same number without hyphens"),
            vector("234-56-789", False, "derived", "eight digits"),
        ],
        [
            item(poms, "Social Security Administration", "POMS RM 10201.035 Invalid Social Security Numbers (SSNs)", "section B, procedure for identifying invalid SSNs", "former area number", "The first three digits (former area number) as"),
            item(poms, "Social Security Administration", "POMS RM 10201.035 Invalid Social Security Numbers (SSNs)", "section B, group and serial", "former serial number", "The second group of two digits (former group number) as"),
            item(cfr, "Internal Revenue Service via the eCFR API", cfr_title, "section 301.6109-1(a)(1)(i)", "000-00-0000", "Social security numbers take the form 000-00-0000."),
        ],
        "The nine-digit Social Security number in the form the Treasury regulation gives (000-00-0000) with the values "
        "the Social Security Administration's operations manual names as never assigned: area 000, 666 or anything in "
        "the 900 series, group 00 and serial 0000. A number that passes may still never have been issued; only a "
        "Numident query confirms assignment. Since randomisation the area and group carry no geographic or "
        "sequential meaning, so generators should draw them uniformly from the permitted values. valid_from is the "
        "manual section's effective date; US government works carry no copyright, but neither source states terms, so "
        "the entry is held at license-review.",
        uses=PERSON_USES,
        valid_from="2011-06-23",
        extra_tags=["ssn", "ssa"],
        assumed=[
            {"parameter": "area_forbidden_ranges", "value": [[f"{digit}00", f"{digit}99"]], "method": "derived", "rationale": "The manual names the 900 series; it is stored as the inclusive range of three-digit areas beginning with 9."},
        ],
    )


def build_us_itin(cfr: Source, oecd: Source) -> dict:
    return base(
        "us-itin-format",
        "United States individual taxpayer identification number (ITIN): nine digits beginning with 9",
        "US",
        "almanac.rules.us_tin_format",
        {"area_required_prefix": oecd.find(r"format:\s*(\d)xx-xx-xxxx")},
        [
            vector({"mask": "9xx-xx-xxxx"}, True, "source", "the format the OECD sheet prints"),
            vector({"mask": "000-00-0000"}, False, "derived", "the general taxpayer number form without the leading 9"),
            vector("912-70-1234", True, "derived"),
            vector("812-70-1234", False, "derived", "does not begin with 9"),
            vector("912-70-123", False, "derived", "eight digits"),
        ],
        [
            item(cfr, "Internal Revenue Service via the eCFR API", f"26 CFR 301.6109-1, Identifying numbers, as of {CFR_DATE} (XML)", "section 301.6109-1(a)(1)(i)", "000-00-0000", "also take the form 000-00-0000 but include a specific number or numbers designated by the IRS."),
            oecd_item(oecd, "United States", "Section II, TIN structure", "9xx-xx-xxxx.", "begins with the number 9 and is in the following format:"),
        ],
        "The ITIN takes the Social Security number form 000-00-0000 with digits the IRS designates (26 CFR "
        "301.6109-1); the United States' OECD tax identification number sheet states that it always begins with 9 "
        "and prints the mask 9xx-xx-xxxx. Further restrictions on the middle digits are not stated in these sources "
        "and are not enforced. valid_from is the date of the regulation version cited; neither source states terms, "
        "so the entry is held at license-review.",
        uses=PERSON_USES,
        valid_from=CFR_DATE,
        extra_tags=["itin", "irs"],
    )


def build_fr_siren_siret(siren: Source, siret: Source, oecd: Source) -> dict:
    siren_length = int(oecd.find(r"The numéro SIREN consists in (\d+) numerals"))
    siret_length = int(oecd.find(r"The numéro SIRET consists in (\d+) numerals"))
    return base(
        "fr-siren-siret-format",
        "France SIREN and SIRET identifiers: nine-digit legal unit and fourteen-digit establishment numbers",
        "FR",
        "almanac.rules.fr_siret",
        {"siren_length": siren_length, "nic_length": siret_length - siren_length},
        [
            vector({"kind": "siren", "value": "999 999 999"}, True, "source", "format printed in the OECD sheet"),
            vector({"kind": "siret", "value": "999 999 999 99999"}, True, "source", "format printed in the OECD sheet"),
            vector({"siren_of": "999 999 999 99999"}, "999999999", "derived", "the SIRET begins with the SIREN"),
            vector({"kind": "siren", "value": "12345678"}, False, "derived", "eight digits"),
            vector({"kind": "siret", "value": "123456789"}, False, "derived", "a SIREN is not a SIRET"),
        ],
        [
            item(siren, "Institut national de la statistique et des études économiques (INSEE)", "Définition: Numéro Siren", "définition", "neuf chiffres", "Le numéro SIREN est un identifiant de neuf chiffres attribué à chaque unité légale."),
            item(siret, "Institut national de la statistique et des études économiques (INSEE)", "Définition: Numéro Siret", "définition", "14 chiffres", "Cet identifiant numérique de 14 chiffres est articulé en deux parties"),
            oecd_item(oecd, "France", "Section II, TIN structure for entities", "(format 999 999 999 99999).", "The numéro SIRET consists in 14 numerals"),
        ],
        "INSEE's definitions: the SIREN is nine digits identifying a legal unit, the first eight without meaning and "
        "the ninth a check digit; the SIRET is fourteen digits, the SIREN followed by the NIC, a four-digit order "
        "number and a check digit over the whole SIRET. INSEE's definition pages do not state the check-digit "
        "arithmetic, so the rule checks lengths and composition only. valid_from is the later of the two pages' "
        "update dates; neither states a licence, so the entry is held at license-review.",
        uses=BUSINESS_USES,
        valid_from="2025-10-21",
        extra_tags=["siren", "siret", "insee"],
    )


def build_ch_ahv(fedlex: Source, oecd: Source) -> dict:
    code = fedlex.find(r"dreistelligen Ländercode für die Schweiz \((\d{3})\)")
    return base(
        "ch-ahv-number-format",
        "Switzerland AHV number (Versichertennummer): 13 digits with country code 756 and control digit",
        "CH",
        "almanac.rules.ch_ahv_number",
        {"country_code": code},
        [
            vector("756.1234.5678.97", True, "source", "the model number in the OECD sheet"),
            vector({"parts_of": "756.1234.5678.97"}, {"country_code": "756", "number": "123456789", "control_digit": "7"}, "derived"),
            vector("7561234567897", True, "derived", "without dots"),
            vector("757.1234.5678.97", False, "derived", "another country code"),
            vector("756.1234.5678.9", False, "derived", "twelve digits"),
        ],
        [
            item(fedlex, "Swiss Federal Chancellery (Fedlex)", "Verordnung über die Alters- und Hinterlassenenversicherung (AHVV), SR 831.101, version of 1 January 2025 (XML)", "Art. 133 AHV-Nummer", code, "Die AHV-Nummer ist 13-stellig. Sie setzt sich zusammen aus:"),
            item(fedlex, "Swiss Federal Chancellery (Fedlex)", "Verordnung über die Alters- und Hinterlassenenversicherung (AHVV), SR 831.101, version of 1 January 2025 (XML)", "Art. 133, footnote on the version in force", "in Kraft seit 1. Dez. 2007", "einer Kontrollziffer.", role="supporting"),
            oecd_item(oecd, "Switzerland", "Section II, individuals", "756.1234.5678.97", "The current OASI Number was introduced in 2008.", role="supporting"),
        ],
        "The Swiss social security number as Art. 133 AHVV defines it: thirteen digits made of the country code 756, "
        "a nine-digit number that reveals nothing about the person, and a control digit; the dotted grouping is the "
        "one Switzerland's OECD sheet shows. The ordinance does not state the control digit's arithmetic, so the rule "
        "checks composition only. valid_from is the date the article's current wording entered into force; the law "
        "publisher states no licence for the XML, so the entry is held at license-review.",
        uses=PERSON_USES,
        tier="A",
        valid_from="2007-12-01",
        extra_tags=["ahv", "avs", "social-security-number"],
    )


def build_in_pan(oecd: Source) -> dict:
    holder_types = dict(re.findall(r"[\"“]([A-Z])[\"”] stands for ([A-Za-z ]+?),?\s*$", oecd.text, re.M))
    low, high = oecd.find(r"sequential number running from (\d{4}) to \d{4}"), oecd.find(r"sequential number running from \d{4} to (\d{4})")
    return base(
        "in-pan-format",
        "India Permanent Account Number (PAN) format and holder-type codes",
        "IN",
        "almanac.rules.in_pan",
        {"holder_types": holder_types, "sequence_range": [int(low), int(high)]},
        [
            vector("AFZPK7190K", True, "source", "the typical PAN in the OECD sheet"),
            vector({"holder_type_of": "AFZPK7190K"}, "Individual", "source", "P stands for Individual"),
            vector({"holder_type_of": "AFZCK7190K"}, "Company", "derived"),
            vector("AFZXK7190K", False, "derived", "X is not a holder-type code"),
            vector("AFZPK0000K", False, "derived", "sequence runs from 0001"),
            vector("AFZPK7190", False, "derived", "nine characters"),
        ],
        [
            oecd_item(oecd, "India", "Section II, TIN structure", "AFZPK7190K.", "A typical PAN is AFZPK7190K."),
            oecd_item(oecd, "India", "Section II, fourth character", "stands for Individual,", "Fourth character of PAN represents the status of PAN holder"),
            oecd_item(oecd, "India", "Section II, last character", "alphabetic check digit.", "Next four characters i.e. \"7190\" in the above PAN are sequential number running from 0001 to 9999."),
        ],
        "The ten-character PAN as India describes it in its OECD tax identification number sheet: a three-letter "
        "series, a holder-type letter (codes read from the sheet), the first letter of the holder's surname or name, "
        "a sequence from 0001 to 9999 and an alphabetic check character whose arithmetic the sheet does not give. "
        "The rule checks shape and holder type only. The sheet carries no date or licence statement, so valid_from is "
        "the access date and the entry is held at license-review.",
        uses=PERSON_USES + ["kyb-onboarding"],
        valid_from=ACCESSED.isoformat(),
        extra_tags=["pan", "tax-identifier"],
    )


def build_ie_trn(oecd: Source) -> dict:
    parameters = {"patterns": {"trn": r"[0-9]{7}[A-Z]{1,2}", "chy": r"CHY ?[0-9]{1,5}"}}
    return base(
        "ie-tax-reference-number-format",
        "Ireland tax reference number (PPS-based TRN) and charity CHY number formats",
        "IE",
        "almanac.rules.ie_pps",
        parameters,
        [
            vector({"kind": "trn", "value": "1234567T"}, True, "source"),
            vector({"kind": "trn", "value": "1497955KA"}, True, "source"),
            vector({"kind": "chy", "value": "CHY 1234"}, True, "source"),
            vector({"kind": "trn", "value": "123456T"}, False, "derived", "six digits"),
            vector({"kind": "trn", "value": "1234567TAB"}, False, "derived", "three letters"),
            vector({"kind": "chy", "value": "CHY 123456"}, False, "derived", "six digits"),
        ],
        [
            oecd_item(oecd, "Ireland", "Section II, TIN structure, TRN", "1497955KA", "Explanation: 7 digits + either 1 or 2 letters."),
            oecd_item(oecd, "Ireland", "Section II, TIN structure, CHY number", "CHY 1234", "The letters CHY followed by between 1 and 5 digits."),
        ],
        "Ireland's tax reference number for individuals and entities (the PPS number for individuals) as Ireland "
        "describes it in its OECD tax identification number sheet: seven digits followed by one or two letters, with "
        "no restriction stated on the letters; charities carry CHY followed by one to five digits. The check-letter "
        "arithmetic is not in the sheet, so the rule checks shape only. The sheet carries no date or licence "
        "statement, so valid_from is the access date and the entry is held at license-review.",
        uses=PERSON_USES + ["kyb-onboarding"],
        valid_from=ACCESSED.isoformat(),
        extra_tags=["pps", "trn"],
        assumed=[
            {"parameter": "patterns", "value": parameters["patterns"], "method": "derived", "rationale": "Regular expressions restating the sheet's descriptions: 7 digits plus one or two letters, and CHY followed by 1 to 5 digits (with the optional space its example shows)."},
        ],
    )


def build_fi_hetu(oecd: Source) -> dict:
    sentence = " ".join(oecd.find(r"(Character \+ means.*?or after that\.)", re.S).split())
    clauses = re.findall(r"(character [^m]+|letter [^m]+)means born (?:in )?(\d{4})", sentence.replace("Character", "character"))
    signs: dict[str, list[str]] = {}
    for clause, start in clauses:
        signs.setdefault(start, []).extend(re.findall(r"(?<![A-Za-z])([A-Z+\-])(?![A-Za-z])", clause))
    if sorted(signs) != ["1800", "1900", "2000"]:
        raise ValueError(f"century signs not parsed: {signs}")
    return base(
        "fi-personal-identity-code-format",
        "Finland personal identity code (henkilötunnus) century signs and business ID format",
        "FI",
        "almanac.rules.fi_hetu",
        {"century_signs": signs, "business_id_pattern": r"[0-9]{7}-[0-9]"},
        [
            vector({"century_of": "+"}, 1800, "source"),
            vector({"century_of": "Y"}, 1900, "source"),
            vector({"century_of": "A"}, 2000, "source"),
            vector({"business_id": "1234567-8"}, True, "source", "the form the OECD sheet prints"),
            vector("010190-123K", True, "derived"),
            vector("010105A1234", True, "derived"),
            vector("010190Z123K", False, "derived", "Z is not a century sign"),
            vector({"business_id": "12345678"}, False, "derived", "no hyphen"),
        ],
        [
            oecd_item(oecd, "Finland", "Section II, individuals", "letter A, B, C, D, E, F means born in 2000 or after that.", "The 7th character (+, - or a letter) represents the century of birth"),
            oecd_item(oecd, "Finland", "Section II, legal persons", "1234567-8.", "For legal persons, it consists of seven digits, a dash and a control mark"),
        ],
        "Finland's personal identity code as Finland describes it in its OECD tax identification number sheet: six "
        "digits of birth date, a century sign (+ for the 1800s; a hyphen or Y, X, W, V, U for the 1900s; A to F from "
        "2000), three digits and one alphanumeric control character. Business IDs are seven digits, a hyphen and a "
        "control digit. The control arithmetic is not in the sheet, so the rule checks shape and decodes the century. "
        "The sheet carries no date or licence statement, so valid_from is the access date and the entry is held at "
        "license-review.",
        uses=PERSON_USES + ["kyb-onboarding"],
        valid_from=ACCESSED.isoformat(),
        extra_tags=["henkilotunnus", "y-tunnus"],
        assumed=[
            {"parameter": "business_id_pattern", "value": "[0-9]{7}-[0-9]", "method": "derived", "rationale": "Restates the sheet's description of seven digits, a dash and a control mark, shown as 1234567-8."},
            {"parameter": "personal code shape", "value": "6 digits, century sign, 3 digits, one character from 0-9 or A-Z", "method": "derived", "rationale": "The sheet calls the last character alphanumeric; upper-case letters and digits are accepted."},
        ],
    )


def main() -> int:
    src = {key: Source(url, fetch(url)) for key, url in URLS.items()}
    entries = [
        build_au_abn(src["abr"], src["oecd_australia"]),
        build_pl_pesel(src["pesel"], src["oecd_poland"]),
        build_pl_nip(src["oecd_poland"]),
        build_dk_cpr(src["cpr"]),
        build_de_idnr(src["elster"], src["oecd_germany"]),
        build_be_nn(src["be_ti000"], src["be_rn"]),
        build_nl_bsn(src["oecd_netherlands"], src["rvig_test"], src["rvig_uc27"]),
        build_no_orgnr(src["brreg"], src["oecd_norway"]),
        build_lt_personal_code(src["oecd_lithuania"]),
        build_se_personnummer(src["scb"], src["oecd_sweden"]),
        build_za_id(src["oecd_south-africa"]),
        build_us_ssn(src["poms"], src["cfr"]),
        build_us_itin(src["cfr"], src["oecd_united-states"]),
        build_fr_siren_siret(src["insee_siren"], src["insee_siret"], src["oecd_france"]),
        build_ch_ahv(src["fedlex"], src["oecd_switzerland"]),
        build_in_pan(src["oecd_india"]),
        build_ie_trn(src["oecd_ireland"]),
        build_fi_hetu(src["oecd_finland"]),
    ]
    for entry in entries:
        write(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())

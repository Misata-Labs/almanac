"""Regenerate the bank code, account check-digit and payment-term entries.

Sources are the operators and publishers of each rule: the Deutsche
Bundesbank (bank sort code file, check-digit methods, base rate series), the
German federal law publisher (BGB and EGBGB XML), Vocalink for the UK
modulus checking specification it maintains for Pay.UK, the Central Bank of
the Republic of Azerbaijan for the IBAN check-digit procedure, and the eCFR
for the routing number structure in Regulation CC. Run from the repository
root:

    uv run python tools/build_bankcodes.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import REPO_ROOT, evidence, fetch, with_taxonomy

from almanac.fetch import Resource
from almanac.rules import (
    de_bank_account_check,
    de_default_interest,
    gb_account_standardisation,
    gb_sort_code_modulus,
    iban,
)

ACCESSED = date(2026, 11, 3)
BUNDESBANK = "Deutsche Bundesbank"
GII = "Bundesministerium der Justiz / Bundesamt für Justiz (gesetze-im-internet.de)"
VOCALINK = "Vocalink Limited (modulus checking specification for Pay.UK schemes)"
CBAR = "Central Bank of the Republic of Azerbaijan"
ECFR = "Office of the Federal Register (eCFR)"

URLS = {
    "blz": "https://www.bundesbank.de/resource/blob/926192/2feadedd079726ffbe1eedaf6c74ff76/mL/blz-aktuell-csv-data.csv",
    "pz": "https://www.bundesbank.de/resource/blob/603320/16a80c739bbbae592ca575905975c2d0/mL/pruefzifferberechnungsmethoden-data.pdf",
    "base": "https://api.statistiken.bundesbank.de/rest/data/BBIN1/M.DE.BBK.BBKBAS2.EUR.ME?format=sdmx_csv&detail=dataonly&startPeriod=2002-01&endPeriod=2026-10",
    "bgb": "https://www.gesetze-im-internet.de/bgb/xml.zip",
    "egbgb": "https://www.gesetze-im-internet.de/bgbeg/xml.zip",
    "vocalink_pdf": "https://www.vocalink.com/media/e0mo2xxa/validating-account-numbers-uk-modulus-checking-v910.pdf",
    "valacdos": "https://www.vocalink.com/media/zttpmnlp/valacdos.txt",
    "scsubtab": "https://www.vocalink.com/media/tedlwtxz/scsubtab.txt",
    "cbar": "https://uploads.cbar.az/assets/Methodological%20Guidelines%20on%20the%20international%20bank%20account%20number%20(IBAN).pdf",
    "ecfr229": "https://www.ecfr.gov/api/versioner/v1/full/2026-10-29/title-12.xml?part=229",
}

TAGS = ["banking", "payments", "bank-codes"]
USES = ["banking-demo", "payments-demo", "kyc-onboarding", "data-quality-validation", "treasury-demo"]
TESTS = [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}]


class Source:
    """One fetched resource with the whitespace-collapsed text the verifier searches."""

    def __init__(self, key: str) -> None:
        self.url = URLS[key]
        self.raw = fetch(self.url)
        self.text = Resource(self.url, self.raw, "").text
        self.collapsed = " ".join(self.text.split())

    def contains(self, needle: Any) -> bool:
        return " ".join(str(needle).split()) in self.collapsed

    def require(self, *needles: Any) -> None:
        missing = [n for n in needles if not self.contains(n)]
        if missing:
            raise ValueError(f"not found in {self.url}: {missing}")


def item(source: Source, publisher: str, title: str, locator: str, value: Any, snippet: str, unit: str = "text", role: str = "primary") -> dict:
    """An evidence item whose snippet and value are confirmed present in the fetched text."""
    shown = str(value).lower() if isinstance(value, bool) else value
    source.require(snippet, shown)
    result = evidence(publisher, title, source.url, locator, value, unit, snippet, "unstated", source.raw, role=role)
    result["accessed_at"] = ACCESSED.isoformat()
    return result


def vector(value: Any, expected: Any, origin: str, note: str | None = None) -> dict:
    result = {"input": value, "expected": expected, "origin": origin}
    if note:
        result["note"] = note
    return result


def rule(entry_id: str, title: str, domain: str, region: str, implementation: str, parameters: dict, vectors: list[dict], items: list[dict], notes: str, *, tier: str, valid_from: str, valid_to: str | None = None, assumed: list[dict] | None = None, tags: list[str] | None = None, tests: list[dict] | None = None) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": "license-review",
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": TAGS + (tags or []),
        "use_cases": USES,
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": items,
        "assumed": assumed or [],
        "tests": TESTS + [{"statistic": "vector_count", "expected": len(vectors), "tolerance": 0}] + (tests or []),
        "notes": notes,
    }


class FlowRow(dict):
    """A table row written on one line, which keeps tables of thousands of rows compact."""


class FlowList(list):
    """A short list of numbers written on one line."""


class EntryDumper(yaml.SafeDumper):
    pass


EntryDumper.add_representer(FlowRow, lambda dumper, data: dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True))
EntryDumper.add_representer(FlowList, lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True))


def write(entry: dict) -> Path:
    entry = with_taxonomy(entry)
    path = REPO_ROOT / "entries" / entry["domain"] / entry["region"] / f"{entry['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(entry, Dumper=EntryDumper, sort_keys=False, allow_unicode=True, width=160), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size // 1024} KB)")
    return path


# Deutsche Bundesbank bank sort code file


def blz_main_offices(source: Source) -> list[list[str]]:
    """Rows of the sort code file for the institution that owns each sort code (Merkmal 1), deletions excluded."""
    rows = list(csv.reader(io.StringIO(source.raw.decode("cp1252")), delimiter=";"))
    header, body = rows[0], rows[1:]
    if header[:2] != ["Bankleitzahl", "Merkmal"] or header[7] != "BIC" or header[10] != "Änderungskennzeichen":
        raise ValueError(f"unexpected sort code file header {header}")
    return [row for row in body if row[1] == "1" and row[10] != "D"]


BLZ_SAMPLES = ("10000000", "50010517", "20041111")


def blz_row_snippet(source: Source, code: str) -> str:
    match = re.search(rf'"{code}";"1";[^\r\n]*?"[A-Z0-9]{{11}}";"[0-9A-E][0-9]"', source.text)
    if match is None or not match.group(0).isascii():
        raise ValueError(f"row {code} not found or not plain ASCII")
    return match.group(0)


def build_blz_lookup(source: Source) -> dict:
    offices = blz_main_offices(source)
    rows = {r[0]: FlowRow(name=r[2], bic=r[7] or None, postcode=r[3], city=r[4], method=r[8]) for r in offices}
    items = []
    for code in BLZ_SAMPLES:
        snippet = blz_row_snippet(source, code)
        bic = rows[code]["bic"]
        items.append(item(source, BUNDESBANK, "Bankleitzahlendatei (CSV, current validity period)", f"row Bankleitzahl={code}, Merkmal=1", bic, snippet))
    items.append(item(source, BUNDESBANK, "Bankleitzahlendatei (CSV, current validity period)", "header row", "Merkmal", "Bankleitzahl;Merkmal;Bezeichnung;PLZ;Ort;Kurzbezeichnung;PAN;BIC", role="supporting"))
    vectors = [
        vector({"key": "10000000", "column": "name"}, "Bundesbank", "source", "first row of the file"),
        vector({"key": "10000000", "column": "bic"}, "MARKDEF1100", "source"),
        vector({"key": "37040044", "column": "method"}, "13", "source"),
        vector({"key": "50010517", "column": "bic"}, "INGDDEFFXXX", "source"),
        vector({"key": "50010517", "column": "method"}, "C1", "source"),
        vector({"key": "20041111", "column": "city"}, "Quickborn", "source"),
        vector("99999999", False, "derived", "not a sort code in the file"),
    ]
    return rule(
        "de-bundesbank-bank-sort-codes",
        f"Germany bank sort codes (Bankleitzahlen): name, BIC, postcode, city and check-digit method, {len(rows)} codes",
        "banking",
        "DE",
        "almanac.rules.lookup_table",
        {"key": "Bankleitzahl", "rows": rows},
        vectors,
        items,
        "The Deutsche Bundesbank's bank sort code file (Bankleitzahlendatei) for the current validity period, reduced to "
        "one row per sort code: the record with Merkmal 1, which marks the payment service provider that holds the code, "
        "while records with Merkmal 2 are further branches sharing it. Records flagged for deletion (Änderungskennzeichen D) "
        "are left out. Each row carries the institution's name (Bezeichnung), BIC (null where the file has none), postcode, "
        "city and the two-character check-digit method code (method) that de-bank-account-check-digit-methods implements. The "
        "Bundesbank replaces the file on the Monday after the first Saturday of March, June, September and December, so the "
        "cited bytes change at the next update; re-run the builder then. The file carries no licence statement, so the "
        "entry is held at license-review.",
        tier="A",
        valid_from="2026-09-07",
        valid_to="2026-12-06",
        tags=["bankleitzahl", "bic", "reference-table"],
        tests=[{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        assumed=[
            {"parameter": "valid_from, valid_to", "value": "2026-09-07 to 2026-12-06", "method": "assumed", "rationale": "The Bundesbank download page states this validity period for the current file; the page itself is not cited because its asset links carry a cache-busting suffix."},
            {"parameter": "rows", "value": "Merkmal 1 records without deletion flag", "method": "derived", "rationale": "One record per sort code keeps the table to the institution that owns each code."},
        ],
    )


def build_blz_method_mix(source: Source) -> dict:
    offices = blz_main_offices(source)
    counts = Counter(r[8] for r in offices)
    total = sum(counts.values())
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shares = {code: round(n / total, 6) for code, n in ordered}
    top = [code for code, _ in ordered[:3]]
    items = [item(source, BUNDESBANK, "Bankleitzahlendatei (CSV, current validity period)", f"row Bankleitzahl={code}, column Pruefzifferberechnungsmethode", code_method, blz_row_snippet(source, code)) for code, code_method in (("10000000", "09"), ("20041111", "13"))]
    return {
        "id": "de-bank-sort-code-check-digit-method-mix",
        "title": "Germany: share of bank sort codes by account check-digit method (Bundesbank sort code file)",
        "kind": "marginal",
        "domain": "banking",
        "region": "DE",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": "2026-09-07", "end": ACCESSED.isoformat()},
        "tags": TAGS + ["bankleitzahl", "check-digit"],
        "use_cases": USES,
        "spec": {"variable": "check_method", "unit": "ratio", "distribution": {"family": "categorical", "parameters": {"counts": dict(ordered), "shares": shares}}},
        "evidence": items,
        "assumed": [{"parameter": "shares", "value": "counts / total", "method": "derived", "rationale": "Counts are the number of sort codes (Merkmal 1 records without deletion flag) naming each method, divided by their total."}],
        "tests": [{"statistic": f'share["{code}"]', "expected": shares[code], "tolerance": 0.01} for code in top] + [{"statistic": "sum_of_shares", "expected": 1, "tolerance": 0.0001}],
        "notes": f"How often each check-digit method code appears across the {total} sort codes of the Bundesbank's current "
        "sort code file, counting the Merkmal 1 record of each code. Method 09 means no check digit is computed. Draw a "
        "method from this distribution, then generate an account number with de-bank-account-check-digit-methods, to "
        "reproduce the national mix. The file changes each quarter and carries no licence statement, so the entry is held "
        "at license-review.",
    }


def build_blz_successors(source: Source) -> dict:
    offices = blz_main_offices(source)
    flagged = [r for r in offices if r[11] == "1" or r[12] != "00000000"]
    rows = {r[0]: FlowRow(name=r[2], deletion_announced=r[11] == "1", successor=None if r[12] == "00000000" else r[12]) for r in flagged}
    ascii_rows = {r[0] for r in flagged if all(ord(c) < 128 for c in ";".join(r))}
    with_successor = sorted(code for code, row in rows.items() if row["successor"] and code in ascii_rows)
    without = sorted(code for code, row in rows.items() if not row["successor"] and code in ascii_rows)
    if not with_successor or not without:
        raise ValueError("expected sort codes with and without successors")
    sample, plain = with_successor[0], without[0]
    sample_line = re.search(rf'"{sample}";"1";[^\r\n]*', source.text).group(0)
    plain_line = re.search(rf'"{plain}";"1";[^\r\n]*', source.text).group(0)
    items = [
        item(source, BUNDESBANK, "Bankleitzahlendatei (CSV, current validity period)", f"row Bankleitzahl={sample}, fields Bankleitzahlloeschung and Nachfolge-Bankleitzahl", rows[sample]["successor"], sample_line),
        item(source, BUNDESBANK, "Bankleitzahlendatei (CSV, current validity period)", f"row Bankleitzahl={plain}", plain, plain_line),
    ]
    vectors = [
        vector({"key": sample, "column": "successor"}, rows[sample]["successor"], "source"),
        vector({"key": sample, "column": "deletion_announced"}, rows[sample]["deletion_announced"], "source"),
        vector({"key": plain, "column": "successor"}, None, "source", "no successor named"),
        vector("10000000", False, "derived", "the Bundesbank's own sort code is not flagged"),
    ]
    return rule(
        "de-bundesbank-sort-code-successors",
        f"Germany bank sort codes announced for deletion or with a successor code, {len(rows)} codes (Bundesbank sort code file)",
        "banking",
        "DE",
        "almanac.rules.lookup_table",
        {"key": "Bankleitzahl", "rows": rows},
        vectors,
        items,
        "Sort codes in the Bundesbank's current Bankleitzahlendatei whose owning record (Merkmal 1) announces an intended "
        "deletion (field Bankleitzahllöschung = 1) or names a successor sort code (Nachfolge-Bankleitzahl), typically after "
        "a bank merger. Use it to age synthetic or migrated account data: an account at a code listed here moves to the "
        f"successor when one is given ({len(with_successor)} codes) and has no announced successor otherwise. Records "
        "already deleted in this file (Änderungskennzeichen D) are excluded. The file is replaced each quarter and carries "
        "no licence statement, so the entry is held at license-review.",
        tier="A",
        valid_from="2026-09-07",
        valid_to="2026-12-06",
        tags=["bankleitzahl", "bank-mergers", "reference-table"],
        tests=[{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        assumed=[{"parameter": "valid_from, valid_to", "value": "2026-09-07 to 2026-12-06", "method": "assumed", "rationale": "The Bundesbank download page states this validity period for the current file; the page itself is not cited because its asset links carry a cache-busting suffix."}],
    )


# Bundesbank check-digit methods


def weights_of(heading: str) -> list[int]:
    match = re.search(r"Gewichtung ((?:[0-9A]+, )*[0-9A]+)", heading)
    if match is None:
        raise ValueError(f"no weights in {heading!r}")
    return [10 if w.strip() == "A" else int(w) for w in match.group(1).split(",") if w.strip()]


def span(first: int, last: int) -> list[int]:
    return list(range(first, last + 1))


def variant(heading: str, positions: list[int], check: int, reduce: str, *, left_to_right: bool = False, extend_to: int | None = None, **extra: Any) -> dict:
    weights = weights_of(heading)
    if extend_to is not None:
        weights = list(range(weights[0], extend_to + 1))
    if left_to_right:
        weights = list(reversed(weights))
    return {"positions": positions, "weights": weights, "check": check, "reduce": reduce, **extra}


NOT9 = [{"position": 3, "not_in": [9]}]
IS9 = [{"position": 3, "in": [9]}]


def de_method_table() -> dict[str, tuple[list[str], dict]]:
    """Method code to (headings confirmed in the PDF, method parameters)."""
    h = {
        "00": "00 Modulus 10, Gewichtung 2, 1, 2, 1, 2, 1, 2, 1, 2",
        "01": "01 Modulus 10, Gewichtung 3, 7, 1, 3, 7, 1, 3, 7, 1",
        "02": "Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 8, 9, 2",
        "06": "06 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7 (modifiziert)",
        "10": "10 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 8, 9, 10 (modifiziert)",
        "13": "13 Modulus 10, Gewichtung 2, 1, 2, 1, 2, 1",
        "17": "Modulus 11, Gewichtung 1, 2, 1, 2, 1, 2",
        "20": "20 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 8, 9, 3 (modifiziert)",
        "24": "24 Modulus 11, Gewichtung 1, 2, 3, 1, 2, 3, 1, 2, 3",
        "28": "28 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 8",
        "32": "32 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7",
        "34": "34 Modulus 11, Gewichtung 2, 4, 8, 5, A, 9, 7 (A = 10)",
        "38": "Modulus 11, Gewichtung 2, 4, 8, 5, A, 9 (A = 10)",
        "61": "61 Modulus 10, Gewichtung 2, 1, 2, 1, 2, 1, 2",
        "61b": "Stammnummer, Artziffer und Unternummer mit der Gewichtung 2, 1, 2, 1, 2, 1, 2, 1, 2",
        "63": "63 Modulus 10, Gewichtung 2, 1, 2, 1, 2, 1",
        "76": "76 Modulus 11, Gewichtung 2, 3, 4, 5 ff.",
        "88": "88 Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7",
        "88b": "Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 8 Ist die 3. Stelle der Kontonummer = 9",
        "91a": "1. Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7",
        "91b": "2. Modulus 11, Gewichtung 7, 6, 5, 4, 3, 2",
        "91c": "3. Modulus 11, Gewichtung 2, 3, 4, 0, 5, 6, 7, 8, 9, A (A = 10)",
        "91d": "4. Modulus 11, Gewichtung 2, 4, 8, 5, 10, 9",
        "99": "Modulus 11, Gewichtung 2, 3, 4, 5, 6, 7, 2, 3, 4 Die Berechnung erfolgt wie bei Verfahren 06. Ausnahmen: Kontonr.:0396000000 bis 0499999999",
    }
    kontoart_76 = [{"position": 1, "in": [0, 4, 6, 7, 8, 9]}]
    first_zero = [{"position": 1, "in": [0]}]
    table = {
        "00": ([h["00"]], {"variants": [variant(h["00"], span(1, 9), 10, "mod10", cross_sum=True)]}),
        "01": ([h["01"]], {"variants": [variant(h["01"], span(1, 9), 10, "mod10")]}),
        "02": ([h["02"]], {"variants": [variant(h["02"], span(1, 9), 10, "mod11")]}),
        "06": ([h["06"]], {"variants": [variant(h["06"], span(1, 9), 10, "mod11_zero")]}),
        "09": (["09 Keine Prüfzifferberechnung"], {"unchecked": True}),
        "10": ([h["10"]], {"variants": [variant(h["10"], span(1, 9), 10, "mod11_zero")]}),
        "13": ([h["13"]], {"variants": [variant(h["13"], span(2, 7), 8, "mod10", cross_sum=True), variant(h["13"], span(2, 7), 8, "mod10", cross_sum=True, shift=2)]}),
        "17": ([h["17"]], {"variants": [variant(h["17"], span(2, 7), 8, "mod11_less_one", left_to_right=True, cross_sum=True)]}),
        "20": ([h["20"]], {"variants": [variant(h["20"], span(1, 9), 10, "mod11_zero")]}),
        "24": ([h["24"]], {"variants": [{"procedure": "m24", "weights": weights_of(h["24"])[:3], "check": 10, "zero_leading": {"3": 1, "4": 1, "5": 1, "6": 1, "9": 3}}]}),
        "28": ([h["28"]], {"variants": [variant(h["28"], span(1, 7), 8, "mod11_zero")]}),
        "32": ([h["32"]], {"variants": [variant(h["32"], span(4, 9), 10, "mod11_zero")]}),
        "34": ([h["34"]], {"variants": [variant(h["34"], span(1, 7), 8, "mod11_zero")]}),
        "38": ([h["38"]], {"variants": [variant(h["38"], span(4, 9), 10, "mod11_zero")]}),
        "61": ([h["61"], h["61b"]], {"variants": [
            variant(h["61"], span(1, 7), 8, "mod10", cross_sum=True, when=[{"position": 9, "not_in": [8]}]),
            variant(h["61b"], span(1, 7) + [9, 10], 8, "mod10", cross_sum=True, when=[{"position": 9, "in": [8]}]),
        ]}),
        "63": ([h["63"]], {"variants": [
            variant(h["63"], span(2, 7), 8, "mod10", cross_sum=True, require=first_zero),
            variant(h["63"], span(2, 7), 8, "mod10", cross_sum=True, shift=2, require=first_zero),
        ]}),
        "76": ([h["76"]], {"variants": [
            variant(h["76"], span(2, 7), 8, "mod11_remainder", extend_to=7, require=kontoart_76),
            variant(h["76"], span(2, 7), 8, "mod11_remainder", extend_to=7, shift=2, require=kontoart_76),
        ]}),
        "88": ([h["88"], h["88b"]], {"variants": [
            variant(h["88"], span(4, 9), 10, "mod11_zero", when=NOT9),
            variant(h["88b"], span(3, 9), 10, "mod11_zero", when=IS9),
        ]}),
        "91": ([h["91a"], h["91b"], h["91c"], h["91d"]], {"variants": [
            variant(h["91a"], span(1, 6), 7, "mod11_zero"),
            variant(h["91b"], span(1, 6), 7, "mod11_zero"),
            variant(h["91c"], span(1, 10), 7, "mod11_zero"),
            variant(h["91d"], span(1, 6), 7, "mod11_zero"),
        ]}),
        "99": ([h["99"]], {"variants": [variant(h["99"], span(1, 9), 10, "mod11_zero")], "valid_ranges": [["0396000000", "0499999999"]]}),
    }
    return table


DE_TEST_NUMBERS = {
    "00": (["9290701", "539290858", "1501824", "1501832"], "Testkontonummern: 9290701, 539290858"),
    "02": (["1501836", "9290702", "539290858"], "Testkontonummern (richtig): 1501836, 9290702, 539290858,"),
    "06": (["94012341", "5073321010"], "Testkontonummern: 94012341, 5073321010"),
    "10": (["12345008", "87654008"], "Testkontonummern: 12345008, 87654008"),
    "17": (["0446786040"], "Testkontonummer: 0446786040"),
    "24": (["1306118605", "3307118608", "9307118603"], "11 5 = Prüfziffer"),
    "28": (["19999000", "9130000201"], "Testkontonummern: 19999000, 9130000201"),
    "32": (["9141405", "1709107983", "0122116979", "0121114867", "9030101192", "9245500460"], "Testkontonummern: 9141405, 1709107983, 0122116979,"),
    "34": (["9913000700", "9914001000"], "Testkontonummern: 9913000700, 9914001000"),
    "38": (["191919", "1100660"], "Testkontonummern: 191919, 1100660"),
    "61": (["2063099200", "0260760481"], "die vollständige Kontonummer lautet: 0 2 6 0 7 6 0 4 8 1"),
    "63": (["123456600", "1234566"], "Kontonummer lautet: 1 2 3 4 5 6 6 0 0"),
    "76": (["0006543200", "9012345600", "7876543100"], "5-stellige Kontonr. (Kontoart = 0) 0006543200"),
    "88": (["2525259", "1000500", "90013000", "92525253", "99913003"], "Testkontonummern: 2525259, 1000500, 90013000,"),
    "91": (["2974118000", "5281770000", "8840019000", "8840012000"], "Testkontonummern (richtig): 2974118000, 5281741000,"),
    "99": (["0068007003", "0847321750"], "Testkontonummern: 0068007003, 0847321750"),
}
WORKED_EXAMPLE_FORMS = {"1234566": "0 0 0 1 2 3 4 5 6 6", "2063099200": "2 0 6 3 0 9 9 2 0 0", "0260760481": "0 2 6 0 7 6 0 4 8 1", "123456600": "1 2 3 4 5 6 6 0 0", "1306118605": "1 3 0 6 1 1 8 6 0 5", "3307118608": "3 3 0 7 1 1 8 6 0 8", "9307118603": "9 3 0 7 1 1 8 6 0 3"}


def build_de_methods(pz: Source, blz: Source) -> dict:
    table = de_method_table()
    for headings, _ in table.values():
        pz.require(*headings)
    parameters = {"methods": {code: spec for code, (_, spec) in table.items()}}
    vectors = []
    items = []
    for code, (numbers, snippet) in DE_TEST_NUMBERS.items():
        pz.require(snippet)
        for number in numbers:
            pz.require(WORKED_EXAMPLE_FORMS.get(number, number))
            vectors.append(vector({"method": code, "account": number}, True, "source", f"Bundesbank test account number for method {code}"))
        items.append(item(pz, BUNDESBANK, "Prüfzifferberechnungsmethoden zur Prüfung von Kontonummern (PDF, Stand Juni 2018)", f"method {code}, heading and test account numbers", table[code][0][0], snippet))
    for code in ("01", "09", "13", "20"):
        items.append(item(pz, BUNDESBANK, "Prüfzifferberechnungsmethoden zur Prüfung von Kontonummern (PDF, Stand Juni 2018)", f"method {code}, heading", table[code][0][0], table[code][0][0]))
    pz.require("Testkontonummern (falsch): 8840010000, 8840057000")
    vectors += [
        vector({"method": "91", "account": "8840010000"}, False, "source", "listed as wrong for the last variant of method 91"),
        vector({"method": "91", "account": "8840057000"}, False, "source", "listed as wrong for the last variant of method 91"),
        vector({"method": "99", "account": "0400000000"}, True, "source", "inside the exception range 0396000000 to 0499999999"),
        vector({"method": "76", "account": "0000123456"}, True, "source", "method 76 worked example with the sub-account omitted"),
        vector({"method": "63", "account": "0001234566"}, True, "source", "method 63 worked example with the sub-account omitted"),
        vector({"method": "06", "account": "94012342"}, False, "derived", "check digit altered"),
        vector({"method": "32", "account": "9141406"}, False, "derived", "check digit altered"),
        vector({"method": "63", "account": "1123456600"}, False, "derived", "position 1 must be zero"),
        vector({"method": "09", "account": "1234567890"}, True, "derived", "method 09 performs no check"),
        vector({"method": "01", "complete": "0123456780"}, "0123456782", "derived", "check digit issued for an account body"),
        vector({"method": "13", "complete": "0123456000"}, "0123456600", "derived", "check digit at position 8"),
        vector({"method": "20", "complete": "0123456780"}, "0123456789", "derived"),
    ]
    for v in vectors:
        if de_bank_account_check.evaluate(parameters, v["input"]) != v["expected"]:
            raise ValueError(f"German vector fails: {v}")
    offices = blz_main_offices(blz)
    covered = sum(1 for r in offices if r[8] in parameters["methods"])
    return rule(
        "de-bank-account-check-digit-methods",
        f"Germany account number check-digit methods (Bundesbank Prüfzifferberechnungsmethoden): {len(parameters['methods'])} methods covering most sort codes",
        "banking",
        "DE",
        "almanac.rules.de_bank_account_check",
        parameters,
        vectors,
        items,
        "Germany's bank account number check digits, as the Deutsche Bundesbank specifies them in its "
        "Prüfzifferberechnungsmethoden. Every sort code in the Bankleitzahlendatei names a method; the account number is "
        "padded with zeros to ten digits and checked against it. This entry implements methods 00, 01, 02, 06, 09, 10, "
        "13, 17, 20, 24, 28, 32, 34, 38, 61, 63, 76, 88, 91 and 99, which together are named by "
        f"{covered} of the {len(offices)} sort codes in the current file. Weights are parsed from each method's heading "
        "in the PDF and positions follow its text. Methods with alternative computations (13, 63 and 76 for accounts "
        "quoted without their 00 sub-account, 61 and 88 depending on a digit, 91 with four variants) accept an account "
        "when any applicable variant does. The source vectors are the PDF's own test account numbers and worked "
        "examples. The 'complete' input fills the check position of the first variant, for generating valid numbers. "
        "The PDF states no licence, so the entry is held at license-review.",
        tier="B",
        valid_from="2018-06-04",
        tags=["check-digit", "account-number", "bankleitzahl"],
        assumed=[
            {"parameter": "valid_from", "value": "2018-06-04", "method": "assumed", "rationale": "The PDF is dated Stand Juni 2018 and its latest dated change takes effect on 04.06.2018."},
            {"parameter": "methods.76.weights", "value": [2, 3, 4, 5, 6, 7], "method": "derived", "rationale": "The heading reads 2, 3, 4, 5 ff. and the worked example weights a six-digit base number 6 5 4 3 2, so the weights continue in steps of one over positions 2 to 7."},
            {"parameter": "methods.17.weights", "value": "reversed", "method": "derived", "rationale": "Method 17 states its weights left to right over positions 2 to 7; the module applies weights from the right, so they are stored reversed."},
        ],
    )


# Bundesbank base rate and BGB default interest


def base_rate_steps(source: Source) -> list[dict]:
    steps = []
    for row in csv.reader(io.StringIO(source.raw.decode("utf-8-sig")), delimiter=";"):
        if len(row) > 9 and row[4] == "BBKBAS2" and row[9].startswith("Ab 1."):
            steps.append({"from": f"{row[7]}-01", "value": float(row[8])})
    if len(steps) < 40:
        raise ValueError("base rate steps not found")
    return steps


def base_item(source: Source, period: str, value: str) -> dict:
    snippet = f"BBKBAS2;EUR;ME;{period};{value};Ab"
    return item(source, BUNDESBANK, "Time series BBIN1.M.DE.BBK.BBKBAS2.EUR.ME, Basiszinssatz gemaess BGB (SDMX CSV)", f"TIME_PERIOD={period}, OBS_VALUE and change comment", value, snippet, unit="percent")


def build_base_rate(source: Source) -> dict:
    steps = base_rate_steps(source)
    items = [base_item(source, "2002-01", "2.57"), base_item(source, "2013-01", "-0.13"), base_item(source, "2026-07", "1.52")]
    vectors = [
        vector({"on": "2002-01-01"}, 2.57, "source"),
        vector({"on": "2013-01-01"}, -0.13, "source", "first negative base rate"),
        vector({"on": "2026-07-01"}, 1.52, "source"),
        vector({"on": "2026-10-31"}, 1.52, "derived", "latest step still in force"),
        vector({"on": "2025-06-30"}, 2.27, "derived", "day before a step"),
    ]
    return rule(
        "de-basiszinssatz-247-bgb",
        "Germany base rate (Basiszinssatz) under section 247 BGB, half-yearly steps since 2002",
        "rates",
        "DE",
        "almanac.rules.step_schedule",
        {"series": "BBIN1.M.DE.BBK.BBKBAS2.EUR.ME", "unit": "percent", "steps": steps},
        vectors,
        items,
        "The German civil-law base rate, which the Deutsche Bundesbank announces for 1 January and 1 July of each year "
        "under section 247 BGB and to which statutory default interest and many contracts refer. Steps are the months "
        "of the Bundesbank's end-of-month series whose observation comment announces a new rate ('Ab 1. Jan.' or 'Ab 1. "
        "Juli'), each taken to apply from the first day of that month; unchanged half-years are kept as steps with the "
        "same value. The query is pinned to January 2002 to October 2026 in data-only SDMX CSV, which carries no update "
        "timestamp. The series carries no licence statement, so the entry is held at license-review.",
        tier="A",
        valid_from="2002-01-01",
        tags=["base-rate", "interest-rate", "step-schedule", "bundesbank"],
        tests=[{"statistic": "count", "expected": len(steps), "tolerance": 0}],
        assumed=[{"parameter": "steps", "value": "months with an 'Ab 1.' comment", "method": "derived", "rationale": "The comment marks the month a new half-yearly rate takes effect; the value applies from the first day of that month."}],
    )


def law_text(source: Source, section: str) -> str:
    archive = zipfile.ZipFile(io.BytesIO(source.raw))
    xml = archive.read(next(n for n in archive.namelist() if n.endswith(".xml"))).decode("utf-8")
    match = re.search(rf"<enbez>{re.escape(section)}</enbez>.*?</norm>", xml, re.DOTALL)
    if match is None:
        raise ValueError(f"{section} not found")
    return match.group(0)


GERMAN_NUMBERS = {"fünf": 5, "neun": 9}


def build_default_interest(bgb: Source, egbgb: Source, base: Source) -> dict:
    s288 = law_text(bgb, "§ 288")
    consumer = re.search(r"beträgt für das Jahr (\w+) Prozentpunkte über dem Basiszinssatz", s288)
    business = re.search(r"Entgeltforderungen (\w+) Prozentpunkte über dem Basiszinssatz", s288)
    fee = re.search(r"Pauschale in Höhe von (\d+) Euro", s288)
    period = re.search(r"nicht innerhalb von (\d+) Tagen nach Fälligkeit und Zugang einer Rechnung", law_text(bgb, "§ 286"))
    applies = re.search(r"in der seit dem (\d+)\. Juli (\d{4}) geltenden Fassung", law_text(egbgb, "§ 34"))
    if not (consumer and business and fee and period and applies):
        raise ValueError("default interest provisions not found")
    parameters = {
        "applies_from": f"{applies.group(2)}-07-{int(applies.group(1)):02d}",
        "margin_points": {"consumer": GERMAN_NUMBERS[consumer.group(1)], "business": GERMAN_NUMBERS[business.group(1)]},
        "flat_fee_eur": int(fee.group(1)),
        "payment_period_days": int(period.group(1)),
        "base_rate_steps": base_rate_steps(base),
    }
    bgb_title = "Bürgerliches Gesetzbuch (BGB), XML"
    items = [
        item(bgb, GII, bgb_title, "section 288(1)", f"{consumer.group(1)} Prozentpunkte", "Der Verzugszinssatz beträgt für das Jahr fünf Prozentpunkte über dem Basiszinssatz."),
        item(bgb, GII, bgb_title, "section 288(2)", f"{business.group(1)} Prozentpunkte", "beträgt der Zinssatz für Entgeltforderungen neun Prozentpunkte über dem Basiszinssatz."),
        item(bgb, GII, bgb_title, "section 288(5)", "40 Euro", "wenn dieser kein Verbraucher ist, außerdem einen Anspruch auf Zahlung einer Pauschale in Höhe von 40 Euro."),
        item(bgb, GII, bgb_title, "section 286(3)", "30 Tagen", "kommt spätestens in Verzug, wenn er nicht innerhalb von 30 Tagen nach Fälligkeit und Zugang einer Rechnung"),
        item(bgb, GII, bgb_title, "section 187(1)", "nicht mitgerechnet", "so wird bei der Berechnung der Frist der Tag nicht mitgerechnet,", role="supporting"),
        item(bgb, GII, bgb_title, "section 188(1)", "Ablauf des letzten Tages", "Eine nach Tagen bestimmte Frist endigt mit dem Ablauf des letzten Tages der Frist.", role="supporting"),
        item(bgb, GII, bgb_title, "section 247(1)", "1. Januar und 1. Juli", "Er verändert sich zum 1. Januar und 1. Juli eines jeden Jahres", role="supporting"),
        item(egbgb, GII, "Einführungsgesetz zum Bürgerlichen Gesetzbuche (EGBGB), XML", "Article 229 section 34", "29. Juli 2014", "in der seit dem 29. Juli 2014 geltenden Fassung sind nur auf ein Schuldverhältnis anzuwenden", unit="date"),
        base_item(base, "2026-07", "1.52"),
    ]
    vectors = [
        vector({"base_rate_on": "2026-07-01"}, 1.52, "source", "Bundesbank base rate from 1 July 2026"),
        vector({"flat_fee": {"debtor_is_consumer": False}}, 40, "source", "section 288(5): 40 euros when the debtor is not a consumer"),
        vector({"flat_fee": {"debtor_is_consumer": True}}, 0, "source", "section 288(5) applies only to non-consumer debtors"),
        vector({"rate_on": "2026-07-01", "consumer_involved": True}, 6.52, "derived", "1.52 plus five points"),
        vector({"rate_on": "2026-07-01", "consumer_involved": False}, 10.52, "derived", "1.52 plus nine points"),
        vector({"rate_on": "2020-03-15", "consumer_involved": False}, 8.12, "derived", "-0.88 plus nine points"),
        vector({"due": "2026-03-01", "invoice_received": "2026-03-05"}, "2026-04-04", "derived", "30 days counted from the day after receipt"),
    ]


    for v in vectors:
        if de_default_interest.evaluate(parameters, v["input"]) != v["expected"]:
            raise ValueError(f"default interest vector fails: {v}")
    return rule(
        "de-bgb-288-default-interest",
        "Germany statutory default interest (section 288 BGB): base rate plus 5 or 9 points, 40 euro flat fee, 30-day default",
        "payments",
        "DE",
        "almanac.rules.de_default_interest",
        parameters,
        vectors,
        items,
        "Late-payment rules of the German Civil Code for invoices and payment claims. A money debt in default bears "
        "interest of five percentage points over the base rate a year (section 288(1)); where no consumer is party, "
        "payment claims bear nine points over it (288(2)); a creditor whose debtor is not a consumer may also claim a flat "
        "fee of 40 euros (288(5)). A debtor of a payment claim is in default at the latest when it has not paid within "
        "30 days of the due date and receipt of the invoice (286(3); for consumers only when the invoice says so), the "
        "period counted from the day after the event and ending with its last day (sections 187(1) and 188(1)). The base "
        "rate steps are the Bundesbank series also published as de-basiszinssatz-247-bgb. Under Article 229 section 34 "
        "EGBGB the current wording applies to obligations arising after 28 July 2014, hence valid_from. The rate applies "
        "to each day at the base rate then in force; weekend and holiday shifts of the last day (section 193) are not "
        "modelled. The law publisher's XML states no licence, so the entry is held at license-review.",
        tier="A",
        valid_from=parameters["applies_from"],
        tags=["late-payment", "default-interest", "base-rate", "invoicing"],
        assumed=[{"parameter": "margin_points", "value": parameters["margin_points"], "method": "derived", "rationale": "The statute writes the margins as words (fünf, neun); they are stored as the numbers 5 and 9."}],
    )


def build_payment_terms(bgb: Source) -> dict:
    s271a = law_text(bgb, "§ 271a")
    days = [int(d) for d in re.findall(r"nach mehr als (\d+) Tagen", s271a)]
    days += [int(d) for d in re.findall(r"Abnahme der Gegenleistung mehr als (\d+) Tage", s271a)]
    if days != [60, 30, 60, 30]:
        raise ValueError(f"unexpected section 271a periods {days}")
    rows = {
        "business_debtor": {"days": days[0], "counted_from": "receipt of performance or of the invoice", "longer_term": "effective only if expressly agreed and not grossly unfair to the creditor"},
        "public_authority": {"days": days[1], "counted_from": "receipt of performance or of the invoice", "longer_term": "effective only if expressly agreed and objectively justified"},
        "public_authority_limit": {"days": days[2], "counted_from": "receipt of performance or of the invoice", "longer_term": "void"},
        "inspection_or_acceptance": {"days": days[3], "counted_from": "receipt of performance", "longer_term": "effective only if expressly agreed and not grossly unfair to the creditor"},
    }
    title = "Bürgerliches Gesetzbuch (BGB), XML"
    items = [
        item(bgb, GII, title, "section 271a(1)", "mehr als 60 Tagen", "erst nach mehr als 60 Tagen nach Empfang der Gegenleistung verlangen kann, ist nur wirksam, wenn sie ausdrücklich getroffen"),
        item(bgb, GII, title, "section 271a(2) no. 1", "mehr als 30 Tagen", "erst nach mehr als 30 Tagen nach Empfang der Gegenleistung verlangen kann, nur wirksam, wenn die Vereinbarung ausdrücklich getroffen"),
        item(bgb, GII, title, "section 271a(2) no. 2", "unwirksam", "erst nach mehr als 60 Tagen nach Empfang der Gegenleistung verlangen kann, unwirksam."),
        item(bgb, GII, title, "section 271a(3)", "mehr als 30 Tage", "die Zeit für die Überprüfung oder Abnahme der Gegenleistung mehr als 30 Tage nach Empfang der Gegenleistung beträgt"),
        item(bgb, GII, title, "section 271a(5) no. 2", "Verbraucher", "ein Schuldverhältnis, aus dem ein Verbraucher die Erfüllung der Entgeltforderung schuldet.", role="supporting"),
    ]
    vectors = [
        vector({"key": "business_debtor", "column": "days"}, 60, "source", "section 271a(1)"),
        vector({"key": "public_authority", "column": "days"}, 30, "source", "section 271a(2) no. 1"),
        vector({"key": "public_authority_limit", "column": "longer_term"}, "void", "source", "section 271a(2) no. 2: a term over 60 days is unwirksam"),
        vector({"key": "inspection_or_acceptance", "column": "days"}, 30, "source", "section 271a(3)"),
        vector("consumer_debtor", False, "derived", "section 271a(5): the limits do not apply when a consumer owes the payment"),
    ]
    return rule(
        "de-bgb-271a-payment-term-limits",
        "Germany limits on agreed payment terms (section 271a BGB): 60 days between businesses, 30 and 60 for public authorities",
        "payments",
        "DE",
        "almanac.rules.lookup_table",
        {"key": "debtor or agreement type", "rows": rows},
        vectors,
        items,
        "How long a German invoice may give a business or public debtor to pay. Between businesses an agreed payment term "
        "of more than 60 days from receipt of the performance (or of a later invoice) is effective only if expressly agreed "
        "and not grossly unfair to the creditor. Where the debtor is a public contracting authority a term over 30 days "
        "needs express agreement and objective justification, and one over 60 days is void. An inspection or acceptance "
        "period over 30 days needs express agreement. None of this applies to instalment payments or to consumers as "
        "debtors. Under Article 229 section 34 EGBGB the provision applies to obligations arising after 28 July 2014. The "
        "law publisher's XML states no licence, so the entry is held at license-review.",
        tier="A",
        valid_from="2014-07-29",
        tags=["payment-terms", "late-payment", "invoicing", "reference-table"],
        assumed=[{"parameter": "rows", "value": "four agreement types", "method": "derived", "rationale": "Each row restates one paragraph of section 271a in English; the day counts are read from the statute."}],
    )


# UK modulus checking


def vocalink_rows(source: Source) -> list[str]:
    rows = []
    for line in source.raw.decode("ascii").splitlines():
        fields = line.split()
        if fields:
            if len(fields) not in (17, 18) or fields[2] not in ("MOD10", "MOD11", "DBLAL"):
                raise ValueError(f"unexpected weight table row {line!r}")
            rows.append(" ".join(fields))
    return rows


def build_gb_modulus(spec: Source, table: Source, subs: Source) -> dict:
    rows = vocalink_rows(table)
    substitutions = dict(line.split() for line in subs.raw.decode("ascii").splitlines() if line.strip())
    w2a, w2b = "0 0 1 2 5 3 6 4 8 7 10 9 3 1", "0 0 0 0 0 0 0 0 8 7 10 9 3 1"
    spec.require(w2a, w2b, "27 to the total (ie before you divide by 10)", "substitute the sorting code with 090126", "substituting the sorting code with 309634")
    parameters = {
        "rows": rows,
        "substitutions": substitutions,
        "exception_1_addend": 27,
        "exception_2_weights": {"g_not_9": [int(w) for w in w2a.split()], "g_is_9": [int(w) for w in w2b.split()]},
        "exception_8_sort_code": "090126",
        "exception_9_sort_code": "309634",
    }
    cases = re.findall(r"\n(\d{1,2}) (.+?)(\d{6}) (\d{8}) ([YN])", spec.text.split("3.1 Test data and expected results")[-1], re.DOTALL)
    if len(cases) != 34:
        raise ValueError(f"expected 34 test cases, found {len(cases)}")
    vectors = [vector({"sort_code": s, "account": a}, flag == "Y", "source", f"test case {n}: {' '.join(desc.split())}"[:150]) for n, desc, s, a, flag in cases]
    vectors += [
        vector({"sort_code": "000001", "account": "12345678"}, True, "derived", "sorting code outside every range cannot be checked and is presumed valid"),
        vector({"sort_code": "089999", "account": "6637495"}, False, "derived", "seven digits must be standardised before checking"),
    ]
    for v in vectors:
        if gb_sort_code_modulus.evaluate(parameters, v["input"]) != v["expected"]:
            raise ValueError(f"UK vector fails: {v}")
    title_pdf = "Validating account numbers: UK modulus checking, version 9.10 (PDF)"
    items = [
        item(spec, VOCALINK, title_pdf, "page 74, section 3.1, test case 1", "66374958", "1 Pass modulus 10 check. 089999 66374958 Y"),
        item(spec, VOCALINK, title_pdf, "page 75, section 3.1, test case 34", "00000190", "180002 00000190 Y"),
        item(spec, VOCALINK, title_pdf, "page 22, section 2.2.2.2, exceptions 2 and 9", w2a, "and g <> 9, substitute the weight specified in the modulus weight table with:"),
        item(spec, VOCALINK, title_pdf, "page 22, section 2.2.2.1, exception 1", "27", "27 to the total (ie before you divide by 10)"),
        item(spec, VOCALINK, title_pdf, "page 1, document date", "05 SEPTEMBER 2026", "VALIDATING ACCOUNT NUMBERS UK Modulus Checking 05 SEPTEMBER 2026", unit="date"),
        item(table, VOCALINK, "Modulus weight table (VALACDOS.txt)", "first row", rows[0], rows[0].split()[0] + " " + rows[0].split()[1] + " MOD11"),
        item(subs, VOCALINK, "Sorting code substitution table (SCSUBTAB.txt)", "first row", "938017", "938173 938017"),
    ]
    return rule(
        "gb-sort-code-modulus-check",
        f"UK sorting code and account number modulus checking (Vocalink v9.10): MOD10, MOD11, DBLAL and 14 exceptions, {len(rows)} table rows",
        "banking",
        "GB",
        "almanac.rules.gb_sort_code_modulus",
        parameters,
        vectors,
        items,
        "How UK payment originators check that an eight-digit account number is possible for a six-digit sorting code "
        "before sending a Bacs or Faster Payments instruction, per the specification Vocalink maintains for Pay.UK. The "
        "full modulus weight table (VALACDOS.txt, each row 'start end method fourteen-weights exception') and the "
        "exception 5 sorting code substitution table (SCSUBTAB.txt) are carried as parameters, and every exception the "
        "specification defines is implemented. The source vectors are all 34 test cases of section 3.1. Account numbers "
        "of other lengths must first be standardised to eight digits as section 2.1.2 describes; a sorting code should "
        "also be checked against the EISCD, which is not public. A pass means the number is possible, not that the "
        "account exists. Vocalink revises the table roughly monthly under a new file location, so the cited bytes are "
        "those of version 9.10. The documents state 'All rights reserved' and no reuse licence, so the entry is held at "
        "license-review.",
        tier="B",
        valid_from="2026-09-05",
        tags=["sort-code", "check-digit", "account-number", "bacs", "modulus-check"],
    )


def build_gb_standardisation(spec: Source) -> dict:
    snippets = {
        "natwest": "National Westminster Bank plc Use the last eight digits only.",
        "co-operative": "Co-Operative Bank plc Use the first eight digits only.",
        "leeds": "Leeds Building Society Use the first eight digits only.",
        "santander": "Replace the last digit of the sorting code with the first digit of the account number,",
        "seven": "General Prefix the account number with a zero (0). 1234567 01234567",
        "six": "General Prefix the account number with two zeros (00)",
    }
    spec.require(*snippets.values(), "0123456789 or 01-23456789 23456789", "nn-nn-nn 123456789 nn-nn-n1 23456789", "123456 00123456")
    parameters = {
        "ten_digit": {"natwest": "last_eight", "co-operative": "first_eight", "leeds": "first_eight"},
        "nine_digit": {"santander": "first_digit_to_sort_code"},
        "pad_from": 6,
    }
    title_pdf = "Validating account numbers: UK modulus checking, version 9.10 (PDF)"
    values = {"natwest": "23456789", "co-operative": "12345678", "leeds": "12345678", "santander": "nn-nn-n1", "seven": "01234567", "six": "00123456"}
    items = [item(spec, VOCALINK, title_pdf, f"pages 20-21, section 2.1.2, {key}", values[key], text) for key, text in snippets.items()]
    vectors = [
        vector({"sort_code": "600000", "account": "0123456789", "institution": "natwest"}, ["600000", "23456789"], "source", "NatWest example 0123456789"),
        vector({"sort_code": "600000", "account": "01-23456789", "institution": "natwest"}, ["600000", "23456789"], "source", "hyphen ignored"),
        vector({"sort_code": "089000", "account": "1234567890", "institution": "co-operative"}, ["089000", "12345678"], "source"),
        vector({"sort_code": "090000", "account": "123456789", "institution": "santander"}, ["090001", "23456789"], "source", "sorting code nn-nn-nn becomes nn-nn-n1"),
        vector({"sort_code": "200000", "account": "1234567"}, ["200000", "01234567"], "source"),
        vector({"sort_code": "200000", "account": "123456"}, ["200000", "00123456"], "source"),
        vector({"sort_code": "200000", "account": "12345678"}, ["200000", "12345678"], "derived", "eight digits are already standard"),
    ]


    for v in vectors:
        if gb_account_standardisation.evaluate(parameters, v["input"]) != v["expected"]:
            raise ValueError(f"standardisation vector fails: {v}")
    return rule(
        "gb-account-number-standardisation",
        "UK nonstandard account numbers converted to eight digits for modulus checking (Vocalink section 2.1.2)",
        "banking",
        "GB",
        "almanac.rules.gb_account_standardisation",
        parameters,
        vectors,
        items,
        "UK modulus checks assume an eight-digit account number. Section 2.1.2 of the Vocalink specification converts the "
        "others: ten-digit National Westminster numbers keep the last eight digits (a hyphen after the second digit is "
        "ignored), ten-digit Co-operative Bank and Leeds Building Society numbers keep the first eight, a nine-digit "
        "Santander number moves its first digit into the last place of the sorting code and keeps the remaining eight, "
        "and seven- and six-digit numbers are prefixed with one or two zeros. Institutions are keyed natwest, "
        "co-operative, leeds and santander. The source vectors are the specification's own examples; sorting codes in "
        "them are placeholders. Apply this before gb-sort-code-modulus-check. The document states 'All rights reserved' "
        "and no reuse licence, so the entry is held at license-review.",
        tier="B",
        valid_from="2026-09-05",
        tags=["sort-code", "account-number", "bacs", "data-cleansing"],
    )


# IBAN


def build_iban(source: Source) -> dict:
    letters = dict(re.findall(r"([A-Z]) = (\d{2})", source.collapsed))
    if len(letters) != 26:
        raise ValueError("letter table incomplete")
    parameters = {
        "modulus": 97,
        "complement_base": 98,
        "valid_remainder": 1,
        "letter_values": {k: int(v) for k, v in sorted(letters.items())},
        "lengths": {"AZ": int(re.search(r"consisting of (\d+) alphanumeric characters in Azerbaijan", source.collapsed).group(1))},
    }
    sample = "AZ84 NABZ 0000 0000 1370 1000 2944"
    vectors = [
        vector("AZ84NABZ00000000137010002944", True, "source", "validation example"),
        vector(sample, True, "source", "printed form with spaces"),
        vector({"country": "AZ", "bban": "NABZ00000000137010002944"}, "84", "source", "calculation example: AZ00 NABZ 0000 0000 1370 1000 2944 gives 84"),
        vector("AZ85NABZ00000000137010002944", False, "derived", "check digits altered"),
        vector("AZ84NABZ0000000013701000294", False, "derived", "27 characters for a 28-character country"),
        vector("AZ84NABZ00000000137010002945", False, "derived", "last digit altered"),
    ]
    for v in vectors:
        if iban.evaluate(parameters, v["input"]) != v["expected"]:
            raise ValueError(f"IBAN vector fails: {v}")
    title = "Methodological guidelines on the international bank account number (IBAN), 2013 (PDF)"
    items = [
        item(source, CBAR, title, "page 5, section VII.1, initial step", "AZ00 NABZ 0000 0000 1370 1000 2944", "with the MOD 97-10 method, the country code of the Republic of Azerbaijan"),
        item(source, CBAR, title, "page 5, section VII.1, step 2, compliance table", "A = 10", "letters used in the IBAN structure are replaced with numbers:"),
        item(source, CBAR, title, "page 6, section VII.1, step 3", sample, "is divided by 97 and the resulting balance is subtracted from 98."),
        item(source, CBAR, title, "page 6, section VII.2, step 2", "2310113500000000137010002944103584", "Outcome: 2310113500000000137010002944103584"),
        item(source, CBAR, title, "page 6, section VII.2, step 3", "must equal to one", "method) must equal to one. Otherwise, check digits are not correct."),
        item(source, CBAR, title, "page 4, section V", 28, "The IBAN structure consisting of 28 alphanumeric characters in Azerbaijan is as follows:", unit="integer"),
    ]
    return rule(
        "global-iban-check-digits-mod97",
        "IBAN check digits by ISO 7064 MOD 97-10: calculation and validation as a central bank specifies them",
        "payments",
        "global",
        "almanac.rules.iban",
        parameters,
        vectors,
        items,
        "The check digits of every International Bank Account Number (ISO 13616): move the country code and check digits "
        "to the end, replace letters by 10 to 35, and require the number to leave remainder 1 modulo 97; to issue check "
        "digits, put 00 in their place and subtract the remainder from 98. The procedure, the letter table and the "
        "worked example are taken from the IBAN guidelines of the Central Bank of the Republic of Azerbaijan, which also "
        "states the Azerbaijani IBAN length of 28. The ISO 13616 registry of country formats is maintained by SWIFT and "
        "could not be fetched, so 'lengths' holds only the lengths an official source fetched here states; a country not "
        "listed is checked for its check digits only. The PDF states no licence, so the entry is held at license-review.",
        tier="B",
        valid_from="2013-01-01",
        tags=["iban", "check-digit", "iso-13616", "iso-7064"],
        assumed=[{"parameter": "valid_from", "value": "2013-01-01", "method": "assumed", "rationale": "The guidelines are dated Baku - 2013 without a day; the algorithm itself is the ISO 7064 procedure in use before that."}],
    )


# US routing numbers (Regulation CC Appendix A)


def appendix_a(source: Source) -> str:
    text = source.raw.decode("utf-8")
    start = text.index("Appendix A to Part 229&#x2014;Routing")
    return text[start: text.index("Appendix B to Part 229", start)]


def build_us_routing_prefix(source: Source) -> dict:
    block = appendix_a(source)
    if "Adding 2 to the first digit denotes a thrift institution." not in block:
        raise ValueError("prefix rule not found")
    rows = {f"{d:02d}": {"district": d, "institution": "bank"} for d in range(1, 13)}
    rows.update({f"{d + 20:02d}": {"district": d, "institution": "thrift"} for d in range(1, 13)})
    title = "12 CFR part 229 (Regulation CC), Appendix A, eCFR XML as of 2026-10-29"
    items = [
        item(source, ECFR, title, "Appendix A, paragraph B", "01", "and 12 will be the first two digits of the routing number of a bank in the Twelfth District (San Francisco)."),
        item(source, ECFR, title, "Appendix A, paragraph B", "thrift", "Adding 2 to the first digit denotes a thrift institution."),
        item(source, ECFR, title, "Appendix A, paragraph B", "32", "Thus, 21 identifies a thrift in the First District, and 32 denotes a thrift in the Twelfth District."),
        item(source, ECFR, title, "Appendix A, citation", "May 27, 1988", "[53 FR 19433, May 27, 1988]", unit="date", role="supporting"),
    ]
    vectors = [
        vector({"key": "01", "column": "district"}, 1, "source", "01: First District (Boston)"),
        vector({"key": "12", "column": "district"}, 12, "source", "12: Twelfth District (San Francisco)"),
        vector({"key": "21", "column": "institution"}, "thrift", "source", "21: a thrift in the First District"),
        vector({"key": "32", "column": "district"}, 12, "source", "32: a thrift in the Twelfth District"),
        vector({"key": "05", "column": "institution"}, "bank", "derived"),
        vector("13", False, "derived", "no district 13"),
    ]
    return rule(
        "us-routing-number-federal-reserve-prefix",
        "US routing number first two digits: Federal Reserve District 01 to 12, thrift institutions 21 to 32",
        "banking",
        "US",
        "almanac.rules.lookup_table",
        {"key": "first two digits of the nine-digit routing number", "rows": rows},
        vectors,
        items,
        "The structure of the American Bankers Association routing number as Regulation CC (12 CFR part 229, Appendix A) "
        "describes it: the first four digits form the Federal Reserve routing symbol and the first two identify the "
        "Federal Reserve District of the bank, 01 (Boston) to 12 (San Francisco), with 2 added to the first digit for a "
        "thrift institution, so 21 to 32. The 24 rows are generated from that rule. Other prefixes in use (such as those "
        "for electronic or Treasury items) are not stated in the regulation and are not listed. The ninth digit's check "
        "algorithm is not stated by any official body fetched here and is not included. valid_from is the appendix's "
        "original Federal Register citation. US federal works carry no copyright, but the eCFR states no reuse terms, so "
        "the entry is held at license-review.",
        tier="A",
        valid_from="1988-05-27",
        tags=["routing-number", "aba", "federal-reserve", "regulation-cc", "reference-table"],
        assumed=[{"parameter": "rows", "value": "01-12 bank, 21-32 thrift", "method": "derived", "rationale": "Expanded from the stated rule and its two endpoint examples."}],
    )


def build_us_fed_routing_numbers(source: Source) -> dict:
    block = appendix_a(source)
    sets = {}
    for heading, key in (("Federal Reserve Banks", "federal_reserve_banks"), ("Federal Home Loan Banks", "federal_home_loan_banks")):
        part = block.split(f"<HD1>{heading}")[1].split("</SCOL2>")[0]
        numbers = [re.sub(r"\s", "", n) for n in re.findall(r"<LI>([\d ]+?)\s*</LI>", part)]
        if not numbers or any(len(n) != 9 for n in numbers):
            raise ValueError(f"routing numbers under {heading} malformed")
        sets[key] = {n: f"{heading[:-1]}, Federal Reserve District {int(n[:2])}" for n in numbers}
    title = "12 CFR part 229 (Regulation CC), Appendix A, eCFR XML as of 2026-10-29"
    items = [
        item(source, ECFR, title, "Appendix A, Federal Reserve Banks, first entry", "0110 0001 5", "<LI>0110 0001 5</LI>"),
        item(source, ECFR, title, "Appendix A, Federal Home Loan Banks, first entry", "0110 0053 6", "<LI>0110 0053 6</LI>"),
        item(source, ECFR, title, "Appendix A, heading", "Routing Number Guide", "The guide lists the routing numbers of checks drawn on Federal Reserve Banks and Federal Home Loan Banks,", role="supporting"),
    ]
    vectors = [
        vector({"set": "federal_reserve_banks", "value": "011000015"}, True, "source", "first Federal Reserve Bank entry, 0110 0001 5"),
        vector({"set": "federal_reserve_banks", "value": "125000011"}, True, "source", "last Federal Reserve Bank entry, 1250 0001 1"),
        vector({"set": "federal_home_loan_banks", "value": "011000536"}, True, "source", "first Federal Home Loan Bank entry"),
        vector({"set": "federal_home_loan_banks", "value": "011000015"}, False, "derived", "a Federal Reserve Bank number, not a Home Loan Bank one"),
    ]
    return rule(
        "us-regulation-cc-federal-reserve-and-fhlb-routing-numbers",
        "US routing numbers of Federal Reserve Banks and Federal Home Loan Banks (Regulation CC Appendix A)",
        "banking",
        "US",
        "almanac.rules.enumeration",
        {"sets": sets},
        vectors,
        items,
        f"The {len(sets['federal_reserve_banks'])} nine-digit routing numbers of Federal Reserve Bank offices and the "
        f"{len(sets['federal_home_loan_banks'])} of Federal Home Loan Banks that Regulation CC Appendix A lists as drawing "
        "next-day availability checks, printed there in the groups 'XXXX XXXX X' and stored here without spaces. Each label "
        "names the Federal Reserve District read from the first two digits (see us-routing-number-federal-reserve-prefix). "
        "Useful as genuine routing numbers of central institutions for test data that should not name a commercial bank. "
        "US federal works carry no copyright, but the eCFR states no reuse terms, so the entry is held at license-review.",
        tier="A",
        valid_from="1988-05-27",
        tags=["routing-number", "aba", "federal-reserve", "regulation-cc"],
        tests=[
            {"statistic": "count[federal_reserve_banks]", "expected": len(sets["federal_reserve_banks"]), "tolerance": 0},
            {"statistic": "count[federal_home_loan_banks]", "expected": len(sets["federal_home_loan_banks"]), "tolerance": 0},
        ],
    )


def main() -> None:
    blz, pz, base = Source("blz"), Source("pz"), Source("base")
    bgb, egbgb = Source("bgb"), Source("egbgb")
    vocalink_pdf, valacdos, scsubtab = Source("vocalink_pdf"), Source("valacdos"), Source("scsubtab")
    cbar, ecfr = Source("cbar"), Source("ecfr229")
    for entry in (
        build_blz_lookup(blz),
        build_blz_method_mix(blz),
        build_blz_successors(blz),
        build_de_methods(pz, blz),
        build_base_rate(base),
        build_default_interest(bgb, egbgb, base),
        build_payment_terms(bgb),
        build_gb_modulus(vocalink_pdf, valacdos, scsubtab),
        build_gb_standardisation(vocalink_pdf),
        build_iban(cbar),
        build_us_routing_prefix(ecfr),
        build_us_fed_routing_numbers(ecfr),
    ):
        write(entry)


if __name__ == "__main__":
    main()

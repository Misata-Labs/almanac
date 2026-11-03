"""Regenerate the European payroll and personal-tax rules for the largest employer markets.

Every value is parsed from an official publication fetched live and cited by hash:

* Germany: Gesetze im Internet XML archives (EStG § 32a, § 32, § 66; SolZG 1995; SGB IV; MiLoG and the
  Fourth and Fifth minimum wage ordinances; the 2026 social insurance reference values ordinance), the
  Bundesgesetzblatt PDF of the Steuerfortentwicklungsgesetz for effective dates, and the 2026 marginal
  employment guidelines of the social insurance central bodies.
* Austria: RIS consolidated federal law XML (EStG 1988 § 33).
* Netherlands: BWB consolidated law XML (Wet inkomstenbelasting 2001) and Staatscourant XML (minimum wage).
* Ireland: Finance Act 2025 XML (Irish Statute Book), Revenue's notes for guidance PDFs and the Department of
  Finance Budget 2026 tax policy changes PDF.
* Spain: BOE consolidated legislation API (Ley 35/2006 art. 63) and BOE XML (Real Decreto 126/2026, Orden PJC/297/2026).
* France: BOFiP-Impôts (BOI-IR-LIQ-20-10, 2026 version).
* Poland: Sejm ELI API PDFs of the Dziennik Ustaw (PIT consolidated text, 2026 minimum wage regulation).

Run from the repository root:

    uv run python tools/build_eu_payroll.py
"""

from __future__ import annotations

import html
import io
import re
import sys
import time
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx
from _common import evidence, fetch, write

from almanac.fetch import Resource
from almanac.rules import (
    cumulative_bracket_tariff,
    de_income_tax_tariff,
    de_solidarity_surcharge,
    ie_income_tax_usc,
    income_tax_bands,
)

MAX_SNIPPET_WORDS = 24
ACCESSED = date(2026, 11, 3)
UNSTATED = "unstated"
GII = "https://www.gesetze-im-internet.de"
BMJ = "Bundesministerium der Justiz (Gesetze im Internet)"
USE_CASES = ["payroll-demo", "hr-demo", "tax-demo", "synthetic-employees"]
GII_LICENSE_NOTE = "Gesetze im Internet carries no licence statement, so the licence is recorded as unstated and the entry stays at license-review."


def fetch_with_retry(url: str, attempts: int = 4) -> bytes:
    """Fetch ``url``, retrying transient connection failures with a growing pause."""
    for attempt in range(1, attempts + 1):
        try:
            return fetch(url)
        except httpx.TransportError:
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def collapse(text: str) -> str:
    return " ".join(text.split())


def plain(markup: str) -> str:
    """Markup with tags replaced by spaces and whitespace collapsed, for parsing values."""
    return collapse(re.sub(r"<[^>]+>", " ", markup))


class Source:
    """A fetched resource seen the way the verifier sees it, so every snippet and value is checked before it is written."""

    def __init__(self, url: str, publisher: str, title: str, license_id: str = UNSTATED) -> None:
        self.url = url
        self.publisher = publisher
        self.title = title
        self.license_id = license_id
        self.raw = fetch_with_retry(url)
        self.text = collapse(Resource(url=url, content=self.raw, content_type="").text)

    def contains(self, needle: str) -> bool:
        return collapse(needle) in self.text

    def cite(self, locator: str, value: Any, snippet: str, unit: str = "text", role: str = "primary") -> dict:
        snippet = window(collapse(snippet), str(value))
        for needle, what in ((snippet, "snippet"), (str(value), "value")):
            if not self.contains(needle):
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        item = evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, self.license_id, self.raw, role)
        item["accessed_at"] = ACCESSED.isoformat()
        return item


def window(snippet: str, value: str, limit: int = MAX_SNIPPET_WORDS) -> str:
    """Trim a sentence to at most ``limit`` words, keeping the words around the cited value when it occurs in the sentence."""
    words = snippet.split()
    if len(words) <= limit:
        return snippet
    first = value.split()[0] if value.split() else ""
    anchor = next((i for i, word in enumerate(words) if first and first in word), 0)
    start = max(0, min(anchor - limit // 2, len(words) - limit))
    return " ".join(words[start:start + limit])


def number(text: str, thousands: str, decimal: str) -> int | float:
    """A figure written with the given separators, as an int when whole and a float otherwise."""
    cleaned = collapse(text).replace("€", "").strip().replace(thousands, "").replace(" ", "").replace(decimal, ".")
    value = Decimal(cleaned)
    return int(value) if value == value.to_integral_value() else float(value)


def de(text: str) -> int | float:
    return number(text, ".", ",")


def match(pattern: str, text: str, what: str, flags: int = 0) -> re.Match:
    found = re.search(pattern, text, flags)
    if found is None:
        raise ValueError(f"{what}: pattern {pattern!r} not found")
    return found


def rule_entry(entry_id: str, title: str, domain: str, region: str, implementation: str, parameters: dict, vectors: list[dict],
               items: list[dict], tests: list[dict], tags: list[str], notes: str, valid: tuple[str, str | None],
               tier: str = "A", assumed: list[dict] | None = None, status: str = "license-review") -> dict:
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": tier,
        "valid_from": valid[0],
        "valid_to": valid[1],
        "tags": tags,
        "use_cases": USE_CASES,
        "spec": {"implementation": f"almanac.rules.{implementation}", "parameters": parameters, "vectors": vectors},
        "evidence": items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}] + tests,
        "notes": notes,
    }


def vector(value: Any, expected: Any, origin: str, note: str | None = None) -> dict:
    item = {"input": value, "expected": expected, "origin": origin}
    if note:
        item["note"] = note
    return item


# ---------------------------------------------------------------- Germany


class GiiLaw(Source):
    """A Gesetze-im-Internet XML archive with access to one section's plain text."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"{GII}/{slug}/xml.zip", BMJ, f"Gesetze im Internet, {slug} (XML archive)")
        archive = zipfile.ZipFile(io.BytesIO(self.raw))
        self.xml = next(archive.read(m) for m in archive.namelist() if m.endswith(".xml")).decode("utf-8")

    def section(self, label: str) -> str:
        for norm in re.findall(r"<norm[^>]*>(.*?)</norm>", self.xml, re.DOTALL):
            found = re.search(r"<enbez>(.*?)</enbez>", norm)
            if found and found.group(1) == label:
                return plain(norm)
        raise ValueError(f"section {label} not found in {self.url}")


def steuerfortentwicklungsgesetz() -> Source:
    return Source(
        "https://www.recht.bund.de/bgbl/1/2024/449/regelungstext.pdf?__blob=publicationFile&v=1",
        "Bundesministerium der Justiz (Bundesgesetzblatt)",
        "Steuerfortentwicklungsgesetz (SteFeG), BGBl. 2024 I Nr. 449 (PDF)",
    )


def de_tariff_entry(estg: GiiLaw, stefeg: Source) -> dict:
    text = estg.section("§ 32a")
    zero = match(r"bis (\d[\d ]*) Euro \(Grundfreibetrag\): 0;", text, "§ 32a zone 1")
    y = match(r"von (\d[\d ]*) Euro bis (\d[\d ]*) Euro: \((\d+,\d+) • y \+ (\d[\d ]*)\) • y;", text, "§ 32a zone 2")
    z = match(r"von (\d[\d ]*) Euro bis (\d[\d ]*) Euro: \((\d+,\d+) • z \+ (\d[\d ]*)\) • z \+ (\d[\d ]*,\d+);", text, "§ 32a zone 3")
    lin42 = match(r"von (\d[\d ]*) Euro bis (\d[\d ]*) Euro: (0,\d+) • x – (\d[\d ]*,\d+);", text, "§ 32a zone 4")
    lin45 = match(r"von (\d[\d ]*) Euro an: (0,\d+) • x – (\d[\d ]*,\d+)\.", text, "§ 32a zone 5")
    z_offset = match(r"Zehntausendstel des (\d[\d ]*) Euro übersteigenden Teils", text, "§ 32a z offset")
    grundfreibetrag = de(zero.group(1))
    zones = [
        {"upper": grundfreibetrag, "formula": "zero"},
        {"upper": de(y.group(2)), "formula": "quadratic", "offset": grundfreibetrag, "a": de(y.group(3)), "b": de(y.group(4)), "c": 0},
        {"upper": de(z.group(2)), "formula": "quadratic", "offset": de(z_offset.group(1)), "a": de(z.group(3)), "b": de(z.group(4)), "c": de(z.group(5))},
        {"upper": de(lin42.group(2)), "formula": "linear", "rate": de(lin42.group(3)), "deduction": de(lin42.group(4))},
        {"upper": None, "formula": "linear", "rate": de(lin45.group(2)), "deduction": de(lin45.group(3))},
    ]
    parameters = {"tax_year_from": 2026, "currency": "EUR", "zones": zones, "rounding": "taxable income and tax rounded down to full euros", "splitting": "twice the tariff on half the joint taxable income"}

    def tax(income: int, joint: bool = False) -> int:
        return de_income_tax_tariff.splitting(parameters, income) if joint else de_income_tax_tariff.tariff(parameters, income)

    z_top, lin_top = zones[2]["upper"], zones[3]["upper"]
    vectors = [
        vector({"income": grundfreibetrag}, 0, "source", "§ 32a(1) Nr. 1: no tax up to the basic allowance"),
        vector({"income": zones[1]["upper"]}, int(zones[2]["c"]), "source", "the constant of zone 3 equals the zone 2 formula at its upper bound, rounded down"),
        vector({"income": grundfreibetrag + 1}, tax(grundfreibetrag + 1), "derived", "first euro above the basic allowance"),
        vector({"income": 30000}, tax(30000), "derived"),
        vector({"income": z_top}, tax(z_top), "derived", "top of the second progressive zone"),
        vector({"income": z_top + 1}, tax(z_top + 1), "derived", "first euro at the 42 percent rate"),
        vector({"income": 100000}, tax(100000), "derived"),
        vector({"income": lin_top + 1}, tax(lin_top + 1), "derived", "first euro at the 45 percent rate"),
        vector({"income": 60000.99}, tax(60000), "derived", "taxable income is rounded down to full euros first"),
        vector({"income": 60000, "splitting": True}, tax(60000, True), "derived", "§ 32a(5) splitting: twice the tax on 30 000"),
        vector({"income": 2 * grundfreibetrag, "splitting": True}, 0, "derived", "a couple pays nothing up to twice the basic allowance"),
    ]
    items = [
        estg.cite("EStG § 32a Absatz 1 Satz 2 Nummer 1", zero.group(1), "bis " + zero.group(1) + " Euro (Grundfreibetrag):"),
        estg.cite("EStG § 32a Absatz 1 Satz 2 Nummer 2", f"({y.group(3)} • y + {y.group(4)}) • y;", f"von {y.group(1)} Euro bis {y.group(2)} Euro:"),
        estg.cite("EStG § 32a Absatz 1 Satz 2 Nummer 3", f"({z.group(3)} • z + {z.group(4)}) • z + {z.group(5)};", f"von {z.group(1)} Euro bis {z.group(2)} Euro:"),
        estg.cite("EStG § 32a Absatz 1 Satz 2 Nummer 4", f"{lin42.group(3)} • x – {lin42.group(4)};", f"von {lin42.group(1)} Euro bis {lin42.group(2)} Euro:"),
        estg.cite("EStG § 32a Absatz 1 Satz 2 Nummer 5", f"{lin45.group(2)} • x – {lin45.group(3)}.", f"von {lin45.group(1)} Euro an:"),
        estg.cite("EStG § 32a Absatz 1 Sätze 2 to 6", "ab dem Veranlagungszeitraum 2026", "Der sich ergebende Steuerbetrag ist auf den nächsten vollen Euro-Betrag abzurunden."),
        estg.cite("EStG § 32a Absatz 5 (Splitting-Verfahren)", "Splitting-Verfahren", "das Zweifache des Steuerbetrags, der sich für die Hälfte ihres gemeinsam zu versteuernden Einkommens nach Absatz 1 ergibt"),
        stefeg.cite("Artikel 10 Absatz 2 (Inkrafttreten)", "Die Artikel 2, 4 und 6 treten am 1. Januar 2026 in Kraft.", "Die Artikel 2, 4 und 6 treten am 1. Januar 2026 in Kraft.", role="supporting"),
    ]
    tests = [
        {"statistic": "count", "expected": 5, "tolerance": 0},
        {"statistic": "tax[50000]", "expected": tax(50000), "tolerance": 0},
        {"statistic": "splitting[100000]", "expected": tax(100000, True), "tolerance": 0},
    ]
    return rule_entry(
        "de-income-tax-tariff-2026",
        "Germany income tax tariff from 2026 under § 32a EStG: basic allowance, progressive zones and splitting for joint assessment",
        "tax", "DE", "de_income_tax_tariff", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "statute", "formula"],
        "The German tariff income tax (tarifliche Einkommensteuer) applicable from the 2026 assessment period as § 32a EStG states it: nil up to the basic allowance "
        "(Grundfreibetrag), two progressive zones that are quadratic in y (one ten-thousandth of the income above the basic allowance) and z (one ten-thousandth of the "
        "income above the zone 3 offset), then linear zones at 42 and 45 percent less a fixed amount. Taxable income is rounded down to full euros before the formula "
        "and the tax is rounded down to full euros. Spouses assessed jointly under §§ 26, 26b pay twice the tariff on half their joint taxable income (§ 32a(5)). "
        "The statute contains no worked examples; the source vectors restate the nil zone and the zone 3 constant, which equals the zone 2 formula at the zone 2 "
        "upper bound, and the other vectors are computed from the statutory formula. Wage tax withheld by employers follows the Federal Ministry of Finance's "
        "Programmablaufplan, which also deducts allowances not modelled here. The Steuerfortentwicklungsgesetz (BGBl. 2024 I Nr. 449) states that its Article 2, "
        "which introduced this tariff, entered into force on 1 January 2026. " + GII_LICENSE_NOTE,
        ("2026-01-01", None),
    )


def de_solidarity_entry(solzg: GiiLaw, stefeg: Source) -> dict:
    s3 = solzg.section("§ 3")
    s4 = solzg.section("§ 4")
    limits = match(r"1\. in den Fällen des § 32a Absatz 5 und 6 des Einkommensteuergesetzes (\d[\d ]*) Euro, 2\. in anderen Fällen (\d[\d ]*) Euro übersteigt", s3, "SolZG § 3(3)")
    rate = match(r"Der Solidaritätszuschlag beträgt (\d+,\d+) Prozent der Bemessungsgrundlage", s4, "SolZG § 4 rate")
    phase = match(r"Er beträgt nicht mehr als (\d+,\d+) Prozent des Unterschiedsbetrages", s4, "SolZG § 4 phase-in")
    parameters = {
        "currency": "EUR",
        "rate_percent": de(rate.group(1)),
        "phase_in_percent": de(phase.group(1)),
        "exemption_limit": {"single": de(limits.group(2)), "joint": de(limits.group(1))},
        "base": "income tax as assessed, computed with the child allowances of § 32(6) EStG (SolZG § 3(2))",
    }

    single, joint = parameters["exemption_limit"]["single"], parameters["exemption_limit"]["joint"]

    def solz(tax: float, is_joint: bool = False) -> str:
        return str(de_solidarity_surcharge.surcharge(parameters, tax, is_joint))

    vectors = [
        vector({"income_tax": single}, "0.00", "source", "§ 3(3) Nr. 2: levied only when the base exceeds the exemption limit"),
        vector({"income_tax": joint, "joint": True}, "0.00", "source", "§ 3(3) Nr. 1: joint assessment limit"),
        vector({"income_tax": single + 1000}, solz(single + 1000), "derived", "phase-in zone: capped at the phase-in rate on the excess"),
        vector({"income_tax": 50000}, solz(50000), "derived", "above the phase-in zone the full rate applies"),
        vector({"income_tax": joint + 1000, "joint": True}, solz(joint + 1000, True), "derived"),
        vector({"income_tax": 30000.123}, solz(30000.123), "derived", "fractions of a cent are dropped"),
    ]
    items = [
        solzg.cite("SolZG 1995 § 3 Absatz 3 Satz 1", limits.group(1), f"in den Fällen des § 32a Absatz 5 und 6 des Einkommensteuergesetzes {limits.group(1)} Euro,"),
        solzg.cite("SolZG 1995 § 3 Absatz 3 Satz 1", limits.group(2), f"in anderen Fällen {limits.group(2)} Euro"),
        solzg.cite("SolZG 1995 § 4 Satz 1", rate.group(1), rate.group(0)),
        solzg.cite("SolZG 1995 § 4 Satz 2 and 3", phase.group(1), "Bruchteile eines Cents bleiben außer Ansatz."),
        solzg.cite("SolZG 1995 § 6 Absatz 27", "erstmals im Veranlagungszeitraum 2026 anzuwenden", "§ 3 Absatz 3 in der Fassung des Artikels 4 des Gesetzes vom 23. Dezember 2024"),
        stefeg.cite("Artikel 10 Absatz 2 (Inkrafttreten)", "Die Artikel 2, 4 und 6 treten am 1. Januar 2026 in Kraft.", "Artikel 4 Weitere Änderung des Solidaritätszuschlaggesetzes 1995", role="supporting"),
    ]
    tests = [
        {"statistic": "rate", "expected": parameters["rate_percent"], "tolerance": 0},
        {"statistic": "exemption_limit[single]", "expected": single, "tolerance": 0},
        {"statistic": "exemption_limit[joint]", "expected": joint, "tolerance": 0},
    ]
    return rule_entry(
        "de-solidarity-surcharge-2026",
        "Germany solidarity surcharge on income tax from 2026: rate, exemption limits and phase-in zone (SolZG 1995)",
        "tax", "DE", "de_solidarity_surcharge", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "surcharge", "statute", "formula"],
        "The Solidaritätszuschlag on assessed income tax: a percentage of the income tax base, levied only when the base exceeds the exemption limit "
        "(Freigrenze), which applies at the joint figure for spouses assessed under § 32a(5) and (6) EStG; above the limit the surcharge is capped at the "
        "phase-in percentage of the excess over the limit, and fractions of a cent are dropped. SolZG § 6(27) applies the § 3(3) limits from the 2026 "
        "assessment period. The rule takes the income tax base as input; the base for wage tax withholding uses the monthly, weekly and daily fractions "
        "of the limits in § 3(4) and is not modelled. Tax on capital income under § 32d(3) and (4) EStG is surcharged at the full rate regardless of the "
        "limit and is outside this rule. Vectors other than the two limits are computed from the statutory formula. " + GII_LICENSE_NOTE,
        ("2026-01-01", None),
    )


def de_child_allowances(estg: GiiLaw, stefeg: Source) -> dict:
    s66 = estg.section("§ 66")
    s32 = estg.section("§ 32")
    kindergeld = match(r"Das Kindergeld beträgt monatlich für jedes Kind (\d+) Euro", s66, "§ 66(1)")
    freibetrag = match(r"ein Freibetrag von (\d[\d ]*) Euro für das sächliche Existenzminimum des Kindes \(Kinderfreibetrag\) sowie ein Freibetrag von (\d[\d ]*) Euro für den Betreuungs- und Erziehungs- oder Ausbildungsbedarf", s32, "§ 32(6)")
    rows = {
        "kindergeld_monthly": {"amount": de(kindergeld.group(1)), "period": "month", "per": "child", "legal_basis": "EStG § 66 Absatz 1"},
        "kinderfreibetrag": {"amount": de(freibetrag.group(1)), "period": "year", "per": "child and parent", "legal_basis": "EStG § 32 Absatz 6 Satz 1"},
        "betreuungsfreibetrag": {"amount": de(freibetrag.group(2)), "period": "year", "per": "child and parent", "legal_basis": "EStG § 32 Absatz 6 Satz 1"},
    }
    vectors = [
        vector({"key": "kindergeld_monthly", "column": "amount"}, rows["kindergeld_monthly"]["amount"], "source"),
        vector({"key": "kinderfreibetrag", "column": "amount"}, rows["kinderfreibetrag"]["amount"], "source"),
        vector({"key": "betreuungsfreibetrag", "column": "amount"}, rows["betreuungsfreibetrag"]["amount"], "source"),
        vector("elterngeld", False, "derived", "not part of this table"),
    ]
    items = [
        estg.cite("EStG § 66 Absatz 1", kindergeld.group(1), kindergeld.group(0)),
        estg.cite("EStG § 32 Absatz 6 Satz 1", freibetrag.group(1), f"ein Freibetrag von {freibetrag.group(1)} Euro für das sächliche Existenzminimum des Kindes (Kinderfreibetrag)"),
        estg.cite("EStG § 32 Absatz 6 Satz 1", freibetrag.group(2), f"ein Freibetrag von {freibetrag.group(2)} Euro für den Betreuungs- und Erziehungs- oder Ausbildungsbedarf des Kindes"),
        estg.cite("EStG § 32 Absatz 6 Satz 2", "verdoppeln sich die Beträge nach Satz 1", "verdoppeln sich die Beträge nach Satz 1, wenn das Kind zu beiden Ehegatten in einem Kindschaftsverhältnis steht", role="supporting"),
        stefeg.cite("Artikel 2 Nummer 1 and Nummer 4 (amendments in force on 1 January 2026)", f"„{freibetrag.group(1)} Euro“", f"In § 32 Absatz 6 Satz 1 wird die Angabe „3 336 Euro“ durch die Angabe „{freibetrag.group(1)} Euro“ ersetzt.", role="supporting"),
        stefeg.cite("Artikel 2 Nummer 4 Buchstabe a", f"„{kindergeld.group(1)} Euro“", f"In Absatz 1 wird die Angabe „255 Euro“ durch die Angabe „{kindergeld.group(1)} Euro“ ersetzt.", role="supporting"),
        stefeg.cite("Artikel 10 Absatz 2 (Inkrafttreten)", "Die Artikel 2, 4 und 6 treten am 1. Januar 2026 in Kraft.", "Die Artikel 2, 4 und 6 treten am 1. Januar 2026 in Kraft.", role="supporting"),
    ]
    tests = [
        {"statistic": "count", "expected": 3, "tolerance": 0},
        {"statistic": "value[kindergeld_monthly, amount]", "expected": rows["kindergeld_monthly"]["amount"], "tolerance": 0},
    ]
    return rule_entry(
        "de-child-benefit-and-child-allowances-2026",
        "Germany child benefit (Kindergeld) and child tax allowances from 1 January 2026 (EStG § 66 and § 32(6))",
        "tax", "DE", "lookup_table", {"currency": "EUR", "rows": rows}, vectors, items, tests,
        ["payroll", "tax", "child-benefit", "allowance", "statute", "reference-table"],
        "Monthly Kindergeld per child (EStG § 66(1)) and the two annual child allowances deducted in the income tax assessment: the Kinderfreibetrag for the "
        "child's material subsistence minimum and the allowance for care, upbringing or education (Betreuungs- und Erziehungs- oder Ausbildungsbedarf), both "
        "per parent; § 32(6) sentence 2 doubles them for spouses assessed jointly when the child is the child of both. In the assessment the tax office "
        "compares the tax saving from the allowances with the Kindergeld received (Günstigerprüfung, § 31) and the rule does not model that comparison. "
        "The Kindergeld and Kinderfreibetrag figures were set by Article 2 of the Steuerfortentwicklungsgesetz, which entered into force on 1 January 2026; "
        "the care allowance is the figure in the consolidated text and was already in force on that date. " + GII_LICENSE_NOTE,
        ("2026-01-01", None),
    )


def de_minimum_wage(milog: GiiLaw, milov4: GiiLaw, milov5: GiiLaw) -> dict:
    base = match(r"Die Höhe des Mindestlohns beträgt ab dem 1\. Oktober 2022 brutto (\d+) Euro je Zeitstunde", milog.section("§ 1"), "MiLoG § 1(2)")
    v4 = re.findall(r"ab 1\. Januar (\d{4}) (\d+,\d+) Euro brutto je Zeitstunde", milov4.section("§ 1"))
    v5 = re.findall(r"ab 1\. Januar (\d{4}) (\d+,\d+) Euro brutto je Zeitstunde", milov5.section("§ 1"))
    if len(v4) != 2 or len(v5) != 2:
        raise ValueError("minimum wage ordinances: expected two steps each")
    steps = [{"from": "2022-10-01", "value": de(base.group(1))}] + [{"from": f"{year}-01-01", "value": de(amount)} for year, amount in v4 + v5]
    vectors = [vector({"on": s["from"]}, s["value"], "source") for s in steps]
    vectors.append(vector({"on": "2026-06-30"}, steps[3]["value"], "derived", "mid-2026 falls in the step that began on 1 January 2026"))
    items = [milog.cite("MiLoG § 1 Absatz 2 Satz 1", base.group(1), base.group(0))]
    for law, pairs, name in ((milov4, v4, "MiLoV4"), (milov5, v5, "MiLoV5")):
        for year, amount in pairs:
            items.append(law.cite(f"{name} § 1, step from 1 January {year}", amount, f"{amount} Euro brutto je Zeitstunde"))
    tests = [
        {"statistic": "count", "expected": len(steps), "tolerance": 0},
        {"statistic": "value[2026-01-01]", "expected": steps[3]["value"], "tolerance": 0},
        {"statistic": "max", "expected": steps[-1]["value"], "tolerance": 0},
    ]
    return rule_entry(
        "de-statutory-minimum-wage-2022-2027",
        "Germany statutory gross hourly minimum wage from October 2022 to January 2027 (MiLoG and the Fourth and Fifth adjustment ordinances)",
        "employment", "DE", "step_schedule", {"currency": "EUR", "unit": "gross per hour", "steps": steps}, vectors, items, tests,
        ["payroll", "employment", "minimum-wage", "statute", "step-schedule"],
        "The general statutory minimum wage in euro per hour, gross, by the date each level took effect: the amount fixed in MiLoG § 1(2) from 1 October 2022, "
        "the two steps of the Fourth Minimum Wage Adjustment Ordinance (MiLoV4) and the two steps of the Fifth (MiLoV5, BGBl. 2025 I Nr. 268), the last of which "
        "takes effect on 1 January 2027. Sector minimum wages under the Posted Workers Act take precedence where higher and are not included; MiLoG § 22 "
        "exempts some groups, such as minors without vocational training, from the minimum wage. " + GII_LICENSE_NOTE,
        (steps[0]["from"], None),
    )


def de_minijob_limit(sgb4: GiiLaw, guidelines: Source) -> dict:
    s8 = sgb4.section("§ 8")
    s20 = sgb4.section("§ 20")
    formula = match(r"Sie wird berechnet, indem der Mindestlohn mit (\d+) vervielfacht, durch (\w+) geteilt und auf volle Euro aufgerundet wird", s8, "SGB IV § 8(1a)")
    upper = match(r"die regelmäßig (\d[\d ]*) Euro im Monat nicht übersteigen", s20, "SGB IV § 20(2)")
    announced = match(r"Anhebung der Geringfügigkeitsgrenze ab 1\. Januar 2026 auf (\d+) Euro sowie ab 1\. Januar 2027 auf (\d+) Euro", guidelines.text, "guidelines 2026 increase")
    history = re.findall(r"((\d\d)\.(\d\d)\.(\d\d) – \d\d\.\d\d\.\d\d) (\d+) €", guidelines.text)
    if not history:
        raise ValueError("guidelines: contribution table by period not found")
    steps: list[dict] = []
    for _, dd, mm, yy, amount in history:
        if not steps or steps[-1]["value"] != int(amount):
            steps.append({"from": f"20{yy}-{mm}-{dd}", "value": int(amount)})
    steps += [{"from": "2026-01-01", "value": int(announced.group(1))}, {"from": "2027-01-01", "value": int(announced.group(2))}]
    vectors = [vector({"on": s["from"]}, s["value"], "source") for s in steps]
    vectors.append(vector({"on": "2023-07-01"}, next(s["value"] for s in steps if s["from"] == "2022-10-01"), "derived", "the limit set from October 2022 stayed in force through 2023"))
    items = [
        sgb4.cite("SGB IV § 8 Absatz 1a Satz 2", formula.group(1), formula.group(0)),
        sgb4.cite("SGB IV § 20 Absatz 2", upper.group(1), f"die regelmäßig {upper.group(1)} Euro im Monat nicht übersteigen"),
        guidelines.cite("Geringfügigkeits-Richtlinien 2026, page 3, summary of changes", announced.group(1), announced.group(0)),
    ]
    items += [guidelines.cite("Geringfügigkeits-Richtlinien 2026, Anlage, contribution table by period", amount, f"{period} {amount} €") for period, _, _, _, amount in history]
    tests = [
        {"statistic": "count", "expected": len(steps), "tolerance": 0},
        {"statistic": "value[2026-03-01]", "expected": int(announced.group(1)), "tolerance": 0},
    ]
    assumed = [{
        "parameter": "steps",
        "value": "each limit equals the hourly minimum wage in force times 130, divided by 3 and rounded up (SGB IV § 8(1a))",
        "method": "derived",
        "rationale": "The guidelines state the 2026 and 2027 limits and Anlage 1 tabulates the earlier ones; a period whose limit repeats the previous one is merged into it. "
                     "From 1 October 2022 the formula in SGB IV § 8(1a) applied to the minimum wage steps in de-statutory-minimum-wage-2022-2027 reproduces each limit, "
                     "which a reviewer can use as a cross-check.",
    }]
    return rule_entry(
        "de-minijob-earnings-limit-2003-2027",
        "Germany marginal employment (Minijob) monthly earnings limit from 2003 to January 2027, with the Midijob transition zone ceiling",
        "employment", "DE", "step_schedule",
        {"currency": "EUR", "unit": "gross per month", "steps": steps, "transition_zone_upper_limit": de(upper.group(1)),
         "formula": f"hourly minimum wage x {formula.group(1)} / 3, rounded up to full euros"},
        vectors, items, tests,
        ["payroll", "employment", "minijob", "social-insurance", "minimum-wage", "step-schedule"],
        "The Geringfügigkeitsgrenze, the monthly earnings limit for a marginal employment (Minijob) under SGB IV § 8(1a): the pay for ten hours a week at the "
        "statutory minimum wage, computed as the hourly minimum wage times 130, divided by three and rounded up to full euros, and announced by the Federal "
        "Ministry of Labour in the Bundesanzeiger. The steps come from the 2026 marginal employment guidelines of the social insurance central bodies, "
        "published by the Minijob-Zentrale, which state the limits from 1 January 2026 and 1 January 2027 and tabulate the earlier ones in Anlage 1 "
        "(the first period of that table, ending 31 March 2003, has no start date and is left out). Earnings above the "
        "limit and up to the transition zone ceiling in SGB IV § 20(2), kept under transition_zone_upper_limit, fall in the Übergangsbereich (Midijob), where "
        "employee contributions are computed on a reduced base. Gesetze im Internet and the guidelines carry no licence statement, so the licence is recorded "
        "as unstated and the entry stays at license-review.",
        (steps[0]["from"], None), tier="B", assumed=assumed,
    )


def de_earnings_ceilings(svbezgrv: GiiLaw) -> dict:
    s1, s2, s3, s4 = (svbezgrv.section(f"§ {n}") for n in (1, 2, 3, 4))
    bezug = match(r"für das Jahr 2026 beträgt (\d[\d ]*) Euro\. Umgerechnet auf den Monat ergeben sich (\d[\d ]*) Euro", s1, "§ 1")
    jaeg = match(r"§ 6 Absatz 6 des Fünften Buches Sozialgesetzbuch wird für das Jahr 2026 auf (\d[\d ]*) Euro festgesetzt\. Umgerechnet auf den Monat ergeben sich (\d[\d ]*) Euro", s2, "§ 2(1)")
    jaeg7 = match(r"§ 6 Absatz 7 des Fünften Buches Sozialgesetzbuch wird für das Jahr 2026 auf (\d[\d ]*) Euro festgesetzt\. Umgerechnet auf den Monat ergeben sich (\d[\d ]*,\d+) Euro", s2, "§ 2(2)")
    avg = match(r"für das Jahr 2026 beträgt (\d[\d ]*) Euro", s3, "§ 3(2)")
    general = match(r"in der allgemeinen Rentenversicherung auf (\d[\d ]*) Euro jährlich; umgerechnet auf den Monat ergeben sich (\d[\d ]*) Euro", s4, "§ 4(1) Nr. 1")
    miners = match(r"in der knappschaftlichen Rentenversicherung auf (\d[\d ]*) Euro jährlich; umgerechnet auf den Monat ergeben sich (\d[\d ]*) Euro", s4, "§ 4(1) Nr. 2")
    rows = {
        "bezugsgroesse": {"annual": de(bezug.group(1)), "monthly": de(bezug.group(2)), "legal_basis": "SVBezGrV 2026 § 1 (SGB IV § 18)"},
        "jahresarbeitsentgeltgrenze": {"annual": de(jaeg.group(1)), "monthly": de(jaeg.group(2)), "legal_basis": "SVBezGrV 2026 § 2(1) (SGB V § 6(6))"},
        "jahresarbeitsentgeltgrenze_bestandsfaelle": {"annual": de(jaeg7.group(1)), "monthly": de(jaeg7.group(2)), "legal_basis": "SVBezGrV 2026 § 2(2) (SGB V § 6(7))"},
        "beitragsbemessungsgrenze_rv_allgemein": {"annual": de(general.group(1)), "monthly": de(general.group(2)), "legal_basis": "SVBezGrV 2026 § 4(1) Nr. 1 (SGB VI § 159)"},
        "beitragsbemessungsgrenze_rv_knappschaft": {"annual": de(miners.group(1)), "monthly": de(miners.group(2)), "legal_basis": "SVBezGrV 2026 § 4(1) Nr. 2 (SGB VI § 159)"},
        "vorlaeufiges_durchschnittsentgelt_rv": {"annual": de(avg.group(1)), "monthly": None, "legal_basis": "SVBezGrV 2026 § 3(2) (SGB VI § 69(2))"},
    }
    vectors = [
        vector({"key": "beitragsbemessungsgrenze_rv_allgemein", "column": "monthly"}, rows["beitragsbemessungsgrenze_rv_allgemein"]["monthly"], "source"),
        vector({"key": "jahresarbeitsentgeltgrenze", "column": "annual"}, rows["jahresarbeitsentgeltgrenze"]["annual"], "source"),
        vector({"key": "bezugsgroesse", "column": "monthly"}, rows["bezugsgroesse"]["monthly"], "source"),
        vector({"key": "jahresarbeitsentgeltgrenze_bestandsfaelle", "column": "monthly"}, rows["jahresarbeitsentgeltgrenze_bestandsfaelle"]["monthly"], "source"),
        vector("beitragsbemessungsgrenze_kv", False, "derived", "the health insurance ceiling is not fixed by this ordinance for 2026"),
    ]
    items = [
        svbezgrv.cite("SVBezGrV 2026 § 1", bezug.group(1), f"für das Jahr 2026 beträgt {bezug.group(1)} Euro. Umgerechnet auf den Monat ergeben sich {bezug.group(2)} Euro."),
        svbezgrv.cite("SVBezGrV 2026 § 2 Absatz 1", jaeg.group(1), f"wird für das Jahr 2026 auf {jaeg.group(1)} Euro festgesetzt. Umgerechnet auf den Monat ergeben sich {jaeg.group(2)} Euro."),
        svbezgrv.cite("SVBezGrV 2026 § 2 Absatz 2", jaeg7.group(1), f"wird für das Jahr 2026 auf {jaeg7.group(1)} Euro festgesetzt. Umgerechnet auf den Monat ergeben sich {jaeg7.group(2)} Euro."),
        svbezgrv.cite("SVBezGrV 2026 § 3 Absatz 2", avg.group(1), f"Sechsten Buches Sozialgesetzbuch für das Jahr 2026 beträgt {avg.group(1)} Euro."),
        svbezgrv.cite("SVBezGrV 2026 § 4 Absatz 1 Nummer 1", general.group(1), general.group(0)),
        svbezgrv.cite("SVBezGrV 2026 § 4 Absatz 1 Nummer 2", miners.group(1), miners.group(0)),
        svbezgrv.cite("SVBezGrV 2026 § 5", "Diese Verordnung tritt am 1. Januar 2026 in Kraft.", "Diese Verordnung tritt am 1. Januar 2026 in Kraft."),
    ]
    tests = [
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
        {"statistic": "value[beitragsbemessungsgrenze_rv_allgemein, annual]", "expected": rows["beitragsbemessungsgrenze_rv_allgemein"]["annual"], "tolerance": 0},
    ]
    return rule_entry(
        "de-social-insurance-reference-values-2026",
        "Germany social insurance reference values for 2026: pension contribution ceilings, health insurance thresholds and reference amount",
        "tax", "DE", "lookup_table", {"currency": "EUR", "year": 2026, "rows": rows}, vectors, items, tests,
        ["payroll", "social-insurance", "social-contributions", "contribution-ceiling", "statute", "reference-table"],
        "The Sozialversicherungsrechengrößen-Verordnung 2026 (BGBl. 2025 I Nr. 278): the reference amount (Bezugsgröße) of SGB IV § 18, the compulsory health "
        "insurance thresholds of SGB V § 6(6) and, for employees already privately insured at the end of 2002, § 6(7), the provisional average earnings in the "
        "pension insurance for 2026, and the pension and unemployment insurance contribution ceilings for the general and miners' pension insurance, each as an "
        "annual amount and the monthly amount the ordinance states. Earnings above a ceiling carry no contributions. The ordinance has applied a single nationwide "
        "set of values since the east-west split ended, and the health and long-term care contribution ceiling for 2026 is not among the values it fixes; SGB V § "
        "223 as now consolidated only states the 2027 ceiling. " + GII_LICENSE_NOTE,
        ("2026-01-01", "2026-12-31"),
    )


# ---------------------------------------------------------------- Austria


def at_income_tax() -> dict:
    jan = Source("https://ogd.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40274868/NOR40274868.xml", "Bundeskanzleramt (RIS, Bundesrecht konsolidiert)",
                 "Einkommensteuergesetz 1988 § 33, version in force from 1 January 2026 (XML)")
    jul = Source("https://ogd.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40279893/NOR40279893.xml", "Bundeskanzleramt (RIS, Bundesrecht konsolidiert)",
                 "Einkommensteuergesetz 1988 § 33, version in force from 30 July 2026 (XML)")
    text = plain(jan.raw.decode("utf-8"))
    first = match(r"für die ersten (\d[\d ]*) Euro (\d+)%", text, "§ 33(1) first slice")
    slices = re.findall(r"für Einkommensteile über (\d[\d ]*) Euro bis (\d[\d ]*) Euro (\d+)%", text)
    top = match(r"für Einkommensteile über (\d[\d ]*) Euro (\d+)% Für Einkommensteile über eine Million Euro beträgt der Steuersatz in den Kalenderjahren 2016 bis 2029 (\d+)%", text, "§ 33(1) top")
    later = re.findall(r"für Einkommensteile über (\d[\d ]*) Euro \(Anm\. \d+\) bis (\d[\d ]*) Euro \(Anm\. \d+\) (\d+)%", plain(jul.raw.decode("utf-8")))
    if not slices or [s[:3] for s in later] != slices:
        raise ValueError("§ 33(1): the July 2026 version does not repeat the January 2026 brackets")
    bands = [{"name": "0%", "up_to": de(first.group(1)), "rate_percent": int(first.group(2))}]
    bands += [{"name": f"{rate}%", "up_to": de(upper), "rate_percent": int(rate)} for _, upper, rate in slices]
    bands += [{"name": f"{top.group(2)}%", "up_to": 1000000, "rate_percent": int(top.group(2))}, {"name": f"{top.group(3)}%", "up_to": None, "rate_percent": int(top.group(3))}]
    parameters = {"tax_year": 2026, "currency": "EUR", "personal_allowance": 0, "bands": bands}

    def tax(income: int) -> str:
        return str(income_tax_bands.tax_due(parameters, income))

    vectors = [
        vector({"income": bands[0]["up_to"]}, "0.00", "source", "§ 33(1): no tax on the first slice"),
        vector({"income": 30000}, tax(30000), "derived"),
        vector({"income": 60000}, tax(60000), "derived"),
        vector({"income": 104859}, tax(104859), "derived", "top of the 48 percent slice"),
        vector({"income": 1500000}, tax(1500000), "derived", "55 percent on the part above one million euros"),
    ]
    items = [jan.cite("§ 33 Absatz 1, first row", first.group(1), f"für die ersten {first.group(1)} Euro")]
    for lower, upper, rate in slices:
        items.append(jan.cite(f"§ 33 Absatz 1, slice at {rate}%", upper, f"für Einkommensteile über {lower} Euro bis {upper} Euro"))
    items += [
        jan.cite("§ 33 Absatz 1, top slice and million-euro rate", top.group(3), "Für Einkommensteile über eine Million Euro beträgt der Steuersatz in den Kalenderjahren 2016 bis 2029 55%."),
        jan.cite("Document metadata, Inkrafttretensdatum", "01.01.2026", '<absatz typ="erltext" ct="ikra" halign="j">01.01.2026</absatz>'),
        jul.cite("Document metadata of the following version, Außerkrafttretensdatum", "31.12.2026", '<absatz typ="erltext" ct="akra" halign="j">31.12.2026</absatz>', role="supporting"),
        jul.cite("§ 33 Absatz 1 with notes on the 2027 amounts", "für 2027: 13 846 Euro", "Anm. 2: gemäß BGBl. II Nr. 260/2026 für 2027: 13 846 Euro", role="supporting"),
    ]
    tests = [
        {"statistic": "count", "expected": len(bands), "tolerance": 0},
        {"statistic": "rate[50%]", "expected": 50, "tolerance": 0},
    ]
    return rule_entry(
        "at-income-tax-brackets-2026",
        "Austria income tax brackets for 2026 under § 33(1) EStG 1988, including the 55 percent rate above one million euros",
        "tax", "AT", "income_tax_bands", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "statute", "tax-bands"],
        "The Austrian income tax scale for the 2026 calendar year as § 33(1) EStG 1988 states it in the RIS consolidated text: income slices taxed at 0, 20, 30, "
        "40, 48 and 50 percent and, for the part of income above one million euros, 55 percent for the calendar years 2016 to 2029. The version in force from "
        "1 January 2026 and the version in force from 30 July 2026 to 31 December 2026 carry the same brackets; the later one adds notes with the inflation-adjusted "
        "amounts for 2027 (BGBl. II Nr. 260/2026). The rule applies the slices to taxable income; deductible credits (Absetzbeträge such as the "
        "Verkehrsabsetzbetrag and Familienbonus Plus) are deducted from the result under § 33(2) and are not modelled, and the sixth-part taxation of "
        "13th and 14th salaries under § 67 is outside this rule. Vectors other than the nil slice are computed from the brackets. RIS documents carry no "
        "licence statement in the fetched XML, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"),
    )


# ---------------------------------------------------------------- Netherlands


def nl_box1() -> dict:
    law = Source("https://repository.officiele-overheidspublicaties.nl/bwb/BWBR0011353/2026-01-01_1/xml/BWBR0011353_2026-01-01_1.xml",
                 "Overheid.nl (Basiswettenbestand)", "Wet inkomstenbelasting 2001, version valid from 1 January 2026 (BWB XML)")
    article = match(r'<artikel[^>]*label="Artikel 2\.10".*?</artikel>', law.raw.decode("utf-8"), "artikel 2.10", re.DOTALL).group(0)
    if 'inwerking="2026-01-01"' not in article:
        raise ValueError("artikel 2.10 is not the version in force from 1 January 2026")
    cells = [plain(c) for c in re.findall(r"<entry[^>]*>(.*?)</entry>", re.search(r"<tbody.*?</tbody>", article, re.DOTALL).group(0), re.DOTALL)]
    rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
    brackets = []
    for index, (over, _upper, base, rate) in enumerate(rows):
        brackets.append({
            "name": f"schijf {index + 1}",
            "over": 0 if over == "-" else de(over),
            "base_tax": 0 if base in ("-", "–") else de(base),
            "rate_percent": de(rate.rstrip("%")),
        })
    parameters = {"tax_year": 2026, "currency": "EUR", "brackets": brackets, "scope": "box 1 tax for taxpayers born on or after 1 January 1946, excluding national insurance contributions"}

    def tax(income: float) -> str:
        return str(cumulative_bracket_tariff.tax_due(parameters, income))

    vectors = [
        vector({"marginal_rate_for": 30000}, brackets[0]["rate_percent"], "source"),
        vector({"marginal_rate_for": 50000}, brackets[1]["rate_percent"], "source"),
        vector({"marginal_rate_for": 100000}, brackets[2]["rate_percent"], "source"),
        vector({"income": brackets[1]["over"]}, tax(brackets[1]["over"]), "derived", "top of the first bracket"),
        vector({"income": 60000}, tax(60000), "derived"),
        vector({"income": brackets[2]["over"] + 10000}, tax(brackets[2]["over"] + 10000), "derived", "column III amount plus the top rate on 10 000 of excess"),
    ]
    items = [
        law.cite("Artikel 2.10 lid 1, tabel, rij 1 (kolom II)", rows[0][1], "Bij een belastbaar inkomen uit werk en woning van meer dan"),
        law.cite("Artikel 2.10 lid 1, tabel, kolom IV", rows[0][3], "maar niet meer dan"),
        law.cite("Artikel 2.10 lid 1, tabel, rij 2 (kolom III)", rows[1][2], "het in kolom III vermelde bedrag, vermeerderd met het bedrag dat wordt berekend door het in kolom IV vermelde percentage"),
        law.cite("Artikel 2.10 lid 1, tabel, rij 2 en 3 (kolom IV)", rows[1][3], "Tarief belastbaar inkomen uit werk en woning"),
        law.cite("Artikel 2.10 lid 1, tabel, rij 3 (kolom III)", rows[2][2], 'label="Artikel 2.10"'),
        law.cite("Artikel 2.10 lid 1, tabel, rij 3 (kolom IV)", rows[2][3], 'inwerking="2026-01-01" label="Artikel 2.10"'),
    ]
    tests = [
        {"statistic": "count", "expected": len(brackets), "tolerance": 0},
        {"statistic": "rate[schijf 3]", "expected": brackets[2]["rate_percent"], "tolerance": 0},
    ]
    return rule_entry(
        "nl-box1-income-tax-brackets-2026",
        "Netherlands box 1 income tax brackets for 2026 (Wet inkomstenbelasting 2001, article 2.10), excluding national insurance contributions",
        "tax", "NL", "cumulative_bracket_tariff", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "statute", "tax-bands"],
        "The tax on taxable income from work and home (box 1) under article 2.10 of the Wet inkomstenbelasting 2001 in the version in force from 1 January 2026 "
        "(Staatscourant 2025, 40487): for each row, the tax is the column III amount plus the column IV percentage of the income above the column I amount. "
        "Article 2.10 sets the tax only: national insurance contributions (premie volksverzekeringen) are levied on the first bracket under separate "
        "legislation and are not included, and taxpayers born before 1 January 1946 use article 2.10a. Article 2.10(2) adds a further charge on certain "
        "deductions in the top bracket, and the general tax credit and labour tax credit (articles 8.10 and 8.11) are deducted from tax and premiums "
        "together; neither is modelled. The column III amounts are whole euros, so the tax just below a bracket limit can exceed the column III amount of the next row by a few cents; the rule follows the table row that applies. The source vectors restate the column IV rates; the others are computed from the table. "
        "Dutch statutes carry no copyright under the Auteurswet, but the BWB XML carries no licence statement, so the licence is recorded as unstated and the "
        "entry stays at license-review.",
        ("2026-01-01", "2026-12-31"),
    )


def nl_minimum_wage() -> dict:
    regs = {
        "2026-01-01": Source("https://repository.overheid.nl/frbr/officielepublicaties/stcrt/2025/stcrt-2025-34131/1/xml/stcrt-2025-34131.xml",
                             "Staatscourant (Ministerie van Sociale Zaken en Werkgelegenheid)", "Staatscourant 2025, 34131: minimum wage from 1 January 2026 (XML)"),
        "2026-07-01": Source("https://repository.overheid.nl/frbr/officielepublicaties/stcrt/2026/stcrt-2026-16505/1/xml/stcrt-2026-16505.xml",
                             "Staatscourant (Ministerie van Sociale Zaken en Werkgelegenheid)", "Staatscourant 2026, 16505: minimum wage from 1 July 2026 (XML)"),
    }
    bands = [{"name": "21 and over", "min_age": 21}] + [{"name": f"{age}", "min_age": age, "max_age": age} for age in (20, 19, 18, 17, 16, 15)]
    tables, items, shares = [], [], {}
    for start, source in regs.items():
        markup = source.raw.decode("utf-8")
        tables_markup = re.findall(r"<tbody.*?</tbody>", markup, re.DOTALL)
        if len(tables_markup) < 2:
            raise ValueError(f"{source.url}: expected the general and bbl youth wage tables")
        rates: dict[str, float] = {}
        for markup_table, prefix in ((tables_markup[0], ""), (tables_markup[1], "bbl ")):
            cells = [plain(c) for c in re.findall(r"<entry[^>]*>(.*?)</entry>", markup_table, re.DOTALL)]
            for age_label, share, hourly in (cells[i:i + 3] for i in range(0, len(cells), 3)):
                band = "21 and over" if age_label == "21 jaar en ouder" else age_label.replace(" jaar", "")
                rates[prefix + band] = de(hourly)
                shares[prefix + band] = de(share.rstrip("%"))
                items.append(source.cite(f"Toelichting, {'bbl ' if prefix else ''}minimumjeugdloon table, row {age_label}", hourly, age_label))
        statutory = match(r"worden met ingang van (\d+ \w+ 2026) onderscheidenlijk als volgt vastgesteld: a\. (€ \d+,\d+); b\. (€ [\d.]+,\d+)\.", plain(markup), "artikel 1")
        if de(statutory.group(2)) != rates["21 and over"]:
            raise ValueError("artikel 1 hourly amount differs from the table")
        items.append(source.cite("Artikel 1 (onderdeel a, minimum hourly wage; onderdeel b, reference monthly wage)", statutory.group(2), f"met ingang van {statutory.group(1)} onderscheidenlijk als volgt vastgesteld:"))
        tables.append({"from": start, "rates": rates, "reference_monthly_wage": de(statutory.group(3))})
    parameters = {"currency": "EUR", "unit": "gross per hour", "bands": bands, "categories": [f"bbl {age}" for age in (20, 19, 18)], "youth_percentages": shares, "tables": tables}
    jan, jul = tables
    vectors = [
        vector({"age": 30, "on": "2026-01-01"}, jan["rates"]["21 and over"], "source"),
        vector({"age": 20, "on": "2026-03-15"}, jan["rates"]["20"], "source"),
        vector({"age": 15, "on": "2026-03-15"}, jan["rates"]["15"], "source"),
        vector({"age": 40, "on": "2026-07-01"}, jul["rates"]["21 and over"], "source"),
        vector({"age": 18, "on": "2026-09-01"}, jul["rates"]["18"], "source"),
        vector({"age": 19, "on": "2026-09-01", "category": "bbl 19"}, jul["rates"]["bbl 19"], "source", "beroepsbegeleidende leerweg rate for a 19-year-old"),
        vector({"age": 21, "on": "2026-06-30"}, jan["rates"]["21 and over"], "derived", "the July table is not yet in force"),
    ]
    tests = [
        {"statistic": "count", "expected": 2, "tolerance": 0},
        {"statistic": "rate[21 and over, 2026-07-01]", "expected": jul["rates"]["21 and over"], "tolerance": 0},
    ]
    return rule_entry(
        "nl-statutory-minimum-wage-by-age-2026",
        "Netherlands statutory gross hourly minimum wage and youth minimum wages by age from 1 January and 1 July 2026",
        "employment", "NL", "age_band_rates", parameters, vectors, items, tests,
        ["payroll", "employment", "minimum-wage", "youth-wage", "age-bands"],
        "The Dutch statutory minimum hourly wage for employees aged 21 and over and the corresponding youth minimum wages for ages 15 to 20, from the two "
        "indexation regulations of the Minister of Social Affairs and Employment published in the Staatscourant: the hourly amount fixed in article 1 under "
        "article 8(1)(a) of the Wet minimumloon en minimumvakantiebijslag, and the youth wage tables in the explanatory notes, which apply the percentages of "
        "the Besluit minimumjeugdloon (kept under youth_percentages). Employees aged 18 to 20 on a beroepsbegeleidende leerweg (bbl) contract have their own "
        "rates, selected with the categories bbl 20, bbl 19 and bbl 18. reference_monthly_wage is the article 8(1)(b) monthly amount, which since 2024 no "
        "longer sets anyone's minimum pay but indexes benefits. The holiday allowance of at least 8 percent is on top. The Staatscourant XML carries no "
        "licence statement, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", None),
    )


# ---------------------------------------------------------------- Ireland


def ie_sources() -> dict[str, Source]:
    return {
        "fa": Source("https://www.irishstatutebook.ie/eli/2025/act/18/enacted/en/xml", "Office of the Attorney General (Irish Statute Book)", "Finance Act 2025 (No. 18 of 2025), XML"),
        "dof": Source("https://assets.gov.ie/static/documents/beb5bc84/Budget_2026_Tax_Policy_Changes_Book_041125.pdf", "Department of Finance (Ireland)", "Budget 2026 Tax Policy Changes (PDF)"),
        "part2": Source("https://www.revenue.ie/en/tax-professionals/documents/notes-for-guidance/tca/part02.pdf", "Revenue Commissioners", "Notes for Guidance, Taxes Consolidation Act 1997, Finance Act 2025 edition, Part 2 (PDF)"),
        "part15": Source("https://www.revenue.ie/en/tax-professionals/documents/notes-for-guidance/tca/part15.pdf", "Revenue Commissioners", "Notes for Guidance, Taxes Consolidation Act 1997, Finance Act 2025 edition, Part 15 (PDF)"),
    }


def dof_single_row(dof: Source, income: str) -> list[str]:
    """Table 2 row for a gross income: income, min wage increase, proposed income, then existing and proposed tax, PRSI and USC."""
    found = match(rf"\b{re.escape(income)} (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) (\d[\d,]*) -?\d", dof.text, f"Table 2 row {income}")
    return [income] + list(found.groups())


def ie_number(text: str) -> int | float:
    return number(text, ",", ".")


def ie_income_tax(src: dict[str, Source]) -> dict:
    part2, part15, dof = src["part2"], src["part15"], src["dof"]
    single = match(r"Single persons, etc\. €(\d[\d,]*) 20% standard rate Balance 40% higher rate", part2.text, "Part 2 single")
    carer = match(r"Single person child carer €(\d[\d,]*) 20% standard rate", part2.text, "Part 2 carer")
    married = match(r"Married couples/Civil Partners €(\d[\d,]*) 20% standard rate", part2.text, "Part 2 married")
    increase = match(r"can get an increase of up to €(\d[\d,]*) giving them a combined standard rate band of €(\d[\d,]*)", part2.text, "Part 2 increase")
    personal = match(r"the basic personal tax credit is €(\d[\d,]*)\. In all other cases the basic personal tax credit is €(\d[\d,]*)\.", part15.text, "section 461")
    employee = match(r"The amount of the tax credit in 2025 is €(\d[\d,]*) or (\d+) per cent of the emoluments, whichever is the lesser", part15.text, "section 472")
    parameters = {
        "charge": "income_tax",
        "tax_year": 2026,
        "currency": "EUR",
        "standard_rate_percent": 20,
        "higher_rate_percent": 40,
        "standard_rate_bands": {"single": ie_number(single.group(1)), "single_child_carer": ie_number(carer.group(1)),
                                "married_one_income": ie_number(married.group(1)), "married_two_incomes": ie_number(married.group(1))},
        "two_income_increase_max": ie_number(increase.group(1)),
        "tax_credits": {"basic_personal_single": ie_number(personal.group(2)), "basic_personal_married": ie_number(personal.group(1)), "employee": ie_number(employee.group(1))},
        "employee_credit_cap_percent": int(employee.group(2)),
    }

    paye = ["basic_personal_single", "employee"]
    rows = {income: dof_single_row(dof, income) for income in ("30,000", "50,000", "100,000", "175,000")}
    vectors = [vector({"income": ie_number(i), "status": "single", "credits": paye, "round": "euro"}, str(ie_number(r[4])), "source",
                      f"Department of Finance Budget 2026, Table 2: single PAYE employee on {i}, income tax proposed for 2026") for i, r in rows.items()]
    vectors += [
        vector({"income": 60000, "status": "married_two_incomes", "second_income": 20000, "credits": ["basic_personal_married", "employee", "employee"]},
               str(ie_income_tax_usc.income_tax(parameters, 60000, "married_two_incomes", ["basic_personal_married", "employee", "employee"], 20000)), "derived",
               "band increased by the lower second income"),
        vector({"income": 8000, "status": "single", "credits": paye}, "0.00", "derived", "credits cannot make the tax negative"),
    ]
    items = [
        part2.cite("Section 15, summary table, Part 1", single.group(1), "Single persons, etc."),
        part2.cite("Section 15, summary table, Part 2", carer.group(1), "Single person child carer"),
        part2.cite("Section 15, summary table, Part 3", married.group(1), "Married couples/Civil Partners"),
        part2.cite("Section 15, note to the summary table", increase.group(1), increase.group(0)),
        part2.cite("Section 15, Details", "20 per cent", "income tax at the standard rate of 20 per cent is chargeable for the year"),
        part2.cite("Cover", "Finance Act 2025 edition", "Notes for Guidance - Taxes Consolidation Act 1997 Finance Act 2025 edition"),
        part15.cite("Section 461, basic personal tax credit", personal.group(2), "In all other cases the basic personal tax credit is"),
        part15.cite("Section 472, employee tax credit", employee.group(1), employee.group(0)),
    ]
    for row in rows.values():
        items.append(dof.cite("page 21, Table 2, single person, PAYE, full rate PRSI", row[4], " ".join(row[:5]), role="supporting"))
    tests = [
        {"statistic": "band[single]", "expected": parameters["standard_rate_bands"]["single"], "tolerance": 0},
        {"statistic": "credit[employee]", "expected": parameters["tax_credits"]["employee"], "tolerance": 0},
    ]
    assumed = [{
        "parameter": "tax_credits.employee",
        "value": parameters["tax_credits"]["employee"],
        "method": "derived",
        "rationale": "Revenue's Part 15 notes (Finance Act 2025 edition) state the employee tax credit for 2025; the Department of Finance Budget 2026 Table 2 income tax "
                     "figures for 2026 equal the band calculation less the basic personal and employee credits at these amounts, which the source vectors reproduce.",
    }]
    return rule_entry(
        "ie-income-tax-rate-bands-and-credits-2026",
        "Ireland income tax for 2026: 20 and 40 percent rates, standard rate bands by circumstance, basic personal and employee tax credits",
        "tax", "IE", "ie_income_tax_usc", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "paye", "tax-credits", "tax-bands"],
        "Irish income tax for the 2026 year of assessment: the standard rate of 20 percent up to the standard rate band for the taxpayer's circumstances (single, "
        "single person child carer, married couple or civil partners with one income, or with two incomes, whose band rises by the lower of the second income and "
        "the maximum increase) and 40 percent on the balance, as Revenue's notes for guidance on section 15 of the Taxes Consolidation Act 1997 (Finance Act 2025 "
        "edition, for 2025 and subsequent years) summarise them; then the basic personal tax credit (section 461) and the employee tax credit (section 472, limited "
        "to 20 percent of employment income) are deducted. Other credits, such as the home carer or earned income credits, are not in the table. Source vectors "
        "are the Department of Finance's Budget 2026 worked figures for a single PAYE employee, which it notes are rounded. Neither publisher states a licence in "
        "these documents, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"), tier="B", assumed=assumed,
    )


def ie_usc(src: dict[str, Source]) -> dict:
    fa, dof = src["fa"], src["dof"]
    section = match(r"Amendment of section 531AN of Principal Act \(rate of charge\) 2\..*?applies for the year of assessment 2026 and each subsequent year of assessment", plain(fa.raw.decode("utf-8")), "section 2")
    slices = re.findall(r"The (first|next) (\d[\d,]*) (\d+(?:\.\d+)?) per cent", section.group(0))
    remainder = match(r"The remainder (\d+) per cent", section.group(0), "remainder")
    bands, upper = [], 0
    for _, amount, rate in slices:
        upper += ie_number(amount)
        bands.append({"up_to": upper, "rate_percent": ie_number(rate)})
    bands.append({"up_to": None, "rate_percent": ie_number(remainder.group(1))})
    parameters = {"charge": "usc", "tax_year": 2026, "currency": "EUR", "bands": bands, "slices_as_enacted": [{"slice": ie_number(a), "rate_percent": ie_number(r)} for _, a, r in slices]}
    rows = {income: dof_single_row(dof, income) for income in ("30,000", "50,000", "100,000", "175,000")}
    vectors = [vector({"income": ie_number(i), "round": "euro"}, str(ie_number(r[8])), "source", f"Department of Finance Budget 2026, Table 2: USC proposed for 2026 on {i}") for i, r in rows.items()]

    vectors.append(vector({"income": bands[1]["up_to"]}, str(ie_income_tax_usc.usc(parameters, bands[1]["up_to"])), "derived", "top of the 2 percent slice"))
    items = [fa.cite("Section 2(1)(c), Part 1 of the Table to section 531AN", amount, "Rate of universal social charge") for _, amount, _ in slices]
    items += [
        fa.cite("Section 2(1)(c), Part 1 of the Table to section 531AN, rates", f"{slices[0][2]} per cent", "Part of aggregate income"),
        fa.cite("Section 2(1)(c), Part 1 of the Table to section 531AN, remainder", f"{remainder.group(1)} per cent", "The remainder"),
        fa.cite("Section 2(2)", "year of assessment 2026", "applies for the year of assessment 2026 and each subsequent year of assessment."),
    ]
    for row in rows.values():
        items.append(dof.cite("page 21, Table 2, single person, PAYE, full rate PRSI", row[8], " ".join(row), role="supporting"))
    tests = [
        {"statistic": "count", "expected": len(bands), "tolerance": 0},
        {"statistic": "rate[3]", "expected": bands[-1]["rate_percent"], "tolerance": 0},
    ]
    assumed = [{
        "parameter": "bands[*].up_to",
        "value": [b["up_to"] for b in bands],
        "method": "derived",
        "rationale": "The Act states each slice as 'the first' or 'the next' amount; the cumulative upper limits are the running sums of those slices.",
    }]
    return rule_entry(
        "ie-universal-social-charge-2026",
        "Ireland Universal Social Charge rates and income slices from 2026 (Finance Act 2025, section 531AN Taxes Consolidation Act 1997)",
        "tax", "IE", "ie_income_tax_usc", parameters, vectors, items, tests,
        ["payroll", "tax", "usc", "social-charge", "statute", "tax-bands"],
        "The standard rates of the Universal Social Charge on aggregate income for 2026 and later years, as section 2 of the Finance Act 2025 substitutes Part 1 of "
        "the Table to section 531AN of the Taxes Consolidation Act 1997: four slices with their rates, which the rule applies in turn (cumulative limits under "
        "bands, the enacted slices under slices_as_enacted). Individuals whose total income is below the exemption threshold in section 531AM pay no USC, reduced "
        "rates apply to medical card holders and people aged 70 or over with lower incomes (section 531AN(3) and (4)), and a surcharge applies to certain "
        "non-PAYE income; none of these is modelled. The source vectors are the Department of Finance's Budget 2026 worked USC figures for a single PAYE "
        "employee, which it notes are rounded. Neither publisher states a licence in these documents, so the licence is recorded as unstated and the entry "
        "stays at license-review.",
        ("2026-01-01", None), assumed=assumed,
    )


def ie_prsi(src: dict[str, Source]) -> dict:
    dof = src["dof"]
    found = match(r"The agreed PRSI increases are included in the analysis \((\d+\.\d+)% will increase to (\d+\.\d+)% from (1 October 2025) and to (\d+\.\d+)% from (1 October 2026)\)", dof.text, "Table 2 note")
    steps = [{"from": "2025-10-01", "value": float(found.group(2))}, {"from": "2026-10-01", "value": float(found.group(4))}]
    vectors = [
        vector({"on": "2025-10-01"}, steps[0]["value"], "source"),
        vector({"on": "2026-10-01"}, steps[1]["value"], "source"),
        vector({"on": "2026-06-30"}, steps[0]["value"], "derived", "before the October 2026 increase"),
    ]
    row = dof_single_row(dof, "50,000")
    items = [
        dof.cite("page 21, Table 2, note 2", found.group(4), "The agreed PRSI increases are included in the analysis"),
        dof.cite("page 21, Table 2, note 2", found.group(2), f"{found.group(1)}% will increase to {found.group(2)}% from {found.group(3)} and to {found.group(4)}% from {found.group(5)}"),
        dof.cite("page 21, Table 2, single person on 50,000, PRSI for 2026", row[6], " ".join(row[:7]), role="supporting"),
    ]
    tests = [
        {"statistic": "count", "expected": 2, "tolerance": 0},
        {"statistic": "value[2026-12-31]", "expected": steps[1]["value"], "tolerance": 0},
    ]
    assumed = [{
        "parameter": "steps",
        "value": "the rate applies to the employee Class A contribution",
        "method": "derived",
        "rationale": "The Department of Finance note attaches the increases to the full rate PRSI contributor of its PAYE tables; its 2026 PRSI figure on 50,000 "
                     "(nine months at the October 2025 rate and three at the October 2026 rate) agrees with these steps.",
    }]
    return rule_entry(
        "ie-prsi-class-a-employee-rate-2025-2026",
        "Ireland employee PRSI rate for full-rate (Class A) contributors from October 2025 and October 2026",
        "tax", "IE", "step_schedule", {"unit": "percent of reckonable earnings", "steps": steps, "prior_rate": float(found.group(1))}, vectors, items, tests,
        ["payroll", "social-insurance", "prsi", "social-contributions", "step-schedule"],
        "The employee rate of Pay Related Social Insurance for full-rate contributors, as the Department of Finance's Budget 2026 tax policy book states the agreed "
        "increases in its notes to the PAYE examples: from the prior rate to the October 2025 rate, then to the October 2026 rate. The weekly earnings threshold, "
        "the PRSI credit, employer rates and other classes are not in this entry. Because the figures come from a note to a worked example rather than from the "
        "Social Welfare Act itself, a reviewer should confirm them against the legislation. The publisher states no licence in the document, so the licence is "
        "recorded as unstated and the entry stays at license-review.",
        ("2025-10-01", None), tier="B", assumed=assumed,
    )


# ---------------------------------------------------------------- Spain

BOE = "Agencia Estatal Boletín Oficial del Estado"


def es_irpf_scale() -> dict:
    source = es_boe("BOE-A-2020-17339", "Ley 11/2020, de Presupuestos Generales del Estado para el año 2021 (BOE XML)")
    article = match(r"Artículo 58\. Escala general del Impuesto sobre la Renta de las Personas Físicas\..*?Artículo 59\.", collapse(source.raw.decode("utf-8")), "artículo 58").group(0)
    cells = [plain(c) for c in re.findall(r"<td>(.*?)</td>", re.search(r"<tbody>.*?</tbody>", article, re.DOTALL).group(0), re.DOTALL)]
    rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
    brackets = [{"name": f"tramo {i + 1}", "over": de(base), "base_tax": de(quota), "rate_percent": de(rate)} for i, (base, quota, _rest, rate) in enumerate(rows)]
    parameters = {"currency": "EUR", "brackets": brackets, "scope": "state half of the general scale on the general taxable base; the autonomous community scale applies on top"}

    vectors = [vector({"income": b["over"]}, f"{Decimal(str(b['base_tax'])):.2f}", "source", f"cuota íntegra at {rows[i][0]}") for i, b in enumerate(brackets) if i > 0]
    vectors += [
        vector({"income": 30000}, str(cumulative_bracket_tariff.tax_due(parameters, 30000)), "derived"),
        vector({"marginal_rate_for": 400000}, brackets[-1]["rate_percent"], "source"),
    ]
    items = [source.cite(f"Artículo 63.1.1.º, escala, row {i + 1}", row[1], "Cuota íntegra") for i, row in enumerate(rows)]
    items += [
        source.cite("Artículo 63.1.1.º, escala, rates", rows[-1][3], "Tipo aplicable"),
        source.cite("Artículo 63.1.1.º, escala, last row", rows[-1][0], "En adelante"),
        source.cite("Artículo 58", "apartado 1 del artículo 63 de la Ley 35/2006", "Con efectos desde 1 de enero de 2021 y vigencia indefinida, se modifica el apartado 1 del artículo 63 de la Ley 35/2006"),
    ]
    tests = [
        {"statistic": "count", "expected": len(brackets), "tolerance": 0},
        {"statistic": f"rate[tramo {len(brackets)}]", "expected": brackets[-1]["rate_percent"], "tolerance": 0},
    ]
    return rule_entry(
        "es-irpf-state-general-scale-2021",
        "Spain personal income tax (IRPF) state general scale in force since 2021 (Ley 35/2006, artículo 63)",
        "tax", "ES", "cumulative_bracket_tariff", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "irpf", "statute", "tax-bands"],
        "The state general scale (escala general estatal) of the IRPF in article 63.1 of Ley 35/2006, as article 58 of Ley 11/2020 (the 2021 State Budget Act) "
        "rewrote it with effect from 1 January 2021 and indefinite validity; the BOE consolidated text of article 63 showed no later version when this entry was "
        "built. For each row, the tax (cuota íntegra) at the lower bound plus the applicable rate on the rest of the general taxable base. This is only "
        "the state half: each autonomous community applies its own scale to the same base, and the scale is applied to the base and to the personal and family "
        "minimum separately, with the result for the minimum subtracted (article 63.1.2.º); neither step is modelled. The source vectors are the cuota íntegra "
        "column; the other vector is computed from the scale. The BOE XML carries no licence statement, so the licence is recorded "
        "as unstated and the entry stays at license-review.",
        ("2021-01-01", None),
    )


def es_amount(value: float) -> str:
    """An amount written the way the BOE prints it, with a point for thousands and a comma for cents."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def es_boe(identifier: str, title: str) -> Source:
    return Source(f"https://www.boe.es/diario_boe/xml.php?id={identifier}", BOE, title)


def es_minimum_wage() -> dict:
    source = es_boe("BOE-A-2026-3815", "Real Decreto 126/2026, por el que se fija el salario mínimo interprofesional para 2026 (BOE XML)")
    general = match(r"queda fijado en (\d+,\d+) euros/día o (\d[\d ]*) euros/mes", source.text, "artículo 1")
    annual = match(r"sin que en ningún caso pueda considerarse una cuantía anual inferior a (\d[\d ]*) euros", source.text, "artículo 3")
    temporary = match(r"sin que la cuantía del salario profesional pueda resultar inferior a (\d+,\d+) euros por jornada legal", source.text, "artículo 4.1")
    household = match(r"el salario mínimo de dichas empleadas y empleados de hogar será de (\d+,\d+) euros por hora efectivamente trabajada", source.text, "artículo 4.2")
    rows = {
        "monthly": {"amount": de(general.group(2)), "unit": "euros per month", "basis": "artículo 1"},
        "daily": {"amount": de(general.group(1)), "unit": "euros per day", "basis": "artículo 1"},
        "annual_minimum": {"amount": de(annual.group(1)), "unit": "euros per year", "basis": "artículo 3.1"},
        "temporary_up_to_120_days_daily": {"amount": de(temporary.group(1)), "unit": "euros per legal working day", "basis": "artículo 4.1"},
        "household_employee_hourly": {"amount": de(household.group(1)), "unit": "euros per hour worked", "basis": "artículo 4.2"},
    }
    vectors = [vector({"key": key, "column": "amount"}, row["amount"], "source") for key, row in rows.items()]
    items = [
        source.cite("Artículo 1", general.group(2), general.group(0)),
        source.cite("Artículo 3.1", annual.group(1), annual.group(0)),
        source.cite("Artículo 4.1", temporary.group(1), temporary.group(0)),
        source.cite("Artículo 4.2", household.group(1), household.group(0)),
        source.cite("Disposición final tercera", "entre el 1 de enero y el 31 de diciembre de 2026", "surtirá efectos durante el período comprendido entre el 1 de enero y el 31 de diciembre de 2026"),
    ]
    tests = [
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
        {"statistic": "value[monthly, amount]", "expected": rows["monthly"]["amount"], "tolerance": 0},
    ]
    return rule_entry(
        "es-minimum-wage-2026",
        "Spain interprofessional minimum wage (SMI) for 2026: monthly, daily and annual amounts (Real Decreto 126/2026)",
        "employment", "ES", "lookup_table", {"currency": "EUR", "rows": rows}, vectors, items, tests,
        ["payroll", "employment", "minimum-wage", "statute", "reference-table"],
        "The Spanish salario mínimo interprofesional for 2026 fixed by Real Decreto 126/2026 (BOE 19 February 2026), with effect from 1 January to 31 December "
        "2026: the general amount by day or by month (article 1), the annual amount used to compare total pay (article 3.1, which corresponds to fourteen "
        "monthly payments), the daily minimum for fixed-term workers whose service with one company does not exceed 120 days, which includes the proportional "
        "share of Sundays, holidays and the two extraordinary payments (article 4.1), and the hourly minimum for household employees working by the hour "
        "(article 4.2). The BOE XML carries no licence statement, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"),
    )


def es_contribution_sources() -> Source:
    return es_boe("BOE-A-2026-7296", "Orden PJC/297/2026, normas legales de cotización a la Seguridad Social para 2026 (BOE XML)")


def es_contribution_bases(source: Source) -> dict:
    markup = match(r"Artículo 3\. Bases máximas y mínimas de cotización\..*?Artículo 4\.", collapse(source.raw.decode("utf-8")), "artículo 3").group(0)
    rows: dict[str, dict] = {}
    for table in re.findall(r"<table.*?</table>", markup, re.DOTALL):
        period = "day" if "Euros/día" in table else "month"
        for row in re.findall(r"<tr>(.*?)</tr>", re.search(r"<tbody>.*?</tbody>", table, re.DOTALL).group(0), re.DOTALL):
            group, category, low, high = (plain(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL))
            rows[group] = {"category": category, "minimum": de(low), "maximum": de(high), "period": period}
    if sorted(rows, key=int) != [str(n) for n in range(1, 12)]:
        raise ValueError("artículo 3: expected contribution groups 1 to 11")
    ceiling = match(r"El tope máximo de la base de cotización al Régimen General de la Seguridad Social será, desde el 1 de enero de 2026, de (\d\.\d{3},\d{2}) euros mensuales", source.text, "artículo 2.1")
    floor = match(r"sin que pueda ser inferior a (\d\.\d{3},\d{2}) euros", source.text, "artículo 2.2")
    vectors = [
        vector({"key": "1", "column": "minimum"}, rows["1"]["minimum"], "source"),
        vector({"key": "7", "column": "maximum"}, rows["7"]["maximum"], "source"),
        vector({"key": "10", "column": "minimum"}, rows["10"]["minimum"], "source"),
        vector({"key": "11", "column": "period"}, "day", "source"),
        vector("12", False, "derived", "there are eleven contribution groups"),
    ]
    items = [
        source.cite("Artículo 2.1", ceiling.group(1), ceiling.group(0)),
        source.cite("Artículo 2.2", floor.group(1), f"sin que pueda ser inferior a {floor.group(1)} euros"),
    ]
    for group in ("1", "2", "3", "8"):
        items.append(source.cite(f"Artículo 3, table row for group {group}", es_amount(rows[group]["minimum"]), rows[group]["category"]))
    items.append(source.cite("Artículo 3, daily maximum base for groups 8 to 11", es_amount(rows["8"]["maximum"]), "Bases máximas"))
    tests = [
        {"statistic": "count", "expected": 11, "tolerance": 0},
        {"statistic": "max[maximum]", "expected": rows["1"]["maximum"], "tolerance": 0},
    ]
    return rule_entry(
        "es-social-security-contribution-bases-2026",
        "Spain General Social Security Scheme minimum and maximum contribution bases by contribution group for 2026 (Orden PJC/297/2026)",
        "tax", "ES", "lookup_table",
        {"currency": "EUR", "rows": rows, "general_ceiling_monthly": de(ceiling.group(1)), "occupational_contingency_floor_monthly": de(floor.group(1))},
        vectors, items, tests,
        ["payroll", "social-insurance", "contribution-ceiling", "contribution-groups", "statute", "reference-table"],
        "Minimum and maximum common-contingency contribution bases of the Spanish General Social Security Scheme from 1 January 2026, keyed by contribution group "
        "(grupo de cotización) 1 to 11 with its professional categories: groups 1 to 7 per month and groups 8 to 11 per day, as article 3 of Orden PJC/297/2026 "
        "states them, plus the general ceiling (article 2.1, set by Real Decreto-ley 3/2026) and the floor for occupational contingencies (article 2.2). A "
        "generator assigns an employee a group from the job category and clamps the contribution base between the group's bounds. The order applies until the "
        "2026 State Budget Act is approved. The BOE XML carries no licence statement, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"),
    )


def es_contribution_rates(source: Source) -> dict:
    common = match(r"Para las contingencias comunes, el (\d+,\d+) por ciento, del que el (\d+,\d+) por ciento será a cargo de la empresa y el (\d+,\d+) por ciento, a cargo de la persona trabajadora", source.text, "artículo 4 a)")
    open_ended = match(r"realizados con personas trabajadoras que tengan reconocido un grado de discapacidad no inferior al 33 por ciento: (\d+,\d+) por ciento, del que el (\d+,\d+) por ciento será a cargo de la empresa y el (\d+,\d+) por ciento, a cargo de la persona trabajadora", source.text, "artículo 33 desempleo indefinido")
    fixed = match(r"Contratación de duración determinada a tiempo completo o a tiempo parcial: (\d+,\d+) por ciento, del que el (\d+,\d+) por ciento será a cargo del empresario y el (\d+,\d+) por ciento, a cargo de la persona trabajadora", source.text, "artículo 33 desempleo temporal")
    fogasa = match(r"Fondo de Garantía Salarial: el (\d+,\d+) por ciento, a cargo de la empresa", source.text, "FOGASA")
    training = match(r"Formación profesional: el (\d+,\d+) por ciento, del que el (\d+,\d+) por ciento será a cargo de la empresa y el (\d+,\d+) por ciento, a cargo de la persona trabajadora", source.text, "formación")
    mei = match(r"en el Régimen General de la Seguridad Social se determinará aplicando el tipo del (\d+,\d+) por ciento sobre la base de cotización por contingencias comunes, del que el (\d+,\d+) por ciento será a cargo del empleador y el (\d+,\d+) por ciento, a cargo de la persona trabajadora", source.text, "MEI")
    slabs = {
        "common_contingencies_total": de(common.group(1)), "common_contingencies_employer": de(common.group(2)), "common_contingencies_employee": de(common.group(3)),
        "unemployment_open_ended_total": de(open_ended.group(1)), "unemployment_open_ended_employer": de(open_ended.group(2)), "unemployment_open_ended_employee": de(open_ended.group(3)),
        "unemployment_fixed_term_total": de(fixed.group(1)), "unemployment_fixed_term_employer": de(fixed.group(2)), "unemployment_fixed_term_employee": de(fixed.group(3)),
        "wage_guarantee_fund_employer": de(fogasa.group(1)),
        "vocational_training_total": de(training.group(1)), "vocational_training_employer": de(training.group(2)), "vocational_training_employee": de(training.group(3)),
        "intergenerational_equity_total": de(mei.group(1)), "intergenerational_equity_employer": de(mei.group(2)), "intergenerational_equity_employee": de(mei.group(3)),
    }
    vectors = [
        vector(slabs["common_contingencies_total"], True, "source"),
        vector(slabs["common_contingencies_employee"], True, "source"),
        vector(slabs["unemployment_open_ended_employee"], True, "source"),
        vector(slabs["intergenerational_equity_total"], True, "source"),
        vector(12.5, False, "derived"),
    ]
    items = [
        source.cite("Artículo 4.a)", common.group(1), common.group(0)),
        source.cite("Artículo 33.2.a).1.º", open_ended.group(1), f"{open_ended.group(1)} por ciento, del que el {open_ended.group(2)} por ciento será a cargo de la empresa y el {open_ended.group(3)} por ciento"),
        source.cite("Artículo 33.2.a).2.º", fixed.group(1), f"Contratación de duración determinada a tiempo completo o a tiempo parcial: {fixed.group(1)} por ciento"),
        source.cite("Artículo 33.2.b)", fogasa.group(1), fogasa.group(0)),
        source.cite("Artículo 33.2.c)", training.group(1), training.group(0)),
        source.cite("Artículo 16", mei.group(1), f"aplicando el tipo del {mei.group(1)} por ciento sobre la base de cotización por contingencias comunes, del que el {mei.group(2)} por ciento será a cargo del empleador"),
    ]
    tests = [
        {"statistic": "count", "expected": len(slabs), "tolerance": 0},
        {"statistic": "slab[common_contingencies_employer]", "expected": slabs["common_contingencies_employer"], "tolerance": 0},
    ]
    return rule_entry(
        "es-social-security-contribution-rates-2026",
        "Spain General Social Security Scheme contribution rates for 2026 with employer and employee shares (Orden PJC/297/2026)",
        "tax", "ES", "rate_schedule", {"slabs": slabs, "unit": "percent of the contribution base"}, vectors, items, tests,
        ["payroll", "social-insurance", "social-contributions", "statute"],
        "Percentage contribution rates of the Spanish General Social Security Scheme from 1 January 2026 under Orden PJC/297/2026, each with its employer and "
        "employee share: common contingencies (article 4), unemployment for open-ended and for fixed-term contracts, the wage guarantee fund (employer only) and "
        "vocational training (article 33), and the intergenerational equity mechanism (article 16). Occupational accident and disease premiums follow a tariff "
        "by activity and are employer-only; overtime surcharges and the solidarity contribution on pay above the maximum base are not in this entry. The BOE XML "
        "carries no licence statement, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"),
    )


# ---------------------------------------------------------------- France


def fr_bareme() -> dict:
    source = Source("https://bofip.impots.gouv.fr/bofip/2491-PGP.html/identifiant%3DBOI-IR-LIQ-20-10-20260407",
                    "Direction générale des Finances publiques (BOFiP-Impôts)", "BOI-IR-LIQ-20-10-20260407, IR - Liquidation - Détermination de l'impôt brut (HTML)", "etalab-2.0")
    page = collapse(html.unescape(plain(source.raw.decode("utf-8"))))
    table = match(r"Barème pour l’imposition sur les revenus 2025 (.*?) Permalien", page, "barème table").group(1)
    first = match(r"N’excédant pas (\d[\d ]*) € (\d+) %", table, "first slice")
    slices = re.findall(r"Supérieure à (\d[\d ]*) € et inférieure ou égale à (\d[\d ]*) € (\d+) %", table)
    top = match(r"Supérieure à (\d[\d ]*) € (\d+) %\s*$", table, "top slice")
    bands = [{"name": f"{first.group(2)}%", "up_to": de(first.group(1)), "rate_percent": int(first.group(2))}]
    bands += [{"name": f"{rate}%", "up_to": de(upper), "rate_percent": int(rate)} for _, upper, rate in slices]
    bands.append({"name": f"{top.group(2)}%", "up_to": None, "rate_percent": int(top.group(2))})
    parameters = {"income_year": 2025, "currency": "EUR", "per": "part of quotient familial", "personal_allowance": 0, "bands": bands}

    vectors = [
        vector({"income": bands[0]["up_to"]}, "0.00", "source", "no tax on the first slice"),
        vector({"income": 40000}, str(income_tax_bands.tax_due(parameters, 40000)), "derived", "tax for one part"),
        vector({"income": 200000}, str(income_tax_bands.tax_due(parameters, 200000)), "derived", "top slice"),
    ]
    items = [source.cite("§ 40, barème pour l'imposition des revenus 2025, row 1", first.group(1), f"N’excédant pas {first.group(1)} €")]
    items += [source.cite(f"§ 40, barème, slice at {rate} %", upper, f"Supérieure à {lower} € et inférieure ou égale à {upper} €") for lower, upper, rate in slices]
    items += [
        source.cite("§ 40, remarque on the indexation by the loi de finances pour 2026", "0,9 %", "indexe les limites des tranches de revenus du barème de l’impôt sur le revenu sur l’évolution de l’IPC hors tabac de 2025 par rapport à 2024"),
        source.cite("§ 40, table title", "revenus 2025", "Barème pour l’imposition sur les revenus 2025"),
        source.cite("Page footer, licence statement", "licence etalab-2.0", "Sauf mention contraire, tous les contenus de ce site sont sous", role="supporting"),
    ]
    tests = [
        {"statistic": "count", "expected": len(bands), "tolerance": 0},
        {"statistic": "rate[45%]", "expected": 45, "tolerance": 0},
    ]
    return rule_entry(
        "fr-income-tax-bareme-revenus-2025",
        "France income tax scale (barème progressif) for 2025 income taxed in 2026, per part of quotient familial (CGI article 197)",
        "tax", "FR", "income_tax_bands", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "tax-bands", "withholding"],
        "The progressive income tax scale of CGI article 197 I-1 for income earned in 2025 and taxed in 2026, as the BOFiP-Impôts (DGFiP's official tax "
        "doctrine) publishes it after the loi n° 2026-103 du 19 février 2026 de finances pour 2026 indexed the slice limits by 0.9 percent. The scale applies "
        "to taxable income for one part of the quotient familial: the household's net taxable income is divided by its number of parts, the scale applied, "
        "and the result multiplied back by the parts (CGI article 193); the cap on the benefit of the quotient familial, the décote and the tax reductions "
        "are not modelled. valid_from and valid_to give the income year the scale taxes. The BOFiP page states that its content is under the Licence Ouverte "
        "(etalab-2.0); the verifier does not list that licence as permissive, so the entry stays at license-review. The page is HTML (tier B) and lists the "
        "document's versions, so it may change when the next version is published.",
        ("2025-01-01", "2025-12-31"), tier="B",
    )


# ---------------------------------------------------------------- Poland

SEJM = "Kancelaria Sejmu (Dziennik Ustaw, ELI API)"


def pl_pit() -> dict:
    source = Source("https://api.sejm.gov.pl/eli/acts/DU/2026/592/text.pdf", SEJM, "Dz.U. 2026 poz. 592, jednolity tekst ustawy o podatku dochodowym od osób fizycznych (PDF)")
    amount = r"(\d{1,3}(?: \d{3})*)"
    first = match(rf"ponad do {amount} (\d+) % minus kwota zmniejszająca podatek (\d+) zł", source.text, "art. 27 ust. 1 row 1")
    second = match(rf"{first.group(1)} {amount} zł \+ (\d+) % nadwyżki ponad {first.group(1)} zł", source.text, "art. 27 ust. 1 row 2")
    brackets = [
        {"name": "first", "over": 0, "base_tax": 0, "rate_percent": int(first.group(2)), "reduction": int(first.group(3))},
        {"name": "second", "over": de(first.group(1)), "base_tax": de(second.group(1)), "rate_percent": int(second.group(2))},
    ]
    parameters = {"currency": "PLN", "brackets": brackets, "reduction_name": "kwota zmniejszająca podatek"}

    tax_free = int(Decimal(brackets[0]["reduction"]) * 100 / brackets[0]["rate_percent"])
    vectors = [
        vector({"income": brackets[1]["over"]}, str(cumulative_bracket_tariff.tax_due(parameters, brackets[1]["over"])), "derived", "top of the first bracket: 12 percent less the reduction"),
        vector({"income": tax_free}, "0.00", "derived", "the reduction cancels the tax up to this income"),
        vector({"income": 200000}, str(cumulative_bracket_tariff.tax_due(parameters, 200000)), "derived"),
        vector({"marginal_rate_for": 150000}, brackets[1]["rate_percent"], "source"),
    ]
    items = [
        source.cite("Art. 27 ust. 1, skala podatkowa, row 1", first.group(3) + " zł", "minus kwota zmniejszająca podatek"),
        source.cite("Art. 27 ust. 1, skala podatkowa, row 2", second.group(1) + " zł", f"{second.group(1)} zł + {second.group(2)} % nadwyżki ponad {first.group(1)} zł"),
        source.cite("Obwieszczenie, point 1", "stanu prawnego na dzień 1 kwietnia 2026 r.", "z uwzględnieniem stanu prawnego na dzień 1 kwietnia 2026 r."),
    ]
    tests = [
        {"statistic": "count", "expected": 2, "tolerance": 0},
        {"statistic": "rate[second]", "expected": brackets[1]["rate_percent"], "tolerance": 0},
    ]
    assumed = [{
        "parameter": "vectors",
        "value": f"zero tax up to {tax_free}",
        "method": "derived",
        "rationale": "The statute states the 12 percent rate less the tax-reducing amount; the income at which the tax reaches zero is that amount divided by the rate.",
    }]
    return rule_entry(
        "pl-pit-tax-scale",
        "Poland personal income tax (PIT) scale under article 27(1) of the PIT Act, consolidated text as at 1 April 2026",
        "tax", "PL", "cumulative_bracket_tariff", parameters, vectors, items, tests,
        ["payroll", "tax", "income-tax", "pit", "statute", "tax-bands"],
        "The Polish progressive tax scale (skala podatkowa) of article 27(1) of the Act of 26 July 1991 on personal income tax, in the consolidated text "
        "announced in Dz.U. 2026 poz. 592, which reflects the law as at 1 April 2026: 12 percent less the tax-reducing amount up to the first threshold and "
        "a fixed amount plus 32 percent of the excess above it. valid_from is the date of that legal state; the text itself does not say when the scale was "
        "first applied. Flat-rate, lump-sum and capital income taxes, the solidarity levy and the health contribution are separate and not modelled; payroll "
        "advances apply the scale monthly with the reducing amount spread by the PIT-2 statement. The Dziennik Ustaw PDF carries no licence statement, so the "
        "licence is recorded as unstated and the entry stays at license-review.",
        ("2026-04-01", None), tier="B", assumed=assumed,
    )


def pl_minimum_wage() -> dict:
    source = Source("https://api.sejm.gov.pl/eli/acts/DU/2025/1242/text.pdf", SEJM, "Dz.U. 2025 poz. 1242, minimalne wynagrodzenie za pracę w 2026 r. (PDF)")
    monthly = match(r"§ 1\. Od dnia 1 stycznia 2026 r\. ustala się minimalne wynagrodzenie za pracę w wysokości (\d+) zł", source.text, "§ 1")
    hourly = match(r"§ 2\. Od dnia 1 stycznia 2026 r\. ustala się minimalną stawkę godzinową w wysokości (\d+,\d+) zł", source.text, "§ 2")
    rows = {
        "monthly": {"amount": de(monthly.group(1)), "unit": "PLN gross per month, full-time employment", "basis": "§ 1"},
        "hourly": {"amount": de(hourly.group(1)), "unit": "PLN gross per hour, specified civil-law contracts", "basis": "§ 2"},
    }
    vectors = [vector({"key": k, "column": "amount"}, r["amount"], "source") for k, r in rows.items()] + [vector("weekly", False, "derived")]
    items = [source.cite("§ 1", monthly.group(1) + " zł", monthly.group(0)), source.cite("§ 2", hourly.group(1) + " zł", hourly.group(0))]
    tests = [{"statistic": "count", "expected": 2, "tolerance": 0}, {"statistic": "value[monthly, amount]", "expected": rows["monthly"]["amount"], "tolerance": 0}]
    return rule_entry(
        "pl-minimum-wage-2026",
        "Poland minimum monthly wage and minimum hourly rate from 1 January 2026 (Council of Ministers regulation, Dz.U. 2025 poz. 1242)",
        "employment", "PL", "lookup_table", {"currency": "PLN", "rows": rows}, vectors, items, tests,
        ["payroll", "employment", "minimum-wage", "statute", "reference-table"],
        "The Polish minimum remuneration for work (minimalne wynagrodzenie za pracę) for a full-time employee and the minimum hourly rate for specified "
        "civil-law contracts, both from 1 January 2026, as the Council of Ministers regulation of 11 September 2025 sets them under article 2(5) of the Act of "
        "10 October 2002 on the minimum wage. Part-time employees receive at least the proportional monthly amount. The Dziennik Ustaw PDF, served by the Sejm "
        "ELI API, carries no licence statement, so the licence is recorded as unstated and the entry stays at license-review.",
        ("2026-01-01", "2026-12-31"), tier="B",
    )


# ---------------------------------------------------------------- main


def main() -> int:
    estg, solzg, sgb4 = GiiLaw("estg"), GiiLaw("solzg_1995"), GiiLaw("sgb_4")
    stefeg = steuerfortentwicklungsgesetz()
    guidelines = Source("https://www.minijob-zentrale.de/SharedDocs/Downloads/DE/Rundschreiben/Geringfuegigkeitsrichtlinien-2026.pdf?__blob=publicationFile",
                        "Minijob-Zentrale (Deutsche Rentenversicherung Knappschaft-Bahn-See)", "Geringfügigkeits-Richtlinien 2026 of the social insurance central bodies (PDF)")
    write(de_tariff_entry(estg, stefeg))
    write(de_solidarity_entry(solzg, stefeg))
    write(de_child_allowances(estg, stefeg))
    write(de_minimum_wage(GiiLaw("milog"), GiiLaw("milov4"), GiiLaw("milov5")))
    write(de_minijob_limit(sgb4, guidelines))
    write(de_earnings_ceilings(GiiLaw("svbezgrv_2026")))
    write(at_income_tax())
    write(nl_box1())
    write(nl_minimum_wage())
    irish = ie_sources()
    write(ie_income_tax(irish))
    write(ie_usc(irish))
    write(ie_prsi(irish))
    write(es_irpf_scale())
    write(es_minimum_wage())
    contributions = es_contribution_sources()
    write(es_contribution_bases(contributions))
    write(es_contribution_rates(contributions))
    write(fr_bareme())
    write(pl_pit())
    write(pl_minimum_wage())
    return 0


if __name__ == "__main__":
    sys.exit(main())

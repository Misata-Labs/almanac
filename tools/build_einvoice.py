"""Build the e-invoicing code-list and field-rule entries from tax-authority and network-operator sources.

Sources, each fetched from its publisher and pinned where the publisher
versions it:

* Italy: the FatturaPA 1.2.3 XML Schema, its example invoices and the
  technical specification 1.4 (fatturapa.gov.it, Agenzia delle Entrate / Sogei).
* Peppol: the BIS Billing 3.0.21 code lists, schematron and release notes in
  the OpenPeppol GitHub repository (pinned commit), the eDelivery participant
  identifier scheme list 9.7 and the Policy for use of Identifiers 4.4.0
  (docs.peppol.eu).
* Poland: the KSeF FA(3) structured invoice schema and its signed metadata
  record (crd.gov.pl, Ministerstwo Finansów).
* Spain: Orden HAC/1177/2024 (VERI*FACTU), as published in the Boletín
  Oficial del Estado.
* Mexico: the CFDI 4.0 catalogue and invoice schemas (www.sat.gob.mx).
* India: the CBIC notifications that set and amend the e-invoicing turnover
  threshold, as hosted by the GST Council Secretariat.
* Saudi Arabia: the ZATCA Electronic Invoice XML Implementation Standard 1.2.

Every code, label and value is read from the fetched resource, and every
evidence value and snippet is checked against the resource's searchable text
before an entry is written. Run from the repository root:

    uv run python tools/build_einvoice.py
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

from almanac.fetch import Resource  # noqa: E402

ACCESSED = "2026-11-03"
UNSTATED = "unstated"
DOMAIN = "invoicing"
BASE_TAGS = ["invoicing", "e-invoicing", "tax", "code-list"]
BASE_USE_CASES = ["invoicing-demo", "erp-demo", "tax-demo", "data-quality-validation"]

XS = "{http://www.w3.org/2001/XMLSchema}"

# Italy
FPA = "https://www.fatturapa.gov.it/export/documenti"
IT_XSD = f"{FPA}/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd"
IT_SPEC = f"{FPA}/fatturapa/v1.4/Specifiche_tecniche_del_formato_FatturaPA_V1.4.pdf"
IT_EXAMPLE_FPR = f"{FPA}/fatturapa/v1.2/IT01234567890_FPR01.xml"
IT_EXAMPLE_FPA = f"{FPA}/fatturapa/v1.2/IT01234567890_FPA01.xml"
IT_PUBLISHER = "Agenzia delle Entrate (FatturaPA, Sistema di Interscambio)"
IT_XSD_TITLE = "Schema del file XML FatturaPA versione 1.2.3 (fattura ordinaria e PA, Schema_VFPR12_v1.2.3.xsd)"
IT_SPEC_TITLE = "Specifiche tecniche operative del formato della fattura del Sistema di Interscambio, versione 1.4"
IT_VALID_FROM = "2025-01-31"

# Peppol
PEPPOL_COMMIT = "5df0eff7c8efafd7c79c0dacce55082d175db759"
PEPPOL_RAW = f"https://raw.githubusercontent.com/OpenPEPPOL/peppol-bis-invoice-3/{PEPPOL_COMMIT}"
PEPPOL_CODELIST = f"{PEPPOL_RAW}/structure/codelist"
PEPPOL_NOTES = f"{PEPPOL_RAW}/guide/release-notes/v3.0.21.adoc"
PEPPOL_HOTFIX = f"{PEPPOL_RAW}/guide/release-notes/v3.0.21-hotfix.adoc"
PEPPOL_SCH = f"{PEPPOL_RAW}/rules/sch/PEPPOL-EN16931-UBL.sch"
PEPPOL_INTRO = f"{PEPPOL_RAW}/guide/bis/introduction.adoc"
PEPPOL_SCHEMES = "https://docs.peppol.eu/edelivery/codelists/v9.7/Peppol%20Code%20Lists%20-%20Participant%20identifier%20schemes%20v9.7.json"
PEPPOL_POLICY = "https://docs.peppol.eu/edelivery/policies/Peppol-EDN-Policy-for-use-of-identifiers-4.4.0-2025-02-06.pdf"
PEPPOL_PUBLISHER = "OpenPeppol AISBL"
PEPPOL_BIS_TITLE = f"Peppol BIS Billing 3.0.21 code lists (OpenPEPPOL/peppol-bis-invoice-3 at {PEPPOL_COMMIT[:8]})"
PEPPOL_VALID_FROM = "2026-08-17"

# Poland
PL_XSD = "https://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd"
PL_META = "https://crd.gov.pl/wzor/2025/06/25/13775/wyroznik.xml"
PL_PUBLISHER = "Ministerstwo Finansów (Centralne Repozytorium Wzorów Dokumentów Elektronicznych)"
PL_XSD_TITLE = "Schemat FA(3) ustrukturyzowanej faktury VAT dla KSeF (wzór 2025/06/25/13775)"
PL_META_TITLE = "Wyróżnik wzoru FA(3) ustrukturyzowanej faktury VAT (wzór 2025/06/25/13775)"

# Spain
ES_BOE = "https://www.boe.es/boe/dias/2024/10/28/pdfs/BOE-A-2024-22138.pdf"
ES_PUBLISHER = "Ministerio de Hacienda (Boletín Oficial del Estado)"
ES_TITLE = "Orden HAC/1177/2024, de 17 de octubre (VERI*FACTU especificaciones técnicas), BOE núm. 260, 28 octubre 2024"
ES_VALID_FROM = "2024-10-29"

# Mexico
MX_CAT = "https://www.sat.gob.mx/sitio_internet/cfd/catalogos/catCFDI.xsd"
MX_CFDI = "https://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
MX_PUBLISHER = "Servicio de Administración Tributaria (SAT)"
MX_VALID_FROM = "2024-12-13"
MX_CFDI_VALID_FROM = "2024-06-04"

# India
GSTC_FILES = "https://gstcouncil.gov.in/sites/default/files/2024-05"
IN_PUBLISHER = "Central Board of Indirect Taxes and Customs (hosted by the GST Council Secretariat)"
GST_LICENSE = "GST Council copyright policy: reproduction free of charge after permission by email, with acknowledgement"

# Saudi Arabia
SA_STD = "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/20230519_ZATCA_Electronic_Invoice_XML_Implementation_Standard_%20vF.pdf"
SA_PUBLISHER = "Zakat, Tax and Customs Authority (ZATCA)"
SA_TITLE = "Electronic Invoice XML Implementation Standard, version 1.2 (2023-05-19)"
SA_VALID_FROM = "2023-05-19"

RAW: dict[str, bytes] = {}
TEXT: dict[str, str] = {}
PAGES: dict[str, list[str]] = {}


def load(url: str) -> bytes:
    """Fetch a resource once, keeping its bytes and whitespace-collapsed searchable text."""
    if url not in RAW:
        RAW[url] = fetch(url)
        TEXT[url] = " ".join(Resource(url, RAW[url], "").text.split())
    return RAW[url]


def pdf_lines(url: str) -> list[str]:
    """Extracted text lines of a PDF, pages concatenated in order, as the verifier extracts them."""
    if url not in PAGES:
        PAGES[url] = Resource(url, load(url), "application/pdf").text.splitlines()
    return PAGES[url]


def cite(publisher: str, title: str, url: str, locator: str, value: Any, snippet: str, license_id: str = UNSTATED, role: str = "primary", unit: str = "text") -> dict:
    """Evidence item whose value and snippet are confirmed present in the fetched text."""
    raw = load(url)
    for label, needle in (("value", str(value)), ("snippet", snippet)):
        if " ".join(needle.split()) not in TEXT[url]:
            raise ValueError(f"{label} not found in {url}: {needle!r}")
    if len(snippet.split()) > 24:
        raise ValueError(f"snippet over 24 words: {snippet!r}")
    item = evidence(publisher, title, url, locator, value, unit, snippet, license_id, raw, role)
    item["accessed_at"] = ACCESSED
    return item


def entry(
    entry_id: str,
    title: str,
    region: str,
    tier: str,
    valid_from: str,
    implementation: str,
    parameters: dict,
    vectors: list[dict],
    evidence_items: list[dict],
    tests: list[dict],
    notes: str,
    tags: list[str],
    use_cases: list[str] | None = None,
    assumed: list[dict] | None = None,
) -> dict:
    if len(title) > 140:
        raise ValueError(f"title too long: {title!r}")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": DOMAIN,
        "region": region,
        "status": "license-review",
        "tier": tier,
        "valid_from": valid_from,
        "valid_to": None,
        "tags": BASE_TAGS + [t for t in tags if t not in BASE_TAGS],
        "use_cases": BASE_USE_CASES + [u for u in (use_cases or ["invoicing", "accounts-payable"]) if u not in BASE_USE_CASES],
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}, *tests],
        "notes": notes,
    }


def member(set_name: str, code: str, expected: bool = True, origin: str = "source", note: str | None = None) -> dict:
    vector = {"input": {"set": set_name, "value": code}, "expected": expected, "origin": origin}
    if note:
        vector["note"] = note
    return vector


def count_tests(sets: dict[str, dict]) -> list[dict]:
    return [{"statistic": f"count[{name}]", "expected": len(codes), "tolerance": 0} for name, codes in sets.items()]


# ---------------------------------------------------------------- XML Schema helpers


def collapse(text: str | None) -> str:
    return " ".join((text or "").split())


def simple_type(raw: bytes, name: str) -> ET.Element:
    root = ET.fromstring(raw)
    for node in root.iter(f"{XS}simpleType"):
        if node.get("name") == name:
            return node
    raise KeyError(f"simpleType {name} not found")


def enumerations(raw: bytes, name: str) -> dict[str, str]:
    """Codes of a simpleType with their annotation text (empty where the schema gives none), in schema order."""
    codes: dict[str, str] = {}
    for enum in simple_type(raw, name).iter(f"{XS}enumeration"):
        doc = enum.find(f"{XS}annotation/{XS}documentation")
        codes[enum.get("value")] = collapse(doc.text if doc is not None else "")
    if not codes:
        raise ValueError(f"{name} has no enumerations")
    return codes


def facets(raw: bytes, name: str) -> dict[str, Any]:
    """Pattern, length and whitespace facets of a simpleType, named as einvoice_field_format expects."""
    restriction = simple_type(raw, name).find(f"{XS}restriction")
    out: dict[str, Any] = {}
    patterns = [p.get("value") for p in restriction.findall(f"{XS}pattern")]
    if patterns:
        out["patterns"] = patterns
    for tag, key in (("length", "length"), ("minLength", "min_length"), ("maxLength", "max_length")):
        node = restriction.find(f"{XS}{tag}")
        if node is not None:
            out[key] = int(node.get("value"))
    ws = restriction.find(f"{XS}whiteSpace")
    if ws is not None:
        out["whitespace"] = ws.get("value")
    return out


def xml_element_text(raw: bytes, local_name: str) -> list[str]:
    """Text of every element with ``local_name`` in an XML document, namespace ignored."""
    return [collapse(node.text) for node in ET.fromstring(raw).iter() if node.tag.split("}")[-1] == local_name]


# ---------------------------------------------------------------- Italy


def it_xsd(locator: str, value: str, snippet: str, role: str = "primary") -> dict:
    return cite(IT_PUBLISHER, IT_XSD_TITLE, IT_XSD, locator, value, snippet, role=role)


def it_spec(locator: str, value: str, snippet: str) -> dict:
    return cite(IT_PUBLISHER, IT_SPEC_TITLE, IT_SPEC, locator, value, snippet, role="supporting")


def it_revision_evidence() -> dict:
    return it_spec("page 5, Stato del documento, revision 1.4", "1.4 31 gennaio 2025", "per la comunicazione all’Agenzia delle entrate della omessa o irregolare fatturazione")


IT_REVISION_ASSUMPTION = {
    "parameter": "valid_from",
    "value": IT_VALID_FROM,
    "method": "derived",
    "rationale": "The specification's revision table dates version 1.4, which introduced the 1.2.3 schema, 31 January 2025; it gives no separate start date for the new codes.",
}

IT_TAGS = ["fatturapa", "sdi", "italy"]


def it_document_types() -> dict:
    raw = load(IT_XSD)
    sets = {"tipo_documento": enumerations(raw, "TipoDocumentoType")}
    return entry(
        "it-fatturapa-document-type-codes",
        "Italy FatturaPA TipoDocumento codes (TD01 to TD29), schema 1.2.3",
        "IT", "A", IT_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("tipo_documento", "TD01"),
            member("tipo_documento", "TD04"),
            member("tipo_documento", "TD29", note="added by specification 1.4"),
            member("tipo_documento", "TD07", False, "derived", "the schema jumps from TD06 to TD16"),
            member("tipo_documento", "td01", False, "derived", "codes are upper case"),
        ],
        [
            it_xsd("simpleType TipoDocumentoType", 'value="TD01"', 'simpleType name="TipoDocumentoType"'),
            it_xsd("simpleType TipoDocumentoType, last enumeration", 'value="TD29"', "Comunicazione per omessa o irregolare fatturazione da parte del cedente/prestatore italiano"),
            it_revision_evidence(),
        ],
        count_tests(sets),
        "Document-type codes for the TipoDocumento element (2.1.1.1) of an Italian electronic invoice sent through the "
        "Sistema di Interscambio, with the Italian descriptions the schema annotates them with. TD01 is an ordinary invoice, "
        "TD04 a credit note, TD16 to TD19 the integration and self-invoicing documents for reverse charge, and TD29 the "
        "notice of omitted or irregular invoicing that version 1.4 of the specification added. Codes and labels are read "
        "from Schema_VFPR12_v1.2.3.xsd as published on fatturapa.gov.it; the schema carries no licence statement.",
        IT_TAGS + ["document-type"],
        assumed=[IT_REVISION_ASSUMPTION],
    )


NATURA_WITHDRAWN = re.compile(r"<!--\s*IL CODICE SEGUENTE \((N[0-9.]+)\) NON SARA' PIU' VALIDO PER LE FATTURE EMESSE A PARTIRE DAL PRIMO GENNAIO 2021\s*-->")


def it_natura() -> dict:
    raw = load(IT_XSD)
    codes = enumerations(raw, "NaturaType")
    block = re.search(r'<xs:simpleType name="NaturaType">.*?</xs:simpleType>', raw.decode("utf-8-sig"), re.S).group(0)
    withdrawn = set(NATURA_WITHDRAWN.findall(block))
    if withdrawn != {"N2", "N3", "N6"}:
        raise ValueError(f"unexpected withdrawn Natura codes {withdrawn}")
    rows = {
        code: {
            "description": label,
            "parent": code.split(".")[0] if "." in code else None,
            "valid_for_invoices_issued_from_2021_01_01": code not in withdrawn,
        }
        for code, label in codes.items()
    }
    return entry(
        "it-fatturapa-vat-nature-codes",
        "Italy FatturaPA Natura codes for VAT-free lines (N1 to N7 with sub-codes), schema 1.2.3",
        "IT", "A", IT_VALID_FROM, "almanac.rules.lookup_table", {"rows": rows},
        [
            {"input": {"key": "N3.2", "column": "description"}, "expected": codes["N3.2"], "origin": "source"},
            {"input": {"key": "N6.3", "column": "parent"}, "expected": "N6", "origin": "derived", "note": "sub-codes share the parent's prefix"},
            {"input": {"key": "N2", "column": "valid_for_invoices_issued_from_2021_01_01"}, "expected": False, "origin": "source"},
            {"input": {"key": "N2.1", "column": "valid_for_invoices_issued_from_2021_01_01"}, "expected": True, "origin": "source"},
            {"input": {"key": "N7", "column": "valid_for_invoices_issued_from_2021_01_01"}, "expected": True, "origin": "source"},
            {"input": "N8", "expected": False, "origin": "derived", "note": "not in the schema"},
        ],
        [
            it_xsd("simpleType NaturaType", 'value="N3.2"', "Non Imponibili - cessioni intracomunitarie"),
            it_xsd("simpleType NaturaType, comment before N2", 'value="N2"', "IL CODICE SEGUENTE (N2) NON SARA' PIU' VALIDO PER LE FATTURE EMESSE A PARTIRE DAL PRIMO GENNAIO 2021"),
            it_xsd("simpleType NaturaType, comment before N6", 'value="N6.9"', "IL CODICE SEGUENTE (N6) NON SARA' PIU' VALIDO"),
            it_spec("section 3.8.1, Natura value list", "N2 non soggette (non più valido dal 1 Gen 2021)", "N3 non imponibili (non più valido dal 1 Gen 2021)"),
            it_revision_evidence(),
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[N4,description]", "expected": codes["N4"], "tolerance": 0},
        ],
        "Codes for the Natura element, which states why an invoice line or VAT summary carries no VAT: N1 excluded under "
        "article 15 of DPR 633/1972, N2.x not subject, N3.x non-taxable (exports, intra-EU supplies, San Marino and so on), "
        "N4 exempt, N5 margin scheme, N6.x reverse charge by sector, and N7 VAT paid in another EU state. The parent codes "
        "N2, N3 and N6 remain in the schema but, per the schema comments and the specification, may not be used on "
        "invoices issued from 1 January 2021; the valid_for_invoices_issued_from_2021_01_01 column records that. "
        "parent is the code before the dot. The schema carries no licence statement.",
        IT_TAGS + ["vat-exemption"],
        assumed=[
            IT_REVISION_ASSUMPTION,
            {"parameter": "rows.*.parent", "value": "code prefix before the dot", "method": "derived", "rationale": "The schema lists sub-codes flat; the parent is read from the code itself."},
        ],
    )


def it_tax_regimes() -> dict:
    raw = load(IT_XSD)
    sets = {"regime_fiscale": enumerations(raw, "RegimeFiscaleType")}
    return entry(
        "it-fatturapa-tax-regime-codes",
        "Italy FatturaPA RegimeFiscale codes for the seller's tax regime (RF01 to RF20), schema 1.2.3",
        "IT", "A", IT_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("regime_fiscale", "RF01"),
            member("regime_fiscale", "RF19"),
            member("regime_fiscale", "RF20", note="cross-border VAT franchise added by specification 1.4"),
            member("regime_fiscale", "RF03", False, "source", "removed in specification revision 1.2.1"),
        ],
        [
            it_xsd("simpleType RegimeFiscaleType", 'value="RF19"', 'simpleType name="RegimeFiscaleType"'),
            it_xsd("simpleType RegimeFiscaleType, last enumeration", 'value="RF20"', "Regime transfrontaliero di Franchigia IVA (Direttiva UE 2020/285)"),
            it_spec("page 5, Stato del documento, revision 1.2.1", "Eliminazione del regime fiscale RF03", "Nuove iniziative produttive"),
            it_revision_evidence(),
        ],
        count_tests(sets),
        "Codes for the RegimeFiscale element (1.2.1.8) that states the tax regime of the seller (cedente/prestatore): RF01 "
        "ordinary, RF02 minimum taxpayers, RF19 the flat-rate scheme, RF20 the cross-border VAT franchise of Directive "
        "2020/285, and the special regimes between them. RF03 was withdrawn in revision 1.2.1 and is absent from the schema. "
        "Codes and labels come from the 1.2.3 schema; it carries no licence statement.",
        IT_TAGS + ["tax-regime"],
        ["invoicing", "kyb-onboarding", "company-generation"],
        assumed=[IT_REVISION_ASSUMPTION],
    )


def it_payment_codes() -> dict:
    raw = load(IT_XSD)
    sets = {"modalita_pagamento": enumerations(raw, "ModalitaPagamentoType"), "condizioni_pagamento": enumerations(raw, "CondizioniPagamentoType")}
    return entry(
        "it-fatturapa-payment-method-and-terms-codes",
        "Italy FatturaPA ModalitaPagamento (MP01 to MP23) and CondizioniPagamento (TP01 to TP03) codes, schema 1.2.3",
        "IT", "A", IT_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("modalita_pagamento", "MP01", note="used by the published example invoice"),
            member("modalita_pagamento", "MP05"),
            member("modalita_pagamento", "MP23"),
            member("modalita_pagamento", "MP24", False, "derived"),
            member("condizioni_pagamento", "TP01", note="used by the published example invoice"),
            member("condizioni_pagamento", "TP03"),
        ],
        [
            it_xsd("simpleType ModalitaPagamentoType", 'value="MP23"', 'simpleType name="ModalitaPagamentoType"'),
            it_xsd("simpleType CondizioniPagamentoType", 'value="TP01"', "pagamento a rate"),
            cite(IT_PUBLISHER, "FatturaPA example invoice IT01234567890_FPR01.xml (fattura ordinaria)", IT_EXAMPLE_FPR, "DatiPagamento", "<ModalitaPagamento>MP01</ModalitaPagamento>", "<CondizioniPagamento>TP01</CondizioniPagamento>", role="supporting"),
            it_revision_evidence(),
        ],
        count_tests(sets),
        "Payment method codes for ModalitaPagamento (2.4.2.2): MP01 cash, MP02 cheque, MP05 bank transfer, MP08 payment card, "
        "MP12 RIBA, MP19 to MP21 SEPA direct debits, MP23 PagoPA, and the others in the schema; and payment terms codes for "
        "CondizioniPagamento (2.4.1): TP01 instalments, TP02 full payment, TP03 advance. Codes and Italian labels come from "
        "the 1.2.3 schema; it carries no licence statement.",
        IT_TAGS + ["payment-method"],
        ["invoicing", "accounts-payable", "payments-demo"],
        assumed=[IT_REVISION_ASSUMPTION],
    )


def it_withholding_codes() -> dict:
    raw = load(IT_XSD)
    sets = {
        "tipo_ritenuta": enumerations(raw, "TipoRitenutaType"),
        "causale_pagamento": enumerations(raw, "CausalePagamentoType"),
        "tipo_cassa": enumerations(raw, "TipoCassaType"),
        "esigibilita_iva": enumerations(raw, "EsigibilitaIVAType"),
    }
    return entry(
        "it-fatturapa-withholding-pension-fund-and-vat-due-codes",
        "Italy FatturaPA TipoRitenuta, CausalePagamento, TipoCassa and EsigibilitaIVA codes, schema 1.2.3",
        "IT", "A", IT_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("tipo_ritenuta", "RT01"),
            member("tipo_ritenuta", "RT06"),
            member("causale_pagamento", "A"),
            member("tipo_cassa", "TC22"),
            member("esigibilita_iva", "S"),
            member("esigibilita_iva", "X", False, "derived"),
        ],
        [
            it_xsd("simpleType TipoRitenutaType", 'value="RT01"', 'simpleType name="TipoRitenutaType"'),
            it_xsd("simpleType CausalePagamentoType", 'value="A"', 'simpleType name="CausalePagamentoType"'),
            it_xsd("simpleType TipoCassaType", 'value="TC22"', 'simpleType name="TipoCassaType"'),
            it_xsd("simpleType EsigibilitaIVAType", 'value="S"', 'simpleType name="EsigibilitaIVAType"'),
            it_revision_evidence(),
        ],
        count_tests(sets),
        "Four smaller FatturaPA vocabularies: TipoRitenuta (2.1.1.5.1) for the withholding type (RT01 natural persons, RT02 "
        "legal persons, RT03 to RT06 social security and pension contributions); CausalePagamento (2.1.1.5.4), the payment "
        "reason letters taken from the Certificazione Unica model; TipoCassa (2.1.1.7.1) for the professional pension fund "
        "(TC01 to TC22); and EsigibilitaIVA (2.2.2.7) for when VAT becomes due (D deferred, I immediate, S split payment). "
        "Codes and labels come from the 1.2.3 schema; it carries no licence statement.",
        IT_TAGS + ["withholding-tax"],
        ["invoicing", "accounts-payable", "payroll-demo"],
        assumed=[IT_REVISION_ASSUMPTION],
    )


def it_field_formats() -> dict:
    raw = load(IT_XSD)
    types = {
        "CodiceDestinatario": "CodiceDestinatarioType",
        "CodiceFiscale": "CodiceFiscaleType",
        "CodiceFiscalePF": "CodiceFiscalePFType",
        "IBAN": "IBANType",
        "BIC": "BICType",
        "CAP": "CAPType",
        "Provincia": "ProvinciaType",
        "Nazione": "NazioneType",
        "Divisa": "DivisaType",
        "Aliquota": "RateType",
        "Importo": "Amount2DecimalType",
        "PrezzoUnitario": "Amount8DecimalType",
    }
    fields = {name: facets(raw, xsd_type) for name, xsd_type in types.items()}
    fpr = load(IT_EXAMPLE_FPR)
    fpa = load(IT_EXAMPLE_FPA)
    b2b_destination = xml_element_text(fpr, "CodiceDestinatario")[0]
    pa_destination = xml_element_text(fpa, "CodiceDestinatario")[0]
    fiscal_code = xml_element_text(fpr, "CodiceFiscale")[0]
    if (len(b2b_destination), len(pa_destination)) != (7, 6):
        raise ValueError("example CodiceDestinatario lengths changed")
    return entry(
        "it-fatturapa-field-formats",
        "Italy FatturaPA field formats: CodiceDestinatario, codice fiscale, IBAN, BIC, CAP and amounts (schema 1.2.3 patterns)",
        "IT", "A", IT_VALID_FROM, "almanac.rules.einvoice_field_format", {"fields": fields},
        [
            {"input": {"field": "CodiceDestinatario", "value": b2b_destination}, "expected": True, "origin": "source", "note": "B2B example invoice, 7 characters"},
            {"input": {"field": "CodiceDestinatario", "value": pa_destination}, "expected": True, "origin": "source", "note": "public administration example invoice, 6 characters"},
            {"input": {"field": "CodiceFiscale", "value": fiscal_code}, "expected": True, "origin": "source"},
            {"input": {"field": "CodiceDestinatario", "value": "abc1234"}, "expected": False, "origin": "derived", "note": "lower case is outside the pattern"},
            {"input": {"field": "CodiceDestinatario", "value": "ABC12345"}, "expected": False, "origin": "derived", "note": "eight characters"},
            {"input": {"field": "CodiceFiscalePF", "value": fiscal_code}, "expected": False, "origin": "derived", "note": "a natural person's code has 16 characters"},
            {"input": {"field": "Aliquota", "value": "22.00"}, "expected": True, "origin": "derived"},
            {"input": {"field": "Importo", "value": "100.5"}, "expected": False, "origin": "derived", "note": "amounts carry exactly two decimals"},
            {"input": {"field": "CAP", "value": "00144"}, "expected": True, "origin": "derived"},
        ],
        [
            it_xsd("simpleType CodiceDestinatarioType, pattern", "[A-Z0-9]{6,7}", 'simpleType name="CodiceDestinatarioType"'),
            it_xsd("simpleType CodiceFiscaleType, pattern", "[A-Z0-9]{11,16}", 'simpleType name="CodiceFiscaleType"'),
            it_xsd("simpleType Amount2DecimalType, pattern", "[0-9]{1,11}\\.[0-9]{2}", 'simpleType name="Amount2DecimalType"'),
            cite(IT_PUBLISHER, "FatturaPA example invoice IT01234567890_FPR01.xml (fattura ordinaria)", IT_EXAMPLE_FPR, "DatiTrasmissione/CodiceDestinatario", f"<CodiceDestinatario>{b2b_destination}</CodiceDestinatario>", "<FormatoTrasmissione>FPR12</FormatoTrasmissione>", role="supporting"),
            cite(IT_PUBLISHER, "FatturaPA example invoice IT01234567890_FPA01.xml (fattura PA)", IT_EXAMPLE_FPA, "DatiTrasmissione/CodiceDestinatario", f"<CodiceDestinatario>{pa_destination}</CodiceDestinatario>", "<FormatoTrasmissione>FPA12</FormatoTrasmissione>", role="supporting"),
            it_spec("section 1.1, CodiceDestinatario", "valore, di 6 caratteri, deve corrispondere a quello presente nel campo", "Amministrazione il suo valore, di 7 caratteri, deve corrispondere a:"),
            it_revision_evidence(),
        ],
        [{"statistic": "count", "expected": len(fields), "tolerance": 0}],
        "Pattern and length facets of selected FatturaPA simple types, read from the 1.2.3 schema and applied as full "
        "matches. CodiceDestinatario routes the invoice through the Sistema di Interscambio: per the specification it has "
        "6 characters (the office code from IndicePA) for a public administration and 7 characters (a code SdI assigns "
        "to a receiving channel) otherwise. CodiceFiscale admits 11 to 16 upper-case letters and digits, CodiceFiscalePF "
        "exactly 16; amounts carry exactly two decimals and unit prices two to eight. The positive vectors are the values "
        "in the example invoices published beside the schema. The schema carries no licence statement.",
        IT_TAGS + ["field-format", "identifier"],
        ["invoicing", "data-quality-validation", "kyb-onboarding"],
        assumed=[IT_REVISION_ASSUMPTION],
    )


IT_SDI = f"{FPA}/Specifiche-tecniche-relative-al-Sistema-di-Interscambio-versione-1.8.4.pdf"
IT_SDI_TITLE = "Specifiche delle regole tecniche di cui all'Allegato B del DM 55 del 3 aprile 2013 (Sistema di Interscambio), versione 1.8.4"


def it_sdi_file_names() -> dict:
    load(IT_SDI)
    text = TEXT[IT_SDI]
    lengths = re.search(r"o (\d+) caratteri \(minimo\) e (\d+) caratteri \(massimo\) nel caso di codice paese IT; o (\d+) caratteri \(minimo\) e (\d+) caratteri \(massimo\) altrimenti", text)
    progressive = int(re.search(r"stringa alfanumerica di lunghezza massima di (\d+) caratteri", text).group(1))
    signed = re.search(r"assume il valore .(\.xml). \(per la firma XAdES\) oppure .(\.xml\.p7m). \(per la firma CAdES\)", text)
    archive = re.search(r"del file può essere solo (\.zip)", text).group(1)
    version_date = re.search(r"\[versione 1\.8\.4\] (\d{2})/(\d{2})/(\d{4})", text)
    valid_from = f"{version_date.group(3)}-{version_date.group(2)}-{version_date.group(1)}"
    parameters = {
        "identifier_length": {"IT": [int(lengths.group(1)), int(lengths.group(2))], "other": [int(lengths.group(3)), int(lengths.group(4))]},
        "progressive_max_length": progressive,
        "extensions": [signed.group(1), signed.group(2), archive],
    }
    examples = ["ITAAABBB99T99X999W_00001.xml", "IT99999999999_00002.xml.p7m", "ITAAABBB99T99X999W_00004.xml.p7m"]
    for example in examples:
        if example not in text:
            raise ValueError(f"example {example} not in the specification")

    def sdi(locator: str, value: str, snippet: str) -> dict:
        return cite(IT_PUBLISHER, IT_SDI_TITLE, IT_SDI, locator, value, snippet)

    return entry(
        "it-sdi-invoice-file-name-rule",
        "Italy Sistema di Interscambio invoice file name rule (country, tax identifier, progressive, extension)",
        "IT", "B", valid_from, "almanac.rules.it_sdi_file_name", parameters,
        [
            {"input": {"name": examples[0]}, "expected": True, "origin": "source", "note": "XAdES-signed example"},
            {"input": {"name": examples[1]}, "expected": True, "origin": "source", "note": "CAdES-signed example"},
            {"input": {"name": examples[2]}, "expected": True, "origin": "source"},
            {"input": {"name": examples[1], "part": "progressive"}, "expected": "00002", "origin": "source"},
            {"input": {"name": "IT01234567890_FPA01.xml"}, "expected": True, "origin": "source", "note": "name of an example invoice published on fatturapa.gov.it"},
            {"input": {"name": "IT01234567890_000001.xml"}, "expected": False, "origin": "derived", "note": "progressive longer than five characters"},
            {"input": {"name": "IT0123456789_00001.xml"}, "expected": False, "origin": "derived", "note": "ten-character Italian identifier"},
            {"input": {"name": "DE123456789_00001.xml"}, "expected": True, "origin": "derived"},
            {"input": {"name": "IT01234567890-00001.xml"}, "expected": False, "origin": "derived", "note": "the separator must be an underscore"},
            {"input": {"name": "IT01234567890_00001.pdf"}, "expected": False, "origin": "derived"},
        ],
        [
            sdi("page 9, section 2.2", "o 11 caratteri (minimo) e 16 caratteri (massimo) nel caso di codice paese IT;", "o 2 caratteri (minimo) e 28 caratteri (massimo) altrimenti;"),
            sdi("page 9, section 2.2", f"alfanumerica di lunghezza massima di {progressive} caratteri", "con valor i ammessi [a-z], [A-Z], [0-9]."),
            sdi("page 9, section 2.2", "(per la firma XAdES) oppure", "l’estensione del file assume il valore"),
            sdi("page 10, section 2.2 examples", "IT99999999999_00002.xml.p7m", "Il separatore tra il secondo ed il terzo elemento del nome file è il carattere underscore"),
            sdi("page footer", "[versione 1.8.4] 31/03/2026", "Specifiche delle regole tecniche di cui all’Allegato B del DM 55 del 3 aprile 2013"),
        ],
        [
            {"statistic": "count[extensions]", "expected": len(parameters["extensions"]), "tolerance": 0},
            {"statistic": "value[progressive_max_length]", "expected": progressive, "tolerance": 0},
        ],
        "Every file sent to the Sistema di Interscambio is named country code, transmitter tax identifier, underscore, "
        "a unique progressive of up to five letters or digits, and an extension: .xml when XAdES-signed, .xml.p7m when "
        "CAdES-signed, or .zip for an archive whose members follow the same rule. The identifier is 11 to 16 characters "
        "for country IT, where it is the transmitter's codice fiscale, and 2 to 28 for a foreign tax identifier. "
        "The progressive only needs to make the "
        "name unique for that transmitter. valid_from is the date of specification 1.8.4's revision as printed in its "
        "footer. The specification carries no licence statement.",
        IT_TAGS + ["file-name", "field-format"],
        ["invoicing", "data-quality-validation"],
        assumed=[{"parameter": "identifier characters", "value": "[A-Za-z0-9]", "method": "assumed", "rationale": "The specification gives the identifier's length but not its alphabet; tax identifiers are letters and digits."}],
    )


# ---------------------------------------------------------------- Peppol

CODELIST_NS = "{urn:fdc:difi.no:2017:vefa:structure:CodeList-1}"


def peppol_codes(file_name: str) -> dict[str, str]:
    root = ET.fromstring(load(f"{PEPPOL_CODELIST}/{file_name}"))
    return {collapse(code.findtext(f"{CODELIST_NS}Id")): collapse(code.findtext(f"{CODELIST_NS}Name")) for code in root.iter(f"{CODELIST_NS}Code")}


def peppol(file_name: str, locator: str, value: str, snippet: str) -> dict:
    return cite(PEPPOL_PUBLISHER, f"{PEPPOL_BIS_TITLE}, {file_name}", f"{PEPPOL_CODELIST}/{file_name}", locator, value, snippet)


def peppol_release_evidence() -> dict:
    return cite(PEPPOL_PUBLISHER, "Peppol BIS Billing 3.0 release notes, version 3.0.21", PEPPOL_NOTES, "header", "Mandatory to use from: 2026-08-17", "Date of publication: 2026-05-20", role="supporting")


def peppol_licence_evidence() -> dict:
    return cite(PEPPOL_PUBLISHER, "Peppol BIS Billing 3.0, introduction (copyright statement)", PEPPOL_INTRO, "copyright paragraph", "OpenPeppol AISBL holds the copyright of this Peppol BIS", "allowing derivate works to be developed and distributed with no additional licensing requirements", role="supporting")


PEPPOL_TAGS = ["peppol", "en-16931", "ubl"]
PEPPOL_LICENCE_NOTE = (
    " OpenPeppol states it holds the copyright of the BIS and that the EC-CEN agreement allows derivative works with no "
    "additional licensing requirements; no SPDX licence is named, so the entry stays at license-review."
)


def peppol_vat_categories() -> dict:
    sets = {"vat_category": peppol_codes("UNCL5305.xml"), "vat_exemption_reason": peppol_codes("VATEX.xml")}
    return entry(
        "global-peppol-vat-category-and-exemption-reason-codes",
        "Peppol BIS Billing 3.0 VAT category codes (UNCL5305 subset) and VATEX exemption reason codes",
        "global", "A", PEPPOL_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("vat_category", "S"),
            member("vat_category", "AE"),
            member("vat_category", "K"),
            member("vat_category", "B", note="Italian split payment, allowed for Italy only"),
            member("vat_category", "H", False, "derived", "in UNCL5305 but outside the Peppol subset"),
            member("vat_exemption_reason", "VATEX-EU-AE"),
            member("vat_exemption_reason", "VATEX-EU-132-1A"),
        ],
        [
            peppol("UNCL5305.xml", "Code AE", "Vat Reverse Charge", "Duty or tax or fee category code (Subset of UNCL5305)"),
            peppol("VATEX.xml", "Code VATEX-EU-132-1A", "VATEX-EU-132-1A", "Exempt based on article 132, section 1 (a) of Council Directive 2006/112/EC"),
            peppol_release_evidence(),
            peppol_licence_evidence(),
        ],
        count_tests(sets),
        "VAT category codes a Peppol BIS Billing 3.0 invoice may use in BT-118 and BT-151 (the OpenPeppol subset of UN/CEFACT "
        "5305, D.16B: S standard, Z zero, E exempt, AE reverse charge, K intra-community, G export, O outside scope, L and M "
        "for the Canary Islands and Ceuta and Melilla, B for Italian split payment), and the VATEX exemption reason codes "
        "for BT-121, from the code-list files of release 3.0.21 at a pinned commit of the OpenPeppol repository." + PEPPOL_LICENCE_NOTE,
        PEPPOL_TAGS + ["vat", "vat-exemption"],
        ["invoicing", "accounts-payable", "audit-demo"],
    )


def peppol_invoice_types() -> dict:
    invoice = peppol_codes("UNCL1001-inv.xml")
    credit = peppol_codes("UNCL1001-cn.xml")
    sch = load(PEPPOL_SCH).decode("utf-8")
    allowed = {}
    for rule in ("P0100", "P0101"):
        match = re.search(rf'id="PEPPOL-EN16931-{rule}" test="\s*not\(\$profile = \(\'01\',\'02\'\)\) or \(some \$code in tokenize\(\'([0-9 ]+)\'', sch)
        allowed[rule] = match.group(1).split()
    rows = {}
    for document, codes, rule in (("invoice", invoice, "P0100"), ("credit_note", credit, "P0101")):
        for code, name in codes.items():
            rows[code] = {"name": name, "document": document, "allowed_in_billing_profiles_01_02": code in allowed[rule]}
    return entry(
        "global-peppol-invoice-and-credit-note-type-codes",
        "Peppol BIS Billing 3.0 invoice and credit note type codes (UNCL1001 subsets) with profile restrictions",
        "global", "A", PEPPOL_VALID_FROM, "almanac.rules.lookup_table", {"rows": rows},
        [
            {"input": {"key": "380", "column": "name"}, "expected": invoice["380"], "origin": "source"},
            {"input": {"key": "381", "column": "document"}, "expected": "credit_note", "origin": "source"},
            {"input": {"key": "388", "column": "allowed_in_billing_profiles_01_02"}, "expected": True, "origin": "source"},
            {"input": {"key": "389", "column": "allowed_in_billing_profiles_01_02"}, "expected": "389" in allowed["P0100"], "origin": "source", "note": "self-billed invoice, absent from rule P0100's token list"},
            {"input": "385", "expected": False, "origin": "derived"},
        ],
        [
            peppol("UNCL1001-inv.xml", "Code 380", "Commercial invoice", "Invoice type code (UNCL1001 subset)"),
            peppol("UNCL1001-cn.xml", "Code 381", "Credit note", "Credit note type code (UNCL1001 subset)"),
            cite(PEPPOL_PUBLISHER, "Peppol BIS Billing 3.0.21 UBL schematron, PEPPOL-EN16931-UBL.sch", PEPPOL_SCH, "assert PEPPOL-EN16931-P0100", " ".join(allowed["P0100"]), "Invoice type code MUST be set according to the profile."),
            cite(PEPPOL_PUBLISHER, "Peppol BIS Billing 3.0.21 UBL schematron, PEPPOL-EN16931-UBL.sch", PEPPOL_SCH, "assert PEPPOL-EN16931-P0101", " ".join(allowed["P0101"]), "Credit note type code MUST be set according to the profile."),
            cite(PEPPOL_PUBLISHER, "Peppol BIS Billing 3.0 release notes, version 3.0.21-hotfix", PEPPOL_HOTFIX, "Changes to code lists and validation artefacts", "Invoice type code 384 (Corrected invoice) is allowed when both buyer and seller are German organizations or both are Slovak organizations.", "Invoice type codes 326 (Partial invoice) and 389 (Self-billed invoice) are only allowed when both buyer and seller are German organizations.", role="supporting"),
            peppol_release_evidence(),
            peppol_licence_evidence(),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        "Document type codes for BT-3 in a Peppol BIS Billing 3.0 invoice (UNCL1001 invoice subset: 380 commercial "
        "invoice, 383 debit note, 384 corrected, 386 prepayment, 389 self-billed and others) and credit note (81, 83, 381, "
        "396, 532). allowed_in_billing_profiles_01_02 records whether the code appears in the token list of schematron "
        "rule P0100 or P0101, which binds the billing profiles; the 3.0.21 hotfix further limits 326 and 389 to German "
        "trading partners and 384 to German or Slovak pairs, which this table does not encode." + PEPPOL_LICENCE_NOTE,
        PEPPOL_TAGS + ["document-type"],
    )


def peppol_payment_means() -> dict:
    sets = {"payment_means": peppol_codes("UNCL4461.xml")}
    return entry(
        "global-peppol-payment-means-codes",
        "Peppol BIS Billing 3.0 payment means codes (UNCL4461, D.16B)",
        "global", "A", PEPPOL_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("payment_means", "30"),
            member("payment_means", "58"),
            member("payment_means", "59"),
            member("payment_means", "ZZZ"),
            member("payment_means", "71", False, "derived", "the list jumps from 70 to 74"),
        ],
        [
            peppol("UNCL4461.xml", "Code 58", "SEPA credit transfer", "Payment means code (UNCL4461)"),
            peppol("UNCL4461.xml", "Code 59", "SEPA direct debit", "Automated clearing house credit"),
            peppol_release_evidence(),
            peppol_licence_evidence(),
        ],
        count_tests(sets),
        "UN/CEFACT 4461 payment means codes accepted in BT-81 of a Peppol BIS Billing 3.0 invoice, with their names: 30 "
        "credit transfer, 31 debit transfer, 48 bank card, 49 direct debit, 58 SEPA credit transfer, 59 SEPA direct debit, "
        "ZZZ mutually defined, and the rest of D.16B, from the release 3.0.21 code-list file at a pinned commit." + PEPPOL_LICENCE_NOTE,
        PEPPOL_TAGS + ["payment-method"],
        ["invoicing", "accounts-payable", "payments-demo", "payments-reconciliation"],
    )


def peppol_address_schemes() -> dict:
    sets = {"eas": peppol_codes("eas.xml"), "icd": peppol_codes("icd.xml")}
    return entry(
        "global-peppol-electronic-address-scheme-and-icd-codes",
        "Peppol BIS Billing 3.0 electronic address schemes (EAS) and ISO 6523 ICD codes",
        "global", "A", PEPPOL_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("eas", "0088"),
            member("eas", "0208"),
            member("eas", "9930"),
            member("icd", "0002"),
            member("icd", "0060"),
            member("eas", "88", False, "derived", "scheme identifiers keep their leading zeros"),
        ],
        [
            peppol("eas.xml", "Code 0088", "Global Location Number", "Electronic Address Scheme (EAS)"),
            peppol("icd.xml", "Code 0060", "Data Universal Numbering System (D-U-N-S Number)", "ISO 6523 ICD list"),
            peppol_release_evidence(),
            peppol_licence_evidence(),
        ],
        count_tests(sets),
        "Scheme identifiers for electronic addresses (BT-34 and BT-49 schemeID: the EAS list, mostly ISO 6523 ICD values "
        "plus 99xx national schemes such as 9930 for German VAT numbers) and for party identifiers (the ISO 6523 ICD list "
        "used for BT-29, BT-46 and similar). Names are as the code-list files of release 3.0.21 give them." + PEPPOL_LICENCE_NOTE,
        PEPPOL_TAGS + ["identifier", "iso-6523"],
        ["invoicing", "kyb-onboarding", "company-generation"],
    )


def peppol_units() -> dict:
    sets = {"unit_of_measure": peppol_codes("UNECERec20-11e.xml")}
    return entry(
        "global-peppol-unit-of-measure-codes",
        "Peppol BIS Billing 3.0 unit of measure codes (UN/ECE Recommendation 20 with X-prefixed Recommendation 21)",
        "global", "A", PEPPOL_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("unit_of_measure", "C62"),
            member("unit_of_measure", "HUR"),
            member("unit_of_measure", "KGM"),
            member("unit_of_measure", "XBX", note="Recommendation 21 package code, X-prefixed"),
            member("unit_of_measure", "kgm", False, "derived", "codes are case sensitive"),
        ],
        [
            peppol("UNECERec20-11e.xml", "Code C62", "<Id>C62</Id>", "Recommendation 20, including Recommendation 21 codes - prefixed with X (UN/ECE)"),
            peppol("UNECERec20-11e.xml", "Code KGM", "<Id>KGM</Id>", "<Name>kilogram</Name>"),
            peppol_release_evidence(),
            peppol_licence_evidence(),
        ],
        count_tests(sets),
        "Unit codes accepted for invoiced quantities (BT-130, BT-150) in Peppol BIS Billing 3.0: UN/ECE Recommendation 20 "
        "revision 11e plus the Recommendation 21 package codes prefixed with X, with their English names, from the "
        "code-list file of release 3.0.21. C62 is the unit 'one', HUR hour, KGM kilogram." + PEPPOL_LICENCE_NOTE,
        PEPPOL_TAGS + ["unit-of-measure"],
        ["invoicing", "retail-demo", "logistics"],
    )


def peppol_scheme_rows() -> tuple[dict, list[dict]]:
    data = json.loads(load(PEPPOL_SCHEMES))
    rows = {}
    for value in data["values"]:
        regex = None
        for line in (value.get("validation-rules") or "").splitlines():
            if line.startswith("RegEx: "):
                regex = line[len("RegEx: ") :].strip()
        rows[value["iso6523"]] = {
            "scheme_id": value["schemeid"],
            "country": value["country"],
            "scheme_name": value["scheme-name"],
            "state": value["state"],
            "registrable": value.get("registrable"),
            "regex": regex,
            "examples": [e.strip() for e in (value.get("examples") or "").splitlines() if e.strip()],
        }
    if len(rows) != data["entry-count"]:
        raise ValueError("participant identifier scheme count mismatch")
    return rows, data["values"]


def peppol_participant_schemes() -> dict:
    rows, _ = peppol_scheme_rows()
    active = sum(1 for r in rows.values() if r["state"] == "active")
    return entry(
        "global-peppol-participant-identifier-schemes",
        "Peppol participant identifier schemes, code list 9.7 (ISO 6523 ICD, country, state, validation pattern)",
        "global", "A", "2025-02-06", "almanac.rules.lookup_table", {"version": "9.7", "rows": rows},
        [
            {"input": {"key": "0088", "column": "scheme_id"}, "expected": rows["0088"]["scheme_id"], "origin": "source"},
            {"input": {"key": "0002", "column": "regex"}, "expected": "[0-9]{9}([0-9]{5})?", "origin": "source"},
            {"input": {"key": "0007", "column": "country"}, "expected": "SE", "origin": "source"},
            {"input": {"key": "9959", "column": "state"}, "expected": rows["9959"]["state"], "origin": "source"},
            {"input": "0001", "expected": False, "origin": "derived"},
        ],
        [
            cite(PEPPOL_PUBLISHER, "Peppol Code Lists - Participant identifier schemes v9.7 (JSON)", PEPPOL_SCHEMES, "values[iso6523=0002]", "RegEx: [0-9]{9}([0-9]{5})?", '"schemeid":"FR:SIRENE"'),
            cite(PEPPOL_PUBLISHER, "Peppol Code Lists - Participant identifier schemes v9.7 (JSON)", PEPPOL_SCHEMES, "header", '"entry-count":105', '"version":"9.7"'),
            cite(PEPPOL_PUBLISHER, "Peppol Policy for use of Identifiers 4.4.0 (2025-02-06)", PEPPOL_POLICY, "page 17, POLICY 4 and 6", 'Rows with the state "removed" MUST NOT be used at all.', 'Code List rows with the state "deprecated" MUST NOT be used for newly exchanged', role="supporting"),
        ],
        [
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[0088,country]", "expected": rows["0088"]["country"], "tolerance": 0},
        ],
        f"The participant identifier schemes Peppol eDelivery accepts, keyed by ISO 6523 ICD: the Peppol scheme id (such "
        f"as FR:SIRENE or GLN), country, scheme name, state, whether it may be registered in the SML, the validation regular "
        f"expression where the list gives one and the published example values. {active} of the {len(rows)} rows are "
        f"active; per the identifier policy, deprecated rows must not be used for new exchanges and removed rows not at all. "
        f"valid_from is the date of the policy version that governs the list; the code list JSON carries no date of its own. "
        f"No licence is stated, so the entry stays at license-review.",
        PEPPOL_TAGS + ["identifier", "iso-6523", "participant-identifier"],
        ["invoicing", "kyb-onboarding", "company-generation"],
        assumed=[{"parameter": "valid_from", "value": "2025-02-06", "method": "derived", "rationale": "Date of the Peppol Policy for use of Identifiers 4.4.0 that defines the code list; the v9.7 JSON has no date field."}],
    )


def peppol_participant_format() -> dict:
    rows, _ = peppol_scheme_rows()
    lines = TEXT[PEPPOL_POLICY] if PEPPOL_POLICY in TEXT else (load(PEPPOL_POLICY) and TEXT[PEPPOL_POLICY])
    meta = re.search(r"The Peppol Participant Identifier Meta Scheme is: \d* ?([a-z0-9-]+)", lines).group(1)
    limits = re.search(r"Participant Identifiers should adhere to the following constraints: \d+ ▪ MUST be at least (\d+) character long \(excluding the numeric identifier scheme\) \d+ ▪ MUST NOT be more than (\d+) characters long", lines)
    example = re.search(r"The Participant Identifier (\d{4}:[0-9a-z]+) with the Meta Scheme", lines).group(1)
    hashed = re.search(r"encoded into the \d+ following identifier: \d+ ([A-Z2-7]{52})\.iso6523-actorid-\d+ upis\.edelivery\.tech\.ec\.europa\.eu\.", lines).group(1)
    parameters = {
        "meta_scheme": meta,
        "min_value_length": int(limits.group(1)),
        "max_value_length": int(limits.group(2)),
        "value_pattern": "[A-Za-z0-9._~-]+",
        "active_icd": sorted(code for code, row in rows.items() if row["state"] == "active"),
    }
    zone = "edelivery.tech.ec.europa.eu."
    return entry(
        "global-peppol-participant-identifier-format",
        "Peppol participant identifier format and SML DNS name (Policy for use of Identifiers 4.4.0)",
        "global", "B", "2025-02-06", "almanac.rules.peppol_participant_id", parameters,
        [
            {"input": {"sml_hash": example}, "expected": hashed, "origin": "source", "note": "POLICY 7 worked example"},
            {"input": {"sml_hash": example.upper()}, "expected": hashed, "origin": "source", "note": "the policy states 0088:123ABC gives the same result"},
            {"input": {"dns_name": example, "zone": zone}, "expected": f"{hashed}.{meta}.{zone}", "origin": "source"},
            {"input": {"identifier": "0088:7300010000001"}, "expected": True, "origin": "source", "note": "POLICY 8 example 1"},
            {"input": {"identifier": "0002:542034942"}, "expected": True, "origin": "source", "note": "POLICY 8 example 2"},
            {"input": {"identifier": f"{meta}::0088:7300010000001"}, "expected": True, "origin": "derived"},
            {"input": {"identifier": "0088:"}, "expected": False, "origin": "derived", "note": "empty value"},
            {"input": {"identifier": "0088:" + "1" * 131}, "expected": False, "origin": "derived", "note": "over the length limit"},
            {"input": {"identifier": "0088:73000 10000001"}, "expected": False, "origin": "derived", "note": "space is not a permitted character"},
            {"input": {"identifier": "1234:abc"}, "expected": False, "origin": "derived", "note": "ICD not in the code list"},
        ],
        [
            cite(PEPPOL_PUBLISHER, "Peppol Policy for use of Identifiers 4.4.0 (2025-02-06)", PEPPOL_POLICY, "page 17, POLICY 5", meta, "The Peppol Participant Identifier Meta Scheme is:"),
            cite(PEPPOL_PUBLISHER, "Peppol Policy for use of Identifiers 4.4.0 (2025-02-06)", PEPPOL_POLICY, "page 14, POLICY 1", f"MUST NOT be more than {parameters['max_value_length']} characters long", "character (.), the underscore character (_) or the tilde character (~) from the invariant"),
            cite(PEPPOL_PUBLISHER, "Peppol Policy for use of Identifiers 4.4.0 (2025-02-06)", PEPPOL_POLICY, "page 18, POLICY 7 example", hashed, "Is the string representation of the SHA-256 hash value, of the"),
            cite(PEPPOL_PUBLISHER, "Peppol Policy for use of Identifiers 4.4.0 (2025-02-06)", PEPPOL_POLICY, "page 19, POLICY 8 examples", ">0088:7300010000001</ParticipantIdentifier>", ">0002:542034942</ParticipantIdentifier>"),
            cite(PEPPOL_PUBLISHER, "Peppol Code Lists - Participant identifier schemes v9.7 (JSON)", PEPPOL_SCHEMES, "values[].state", '"state":"active"', '"version":"9.7"'),
        ],
        [
            {"statistic": "count[active_icd]", "expected": len(parameters["active_icd"]), "tolerance": 0},
            {"statistic": "value[max_value_length]", "expected": parameters["max_value_length"], "tolerance": 0},
        ],
        "A Peppol participant identifier is an ISO 6523 ICD and a value joined by a colon (for example 0088 and a GLN), "
        "under the meta scheme iso6523-actorid-upis. Policy 1 limits the value, excluding the ICD, to 1 to 130 letters, "
        "digits, minus, period, underscore or tilde; Policy 2 makes values case insensitive. Policy 7 publishes each "
        "participant in the SML under a DNS label made of the unpadded Base32 SHA-256 digest of the lowercased "
        "identifier, which the vectors check against the policy's own worked example. active_icd is the set of ICD "
        "values with state active in code list 9.7. No licence is stated, so the entry stays at license-review.",
        PEPPOL_TAGS + ["identifier", "participant-identifier", "hash"],
        ["invoicing", "kyb-onboarding", "data-quality-validation"],
        assumed=[{"parameter": "value_pattern", "value": "[A-Za-z0-9._~-]+", "method": "derived", "rationale": "Policy 1 lists the permitted characters in prose; the pattern restates that list as a regular expression."}],
    )


# ---------------------------------------------------------------- Poland


def pl_xsd(locator: str, value: str, snippet: str) -> dict:
    return cite(PL_PUBLISHER, PL_XSD_TITLE, PL_XSD, locator, value, snippet)


def pl_validity() -> tuple[str, dict]:
    raw = load(PL_META)
    valid_from = xml_element_text(raw, "Od")[0]
    return valid_from, cite(PL_PUBLISHER, PL_META_TITLE, PL_META, "WaznoscWzoru/Od", f"<meta:Od>{valid_from}</meta:Od>", "FA(3) USTRUKTURYZOWANA FAKTURA VAT")


PL_TAGS = ["ksef", "fa-3", "poland"]


def pl_invoice_types() -> dict:
    raw = load(PL_XSD)
    sets = {"rodzaj_faktury": enumerations(raw, "TRodzajFaktury"), "typ_korekty": enumerations(raw, "TTypKorekty")}
    valid_from, validity = pl_validity()
    return entry(
        "pl-ksef-fa3-invoice-type-codes",
        "Poland KSeF FA(3) RodzajFaktury invoice types and TypKorekty correction types",
        "PL", "A", valid_from, "almanac.rules.enumeration", {"sets": sets},
        [
            member("rodzaj_faktury", "VAT"),
            member("rodzaj_faktury", "KOR"),
            member("rodzaj_faktury", "ZAL"),
            member("rodzaj_faktury", "KOR_ROZ"),
            member("typ_korekty", "1"),
            member("rodzaj_faktury", "vat", False, "derived", "codes are upper case"),
        ],
        [
            pl_xsd("simpleType TRodzajFaktury", 'value="KOR_ZAL"', "Faktura podstawowa"),
            pl_xsd("simpleType TTypKorekty", 'value="3"', "Korekta skutkująca w dacie ujęcia faktury pierwotnej"),
            validity,
        ],
        count_tests(sets),
        "Invoice kinds for the RodzajFaktury element of a KSeF structured invoice in the FA(3) schema: VAT basic invoice, "
        "KOR corrective invoice, ZAL advance-payment invoice, ROZ the invoice of art. 106f(3) of the VAT act, UPR the "
        "invoice of art. 106e(5)(3), and KOR_ZAL and KOR_ROZ correcting those; and TypKorekty, the date from which a "
        "correction takes effect. Labels are the "
        "Polish annotations of the schema. valid_from is the validity date the signed FA(3) metadata record gives. The "
        "repository states no licence, so the entry stays at license-review.",
        PL_TAGS + ["document-type"],
    )


def pl_vat_rates() -> dict:
    raw = load(PL_XSD)
    codes = enumerations(raw, "TStawkaPodatku")
    valid_from, validity = pl_validity()
    sets = {"stawka_podatku": codes}
    numeric = sorted((int(c) for c in codes if c.isdigit()), reverse=True)
    return entry(
        "pl-ksef-fa3-vat-rate-codes",
        "Poland KSeF FA(3) P_12 VAT rate values (TStawkaPodatku: numeric rates, 0 KR/WDT/EX, zw, oo, np I/II)",
        "PL", "A", valid_from, "almanac.rules.enumeration", {"sets": sets},
        [
            member("stawka_podatku", "23"),
            member("stawka_podatku", "8"),
            member("stawka_podatku", "5"),
            member("stawka_podatku", "0 WDT"),
            member("stawka_podatku", "zw"),
            member("stawka_podatku", "np I"),
            member("stawka_podatku", "0", False, "derived", "zero rate must say which: 0 KR, 0 WDT or 0 EX"),
            member("stawka_podatku", "23%", False, "derived", "values carry no percent sign"),
        ],
        [
            pl_xsd("simpleType TStawkaPodatku", 'value="23"', "Stawka podatku"),
            pl_xsd("simpleType TStawkaPodatku, 0 WDT", 'value="0 WDT"', "Stawka 0% w przypadku wewnątrzwspólnotowej dostawy towarów (WDT)"),
            pl_xsd("element P_12", 'name="P_12" type="tns:TStawkaPodatku"', "Stawka podatku. Pole opcjonalne dla przypadków określonych w art. 106e ust. 2, 3, ust. 4 pkt 3"),
            validity,
        ],
        count_tests(sets),
        f"Values allowed in P_12, the VAT rate of an invoice line in a KSeF FA(3) invoice. The numeric values ({', '.join(map(str, numeric))}) "
        "are percentages and the schema gives them no label, so their label is empty; the others are annotated: 0 KR "
        "domestic zero rate, 0 WDT intra-community supply, 0 EX export, zw exempt, oo reverse charge, np I and np II "
        "not subject to Polish VAT. A plain 0 is not a valid value. The repository states no licence, so the entry stays "
        "at license-review.",
        PL_TAGS + ["vat", "tax-rates"],
        ["invoicing", "accounts-payable", "retail-demo"],
    )


def pl_payment_and_procedure_codes() -> dict:
    raw = load(PL_XSD)
    sets = {
        "forma_platnosci": enumerations(raw, "TFormaPlatnosci"),
        "rodzaj_transportu": enumerations(raw, "TRodzajTransportu"),
        "gtu": enumerations(raw, "TGTU"),
        "oznaczenie_procedury": enumerations(raw, "TOznaczenieProcedury"),
    }
    valid_from, validity = pl_validity()
    return entry(
        "pl-ksef-fa3-payment-transport-gtu-and-procedure-codes",
        "Poland KSeF FA(3) payment form, transport mode, GTU goods group and procedure marking codes",
        "PL", "A", valid_from, "almanac.rules.enumeration", {"sets": sets},
        [
            member("forma_platnosci", "6"),
            member("forma_platnosci", "1"),
            member("rodzaj_transportu", "3"),
            member("gtu", "GTU_01"),
            member("gtu", "GTU_13"),
            member("oznaczenie_procedury", "TT_D"),
            member("forma_platnosci", "8", False, "derived"),
            member("gtu", "GTU_14", False, "derived"),
        ],
        [
            pl_xsd("simpleType TFormaPlatnosci", 'value="6"', "Przelew"),
            pl_xsd("simpleType TRodzajTransportu", 'value="3"', "Transport drogowy"),
            pl_xsd("simpleType TGTU", 'value="GTU_13"', 'simpleType name="TGTU"'),
            pl_xsd("simpleType TOznaczenieProcedury", 'value="B_MPV_PROWIZJA"', 'simpleType name="TOznaczenieProcedury"'),
            validity,
        ],
        count_tests(sets),
        "Four FA(3) vocabularies: FormaPlatnosci payment forms (1 cash, 2 card, 3 voucher, 4 cheque, 5 credit, 6 transfer, "
        "7 mobile); RodzajTransportu transport modes; the GTU_01 to GTU_13 goods and services group markings of the VAT "
        "records regulation; and the procedure markings (WSTO_EE, IED, TT_D, I_42, I_63, B_SPV and others). Labels are the "
        "Polish annotations of the schema. The repository states no licence, so the entry stays at license-review.",
        PL_TAGS + ["payment-method", "gtu"],
        ["invoicing", "accounts-payable", "payments-demo", "logistics"],
    )


# ---------------------------------------------------------------- Spain

BOE_NOISE = re.compile(r"^(BOLETÍN OFICIAL DEL ESTADO|Núm\. 260 |cve: BOE-|Verificable en https://www\.boe\.es|Valores Descripción)")
BOE_ROW = re.compile(r"^(1\.0|[A-Z]\d|\d{2}|[A-Z])(?: (.*))?$")


def boe_lists() -> dict[str, dict[str, str]]:
    """The code lists of section 6 of the annex, keyed by list id, each code with its description."""
    lines = pdf_lines(ES_BOE)
    start = next(i for i, line in enumerate(lines) if " ".join(line.split()).startswith("6. Listas empleadas"))
    lists: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    last: str | None = None
    for raw_line in lines[start + 1 :]:
        line = raw_line.strip()
        if not line or BOE_NOISE.match(line):
            continue
        header = re.fullmatch(r"L(\d+[A-Z]?)", line)
        if header:
            current, last = {}, None
            lists[f"L{header.group(1)}"] = current
            continue
        if current is None:
            continue
        if line.startswith("Nota:"):
            current, last = None, None
            continue
        row = BOE_ROW.match(line)
        if row and (row.group(2) is not None or last is None or current[last]):
            last = row.group(1)
            current[last] = (row.group(2) or "").strip()
        elif last is not None:
            current[last] = f"{current[last]} {line}".strip()
    return lists


def es_cite(locator: str, value: str, snippet: str) -> dict:
    return cite(ES_PUBLISHER, ES_TITLE, ES_BOE, locator, value, snippet)


ES_ASSUMED = [
    {
        "parameter": "valid_from",
        "value": ES_VALID_FROM,
        "method": "derived",
        "rationale": "The order enters into force the day after its publication in the BOE on 28 October 2024; when invoicing systems must comply is set separately by Real Decreto 1007/2023 and its amendments.",
    }
]
ES_IN_FORCE = ("final provision", "La presente orden entrará en vigor el día siguiente al de su publicación", "Núm. 260 Lunes 28 de octubre de 2024")
ES_TAGS = ["verifactu", "aeat", "spain"]


def es_invoice_types() -> dict:
    lists = boe_lists()
    sets = {"tipo_factura": lists["L2"], "tipo_rectificativa": lists["L3"]}
    return entry(
        "es-verifactu-invoice-type-codes",
        "Spain VERI*FACTU TipoFactura (F1, F2, F3, R1 to R5) and TipoRectificativa codes, Orden HAC/1177/2024",
        "ES", "B", ES_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("tipo_factura", "F1"),
            member("tipo_factura", "F2"),
            member("tipo_factura", "R5"),
            member("tipo_rectificativa", "S"),
            member("tipo_rectificativa", "I"),
            member("tipo_factura", "R6", False, "derived"),
        ],
        [
            es_cite("annex section 6, list L2 (page 137556)", "F1 Factura (art. 6, 7.2 y 7.3 del RD 1619/2012).", "F2 Factura Simplificada y Facturas sin identificación del destinatario art. 6.1.d) RD 1619/2012."),
            es_cite("annex section 6, list L3", "S Por sustitución.", "I Por diferencias."),
            es_cite("annex section 2, RegistroAlta fields", "TipoFactura1 Especificación del tipo de factura", "sustitución o por diferencia. Alfanumérico (1) L3"),
            es_cite(*ES_IN_FORCE),
        ],
        count_tests(sets),
        "Invoice types for the TipoFactura field of a VERI*FACTU invoicing record (list L2 of the annex to Orden "
        "HAC/1177/2024): F1 full invoice, F2 simplified invoice, F3 invoice replacing simplified ones, R1 to R4 corrective "
        "invoices by legal ground, R5 corrective simplified invoice; and list L3 for TipoRectificativa (S by substitution, "
        "I by differences). Descriptions are as printed in the BOE. The BOE states no licence on the document, so the "
        "entry stays at license-review.",
        ES_TAGS + ["document-type"],
        assumed=ES_ASSUMED,
    )


def es_regime_keys() -> dict:
    lists = boe_lists()
    sets = {"clave_regimen_iva": lists["L8A"], "clave_regimen_igic": lists["L8B"]}
    return entry(
        "es-verifactu-regime-key-codes",
        "Spain VERI*FACTU ClaveRegimen codes for VAT (L8A) and Canary Islands IGIC (L8B), Orden HAC/1177/2024",
        "ES", "B", ES_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("clave_regimen_iva", "01"),
            member("clave_regimen_iva", "02"),
            member("clave_regimen_iva", "20"),
            member("clave_regimen_igic", "17"),
            member("clave_regimen_igic", "20", False, "source", "L8B ends at 19"),
            member("clave_regimen_iva", "12", False, "derived", "the list jumps from 11 to 14"),
        ],
        [
            es_cite("annex section 6, list L8A", "20 Régimen simplificado", "Descripción de la clave de régimen para desgloses donde el impuesto de aplicación es el IVA"),
            es_cite("annex section 6, list L8B", "19 Operaciones interiores exentas por aplicación artículo 25 Ley 19/1994.", "Descripción de la clave de régimen para desgloses donde el impuesto de aplicación es el IGIC"),
            es_cite("annex section 2, Desglose fields", "ClaveRegimen Clave que identificará el tipo de régimen del impuesto", "o una operación con trascendencia tributaria. Alfanumérico (2) L8A/L8B"),
            es_cite(*ES_IN_FORCE),
        ],
        count_tests(sets),
        "Regime keys for the ClaveRegimen field of each tax breakdown in a VERI*FACTU record: list L8A where the tax is "
        "VAT (01 general regime, 02 export, 03 second-hand goods, 07 cash accounting, 17 OSS and IOSS, 18 equivalence "
        "surcharge, 20 simplified regime and the rest) and list L8B where it is the Canary Islands IGIC. Descriptions are "
        "as printed in the BOE. The BOE states no licence on the document, so the entry stays at license-review.",
        ES_TAGS + ["tax-regime", "vat"],
        assumed=ES_ASSUMED,
    )


def es_operation_codes() -> dict:
    lists = boe_lists()
    sets = {"impuesto": lists["L1"], "calificacion_operacion": lists["L9"], "operacion_exenta": lists["L10"], "id_type": lists["L7"]}
    return entry(
        "es-verifactu-tax-operation-and-exemption-codes",
        "Spain VERI*FACTU tax, CalificacionOperacion, OperacionExenta (E1 to E6) and IDType codes, Orden HAC/1177/2024",
        "ES", "B", ES_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("impuesto", "01"),
            member("impuesto", "03"),
            member("calificacion_operacion", "S1"),
            member("calificacion_operacion", "N2"),
            member("operacion_exenta", "E1"),
            member("operacion_exenta", "E6"),
            member("id_type", "02"),
            member("operacion_exenta", "E7", False, "derived"),
            member("impuesto", "04", False, "derived", "list L1 jumps from 03 to 05"),
        ],
        [
            es_cite("annex section 6, list L1", "03 Impuesto General Indirecto Canario (IGIC).", "02 Impuesto sobre la Producción, los Servicios y la Importación (IPSI) de Ceuta y Melilla."),
            es_cite("annex section 6, list L9", "S1 Operación Sujeta y No exenta - Sin inversión del sujeto pasivo.", "N2 Operación No Sujeta por Reglas de localización."),
            es_cite("annex section 6, list L10 (pages 137559 and 137560)", "E6 Exenta por otros.", "E1 Exenta por el artículo 20."),
            es_cite("annex section 6, list L7", "02 NIF-IVA.", "04 Documento oficial de identificación expedido por el país o territorio de residencia."),
            es_cite("annex section 2, Desglose fields", "OperacionExenta1 Campo que especifica la causa de exención.", "Clave de la operación sujeta y no exenta o de la operación no sujeta. Alfanumérico (2) L9"),
            es_cite(*ES_IN_FORCE),
        ],
        count_tests(sets),
        "Code lists for the tax breakdown and party identification of a VERI*FACTU record: L1 for Impuesto (01 VAT, 02 "
        "IPSI of Ceuta and Melilla, 03 IGIC, 05 other); L9 for CalificacionOperacion (S1 and S2 subject and not exempt, "
        "without and with reverse charge, N1 and N2 not subject); L10 for OperacionExenta (E1 to E6 by article of the VAT "
        "law); and L7 for the IDType of a foreign party (02 EU VAT number, 03 passport and others). Descriptions are as "
        "printed in the BOE. The BOE states no licence on the document, so the entry stays at license-review.",
        ES_TAGS + ["vat", "vat-exemption", "identifier"],
        assumed=ES_ASSUMED,
    )


# ---------------------------------------------------------------- Mexico

MX_CATALOGUES = [
    "c_FormaPago", "c_MetodoPago", "c_TipoDeComprobante", "c_Exportacion", "c_ObjetoImp", "c_Impuesto", "c_TipoFactor",
    "c_TipoRelacion", "c_Periodicidad", "c_Meses", "c_RegimenFiscal", "c_UsoCFDI", "c_Moneda",
]
MX_ASSUMED = [
    {
        "parameter": "valid_from",
        "value": MX_VALID_FROM,
        "method": "derived",
        "rationale": "The catalogue schema carries no date; this is the Last-Modified date the SAT server reports for the pinned file, taken as the revision date.",
    }
]
MX_TAGS = ["cfdi", "sat", "mexico"]


def mx_cite(url: str, title: str, locator: str, value: str, snippet: str) -> dict:
    return cite(MX_PUBLISHER, title, url, locator, value, snippet)


def mx_catalogue_codes() -> dict:
    raw = load(MX_CAT)
    sets = {name: enumerations(raw, name) for name in MX_CATALOGUES}
    title = "Catálogos del CFDI versión 4.0, esquema catCFDI.xsd"
    return entry(
        "mx-cfdi-40-catalogue-codes",
        "Mexico SAT CFDI 4.0 catalogue codes: FormaPago, MetodoPago, UsoCFDI, RegimenFiscal, ObjetoImp, Impuesto, Moneda and others",
        "MX", "A", MX_VALID_FROM, "almanac.rules.enumeration", {"sets": sets},
        [
            member("c_FormaPago", "03"),
            member("c_FormaPago", "99"),
            member("c_MetodoPago", "PUE"),
            member("c_MetodoPago", "PPD"),
            member("c_TipoDeComprobante", "I"),
            member("c_UsoCFDI", "G03"),
            member("c_UsoCFDI", "CP01"),
            member("c_RegimenFiscal", "601"),
            member("c_RegimenFiscal", "626"),
            member("c_ObjetoImp", "02"),
            member("c_Impuesto", "002"),
            member("c_Moneda", "MXN"),
            member("c_FormaPago", "07", False, "derived", "the catalogue skips from 06 to 08"),
            member("c_MetodoPago", "PIP", False, "derived"),
        ],
        [
            mx_cite(MX_CAT, title, "simpleType c_FormaPago", '<xs:enumeration value="31"/>', '<xs:simpleType name="c_FormaPago">'),
            mx_cite(MX_CAT, title, "simpleType c_MetodoPago", '<xs:enumeration value="PPD"/>', '<xs:simpleType name="c_MetodoPago">'),
            mx_cite(MX_CAT, title, "simpleType c_UsoCFDI", '<xs:enumeration value="CN01"/>', '<xs:simpleType name="c_UsoCFDI">'),
            mx_cite(MX_CAT, title, "simpleType c_RegimenFiscal", '<xs:enumeration value="626"/>', '<xs:simpleType name="c_RegimenFiscal">'),
            mx_cite(MX_CAT, title, "simpleType c_ObjetoImp", '<xs:enumeration value="08"/>', '<xs:simpleType name="c_ObjetoImp">'),
        ],
        count_tests(sets),
        "The closed CFDI 4.0 catalogues that most invoice fields draw from, exactly as the SAT's catalogue schema enumerates "
        "them: payment forms (c_FormaPago), payment method PUE or PPD (c_MetodoPago), voucher type I, E, T, N or P "
        "(c_TipoDeComprobante), export key, tax object key (c_ObjetoImp), tax codes 001 to 003 (c_Impuesto), "
        "factor type, relation type, periodicity and months for global invoices, tax regimes (c_RegimenFiscal), CFDI uses "
        "(c_UsoCFDI) and currencies (c_Moneda). The schema carries codes only; the descriptions, the regimes each use "
        "allows, the person types and the c_TasaOCuota rate table are published only in catCFDI.xls on "
        "omawww.sat.gob.mx, which was unreachable, so labels are empty. No licence is stated, so the entry stays at "
        "license-review.",
        MX_TAGS + ["payment-method", "tax-regime"],
        ["invoicing", "accounts-payable", "kyb-onboarding"],
        assumed=MX_ASSUMED,
    )


def mx_attribute_catalogues() -> dict:
    raw = load(MX_CFDI)
    root = ET.fromstring(raw)
    rows: dict[str, dict[str, str]] = {}

    def walk(node: ET.Element, path: list[str]) -> None:
        for child in node:
            if child.tag == f"{XS}element" and child.get("name"):
                walk(child, path + [child.get("name")])
            elif child.tag == f"{XS}attribute" and child.get("name"):
                kind = child.get("type") or ""
                if not kind:
                    base = child.find(f"{XS}simpleType/{XS}restriction")
                    kind = base.get("base") if base is not None else ""
                if kind.startswith("catCFDI:"):
                    rows["/".join(path) + "/@" + child.get("name")] = {"catalogue": kind.split(":", 1)[1], "use": child.get("use", "optional")}
            else:
                walk(child, path)

    walk(root, [])
    title = "Esquema del Comprobante Fiscal Digital por Internet versión 4.0, cfdv40.xsd"
    return entry(
        "mx-cfdi-40-attribute-catalogues",
        "Mexico SAT CFDI 4.0 attributes bound to SAT catalogues, with required or optional use (cfdv40.xsd)",
        "MX", "A", MX_CFDI_VALID_FROM, "almanac.rules.lookup_table", {"rows": rows},
        [
            {"input": {"key": "Comprobante/Receptor/@UsoCFDI", "column": "catalogue"}, "expected": "c_UsoCFDI", "origin": "source"},
            {"input": {"key": "Comprobante/Receptor/@RegimenFiscalReceptor", "column": "use"}, "expected": "required", "origin": "source"},
            {"input": {"key": "Comprobante/@MetodoPago", "column": "use"}, "expected": "optional", "origin": "source"},
            {"input": {"key": "Comprobante/@Exportacion", "column": "catalogue"}, "expected": "c_Exportacion", "origin": "source"},
            {"input": "Comprobante/@Folio", "expected": False, "origin": "derived", "note": "free-text attribute, no catalogue"},
        ],
        [
            mx_cite(MX_CFDI, title, "Receptor, attribute UsoCFDI", '<xs:attribute name="UsoCFDI" type="catCFDI:c_UsoCFDI" use="required">', "Atributo requerido para expresar la clave del uso que dará a esta factura el receptor del CFDI."),
            mx_cite(MX_CFDI, title, "Receptor, attribute RegimenFiscalReceptor", '<xs:attribute name="RegimenFiscalReceptor" type="catCFDI:c_RegimenFiscal" use="required">', "Atributo requerido para incorporar la clave del régimen fiscal del contribuyente receptor"),
            mx_cite(MX_CFDI, title, "Comprobante, attribute MetodoPago", '<xs:attribute name="MetodoPago" type="catCFDI:c_MetodoPago" use="optional">', "Atributo condicional para precisar la clave del método de pago"),
            mx_cite(MX_CFDI, title, "Comprobante, attribute Version", '<xs:attribute name="Version" use="required" fixed="4.0">', '<xs:attribute name="Exportacion" type="catCFDI:c_Exportacion" use="required">'),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        "Which attributes of a CFDI 4.0 invoice take their value from a SAT catalogue, keyed by element path and attribute "
        "(for example Comprobante/Receptor/@UsoCFDI), with the catalogue type and whether the schema marks the attribute "
        "required or optional. Optional attributes such as MetodoPago and FormaPago are conditional under the filling "
        "guide, which was not reachable. Read from cfdv40.xsd on www.sat.gob.mx; no licence is stated, so the entry stays "
        "at license-review.",
        MX_TAGS + ["field-rule"],
        ["invoicing", "data-quality-validation"],
        assumed=[
            {
                "parameter": "valid_from",
                "value": MX_CFDI_VALID_FROM,
                "method": "derived",
                "rationale": "cfdv40.xsd carries no date; this is the Last-Modified date the SAT server reports for the pinned file, taken as the revision date.",
            }
        ],
    )


# ---------------------------------------------------------------- India

CRORE_WORDS = {"five hundred": 500, "one hundred": 100, "fifty": 50, "twenty": 20, "ten": 10, "five": 5}
IN_NOTIFICATIONS = [
    ("13/2020", "notfctn-13-central-tax-english-2020.pdf"),
    ("61/2020", "notfctn-61-central-tax-english-2020.pdf"),
    ("88/2020", "notfctn-88-central-tax-english-2020.pdf"),
    ("05/2021", "notfctn-05-central-tax-english-2021.pdf"),
    ("01/2022", "nn_01_2022_english.pdf"),
    ("17/2022", "17-2022-ct-eng_1_1.pdf"),
    ("10/2023", "10ct_eng.pdf"),
]
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def crore(words: str) -> int:
    return CRORE_WORDS[" ".join(words.split())] * 10_000_000


def in_threshold_schedule() -> dict:
    texts = {number: (load(f"{GSTC_FILES}/{name}"), TEXT[f"{GSTC_FILES}/{name}"]) for number, name in IN_NOTIFICATIONS}
    principal = texts["13/2020"][1]
    base = re.search(r"aggregate turnover in a financial year exceeds ([a-z ]+?) rupees", principal).group(1)
    start = re.search(r"This notification shall come into force from the (\d+)st (\w+), (\d{4})", principal)
    start_date = f"{start.group(3)}-{MONTHS[start.group(2)]:02d}-{int(start.group(1)):02d}"
    pre_start = re.search(r"for the words .([a-z ]+) crore rupees., the words .([a-z ]+) crore rupees. shall be substituted", texts["61/2020"][1])
    if crore(base.replace(" crore", "")) != crore(pre_start.group(1)):
        raise ValueError("61/2020 does not amend the principal threshold")
    steps = [{"from": start_date, "value": crore(pre_start.group(2)), "notification": "13/2020 as amended by 61/2020"}]
    evidence_items = [
        cite(IN_PUBLISHER, "Notification No. 13/2020 - Central Tax, 21 March 2020", f"{GSTC_FILES}/notfctn-13-central-tax-english-2020.pdf", "paragraphs 1 and 2", "This notification shall come into force from the 1st October, 2020.", "of supply of goods or services or both to a registered person.", GST_LICENSE),
        cite(IN_PUBLISHER, "Notification No. 61/2020 - Central Tax, 30 July 2020", f"{GSTC_FILES}/notfctn-61-central-tax-english-2020.pdf", "paragraph (ii)", "five hundred crore rupees", "Zone unit and", GST_LICENSE),
    ]
    for number in ("88/2020", "05/2021", "01/2022", "17/2022", "10/2023"):
        text = texts[number][1]
        match = re.search(r"with e\s?ffect from the (\d+) ?(?:st|th|nd|rd)? day of (\w+), (\d{4}),? for the words .\s?([a-z ]+?) crore rupees\s?., the words .\s?([a-z ]+?) crore rupees\s?. shall be\s+substituted", text)
        if match is None:
            raise ValueError(f"amendment not found in {number}")
        day, month, year, old, new = match.groups()
        if crore(old) != steps[-1]["value"]:
            raise ValueError(f"{number} amends {old}, expected the previous step")
        steps.append({"from": f"{year}-{MONTHS[month]:02d}-{int(day):02d}", "value": crore(new), "notification": number})
        url = f"{GSTC_FILES}/{dict(IN_NOTIFICATIONS)[number]}"
        evidence_items.append(cite(IN_PUBLISHER, f"Notification No. {number} - Central Tax", url, "operative paragraph", match.group(0), f"No. {number}", GST_LICENSE))
    evidence_items += [
        cite(IN_PUBLISHER, "Notification No. 70/2020 - Central Tax, 30 September 2020", f"{GSTC_FILES}/notfctn-70-central-tax-english-2020.pdf", "paragraphs (i) and (ii)", "any preceding financial year from 2017-18 onwards", "or for exports", GST_LICENSE, role="supporting"),
        cite(IN_PUBLISHER, "Notification No. 23/2021 - Central Tax, 1 June 2021", f"{GSTC_FILES}/notfctn-23-central-tax-english-2021.pdf", "operative paragraph", "a government department, a local authority,", "notifies registered person, other than", GST_LICENSE, role="supporting"),
    ]
    return entry(
        "in-gst-e-invoicing-turnover-threshold-history",
        "India GST e-invoicing (IRN) aggregate turnover threshold by date, Notification 13/2020-CT and amendments to 10/2023",
        "IN", "B", start_date, "almanac.rules.step_schedule", {"unit": "currency:INR", "basis": "aggregate turnover in any preceding financial year from 2017-18", "steps": steps},
        [
            {"input": {"on": "2020-10-01"}, "expected": steps[0]["value"], "origin": "source"},
            {"input": {"on": "2021-01-01"}, "expected": steps[1]["value"], "origin": "source"},
            {"input": {"on": "2022-09-30"}, "expected": steps[3]["value"], "origin": "source"},
            {"input": {"on": "2023-08-01"}, "expected": steps[-1]["value"], "origin": "source"},
            {"input": {"on": "2026-11-01"}, "expected": steps[-1]["value"], "origin": "derived", "note": "no later amendment fetched"},
        ],
        evidence_items,
        [
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": "min", "expected": min(s["value"] for s in steps), "tolerance": 0},
            {"statistic": "max", "expected": max(s["value"] for s in steps), "tolerance": 0},
        ],
        "Registered persons whose aggregate turnover exceeds this amount must issue e-invoices (report to the Invoice "
        "Registration Portal and obtain an IRN) for supplies to registered persons and for exports, under rule 48(4) of "
        "the CGST Rules. Notification 13/2020-Central Tax set the class from 1 October 2020; 61/2020 raised its figure "
        "to five hundred crore before it took effect; 88/2020, 05/2021, 01/2022, 17/2022 and 10/2023 lowered it on the "
        "dates shown. 70/2020 made the test any preceding financial year from 2017-18 and added exports; 23/2021 excluded "
        "government departments and local authorities, and SEZ units and persons under rule 54(2) to (4A) are excluded "
        "throughout. Values are rupees. The 57th Council's proposed extension to reverse-charge and import supplies is a "
        "separate entry (in-gst-registration-and-compliance-thresholds-57th-council).",
        ["gst", "irn", "india", "thresholds"],
        ["invoicing", "kyb-onboarding", "tax-filing-demo"],
        assumed=[{"parameter": "steps.*.value", "value": "crore = 10,000,000 rupees", "method": "derived", "rationale": "The notifications state amounts in words of crore rupees; values are converted to rupees."}],
    )


# ---------------------------------------------------------------- Saudi Arabia

ARABIC = re.compile(r"[؀-ۿ]")


def sa_section(start: str, end: str) -> list[str]:
    lines = pdf_lines(SA_STD)
    first = next(i for i, line in enumerate(lines) if line.strip() == start)
    last = next(i for i in range(first + 1, len(lines)) if lines[i].strip().startswith(end))
    return [line.strip() for line in lines[first:last]]


def sa_exemption_rows() -> dict[str, dict[str, str]]:
    """VATEX-SA reason codes with their VAT category and English text, read from table 11.2.4."""
    rows: dict[str, dict[str, str]] = {}
    category = None
    code = None
    for line in sa_section("11.2.4 VAT categories code", "11.2.5"):
        if line in ("E", "S", "Z"):
            category, code = line, None
            continue
        if line.startswith("O Services outside scope"):
            category, code = "O", None
            continue
        found = re.match(r"^(VATEX-SA-[A-Z0-9-]+?)(?:\s+(.*))?$", line)
        if found:
            code = found.group(1)
            rows[code] = {"vat_category": category, "reason": ""}
            line = found.group(2) or ""
        if code is None or not line:
            if code is not None and rows[code]["reason"]:
                code = None
            continue
        english = ARABIC.split(line, 1)[0].strip() if ARABIC.search(line) else line
        if english:
            rows[code]["reason"] = f"{rows[code]['reason']} {english}".strip()
        if ARABIC.search(line):
            code = None
    return rows


def sa_vat_exemptions() -> dict:
    rows = sa_exemption_rows()
    if {r["vat_category"] for r in rows.values()} != {"E", "Z", "O"}:
        raise ValueError(f"unexpected categories {rows}")
    for row in rows.values():
        if row["reason"] not in TEXT[SA_STD]:
            raise ValueError(f"reason not found verbatim: {row}")
    return entry(
        "sa-zatca-vat-exemption-reason-codes",
        "Saudi Arabia ZATCA e-invoice VAT exemption and zero-rating reason codes (VATEX-SA) by VAT category",
        "SA", "B", SA_VALID_FROM, "almanac.rules.lookup_table", {"vat_categories": ["S", "Z", "E", "O"], "rows": rows},
        [
            {"input": {"key": "VATEX-SA-32", "column": "vat_category"}, "expected": "Z", "origin": "source"},
            {"input": {"key": "VATEX-SA-29", "column": "vat_category"}, "expected": "E", "origin": "source"},
            {"input": {"key": "VATEX-SA-OOS", "column": "vat_category"}, "expected": "O", "origin": "source"},
            {"input": {"key": "VATEX-SA-35", "column": "reason"}, "expected": rows["VATEX-SA-35"]["reason"], "origin": "source"},
            {"input": "VATEX-SA-31", "expected": False, "origin": "derived"},
        ],
        [
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 32, section 11.2.4", "VATEX-SA-29", "A subset of values from UN/CEFACT code list 5305, D.16B shall be used.", role="primary"),
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 32, section 11.2.4, category E", "Financial services mentioned in Article 29 of the VAT Regulations", "Real estate transactions mentioned in"),
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 33, section 11.2.4, categories Z and O", "Medicines and medical equipment", "Reason is free text, to be provided by the taxpayer on case to case basis."),
        ],
        [{"statistic": "count", "expected": len(rows), "tolerance": 0}],
        "Exemption and exception reason codes a ZATCA e-invoice gives in BT-121 when a line's VAT category (BT-151, a "
        "subset of UN/CEFACT 5305) is not S: category E exempt supplies (financial services, life insurance, real estate), "
        "Z zero-rated supplies (exports, international transport, qualifying transport means, medicines, qualifying metals, "
        "private education and healthcare to citizens, military goods), and O out of scope, where VATEX-SA-OOS takes a "
        "free-text reason. Reasons are the English text of table 11.2.4 of the standard. No licence is stated, so the "
        "entry stays at license-review.",
        ["zatca", "fatoora", "saudi-arabia", "vat-exemption"],
        assumed=[{"parameter": "rows.*.vat_category", "value": "table grouping", "method": "derived", "rationale": "Each code's category is the row group it sits under in table 11.2.4."}],
    )


def sa_transaction_codes() -> dict:
    text = TEXT[SA_STD] if SA_STD in TEXT else (load(SA_STD) and TEXT[SA_STD])
    documents = re.findall(r"For ([A-Za-z ]+?), code is (\d{3}) and subtype is (\d{2})\.", text)
    type_codes: dict[str, dict[str, Any]] = {}
    for name, code, subtype in documents:
        row = type_codes.setdefault(code, {"documents": {}})
        row["documents"][subtype] = name
    subtypes = dict(re.findall(r"- (\d{2}) for (tax invoice|simplified tax invoice)", text))
    positions = re.findall(r"([A-Z]) \(position (\d)\) = ([A-Za-z0-9 ]+?) (?:invoice )?transaction", text)
    names = {"3rd Party": "third_party", "Nominal": "nominal", "Exports": "export", "Summary": "summary"}
    flags = [names[label] for _, _, label in sorted(positions, key=lambda p: int(p[1]))]
    if re.search(r"B \(position 7\) = Self billed invoice", text):
        flags.append("self_billed")
    rule = re.search(r"position (\d) cannot be .1.\) for export invoices \(KSA-2, position (\d) = 1\)", text)
    by_position = {position: flag for position, flag in zip(range(3, 3 + len(flags)), flags)}
    forbidden = [[by_position[int(rule.group(2))], by_position[int(rule.group(1))]]]
    parameters = {"type_codes": type_codes, "subtypes": subtypes, "flags": flags, "forbidden_combinations": forbidden}
    if set(type_codes) != {"388", "386", "383", "381"} or flags != ["third_party", "nominal", "export", "summary", "self_billed"]:
        raise ValueError(f"unexpected ZATCA structure {parameters}")
    return entry(
        "sa-zatca-invoice-type-and-transaction-codes",
        "Saudi Arabia ZATCA e-invoice type codes (388, 386, 383, 381) and KSA-2 transaction code NNPNESB",
        "SA", "B", SA_VALID_FROM, "almanac.rules.sa_zatca_transaction_code", parameters,
        [
            {"input": {"transaction_code": "0100000"}, "expected": True, "origin": "source", "note": "tax invoice example"},
            {"input": {"transaction_code": "0200000"}, "expected": True, "origin": "source", "note": "simplified tax invoice example"},
            {"input": {"transaction_code": "0200000", "field": "subtype"}, "expected": "02", "origin": "source"},
            {"input": {"type_code": "388"}, "expected": True, "origin": "source"},
            {"input": {"type_code": "381"}, "expected": True, "origin": "source"},
            {"input": {"type_code": "380"}, "expected": False, "origin": "derived", "note": "outside the KSA subset of UNCL1001"},
            {"input": {"transaction_code": "0100101"}, "expected": False, "origin": "derived", "note": "BR-KSA-07: export invoice cannot be self-billed"},
            {"input": {"transaction_code": "0100100", "field": "export"}, "expected": True, "origin": "derived"},
            {"input": {"transaction_code": "0300000"}, "expected": False, "origin": "derived", "note": "unknown subtype"},
            {"input": {"transaction_code": "010000"}, "expected": False, "origin": "derived", "note": "six characters"},
        ],
        [
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 31, section 11.2.1 notes", "For Simplified Tax Invoice, code is 388 and subtype is 02.", "For Prepayment Tax Invoice, code is 386 and subtype is 01."),
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 31, section 11.2.1 notes", "For simplified credit note, code is 381 and subtype is 02.", "For tax invoice debit note, code is 383 and subtype is 01."),
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 48, rule BR-KSA-06", "NNPNESB", "P (position 3) = 3rd Party invoice transaction, 0 for false, 1 for true"),
            cite(SA_PUBLISHER, SA_TITLE, SA_STD, "page 48, rule BR-KSA-07", "Self-billing is not allowed (KSA-2,", "export invoices (KSA-2, position 5 = 1)."),
        ],
        [
            {"statistic": "count[type_codes]", "expected": len(type_codes), "tolerance": 0},
            {"statistic": "count[flags]", "expected": len(flags), "tolerance": 0},
        ],
        "A ZATCA (FATOORA) e-invoice states its document type in cbc:InvoiceTypeCode (BT-3): 388 tax invoice, 386 "
        "prepayment invoice, 383 debit note, 381 credit note. The name attribute carries the seven-character "
        "transaction code KSA-2, NNPNESB: subtype 01 tax invoice (B2B) or 02 simplified tax invoice (B2C), then 0/1 "
        "flags for third-party, nominal, export, summary and self-billed transactions (BR-KSA-06). BR-KSA-07 forbids "
        "self-billing on export invoices. type_codes lists, per code, the document each subtype makes. No licence is "
        "stated, so the entry stays at license-review.",
        ["zatca", "fatoora", "saudi-arabia", "document-type"],
    )


BUILDERS: list[Callable[[], dict]] = [
    it_document_types,
    it_natura,
    it_tax_regimes,
    it_payment_codes,
    it_withholding_codes,
    it_field_formats,
    it_sdi_file_names,
    peppol_vat_categories,
    peppol_invoice_types,
    peppol_payment_means,
    peppol_address_schemes,
    peppol_units,
    peppol_participant_schemes,
    peppol_participant_format,
    pl_invoice_types,
    pl_vat_rates,
    pl_payment_and_procedure_codes,
    es_invoice_types,
    es_regime_keys,
    es_operation_codes,
    mx_catalogue_codes,
    mx_attribute_catalogues,
    in_threshold_schedule,
    sa_vat_exemptions,
    sa_transaction_codes,
]


def main(selected: list[str]) -> int:
    for build in BUILDERS:
        if not selected or build.__name__ in selected:
            write(build())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

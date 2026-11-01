"""Machine-readable indexes of the Almanac for search engines, data catalogues and AI agents.

Three artefacts are produced from the entries: ``manifest.json`` (every
entry with its provenance summary and path), ``dataset.jsonld`` (a
schema.org Dataset description) and ``llms.txt`` (a plain-text map an
agent can read before deciding which entries to open).
"""

from __future__ import annotations

import json
from typing import Any

from almanac.api import Almanac
from almanac.catalogue import publishers, validity
from almanac.models import Entry, RuleSpec

REPOSITORY = "https://github.com/Misata-labs/almanac"
RAW_BASE = "https://raw.githubusercontent.com/Misata-labs/almanac/main/"
NAME = "Misata Almanac"
DESCRIPTION = (
    "Synthetic data rules for realistic synthetic data: the open rulebook of how real-world records behave, for synthetic "
    "data generation, privacy-safe test data and data validation. Check-digit "
    "algorithms, identifier formats, tax rates, bank and federal holidays, currency conventions, industry code lists "
    "and official distributions, each traced to the government body, central bank, regulator or standards agency "
    "that published it, with the exact URL, a SHA-256 content hash and executable tests. Read by the Misata synthetic "
    "data engine; usable on its own as a Python library and CLI."
)
CREATOR = "Muhammed Rasin"


def _entry_record(almanac: Almanac, entry: Entry) -> dict[str, Any]:
    path = almanac.path(entry.id)
    rel = path.relative_to(path.parents[3]).as_posix()
    record: dict[str, Any] = {
        "id": entry.id,
        "title": entry.title,
        "kind": entry.kind,
        "domain": entry.domain,
        "region": entry.region,
        "tier": entry.tier,
        "status": entry.status,
        "validity": validity(entry),
        "publishers": publishers(entry),
        "source_licenses": sorted({item.source_license for item in entry.evidence}),
        "tags": entry.tags,
        "use_cases": entry.use_cases,
        "path": rel,
        "url": RAW_BASE + rel,
    }
    if entry.kind == "rule":
        record["valid_from"] = entry.valid_from.isoformat() if entry.valid_from else None
        record["valid_to"] = entry.valid_to.isoformat() if entry.valid_to else None
        if isinstance(entry.spec, RuleSpec):
            record["implementation"] = entry.spec.implementation
            record["vectors"] = len(entry.spec.vectors)
    else:
        assert entry.observed_period is not None
        record["observed_period"] = {"start": entry.observed_period.start.isoformat(), "end": entry.observed_period.end.isoformat()}
        record["variable"] = getattr(entry.spec, "variable", None)
    return record


def render_manifest(almanac: Almanac) -> str:
    entries = [_entry_record(almanac, e) for e in sorted(almanac, key=lambda e: (e.domain, e.region, e.id))]
    payload = {
        "name": NAME,
        "description": DESCRIPTION,
        "repository": REPOSITORY,
        "creator": CREATOR,
        "schema": RAW_BASE + "schema/entry.schema.json",
        "license": {"entries": "ODbL-1.0", "code": "Apache-2.0"},
        "entry_count": len(entries),
        "entries": entries,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_jsonld(almanac: Almanac) -> str:
    regions = sorted({e.region for e in almanac})
    keywords = sorted(
        {"synthetic data", "data validation", "check digit", "test data", "data quality", "official statistics", "reference data"}
        | {e.domain for e in almanac}
        | {t for e in almanac for t in e.tags}
        | {u for e in almanac for u in e.use_cases}
        | {f"{e.region} data rules" for e in almanac if e.region != "global"}
    )
    parts = [
        {
            "@type": "Dataset",
            "name": e.title,
            "identifier": e.id,
            "url": f"{REPOSITORY}/blob/main/{almanac.path(e.id).relative_to(almanac.path(e.id).parents[3]).as_posix()}",
            "temporalCoverage": validity(e),
            "spatialCoverage": e.region,
            "creator": [{"@type": "Organization", "name": p} for p in publishers(e)],
        }
        for e in sorted(almanac, key=lambda e: (e.domain, e.region, e.id))
    ]
    payload = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": NAME,
        "description": DESCRIPTION,
        "url": REPOSITORY,
        "sameAs": REPOSITORY,
        "license": "https://opendatacommons.org/licenses/odbl/1-0/",
        "isAccessibleForFree": True,
        "creator": {"@type": "Person", "name": CREATOR},
        "publisher": {"@type": "Organization", "name": "Misata Studio", "url": "https://www.misata.studio"},
        "keywords": keywords,
        "spatialCoverage": regions,
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": RAW_BASE + "manifest.json"},
            {"@type": "DataDownload", "encodingFormat": "application/x-yaml", "contentUrl": RAW_BASE + "entries/"},
        ],
        "hasPart": parts,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_llms_txt(almanac: Almanac) -> str:
    lines = [
        f"# {NAME}",
        "",
        f"> {DESCRIPTION}",
        "",
        "Use this archive when you need an authoritative answer to questions such as: how is a UK VAT number validated, "
        "what are the CNPJ check digits, how is the VIN check digit computed, which days are UK bank holidays or US federal "
        "holidays, how many decimals does a currency use, what are the UK income tax bands or minimum wage rates, what is "
        "the age distribution of England and Wales, what is the Selic or ECB deposit rate on a date. Every entry is a YAML "
        "file validated by schema/entry.schema.json. Read an entry's `spec` to execute the rule or sample the distribution, "
        "its `evidence` for the primary source, URL and SHA-256 of the fetched resource, `assumed` for anything derived "
        "rather than published, and `tests` for the statistics the verifier reproduces. Rules carry valid_from and "
        "valid_to; statistics carry observed_period. Ask which entries applied on a date with "
        "`almanac applies --on YYYY-MM-DD`. Cite entries as: Muhammed Rasin, Misata Almanac, Misata Labs.",
        "",
        f"- Repository: {REPOSITORY}",
        "- Misata, the synthetic data engine that reads this archive: https://www.misata.studio",
        f"- Manifest (JSON index of every entry): {RAW_BASE}manifest.json",
        f"- Schema: {RAW_BASE}schema/entry.schema.json",
        f"- Catalogue: {RAW_BASE}CATALOGUE.md",
        f"- Wanted entries and their official sources: {RAW_BASE}WANTED.md",
        f"- Contributing and source policy: {RAW_BASE}CONTRIBUTING.md",
        "",
    ]
    by_use_case: dict[str, list[str]] = {}
    for entry in almanac:
        for use_case in entry.use_cases:
            by_use_case.setdefault(use_case, []).append(entry.id)
    lines.append("## Entries by business problem")
    lines.append("")
    for use_case, ids in sorted(by_use_case.items()):
        lines.append(f"- {use_case}: {', '.join(sorted(ids))}")
    lines.append("")
    by_domain: dict[str, list[Entry]] = {}
    for entry in sorted(almanac, key=lambda e: (e.domain, e.region, e.id)):
        by_domain.setdefault(entry.domain, []).append(entry)
    for domain, entries in by_domain.items():
        lines.append(f"## {domain}")
        lines.append("")
        for entry in entries:
            rel = almanac.path(entry.id).relative_to(almanac.path(entry.id).parents[3]).as_posix()
            lines.append(
                f"- [{entry.id}]({RAW_BASE}{rel}): {entry.title}. {entry.kind}, {entry.region}, tier {entry.tier}, {entry.status}, "
                f"{validity(entry)}. Source: {'; '.join(publishers(entry))}. Use cases: {', '.join(entry.use_cases) or 'none'}."
            )
        lines.append("")
    return "\n".join(lines)

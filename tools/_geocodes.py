"""Shared pieces for the geocodes builders: stable fetching, workbook and archive reading, rule-entry assembly.

Every reference list here is published as a static file, so the builders fetch each URL twice and refuse to
cite bytes that differ between the two fetches. Entries are keyed reference tables (``almanac.rules.lookup_table``)
or closed code lists (``almanac.rules.enumeration``), assembled through :func:`rule_entry` so every builder
produces the same shape.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from typing import Any

import openpyxl
from _common import ACCESSED, fetch, sha

TAGS = ["geography", "codes", "reference"]
USE_CASES = ["synthetic-addresses", "synthetic-companies", "product-catalogue", "data-quality-validation"]
VINTAGE_NOTE = "The file carries no application date of its own; valid_from is the first day of the vintage its name announces."
ACCESSED_NOTE = "The file carries no application or publication date; valid_from is the day it was fetched."


def stable(url: str) -> bytes:
    """Fetch ``url`` twice and return the bytes only when both fetches agree, so the recorded hash is reproducible."""
    first, second = fetch(url), fetch(url)
    if sha(first) != sha(second):
        raise RuntimeError(f"{url} returned different bytes on two fetches; it cannot be cited")
    return first


def zip_member(raw: bytes, name: str, encoding: str = "utf-8") -> str:
    return zipfile.ZipFile(io.BytesIO(raw)).read(name).decode(encoding)


def csv_rows(text: str, delimiter: str = ",") -> list[dict[str, str]]:
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter)]


def sheet_rows(raw: bytes, sheet: str | None = None) -> list[tuple[Any, ...]]:
    """All rows of one worksheet (the first when ``sheet`` is None) as tuples of cell values."""
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
    return [tuple(row) for row in worksheet.iter_rows(values_only=True)]


def vintage_assumption(valid_from: str, vintage: str) -> dict:
    return {
        "parameter": "valid_from",
        "value": valid_from,
        "method": "assumed",
        "rationale": f"{VINTAGE_NOTE} The vintage is {vintage}.",
    }


def accessed_assumption() -> dict:
    return {"parameter": "valid_from", "value": ACCESSED.isoformat(), "method": "assumed", "rationale": ACCESSED_NOTE}


def membership_vectors(keys: Iterable[str], absent: str) -> list[dict]:
    """Lookup-table vectors: each listed key is present, ``absent`` is not."""
    vectors = [{"input": key, "expected": True, "origin": "source"} for key in keys]
    vectors.append({"input": absent, "expected": False, "origin": "derived"})
    return vectors


def column_vector(key: str, column: str, expected: Any) -> dict:
    return {"input": {"key": key, "column": column}, "expected": expected, "origin": "source"}


def set_vectors(sets: dict[str, dict[str, str]], absent: str) -> list[dict]:
    """Enumeration vectors: the first code of every set is a member, ``absent`` belongs to none."""
    vectors = [{"input": {"set": name, "value": next(iter(codes))}, "expected": True, "origin": "source"} for name, codes in sets.items()]
    vectors.append({"input": {"set": next(iter(sets)), "value": absent}, "expected": False, "origin": "derived"})
    return vectors


def lookup_tests(rows: dict[str, dict], samples: list[tuple[str, str]]) -> list[dict]:
    tests = [
        {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
        {"statistic": "count", "expected": len(rows), "tolerance": 0},
    ]
    for key, column in samples:
        tests.append({"statistic": f'value["{key}","{column}"]', "expected": rows[key][column], "tolerance": 0})
    return tests


def set_tests(sets: dict[str, dict[str, str]]) -> list[dict]:
    tests = [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}]
    tests.extend({"statistic": f"count[{name}]", "expected": len(codes), "tolerance": 0} for name, codes in sets.items())
    return tests


def rule_entry(
    entry_id: str,
    title: str,
    domain: str,
    region: str,
    *,
    valid_from: str,
    implementation: str,
    parameters: dict,
    vectors: list[dict],
    evidence_items: list[dict],
    tests: list[dict],
    notes: str,
    status: str,
    tags: list[str],
    use_cases: list[str] | None = None,
    assumed: list[dict] | None = None,
    valid_to: str | None = None,
) -> dict:
    """Assemble a tier A rule entry with the geocodes tag and use-case vocabulary merged in."""
    if len(title) > 140:
        raise ValueError(f"title too long ({len(title)} chars): {title}")
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": domain,
        "region": region,
        "status": status,
        "tier": "A",
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tags": list(dict.fromkeys(TAGS + tags)),
        "use_cases": list(dict.fromkeys(USE_CASES + (use_cases or []))),
        "spec": {"implementation": implementation, "parameters": parameters, "vectors": vectors},
        "evidence": evidence_items,
        "assumed": assumed or [],
        "tests": tests,
        "notes": notes,
    }

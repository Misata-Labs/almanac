"""Brazil Pix identifier format rules.

The Pix API published by Banco Central do Brasil fixes the shape of the
transaction identifier (txid), the end-to-end identifier, the CPF and CNPJ
document fields, the ISPB participant code, and monetary amounts. Each is
a regular expression, optionally with explicit length bounds.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def field_pattern(parameters: Mapping[str, Any], field: str) -> re.Pattern[str]:
    try:
        return re.compile(parameters["fields"][field]["pattern"])
    except KeyError as exc:
        raise KeyError(f"unknown Pix field {field!r}") from exc


def is_valid(value: str, parameters: Mapping[str, Any], field: str) -> bool:
    """Return whether ``value`` conforms to the published format of ``field``."""
    spec = parameters["fields"][field]
    if "min_length" in spec and len(value) < spec["min_length"]:
        return False
    if "max_length" in spec and len(value) > spec["max_length"]:
        return False
    return field_pattern(parameters, field).fullmatch(value) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value["value"]), parameters, str(value["field"]))

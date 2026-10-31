"""United Kingdom National Insurance number (NINO) format rule.

A NINO is two prefix letters, six digits, and a suffix letter. Certain letters
are never used in the first or second position and a handful of two-letter
prefixes are never issued. Digit pairs may be separated by single spaces.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_DIGIT_GROUPS = 3


def _letter_class(excluded: list[str]) -> str:
    return "[" + "".join(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in set(excluded)) + "]"


def build_pattern(parameters: Mapping[str, Any]) -> re.Pattern[str]:
    """Compile the NINO pattern from the excluded letters and allowed suffixes."""
    first = _letter_class(parameters["excluded_first_letters"])
    second = _letter_class(parameters["excluded_second_letters"])
    suffix = "[" + "".join(parameters["suffix_letters"]) + "]"
    separator = " ?" if parameters.get("optional_spaces", True) else ""
    digits = separator.join([r"\d{2}"] * _DIGIT_GROUPS)
    return re.compile(f"{first}{second}{separator}{digits}{separator}{suffix}")


def is_valid(nino: str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``nino`` is well formed under the given parameters."""
    if any(nino.startswith(prefix) for prefix in parameters["invalid_prefixes"]):
        return False
    return build_pattern(parameters).fullmatch(nino) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value), parameters)

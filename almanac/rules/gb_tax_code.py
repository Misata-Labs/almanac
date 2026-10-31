"""United Kingdom PAYE tax code format rule.

A tax code is a numeric allowance followed by a letter, such as 1257L,
optionally prefixed with K for negative allowances, or one of the fixed
codes BR, NT, D0 and D1. The shape is published as a single pattern.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def is_valid(code: str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``code`` matches the published tax code pattern in full."""
    return re.fullmatch(parameters["pattern"], code) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value), parameters)

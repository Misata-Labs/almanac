"""Conversion of nonstandard UK account numbers to the eight digits that modulus checking expects.

Ten-digit account numbers keep their first or last eight digits depending on
the institution, a nine-digit number of the named institution moves its first
digit into the last place of the sorting code, and shorter numbers are padded
with leading zeros. Separators such as hyphens are ignored. ``ten_digit`` and
``nine_digit`` map institution keys to the conversion they use; ``pad_from``
is the shortest length that zero padding accepts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def standardise(sort_code: str, account: str, institution: str | None, parameters: Mapping[str, Any]) -> tuple[str, str]:
    """The (sorting code, eight-digit account number) pair to use for modulus checking."""
    sort_code = "".join(c for c in sort_code if c.isdigit())
    digits = "".join(c for c in account if c.isdigit())
    if len(digits) == 10:
        rule = parameters["ten_digit"].get(institution or "")
        if rule == "first_eight":
            return sort_code, digits[:8]
        if rule == "last_eight":
            return sort_code, digits[2:]
        raise ValueError(f"no ten-digit conversion for institution {institution!r}")
    if len(digits) == 9:
        if parameters["nine_digit"].get(institution or "") != "first_digit_to_sort_code":
            raise ValueError(f"no nine-digit conversion for institution {institution!r}")
        return sort_code[:5] + digits[0], digits[1:]
    if parameters["pad_from"] <= len(digits) <= 8:
        return sort_code, digits.zfill(8)
    raise ValueError(f"an account number of {len(digits)} digits cannot be standardised")


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    sort_code, account = standardise(str(value["sort_code"]), str(value["account"]), value.get("institution"), parameters)
    return [sort_code, account]

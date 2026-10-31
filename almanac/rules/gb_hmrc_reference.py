"""HM Revenue & Customs payment reference check characters (modulus 23).

Three reference families share one scheme: a weighted sum over the
characters of the reference, taken modulo 23, selects a check letter from a
23-letter alphabet, and that letter must sit at a fixed position. The
families differ in their weights, the numeric values assigned to letters,
the check position and the overall shape:

* ``epaye``: the 13-character Accounts Office reference used for PAYE payments.
* ``other_tax``: the 14- or 15-character X-prefixed reference for other taxes.
* ``sdlt``: the 11-character Stamp Duty Land Tax reference ending in M and a letter.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_BASE36 = 36


def character_value(char: str, letter_values: Mapping[str, int]) -> int:
    """Numeric value of one character: the family's letter table, else its base-36 digit value, else -1."""
    if char in letter_values:
        return letter_values[char]
    if char.isdigit():
        return int(char)
    if char.isascii() and char.isalpha():
        return int(char.upper(), _BASE36)
    return -1


def weighted_sum(reference: str, weights: list[int], letter_values: Mapping[str, int]) -> int:
    return sum(w * character_value(c, letter_values) for w, c in zip(weights, reference))


def check_character(reference: str, parameters: Mapping[str, Any], family: str) -> str:
    """Return the check letter implied by ``reference`` for ``family``."""
    scheme = parameters["families"][family]
    total = weighted_sum(reference.upper(), scheme["weights"], scheme["letter_values"])
    if total < 0:
        raise ValueError("reference contains a character outside the scheme alphabet")
    return parameters["check_alphabet"][total % parameters["modulus"]]


def _epaye_extra_checks(reference: str, scheme: Mapping[str, Any]) -> bool:
    if not reference.startswith(scheme["special_prefix"]):
        return True
    if reference[12] == "X":
        return reference[5] == "0"
    return re.fullmatch(scheme["special_prefix_pattern"], reference) is not None


def is_valid(reference: str, parameters: Mapping[str, Any], family: str) -> bool:
    """Return whether ``reference`` has the family's shape and the right check letter."""
    scheme = parameters["families"][family]
    prepared = reference.upper()
    if re.fullmatch(scheme["pattern"], prepared) is None:
        return False
    try:
        expected = check_character(prepared, parameters, family)
    except ValueError:
        return False
    if prepared[scheme["check_index"]] != expected:
        return False
    if family == "epaye" and not _epaye_extra_checks(prepared, scheme):
        return False
    return True


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value["reference"]), parameters, str(value["family"]))

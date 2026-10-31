"""Brazil CNPJ check digits (modulus 11), covering the alphanumeric format.

A CNPJ is twelve base characters followed by two check digits. Each
character is valued at its ASCII code minus 48, so digits keep their face
value and letters A to Z take 17 to 42. The weighted sum of the twelve
values (and then of the thirteen, once the first check digit is appended)
is taken modulo 11; a remainder of 0 or 1 yields check digit 0, any other
remainder yields 11 minus the remainder.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_ASCII_OFFSET = 48
_BASE_LENGTH = 12


def character_value(char: str) -> int:
    return ord(char) - _ASCII_OFFSET


def normalise(cnpj: str) -> str:
    """Strip the conventional punctuation (dots, slash, hyphen) and upper-case the result."""
    return re.sub(r"[.\-/]", "", cnpj).upper()


def _digit(values: list[int], weights: list[int], parameters: Mapping[str, Any]) -> int:
    remainder = sum(v * w for v, w in zip(values, weights)) % parameters["modulus"]
    if remainder < parameters["zero_below_remainder"]:
        return 0
    return parameters["modulus"] - remainder


def check_digits(base: str, parameters: Mapping[str, Any]) -> str:
    """Compute the two check digits for a twelve-character alphanumeric ``base``."""
    base = normalise(base)
    if len(base) != _BASE_LENGTH or re.fullmatch(parameters["base_pattern"], base) is None:
        raise ValueError("CNPJ base must be twelve characters from 0-9 and A-Z")
    values = [character_value(c) for c in base]
    first = _digit(values, parameters["weights_first"], parameters)
    second = _digit(values + [first], parameters["weights_second"], parameters)
    return f"{first}{second}"


def is_valid(cnpj: str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``cnpj`` (with or without punctuation) carries correct check digits."""
    text = normalise(cnpj)
    if len(text) != _BASE_LENGTH + 2 or not text[-2:].isdigit():
        return False
    try:
        return check_digits(text[:_BASE_LENGTH], parameters) == text[-2:]
    except ValueError:
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "base" in value:
        return check_digits(str(value["base"]), parameters)
    return is_valid(str(value), parameters)

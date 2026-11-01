"""Luhn (ISO/IEC 7812-1 modulus 10 "double-add-double") check digit.

The parameters may name a ``prefix`` that is prepended before the check
digit is computed, which is how the US National Provider Identifier keeps
its check digit compatible with the 80840-prefixed card issuer identifier.
"""

from __future__ import annotations

from typing import Any, Mapping


def _digit_sum(number: str) -> int:
    total = 0
    for index, char in enumerate(reversed(number)):
        value = int(char)
        if index % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Check digit for ``body`` (digits only), computed over the optional prefix plus the body."""
    if not body.isdigit():
        raise ValueError("Luhn bodies are digits only")
    length = parameters.get("body_length")
    if length is not None and len(body) != length:
        raise ValueError(f"body must be {length} digits")
    total = _digit_sum(str(parameters.get("prefix", "")) + body)
    return str((10 - total % 10) % 10)


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` (body plus trailing check digit) carries the right check digit."""
    if not number.isdigit() or len(number) < 2:
        return False
    length = parameters.get("body_length")
    if length is not None and len(number) != length + 1:
        return False
    try:
        return check_digit(number[:-1], parameters) == number[-1]
    except ValueError:
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "body" in value:
        return check_digit(str(value["body"]), parameters)
    return is_valid(str(value), parameters)

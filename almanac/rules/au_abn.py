"""Australian Business Number (ABN) check digits, the modulus 89 rule the ABR publishes.

An ABN is eleven digits whose two leading digits are check digits. To verify
one, subtract 1 from the first digit, multiply each of the eleven digits by
the weight of its position, and sum the products: the number is valid when
the sum is divisible by 89. Issuing the leading pair therefore means picking
the two digits, from 10 upwards, that make the weighted sum divisible.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

LENGTH = 11
CHECK_LENGTH = 2


def normalise(abn: str) -> str:
    return re.sub(r"\s", "", abn)


def weighted_sum(digits: str, parameters: Mapping[str, Any]) -> int:
    values = [int(d) for d in digits]
    values[0] -= parameters["first_digit_offset"]
    return sum(v * w for v, w in zip(values, parameters["weights"]))


def is_valid(abn: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``abn`` (spaces allowed) passes the modulus 89 check."""
    digits = normalise(abn)
    if len(digits) != LENGTH or not digits.isdigit():
        return False
    return weighted_sum(digits, parameters) % parameters["modulus"] == 0


def check_digits(identifier: str, parameters: Mapping[str, Any]) -> str:
    """The leading check digits for a nine-digit ``identifier``."""
    identifier = normalise(identifier)
    if len(identifier) != LENGTH - CHECK_LENGTH or not identifier.isdigit():
        raise ValueError("an ABN identifier is nine digits")
    for candidate in range(10, 100):
        if is_valid(f"{candidate}{identifier}", parameters):
            return str(candidate)
    raise ValueError("no leading check digits satisfy the modulus")


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "identifier" in value:
        return check_digits(str(value["identifier"]), parameters)
    return is_valid(str(value), parameters)

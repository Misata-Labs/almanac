"""Germany's steuerliche Identifikationsnummer (IdNr): structure and ISO 7064 MOD 11,10 check digit.

An IdNr is eleven digits whose last digit is the check digit over the first
ten. The first ten digits never start with 0 (test numbers excepted), contain
exactly one digit that occurs two or three times, and when a digit occurs
three times those occurrences are never adjacent.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from almanac.rules import iso7064_mod11_10

LENGTH = 11


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Check digit for the ten leading digits ``body``."""
    if len(body) != LENGTH - 1 or not body.isdigit():
        raise ValueError("the IdNr body is ten digits")
    return iso7064_mod11_10.check_digit(body, parameters["check_digit"])


def has_valid_structure(body: str, parameters: Mapping[str, Any]) -> bool:
    """Whether the ten leading digits obey the repetition rules of the tax administration."""
    if len(body) != LENGTH - 1 or not body.isdigit():
        return False
    if body[0] == "0" and not parameters.get("allow_leading_zero", False):
        return False
    repeated = [digit for digit, count in Counter(body).items() if count > 1]
    if len(repeated) != 1 or body.count(repeated[0]) not in parameters["repeat_counts"]:
        return False
    digit = repeated[0]
    if body.count(digit) == max(parameters["repeat_counts"]) and digit * 3 in body:
        return False
    return True


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` is a structurally valid IdNr with the right check digit."""
    if len(number) != LENGTH or not number.isdigit():
        return False
    body = number[:-1]
    return has_valid_structure(body, parameters) and check_digit(body, parameters) == number[-1]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "body" in value:
        return check_digit(str(value["body"]), parameters)
    return is_valid(str(value), parameters)

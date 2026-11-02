"""South African identity number: birth date, sex range, citizenship digit and Luhn check digit.

The thirteen digits are YYMMDD, a four-digit sequence whose range encodes
sex (0000 to 4999 female, 5000 to 9999 male), a citizenship digit (0
citizen, 1 permanent resident, 2 refugee), one further digit, and a check
digit computed over the first twelve digits with the Luhn formula.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from almanac.rules import luhn

LENGTH = 13


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Luhn check digit for the first twelve digits ``body``."""
    if len(body) != LENGTH - 1 or not body.isdigit():
        raise ValueError("the identity number body is twelve digits")
    return luhn.check_digit(body, parameters.get("luhn", {}))


def encode_birth_date(day: date) -> str:
    return day.strftime("%y%m%d")


def sex(number: str, parameters: Mapping[str, Any]) -> str:
    sequence = int(number[6:10])
    for label, bounds in parameters["sex_ranges"].items():
        if bounds[0] <= sequence <= bounds[1]:
            return label
    raise ValueError(f"sequence {sequence:04d} is outside every sex range")


def citizenship(number: str, parameters: Mapping[str, Any]) -> str:
    return parameters["citizenship_codes"][number[10]]


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` is thirteen digits with a plausible date, known citizenship code and right check digit."""
    if len(number) != LENGTH or not number.isdigit():
        return False
    try:
        date(2000 + int(number[0:2]), int(number[2:4]), int(number[4:6]))
        citizenship(number, parameters)
    except (ValueError, KeyError):
        return False
    return check_digit(number[:-1], parameters) == number[-1]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "body" in value:
            return check_digit(str(value["body"]), parameters)
        if "encode_birth_date" in value:
            return encode_birth_date(date.fromisoformat(str(value["encode_birth_date"])))
        if "sex_of" in value:
            return sex(str(value["sex_of"]), parameters)
        if "citizenship_of" in value:
            return citizenship(str(value["citizenship_of"]), parameters)
    return is_valid(str(value), parameters)

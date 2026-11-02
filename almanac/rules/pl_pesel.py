"""Poland's PESEL number: birth date with century-coded month, sex digit and modulus 10 check digit.

A PESEL is eleven digits RRMMDDPPPPK: two-digit year, month raised by a
century offset (20 for 2000 to 2099, 80 for 1800 to 1899, and so on), day,
a four-digit serial whose last digit is even for women and odd for men, and
a check digit. The check digit is 10 minus the last digit of the weighted
digit sum, taken modulo 10, with weights 1 3 7 9 1 3 7 9 1 3.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from almanac.rules import weighted_modulus

LENGTH = 11


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Check digit for the first ten digits ``body``."""
    if len(body) != LENGTH - 1:
        raise ValueError("a PESEL body is ten digits")
    result = weighted_modulus.check_digit(body, parameters["check_digit"])
    if result is None:
        raise ValueError("the modulus 10 rule always yields a digit")
    return result


def birth_date(pesel: str, parameters: Mapping[str, Any]) -> date:
    """Decode the birth date, resolving the century from the month offset."""
    year, month, day = int(pesel[0:2]), int(pesel[2:4]), int(pesel[4:6])
    for offset, century in parameters["month_offsets"].items():
        if int(offset) < month <= int(offset) + 12:
            return date(int(century) + year, month - int(offset), day)
    raise ValueError(f"month field {month:02d} matches no century offset")


def sex(pesel: str) -> str:
    return "female" if int(pesel[9]) % 2 == 0 else "male"


def is_valid(pesel: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``pesel`` is eleven digits with a decodable date and the right check digit."""
    if len(pesel) != LENGTH or not pesel.isdigit():
        return False
    try:
        birth_date(pesel, parameters)
    except ValueError:
        return False
    return check_digit(pesel[:-1], parameters) == pesel[-1]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "body" in value:
            return check_digit(str(value["body"]), parameters)
        if "birth_date_of" in value:
            return birth_date(str(value["birth_date_of"]), parameters).isoformat()
        if "sex_of" in value:
            return sex(str(value["sex_of"]))
    return is_valid(str(value), parameters)

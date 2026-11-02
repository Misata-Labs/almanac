"""Sweden's personnummer: birth date, three-digit birth number and a Luhn (modulus 10) check digit.

The ten-digit form is YYMMDD, a separator (a hyphen, or a plus sign once the
person turns 100), three digits of birth number and the check digit; the
twelve-digit form used in registers carries the century and no separator.
The check digit is computed over the nine digits of birth date and birth
number with alternating weights 2 and 1, digit-summing the products, as the
Luhn formula does.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from almanac.rules import luhn

BODY_LENGTH = 9
_TEN = re.compile(r"^(\d{6})([-+]?)(\d{3})(\d)$")
_TWELVE = re.compile(r"^(\d{8})(\d{3})(\d)$")


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Check digit for the nine digits YYMMDDNNN."""
    if len(body) != BODY_LENGTH or not body.isdigit():
        raise ValueError("the personnummer body is nine digits")
    return luhn.check_digit(body, parameters.get("luhn", {}))


def parts(number: str) -> tuple[str, str, str] | None:
    """Split a ten- or twelve-digit personnummer into (birth date digits, birth number, check digit)."""
    match = _TEN.match(number)
    if match:
        return match.group(1), match.group(3), match.group(4)
    match = _TWELVE.match(number)
    if match:
        return match.group(1)[2:], match.group(2), match.group(3)
    return None


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` is well formed in either notation and carries the right check digit."""
    split = parts(number)
    if split is None:
        return False
    birth, serial, check = split
    return check_digit(birth + serial, parameters) == check


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "body" in value:
        return check_digit(str(value["body"]), parameters)
    return is_valid(str(value), parameters)

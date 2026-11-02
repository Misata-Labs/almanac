"""Switzerland's AHV number (Versichertennummer) as the AHVV defines it.

Thirteen digits: the country code 756, a nine-digit non-speaking number and
one control digit, customarily written 756.XXXX.XXXX.XX. The ordinance names
the control digit without stating its arithmetic, so the rule verifies the
composition only.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

LENGTH = 13


def normalise(number: str) -> str:
    return re.sub(r"[.\s]", "", number)


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    digits = normalise(number)
    return digits.isdigit() and len(digits) == LENGTH and digits.startswith(parameters["country_code"])


def parts(number: str, parameters: Mapping[str, Any]) -> dict[str, str]:
    if not is_valid(number, parameters):
        raise ValueError("not an AHV number")
    digits = normalise(number)
    code = len(parameters["country_code"])
    return {"country_code": digits[:code], "number": digits[code:-1], "control_digit": digits[-1]}


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "parts_of" in value:
        return parts(str(value["parts_of"]), parameters)
    return is_valid(str(value), parameters)

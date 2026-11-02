"""India's Permanent Account Number (PAN) format: AAAPL1234C.

Ten characters: three letters of a series, one letter naming the holder
type, the first letter of the holder's surname or name, a four-digit
sequence from 0001 to 9999, and an alphabetic check character. The check
character's arithmetic is not published, so the rule verifies only the
shape and the holder-type code.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_PAN = re.compile(r"^([A-Z]{3})([A-Z])([A-Z])(\d{4})([A-Z])$")


def holder_type(pan: str, parameters: Mapping[str, Any]) -> str:
    """The holder type the fourth character denotes."""
    match = _PAN.match(pan)
    if match is None:
        raise ValueError("not a PAN")
    return parameters["holder_types"][match.group(2)]


def is_valid(pan: str, parameters: Mapping[str, Any]) -> bool:
    match = _PAN.match(pan)
    if match is None:
        return False
    low, high = parameters["sequence_range"]
    return match.group(2) in parameters["holder_types"] and low <= int(match.group(4)) <= high


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "holder_type_of" in value:
        return holder_type(str(value["holder_type_of"]), parameters)
    return is_valid(str(value), parameters)

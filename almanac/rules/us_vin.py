"""United States vehicle identification number (VIN) check digit, 49 CFR 565.15.

Each of the seventeen characters is transliterated to a numeric value,
multiplied by the weight of its position, and the products are summed. The
sum modulo 11 is the check digit, written as X when it is 10; it must appear
in position nine. The tables of values and weights come from the regulation.
"""

from __future__ import annotations

from typing import Any, Mapping

VIN_LENGTH = 17
CHECK_POSITION = 9


def check_digit(vin: str, parameters: Mapping[str, Any]) -> str:
    """The check character the regulation requires for ``vin``, ignoring whatever sits in position nine."""
    if len(vin) != VIN_LENGTH:
        raise ValueError("a VIN has seventeen characters")
    values: Mapping[str, int] = parameters["character_values"]
    weights: list[int] = parameters["weights"]
    total = 0
    for position, char in enumerate(vin.upper(), start=1):
        if position == CHECK_POSITION:
            continue
        if char not in values:
            raise ValueError(f"character {char!r} is not permitted in a VIN")
        total += values[char] * weights[position - 1]
    remainder = total % parameters["modulus"]
    return "X" if remainder == 10 else str(remainder)


def is_valid(vin: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``vin`` has seventeen permitted characters and a correct check digit."""
    try:
        return vin[CHECK_POSITION - 1].upper() == check_digit(vin, parameters)
    except (ValueError, IndexError):
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "check_digit_for" in value:
        return check_digit(str(value["check_digit_for"]), parameters)
    return is_valid(str(value), parameters)

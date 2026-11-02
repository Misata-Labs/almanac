"""Denmark's CPR number (personnummer): birth date, century-coded serial and the modulus 11 control.

A CPR number is ten digits DDMMYY followed by a four-digit serial whose last
digit is even for women and odd for men. The first digit of the serial,
together with the two-digit year, fixes the century. Until the serials with
a control digit ran out, the tenth digit was chosen so that the ten digits
weighted 4 3 2 7 6 5 4 3 2 1 sum to a multiple of 11; since 2007 the CPR
office also assigns numbers without that property, so the modulus check
identifies the older construction but does not decide validity.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

LENGTH = 10


def normalise(cpr: str) -> str:
    return cpr.replace("-", "").replace(" ", "")


def check_digit(first_nine: str, parameters: Mapping[str, Any]) -> str | None:
    """The control digit for ``first_nine`` digits, or None when the remainder leaves no single digit."""
    if len(first_nine) != LENGTH - 1 or not first_nine.isdigit():
        raise ValueError("the CPR body is nine digits")
    modulus = parameters["modulus"]
    remainder = sum(int(d) * w for d, w in zip(first_nine, parameters["weights"])) % modulus
    if remainder == 0:
        return "0"
    result = modulus - remainder
    return str(result) if result < 10 else None


def satisfies_modulus(cpr: str, parameters: Mapping[str, Any]) -> bool:
    """Whether the ten digits pass the modulus 11 control that pre-2007 numbers were built to satisfy."""
    digits = normalise(cpr)
    if len(digits) != LENGTH or not digits.isdigit():
        return False
    weights = list(parameters["weights"]) + [1]
    return sum(int(d) * w for d, w in zip(digits, weights)) % parameters["modulus"] == 0


def birth_date(cpr: str, parameters: Mapping[str, Any]) -> date:
    """Decode the birth date, resolving the century from the year and the serial's first digit."""
    digits = normalise(cpr)
    day, month, year, serial = int(digits[0:2]), int(digits[2:4]), int(digits[4:6]), digits[6]
    for row in parameters["centuries"]:
        if row["serial_first_digit"] == serial and row["year_from"] <= year <= row["year_to"]:
            return date(row["century"] + year, month, day)
    raise ValueError(f"serial digit {serial} with year {year:02d} matches no century row")


def sex(cpr: str) -> str:
    return "female" if int(normalise(cpr)[9]) % 2 == 0 else "male"


def is_well_formed(cpr: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``cpr`` is ten digits whose date and century resolve."""
    digits = normalise(cpr)
    if len(digits) != LENGTH or not digits.isdigit():
        return False
    try:
        birth_date(digits, parameters)
    except ValueError:
        return False
    return True


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "body" in value:
            return check_digit(str(value["body"]), parameters)
        if "modulus_check" in value:
            return satisfies_modulus(str(value["modulus_check"]), parameters)
        if "birth_date_of" in value:
            return birth_date(str(value["birth_date_of"]), parameters).isoformat()
        if "sex_of" in value:
            return sex(str(value["sex_of"]))
    return is_well_formed(str(value), parameters)

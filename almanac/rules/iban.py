"""International Bank Account Number (ISO 13616) check digits by ISO/IEC 7064 MOD 97-10.

Spaces are removed, the country code and the two check digits move to the
end, every letter is replaced by its two-digit value (A = 10 to Z = 35, from
the ``letter_values`` table) and the resulting integer is reduced modulo 97.
A valid IBAN leaves remainder 1. To issue check digits, the same number is
formed with ``00`` in their place and the remainder is subtracted from 98,
written with a leading zero when it is a single digit. ``lengths`` holds the
total IBAN length for the countries whose length the sources state; an IBAN
from a listed country must have exactly that length.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _compact(iban: str) -> str:
    return "".join(str(iban).split()).upper()


def _numeric(text: str, parameters: Mapping[str, Any]) -> int:
    values = parameters["letter_values"]
    digits = []
    for char in text:
        if char.isdigit():
            digits.append(char)
        elif char in values:
            digits.append(str(values[char]))
        else:
            raise ValueError(f"character {char!r} cannot appear in an IBAN")
    return int("".join(digits))


def check_digits(country: str, bban: str, parameters: Mapping[str, Any]) -> str:
    """The two check digits for the basic bank account number ``bban`` in ``country``."""
    rearranged = _compact(bban) + _compact(country) + "00"
    remainder = _numeric(rearranged, parameters) % parameters["modulus"]
    return f"{parameters['complement_base'] - remainder:02d}"


def is_valid(iban: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``iban`` (spaces allowed) has a known-length form and correct check digits."""
    compact = _compact(iban)
    if len(compact) < 5 or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    expected = parameters.get("lengths", {}).get(compact[:2])
    if expected is not None and len(compact) != expected:
        return False
    try:
        return _numeric(compact[4:] + compact[:4], parameters) % parameters["modulus"] == parameters["valid_remainder"]
    except ValueError:
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        return check_digits(str(value["country"]), str(value["bban"]), parameters)
    return is_valid(str(value), parameters)

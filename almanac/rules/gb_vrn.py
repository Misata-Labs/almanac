"""United Kingdom VAT registration number (VRN) check-digit rule.

A nine-digit VRN carries two check digits computed from the first seven with
a weighted sum reduced modulo 97. Two variants are accepted: the original
MOD 97 scheme and the later MOD 9755 scheme, which adds 55 to the sum
before reduction.
"""

from __future__ import annotations

from typing import Any, Mapping


def _reduce(total: int, modulus: int) -> int:
    while total > modulus:
        total -= modulus
    return total


def check_digits(body: str, parameters: Mapping[str, Any], variant: str = "mod97") -> str:
    """Compute the two check digits for a seven-digit ``body`` under ``variant``."""
    weights: list[int] = parameters["weights"]
    if len(body) != len(weights) or not body.isdigit():
        raise ValueError(f"VRN body must be {len(weights)} digits")
    total = sum(w * int(d) for w, d in zip(weights, body))
    if variant == "mod9755":
        total += parameters["variant_offset"]
    elif variant != "mod97":
        raise ValueError(f"unknown VRN variant {variant!r}")
    modulus = parameters["modulus"]
    return f"{modulus - _reduce(total, modulus):02d}"


def is_valid(vrn: str, parameters: Mapping[str, Any]) -> bool:
    """Return whether ``vrn`` is nine digits whose check digits satisfy either variant."""
    if len(vrn) != parameters["length"] or not vrn.isdigit():
        return False
    body, check = vrn[:-2], vrn[-2:]
    return check in {check_digits(body, parameters, "mod97"), check_digits(body, parameters, "mod9755")}


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value), parameters)

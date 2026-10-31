"""United Kingdom Unique Taxpayer Reference (UTR) check-digit rule.

A UTR is ten digits. The first digit is a check character derived from the
remaining nine with a weighted modulus-11 sum and a remainder lookup table.
Self Assessment references may carry a ``K`` before or after the digits.
"""

from __future__ import annotations

from typing import Any, Mapping

SCHEMES = ("sa", "ct")


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Compute the leading check digit for the nine-digit ``body``."""
    weights: list[int] = parameters["weights"]
    if len(body) != len(weights) or not body.isdigit():
        raise ValueError(f"UTR body must be {len(weights)} digits")
    total = sum(w * int(d) for w, d in zip(weights, body))
    return parameters["remainder_lookup"][total % parameters["modulus"]]


def strip_affix(reference: str, parameters: Mapping[str, Any], scheme: str) -> str:
    affix = parameters["sa_affix"]
    if scheme == "sa":
        if reference.startswith(affix):
            return reference[len(affix) :]
        if reference.endswith(affix):
            return reference[: -len(affix)]
    return reference


def is_valid(reference: str, parameters: Mapping[str, Any], scheme: str = "sa") -> bool:
    """Return whether ``reference`` is a well-formed UTR for ``scheme`` ('sa' or 'ct')."""
    if scheme not in SCHEMES:
        raise ValueError(f"unknown UTR scheme {scheme!r}")
    digits = strip_affix(reference.upper(), parameters, scheme)
    if len(digits) != parameters["length"] or not digits.isdigit():
        return False
    return digits[0] == check_digit(digits[1:], parameters)


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    if isinstance(value, Mapping):
        return is_valid(str(value["reference"]), parameters, str(value.get("scheme", "sa")))
    return is_valid(str(value), parameters)

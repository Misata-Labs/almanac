"""German account number check-digit methods (Prüfzifferberechnungsmethoden) of the Deutsche Bundesbank.

Every bank sort code (Bankleitzahl) names one two-character method that
decides whether a ten-digit account number is plausible. The account is
left-padded with zeros to ten digits and positions are numbered 1 to 10 from
the left. A method is a list of variants; the account is valid when any
variant that applies to it accepts it. A variant declares:

``positions``
    The positions that enter the weighted sum, read left to right.
``weights``
    Weights applied from the rightmost listed position leftwards, repeated
    cyclically when there are more positions than weights.
``check``
    The position of the check digit.
``reduce``
    How the weighted sum becomes a check digit: ``mod10`` (10 minus the units
    digit, 10 written 0), ``mod11`` (11 minus the remainder, remainder 0 gives
    0 and remainder 1 means no valid number), ``mod11_zero`` (remainders 0 and
    1 both give 0), ``mod11_remainder`` (the remainder itself, 10 means no
    valid number) and ``mod11_less_one`` (10 minus the remainder of the sum
    less one, remainder 0 giving 0).
``cross_sum``
    Replace each two-digit product by its digit sum before adding.
``shift``
    Move the account this many places to the left, filling with zeros, for
    accounts quoted without a trailing ``00`` sub-account; the dropped digits
    must be zeros.
``when`` / ``require``
    Lists of digit conditions such as ``{"position": 3, "in": [9]}`` or
    ``{"position": 9, "not_in": [8]}``; ``when`` selects whether the variant
    applies, ``require`` rejects the account when a condition fails.

Method 24 has its own procedure (``procedure: m24``): leading digits named in
``zero_leading`` are read as zeros, weighting starts at the first non-zero
digit, each product plus its weight is reduced modulo 11 and the units digit
of the sum is the check digit. ``unchecked: true`` marks a method without a
check, and ``valid_ranges`` lists account ranges that are valid without one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _normalise(account: str) -> str:
    digits = str(account).strip()
    if not digits.isdigit() or not 1 <= len(digits) <= 10:
        raise ValueError("an account number has one to ten digits")
    return digits.zfill(10)


def _matches(account: str, condition: Mapping[str, Any]) -> bool:
    digit = int(account[int(condition["position"]) - 1])
    if "in" in condition:
        return digit in condition["in"]
    return digit not in condition["not_in"]


def _reduce(total: int, method: str) -> int | None:
    if method == "mod10":
        return (10 - total % 10) % 10
    remainder = total % 11
    if method == "mod11":
        return None if remainder == 1 else (0 if remainder == 0 else 11 - remainder)
    if method == "mod11_zero":
        return 0 if remainder in (0, 1) else 11 - remainder
    if method == "mod11_remainder":
        return None if remainder == 10 else remainder
    if method == "mod11_less_one":
        remainder = (total - 1) % 11
        return 0 if remainder == 0 else 10 - remainder
    raise ValueError(f"unknown reduction {method!r}")


def _weighted_check(account: str, variant: Mapping[str, Any]) -> int | None:
    weights: Sequence[int] = variant["weights"]
    total = 0
    for index, position in enumerate(reversed(variant["positions"])):
        product = int(account[position - 1]) * weights[index % len(weights)]
        if variant.get("cross_sum") and product > 9:
            product = sum(int(c) for c in str(product))
        total += product
    return _reduce(total, variant["reduce"])


def _m24_check(account: str, variant: Mapping[str, Any]) -> int:
    digits = [int(c) for c in account[:9]]
    zeroed = variant["zero_leading"].get(str(digits[0]), 0)
    for index in range(zeroed):
        digits[index] = 0
    weights: Sequence[int] = variant["weights"]
    start = next((i for i, d in enumerate(digits) if d != 0), len(digits))
    total = 0
    for offset, digit in enumerate(digits[start:]):
        weight = weights[offset % len(weights)]
        total += (digit * weight + weight) % 11
    return total % 10


def _variant_accepts(account: str, variant: Mapping[str, Any]) -> bool | None:
    """True or False when the variant applies to ``account``, None when it does not apply."""
    if any(not _matches(account, c) for c in variant.get("when", [])):
        return None
    shift = int(variant.get("shift", 0))
    if shift:
        if account[:shift] != "0" * shift:
            return False
        account = account[shift:] + "0" * shift
    if any(not _matches(account, c) for c in variant.get("require", [])):
        return False
    if variant.get("procedure") == "m24":
        expected: int | None = _m24_check(account, variant)
    else:
        expected = _weighted_check(account, variant)
    return expected is not None and expected == int(account[variant["check"] - 1])


def method(parameters: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    try:
        return parameters["methods"][code]
    except KeyError as exc:
        raise KeyError(f"method {code!r} is not implemented") from exc


def is_valid(code: str, account: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``account`` passes check-digit method ``code``."""
    try:
        account = _normalise(account)
    except ValueError:
        return False
    spec = method(parameters, code)
    if spec.get("unchecked"):
        return True
    for low, high in spec.get("valid_ranges", []):
        if int(low) <= int(account) <= int(high):
            return True
    return any(_variant_accepts(account, variant) for variant in spec["variants"])


def complete(code: str, account: str, parameters: Mapping[str, Any]) -> str | None:
    """Fill the check position of the first variant with the smallest digit that makes ``account`` valid."""
    account = _normalise(account)
    spec = method(parameters, code)
    if spec.get("unchecked"):
        return account
    position = spec["variants"][0]["check"]
    for digit in "0123456789":
        candidate = account[: position - 1] + digit + account[position:]
        if is_valid(code, candidate, parameters):
            return candidate
    return None


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    code = str(value["method"])
    if "complete" in value:
        return complete(code, str(value["complete"]), parameters)
    return is_valid(code, str(value["account"]), parameters)

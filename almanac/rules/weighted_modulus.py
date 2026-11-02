"""Position-weighted modulus check digits, the family behind many national identifiers.

Every digit of the number except the check digit is multiplied by the weight
of its position, the products are summed and the sum is reduced modulo the
modulus. The check digit is either that remainder (``check: remainder``) or
the modulus minus it (``check: complement``). Remainders the issuing body
treats specially are listed in ``remainder_map``: a digit to use instead, or
null when no valid check digit exists and the number is never issued. When
``fallback_weights`` is given, a first pass that ends in ``retry_remainder``
is recomputed with those weights, as the Lithuanian personal code requires.
``check_position`` (1-based, within the full number) defaults to the last
digit; weights apply to the remaining digits read left to right.
"""

from __future__ import annotations

from typing import Any, Mapping


def _remainder(body: str, weights: list[int], modulus: int) -> int:
    if len(body) != len(weights):
        raise ValueError(f"body must have {len(weights)} digits")
    return sum(int(digit) * weight for digit, weight in zip(body, weights)) % modulus


def _resolve(remainder: int, parameters: Mapping[str, Any]) -> int | None:
    mapped = parameters.get("remainder_map", {})
    if str(remainder) in mapped:
        return mapped[str(remainder)]
    if parameters["check"] == "remainder":
        result = remainder
    else:
        result = parameters["modulus"] - remainder
    return result if 0 <= result <= 9 else None


def check_digit(body: str, parameters: Mapping[str, Any]) -> str | None:
    """The check digit for ``body``, or None when the arithmetic yields no single digit."""
    if not body.isdigit():
        raise ValueError("the body must be digits only")
    remainder = _remainder(body, parameters["weights"], parameters["modulus"])
    fallback = parameters.get("fallback_weights")
    if fallback is not None and remainder == parameters.get("retry_remainder"):
        remainder = _remainder(body, fallback, parameters["modulus"])
    result = _resolve(remainder, parameters)
    return None if result is None else str(result)


def split(number: str, parameters: Mapping[str, Any]) -> tuple[str, str]:
    """Separate ``number`` into its body digits and its check digit."""
    length = len(parameters["weights"]) + 1
    if len(number) != length or not number.isdigit():
        raise ValueError(f"the number must be {length} digits")
    position = parameters.get("check_position", length)
    return number[: position - 1] + number[position:], number[position - 1]


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` carries the check digit its body requires."""
    try:
        body, check = split(number, parameters)
        return check_digit(body, parameters) == check
    except ValueError:
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "body" in value:
        return check_digit(str(value["body"]), parameters)
    return is_valid(str(value), parameters)

"""ISO/IEC 7064 MOD 11,10 check digit, as the German tax authorities publish it for the IdNr.

The digits are folded left to right: each digit is added to a running
product and reduced modulo 10 (a zero becoming 10), and the doubled result
is reduced modulo 11 to form the next product. The check digit is 11 minus
the final product, written 0 when that difference is 10. The modulus and
radix are parameters so the same fold serves every identifier built on the
standard, such as the Croatian OIB.
"""

from __future__ import annotations

from typing import Any, Mapping


def check_digit(body: str, parameters: Mapping[str, Any]) -> str:
    """Check digit for the digit string ``body``."""
    if not body.isdigit():
        raise ValueError("the body must be digits only")
    length = parameters.get("body_length")
    if length is not None and len(body) != length:
        raise ValueError(f"body must be {length} digits")
    modulus, radix = parameters["modulus"], parameters["radix"]
    product = radix
    for char in body:
        total = (int(char) + product) % radix
        if total == 0:
            total = radix
        product = (2 * total) % modulus
    result = modulus - product
    return "0" if result == radix else str(result)


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` (body plus trailing check digit) carries the right check digit."""
    if not number.isdigit() or len(number) < 2:
        return False
    try:
        return check_digit(number[:-1], parameters) == number[-1]
    except ValueError:
        return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "body" in value:
        return check_digit(str(value["body"]), parameters)
    return is_valid(str(value), parameters)

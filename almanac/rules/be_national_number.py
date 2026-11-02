"""Belgium's national register number: birth date, order number and modulus 97 control number.

The eleven digits are YYMMDD, a three-digit order number (odd for men, even
for women) and a two-digit control number: 97 minus the remainder of the
nine preceding digits divided by 97. For people born from 2000 the digit 2
is placed in front of the nine digits before dividing, so the control number
also tells the birth periods apart. Unknown birth months or days are written 00.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

LENGTH = 11
BODY_LENGTH = 9


def normalise(number: str) -> str:
    return re.sub(r"[.\- ]", "", number)


def control_number(body: str, period: str, parameters: Mapping[str, Any]) -> str:
    """Two-digit control number for the nine digits ``body`` of a person born in birth ``period``."""
    if len(body) != BODY_LENGTH or not body.isdigit():
        raise ValueError("the body is nine digits")
    try:
        prefix = parameters["prefix_by_birth_period"][period]
    except KeyError as exc:
        raise ValueError(f"no prefix rule for birth period {period!r}") from exc
    modulus = parameters["modulus"]
    return f"{modulus - int(prefix + body) % modulus:02d}"


def birth_period_of(number: str, parameters: Mapping[str, Any]) -> str | None:
    """The birth period whose prefix reproduces the control number, or None when none does."""
    digits = normalise(number)
    if len(digits) != LENGTH or not digits.isdigit():
        return None
    body, control = digits[:BODY_LENGTH], digits[BODY_LENGTH:]
    for period in parameters["prefix_by_birth_period"]:
        if control_number(body, period, parameters) == control:
            return period
    return None


def sex(number: str) -> str:
    return "male" if int(normalise(number)[6:9]) % 2 else "female"


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether the control number matches the body under one of the birth-period rules."""
    return birth_period_of(number, parameters) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "body" in value:
            return control_number(str(value["body"]), str(value["period"]), parameters)
        if "birth_period_of" in value:
            return birth_period_of(str(value["birth_period_of"]), parameters)
        if "sex_of" in value:
            return sex(str(value["sex_of"]))
    return is_valid(str(value), parameters)

"""Finland's personal identity code (henkilötunnus) and business ID shapes.

A personal identity code is eleven characters: the birth date as DDMMYY, a
century sign, a three-digit individual number and a control character. The
century sign is + for 1800 to 1899, a hyphen or one of Y X W V U for 1900
to 1999, and one of A to F from 2000. A business ID is seven digits, a
hyphen and a control digit. The control arithmetic is not part of the cited
description, so the rule checks shape and decodes the birth century.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def century_of(sign: str, parameters: Mapping[str, Any]) -> int:
    """The first year of the century a century ``sign`` denotes."""
    for century, signs in parameters["century_signs"].items():
        if sign in signs:
            return int(century)
    raise ValueError(f"{sign!r} is not a century sign")


def _personal_pattern(parameters: Mapping[str, Any]) -> re.Pattern[str]:
    signs = "".join(re.escape(sign) for signs in parameters["century_signs"].values() for sign in signs)
    return re.compile(rf"^(\d{{2}})(\d{{2}})(\d{{2}})([{signs}])(\d{{3}})([0-9A-Z])$")


def is_personal_code(code: str, parameters: Mapping[str, Any]) -> bool:
    return _personal_pattern(parameters).fullmatch(code) is not None


def is_business_id(code: str, parameters: Mapping[str, Any]) -> bool:
    return re.fullmatch(parameters["business_id_pattern"], code) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "century_of" in value:
            return century_of(str(value["century_of"]), parameters)
        if "business_id" in value:
            return is_business_id(str(value["business_id"]), parameters)
    return is_personal_code(str(value), parameters)

"""France's SIREN and SIRET identifiers as INSEE defines them.

A SIREN is nine digits identifying a legal unit, the ninth being a check
digit. A SIRET is fourteen digits identifying an establishment: the SIREN
followed by the NIC, a four-digit order number and one check digit over the
whole SIRET. The check-digit arithmetic is not part of the cited
definitions, so the rule verifies lengths and composition only.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def normalise(number: str) -> str:
    return re.sub(r"\s", "", number)


def is_siren(number: str, parameters: Mapping[str, Any]) -> bool:
    digits = normalise(number)
    return digits.isdigit() and len(digits) == parameters["siren_length"]


def is_siret(number: str, parameters: Mapping[str, Any]) -> bool:
    digits = normalise(number)
    return digits.isdigit() and len(digits) == parameters["siren_length"] + parameters["nic_length"]


def siren_of(siret: str, parameters: Mapping[str, Any]) -> str:
    if not is_siret(siret, parameters):
        raise ValueError("not a SIRET")
    return normalise(siret)[: parameters["siren_length"]]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "siren_of" in value:
            return siren_of(str(value["siren_of"]), parameters)
        kind, number = str(value["kind"]), str(value["value"])
        return is_siren(number, parameters) if kind == "siren" else is_siret(number, parameters)
    digits = normalise(str(value))
    return is_siren(digits, parameters) or is_siret(digits, parameters)

"""File names for invoices sent to Italy's Sistema di Interscambio (SdI).

A file name is the transmitter's country code (ISO 3166-1 alpha-2), the
transmitter's tax identifier, an underscore and a unique progressive of up
to five letters or digits, followed by an extension: ``.xml`` for a XAdES
signature, ``.xml.p7m`` for CAdES, or ``.zip`` for an archive of such files.
The identifier length depends on the country: an Italian codice fiscale or
partita IVA, or a foreign tax identifier. The parameters hold those lengths,
the progressive's maximum length and the permitted extensions.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from almanac.models import Statistic

_SHAPE = re.compile(r"^([A-Z]{2})([A-Za-z0-9]+)_([A-Za-z0-9]+)(\..+)$")


def parse(name: str) -> dict[str, str]:
    """Split a file name into country, identifier, progressive and extension; raises ValueError on another shape."""
    match = _SHAPE.match(name)
    if match is None:
        raise ValueError(f"{name!r} is not country + identifier + '_' + progressive + extension")
    country, identifier, progressive, extension = match.groups()
    return {"country": country, "identifier": identifier, "progressive": progressive, "extension": extension}


def is_valid(name: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``name`` follows the SdI naming rule for a transmitted file."""
    try:
        parts = parse(name)
    except ValueError:
        return False
    low, high = parameters["identifier_length"].get(parts["country"], parameters["identifier_length"]["other"])
    if not low <= len(parts["identifier"]) <= high:
        return False
    if len(parts["progressive"]) > parameters["progressive_max_length"]:
        return False
    return parts["extension"] in parameters["extensions"]


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "part" in value:
            return parse(str(value["name"]))[str(value["part"])]
        return is_valid(str(value["name"]), parameters)
    return is_valid(str(value), parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and stat.args == ("extensions",):
        return len(parameters["extensions"])
    if stat.name == "value" and len(stat.args) == 1:
        return parameters[stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

"""Peppol participant identifiers and their SML DNS names.

A Peppol participant identifier is an ISO 6523 international code designator
(ICD) and an identifier value joined by a colon, such as ``0088:7300010000001``,
optionally preceded by the meta scheme and a double colon. The parameters
hold the meta scheme, the ICD values the Peppol code list marks active, the
permitted value length and the permitted value characters.

The Service Metadata Locator publishes each participant under a DNS name
built from the Base32 encoding, without padding, of the SHA-256 digest of the
lowercased identifier, followed by the meta scheme and the SML zone.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Mapping, NamedTuple

from almanac.models import Statistic


class ParticipantId(NamedTuple):
    scheme: str | None
    icd: str
    value: str


def parse(identifier: str) -> ParticipantId:
    """Split ``[scheme::]icd:value``; raises ValueError when the shape is wrong."""
    scheme: str | None = None
    rest = identifier
    if "::" in identifier:
        scheme, rest = identifier.split("::", 1)
    icd, sep, value = rest.partition(":")
    if not sep:
        raise ValueError(f"{identifier!r} has no ICD separator")
    return ParticipantId(scheme, icd, value)


def is_valid(identifier: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``identifier`` uses the meta scheme, an active ICD and a value of permitted length and characters."""
    try:
        parsed = parse(identifier)
    except ValueError:
        return False
    if parsed.scheme is not None and parsed.scheme != parameters["meta_scheme"]:
        return False
    if parsed.icd not in parameters["active_icd"]:
        return False
    if not parameters["min_value_length"] <= len(parsed.value) <= parameters["max_value_length"]:
        return False
    return re.fullmatch(parameters["value_pattern"], parsed.value) is not None


def sml_hash(identifier: str) -> str:
    """Base32 (RFC 4648, unpadded) of the SHA-256 of the lowercased ``icd:value``."""
    parsed = parse(identifier)
    digest = hashlib.sha256(f"{parsed.icd}:{parsed.value}".lower().encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")


def dns_name(identifier: str, parameters: Mapping[str, Any], zone: str) -> str:
    """The SML DNS name ``<hash>.<meta scheme>.<zone>`` for ``identifier``."""
    return f"{sml_hash(identifier)}.{parameters['meta_scheme']}.{zone}"


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "dns_name" in value:
            return dns_name(str(value["dns_name"]), parameters, str(value["zone"]))
        if "sml_hash" in value:
            return sml_hash(str(value["sml_hash"]))
        return is_valid(str(value["identifier"]), parameters)
    return is_valid(str(value), parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> Any:
    if stat.name == "count" and stat.args == ("active_icd",):
        return len(parameters["active_icd"])
    if stat.name == "value" and len(stat.args) == 1:
        return parameters[stat.args[0]]
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

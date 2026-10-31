"""Email address acceptance rule used across HM Revenue & Customs services.

The rule is a pattern for the whole address plus a stricter pattern for the
domain part. It is deliberately narrower than RFC 5322: no quoted local
parts, no IP-literal domains, no leading or trailing dots in the domain.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def is_valid(address: str, parameters: Mapping[str, Any]) -> bool:
    return re.fullmatch(parameters["address_pattern"], address) is not None


def is_valid_domain(domain: str, parameters: Mapping[str, Any]) -> bool:
    return re.fullmatch(parameters["domain_pattern"], domain) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    if isinstance(value, Mapping):
        part = str(value.get("part", "address"))
        text = str(value["value"])
        return is_valid_domain(text, parameters) if part == "domain" else is_valid(text, parameters)
    return is_valid(str(value), parameters)

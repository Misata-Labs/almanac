"""Format of the nine-digit United States taxpayer identifiers written 000-00-0000 (SSN, ITIN).

The three groups are the area, group and serial. Parameters list area
values that are never assigned (exact values and inclusive ranges), a
required leading digit for the area where one applies, and the group and
serial values that are never assigned. A mask as a publisher prints it, such
as 9xx-xx-xxxx, can be checked for consistency with the same parameters.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

GROUPS = (3, 2, 4)
_NUMBER = re.compile(r"^(\d{3})-?(\d{2})-?(\d{4})$")
_MASK = re.compile(r"^([\dx]{3})-?([\dx]{2})-?([\dx]{4})$", re.IGNORECASE)


def _area_allowed(area: str, parameters: Mapping[str, Any]) -> bool:
    prefix = parameters.get("area_required_prefix")
    if prefix and not area.startswith(prefix):
        return False
    if area in parameters.get("area_forbidden", []):
        return False
    return not any(low <= area <= high for low, high in parameters.get("area_forbidden_ranges", []))


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``number`` (hyphens optional) has three groups that could have been assigned."""
    match = _NUMBER.match(number)
    if match is None:
        return False
    area, group, serial = match.groups()
    return (
        _area_allowed(area, parameters)
        and group not in parameters.get("group_forbidden", [])
        and serial not in parameters.get("serial_forbidden", [])
    )


def mask_is_consistent(mask: str, parameters: Mapping[str, Any]) -> bool:
    """Whether a printed mask (x for any digit) admits at least one assignable number."""
    match = _MASK.match(mask)
    if match is None:
        return False
    fixed = "".join(match.groups()).lower()
    for candidate in ("1", "2", "5"):
        number = "".join(candidate if c == "x" else c for c in fixed)
        if is_valid(number, parameters):
            return True
    return False


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping):
        if "mask" in value:
            return mask_is_consistent(str(value["mask"]), parameters)
        if "area" in value:
            return _area_allowed(str(value["area"]), parameters)
    return is_valid(str(value), parameters)

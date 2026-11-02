"""United States employer identification number (EIN): the 00-0000000 form and the assigned prefixes.

The two leading digits identify the IRS campus or channel that assigned the
number; the parameters map each location to its prefixes. A number is well
formed when it has nine digits with an optional hyphen after the second and
its prefix appears in the table.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_NUMBER = re.compile(r"^(\d{2})-?(\d{7})$")


def locations_for(prefix: str, parameters: Mapping[str, Any]) -> list[str]:
    """The campuses or channels that assign ``prefix``, in the order the table lists them."""
    return [location for location, prefixes in parameters["prefixes_by_location"].items() if prefix in prefixes]


def is_valid(number: str, parameters: Mapping[str, Any]) -> bool:
    match = _NUMBER.match(number)
    return match is not None and bool(locations_for(match.group(1), parameters))


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if isinstance(value, Mapping) and "locations_for" in value:
        return locations_for(str(value["locations_for"]), parameters)
    return is_valid(str(value), parameters)

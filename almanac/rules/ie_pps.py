"""Ireland's tax reference numbers: the PPS-based TRN and the CHY charity number.

A TRN is seven digits followed by one or two letters; a charity reference is
CHY followed by one to five digits. The arithmetic behind the trailing
letter is not part of the cited description, so the rule checks shape only.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def is_valid(value: str, parameters: Mapping[str, Any], kind: str) -> bool:
    """Whether ``value`` has the published shape of reference ``kind``."""
    try:
        pattern = parameters["patterns"][kind]
    except KeyError as exc:
        raise KeyError(f"unknown reference kind {kind!r}") from exc
    return re.fullmatch(pattern, value) is not None


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value["value"]), parameters, str(value["kind"]))

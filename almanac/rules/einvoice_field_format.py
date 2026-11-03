"""Field formats declared by e-invoicing schemas as XML Schema facets.

Tax authorities publish their structured invoice formats as XML Schema, where
each identifier or code field is a simple type restricted by a regular
expression, length facets and a whitespace rule. The parameters hold those
facets per field exactly as the schema states them; the rule answers whether
a value satisfies every facet of a field.

XML Schema patterns always match the whole value and may use Unicode block
escapes such as ``\\p{IsBasicLatin}``; both are translated to Python's
``re`` before matching.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping

from almanac.models import Statistic

# Unicode block escapes that appear in tax-authority schemas, as code-point ranges.
_BLOCKS = {
    "IsBasicLatin": "\\x00-\\x7F",
    "IsLatin-1Supplement": "\\x80-\\xFF",
}
_BLOCK_ESCAPE = re.compile(r"\\p\{(Is[A-Za-z0-9-]+)\}")


def _block_range(match: re.Match[str], inside_class: bool) -> str:
    try:
        span = _BLOCKS[match.group(1)]
    except KeyError as exc:
        raise ValueError(f"unsupported XML Schema block escape {match.group(0)}") from exc
    return span if inside_class else f"[{span}]"


@lru_cache(maxsize=256)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile an XML Schema regular expression as an anchored Python pattern."""
    translated: list[str] = []
    depth = 0
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            block = _BLOCK_ESCAPE.match(pattern, index)
            if block is not None:
                translated.append(_block_range(block, depth > 0))
                index = block.end()
                continue
            translated.append(pattern[index : index + 2])
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        translated.append(char)
        index += 1
    return re.compile("".join(translated))


def field(parameters: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    try:
        return parameters["fields"][name]
    except KeyError as exc:
        raise KeyError(f"unknown field {name!r}") from exc


def normalise(value: str, facets: Mapping[str, Any]) -> str:
    """Apply the schema's whitespace facet: ``collapse`` trims and folds runs of whitespace."""
    rule = facets.get("whitespace", "preserve")
    if rule == "collapse":
        return " ".join(value.split())
    if rule == "replace":
        return re.sub(r"[\t\n\r]", " ", value)
    return value


def is_valid(value: str, parameters: Mapping[str, Any], name: str) -> bool:
    """Whether ``value`` satisfies every length and pattern facet of field ``name``."""
    facets = field(parameters, name)
    text = normalise(value, facets)
    size = len(text)
    if "length" in facets and size != facets["length"]:
        return False
    if "min_length" in facets and size < facets["min_length"]:
        return False
    if "max_length" in facets and size > facets["max_length"]:
        return False
    patterns = facets.get("patterns", [])
    return not patterns or any(compile_pattern(p).fullmatch(text) for p in patterns)


def evaluate(parameters: Mapping[str, Any], value: Any) -> bool:
    return is_valid(str(value["value"]), parameters, str(value["field"]))


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> int:
    if stat.name == "count" and not stat.args:
        return len(parameters["fields"])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

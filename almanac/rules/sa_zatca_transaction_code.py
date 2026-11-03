"""Saudi Arabia ZATCA e-invoice type codes and the invoice transaction code (KSA-2).

A ZATCA invoice carries a UN/CEFACT 1001 type code (BT-3) and, in the
``name`` attribute of the same element, a seven-character transaction code
written NNPNESB: a two-digit invoice subtype followed by five 0/1 flags for
third-party, nominal, export, summary and self-billed transactions. Export
invoices may not be self-billed. The parameters hold the permitted type
codes, the subtypes, the flag order and the forbidden flag combinations.
"""

from __future__ import annotations

from typing import Any, Mapping

from almanac.models import Statistic


def parse(code: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Split a transaction code into its subtype and named flags; raises ValueError on a malformed code."""
    flags = parameters["flags"]
    if len(code) != 2 + len(flags):
        raise ValueError(f"transaction code {code!r} must be {2 + len(flags)} characters")
    subtype, bits = code[:2], code[2:]
    if subtype not in parameters["subtypes"]:
        raise ValueError(f"unknown invoice subtype {subtype!r}")
    if any(bit not in "01" for bit in bits):
        raise ValueError(f"flags in {code!r} must be 0 or 1")
    return {"subtype": subtype, **{flag: bit == "1" for flag, bit in zip(flags, bits)}}


def is_valid(code: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``code`` is well formed and sets no forbidden combination of flags."""
    try:
        parsed = parse(code, parameters)
    except ValueError:
        return False
    return not any(all(parsed[flag] for flag in combination) for combination in parameters["forbidden_combinations"])


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    if "type_code" in value:
        return str(value["type_code"]) in parameters["type_codes"]
    code = str(value["transaction_code"])
    if "field" in value:
        return parse(code, parameters)[str(value["field"])]
    return is_valid(code, parameters)


def statistic(parameters: Mapping[str, Any], stat: Statistic) -> int:
    if stat.name == "count" and len(stat.args) == 1 and stat.args[0] in ("type_codes", "subtypes", "flags"):
        return len(parameters[stat.args[0]])
    raise ValueError(f"unsupported statistic {stat.name}{list(stat.args)}")

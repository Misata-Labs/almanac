"""Executable rule implementations referenced by Almanac entries.

Every rule module exposes ``evaluate(parameters, value)``, which applies the
rule described by an entry's ``spec.parameters`` to one test-vector input.
Modules may also expose ``statistic(parameters, statistic)`` to answer the
named statistics an entry lists under ``tests``.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Callable, Mapping, Protocol

from almanac.models import Statistic

RULES_PACKAGE = __name__


class RuleModule(Protocol):
    def evaluate(self, parameters: Mapping[str, Any], value: Any) -> Any: ...


def load_rule(implementation: str) -> ModuleType:
    """Import the rule module named by an entry's ``spec.implementation``."""
    if not implementation.startswith(f"{RULES_PACKAGE}."):
        raise ValueError(f"{implementation} is outside the {RULES_PACKAGE} package")
    module = importlib.import_module(implementation)
    if not callable(getattr(module, "evaluate", None)):
        raise ValueError(f"{implementation} does not define evaluate()")
    return module


def statistic_resolver(module: ModuleType) -> Callable[[Mapping[str, Any], Statistic], Any] | None:
    resolver = getattr(module, "statistic", None)
    return resolver if callable(resolver) else None

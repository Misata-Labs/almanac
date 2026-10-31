"""Programmatic access to the Almanac for data engines and scripts.

``Almanac.load()`` reads every entry under ``entries/`` into typed models.
From there a caller can ask which entries applied on a date, fetch one by
id, or bind a rule to its parameters and evaluate values against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

from almanac.models import Entry, RuleSpec
from almanac.rules import load_rule
from almanac.store import DEFAULT_ENTRIES, discover, read_entry_file


@dataclass(frozen=True)
class BoundRule:
    """A rule implementation joined to the parameters of one entry."""

    entry: Entry
    module: ModuleType

    @property
    def parameters(self) -> dict[str, Any]:
        assert isinstance(self.entry.spec, RuleSpec)
        return self.entry.spec.parameters

    def evaluate(self, value: Any) -> Any:
        """Apply the rule to ``value`` exactly as the verifier applies it to test vectors."""
        return self.module.evaluate(self.parameters, value)

    def call(self, helper: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke a named helper of the rule module with this entry's parameters supplied."""
        function = getattr(self.module, helper)
        return function(*args, self.parameters, **kwargs)


class Almanac:
    """An in-memory view of a set of entries."""

    def __init__(self, entries: dict[str, tuple[Entry, Path]]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, root: Path | str = DEFAULT_ENTRIES) -> Almanac:
        entries: dict[str, tuple[Entry, Path]] = {}
        for path in discover([Path(root)]):
            entry = Entry.model_validate(read_entry_file(path).raw)
            if entry.id in entries:
                raise ValueError(f"duplicate entry id {entry.id!r} at {path} and {entries[entry.id][1]}")
            entries[entry.id] = (entry, path)
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Entry]:
        return (entry for entry, _ in self._entries.values())

    def __contains__(self, entry_id: str) -> bool:
        return entry_id in self._entries

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def get(self, entry_id: str) -> Entry:
        try:
            return self._entries[entry_id][0]
        except KeyError as exc:
            raise KeyError(f"no entry with id {entry_id!r}") from exc

    def path(self, entry_id: str) -> Path:
        return self._entries[entry_id][1]

    def select(
        self,
        *,
        on: date | None = None,
        region: str | None = None,
        domain: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        use_case: str | None = None,
        tag: str | None = None,
    ) -> list[Entry]:
        """Entries matching every given filter; ``on`` keeps those whose validity covers that date."""
        chosen = []
        for entry in self:
            if on is not None and not entry.applies_on(on):
                continue
            if region is not None and entry.region not in (region, "global"):
                continue
            if domain is not None and entry.domain != domain:
                continue
            if kind is not None and entry.kind != kind:
                continue
            if status is not None and entry.status != status:
                continue
            if use_case is not None and use_case not in entry.use_cases:
                continue
            if tag is not None and tag not in entry.tags:
                continue
            chosen.append(entry)
        return sorted(chosen, key=lambda e: (e.domain, e.region, e.id))

    def rule(self, entry_id: str) -> BoundRule:
        entry = self.get(entry_id)
        if not isinstance(entry.spec, RuleSpec):
            raise TypeError(f"{entry_id} is a {entry.kind} entry, not a rule")
        return BoundRule(entry=entry, module=load_rule(entry.spec.implementation))

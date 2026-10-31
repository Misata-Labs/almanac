"""Discovery and loading of entry files from the ``entries/`` tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

ENTRY_SUFFIX = ".yaml"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENTRIES = REPO_ROOT / "entries"
DEFAULT_SCHEMA = REPO_ROOT / "schema" / "entry.schema.json"


class EntryLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps dates and timestamps as the strings written in the file."""


EntryLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass(frozen=True)
class EntryFile:
    """A located entry document together with the raw mapping it parsed to."""

    path: Path
    raw: dict[str, Any]

    @property
    def expected_domain(self) -> str:
        return self.path.parent.parent.name

    @property
    def expected_region(self) -> str:
        return self.path.parent.name

    @property
    def expected_id(self) -> str:
        return self.path.stem


def discover(targets: list[Path]) -> list[Path]:
    """Expand files and directories into the sorted list of entry files they contain."""
    found: set[Path] = set()
    for target in targets:
        if target.is_dir():
            found.update(p for p in target.rglob(f"*{ENTRY_SUFFIX}") if p.is_file())
        elif target.is_file() and target.suffix == ENTRY_SUFFIX:
            found.add(target)
        else:
            raise FileNotFoundError(f"{target} is not an entry file or directory")
    return sorted(found)


def read_entry_file(path: Path | str) -> EntryFile:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.load(handle, Loader=EntryLoader)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: entry document must be a mapping")
    return EntryFile(path=path, raw=raw)


def iter_entry_files(targets: list[Path]) -> Iterator[EntryFile]:
    for path in discover(targets):
        yield read_entry_file(path)

"""Offline checks over every committed entry: schema, models, locations, vectors and statistics."""

from __future__ import annotations

from datetime import date

import pytest

from almanac.checks import Verifier
from almanac.store import discover, read_entry_file
from tests.conftest import REPO_ROOT

ENTRY_PATHS = discover([REPO_ROOT / "entries"])


def test_entries_exist():
    assert len(ENTRY_PATHS) >= 4


@pytest.mark.parametrize("path", ENTRY_PATHS, ids=[p.stem for p in ENTRY_PATHS])
def test_entry_passes_offline_checks(schema, path):
    report = Verifier(schema, None, today=date.today(), sample_size=200_000).verify(read_entry_file(path))
    failures = [(r.name, r.detail) for r in report.results if r.failed]
    assert not failures, failures


@pytest.mark.parametrize("path", ENTRY_PATHS, ids=[p.stem for p in ENTRY_PATHS])
def test_vectors_come_from_sources_or_are_labelled(path):
    raw = read_entry_file(path).raw
    if raw["kind"] != "rule":
        return
    origins = {vector["origin"] for vector in raw["spec"]["vectors"]}
    assert "source" in origins


@pytest.mark.parametrize("path", ENTRY_PATHS, ids=[p.stem for p in ENTRY_PATHS])
def test_snippets_are_short_and_single(path):
    for item in read_entry_file(path).raw["evidence"]:
        assert len(item["snippet"].split()) < 25

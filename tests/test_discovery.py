from __future__ import annotations

import json

import pytest

from almanac.api import Almanac
from almanac.discovery import render_jsonld, render_llms_txt, render_manifest
from almanac.models import Statistic, split_arguments
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def almanac() -> Almanac:
    return Almanac.load(REPO_ROOT / "entries")


def test_manifest_lists_every_entry(almanac):
    manifest = json.loads(render_manifest(almanac))
    assert manifest["entry_count"] == len(almanac)
    ids = {e["id"] for e in manifest["entries"]}
    assert ids == set(almanac.ids())
    rule = next(e for e in manifest["entries"] if e["id"] == "gb-nino-format")
    assert rule["implementation"] == "almanac.rules.gb_nino" and rule["valid_to"] is None
    stat = next(e for e in manifest["entries"] if e["kind"] != "rule")
    assert "observed_period" in stat


def test_jsonld_is_a_schema_org_dataset(almanac):
    doc = json.loads(render_jsonld(almanac))
    assert doc["@type"] == "Dataset" and doc["creator"]["name"] == "Muhammed Rasin"
    assert len(doc["hasPart"]) == len(almanac)
    assert "synthetic data" in doc["keywords"]


def test_llms_txt_names_every_entry(almanac):
    text = render_llms_txt(almanac)
    assert text.startswith("# Misata Almanac")
    for entry_id in almanac.ids():
        assert f"[{entry_id}]" in text


def test_committed_indexes_are_current(almanac):
    assert (REPO_ROOT / "manifest.json").read_text(encoding="utf-8") == render_manifest(almanac), "run: uv run almanac index"
    assert (REPO_ROOT / "dataset.jsonld").read_text(encoding="utf-8") == render_jsonld(almanac), "run: uv run almanac index"
    assert (REPO_ROOT / "llms.txt").read_text(encoding="utf-8") == render_llms_txt(almanac), "run: uv run almanac index"


def test_quoted_statistic_arguments():
    assert split_arguments('"White: English, Welsh", 2026') == ("White: English, Welsh", "2026")
    assert Statistic.parse('share["a, b"]').args == ("a, b",)
    assert Statistic.parse("count[x, y]").args == ("x", "y")

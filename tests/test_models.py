from __future__ import annotations

import pytest
from pydantic import ValidationError

from almanac.models import Entry, Statistic, is_known_unit


def _rule_entry(**overrides):
    entry = {
        "id": "xx-sample-rule",
        "title": "Sample rule",
        "kind": "rule",
        "domain": "identifiers",
        "region": "XX",
        "status": "draft",
        "tier": "A",
        "valid_from": "2024-01-01",
        "valid_to": None,
        "spec": {"implementation": "almanac.rules.gb_vrn", "parameters": {}, "vectors": [{"input": "x", "expected": False, "origin": "source"}]},
        "evidence": [
            {
                "publisher": "P",
                "title": "T",
                "url": "https://example.test/x",
                "accessed_at": "2026-01-01",
                "locator": "l1",
                "value": "v",
                "unit": "text",
                "snippet": "snip",
                "source_license": "MIT",
                "content_sha256": "0" * 64,
            }
        ],
        "assumed": [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}],
        "notes": "",
    }
    entry.update(overrides)
    return entry


def test_spec_is_selected_by_kind():
    entry = Entry.model_validate(_rule_entry())
    assert entry.spec.kind == "rule"
    assert entry.spec.implementation == "almanac.rules.gb_vrn"


def test_rule_requires_valid_from():
    with pytest.raises(ValidationError, match="valid_from"):
        Entry.model_validate(_rule_entry(valid_from=None))


def test_valid_to_cannot_precede_valid_from():
    with pytest.raises(ValidationError, match="precedes"):
        Entry.model_validate(_rule_entry(valid_to="2023-12-31"))


def test_statistics_require_observed_period():
    raw = _rule_entry(kind="marginal", spec={"variable": "x", "unit": "count", "distribution": {"family": "normal", "parameters": {"mean": 0, "std": 1}}})
    raw.pop("valid_from")
    with pytest.raises(ValidationError, match="observed_period"):
        Entry.model_validate(raw)


def test_applies_on_uses_validity_window():
    entry = Entry.model_validate(_rule_entry(valid_to="2024-12-31"))
    from datetime import date

    assert entry.applies_on(date(2024, 6, 1))
    assert not entry.applies_on(date(2025, 1, 1))


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Entry.model_validate(_rule_entry(extra="no"))


@pytest.mark.parametrize(
    ("text", "name", "args"),
    [("mean", "mean", ()), ("share[female]", "share", ("female",)), ("count[scotland, 2026]", "count", ("scotland", "2026"))],
)
def test_statistic_parsing(text, name, args):
    parsed = Statistic.parse(text)
    assert (parsed.name, parsed.args) == (name, args)


def test_statistic_rejects_garbage():
    with pytest.raises(ValueError):
        Statistic.parse("Mean()")


def test_unit_vocabulary():
    assert is_known_unit("regex")
    assert is_known_unit("currency:INR")
    assert not is_known_unit("currency:inr")
    assert not is_known_unit("widgets")

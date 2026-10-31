from __future__ import annotations

from datetime import date
from pathlib import Path

from almanac import cli
from almanac.checks import Verifier
from almanac.fetch import FetchError, Fetcher
from almanac.store import discover, read_entry_file
from tests.conftest import evidence, write_entry

URL = "https://stats.example.test/release.csv"
TODAY = date(2026, 10, 31)


def _marginal_entry(sha: str, **overrides):
    entry = {
        "id": "xx-sex-shares",
        "title": "Population share by sex",
        "kind": "marginal",
        "domain": "demographics",
        "region": "XX",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": "2025-01-01", "end": "2025-12-31"},
        "spec": {
            "variable": "sex",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": {"female": 0.51, "male": 0.49}}},
        },
        "evidence": [evidence(URL, sha, 0.51, "female,0.51", unit="ratio")],
        "assumed": [],
        "tests": [
            {"statistic": "share[female]", "expected": 0.51, "tolerance": 0.01},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-9},
        ],
        "notes": "",
    }
    entry.update(overrides)
    return entry


def _rule_entry(sha: str, **overrides):
    entry = {
        "id": "xx-vrn",
        "title": "VRN check",
        "kind": "rule",
        "domain": "identifiers",
        "region": "XX",
        "status": "verified",
        "tier": "A",
        "valid_from": "2025-01-01",
        "valid_to": None,
        "spec": {
            "implementation": "almanac.rules.gb_vrn",
            "parameters": {"length": 9, "weights": [8, 7, 6, 5, 4, 3, 2], "modulus": 97, "variant_offset": 55},
            "vectors": [{"input": "101747696", "expected": True, "origin": "source"}, {"input": "123456789", "expected": False, "origin": "source"}],
        },
        "evidence": [evidence(URL, sha, "101747696", "valid: 101747696", source_license="Apache-2.0")],
        "assumed": [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}],
        "notes": "",
    }
    entry.update(overrides)
    return entry


def _verify(schema, web, tmp_path: Path, entry: dict, **kwargs):
    path = write_entry(tmp_path, entry)
    with web.fetcher() as fetcher:
        return Verifier(schema, fetcher, today=TODAY, sample_size=20_000, **kwargs).verify(read_entry_file(path))


def _failed(report):
    return {r.name: r.detail for r in report.results if r.failed}


def test_marginal_entry_passes_end_to_end(schema, web, tmp_path):
    sha = web.add(URL, "sex,share\nfemale,0.51\nmale,0.49\n", "text/csv")
    report = _verify(schema, web, tmp_path, _marginal_entry(sha))
    assert report.passed, _failed(report)


def test_changed_resource_fails_hash_check(schema, web, tmp_path):
    sha = web.add(URL, "sex,share\nfemale,0.51\nmale,0.49\n", "text/csv")
    web.add(URL, "sex,share\nfemale,0.52\nmale,0.48\n", "text/csv")
    report = _verify(schema, web, tmp_path, _marginal_entry(sha))
    assert "content_sha256 changed" in _failed(report)["evidence[0]"]


def test_missing_snippet_and_value_are_reported(schema, web, tmp_path):
    sha = web.add(URL, "unrelated content\n", "text/csv")
    report = _verify(schema, web, tmp_path, _marginal_entry(sha))
    detail = _failed(report)["evidence[0]"]
    assert "snippet not found" in detail and "value not found" in detail


def test_tier_a_requires_machine_readable_resource(schema, web, tmp_path):
    sha = web.add(URL, "<html>female,0.51</html>", "text/html; charset=utf-8")
    report = _verify(schema, web, tmp_path, _marginal_entry(sha))
    assert "machine-readable" in _failed(report)["evidence[0]"]


def test_statistic_outside_tolerance_fails(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    entry = _marginal_entry(sha, tests=[{"statistic": "share[female]", "expected": 0.9, "tolerance": 0.01}])
    report = _verify(schema, web, tmp_path, entry)
    assert "test share[female]" in _failed(report)


def test_verified_status_needs_permissive_license(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    entry = _marginal_entry(sha)
    entry["evidence"][0]["source_license"] = "all rights reserved"
    report = _verify(schema, web, tmp_path, entry)
    assert "license" in _failed(report)
    entry["status"] = "license-review"
    report = _verify(schema, web, tmp_path, entry)
    assert report.passed, _failed(report)


def test_schema_violation_stops_further_checks(schema, web, tmp_path):
    entry = _marginal_entry("0" * 64)
    entry["tier"] = "D"
    report = _verify(schema, web, tmp_path, entry)
    assert [r.name for r in report.results] == ["schema"]
    assert not report.passed


def test_location_mismatch_is_detected(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    path = write_entry(tmp_path, _marginal_entry(sha))
    moved = path.parent.parent / "YY" / path.name
    moved.parent.mkdir()
    path.rename(moved)
    with web.fetcher() as fetcher:
        report = Verifier(schema, fetcher, today=TODAY).verify(read_entry_file(moved))
    assert "region" in _failed(report)["location"]


def test_future_dates_fail(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    entry = _marginal_entry(sha)
    entry["evidence"][0]["accessed_at"] = "2027-01-01"
    report = _verify(schema, web, tmp_path, entry)
    assert "future" in _failed(report)["dates"]


def test_snippet_word_limit(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    entry = _marginal_entry(sha)
    entry["evidence"][0]["snippet"] = " ".join(["word"] * 25)
    report = _verify(schema, web, tmp_path, entry)
    assert "25 words" in _failed(report)["evidence[0]"]


def test_tier_c_requires_assumptions(schema, web, tmp_path):
    sha = web.add(URL, "female,0.51", "text/csv")
    report = _verify(schema, web, tmp_path, _marginal_entry(sha, tier="C"))
    assert "assumptions" in _failed(report)


def test_rule_entry_runs_vectors_and_reports_mismatches(schema, web, tmp_path):
    sha = web.add(URL, "valid: 101747696", "text/plain")
    report = _verify(schema, web, tmp_path, _rule_entry(sha))
    assert report.passed, _failed(report)
    broken = _rule_entry(sha)
    broken["spec"]["vectors"][1]["expected"] = True
    report = _verify(schema, web, tmp_path, broken)
    assert "1/2 passed" in _failed(report)["vectors"]
    assert "test vector_pass_fraction" in _failed(report)


def test_rule_statistics_without_resolver_are_rejected(schema, web, tmp_path):
    sha = web.add(URL, "valid: 101747696", "text/plain")
    entry = _rule_entry(sha, tests=[{"statistic": "count[x]", "expected": 1, "tolerance": 0}])
    report = _verify(schema, web, tmp_path, entry)
    assert "answers only" in _failed(report)["test count[x]"]


def test_temporal_and_conditional_entries(schema, web, tmp_path):
    sha = web.add(URL, "2025-01,100\n2025-02,150\n", "text/csv")
    temporal = _marginal_entry(
        sha,
        id="xx-monthly-volume",
        kind="temporal",
        spec={"variable": "volume", "unit": "count", "frequency": "monthly", "series": [{"period": "2025-01", "value": 100}, {"period": "2025-02", "value": 150}]},
        tests=[{"statistic": "ratio[2025-02,2025-01]", "expected": 1.5, "tolerance": 0}, {"statistic": "value[2025-01]", "expected": 100, "tolerance": 0}],
        evidence=[evidence(URL, sha, 150, "2025-02,150", unit="count")],
    )
    assert _verify(schema, web, tmp_path, temporal).passed
    conditional = _marginal_entry(
        sha,
        id="xx-volume-by-channel",
        kind="conditional",
        spec={
            "variable": "amount",
            "unit": "count",
            "given": "channel",
            "distributions": {"web": {"family": "normal", "parameters": {"mean": 100, "std": 1}}, "app": {"family": "categorical", "parameters": {"shares": {"low": 1}}}},
        },
        tests=[{"statistic": "mean[web]", "expected": 100, "tolerance": 0.1}, {"statistic": "share[app,low]", "expected": 1, "tolerance": 0}, {"statistic": "sum_of_shares[app]", "expected": 1, "tolerance": 0}],
        evidence=[evidence(URL, sha, 150, "2025-02,150", unit="count")],
    )
    report = _verify(schema, web, tmp_path, conditional)
    assert report.passed, _failed(report)


def test_no_fetch_skips_evidence(schema, web, tmp_path):
    path = write_entry(tmp_path, _marginal_entry("0" * 64))
    report = Verifier(schema, None, today=TODAY, sample_size=1000).verify(read_entry_file(path))
    assert report.passed
    assert {r.outcome for r in report.results if r.name.startswith("evidence")} == {"skip"}


def test_fetcher_cache_and_offline(web, tmp_path):
    web.add(URL, "payload", "text/plain")
    cache = tmp_path / "cache"
    with web.fetcher(cache_dir=cache) as fetcher:
        first = fetcher.get(URL)
    assert any(cache.iterdir())
    with Fetcher(cache_dir=cache, offline=True, transport=web.transport()) as offline:
        assert offline.get(URL).sha256 == first.sha256
        try:
            offline.get("https://stats.example.test/missing.csv")
        except FetchError as exc:
            assert "offline cache" in str(exc)
        else:
            raise AssertionError("offline fetch of an uncached URL must fail")


def test_fetch_errors_surface_as_failures(schema, web, tmp_path):
    report = _verify(schema, web, tmp_path, _marginal_entry("0" * 64))
    assert "HTTP 404" in _failed(report)["evidence[0]"]


def test_discover_rejects_unknown_targets(tmp_path):
    try:
        discover([tmp_path / "nope"])
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing targets must raise")


def test_cli_exit_codes(schema, web, tmp_path, capsys):
    sha = web.add(URL, "female,0.51", "text/csv")
    path = write_entry(tmp_path, _marginal_entry(sha))
    schema_path = Path(__file__).resolve().parent.parent / "schema" / "entry.schema.json"
    assert cli.main(["verify", str(path), "--no-fetch", "--sample-size", "2000", "--today", "2026-10-31", "--schema", str(schema_path)]) == 0
    assert "1 passed, 0 failed" in capsys.readouterr().out
    broken = _marginal_entry(sha, tests=[{"statistic": "share[female]", "expected": 0.1, "tolerance": 0}])
    path = write_entry(tmp_path, broken)
    assert cli.main(["verify", str(path), "--no-fetch", "--sample-size", "2000", "--json", "--schema", str(schema_path)]) == 1
    assert '"passed": false' in capsys.readouterr().out

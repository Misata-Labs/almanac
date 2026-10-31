"""Verification checks applied to every Almanac entry.

A check never raises for a failing entry; it records a result the report
renders. Only programming errors propagate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import jsonschema
from pydantic import ValidationError

from almanac.distributions import declared_share_total, sample, series_statistic, summarise
from almanac.fetch import FetchError, Fetcher
from almanac.models import ConditionalSpec, Entry, MarginalSpec, RuleSpec, Statistic, TemporalSpec, Test, is_known_unit
from almanac.rules import load_rule, statistic_resolver
from almanac.store import EntryFile

MAX_SNIPPET_WORDS = 24

PERMISSIVE_LICENSES: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "ODbL-1.0",
        "ODC-By-1.0",
        "PDDL-1.0",
        "OGL-UK-3.0",
        "public-domain",
    }
)

PERMISSIVE_TERMS: frozenset[str] = frozenset(
    {
        # Publisher terms that are not SPDX licences but explicitly permit free reuse with attribution.
        # Each identifier is documented in CONTRIBUTING.md with the clause it stands for.
        "ECB-free-use-with-attribution",
    }
)

RULE_STATISTICS = ("vector_count", "vectors_passed", "vector_pass_fraction")


@dataclass(frozen=True)
class CheckResult:
    name: str
    outcome: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome == "fail"


@dataclass
class EntryReport:
    path: Path
    entry_id: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(result.failed for result in self.results)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name, "pass" if passed else "fail", detail))

    def skip(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult(name, "skip", detail))


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _collapse(text: str) -> str:
    """Normalise whitespace so a snippet matches regardless of line wrapping in the resource."""
    return " ".join(text.split())


def _within(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= tolerance
    return actual == expected


class Verifier:
    """Run every check against entry files and collect per-entry reports."""

    def __init__(
        self,
        schema: dict[str, Any],
        fetcher: Fetcher | None,
        *,
        today: date | None = None,
        sample_size: int = 200_000,
        seed: int = 0,
    ) -> None:
        self._validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        self._fetcher = fetcher
        self._today = today or date.today()
        self._sample_size = sample_size
        self._seed = seed

    def verify(self, entry_file: EntryFile) -> EntryReport:
        report = EntryReport(path=entry_file.path, entry_id=str(entry_file.raw.get("id", entry_file.expected_id)))
        if not self._check_schema(entry_file, report):
            return report
        entry = self._check_model(entry_file, report)
        if entry is None:
            return report
        self._check_location(entry, entry_file, report)
        self._check_dates(entry, report)
        self._check_units(entry, report)
        self._check_license(entry, report)
        self._check_assumptions(entry, report)
        self._check_evidence(entry, report)
        self._check_spec(entry, report)
        return report

    def verify_all(self, entry_files: Iterable[EntryFile]) -> list[EntryReport]:
        return [self.verify(entry_file) for entry_file in entry_files]

    def _check_schema(self, entry_file: EntryFile, report: EntryReport) -> bool:
        errors = sorted(self._validator.iter_errors(entry_file.raw), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            location = "/".join(str(p) for p in first.path) or "<root>"
            report.add("schema", False, f"{len(errors)} violation(s); first at {location}: {first.message}")
            return False
        report.add("schema", True)
        return True

    def _check_model(self, entry_file: EntryFile, report: EntryReport) -> Entry | None:
        try:
            entry = Entry.model_validate(entry_file.raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            report.add("model", False, f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}")
            return None
        report.add("model", True)
        return entry

    def _check_location(self, entry: Entry, entry_file: EntryFile, report: EntryReport) -> None:
        problems = []
        if entry.id != entry_file.expected_id:
            problems.append(f"id {entry.id!r} differs from file name {entry_file.expected_id!r}")
        if entry.domain != entry_file.expected_domain:
            problems.append(f"domain {entry.domain!r} differs from directory {entry_file.expected_domain!r}")
        if entry.region != entry_file.expected_region:
            problems.append(f"region {entry.region!r} differs from directory {entry_file.expected_region!r}")
        report.add("location", not problems, "; ".join(problems))

    def _check_dates(self, entry: Entry, report: EntryReport) -> None:
        problems = []
        for index, item in enumerate(entry.evidence):
            if item.accessed_at > self._today:
                problems.append(f"evidence[{index}] accessed_at {item.accessed_at} is in the future")
        if entry.kind == "rule" and entry.valid_from is not None and entry.valid_from > self._today:
            problems.append(f"valid_from {entry.valid_from} is in the future")
        if entry.observed_period is not None and entry.observed_period.end > self._today:
            problems.append(f"observed_period ends in the future ({entry.observed_period.end})")
        report.add("dates", not problems, "; ".join(problems))

    def _check_units(self, entry: Entry, report: EntryReport) -> None:
        problems = [f"evidence[{i}] unit {item.unit!r}" for i, item in enumerate(entry.evidence) if not is_known_unit(item.unit)]
        spec_unit = getattr(entry.spec, "unit", None)
        if spec_unit is not None and not is_known_unit(spec_unit):
            problems.append(f"spec unit {spec_unit!r}")
        report.add("units", not problems, "unknown: " + ", ".join(problems) if problems else "")

    def _check_license(self, entry: Entry, report: EntryReport) -> None:
        if entry.status != "verified":
            report.add("license", True, f"status {entry.status}: no permissive-license requirement")
            return
        unclear = sorted({item.source_license for item in entry.evidence} - PERMISSIVE_LICENSES - PERMISSIVE_TERMS)
        report.add("license", not unclear, f"verified entry cites non-permissive license(s): {', '.join(unclear)}" if unclear else "")

    def _check_assumptions(self, entry: Entry, report: EntryReport) -> None:
        if entry.tier == "C" and not entry.assumed:
            report.add("assumptions", False, "tier C entries must declare what was assumed or derived")
            return
        report.add("assumptions", True)

    def _check_evidence(self, entry: Entry, report: EntryReport) -> None:
        for index, item in enumerate(entry.evidence):
            name = f"evidence[{index}]"
            if item.snippet_word_count > MAX_SNIPPET_WORDS:
                report.add(name, False, f"snippet has {item.snippet_word_count} words; limit is {MAX_SNIPPET_WORDS}")
                continue
            if self._fetcher is None:
                report.skip(name, "fetch disabled")
                continue
            try:
                resource = self._fetcher.get(item.url)
            except FetchError as exc:
                report.add(name, False, str(exc))
                continue
            problems = []
            if resource.sha256 != item.content_sha256:
                problems.append(f"content_sha256 changed to {resource.sha256[:12]}…")
            if entry.tier == "A" and item.role == "primary" and not resource.is_machine_readable:
                problems.append(f"tier A primary evidence must be machine-readable, got {resource.content_type or 'unknown type'}")
            text = _collapse(resource.text)
            if _collapse(item.snippet) not in text:
                problems.append("snippet not found in resource")
            if _collapse(_scalar_text(item.value)) not in text:
                problems.append("value not found in resource")
            report.add(name, not problems, "; ".join(problems))

    def _check_spec(self, entry: Entry, report: EntryReport) -> None:
        spec = entry.spec
        if isinstance(spec, RuleSpec):
            self._check_rule(spec, entry.tests, report)
        elif isinstance(spec, MarginalSpec):
            self._check_tests(entry.tests, self._marginal_resolver(spec), report)
        elif isinstance(spec, TemporalSpec):
            series = {point.period: point.value for point in spec.series}
            columns = {name: {point.period: point.column(name) for point in spec.series} for name in spec.columns}
            self._check_tests(entry.tests, lambda stat: series_statistic(series, stat, columns), report)
        elif isinstance(spec, ConditionalSpec):
            self._check_tests(entry.tests, self._conditional_resolver(spec), report)

    def _check_rule(self, spec: RuleSpec, tests: list[Test], report: EntryReport) -> None:
        try:
            module = load_rule(spec.implementation)
        except (ImportError, ValueError) as exc:
            report.add("rule", False, str(exc))
            return
        failures = []
        for index, vector in enumerate(spec.vectors):
            try:
                actual = module.evaluate(spec.parameters, vector.input)
            except Exception as exc:  # a vector that crashes the rule is a verification failure, not a tool error
                failures.append(f"#{index} raised {type(exc).__name__}: {exc}")
                continue
            if actual != vector.expected:
                failures.append(f"#{index} {vector.input!r} -> {actual!r}, expected {vector.expected!r}")
        passed = len(spec.vectors) - len(failures)
        report.add("vectors", not failures, f"{passed}/{len(spec.vectors)} passed" + ("; " + "; ".join(failures[:3]) if failures else ""))

        built_in = {
            "vector_count": len(spec.vectors),
            "vectors_passed": passed,
            "vector_pass_fraction": passed / len(spec.vectors),
        }
        custom = statistic_resolver(module)

        def resolve(stat: Statistic) -> Any:
            if stat.name in built_in and not stat.args:
                return built_in[stat.name]
            if custom is None:
                raise ValueError(f"{spec.implementation} answers only {', '.join(RULE_STATISTICS)}")
            return custom(spec.parameters, stat)

        self._check_tests(tests, resolve, report)

    def _marginal_resolver(self, spec: MarginalSpec) -> Callable[[Statistic], Any]:
        samples: list[Any] | None = None

        def resolve(stat: Statistic) -> Any:
            nonlocal samples
            if stat.name == "sum_of_shares":
                return declared_share_total(spec.distribution)
            if samples is None:
                samples = sample(spec.distribution, self._sample_size, self._seed)
            return summarise(samples, stat)

        return resolve

    def _conditional_resolver(self, spec: ConditionalSpec) -> Callable[[Statistic], Any]:
        cache: dict[str, list[Any]] = {}

        def resolve(stat: Statistic) -> Any:
            if not stat.args:
                raise ValueError("conditional statistics take the conditioning value as their first argument")
            given, rest = stat.args[0], stat.args[1:]
            distribution = spec.distributions[given]
            inner = Statistic(name=stat.name, args=rest)
            if stat.name == "sum_of_shares":
                return declared_share_total(distribution)
            if given not in cache:
                cache[given] = sample(distribution, self._sample_size, self._seed)
            return summarise(cache[given], inner)

        return resolve

    def _check_tests(self, tests: list[Test], resolve: Callable[[Statistic], Any], report: EntryReport) -> None:
        for test in tests:
            name = f"test {test.statistic}"
            try:
                actual = resolve(test.parsed)
            except (KeyError, ValueError, ZeroDivisionError) as exc:
                report.add(name, False, f"cannot evaluate: {exc}")
                continue
            ok = _within(actual, test.expected, test.tolerance)
            shown = f"{actual:.6g}" if isinstance(actual, float) else repr(actual)
            report.add(name, ok, f"observed {shown}, expected {test.expected!r} ± {test.tolerance:g}")

"""Typed models for Almanac entries.

The models mirror ``schema/entry.schema.json``. The JSON Schema is the
contract contributors validate against; these classes give the verifier and
the rule runtime a typed view of the same data.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["rule", "marginal", "temporal", "conditional"]
Status = Literal["draft", "verified", "license-review"]
Tier = Literal["A", "B", "C"]
Scalar = str | int | float | bool

UNIT_VOCABULARY: frozenset[str] = frozenset(
    {
        "text",
        "regex",
        "integer",
        "decimal",
        "ratio",
        "percent",
        "count",
        "date",
        "datetime",
        "version",
        "boolean",
        "list",
    }
)
_CURRENCY_UNIT = re.compile(r"^currency:[A-Z]{3}$")
_STATISTIC = re.compile(r"^(?P<name>[a-z_]+)(?:\[(?P<args>.*)\])?$")
_ARGUMENT = re.compile(r'\s*(?:"(?P<quoted>[^"]*)"|(?P<bare>[^,]*))\s*(?:,|$)')


def split_arguments(text: str) -> tuple[str, ...]:
    """Split bracketed statistic arguments on commas, honouring double-quoted arguments that contain commas."""
    args: list[str] = []
    position = 0
    while position < len(text):
        match = _ARGUMENT.match(text, position)
        if match is None or match.end() == position:
            raise ValueError(f"malformed statistic arguments {text!r}")
        args.append(match.group("quoted") if match.group("quoted") is not None else match.group("bare").strip())
        position = match.end()
    return tuple(args)


def is_known_unit(unit: str) -> bool:
    """Return whether ``unit`` belongs to the controlled unit vocabulary."""
    return unit in UNIT_VOCABULARY or bool(_CURRENCY_UNIT.match(unit))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(StrictModel):
    start: date
    end: date


class Evidence(StrictModel):
    publisher: str
    title: str
    url: str
    accessed_at: date
    locator: str
    value: Scalar
    unit: str
    snippet: str
    source_license: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["primary", "supporting"] = "primary"

    @property
    def snippet_word_count(self) -> int:
        return len(self.snippet.split())


class Assumption(StrictModel):
    parameter: str
    value: Any
    method: Literal["fitted", "derived", "assumed"]
    rationale: str


class Statistic(StrictModel):
    """A parsed test statistic such as ``share[female]`` or ``count[scotland,2026]``."""

    name: str
    args: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> Statistic:
        match = _STATISTIC.match(text)
        if match is None:
            raise ValueError(f"malformed statistic {text!r}")
        raw_args = match.group("args")
        return cls(name=match.group("name"), args=split_arguments(raw_args) if raw_args is not None else ())


class Test(StrictModel):
    statistic: str
    expected: Scalar
    tolerance: float = Field(ge=0)

    @property
    def parsed(self) -> Statistic:
        return Statistic.parse(self.statistic)


class Vector(StrictModel):
    input: Any
    expected: Any
    origin: Literal["source", "derived"]
    note: str | None = None


class RuleSpec(StrictModel):
    kind: Literal["rule"]
    implementation: str = Field(pattern=r"^almanac\.rules\.[a-z0-9_]+$")
    parameters: dict[str, Any]
    vectors: list[Vector] = Field(min_length=1)


class Distribution(StrictModel):
    family: Literal["categorical", "uniform", "normal", "lognormal", "empirical"]
    parameters: dict[str, Any]


class MarginalSpec(StrictModel):
    kind: Literal["marginal"]
    variable: str
    unit: str
    distribution: Distribution


class SeriesPoint(BaseModel):
    """One observation of a temporal series; extra numeric columns ride alongside ``value``."""

    model_config = ConfigDict(extra="allow", frozen=True)

    period: str
    value: float

    def column(self, name: str) -> float:
        extra = self.model_extra or {}
        if name not in extra:
            raise KeyError(f"series point {self.period} has no column {name!r}")
        return float(extra[name])


class TemporalSpec(StrictModel):
    kind: Literal["temporal"]
    variable: str
    unit: str
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "annual"]
    columns: list[str] = []
    series: list[SeriesPoint] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_columns_present(self) -> TemporalSpec:
        for point in self.series:
            extra = set(point.model_extra or {})
            missing = set(self.columns) - extra
            unexpected = extra - set(self.columns)
            if missing or unexpected:
                raise ValueError(f"series point {point.period}: missing {sorted(missing)}, unexpected {sorted(unexpected)}")
        return self


class ConditionalSpec(StrictModel):
    kind: Literal["conditional"]
    variable: str
    unit: str
    given: str
    distributions: dict[str, Distribution] = Field(min_length=1)


Spec = Annotated[
    Union[RuleSpec, MarginalSpec, TemporalSpec, ConditionalSpec],
    Field(discriminator="kind"),
]


class Entry(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str
    kind: Kind
    domain: str = Field(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
    region: str = Field(pattern=r"^([A-Z]{2}|global)$")
    status: Status
    tier: Tier
    valid_from: date | None = None
    valid_to: date | None = None
    observed_period: Period | None = None
    spec: Spec
    evidence: list[Evidence] = Field(min_length=1)
    assumed: list[Assumption]
    tests: list[Test] = Field(min_length=1)
    notes: str
    tags: list[str] = []
    use_cases: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _tag_spec_with_kind(cls, data: Any) -> Any:
        """Copy the entry's kind into the spec so the discriminated union can select a spec model."""
        if isinstance(data, dict) and isinstance(data.get("spec"), dict) and "kind" in data:
            spec = dict(data["spec"])
            spec.setdefault("kind", data["kind"])
            return {**data, "spec": spec}
        return data

    @model_validator(mode="after")
    def _check_temporal_validity(self) -> Entry:
        if self.kind == "rule":
            if self.valid_from is None:
                raise ValueError("rule entries require valid_from")
            if self.valid_to is not None and self.valid_to < self.valid_from:
                raise ValueError("valid_to precedes valid_from")
        elif self.observed_period is None:
            raise ValueError(f"{self.kind} entries require observed_period")
        elif self.observed_period.end < self.observed_period.start:
            raise ValueError("observed_period end precedes start")
        return self

    def applies_on(self, day: date) -> bool:
        """Return whether the entry's temporal validity covers ``day``."""
        if self.kind == "rule":
            assert self.valid_from is not None
            return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)
        assert self.observed_period is not None
        return self.observed_period.start <= day <= self.observed_period.end

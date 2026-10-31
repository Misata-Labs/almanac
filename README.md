# Misata Almanac

An open, proof-backed knowledge base of real-world data rules and patterns.
The [Misata](https://pypi.org/project/misata/) synthetic data engine reads it
to generate data that behaves like the real thing: identifiers that pass the
official check-digit tests, calendars that match the published holidays,
distributions that reproduce the statistics a national office publishes.

Every entry is a small YAML document that states a rule or a distribution,
cites the official source it came from, records a content hash of that source,
and carries the tests that prove the stated value is still what the source
says. Nothing in an entry is written from memory. If a value cannot be fetched
and confirmed from a primary source, it is not in the Almanac.

Created and edited by Muhammed Rasin.

## Integrity rules

1. **No value from memory.** Every number, rate, rule, or date comes from a
   source fetched at authoring time and recorded in `evidence[]`.
2. **Primary sources only**, in priority order: national statistical offices;
   central banks; government ministries, regulators and official gazettes;
   intergovernmental bodies (World Bank, IMF, OECD, UN, BIS, ILO, WHO);
   official operators of payment or numbering systems; peer-reviewed
   open-access papers. Blogs, vendor material, news, encyclopaedias, forums,
   paywalled documents and model output are never primary sources.
3. **Licence recorded.** Each evidence item names the source licence. An entry
   whose sources do not clearly permit reuse is kept at status
   `license-review` and is never marked `verified`.
4. **Minimal quotation.** At most one verbatim snippet under 25 words per
   evidence item, used only to locate the value. Tables and passages are never
   copied.
5. **Observation apart from assumption.** Anything fitted, derived, or assumed
   rather than published goes in `assumed[]` with the method stated.

## Evidence tiers

| Tier | Meaning |
| --- | --- |
| A | Reproducible from an official machine-readable artefact (API response, CSV, XLSX, SDMX, JSON, YAML, or source code published by the body) at an exact URL, with the content hash recorded. |
| B | A value located in an official document (PDF or HTML) with publisher, title, page, table or cell locator, and a short snippet. |
| C | An estimate or derived value without direct official publication. Allowed only when clearly labelled and accompanied by `assumed[]`; omission is preferred. |

## Entry kinds

- **rule**: deterministic and executable (check digits, numbering formats,
  calendars, rate schedules). Each rule has a Python implementation under
  `almanac/rules/` and test vectors taken from the source's own worked
  examples.
- **marginal**: a distribution or category shares for one variable.
- **temporal**: seasonality, calendar effects or trends from an official
  time series.
- **conditional**: a distribution conditioned on another variable, only when
  the source publishes it directly.

Every entry carries temporal validity: `valid_from` and `valid_to` for rules,
`observed_period` for statistics, so a consumer can ask what applied on a given
date. For a rule, `valid_from` is the earliest date the cited evidence attests
the rule, unless the source states an effective date.

## Layout

```
schema/entry.schema.json      JSON Schema every entry must satisfy
entries/<domain>/<region>/    one YAML file per entry; region is ISO 3166-1 alpha-2 or "global"
almanac/                      Python package: models, rules, fetcher, verifier CLI
almanac/rules/                executable rule implementations
tools/                        reproducible builders for generated entries
tests/                        pytest suites for the verifier and the rules
```

## Verify locally

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13. There is no CI;
everything runs on your machine.

```
uv sync
uv run almanac verify            # all entries, live re-fetch of every evidence URL
uv run almanac verify entries/identifiers/GB
uv run almanac verify --cache-dir .cache/evidence         # keep fetched copies
uv run almanac verify --cache-dir .cache/evidence --offline
uv run almanac verify --no-fetch                          # structure, vectors and statistics only
uv run almanac verify -v --json                           # machine-readable report
uv run pytest
```

For each entry the verifier validates the schema and typed models, checks that
the file sits in the directory its `domain` and `region` declare, confirms
dates and units, re-fetches every evidence URL and confirms the recorded
SHA-256, snippet and value still appear, requires machine-readable resources
for tier A, requires permissive licences for `verified` entries, runs every
rule test vector, and samples each declared distribution to reproduce the
published statistics within tolerance. It prints a pass/fail report per entry
and exits non-zero on any failure.

## Using an entry

```python
from datetime import date
from almanac.rules import gb_utr
from almanac.store import read_entry_file

entry = read_entry_file("entries/identifiers/GB/gb-utr-check-digit.yaml").raw
params = entry["spec"]["parameters"]
gb_utr.check_digit("234567890", params)       # '2'
gb_utr.is_valid("2234567890K", params, "sa")  # True
```

## Licences

Two licences apply, and the split matters:

- **Entries** (everything under `entries/` and `schema/`) are data and are
  released under the Open Database License 1.0, in `LICENSE-DATA`. You may
  share, create and adapt the database, provided you attribute it and keep
  derived databases open.
- **Code** (everything under `almanac/`, `tools/` and `tests/`) is released
  under the Apache License 2.0, in `LICENSE`.

Each evidence item also records the licence of its own source; those licences
govern the source material, not this repository's restatement of it.

## Citing

See `CITATION.cff`. In prose: Muhammed Rasin, *Misata Almanac*, Misata Labs,
https://github.com/Misata-labs/almanac.

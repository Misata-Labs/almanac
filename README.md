# Misata Almanac

**Real-world data has rules. Synthetic data usually breaks them.**

A VAT number whose check digits fail. An invoice dated on a bank holiday. A
tax code with a leading zero. A Pix transaction id with a hyphen. These are
the details that make generated data useless the moment it meets a real
validator, a real reconciliation job, or a real analyst.

The Almanac is an open knowledge base of those rules and patterns, written
so that every value can be traced to the official body that published it,
re-fetched, and re-checked. The [Misata](https://pypi.org/project/misata/)
synthetic data engine reads it to generate data that passes the same checks
the real thing passes.

Created and edited by Muhammed Rasin.

## The promise

Every entry carries its own proof.

- **No value from memory.** Every number, pattern, date, and code list was
  fetched from a primary source while the entry was written, and the entry
  records the exact URL, the SHA-256 of what was fetched, where in the
  resource the value sits, and a snippet that locates it.
- **Primary sources only.** Statistical offices, central banks, ministries
  and regulators, intergovernmental bodies, official operators of payment
  and numbering systems, peer-reviewed open-access papers. Nothing else.
- **Executable.** Rules ship with a typed Python implementation and test
  vectors taken from the source's own worked examples. Distributions ship
  with the statistics the source publishes, and the verifier reproduces them
  by sampling.
- **Dated.** Every entry says when it applied, so you can ask what the world
  looked like on a given day.
- **Re-verifiable by anyone.** `uv run almanac verify` re-fetches every
  source and fails loudly if anything drifted.

## Try it

```
uv sync
uv run almanac verify                      # re-fetch and re-check every entry
uv run almanac applies --on 2026-06-15     # which entries applied on that date
uv run almanac show gb-utr-check-digit     # the provenance card for one entry
uv run almanac catalogue                   # the table in CATALOGUE.md
```

A verifier run looks like this:

```
[PASS] gb-utr-check-digit  (entries/identifiers/GB/gb-utr-check-digit.yaml)
    PASS evidence[0]
    PASS vectors  23/23 passed
    PASS test vector_pass_fraction  observed 1, expected 1 ± 0
...
10 passed, 0 failed, 10 entries
```

And from Python:

```python
from datetime import date
from almanac.api import Almanac

almanac = Almanac.load()

utr = almanac.rule("gb-utr-check-digit")
utr.call("check_digit", "234567890")            # '2'
utr.evaluate({"reference": "2234567890K", "scheme": "sa"})  # True

holidays = almanac.rule("gb-bank-holidays")
holidays.call("is_bank_holiday", date(2026, 12, 28), division="england-and-wales")  # True

for entry in almanac.select(on=date(2026, 6, 15), region="GB"):
    print(entry.id, entry.tier, entry.status)
```

## What is in it

See [CATALOGUE.md](CATALOGUE.md) for the generated table. Highlights:

- **UK identifiers from HM Revenue & Customs' own validation library**:
  National Insurance numbers, Unique Taxpayer References (modulus 11),
  VAT registration numbers (MOD 97 and MOD 9755), PAYE tax codes, and the
  modulus-23 check characters on PAYE, SDLT and other-tax payment references.
  Every vector is one HMRC uses in its own test suite.
- **UK calendars from GOV.UK**: bank holidays for England and Wales,
  Scotland and Northern Ireland for 2019 to 2028, and the clock-change
  rule with its published dates.
- **Brazil Pix identifier formats from Banco Central do Brasil**: txid,
  EndToEndId, CPF, CNPJ (alphanumeric since 2024), ISPB and monetary amounts.
- **Companies House code lists**: company type and company status codes,
  held at `license-review` until the publisher's terms for the file are
  confirmed.

[WANTED.md](WANTED.md) lists the entries we most want next, each with the
official body to source it from. If you know a national numbering scheme or
a statistical release well, that is the place to start.

## Anatomy of an entry

```yaml
id: gb-vrn-check-digits
kind: rule
region: GB
status: verified
tier: A
valid_from: 2025-08-11
valid_to: null
spec:
  implementation: almanac.rules.gb_vrn
  parameters: {length: 9, weights: [8, 7, 6, 5, 4, 3, 2], modulus: 97, variant_offset: 55}
  vectors:
    - {input: "101747696", expected: true, origin: source}
evidence:
  - publisher: HM Revenue & Customs
    url: https://raw.githubusercontent.com/hmrc/domain/bc4a37fe.../ReferenceChecker.scala
    locator: "lines 123-127, VatReferenceChecker"
    value: "List(8, 7, 6, 5, 4, 3, 2)"
    snippet: "object VatReferenceChecker extends DifferenceReferenceChecker"
    source_license: Apache-2.0
    content_sha256: 28370b88…
assumed: []
tests:
  - {statistic: vector_pass_fraction, expected: 1, tolerance: 0}
```

`spec` is what a data engine executes. `evidence` is why you should believe
it. `assumed` is where anything restated, converted, fitted or guessed is
confessed, with the method. `tests` is what the verifier reproduces.

## Evidence tiers

| Tier | Meaning |
| --- | --- |
| A | Reproducible from an official machine-readable artefact (API response, CSV, XLSX, SDMX, JSON, YAML, or source code published by the body) at an exact URL, with the content hash recorded. |
| B | A value located in an official document (PDF or HTML) with publisher, title, page, table or cell locator, and a short snippet. |
| C | An estimate or derived value without direct official publication. Allowed only when clearly labelled and accompanied by `assumed[]`; omission is preferred. |

## Entry kinds and temporal validity

- **rule**: deterministic and executable: check digits, numbering formats,
  code lists, calendars, rate schedules. Carries `valid_from` and `valid_to`.
- **marginal**: a distribution or category shares for one variable. Carries
  `observed_period`.
- **temporal**: seasonality, calendar effects or trends from an official
  time series. Carries `observed_period`.
- **conditional**: a distribution conditioned on another variable, only when
  the source publishes it directly. Carries `observed_period`.

For a rule, `valid_from` is the earliest date the cited evidence attests the
rule, unless the source states an effective date. It is a statement about the
proof, not a claim about legislative history.

## Integrity rules

1. Never write a number, rate, rule or date from memory.
2. Primary sources only, in the priority order above.
3. Record each source's licence; unclear terms keep an entry at
   `license-review`, never `verified`.
4. At most one verbatim snippet under 25 words per evidence item, used only
   to locate the value. Never copy tables or passages.
5. Keep observation apart from assumption: anything fitted, derived or
   assumed goes in `assumed[]` with the method stated.

The verifier enforces what it can: schema and typed models, directory
placement, dates, units, snippet length, hash and content checks against the
live source, machine-readable resources for tier A, permissive licences for
`verified` entries, every rule vector, and every published statistic.

## Layout

```
schema/entry.schema.json      JSON Schema every entry must satisfy
entries/<domain>/<region>/    one YAML file per entry; region is ISO 3166-1 alpha-2 or "global"
almanac/                      Python package: models, api, rules, fetcher, verifier, CLI
almanac/rules/                executable rule implementations
tools/                        reproducible builders for generated entries
tests/                        pytest suites for the verifier, the API and the rules
CATALOGUE.md                  generated table of entries
WANTED.md                     entries we want next, with their official sources
```

## Verify locally

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13. There is no CI;
everything runs on your machine, which is the point.

```
uv sync
uv run almanac verify                                     # all entries, live re-fetch
uv run almanac verify entries/identifiers/GB              # one directory or file
uv run almanac verify --cache-dir .cache/evidence         # keep fetched copies
uv run almanac verify --cache-dir .cache/evidence --offline
uv run almanac verify --no-fetch                          # structure, vectors and statistics only
uv run almanac verify -v --json                           # machine-readable report
uv run almanac catalogue --write CATALOGUE.md             # refresh the catalogue
uv run pytest
```

## Licences

- **Entries** (`entries/`, `schema/`, `CATALOGUE.md`) are data, released
  under the Open Database License 1.0 in `LICENSE-DATA`. Share, create and
  adapt the database; attribute it; keep derived databases open.
- **Code** (`almanac/`, `tools/`, `tests/`) is released under the Apache
  License 2.0 in `LICENSE`.

Each evidence item also records the licence of its own source; that licence
governs the source material, not this repository's restatement of it.

## Citing

See `CITATION.cff`. In prose: Muhammed Rasin, *Misata Almanac*, Misata Labs,
https://github.com/Misata-labs/almanac.

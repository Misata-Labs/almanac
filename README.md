<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
    <img src="docs/assets/hero-light.svg" alt="Misata Almanac: the rules real-world data obeys, with receipts" width="100%">
  </picture>
</p>

# Misata Almanac

**Real data obeys rules. Fake data usually breaks them. This is the rulebook, with receipts.**

A VAT number whose check digits do not add up. A payment dated on a bank
holiday. A yen amount with two decimal places. A tax code with a leading zero.
A Pix transaction id with hyphens in it. Each slip is small. Together they are
why synthetic data gets thrown out the moment it meets a real validator, a real
reconciliation job, or a real auditor.

The Almanac is an open archive of those rules and the distributions behind
them: check-digit algorithms, identifier formats, tax bands, holiday calendars,
currency conventions, code lists, and the statistics official bodies publish.
Every value is traced to the statistical office, central bank, regulator or
standards body that published it, with the exact URL, the SHA-256 of what was
fetched, and the tests that prove it still holds. The
[Misata](https://pypi.org/project/misata/) synthetic data engine reads it so
the data it generates passes the same checks real data passes.

Created and edited by Muhammed Rasin.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/before-after-dark.svg">
    <img src="docs/assets/before-after-light.svg" alt="Three panels of synthetic data failing real-world checks, and one passing with the Almanac" width="100%">
  </picture>
</p>

## The promise

No value in this archive was typed from memory. A number, a pattern, a date
or a code list exists here only because someone fetched it from a primary
source while writing the entry, recorded where it sits in that source, hashed
the bytes, and wrote down the test that reproduces it. Anyone can run the
verifier and watch every entry re-fetch and re-check itself.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/proof-chain-dark.svg">
    <img src="docs/assets/proof-chain-light.svg" alt="How a value earns its place: primary source, exact URL, sha256, locator and snippet, test vectors, verifier" width="100%">
  </picture>
</p>

## Start from the business problem

Every entry carries `use_cases`, so a demo team pulls exactly what it needs.

```
uv run almanac list --use-case payroll-demo
uv run almanac list --use-case kyb-onboarding
uv run almanac applies --on 2026-06-15 --use-case banking-demo
```

| If you are building… | Start with |
| --- | --- |
| **Payroll and HR** | UK Income Tax bands with the tapered allowance, minimum wage by age band and date, NINO and tax code formats, Census economic activity and qualifications |
| **Banking, lending, treasury** | Selic and ECB deposit-rate step schedules, policy rates for nine economies, euro area mortgage cost of borrowing, Brazil household credit default rate, account ownership by economy |
| **Payments and fintech** | Pix identifier formats, monthly Pix volume and average ticket, Pix key-type mix, HMRC payment reference check characters, bank holidays for settlement calendars |
| **KYC, KYB, onboarding** | CNPJ and UTR check digits, VAT registration numbers, Companies House types and statuses, SIC 2007 codes, the email pattern HMRC accepts, World Bank economy classification |
| **Invoicing, tax, audit** | UK VAT rates, India GST slab structure, ISO 4217 minor units, ECB and US Treasury exchange-rate tables, CPIH and IPCA price indices |
| **Customers, people, households** | Twelve Census 2021 marginals, single-year age distributions for Germany and France, world population weights, fertility and life expectancy by economy |
| **Healthcare and claims** | ICD-10-CM 2026 diagnosis categories with code counts, the NPI Luhn check digit, Census general health, life expectancy by economy |
| **Insurance, property, fleet** | The VIN check digit from the federal regulation, UK house prices by month, euro area mortgage rates, Census tenure and car availability |
| **Retail and demand** | Retail sales index with its December peak, inflation by month and by country, GDP and GDP per capita by economy |
| **Telecom, energy, utilities** | ITU country calling codes, internet and mobile penetration by economy, household electricity prices for ten EU states, clock-change dates |

The full matrix of use cases to entries opens [CATALOGUE.md](CATALOGUE.md).

## Thirty seconds

```
uv sync
uv run almanac verify                      # re-fetch and re-check every entry
uv run almanac applies --on 2026-06-15     # which entries applied on that date
uv run almanac show gb-utr-check-digit     # the provenance card for one entry
```

```python
from datetime import date
from almanac.api import Almanac

almanac = Almanac.load()

almanac.rule("gb-utr-check-digit").call("check_digit", "234567890")            # '2'
almanac.rule("br-cnpj-check-digits").call("check_digits", "12.ABC.345/01DE")   # '35'
almanac.rule("us-vin-check-digit").call("check_digit", "1G4AH59H45G118341")    # '4'
almanac.rule("global-iso4217-currency-minor-units").call("minor_units", "JPY") # 0
almanac.rule("gb-income-tax-bands-2026-27").call("tax_due", 35000)             # Decimal('4486.00')
almanac.rule("us-federal-holidays").call("is_holiday", date(2026, 7, 3))       # True, observed day
almanac.rule("br-selic-target-rate-changes-2025").call("value_on", date(2025, 7, 1))  # 15.0

for entry in almanac.select(on=date(2026, 6, 15), region="GB", kind="rule"):
    print(entry.id, entry.tier, entry.status)
```

## Anatomy of an entry

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/anatomy-dark.svg">
    <img src="docs/assets/anatomy-light.svg" alt="Anatomy of an entry: spec runs in the data engine; evidence, assumed and tests are checked by the verifier" width="100%">
  </picture>
</p>

```yaml
id: gb-vrn-check-digits
kind: rule
region: GB
status: verified
tier: A
valid_from: 2025-08-11
valid_to: null
tags: [vat, vrn, check-digit, hmrc]
use_cases: [invoicing, kyb-onboarding, accounts-payable, audit-demo]
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
it; an item marked `role: supporting` documents context such as units or
licence terms. `assumed` is where anything restated, converted, fitted or
guessed is confessed, with the method. `tests` is what the verifier
reproduces.

## What the verifier does

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/pipeline-dark.svg">
    <img src="docs/assets/pipeline-light.svg" alt="What almanac verify checks, in order: schema, models, placement, dates and units, fetch and hash, snippet and value, rule vectors, statistics, report" width="100%">
  </picture>
</p>

```
[PASS] gb-utr-check-digit  (entries/identifiers/GB/gb-utr-check-digit.yaml)
    PASS evidence[0]
    PASS vectors  23/23 passed
    PASS test vector_pass_fraction  observed 1, expected 1 ± 0
[PASS] br-pix-monthly-volume-and-value  (entries/payments/BR/br-pix-monthly-volume-and-value.yaml)
    PASS test column[quantity_thousands,2026-09]  observed 7.89294e+06, expected 7892936.44 ± 0
...
68 passed, 0 failed, 68 entries
```

## What is in the archive

[CATALOGUE.md](CATALOGUE.md) is generated from the entries and lists all of
them by use case and by domain. The short version:

- **Identifiers**: UK National Insurance numbers, Unique Taxpayer References,
  VAT registration numbers, and PAYE, SDLT and other-tax payment references
  from HM Revenue & Customs' own validation library; Brazil CNPJ check digits
  from Receita Federal's worked example; the US VIN check digit from
  49 CFR 565.15; the NPI check digit from the CMS note.
- **Payments and currency**: Pix identifier formats, monthly Pix volume and
  key-type mix from Banco Central do Brasil; ISO 4217 codes and minor units
  from the maintenance agency; ECB euro reference rates; US Treasury
  reporting rates of exchange for 174 currency pairs.
- **Tax and employment**: UK VAT rates, UK Income Tax bands for 2026 to 2027,
  National Minimum Wage rates for April 2026 and April 2027, the PAYE tax
  code format, and the India GST slab structure.
- **Calendars**: UK bank holidays by nation to 2028, the UK clock-change
  rule, and US federal holidays with Saturday and Sunday observance.
- **Economy and rates**: thirteen World Bank reference tables by economy;
  euro area HICP and mortgage rates; ECB deposit facility and Selic step
  schedules; central bank policy rates for nine economies; UK CPIH and retail
  sales indices; Brazil IPCA and household credit default; Eurostat
  unemployment and inflation by member state.
- **Demographics**: twelve Census 2021 marginals for England and Wales,
  single-year age distributions for Germany and France, population by sex
  for ten member states, world population weights.
- **Healthcare, property, energy, telecom**: ICD-10-CM 2026 categories, UK
  house prices by month, household electricity prices across the EU, ITU
  country calling codes.
- **Companies and contact**: Companies House company types and statuses, the
  SIC 2007 condensed list, the email pattern HMRC services accept.

Entries whose source terms are not clearly permissive stay at
`license-review` and say why. [WANTED.md](WANTED.md) lists what comes next,
each with the official body to source it from.

## Findable by people and by agents

- `llms.txt` maps the whole archive for AI agents in a single read.
- `manifest.json` indexes every entry with validity, publishers, licences,
  tags and use cases.
- `dataset.jsonld` describes the archive as a schema.org Dataset for data
  catalogues and search engines.

All three are generated by `uv run almanac index`, and a test fails when
they drift from the entries.

## Evidence tiers

| Tier | Meaning |
| --- | --- |
| A | Reproducible from an official machine-readable artefact (API response, CSV, XLSX, SDMX, JSON, XML, YAML, ZIP, or source code published by the body) at an exact URL, with the content hash recorded. |
| B | A value located in an official document (PDF or HTML) with publisher, title, page, table or cell locator, and a short snippet. |
| C | An estimate or derived value without direct official publication. Allowed only when clearly labelled and accompanied by `assumed[]`; omission is preferred. |

## Entry kinds and time

- **rule**: deterministic and executable: check digits, formats, code lists,
  calendars, rate schedules, reference tables. Carries `valid_from` and
  `valid_to`.
- **marginal**: a distribution or category shares for one variable. Carries
  `observed_period`.
- **temporal**: a time series, seasonality or trend from an official source.
  Carries `observed_period`.
- **conditional**: a distribution conditioned on another variable, only when
  the source publishes it directly. Carries `observed_period`.

For a rule, `valid_from` is the earliest date the cited evidence attests the
rule, unless the source states an effective date. It is a statement about the
proof, not a claim about legislative history.

## Integrity rules

1. Never write a number, rate, rule or date from memory.
2. Primary sources only: national statistical offices; central banks;
   ministries, regulators and gazettes; intergovernmental bodies; official
   operators of payment and numbering systems; peer-reviewed open-access
   papers.
3. Record each source's licence; unclear terms keep an entry at
   `license-review`, never `verified`.
4. At most one verbatim snippet under 25 words per evidence item, used only
   to locate the value. Never copy tables or passages.
5. Keep observation apart from assumption: anything fitted, derived or
   assumed goes in `assumed[]` with the method stated.

## Layout

```
schema/entry.schema.json      JSON Schema every entry must satisfy
entries/<domain>/<region>/    one YAML file per entry; region is ISO 3166-1 alpha-2, EU, or global
almanac/                      Python package: models, api, rules, fetcher, verifier, CLI
almanac/rules/                executable rule implementations
tools/                        reproducible builders for generated entries and artwork
tests/                        pytest suites for the verifier, the API and the rules
docs/assets/                  README artwork, light and dark, generated by tools/build_assets.py
CATALOGUE.md                  generated table of entries, by use case and in full
manifest.json                 generated JSON index of every entry
dataset.jsonld                generated schema.org Dataset description
llms.txt                      generated map of the archive for AI agents
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
uv run almanac index                                      # refresh manifest.json, dataset.jsonld, llms.txt
uv run pytest
```

## Licences

- **Entries** (`entries/`, `schema/`, the generated catalogue and indexes)
  are data, released under the Open Database License 1.0 in `LICENSE-DATA`.
  Share, create and adapt the database; attribute it; keep derived databases
  open.
- **Code** (`almanac/`, `tools/`, `tests/`) is released under the Apache
  License 2.0 in `LICENSE`.

Each evidence item also records the licence of its own source; that licence
governs the source material, not this repository's restatement of it.

## Citing

See `CITATION.cff`. In prose: Muhammed Rasin, *Misata Almanac*, Misata Labs,
https://github.com/Misata-labs/almanac.

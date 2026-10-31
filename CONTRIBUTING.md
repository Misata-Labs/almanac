# Contributing

The Almanac only accepts entries whose every value traces to a primary
source fetched while the entry was written. Read this before opening a
pull request.

## Source policy

Allowed sources, in priority order:

1. National statistical offices.
2. Central banks.
3. Government ministries, regulators and official gazettes.
4. Intergovernmental bodies: World Bank, IMF, OECD, UN agencies, BIS, ILO, WHO.
5. Official operators of payment or numbering systems (for example a national
   payments corporation, a telecom regulator, the IBAN registry maintainer).
6. Peer-reviewed open-access papers.

Not allowed as primary sources: blogs, vendor marketing, news articles,
encyclopaedias, forums, paywalled documents, and output of language models.
Code or data an official body publishes on a code-hosting platform under its
own organisation counts as that body's publication; pin it to a commit.

Never write a number, rate, rule or date from memory. If you cannot fetch and
confirm a value, leave the entry out.

## Tiers

- **A**: reproducible from an official machine-readable artefact at an exact
  URL, hash recorded.
- **B**: a value located in an official PDF or HTML document, with page, table
  or cell locator and a snippet.
- **C**: estimate or derived value; clearly labelled, with `assumed[]` filled
  in. Prefer omitting.

## Writing an entry

1. Pick `entries/<domain>/<region>/<id>.yaml`. `region` is an ISO 3166-1
   alpha-2 code or `global`; `id` equals the file name.
2. Fetch each source yourself. Record the URL you fetched, the date, the
   locator, the value exactly as it appears, the unit from the controlled
   vocabulary, one snippet under 25 words that locates the value, the source
   licence, and the SHA-256 of the fetched bytes:
   `curl -sSL <url> | sha256sum`.
   Fetch twice and compare the hashes: a page that changes on every request
   (personalised HTML, rotating tokens) cannot be verified and must not be
   cited. Prefer an API response, a CSV, or a PDF from the same publisher.
   PDFs are searched by their extracted text, so take snippets from text the
   PDF actually contains, not from headings rendered as images.
   Mark an item `role: supporting` when it documents context such as units
   or licence terms rather than a value the spec depends on; supporting items
   may be HTML or PDF even in a tier A entry.
3. For a rule, implement it under `almanac/rules/<name>.py` with an
   `evaluate(parameters, value)` function, and take the test vectors from the
   source's own worked examples (`origin: source`). Vectors you construct from
   source data, such as a date absent from a published list, are
   `origin: derived` and should stay few.
4. For a distribution, declare the family and parameters, and add tests whose
   expected values are the statistics the source publishes.
5. Anything fitted, restated or assumed goes in `assumed[]` with `method` and
   `rationale`.
6. Set `status`: `draft` while working, `license-review` if the source's terms
   are unclear, `verified` only when the verifier passes and all source
   licences are clearly permissive.
7. Write `notes` for a reader who has never seen the source: what the rule is,
   where the dates come from, anything odd you noticed.

## Licence identifiers

`source_license` takes an SPDX identifier where one exists (Apache-2.0, MIT,
OGL-UK-3.0, CC-BY-4.0, ODbL-1.0, CC0-1.0 and so on). A `verified` entry may
cite only licences the verifier lists as permissive, plus these documented
publisher terms, each of which explicitly permits free reuse with attribution:

| Identifier | Publisher | Clause |
| --- | --- | --- |
| ECB-free-use-with-attribution | European Central Bank | Users may make free use of information obtained from the ECB website provided it is reproduced accurately and the ECB is cited as the source (website disclaimer, Copyright section). |

Any other wording, including "reproduction permitted after permission" or
"no derivatives", keeps the entry at `license-review`. Write `unstated` when
the source carries no licence statement at all.

## Generated entries

Entries built from APIs live next to a builder under `tools/` that fetches
the pinned URLs and rewrites the YAML. Re-run the builder rather than editing
those files by hand, and commit both. After adding or changing entries run
`uv run almanac catalogue --write CATALOGUE.md` and `uv run almanac index`
so the catalogue, manifest, schema.org description and llms.txt stay current;
a test fails when they drift.

## Tags and use cases

`tags` are free-form lowercase topics (`vat`, `check-digit`, `census`).
`use_cases` name the business scenario an entry serves, so the catalogue can
be read by problem. Reuse these before inventing a new one:

payroll-demo, hr-analytics, workforce-planning, personal-finance,
financial-planning, banking-demo, loan-pricing, mortgage-origination,
credit-risk, collections, treasury, payments-demo, fintech-demo,
payments-reconciliation, payments-scheduling, kyc-onboarding, kyb-onboarding,
company-generation, person-generation, household-generation,
address-generation, customer-segmentation, market-sizing, invoicing,
accounts-payable, tax-filing-demo, audit-demo, financial-reporting,
multi-currency-ledger, contract-indexation, pricing, retail-demo,
demand-forecasting, sales-generation, insurance, pensions, health-demo,
utilities-demo, telecom-demo, digital-channels, logistics,
capacity-planning, sla-calculation, event-timestamps, crm-demo.

## Before opening a pull request

Run all of these and include the output summary in the pull request:

```
uv sync
uv run almanac verify <path-to-your-entry>
uv run almanac verify
uv run pytest
```

Then confirm by hand:

- Open each evidence URL in a browser and check the snippet and value are
  there and the locator is right.
- Confirm the licence you recorded is the one the publisher states.
- Check that `valid_from`, `valid_to` or `observed_period` reflect what the
  source says, not what you expect.
- Re-read `assumed[]`: is every restatement, conversion or derived parameter
  listed?

Pull requests that add values without fetched evidence, or that copy tables
or passages from a source, will be declined.

## Code

Code is typed, small and documented for intent. Comments explain what the
code does and why, never the history of how it was written. Run `uv run
pytest` before pushing. Commit messages are short and simple.

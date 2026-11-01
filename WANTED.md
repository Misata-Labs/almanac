# Wanted entries

The entries below would each make the Almanac materially more useful. For
each one the official source is named so a contributor can start from the
right place. None of the values are recorded here: an entry exists only
once its source has been fetched, hashed and cited under the rules in
CONTRIBUTING.md.

Claim one by opening an issue titled with the entry id.

Already done, for the pattern to copy: `br-cnpj-check-digits`,
`br-pix-monthly-volume-and-value`, `br-pix-key-types`, the twelve
`gb-census-2021-*` marginals, `gb-vat-rates`, `in-gst-rate-structure`,
`global-iso4217-currency-minor-units`, `global-ecb-euro-fx-reference-rates-monthly-2025`,
`global-population-by-economy-2024`, `global-central-bank-policy-rates-monthly-2025`,
the thirteen World Bank reference tables, the ECB, BCB and ONS series,
`gb-income-tax-bands-2026-27`, `gb-national-minimum-wage-2026-2027`,
`gb-sic-2007-condensed-codes`, `us-treasury-reporting-rates-of-exchange-2025-12-31`,
`us-federal-holidays`, `us-vin-check-digit`, `us-npi-check-digit`,
`us-icd-10-cm-2026-categories`, `global-e164-country-calling-codes-2011`,
`gb-house-price-index-monthly-2025` and the Eurostat entries each started as a line
in this file.

## Blocked by bot protection, worth a manual download

GS1 (GTIN check digit), the Bureau International des Containers (ISO 6346
check digit), Ofcom numbering data, UNECE UN/LOCODE, the NHS data dictionary
and USPS Publication 28 all refuse non-browser clients. Download the official
file by hand, cite its URL and record its hash; the verifier will re-fetch it
from a machine that is allowed through.

Three Indian sources are stable but not yet usable: the TRAI December 2025
subscription release is an image-only PDF with no extractable text, the IRDAI
Handbook on Indian Insurance Statistics ships as a ZIP of workbooks that the
verifier cannot search, and PFRDA subscriber and asset figures are served
dynamically rather than in the statistics handbook. A reader with the files
to hand can extend `in-wireless-subscribers-monthly-2025` through December and
add NPS subscriber counts by sector.

## Most wanted right now

| Entry id | Why it matters | Where the official source lives |
| --- | --- | --- |
| global-iban-structure | Every bank transfer generator needs it | SWIFT IBAN Registry (the site refuses non-browser clients; download the TXT release by hand and cite its release number) |
| in-upi-monthly-volume | The largest real-time payment system by volume | NPCI product statistics (download the XLSX by hand) |
| in-nps-subscribers-and-aum-by-sector | Pension demos need the sector split | PFRDA monthly statistics (served dynamically; save the table by hand) |
| br-cpf-check-digits | The identifier on every Brazilian customer record | Receita Federal do Brasil |
| global-card-pan-luhn | Card numbers that pass issuer checks | ISO/IEC 7812 registration authority |
| eu-vat-rates | Invoices across 27 member states | European Commission, Taxation and Customs Union |

## Identifiers and numbering systems

| Entry id | What it fixes | Where the official source lives |
| --- | --- | --- |
| global-iban-structure | IBAN length, check digits (ISO 7064 MOD 97-10) and per-country BBAN layout | SWIFT, the ISO 13616 registration authority: the IBAN Registry (TXT and PDF releases) |
| br-cpf-check-digits | Brazilian CPF check digits | Receita Federal do Brasil |
| in-aadhaar-verhoeff | Aadhaar number Verhoeff check digit | Unique Identification Authority of India |
| in-pan-format | Permanent Account Number structure | Income Tax Department, India |
| in-gstin-format | GSTIN composition and check character | Goods and Services Tax Network |
| in-ifsc-format | IFSC bank branch code structure | Reserve Bank of India |
| global-lei-check-digits | Legal Entity Identifier structure and MOD 97-10 check digits | Global Legal Entity Identifier Foundation (api.gleif.org serves stable LEI records; the structure page is HTML) |
| global-isin-check-digit | ISIN Luhn check digit | Association of National Numbering Agencies (ISO 6166); the ANNA site has moved, find the current standard page |
| gb-nhs-number-check-digit | NHS number modulus 11 check digit | NHS England data dictionary (the site refuses non-browser clients; save the page by hand) |
| gb-postcode-format | Postcode structure as defined for government data exchange | Office for National Statistics or Cabinet Office |
| us-ssn-issuance-rules | Social Security number structural exclusions since randomisation | US Social Security Administration |
| us-routing-number-check-digit | ABA routing transit number check digit | Federal Reserve or ABA |
| ca-sin-luhn | Canadian Social Insurance Number Luhn check | Employment and Social Development Canada |
| au-abn-check-digits | Australian Business Number modulus 89 check | Australian Business Register |
| au-tfn-check-digit | Tax File Number weighted check | Australian Taxation Office |
| fr-siren-siret-luhn | SIREN and SIRET Luhn check | INSEE |
| de-steuer-id-check-digit | German tax identification number check digit | Bundeszentralamt für Steuern |
| nl-bsn-eleven-proof | Dutch citizen service number eleven-proof | Rijksoverheid / Logius |
| es-dni-nie-letter | Spanish DNI and NIE control letter | Ministerio del Interior |
| it-codice-fiscale | Italian fiscal code composition and control character | Agenzia delle Entrate |

## Payments

| Entry id | What it fixes | Where the official source lives |
| --- | --- | --- |
| in-upi-monthly-volume | UPI transaction count and value by month, giving ticket size | National Payments Corporation of India, product statistics (the site refuses non-browser clients; fetch the published XLSX by hand) |
| in-upi-vpa-format | Virtual payment address structure | National Payments Corporation of India |
| eu-sepa-creditor-identifier | SEPA creditor identifier structure and check digits | European Payments Council |
| global-card-pan-luhn | Payment card number Luhn check and issuer identifier lengths | ISO/IEC 7812 registration authority (ABA) |
| gb-sort-code-structure | Sort code and account number modulus checks (VocaLink rules) | Pay.UK |

## Tax and pricing

| Entry id | What it fixes | Where the official source lives |
| --- | --- | --- |
| in-gst-rate-schedule | Item-level GST rates by HSN chapter with effective dates (the slab structure is already in in-gst-rate-structure) | Central Board of Indirect Taxes and Customs rate notifications |
| gb-vat-rate-history | Historic standard-rate changes before 2011 (current rates are in gb-vat-rates) | HM Revenue & Customs |
| eu-vat-rates | VAT rates by member state | European Commission, Taxation and Customs Union |
| ca-cash-rounding | Cash rounding to the nearest five cents after the penny was withdrawn | Department of Finance Canada |
| ch-cash-rounding | Rounding to five centimes | Swiss Federal Department of Finance |
| us-sales-tax-rates | State sales tax rates with effective dates | State revenue departments |

## Calendars and time

| Entry id | What it fixes | Where the official source lives |
| --- | --- | --- |
| in-gazetted-holidays | Central government gazetted holidays | Ministry of Personnel, Public Grievances and Pensions |
| br-national-holidays | National holidays and point facultativo days | Ministério da Gestão e da Inovação |
| global-target2-closing-days | TARGET closing days for euro settlement | European Central Bank (use the ECB Data Portal or a PDF; the website renders dynamically) |
| us-nyse-trading-calendar | Exchange holidays and early closes | NYSE |

## Distributions from official statistics

| Entry id | What it fixes | Where the official source lives |
| --- | --- | --- |
| gb-population-by-age-sex | Mid-year population by single year of age and sex, as a conditional on top of the Census 2021 marginals | Office for National Statistics |
| us-household-income-distribution | Household income distribution by bracket | US Census Bureau API (needs a free API key; record the query without the key) |
| in-population-by-state | Population by state and sex | Office of the Registrar General, Census of India |
| gb-baby-names | Given name frequencies by sex and year | Office for National Statistics |
| us-baby-names | Given name frequencies by sex and year | US Social Security Administration |
| global-retail-sales-seasonality | Monthly retail sales index with seasonal factors for the US and euro area (the UK series is in gb-retail-sales-index-volume-monthly-2025) | US Census Bureau, Eurostat |
| gb-card-spending-by-category | Card spending shares by merchant category | Bank of England or UK Finance |
| in-mobile-subscribers-by-operator | Subscriber shares by operator | Telecom Regulatory Authority of India |

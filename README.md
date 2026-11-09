<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
    <img src="docs/assets/hero-light.svg" alt="Misata Almanac: open rulebook of real-world data rules for synthetic data, with receipts" width="100%">
  </picture>
</p>

# Misata Almanac

### Synthetic data rules for realistic synthetic data. Every rule has a receipt.

Check-digit algorithms, identifier formats, tax rates, bank holidays, currency
conventions, industry code lists and official statistics, collected in one
place and traced back to the government body, central bank, regulator or
standards agency that published them. The reference layer for synthetic data
generation, privacy-safe test data, demo environments and data validation,
read by the [Misata](https://pypi.org/project/misata/) synthetic data engine.

Created and edited by Muhammed Rasin · [Misata Studio](https://www.misata.studio) · [misata on PyPI](https://pypi.org/project/misata/)

---

## Why realistic synthetic data needs a rulebook

Synthetic data is only as useful as its fidelity. A generated VAT number
whose check digits do not add up, an invoice dated on a bank holiday, a yen
amount with two decimals, a tax code with a leading zero, a Pix transaction id
with hyphens in it: each is a small departure from how real records behave,
and each one stops a dataset at the first validator, reconciliation job or
review it meets. Teams building synthetic data for product demos, QA
environments, analytics prototypes and machine learning need records that
follow the same rules as production data, without touching production data.

Fidelity is not a matter of cleverer generators. It comes from knowing the
rules, knowing where they come from, and being able to prove it. That is what
an almanac is for.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/before-after-dark.svg">
    <img src="docs/assets/before-after-light.svg" alt="Synthetic data before and after the Misata Almanac: invoice, customer and Pix records failing real checks, then passing" width="100%">
  </picture>
</p>

## What makes this different

Much of the reference data that synthetic data tools rely on is second-hand:
copied from a blog, a wiki, or someone's memory. Nothing here was typed from
memory.

- **Primary sources only.** HM Revenue & Customs, Banco Central do Brasil,
  the European Central Bank, Eurostat, the Office for National Statistics,
  the World Bank, the US Code of Federal Regulations, the CDC, Receita
  Federal, the ITU, the ISO 4217 maintenance agency. If a body did not
  publish it, it is not in here.
- **Receipts, not citations.** Every value records the exact URL it was
  fetched from, the SHA-256 of the bytes, where in the resource it sits, and
  a snippet that finds it. A citation says "trust me". A receipt says "check".
- **Executable, not descriptive.** Rules ship as typed Python with the
  publisher's own worked examples as test vectors. Distributions ship with the
  published counts beside the derived shares, and the verifier reproduces
  them by sampling.
- **Dated.** Every entry says when it applied. Ask the archive what the world
  looked like on any given day.
- **Re-verifiable by anyone.** One command re-fetches every source and fails
  loudly if anything drifted. There is no CI because you should not have to
  trust ours.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/proof-chain-dark.svg">
    <img src="docs/assets/proof-chain-light.svg" alt="How a value earns its place in the Almanac: primary source, exact URL, SHA-256, locator and snippet, test vectors, verifier" width="100%">
  </picture>
</p>

## Start from the problem you are solving

Every entry is tagged with the business scenario it serves, so a demo team or
a test engineer pulls exactly what the story needs.

```
uv run almanac list --use-case payroll-demo
uv run almanac list --use-case kyb-onboarding
uv run almanac applies --on 2026-06-15 --use-case banking-demo
```

| You are building… | Reach for |
| --- | --- |
| **A payroll or HR demo** | UK Income Tax bands with the tapered Personal Allowance, National Minimum Wage by age band and date, ASHE pay percentiles by region and worker group, SOC 2020 occupations, sickness absence by age, occupation and industry, OECD wages, tenure, hours and tax wedges, ILO earnings by occupation, US General Schedule pay grids, German social insurance rates, public holidays for ten countries |
| **A banking, lending or treasury demo** | Selic and ECB deposit-rate step schedules, policy rates for nine economies, the daily US Treasury par yield curve, HMDA mortgage applications by outcome, purpose and loan type, New York Fed household debt by type, delinquency and borrower age, credit scores at origination, every US bank failure since 2000, Survey of Consumer Finances income and net worth |
| **A payments or fintech demo** | Pix identifier formats, monthly Pix volume and average ticket, Pix key-type mix, HMRC payment reference check characters, bank holidays for settlement calendars |
| **KYC, KYB or customer onboarding test data** | Personal and business identifiers for sixteen countries: Australian ABN, Polish PESEL and NIP, Danish CPR, German tax ID, Belgian national number, Dutch BSN, Norwegian organisation number, Lithuanian personal code, Swedish personnummer, South African ID, US SSN, ITIN and EIN prefixes, French SIREN and SIRET, Swiss AHV, Indian PAN, Irish TRN, Finnish identity code, plus CNPJ and UTR check digits, VAT registration number validation, Companies House company types and statuses, SIC 2007 codes, the email pattern HMRC accepts, World Bank economy classification |
| **Invoicing, tax or audit test data** | UK VAT rates, India GST slab structure, ISO 4217 minor units, ECB and US Treasury exchange-rate tables, CPIH and IPCA price indices |
| **Synthetic customers, people and households** | First names by sex, region and birth cohort for England and Wales, Scotland, France, Ireland, Belgium, Spain and Norway, US Census surnames with ethnicity shares, Census 2021 marginals, single-year age distributions, world population weights |
| **Healthcare and claims test data** | MS-DRG FY2026 relative weights and lengths of stay, Medicare inpatient payments by DRG, outpatient APCs, top physician services, Part B and Part D drug spending, HCPCS Level II sections, office-visit RVUs, readmission penalties, Medicare enrolment, NDC and Orange Book product mixes, ICD-10-CM categories, the NPI check digit |
| **Insurance, property or fleet data** | FEMA disaster declarations by year, incident type and state, FHFA house price indices by state, UK house prices, the VIN check digit, EPA fuel economy by vehicle class, licensed vehicles by body type, fuel and make, MOT failure rates and defect mix |
| **Retail and demand forecasting demos** | Retail sales index with its December peak, inflation by month and by country, GDP and GDP per capita by economy |
| **Telecom, energy and utilities demos** | ITU country calling codes, internet and mobile penetration by economy, household electricity prices for ten EU states, clock-change dates |
| **Addresses, geography and product catalogues** | US state, county and CBSA codes, ZIP Code Tabulation Areas by prefix, Census places, French regions, départements and communes, NUTS 2024 with urban-rural typologies, Japanese postal codes, IANA time zones, UN M49 areas, ISO 639 languages, NAICS, ISIC, COICOP and COFOG structures |
| **Fleet, mobility and telematics** | US fatal crashes by month, weekday, hour, weather and light, GB collisions by severity, hour and speed limit, driver and vehicle age in collisions, road traffic by vehicle and road type, NHTSA recalls, FAA aircraft registry and airports, rail, air and port volumes |
| **US payroll, tax and benefits for 2026** | Federal income tax brackets for every filing status, the Publication 15-T withholding worksheet, standard deduction, capital gains breakpoints, AMT, EITC, child tax credit, wage bases, mileage rates, 401(k), IRA, HSA and ACA limits, Medicare Part A and B premiums with IRMAA tiers, HHS poverty guidelines, conforming loan limits by county, MACRS depreciation |
| **European payroll** | Germany's income tax formula with splitting, solidarity surcharge, child benefit, minimum wage and minijob limits, social insurance reference values; income tax scales for Austria, the Netherlands, Ireland with USC and PRSI, Spain, France and Poland; Dutch youth minimum wages; Spanish contribution bases and rates |
| **AML, fraud and compliance** | Bank Secrecy Act reporting thresholds, SAR thresholds by institution type, Form 8300 instalment aggregation, FDIC and NCUA insurance coverage, Regulation F call limits, TCPA calling hours, FTC cooling-off and mail-order rules, UK money-laundering thresholds, HM Treasury high-risk countries, UK GDPR deadlines, DPA 2018 penalty maxima, PSD2 strong customer authentication exemptions |
| **Bank accounts and payment validation** | German sort codes with BIC and check method, twenty German account check-digit methods, UK sort code modulus checking with every exception, account number standardisation, the IBAN MOD 97 check, US routing number prefixes, German base rate and late-payment interest, UK statutory late-payment compensation |
| **Invoicing and e-invoicing** | Italy FatturaPA document, VAT nature, regime and payment codes, Peppol VAT categories, invoice types, payment means, address schemes and units, Mexico CFDI 4.0 catalogues, Poland KSeF, Spain VeriFactu, Saudi ZATCA, India's e-invoicing thresholds, VAT and GST rates for OECD members, Japan, Switzerland, Australia, Singapore and Norway |
| **Trade, customs and e-commerce** | US tariff schedule headings and duty rates for apparel, footwear, machinery, electronics, furniture and toys, US de minimis and informal entry thresholds, UK tariff sections and consumer-goods duties, EU Combined Nomenclature 2026 |
| **The Gulf: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman** | Population pyramids and workforce by nationality, sector and sex, wages by nationality, age and education, migrant stock by country of origin for every GCC state, remittance outflows and sending costs, CPI by group, Saudi point-of-sale spending by merchant activity and city, card, ATM and instant payments, hotel occupancy and guests by nationality, VAT rates and thresholds, UAE corporate and top-up tax, Saudi withholding tax, end-of-service gratuity, working time and leave rules, IBAN formats, currency pegs |
| **India: labour codes and company law** | The four Labour Codes in force from November 2025, the 50 per cent wage rule, bonus, gratuity, retrenchment, maternity, working hours and establishment thresholds, EPF limits, contractor and professional-fee TDS, MSME classification, small company and CSR thresholds |
| **Value pools: margins, costs, churn and defaults** | After-tax margins by industry from the Census Quarterly Financial Report, FDIC bank performance ratios and size classes, Fed charge-off and delinquency rates, IRS corporation returns by sector, Eurostat enterprise accounts for ten member states with operating rate and personnel-cost share, enterprise birth, death and survival rates, hourly labour cost by section, UK rate of return and business survival |
| **Behaviour over time** | UK employment, unemployment, vacancies, redundancies and claimant count by month, average weekly earnings, household saving ratio, internet share of retail, energy price cap levels, EU air passengers by month, Indian wireless subscribers and ARPU by quarter |
| **India: telecom, insurance and insolvency demos** | TRAI subscribers by operator and service area, prepaid versus postpaid split, mobile number portability requests, broadband by provider, IRDAI premium by segment and death-claim outcomes, IBBI corporate insolvency status and recoveries by initiator, Income Tax slabs and GST structure |

The complete map of use cases to entries opens [CATALOGUE.md](CATALOGUE.md).

## Thirty seconds to a verified rule

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
almanac.rule("us-federal-holidays").call("is_holiday", date(2026, 7, 3))       # True, the observed day
almanac.rule("br-selic-target-rate-changes-2025").call("value_on", date(2025, 7, 1))  # 15.0

for entry in almanac.select(on=date(2026, 6, 15), region="GB", kind="rule"):
    print(entry.id, entry.tier, entry.status)
```

## What is inside

Eight hundred and thirty-two entries across thirty-seven domains and thirty-three
regions at the time of writing, every one of them passing live verification. The generated
[CATALOGUE.md](CATALOGUE.md) is the authoritative list; this is the tour.

**Rules from statute and regulation.** US Regulation CC funds-availability
amounts, Regulation E liability limits, Regulation Z thresholds, FCRA time
limits, FLSA salary levels, OSHA and FMLA thresholds, the federal minimum wage
history, Social Security full retirement age, FICA rates, the HIPAA
safe-harbour identifier list, FDA daily values; UK working-time limits and
statutory holiday entitlement; UK Scottish income tax, dividend, capital gains,
corporation, stamp duty and inheritance tax rates; Universal Credit,
Jobseeker's Allowance, disability and child benefit rates; State Pension rates.

**Identifier validation and check digits.** UK National Insurance numbers,
Unique Taxpayer References, VAT registration numbers and the PAYE, SDLT and
other-tax payment references, all from HM Revenue & Customs' own validation
library with its own test suite as vectors. Brazil CNPJ check digits for the
numeric and the new alphanumeric format, from Receita Federal's worked
example. The US vehicle identification number check digit lifted from
49 CFR 565.15 through the eCFR API, with NHTSA's decoder confirming the
vectors. The National Provider Identifier check digit from the CMS note that
defines it.
Nineteen more national identifiers, each from its own issuing body or the
OECD's tax identification sheets: the Australian Business Number from the
Australian Business Register's worked example, PESEL and NIP, the Danish CPR
number from CPR-kontoret, the German tax identification number with all six
ELSTER examples, the Belgian national register number, the Dutch BSN eleven
test with the population register's own test persons, Norwegian organisation
numbers, Lithuanian personal codes, the Swedish personnummer from Statistics
Sweden, South African identity numbers, US SSN, ITIN and EIN prefix rules from
the regulation and the IRS, and the formats of SIREN, SIRET, AHV, PAN, the
Irish tax reference and the Finnish identity code. Two generic engines,
weighted modulus and ISO 7064 MOD 11,10, sit underneath them.

**Payments and currency.** Pix identifier formats from the Banco Central do
Brasil API specification, monthly Pix volume with the derived average ticket,
and the mix of Pix key types registered in the DICT. ISO 4217 currency codes
with numeric codes and minor units from the maintenance agency's own list.
ECB euro reference rates for seven currencies. US Treasury reporting rates of
exchange for 174 currency pairs.

**Tax, payroll and employment.** UK VAT rates with the 2011 effective date.
UK Income Tax bands and the tapered Personal Allowance for 2026 to 2027.
National Minimum Wage and National Living Wage rates for April 2026 and April
2027. The PAYE tax code format. The India GST slab structure after the 56th
GST Council meeting.

**Calendars.** UK bank holidays by nation through 2028 from the GOV.UK
endpoint. The British Summer Time clock-change rule with its published dates.
US federal holidays from the statute, the executive order and the regulation,
with the Saturday and Sunday observance rules that payroll and settlement
systems actually apply.
Public holidays for Japan from the Cabinet Office since 1955, France
metropolitan, Alsace-Moselle and overseas zones, Hong Kong, Australia by state
and territory, Singapore with observed days, Spain by autonomous community,
India's central government list with restricted holidays, and the statutory
rest days of Mexico and Ireland. One shared engine answers whether a
day is a holiday, the next business day, and N business days ahead.

**Economy, rates and prices.** Eighty World Bank reference tables by economy,
from GDP per capita to financial account ownership, health workforce, energy
access, broadband, education and emissions, plus the region and income-group
classification. Euro area HICP inflation and mortgage cost of
borrowing. ECB deposit facility and Selic target rate changes as step
schedules. Central bank policy rates for nine economies. UK CPIH and retail
sales indices. Brazil IPCA inflation and household credit default rate.
Eurostat unemployment and inflation by member state, household electricity
prices across ten states.

**Demographics.** Twelve Census 2021 marginals for England and Wales: sex,
single year of age, ethnic group, religion, marital status, economic activity,
general health, highest qualification, household size, tenure, car
availability, accommodation type. Single-year age distributions for Germany
and France. Population by sex for ten member states. World population weights
for 217 economies.

**The Gulf.** Gulf populations are majority migrant, so nationality drives
almost every distribution, and the archive models it that way. Saudi labour
force, social insurance and population tables by nationality, sex, age,
region, occupation and activity from GASTAT, with wages by age and education,
CPI weights and retail prices, household income and spending, and SAMA's
point-of-sale, card, ATM, instant payment and personal transfer statistics.
Abu Dhabi prices, hotels, bank rates, births and building permits from its
statistics centre, and UAE bank deposits, vehicles and licences from the
federal open data portal. Qatar labour force, occupations, wages by sector,
CPI and hotel guests; Kuwait workers and wages by nationality group and
sector; Bahrain population pyramids by nationality, wage bands, work permits
and visitors; Oman population and workers by governorate, sector and
nationality. For all six states, the UN's migrant stock by country of origin
and sex, migrant age structure, population pyramids and projections,
employment by activity, remittance outflows and costs, and obesity and
diabetes prevalence. The rules follow the tax authorities, labour ministries
and central banks: VAT, UAE corporate and minimum top-up tax, Saudi
withholding tax, Oman income tax, end-of-service gratuity formulas, working
time, leave and notice rules, holidays, IBAN formats and currency pegs.

**Business rules that systems enforce.** The thresholds, formulas and code
lists that payroll engines, banks, tax software and compliance tools apply on
every transaction, each with the statute, regulation or operator document it
came from. US federal tax and benefit figures for 2026 from the IRS revenue
procedures and publications, CMS and HHS notices in the Federal Register and
FHFA's county file. The Bank Secrecy Act, deposit insurance, debt collection,
telemarketing and consumer-protection rules from the eCFR. UK money
laundering, data protection, consumer contracts, payment services and late
payment rules from legislation.gov.uk. Germany's tax tariff, social insurance
values and default interest from Gesetze im Internet and the Bundesbank, with
the Bundesbank's sort code file and account check methods and Vocalink's UK
modulus checking. E-invoicing code lists from the Italian, Polish, Spanish,
Mexican and Saudi tax authorities and the Peppol network. Tariff schedules
from USITC, the UK Trade Tariff and Eurostat. India's Labour Codes from India
Code, with company, MSME, tax and market-cap thresholds from the ministries
and SEBI.

**People and names.** First-name distributions from seven statistical
offices: ONS for England and Wales nationally and by region, National Records
of Scotland, INSEE by sex and by birth cohort from 1960, CSO Ireland, Statbel
by region and province, INE with the mean age of each name, and Statistics
Norway. Surnames from the US Census Bureau with race and Hispanic-origin
shares per name, Statbel and Statistics Norway.

**Geography and code lists.** US state, county, CBSA and place codes with
land area and internal points, ZIP Code Tabulation Areas, the CBSA delineation
file. INSEE's official geographic code for regions, départements and communes.
NUTS 2024 codes and NUTS-3 typologies from Eurostat. Australian postal areas
and Japanese postal codes from their official publishers. IANA time zones
pinned to a release, UN M49 areas with development flags, ISO 639 languages,
NAICS 2022, ISIC Rev.4 and Rev.5, COICOP 2018 and COFOG.

**Healthcare and claims.** The MS-DRG FY2026 relative weights table with
geometric and arithmetic mean length of stay. Medicare inpatient discharges
and payments by DRG and state, outpatient APCs, the top physician services,
Part B and Part D drug spending, HCPCS Level II sections and coverage codes,
office-visit RVUs, readmission penalties by condition, Medicare enrolment by
state and age. FDA drug product mixes by dosage form, route and marketing
category, recalls by class and year. CDC births by month and year and the
leading causes of death. AHRQ costliest inpatient conditions and emergency
department costs by patient characteristic.

**Lending, failures and disasters.** HMDA mortgage applications by outcome,
purpose and type. The New York Fed household debt workbook: balances, delinquency
buckets, transitions into serious delinquency by age, credit scores at
origination. Every US bank failure since 2000 with assets and estimated loss.
FEMA declarations by year, incident type and state. FHFA
house prices by state and division, the Treasury par yield curve, the Federal
Reserve Payments Study and the Survey of Consumer Finances.

**Work and pay.** The SOC 2020 occupation list, ASHE annual and hourly pay
percentiles by region and worker group, sickness absence by age, region,
occupation, industry and employer type. OECD wages, minimum wages, tenure,
temporary and part-time shares, unemployment duration, protection indices,
retirement ages, tax wedges and hours. ILO earnings by occupation, informal
employment and hours for around a hundred economies. Eurostat vacancy rates,
labour market flows and minimum wage history. US General Schedule pay and
locality grids. German social insurance contribution rates from statute.

**Roads, vehicles and aviation.** NHTSA fatal crash distributions by month,
weekday, hour, weather and light, and by state. GB road collisions from
STATS19 by severity, time, conditions and speed limit, with driver and
vehicle age. Licensed vehicles by body type, fuel and make, new registrations
by fuel, road traffic by vehicle and road type, MOT results and defect mix.
EPA fuel economy by class, NHTSA recalls, the FAA aircraft registry and
airport facilities with runway lengths, border crossings, rail passengers,
airport passengers, car stock by age and port freight.

**Value pools and behaviour.** The numbers a demo most often has to invent
and gets wrong: what a company in a given industry actually earns, what it
pays its people, how often customers default or firms die. After-tax profit
margins by industry from the Census Bureau's Quarterly Financial Report. FDIC
quarterly aggregates and performance ratios, institutions by size class,
charter and state, the largest banks by assets. Federal Reserve charge-off and
delinquency rates by loan type, consumer credit outstanding and consumer loan
rates. IRS corporation returns and receipts by sector, individual returns by
income size. Eurostat enterprise accounts for ten member states by NACE
section and division with gross operating rate, personnel-cost share and
value added per person, enterprise births, deaths, churn and survival, hourly
labour cost and the gender pay gap by section, household consumption
structure, housing-cost burden, e-commerce sales and road freight load
factors. UK business births, deaths and survival by industry and region,
private non-financial corporations' rate of return, household saving ratio,
monthly labour market series and the energy price cap.

**India.** TRAI wireless and wireline subscribers by operator and licensed
service area, prepaid and postpaid split, ARPU and minutes of use by quarter,
porting requests, broadband by provider, pay-DTH by operator. IRDAI registered
insurers, premium by segment, motor premium by insurer and death-claim
settlement outcomes. IBBI corporate insolvency admissions by year and sector,
outcomes and realisation by initiator. Income Tax slabs under both regimes and
the GST rate structure.

**Healthcare, property, telecom, companies.** ICD-10-CM FY2026 diagnosis
categories with code counts from the CDC archive. UK House Price Index by
month from HM Land Registry. ITU-T E.164 country calling codes. Companies
House company types and statuses, the SIC 2007 condensed list, and the email
address pattern HMRC services accept.

Entries whose source terms are not clearly permissive wait at
`license-review` and say exactly why. [WANTED.md](WANTED.md) is the queue of
what comes next, each with the official body to source it from. If you know a
national numbering scheme or a statistical release well, that is where to
start.

## Anatomy of an entry

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/anatomy-dark.svg">
    <img src="docs/assets/anatomy-light.svg" alt="Anatomy of a Misata Almanac entry: spec runs in the data engine; evidence, assumed and tests are checked by the verifier" width="100%">
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
it. `assumed` is where anything restated, converted, fitted or guessed is
confessed, with the method. `tests` is what the verifier reproduces.

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
832 passed, 0 failed, 832 entries
```

## Frequently asked questions

**What is the Misata Almanac?**
An open, proof-backed knowledge base of the rules real-world data follows:
check-digit algorithms, identifier formats, tax rates, holiday calendars,
currency conventions, code lists and official distributions. Each entry is a
YAML file that cites its primary source, records a content hash, and carries
executable tests. It is the reference layer behind the Misata synthetic data
engine, and it works on its own as a Python library and CLI.

**Who is it for?**
Anyone producing synthetic data that has to behave like the real thing:
synthetic data and test data engineers, QA and platform teams seeding
environments, consultancies building client demonstrations, fintech, payments
and insurance teams, machine learning teams who need realistic training data
without personal data, and AI agents that need an authoritative answer to
"what does a valid VAT number look like" without guessing.

**How is this different from a random data generator?**
Generators produce values of the right shape. The Almanac supplies the rule
itself, with a receipt showing where it was published, and lets you check that
it still holds. The two work together: a generator produces the record, the
Almanac makes it realistic and verifiable.

**Can I use it without Misata?**
Yes. `uv sync` and `from almanac.api import Almanac` give you every rule,
distribution and series as typed Python. The YAML entries are plain data and
can be read by anything.

**Is the data licensed for commercial use?**
Entries are released under the Open Database License 1.0 and the code under
Apache 2.0. Each evidence item also records the licence of its own source.
Entries whose source terms are unclear are marked `license-review` and are
never marked `verified`.

**How do I know a value is still current?**
Run `uv run almanac verify`. It re-fetches every source, checks the hash,
finds the snippet and the value again, runs every rule vector and reproduces
every published statistic. A changed source fails the run and names the
entry.

**How does an AI agent find the right entry?**
Read `llms.txt` first; it maps the archive by business problem and links
every entry. `manifest.json` is the machine index with validity, publishers,
licences, tags and use cases, and `dataset.jsonld` describes the archive as a
schema.org Dataset. All three are generated from the entries and tested for
drift.

**What applied on a given date?**
`uv run almanac applies --on 2026-06-15` lists every entry whose validity
covers that day; add `--region`, `--domain` or `--use-case` to narrow it.

**Can I contribute an entry?**
Yes, and [CONTRIBUTING.md](CONTRIBUTING.md) explains the source policy, the
evidence tiers and the manual checks to run before opening a pull request.
Start with [WANTED.md](WANTED.md).

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

See `CITATION.cff`. In prose: Muhammed Rasin, *Misata Almanac*, Misata Studio,
https://github.com/Misata-labs/almanac. Misata itself lives at
https://www.misata.studio.

<sub>Keywords: synthetic data rules, realistic synthetic data, synthetic data generation, privacy-safe test data, data validation rules, check digit algorithms, VAT number validation, CNPJ validation, VIN check digit, NPI check digit, National Insurance number format, bank holidays API, federal holidays, ISO 4217 minor units, exchange rates, income tax bands, minimum wage rates, GST rates, ICD-10-CM codes, SIC codes, census distributions, official statistics, reference data, KYC test data, KYB test data, payroll test data, fintech demo data, Misata.</sub>

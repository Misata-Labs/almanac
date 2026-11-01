"""Regenerate the extended Companies House code-list entries from the pinned enumerations file.

Officer roles, accounts, registration and insolvency vocabularies are read
from the constants file Companies House publishes for its public API, pinned
to one commit; codes and labels are copied unchanged. The company type and
status lists live in the earlier entry gb-company-type-and-status-codes. Run
from the repository root:

    uv run python tools/build_gb_company_codes_extended.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

COMMIT = "05067abc50da2c9277bb5d3504187f55e5ec9e24"
URL = f"https://raw.githubusercontent.com/companieshouse/api-enumerations/{COMMIT}/constants.yml"
PUBLISHER = "Companies House"
TITLE = "Companies House API enumerations (companieshouse/api-enumerations constants.yml)"
VALID_FROM = "2026-09-11"
LICENSE_NOTE = (
    f"The code lists are enumerations Companies House publishes for its public API (companieshouse/api-enumerations, "
    f"commit {COMMIT[:8]}); codes and labels are copied unchanged. The repository carries no licence file, so the entry "
    "stays at license-review until the publisher's terms for this file are confirmed; Companies House data is generally "
    "released under the Open Government Licence, but that is not stated here. valid_from is the date of the pinned "
    "revision; valid_to is open."
)

# Each entry: id, title, tags, use cases, the enumeration names it carries, vectors and notes.
ENTRIES = [
    {
        "id": "gb-company-officer-role-codes",
        "title": "United Kingdom Companies House officer role and officer identification type codes",
        "tags": ["companies-house", "officer-role", "directors", "code-list"],
        "use_cases": ["company-generation", "kyb-onboarding", "person-generation", "audit-demo"],
        "sets": ["officer_role", "identification_type"],
        "vectors": [
            ({"set": "officer_role", "value": "director"}, True, "source", None),
            ({"set": "officer_role", "value": "secretary"}, True, "source", None),
            ({"set": "officer_role", "value": "llp-designated-member"}, True, "source", None),
            ({"set": "officer_role", "value": "corporate-director"}, True, "source", None),
            ({"set": "officer_role", "value": "chairman"}, False, "derived", "not a Companies House role code"),
            ({"set": "identification_type", "value": "uk-limited-company"}, True, "source", None),
            ({"set": "identification_type", "value": "eea"}, True, "source", None),
            ({"set": "identification_type", "value": "Director"}, False, "derived", "a label, not a code, and in the wrong set"),
        ],
        "notes": "Officer roles are the appointment types that appear on a company's officer list (director, secretary, LLP member, nominee and corporate variants, limited partnership partners and the organ memberships used for European entities); identification types describe how a corporate officer is identified. ",
    },
    {
        "id": "gb-company-accounts-codes",
        "title": "United Kingdom Companies House accounts type, foreign accounts and accounts publication terms codes",
        "tags": ["companies-house", "accounts", "filing", "code-list"],
        "use_cases": ["company-generation", "kyb-onboarding", "financial-reporting", "audit-demo"],
        "sets": ["account_type", "foreign_account_type", "terms_of_account_publication"],
        "vectors": [
            ({"set": "account_type", "value": "micro-entity"}, True, "source", None),
            ({"set": "account_type", "value": "dormant"}, True, "source", None),
            ({"set": "account_type", "value": "total-exemption-full"}, True, "source", None),
            ({"set": "account_type", "value": "unaudited-abridged"}, True, "source", None),
            ({"set": "account_type", "value": "abbreviated"}, False, "derived", "not in the current list"),
            ({"set": "foreign_account_type", "value": "accounting-requirements-of-originating-country-apply"}, True, "source", None),
            ({"set": "terms_of_account_publication", "value": "accounting-reference-date-allocated-by-companies-house"}, True, "source", None),
            ({"set": "terms_of_account_publication", "value": "full"}, False, "derived", "an account_type code, not a publication term"),
        ],
        "notes": "Account types label the kind of annual accounts a company last filed (full, small, micro-entity, dormant, group, exemption variants); the foreign account and publication-terms codes apply to overseas companies with UK establishments. ",
    },
    {
        "id": "gb-company-registration-codes",
        "title": "United Kingdom Companies House jurisdiction, company subtype, incorporation wording, register type and register location codes",
        "tags": ["companies-house", "jurisdiction", "registers", "code-list"],
        "use_cases": ["company-generation", "kyb-onboarding", "address-generation", "audit-demo"],
        "sets": ["jurisdiction", "company_subtype", "company_birth_type", "register_types", "register_locations"],
        "vectors": [
            ({"set": "jurisdiction", "value": "england-wales"}, True, "source", None),
            ({"set": "jurisdiction", "value": "scotland"}, True, "source", None),
            ({"set": "jurisdiction", "value": "northern-ireland"}, True, "source", None),
            ({"set": "jurisdiction", "value": "ireland"}, False, "derived", "not a Companies House jurisdiction"),
            ({"set": "company_subtype", "value": "community-interest-company"}, True, "source", None),
            ({"set": "company_birth_type", "value": "ltd"}, True, "source", None),
            ({"set": "register_types", "value": "persons-with-significant-control"}, True, "source", None),
            ({"set": "register_locations", "value": "registered-office"}, True, "source", None),
            ({"set": "register_locations", "value": "directors"}, False, "derived", "a register type, not a location"),
        ],
        "notes": "Jurisdictions name the register a company is incorporated in; subtypes flag community interest companies and private fund limited partnerships; company_birth_type maps each company type to the wording used for its incorporation date (incorporated, registered, formed or opened on); register types and locations describe the statutory registers a company may keep and where they are inspected. ",
    },
    {
        "id": "gb-company-insolvency-codes",
        "title": "United Kingdom Companies House insolvency case type and insolvency case date type codes",
        "tags": ["companies-house", "insolvency", "liquidation", "code-list"],
        "use_cases": ["company-generation", "kyb-onboarding", "credit-risk", "collections", "audit-demo"],
        "sets": ["insolvency_case_type", "insolvency_case_date_type"],
        "vectors": [
            ({"set": "insolvency_case_type", "value": "compulsory-liquidation"}, True, "source", None),
            ({"set": "insolvency_case_type", "value": "creditors-voluntary-liquidation"}, True, "source", None),
            ({"set": "insolvency_case_type", "value": "in-administration"}, True, "source", None),
            ({"set": "insolvency_case_type", "value": "corporate-voluntary-arrangement"}, True, "source", None),
            ({"set": "insolvency_case_type", "value": "bankruptcy"}, False, "derived", "a personal insolvency, not a company case type"),
            ({"set": "insolvency_case_date_type", "value": "wound-up-on"}, True, "source", None),
            ({"set": "insolvency_case_date_type", "value": "dissolved-on"}, True, "source", None),
            ({"set": "insolvency_case_date_type", "value": "in-administration"}, False, "derived", "a case type, not a date type"),
        ],
        "notes": "Insolvency case types classify the proceedings recorded against a company (liquidations, administration, receivership, voluntary arrangements, restructuring plans and the moratorium events); date types name the dated milestones within a case. ",
    },
]


def line_of(raw: bytes, key: str) -> int:
    """1-based line number of the top-level key ``key:`` in the YAML file."""
    for index, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if line.rstrip() == f"{key}:":
            return index
    raise LookupError(f"{key}: not found in {URL}")


def build(spec: dict, raw: bytes, constants: dict) -> dict:
    sets = {name: {str(code): str(label) for code, label in constants[name].items()} for name in spec["sets"]}
    items = []
    for name in spec["sets"]:
        first_code, first_label = next(iter(constants[name].items()))
        items.append(evidence(PUBLISHER, TITLE, URL, f"line {line_of(raw, name)}, {name} ({len(sets[name])} codes)", f"{name}:", "text", f"'{first_code}'", "unstated", raw))
    vectors = [
        {"input": value, "expected": expected, "origin": origin, **({"note": note} if note else {})}
        for value, expected, origin, note in spec["vectors"]
    ]
    return {
        "id": spec["id"],
        "title": spec["title"],
        "kind": "rule",
        "domain": "company",
        "region": "GB",
        "status": "license-review",
        "tier": "A",
        "valid_from": VALID_FROM,
        "valid_to": None,
        "tags": spec["tags"],
        "use_cases": spec["use_cases"],
        "spec": {"implementation": "almanac.rules.enumeration", "parameters": {"sets": sets}, "vectors": vectors},
        "evidence": items,
        "assumed": [],
        "tests": [{"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0}]
        + [{"statistic": f"count[{name}]", "expected": len(sets[name]), "tolerance": 0} for name in spec["sets"]],
        "notes": spec["notes"] + LICENSE_NOTE,
    }


def main() -> int:
    raw = fetch(URL)
    constants = yaml.safe_load(raw)
    for spec in ENTRIES:
        write(build(spec, raw, constants))
    return 0


if __name__ == "__main__":
    sys.exit(main())

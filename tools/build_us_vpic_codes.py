"""Regenerate the NHTSA vPIC entries: the vehicle attribute code lists (vehicle type, body class,
primary fuel type and drive type) and a table of well-known world manufacturer identifiers decoded by
the vPIC service. Run from the repository root:

    uv run python tools/build_us_vpic_codes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

API = "https://vpic.nhtsa.dot.gov/api/vehicles"
PUBLISHER = "National Highway Traffic Safety Administration"
LICENSE = "unstated"
LICENSE_NOTE = (
    "US federal government works carry no copyright, but the vPIC API states no reuse terms, so the licence is "
    "recorded as unstated and the entry held at license-review."
)
VARIABLES = {
    "vehicle_type": "Vehicle Type",
    "body_class": "Body Class",
    "fuel_type_primary": "Fuel Type - Primary",
    "drive_type": "Drive Type",
}
WMIS = ["1HG", "1G1", "1FA", "1FT", "1C4", "1N4", "2T1", "3VW", "4T1", "5YJ", "JHM", "JTD", "KMH", "WBA", "WVW", "WDD", "WAU", "SAL", "YV1", "ZFF"]


def values_url(variable: str) -> str:
    return f"{API}/GetVehicleVariableValuesList/{variable.replace(' ', '%20')}?format=json"


def wmi_url(wmi: str) -> str:
    return f"{API}/DecodeWMI/{wmi}?format=json"


def attribute_codes(responses: dict[str, bytes]) -> dict:
    sets = {}
    evidence_items = []
    for name, variable in VARIABLES.items():
        payload = json.loads(responses[name])
        results = payload["Results"]
        if payload["Count"] != len(results):
            raise ValueError(f"{variable}: Count {payload['Count']} differs from {len(results)} results")
        sets[name] = {str(r["Id"]): r["Name"] for r in sorted(results, key=lambda r: r["Id"])}
        # vPIC escapes solidus characters in its JSON, so the sample cited is the first name without one.
        sample = next(r for r in results if "/" not in r["Name"] and '"' not in r["Name"])
        evidence_items.append(
            evidence(PUBLISHER, f"vPIC API, GetVehicleVariableValuesList for {variable} (JSON)", values_url(variable), f'Results[Id={sample["Id"]}].Name', sample["Name"], "text", f'"Id":{sample["Id"]},"Name":"{sample["Name"]}"', LICENSE, responses[name])
        )
        evidence_items.append(
            evidence(PUBLISHER, f"vPIC API, GetVehicleVariableValuesList for {variable} (JSON)", values_url(variable), "Count", payload["Count"], "count", f'"Count":{payload["Count"]}', LICENSE, responses[name])
        )
    car_id = next(k for k, v in sets["vehicle_type"].items() if v == "Passenger Car")
    return {
        "id": "us-nhtsa-vpic-vehicle-attribute-codes",
        "title": "United States NHTSA vPIC vehicle attribute code lists: vehicle type, body class, primary fuel type and drive type",
        "kind": "rule",
        "domain": "automotive",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2026-10-31",
        "valid_to": None,
        "tags": ["vpic", "nhtsa", "vehicle-attributes", "code-list", "vin-decoding"],
        "use_cases": ["automotive-demo", "fleet-demo", "insurance", "claims-generation"],
        "spec": {
            "implementation": "almanac.rules.enumeration",
            "parameters": {"sets": sets},
            "vectors": [
                {"input": {"set": "vehicle_type", "value": car_id}, "expected": True, "origin": "source", "note": "Passenger Car"},
                {"input": {"set": "body_class", "value": next(iter(sets["body_class"]))}, "expected": True, "origin": "source", "note": sets["body_class"][next(iter(sets["body_class"]))]},
                {"input": {"set": "fuel_type_primary", "value": next(iter(sets["fuel_type_primary"]))}, "expected": True, "origin": "source", "note": sets["fuel_type_primary"][next(iter(sets["fuel_type_primary"]))]},
                {"input": {"set": "drive_type", "value": next(iter(sets["drive_type"]))}, "expected": True, "origin": "source", "note": sets["drive_type"][next(iter(sets["drive_type"]))]},
                {"input": {"set": "vehicle_type", "value": "0"}, "expected": False, "origin": "derived"},
            ],
        },
        "evidence": evidence_items,
        "assumed": [
            {
                "parameter": "valid_from",
                "value": "2026-10-31",
                "method": "assumed",
                "rationale": "The vPIC lists carry no effective date; valid_from is the day the lists were fetched, and the lists may grow as NHTSA adds values.",
            }
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            *[{"statistic": f"count[{name}]", "expected": len(codes), "tolerance": 0} for name, codes in sets.items()],
        ],
        "notes": (
            "The closed value lists NHTSA's Product Information Catalog and Vehicle Listing (vPIC) uses for four "
            "attributes of a decoded VIN, keyed by the vPIC numeric Id with the published Name as the label. They "
            "give a generator the exact vocabulary a vPIC decode returns for vehicle type, body class, primary fuel "
            "type and drive type, so synthetic fleet and policy records match what a VIN lookup would produce. "
            + LICENSE_NOTE
        ),
    }


def wmi_table(responses: dict[str, bytes]) -> dict:
    rows = {}
    evidence_items = []
    for wmi in WMIS:
        payload = json.loads(responses[wmi])
        if payload["Count"] != 1:
            raise ValueError(f"WMI {wmi}: expected one result, got {payload['Count']}")
        result = payload["Results"][0]
        rows[wmi] = {
            "make": result["Make"],
            "manufacturer": result["ManufacturerName"],
            "vehicle_type": result["VehicleType"],
            "common_name": result["CommonName"],
            "parent_company": result["ParentCompanyName"] or None,
            "available_to_public_from": result["DateAvailableToPublic"][:10] if result["DateAvailableToPublic"] else None,
        }
        evidence_items.append(
            evidence(PUBLISHER, f"vPIC API, DecodeWMI {wmi} (JSON)", wmi_url(wmi), "Results[0].ManufacturerName", result["ManufacturerName"], "text", f'"ManufacturerName":"{result["ManufacturerName"]}"', LICENSE, responses[wmi])
        )
    return {
        "id": "us-nhtsa-wmi-manufacturers",
        "title": f"United States NHTSA vPIC decode of {len(rows)} well-known world manufacturer identifiers (VIN positions 1 to 3)",
        "kind": "rule",
        "domain": "automotive",
        "region": "US",
        "status": "license-review",
        "tier": "A",
        "valid_from": "2026-10-31",
        "valid_to": None,
        "tags": ["vin", "wmi", "manufacturer", "nhtsa", "vpic", "reference-table"],
        "use_cases": ["automotive-demo", "fleet-demo", "insurance", "claims-generation"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"rows": rows},
            "vectors": [
                {"input": {"key": "1HG", "column": "make"}, "expected": rows["1HG"]["make"], "origin": "source"},
                {"input": {"key": "WBA", "column": "manufacturer"}, "expected": rows["WBA"]["manufacturer"], "origin": "source"},
                {"input": {"key": "1FT", "column": "vehicle_type"}, "expected": rows["1FT"]["vehicle_type"], "origin": "source"},
                {"input": "5YJ", "expected": True, "origin": "source"},
                {"input": "ZZZ", "expected": False, "origin": "derived", "note": "not among the identifiers kept here"},
            ],
        },
        "evidence": evidence_items,
        "assumed": [
            {
                "parameter": "rows",
                "value": "a hand-picked subset of identifiers",
                "method": "assumed",
                "rationale": "The identifiers were chosen as widely seen prefixes of passenger car and light truck VINs; the decoded values are copied from the vPIC responses, but the selection is the builder's and is not a complete list of any kind.",
            },
            {
                "parameter": "valid_from",
                "value": "2026-10-31",
                "method": "assumed",
                "rationale": "The decode responses carry creation dates for each record but no effective date for the assignment; valid_from is the fetch date.",
            },
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "value[JHM,make]", "expected": rows["JHM"]["make"], "tolerance": 0},
        ],
        "notes": (
            "The make, manufacturer and vehicle type NHTSA's vPIC service decodes for a set of common world "
            "manufacturer identifiers, the first three characters of a VIN, one API call per identifier. The table "
            "lets a generator pair a plausible VIN prefix with the make and vehicle type a decoder would report, "
            "while us-vin-check-digit supplies the check digit. Where the vPIC Make field lists several brands the "
            "value is kept as published. " + LICENSE_NOTE
        ),
    }


def main() -> int:
    write(attribute_codes({name: fetch(values_url(variable)) for name, variable in VARIABLES.items()}))
    write(wmi_table({wmi: fetch(wmi_url(wmi)) for wmi in WMIS}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

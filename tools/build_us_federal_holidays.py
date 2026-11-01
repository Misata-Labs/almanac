"""Regenerate the US federal holidays entry from the statute, the executive order and the regulation.

Sources: 5 U.S.C. 6103 as published by the Government Publishing Office, Executive Order 11582 as
codified by the National Archives, and 5 CFR 610.202 from the eCFR API. Run from the repository root:

    uv run python tools/build_us_federal_holidays.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

STATUTE_URL = "https://www.govinfo.gov/content/pkg/USCODE-2023-title5/html/USCODE-2023-title5-partIII-subpartE-chap61-subchapI-sec6103.htm"
ORDER_URL = "https://www.archives.gov/federal-register/codification/executive-order/11582.html"
CFR_URL = "https://www.ecfr.gov/api/versioner/v1/full/2026-10-29/title-5.xml?part=610"
LICENSE = "unstated"

HOLIDAYS = [
    {"name": "New Year's Day", "month": 1, "day": 1},
    {"name": "Birthday of Martin Luther King, Jr.", "month": 1, "weekday": "monday", "ordinal": "third"},
    {"name": "Washington's Birthday", "month": 2, "weekday": "monday", "ordinal": "third"},
    {"name": "Memorial Day", "month": 5, "weekday": "monday", "ordinal": "last"},
    {"name": "Juneteenth National Independence Day", "month": 6, "day": 19},
    {"name": "Independence Day", "month": 7, "day": 4},
    {"name": "Labor Day", "month": 9, "weekday": "monday", "ordinal": "first"},
    {"name": "Columbus Day", "month": 10, "weekday": "monday", "ordinal": "second"},
    {"name": "Veterans Day", "month": 11, "day": 11},
    {"name": "Thanksgiving Day", "month": 11, "weekday": "thursday", "ordinal": "fourth"},
    {"name": "Christmas Day", "month": 12, "day": 25},
]


def build(statute_raw: bytes, order_raw: bytes, cfr_raw: bytes) -> dict:
    return {
        "id": "us-federal-holidays",
        "title": "United States legal public holidays (5 U.S.C. 6103) with Saturday and Sunday observance rules",
        "kind": "rule",
        "domain": "calendar",
        "region": "US",
        "status": "license-review",
        "tier": "B",
        "valid_from": "2023-12-31",
        "valid_to": None,
        "tags": ["federal-holidays", "calendar", "working-days", "observed-holidays"],
        "use_cases": ["payments-scheduling", "payroll-demo", "logistics", "sla-calculation"],
        "spec": {
            "implementation": "almanac.rules.us_federal_holidays",
            "parameters": {"holidays": HOLIDAYS, "observance": {"saturday": "preceding_friday", "sunday": "following_monday"}},
            "vectors": [
                {"input": {"year": 2026, "name": "Birthday of Martin Luther King, Jr."}, "expected": {"name": "Birthday of Martin Luther King, Jr.", "date": "2026-01-19", "observed": "2026-01-19"}, "origin": "derived", "note": "third Monday in January 2026"},
                {"input": {"year": 2026, "name": "Independence Day"}, "expected": {"name": "Independence Day", "date": "2026-07-04", "observed": "2026-07-03"}, "origin": "derived", "note": "4 July 2026 is a Saturday, observed the Friday before"},
                {"input": {"year": 2027, "name": "Independence Day"}, "expected": {"name": "Independence Day", "date": "2027-07-04", "observed": "2027-07-05"}, "origin": "derived", "note": "4 July 2027 is a Sunday, observed the Monday after"},
                {"input": {"year": 2026, "name": "Christmas Day"}, "expected": {"name": "Christmas Day", "date": "2026-12-25", "observed": "2026-12-25"}, "origin": "source", "note": "the statute fixes 25 December; 2026-12-25 is a Friday"},
                {"input": {"year": 2026, "name": "Veterans Day"}, "expected": {"name": "Veterans Day", "date": "2026-11-11", "observed": "2026-11-11"}, "origin": "source", "note": "the statute fixes 11 November"},
                {"input": {"year": 2026, "name": "Thanksgiving Day"}, "expected": {"name": "Thanksgiving Day", "date": "2026-11-26", "observed": "2026-11-26"}, "origin": "derived"},
                {"input": {"year": 2026, "name": "Memorial Day"}, "expected": {"name": "Memorial Day", "date": "2026-05-25", "observed": "2026-05-25"}, "origin": "derived"},
                {"input": {"date": "2026-07-03"}, "expected": True, "origin": "derived"},
                {"input": {"date": "2026-07-04", "observed": False}, "expected": True, "origin": "derived"},
                {"input": {"date": "2026-07-04"}, "expected": False, "origin": "derived", "note": "the statutory date is not the observed day in 2026"},
            ],
        },
        "evidence": [
            evidence("Office of the Law Revision Counsel via the Government Publishing Office (govinfo)", "5 U.S.C. 6103, Holidays (United States Code 2023 edition)", STATUTE_URL, "subsection (a)", "Birthday of Martin Luther King, Jr., the third Monday in January.", "text", "The following are legal public holidays", LICENSE, statute_raw),
            evidence("Office of the Law Revision Counsel via the Government Publishing Office (govinfo)", "5 U.S.C. 6103, Holidays (United States Code 2023 edition)", STATUTE_URL, "subsection (b)(1)", "Instead of a holiday that occurs on a Saturday, the Friday immediately before is a legal public holiday", "text", "employees whose basic workweek is Monday through Friday", LICENSE, statute_raw),
            evidence("National Archives and Records Administration, Federal Register codification", "Executive Order 11582, Observance of holidays by Government agencies (1971)", ORDER_URL, "section 3(a)", "shall be excused from work on the next workday of his basic workweek whenever a holiday falls on Sunday", "text", "whose basic workweek does not include Sunday", LICENSE, order_raw),
            evidence("Office of Personnel Management via the eCFR API", "5 CFR 610.202, Determining the holiday", CFR_URL, "section 610.202(b)", "Executive Order 11582", "text", "Determining the holiday", LICENSE, cfr_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "observance",
                "value": "Saturday to preceding Friday; Sunday to following Monday",
                "method": "derived",
                "rationale": "The statute moves a Saturday holiday to the Friday before for Monday-to-Friday workweeks; Executive Order 11582 moves a Sunday holiday to the next workday of the basic workweek, which for that workweek is Monday. The rule implements only this common workweek; the alternative rules for other schedules in 6103(b)(2), (b)(3) and (d) are not modelled.",
            },
            {
                "parameter": "vectors",
                "value": "computed dates for 2026 and 2027",
                "method": "derived",
                "rationale": "The sources state the holidays as ordinal weekdays and fixed dates, not as calendar dates for a given year; the vectors apply those rules and are checked by hand against a calendar.",
            },
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(HOLIDAYS), "tolerance": 0},
            {"statistic": "count[2026]", "expected": 11, "tolerance": 0},
        ],
        "notes": (
            "The eleven legal public holidays of 5 U.S.C. 6103(a), each as a fixed date or an ordinal weekday of a month, "
            "with the observance shifts for a Monday-to-Friday workweek: Saturday holidays are observed the Friday before "
            "(6103(b)(1)) and Sunday holidays the Monday after (Executive Order 11582 section 3(a), referenced by 5 CFR "
            "610.202(b)). Inauguration Day (6103(c)) applies only in the Washington area every fourth year and is not "
            "modelled. valid_from is the statutory text's edition date (2023 edition, current through the end of 2023). "
            "US government works are not subject to copyright, but none of the three pages states terms, so the entry is "
            "held at license-review."
        ),
    }


def main() -> int:
    write(build(fetch(STATUTE_URL), fetch(ORDER_URL), fetch(CFR_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

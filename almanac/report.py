"""Rendering of verification reports for the terminal and for machines."""

from __future__ import annotations

import json
from typing import Iterable

from almanac.checks import EntryReport

_MARK = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}


def render_text(reports: Iterable[EntryReport], *, verbose: bool = False) -> str:
    lines: list[str] = []
    reports = list(reports)
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        lines.append(f"[{status}] {report.entry_id}  ({report.path})")
        for result in report.results:
            if result.outcome == "pass" and not verbose:
                continue
            detail = f"  {result.detail}" if result.detail else ""
            lines.append(f"    {_MARK[result.outcome]:<4} {result.name}{detail}")
    failed = sum(1 for r in reports if not r.passed)
    lines.append("")
    lines.append(f"{len(reports) - failed} passed, {failed} failed, {len(reports)} entries")
    return "\n".join(lines)


def render_json(reports: Iterable[EntryReport]) -> str:
    payload = [
        {
            "id": report.entry_id,
            "path": str(report.path),
            "passed": report.passed,
            "checks": [
                {"name": r.name, "outcome": r.outcome, "detail": r.detail} for r in report.results
            ],
        }
        for report in reports
    ]
    return json.dumps(payload, indent=2)

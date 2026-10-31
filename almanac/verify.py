"""The ``almanac verify`` command.

Validates entries against the schema and models, re-fetches every evidence
resource to confirm hashes, snippets and values, checks units and dates,
runs rule test vectors, and reproduces published statistics from declared
distributions. Exits non-zero when any entry fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from almanac.checks import Verifier
from almanac.fetch import Fetcher
from almanac.report import render_json, render_text
from almanac.store import DEFAULT_ENTRIES, DEFAULT_SCHEMA, iter_entry_files


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="almanac verify")
    parser.add_argument("paths", nargs="*", type=Path, help="entry files or directories (default: entries/)")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="JSON Schema to validate against")
    parser.add_argument("--cache-dir", type=Path, help="directory in which fetched resources are stored and reused")
    parser.add_argument("--offline", action="store_true", help="serve evidence only from --cache-dir; never go online")
    parser.add_argument("--no-fetch", action="store_true", help="skip evidence retrieval entirely (evidence checks are reported as SKIP)")
    parser.add_argument("--sample-size", type=int, default=200_000, help="samples drawn per distribution test")
    parser.add_argument("--seed", type=int, default=0, help="seed for distribution sampling")
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="override the reference date for date checks (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    parser.add_argument("-v", "--verbose", action="store_true", help="list passing checks as well as failures")
    return parser


def run(args: argparse.Namespace) -> int:
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    targets = args.paths or [DEFAULT_ENTRIES]
    if args.offline and args.cache_dir is None:
        print("--offline requires --cache-dir", file=sys.stderr)
        return 2

    fetcher = None if args.no_fetch else Fetcher(cache_dir=args.cache_dir, offline=args.offline)
    try:
        verifier = Verifier(schema, fetcher, today=args.today, sample_size=args.sample_size, seed=args.seed)
        reports = verifier.verify_all(iter_entry_files(targets))
    finally:
        if fetcher is not None:
            fetcher.close()

    print(render_json(reports) if args.json else render_text(reports, verbose=args.verbose))
    return 0 if reports and all(report.passed for report in reports) else 1


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

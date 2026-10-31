"""Top-level ``almanac`` command line interface."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from almanac import verify
from almanac.api import Almanac
from almanac.catalogue import render_card, render_catalogue, validity
from almanac.store import DEFAULT_ENTRIES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almanac", description="Misata Almanac tools")
    parser.add_argument("--entries", type=Path, default=DEFAULT_ENTRIES, help="root directory of entries")
    subcommands = parser.add_subparsers(dest="command", required=True)

    verify.build_parser(subcommands.add_parser("verify", help="validate entries and re-check their evidence"))

    subcommands.add_parser("list", help="list entry ids with kind, region and status")

    show = subcommands.add_parser("show", help="print the provenance card of one entry")
    show.add_argument("entry_id")

    applies = subcommands.add_parser("applies", help="list the entries whose validity covers a date")
    applies.add_argument("--on", type=date.fromisoformat, default=date.today(), help="date to ask about (YYYY-MM-DD)")
    applies.add_argument("--region")
    applies.add_argument("--domain")
    applies.add_argument("--kind", choices=["rule", "marginal", "temporal", "conditional"])
    applies.add_argument("--status", choices=["draft", "verified", "license-review"])

    catalogue = subcommands.add_parser("catalogue", help="render the catalogue table as Markdown")
    catalogue.add_argument("--write", type=Path, help="write to this file instead of standard output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        if not args.paths and args.entries != DEFAULT_ENTRIES:
            args.paths = [args.entries]
        return verify.run(args)

    almanac = Almanac.load(args.entries)
    if args.command == "list":
        for entry in almanac.select():
            print(f"{entry.id:<48} {entry.kind:<11} {entry.region:<6} {entry.tier}  {entry.status}")
        return 0
    if args.command == "show":
        if args.entry_id not in almanac:
            print(f"no entry with id {args.entry_id!r}", file=sys.stderr)
            return 2
        print(render_card(almanac.get(args.entry_id)))
        return 0
    if args.command == "applies":
        chosen = almanac.select(on=args.on, region=args.region, domain=args.domain, kind=args.kind, status=args.status)
        for entry in chosen:
            print(f"{entry.id:<48} {validity(entry)}")
        print(f"\n{len(chosen)} entries apply on {args.on}", file=sys.stderr)
        return 0
    if args.command == "catalogue":
        text = render_catalogue(almanac)
        if args.write:
            args.write.write_text(text, encoding="utf-8")
            print(f"wrote {args.write}")
        else:
            print(text, end="")
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main())

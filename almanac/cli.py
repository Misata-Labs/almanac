"""Top-level ``almanac`` command line interface."""

from __future__ import annotations

import argparse
import sys

from almanac import verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almanac", description="Misata Almanac tools")
    subcommands = parser.add_subparsers(dest="command", required=True)
    verify.build_parser(subcommands.add_parser("verify", help="validate entries and re-check their evidence"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        return verify.run(args)
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main())

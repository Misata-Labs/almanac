"""Build every Qatar, Kuwait, Bahrain and Oman statistics entry.

Each country has its own builder (build_gulf4_qa, build_gulf4_kw, build_gulf4_bh, build_gulf4_om),
runnable on its own; this script runs them in turn. Run from the repository root:

    uv run python tools/build_gulf4_stats.py [qa kw bh om]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_gulf4_bh  # noqa: E402
import build_gulf4_kw  # noqa: E402
import build_gulf4_om  # noqa: E402
import build_gulf4_qa  # noqa: E402

COUNTRIES = {"qa": build_gulf4_qa.build, "kw": build_gulf4_kw.build, "bh": build_gulf4_bh.build, "om": build_gulf4_om.build}


def main(selected: list[str]) -> None:
    for code in selected or list(COUNTRIES):
        COUNTRIES[code]()


if __name__ == "__main__":
    main([a.lower() for a in sys.argv[1:]])

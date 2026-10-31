"""Write tags and use cases from ``taxonomy.py`` into the entries that do not set their own.

Hand-written entries get the two keys appended after ``notes``; generated
entries are left to their builders. Run from the repository root:

    uv run python tools/apply_taxonomy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO_ROOT  # noqa: E402
from taxonomy import TAXONOMY  # noqa: E402


def main() -> int:
    for path in sorted((REPO_ROOT / "entries").rglob("*.yaml")):
        entry_id = path.stem
        if entry_id not in TAXONOMY:
            continue
        tags, use_cases = TAXONOMY[entry_id]
        text = path.read_text(encoding="utf-8")
        if "\ntags:" in text or text.startswith("tags:"):
            continue
        block = yaml.safe_dump({"tags": tags, "use_cases": use_cases}, sort_keys=False, default_flow_style=None, width=200)
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + block, encoding="utf-8")
        print(f"tagged {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

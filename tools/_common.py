"""Shared helpers for the entry builders: fetching, hashing, evidence items and writing."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ACCESSED = date(2026, 10, 31)


def fetch(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=120, headers={"User-Agent": "misata-almanac-builder/0.1"})
    response.raise_for_status()
    return response.content


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def evidence(publisher: str, title: str, url: str, locator: str, value, unit: str, snippet: str, license_id: str, raw: bytes, role: str = "primary") -> dict:
    return {
        "publisher": publisher,
        "title": title,
        "url": url,
        "accessed_at": ACCESSED.isoformat(),
        "locator": locator,
        "value": value,
        "unit": unit,
        "snippet": snippet,
        "source_license": license_id,
        "content_sha256": sha(raw),
        "role": role,
    }


def write(entry: dict) -> Path:
    path = REPO_ROOT / "entries" / entry["domain"] / entry["region"] / f"{entry['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return path

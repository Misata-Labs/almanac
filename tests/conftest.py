"""Shared fixtures: an in-memory evidence server and entry factories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from almanac.fetch import Fetcher

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def schema() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "schema" / "entry.schema.json").read_text(encoding="utf-8"))


class FakeWeb:
    """Serves fixed byte payloads for URLs so evidence checks run without a network."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[bytes, str]] = {}

    def add(self, url: str, body: str, content_type: str = "text/plain") -> str:
        payload = body.encode("utf-8")
        self.pages[url] = (payload, content_type)
        return hashlib.sha256(payload).hexdigest()

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            page = self.pages.get(str(request.url))
            if page is None:
                return httpx.Response(404)
            return httpx.Response(200, content=page[0], headers={"content-type": page[1]})

        return httpx.MockTransport(handler)

    def fetcher(self, **kwargs: Any) -> Fetcher:
        return Fetcher(transport=self.transport(), **kwargs)


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


def write_entry(root: Path, entry: dict[str, Any]) -> Path:
    path = root / "entries" / entry["domain"] / entry["region"] / f"{entry['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")
    return path


def evidence(url: str, sha: str, value: Any, snippet: str, **overrides: Any) -> dict[str, Any]:
    item = {
        "publisher": "Test Statistical Office",
        "title": "Test release",
        "url": url,
        "accessed_at": "2026-10-31",
        "locator": "table 1",
        "value": value,
        "unit": "text",
        "snippet": snippet,
        "source_license": "CC-BY-4.0",
        "content_sha256": sha,
    }
    item.update(overrides)
    return item

"""Retrieval of evidence resources with content hashing and optional caching.

Each evidence item records the SHA-256 of the resource it was taken from.
The fetcher returns the raw bytes, the digest, and the content type so the
verifier can confirm the resource is unchanged and still contains the
recorded value and snippet.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from pypdf import PdfReader

USER_AGENT = "misata-almanac-verify/0.1"
DEFAULT_TIMEOUT = 30.0


class FetchError(RuntimeError):
    """Raised when a resource cannot be retrieved."""


@dataclass(frozen=True)
class Resource:
    url: str
    content: bytes
    content_type: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def is_pdf(self) -> bool:
        return self.content.startswith(b"%PDF")

    @property
    def is_zip(self) -> bool:
        return self.content.startswith(b"PK\x03\x04")

    @property
    def text(self) -> str:
        """The resource as searchable text: extracted page text for a PDF, text members of a ZIP, decoded bytes otherwise."""
        if self.is_pdf:
            reader = PdfReader(io.BytesIO(self.content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if self.is_zip:
            return self._zip_text()
        return self.content.decode("utf-8", errors="replace")

    def _zip_text(self) -> str:
        """Text members of a ZIP archive (txt, csv, json, xml, yaml), each preceded by its name."""
        archive = zipfile.ZipFile(io.BytesIO(self.content))
        parts = []
        for info in archive.infolist():
            if info.filename.lower().endswith((".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".tsv")):
                parts.append(f"== {info.filename} ==\n" + archive.read(info).decode("utf-8", errors="replace"))
        return "\n".join(parts)

    @property
    def is_machine_readable(self) -> bool:
        """Whether the media type is data rather than a rendered document."""
        media = self.content_type.split(";")[0].strip().lower()
        return media not in {"text/html", "application/xhtml+xml", "application/pdf"}


class Fetcher:
    """Fetch resources over HTTPS, remembering each URL for the lifetime of the run.

    ``cache_dir`` enables an on-disk cache keyed by URL digest; ``offline``
    serves only from that cache and fails for anything missing from it.
    """

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        offline: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._memory: dict[str, Resource] = {}
        self._cache_dir = cache_dir
        self._offline = offline
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str) -> Resource:
        if url in self._memory:
            return self._memory[url]
        resource = self._from_disk(url)
        if resource is None:
            if self._offline:
                raise FetchError(f"{url} is not in the offline cache")
            resource = self._download(url)
            self._to_disk(resource)
        self._memory[url] = resource
        return resource

    def _download(self, url: str) -> Resource:
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {exc}") from exc
        if response.status_code != 200:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        return Resource(url=url, content=response.content, content_type=response.headers.get("content-type", ""))

    def _cache_paths(self, url: str) -> tuple[Path, Path] | None:
        if self._cache_dir is None:
            return None
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{key}.bin", self._cache_dir / f"{key}.json"

    def _from_disk(self, url: str) -> Resource | None:
        paths = self._cache_paths(url)
        if paths is None or not (paths[0].exists() and paths[1].exists()):
            return None
        meta = json.loads(paths[1].read_text(encoding="utf-8"))
        return Resource(url=url, content=paths[0].read_bytes(), content_type=meta.get("content_type", ""))

    def _to_disk(self, resource: Resource) -> None:
        paths = self._cache_paths(resource.url)
        if paths is None:
            return
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        paths[0].write_bytes(resource.content)
        paths[1].write_text(json.dumps({"url": resource.url, "content_type": resource.content_type}), encoding="utf-8")

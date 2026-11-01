"""Helpers for builders that read GOV.UK content API items and other text resources.

A ``Source`` wraps one fetched resource and produces evidence items only for
snippets and values it actually contains, so a builder fails at build time
rather than leaving an entry the verifier would reject. ``html_tables`` turns
the HTML bodies GOV.UK embeds in its JSON into plain cell text so values are
read from the published tables instead of being typed by hand.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from _common import evidence, fetch

GOVUK_API = "https://www.gov.uk/api/content"
OGL = "OGL-UK-3.0"
MAX_SNIPPET_WORDS = 24

_TABLE = re.compile(r"<table.*?</table>", re.S)
_ROW = re.compile(r"<tr.*?</tr>", re.S)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def collapse(text: str) -> str:
    return " ".join(text.split())


def scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(frozen=True)
class Source:
    publisher: str
    title: str
    url: str
    raw: bytes
    license_id: str = OGL

    @property
    def text(self) -> str:
        return collapse(self.raw.decode("utf-8", errors="replace"))

    def contains(self, needle: str) -> bool:
        return collapse(needle) in self.text

    def cite(self, locator: str, value: Any, unit: str, snippet: str, role: str = "primary") -> dict:
        """Evidence item for this source; raises when the snippet or value is not in the fetched bytes."""
        if len(snippet.split()) > MAX_SNIPPET_WORDS:
            raise ValueError(f"snippet exceeds {MAX_SNIPPET_WORDS} words: {snippet!r}")
        for needle, what in ((snippet, "snippet"), (scalar_text(value), "value")):
            if not self.contains(needle):
                raise ValueError(f"{what} {needle!r} not found in {self.url}")
        return evidence(self.publisher, self.title, self.url, locator, value, unit, snippet, self.license_id, self.raw, role)


def govuk(path: str, publisher: str, title: str | None = None) -> Source:
    """Fetch a GOV.UK content item through the content API, which is stable between editorial updates."""
    url = f"{GOVUK_API}/{path}"
    return Source(f"{publisher} (GOV.UK)", title or f"GOV.UK content API item for /{path} (JSON)", url, fetch(url))


def content_item(source: Source) -> dict:
    return json.loads(source.raw)


def body_html(source: Source) -> str:
    """Every HTML body of a content item: the main body plus each part of a guide."""
    details = content_item(source).get("details", {})
    parts = [details.get("body", "")] + [part.get("body", "") for part in details.get("parts", [])]
    return "\n".join(parts)


def cell_text(fragment: str) -> str:
    return collapse(html.unescape(_TAG.sub(" ", fragment.replace("<br>", " "))))


def html_tables(markup: str) -> list[list[list[str]]]:
    """All tables in ``markup`` as rows of plain cell text."""
    return [[[cell_text(c) for c in _CELL.findall(row)] for row in _ROW.findall(table)] for table in _TABLE.findall(markup)]


def find_table(tables: list[list[list[str]]], *header_fragments: str) -> list[list[str]]:
    """The first table whose header row contains every fragment."""
    for table in tables:
        header = " | ".join(table[0]) if table else ""
        if all(fragment in header for fragment in header_fragments):
            return table
    raise LookupError(f"no table with header containing {header_fragments}")


def table_after(markup: str, heading_fragment: str) -> list[list[str]]:
    """The first table that follows the first occurrence of ``heading_fragment`` in the markup."""
    position = markup.find(heading_fragment)
    if position < 0:
        raise LookupError(f"heading {heading_fragment!r} not found")
    tables = html_tables(markup[position:])
    if not tables:
        raise LookupError(f"no table after {heading_fragment!r}")
    return tables[0]


def number(text: str) -> float | int:
    """The first number in ``text`` with currency symbols, commas and percent signs removed."""
    match = _NUMBER.search(text)
    if match is None:
        raise ValueError(f"no number in {text!r}")
    value = Decimal(match.group().replace(",", ""))
    return int(value) if value == value.to_integral_value() else float(value)


def percent(text: str) -> float | int:
    """A percentage cell as a number; 'nil' and 'N/A' mean no contribution and read as 0."""
    if text.strip().lower() in {"nil", "n/a", "zero"}:
        return 0
    return number(text)

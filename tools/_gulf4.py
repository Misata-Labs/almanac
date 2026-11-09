"""Shared helpers for the Qatar, Kuwait, Bahrain and Oman statistics builders.

The four builders read Opendatasoft CSV exports (Qatar and Bahrain open data portals), PDF bulletins
(Oman's National Centre for Statistics and Information, the Central Bank of Kuwait) and HTML dashboards
(Kuwait's Labour Market Information System). This module holds what they share: a patient fetch for
hosts that drop connections, Opendatasoft export URLs pinned to one period with an explicit column
order and sort, and constructors for categorical distributions that keep the published counts beside
the derived shares.
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Iterable, Mapping
from urllib.parse import quote, urlencode

import httpx

from _common import fetch

SHARE_DIGITS = 8
SHARE_TOLERANCE = 0.005


def fetch_patiently(url: str, attempts: int = 12, pause: float = 6.0) -> bytes:
    """Fetch ``url``, retrying dropped connections and transient statuses; several Gulf hosts reset often."""
    failure: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(pause)
        try:
            return fetch(url)
        except httpx.TransportError as exc:
            failure = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (429, 500, 502, 503, 504):
                raise
            failure = exc
    raise RuntimeError(f"{url}: gave up after {attempts} attempts") from failure


def ods_export(portal: str, dataset: str, *, select: Iterable[str], where: str, order_by: Iterable[str]) -> str:
    """An Opendatasoft CSV export restricted to ``where``, with fixed column order and row order."""
    params = {
        "delimiter": ",",
        "select": ",".join(select),
        "where": where,
        "order_by": ",".join(order_by),
    }
    return f"{portal}/api/explore/v2.1/catalog/datasets/{dataset}/exports/csv?{urlencode(params, quote_via=quote)}"


def ods_licence_query(portal: str, dataset: str) -> str:
    """A catalogue query returning only the licence and publisher fields of one dataset (no timestamps or counters)."""
    params = {
        "select": "dataset_id,default.license,default.license_url,default.publisher",
        "where": f'dataset_id="{dataset}"',
    }
    return f"{portal}/api/explore/v2.1/catalog/datasets?{urlencode(params, quote_via=quote)}"


def csv_rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def csv_line(raw: bytes, *needles: str) -> str:
    """The first CSV line containing every needle, used to build snippets that exist verbatim in the export."""
    for line in raw.decode("utf-8-sig").splitlines():
        if all(n in line for n in needles):
            return line
    raise LookupError(f"no line contains {needles!r}")


def number(text: str) -> float | None:
    """Parse a published cell; blank cells are unpublished and return None."""
    text = text.strip().replace(",", "")
    return float(text) if text else None


def whole(value: float) -> int | float:
    """Counts exported as 123.0 are stored as integers; genuine fractions are kept."""
    return int(value) if float(value).is_integer() else value


def categorical(counts: Mapping[str, int | float], labels_ar: Mapping[str, str] | None = None) -> dict:
    """A categorical distribution whose shares are the published counts over their sum."""
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("a categorical distribution needs a positive total")
    parameters: dict = {
        "shares": {k: round(v / total, SHARE_DIGITS) for k, v in counts.items()},
        "counts": {k: whole(v) for k, v in counts.items()},
        "total": whole(total),
    }
    if labels_ar:
        parameters["labels_ar"] = {k: labels_ar[k] for k in counts if k in labels_ar}
    return {"family": "categorical", "parameters": parameters}


def share_tests(distributions: Mapping[str, dict], per_group: int = 2) -> list[dict]:
    """Share tests for the largest categories of each conditional group, plus a share-total check per group."""
    tests = []
    for given, dist in distributions.items():
        shares = dist["parameters"]["shares"]
        for category in sorted(shares, key=shares.get, reverse=True)[:per_group]:
            tests.append({"statistic": f'share["{given}","{category}"]', "expected": shares[category], "tolerance": SHARE_TOLERANCE})
        tests.append({"statistic": f'sum_of_shares["{given}"]', "expected": 1, "tolerance": 1e-6})
    return tests


def marginal_tests(dist: dict, top: int = 3) -> list[dict]:
    shares = dist["parameters"]["shares"]
    tests = [{"statistic": f'share["{c}"]', "expected": shares[c], "tolerance": SHARE_TOLERANCE} for c in sorted(shares, key=shares.get, reverse=True)[:top]]
    tests.append({"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-6})
    return tests


def shares_assumption(parameter: str, detail: str) -> dict:
    return {
        "parameter": parameter,
        "value": "count / sum of counts within each group",
        "method": "derived",
        "rationale": f"The publisher gives counts; shares are each count over the group total. {detail}".strip(),
    }

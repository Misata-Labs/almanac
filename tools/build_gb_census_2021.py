"""Regenerate the England and Wales Census 2021 distribution entries from the ONS API.

Two marginal entries are built: usual residents by sex and by single year of
age, both for England and Wales combined. Counts come from the census
observations endpoint; shares are derived from them. Run from the repository
root:

    uv run python tools/build_gb_census_2021.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
API = "https://api.beta.ons.gov.uk/v1"
SEX_URL = f"{API}/population-types/UR/census-observations?area-type=ctry&dimensions=sex"
AGE_URL = f"{API}/population-types/UR/census-observations?area-type=ctry&dimensions=resident_age_101a"
SEX_META_URL = f"{API}/datasets/TS008"
AGE_META_URL = f"{API}/datasets/TS007"
LICENSE_URL = f"{API}/datasets/mid-year-pop-est"
CENSUS_DAY = date(2021, 3, 21)
ACCESSED = date(2026, 10, 31)
PUBLISHER = "Office for National Statistics"
LICENSE = "OGL-UK-3.0"


def fetch(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=120)
    response.raise_for_status()
    return response.content


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def totals(raw: bytes, dimension_id: str) -> dict[str, int]:
    """Sum the observations over countries, keyed by the option id of ``dimension_id``."""
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for obs in json.loads(raw)["observations"]:
        option = next(d for d in obs["dimensions"] if d["dimension_id"] == dimension_id)
        counts[option["option_id"]] = counts.get(option["option_id"], 0) + int(obs["observation"])
        labels[option["option_id"]] = option["option"]
    return {labels[k]: v for k, v in counts.items()}


def item(url: str, title: str, locator: str, value, unit: str, snippet: str, raw: bytes, role: str = "primary") -> dict:
    return {
        "publisher": PUBLISHER,
        "title": title,
        "url": url,
        "accessed_at": ACCESSED.isoformat(),
        "locator": locator,
        "value": value,
        "unit": unit,
        "snippet": snippet,
        "source_license": LICENSE,
        "content_sha256": sha(raw),
        "role": role,
    }


def shares(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: round(v / total, 6) for k, v in counts.items()}


def build_sex(raw: bytes, meta_raw: bytes, terms_raw: bytes) -> dict:
    counts = totals(raw, "sex")
    share = shares(counts)
    england_female = next(o["observation"] for o in json.loads(raw)["observations"] if o["dimensions"][0]["option"] == "England" and o["dimensions"][1]["option"] == "Female")
    return {
        "id": "gb-census-2021-sex",
        "title": "England and Wales usual residents by sex, Census 2021",
        "kind": "marginal",
        "domain": "demographics",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": CENSUS_DAY.isoformat(), "end": CENSUS_DAY.isoformat()},
        "spec": {
            "variable": "sex",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": share, "counts": counts, "total": sum(counts.values())}},
        },
        "evidence": [
            item(SEX_URL, "Census 2021 observations: usual residents by sex, by country (ONS API)", 'observations[ctry=England, sex=Female].observation', england_female, "count", '"option":"Female","option_id":"1"}],"observation":', raw),
            item(SEX_META_URL, "ONS dataset metadata TS008 (Sex)", "description", "The estimates are as at Census Day, 21 March 2021.", "text", "classify usual residents in England and Wales by sex", meta_raw),
            item(LICENSE_URL, "ONS dataset metadata, Population Estimates (licence statement)", "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', terms_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "count / total over England and Wales",
                "method": "derived",
                "rationale": "The API publishes counts per country; England and Wales are summed and each share is the summed count divided by the total.",
            }
        ],
        "tests": [
            {"statistic": "share[Female]", "expected": share["Female"], "tolerance": 0.005},
            {"statistic": "share[Male]", "expected": share["Male"], "tolerance": 0.005},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-5},
        ],
        "notes": (
            "Census 2021 usual residents of England and Wales by sex, from the ONS census observations API "
            "(population type UR, area type country), summed over England and Wales. Counts are recorded under "
            "distribution.parameters.counts so the shares can be re-derived. The reference date is Census Day, "
            "21 March 2021. ONS publishes its datasets under the Open Government Licence v3.0, as the licence field "
            "of its dataset metadata states; the census observations endpoint itself carries no licence field."
        ),
    }


def build_age(raw: bytes, meta_raw: bytes, terms_raw: bytes) -> dict:
    counts = totals(raw, "resident_age_101a")
    share = shares(counts)
    obs = json.loads(raw)["observations"]
    england_under_1 = next(o["observation"] for o in obs if o["dimensions"][0]["option"] == "England" and o["dimensions"][1]["option_id"] == "0")
    under_1 = next(k for k in counts if k.startswith("Aged under 1"))
    oldest = max(counts, key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or 0))
    return {
        "id": "gb-census-2021-age",
        "title": "England and Wales usual residents by single year of age, Census 2021",
        "kind": "marginal",
        "domain": "demographics",
        "region": "GB",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": CENSUS_DAY.isoformat(), "end": CENSUS_DAY.isoformat()},
        "spec": {
            "variable": "age",
            "unit": "ratio",
            "distribution": {"family": "categorical", "parameters": {"shares": share, "counts": counts, "total": sum(counts.values())}},
        },
        "evidence": [
            item(AGE_URL, "Census 2021 observations: usual residents by age (101 categories), by country (ONS API)", 'observations[ctry=England, resident_age_101a=0].observation', england_under_1, "count", '"option":"Aged under 1 year","option_id":"0"}],"observation":', raw),
            item(AGE_META_URL, "ONS dataset metadata TS007 (Age by single year)", "description", "The estimates are as at Census Day, 21 March 2021.", "text", "classify usual residents in England and Wales by single year of age", meta_raw),
            item(LICENSE_URL, "ONS dataset metadata, Population Estimates (licence statement)", "license", "Open Government Licence v3.0", "text", '"license":"Open Government Licence v3.0"', terms_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "count / total over England and Wales",
                "method": "derived",
                "rationale": "The API publishes counts per country; England and Wales are summed and each share is the summed count divided by the total.",
            }
        ],
        "tests": [
            {"statistic": f"share[{under_1}]", "expected": share[under_1], "tolerance": 0.002},
            {"statistic": f"share[{oldest}]", "expected": share[oldest], "tolerance": 0.002},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-4},
        ],
        "notes": (
            "Census 2021 usual residents of England and Wales by single year of age (101 categories, the last being "
            "aged 100 and over), from the ONS census observations API summed over England and Wales. Categories keep "
            "the ONS labels; counts are recorded alongside the shares. Reference date is Census Day, 21 March 2021. "
            "ONS publishes its datasets under the Open Government Licence v3.0, as the licence field of its dataset "
            "metadata states; the census observations endpoint itself carries no licence field."
        ),
    }


def write(entry: dict) -> None:
    path = REPO_ROOT / "entries" / "demographics" / "GB" / f"{entry['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def main() -> int:
    terms = fetch(LICENSE_URL)
    write(build_sex(fetch(SEX_URL), fetch(SEX_META_URL), terms))
    write(build_age(fetch(AGE_URL), fetch(AGE_META_URL), terms))
    return 0


if __name__ == "__main__":
    sys.exit(main())

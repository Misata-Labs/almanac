"""Regenerate the Brazil Pix monthly volume entry from Banco Central do Brasil open data.

The monthly payment-instrument statistics service returns one row per month
with the number of Pix transactions (thousands) and the value settled
(BRL millions). The entry keeps both columns and derives the average ticket.
Run from the repository root:

    uv run python tools/build_br_pix_monthly.py
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
FIRST_MONTH = "202401"
DATA_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/MPV_DadosAbertos/versao/v1/odata/"
    f"MeiosdePagamentosMensalDA(AnoMes=@AnoMes)?@AnoMes='{FIRST_MONTH}'&$format=json"
)
DOC_URL = "https://olinda.bcb.gov.br/olinda/servico/MPV_DadosAbertos/versao/v1/aplicacao"
LICENSE_URL = "https://dadosabertos.bcb.gov.br/api/3/action/package_show?id=estatisticas-meios-pagamentos"
ACCESSED = date(2026, 10, 31)
PUBLISHER = "Banco Central do Brasil"
LICENSE = "ODbL-1.0"


def fetch(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=120)
    response.raise_for_status()
    return response.content


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def period(ano_mes: str) -> str:
    return f"{ano_mes[:4]}-{ano_mes[4:]}"


def build(data_raw: bytes, doc_raw: bytes, license_raw: bytes) -> dict:
    rows = sorted(json.loads(data_raw)["value"], key=lambda r: r["AnoMes"])
    series = []
    for row in rows:
        quantity_thousands = float(row["quantidadePix"])
        value_brl_millions = float(row["valorPix"])
        series.append(
            {
                "period": period(row["AnoMes"]),
                "value": round(value_brl_millions * 1_000_000 / (quantity_thousands * 1_000), 2),
                "quantity_thousands": quantity_thousands,
                "value_brl_millions": value_brl_millions,
            }
        )
    first, last = series[0], series[-1]
    last_year, last_month = int(last["period"][:4]), int(last["period"][5:])
    end = date(last_year + (last_month == 12), last_month % 12 + 1, 1).toordinal() - 1

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

    data_title = "Estatísticas de Meios de Pagamentos, MeiosdePagamentosMensalDA (Olinda open data API)"
    tests = [
        {"statistic": f"column[quantity_thousands,{last['period']}]", "expected": last["quantity_thousands"], "tolerance": 0},
        {"statistic": f"column[value_brl_millions,{last['period']}]", "expected": last["value_brl_millions"], "tolerance": 0},
        {"statistic": f"column[quantity_thousands,{first['period']}]", "expected": first["quantity_thousands"], "tolerance": 0},
        {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0.01},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    return {
        "id": "br-pix-monthly-volume-and-value",
        "title": f"Brazil Pix monthly transaction volume, value and average ticket, {first['period']} to {last['period']}",
        "kind": "temporal",
        "domain": "payments",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{first['period']}-01", "end": date.fromordinal(end).isoformat()},
        "spec": {
            "variable": "pix_average_ticket_brl",
            "unit": "currency:BRL",
            "frequency": "monthly",
            "columns": ["quantity_thousands", "value_brl_millions"],
            "series": series,
        },
        "evidence": [
            item(DATA_URL, data_title, f"value[AnoMes={last['period'].replace('-', '')}].quantidadePix", last["quantity_thousands"], "count", f'"AnoMes":"{last["period"].replace("-", "")}"', data_raw),
            item(DATA_URL, data_title, f"value[AnoMes={last['period'].replace('-', '')}].valorPix", last["value_brl_millions"], "currency:BRL", '"valorPix"', data_raw),
            item(DATA_URL, data_title, f"value[AnoMes={first['period'].replace('-', '')}].quantidadePix", first["quantity_thousands"], "count", f'"AnoMes":"{first["period"].replace("-", "")}"', data_raw),
            item(DOC_URL, "MPV_DadosAbertos service documentation (field descriptions)", "quantidadePix description", "Quantidade (em milhares) de transações Pix liquidadas mensalmente", "text", "Quantidade (em milhares) de transações Pix", doc_raw, role="supporting"),
            item(DOC_URL, "MPV_DadosAbertos service documentation (field descriptions)", "valorPix description", "Volume financeiro (R$ milhões) de transações Pix liquidadas mensalmente", "text", "Volume financeiro (R$ milhões) de transações Pix", doc_raw, role="supporting"),
            item(LICENSE_URL, "dadosabertos.bcb.gov.br package metadata for Estatísticas de Meios de Pagamentos", "result.license_id", "odc-odbl", "text", '"license_title": "Open Data Commons Open Database License (ODbL)"', license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "series[*].value (pix_average_ticket_brl)",
                "value": "value_brl_millions * 1e6 / (quantity_thousands * 1e3), rounded to cents",
                "method": "derived",
                "rationale": "The source publishes the monthly count (thousands) and the settled value (BRL millions); the average ticket is their quotient and is not itself published.",
            }
        ],
        "tests": tests,
        "notes": (
            "Monthly Pix transactions and settled value from the Banco Central do Brasil payment-instrument statistics "
            "(Olinda MPV_DadosAbertos service), covering settlements inside and outside the SPI including payment orders "
            "and returns. The query asks for every month from "
            f"{first['period']} onward; the service answered with {len(series)} months ending {last['period']}. The publisher "
            "warns that figures for transactions settled outside the SPI can be revised retroactively, so a later re-fetch "
            "may change the content hash; the figures recorded here are those served on the access date. The dataset is "
            "released under the Open Database License according to the BCB open data catalogue."
        ),
    }


def main() -> int:
    entry = build(fetch(DATA_URL), fetch(DOC_URL), fetch(LICENSE_URL))
    path = REPO_ROOT / "entries" / "payments" / "BR" / f"{entry['id']}.yaml"
    path.write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

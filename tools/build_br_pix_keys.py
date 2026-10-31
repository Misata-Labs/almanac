"""Regenerate the Brazil Pix key type entry from Banco Central do Brasil open data.

Run from the repository root:

    uv run python tools/build_br_pix_keys.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

SNAPSHOT = "2026-09-30"
DATA_URL = f"https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1/odata/ChavesPix(Data=@Data)?@Data='{SNAPSHOT}'&$format=json"
LICENSE_URL = "https://dadosabertos.bcb.gov.br/api/3/action/package_show?id=pix"
PUBLISHER = "Banco Central do Brasil"
LICENSE = "ODbL-1.0"
KEY_LABELS = {"Aleatória": "random_evp", "Celular": "phone", "CPF": "cpf", "e-mail": "email", "CNPJ": "cnpj"}


def build(raw: bytes, license_raw: bytes) -> dict:
    rows = json.loads(raw)["value"]
    counts: dict[str, int] = {}
    holders: dict[str, int] = {}
    for row in rows:
        counts[KEY_LABELS[row["TipoChave"]]] = counts.get(KEY_LABELS[row["TipoChave"]], 0) + int(row["qtdChaves"])
        holders[row["NaturezaUsuario"]] = holders.get(row["NaturezaUsuario"], 0) + int(row["qtdChaves"])
    counts = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    total = sum(counts.values())
    shares = {k: round(v / total, 6) for k, v in counts.items()}
    first = rows[0]
    return {
        "id": "br-pix-key-types",
        "title": f"Brazil Pix keys registered in the DICT by key type, snapshot {SNAPSHOT}",
        "kind": "marginal",
        "domain": "payments",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": SNAPSHOT, "end": SNAPSHOT},
        "spec": {
            "variable": "pix_key_type",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {"shares": shares, "counts": counts, "total": total, "holders": holders, "source_labels": {v: k for k, v in KEY_LABELS.items()}},
            },
        },
        "evidence": [
            evidence(PUBLISHER, f"Estatísticas do Pix, ChavesPix (keys by participant, holder type and key type), {SNAPSHOT}", DATA_URL, f'value[0] (ISPB {first["ISPB"]}, {first["TipoChave"]}).qtdChaves', first["qtdChaves"], "count", f'"ISPB":"{first["ISPB"]}"', LICENSE, raw),
            evidence(PUBLISHER, f"Estatísticas do Pix, ChavesPix (keys by participant, holder type and key type), {SNAPSHOT}", DATA_URL, "value[*].Data", SNAPSHOT, "date", f'"Data":"{SNAPSHOT}"', LICENSE, raw),
            evidence(PUBLISHER, "dadosabertos.bcb.gov.br package metadata for Estatísticas do Pix", LICENSE_URL, "result.license_id", "odc-odbl", "text", '"name": "pix"', LICENSE, license_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "sum of qtdChaves per key type / total keys",
                "method": "derived",
                "rationale": "The service publishes key counts per participant, holder type and key type; counts are summed per key type across all participants and both holder types. English category names map from the source labels recorded in source_labels.",
            }
        ],
        "tests": [
            {"statistic": "share[random_evp]", "expected": shares["random_evp"], "tolerance": 0.002},
            {"statistic": "share[cnpj]", "expected": shares["cnpj"], "tolerance": 0.001},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-5},
        ],
        "notes": (
            f"Pix keys registered in the DICT on {SNAPSHOT}, from the Banco Central do Brasil Pix statistics service, "
            "summed by key type: random keys (EVP), mobile phone numbers, CPF, e-mail and CNPJ. Holder totals by natural "
            "and legal person are kept under parameters.holders. Released under the Open Database License according to "
            "the BCB open data catalogue."
        ),
    }


def main() -> int:
    write(build(fetch(DATA_URL), fetch(LICENSE_URL)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

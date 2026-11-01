"""Regenerate the extended central bank entries from three machine-readable sources:

- Banco Central do Brasil: SGS time series (PTAX, lending rates, default and indebtedness) and the
  Olinda open data services for payment instruments by quarter and Pix transactions by municipality;
- European Central Bank Data Portal: key interest rate changes, the euro short-term rate, the daily
  USD/EUR reference rate, MFI interest rates, HICP by COICOP division and payment statistics;
- BIS Data Portal: effective exchange rates, US dollar exchange rates, residential property prices
  and credit to the private non-financial sector.

Run from the repository root:

    uv run python tools/build_centralbanks_extended.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, fetch, write  # noqa: E402

YEAR = 2025


def end_of_period(period: str) -> str:
    """Return the last calendar day of a daily, monthly, quarterly or annual period label."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
        return period
    if match := re.fullmatch(r"(\d{4})-Q([1-4])", period):
        year, quarter = int(match.group(1)), int(match.group(2))
        month = quarter * 3
        return date(year, month, monthrange(year, month)[1]).isoformat()
    if match := re.fullmatch(r"(\d{4})-(\d{2})", period):
        year, month = int(match.group(1)), int(match.group(2))
        return date(year, month, monthrange(year, month)[1]).isoformat()
    if re.fullmatch(r"\d{4}", period):
        return f"{period}-12-31"
    raise ValueError(f"unrecognised period label {period!r}")


def start_of_period(period: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
        return period
    if match := re.fullmatch(r"(\d{4})-Q([1-4])", period):
        return f"{match.group(1)}-{int(match.group(2)) * 3 - 2:02d}-01"
    if re.fullmatch(r"\d{4}-\d{2}", period):
        return f"{period}-01"
    if re.fullmatch(r"\d{4}", period):
        return f"{period}-01-01"
    raise ValueError(f"unrecognised period label {period!r}")


def raw_number(text: str, pattern: str) -> str:
    """Return the number exactly as the resource spells it, so evidence values match the bytes verbatim."""
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        raise ValueError(f"pattern {pattern!r} not found in resource")
    return match.group(1)


def slug(label: str) -> str:
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")


# --------------------------------------------------------------------------------------------------
# Banco Central do Brasil
# --------------------------------------------------------------------------------------------------

BCB = "Banco Central do Brasil"
BCB_LICENSE = "ODbL-1.0"
BCB_LICENSE_NOTE = (
    "The BCB open data catalogue (dadosabertos.bcb.gov.br) lists this series under the Open Database License; the "
    "catalogue API answers vary between requests, so that record is referenced here rather than hashed as evidence."
)
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
MPV_DOC_URL = f"{OLINDA}/MPV_DadosAbertos/versao/v1/aplicacao"
PIX_DOC_URL = f"{OLINDA}/Pix_DadosAbertos/versao/v1/aplicacao"


def sgs_url(code: int) -> str:
    return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/{YEAR}&dataFinal=31/12/{YEAR}"


def iso(dmy: str) -> str:
    return datetime.strptime(dmy, "%d/%m/%Y").date().isoformat()


class SgsSeries:
    """One SGS series for the year: its rows, raw bytes and the evidence items that point into them."""

    def __init__(self, code: int, name: str, unit: str, frequency: str) -> None:
        self.code, self.name, self.unit, self.frequency = code, name, unit, frequency
        self.url = sgs_url(code)
        self.raw = fetch(self.url)
        self.rows = json.loads(self.raw)

    def period(self, row: dict) -> str:
        day = iso(row["data"])
        return day if self.frequency == "daily" else day[:7]

    def points(self) -> dict[str, float]:
        return {self.period(r): float(r["valor"]) for r in self.rows}

    def item(self, row: dict) -> dict:
        title = f"SGS series {self.code}, {self.name} ({self.frequency}, JSON)"
        return evidence(BCB, title, self.url, f"data={row['data']}, valor", row["valor"], self.unit, f'{{"data":"{row["data"]}","valor":', BCB_LICENSE, self.raw)


def sgs_temporal(entry_id: str, title: str, domain: str, primary: SgsSeries, variable: str, tags: list[str], use_cases: list[str], note: str, columns: dict[str, SgsSeries] | None = None) -> dict:
    columns = columns or {}
    main = primary.points()
    extra = {name: s.points() for name, s in columns.items()}
    series = [{"period": p, "value": v, **{name: extra[name][p] for name in columns}} for p, v in main.items()]
    first, last = series[0], series[-1]
    items = [primary.item(primary.rows[0]), primary.item(primary.rows[-1])]
    items += [s.item(s.rows[-1]) for s in columns.values()]
    tests = [
        {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
        {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
        {"statistic": "count", "expected": len(series), "tolerance": 0},
    ]
    tests += [{"statistic": f"column[{name},{last['period']}]", "expected": last[name], "tolerance": 1e-9} for name in columns]
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": start_of_period(first["period"]), "end": end_of_period(last["period"])},
        "tags": tags + ["bcb", "sgs"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": primary.unit, "frequency": primary.frequency, "columns": list(columns), "series": series},
        "evidence": items,
        "assumed": [],
        "tests": tests,
        "notes": note + " " + BCB_LICENSE_NOTE,
    }


def bcb_sgs_entries() -> list[dict]:
    ptax = SgsSeries(1, "Taxa de câmbio - Livre - Dólar americano (venda) - diário", "currency:BRL", "daily")
    personal = SgsSeries(20742, "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Crédito pessoal não consignado", "percent", "monthly")
    payroll = SgsSeries(20747, "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Crédito pessoal consignado total", "percent", "monthly")
    overdraft = SgsSeries(20741, "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cheque especial", "percent", "monthly")
    revolving = SgsSeries(22022, "Taxa média de juros das operações de crédito com recursos livres - Pessoas físicas - Cartão de crédito rotativo", "percent", "monthly")
    corporate_default = SgsSeries(21083, "Inadimplência da carteira de crédito - Pessoas jurídicas - Total", "percent", "monthly")
    indebtedness = SgsSeries(29037, "Endividamento das famílias com o Sistema Financeiro Nacional em relação à renda acumulada dos últimos doze meses (RNDBF)", "percent", "monthly")
    return [
        sgs_temporal(
            f"br-usd-brl-ptax-sell-rate-daily-{YEAR}", f"Brazil PTAX US dollar sell rate (BRL per USD), daily {YEAR}", "currency", ptax, "brl_per_usd",
            ["exchange-rates", "fx", "ptax", "usd-brl", "time-series"], ["multi-currency-ledger", "financial-reporting", "treasury"],
            f"Daily PTAX closing sell rate of the US dollar in Brazilian reais for every business day of {YEAR}, from SGS series 1 (free-market exchange rate, sale). The series carries one observation per business day, so weekends and holidays are absent.",
        ),
        sgs_temporal(
            f"br-personal-loan-interest-rates-monthly-{YEAR}", f"Brazil average interest rates on personal loans to individuals, monthly {YEAR} (non-payroll and payroll-deducted)", "rates", personal, "non_payroll_personal_loan_percent",
            ["lending-rates", "personal-loans", "consumer-credit"], ["loan-pricing", "banking-demo", "personal-finance"],
            f"Average interest rate (percent per year) on new non-earmarked personal loans to individuals without payroll deduction (crédito pessoal não consignado, SGS 20742) for each month of {YEAR}; the payroll-deducted personal loan rate (crédito pessoal consignado total, SGS 20747) rides along as a column.",
            columns={"payroll_deducted_personal_loan_percent": payroll},
        ),
        sgs_temporal(
            f"br-overdraft-interest-rate-monthly-{YEAR}", f"Brazil average interest rate on overdrafts for individuals (cheque especial), monthly {YEAR}", "rates", overdraft, "overdraft_rate_percent",
            ["lending-rates", "overdraft", "consumer-credit"], ["banking-demo", "loan-pricing", "personal-finance"],
            f"Average interest rate (percent per year) on non-earmarked overdraft credit to individuals (cheque especial) for each month of {YEAR}, from SGS series 20741 of the BCB credit statistics.",
        ),
        sgs_temporal(
            f"br-credit-card-revolving-interest-rate-monthly-{YEAR}", f"Brazil average interest rate on revolving credit card credit for individuals, monthly {YEAR}", "rates", revolving, "revolving_card_rate_percent",
            ["lending-rates", "credit-card", "revolving-credit"], ["banking-demo", "loan-pricing", "fintech-demo"],
            f"Average interest rate (percent per year) on revolving credit card balances of individuals (cartão de crédito rotativo) for each month of {YEAR}, from SGS series 22022 of the BCB credit statistics.",
        ),
        sgs_temporal(
            f"br-corporate-credit-default-rate-{YEAR}", f"Brazil credit portfolio default rate, companies, monthly {YEAR}", "economy", corporate_default, "default_rate_percent",
            ["credit-risk", "default", "corporate-credit"], ["credit-risk", "banking-demo", "collections"],
            f"Share of the credit portfolio of legal entities (pessoas jurídicas) in arrears, monthly for {YEAR}, from SGS series 21083 of the BCB credit statistics; the companion series for individuals is entry br-household-credit-default-rate-{YEAR}.",
        ),
        sgs_temporal(
            f"br-household-indebtedness-ratio-monthly-{YEAR}", f"Brazil household debt with the financial system as a share of twelve-month income, monthly {YEAR}", "economy", indebtedness, "household_debt_to_income_percent",
            ["household-debt", "indebtedness", "credit-risk"], ["credit-risk", "personal-finance", "household-generation"],
            f"Household debt with the National Financial System as a percentage of gross disposable household income accumulated over the previous twelve months, monthly for {YEAR}, from SGS series 29037.",
        ),
    ]


QUARTERLY_URL = f"{OLINDA}/MPV_DadosAbertos/versao/v1/odata/MeiosdePagamentosTrimestralDA(trimestre=@trimestre)?@trimestre='{YEAR}1'&$format=json"
INSTRUMENT_FIELDS = {
    "Pix": "pix",
    "TED": "ted",
    "TEC": "tec",
    "Cheque": "cheque",
    "Boleto": "boleto",
    "DOC": "doc",
    "CartaoCredito": "credit_card",
    "CartaoDebito": "debit_card",
    "CartaoPrePago": "prepaid_card",
    "TransIntrabancaria": "intrabank_transfer",
    "Convenios": "utility_and_tax_collection",
    "DebitoDireto": "direct_debit",
    "Saques": "atm_withdrawal",
}


def quarter_label(end_date: str) -> str:
    month = int(end_date[5:7])
    return f"{end_date[:4]}-Q{(month + 2) // 3}"


def bcb_payment_instrument_entries() -> list[dict]:
    raw = fetch(QUARTERLY_URL)
    text = raw.decode("utf-8")
    doc_raw = fetch(MPV_DOC_URL)
    rows = sorted(json.loads(raw)["value"], key=lambda r: r["datatrimestre"])
    data_title = "Estatísticas de Meios de Pagamentos, MeiosdePagamentosTrimestralDA (Olinda open data API)"
    columns = [f"{name}_thousands" for field, name in INSTRUMENT_FIELDS.items() if field != "Pix"]
    series = []
    for row in rows:
        point = {"period": quarter_label(row["datatrimestre"]), "value": float(row["quantidadePix"])}
        for field, name in INSTRUMENT_FIELDS.items():
            if field != "Pix":
                point[f"{name}_thousands"] = float(row[f"quantidade{field}"])
        series.append(point)
    first, last = series[0], series[-1]

    def quantity(row: dict, field: str) -> str:
        return raw_number(text, rf'"datatrimestre":"{row["datatrimestre"]}".*?"quantidade{field}":([0-9.]+)')

    def item(locator: str, value, unit: str, snippet: str) -> dict:
        return evidence(BCB, data_title, QUARTERLY_URL, locator, value, unit, snippet, BCB_LICENSE, raw)

    def doc_item(field: str, description: str, snippet: str) -> dict:
        return evidence(BCB, "MPV_DadosAbertos service documentation (field descriptions)", MPV_DOC_URL, f"MeiosdePagamentosTrimestralDA, {field} description", description, "text", snippet, BCB_LICENSE, doc_raw, role="supporting")

    quarterly = {
        "id": "br-payment-instruments-quarterly-volumes",
        "title": f"Brazil payment transactions by instrument, quarterly counts {first['period']} to {last['period']}",
        "kind": "temporal",
        "domain": "payments",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": start_of_period(first["period"]), "end": end_of_period(last["period"])},
        "tags": ["payments", "payment-instruments", "pix", "cards", "boleto", "bcb", "time-series"],
        "use_cases": ["payments-demo", "fintech-demo", "market-sizing"],
        "spec": {"variable": "pix_thousands", "unit": "count", "frequency": "quarterly", "columns": columns, "series": series},
        "evidence": [
            item(f"value[datatrimestre={rows[0]['datatrimestre']}].quantidadePix", quantity(rows[0], "Pix"), "count", f'"datatrimestre":"{rows[0]["datatrimestre"]}"'),
            item(f"value[datatrimestre={rows[-1]['datatrimestre']}].quantidadePix", quantity(rows[-1], "Pix"), "count", f'"datatrimestre":"{rows[-1]["datatrimestre"]}"'),
            item(f"value[datatrimestre={rows[-1]['datatrimestre']}].quantidadeCartaoCredito", quantity(rows[-1], "CartaoCredito"), "count", '"quantidadeCartaoCredito"'),
            doc_item("quantidadePix", "Quantidade (em milhares) de transações Pix liquidadas trimestralmente no SPI e fora do SPI", "de transações Pix liquidadas trimestralmente"),
            doc_item("quantidadeCartaoCredito", "Quantidade (em milhares) de transações realizadas com cartão de crédito trimestralmente", "transações realizadas com cartão de crédito trimestralmente"),
        ],
        "assumed": [
            {
                "parameter": "series[*].period",
                "value": "calendar quarter containing the published quarter-end date (datatrimestre)",
                "method": "derived",
                "rationale": "The service labels each row with the last day of the quarter; the entry relabels it as YYYY-Qn so the period reads as a quarter.",
            }
        ],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 0},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 0},
            {"statistic": f"column[credit_card_thousands,{last['period']}]", "expected": last["credit_card_thousands"], "tolerance": 0},
            {"statistic": f"column[boleto_thousands,{first['period']}]", "expected": first["boleto_thousands"], "tolerance": 0},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Quarterly counts of transactions (thousands) by payment instrument from the Banco Central do Brasil "
            "payment-instrument statistics (Olinda MPV_DadosAbertos service, quarterly table): Pix as the primary series "
            "with TED, TEC, cheques, boletos, DOC, credit, debit and prepaid cards, intrabank transfers, utility and tax "
            f"collection agreements (convênios), direct debits and ATM withdrawals as columns. The query asks for every quarter from {YEAR} Q1 "
            f"onward; the service answered with {len(series)} quarters ending {last['period']}. The publisher warns that figures for "
            "Pix transactions settled outside the SPI can be revised, so a later re-fetch may change the content hash. "
            + BCB_LICENSE_NOTE
        ),
    }

    year_rows = [r for r in rows if r["datatrimestre"].startswith(str(YEAR))]
    counts = {name: round(sum(float(r[f"quantidade{field}"]) for r in year_rows), 2) for field, name in INSTRUMENT_FIELDS.items() if field != "Saques"}
    counts = {name: count for name, count in counts.items() if count > 0}
    total = round(sum(counts.values()), 2)
    shares = {name: round(count / total, 6) for name, count in counts.items()}
    ranked = sorted(shares, key=shares.get, reverse=True)
    mix = {
        "id": f"br-payment-instrument-mix-by-count-{YEAR}",
        "title": f"Brazil payment transactions by instrument, share of transaction count, {YEAR}",
        "kind": "marginal",
        "domain": "payments",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": ["payments", "payment-instruments", "category-shares", "pix", "cards", "bcb"],
        "use_cases": ["payments-demo", "fintech-demo", "sales-generation"],
        "spec": {
            "variable": "payment_instrument",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {
                    "shares": shares,
                    "counts_thousands": counts,
                    "total_thousands": total,
                    "quarters": [quarter_label(r["datatrimestre"]) for r in year_rows],
                    "source_fields": {name: f"quantidade{field}" for field, name in INSTRUMENT_FIELDS.items() if name in counts},
                },
            },
        },
        "evidence": [
            item(f"value[datatrimestre={year_rows[0]['datatrimestre']}].quantidadePix", quantity(year_rows[0], "Pix"), "count", f'"datatrimestre":"{year_rows[0]["datatrimestre"]}"'),
            item(f"value[datatrimestre={year_rows[-1]['datatrimestre']}].quantidadeCartaoDebito", quantity(year_rows[-1], "CartaoDebito"), "count", f'"datatrimestre":"{year_rows[-1]["datatrimestre"]}"'),
            doc_item("quantidadePix", "Quantidade (em milhares) de transações Pix liquidadas trimestralmente no SPI e fora do SPI", "de transações Pix liquidadas trimestralmente"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": f"sum of the four {YEAR} quarterly counts per instrument / sum over instruments",
                "method": "derived",
                "rationale": "The service publishes quarterly counts per instrument; the shares are their quotient over the year. ATM withdrawals are left out because they are not payments, and instruments with a zero count for the year are left out so every category can be sampled.",
            }
        ],
        "tests": [
            {"statistic": f"share[{ranked[0]}]", "expected": shares[ranked[0]], "tolerance": 0.003},
            {"statistic": f"share[{ranked[1]}]", "expected": shares[ranked[1]], "tolerance": 0.003},
            {"statistic": f"share[{ranked[-1]}]", "expected": shares[ranked[-1]], "tolerance": 0.001},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-5},
        ],
        "notes": (
            f"Mix of payment instruments by number of transactions in Brazil over the four quarters of {YEAR}, derived from the "
            "quarterly payment-instrument statistics of the Banco Central do Brasil (Olinda MPV_DadosAbertos service). Counts are "
            "kept in thousands as published. " + BCB_LICENSE_NOTE
        ),
    }
    return [quarterly, mix]


PIX_MONTH = f"{YEAR}06"
PIX_STATE_URL = (
    f"{OLINDA}/Pix_DadosAbertos/versao/v1/odata/TransacoesPixPorMunicipio(DataBase=@DataBase)?@DataBase='{PIX_MONTH}'"
    f"&$filter=AnoMes%20eq%20{PIX_MONTH}&$select=AnoMes,Municipio_Ibge,Municipio,Estado,Sigla_Regiao,Regiao,VL_PagadorPF,QT_PagadorPF,VL_PagadorPJ,QT_PagadorPJ&$format=json"
)


def bcb_pix_by_state_entry() -> dict:
    raw = fetch(PIX_STATE_URL)
    doc_raw = fetch(PIX_DOC_URL)
    rows = json.loads(raw)["value"]
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    regions: dict[str, str] = {}
    for row in rows:
        key = slug(row["Estado"])
        counts[key] = counts.get(key, 0) + int(row["QT_PagadorPF"]) + int(row["QT_PagadorPJ"])
        labels[key] = row["Estado"]
        regions[key] = row["Regiao"]
    total = sum(counts.values())
    shares = {k: round(v / total, 6) for k, v in counts.items()}
    ranked = sorted(shares, key=shares.get, reverse=True)
    sample = rows[0]
    data_title = f"Estatísticas do Pix, TransacoesPixPorMunicipio (Pix transactions by municipality), {YEAR}-06"

    def item(locator: str, value, unit: str, snippet: str) -> dict:
        return evidence(BCB, data_title, PIX_STATE_URL, locator, value, unit, snippet, BCB_LICENSE, raw)

    period_start = f"{YEAR}-06-01"
    period_end = end_of_period(f"{YEAR}-06")
    return {
        "id": f"br-pix-transactions-by-state-{YEAR}-06",
        "title": f"Brazil Pix transactions by payer state, share of transaction count, June {YEAR}",
        "kind": "marginal",
        "domain": "payments",
        "region": "BR",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": period_start, "end": period_end},
        "tags": ["pix", "geography", "states", "category-shares", "bcb"],
        "use_cases": ["payments-demo", "fintech-demo", "address-generation", "customer-segmentation"],
        "spec": {
            "variable": "payer_state",
            "unit": "ratio",
            "distribution": {
                "family": "categorical",
                "parameters": {
                    "shares": shares,
                    "counts": counts,
                    "total": total,
                    "source_labels": labels,
                    "regions": regions,
                },
            },
        },
        "evidence": [
            item(f"value[0] (Municipio {sample['Municipio']}, {sample['Estado']}).QT_PagadorPF", int(sample["QT_PagadorPF"]), "count", f'"Municipio":"{sample["Municipio"]}"'),
            item(f"value[0] (Municipio {sample['Municipio']}, {sample['Estado']}).QT_PagadorPJ", int(sample["QT_PagadorPJ"]), "count", f'"Estado":"{sample["Estado"]}"'),
            item("value[*].AnoMes", int(PIX_MONTH), "integer", f'"AnoMes":{PIX_MONTH}'),
            evidence(BCB, "Pix_DadosAbertos service documentation (field descriptions)", PIX_DOC_URL, "TransacoesPixPorMunicipio, QT_PagadorPF description", "Quantidade de transações cujo Pagador é uma pessoa física (PF)", "text", "Quantidade de transações cujo Pagador é uma pessoa física", BCB_LICENSE, doc_raw, role="supporting"),
        ],
        "assumed": [
            {
                "parameter": "distribution.parameters.shares",
                "value": "sum over municipalities of QT_PagadorPF + QT_PagadorPJ per state / total",
                "method": "derived",
                "rationale": "The service publishes transaction counts per municipality split by payer type; counts are summed per state (payer side, natural and legal persons together). Rows the publisher could not assign to a municipality are kept as the category nao_informado.",
            }
        ],
        "tests": [
            {"statistic": f"share[{ranked[0]}]", "expected": shares[ranked[0]], "tolerance": 0.003},
            {"statistic": f"share[{ranked[1]}]", "expected": shares[ranked[1]], "tolerance": 0.003},
            {"statistic": f"share[{ranked[-1]}]", "expected": shares[ranked[-1]], "tolerance": 0.001},
            {"statistic": "sum_of_shares", "expected": 1, "tolerance": 1e-5},
        ],
        "notes": (
            f"Share of Pix transactions by the payer's state in June {YEAR}, derived from the Banco Central do Brasil Pix statistics "
            f"service table of transactions by municipality ({len(rows)} rows, one month selected with an OData filter and the "
            "payer-side columns projected). Keys are ASCII slugs of the state names; the published spelling and region sit under "
            "source_labels and regions. " + BCB_LICENSE_NOTE
        ),
    }


# --------------------------------------------------------------------------------------------------
# European Central Bank
# --------------------------------------------------------------------------------------------------

ECB_API = "https://data-api.ecb.europa.eu/service/data"
ECB = "European Central Bank"
ECB_LICENSE = "ECB-free-use-with-attribution"
ECB_LICENSE_NOTE = (
    "The ECB's website disclaimer states that users may make free use of information obtained from it provided it is "
    "reproduced accurately and the ECB is cited as the source; the page renders dynamically, so the clause is carried by "
    "the licence identifier ECB-free-use-with-attribution documented in CONTRIBUTING.md."
)


def ecb_url(flow: str, key: str, start: str, end: str) -> str:
    return f"{ECB_API}/{flow}/{key}?startPeriod={start}&endPeriod={end}&format=csvdata"


def csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def csv_line(raw: bytes, marker: str, tail: str) -> str:
    """Return the start of the CSV line that holds ``marker`` and ends its observation with ``tail``, as a snippet."""
    for line in raw.decode("utf-8").splitlines():
        if marker in line and tail in line:
            return line[: line.index(tail) + len(tail)]
    raise ValueError(f"no CSV line with {marker!r} and {tail!r}")


def ecb_item(title: str, url: str, raw: bytes, locator: str, value, unit: str, snippet: str) -> dict:
    return evidence(ECB, title, url, locator, value, unit, snippet, ECB_LICENSE, raw)


def ecb_temporal(entry_id: str, title: str, domain: str, flow: str, key: str, frequency: str, variable: str, unit: str, tags: list[str], use_cases: list[str], note: str) -> dict:
    start, end = (f"{YEAR}-01-01", f"{YEAR}-12-31") if frequency == "daily" else (f"{YEAR}-01", f"{YEAR}-12")
    url = ecb_url(flow, key, start, end)
    raw = fetch(url)
    rows = csv_rows(raw)
    series = [{"period": r["TIME_PERIOD"], "value": float(r["OBS_VALUE"])} for r in rows]
    first, last = series[0], series[-1]
    full_key = rows[0]["KEY"]
    source_title = f"ECB Data Portal, series {full_key} (SDMX CSV)"
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": tags + ["ecb", "euro-area"],
        "use_cases": use_cases,
        "spec": {"variable": variable, "unit": unit, "frequency": frequency, "columns": [], "series": series},
        "evidence": [
            ecb_item(source_title, url, raw, f"TIME_PERIOD={first['period']}, OBS_VALUE", rows[0]["OBS_VALUE"], unit, f"{full_key},"),
            ecb_item(source_title, url, raw, f"TIME_PERIOD={last['period']}, OBS_VALUE", rows[-1]["OBS_VALUE"], unit, f",{last['period']},{rows[-1]['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, "TITLE_COMPL", rows[0]["TITLE_COMPL"][:90], "text", rows[0]["TITLE"]),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " " + ECB_LICENSE_NOTE,
    }


def ecb_step_schedule(entry_id: str, title: str, key: str, instrument: str, note: str) -> dict:
    url = ecb_url("FM", key, f"{YEAR}-01-01", f"{YEAR}-12-31")
    raw = fetch(url)
    rows = csv_rows(raw)
    steps = [{"from": r["TIME_PERIOD"], "value": float(r["OBS_VALUE"])} for r in rows]
    full_key = rows[0]["KEY"]
    source_title = f"ECB Data Portal, series {full_key} ({instrument}, date of changes)"
    return {
        "id": entry_id,
        "title": title,
        "kind": "rule",
        "domain": "rates",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "valid_from": steps[0]["from"],
        "valid_to": None,
        "tags": ["ecb", "euro-area", "policy-rate", "step-schedule"],
        "use_cases": ["banking-demo", "treasury", "loan-pricing"],
        "spec": {
            "implementation": "almanac.rules.step_schedule",
            "parameters": {"series": full_key, "unit": "percent", "steps": steps},
            "vectors": [
                {"input": {"on": steps[0]["from"]}, "expected": steps[0]["value"], "origin": "source"},
                {"input": {"on": steps[-1]["from"]}, "expected": steps[-1]["value"], "origin": "source"},
                {"input": {"on": f"{YEAR}-12-31"}, "expected": steps[-1]["value"], "origin": "derived", "note": "last change still in force at year end"},
            ],
        },
        "evidence": [
            ecb_item(source_title, url, raw, f"TIME_PERIOD={steps[0]['from']}, OBS_VALUE", rows[0]["OBS_VALUE"], "percent", f"{full_key},"),
            ecb_item(source_title, url, raw, f"TIME_PERIOD={steps[-1]['from']}, OBS_VALUE", rows[-1]["OBS_VALUE"], "percent", f",{rows[-1]['TIME_PERIOD']},{rows[-1]['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, "TITLE", rows[0]["TITLE"], "text", rows[0]["TITLE"]),
        ],
        "assumed": [],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(steps), "tolerance": 0},
            {"statistic": f"value[{YEAR}-12-31]", "expected": steps[-1]["value"], "tolerance": 1e-9},
        ],
        "notes": note + " " + ECB_LICENSE_NOTE,
    }


COICOP_DIVISIONS = {
    "010000": "food_non_alcoholic_beverages",
    "020000": "alcohol_tobacco",
    "030000": "clothing_footwear",
    "040000": "housing_water_energy",
    "050000": "furnishings_household_equipment",
    "060000": "health",
    "070000": "transport",
    "080000": "communication",
    "090000": "recreation_culture",
    "100000": "education",
    "110000": "restaurants_hotels",
    "120000": "miscellaneous_goods_services",
}


def ecb_hicp_divisions_entry() -> dict:
    items = "+".join(["000000", *COICOP_DIVISIONS])
    url = ecb_url("ICP", f"M.U2.N.{items}.4.ANR", f"{YEAR}-01", f"{YEAR}-12")
    raw = fetch(url)
    rows = csv_rows(raw)
    by_period: dict[str, dict[str, float]] = {}
    titles: dict[str, str] = {}
    for r in rows:
        by_period.setdefault(r["TIME_PERIOD"], {})[r["ICP_ITEM"]] = float(r["OBS_VALUE"])
        titles[r["ICP_ITEM"]] = r["TITLE"]
    columns = [f"{name}_percent" for name in COICOP_DIVISIONS.values()]
    series = []
    for period in sorted(by_period):
        point = {"period": period, "value": by_period[period]["000000"]}
        for code, name in COICOP_DIVISIONS.items():
            point[f"{name}_percent"] = by_period[period][code]
        series.append(point)
    first, last = series[0], series[-1]
    overall_first = next(r for r in rows if r["ICP_ITEM"] == "000000" and r["TIME_PERIOD"] == first["period"])
    food_last = next(r for r in rows if r["ICP_ITEM"] == "010000" and r["TIME_PERIOD"] == last["period"])
    source_title = "ECB Data Portal, dataset ICP, HICP annual rate of change by COICOP division (SDMX CSV)"
    division_list = "; ".join(f"{code} {titles[code].removeprefix('HICP - ')} as {name}_percent" for code, name in COICOP_DIVISIONS.items())
    return {
        "id": f"eu-hicp-inflation-by-coicop-division-monthly-{YEAR}",
        "title": f"Euro area HICP inflation by COICOP division, annual rate of change by month, {YEAR}",
        "kind": "temporal",
        "domain": "economy",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": f"{YEAR}-01-01", "end": f"{YEAR}-12-31"},
        "tags": ["inflation", "prices", "coicop", "ecb", "euro-area"],
        "use_cases": ["pricing", "retail-demo", "financial-planning"],
        "spec": {"variable": "hicp_all_items_annual_rate_percent", "unit": "percent", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            ecb_item(source_title, url, raw, f"KEY=ICP.M.U2.N.000000.4.ANR, TIME_PERIOD={first['period']}, OBS_VALUE", overall_first["OBS_VALUE"], "percent", f"ICP.M.U2.N.000000.4.ANR,M,U2,N,000000,4,ANR,{first['period']},{overall_first['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, f"KEY=ICP.M.U2.N.010000.4.ANR, TIME_PERIOD={last['period']}, OBS_VALUE", food_last["OBS_VALUE"], "percent", f"ICP.M.U2.N.010000.4.ANR,M,U2,N,010000,4,ANR,{last['period']},{food_last['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, "TITLE for ICP_ITEM 010000", titles["010000"], "text", titles["010000"]),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": f"column[food_non_alcoholic_beverages_percent,{last['period']}]", "expected": last["food_non_alcoholic_beverages_percent"], "tolerance": 1e-9},
            {"statistic": f"column[transport_percent,{first['period']}]", "expected": first["transport_percent"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            f"Euro area (changing composition) HICP annual rate of change, monthly for {YEAR}, for the overall index (primary series) "
            f"and the twelve COICOP divisions as columns: {division_list}. Source: ECB Data Portal dataset ICP, compiled by Eurostat. "
            + ECB_LICENSE_NOTE
        ),
    }


PSS_INSTRUMENTS = {"I01": None, "I1A": "card_payments_millions", "I31": "credit_transfers_millions", "I34": "direct_debits_millions", "I35": "cheques_millions", "IEM": "e_money_payments_millions"}


def ecb_payments_entry() -> dict:
    key = f"A.U2.F000.{'+'.join(PSS_INSTRUMENTS)}.Z00Z.NT.X0.20.Z0Z.Z"
    url = ecb_url("PSS", key, "2019", "2024")
    raw = fetch(url)
    rows = csv_rows(raw)
    by_period: dict[str, dict[str, float]] = {}
    titles: dict[str, str] = {}
    for r in rows:
        by_period.setdefault(r["TIME_PERIOD"], {})[r["PSS_INSTRUMENT"]] = float(r["OBS_VALUE"])
        titles[r["PSS_INSTRUMENT"]] = r["TITLE"]
    columns = [name for name in PSS_INSTRUMENTS.values() if name]
    series = []
    for period in sorted(by_period):
        point = {"period": period, "value": by_period[period]["I01"]}
        for code, name in PSS_INSTRUMENTS.items():
            if name:
                point[name] = by_period[period][code]
        series.append(point)
    first, last = series[0], series[-1]
    total_last = next(r for r in rows if r["PSS_INSTRUMENT"] == "I01" and r["TIME_PERIOD"] == last["period"])
    cards_last = next(r for r in rows if r["PSS_INSTRUMENT"] == "I1A" and r["TIME_PERIOD"] == last["period"])
    source_title = "ECB Data Portal, dataset PSS (payments statistics), number of transactions by instrument (SDMX CSV)"
    return {
        "id": f"eu-cashless-payments-by-instrument-annual-{first['period']}-{last['period']}",
        "title": f"Euro area cashless payment transactions by instrument, annual counts {first['period']} to {last['period']}",
        "kind": "temporal",
        "domain": "payments",
        "region": "EU",
        "status": "verified",
        "tier": "A",
        "observed_period": {"start": start_of_period(first["period"]), "end": end_of_period(last["period"])},
        "tags": ["payments", "payment-instruments", "cards", "credit-transfers", "direct-debits", "ecb", "euro-area"],
        "use_cases": ["payments-demo", "fintech-demo", "market-sizing"],
        "spec": {"variable": "total_payment_transactions_millions", "unit": "count", "frequency": "annual", "columns": columns, "series": series},
        "evidence": [
            ecb_item(source_title, url, raw, f"KEY={total_last['KEY']}, TIME_PERIOD={last['period']}, OBS_VALUE", total_last["OBS_VALUE"], "count", f"{total_last['KEY']},A,U2,F000,I01,Z00Z,NT,X0,20,Z0Z,Z,{last['period']},{total_last['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, f"KEY={cards_last['KEY']}, TIME_PERIOD={last['period']}, OBS_VALUE", cards_last["OBS_VALUE"], "count", f"{cards_last['KEY']},A,U2,F000,I1A,Z00Z,NT,X0,20,Z0Z,Z,{last['period']},{cards_last['OBS_VALUE']},"),
            ecb_item(source_title, url, raw, "TITLE for instrument I1A", titles["I1A"], "text", titles["I1A"]),
            ecb_item(source_title, url, raw, "UNIT_MULT for the I01 series", total_last["UNIT_MULT"], "integer", f",{total_last['UNIT']},{total_last['UNIT_MULT']}"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-6},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-6},
            {"statistic": f"column[card_payments_millions,{last['period']}]", "expected": last["card_payments_millions"], "tolerance": 1e-6},
            {"statistic": f"column[cheques_millions,{first['period']}]", "expected": first["cheques_millions"], "tolerance": 1e-6},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Annual number of payment transactions involving non-MFIs sent from the euro area (changing composition), in millions "
            "(UNIT_MULT 6 in the source), from the ECB payments statistics dataset PSS: all payment services as the primary series, "
            "with card payments by cards issued by resident PSPs, credit transfers, direct debits, cheques and e-money payment "
            f"transactions as columns. The query asked for 2019 to 2024; the portal served {len(series)} years ending {last['period']}, "
            "the last reference year compiled under the earlier payments statistics methodology. " + ECB_LICENSE_NOTE
        ),
    }


def ecb_entries() -> list[dict]:
    return [
        ecb_step_schedule(
            f"eu-ecb-main-refinancing-rate-changes-{YEAR}", f"ECB main refinancing operations rate (fixed rate tenders): changes decided in {YEAR}",
            "B.U2.EUR.4F.KR.MRR_FR.LEV", "main refinancing operations",
            f"Each change to the fixed rate of the ECB's main refinancing operations decided in {YEAR}, with the date from which the new level applied, from the ECB Data Portal's key-interest-rate series (dates of changes). The schedule starts at the first change of the year; the level in force before it is not part of this entry.",
        ),
        ecb_step_schedule(
            f"eu-ecb-marginal-lending-facility-rate-changes-{YEAR}", f"ECB marginal lending facility rate: changes decided in {YEAR}",
            "B.U2.EUR.4F.KR.MLFR.LEV", "marginal lending facility",
            f"Each change to the ECB marginal lending facility rate decided in {YEAR}, with the date from which the new level applied, from the ECB Data Portal's key-interest-rate series (dates of changes, raw data). The schedule starts at the first change of the year; the level in force before it is not part of this entry.",
        ),
        ecb_temporal(
            f"eu-estr-daily-{YEAR}", f"Euro short-term rate (€STR), daily {YEAR}", "rates", "EST", "B.EU000A2X2A25.WT", "daily", "estr_percent", "percent",
            ["money-market", "estr", "benchmark-rate", "time-series"], ["treasury", "banking-demo", "loan-pricing"],
            f"The euro short-term rate (€STR), volume-weighted trimmed mean of unsecured overnight borrowing by euro area banks, for every TARGET business day of {YEAR} as published by the ECB (dataset EST). The series dates each rate by the business day it refers to.",
        ),
        ecb_temporal(
            f"eu-usd-eur-reference-rate-daily-{YEAR}", f"ECB euro foreign exchange reference rate, US dollar per euro, daily {YEAR}", "currency", "EXR", "D.USD.EUR.SP00.A", "daily", "usd_per_eur", "ratio",
            ["exchange-rates", "fx", "eur-usd", "time-series"], ["multi-currency-ledger", "financial-reporting", "treasury"],
            f"Daily ECB euro foreign exchange reference rate for the US dollar (USD per EUR, fixed at 2.15 pm CET) for every TARGET business day of {YEAR}, from the ECB Data Portal dataset EXR. Monthly averages of this and six other currencies are in entry global-ecb-euro-fx-reference-rates-monthly-{YEAR}.",
        ),
        ecb_temporal(
            f"eu-cost-of-borrowing-corporations-monthly-{YEAR}", f"Euro area cost of borrowing for non-financial corporations, monthly {YEAR}", "rates", "MIR", "M.U2.B.A2I.AM.R.A.2240.EUR.N", "monthly", "corporate_borrowing_rate_percent", "percent",
            ["lending-rates", "corporate-loans"], ["loan-pricing", "banking-demo", "financial-planning"],
            f"Euro area cost-of-borrowing indicator for non-financial corporations (annualised agreed rate on new euro-denominated loans, volumes weighted with a moving average), monthly for {YEAR}, from the ECB MFI interest rate statistics.",
        ),
        ecb_temporal(
            f"eu-household-deposit-rate-agreed-maturity-monthly-{YEAR}", f"Euro area bank interest rate on household deposits with agreed maturity (new business), monthly {YEAR}", "rates", "MIR", "M.U2.B.L22.A.R.A.2250.EUR.N", "monthly", "household_deposit_rate_percent", "percent",
            ["deposit-rates", "savings"], ["banking-demo", "personal-finance", "financial-planning"],
            f"Annualised agreed rate on new euro-denominated deposits with agreed maturity from households and non-profit institutions serving households in the euro area, all original maturities, monthly for {YEAR}, from the ECB MFI interest rate statistics.",
        ),
        ecb_hicp_divisions_entry(),
        ecb_payments_entry(),
    ]


# --------------------------------------------------------------------------------------------------
# Bank for International Settlements
# --------------------------------------------------------------------------------------------------

BIS_API = "https://stats.bis.org/api/v2/data/dataflow/BIS"
BIS = "Bank for International Settlements"
BIS_LICENSE = "BIS terms and conditions (statistics subject to 'About BIS statistics' terms)"
BIS_TERMS_URL = "https://www.bis.org/terms_conditions.htm"
BIS_LICENSE_NOTE = (
    "The BIS general terms permit limited extracts with attribution but refer statistics to a separate 'About BIS "
    "statistics' notice that was not fetched, so the entry is held at license-review until those terms are confirmed."
)
BIS_AREAS = ["US", "XM", "GB", "JP", "BR", "IN", "CH", "CA", "AU"]


def bis_table(
    entry_id: str,
    title: str,
    domain: str,
    flow: str,
    version: str,
    key: str,
    frequency: str,
    unit: str,
    area_field: str,
    label_field: str,
    primary_label: str,
    suffix: str,
    title_field: str,
    tags: list[str],
    use_cases: list[str],
    note: str,
    terms_raw: bytes,
) -> dict:
    url = f"{BIS_API}/{flow}/{version}/{key}?startPeriod={YEAR}-01&endPeriod={YEAR}-12&format=csv"
    raw = fetch(url)
    rows = csv_rows(raw)
    by_period: dict[str, dict[str, float]] = {}
    for r in rows:
        by_period.setdefault(r["TIME_PERIOD"], {})[r[label_field].lower()] = float(r["OBS_VALUE"])
    periods = sorted(by_period)
    others = sorted(label for label in by_period[periods[0]] if label != primary_label)
    columns = [f"{label}_{suffix}" for label in others]
    series = []
    for period in periods:
        point = {"period": period, "value": by_period[period][primary_label]}
        for label in others:
            point[f"{label}_{suffix}"] = by_period[period][label]
        series.append(point)
    first, last = series[0], series[-1]
    primary_first = next(r for r in rows if r[label_field].lower() == primary_label and r["TIME_PERIOD"] == periods[0])
    source_title = f"BIS Data Portal, dataflow {flow} (SDMX CSV)"
    row_snippet = csv_line(raw, f",{primary_first[area_field]},", f",{periods[0]},{primary_first['OBS_VALUE']},")
    title_items = []
    if primary_first[title_field].strip():
        title_items.append(evidence(BIS, source_title, url, f"{title_field} for the {primary_first[label_field]} series", primary_first[title_field].strip(), "text", primary_first[title_field].strip(), BIS_LICENSE, raw))
    return {
        "id": entry_id,
        "title": title,
        "kind": "temporal",
        "domain": domain,
        "region": "global",
        "status": "license-review",
        "tier": "A",
        "observed_period": {"start": start_of_period(periods[0]), "end": end_of_period(periods[-1])},
        "tags": tags + ["bis", "time-series"],
        "use_cases": use_cases,
        "spec": {"variable": f"{primary_label}_{suffix}", "unit": unit, "frequency": frequency, "columns": columns, "series": series},
        "evidence": [
            evidence(BIS, source_title, url, f"{label_field}={primary_first[label_field]}, TIME_PERIOD={periods[0]}, OBS_VALUE", primary_first["OBS_VALUE"], unit, row_snippet, BIS_LICENSE, raw),
            *title_items,
            evidence(BIS, "BIS terms and conditions", BIS_TERMS_URL, "Copyright and permissions", "Users may use the statistics published in the BIS Data Portal in accordance with the terms set out under the heading", "text", "Users may use the statistics published in the BIS Data Portal", BIS_LICENSE, terms_raw, role="supporting"),
        ],
        "assumed": [],
        "tests": [
            {"statistic": f"value[{first['period']}]", "expected": first["value"], "tolerance": 1e-9},
            {"statistic": f"value[{last['period']}]", "expected": last["value"], "tolerance": 1e-9},
            {"statistic": f"column[{columns[0]},{last['period']}]", "expected": last[columns[0]], "tolerance": 1e-9},
            {"statistic": f"column[{columns[-1]},{first['period']}]", "expected": first[columns[-1]], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": note + " " + BIS_LICENSE_NOTE,
    }


def bis_entries() -> list[dict]:
    terms_raw = fetch(BIS_TERMS_URL)
    areas = "+".join(BIS_AREAS)
    xru_areas = "XM+GB+JP+BR+IN+CH+CA+AU+CN+MX"
    return [
        bis_table(
            f"global-nominal-effective-exchange-rates-monthly-{YEAR}", f"Nominal effective exchange rates, broad basket, monthly {YEAR} (US, euro area, GB, JP, BR, IN, CH, CA, AU)", "currency",
            "WS_EER", "1.0", f"M.N.B.{areas}", "monthly", "decimal", "REF_AREA", "REF_AREA", "us", "neer", "TITLE_TS",
            ["exchange-rates", "effective-exchange-rate", "fx"], ["treasury", "financial-reporting", "multi-currency-ledger"],
            f"Monthly averages of the BIS nominal effective exchange rate indices (broad basket of 64 economies, 2020 = 100) for {YEAR}, from the BIS Data Portal dataflow WS_EER, with the United States as the primary series and the euro area (XM), United Kingdom, Japan, Brazil, India, Switzerland, Canada and Australia as columns. A rise means the currency appreciated against its trading partners.",
            terms_raw,
        ),
        bis_table(
            f"global-usd-exchange-rates-monthly-{YEAR}", f"Exchange rates against the US dollar, monthly averages {YEAR} (EUR, GBP, JPY, BRL, INR, CHF, CAD, AUD, CNY, MXN per USD)", "currency",
            "WS_XRU", "1.0", f"M.{xru_areas}.*.A", "monthly", "ratio", "REF_AREA", "CURRENCY", "eur", "per_usd", "TITLE",
            ["exchange-rates", "fx", "usd"], ["multi-currency-ledger", "financial-reporting", "treasury"],
            f"Monthly averages of national currency units per US dollar for {YEAR}, from the BIS Data Portal dataflow WS_XRU (US dollar exchange rates, average of observations through the period), with the euro as the primary series and the pound sterling, yen, real, rupee, Swiss franc, Canadian and Australian dollars, renminbi and Mexican peso as columns.",
            terms_raw,
        ),
        bis_table(
            f"global-residential-property-prices-quarterly-{YEAR}", f"Residential property price indices, nominal, quarterly {YEAR} (US, euro area, GB, JP, BR, IN, CH, CA, AU)", "economy",
            "WS_SPP", "1.0", f"Q.{areas}.N.628", "quarterly", "decimal", "REF_AREA", "REF_AREA", "us", "index", "TITLE_TS",
            ["property-prices", "housing"], ["property-demo", "mortgage-origination", "insurance"],
            f"Quarterly nominal residential property price indices (2010 = 100) for {YEAR}, from the BIS selected residential property price series (dataflow WS_SPP, unit 628), with the United States as the primary series and the euro area, United Kingdom, Japan, Brazil, India, Switzerland, Canada and Australia as columns. The portal publishes the latest quarter for some economies before the underlying national release; the figures recorded are those served on the access date.",
            terms_raw,
        ),
        bis_table(
            f"global-credit-to-private-non-financial-sector-quarterly-{YEAR}", f"Credit to the private non-financial sector as a percentage of GDP, quarterly {YEAR} (US, euro area, GB, JP, BR, IN, CH, CA, AU)", "economy",
            "WS_TC", "2.0", f"Q.{areas}.P.A.M.770.A", "quarterly", "percent", "BORROWERS_CTY", "BORROWERS_CTY", "us", "percent_of_gdp", "TITLE_TS",
            ["credit", "private-debt", "credit-risk"], ["credit-risk", "banking-demo", "market-sizing"],
            f"Total credit to the private non-financial sector from all lenders at market value, as a percentage of GDP and adjusted for breaks, quarterly for {YEAR}, from the BIS total credit statistics (dataflow WS_TC version 2.0), with the United States as the primary series and the euro area, United Kingdom, Japan, Brazil, India, Switzerland, Canada and Australia as columns.",
            terms_raw,
        ),
    ]


def main() -> int:
    for entry in [*bcb_sgs_entries(), *bcb_payment_instrument_entries(), bcb_pix_by_state_entry(), *ecb_entries(), *bis_entries()]:
        write(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build the Kuwait statistics entries.

Employment by nationality group, sector and sex, by top nationalities and sex, average monthly wage by
nationality, sector and sex, and Kuwaiti government employees by age group and sex, all read from the
charts of the Central Statistical Bureau's Labour Market Information System (lmis.csb.gov.kw), which
embed the published counts for the latest quarter (31 March 2026). Valid credit and debit cards by
month come from the Central Bank of Kuwait's Monthly Monetary Statistical Bulletin for September 2026.
Run from the repository root:

    uv run python tools/build_gulf4_kw.py
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import evidence, write  # noqa: E402
from _gulf4 import categorical, fetch_patiently, share_tests, shares_assumption  # noqa: E402

LMIS = "https://lmis.csb.gov.kw"
DASHBOARD = f"{LMIS}/MainDashBoard"
AGE_REPORT = f"{LMIS}/InteractiveReportPerSectorPerAge"
CBK_BULLETIN = "https://www.cbk.gov.kw/en/redirects/download?compId=172793&esIndex=reports"
PUBLISHER_CSB = "Central Statistical Bureau, State of Kuwait (Labour Market Information System)"
PUBLISHER_CBK = "Central Bank of Kuwait"
LICENSE = "unstated"
PERIOD = "2026-03-31"
TAGS = ["kuwait", "gcc"]
LMIS_NOTE = (
    "The Labour Market Information System states no reuse licence (its footer reads 'all rights reserved'), so the entry "
    "stays at license-review. The dashboard always shows the latest quarter: when the CSB publishes the next quarter the "
    "page changes and this entry's evidence hash will no longer match, which is the signal to rebuild it."
)
COUNTRY_GROUPS = {
    "دولة الكويت": "Kuwait",
    "دول مجلس التعاون الخليجي": "Other GCC countries",
    "دول عربية أخرى": "Other Arab countries",
    "دول آسيوية غير عربية": "Non-Arab Asian countries",
    "دول أفريقية غير عربية": "Non-Arab African countries",
    "دول أوروبا": "Europe",
    "دول امريكا الشمالية": "North America",
    "دول امريكا الجنوبية": "South America",
    "استراليا ونيوزيلندا": "Australia and New Zealand",
    "غير مبين": "Not stated",
}
NATIONALITIES = {
    "الهنــد": "India",
    "مصـــر": "Egypt",
    "الكويت": "Kuwait",
    "بنجلاديش": "Bangladesh",
    "نيبال": "Nepal",
    "ســوريا": "Syria",
    "باكستان": "Pakistan",
    "الفلبين": "Philippines",
    "الأردن": "Jordan",
    "سيريلانكا": "Sri Lanka",
    "باقي الجنسيات": "All other nationalities",
}
WAGE_GROUPS = {"كويتي-ذكر": "kuwaiti|male", "كويتي-أنثي": "kuwaiti|female", "غير كويتي-ذكر": "non_kuwaiti|male", "غير كويتي-أنثي": "non_kuwaiti|female"}
TRANSLATION = {
    "parameter": "category labels",
    "value": "English renderings of the dashboard's Arabic labels, with the Arabic labels kept alongside",
    "method": "assumed",
    "rationale": "The Labour Market Information System publishes Arabic labels only; the English keys are translations made for this entry and change no value.",
}


def array_after(html: str, title: str, series: str) -> list[int]:
    """The integers of a chart's ``data: [...]`` array for the series named ``series`` after the chart titled ``title``."""
    block = html[html.index(f"text: '{title}'"):]
    match = re.search(r"name:\s*'\s*" + re.escape(series) + r"\s*',\s*data:\s*\[([\d,]+)\]", block)
    if match is None:
        raise LookupError(f"series {series!r} not found after {title!r}")
    return [int(x) for x in match.group(1).split(",") if x]


def categories_after(html: str, title: str) -> list[str]:
    block = html[html.index(f"text: '{title}'"):]
    match = re.search(r"categories:\s*\[([^\]]+)\]", block)
    if match is None:
        raise LookupError(f"no categories after {title!r}")
    return [c.strip().strip("'") for c in match.group(1).split(",") if c.strip()]


def chart_title(html: str, phrase: str) -> str:
    """The full title text of the first chart whose title contains ``phrase``."""
    match = re.search(r"text: '([^']*" + re.escape(phrase) + r"[^']*)'", html)
    if match is None:
        raise LookupError(f"no chart title containing {phrase!r}")
    return match.group(1)


def data_snippet(html: str, values: list[int]) -> str:
    """The literal ``data: [...]`` text for ``values`` as it appears in the page source."""
    body = ",".join(str(v) for v in values) + ","
    match = re.search(r"data:\s*\[" + re.escape(body) + r"\]", html)
    if match is None:
        raise LookupError("data array not found verbatim")
    return match.group(0)


def lmis_item(url: str, title: str, locator: str, value, snippet: str, raw: bytes, unit: str = "count") -> dict:
    return evidence(PUBLISHER_CSB, title, url, locator, value, unit, snippet, LICENSE, raw)


def nationality_groups(html: str, raw: bytes) -> dict:
    all_title = chart_title(html, "حسب مجموعات الدول والنوع وفقا للحالة للفترة")
    gov_title = chart_title(html, "فى القطاع الحكومي للفترة")
    private_title = chart_title(html, "فى القطاع الخاص للفترة")
    labels = [COUNTRY_GROUPS[c] for c in categories_after(html, all_title)]
    labels_ar = {COUNTRY_GROUPS[c]: c for c in categories_after(html, all_title)}
    series = {
        "all_sectors|male": array_after(html, all_title, "ذكور"),
        "all_sectors|female": array_after(html, all_title, "إناث"),
        "government|male": array_after(html, gov_title, "ذكر"),
        "government|female": array_after(html, gov_title, "أنثي"),
        "private|male": array_after(html, private_title, "ذكر"),
        "private|female": array_after(html, private_title, "أنثي"),
    }
    for chart in (gov_title, private_title):
        if categories_after(html, chart) != categories_after(html, all_title):
            raise ValueError("sector charts list country groups in a different order")
    dists = {k: categorical(dict(zip(labels, v)), labels_ar) for k, v in series.items()}
    title = "CSB Labour Market Information System, main dashboard (HTML, data as at 31 March 2026)"
    return {
        "id": "kw-workers-by-nationality-group-sector-and-sex-2026-03",
        "title": "Kuwait workers by nationality group given sector (all, government, private) and sex, 31 March 2026",
        "kind": "conditional",
        "domain": "employment",
        "region": "KW",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": PERIOD, "end": PERIOD},
        "tags": TAGS + ["employment", "workforce", "nationality", "sector", "sex", "expatriates", "csb", "lmis"],
        "use_cases": ["synthetic-employees", "hr-demo", "workforce-planning", "hr-analytics", "person-generation"],
        "spec": {"variable": "nationality_group", "unit": "ratio", "given": "sector|sex", "distributions": dists},
        "evidence": [
            lmis_item(DASHBOARD, title, "chart 'by country groups and sex', series males (ذكور)", series["all_sectors|male"][0], data_snippet(html, series["all_sectors|male"]), raw),
            lmis_item(DASHBOARD, title, "chart 'by country groups and sex in the government sector', series male (ذكر)", series["government|male"][0], "series: [{ name: 'ذكر', data: [" + ",".join(map(str, series["government|male"][:4])), raw),
            lmis_item(DASHBOARD, title, "chart 'by country groups and sex in the private sector', series male (ذكر)", series["private|male"][0], "series: [{ name: 'ذكر', data: [" + ",".join(map(str, series["private|male"][:4])), raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", ""), TRANSLATION],
        "tests": share_tests(dists, 1),
        "notes": (
            "Workers in Kuwait as at 31 March 2026 by nationality group (Kuwait, other GCC, other Arab, non-Arab Asian, "
            "non-Arab African, Europe, North and South America, Australia and New Zealand, not stated) for men and women, "
            "across all sectors and separately for the government and private sectors, from the charts of the Central "
            "Statistical Bureau's Labour Market Information System, which compiles administrative records. All-sector "
            "counts exceed government plus private: the remainder is employment outside those two sectors (the system reports "
            "family-sector employment in separate tables). " + LMIS_NOTE
        ),
    }


def top_nationalities(html: str, raw: bytes) -> dict:
    t = chart_title(html, "حسب أعلى 10 جنسيات والنوع وفقا للحالة للفترة")
    cats = categories_after(html, t)
    labels = [NATIONALITIES[c] for c in cats]
    labels_ar = {NATIONALITIES[c]: c for c in cats}
    series = {"male": array_after(html, t, "ذكور"), "female": array_after(html, t, "إناث")}
    dists = {k: categorical(dict(zip(labels, v)), labels_ar) for k, v in series.items()}
    title = "CSB Labour Market Information System, main dashboard (HTML, data as at 31 March 2026)"
    return {
        "id": "kw-workers-by-nationality-and-sex-2026-03",
        "title": "Kuwait workers by nationality (ten largest and all others) given sex, 31 March 2026",
        "kind": "conditional",
        "domain": "employment",
        "region": "KW",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": PERIOD, "end": PERIOD},
        "tags": TAGS + ["employment", "workforce", "nationality", "sex", "expatriates", "csb", "lmis"],
        "use_cases": ["synthetic-employees", "hr-demo", "person-generation", "synthetic-customers"],
        "spec": {"variable": "nationality", "unit": "ratio", "given": "sex", "distributions": dists},
        "evidence": [
            lmis_item(DASHBOARD, title, "chart 'by top 10 nationalities and sex', series males (ذكور)", series["male"][0], data_snippet(html, series["male"]), raw),
            lmis_item(DASHBOARD, title, "chart 'by top 10 nationalities and sex', series females (إناث)", series["female"][0], "data:[" + ",".join(map(str, series["female"])) + ",]", raw),
        ],
        "assumed": [shares_assumption("distributions.*.parameters.shares", ""), TRANSLATION],
        "tests": share_tests(dists, 2),
        "notes": (
            "Workers in Kuwait as at 31 March 2026, all sectors, by nationality for the ten largest nationalities (India, "
            "Egypt, Kuwait, Bangladesh, Nepal, Syria, Pakistan, the Philippines, Jordan, Sri Lanka) and all others, for men "
            "and women, from the Central Statistical Bureau's Labour Market Information System. " + LMIS_NOTE
        ),
    }


def wages(html: str, raw: bytes) -> dict:
    rows: dict[str, dict] = {}
    snippets = {}
    for sector, phrase in (("government", "متوسط الدخل الشهري فى القطاع الحكومى"), ("private", "متوسط الدخل الشهري فى القطاع الخاص")):
        t = chart_title(html, phrase)
        block = html[html.index(f"text: '{t}'"):]
        match = re.search(r"data: \[(\{name: '[^\]]+)\]", block)
        points = re.findall(r"\{name: '([^']+)', y: (\d+)\}", match.group(1))
        for name, value in points:
            rows[f"{sector}|{WAGE_GROUPS[name.strip()]}"] = {"average_monthly_wage_kwd": int(value), "label_ar": name.strip()}
        snippets[sector] = re.search(r"data: \[\{name: '[^']+', y: \d+\}", block).group(0)
    title = "CSB Labour Market Information System, main dashboard (HTML, data as at 31 March 2026)"
    return {
        "id": "kw-average-monthly-wage-by-nationality-sector-and-sex-2026-03",
        "title": "Kuwait average monthly wage (KWD) by sector, Kuwaiti or non-Kuwaiti nationality and sex, 31 March 2026",
        "kind": "rule",
        "domain": "employment",
        "region": "KW",
        "status": "license-review",
        "tier": "B",
        "valid_from": PERIOD,
        "valid_to": PERIOD,
        "tags": TAGS + ["wages", "salary", "earnings", "nationality", "sector", "sex", "csb", "lmis", "reference-table"],
        "use_cases": ["synthetic-employees", "payroll-demo", "hr-demo", "banking-demo", "hr-analytics"],
        "spec": {
            "implementation": "almanac.rules.lookup_table",
            "parameters": {"currency": "KWD", "rows": rows},
            "vectors": [
                {"input": {"key": "government|kuwaiti|male", "column": "average_monthly_wage_kwd"}, "expected": rows["government|kuwaiti|male"]["average_monthly_wage_kwd"], "origin": "source"},
                {"input": {"key": "private|non_kuwaiti|female", "column": "average_monthly_wage_kwd"}, "expected": rows["private|non_kuwaiti|female"]["average_monthly_wage_kwd"], "origin": "source"},
                {"input": "family|kuwaiti|male", "expected": False, "origin": "derived"},
            ],
        },
        "evidence": [
            lmis_item(DASHBOARD, title, "chart 'average monthly income in the government sector by nationality'", rows["government|kuwaiti|male"]["average_monthly_wage_kwd"], snippets["government"], raw, "currency:KWD"),
            lmis_item(DASHBOARD, title, "chart 'average monthly income in the private sector by nationality'", rows["private|kuwaiti|male"]["average_monthly_wage_kwd"], snippets["private"], raw, "currency:KWD"),
        ],
        "assumed": [
            {
                "parameter": "currency",
                "value": "KWD",
                "method": "assumed",
                "rationale": "The charts title the measure average monthly income (متوسط الدخل الشهري) and print no unit; the figures are read as Kuwaiti dinars per month, the national currency.",
            },
            TRANSLATION,
        ],
        "tests": [
            {"statistic": "vector_pass_fraction", "expected": 1, "tolerance": 0},
            {"statistic": "count", "expected": len(rows), "tolerance": 0},
            {"statistic": "max[average_monthly_wage_kwd]", "expected": max(r["average_monthly_wage_kwd"] for r in rows.values()), "tolerance": 0},
        ],
        "notes": (
            "Average monthly wage of workers in Kuwait as at 31 March 2026 for Kuwaiti and non-Kuwaiti men and women in the "
            "government sector and in the private sector, keyed sector|nationality|sex, from the Labour Market Information "
            "System's dashboard charts (whole dinars as published). Combine with the nationality-by-sector counts in "
            "kw-workers-by-nationality-group-sector-and-sex-2026-03 to draw synthetic salaries. " + LMIS_NOTE
        ),
    }


def kuwaiti_government_age(html: str, raw: bytes, dashboard: str) -> dict:
    t = chart_title(html, "التوزيع العددى والنسبي للعمالة حسب النوع -كويتي")
    if 'option selected="selected" value="1">أ- القطاع الحكومي' not in html or 'option selected="selected" value="1">كويتي' not in html:
        raise ValueError("the age report's default selection is no longer Kuwaiti government-sector workers")
    cats = [c.replace("غير مبين", "Not stated") for c in categories_after(html, t)]
    series = {"male": array_after(html, t, "ذكور"), "female": array_after(html, t, "إناث")}
    government = chart_title(dashboard, "فى القطاع الحكومي للفترة")
    if sum(series["male"]) != array_after(dashboard, government, "ذكر")[0] or sum(series["female"]) != array_after(dashboard, government, "أنثي")[0]:
        raise ValueError("age totals no longer match the Kuwaiti government-sector counts on the dashboard")
    dists = {k: categorical(dict(zip(cats, v))) for k, v in series.items()}
    title = "CSB Labour Market Information System, report by sector and age (HTML, default view: government sector, Kuwaiti, 31 March 2026)"
    return {
        "id": "kw-kuwaiti-government-workers-by-age-group-and-sex-2026-03",
        "title": "Kuwait: Kuwaiti government-sector workers by five-year age group given sex, 31 March 2026",
        "kind": "conditional",
        "domain": "employment",
        "region": "KW",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": PERIOD, "end": PERIOD},
        "tags": TAGS + ["employment", "public-sector", "age", "sex", "nationals", "csb", "lmis"],
        "use_cases": ["synthetic-employees", "hr-demo", "pensions", "workforce-planning"],
        "spec": {"variable": "age_group", "unit": "ratio", "given": "sex", "distributions": dists},
        "evidence": [
            lmis_item(AGE_REPORT, title, "chart 'distribution by sex - Kuwaiti', series males (ذكور)", series["male"][2], data_snippet(html, series["male"]), raw),
            lmis_item(AGE_REPORT, title, "sector selector, selected option", "أ- القطاع الحكومي", 'option selected="selected" value="1">أ- القطاع الحكومي', raw, "text"),
        ],
        "assumed": [
            shares_assumption("distributions.*.parameters.shares", "The 'not stated' (غير مبين) age row is kept as 'Not stated'."),
            {
                "parameter": "population covered",
                "value": "Kuwaiti workers in the government sector",
                "method": "derived",
                "rationale": "The report's default view selects the government sector and Kuwaiti nationality; the male and female totals equal the Kuwait row of the dashboard's government-sector chart.",
            },
        ],
        "tests": share_tests(dists, 2),
        "notes": (
            "Kuwaiti nationals employed in the government sector as at 31 March 2026 by five-year age group (15-19 to 65+, "
            "plus not stated) for men and women, from the Labour Market Information System's report by sector and age in "
            "its default view. " + LMIS_NOTE
        ),
    }


def bank_cards(raw: bytes) -> dict:
    text = " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(raw)).pages)
    months = re.findall(r"([A-Z][a-z]{2})-26 [^A-Z]*?Local Bank Cards", text)[:9]
    credit = re.findall(r"\(1\)(\d+\.\d)(\d+\.\d)-- - Credit Cards \(1\)", text)[:9]
    debit = re.findall(r"\(2\)(\d+\.\d)(\d+\.\d)-- - Debit Cards \(2\)", text)[:9]
    totals = re.findall(r"المجموع(\d+\.\d)(\d+\.\d)\d+Total", text)[:9]
    if months != ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"] or not (len(credit) == len(debit) == len(totals) == 9):
        raise ValueError("card table layout changed")
    number = {m: f"{i + 1:02d}" for i, m in enumerate(months)}
    series = []
    for m, (cv, ci), (dv, di), (tv, ti) in zip(months, credit, debit, totals):
        if abs(float(cv) + float(dv) - float(tv)) > 0.15:
            raise ValueError(f"{m}: credit plus debit cards do not match the total")
        series.append({
            "period": f"2026-{number[m]}",
            "value": float(tv),
            "credit_cards_valid_thousands": float(cv),
            "debit_cards_valid_thousands": float(dv),
            "cards_issued_thousands": float(ti),
            "credit_cards_issued_thousands": float(ci),
            "debit_cards_issued_thousands": float(di),
        })
    columns = [k for k in series[0] if k not in ("period", "value")]
    title = "Central Bank of Kuwait, Monthly Monetary Statistical Bulletin, September 2026 (PDF)"
    return {
        "id": "kw-bank-cards-valid-and-issued-monthly-2026",
        "title": "Kuwait local bank credit and debit cards, valid and issued, monthly January to September 2026",
        "kind": "temporal",
        "domain": "payments",
        "region": "KW",
        "status": "license-review",
        "tier": "B",
        "observed_period": {"start": "2026-01-01", "end": "2026-09-30"},
        "tags": TAGS + ["cards", "credit-cards", "debit-cards", "payments", "monthly", "time-series", "cbk"],
        "use_cases": ["banking-demo", "payments-demo", "fintech-demo", "synthetic-customers", "market-sizing"],
        "spec": {"variable": "valid_local_bank_cards_thousands", "unit": "decimal", "frequency": "monthly", "columns": columns, "series": series},
        "evidence": [
            evidence(PUBLISHER_CBK, title, CBK_BULLETIN, "plastic cards table (valid and issued cards, ATM and POS machines), January 2026, Credit Cards (1)", credit[0][0], "decimal", f"{credit[0][0]}{credit[0][1]}-- - Credit Cards (1)", LICENSE, raw),
            evidence(PUBLISHER_CBK, title, CBK_BULLETIN, "plastic cards table, September 2026, Debit Cards (2)", debit[8][0], "decimal", f"{debit[8][0]}{debit[8][1]}-- - Debit Cards (2)", LICENSE, raw),
        ],
        "assumed": [
            {
                "parameter": "cell boundaries",
                "value": "each figure has one decimal place",
                "method": "derived",
                "rationale": "The PDF's extracted text runs adjacent cells together (for example 1738.036.0); every figure in the table carries one decimal, and credit plus debit valid cards reproduce the printed total each month, which the builder checks.",
            }
        ],
        "tests": [
            {"statistic": "value[2026-09]", "expected": series[-1]["value"], "tolerance": 1e-9},
            {"statistic": "column[credit_cards_valid_thousands,2026-01]", "expected": series[0]["credit_cards_valid_thousands"], "tolerance": 1e-9},
            {"statistic": "count", "expected": len(series), "tolerance": 0},
        ],
        "notes": (
            "Credit and debit cards issued by local banks in Kuwait, in thousands: cards valid at the end of each month "
            "(the series value is the total) and cards issued during the month, January to September 2026, from the plastic "
            "cards table of the Central Bank of Kuwait's Monthly Monetary Statistical Bulletin (September 2026 issue). ATM and "
            "point-of-sale machine counts in the same table are left out because the extracted text runs the two counts "
            "together without a separator. The bulletin publishes no reuse licence, so the entry stays at license-review."
        ),
    }


def build() -> list[Path]:
    dashboard_raw = fetch_patiently(DASHBOARD)
    dashboard = dashboard_raw.decode("utf-8")
    age_raw = fetch_patiently(AGE_REPORT)
    paths = [
        write(nationality_groups(dashboard, dashboard_raw)),
        write(top_nationalities(dashboard, dashboard_raw)),
        write(wages(dashboard, dashboard_raw)),
        write(kuwaiti_government_age(age_raw.decode("utf-8"), age_raw, dashboard)),
        write(bank_cards(fetch_patiently(CBK_BULLETIN))),
    ]
    return paths


if __name__ == "__main__":
    build()

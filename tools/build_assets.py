"""Generate the README artwork as SVG, in light and dark variants, with text that is measured to fit.

GitHub renders README images through an <img> tag, so the drawings rely on
system font stacks and keep every label inside its box by budgeting
characters per line. Run from the repository root:

    uv run python tools/build_assets.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "assets"
SANS = "Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, 'DejaVu Sans Mono', monospace"


@dataclass(frozen=True)
class Palette:
    name: str
    page: str
    card: str
    card_edge: str
    ink: str
    ink_soft: str
    ink_faint: str
    accent: str
    good: str
    bad: str
    hero_a: str
    hero_b: str
    hero_grid: str
    hero_ink: str
    hero_soft: str
    chip: str
    chip_ink: str


LIGHT = Palette("light", "#f6f8fa", "#ffffff", "#d0d7de", "#1f2328", "#57606a", "#8c959f", "#0969da", "#1a7f37", "#cf222e", "#0b1220", "#1b2a4a", "#2b3a5c", "#f8fafc", "#9fb0cc", "#1d2a44", "#cfe0ff")
DARK = Palette("dark", "#0d1117", "#161b22", "#30363d", "#e6edf3", "#9da7b3", "#6e7681", "#58a6ff", "#3fb950", "#f85149", "#0b1220", "#141c2e", "#243049", "#f8fafc", "#9fb0cc", "#1f2b47", "#bcd3ff")


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x: float, y: float, s: str, size: float, fill: str, family: str = SANS, weight: str = "400", anchor: str = "start", extra: str = "") -> str:
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>'


def mono_width(s: str, size: float) -> float:
    return len(s) * size * 0.62


def sans_width(s: str, size: float) -> float:
    return len(s) * size * 0.55


def hero(p: Palette) -> str:
    w, h = 960, 250
    chips = ["check digits", "identifier formats", "tax rates", "calendars", "code lists", "currency rules", "official statistics", "exchange rates"]
    rows: list[list[str]] = [[]]
    x = 48
    for chip in chips:
        cw = sans_width(chip, 12) + 22
        if x + cw > 560:
            rows.append([])
            x = 48
        rows[-1].append(chip)
        x += cw + 8
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Misata Almanac: the rules real-world data obeys, with receipts">',
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{p.hero_a}"/><stop offset="1" stop-color="{p.hero_b}"/></linearGradient>',
        f'<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="{p.hero_grid}" stroke-width="0.7"/></pattern></defs>',
        f'<rect width="{w}" height="{h}" rx="18" fill="url(#g)"/><rect width="{w}" height="{h}" rx="18" fill="url(#grid)" opacity="0.6"/>',
        text(48, 86, "Misata Almanac", 44, p.hero_ink, SANS, "700"),
        text(48, 120, "The rules real-world data obeys. With receipts.", 18, p.hero_soft, SANS, "400"),
    ]
    y = 150
    for row in rows:
        x = 48
        for chip in row:
            cw = sans_width(chip, 12) + 22
            svg.append(f'<rect x="{x}" y="{y}" width="{cw:.0f}" height="24" rx="12" fill="{p.chip}"/>')
            svg.append(text(x + 11, y + 16, chip, 12, p.chip_ink, SANS, "500"))
            x += cw + 8
        y += 32
    svg.append(text(48, 228, "value  →  primary source  →  URL  →  sha256  →  tests  →  verified", 13, "#64d8cb", MONO, "500"))
    # receipt card
    cx, cy, cw, ch = 672, 34, 250, 182
    svg.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="12" fill="{p.card}" stroke="{p.card_edge}"/>')
    lines = [("RECEIPT", "gb-vrn-check-digits"), ("publisher", "HM Revenue & Customs"), ("weights", "8 7 6 5 4 3 2"), ("modulus", "97, +55 variant"), ("sha256", "28370b88…ff6b"), ("vectors", "7/7 from the source")]
    ly = cy + 30
    for k, v in lines:
        svg.append(text(cx + 16, ly, k, 11, p.ink_faint, MONO, "600"))
        svg.append(text(cx + 90, ly, v, 11, p.ink, MONO, "700" if k == "RECEIPT" else "400"))
        ly += 22
    svg.append(f'<g transform="translate({cx + 180} {cy + 150}) rotate(-12)"><rect x="-44" y="-13" width="88" height="26" rx="4" fill="none" stroke="{p.good}" stroke-width="2.5"/>'
               + text(0, 5, "VERIFIED", 12, p.good, MONO, "700", "middle")
               + '<animate attributeName="opacity" values="0;0;1;1" keyTimes="0;0.5;0.56;1" dur="4s" repeatCount="indefinite"/></g>')
    svg.append("</svg>")
    return "\n".join(svg)


def before_after(p: Palette) -> str:
    w, h = 960, 330
    panels = [
        ("The invoice", ["VAT no.  GB123456789", "date     2026-12-28", "amount   ¥1,234.56"], ["✗ check digits fail MOD 97", "✗ substitute bank holiday", "✗ yen has no minor units"], "Three strikes in three fields.", False),
        ("The customer", ["NINO     AO 12 34 56 E", "tax code 0500L", "e-mail   a@.uk"], ["✗ O never in position 2", "✗ leading zero", "✗ domain starts with a dot"], "HMRC bounces all three.", False),
        ("The Pix", ["txid   7978c0c9-7ea8-…", "CNPJ   12.ABC.345/01DE-53", "valor  100"], ["✗ hyphens not allowed", "✗ check digits must be 35", "✗ two decimals required"], "Banco Central says no.", False),
        ("With the Almanac", ["VAT no.  101747696", "NINO     AB 12 34 56 C", "CNPJ     12.ABC.345/01DE-35"], ["✓ HMRC's own test vector", "✓ prefix and suffix rules", "✓ Receita's worked example"], "Every line has a receipt.", True),
    ]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Three panels of synthetic data failing real-world checks, and one passing with the Almanac">',
        f'<rect width="{w}" height="{h}" rx="18" fill="{p.page}"/>',
        text(28, 38, "Synthetic data in the wild", 17, p.ink, SANS, "700"),
        text(28, 58, "Before and after the Almanac. Same fields, different outcome.", 12, p.ink_soft, SANS, "400"),
    ]
    pw, gap, x0, y0, ph = 218, 14, 28, 78, 226
    for i, (title, fields, verdicts, caption, good) in enumerate(panels):
        x = x0 + i * (pw + gap)
        edge = p.good if good else p.card_edge
        svg.append(f'<rect x="{x}" y="{y0}" width="{pw}" height="{ph}" rx="12" fill="{p.card}" stroke="{edge}" stroke-width="{1.6 if good else 1}"/>')
        svg.append(text(x + 16, y0 + 28, title, 13, p.ink, SANS, "700"))
        y = y0 + 56
        for f in fields:
            svg.append(text(x + 16, y, f, 11.5, p.ink_soft, MONO))
            y += 19
        y += 12
        for v in verdicts:
            svg.append(text(x + 16, y, v, 11.5, p.good if good else p.bad, MONO, "700"))
            y += 19
        svg.append(text(x + 16, y0 + ph - 16, caption, 11, p.ink_faint, SANS, "400", extra='font-style="italic"'))
        if good:
            svg.append(f'<g transform="translate({x + pw - 48} {y0 + 24}) rotate(12)"><rect x="-26" y="-10" width="52" height="20" rx="3" fill="none" stroke="{p.good}" stroke-width="2"/>'
                       + text(0, 4, "PASS", 10, p.good, MONO, "700", "middle")
                       + '<animate attributeName="opacity" values="0;0;1;1" keyTimes="0;0.45;0.52;1" dur="3.5s" repeatCount="indefinite"/></g>')
    svg.append("</svg>")
    return "\n".join(svg)


def proof_chain(p: Palette) -> str:
    w, h = 960, 150
    steps = [("primary source", "office, bank, regulator"), ("exact URL", "pinned or queried"), ("sha256", "of the bytes read"), ("locator + snippet", "finds the value"), ("test vectors", "the source's own"), ("verifier", "re-fetch, re-check")]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="How a value earns its place: primary source, exact URL, sha256, locator and snippet, test vectors, verifier">',
        f'<rect width="{w}" height="{h}" rx="18" fill="{p.page}"/>',
        text(28, 34, "How a value earns its place", 15, p.ink, SANS, "700"),
    ]
    bw, bh, gap, x0, y0 = 138, 60, 15, 28, 56
    for i, (title, sub) in enumerate(steps):
        x = x0 + i * (bw + gap)
        last = i == len(steps) - 1
        svg.append(f'<rect x="{x}" y="{y0}" width="{bw}" height="{bh}" rx="9" fill="{p.card}" stroke="{p.good if last else p.card_edge}" stroke-width="{1.6 if last else 1}"/>')
        svg.append(text(x + 12, y0 + 25, title, 11.5, p.good if last else p.ink, MONO, "700"))
        svg.append(text(x + 12, y0 + 44, sub, 10.5, p.ink_soft, SANS))
        if not last:
            svg.append(f'<path d="M{x + bw + 2} {y0 + bh / 2} h{gap - 4}" stroke="{p.ink_faint}" stroke-width="1.5" fill="none"/>')
            svg.append(f'<path d="M{x + bw + gap - 6} {y0 + bh / 2 - 4} l5 4 -5 4" stroke="{p.ink_faint}" stroke-width="1.5" fill="none"/>')
    svg.append(f'<circle r="4" fill="{p.good}"><animateMotion dur="6s" repeatCount="indefinite" path="M{x0 + 10} {y0 + bh + 18} H{x0 + 6 * bw + 5 * gap - 10}"/></circle>')
    svg.append(f'<path d="M{x0 + 10} {y0 + bh + 18} H{x0 + 6 * bw + 5 * gap - 10}" stroke="{p.card_edge}" stroke-width="1" stroke-dasharray="3 4"/>')
    svg.append("</svg>")
    return "\n".join(svg)


def anatomy(p: Palette) -> str:
    w, h = 960, 300
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Anatomy of an entry: spec is executed by the data engine, evidence, assumed and tests are checked by the verifier">',
        f'<rect width="{w}" height="{h}" rx="18" fill="{p.page}"/>',
        text(28, 34, "Anatomy of an entry", 15, p.ink, SANS, "700"),
        text(28, 54, "One YAML file. Four blocks. Two readers.", 12, p.ink_soft, SANS),
    ]
    blocks = [
        ("spec", "what runs", ["implementation", "parameters", "vectors"], p.accent),
        ("evidence", "why believe it", ["publisher, URL", "sha256, locator", "snippet, licence"], p.good),
        ("assumed", "what we derived", ["parameter", "method", "rationale"], p.ink_soft),
        ("tests", "what reproduces", ["statistic", "expected", "tolerance"], p.ink_soft),
    ]
    bx, by, bw, bh, gap = 28, 74, 150, 150, 14
    for i, (name, tag, lines, colour) in enumerate(blocks):
        x = bx + i * (bw + gap)
        svg.append(f'<rect x="{x}" y="{by}" width="{bw}" height="{bh}" rx="10" fill="{p.card}" stroke="{p.card_edge}"/>')
        svg.append(f'<rect x="{x}" y="{by}" width="{bw}" height="6" rx="3" fill="{colour}"/>')
        svg.append(text(x + 14, by + 32, name, 13, p.ink, MONO, "700"))
        svg.append(text(x + 14, by + 50, tag, 11, p.ink_soft, SANS, "400", extra='font-style="italic"'))
        y = by + 80
        for line in lines:
            svg.append(text(x + 14, y, line, 11, p.ink_soft, MONO))
            y += 20
    # readers
    rx = bx + 4 * (bw + gap) + 20
    svg.append(f'<rect x="{rx}" y="{by}" width="200" height="64" rx="10" fill="{p.card}" stroke="{p.accent}" stroke-width="1.6"/>')
    svg.append(text(rx + 16, by + 27, "data engine", 13, p.accent, MONO, "700"))
    svg.append(text(rx + 16, by + 47, "executes spec, samples, validates", 10.5, p.ink_soft, SANS))
    svg.append(f'<rect x="{rx}" y="{by + 86}" width="200" height="64" rx="10" fill="{p.card}" stroke="{p.good}" stroke-width="1.6"/>')
    svg.append(text(rx + 16, by + 113, "verifier", 13, p.good, MONO, "700"))
    svg.append(text(rx + 16, by + 133, "re-fetches, re-hashes, re-runs", 10.5, p.ink_soft, SANS))
    svg.append(f'<path d="M{bx + bw - 24} {by} V{by - 12} H{rx - 16} Q{rx} {by - 12} {rx} {by + 2} V{by + 10}" stroke="{p.accent}" stroke-width="1.5" fill="none" stroke-dasharray="4 3"/>')
    last_right = bx + 4 * (bw + gap) - gap
    svg.append(f'<path d="M{last_right} {by + bh - 20} C {last_right + 30} {by + bh - 20}, {rx - 30} {by + 118}, {rx} {by + 118}" stroke="{p.good}" stroke-width="1.5" fill="none" stroke-dasharray="4 3"/>')
    svg.append(text(28, 270, "valid_from · valid_to · observed_period answer “what applied on date X”; tags and use_cases answer “which entry do I need”.", 11, p.ink_faint, SANS))
    svg.append("</svg>")
    return "\n".join(svg)


def pipeline(p: Palette) -> str:
    w, h = 960, 170
    steps = ["schema", "models", "placement", "dates, units", "fetch + hash", "snippet, value", "rule vectors", "statistics", "report"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="What almanac verify checks, in order">',
        f'<rect width="{w}" height="{h}" rx="18" fill="{p.page}"/>',
        text(28, 34, "What  almanac verify  checks, in order", 15, p.ink, SANS, "700"),
    ]
    x, y0, bh = 28, 58, 40
    for i, s in enumerate(steps):
        bw = sans_width(s, 11.5) + 22
        last = i == len(steps) - 1
        svg.append(f'<rect x="{x:.0f}" y="{y0}" width="{bw:.0f}" height="{bh}" rx="20" fill="{p.card}" stroke="{p.good if last else p.card_edge}" stroke-width="{1.6 if last else 1}"/>')
        svg.append(text(x + 13, y0 + 25, s, 11.5, p.good if last else p.ink, SANS, "600"))
        x += bw + 6
        if not last:
            svg.append(f'<path d="M{x:.0f} {y0 + bh / 2 - 4} l5 4 -5 4" stroke="{p.ink_faint}" stroke-width="1.5" fill="none"/>')
            x += 12
    svg.append(text(28, 128, "Any failure fails the run. Tier A primary evidence must be machine-readable; verified entries must cite permissive terms.", 11, p.ink_soft, SANS))
    svg.append(text(28, 148, "PDFs are searched by extracted text, ZIP archives by their text members, everything else by its bytes.", 11, p.ink_faint, SANS))
    svg.append("</svg>")
    return "\n".join(svg)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for palette in (LIGHT, DARK):
        for name, fn in (("hero", hero), ("before-after", before_after), ("proof-chain", proof_chain), ("anatomy", anatomy), ("pipeline", pipeline)):
            path = OUT / f"{name}-{palette.name}.svg"
            path.write_text(fn(palette), encoding="utf-8")
            print(f"wrote {path.relative_to(OUT.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

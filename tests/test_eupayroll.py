"""Tests for the European payroll and personal-tax rule modules and the entries built on them.

Parameters are read from the entries themselves, so the tests exercise the
published figures rather than a copy of them.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from almanac.rules import (
    cumulative_bracket_tariff,
    de_income_tax_tariff,
    de_solidarity_surcharge,
    ie_income_tax_usc,
    load_rule,
)

ENTRIES = Path(__file__).resolve().parent.parent / "entries"

ENTRY_IDS = {
    "de-income-tax-tariff-2026": "tax/DE",
    "de-solidarity-surcharge-2026": "tax/DE",
    "de-child-benefit-and-child-allowances-2026": "tax/DE",
    "de-social-insurance-reference-values-2026": "tax/DE",
    "de-statutory-minimum-wage-2022-2027": "employment/DE",
    "de-minijob-earnings-limit-2003-2027": "employment/DE",
    "at-income-tax-brackets-2026": "tax/AT",
    "nl-box1-income-tax-brackets-2026": "tax/NL",
    "nl-statutory-minimum-wage-by-age-2026": "employment/NL",
    "ie-income-tax-rate-bands-and-credits-2026": "tax/IE",
    "ie-universal-social-charge-2026": "tax/IE",
    "ie-prsi-class-a-employee-rate-2025-2026": "tax/IE",
    "es-irpf-state-general-scale-2021": "tax/ES",
    "es-minimum-wage-2026": "employment/ES",
    "es-social-security-contribution-bases-2026": "tax/ES",
    "es-social-security-contribution-rates-2026": "tax/ES",
    "fr-income-tax-bareme-revenus-2025": "tax/FR",
    "pl-pit-tax-scale": "tax/PL",
    "pl-minimum-wage-2026": "employment/PL",
}


def entry(entry_id: str) -> dict:
    return yaml.safe_load((ENTRIES / ENTRY_IDS[entry_id] / f"{entry_id}.yaml").read_text(encoding="utf-8"))


def parameters(entry_id: str) -> dict:
    return entry(entry_id)["spec"]["parameters"]


@pytest.mark.parametrize("entry_id", sorted(ENTRY_IDS))
def test_every_vector_passes(entry_id: str) -> None:
    spec = entry(entry_id)["spec"]
    module = load_rule(spec["implementation"])
    for item in spec["vectors"]:
        assert module.evaluate(spec["parameters"], item["input"]) == item["expected"], item


@pytest.mark.parametrize("entry_id", sorted(ENTRY_IDS))
def test_every_entry_has_a_source_vector(entry_id: str) -> None:
    assert any(item["origin"] == "source" for item in entry(entry_id)["spec"]["vectors"])


class TestGermanTariff:
    params = staticmethod(lambda: parameters("de-income-tax-tariff-2026"))

    def test_nil_up_to_the_basic_allowance(self) -> None:
        params = self.params()
        allowance = params["zones"][0]["upper"]
        assert de_income_tax_tariff.tariff(params, allowance) == 0
        assert de_income_tax_tariff.tariff(params, 0) == 0
        assert de_income_tax_tariff.tariff(params, -500) == 0

    def test_zones_join_without_jumps(self) -> None:
        params = self.params()
        for zone in params["zones"][1:-1]:
            upper = zone["upper"]
            below, above = de_income_tax_tariff.tariff(params, upper), de_income_tax_tariff.tariff(params, upper + 1)
            assert 0 <= above - below <= 1

    def test_tax_never_falls_as_income_rises(self) -> None:
        params = self.params()
        taxes = [de_income_tax_tariff.tariff(params, income) for income in range(0, 400_000, 997)]
        assert taxes == sorted(taxes)

    def test_income_and_tax_are_rounded_down(self) -> None:
        params = self.params()
        assert de_income_tax_tariff.tariff(params, "45000.99") == de_income_tax_tariff.tariff(params, 45000)
        assert isinstance(de_income_tax_tariff.tariff(params, 45000), int)

    def test_splitting_doubles_the_tax_on_half(self) -> None:
        params = self.params()
        assert de_income_tax_tariff.splitting(params, 90000) == 2 * de_income_tax_tariff.tariff(params, 45000)
        assert de_income_tax_tariff.splitting(params, 90001) == 2 * de_income_tax_tariff.tariff(params, 45000)
        assert de_income_tax_tariff.splitting(params, 90000) < de_income_tax_tariff.tariff(params, 90000)

    def test_top_rate_is_the_marginal_rate_far_above_the_last_threshold(self) -> None:
        params = self.params()
        top = Decimal(str(params["zones"][-1]["rate"]))
        assert de_income_tax_tariff.tariff(params, 1_000_100) - de_income_tax_tariff.tariff(params, 1_000_000) == int(top * 100)


class TestSolidaritySurcharge:
    def test_nothing_at_or_below_the_limit(self) -> None:
        params = parameters("de-solidarity-surcharge-2026")
        limit = params["exemption_limit"]["single"]
        assert de_solidarity_surcharge.surcharge(params, limit) == Decimal("0.00")
        assert de_solidarity_surcharge.surcharge(params, params["exemption_limit"]["joint"], joint=True) == Decimal("0.00")

    def test_phase_in_reaches_the_full_rate(self) -> None:
        params = parameters("de-solidarity-surcharge-2026")
        rate, phase = Decimal(str(params["rate_percent"])) / 100, Decimal(str(params["phase_in_percent"])) / 100
        limit = Decimal(str(params["exemption_limit"]["single"]))
        crossover = limit * phase / (phase - rate)
        just_above = de_solidarity_surcharge.surcharge(params, limit + 1)
        assert just_above == (phase * 1).quantize(Decimal("0.01"), rounding="ROUND_DOWN")
        assert de_solidarity_surcharge.surcharge(params, crossover * 2) == (crossover * 2 * rate).quantize(Decimal("0.01"), rounding="ROUND_DOWN")

    def test_fractions_of_a_cent_are_dropped(self) -> None:
        params = parameters("de-solidarity-surcharge-2026")
        assert de_solidarity_surcharge.surcharge(params, "100000.19") == Decimal("5500.01")


class TestCumulativeBracketTariff:
    def test_table_rows_are_continuous_where_the_statute_is(self) -> None:
        params = parameters("es-irpf-state-general-scale-2021")
        for row in params["brackets"][1:]:
            assert cumulative_bracket_tariff.tax_due(params, row["over"]) == Decimal(str(row["base_tax"])).quantize(Decimal("0.01"))

    def test_row_selection_at_the_boundary(self) -> None:
        params = parameters("nl-box1-income-tax-brackets-2026")
        second = params["brackets"][1]["over"]
        assert cumulative_bracket_tariff.marginal_rate(params, second) == params["brackets"][0]["rate_percent"]
        assert cumulative_bracket_tariff.marginal_rate(params, second + 1) == params["brackets"][1]["rate_percent"]

    def test_reduction_never_makes_the_tax_negative(self) -> None:
        params = parameters("pl-pit-tax-scale")
        assert cumulative_bracket_tariff.tax_due(params, 1000) == Decimal("0.00")
        first = params["brackets"][0]
        threshold = Decimal(first["reduction"]) * 100 / Decimal(str(first["rate_percent"]))
        assert cumulative_bracket_tariff.tax_due(params, threshold) == Decimal("0.00")
        assert cumulative_bracket_tariff.tax_due(params, threshold + 100) > 0

    def test_top_bracket_continues_the_first(self) -> None:
        params = parameters("pl-pit-tax-scale")
        over = params["brackets"][1]["over"]
        assert cumulative_bracket_tariff.tax_due(params, over) == Decimal(str(params["brackets"][1]["base_tax"]))


class TestIrishCharges:
    def test_two_income_band_increase_is_capped(self) -> None:
        params = parameters("ie-income-tax-rate-bands-and-credits-2026")
        base = Decimal(str(params["standard_rate_bands"]["married_two_incomes"]))
        cap = Decimal(str(params["two_income_increase_max"]))
        assert ie_income_tax_usc.standard_rate_band(params, "married_two_incomes", 10000) == base + 10000
        assert ie_income_tax_usc.standard_rate_band(params, "married_two_incomes", 10 * cap) == base + cap
        assert ie_income_tax_usc.standard_rate_band(params, "single", 10000) == Decimal(str(params["standard_rate_bands"]["single"]))

    def test_employee_credit_is_limited_by_income(self) -> None:
        params = parameters("ie-income-tax-rate-bands-and-credits-2026")
        low = Decimal(1000)
        assert ie_income_tax_usc.credit_amount(params, "employee", low) == low * Decimal(params["employee_credit_cap_percent"]) / 100

    def test_usc_slices_add_up(self) -> None:
        params = parameters("ie-universal-social-charge-2026")
        enacted = sum(Decimal(str(s["slice"])) for s in params["slices_as_enacted"])
        assert Decimal(str(params["bands"][-2]["up_to"])) == enacted
        assert ie_income_tax_usc.usc(params, 0) == Decimal("0.00")

    def test_round_to_euro_option(self) -> None:
        params = parameters("ie-universal-social-charge-2026")
        exact = ie_income_tax_usc.evaluate(params, {"income": 50000})
        rounded = ie_income_tax_usc.evaluate(params, {"income": 50000, "round": "euro"})
        assert Decimal(rounded) == Decimal(exact).quantize(Decimal(1), rounding="ROUND_HALF_UP")

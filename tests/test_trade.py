from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from almanac.models import Statistic
from almanac.rules import consumption_tax

SCHEDULE = {"slabs": {"standard": 9, "zero": 0}}
REDUCED = {"slabs": {"standard": 10, "reduced": 8}, "rounding": "1"}


def test_slab_membership_and_names():
    assert consumption_tax.is_slab(9, SCHEDULE)
    assert consumption_tax.is_slab("0", SCHEDULE)
    assert not consumption_tax.is_slab(8, SCHEDULE)
    assert consumption_tax.slab_name(9.0, SCHEDULE) == "standard"
    with pytest.raises(KeyError):
        consumption_tax.slab_name(7, SCHEDULE)


def test_tax_on_tax_exclusive_amounts():
    assert consumption_tax.tax_on_net(40, SCHEDULE) == Decimal("3.60")
    assert consumption_tax.gross_from_net(40, SCHEDULE) == Decimal("43.60")
    assert consumption_tax.tax_on_net(1000, REDUCED, "reduced") == Decimal(80)


def test_tax_fraction_is_in_lowest_terms():
    assert consumption_tax.tax_fraction(SCHEDULE, "standard") == Fraction(9, 109)
    assert consumption_tax.tax_fraction({"slabs": {"standard": 10}}, "standard") == Fraction(1, 11)
    assert consumption_tax.tax_fraction({"slabs": {"standard": 8.1}}, "standard") == Fraction(81, 1081)


def test_tax_within_tax_inclusive_amounts():
    assert consumption_tax.tax_in_gross("43.60", SCHEDULE) == Decimal("3.60")
    assert consumption_tax.tax_in_gross(110, {"slabs": {"standard": 10}}) == Decimal("10.00")
    assert consumption_tax.tax_in_gross(0, SCHEDULE, "zero") == Decimal("0.00")


def test_evaluate_dispatches_on_input_shape():
    assert consumption_tax.evaluate(SCHEDULE, 9) is True
    assert consumption_tax.evaluate(SCHEDULE, {"net": 200, "slab": "standard"}) == "18.00"
    assert consumption_tax.evaluate(SCHEDULE, {"gross": "43.60"}) == "3.60"
    with pytest.raises(ValueError):
        consumption_tax.evaluate(SCHEDULE, {"slab": "standard"})
    with pytest.raises(KeyError):
        consumption_tax.evaluate(SCHEDULE, {"net": 1, "slab": "reduced"})


def test_statistics():
    assert consumption_tax.statistic(SCHEDULE, Statistic.parse("count")) == 2
    assert consumption_tax.statistic(SCHEDULE, Statistic.parse("slab[standard]")) == 9.0
    assert consumption_tax.statistic(SCHEDULE, Statistic.parse("tax_fraction[standard]")) == pytest.approx(9 / 109)
    with pytest.raises(ValueError):
        consumption_tax.statistic(SCHEDULE, Statistic.parse("mean"))

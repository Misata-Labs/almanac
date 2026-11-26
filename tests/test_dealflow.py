from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from almanac.models import Statistic
from almanac.rules import us_hsr_premerger as hsr

ENTRY = Path(__file__).resolve().parent.parent / "entries/deals/US/us-hsr-premerger-thresholds-and-filing-fees-2026.yaml"

# A small schedule with round numbers, so the boundary behaviour is easy to read.
TOY = {
    "size_of_transaction": {"all_transactions_above_usd": 500, "size_of_person_test_above_usd": 100},
    "size_of_person": {"smaller_person_usd": 10, "larger_person_usd": 100},
    "filing_fees": [
        {"from_usd": 0, "below_usd": 200, "fee_usd": 1},
        {"from_usd": 200, "below_usd": 1000, "fee_usd": 2},
        {"from_usd": 1000, "below_usd": None, "fee_usd": 3},
    ],
}


@pytest.fixture(scope="module")
def published() -> dict:
    return yaml.safe_load(ENTRY.read_text(encoding="utf-8"))["spec"]["parameters"]


def test_fee_tiers_have_inclusive_lower_bounds():
    assert hsr.filing_fee(0, TOY) == 1
    assert hsr.filing_fee(199, TOY) == 1
    assert hsr.filing_fee(200, TOY) == 2
    assert hsr.filing_fee(999, TOY) == 2
    assert hsr.filing_fee(10**12, TOY) == 3


def test_transaction_thresholds_are_strict():
    assert hsr.transaction_band(100, TOY) == hsr.NOT_REPORTABLE
    assert hsr.transaction_band(101, TOY) == hsr.REPORTABLE_IF_SIZE_OF_PERSON
    assert hsr.transaction_band(500, TOY) == hsr.REPORTABLE_IF_SIZE_OF_PERSON
    assert hsr.transaction_band(501, TOY) == hsr.REPORTABLE


def test_size_of_person_tests():
    big = {"annual_net_sales_usd": 100}
    small = {"total_assets_usd": 10}
    assert hsr.meets_size_of_person(big, {"manufacturing": True, "annual_net_sales_usd": 10}, TOY)
    assert not hsr.meets_size_of_person(big, {"manufacturing": False, "annual_net_sales_usd": 10}, TOY)
    assert hsr.meets_size_of_person(big, {"manufacturing": False, "total_assets_usd": 10}, TOY)
    assert hsr.meets_size_of_person(small, {"annual_net_sales_usd": 100}, TOY)
    assert not hsr.meets_size_of_person({"total_assets_usd": 9}, {"annual_net_sales_usd": 100}, TOY)


def test_reportability_needs_parties_only_in_the_middle_band():
    assert hsr.is_reportable(501, None, None, TOY)
    assert not hsr.is_reportable(100, None, None, TOY)
    with pytest.raises(ValueError):
        hsr.is_reportable(300, None, None, TOY)
    assert hsr.is_reportable(300, {"annual_net_sales_usd": 100}, {"manufacturing": True, "total_assets_usd": 10}, TOY)


def test_negative_amounts_are_rejected():
    with pytest.raises(ValueError):
        hsr.filing_fee(-1, TOY)


def test_evaluate_dispatches_on_query_shape():
    assert hsr.evaluate(TOY, 250) == 2
    assert hsr.evaluate(TOY, {"fee": 1000}) == 3
    assert hsr.evaluate(TOY, {"band": 50}) == hsr.NOT_REPORTABLE
    with pytest.raises(ValueError):
        hsr.evaluate(TOY, {"unknown": 1})


def test_published_schedule_is_contiguous_and_rising(published):
    tiers = published["filing_fees"]
    assert tiers[0]["from_usd"] == 0 and tiers[-1]["below_usd"] is None
    for lower, upper in zip(tiers, tiers[1:]):
        assert lower["below_usd"] == upper["from_usd"]
        assert lower["fee_usd"] < upper["fee_usd"]


def test_published_thresholds_are_ordered(published):
    transaction = published["size_of_transaction"]
    person = published["size_of_person"]
    assert transaction["size_of_person_test_above_usd"] < transaction["all_transactions_above_usd"]
    assert person["smaller_person_usd"] < person["larger_person_usd"]


def test_statistics(published):
    assert hsr.statistic(published, Statistic(name="tier_count")) == len(published["filing_fees"])
    top = published["filing_fees"][-1]
    assert hsr.statistic(published, Statistic(name="fee", args=(str(top["from_usd"]),))) == top["fee_usd"]
    with pytest.raises(ValueError):
        hsr.statistic(published, Statistic(name="median"))

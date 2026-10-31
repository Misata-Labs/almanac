from __future__ import annotations

from datetime import date

import pytest

from almanac import cli
from almanac.api import Almanac
from almanac.catalogue import render_card, render_catalogue
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def almanac() -> Almanac:
    return Almanac.load(REPO_ROOT / "entries")


def test_load_reads_every_entry(almanac):
    assert len(almanac) >= 10
    assert "gb-utr-check-digit" in almanac
    assert almanac.ids() == sorted(almanac.ids())


def test_get_unknown_id(almanac):
    with pytest.raises(KeyError):
        almanac.get("nope")


def test_select_by_date_region_and_domain(almanac):
    on_day = almanac.select(on=date(2026, 6, 15), region="GB", domain="calendar")
    assert {e.id for e in on_day} == {"gb-bank-holidays", "gb-clock-change"}
    assert almanac.select(on=date(2018, 1, 1), domain="calendar") == []
    assert all(e.status == "verified" for e in almanac.select(status="verified"))
    assert all(e.region == "BR" for e in almanac.select(region="BR"))


def test_bound_rule_evaluates_and_exposes_helpers(almanac):
    utr = almanac.rule("gb-utr-check-digit")
    assert utr.evaluate({"reference": "2234567890K", "scheme": "sa"}) is True
    assert utr.call("check_digit", "234567890") == "2"
    holidays = almanac.rule("gb-bank-holidays")
    assert holidays.call("is_bank_holiday", date(2026, 12, 28), division="england-and-wales") is True
    with pytest.raises(KeyError):
        almanac.rule("missing")


def test_cards_and_catalogue_render(almanac):
    card = render_card(almanac.get("gb-nino-format"))
    assert "HM Revenue & Customs" in card and "sha256" in card and "assumed" in card
    table = render_catalogue(almanac)
    assert table.count("\n| ") >= len(almanac) + 1
    assert "entries/identifiers/GB/gb-nino-format.yaml" in table


def test_cli_list_show_applies_catalogue(capsys, tmp_path):
    assert cli.main(["list"]) == 0
    assert "gb-nino-format" in capsys.readouterr().out
    assert cli.main(["show", "gb-clock-change"]) == 0
    assert "last Sunday" in capsys.readouterr().out
    assert cli.main(["show", "missing"]) == 2
    assert cli.main(["applies", "--on", "2026-10-30", "--region", "BR"]) == 0
    assert "br-pix-identifier-formats" in capsys.readouterr().out
    target = tmp_path / "CATALOGUE.md"
    assert cli.main(["catalogue", "--write", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("# Catalogue")


def test_committed_catalogue_is_current(almanac):
    committed = (REPO_ROOT / "CATALOGUE.md").read_text(encoding="utf-8")
    assert committed == render_catalogue(almanac), "run: uv run almanac catalogue --write CATALOGUE.md"

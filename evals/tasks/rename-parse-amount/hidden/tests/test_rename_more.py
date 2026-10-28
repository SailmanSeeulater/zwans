import pytest

import ledger.money
from ledger.budget import Budget
from ledger.cli import main
from ledger.importer import read_rows
from ledger.invoice import render_invoice


def test_parse_amount_edge_cases() -> None:
    assert ledger.money.parse_amount(" .5 ") == 50
    assert ledger.money.parse_amount("(-1.00)") == 100
    with pytest.raises(ValueError):
        ledger.money.parse_amount("")
    with pytest.raises(ValueError):
        ledger.money.parse_amount("1.2x")


def test_read_rows() -> None:
    assert read_rows("2024-01-01, coffee ,-2.40\n") == [("2024-01-01", "coffee", -240)]


def test_render_invoice() -> None:
    assert render_invoice([(3, "1,000")], discount="0.01") == "3 x 1,000\ntotal 2,999.99"


def test_budget_remaining() -> None:
    budget = Budget({"rent": "$900"})
    budget.spend("rent", "(100)")
    assert budget.remaining("rent") == 100000


def test_cli_rejects_junk(capsys) -> None:
    assert main(["1", "abc"]) == 1
    assert "not an amount" in capsys.readouterr().err

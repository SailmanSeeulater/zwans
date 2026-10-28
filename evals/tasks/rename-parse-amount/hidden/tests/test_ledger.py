from ledger.budget import Budget
from ledger.cli import main
from ledger.importer import balance
from ledger.invoice import invoice_total


def test_invoice_total() -> None:
    assert invoice_total([(2, "3.50"), (1, "10")], discount="1.00") == 1600


def test_balance() -> None:
    export = "date,description,amount\n2024-01-02,rent,(800)\n2024-01-03,pay,1500.25\n"
    assert balance(export, opening="100") == 80025


def test_budget() -> None:
    budget = Budget({"food": "200", "fun": "50"})
    budget.spend("fun", "60.50")
    assert budget.over_budget() == ["fun"]


def test_cli(capsys) -> None:
    assert main(["12.50", "(2.25)"]) == 0
    assert capsys.readouterr().out == "10.25\n"

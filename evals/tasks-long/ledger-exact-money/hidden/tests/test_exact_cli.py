"""Rule 8: the CLI reads every amount form, shows amounts as today, and --json has strings."""

import json


def setup(cli) -> None:
    assert cli("account", "add", "Checking", "--opening", "0.70")[0] == 0
    assert cli("account", "add", "Yen", "--currency", "JPY", "--opening", "15,000")[0] == 0
    for amount in ("-0.10", "(0.20)", "1,234.56", "19.99-"):
        code, _, err = cli("add", "Checking", amount, "--date", "2026-03-02", "--payee", "X")
        assert code == 0, err


def test_cli_reads_every_form(cli) -> None:
    setup(cli)
    code, out, _ = cli("balance", "Checking")
    assert code == 0 and "1,214.97 EUR" in out
    assert "15,000 JPY" in cli("balance", "Yen")[1]


def test_cli_refuses_extra_places(cli) -> None:
    setup(cli)
    code, _, err = cli("add", "Checking", "0.125")
    assert code == 1 and err.startswith("billfold:")
    assert "1,214.97 EUR" in cli("balance", "Checking")[1]


def test_balance_json_has_strings(cli) -> None:
    setup(cli)
    rows = json.loads(cli("balance", "--json")[1])
    assert {r["account"]: r["balance"] for r in rows} == {"Checking": "1214.97", "Yen": "15000"}


def test_list_json_has_strings(cli) -> None:
    setup(cli)
    txns = json.loads(cli("list", "Checking", "--json")[1])
    assert [t["amount"] for t in txns] == ["-0.10", "-0.20", "1234.56", "-19.99"]


def test_report_json_has_strings(cli) -> None:
    setup(cli)
    report = json.loads(cli("report", "monthly", "2026-03", "--json")[1])
    assert report["expenses"] == "20.29" and report["income"] == "1234.56"
    cli("rate", "set", "EUR", "JPY", "161.5", "--date", "2026-01-01")
    yen = json.loads(
        cli("report", "networth", "--currency", "JPY", "--on", "2026-03-31", "--json")[1])
    assert yen["accounts"][1]["balance"] == "15000"
    assert yen["accounts"][0]["converted"] == "196218"
    assert yen["total"] == "211218"


def test_cli_transfer_with_a_rate_and_convert(cli) -> None:
    setup(cli)
    cli("account", "add", "Dollars", "--currency", "USD")
    code, _, err = cli("transfer", "Checking", "Dollars", "10.50", "--rate", "0.25",
                       "--date", "2026-03-03")
    assert code == 0, err
    assert "2.63 USD" in cli("balance", "Dollars")[1]
    cli("rate", "set", "EUR", "USD", "0.25", "--date", "2026-01-01")
    code, out, _ = cli("convert", "10.70", "EUR", "USD", "--date", "2026-03-01")
    assert code == 0 and "2.68 USD" in out


def test_cli_budget_allocate_and_recurring(cli) -> None:
    setup(cli)
    code, out, _ = cli("budget", "allocate", "2026-04", "100.00", "A=1", "B=1", "C=1")
    assert code == 0
    assert out.split() == ["A:", "33.34", "B:", "33.33", "C:", "33.33"]
    cli("recurring", "add", "Checking", "Insurer", "-100.00", "monthly", "2026-03-10",
        "--instalments", "3")
    cli("recurring", "run", "--until", "2026-05-31")
    txns = json.loads(cli("list", "Checking", "--json")[1])
    assert [t["amount"] for t in txns if t["payee"] == "Insurer"] == ["-33.34", "-33.33", "-33.33"]


def test_cli_large_transaction_alert(cli) -> None:
    setup(cli)
    assert cli("alert", "999.99")[0] == 0
    code, _, err = cli("add", "Checking", "-999.99", "--payee", "Sofa", "--date", "2026-03-05")
    assert code == 0 and "large transaction" in err and "-999.99" in err


def test_cli_reconcile(cli) -> None:
    setup(cli)
    txns = json.loads(cli("list", "Checking", "--json")[1])
    args = []
    for txn in txns[:2]:
        args += ["--clear", txn["id"]]
    code, out, _ = cli("reconcile", "Checking", "0.40", "--on", "2026-03-31", *args)
    assert code == 0 and "reconciled at 0.40" in out
    code, out, _ = cli("reconcile", "Checking", "0.41", "--on", "2026-03-31")
    assert code == 0 and "off by +0.01" in out

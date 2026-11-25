import json
from pathlib import Path


def setup(cli) -> None:
    assert cli("account", "add", "Checking", "--opening", "1000")[0] == 0
    assert cli("account", "add", "Savings", "--kind", "savings")[0] == 0
    cli("add", "Checking", "-42.50", "--payee", "REWE Markt", "--category", "Food",
        "--date", "2026-03-02")
    cli("add", "Checking", "2500", "--payee", "ACME", "--category", "Salary",
        "--date", "2026-03-03")


def test_balance(cli) -> None:
    setup(cli)
    code, out, _ = cli("balance")
    assert code == 0
    assert "Checking" in out and "3,457.50 EUR" in out


def test_balance_json(cli) -> None:
    setup(cli)
    _, out, _ = cli("balance", "Checking", "--json")
    (row,) = json.loads(out)
    assert row["account"] == "Checking" and float(row["balance"]) == 3457.5


def test_transfer_and_undo(cli) -> None:
    setup(cli)
    assert cli("transfer", "Checking", "Savings", "457.50", "--date", "2026-03-04")[0] == 0
    assert "3,000.00 EUR" in cli("balance", "Checking")[1]
    assert cli("undo")[0] == 0
    assert "3,457.50 EUR" in cli("balance", "Checking")[1]


def test_monthly_report(cli) -> None:
    setup(cli)
    code, out, _ = cli("report", "monthly", "2026-03")
    assert code == 0
    assert "2,500.00" in out and "42.50" in out


def test_budget_alert_goes_to_stderr_and_the_jsonl_file(cli) -> None:
    setup(cli)
    cli("budget", "set", "Food", "2026-03", "50")
    code, _, err = cli("add", "Checking", "-10.00", "--category", "Food", "--date", "2026-03-05")
    assert code == 0 and "over budget" in err
    lines = (Path(cli.path).parent / "alerts.jsonl").read_text("utf-8").splitlines()
    assert json.loads(lines[-1])["type"] == "budget.exceeded"


def test_errors_are_one_line(cli) -> None:
    code, _, err = cli("add", "Nowhere", "-1.00")
    assert code == 1 and err.startswith("billfold: no account")


def test_export_and_backup(cli, tmp_path: Path) -> None:
    setup(cli)
    assert cli("export", "qif", str(tmp_path / "out.qif"))[0] == 0
    assert "T-42.50" in (tmp_path / "out.qif").read_text("utf-8")
    code, out, _ = cli("backup", "create")
    assert code == 0 and "billfold-2026" in out

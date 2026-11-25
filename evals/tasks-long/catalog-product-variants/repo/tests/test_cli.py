import csv
import io
import json


def setup_shop(cli) -> None:
    for argv in (
        ("category", "add", "kitchen", "Kitchen"),
        ("warehouse", "add", "MAIN", "Main warehouse"),
        ("warehouse", "add", "WEST", "West store", "--priority", "1"),
        (
            "product", "add", "MUG-01", "Blue mug", "--price", "12.50", "--category", "kitchen",
            "--barcode", "5012345678900", "--reorder-level", "5", "--cost", "4.00",
        ),
        ("product", "add", "TEA-07", "Green tea", "--price", "4.50", "--tax-class", "reduced"),
        ("receive", "MUG-01", "8", "--warehouse", "MAIN", "--ref", "PO-1"),
        ("receive", "TEA-07", "30", "-w", "WEST"),
    ):
        code, out, err = cli(*argv)
        assert code == 0, err


def test_selling_from_the_command_line(cli) -> None:
    setup_shop(cli)
    assert cli("cart", "new")[1].strip() == "C0001"
    assert cli("cart", "add", "C0001", "MUG-01", "4")[0] == 0
    assert cli("cart", "add", "C0001", "TEA-07")[0] == 0
    code, out, _ = cli("cart", "show", "C0001")
    assert "Blue mug" in out and "total 54.50 GBP" in out
    code, out, _ = cli("checkout", "C0001", "--customer", "Ann Lee")
    assert out.strip() == "Order SO-000001: 5 items, 54.50 GBP"
    code, out, _ = cli("invoice", "create", "SO-000001")
    assert out.strip() == "Invoice INV-2026-0001: 64.73 GBP including VAT"
    code, out, _ = cli("invoice", "show", "INV-2026-0001")
    assert "5012345678900" in out
    code, out, _ = cli("alerts")
    assert out.startswith("MUG-01")


def test_stock_commands(cli) -> None:
    setup_shop(cli)
    assert cli("transfer", "MUG-01", "3", "--from", "MAIN", "--to", "WEST")[0] == 0
    assert cli("count", "MUG-01", "4", "-w", "MAIN")[0] == 0
    code, out, _ = cli("stock", "MUG-01")
    assert out.split() == ["MAIN", "4", "WEST", "3", "total", "7"]
    code, out, _ = cli("product", "show", "MUG-01")
    assert "12.50 GBP" in out and "MAIN:4" in out and "5012345678900" in out


def test_errors_are_one_line_and_exit_1(cli) -> None:
    setup_shop(cli)
    code, out, err = cli("receive", "NOPE", "1", "-w", "MAIN")
    assert code == 1 and err == "error: No product with SKU 'NOPE'.\n"
    code, out, err = cli("cart", "add", "C0009", "MUG-01")
    assert code == 1 and err.startswith("error: No cart")


def test_reports_and_feed(cli, tmp_path) -> None:
    setup_shop(cli)
    cli("cart", "new")
    cli("cart", "add", "C0001", "MUG-01", "2")
    cli("checkout", "C0001", "--customer", "Ann")
    code, out, _ = cli("report", "sales", "--csv")
    assert list(csv.reader(io.StringIO(out))) == [
        ["sku", "name", "units", "revenue", "orders"],
        ["MUG-01", "Blue mug", "2", "25.00", "1"],
    ]
    code, out, _ = cli("report", "stock")
    assert "MUG-01" in out and "TEA-07" in out
    code, out, _ = cli("report", "valuation", "--csv")
    assert ["MUG-01", "Blue mug", "6", "4.00", "24.00"] in list(csv.reader(io.StringIO(out)))
    code, out, _ = cli("feed", "csv", "--out", str(tmp_path / "feed.csv"))
    assert out.strip().startswith("Wrote 2 items")
    code, out, _ = cli("search", "tea", "--facets")
    assert out.splitlines()[0].startswith("TEA-07")


def test_import_and_backup(cli, tmp_path) -> None:
    setup_shop(cli)
    supplier = tmp_path / "acme.csv"
    supplier.write_text("sku,name,price\nCUP-03,Paper cup,0.30\nMUG-01,Blue mug,13.00\n")
    code, out, _ = cli("import", str(supplier), "--supplier", "Acme", "--dry-run")
    assert out.startswith("1 new, 1 updated")
    assert "CUP-03" not in cli("product", "list")[1]
    cli("import", str(supplier), "--supplier", "Acme")
    assert "CUP-03" in cli("product", "list")[1]
    code, out, _ = cli("backup", "create", "--dir", str(tmp_path / "b"))
    backup = out.split()[-1]
    cli("product", "update", "MUG-01", "--set", "price=1.00")
    assert cli("backup", "restore", backup)[0] == 0
    assert "13.00 GBP" in cli("product", "show", "MUG-01")[1]


def test_outbox_flush(cli, tmp_path) -> None:
    setup_shop(cli)
    cli("cart", "new")
    cli("cart", "add", "C0001", "MUG-01", "3")
    cli("checkout", "C0001", "--customer", "Ann")
    target = tmp_path / "out.jsonl"
    code, out, _ = cli("outbox", "flush", "--to", str(target))
    lines = [json.loads(line) for line in target.read_text().splitlines()]
    assert [n["topic"] for n in lines] == ["stock.low", "order.placed"]
    assert lines[0]["payload"]["sku"] == "MUG-01"
    assert cli("outbox", "list")[1] == ""

import json


def test_a_day_in_the_stockroom(cli) -> None:
    assert cli("add", "MUG-01", "Blue mug", "--cost", "4.25", "--reorder-level", "10") == (
        0,
        "added MUG-01\n",
        "",
    )
    assert (
        cli("receive", "MUG-01", "40", "--ref", "PO-1001")[1]
        == "MV-000001: MUG-01 +40, on hand 40\n"
    )
    assert cli("ship", "MUG-01", "31")[1] == "MV-000002: MUG-01 -31, on hand 9\n"
    assert cli("count", "MUG-01", "8")[1] == "MV-000003: MUG-01 adjusted by -1, on hand 8\n"

    code, out, _ = cli("show", "MUG-01")
    assert "on hand: 8 pcs" in out.splitlines()
    assert cli("list")[1] == "MUG-01  8  Blue mug\n"
    assert cli("search", "blue")[1] == "MUG-01  Blue mug\n"
    assert cli("low")[1] == "MUG-01  Blue mug  on hand 8  reorder level 10  order 3\n"
    assert cli("alerts")[1] == "2026-03-01T09:00:00Z  MUG-01  on hand 9 (reorder level 10)\n"
    assert cli("value")[1].splitlines()[-1].split() == ["total", "34.00"]
    assert len(cli("history", "--sku", "MUG-01")[1].splitlines()) == 4


def test_cli_errors(cli) -> None:
    cli("add", "MUG-01", "Blue mug", "--cost", "4.25")
    assert cli("add", "MUG-01", "Again", "--cost", "1")[0] == 4
    assert cli("ship", "MUG-01", "1")[0] == 5
    assert cli("show", "NOPE-1")[0] == 3
    code, _, err = cli("add", "X", "Bad", "--cost", "1")
    assert (code, err.startswith("error: ")) == (2, True)


def test_cli_import_and_snapshot(cli, tmp_path) -> None:
    csv_file = tmp_path / "products.csv"
    csv_file.write_text(
        "sku,name,unit_cost,opening_stock\nMUG-01,Blue mug,4.25,40\nKET-02,Red kettle,19.99,3\n",
        "utf-8",
    )
    assert cli("import", str(csv_file)) == (0, "imported 2 products\n", "")
    data = json.loads(cli("snapshot")[1])
    assert [(p["sku"], p["on_hand"]) for p in data["products"]] == [("KET-02", 3), ("MUG-01", 40)]

import json

import pytest
from conftest import Clock, stock_up
from stockroom import Database, Inventory
from stockroom.errors import DuplicateSku, InsufficientStock, UnknownSku
from stockroom.importer import import_products


def shops(db: Database) -> tuple[Inventory, Inventory]:
    return Inventory(db, tenant="acme", clock=Clock()), Inventory(
        db, tenant="globex", clock=Clock()
    )


def skus(products) -> list[str]:
    return [p.sku for p in products]


def names(products) -> list[str]:
    return [p.name for p in products]


def test_the_default_tenant_is_what_you_get_without_one(db) -> None:
    Inventory(db).add_product("MUG-01", "Blue mug", 425)
    assert skus(Inventory(db, tenant="default").all_products()) == ["MUG-01"]
    assert Inventory(db, tenant="acme").all_products() == []


def test_each_tenant_has_its_own_skus(db) -> None:
    acme, globex = shops(db)
    acme.add_product("MUG-01", "Blue mug", 425)
    globex.add_product("MUG-01", "Red kettle", 1999)
    with pytest.raises(DuplicateSku):
        acme.add_product("MUG-01", "Again", 1)
    assert acme.product("MUG-01").name == "Blue mug"
    assert globex.product("MUG-01").name == "Red kettle"
    assert names(acme.all_products()) == ["Blue mug"]
    assert names(globex.all_products()) == ["Red kettle"]


def test_a_cached_lookup_never_leaks_to_another_tenant(db) -> None:
    acme, globex = shops(db)
    acme.add_product("MUG-01", "Blue mug", 425)
    acme.add_product("CUP-03", "Paper cup", 10)
    assert acme.product("MUG-01").name == "Blue mug"
    assert acme.product("CUP-03").name == "Paper cup"

    with pytest.raises(UnknownSku):
        globex.product("CUP-03")
    with pytest.raises(UnknownSku):
        globex.receive("CUP-03", 5)
    globex.add_product("MUG-01", "Red kettle", 1999)
    assert globex.product("MUG-01").name == "Red kettle"
    assert acme.product("MUG-01").name == "Blue mug"

    acme.rename("MUG-01", "Navy mug")
    assert globex.product("MUG-01").name == "Red kettle"
    assert acme.product("MUG-01").name == "Navy mug"


def test_stock_belongs_to_one_tenant(db) -> None:
    acme, globex = shops(db)
    for shop in (acme, globex):
        shop.add_product("MUG-01", "Mug", 425, reorder_level=5)
    acme.receive("MUG-01", 40)
    globex.receive("MUG-01", 3)

    assert (acme.on_hand("MUG-01"), globex.on_hand("MUG-01")) == (40, 3)
    with pytest.raises(InsufficientStock):
        globex.ship("MUG-01", 4)
    assert len(acme.history()) == 1
    assert len(globex.history("MUG-01")) == 1
    assert acme.count("MUG-01", 40) is None
    assert [(p.sku, q) for p, q in globex.levels()] == [("MUG-01", 3)]


def test_search_only_finds_your_own_products(db) -> None:
    acme, globex = shops(db)
    acme.add_product("MUG-01", "Blue mug", 425)
    acme.add_product("TEA-07", "Green tea", 350)
    globex.add_product("MUG-01", "Red kettle", 1999)

    assert names(acme.search("blue")) == ["Blue mug"]
    assert names(acme.search("mug")) == ["Blue mug"]
    assert names(globex.search("mug")) == ["Red kettle"]
    assert globex.search("blue") == []
    assert globex.search("tea") == []
    assert acme.search("kettle") == []


def test_removing_a_product_leaves_other_tenants_alone(db) -> None:
    acme, globex = shops(db)
    acme.add_product("MUG-01", "Blue mug", 425)
    globex.add_product("MUG-01", "Red kettle", 1999)
    globex.receive("MUG-01", 2)
    globex.product("MUG-01")

    acme.remove_product("MUG-01")  # globex's history for its own MUG-01 does not count
    with pytest.raises(UnknownSku):
        acme.product("MUG-01")
    assert globex.product("MUG-01").name == "Red kettle"
    assert names(globex.search("kettle")) == ["Red kettle"]
    assert acme.search("mug") == []


def test_a_rollback_keeps_tenants_apart(db) -> None:
    acme, globex = shops(db)
    acme.add_product("MUG-01", "Blue mug", 425)
    globex.add_product("MUG-01", "Red kettle", 1999)
    with pytest.raises(DuplicateSku):
        import_products(acme, "sku,name,unit_cost\nCUP-03,Paper cup,0.10\nMUG-01,Again,1\n")

    assert names(acme.search("mug")) == ["Blue mug"]
    assert names(globex.search("kettle")) == ["Red kettle"]
    assert acme.product("MUG-01").name == "Blue mug"
    assert globex.product("MUG-01").name == "Red kettle"
    assert skus(acme.all_products()) == ["MUG-01"]


def test_imports_go_to_the_tenant_doing_them(db) -> None:
    acme, globex = shops(db)
    globex.add_product("MUG-01", "Red kettle", 1999)
    import_products(acme, "sku,name,unit_cost,opening_stock\nMUG-01,Blue mug,4.25,40\n")
    assert acme.on_hand("MUG-01") == 40
    assert globex.on_hand("MUG-01") == 0


def test_alerts_low_stock_and_valuation_are_per_tenant(db) -> None:
    acme, globex = shops(db)
    stock_up(acme)
    globex.add_product("MUG-01", "Mug", 100, reorder_level=1)
    globex.receive("MUG-01", 2)
    globex.ship("MUG-01", 1)
    acme.ship("KET-02", 4)

    assert [a.sku for a in acme.alerts()] == ["KET-02"]
    assert [(a.sku, a.on_hand) for a in globex.alerts()] == [("MUG-01", 1)]
    assert [(p.sku, q) for p, q in acme.low_stock()] == [("KET-02", 1)]
    assert [(p.sku, q) for p, q in globex.low_stock()] == [("MUG-01", 1)]
    assert acme.valuation_cents() == 40 * 425 + 1 * 1999
    assert globex.valuation_cents() == 100


def test_tenants_survive_reopening(tmp_path) -> None:
    path = tmp_path / "stock.json"
    acme, globex = shops(Database(path))
    acme.add_product("MUG-01", "Blue mug", 425)
    globex.add_product("MUG-01", "Red kettle", 1999)
    acme.receive("MUG-01", 7)

    acme, globex = shops(Database(path))
    assert names(acme.search("mug")) == ["Blue mug"]
    assert names(globex.search("mug")) == ["Red kettle"]
    assert (acme.on_hand("MUG-01"), globex.on_hand("MUG-01")) == (7, 0)
    assert Inventory(Database(path)).all_products() == []


def test_old_databases_belong_to_the_default_tenant(legacy_file) -> None:
    db = Database(legacy_file)
    acme = Inventory(db, tenant="acme", clock=Clock())
    assert acme.all_products() == []
    assert acme.search("mug") == []
    assert acme.alerts() == []
    with pytest.raises(UnknownSku):
        acme.product("MUG-01")
    acme.add_product("MUG-01", "Acme mug", 500)
    acme.receive("MUG-01", 3)

    old = Inventory(Database(legacy_file), clock=Clock())
    assert [(p.sku, q) for p, q in old.levels()] == [("KET-02", 2), ("MUG-01", 9), ("TEA-07", 118)]
    assert old.product("MUG-01").name == "Blue mug"
    assert [a.sku for a in old.alerts()] == ["MUG-01", "KET-02"]
    assert old.valuation_cents() == 49123
    assert names(Inventory(Database(legacy_file), tenant="acme").search("mug")) == ["Acme mug"]


# ------------------------------------------------------------------------- CLI


def test_the_cli_takes_a_tenant(cli, tmp_path) -> None:
    acme = ("--tenant", "acme")
    globex = ("--tenant", "globex")
    assert (
        cli(*acme, "add", "MUG-01", "Blue mug", "--cost", "4.25", "--reorder-level", "10")[0] == 0
    )
    assert (
        cli(*globex, "add", "MUG-01", "Red kettle", "--cost", "19.99", "--reorder-level", "2")[0]
        == 0
    )
    assert cli(*acme, "receive", "MUG-01", "40")[0] == 0
    assert cli(*globex, "receive", "MUG-01", "3")[0] == 0
    assert cli(*acme, "ship", "MUG-01", "31")[0] == 0
    assert cli(*globex, "ship", "MUG-01", "1")[0] == 0

    assert cli(*acme, "list")[1] == "MUG-01  9  Blue mug\n"
    assert cli(*globex, "list")[1] == "MUG-01  2  Red kettle\n"
    assert cli("list")[1] == ""
    assert cli(*globex, "search", "mug")[1] == "MUG-01  Red kettle\n"
    assert cli(*globex, "search", "blue")[1] == ""
    assert "on hand: 2 pcs" in cli(*globex, "show", "MUG-01")[1].splitlines()


def test_cli_reports_are_per_tenant(cli, tmp_path) -> None:
    acme = ("--tenant", "acme")
    globex = ("--tenant", "globex")
    cli(*acme, "add", "MUG-01", "Blue mug", "--cost", "4.25", "--reorder-level", "10")
    cli(*globex, "add", "MUG-01", "Red kettle", "--cost", "19.99", "--reorder-level", "2")
    cli(*globex, "add", "TEA-07", "Green tea", "--cost", "3.50")
    cli(*acme, "receive", "MUG-01", "40")
    cli(*acme, "ship", "MUG-01", "31")
    cli(*globex, "receive", "MUG-01", "3")
    cli(*globex, "ship", "MUG-01", "1")

    assert cli(*acme, "value")[1].splitlines()[-1].split() == ["total", "38.25"]
    assert cli(*globex, "value")[1].splitlines()[-1].split() == ["total", "39.98"]
    assert [line.split()[0] for line in cli(*globex, "value")[1].splitlines()[1:-1]] == [
        "MUG-01",
        "TEA-07",
    ]
    assert cli("value")[1].splitlines()[-1].split() == ["total", "0.00"]

    assert cli(*acme, "low")[1] == "MUG-01  Blue mug  on hand 9  reorder level 10  order 2\n"
    assert cli(*globex, "low")[1] == "MUG-01  Red kettle  on hand 2  reorder level 2  order 1\n"
    assert cli(*acme, "alerts")[1].split()[1:4] == ["MUG-01", "on", "hand"]
    assert len(cli(*globex, "alerts")[1].splitlines()) == 1
    assert cli("alerts")[1] == "no alerts\n"

    acme_history = cli(*acme, "history")[1].splitlines()
    assert len(acme_history) == 3
    assert [row.split(",")[3] for row in acme_history[1:]] == ["40", "-31"]
    assert len(cli(*globex, "history", "--sku", "MUG-01")[1].splitlines()) == 3
    assert cli(*globex, "history", "--sku", "TEA-07")[1].splitlines() == ["id,sku,kind,qty,ref,at"]

    snapshot = json.loads(cli(*globex, "snapshot")[1])
    assert [(p["name"], p["on_hand"]) for p in snapshot["products"]] == [
        ("Red kettle", 2),
        ("Green tea", 0),
    ]

    csv_file = tmp_path / "more.csv"
    csv_file.write_text("sku,name,unit_cost\nTEA-07,Black tea,2.00\n", "utf-8")
    assert cli(*acme, "import", str(csv_file))[0] == 0
    assert cli(*acme, "show", "TEA-07")[1].splitlines()[1] == "name: Black tea"
    assert cli(*globex, "show", "TEA-07")[1].splitlines()[1] == "name: Green tea"

import json

import pytest
from conftest import Clock, sell

from shopdesk import Shop
from shopdesk.errors import StoreError
from shopdesk.reports import sales_report, stock_report, valuation
from shopdesk.store import FORMAT_VERSION, create_backup, list_backups, restore_backup


def test_a_shop_survives_saving_and_opening(stocked, tmp_path) -> None:
    stocked.set_list_price("trade", "MUG-01", 900)
    stocked.add_discount("TEN", "percent", 10, auto=True)
    number = sell(stocked, "Ann", ("MUG-01", 22), ("TEA-07", 1))
    stocked.invoice_order(number)
    path = tmp_path / "shop.json"
    stocked.save(path)

    again = Shop.open(path, clock=Clock())
    assert [p.sku for p in again.products()] == ["KET-02", "MUG-01", "TEA-07"]
    assert again.ledger.by_warehouse("MUG-01") == {"MAIN": 0, "WEST": 3}
    assert again.order(number).lines[0].allocations[1].warehouse == "WEST"
    assert again.invoice("INV-2026-0001").gross_total == stocked.invoice("INV-2026-0001").gross_total
    assert again.price_of("MUG-01", "trade") == 900
    assert sales_report(again) == sales_report(stocked)
    assert again.search("mug").hits == ["MUG-01"]
    assert json.loads(path.read_text())["version"] == FORMAT_VERSION


def test_a_missing_file_is_an_empty_shop(tmp_path) -> None:
    shop = Shop.open(tmp_path / "new.json")
    assert shop.products() == []


def test_files_from_a_newer_release_or_another_program_are_refused(tmp_path) -> None:
    path = tmp_path / "shop.json"
    path.write_text(json.dumps({"format": "shopdesk", "version": 99}))
    with pytest.raises(StoreError):
        Shop.open(path)
    path.write_text(json.dumps({"format": "spreadsheet", "version": 1}))
    with pytest.raises(StoreError):
        Shop.open(path)
    path.write_text("{not json")
    with pytest.raises(StoreError):
        Shop.open(path)


def test_a_version_1_file_opens(old_file) -> None:
    shop = Shop.open(old_file("shop-v1.json"), clock=Clock())
    mug = shop.product("MUG-01")
    assert (mug.price, mug.cost, mug.reorder_level) == (1100, 400, 5)
    assert shop.product("JUG-04").price == 1850
    assert shop.ledger.by_warehouse("MUG-01") == {"MAIN": 12}
    assert shop.lookup_barcode("5012345678948") == "JUG-04"
    order = shop.order("SO-000001")
    assert [(line.sku, line.unit_price, line.net) for line in order.lines] == [
        ("MUG-01", 1100, 2200),
        ("JUG-04", 1850, 1850),
    ]
    assert [(r.sku, r.units, r.revenue) for r in sales_report(shop)] == [
        ("MUG-01", 2, 2200),
        ("JUG-04", 1, 1850),
    ]
    assert shop.settings.shop_name == "Corner Shop"


def test_a_version_1_shop_keeps_working_and_saves_as_current(old_file) -> None:
    path = old_file("shop-v1.json")
    shop = Shop.open(path, clock=Clock())
    shop.receive("JUG-04", "MAIN", 2)
    cart = shop.new_cart()
    shop.cart_add(cart, "MUG-01", 8)
    assert shop.checkout(cart, "Dee").number == "SO-000003"
    assert [a.sku for a in shop.alerts()] == ["MUG-01"]
    shop.save()
    again = Shop.open(path, clock=Clock())
    assert again.stock("MUG-01") == 4
    assert json.loads(path.read_text())["version"] == FORMAT_VERSION


def test_a_version_2_file_opens(old_file) -> None:
    shop = Shop.open(old_file("shop-v2.json"), clock=Clock())
    assert [p.sku for p in shop.products()] == ["KET-02", "MUG-01", "TEA-07", "TEE-01"]
    assert shop.stock("TEE-01") == 2
    assert [a.sku for a in shop.alerts()] == ["TEE-01"]
    assert [(r.sku, r.units, r.revenue) for r in sales_report(shop)] == [
        ("TEE-01", 8, 12000),
        ("MUG-01", 12, 11500),
        ("KET-02", 1, 3999),
        ("TEA-07", 5, 1800),
    ]
    assert {r.sku: r.total for r in stock_report(shop)}["MUG-01"] == 13
    assert valuation(shop)[1] == 2 * 600 + 13 * 400 + 5 * 2100 + 35 * 150
    assert shop.invoice("INV-2026-0001").lines[0].gtin == "5012345678900"
    assert shop.cart("C0005").lines[0].sku == "TEE-01"


def test_backups_restore(stocked, tmp_path) -> None:
    path = tmp_path / "shop.json"
    stocked.save(path)
    backup = create_backup(path, tmp_path / "backups", Clock())
    assert list_backups(tmp_path / "backups") == [backup]
    stocked.receive("TEA-07", "MAIN", 5)
    stocked.save()
    restore_backup(backup, path)
    assert Shop.open(path).stock("TEA-07") == 40


def test_a_backup_of_an_old_file_restores(old_file, tmp_path) -> None:
    backup = old_file("shop-v1.json")
    path = tmp_path / "live.json"
    restore_backup(backup, path)
    assert Shop.open(path).product("MUG-01").price == 1100


def test_restoring_something_that_isnt_a_backup_is_refused(tmp_path) -> None:
    junk = tmp_path / "junk.json"
    junk.write_text(json.dumps({"format": "shopdesk", "version": 2, "products": [{"sku": 1}]}))
    path = tmp_path / "shop.json"
    path.write_text("{}")
    with pytest.raises(StoreError):
        restore_backup(junk, path)
    assert path.read_text() == "{}"

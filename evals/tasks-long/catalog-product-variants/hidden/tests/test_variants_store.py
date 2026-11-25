from conftest import Clock, TEE_EAN, sell

from shopdesk import Shop
from shopdesk.reports import sales_report, stock_report
from shopdesk.store import create_backup, restore_backup


def test_variants_survive_saving_and_opening(dressed, tmp_path) -> None:
    dressed.add_variant("MUG-01", "MUG-01-GRN", {"glaze": "green"}, price=1350, reorder_level=1)
    number = sell(dressed, "Ann", ("TEE-M-RED", 8), ("TEE-S-RED", 1))
    path = tmp_path / "shop.json"
    dressed.save(path)

    again = Shop.open(path, clock=Clock())
    tee = again.product("TEE-M-BLUE")
    assert [(v.sku, v.options, v.price, v.barcode, v.reorder_level) for v in tee.variants] == [
        ("TEE-S-RED", {"size": "S", "colour": "red"}, None, TEE_EAN["TEE-S-RED"], None),
        ("TEE-M-RED", {"size": "M", "colour": "red"}, None, TEE_EAN["TEE-M-RED"], 5),
        ("TEE-M-BLUE", {"size": "M", "colour": "blue"}, 1700, TEE_EAN["TEE-M-BLUE"], None),
    ]
    assert [v.sku for v in again.product("MUG-01").variants] == ["MUG-01", "MUG-01-GRN"]
    assert again.price_of("MUG-01-GRN") == 1350
    assert again.ledger.by_warehouse("TEE-M-RED") == {"MAIN": 0, "WEST": 4}
    assert [l.product_sku for l in again.order(number).lines] == ["TEE-01", "TEE-01"]
    assert again.lookup_barcode(TEE_EAN["TEE-M-BLUE"]) == "TEE-M-BLUE"
    assert sales_report(again) == sales_report(dressed)
    assert again.search("tee-s-red").hits == ["TEE-01"]


def test_an_opened_shop_still_knows_which_sku_is_whose(dressed, tmp_path) -> None:
    path = tmp_path / "shop.json"
    dressed.save(path)
    again = Shop.open(path, clock=Clock())
    again.receive("TEE-M-BLUE", "MAIN", 2)
    assert again.stock("TEE-M-BLUE") == 8
    cart = again.new_cart()
    again.cart_add(cart, "TEE-S-RED", 8)
    again.checkout(cart, "Ann")
    assert [a.sku for a in again.alerts()] == ["TEE-S-RED"]


def test_a_version_1_file_opens_with_single_variant_products(old_file) -> None:
    shop = Shop.open(old_file("shop-v1.json"), clock=Clock())
    mug = shop.product("MUG-01")
    [variant] = mug.variants
    assert (variant.sku, variant.options, variant.barcode) == ("MUG-01", {}, "5012345678900")
    assert shop.product("OLD-99").variants[0].barcode is None
    assert shop.price_of("JUG-04") == 1850
    assert [l.product_sku for l in shop.order("SO-000001").lines] == ["MUG-01", "JUG-04"]
    assert [(r.sku, r.name, r.units) for r in sales_report(shop)] == [
        ("MUG-01", "Blue mug", 2),
        ("JUG-04", "Milk jug", 1),
    ]


def test_a_version_2_file_opens_with_single_variant_products(old_file) -> None:
    shop = Shop.open(old_file("shop-v2.json"), clock=Clock())
    assert [[v.sku for v in p.variants] for p in shop.products()] == [
        ["KET-02"], ["MUG-01"], ["TEA-07"], ["TEE-01"],
    ]
    assert shop.variant("TEE-01").barcode == "5012345678955"
    assert shop.lookup_barcode("5012345678955") == "TEE-01"
    assert [(l.sku, l.product_sku) for l in shop.order("SO-000002").lines] == [
        ("MUG-01", "MUG-01"),
        ("KET-02", "KET-02"),
    ]
    invoice = shop.invoice("INV-2026-0001")
    assert [(l.sku, l.product_sku, l.gtin) for l in invoice.lines] == [
        ("MUG-01", "MUG-01", "5012345678900"),
        ("KET-02", "KET-02", "5012345678917"),
    ]
    assert [(r.sku, r.units) for r in sales_report(shop)] == [
        ("TEE-01", 8), ("MUG-01", 12), ("KET-02", 1), ("TEA-07", 5),
    ]
    assert [(r.sku, r.units) for r in sales_report(shop, by_variant=True)] == [
        ("TEE-01", 8), ("MUG-01", 12), ("KET-02", 1), ("TEA-07", 5),
    ]
    assert shop.price_of("MUG-01", "trade") == 900
    assert shop.cart("C0005").lines[0].name == "Logo tee"


def test_old_products_can_grow_variants(old_file) -> None:
    path = old_file("shop-v2.json")
    shop = Shop.open(path, clock=Clock())
    shop.add_variant("TEE-01", "TEE-01-XL", {"size": "XL"}, price=1700)
    shop.receive("TEE-01-XL", "MAIN", 3)
    cart = shop.new_cart()
    shop.cart_add(cart, "TEE-01-XL", 1)
    shop.cart_add(cart, "TEE-01", 1)
    order = shop.checkout(cart, "Dee")
    assert [(l.sku, l.product_sku, l.name) for l in order.lines] == [
        ("TEE-01-XL", "TEE-01", "Logo tee (size: XL)"),
        ("TEE-01", "TEE-01", "Logo tee"),
    ]
    shop.save()
    again = Shop.open(path, clock=Clock())
    assert [v.sku for v in again.product("TEE-01").variants] == ["TEE-01", "TEE-01-XL"]
    assert [(r.sku, r.units) for r in sales_report(again)][0] == ("TEE-01", 10)
    assert {r.sku for r in stock_report(again)} >= {"TEE-01", "TEE-01-XL"}


def test_a_backup_of_a_shop_with_variants_restores(dressed, tmp_path) -> None:
    path = tmp_path / "shop.json"
    dressed.save(path)
    backup = create_backup(path, tmp_path / "backups", Clock())
    dressed.adjust("TEE-M-BLUE", "WEST", -6)
    dressed.save()
    restore_backup(backup, path)
    again = Shop.open(path, clock=Clock())
    assert again.stock("TEE-M-BLUE") == 6
    assert len(again.product("TEE-01").variants) == 3


def test_a_backup_of_a_version_2_file_restores(old_file, tmp_path) -> None:
    path = tmp_path / "live.json"
    restore_backup(old_file("shop-v2.json"), path)
    assert Shop.open(path, clock=Clock()).variant("MUG-01").barcode == "5012345678900"

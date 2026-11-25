import csv
import io
import xml.etree.ElementTree as ET

from conftest import KETTLE_EAN, TEE_EAN, sell


def csv_rows(shop) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(shop.feed_csv())))


def xml_items(shop) -> list[ET.Element]:
    return ET.fromstring(shop.feed_xml()).findall("item")


def test_the_csv_feed_has_one_row_per_variant(dressed) -> None:
    rows = csv_rows(dressed)
    assert [(r["id"], r["item_group_id"]) for r in rows] == [
        ("KET-02", "KET-02"),
        ("MUG-01", "MUG-01"),
        ("TEA-07", "TEA-07"),
        ("TEE-S-RED", "TEE-01"),
        ("TEE-M-RED", "TEE-01"),
        ("TEE-M-BLUE", "TEE-01"),
    ]
    blue = rows[5]
    assert blue["title"] == "Logo tee (colour: blue, size: M)"
    assert blue["price"] == "17.00 GBP"
    assert blue["gtin"] == TEE_EAN["TEE-M-BLUE"]
    assert blue["options"] == "colour=blue;size=M"
    assert blue["brand"] == "Shopdesk"
    assert blue["product_type"] == "Clothing"
    assert rows[3]["price"] == "15.00 GBP"


def test_single_variant_products_look_as_before_plus_a_group(dressed) -> None:
    kettle = csv_rows(dressed)[0]
    assert kettle["title"] == "Red kettle"
    assert kettle["gtin"] == KETTLE_EAN
    assert kettle["options"] == ""
    assert kettle["price"] == "39.99 GBP"


def test_availability_is_each_variants_own(dressed) -> None:
    sell(dressed, "Ann", ("TEE-M-BLUE", 6))
    rows = {r["id"]: r["availability"] for r in csv_rows(dressed)}
    assert rows["TEE-M-BLUE"] == "out of stock"
    assert rows["TEE-M-RED"] == "in stock"
    assert rows["TEE-S-RED"] == "in stock"


def test_sale_prices_per_variant_from_a_product_discount(dressed) -> None:
    dressed.add_discount("TEEWEEK", "percent", 10, target_kind="product", target="TEE-01", auto=True)
    rows = {r["id"]: r for r in csv_rows(dressed)}
    assert rows["TEE-S-RED"]["sale_price"] == "13.50 GBP"
    assert rows["TEE-M-BLUE"]["sale_price"] == "15.30 GBP"
    assert rows["MUG-01"]["sale_price"] == ""


def test_the_xml_feed_has_groups_and_options(dressed) -> None:
    items = xml_items(dressed)
    assert [i.findtext("id") for i in items] == [
        "KET-02", "MUG-01", "TEA-07", "TEE-S-RED", "TEE-M-RED", "TEE-M-BLUE",
    ]
    assert [i.findtext("item_group_id") for i in items] == [
        "KET-02", "MUG-01", "TEA-07", "TEE-01", "TEE-01", "TEE-01",
    ]
    red = items[3]
    assert red.findtext("title") == "Logo tee (colour: red, size: S)"
    assert red.findtext("gtin") == TEE_EAN["TEE-S-RED"]
    assert red.findtext("price") == "15.00 GBP"
    assert [(o.get("name"), o.text) for o in red.findall("option")] == [
        ("colour", "red"),
        ("size", "S"),
    ]
    assert items[0].findall("option") == []


def test_the_xml_feed_marks_availability_per_variant(dressed) -> None:
    sell(dressed, "Ann", ("TEE-S-RED", 10))
    items = {i.findtext("id"): i for i in xml_items(dressed)}
    assert items["TEE-S-RED"].findtext("availability") == "out of stock"
    assert items["TEE-M-RED"].findtext("availability") == "in stock"


def test_inactive_products_leave_the_feed_with_all_their_variants(dressed) -> None:
    dressed.catalog.set_active("TEE-01", False)
    assert [r["id"] for r in csv_rows(dressed)] == ["KET-02", "MUG-01", "TEA-07"]
    assert len(xml_items(dressed)) == 3

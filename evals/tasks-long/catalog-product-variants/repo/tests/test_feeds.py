import csv
import io
import xml.etree.ElementTree as ET

from conftest import MUG_EAN, sell


def xml_items(shop) -> list[dict[str, str]]:
    root = ET.fromstring(shop.feed_xml())
    return [{child.tag: child.text for child in item} for item in root.findall("item")]


def csv_items(shop) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(shop.feed_csv())))


def test_the_xml_feed_has_one_item_per_active_product(stocked) -> None:
    stocked.catalog.set_active("KET-02", False)
    items = xml_items(stocked)
    assert [i["id"] for i in items] == ["MUG-01", "TEA-07"]
    mug = items[0]
    assert mug["title"] == "Blue mug"
    assert mug["description"] == "A blue stoneware mug."
    assert mug["link"] == "https://shop.example.com/p/mug-01"
    assert mug["price"] == "12.50 GBP"
    assert mug["availability"] == "in stock"
    assert mug["gtin"] == MUG_EAN
    assert mug["brand"] == "Potter"
    assert mug["product_type"] == "Home > Kitchen"
    assert "sale_price" not in mug


def test_the_xml_feed_escapes_text(stocked) -> None:
    tea = xml_items(stocked)[2]
    assert tea["brand"] == "Leaf & Co"
    assert "Leaf &amp; Co" in stocked.feed_xml()


def test_the_csv_feed_matches_the_xml_feed(stocked) -> None:
    rows = csv_items(stocked)
    assert [r["id"] for r in rows] == ["KET-02", "MUG-01", "TEA-07"]
    assert rows[1]["price"] == "12.50 GBP"
    assert rows[1]["sale_price"] == ""
    assert rows[1]["gtin"] == MUG_EAN


def test_availability_follows_stock(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 6))
    rows = {r["id"]: r for r in csv_items(stocked)}
    assert rows["KET-02"]["availability"] == "out of stock"
    assert rows["MUG-01"]["availability"] == "in stock"


def test_sale_price_from_automatic_discounts_only(stocked) -> None:
    stocked.add_discount("TEATIME", "percent", 20, target_kind="product", target="TEA-07", auto=True)
    stocked.add_discount("KITCHEN", "amount", 100, target_kind="category", target="kitchen")
    rows = {r["id"]: r for r in csv_items(stocked)}
    assert rows["TEA-07"]["sale_price"] == "3.60 GBP"
    assert rows["MUG-01"]["sale_price"] == ""


def test_long_titles_are_cut_at_a_word(stocked) -> None:
    stocked.settings.set("feed_title_limit", "20")
    stocked.add_product("LONG-1", "A very long product name indeed", 100)
    rows = {r["id"]: r for r in csv_items(stocked)}
    assert rows["LONG-1"]["title"] == "A very long product…"


def test_the_feed_uses_the_shop_currency_and_url(stocked) -> None:
    stocked.settings.set("currency", "eur")
    stocked.settings.set("base_url", "https://example.org/")
    mug = xml_items(stocked)[1]
    assert mug["price"] == "12.50 EUR"
    assert mug["link"] == "https://example.org/p/mug-01"

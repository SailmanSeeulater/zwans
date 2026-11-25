import pytest
from conftest import KETTLE_EAN, MUG_EAN

from shopdesk.errors import (
    DuplicateBarcode,
    DuplicateSku,
    InvalidInput,
    UnknownCategory,
    UnknownSku,
)


def test_a_product_is_found_by_its_sku_in_any_case(stocked) -> None:
    assert stocked.product("mug-01").name == "Blue mug"
    assert stocked.product("MUG-01").price == 1250


def test_skus_are_unique_and_well_formed(stocked) -> None:
    with pytest.raises(DuplicateSku):
        stocked.add_product("mug-01", "Another mug", 100)
    with pytest.raises(InvalidInput):
        stocked.add_product("MUG 01", "Spaced", 100)
    with pytest.raises(InvalidInput):
        stocked.add_product("-MUG", "Dash first", 100)


def test_unknown_skus_say_so(stocked) -> None:
    with pytest.raises(UnknownSku):
        stocked.product("NOPE-1")
    with pytest.raises(UnknownSku):
        stocked.receive("NOPE-1", "MAIN", 1)


def test_barcodes_are_checked_and_unique(stocked) -> None:
    with pytest.raises(InvalidInput):
        stocked.add_product("CUP-03", "Cup", 300, barcode="5012345678901")
    with pytest.raises(DuplicateBarcode):
        stocked.add_product("CUP-03", "Cup", 300, barcode=MUG_EAN)
    stocked.add_product("CUP-03", "Cup", 300, barcode="5012345678931")
    assert stocked.lookup_barcode("5012345678931") == "CUP-03"


def test_barcode_lookup(stocked) -> None:
    assert stocked.lookup_barcode(MUG_EAN) == "MUG-01"
    assert stocked.lookup_barcode(KETTLE_EAN[:6] + " " + KETTLE_EAN[6:]) == "KET-02"
    with pytest.raises(InvalidInput):
        stocked.lookup_barcode("5012345678931")


def test_prices_are_whole_cents_and_not_negative(stocked) -> None:
    with pytest.raises(InvalidInput):
        stocked.add_product("CUP-03", "Cup", -1)
    with pytest.raises(InvalidInput):
        stocked.add_product("CUP-03", "Cup", 2.5)


def test_update_changes_only_what_is_asked(stocked) -> None:
    stocked.update_product("MUG-01", price=1300, name="  Blue   mug, large ")
    product = stocked.product("MUG-01")
    assert (product.price, product.name, product.brand) == (1300, "Blue mug, large", "Potter")
    with pytest.raises(InvalidInput):
        stocked.update_product("MUG-01", colour="red")
    with pytest.raises(UnknownCategory):
        stocked.update_product("MUG-01", category="garden")


def test_categories_nest(stocked) -> None:
    stocked.add_category("mugs", "Mugs", "kitchen")
    assert stocked.categories.breadcrumb("mugs") == "Home > Kitchen > Mugs"
    assert stocked.categories.descendants("home") == {"home", "kitchen", "mugs"}
    with pytest.raises(InvalidInput):
        stocked.categories.move("home", "mugs")


def test_products_in_a_category_include_subcategories(stocked) -> None:
    assert [p.sku for p in stocked.catalog.in_category("home")] == ["KET-02", "MUG-01"]
    stocked.catalog.set_active("KET-02", False)
    assert [p.sku for p in stocked.catalog.in_category("home")] == ["MUG-01"]


def test_inactive_products_are_listed_only_on_request(stocked) -> None:
    stocked.catalog.set_active("TEA-07", False)
    assert [p.sku for p in stocked.products(active_only=True)] == ["KET-02", "MUG-01"]
    assert len(stocked.products()) == 3


def test_changes_land_in_the_audit_log(stocked) -> None:
    stocked.update_product("MUG-01", price=1300)
    entries = stocked.audit.entries(subject="MUG-01", action="product")
    assert [e.action for e in entries] == ["product.added", "product.changed"]
    assert entries[-1].detail["fields"] == ["price"]

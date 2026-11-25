import pytest
from conftest import MUG_EAN, TEE_EAN

from shopdesk.errors import DuplicateBarcode, DuplicateSku, ShopError, UnknownSku


def test_a_product_made_without_variants_has_one_with_its_own_sku(stocked) -> None:
    [variant] = stocked.product("MUG-01").variants
    assert (variant.sku, variant.options, variant.barcode) == ("MUG-01", {}, MUG_EAN)
    assert stocked.variant("MUG-01").sku == "MUG-01"
    assert stocked.price_of("MUG-01") == 1250


def test_a_product_made_with_variants_has_exactly_those(dressed) -> None:
    tee = dressed.product("TEE-01")
    assert [v.sku for v in tee.variants] == ["TEE-S-RED", "TEE-M-RED", "TEE-M-BLUE"]
    assert tee.variants[0].options == {"size": "S", "colour": "red"}
    assert tee.variants[1].reorder_level == 5
    assert tee.variants[2].price == 1700
    assert tee.variants[2].barcode == TEE_EAN["TEE-M-BLUE"]


def test_a_variant_sku_finds_its_product(dressed) -> None:
    assert dressed.product("tee-m-blue").sku == "TEE-01"
    assert dressed.variant("TEE-M-BLUE").options == {"size": "M", "colour": "blue"}
    with pytest.raises(ShopError):
        dressed.variant("TEE-L-RED")


def test_added_variants_come_last(dressed) -> None:
    dressed.add_variant("TEE-01", "TEE-L-RED", {"size": "L", "colour": "red"}, price=1600)
    dressed.add_variant("MUG-01", "MUG-01-GRN", {"glaze": "green"})
    assert [v.sku for v in dressed.product("TEE-01").variants][-1] == "TEE-L-RED"
    assert [v.sku for v in dressed.product("MUG-01").variants] == ["MUG-01", "MUG-01-GRN"]
    assert dressed.price_of("TEE-L-RED") == 1600
    assert dressed.price_of("MUG-01-GRN") == 1250


def test_variant_skus_are_unique_across_the_shop(dressed) -> None:
    with pytest.raises(DuplicateSku):
        dressed.add_variant("MUG-01", "TEE-S-RED", {"glaze": "red"})
    with pytest.raises(DuplicateSku):
        dressed.add_variant("TEE-01", "KET-02", {"size": "XL"})
    with pytest.raises(DuplicateSku):
        dressed.add_product("TEE-M-RED", "Clash", 100)
    with pytest.raises(ShopError):
        dressed.add_variant("TEE-01", "bad sku", {"size": "XL"})


def test_barcodes_are_unique_across_variants(dressed) -> None:
    with pytest.raises(DuplicateBarcode):
        dressed.add_variant("TEE-01", "TEE-L-RED", {"size": "L"}, barcode=MUG_EAN)
    with pytest.raises(DuplicateBarcode):
        dressed.add_product("CUP-03", "Cup", 300, barcode=TEE_EAN["TEE-S-RED"])
    assert dressed.lookup_barcode(TEE_EAN["TEE-M-RED"]) == "TEE-M-RED"
    assert dressed.lookup_barcode(MUG_EAN) == "MUG-01"


def test_two_variants_of_a_product_cant_have_the_same_options(dressed) -> None:
    with pytest.raises(ShopError):
        dressed.add_variant("TEE-01", "TEE-M-RED2", {"colour": "red", "size": "M"})


def test_updating_a_variant(dressed) -> None:
    dressed.update_variant("TEE-S-RED", price=1450, barcode="8712345000042", reorder_level=7)
    variant = dressed.variant("TEE-S-RED")
    assert (variant.price, variant.barcode, variant.reorder_level) == (1450, "8712345000042", 7)
    assert dressed.lookup_barcode("8712345000042") == "TEE-S-RED"
    dressed.update_variant("TEE-S-RED", options={"size": "S", "colour": "crimson"})
    assert dressed.variant("TEE-S-RED").options["colour"] == "crimson"
    dressed.update_variant("TEE-S-RED", price=None)
    assert dressed.price_of("TEE-S-RED") == 1500


def test_removing_variants(dressed) -> None:
    with pytest.raises(ShopError):
        dressed.remove_variant("TEE-M-BLUE")  # still has stock
    dressed.adjust("TEE-M-BLUE", "WEST", -6)
    dressed.remove_variant("TEE-M-BLUE")
    assert [v.sku for v in dressed.product("TEE-01").variants] == ["TEE-S-RED", "TEE-M-RED"]
    with pytest.raises(ShopError):
        dressed.variant("TEE-M-BLUE")
    dressed.adjust("MUG-01", "MAIN", -20)
    dressed.adjust("MUG-01", "WEST", -5)
    with pytest.raises(ShopError):
        dressed.remove_variant("MUG-01")  # the product's last variant


def test_a_product_sku_that_is_not_a_variant_cant_be_sold_or_stocked(dressed) -> None:
    with pytest.raises(UnknownSku):
        dressed.cart_add(dressed.new_cart(), "TEE-01")
    with pytest.raises(UnknownSku):
        dressed.receive("TEE-01", "MAIN", 1)
    with pytest.raises(UnknownSku):
        dressed.stock("TEE-01")
    with pytest.raises(UnknownSku):
        dressed.price_of("TEE-01")
    with pytest.raises(UnknownSku):
        dressed.count("TEE-01", "MAIN", 3)
    with pytest.raises(UnknownSku):
        dressed.transfer("TEE-01", "MAIN", "WEST", 1)

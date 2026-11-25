import pytest

from shopdesk.errors import UnknownSku

HOODIES = """sku,parent_sku,options,name,price,ean,category,brand
HOOD-M,HOOD-1,size=M,Zip hoodie,35.00,8712345000059,Clothing,Shopdesk
HOOD-L,HOOD-1,size=L,Zip hoodie,35.00,8712345000066,Clothing,Shopdesk
HOOD-XL,HOOD-1,size=XL,Zip hoodie,38.00,,Clothing,Shopdesk
"""


def test_rows_with_a_parent_become_variants_of_one_product(dressed) -> None:
    result = dressed.import_supplier(HOODIES, "Knitwear Ltd")
    assert result.errors == []
    assert result.created == ["HOOD-M", "HOOD-L", "HOOD-XL"]
    hoodie = dressed.product("HOOD-1")
    assert (hoodie.name, hoodie.price, hoodie.category, hoodie.brand) == (
        "Zip hoodie", 3500, "clothing", "Shopdesk",
    )
    assert [(v.sku, v.options) for v in hoodie.variants] == [
        ("HOOD-M", {"size": "M"}),
        ("HOOD-L", {"size": "L"}),
        ("HOOD-XL", {"size": "XL"}),
    ]
    assert [dressed.price_of(v.sku) for v in hoodie.variants] == [3500, 3500, 3800]
    assert dressed.lookup_barcode("8712345000066") == "HOOD-L"
    with pytest.raises(UnknownSku):
        dressed.receive("HOOD-1", "MAIN", 1)
    dressed.receive("HOOD-L", "MAIN", 4)
    assert dressed.stock("HOOD-L") == 4


def test_importing_the_same_variants_again_changes_nothing(dressed) -> None:
    dressed.import_supplier(HOODIES, "Knitwear Ltd")
    again = dressed.import_supplier(HOODIES, "Knitwear Ltd")
    assert (again.created, again.updated) == ([], [])
    assert again.unchanged == ["HOOD-M", "HOOD-L", "HOOD-XL"]
    assert len(dressed.product("HOOD-1").variants) == 3


def test_existing_variants_get_the_rows_price_and_barcode(dressed) -> None:
    text = (
        "sku,parent_sku,options,price,ean\n"
        "TEE-M-BLUE,TEE-01,size=M;colour=blue,18.00,8712345000073\n"
        "TEE-S-RED,TEE-01,size=S;colour=red,15.00,\n"
        "TEE-L-RED,TEE-01,size=L;colour=red,16.00,\n"
    )
    result = dressed.import_supplier(text, "Acme")
    assert result.errors == []
    # TEE-S-RED inherits 15.00 and the row gives it 15.00 of its own: the shop sells it at
    # the same price either way, so calling that unchanged or updated both fit the README.
    assert "TEE-M-BLUE" in result.updated
    assert sorted(result.updated + result.unchanged) == ["TEE-M-BLUE", "TEE-S-RED"]
    assert result.created == ["TEE-L-RED"]
    assert dressed.price_of("TEE-M-BLUE") == 1800
    assert dressed.lookup_barcode("8712345000073") == "TEE-M-BLUE"
    assert dressed.price_of("TEE-S-RED") == 1500
    assert dressed.price_of("TEE-M-RED") == 1500
    assert dressed.variant("TEE-L-RED").options == {"size": "L", "colour": "red"}
    assert dressed.price_of("TEE-L-RED") == 1600


def test_a_row_without_a_parent_updates_the_variant_with_that_sku(dressed) -> None:
    text = "sku,price,ean\nTEE-S-RED,14.00,8712345000080\nMUG-01,13.00,\n"
    result = dressed.import_supplier(text, "Acme")
    assert result.errors == []
    assert result.created == []
    assert sorted(result.updated) == ["MUG-01", "TEE-S-RED"]
    assert dressed.price_of("TEE-S-RED") == 1400
    assert dressed.price_of("TEE-M-RED") == 1500
    assert dressed.lookup_barcode("8712345000080") == "TEE-S-RED"
    assert dressed.product("TEE-01").price == 1500
    assert dressed.price_of("MUG-01") == 1300
    assert dressed.product("TEE-S-RED").sku == "TEE-01"
    assert len(dressed.products()) == 4


def test_a_dry_run_with_variants_changes_nothing(dressed) -> None:
    result = dressed.import_supplier(HOODIES, "Knitwear Ltd", dry_run=True)
    assert result.created == ["HOOD-M", "HOOD-L", "HOOD-XL"]
    assert result.errors == []
    with pytest.raises(UnknownSku):
        dressed.product("HOOD-1")
    with pytest.raises(UnknownSku):
        dressed.product("HOOD-M")


def test_a_new_parent_needs_a_name_and_price(dressed) -> None:
    text = "sku,parent_sku,options\nCAP-S,CAP-1,size=S\n"
    result = dressed.import_supplier(text, "Acme")
    assert [line for line, _ in result.errors] == [2]
    with pytest.raises(UnknownSku):
        dressed.product("CAP-1")

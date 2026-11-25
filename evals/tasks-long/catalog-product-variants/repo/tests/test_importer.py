import pytest

from shopdesk.errors import SupplierFileError

FILE = """sku,name,price,cost,ean,category,brand
MUG-01,Blue mug,12.50,4.20,,Kitchen,Potter
CUP-03,Paper cup,0.30,0.05,5012345678931,Kitchen,Cuppa
KET-02,Red kettle,41.00,,,,
"""


def test_known_skus_update_and_new_skus_are_created(stocked) -> None:
    result = stocked.import_supplier(FILE, "Acme")
    assert (result.created, result.updated, result.unchanged, result.errors) == (
        ["CUP-03"], ["MUG-01", "KET-02"], [], [],
    )
    assert stocked.product("MUG-01").cost == 420
    assert stocked.product("MUG-01").supplier == "Acme"
    assert stocked.product("KET-02").price == 4100
    cup = stocked.product("CUP-03")
    assert (cup.name, cup.price, cup.category, cup.brand) == ("Paper cup", 30, "kitchen", "Cuppa")
    assert stocked.lookup_barcode("5012345678931") == "CUP-03"
    assert stocked.data.imports[-1].created == 1


def test_importing_the_same_file_again_changes_nothing(stocked) -> None:
    stocked.import_supplier(FILE, "Acme")
    again = stocked.import_supplier(FILE, "Acme")
    assert again.created == [] and again.updated == []
    assert again.unchanged == ["MUG-01", "CUP-03", "KET-02"]


def test_a_dry_run_changes_nothing(stocked) -> None:
    result = stocked.import_supplier(FILE, "Acme", dry_run=True)
    assert result.created == ["CUP-03"]
    assert not stocked.catalog.exists("CUP-03")
    assert stocked.product("KET-02").price == 3999
    assert stocked.data.imports == []
    assert "would be" in result.summary()


def test_bad_rows_are_reported_and_skipped(stocked) -> None:
    text = (
        "code;title;rrp;gtin\n"
        "PEN-1;Pen;1,20;\n"
        "PAD 2;Pad;2.00;\n"
        "INK-3;Ink;lots;\n"
        "NIB-4;;0.50;\n"
        "PEN-1;Pen again;1.30;\n"
        "BAD-5;Bad barcode;1.00;5012345678901\n"
    )
    result = stocked.import_supplier(text, "Pens Ltd")
    assert result.created == ["PEN-1"]
    assert [line for line, _ in result.errors] == [3, 4, 5, 6, 7]
    assert stocked.product("PEN-1").price == 120


def test_unknown_categories_are_errors_unless_asked_to_create_them(stocked) -> None:
    text = "sku,name,price,category\nPOT-9,Plant pot,6.00,Garden Things\n"
    assert stocked.import_supplier(text, "Acme").errors == [(2, "Unknown category 'Garden Things'.")]
    result = stocked.import_supplier(text, "Acme", create_categories=True)
    assert result.created == ["POT-9"]
    assert stocked.product("POT-9").category == "garden-things"


def test_files_without_a_sku_column_are_refused(stocked) -> None:
    with pytest.raises(SupplierFileError):
        stocked.import_supplier("name,price\nPen,1.00\n", "Acme")
    with pytest.raises(SupplierFileError):
        stocked.import_supplier("", "Acme")


def test_an_import_rebuilds_search_once_everything_is_in(stocked) -> None:
    stocked.search("cup")
    stocked.import_supplier(FILE, "Acme")
    assert stocked.search("cup").hits == ["CUP-03"]

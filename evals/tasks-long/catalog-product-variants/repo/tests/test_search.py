import pytest
from conftest import MUG_EAN, sell

from shopdesk.errors import InvalidInput


def test_text_search_matches_names_brands_and_categories(stocked) -> None:
    assert stocked.search("mug").hits == ["MUG-01"]
    assert stocked.search("mugs").hits == ["MUG-01"]
    assert stocked.search("boilco").hits == ["KET-02"]
    assert stocked.search("kitchen").hits == ["MUG-01", "KET-02"]
    assert stocked.search("ket").hits == ["KET-02"]
    assert stocked.search("blue kettle").hits == []


def test_search_by_sku_and_barcode(stocked) -> None:
    assert stocked.search("mug-01").hits == ["MUG-01"]
    assert stocked.search(MUG_EAN).hits == ["MUG-01"]


def test_whole_word_matches_rank_first(stocked) -> None:
    stocked.add_product("MUGT-1", "Mugtree stand", 1500)
    assert stocked.search("mug").hits == ["MUG-01", "MUGT-1"]


def test_filters(stocked) -> None:
    assert stocked.search(category="home").hits == ["MUG-01", "KET-02"]
    assert stocked.search(brand="potter").hits == ["MUG-01"]
    assert stocked.search(price_min=1000, price_max=2000).hits == ["MUG-01"]
    assert stocked.search(sort="price").hits == ["TEA-07", "MUG-01", "KET-02"]
    assert stocked.search(sort="-price").hits == ["KET-02", "MUG-01", "TEA-07"]
    with pytest.raises(InvalidInput):
        stocked.search(sort="colour")


def test_facets_count_the_results(stocked) -> None:
    facets = stocked.search().facets
    assert facets["category"] == {"kitchen": 2, "pantry": 1}
    assert facets["brand"] == {"Boilco": 1, "Leaf & Co": 1, "Potter": 1}
    assert facets["price"] == {"0-10": 1, "10-25": 1, "25-50": 1, "50+": 0}
    assert facets["in_stock"] == {"yes": 3, "no": 0}
    assert stocked.search("kitchen").facets["category"] == {"kitchen": 2}


def test_stock_changes_reach_the_index(stocked) -> None:
    assert stocked.search(in_stock=True).total == 3
    sell(stocked, "Ann", ("KET-02", 6))
    assert stocked.search(in_stock=False).hits == ["KET-02"]
    stocked.receive("KET-02", "WEST", 1)
    assert stocked.search(in_stock=False).hits == []


def test_catalog_changes_reach_the_index(stocked) -> None:
    stocked.search("blue")
    stocked.update_product("MUG-01", name="Cobalt cup", description="")
    assert stocked.search("blue").hits == []
    assert stocked.search("cobalt").hits == ["MUG-01"]
    stocked.catalog.set_active("MUG-01", False)
    assert stocked.search("cobalt").hits == []
    assert stocked.search("cobalt", include_inactive=True).hits == ["MUG-01"]


def test_price_bands_follow_the_settings(stocked) -> None:
    stocked.settings.set("price_bands", "500,4000")
    assert stocked.search().facets["price"] == {"0-5": 1, "5-40": 2, "40+": 0}

from conftest import TEE_EAN, sell


def add_hoodie(shop) -> None:
    shop.add_product(
        "HOOD-1", "Zip hoodie", 3500, category="clothing", brand="Shopdesk", variants=[
            {"sku": "HOOD-1-M", "options": {"size": "M"}},
            {"sku": "HOOD-1-L", "options": {"size": "L"}},
        ],
    )


def test_one_hit_per_product(dressed) -> None:
    assert dressed.search("tee").hits == ["TEE-01"]
    assert dressed.search("logo").total == 1
    assert dressed.search(category="clothing").hits == ["TEE-01"]


def test_found_by_a_variants_sku_barcode_or_option(dressed) -> None:
    assert dressed.search("tee-m-blue").hits == ["TEE-01"]
    assert dressed.search(TEE_EAN["TEE-S-RED"]).hits == ["TEE-01"]
    assert dressed.search("blue").hits == ["MUG-01", "TEE-01"]


def test_a_product_is_in_stock_while_any_variant_is(dressed) -> None:
    assert "TEE-01" in dressed.search(in_stock=True).hits
    sell(dressed, "Ann", ("TEE-S-RED", 10), ("TEE-M-RED", 12))
    assert "TEE-01" in dressed.search(in_stock=True).hits
    sell(dressed, "Bob", ("TEE-M-BLUE", 6))
    assert dressed.search(in_stock=False).hits == ["TEE-01"]
    dressed.receive("TEE-M-RED", "WEST", 1)
    assert dressed.search(in_stock=False).hits == []


def test_prices_in_search_are_the_lowest_variant_price(dressed) -> None:
    dressed.update_product("TEE-01", price=2600)  # S-RED and M-RED follow; M-BLUE stays 17.00
    assert dressed.search("tee").facets["price"] == {"0-10": 0, "10-25": 1, "25-50": 0, "50+": 0}
    assert dressed.search(price_max=1800, sort="price").hits == ["TEA-07", "MUG-01", "TEE-01"]
    assert "TEE-01" in dressed.search(price_min=1600, price_max=1800).hits
    assert "TEE-01" not in dressed.search(price_min=2000).hits
    assert dressed.search(sort="price").hits == ["TEA-07", "MUG-01", "TEE-01", "KET-02"]


def test_option_facets_count_products(dressed) -> None:
    add_hoodie(dressed)
    facets = dressed.search().facets
    assert facets["options"] == {
        "colour": {"blue": 1, "red": 1},
        "size": {"L": 1, "M": 2, "S": 1},
    }
    assert dressed.search("hoodie").facets["options"] == {"size": {"L": 1, "M": 1}}
    assert dressed.search("kettle").facets["options"] == {}


def test_filtering_by_options(dressed) -> None:
    add_hoodie(dressed)
    assert dressed.search(options={"size": "M"}).hits == ["TEE-01", "HOOD-1"]
    assert dressed.search(options={"size": "M", "colour": "blue"}).hits == ["TEE-01"]
    assert dressed.search(options={"size": "L"}).hits == ["HOOD-1"]
    assert dressed.search(options={"size": "S", "colour": "blue"}).hits == []


def test_variant_changes_reach_the_index(dressed) -> None:
    assert dressed.search("gold").hits == []
    assert dressed.search("tee-xl-gld").hits == []
    dressed.add_variant("TEE-01", "TEE-XL-GLD", {"size": "XL", "colour": "gold"})
    assert dressed.search("gold").hits == ["TEE-01"]
    assert dressed.search("tee-xl-gld").hits == ["TEE-01"]
    assert dressed.search().facets["options"]["size"] == {"M": 1, "S": 1, "XL": 1}
    dressed.update_variant("TEE-M-BLUE", price=900)
    assert dressed.search(price_max=1000).hits == ["TEA-07", "TEE-01"]

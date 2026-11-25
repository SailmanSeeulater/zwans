def cart_of(shop, *lines, price_list=None, code=None):
    cart = shop.new_cart(price_list)
    for sku, qty in lines:
        shop.cart_add(cart, sku, qty)
    if code:
        shop.cart_code(cart, code)
    return shop.cart(cart)


def test_a_variant_costs_its_own_price_or_else_the_products(dressed) -> None:
    assert dressed.price_of("TEE-S-RED") == 1500
    assert dressed.price_of("TEE-M-BLUE") == 1700
    dressed.update_product("TEE-01", price=1600)
    assert dressed.price_of("TEE-S-RED") == 1600
    assert dressed.price_of("TEE-M-RED") == 1600
    assert dressed.price_of("TEE-M-BLUE") == 1700


def test_price_list_entries_for_the_variant_beat_those_for_the_product(dressed) -> None:
    dressed.set_list_price("trade", "TEE-01", 1200)
    dressed.set_list_price("trade", "TEE-M-BLUE", 1100)
    assert dressed.price_of("TEE-S-RED", "trade") == 1200
    assert dressed.price_of("TEE-M-RED", "trade") == 1200
    assert dressed.price_of("TEE-M-BLUE", "trade") == 1100
    assert dressed.price_of("TEE-M-BLUE") == 1700
    view = cart_of(dressed, ("TEE-S-RED", 1), ("TEE-M-BLUE", 2), price_list="trade")
    assert [line.unit_price for line in view.lines] == [1200, 1100]


def test_a_price_list_entry_for_one_variant_leaves_its_siblings_alone(dressed) -> None:
    dressed.set_list_price("staff", "TEE-M-RED", 900)
    assert dressed.price_of("TEE-M-RED", "staff") == 900
    assert dressed.price_of("TEE-S-RED", "staff") == 1500
    assert dressed.price_of("TEE-M-BLUE", "staff") == 1700


def test_a_discount_on_a_product_covers_every_variant(dressed) -> None:
    dressed.add_discount("TEE10", "percent", 10, target_kind="product", target="TEE-01")
    view = cart_of(dressed, ("TEE-S-RED", 2), ("TEE-M-BLUE", 1), ("MUG-01", 1), code="TEE10")
    assert [(line.sku, line.discount) for line in view.lines] == [
        ("TEE-S-RED", 300),
        ("TEE-M-BLUE", 170),
        ("MUG-01", 0),
    ]


def test_an_automatic_product_discount_covers_every_variant(dressed) -> None:
    dressed.add_discount("TEEDAY", "amount", 250, target_kind="product", target="TEE-01", auto=True)
    view = cart_of(dressed, ("TEE-M-RED", 1), ("TEE-M-BLUE", 2))
    assert [line.discount for line in view.lines] == [250, 500]


def test_category_discounts_follow_the_product(dressed) -> None:
    dressed.add_discount("CLOTHES", "percent", 20, target_kind="category", target="clothing", auto=True)
    view = cart_of(dressed, ("TEE-M-BLUE", 1), ("KET-02", 1))
    assert [line.discount for line in view.lines] == [340, 0]

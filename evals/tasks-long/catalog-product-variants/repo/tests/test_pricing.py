import pytest

from shopdesk.errors import InvalidInput, UnknownDiscount


def cart_of(shop, *lines, price_list=None, code=None):
    cart = shop.new_cart(price_list)
    for sku, qty in lines:
        shop.cart_add(cart, sku, qty)
    if code:
        shop.cart_code(cart, code)
    return shop.cart(cart)


def test_price_lists_override_the_normal_price(stocked) -> None:
    stocked.set_list_price("trade", "MUG-01", 900)
    assert stocked.price_of("MUG-01") == 1250
    assert stocked.price_of("MUG-01", "trade") == 900
    assert stocked.price_of("KET-02", "trade") == 3999
    view = cart_of(stocked, ("MUG-01", 2), ("KET-02", 1), price_list="trade")
    assert [line.unit_price for line in view.lines] == [900, 3999]
    assert view.total == 900 * 2 + 3999


def test_a_cart_needs_an_existing_price_list(stocked) -> None:
    with pytest.raises(InvalidInput):
        stocked.new_cart("staff")


def test_percentage_discount_on_a_category_and_below(stocked) -> None:
    stocked.add_discount("HOME10", "percent", 10, target_kind="category", target="home")
    view = cart_of(stocked, ("MUG-01", 3), ("TEA-07", 2), code="HOME10")
    mug, tea = view.lines
    assert (mug.discount, mug.discount_code) == (375, "HOME10")
    assert (tea.discount, tea.discount_code) == (0, None)


def test_codes_only_apply_when_entered(stocked) -> None:
    stocked.add_discount("SAVE5", "amount", 500)
    assert cart_of(stocked, ("KET-02", 1)).discount == 0
    assert cart_of(stocked, ("KET-02", 1), code="save5").discount == 500


def test_automatic_discounts_need_no_code(stocked) -> None:
    stocked.add_discount("TEATIME", "percent", 20, target_kind="product", target="TEA-07", auto=True)
    view = cart_of(stocked, ("TEA-07", 3), ("MUG-01", 1))
    assert [line.discount for line in view.lines] == [270, 0]


def test_the_best_discount_wins_and_they_never_stack(stocked) -> None:
    stocked.add_discount("ALL5", "percent", 5, auto=True)
    stocked.add_discount("MUGS", "amount", 200, target_kind="product", target="MUG-01")
    view = cart_of(stocked, ("MUG-01", 2), code="MUGS")
    assert (view.lines[0].discount, view.lines[0].discount_code) == (400, "MUGS")
    view = cart_of(stocked, ("KET-02", 1), code="MUGS")
    assert (view.lines[0].discount, view.lines[0].discount_code) == (200, "ALL5")


def test_minimum_quantity_is_per_line(stocked) -> None:
    stocked.add_discount("BULK", "percent", 15, min_qty=6, auto=True)
    assert cart_of(stocked, ("TEA-07", 5)).discount == 0
    assert cart_of(stocked, ("TEA-07", 6)).discount == 405


def test_discounts_run_between_dates(stocked) -> None:
    stocked.add_discount("SPRING", "percent", 10, auto=True, starts="2026-03-03", ends="2026-03-31")
    stocked.add_discount("WINTER", "percent", 50, auto=True, ends="2026-02-28")
    assert cart_of(stocked, ("MUG-01", 1)).discount == 0
    stocked.clock.day = "2026-03-03"
    assert cart_of(stocked, ("MUG-01", 1)).discount == 125


def test_amount_discount_never_goes_below_zero(stocked) -> None:
    stocked.add_discount("BIG", "amount", 1000, auto=True)
    assert cart_of(stocked, ("TEA-07", 2)).lines[0].discount == 900


def test_percentages_round_half_up_per_line(stocked) -> None:
    stocked.add_product("PEN-1", "Pen", 25)
    stocked.add_discount("TEN", "percent", 10, auto=True)
    assert cart_of(stocked, ("PEN-1", 1)).lines[0].discount == 3  # 2.5 -> 3
    assert cart_of(stocked, ("PEN-1", 3)).lines[0].discount == 8  # 7.5 -> 8


def test_bad_discounts_are_refused(stocked) -> None:
    with pytest.raises(InvalidInput):
        stocked.add_discount("X", "percent", 120)
    with pytest.raises(InvalidInput):
        stocked.add_discount("X", "bogus", 1)
    with pytest.raises(UnknownDiscount):
        stocked.cart_code(stocked.new_cart(), "NOPE")

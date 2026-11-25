"""Random histories of variant products, checked against variant_model after every step."""

import csv
import io
import random

import pytest
from conftest import Clock
from variant_model import WAREHOUSES, MProduct, Model, MVariant

from shopdesk import Shop
from shopdesk.errors import OutOfStock
from shopdesk.reports import sales_report, stock_report, valuation

SIZES = ("XS", "S", "M", "L", "XL")
COLOURS = ("red", "blue", "green", "black")


def _spec(variant: MVariant) -> dict:
    spec = {"sku": variant.sku, "options": variant.options}
    if variant.price is not None:
        spec["price"] = variant.price
    if variant.reorder is not None:
        spec["reorder_level"] = variant.reorder
    return spec


class Run:
    def __init__(self, seed: int, path) -> None:
        self.rng = random.Random(seed)
        self.path = path
        self.shop = Shop(clock=Clock())
        self.model = Model()
        self.counter = 0
        self.numbers: list[str] = []

    # -- setup -----------------------------------------------------------------------

    def setup(self) -> None:
        shop, model, rng = self.shop, self.model, self.rng
        shop.add_warehouse("WA", "First", 0)
        shop.add_warehouse("WB", "Second", 1)
        for sku, name in (("SHIRT", "Oxford shirt"), ("MUG", "Glazed mug")):
            product = MProduct(
                sku, name, rng.randint(5, 30) * 100, rng.randint(1, 4) * 100, rng.randint(0, 4)
            )
            model.add_product(product)
            specs = []
            for _ in range(rng.randint(1, 3)):
                variant = self._variant_spec(product)
                model.add_variant(variant)
                specs.append(variant)
            shop.add_product(
                sku, name, product.price, cost=product.cost, reorder_level=product.reorder,
                variants=[_spec(v) for v in specs],
            )
            for v in specs:
                self._stock_new(v.sku)
        plain = MProduct("CAP", "Cap", rng.randint(5, 30) * 100, 150, rng.randint(0, 3))
        model.add_product(plain)
        model.add_variant(MVariant("CAP", "CAP", {}))
        shop.add_product("CAP", "Cap", plain.price, cost=150, reorder_level=plain.reorder)
        self._stock_new("CAP")
        model.products["SHIRT"].discount = 10
        shop.add_discount("SHIRTS", "percent", 10, target_kind="product", target="SHIRT", auto=True)

    def _variant_spec(self, product: MProduct) -> MVariant:
        taken = [self.model.variants[s].options for s in product.variants]
        while True:
            options = {"size": self.rng.choice(SIZES), "colour": self.rng.choice(COLOURS)}
            if options not in taken:
                break
        self.counter += 1
        variant = MVariant(
            f"{product.sku}-{self.counter}",
            product.sku,
            options,
            price=self.rng.choice([None, self.rng.randint(5, 30) * 100]),
            reorder=self.rng.choice([None, None, self.rng.randint(0, 5)]),
        )
        return variant

    def _stock_new(self, sku: str) -> None:
        # Every new variant gets some stock, so it has been checked for alerts.
        for warehouse in WAREHOUSES:
            qty = self.rng.randint(1 if warehouse == WAREHOUSES[0] else 0, 6)
            if qty:
                self.shop.receive(sku, warehouse, qty)
                self.model.receive(sku, warehouse, qty)

    # -- steps -----------------------------------------------------------------------

    def step(self) -> str:
        rng, shop, model = self.rng, self.shop, self.model
        skus = sorted(model.variants)
        kind = rng.choices(
            ["receive", "sell", "cancel", "transfer", "variant", "price", "vprice", "level",
             "vlevel", "reopen"],
            weights=[6, 10, 2, 2, 1, 1, 1, 1, 1, 1],
        )[0]
        if kind == "receive":
            sku, warehouse, qty = rng.choice(skus), rng.choice(WAREHOUSES), rng.randint(1, 8)
            shop.receive(sku, warehouse, qty)
            model.receive(sku, warehouse, qty)
        elif kind == "sell":
            chosen = rng.sample(skus, rng.randint(1, min(3, len(skus))))
            lines = [(sku, rng.randint(1, 4)) for sku in chosen]
            cart = shop.new_cart()
            for sku, qty in lines:
                shop.cart_add(cart, sku, qty)
            if model.can_sell(lines):
                number = shop.checkout(cart, "Customer").number
                model.sell(number, lines)
                self.numbers.append(number)
            else:
                with pytest.raises(OutOfStock):
                    shop.checkout(cart, "Customer")
                shop.carts.discard(cart)
        elif kind == "cancel":
            placed = [n for n in self.numbers if model.orders[n].status == "placed"]
            if placed:
                number = rng.choice(placed)
                shop.cancel_order(number)
                model.cancel(number)
        elif kind == "transfer":
            sku = rng.choice(skus)
            stock = model.variants[sku].stock
            source = max(WAREHOUSES, key=lambda w: (stock[w], w))
            if stock[source]:
                target = "WB" if source == "WA" else "WA"
                qty = rng.randint(1, stock[source])
                shop.transfer(sku, source, target, qty)
                model.transfer(sku, source, target, qty)
        elif kind == "variant":
            product = model.products[rng.choice(sorted(model.products))]
            if len(product.variants) < 6:
                v = self._variant_spec(product)
                shop.add_variant(product.sku, v.sku, v.options, price=v.price, reorder_level=v.reorder)
                model.add_variant(v)
                self._stock_new(v.sku)
        elif kind == "price":
            product = model.products[rng.choice(sorted(model.products))]
            product.price = rng.randint(5, 30) * 100
            shop.update_product(product.sku, price=product.price)
        elif kind == "vprice":
            sku = rng.choice(skus)
            price = rng.choice([None, rng.randint(5, 30) * 100])
            shop.update_variant(sku, price=price)
            model.variants[sku].price = price
        elif kind == "level":
            product = model.products[rng.choice(sorted(model.products))]
            product.reorder = rng.randint(0, 6)
            shop.update_product(product.sku, reorder_level=product.reorder)
        elif kind == "vlevel":
            sku = rng.choice(skus)
            level = rng.choice([None, rng.randint(0, 6)])
            shop.update_variant(sku, reorder_level=level)
            model.variants[sku].reorder = level
        elif kind == "reopen":
            shop.save(self.path)
            self.shop = Shop.open(self.path, clock=Clock("2026-03-02"))
        return kind

    # -- checks ----------------------------------------------------------------------

    def check_step(self, where: str) -> None:
        shop, model = self.shop, self.model
        for sku, v in model.variants.items():
            assert shop.ledger.by_warehouse(sku) == v.stock, (where, sku)
            assert shop.price_of(sku) == model.price(sku), (where, sku)
        assert {a.sku for a in shop.alerts()} == model.open_alerts(), where

    def check_views(self, where: str) -> None:
        shop, model = self.shop, self.model
        rollup = {r.sku: (r.units, r.revenue, r.orders) for r in sales_report(shop)}
        assert rollup == model.sales(by_variant=False), where
        per_variant = {r.sku: (r.units, r.revenue, r.orders) for r in sales_report(shop, by_variant=True)}
        assert per_variant == model.sales(by_variant=True), where
        names = {r.sku: r.name for r in sales_report(shop, by_variant=True)}
        for number in self.numbers:
            if model.orders[number].status == "cancelled":
                continue
            for line in model.orders[number].lines:
                assert names[line.sku] == line.name, where
        rows = list(csv.DictReader(io.StringIO(shop.feed_csv())))
        feed = [
            (r["id"], r["item_group_id"], r["price"], r["availability"] == "in stock") for r in rows
        ]
        expected = [
            (sku, group, f"{price // 100}.{price % 100:02d} GBP", available)
            for sku, group, price, available in model.feed()
        ]
        assert feed == expected, where
        stock = {r.sku: (r.total, r.low) for r in stock_report(shop)}
        assert stock == {
            sku: (v.total, model.level(sku) > 0 and v.total <= model.level(sku))
            for sku, v in model.variants.items()
        }, where
        assert valuation(shop)[1] == model.valuation(), where
        assert set(shop.search(in_stock=True).hits) == model.in_stock_products(), where


@pytest.mark.parametrize("seed", range(25))
def test_random_histories_match_the_model(seed: int, tmp_path) -> None:
    run = Run(seed, tmp_path / "shop.json")
    run.setup()
    run.check_step("setup")
    for number in range(60):
        kind = run.step()
        run.check_step(f"step {number} ({kind})")
        if number % 20 == 19:
            run.check_views(f"after step {number}")
    run.check_views("end")

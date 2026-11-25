"""CLI: categories, products, barcodes, price lists and discounts."""

import argparse
from typing import Any

from shopdesk.cli.output import Context, command, group, key_values, money_arg, positive_int
from shopdesk.errors import InvalidInput
from shopdesk.money import parse_money

MONEY_FIELDS = ("price", "cost")
INT_FIELDS = ("reorder_level",)


def register(commands: Any) -> None:
    categories = group(commands, "category", "manage categories")
    p = command(categories, "add", category_add, saves=True, help="add a category")
    p.add_argument("slug")
    p.add_argument("name")
    p.add_argument("--parent")
    command(categories, "list", category_list, help="list categories")

    products = group(commands, "product", "manage products")
    p = command(products, "add", product_add, saves=True, help="add a product")
    p.add_argument("sku")
    p.add_argument("name")
    p.add_argument("--price", type=money_arg, required=True)
    p.add_argument("--category")
    p.add_argument("--brand", default="")
    p.add_argument("--barcode")
    p.add_argument("--tax-class", default="standard")
    p.add_argument("--cost", type=money_arg, default=0)
    p.add_argument("--reorder-level", type=int, default=0)
    p.add_argument("--description", default="")
    p = command(products, "show", product_show, help="show one product")
    p.add_argument("sku")
    p = command(products, "list", product_list, help="list products")
    p.add_argument("--all", action="store_true", help="include inactive products")
    p.add_argument("--category")
    p = command(products, "update", product_update, saves=True, help="change product fields")
    p.add_argument("sku")
    p.add_argument("--set", action="append", metavar="FIELD=VALUE", required=True)
    p = command(products, "deactivate", product_deactivate, saves=True, help="stop selling")
    p.add_argument("sku")
    p = command(products, "activate", product_activate, saves=True, help="sell again")
    p.add_argument("sku")

    variants = group(commands, "variant", "product variants")
    p = command(variants, "add", variant_add, saves=True, help="add a variant to a product")
    p.add_argument("product")
    p.add_argument("sku")
    p.add_argument("--option", action="append", metavar="NAME=VALUE", default=[])
    p.add_argument("--price", type=money_arg)
    p.add_argument("--barcode")
    p.add_argument("--reorder-level", type=int)
    p = command(variants, "remove", variant_remove, saves=True, help="remove a variant")
    p.add_argument("sku")

    p = command(commands, "barcode", barcode_lookup, help="which SKU has this barcode")
    p.add_argument("code")

    lists = group(commands, "pricelist", "special prices")
    p = command(lists, "set", pricelist_set, saves=True, help="set a SKU's price on a list")
    p.add_argument("list")
    p.add_argument("sku")
    p.add_argument("price", type=money_arg)
    p = command(lists, "show", pricelist_show, help="show a price list")
    p.add_argument("list")

    discounts = group(commands, "discount", "discounts and codes")
    p = command(discounts, "add", discount_add, saves=True, help="add a discount")
    p.add_argument("code")
    amount = p.add_mutually_exclusive_group(required=True)
    amount.add_argument("--percent", type=positive_int)
    amount.add_argument("--amount", type=money_arg)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--category")
    target.add_argument("--product")
    p.add_argument("--min-qty", type=positive_int, default=1)
    p.add_argument("--auto", action="store_true", help="apply without a code")
    p.add_argument("--starts")
    p.add_argument("--ends")
    command(discounts, "list", discount_list, help="list discounts")


def category_add(ctx: Context, args: argparse.Namespace) -> int:
    category = ctx.shop.add_category(args.slug, args.name, args.parent)
    ctx.say(f"Added category {ctx.shop.categories.breadcrumb(category.slug)}")
    return 0


def category_list(ctx: Context, args: argparse.Namespace) -> int:
    for category in ctx.shop.categories.all():
        ctx.say(f"{category.slug:<20} {ctx.shop.categories.breadcrumb(category.slug)}")
    return 0


def product_add(ctx: Context, args: argparse.Namespace) -> int:
    product = ctx.shop.add_product(
        args.sku,
        args.name,
        args.price,
        category=args.category,
        brand=args.brand,
        barcode=args.barcode,
        tax_class=args.tax_class,
        cost=args.cost,
        reorder_level=args.reorder_level,
        description=args.description,
    )
    ctx.say(f"Added {product.sku} {product.name} at {ctx.money(product.price)}")
    return 0


def product_show(ctx: Context, args: argparse.Namespace) -> int:
    shop = ctx.shop
    product = shop.product(args.sku)
    category = shop.categories.breadcrumb(product.category) if product.category else "-"
    ctx.say(f"{product.sku}  {product.name}{'' if product.active else '  (inactive)'}")
    ctx.say(f"  price      {ctx.money(product.price)}")
    ctx.say(f"  cost       {ctx.money(product.cost)}")
    ctx.say(f"  category   {category}")
    ctx.say(f"  brand      {product.brand or '-'}")
    ctx.say(f"  tax class  {product.tax_class}")
    ctx.say(f"  reorder at {product.reorder_level}")
    stock = {code: 0 for code in shop.warehouses.codes()}
    for variant in product.variants:
        for code, qty in shop.ledger.by_warehouse(variant.sku).items():
            stock[code] += qty
    ctx.say(f"  stock      {sum(stock.values())}  " + "  ".join(f"{w}:{q}" for w, q in stock.items()))
    ctx.say("  variants")
    for variant in product.variants:
        options = ", ".join(f"{k}: {v}" for k, v in sorted(variant.options.items())) or "-"
        ctx.say(
            f"    {variant.sku:<16} {options:<28} {ctx.money(product.price_of(variant)):>12}"
            f"  stock {shop.ledger.on_hand(variant.sku):<5} barcode {variant.barcode or '-'}"
        )
    return 0


def product_list(ctx: Context, args: argparse.Namespace) -> int:
    shop = ctx.shop
    if args.category:
        products = shop.catalog.in_category(args.category, active_only=not args.all)
    else:
        products = shop.products(active_only=not args.all)
    for product in products:
        ctx.say(f"{product.sku:<16} {ctx.money(product.price):>12}  {product.name}")
    return 0


def product_update(ctx: Context, args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    for key, value in key_values(args.set).items():
        if key in MONEY_FIELDS:
            changes[key] = parse_money(value)
        elif key in INT_FIELDS:
            try:
                changes[key] = int(value)
            except ValueError:
                raise InvalidInput(f"{key} must be a whole number.") from None
        else:
            changes[key] = value
    product = ctx.shop.update_product(args.sku, **changes)
    ctx.say(f"Updated {product.sku}")
    return 0


def product_deactivate(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.catalog.set_active(args.sku, False)
    ctx.say(f"{args.sku.upper()} is no longer for sale")
    return 0


def product_activate(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.catalog.set_active(args.sku, True)
    ctx.say(f"{args.sku.upper()} is for sale again")
    return 0


def variant_add(ctx: Context, args: argparse.Namespace) -> int:
    variant = ctx.shop.add_variant(
        args.product,
        args.sku,
        key_values(args.option),
        price=args.price,
        barcode=args.barcode,
        reorder_level=args.reorder_level,
    )
    product = ctx.shop.product(variant.sku)
    ctx.say(f"Added {variant.sku} {product.display_name(variant)} at {ctx.money(product.price_of(variant))}")
    return 0


def variant_remove(ctx: Context, args: argparse.Namespace) -> int:
    variant = ctx.shop.remove_variant(args.sku)
    ctx.say(f"Removed {variant.sku}")
    return 0


def barcode_lookup(ctx: Context, args: argparse.Namespace) -> int:
    ctx.say(ctx.shop.lookup_barcode(args.code))
    return 0


def pricelist_set(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.set_list_price(args.list, args.sku, args.price)
    ctx.say(f"{args.sku.upper()} costs {ctx.money(args.price)} on {args.list}")
    return 0


def pricelist_show(ctx: Context, args: argparse.Namespace) -> int:
    for sku, price in ctx.shop.price_lists.entries(args.list):
        ctx.say(f"{sku:<16} {ctx.money(price):>12}")
    return 0


def discount_add(ctx: Context, args: argparse.Namespace) -> int:
    if args.category:
        target_kind, target = "category", args.category
    elif args.product:
        target_kind, target = "product", args.product
    else:
        target_kind, target = "all", None
    kind, value = ("percent", args.percent) if args.percent else ("amount", args.amount)
    discount = ctx.shop.add_discount(
        args.code,
        kind,
        value,
        target_kind=target_kind,
        target=target,
        min_qty=args.min_qty,
        auto=args.auto,
        starts=args.starts,
        ends=args.ends,
    )
    ctx.say(f"Added discount {discount.code}")
    return 0


def discount_list(ctx: Context, args: argparse.Namespace) -> int:
    for d in ctx.shop.discounts.all():
        value = f"{d.value}%" if d.kind == "percent" else f"{ctx.money(d.value)} each"
        target = d.target_kind if d.target is None else f"{d.target_kind} {d.target}"
        flags = " auto" if d.auto else ""
        flags += "" if d.active else " inactive"
        ctx.say(f"{d.code:<12} {value:<14} {target:<24} min {d.min_qty}{flags}")
    return 0

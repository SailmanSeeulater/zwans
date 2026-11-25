"""CLI: carts, checkout, orders and invoices."""

import argparse
from typing import Any

from shopdesk.cli.output import Context, command, group, positive_int
from shopdesk.sales.invoices import render_invoice


def register(commands: Any) -> None:
    carts = group(commands, "cart", "carts")
    p = command(carts, "new", cart_new, saves=True, help="start a cart")
    p.add_argument("--price-list")
    p = command(carts, "add", cart_add, saves=True, help="add a SKU to a cart")
    p.add_argument("cart")
    p.add_argument("sku")
    p.add_argument("qty", type=positive_int, nargs="?", default=1)
    p = command(carts, "set", cart_set, saves=True, help="change a quantity (0 removes)")
    p.add_argument("cart")
    p.add_argument("sku")
    p.add_argument("qty", type=int)
    p = command(carts, "code", cart_code, saves=True, help="enter a discount code")
    p.add_argument("cart")
    p.add_argument("code")
    p = command(carts, "show", cart_show, help="show a cart, priced")
    p.add_argument("cart")

    p = command(commands, "checkout", checkout, saves=True, help="turn a cart into an order")
    p.add_argument("cart")
    p.add_argument("--customer", required=True)
    p.add_argument("--warehouse")

    orders = group(commands, "order", "orders")
    p = command(orders, "list", order_list, help="list orders")
    p.add_argument("--status")
    p = command(orders, "show", order_show, help="show an order")
    p.add_argument("number")
    p = command(orders, "cancel", order_cancel, saves=True, help="cancel an order")
    p.add_argument("number")

    invoices = group(commands, "invoice", "invoices")
    p = command(invoices, "create", invoice_create, saves=True, help="invoice an order")
    p.add_argument("order")
    p = command(invoices, "show", invoice_show, help="print an invoice")
    p.add_argument("number")


def cart_new(ctx: Context, args: argparse.Namespace) -> int:
    ctx.say(ctx.shop.new_cart(args.price_list))
    return 0


def cart_add(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.cart_add(args.cart, args.sku, args.qty)
    ctx.say(f"Added {args.qty} x {args.sku.upper()} to {args.cart.upper()}")
    return 0


def cart_set(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.cart_set(args.cart, args.sku, args.qty)
    return cart_show(ctx, args)


def cart_code(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.cart_code(args.cart, args.code)
    return cart_show(ctx, args)


def cart_show(ctx: Context, args: argparse.Namespace) -> int:
    view = ctx.shop.cart(args.cart)
    ctx.say(f"Cart {view.id}" + (f" ({view.price_list} prices)" if view.price_list else ""))
    for line in view.lines:
        discount = f"  -{ctx.money(line.discount)} {line.discount_code}" if line.discount else ""
        ctx.say(
            f"  {line.qty:>3} x {line.sku:<16} {line.name:<36} "
            f"{ctx.money(line.unit_price):>12}{discount}"
        )
    ctx.say(f"  total {ctx.money(view.total)}")
    return 0


def checkout(ctx: Context, args: argparse.Namespace) -> int:
    order = ctx.shop.checkout(args.cart, args.customer, args.warehouse)
    ctx.say(f"Order {order.number}: {order.units} items, {ctx.money(order.total)}")
    return 0


def order_list(ctx: Context, args: argparse.Namespace) -> int:
    for order in ctx.shop.orders(args.status):
        ctx.say(
            f"{order.number}  {order.placed_at[:10]}  {order.status:<9} "
            f"{ctx.money(order.total):>14}  {order.customer}"
        )
    return 0


def order_show(ctx: Context, args: argparse.Namespace) -> int:
    order = ctx.shop.order(args.number)
    ctx.say(f"Order {order.number} for {order.customer}, {order.status}")
    for line in order.lines:
        picked = ", ".join(f"{a.qty} from {a.warehouse}" for a in line.allocations)
        ctx.say(f"  {line.qty:>3} x {line.sku:<16} {line.name:<36} {ctx.money(line.net):>12}  ({picked})")
    ctx.say(f"  total {ctx.money(order.total)}")
    return 0


def order_cancel(ctx: Context, args: argparse.Namespace) -> int:
    order = ctx.shop.cancel_order(args.number)
    ctx.say(f"Cancelled {order.number}; stock returned")
    return 0


def invoice_create(ctx: Context, args: argparse.Namespace) -> int:
    invoice = ctx.shop.invoice_order(args.order)
    ctx.say(f"Invoice {invoice.number}: {ctx.money(invoice.gross_total)} including VAT")
    return 0


def invoice_show(ctx: Context, args: argparse.Namespace) -> int:
    ctx.out.write(render_invoice(ctx.shop.invoice(args.number), ctx.shop.settings))
    return 0

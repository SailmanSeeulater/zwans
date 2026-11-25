"""CLI: warehouses, stock moves, counts and alerts."""

import argparse
from typing import Any

from shopdesk.cli.output import Context, command, group, positive_int


def register(commands: Any) -> None:
    warehouses = group(commands, "warehouse", "manage warehouses")
    p = command(warehouses, "add", warehouse_add, saves=True, help="add a warehouse")
    p.add_argument("code")
    p.add_argument("name")
    p.add_argument("--priority", type=int, default=0)
    command(warehouses, "list", warehouse_list, help="list warehouses in picking order")

    p = command(commands, "receive", receive, saves=True, help="book stock in")
    p.add_argument("sku")
    p.add_argument("qty", type=positive_int)
    p.add_argument("--warehouse", "-w", required=True)
    p.add_argument("--ref", default="")

    p = command(commands, "adjust", adjust, saves=True, help="correct stock up or down")
    p.add_argument("sku")
    p.add_argument("qty", type=int)
    p.add_argument("--warehouse", "-w", required=True)
    p.add_argument("--ref", default="")

    p = command(commands, "count", count, saves=True, help="record a stock count")
    p.add_argument("sku")
    p.add_argument("counted", type=int)
    p.add_argument("--warehouse", "-w", required=True)

    p = command(commands, "transfer", transfer, saves=True, help="move stock between warehouses")
    p.add_argument("sku")
    p.add_argument("qty", type=positive_int)
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--to", dest="target", required=True)

    p = command(commands, "stock", stock, help="stock of one SKU per warehouse")
    p.add_argument("sku")

    p = command(commands, "history", history, help="stock moves of one SKU")
    p.add_argument("sku")

    p = command(commands, "alerts", alerts, help="low-stock alerts")
    p.add_argument("--all", action="store_true", help="include cleared alerts")


def warehouse_add(ctx: Context, args: argparse.Namespace) -> int:
    warehouse = ctx.shop.add_warehouse(args.code, args.name, args.priority)
    ctx.say(f"Added warehouse {warehouse.code} ({warehouse.name})")
    return 0


def warehouse_list(ctx: Context, args: argparse.Namespace) -> int:
    for w in ctx.shop.warehouses.all():
        ctx.say(f"{w.code:<10} {w.priority:>3}  {w.name}")
    return 0


def receive(ctx: Context, args: argparse.Namespace) -> int:
    move = ctx.shop.receive(args.sku, args.warehouse, args.qty, args.ref)
    ctx.say(f"Received {move.qty} x {move.sku} into {move.warehouse}")
    return 0


def adjust(ctx: Context, args: argparse.Namespace) -> int:
    move = ctx.shop.adjust(args.sku, args.warehouse, args.qty, args.ref)
    ctx.say(f"Adjusted {move.sku} in {move.warehouse} by {move.qty:+d}")
    return 0


def count(ctx: Context, args: argparse.Namespace) -> int:
    move = ctx.shop.count(args.sku, args.warehouse, args.counted)
    if move is None:
        ctx.say("Count matches; nothing to change")
    else:
        ctx.say(f"Counted {args.counted} of {move.sku} in {move.warehouse} ({move.qty:+d})")
    return 0


def transfer(ctx: Context, args: argparse.Namespace) -> int:
    ref = ctx.shop.transfer(args.sku, args.source, args.target, args.qty)
    ctx.say(f"Moved {args.qty} x {args.sku.upper()} from {args.source.upper()} to {args.target.upper()} ({ref})")
    return 0


def stock(ctx: Context, args: argparse.Namespace) -> int:
    total = ctx.shop.stock(args.sku)
    for code, qty in ctx.shop.ledger.by_warehouse(args.sku).items():
        ctx.say(f"{code:<10} {qty:>6}")
    ctx.say(f"{'total':<10} {total:>6}")
    return 0


def history(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.product(args.sku)
    for move in ctx.shop.ledger.history(args.sku):
        ctx.say(f"{move.at}  {move.warehouse:<8} {move.qty:>+6}  {move.reason:<9} {move.ref}")
    return 0


def alerts(ctx: Context, args: argparse.Namespace) -> int:
    for alert in ctx.shop.alerts(open_only=not args.all):
        state = "open" if alert.is_open else f"cleared {alert.cleared_at}"
        ctx.say(
            f"{alert.sku:<16} stock {alert.stock:>4} / reorder at {alert.reorder_level:<4} "
            f"raised {alert.raised_at}  {state}"
        )
    return 0

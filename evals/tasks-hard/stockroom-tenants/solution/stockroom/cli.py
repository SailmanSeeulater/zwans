"""The stockroom command line.

    stockroom [--db FILE] [--tenant NAME] <command> ...

Exit codes: 0 fine, otherwise the exit_code of the StockroomError (see errors.py).
"""

import argparse
import os
import sys
from pathlib import Path

from .errors import StockroomError
from .importer import import_products
from .inventory import Inventory, utc_now
from .reports import alerts_report, low_stock_report, movements_csv, valuation_report
from .snapshot import snapshot_json
from .storage import DEFAULT_TENANT, Database
from .validation import format_cents, parse_cents


def clock() -> str:
    """STOCKROOM_NOW (e.g. 2026-03-01T09:00:00Z) fixes the clock, for scripts and tests."""
    return os.environ.get("STOCKROOM_NOW") or utc_now()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stockroom", description="Stock levels for a small shop.")
    parser.add_argument(
        "--db", default="stockroom.json", help="database file (default: %(default)s)"
    )
    parser.add_argument(
        "--tenant", default=DEFAULT_TENANT, help="which shop's stock (default: %(default)s)"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("add", help="add a product")
    p.add_argument("sku")
    p.add_argument("name")
    p.add_argument("--cost", required=True, help="unit cost, e.g. 4.25")
    p.add_argument("--reorder-level", type=int, default=0)
    p.add_argument("--unit", default="pcs")

    p = sub.add_parser("rename", help="rename a product")
    p.add_argument("sku")
    p.add_argument("name")

    p = sub.add_parser("set-cost", help="change a product's unit cost")
    p.add_argument("sku")
    p.add_argument("cost")

    p = sub.add_parser("set-reorder", help="change a product's reorder level")
    p.add_argument("sku")
    p.add_argument("level", type=int)

    p = sub.add_parser("remove", help="remove a product that never had stock")
    p.add_argument("sku")

    for name, text in (("receive", "stock came in"), ("ship", "stock went out")):
        p = sub.add_parser(name, help=text)
        p.add_argument("sku")
        p.add_argument("qty", type=int)
        p.add_argument("--ref", default="")

    p = sub.add_parser("count", help="record a stock count")
    p.add_argument("sku")
    p.add_argument("counted", type=int)
    p.add_argument("--ref", default="stocktake")

    p = sub.add_parser("show", help="one product and its stock")
    p.add_argument("sku")

    sub.add_parser("list", help="every product and its stock")

    p = sub.add_parser("search", help="find products by name or SKU")
    p.add_argument("query")

    p = sub.add_parser("history", help="stock movements as CSV")
    p.add_argument("--sku")

    sub.add_parser("low", help="products at or below their reorder level")
    sub.add_parser("value", help="stock valuation")
    sub.add_parser("alerts", help="low-stock alerts so far")
    sub.add_parser("snapshot", help="catalogue and stock levels as JSON, for the web shop")

    p = sub.add_parser("import", help="import products from a CSV file")
    p.add_argument("file", type=Path)
    return parser


def run(args: argparse.Namespace, inventory: Inventory) -> None:
    db, tenant = inventory.db, inventory.tenant
    match args.command:
        case "add":
            product = inventory.add_product(
                args.sku, args.name, parse_cents(args.cost), args.reorder_level, args.unit
            )
            print(f"added {product.sku}")
        case "rename":
            inventory.rename(args.sku, args.name)
            print(f"renamed {args.sku}")
        case "set-cost":
            inventory.set_cost(args.sku, parse_cents(args.cost))
            print(f"updated {args.sku}")
        case "set-reorder":
            inventory.set_reorder_level(args.sku, args.level)
            print(f"updated {args.sku}")
        case "remove":
            inventory.remove_product(args.sku)
            print(f"removed {args.sku}")
        case "receive":
            movement = inventory.receive(args.sku, args.qty, args.ref)
            print(f"{movement.id}: {args.sku} +{args.qty}, on hand {inventory.on_hand(args.sku)}")
        case "ship":
            movement = inventory.ship(args.sku, args.qty, args.ref)
            print(f"{movement.id}: {args.sku} -{args.qty}, on hand {inventory.on_hand(args.sku)}")
        case "count":
            movement = inventory.count(args.sku, args.counted, args.ref)
            if movement is None:
                print(f"{args.sku}: count matches")
            else:
                print(
                    f"{movement.id}: {args.sku} adjusted by {movement.qty:+d}, on hand {args.counted}"
                )
        case "show":
            product = inventory.product(args.sku)
            print(f"sku: {product.sku}")
            print(f"name: {product.name}")
            print(f"unit cost: {format_cents(product.unit_cost_cents)}")
            print(f"reorder level: {product.reorder_level}")
            print(f"on hand: {inventory.on_hand(product.sku)} {product.unit}")
        case "list":
            for product, qty in inventory.levels():
                print(f"{product.sku}  {qty}  {product.name}")
        case "search":
            for product in inventory.search(args.query):
                print(f"{product.sku}  {product.name}")
        case "history":
            if args.sku:
                inventory.product(args.sku)
            sys.stdout.write(movements_csv(db, args.sku, tenant))
        case "low":
            sys.stdout.write(low_stock_report(db, tenant))
        case "value":
            sys.stdout.write(valuation_report(db, tenant))
        case "alerts":
            sys.stdout.write(alerts_report(db, tenant))
        case "snapshot":
            sys.stdout.write(snapshot_json(inventory))
        case "import":
            result = import_products(inventory, args.file.read_text(encoding="utf-8"))
            print(f"imported {len(result.added)} products")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inventory = Inventory(Database(args.db), tenant=args.tenant, clock=clock)
        run(args, inventory)
    except StockroomError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0

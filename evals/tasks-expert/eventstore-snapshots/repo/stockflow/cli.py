"""The stockflow command line. Every command opens the data directory, does one thing, and
exits; the store is safe to share between processes."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from stockflow.app import App
from stockflow.errors import StockflowError
from stockflow.legacy import import_scans, parse_scans

DEFAULT_DATA = "stockflow-data"


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def parse_price(text: str) -> int:
    """'12.5' or '12.50' -> 1250 cents."""
    whole, _, fraction = text.strip().partition(".")
    if not whole.isdigit() or (fraction and not fraction.isdigit()) or len(fraction) > 2:
        raise argparse.ArgumentTypeError(f"not a price: {text!r}")
    return int(whole) * 100 + int((fraction + "00")[:2])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stockflow", description="Inventory and orders.")
    parser.add_argument(
        "--data",
        type=Path,
        default=Path(os.environ.get("STOCKFLOW_DATA", DEFAULT_DATA)),
        help="data directory (default: $STOCKFLOW_DATA or ./stockflow-data)",
    )
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    groups = parser.add_subparsers(dest="group", required=True)

    item = groups.add_parser("item", help="stock items").add_subparsers(dest="action", required=True)
    register = item.add_parser("register")
    register.add_argument("sku")
    register.add_argument("name")
    register.add_argument("--reorder", type=int, default=None)
    receive = item.add_parser("receive")
    receive.add_argument("sku")
    receive.add_argument("quantity", type=int)
    receive.add_argument("--lot", default="manual")
    adjust = item.add_parser("adjust")
    adjust.add_argument("sku")
    adjust.add_argument("delta", type=int)
    adjust.add_argument("--reason", default="recount")
    show = item.add_parser("show")
    show.add_argument("sku")

    order = groups.add_parser("order", help="orders").add_subparsers(dest="action", required=True)
    place = order.add_parser("place")
    place.add_argument("order_id")
    place.add_argument("customer")
    add = order.add_parser("add")
    add.add_argument("order_id")
    add.add_argument("sku")
    add.add_argument("quantity", type=int)
    add.add_argument("price", type=parse_price)
    remove = order.add_parser("remove")
    remove.add_argument("order_id")
    remove.add_argument("sku")
    for name in ("confirm", "ship", "show"):
        order.add_parser(name).add_argument("order_id")
    cancel = order.add_parser("cancel")
    cancel.add_argument("order_id")
    cancel.add_argument("--reason", default="")

    report = groups.add_parser("report", help="reports").add_subparsers(dest="action", required=True)
    for name in ("stock", "low-stock", "orders"):
        report.add_parser(name)

    scans = groups.add_parser("scans", help="scanner gateway").add_subparsers(
        dest="action", required=True
    )
    scans.add_parser("import").add_argument("file", type=Path)
    return parser


def run(args: argparse.Namespace) -> Any:
    app = App.open(args.data)
    inventory = app.inventory
    match (args.group, args.action):
        case ("item", "register"):
            return inventory.register_item(args.sku, args.name, args.reorder).as_dict()
        case ("item", "receive"):
            return inventory.receive(args.sku, args.quantity, args.lot).as_dict()
        case ("item", "adjust"):
            return inventory.adjust(args.sku, args.delta, args.reason).as_dict()
        case ("item", "show"):
            return inventory.item(args.sku).as_dict()
        case ("order", "place"):
            return inventory.place_order(args.order_id, args.customer).as_dict()
        case ("order", "add"):
            return inventory.add_line(args.order_id, args.sku, args.quantity, args.price).as_dict()
        case ("order", "remove"):
            return inventory.remove_line(args.order_id, args.sku).as_dict()
        case ("order", "confirm"):
            return inventory.confirm_order(args.order_id).as_dict()
        case ("order", "cancel"):
            return inventory.cancel_order(args.order_id, args.reason).as_dict()
        case ("order", "ship"):
            return inventory.ship_order(args.order_id).as_dict()
        case ("order", "show"):
            return inventory.order(args.order_id).as_dict()
        case ("report", "stock"):
            return app.projector.result("stock_levels")
        case ("report", "low-stock"):
            return app.projector.result("low_stock")
        case ("report", "orders"):
            return app.projector.result("open_orders")
        case ("scans", "import"):
            scans = parse_scans(args.file.read_text("utf-8"))
            return {"imported": import_scans(app.store, scans), "scans": len(scans)}
    raise AssertionError(f"unhandled command {args.group} {args.action}")


def show(result: Any, as_json: bool) -> str:
    if as_json:
        return json.dumps(result, indent=2, sort_keys=True)
    if isinstance(result, list):
        return "\n".join(result) if result else "(none)"
    lines = []
    for key, value in result.items():
        if isinstance(value, dict):
            inner = ", ".join(f"{k}={v}" for k, v in value.items()) or "-"
            lines.append(f"{key}: {inner}")
        elif key.endswith("_cents") and isinstance(value, int):
            lines.append(f"{key[: -len('_cents')]}: {money(value)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (StockflowError, OSError) as error:
        print(f"stockflow: {error}", file=sys.stderr)
        return 1
    print(show(result, args.json))
    return 0

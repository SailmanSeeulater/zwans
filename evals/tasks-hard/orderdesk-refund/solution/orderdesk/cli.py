"""The orderdesk command line.

    orderdesk [--data DIR] [--actor NAME] [--role ROLE] <command> ...

Commands that change an order go through the desk (so they are permission-checked,
validated and audited); each one has a sub-parser in _add_command_parsers() and a builder
in BUILDERS that turns the parsed arguments into the command. Views only read the read
models; each one names the permission it needs in VIEWS.
"""

import argparse
import sys
from collections.abc import Callable

from .app import App, open_app
from .commands import COMMANDS, Command
from .errors import OrderDeskError, ValidationError
from .events import Line
from .handlers.cancel import CancelOrder
from .handlers.note import AddNote
from .handlers.pay import METHODS, PayOrder
from .handlers.place import PlaceOrder
from .handlers.refund import RefundOrder
from .handlers.ship import ShipOrder
from .money import format_amount, parse_amount
from .permissions import Actor, require

# ---------------------------------------------------------------------------- commands


def _parse_line(text: str) -> Line:
    """'SKU:QTY:PRICE', e.g. 'MUG-01:2:9.50'."""
    parts = text.split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        raise ValidationError(f"a line looks like SKU:QTY:PRICE, not {text!r}")
    sku, qty, price = parts
    return Line(sku.strip(), int(qty), parse_amount(price))


def _build_place(args: argparse.Namespace, app: App) -> Command:
    lines = tuple(_parse_line(text) for text in args.line)
    return PlaceOrder(app.desk.next_order_id(), args.customer, args.email, lines)


def _build_pay(args: argparse.Namespace, app: App) -> Command:
    return PayOrder(args.order, parse_amount(args.amount), args.method)


def _build_ship(args: argparse.Namespace, app: App) -> Command:
    return ShipOrder(args.order, args.carrier, args.tracking)


def _build_cancel(args: argparse.Namespace, app: App) -> Command:
    return CancelOrder(args.order, args.reason)


def _build_refund(args: argparse.Namespace, app: App) -> Command:
    return RefundOrder(args.order, parse_amount(args.amount), args.reason)


def _build_note(args: argparse.Namespace, app: App) -> Command:
    return AddNote(args.order, args.text)


BUILDERS: dict[str, Callable[[argparse.Namespace, App], Command]] = {
    "place": _build_place,
    "pay": _build_pay,
    "ship": _build_ship,
    "cancel": _build_cancel,
    "refund": _build_refund,
    "note": _build_note,
}


def _add_command_parsers(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("place", help=COMMANDS["place"].summary)
    p.add_argument("--customer", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--line", action="append", required=True, metavar="SKU:QTY:PRICE")

    p = sub.add_parser("pay", help=COMMANDS["pay"].summary)
    p.add_argument("order")
    p.add_argument("--amount", required=True)
    p.add_argument("--method", default="card", choices=METHODS)

    p = sub.add_parser("ship", help=COMMANDS["ship"].summary)
    p.add_argument("order")
    p.add_argument("--carrier", required=True)
    p.add_argument("--tracking", required=True)

    p = sub.add_parser("cancel", help=COMMANDS["cancel"].summary)
    p.add_argument("order")
    p.add_argument("--reason", required=True)

    p = sub.add_parser("refund", help=COMMANDS["refund"].summary)
    p.add_argument("order")
    p.add_argument("--amount", required=True)
    p.add_argument("--reason", required=True)

    p = sub.add_parser("note", help=COMMANDS["note"].summary)
    p.add_argument("order")
    p.add_argument("text")


# ------------------------------------------------------------------------------- views


def _show(args: argparse.Namespace, app: App) -> None:
    state = app.desk.state(args.order)
    print(f"order {state.order_id}")
    print(f"customer: {state.customer} <{state.email}>")
    print(f"status: {state.status}")
    print("lines:")
    for line in state.lines:
        print(f"  {line.sku} x{line.qty} @ {format_amount(line.unit_cents)}")
    print(f"total: {format_amount(state.total_cents)}")
    print(f"paid: {format_amount(state.paid_cents)}")
    if state.refunded_cents:
        print(f"refunded: {format_amount(state.refunded_cents)}")
    if state.status == "shipped":
        print(f"shipped: {state.carrier} {state.tracking}")
    if state.status == "cancelled":
        print(f"cancelled: {state.cancel_reason}")
    for text in state.notes:
        print(f"note: {text}")


def _list(args: argparse.Namespace, app: App) -> None:
    for row in app.orders.rows(args.status):
        print(f"{row.order_id}  {row.customer}  {row.status}  {format_amount(row.total_cents)}")


def _report(args: argparse.Namespace, app: App) -> None:
    print(f"{'day':<11} {'gross':>10} {'refunds':>10} {'net':>10}")
    for day in [*app.sales.days(), app.sales.total()]:
        print(
            f"{day.day:<11} {format_amount(day.gross_cents):>10} "
            f"{format_amount(day.refunds_cents):>10} {format_amount(day.net_cents):>10}"
        )


def _customers(args: argparse.Namespace, app: App) -> None:
    for figures in app.customers.customers():
        print(
            f"{figures.customer}  orders {figures.orders}  spent {format_amount(figures.spent_cents)}"
        )


def _audit(args: argparse.Namespace, app: App) -> None:
    for entry in app.audit.entries():
        line = f"{entry['at']}  {entry['actor']}  {entry['command']}  {entry['order_id']}  {entry['outcome']}"
        if entry["error"]:
            line += f"  ({entry['error']})"
        print(line)


def _help(args: argparse.Namespace, app: App) -> None:
    print("commands:")
    for name, spec in COMMANDS.items():
        print(f"  {name:<10} {spec.summary}")
    print("views:")
    for name, (_, summary, _) in VIEWS.items():
        print(f"  {name:<10} {summary}")


# name -> (function, summary, permission needed or None)
VIEWS: dict[str, tuple[Callable[[argparse.Namespace, App], None], str, str | None]] = {
    "show": (_show, "Show one order", "orders.view"),
    "list": (_list, "List orders, optionally only those with one status", "orders.view"),
    "report": (_report, "Money in and out per day", "reports.view"),
    "customers": (_customers, "Lifetime figures per customer", "reports.view"),
    "audit": (_audit, "Everything anyone tried to do", "audit.view"),
    "help": (_help, "This list", None),
}


def _add_view_parsers(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("show", help=VIEWS["show"][1]).add_argument("order")
    sub.add_parser("list", help=VIEWS["list"][1]).add_argument("--status")
    for name in ("report", "customers", "audit", "help"):
        sub.add_parser(name, help=VIEWS[name][1])


# -------------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orderdesk", description="Orders, payments and shipping.")
    parser.add_argument(
        "--data", default="orderdesk-data", help="data folder (default: %(default)s)"
    )
    parser.add_argument("--actor", default="cli", help="who is doing this, for the audit log")
    parser.add_argument("--role", default="clerk", help="the actor's role (default: %(default)s)")
    sub = parser.add_subparsers(dest="name", required=True, metavar="command")
    _add_command_parsers(sub)
    _add_view_parsers(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = open_app(args.data)
    actor = Actor(args.actor, args.role)
    try:
        if args.name in BUILDERS:
            cmd = BUILDERS[args.name](args, app)
            app.desk.execute(cmd, actor)
            print(f"{args.name}: {cmd.order_id}")
        else:
            view, _, permission = VIEWS[args.name]
            if permission is not None:
                require(actor, permission)
            view(args, app)
    except OrderDeskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0

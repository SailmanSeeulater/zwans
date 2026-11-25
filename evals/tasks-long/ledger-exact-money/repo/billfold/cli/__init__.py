"""`python -m billfold`: the command line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .. import clock as clocks
from ..book import Book
from ..errors import BillfoldError
from ..notifications import JsonlSink
from . import commands, io_commands
from .output import err
from .parser import build_parser

HANDLERS = {
    "account": commands.account,
    "add": commands.add,
    "edit": commands.edit,
    "delete": commands.delete,
    "split": commands.split,
    "transfer": commands.transfer,
    "balance": commands.balance,
    "list": commands.list_transactions,
    "search": commands.search,
    "undo": commands.undo,
    "history": commands.history,
    "rule": commands.rule,
    "budget": commands.budget,
    "recurring": commands.recurring,
    "rate": commands.rate,
    "convert": commands.convert,
    "reconcile": commands.reconcile_command,
    "alert": commands.alert,
    "report": io_commands.report,
    "import": io_commands.import_command,
    "export": io_commands.export_command,
}


def _print_alert(event: dict) -> None:
    if event.get("type") == "budget.exceeded":
        err(f"! {event['category']} is over budget for {event['month']} by {event['over_by']}")
    elif event.get("type") == "transaction.large":
        err(f"! large transaction: {event['amount']} {event['currency']} to {event['payee']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.file)
    try:
        book = Book.open(path, clock=clocks.from_environment())
        book.notifier.add_sink(JsonlSink(path.with_name("alerts.jsonl")))
        book.on_alert(_print_alert)
        if args.command == "backup":
            changed = io_commands.backup_command(book, args, path)
        else:
            changed = HANDLERS[args.command](book, args)
        if changed:
            book.save(path)
    except BillfoldError as error:
        err(f"billfold: {error}")
        return 1
    return 0

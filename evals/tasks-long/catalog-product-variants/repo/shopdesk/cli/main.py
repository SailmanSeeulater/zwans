"""The `shopdesk` command line.

    python -m shopdesk [--db shop.json] COMMAND ...

Every command opens the data file, does its work, and saves the file again if it changed
anything. Errors print one line to stderr and exit with status 1.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from shopdesk.cli import catalog_cmds, report_cmds, sales_cmds, stock_cmds, admin_cmds
from shopdesk.cli.output import Context
from shopdesk.clock import clock_from_env
from shopdesk.errors import ShopError
from shopdesk.shop import Shop

MODULES = (catalog_cmds, stock_cmds, sales_cmds, report_cmds, admin_cmds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shopdesk", description="Back office for a small shop.")
    parser.add_argument("--db", default="shop.json", help="the data file (default shop.json)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in MODULES:
        module.register(commands)
    return parser


def main(
    argv: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    path = Path(args.db)
    clock = clock_from_env()
    try:
        shop = Shop.open(path, clock=clock)
        context = Context(shop=shop, path=path, out=out, err=err, clock=clock)
        code = args.handler(context, args)
        if code == 0 and getattr(args, "saves", False):
            shop.save()
        return code
    except ShopError as exc:
        print(f"error: {exc}", file=err)
        return 1

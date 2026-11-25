"""The command line's arguments."""

from __future__ import annotations

import argparse
import os

from ..dates import parse_date


def _day(text: str):
    try:
        return parse_date(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _pair(text: str) -> tuple[str, str]:
    name, sep, value = text.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, got {text!r}")
    return name, value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="billfold", description="Personal bookkeeping.")
    parser.add_argument("--file", default=os.environ.get("BILLFOLD_FILE", "billfold.json"),
                        help="data file (default: $BILLFOLD_FILE or billfold.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    account = sub.add_parser("account", help="add, list, rename or close accounts")
    acc = account.add_subparsers(dest="action", required=True)
    p = acc.add_parser("add")
    p.add_argument("name")
    p.add_argument("--currency", default=None)
    p.add_argument("--kind", default="checking")
    p.add_argument("--opening", default="0")
    p.add_argument("--opened", type=_day)
    acc.add_parser("list").add_argument("--all", action="store_true")
    p = acc.add_parser("rename")
    p.add_argument("name")
    p.add_argument("new_name")
    acc.add_parser("close").add_argument("name")

    p = sub.add_parser("add", help="add a transaction")
    p.add_argument("account")
    p.add_argument("amount")
    p.add_argument("--date", type=_day)
    p.add_argument("--payee", default="")
    p.add_argument("--memo", default="")
    p.add_argument("--category")
    p.add_argument("--tag", action="append", default=[])

    p = sub.add_parser("edit", help="change a transaction")
    p.add_argument("id")
    p.add_argument("--amount")
    p.add_argument("--date", type=_day)
    p.add_argument("--payee")
    p.add_argument("--memo")
    p.add_argument("--category")

    sub.add_parser("delete", help="delete a transaction").add_argument("id")

    p = sub.add_parser("split", help="split a transaction over categories")
    p.add_argument("id")
    p.add_argument("categories", nargs="*")
    p.add_argument("--part", type=_pair, action="append", default=[],
                   help="CATEGORY=AMOUNT (instead of an even split)")

    p = sub.add_parser("transfer", help="move money between accounts")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("amount")
    p.add_argument("--date", type=_day)
    p.add_argument("--memo", default="")
    p.add_argument("--rate")

    p = sub.add_parser("balance", help="account balances")
    p.add_argument("account", nargs="?")
    p.add_argument("--on", type=_day)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list", help="list transactions")
    p.add_argument("account", nargs="?")
    p.add_argument("--from", dest="start", type=_day)
    p.add_argument("--to", dest="end", type=_day)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("search", help="find transactions")
    p.add_argument("query", nargs="+")
    p.add_argument("--json", action="store_true")

    sub.add_parser("undo", help="take back the last change")
    sub.add_parser("history", help="recent changes").add_argument("-n", type=int, default=10)

    rule = sub.add_parser("rule", help="categorisation rules")
    rl = rule.add_subparsers(dest="action", required=True)
    p = rl.add_parser("add")
    p.add_argument("name")
    p.add_argument("--if", dest="conditions", action="append", required=True)
    p.add_argument("--category")
    p.add_argument("--rename")
    p.add_argument("--split", type=_pair, action="append", default=[],
                   help="CATEGORY=PERCENT")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--priority", type=int, default=100)
    rl.add_parser("list")
    rl.add_parser("remove").add_argument("id")
    rl.add_parser("run").add_argument("account", nargs="?")

    budget = sub.add_parser("budget", help="monthly budgets")
    bd = budget.add_subparsers(dest="action", required=True)
    p = bd.add_parser("set")
    p.add_argument("category")
    p.add_argument("month")
    p.add_argument("amount")
    p.add_argument("--rollover", action="store_true")
    p = bd.add_parser("allocate")
    p.add_argument("month")
    p.add_argument("total")
    p.add_argument("weights", type=_pair, nargs="+", help="CATEGORY=WEIGHT")
    p.add_argument("--rollover", action="store_true")
    p = bd.add_parser("status")
    p.add_argument("month")
    p.add_argument("--json", action="store_true")

    rec = sub.add_parser("recurring", help="recurring entries")
    rc = rec.add_subparsers(dest="action", required=True)
    p = rc.add_parser("add")
    p.add_argument("account")
    p.add_argument("payee")
    p.add_argument("amount")
    p.add_argument("frequency")
    p.add_argument("start", type=_day)
    p.add_argument("--category")
    p.add_argument("--memo", default="")
    p.add_argument("--end", type=_day)
    p.add_argument("--instalments", type=int)
    rc.add_parser("list")
    rc.add_parser("run").add_argument("--until", type=_day)
    rc.add_parser("remove").add_argument("id")

    rate = sub.add_parser("rate", help="exchange rates")
    rt = rate.add_subparsers(dest="action", required=True)
    p = rt.add_parser("set")
    p.add_argument("base")
    p.add_argument("quote")
    p.add_argument("rate")
    p.add_argument("--date", type=_day)
    rt.add_parser("import").add_argument("path")
    rt.add_parser("list")

    p = sub.add_parser("convert", help="convert an amount between currencies")
    p.add_argument("amount")
    p.add_argument("base")
    p.add_argument("quote")
    p.add_argument("--date", type=_day)

    report = sub.add_parser("report", help="reports")
    rp = report.add_subparsers(dest="kind", required=True)
    p = rp.add_parser("monthly")
    p.add_argument("month")
    p.add_argument("--currency")
    p.add_argument("--json", action="store_true")
    p = rp.add_parser("yearly")
    p.add_argument("year", type=int)
    p.add_argument("--currency")
    p.add_argument("--json", action="store_true")
    p = rp.add_parser("networth")
    p.add_argument("--on", type=_day)
    p.add_argument("--currency")
    p.add_argument("--json", action="store_true")
    p = rp.add_parser("budget")
    p.add_argument("month")
    p.add_argument("--json", action="store_true")

    imp = sub.add_parser("import", help="import a bank file")
    im = imp.add_subparsers(dest="kind", required=True)
    p = im.add_parser("csv")
    p.add_argument("account")
    p.add_argument("path")
    p.add_argument("--profile", default="default")
    p.add_argument("--dry-run", action="store_true")
    p = im.add_parser("statement")
    p.add_argument("account")
    p.add_argument("path")
    p.add_argument("--dry-run", action="store_true")

    exp = sub.add_parser("export", help="export for other programs")
    ex = exp.add_subparsers(dest="kind", required=True)
    for kind in ("csv", "json", "qif"):
        p = ex.add_parser(kind)
        p.add_argument("path")
        if kind != "json":
            p.add_argument("--account")

    backup = sub.add_parser("backup", help="backups")
    bk = backup.add_subparsers(dest="action", required=True)
    bk.add_parser("create").add_argument("--dir", default=None)
    bk.add_parser("restore").add_argument("archive")
    bk.add_parser("list").add_argument("--dir", default=None)

    p = sub.add_parser("reconcile", help="check an account against a statement balance")
    p.add_argument("account")
    p.add_argument("balance")
    p.add_argument("--on", type=_day)
    p.add_argument("--clear", action="append", default=[])

    p = sub.add_parser("alert", help="alert on large transactions")
    p.add_argument("threshold", help="an amount, or 'off'")
    return parser

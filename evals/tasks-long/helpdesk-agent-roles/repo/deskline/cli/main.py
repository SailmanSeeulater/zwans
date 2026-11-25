"""The ``deskline`` command line.

    deskline [--db FILE] [--as AGENT] COMMAND ...

Without ``--as`` the CLI acts as the system. Exit status: 0 on success, 1 when deskline
refuses or fails (the reason goes to stderr), 2 for usage errors.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from ..desk import Desk
from ..errors import DesklineError
from . import commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deskline", description="A small helpdesk.")
    parser.add_argument("--db", default=os.environ.get("DESKLINE_DB", "desk.json"))
    parser.add_argument("--as", dest="actor", metavar="AGENT", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create a new helpdesk file")

    customer = sub.add_parser("customer").add_subparsers(dest="sub", required=True)
    p = customer.add_parser("add")
    p.add_argument("name")
    p.add_argument("--email", default="")
    p.add_argument("--phone", default="")
    p.add_argument("--address", default="")
    p.add_argument("--org", default="")
    p.add_argument("--tag", action="append", default=[])
    p = customer.add_parser("list")
    p.add_argument("text", nargs="?")
    p = customer.add_parser("show")
    p.add_argument("id")
    p = customer.add_parser("edit")
    p.add_argument("id")
    for name in ("name", "email", "phone", "address", "org"):
        p.add_argument(f"--{name}")
    p = customer.add_parser("delete")
    p.add_argument("id")
    p = customer.add_parser("import")
    p.add_argument("file")

    agent = sub.add_parser("agent").add_subparsers(dest="sub", required=True)
    p = agent.add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("email")
    p.add_argument("--signature", default="")
    p = agent.add_parser("list")
    p.add_argument("--all", action="store_true")
    for name in ("activate", "deactivate"):
        agent.add_parser(name).add_argument("id")

    team = sub.add_parser("team").add_subparsers(dest="sub", required=True)
    p = team.add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    for name in ("join", "leave"):
        p = team.add_parser(name)
        p.add_argument("team")
        p.add_argument("agent")

    queue = sub.add_parser("queue").add_subparsers(dest="sub", required=True)
    p = queue.add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--team")
    p.add_argument("--priority", default="normal")
    p.add_argument("--keyword", action="append", default=[])
    queue.add_parser("list")

    ticket = sub.add_parser("ticket").add_subparsers(dest="sub", required=True)
    p = ticket.add_parser("new")
    p.add_argument("customer")
    p.add_argument("subject")
    p.add_argument("body")
    p.add_argument("--priority")
    p.add_argument("--queue")
    p.add_argument("--tag", action="append", default=[])
    p = ticket.add_parser("show")
    p.add_argument("id")
    p.add_argument("--public", action="store_true")
    p = ticket.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--queue")
    p.add_argument("--assignee")
    for name in ("reply", "note"):
        p = ticket.add_parser(name)
        p.add_argument("id")
        p.add_argument("text")
    for name, arg in (("status", "status"), ("priority", "priority"), ("tag", "tag"),
                      ("untag", "tag"), ("assign", "agent"), ("move", "queue")):
        p = ticket.add_parser(name)
        p.add_argument("id")
        p.add_argument(arg)
    for name in ("take", "delete", "history"):
        ticket.add_parser(name).add_argument("id")
    p = ticket.add_parser("merge")
    p.add_argument("source")
    p.add_argument("target")

    macro = sub.add_parser("macro").add_subparsers(dest="sub", required=True)
    p = macro.add_parser("add")
    p.add_argument("name")
    p.add_argument("--action", action="append", default=[], metavar="TYPE[=VALUE]")
    macro.add_parser("list")
    p = macro.add_parser("run")
    p.add_argument("macro")
    p.add_argument("ticket")
    macro.add_parser("delete").add_argument("id")

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--sort", default="updated")
    p.add_argument("--limit", type=int)

    saved = sub.add_parser("saved").add_subparsers(dest="sub", required=True)
    p = saved.add_parser("add")
    p.add_argument("name")
    p.add_argument("query")
    p.add_argument("--shared", action="store_true")
    p.add_argument("--sort", default="updated")
    saved.add_parser("list")
    for name in ("run", "delete"):
        saved.add_parser(name).add_argument("id")

    p = sub.add_parser("bulk")
    p.add_argument("ids", nargs="+")
    p.add_argument("--status")
    p.add_argument("--priority")
    p.add_argument("--queue")
    p.add_argument("--assignee")
    p.add_argument("--add-tag", action="append", default=[])
    p.add_argument("--remove-tag", action="append", default=[])

    export = sub.add_parser("export").add_subparsers(dest="sub", required=True)
    p = export.add_parser("tickets")
    p.add_argument("--query", default="")
    p.add_argument("--out")
    p = export.add_parser("customers")
    p.add_argument("--out")

    p = sub.add_parser("report")
    p.add_argument("name", choices=["sla", "workload", "satisfaction"])
    p.add_argument("--json", action="store_true")
    p.add_argument("--since")

    p = sub.add_parser("audit")
    p.add_argument("--target")
    p.add_argument("--actor", dest="by_actor", metavar="ACTOR")
    p.add_argument("--action")
    p.add_argument("--since")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("mail-in")
    p.add_argument("file")

    p = sub.add_parser("outbox")
    p.add_argument("--all", action="store_true")

    jobs = sub.add_parser("jobs").add_subparsers(dest="sub", required=True)
    jobs.add_parser("run")

    sla = sub.add_parser("sla").add_subparsers(dest="sub", required=True)
    sla.add_parser("show")
    p = sla.add_parser("set")
    p.add_argument("priority")
    p.add_argument("first_response", type=int)
    p.add_argument("resolution", type=int)

    template = sub.add_parser("template").add_subparsers(dest="sub", required=True)
    template.add_parser("list")
    p = template.add_parser("preview")
    p.add_argument("name")
    p.add_argument("ticket")

    setting = sub.add_parser("setting").add_subparsers(dest="sub", required=True)
    setting.add_parser("show")
    p = setting.add_parser("set")
    p.add_argument("key")
    p.add_argument("value")

    sub.add_parser("backup").add_argument("file")
    sub.add_parser("restore").add_argument("file")

    p = sub.add_parser("survey")
    p.add_argument("token")
    p.add_argument("rating", type=int)
    p.add_argument("remark", nargs="?", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        if args.command == "init":
            Desk.create(args.db)
            print(f"created {args.db}")
            return 0
        desk = Desk.open(args.db)
        ctx = desk.context(args.actor)
        return commands.run(ctx, args)
    except DesklineError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1

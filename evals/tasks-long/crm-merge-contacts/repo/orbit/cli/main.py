"""The `orbit` command.

Every command opens the data file, does its work, and saves the file if it changed
anything. Errors print as "error: ..." on stderr with exit code 1.
"""

import argparse
import os
import sys
from pathlib import Path

from orbit import __version__
from orbit.cli import activity_cmds, contact_cmds, data_cmds, deal_cmds, report_cmds, webhook_cmds
from orbit.clock import clock_from_env
from orbit.crm import Crm
from orbit.errors import CrmError

MODULES = (contact_cmds, deal_cmds, activity_cmds, data_cmds, report_cmds, webhook_cmds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbit", description="A small CRM.")
    parser.add_argument(
        "--db", type=Path, help="the data file (default: $ORBIT_DB or ./orbit.json)"
    )
    parser.add_argument("--json", action="store_true", help="print JSON where it applies")
    parser.add_argument("--version", action="version", version=f"orbit {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in MODULES:
        module.register(commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.db or Path(os.environ.get("ORBIT_DB", "orbit.json"))
    try:
        crm = Crm.open(path, clock=clock_from_env())
        changed = args.handler(crm, args)
        if changed:
            crm.save()
    except CrmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

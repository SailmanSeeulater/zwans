"""libsys import | overdue | notices | loans | holds"""

import argparse
import sys
from datetime import date
from pathlib import Path

from libsys.clock import format_day
from libsys.config import ConfigError, load_branches
from libsys.csvio import ExportError, read_export, to_csv
from libsys.holds import queue_lengths
from libsys.importer import import_events
from libsys.notices import build_notices, render_notice
from libsys.overdue import overdue_loans, overdue_report
from libsys.reports import table
from libsys.store import LibraryStore, StoreError


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="libsys")
    parser.add_argument("--db", default="library.json", help="the records file")
    parser.add_argument("--branches", default="branches.toml", help="the branches file")
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser("import", help="import desk exports")
    imp.add_argument("files", nargs="+")

    overdue = commands.add_parser("overdue", help="the overdue report")
    overdue.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    overdue.add_argument("--csv", action="store_true")

    notices = commands.add_parser("notices", help="overdue notices, one per member")
    notices.add_argument("--as-of", type=date.fromisoformat, default=date.today())

    loans = commands.add_parser("loans", help="a member's loans")
    loans.add_argument("member")

    commands.add_parser("holds", help="how many members wait for each title")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        branches = load_branches(Path(args.branches))
        store = LibraryStore.load(Path(args.db))
    except (ConfigError, StoreError) as exc:
        print(f"libsys: {exc}", file=sys.stderr)
        return 1

    if args.command == "import":
        status = 0
        for name in args.files:
            try:
                rows = read_export(Path(name))
            except (OSError, ExportError) as exc:
                print(f"libsys: {name}: {exc}", file=sys.stderr)
                status = 1
                continue
            result = import_events(store, rows, branches)
            print(f"{name}: {result.describe()}")
            for line, reason in result.rejected:
                print(f"  line {line}: {reason}")
        store.save(Path(args.db))
        return status

    if args.command == "overdue":
        if args.csv:
            items = overdue_loans(store, branches, args.as_of)
            rows = [
                [
                    i.loan.branch,
                    i.loan.number,
                    i.loan.member,
                    i.loan.title,
                    i.loan.due.isoformat(),
                    i.days,
                    f"{i.fine:.2f}",
                ]
                for i in items
            ]
            print(
                to_csv(["branch", "loan_no", "member", "title", "due", "days", "fine"], rows),
                end="",
            )
        else:
            print(overdue_report(store, branches, args.as_of), end="")
        return 0

    if args.command == "notices":
        for notice in build_notices(store, branches, args.as_of):
            print(render_notice(notice, branches, args.as_of))
            print("-" * 60)
        return 0

    if args.command == "loans":
        member = args.member.strip().upper()
        rows = []
        for loan in store.loans_for_member(member):
            status = "returned" if loan.returned_at else f"due {format_day(loan.due)}"
            rows.append([f"{loan.branch}-{loan.number}", loan.title, status])
        if not rows:
            print(f"{member} has no loans.")
        else:
            print("\n".join(table(["loan", "title", "status"], rows)))
        return 0

    if args.command == "holds":
        for (branch, title), count in sorted(queue_lengths(store).items()):
            print(f"{branch}  {count:3d}  {title}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""CLI handlers for reports, imports, exports and backups."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from .. import backup as backups
from ..book import Book
from ..exporters import export_csv, export_json, export_qif
from ..importers import import_csv, import_statement
from ..reports import budget_report, monthly_report, net_worth, yearly_report
from ..reports import monthly as monthly_module
from ..reports import networth as networth_module
from ..reports import yearly as yearly_module
from ..reports.budget_report import render_budget
from ..reports.monthly import render_monthly
from ..reports.networth import render_net_worth
from ..reports.yearly import render_yearly
from .output import emit_json, out


def report(book: Book, args: Namespace) -> bool:
    if args.kind == "monthly":
        result = monthly_report(book, args.month, args.currency)
        emit_json(monthly_module.to_dict(result)) if args.json else out(render_monthly(result))
    elif args.kind == "yearly":
        result = yearly_report(book, args.year, args.currency)
        emit_json(yearly_module.to_dict(result)) if args.json else out(render_yearly(result))
    elif args.kind == "networth":
        result = net_worth(book, args.on, args.currency)
        emit_json(networth_module.to_dict(result)) if args.json else out(render_net_worth(result))
    elif args.kind == "budget":
        from ..reports.budget_report import to_dict

        lines = budget_report(book, args.month)
        if args.json:
            emit_json(to_dict(lines))
        else:
            out(render_budget(lines, args.month, book.settings.base_currency))
    return False


def import_command(book: Book, args: Namespace) -> bool:
    if args.kind == "csv":
        result = import_csv(book, args.account, args.path, args.profile, dry_run=args.dry_run)
    else:
        result = import_statement(book, args.account, args.path, dry_run=args.dry_run)
    out(result.summary() + (" (dry run)" if args.dry_run else ""))
    return bool(result.added) and not args.dry_run


def export_command(book: Book, args: Namespace) -> bool:
    if args.kind == "csv":
        count = export_csv(book, args.path, account=args.account)
    elif args.kind == "json":
        count = export_json(book, args.path)
    else:
        count = export_qif(book, args.path, account=args.account)
    out(f"wrote {count} entries to {args.path}")
    return False


def backup_command(book: Book, args: Namespace, data_file: Path) -> bool:
    folder = Path(getattr(args, "dir", None) or data_file.parent / "backups")
    if args.action == "create":
        path = backups.create_backup(book, folder)
        out(f"backed up to {path}")
    elif args.action == "list":
        for path in backups.list_backups(folder):
            out(path.name)
    elif args.action == "restore":
        restored = backups.restore_backup(args.archive, data_file, clock=book.clock)
        out(f"restored {len(restored.accounts)} accounts and "
            f"{len(restored.transactions)} transactions into {data_file}")
    return False

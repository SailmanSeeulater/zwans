"""CLI: supplier imports, the outbox, backups, settings and the audit log."""

import argparse
from pathlib import Path
from typing import Any

from shopdesk.cli.output import Context, command, group
from shopdesk.errors import StoreError
from shopdesk.notify import as_json_line
from shopdesk.store.backup import create_backup, list_backups, restore_backup


def register(commands: Any) -> None:
    p = command(commands, "import", import_file, saves=True, help="import a supplier price file")
    p.add_argument("file", type=Path)
    p.add_argument("--supplier", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--create-categories", action="store_true")

    outbox = group(commands, "outbox", "notifications waiting to go out")
    p = command(outbox, "list", outbox_list, help="list notifications")
    p.add_argument("--all", action="store_true", help="include sent ones")
    p = command(outbox, "flush", outbox_flush, saves=True, help="write pending ones out")
    p.add_argument("--to", type=Path, required=True, help="JSON-lines file to append to")

    backups = group(commands, "backup", "backups of the data file")
    p = command(backups, "create", backup_create, help="back up the data file")
    p.add_argument("--dir", type=Path, default=Path("backups"))
    p = command(backups, "list", backup_list, help="list backups")
    p.add_argument("--dir", type=Path, default=Path("backups"))
    p = command(backups, "restore", backup_restore, help="put a backup back")
    p.add_argument("file", type=Path)

    settings = group(commands, "settings", "shop settings")
    command(settings, "show", settings_show, help="show settings")
    p = command(settings, "set", settings_set, saves=True, help="change a setting")
    p.add_argument("key")
    p.add_argument("value")

    p = command(commands, "audit", audit, help="the audit log")
    p.add_argument("--subject")
    p.add_argument("--limit", type=int, default=50)


def import_file(ctx: Context, args: argparse.Namespace) -> int:
    try:
        text = args.file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise StoreError(f"Can't read {args.file}: {exc}") from None
    result = ctx.shop.import_supplier(
        text, args.supplier, dry_run=args.dry_run, create_categories=args.create_categories
    )
    for line, message in result.errors:
        print(f"line {line}: {message}", file=ctx.err)
    ctx.say(result.summary())
    if args.dry_run:
        args.saves = False
    return 0


def outbox_list(ctx: Context, args: argparse.Namespace) -> int:
    for note in ctx.shop.outbox(pending_only=not args.all):
        ctx.say(as_json_line(note))
    return 0


def outbox_flush(ctx: Context, args: argparse.Namespace) -> int:
    with args.to.open("a", encoding="utf-8") as handle:
        sent = ctx.shop.notifier.flush(lambda note: handle.write(as_json_line(note) + "\n"))
    ctx.say(f"Wrote {sent} notifications to {args.to}")
    return 0


def backup_create(ctx: Context, args: argparse.Namespace) -> int:
    target = create_backup(ctx.path, args.dir, ctx.clock)
    ctx.say(f"Backed up to {target}")
    return 0


def backup_list(ctx: Context, args: argparse.Namespace) -> int:
    for path in list_backups(args.dir):
        ctx.say(str(path))
    return 0


def backup_restore(ctx: Context, args: argparse.Namespace) -> int:
    restore_backup(args.file, ctx.path)
    ctx.say(f"Restored {args.file} to {ctx.path}")
    return 0


def settings_show(ctx: Context, args: argparse.Namespace) -> int:
    for key, value in ctx.shop.settings.to_dict().items():
        ctx.say(f"{key} = {value}")
    return 0


def settings_set(ctx: Context, args: argparse.Namespace) -> int:
    ctx.shop.settings.set(args.key, args.value)
    ctx.say(f"{args.key} set")
    return 0


def audit(ctx: Context, args: argparse.Namespace) -> int:
    entries = ctx.shop.audit.entries(subject=args.subject)
    for entry in entries[-args.limit :]:
        ctx.say(f"{entry.at}  {entry.action:<20} {entry.subject}")
    return 0

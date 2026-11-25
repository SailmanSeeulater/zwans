"""orbit import, export, backup, backups, restore, undo, history, reindex."""

import json
from pathlib import Path

from orbit.cli.output import emit_json, say
from orbit.io.csv_export import export_contacts
from orbit.io.csv_import import import_contacts
from orbit.io.json_export import contact_dossier, export_all
from orbit.io.vcard import export_vcards
from orbit.jobs.reindex import check_indexes, reindex
from orbit.store import backup


def register(commands) -> None:
    imp = commands.add_parser("import", help="import contacts from CSV")
    imp.add_argument("file", type=Path)
    imp.add_argument("--dry-run", action="store_true")
    imp.set_defaults(handler=import_csv)

    exp = commands.add_parser("export", help="export contacts")
    sub = exp.add_subparsers(dest="what", required=True)
    csv = sub.add_parser("csv")
    csv.add_argument("--all", action="store_true", help="include archived contacts")
    csv.add_argument("--out", type=Path)
    csv.set_defaults(handler=export_csv)
    vcf = sub.add_parser("vcard")
    vcf.add_argument("ids", nargs="*")
    vcf.add_argument("--out", type=Path)
    vcf.set_defaults(handler=export_vcard)
    one = sub.add_parser("contact", help="everything about one contact, as JSON")
    one.add_argument("id")
    one.add_argument("--out", type=Path)
    one.set_defaults(handler=export_contact)
    everything = sub.add_parser("all", help="the whole CRM, as JSON")
    everything.add_argument("--out", type=Path)
    everything.set_defaults(handler=export_everything)

    back = commands.add_parser("backup", help="save a backup of the data file")
    back.add_argument("--dir", type=Path)
    back.set_defaults(handler=make_backup)
    backs = commands.add_parser("backups", help="list backups")
    backs.add_argument("--dir", type=Path)
    backs.set_defaults(handler=list_backups)
    rest = commands.add_parser("restore", help="replace the data with a backup")
    rest.add_argument("file", type=Path)
    rest.set_defaults(handler=restore_backup)

    commands.add_parser("undo", help="undo the last change").set_defaults(handler=undo)
    commands.add_parser("history", help="what undo would undo").set_defaults(handler=history)

    re = commands.add_parser("reindex", help="rebuild (or --check) the search indexes")
    re.add_argument("--check", action="store_true")
    re.set_defaults(handler=rebuild_indexes)


def _write(text: str, out: Path | None) -> None:
    if out is None:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        out.write_text(text, encoding="utf-8")
        say(f"Wrote {out}")


def _backup_dir(crm, given: Path | None) -> Path:
    if given is not None:
        return given
    base = crm.store.path.parent if crm.store.path else Path.cwd()
    return base / "backups"


def import_csv(crm, args) -> bool:
    result = import_contacts(crm, args.file.read_text(encoding="utf-8"), dry_run=args.dry_run)
    for line, why in result.skipped:
        say(f"line {line}: {why}")
    say(("Would have: " if args.dry_run else "") + result.summary())
    return not args.dry_run


def export_csv(crm, args) -> bool:
    _write(export_contacts(crm, include_archived=args.all), args.out)
    return False


def export_vcard(crm, args) -> bool:
    _write(export_vcards(crm, args.ids), args.out)
    return False


def export_contact(crm, args) -> bool:
    _write(json.dumps(contact_dossier(crm, args.id), indent=2, ensure_ascii=False) + "\n", args.out)
    return False


def export_everything(crm, args) -> bool:
    if args.out is None:
        emit_json(export_all(crm))
    else:
        _write(json.dumps(export_all(crm), indent=2, ensure_ascii=False) + "\n", args.out)
    return False


def make_backup(crm, args) -> bool:
    path = backup.create_backup(crm.store, _backup_dir(crm, args.dir), crm.clock)
    say(f"Backed up to {path}")
    return False


def list_backups(crm, args) -> bool:
    found = backup.list_backups(_backup_dir(crm, args.dir))
    if found:
        say(*(backup.describe(path) for path in found))
    else:
        say("No backups.")
    return False


def restore_backup(crm, args) -> bool:
    counts = backup.restore(args.file, crm.store)
    crm.rebuild_indexes()
    say(f"Restored {counts.get('contacts', 0)} contacts and {counts.get('deals', 0)} deals")
    return True


def undo(crm, args) -> bool:
    label = crm.undo()
    say(f"Undid {label}")
    return True


def history(crm, args) -> bool:
    entries = crm.history()
    for entry in entries:
        say(f"{entry['at']}  {entry['label']}  ({entry['changes']} rows)")
    if not entries:
        say("Nothing to undo.")
    return False


def rebuild_indexes(crm, args) -> bool:
    if args.check:
        problems = check_indexes(crm)
        say(*(problems or ["Indexes match the data."]))
        return False
    counts = reindex(crm)
    say(", ".join(f"{name}: {n}" for name, n in counts.items()))
    return False

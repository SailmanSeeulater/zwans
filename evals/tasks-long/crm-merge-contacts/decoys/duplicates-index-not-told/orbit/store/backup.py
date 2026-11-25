"""Backups: a copy of the whole data file, with a little header, in a folder of their own.

    {"backup": {"created_at": "...", "source": "crm.json", "counts": {"contacts": 12, ...}},
     "document": {...the data file...}}

Restoring checks every row before anything is replaced, so a damaged backup never
clobbers good data. A restored file starts with an empty undo history.
"""

import json
from pathlib import Path

from orbit.clock import Clock
from orbit.errors import StoreError
from orbit.store.jsonstore import Store, read_document, write_document
from orbit.store.migrations import FORMAT_VERSION, upgrade

REQUIRED = {
    "contacts": ("id", "first_name"),
    "companies": ("id", "name"),
    "deals": ("id", "title", "stage"),
    "notes": ("id", "contact_id", "body"),
    "tasks": ("id", "contact_id", "title"),
    "emails": ("id", "contact_id", "subject"),
    "timeline": ("id", "contact_id", "kind"),
    "fields": ("id", "type"),
    "subscriptions": ("id", "url"),
    "outbox": ("id", "subscription_id", "event"),
    "merged": ("id", "into"),
}


def backup_name(stamp: str) -> str:
    return "orbit-" + stamp.replace(":", "").replace("-", "") + ".json"


def create_backup(store: Store, folder: Path, clock: Clock) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = clock()
    document = store.document()
    header = {
        "created_at": stamp,
        "source": str(store.path) if store.path else None,
        "counts": {name: len(rows) for name, rows in document["tables"].items()},
    }
    target = folder / backup_name(stamp)
    write_document(target, {"backup": header, "document": document})
    return target


def list_backups(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("orbit-*.json"))


def read_backup(path: Path) -> dict:
    wrapper = read_document(path)
    if "document" not in wrapper or "backup" not in wrapper:
        raise StoreError(f"{path} is not an orbit backup.")
    document = upgrade(wrapper["document"])
    tables = document.get("tables", {})
    checked = {}
    for name, required in REQUIRED.items():
        rows = tables.get(name, {})
        for key, row in rows.items():
            missing = [field for field in required if field not in row]
            if missing:
                raise StoreError(f"{path}: {name} row {key!r} has no {', '.join(missing)}.")
            if row["id"] != key:
                raise StoreError(f"{path}: {name} row {key!r} has id {row['id']!r}.")
        checked[name] = rows
    return {"format": "orbit", "version": FORMAT_VERSION, "tables": checked, "undo": []}


def restore(path: Path, store: Store) -> dict[str, int]:
    document = read_backup(path)
    store.load_document(document)
    return {name: len(rows) for name, rows in document["tables"].items()}


def describe(path: Path) -> str:
    header = read_document(path).get("backup", {})
    counts = ", ".join(f"{n} {name}" for name, n in header.get("counts", {}).items() if n)
    return f"{path.name}  {header.get('created_at', '?')}  {counts or 'empty'}"


def dump(path: Path) -> str:
    return json.dumps(read_backup(path), indent=1, ensure_ascii=False)

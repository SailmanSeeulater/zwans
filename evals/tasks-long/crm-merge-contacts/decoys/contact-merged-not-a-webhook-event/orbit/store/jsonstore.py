"""The data file: one JSON document holding every table and the undo history.

    {"format": "orbit", "version": 2,
     "tables": {"contacts": {"c1": {...}, ...}, "deals": {...}, ...},
     "undo": [...]}

Rows are plain dicts keyed by id. `get` and `rows` hand out copies, so nothing outside the
store can change a row without going through `put`, which is also how the undo log sees
every change. Saving writes a temporary file and renames it over the real one.
"""

import copy
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from orbit import ids
from orbit.errors import StoreError
from orbit.store.migrations import FORMAT_VERSION, upgrade

TABLES = (
    "contacts",
    "companies",
    "deals",
    "notes",
    "tasks",
    "emails",
    "timeline",
    "fields",
    "subscriptions",
    "outbox",
    "merged",  # {"id": merged contact id, "into": the contact it was merged into, "at": ...}
)

type Watcher = Callable[[str, str, dict | None], None]


def read_document(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path} is not valid JSON: {exc}") from None
    except OSError as exc:
        raise StoreError(f"Can't read {path}: {exc}") from None
    if not isinstance(document, dict):
        raise StoreError(f"{path} is not an orbit data file.")
    return document


def write_document(path: Path, document: dict) -> None:
    text = json.dumps(document, indent=1, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise StoreError(f"Can't write {path}: {exc}") from None


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.tables: dict[str, dict[str, dict]] = {name: {} for name in TABLES}
        self.undo: list[dict] = []
        self._watchers: list[Watcher] = []

    @classmethod
    def memory(cls) -> "Store":
        return cls()

    @classmethod
    def open(cls, path: str | Path) -> "Store":
        store = cls(Path(path))
        if store.path.exists():
            store.load_document(read_document(store.path))
        return store

    # -- the document -----------------------------------------------------------------

    def load_document(self, document: dict) -> None:
        data = upgrade(document)
        tables = data.get("tables", {})
        if not isinstance(tables, dict):
            raise StoreError("The data file's tables are not an object.")
        self.tables = {name: dict(tables.get(name, {})) for name in TABLES}
        self.undo = list(data.get("undo", []))

    def document(self) -> dict:
        return {
            "format": "orbit",
            "version": FORMAT_VERSION,
            "tables": copy.deepcopy(self.tables),
            "undo": copy.deepcopy(self.undo),
        }

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise StoreError("This store has no file to save to.")
        write_document(target, self.document())
        return target

    # -- rows -------------------------------------------------------------------------

    def _table(self, name: str) -> dict[str, dict]:
        try:
            return self.tables[name]
        except KeyError:
            raise StoreError(f"No table {name!r}.") from None

    def get(self, table: str, key: str) -> dict | None:
        row = self._table(table).get(key)
        return copy.deepcopy(row) if row is not None else None

    def has(self, table: str, key: str) -> bool:
        return key in self._table(table)

    def keys(self, table: str) -> list[str]:
        return sorted(self._table(table), key=ids.sort_key)

    def rows(self, table: str) -> list[dict]:
        rows = self._table(table)
        return [copy.deepcopy(rows[key]) for key in self.keys(table)]

    def iter_rows(self, table: str) -> Iterator[dict]:
        yield from self.rows(table)

    def find(self, table: str, **match) -> list[dict]:
        return [
            row
            for row in self.rows(table)
            if all(row.get(key) == value for key, value in match.items())
        ]

    def count(self, table: str) -> int:
        return len(self._table(table))

    def put(self, table: str, row: dict) -> None:
        rows = self._table(table)
        key = row["id"]
        self._notify(table, key, rows.get(key))
        rows[key] = copy.deepcopy(row)

    def delete(self, table: str, key: str) -> None:
        rows = self._table(table)
        if key not in rows:
            return
        self._notify(table, key, rows[key])
        del rows[key]

    # -- watching changes ---------------------------------------------------------------

    def watch(self, watcher: Watcher) -> None:
        self._watchers.append(watcher)

    def unwatch(self, watcher: Watcher) -> None:
        self._watchers.remove(watcher)

    def _notify(self, table: str, key: str, before: dict | None) -> None:
        for watcher in list(self._watchers):
            watcher(table, key, before)

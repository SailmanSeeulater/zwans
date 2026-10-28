"""The database: every table in memory, saved to one JSON file.

    {
      "version": 1,
      "products":  [{"sku": ..., "name": ..., ...}, ...],
      "movements": [{"id": ..., "sku": ..., ...}, ...],
      "alerts":    [...],
      "counters":  {"movement": 12}
    }

Changes go through `with db.transaction():`. When the block finishes the file is saved
(atomically: written next to it, then moved into place). When it raises, every table is put
back as it was and the derived structures (the lookup cache and the search index) are
rebuilt, so nothing half-done is ever visible or saved.
"""

import copy
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .cache import LookupCache
from .errors import CorruptDatabase
from .search import SearchIndex

SCHEMA_VERSION = 1
TABLES = ("products", "movements", "alerts")


def search_text(record: dict[str, Any]) -> str:
    """What the search index knows about a product record."""
    return f"{record['sku']} {record['name']}"


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
        self.counters: dict[str, int] = {}
        self.cache = LookupCache()
        self.index = SearchIndex()
        self._depth = 0
        if self.path is not None and self.path.exists():
            self._load()

    @classmethod
    def memory(cls) -> "Database":
        return cls(None)

    # ------------------------------------------------------------------ file

    def _load(self) -> None:
        assert self.path is not None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CorruptDatabase(f"cannot read {self.path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            raise CorruptDatabase(
                f"{self.path} is not a stockroom database (version {SCHEMA_VERSION})"
            )
        for name in TABLES:
            rows = data.get(name, [])
            if not isinstance(rows, list):
                raise CorruptDatabase(f"{self.path}: {name} should be a list")
            self.tables[name] = rows
        self.counters = dict(data.get("counters", {}))
        self._rebuild_derived()

    def save(self) -> None:
        if self.path is None:
            return
        data = {"version": SCHEMA_VERSION, **self.tables, "counters": self.counters}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    # ---------------------------------------------------------- derived data

    def _rebuild_derived(self) -> None:
        self.cache.clear()
        self.index.rebuild(
            (record["sku"], search_text(record)) for record in self.tables["products"]
        )

    # ---------------------------------------------------------- transactions

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        """Group changes: all of them are kept and saved, or none are. Nests."""
        if self._depth:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        snapshot = copy.deepcopy((self.tables, self.counters))
        self._depth = 1
        try:
            yield self
        except BaseException:
            self.tables, self.counters = snapshot
            self._rebuild_derived()
            raise
        finally:
            self._depth = 0
        self.save()

    def next_id(self, counter: str) -> int:
        self.counters[counter] = self.counters.get(counter, 0) + 1
        return self.counters[counter]

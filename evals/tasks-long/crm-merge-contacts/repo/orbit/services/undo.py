"""The undo log.

Every command runs as one operation. While it runs, the log watches the store and keeps
the first "before" image of every row the command touches; when the command finishes,
those images become one entry in the log, which is saved in the data file with
everything else. Undo puts the images back, newest entry first. Operations nest: a
command that calls other commands still makes a single entry.

If a command fails halfway, its changes are rolled back on the spot.

The outbox is not part of undo: a webhook that has been queued stays queued.
"""

from orbit.clock import Clock
from orbit.errors import NothingToUndo
from orbit.store import Store

EXCLUDED = frozenset({"outbox"})


class Operation:
    def __init__(self, log: "UndoLog", label: str) -> None:
        self.log = log
        self.label = label

    def __enter__(self) -> "Operation":
        self.log._begin(self.label)
        return self

    def __exit__(self, kind, error, traceback) -> None:
        self.log._end(failed=kind is not None)


class UndoLog:
    def __init__(self, store: Store, clock: Clock, limit: int = 50) -> None:
        self.store = store
        self.clock = clock
        self.limit = limit
        self._depth = 0
        self._label = ""
        self._before: dict[tuple[str, str], dict | None] = {}

    def operation(self, label: str) -> Operation:
        return Operation(self, label)

    @property
    def busy(self) -> bool:
        return self._depth > 0

    def _begin(self, label: str) -> None:
        self._depth += 1
        if self._depth > 1:
            return
        self._label = label
        self._before = {}
        self.store.watch(self._record)

    def _record(self, table: str, key: str, before: dict | None) -> None:
        self._before.setdefault((table, key), before)

    def _end(self, failed: bool) -> None:
        self._depth -= 1
        if self._depth > 0:
            return
        self.store.unwatch(self._record)
        changes = [
            {"table": table, "id": key, "before": before}
            for (table, key), before in self._before.items()
        ]
        self._before = {}
        if failed:
            self._restore(changes)
            return
        changes = [change for change in changes if change["table"] not in EXCLUDED]
        if not changes:
            return
        self.store.undo.append({"label": self._label, "at": self.clock(), "changes": changes})
        del self.store.undo[: -self.limit]

    def _restore(self, changes: list[dict]) -> None:
        for change in reversed(changes):
            if change["before"] is None:
                self.store.delete(change["table"], change["id"])
            else:
                self.store.put(change["table"], change["before"])

    def undo(self) -> str:
        if self.busy:
            raise RuntimeError("Can't undo in the middle of an operation.")
        if not self.store.undo:
            raise NothingToUndo()
        entry = self.store.undo.pop()
        self._restore(entry["changes"])
        return entry["label"]

    def history(self) -> list[dict]:
        return [
            {"label": entry["label"], "at": entry["at"], "changes": len(entry["changes"])}
            for entry in reversed(self.store.undo)
        ]

"""The audit log: one entry for every command anyone tried to run, whatever the outcome.

Outcomes:
    ok        the command ran and its events were recorded
    denied    the actor lacked the permission
    rejected  the command was invalid or did not fit the order's state
"""

import json
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            with self.path.open(encoding="utf-8") as file:
                self._entries = [json.loads(line) for line in file if line.strip()]

    def record(
        self,
        *,
        at: str,
        actor: str,
        role: str,
        command: str,
        order_id: str,
        outcome: str,
        details: dict[str, Any],
        error: str = "",
    ) -> None:
        entry = {
            "at": at,
            "actor": actor,
            "role": role,
            "command": command,
            "order_id": order_id,
            "outcome": outcome,
            "details": details,
            "error": error,
        }
        self._entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

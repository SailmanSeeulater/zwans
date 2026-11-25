"""The audit log: an append-only record of who changed what.

Entries live in the store, so they are part of the same transaction as the change they
describe: a change that fails leaves no entry behind.
"""

from __future__ import annotations

from typing import Any

from .models import AuditEntry
from .store import Store

SYSTEM = "system"


def record(
    store: Store, at: str, actor: str | None, action: str, target: str, details: dict[str, Any]
) -> AuditEntry:
    entry = AuditEntry(
        seq=len(store.audit) + 1,
        at=at,
        actor=actor or SYSTEM,
        action=action,
        target=target,
        details=_plain(details),
    )
    store.audit.append(entry)
    return entry


def _plain(value: Any) -> Any:
    """Copy details into plain JSON-able values so later edits can't change history."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def find(
    store: Store,
    *,
    target: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: str | None = None,
) -> list[AuditEntry]:
    out = []
    for entry in store.audit:
        if target is not None and entry.target != target:
            continue
        if actor is not None and entry.actor != actor:
            continue
        if action is not None:
            if action.endswith("*"):
                if not entry.action.startswith(action[:-1]):
                    continue
            elif entry.action != action:
                continue
        if since is not None and entry.at < since:
            continue
        out.append(entry)
    return out


def changes(before: Any, after: Any, fields: list[str]) -> dict[str, list[Any]]:
    """{field: [old, new]} for each field whose value differs between two records."""
    diff = {}
    for name in fields:
        old, new = getattr(before, name), getattr(after, name)
        if old != new:
            diff[name] = [old, new]
    return diff

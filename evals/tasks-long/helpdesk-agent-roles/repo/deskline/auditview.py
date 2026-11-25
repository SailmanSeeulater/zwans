"""The audit log viewer: filtered audit entries for people to read."""

from __future__ import annotations

import json
from typing import Any

from . import audit
from .context import Context


def entries(
    ctx: Context,
    *,
    target: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Matching entries, newest first, as plain dicts."""
    found = audit.find(ctx.store, target=target, actor=actor, action=action, since=since)
    found.reverse()
    if limit is not None:
        found = found[:limit]
    return [entry.to_dict() for entry in found]


def _value(value: Any) -> str:
    if isinstance(value, str):
        return value if value and " " not in value else json.dumps(value)
    return json.dumps(value, sort_keys=True)


def format_entry(entry: dict[str, Any]) -> str:
    details = " ".join(f"{k}={_value(v)}" for k, v in sorted(entry["details"].items()))
    line = f"{entry['seq']:>5}  {entry['at']}  {entry['actor']:<10}  {entry['action']:<24}  {entry['target']}"
    return f"{line}  {details}".rstrip()


def render(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no audit entries)\n"
    return "\n".join(format_entry(row) for row in rows) + "\n"


def history(ctx: Context, ticket_id: str) -> list[dict[str, Any]]:
    """A ticket's own trail, oldest first."""
    rows = entries(ctx, target=ticket_id)
    rows.reverse()
    return rows

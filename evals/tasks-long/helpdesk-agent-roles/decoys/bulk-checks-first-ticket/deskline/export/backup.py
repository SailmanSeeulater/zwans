"""Full backups: the whole helpdesk as one JSON document, and restoring from one."""

from __future__ import annotations

import json
from typing import Any

from ..context import Context
from ..errors import StoreError
from ..permissions import require
from ..store import Store
from ..store.migrate import CURRENT_VERSION, upgrade


def dump(ctx: Context) -> dict[str, Any]:
    require(ctx, "admin")
    document = {
        "format": "deskline",
        "version": CURRENT_VERSION,
        "backup_at": ctx.now(),
        "data": ctx.store.to_data(),
    }
    with ctx.store.transaction():
        ctx.record("desk.backed_up", "desk", tickets=len(ctx.store.tickets))
    return document


def dumps(ctx: Context) -> str:
    return json.dumps(dump(ctx), indent=1, sort_keys=True)


def restore(ctx: Context, document: dict[str, Any]) -> dict[str, int]:
    """Replace everything in the store with the backup's contents."""
    require(ctx, "admin")
    data = upgrade(document)
    fresh = Store.from_data(data)
    if not fresh.queues and not fresh.tickets and not fresh.customers:
        raise StoreError("refusing to restore an empty backup")
    with ctx.store.transaction():
        audit_before = list(ctx.store.audit)
        for name in ("customers", "agents", "teams", "queues", "tickets", "macros", "searches",
                     "surveys", "sla", "outbox", "counters", "settings"):
            setattr(ctx.store, name, getattr(fresh, name))
        ctx.store.audit = fresh.audit or audit_before
        ctx.record(
            "desk.restored",
            "desk",
            backup_at=document.get("backup_at", ""),
            tickets=len(fresh.tickets),
        )
    return {"tickets": len(fresh.tickets), "customers": len(fresh.customers)}

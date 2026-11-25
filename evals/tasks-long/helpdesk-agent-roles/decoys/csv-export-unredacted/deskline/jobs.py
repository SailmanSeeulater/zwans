"""Housekeeping that runs on a schedule (cron calls ``deskline jobs run``)."""

from __future__ import annotations

from typing import Any

from .context import Context
from .mail import outbox
from .permissions import require
from .services import sla, tickets


def run_all(ctx: Context) -> dict[str, Any]:
    require(ctx, "admin")
    breaches = sla.check_breaches(ctx)
    closed = tickets.close_solved(ctx, ctx.setting("auto_close_days"))
    with ctx.store.transaction():
        purged = outbox.purge(ctx.store, ctx.now(), ctx.setting("outbox_keep_days"))
        ctx.record(
            "jobs.ran",
            "desk",
            breaches=len(breaches),
            closed=len(closed),
            purged=purged,
        )
    return {
        "breaches": [f"{ticket}:{target}" for ticket, target in breaches],
        "closed": closed,
        "purged": purged,
    }

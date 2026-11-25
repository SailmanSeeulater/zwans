"""Queues sort incoming tickets; each may belong to a team whose members get told."""

from __future__ import annotations

import re

from ..context import Context
from ..errors import Conflict, ValidationError
from ..models import PRIORITIES, Queue
from ..store import Store
from ..textutil import is_handle


def ensure_default(store: Store, queue_id: str = "general") -> None:
    if queue_id not in store.queues:
        store.queues[queue_id] = Queue(id=queue_id, name=queue_id.title())


def create_queue(
    ctx: Context,
    queue_id: str,
    name: str,
    *,
    team: str | None = None,
    default_priority: str = "normal",
    keywords: list[str] | tuple[str, ...] = (),
) -> Queue:
    if not is_handle(queue_id):
        raise ValidationError(f"bad queue id {queue_id!r}")
    if default_priority not in PRIORITIES:
        raise ValidationError(f"unknown priority {default_priority!r}")
    with ctx.store.transaction():
        if queue_id in ctx.store.queues:
            raise Conflict(f"queue {queue_id} already exists")
        if team is not None:
            ctx.store.team(team)
        queue = Queue(
            id=queue_id,
            name=name.strip() or queue_id,
            team=team,
            default_priority=default_priority,
            keywords=[k.lower() for k in keywords if k.strip()],
        )
        ctx.store.queues[queue_id] = queue
        ctx.record("queue.created", queue_id, name=queue.name, team=team)
    return queue


def update_queue(
    ctx: Context,
    queue_id: str,
    *,
    name: str | None = None,
    team: str | None = None,
    default_priority: str | None = None,
    keywords: list[str] | None = None,
) -> Queue:
    with ctx.store.transaction():
        queue = ctx.store.queue(queue_id)
        changes = {}
        if name is not None and name != queue.name:
            changes["name"] = [queue.name, name]
            queue.name = name
        if team is not None:
            new_team = team or None
            if new_team is not None:
                ctx.store.team(new_team)
            if new_team != queue.team:
                changes["team"] = [queue.team, new_team]
                queue.team = new_team
        if default_priority is not None:
            if default_priority not in PRIORITIES:
                raise ValidationError(f"unknown priority {default_priority!r}")
            if default_priority != queue.default_priority:
                changes["default_priority"] = [queue.default_priority, default_priority]
                queue.default_priority = default_priority
        if keywords is not None:
            queue.keywords = [k.lower() for k in keywords if k.strip()]
            changes["keywords"] = list(queue.keywords)
        if changes:
            ctx.record("queue.updated", queue_id, changes=changes)
    return queue


def list_queues(ctx: Context) -> list[Queue]:
    return sorted(ctx.store.queues.values(), key=lambda q: q.id)


def route(store: Store, text: str) -> str | None:
    """The first queue (by id) with a keyword in the text, if any."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    for queue in sorted(store.queues.values(), key=lambda q: q.id):
        if any(keyword in words for keyword in queue.keywords):
            return queue.id
    return None

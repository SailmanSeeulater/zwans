"""Merging duplicate tickets.

``merge(ctx, source, target)`` copies the source ticket's conversation and tags onto the
target, leaves a note on both, and closes the source with ``merged_into`` set.
"""

from __future__ import annotations

from ..context import Context
from ..errors import Conflict, ValidationError
from ..models import Comment, Ticket
from ..permissions import require
from . import tickets


def _check(source: Ticket, target: Ticket) -> None:
    if source.id == target.id:
        raise ValidationError("cannot merge a ticket into itself")
    for ticket in (source, target):
        if ticket.status == "closed":
            raise Conflict(f"{ticket.id} is closed")
        if ticket.merged_into:
            raise Conflict(f"{ticket.id} was already merged into {ticket.merged_into}")


def merge(ctx: Context, source_id: str, target_id: str) -> Ticket:
    with ctx.store.transaction():
        source = ctx.store.ticket(source_id)
        target = ctx.store.ticket(target_id)
        require(ctx, "ticket.edit", ticket=source)
        require(ctx, "ticket.edit", ticket=target)
        _check(source, target)
        now = ctx.now()
        for comment in sorted(source.comments, key=lambda c: c.created_at):
            target.comments.append(
                Comment(
                    id=target.next_comment_id(),
                    author_kind=comment.author_kind,
                    author=comment.author,
                    body=comment.body,
                    public=comment.public,
                    created_at=comment.created_at,
                    via="merge",
                    from_address=comment.from_address,
                )
            )
        for name in source.tags:
            if name not in target.tags:
                target.tags.append(name)
        tickets.post_note(ctx, target, f"Merged {source.id} ({source.subject}) into this ticket.", via="merge")
        tickets.post_note(ctx, source, f"Merged into {target.id}.", via="merge")
        source.status = "closed"
        source.closed_at = now
        source.merged_into = target.id
        target.updated_at = now
        if target.first_response_at is None and source.first_response_at is not None:
            target.first_response_at = source.first_response_at
        ctx.record("ticket.merged", target.id, source=source.id, into=target.id)
    return target

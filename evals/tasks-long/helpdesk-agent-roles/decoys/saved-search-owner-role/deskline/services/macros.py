"""Macros: canned sequences of ticket actions, applied in one go.

A macro is a list of actions such as ``{"type": "set_status", "value": "pending"}`` or
``{"type": "reply", "value": "Hello {{ customer.name }}, ..."}``. Reply and note texts
are templates rendered against the ticket. Applying a macro is all-or-nothing.
"""

from __future__ import annotations

from ..context import Context
from ..errors import ValidationError
from ..mail import templates
from ..models import MACRO_ACTIONS, PRIORITIES, STATUSES, Macro, Ticket
from ..permissions import require, require_assign
from . import tickets

_NEEDS_VALUE = {"set_status", "set_priority", "set_queue", "add_tag", "remove_tag", "reply", "note"}


def validate_actions(ctx: Context, actions: list[dict[str, str]]) -> list[dict[str, str]]:
    if not actions:
        raise ValidationError("a macro needs at least one action")
    clean = []
    for n, action in enumerate(actions, 1):
        kind = action.get("type")
        if kind not in MACRO_ACTIONS:
            raise ValidationError(f"action {n}: unknown type {kind!r}")
        value = str(action.get("value", "")).strip()
        if kind in _NEEDS_VALUE and not value:
            raise ValidationError(f"action {n}: {kind} needs a value")
        if kind == "set_status" and value not in STATUSES:
            raise ValidationError(f"action {n}: unknown status {value!r}")
        if kind == "set_priority" and value not in PRIORITIES:
            raise ValidationError(f"action {n}: unknown priority {value!r}")
        if kind == "set_queue":
            ctx.store.queue(value)
        if kind == "assign":
            if not value:
                raise ValidationError(f"action {n}: assign needs an agent")
            ctx.store.agent(value)
        if kind in ("reply", "note"):
            templates.render_text(value, {})
        clean.append({"type": kind, "value": value} if kind != "assign_self" else {"type": kind})
    return clean


def create_macro(ctx: Context, name: str, actions: list[dict[str, str]]) -> Macro:
    require(ctx, "macro.manage")
    name = name.strip()
    if not name:
        raise ValidationError("a macro needs a name")
    with ctx.store.transaction():
        macro = Macro(
            id=ctx.store.next_id("macro", "M"),
            name=name,
            actions=validate_actions(ctx, actions),
            created_by=ctx.actor_name,
        )
        ctx.store.macros[macro.id] = macro
        ctx.record("macro.created", macro.id, name=name, actions=len(macro.actions))
    return macro


def update_macro(
    ctx: Context, macro_id: str, *, name: str | None = None, actions: list | None = None
) -> Macro:
    with ctx.store.transaction():
        macro = ctx.store.macro(macro_id)
        require(ctx, "macro.manage", target=macro.id)
        if name is not None and name.strip():
            macro.name = name.strip()
        if actions is not None:
            macro.actions = validate_actions(ctx, actions)
        ctx.record("macro.updated", macro.id, name=macro.name, actions=len(macro.actions))
    return macro


def delete_macro(ctx: Context, macro_id: str) -> None:
    with ctx.store.transaction():
        macro = ctx.store.macro(macro_id)
        require(ctx, "macro.manage", target=macro.id)
        del ctx.store.macros[macro.id]
        ctx.record("macro.deleted", macro.id, name=macro.name)


def list_macros(ctx: Context) -> list[Macro]:
    require(ctx, "ticket.view")
    return sorted(ctx.store.macros.values(), key=lambda m: int(m.id.split("-")[1]))


def _text(ctx: Context, ticket: Ticket, source: str) -> str:
    return templates.render_text(source, templates.ticket_context(ctx.store, ticket))


def check_action(ctx: Context, ticket: Ticket, action: dict[str, str]) -> None:
    """Each action needs what it would need on its own."""
    kind = action["type"]
    if kind == "note":
        require(ctx, "ticket.note", ticket=ticket)
    elif kind == "assign":
        require_assign(ctx, ticket, action.get("value") or None)
    else:
        require(ctx, "ticket.edit", ticket=ticket)


def run_action(ctx: Context, ticket: Ticket, action: dict[str, str]) -> None:
    kind = action["type"]
    value = action.get("value", "")
    if kind == "set_status":
        tickets.change_status(ctx, ticket, value)
    elif kind == "set_priority":
        tickets.change_priority(ctx, ticket, value)
    elif kind == "set_queue":
        tickets.change_queue(ctx, ticket, value)
    elif kind == "add_tag":
        tickets.tag(ctx, ticket, value)
    elif kind == "remove_tag":
        tickets.untag(ctx, ticket, value)
    elif kind == "assign":
        tickets.change_assignee(ctx, ticket, value)
    elif kind == "assign_self":
        if ctx.is_system:
            raise ValidationError("the system cannot take tickets")
        tickets.change_assignee(ctx, ticket, ctx.actor)
    elif kind == "reply":
        tickets.post_reply(ctx, ticket, _text(ctx, ticket, value), via="macro")
    elif kind == "note":
        tickets.post_note(ctx, ticket, _text(ctx, ticket, value), via="macro")
    else:  # pragma: no cover - validate_actions keeps these out
        raise ValidationError(f"unknown action {kind!r}")


def apply_macro(ctx: Context, macro_id: str, ticket_id: str) -> Ticket:
    with ctx.store.transaction():
        macro = ctx.store.macro(macro_id)
        ticket = ctx.store.ticket(ticket_id)
        require(ctx, "macro.run", ticket=ticket)
        for action in macro.actions:
            check_action(ctx, ticket, action)
            run_action(ctx, ticket, action)
        ctx.record("macro.applied", ticket.id, macro=macro.id, name=macro.name)
    return ticket

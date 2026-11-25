"""One handler per API action. Each takes the request's context and params and returns
JSON-able data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import auditview, search, views
from ..context import Context
from ..export import csv_export
from ..mail import preview
from ..reports import satisfaction, sla_report, workload
from ..services import agents, bulk, customers, macros, merging, searches, tickets
from .params import Params

Handler = Callable[[Context, Params], Any]
ACTIONS: dict[str, Handler] = {}


def action(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        ACTIONS[name] = fn
        return fn

    return register


def _ticket(ctx: Context, ticket_id: str) -> dict[str, Any]:
    return views.ticket_view(ctx.store, ctx.store.ticket(ticket_id))


# -- tickets ----------------------------------------------------------------------------


@action("tickets.create")
def ticket_create(ctx: Context, p: Params) -> Any:
    ticket = tickets.create(
        ctx,
        p.str("customer"),
        p.str("subject"),
        p.str("body"),
        priority=p.str("priority", None),
        queue=p.str("queue", None),
        tags=p.list("tags", []),
        via="api",
    )
    return views.ticket_view(ctx.store, ticket)


@action("tickets.get")
def ticket_get(ctx: Context, p: Params) -> Any:
    return _ticket(ctx, p.str("id"))


@action("tickets.list")
def ticket_list(ctx: Context, p: Params) -> Any:
    found = tickets.list_tickets(
        ctx,
        status=p.str("status", None),
        queue=p.str("queue", None),
        assignee=p.str("assignee", None),
        customer=p.str("customer", None),
    )
    return [views.ticket_row(ctx.store, t) for t in found]


@action("tickets.reply")
def ticket_reply(ctx: Context, p: Params) -> Any:
    ticket_id = p.str("id")
    tickets.reply(ctx, ticket_id, p.str("body"), via="api")
    return _ticket(ctx, ticket_id)


@action("tickets.note")
def ticket_note(ctx: Context, p: Params) -> Any:
    ticket_id = p.str("id")
    tickets.note(ctx, ticket_id, p.str("body"), via="api")
    return _ticket(ctx, ticket_id)


@action("tickets.update")
def ticket_update(ctx: Context, p: Params) -> Any:
    ticket_id = p.str("id")
    status = p.str("status", None)
    priority = p.str("priority", None)
    queue = p.str("queue", None)
    add_tags = p.list("add_tags", [])
    remove_tags = p.list("remove_tags", [])
    with ctx.store.transaction():
        if queue is not None:
            tickets.set_queue(ctx, ticket_id, queue)
        if priority is not None:
            tickets.set_priority(ctx, ticket_id, priority)
        for name in add_tags:
            tickets.add_tag(ctx, ticket_id, name)
        for name in remove_tags:
            tickets.remove_tag(ctx, ticket_id, name)
        if status is not None:
            tickets.set_status(ctx, ticket_id, status)
    return _ticket(ctx, ticket_id)


@action("tickets.assign")
def ticket_assign(ctx: Context, p: Params) -> Any:
    ticket_id = p.str("id")
    tickets.assign(ctx, ticket_id, p.str("agent", None) or None)
    return _ticket(ctx, ticket_id)


@action("tickets.take")
def ticket_take(ctx: Context, p: Params) -> Any:
    ticket_id = p.str("id")
    tickets.take(ctx, ticket_id)
    return _ticket(ctx, ticket_id)


@action("tickets.merge")
def ticket_merge(ctx: Context, p: Params) -> Any:
    target = merging.merge(ctx, p.str("source"), p.str("target"))
    return views.ticket_view(ctx.store, target)


@action("tickets.delete")
def ticket_delete(ctx: Context, p: Params) -> Any:
    tickets.delete(ctx, p.str("id"))
    return {"deleted": True}


@action("tickets.bulk")
def ticket_bulk(ctx: Context, p: Params) -> Any:
    changed = bulk.bulk_update(ctx, p.list("ids"), p.dict("changes"))
    return [views.ticket_row(ctx.store, t) for t in changed]


@action("tickets.search")
def ticket_search(ctx: Context, p: Params) -> Any:
    return search.run(
        ctx, p.str("query"), sort=p.str("sort", "updated"), limit=p.int("limit", None)
    )


# -- customers --------------------------------------------------------------------------


@action("customers.create")
def customer_create(ctx: Context, p: Params) -> Any:
    customer = customers.create(
        ctx,
        p.str("name"),
        email=p.str("email", ""),
        phone=p.str("phone", ""),
        address=p.str("address", ""),
        organization=p.str("organization", ""),
        tags=p.list("tags", []),
    )
    return views.customer_view(customer)


@action("customers.get")
def customer_get(ctx: Context, p: Params) -> Any:
    customer = customers.get(ctx, p.str("id"))
    return views.customer_view(customer, ticket_ids=customers.tickets_of(ctx, customer.id))


@action("customers.list")
def customer_list(ctx: Context, p: Params) -> Any:
    return [views.customer_view(c) for c in customers.list_customers(ctx, p.str("text", None))]


@action("customers.update")
def customer_update(ctx: Context, p: Params) -> Any:
    customer_id = p.str("id")
    fields = {
        name: p.any(name, None)
        for name in customers.EDITABLE
    }
    customer = customers.update(ctx, customer_id, **{k: v for k, v in fields.items() if v is not None})
    return views.customer_view(customer)


@action("customers.delete")
def customer_delete(ctx: Context, p: Params) -> Any:
    customers.delete(ctx, p.str("id"))
    return {"deleted": True}


# -- agents -----------------------------------------------------------------------------


@action("agents.create")
def agent_create(ctx: Context, p: Params) -> Any:
    agent = agents.create_agent(
        ctx, p.str("id"), p.str("name"), p.str("email"), signature=p.str("signature", "")
    )
    return views.agent_view(agent)


@action("agents.list")
def agent_list(ctx: Context, p: Params) -> Any:
    found = agents.list_agents(ctx, include_inactive=p.bool("include_inactive", False))
    return [views.agent_view(a) for a in found]


@action("agents.update")
def agent_update(ctx: Context, p: Params) -> Any:
    agent = agents.update_agent(
        ctx,
        p.str("id"),
        name=p.str("name", None),
        email=p.str("email", None),
        signature=p.str("signature", None),
    )
    return views.agent_view(agent)


# -- macros and saved searches ----------------------------------------------------------


@action("macros.create")
def macro_create(ctx: Context, p: Params) -> Any:
    return views.macro_view(macros.create_macro(ctx, p.str("name"), p.list("actions")))


@action("macros.list")
def macro_list(ctx: Context, p: Params) -> Any:
    return [views.macro_view(m) for m in macros.list_macros(ctx)]


@action("macros.apply")
def macro_apply(ctx: Context, p: Params) -> Any:
    ticket = macros.apply_macro(ctx, p.str("macro"), p.str("ticket"))
    return views.ticket_view(ctx.store, ticket)


@action("macros.delete")
def macro_delete(ctx: Context, p: Params) -> Any:
    macros.delete_macro(ctx, p.str("id"))
    return {"deleted": True}


@action("searches.save")
def search_save(ctx: Context, p: Params) -> Any:
    saved = searches.save_search(
        ctx,
        p.str("name"),
        p.str("query"),
        shared=p.bool("shared", False),
        sort=p.str("sort", "updated"),
    )
    return views.search_view(saved)


@action("searches.list")
def search_list(ctx: Context, p: Params) -> Any:
    return [views.search_view(s) for s in searches.list_searches(ctx)]


@action("searches.run")
def search_run(ctx: Context, p: Params) -> Any:
    return searches.run_saved(ctx, p.str("id"), limit=p.int("limit", None))


# -- reports, audit, templates, export --------------------------------------------------


@action("reports.sla")
def report_sla(ctx: Context, p: Params) -> Any:
    return sla_report.build(ctx, since=p.str("since", None), queue=p.str("queue", None))


@action("reports.workload")
def report_workload(ctx: Context, p: Params) -> Any:
    return workload.build(ctx)


@action("reports.satisfaction")
def report_satisfaction(ctx: Context, p: Params) -> Any:
    return satisfaction.build(ctx, since=p.str("since", None))


@action("audit.list")
def audit_list(ctx: Context, p: Params) -> Any:
    return auditview.entries(
        ctx,
        target=p.str("target", None),
        actor=p.str("actor", None),
        action=p.str("action", None),
        since=p.str("since", None),
        limit=p.int("limit", None),
    )


@action("templates.preview")
def template_preview(ctx: Context, p: Params) -> Any:
    return preview.preview(ctx, p.str("template"), p.str("ticket"))


@action("export.tickets")
def export_tickets(ctx: Context, p: Params) -> Any:
    return {"csv": csv_export.tickets_csv(ctx, p.str("query", ""))}


@action("export.customers")
def export_customers(ctx: Context, p: Params) -> Any:
    return {"csv": csv_export.customers_csv(ctx)}

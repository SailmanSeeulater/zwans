"""What each CLI command does."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import auditview, search
from ..context import Context
from ..errors import ValidationError
from ..export import backup, csv_export, importer
from ..mail import inbound, outbox, preview
from ..reports import satisfaction, sla_report, workload
from ..services import (
    agents,
    bulk,
    customers,
    macros,
    merging,
    queues,
    searches,
    settings,
    sla,
    surveys,
    tickets,
)
from ..textutil import table
from . import output


def _say(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _write(text: str, path: str | None) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")
        _say(f"wrote {path}")
    else:
        sys.stdout.write(text)


def _parse_action(spec: str) -> dict[str, str]:
    kind, sep, value = spec.partition("=")
    if not kind:
        raise ValidationError(f"bad action {spec!r}")
    return {"type": kind.strip(), "value": value} if sep else {"type": kind.strip()}


# -- command groups ---------------------------------------------------------------------


def _customer(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        customer = customers.create(
            ctx,
            args.name,
            email=args.email,
            phone=args.phone,
            address=args.address,
            organization=args.org,
            tags=args.tag,
        )
        _say(f"added {customer.id}")
    elif args.sub == "list":
        _write(output.customer_rows(customers.list_customers(ctx, args.text)), None)
    elif args.sub == "show":
        customer = customers.get(ctx, args.id)
        _write(output.customer_detail(customer, customers.tickets_of(ctx, customer.id)), None)
    elif args.sub == "edit":
        fields = {
            "name": args.name,
            "email": args.email,
            "phone": args.phone,
            "address": args.address,
            "organization": args.org,
        }
        customers.update(ctx, args.id, **{k: v for k, v in fields.items() if v is not None})
        _say(f"updated {args.id}")
    elif args.sub == "delete":
        customers.delete(ctx, args.id)
        _say(f"deleted {args.id}")
    elif args.sub == "import":
        result = importer.import_customers(ctx, Path(args.file).read_text("utf-8"))
        _say(
            f"created {len(result.created)}, updated {len(result.updated)}, "
            f"skipped {len(result.skipped)}"
        )
        for line, reason in result.skipped:
            _say(f"  line {line}: {reason}")
    return 0


def _agent(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        agent = agents.create_agent(ctx, args.id, args.name, args.email, signature=args.signature)
        _say(f"added agent {agent.id}")
    elif args.sub == "list":
        _write(output.agent_rows(agents.list_agents(ctx, include_inactive=args.all)), None)
    elif args.sub in ("activate", "deactivate"):
        agents.set_active(ctx, args.id, args.sub == "activate")
        _say(f"{args.sub}d {args.id}")
    return 0


def _team(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        agents.create_team(ctx, args.id, args.name)
        _say(f"added team {args.id}")
    elif args.sub == "join":
        agents.add_member(ctx, args.team, args.agent)
        _say(f"{args.agent} joined {args.team}")
    elif args.sub == "leave":
        agents.remove_member(ctx, args.team, args.agent)
        _say(f"{args.agent} left {args.team}")
    return 0


def _queue(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        queues.create_queue(
            ctx,
            args.id,
            args.name,
            team=args.team,
            default_priority=args.priority,
            keywords=args.keyword,
        )
        _say(f"added queue {args.id}")
    else:
        rows = [
            [q.id, q.name, q.team or "-", q.default_priority, ", ".join(q.keywords) or "-"]
            for q in queues.list_queues(ctx)
        ]
        _write(table(["id", "name", "team", "priority", "keywords"], rows) + "\n", None)
    return 0


def _ticket(ctx: Context, args: argparse.Namespace) -> int:
    sub = args.sub
    if sub == "new":
        ticket = tickets.create(
            ctx,
            args.customer,
            args.subject,
            args.body,
            priority=args.priority,
            queue=args.queue,
            tags=args.tag,
        )
        _say(f"created {ticket.id}")
    elif sub == "show":
        ticket = tickets.get(ctx, args.id)
        _write(output.ticket_detail(ctx.store, ticket, internal=not args.public), None)
    elif sub == "list":
        found = tickets.list_tickets(
            ctx, status=args.status, queue=args.queue, assignee=args.assignee
        )
        from ..views import ticket_row

        _write(output.ticket_rows([ticket_row(ctx.store, t) for t in found]), None)
    elif sub == "reply":
        comment = tickets.reply(ctx, args.id, args.text)
        _say(f"replied on {args.id} (#{comment.id})")
    elif sub == "note":
        comment = tickets.note(ctx, args.id, args.text)
        _say(f"noted on {args.id} (#{comment.id})")
    elif sub == "status":
        tickets.set_status(ctx, args.id, args.status)
        _say(f"{args.id} is {args.status}")
    elif sub == "priority":
        tickets.set_priority(ctx, args.id, args.priority)
        _say(f"{args.id} is {args.priority}")
    elif sub == "tag":
        tickets.add_tag(ctx, args.id, args.tag)
        _say(f"tagged {args.id}")
    elif sub == "untag":
        tickets.remove_tag(ctx, args.id, args.tag)
        _say(f"untagged {args.id}")
    elif sub == "assign":
        agent = None if args.agent in ("none", "-") else args.agent
        tickets.assign(ctx, args.id, agent)
        _say(f"{args.id} assigned to {agent or 'nobody'}")
    elif sub == "move":
        tickets.set_queue(ctx, args.id, args.queue)
        _say(f"{args.id} moved to {args.queue}")
    elif sub == "take":
        tickets.take(ctx, args.id)
        _say(f"{args.id} is yours")
    elif sub == "delete":
        tickets.delete(ctx, args.id)
        _say(f"deleted {args.id}")
    elif sub == "merge":
        merging.merge(ctx, args.source, args.target)
        _say(f"merged {args.source} into {args.target}")
    elif sub == "history":
        tickets.get(ctx, args.id)
        _write(auditview.render(auditview.history(ctx, args.id)), None)
    return 0


def _macro(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        macro = macros.create_macro(ctx, args.name, [_parse_action(a) for a in args.action])
        _say(f"added macro {macro.id}")
    elif args.sub == "list":
        _write(output.macro_rows(macros.list_macros(ctx)), None)
    elif args.sub == "run":
        macros.apply_macro(ctx, args.macro, args.ticket)
        _say(f"applied {args.macro} to {args.ticket}")
    elif args.sub == "delete":
        macros.delete_macro(ctx, args.id)
        _say(f"deleted {args.id}")
    return 0


def _saved(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "add":
        saved = searches.save_search(ctx, args.name, args.query, shared=args.shared, sort=args.sort)
        _say(f"saved {saved.id}")
    elif args.sub == "list":
        _write(output.search_rows(searches.list_searches(ctx)), None)
    elif args.sub == "run":
        result = searches.run_saved(ctx, args.id)
        _say(f"{result['search']['name']}: {result['count']} ticket(s)")
        _write(output.ticket_rows(result["results"]), None)
    elif args.sub == "delete":
        searches.delete_search(ctx, args.id)
        _say(f"deleted {args.id}")
    return 0


def _bulk(ctx: Context, args: argparse.Namespace) -> int:
    changes = {
        "status": args.status,
        "priority": args.priority,
        "queue": args.queue,
        "assignee": None if args.assignee is None else ("" if args.assignee == "none" else args.assignee),
        "add_tags": args.add_tag or None,
        "remove_tags": args.remove_tag or None,
    }
    changed = bulk.bulk_update(ctx, args.ids, changes)
    _say(f"updated {len(changed)} ticket(s)")
    return 0


def _export(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "tickets":
        _write(csv_export.tickets_csv(ctx, args.query), args.out)
    else:
        _write(csv_export.customers_csv(ctx), args.out)
    return 0


def _report(ctx: Context, args: argparse.Namespace) -> int:
    if args.name == "sla":
        report = sla_report.build(ctx, since=args.since)
        text = sla_report.render(report)
    elif args.name == "workload":
        report = workload.build(ctx)
        text = workload.render(report)
    else:
        report = satisfaction.build(ctx, since=args.since)
        text = satisfaction.render(report)
    _write(json.dumps(report, indent=2) + "\n" if args.json else text, None)
    return 0


def _audit(ctx: Context, args: argparse.Namespace) -> int:
    rows = auditview.entries(
        ctx,
        target=args.target,
        actor=args.by_actor,
        action=args.action,
        since=args.since,
        limit=args.limit,
    )
    _write(auditview.render(rows), None)
    return 0


def _mail_in(ctx: Context, args: argparse.Namespace) -> int:
    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
    received = inbound.receive(ctx, raw)
    if received.ticket is None:
        _say(received.reason)
    else:
        _say(f"{received.reason}: {received.ticket.id}")
    return 0


def _outbox(ctx: Context, args: argparse.Namespace) -> int:
    mails = ctx.store.outbox if args.all else outbox.pending(ctx.store)
    rows = [[str(m.id), m.to, m.template, m.ticket_id or "-", "yes" if m.sent else "no"] for m in mails]
    _write(table(["id", "to", "template", "ticket", "sent"], rows) + "\n", None)
    return 0


def _sla(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "set":
        sla.set_policy(ctx, args.priority, args.first_response, args.resolution)
        _say(f"SLA for {args.priority} set")
    else:
        rows = [
            [p.priority, str(p.first_response_minutes), str(p.resolution_minutes)]
            for p in sla.policies(ctx.store)
        ]
        _write(table(["priority", "first reply (min)", "resolution (min)"], rows) + "\n", None)
    return 0


def _template(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "list":
        rows = [[t["name"], t["audience"], t["subject"]] for t in preview.list_templates()]
        _write(table(["name", "audience", "subject"], rows) + "\n", None)
    else:
        shown = preview.preview(ctx, args.name, args.ticket)
        _write(f"Subject: {shown['subject']}\n\n{shown['body']}", None)
    return 0


def _setting(ctx: Context, args: argparse.Namespace) -> int:
    if args.sub == "set":
        value = settings.set_setting(ctx, args.key, args.value)
        _say(f"{args.key} = {value}")
    else:
        for key, value in settings.all_settings(ctx).items():
            _say(f"{key} = {value}")
    return 0


def run(ctx: Context, args: argparse.Namespace) -> int:
    command = args.command
    if command == "customer":
        return _customer(ctx, args)
    if command == "agent":
        return _agent(ctx, args)
    if command == "team":
        return _team(ctx, args)
    if command == "queue":
        return _queue(ctx, args)
    if command == "ticket":
        return _ticket(ctx, args)
    if command == "macro":
        return _macro(ctx, args)
    if command == "search":
        _write(output.ticket_rows(search.run(ctx, args.query, sort=args.sort, limit=args.limit)), None)
        return 0
    if command == "saved":
        return _saved(ctx, args)
    if command == "bulk":
        return _bulk(ctx, args)
    if command == "export":
        return _export(ctx, args)
    if command == "report":
        return _report(ctx, args)
    if command == "audit":
        return _audit(ctx, args)
    if command == "mail-in":
        return _mail_in(ctx, args)
    if command == "outbox":
        return _outbox(ctx, args)
    if command == "jobs":
        result = jobs_run(ctx)
        _say(
            f"breaches: {len(result['breaches'])}, closed: {len(result['closed'])}, "
            f"purged: {result['purged']}"
        )
        return 0
    if command == "sla":
        return _sla(ctx, args)
    if command == "template":
        return _template(ctx, args)
    if command == "setting":
        return _setting(ctx, args)
    if command == "backup":
        Path(args.file).write_text(backup.dumps(ctx), encoding="utf-8")
        _say(f"backed up to {args.file}")
        return 0
    if command == "restore":
        counts = backup.restore(ctx, json.loads(Path(args.file).read_text("utf-8")))
        _say(f"restored {counts['tickets']} ticket(s), {counts['customers']} customer(s)")
        return 0
    if command == "survey":
        surveys.respond(ctx, args.token, args.rating, args.remark)
        _say("thank you")
        return 0
    raise ValidationError(f"unknown command {command!r}")


def jobs_run(ctx: Context) -> dict:
    from ..jobs import run_all

    return run_all(ctx)

"""orbit webhook ..., outbox, deliver."""

from orbit.cli.output import emit_json, say
from orbit.jobs.dispatcher import deliver, retry_failed, urllib_transport


def register(commands) -> None:
    hook = commands.add_parser("webhook", help="webhook subscriptions")
    sub = hook.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    add.add_argument("url")
    add.add_argument("--event", action="append", default=[])
    add.add_argument("--contact", help="only events about this contact")
    add.add_argument("--secret")
    add.set_defaults(handler=add_webhook)
    sub.add_parser("list").set_defaults(handler=list_webhooks)
    remove = sub.add_parser("remove")
    remove.add_argument("id")
    remove.set_defaults(handler=remove_webhook)

    outbox = commands.add_parser("outbox", help="queued webhook messages")
    outbox.add_argument("--pending", action="store_true")
    outbox.set_defaults(handler=show_outbox)

    send = commands.add_parser("deliver", help="send queued webhook messages")
    send.add_argument("--limit", type=int)
    send.add_argument("--retry-failed", action="store_true")
    send.set_defaults(handler=send_outbox)


def add_webhook(crm, args) -> bool:
    subscription = crm.subscribe(args.url, args.event or ["*"], args.contact, args.secret)
    say(f"Added {subscription.id} -> {subscription.url}")
    say(f"secret {subscription.secret}")
    return True


def list_webhooks(crm, args) -> bool:
    for sub in crm.subscriptions():
        only = f"  (contact {sub.contact_id})" if sub.contact_id else ""
        state = "" if sub.active else "  paused"
        say(f"{sub.id:<5} {sub.url}  {', '.join(sub.events)}{only}{state}")
    return False


def remove_webhook(crm, args) -> bool:
    crm.unsubscribe(args.id)
    say(f"Removed {args.id}")
    return True


def show_outbox(crm, args) -> bool:
    messages = crm.outbox(args.pending)
    if args.json:
        emit_json([message.to_row() for message in messages])
        return False
    for m in messages:
        state = "sent" if m.delivered_at else "failed" if m.failed else "pending"
        say(f"{m.id:<6} {m.subscription_id:<5} {m.event:<20} {state}")
    return False


def send_outbox(crm, args) -> bool:
    if args.retry_failed:
        retry_failed(crm)
    report = deliver(crm, urllib_transport, args.limit)
    say(report.summary())
    return True

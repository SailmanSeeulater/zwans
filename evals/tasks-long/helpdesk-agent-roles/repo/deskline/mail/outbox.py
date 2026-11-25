"""Outgoing mail waits in the outbox until a sender (not part of deskline) picks it up."""

from __future__ import annotations

from ..clock import days_between
from ..models import OutgoingMail
from ..store import Store


def queue_mail(
    store: Store,
    at: str,
    *,
    to: str,
    subject: str,
    body: str,
    template: str,
    ticket_id: str | None = None,
    recipient_agent: str | None = None,
) -> OutgoingMail:
    mail = OutgoingMail(
        id=store.next_number("mail"),
        to=to,
        subject=subject,
        body=body,
        template=template,
        ticket_id=ticket_id,
        recipient_agent=recipient_agent,
        created_at=at,
    )
    store.outbox.append(mail)
    return mail


def pending(store: Store) -> list[OutgoingMail]:
    return [mail for mail in store.outbox if not mail.sent]


def for_ticket(store: Store, ticket_id: str) -> list[OutgoingMail]:
    return [mail for mail in store.outbox if mail.ticket_id == ticket_id]


def mark_sent(store: Store, mail_ids: list[int]) -> int:
    wanted = set(mail_ids)
    count = 0
    for mail in store.outbox:
        if mail.id in wanted and not mail.sent:
            mail.sent = True
            count += 1
    return count


def purge(store: Store, now: str, keep_days: int) -> int:
    """Drop sent mail older than ``keep_days``; unsent mail is always kept."""
    before = len(store.outbox)
    store.outbox = [
        mail
        for mail in store.outbox
        if not mail.sent or days_between(mail.created_at, now) < keep_days
    ]
    return before - len(store.outbox)

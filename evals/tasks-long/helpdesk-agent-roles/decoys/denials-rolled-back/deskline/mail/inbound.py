"""The mail gateway: turns inbound mail into tickets and replies.

- Mail whose subject carries a ``[T-n]`` tag of an open ticket of the same customer is
  added to that ticket as a customer reply (reopening it if it was solved).
- A tagged reply to a closed ticket starts a new ticket that refers to the old one.
- Anything else starts a new ticket; unknown senders become customers.
- Automatic replies (out-of-office and the like) are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..context import Context
from ..models import Ticket
from ..services import customers, tickets
from . import parser


@dataclass
class Received:
    ticket: Ticket | None
    created: bool
    reason: str = ""


def receive(ctx: Context, raw: str) -> Received:
    mail = parser.parse(raw)
    if mail.automatic:
        return Received(None, False, "automatic reply ignored")
    # The gateway acts for the customer who wrote, whoever feeds it the message.
    ctx = ctx.as_system()
    with ctx.store.transaction():
        customer, _ = customers.find_or_create(ctx, mail.sender_name, mail.sender_address)
        body = mail.body or "(empty message)"
        if mail.ticket_ref and mail.ticket_ref in ctx.store.tickets:
            ticket = ctx.store.tickets[mail.ticket_ref]
            if ticket.customer_id == customer.id and ticket.merged_into:
                ticket = ctx.store.tickets.get(ticket.merged_into, ticket)
            if ticket.customer_id == customer.id and ticket.status != "closed":
                tickets.post_customer_comment(
                    ctx, ticket, body, from_address=mail.sender_address, via="email"
                )
                return Received(ticket, False, "reply added")
            if ticket.customer_id == customer.id:
                body = f"Follow-up to {ticket.id}.\n\n{body}"
        ticket = tickets.create(
            ctx,
            customer.id,
            mail.clean_subject,
            body,
            via="email",
            from_address=mail.sender_address,
        )
        return Received(ticket, True, "new ticket")

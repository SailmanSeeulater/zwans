from deskline.mail import inbound, outbox, parser, preview
from deskline.services import tickets

NEW = """\
From: Jane Doe <Jane@Example.org>
To: support@deskline.example
Subject: Refund please
Message-ID: <a1@example.org>

I was charged twice for my invoice.

Thanks,
Jane
--
Jane Doe, Example Org
"""

REPLY = """\
From: Jane Doe <jane@example.org>
To: support@deskline.example
Subject: Re: [T-1] Refund please

Any news?

On Mon, 2 Mar 2026 at 10:00, Deskline Support wrote:
> Hello Jane,
> Thanks for getting in touch.
"""

STRANGER = """\
From: newbie@fresh.example
Subject: Hello

Who are you?
"""

AUTO = """\
From: Jane Doe <jane@example.org>
Subject: Out of office
Auto-Submitted: auto-replied

I am away.
"""


def test_the_parser_cuts_signatures_and_quotes() -> None:
    mail = parser.parse(NEW)
    assert mail.sender_address == "jane@example.org"
    assert mail.body == "I was charged twice for my invoice.\n\nThanks,\nJane"
    reply = parser.parse(REPLY)
    assert reply.ticket_ref == "T-1"
    assert reply.body == "Any news?"
    assert reply.clean_subject == "Refund please"


def test_inbound_mail_creates_a_ticket_for_a_known_customer(desk, ctx, seeded) -> None:
    received = inbound.receive(ctx, NEW)
    assert received.created
    ticket = received.ticket
    assert ticket.customer_id == seeded["jane"].id
    assert ticket.queue == "billing"
    assert ticket.comments[0].from_address == "jane@example.org"
    assert ticket.comments[0].via == "email"


def test_a_tagged_reply_lands_on_the_ticket_and_reopens_it(desk, ctx, seeded) -> None:
    ticket = inbound.receive(ctx, NEW).ticket
    tickets.set_status(ctx, ticket.id, "solved")
    received = inbound.receive(ctx, REPLY)
    assert not received.created
    assert received.ticket.id == ticket.id
    assert ticket.status == "open"
    assert ticket.comments[-1].body == "Any news?"


def test_a_reply_to_a_closed_ticket_starts_a_follow_up(ctx, seeded) -> None:
    ticket = inbound.receive(ctx, NEW).ticket
    tickets.set_status(ctx, ticket.id, "solved")
    tickets.set_status(ctx, ticket.id, "closed")
    received = inbound.receive(ctx, REPLY)
    assert received.created
    assert received.ticket.comments[0].body.startswith(f"Follow-up to {ticket.id}.")


def test_unknown_senders_become_customers_and_auto_replies_are_dropped(desk, ctx) -> None:
    received = inbound.receive(ctx, STRANGER)
    customer = desk.store.customers[received.ticket.customer_id]
    assert customer.email == "newbie@fresh.example"
    assert inbound.receive(ctx, AUTO).ticket is None


def test_new_tickets_notify_the_customer_and_the_team(desk, ctx, seeded) -> None:
    ticket = inbound.receive(ctx, NEW).ticket
    mails = outbox.for_ticket(desk.store, ticket.id)
    assert [(m.template, m.to) for m in mails] == [
        ("customer_ack", "jane@example.org"),
        ("agent_new_ticket", "maria@ourdesk.example"),
        ("agent_new_ticket", "tom@ourdesk.example"),
    ]
    assert "Your reference is T-1." in mails[0].body
    assert "From: Jane Doe" in mails[1].body
    assert "I was charged twice" in mails[1].body


def test_agents_are_not_told_about_their_own_actions(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    maria = desk.context("maria")
    before = len(desk.store.outbox)
    tickets.take(maria, ticket.id)
    assert len(desk.store.outbox) == before
    tickets.assign(ctx, ticket.id, "tom")
    assigned = desk.store.outbox[-1]
    assert assigned.template == "agent_assigned"
    assert assigned.recipient_agent == "tom"
    assert "T-1 is assigned to you" in assigned.subject


def test_an_agent_reply_is_mailed_to_the_customer_with_the_signature(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    maria = desk.context("maria")
    tickets.take(maria, ticket.id)
    tickets.reply(maria, ticket.id, "Please send a photo.")
    mail = desk.store.outbox[-1]
    assert mail.template == "customer_reply"
    assert mail.to == "jane@example.org"
    assert "Please send a photo." in mail.body
    assert "-- Maria Lopez, Deskline Support" in mail.body


def test_previews_render_without_sending(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    before = len(desk.store.outbox)
    shown = preview.preview(ctx, "customer_ack", ticket.id)
    assert shown["subject"] == "[T-1] Printer"
    assert shown["audience"] == "customer"
    assert len(desk.store.outbox) == before
    assert "agent_assigned" in [t["name"] for t in preview.list_templates()]

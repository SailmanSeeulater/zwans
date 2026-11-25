"""Email rendered for agents (notifications and previews) follows the reader's role."""

import pytest
from conftest import JANE_ADDRESS, JANE_EMAIL, JANE_PHONE, REDACTED, leaks
from deskline.errors import PermissionDenied
from deskline.mail import inbound, preview
from deskline.services import tickets

NEW = """\
From: Jane Doe <jane@example.org>
Subject: Invoice wrong

My invoice is wrong.
"""

REPLY = """\
From: Jane Doe <jane@example.org>
Subject: Re: [T-1] Invoice wrong

Still wrong!
"""


def mail_to(desk, agent_id, template):
    found = [m for m in desk.store.outbox if m.recipient_agent == agent_id and m.template == template]
    assert found, (agent_id, template)
    return found[-1]


def test_new_ticket_mail_follows_each_recipients_role(desk, ctx, people) -> None:
    inbound.receive(ctx, NEW)
    to_ana = mail_to(desk, "ana", "agent_new_ticket")
    to_lou = mail_to(desk, "lou", "agent_new_ticket")
    assert leaks(to_ana.subject + to_ana.body) == []
    assert f"From: Jane Doe <{REDACTED}>" in to_ana.body
    assert "My invoice is wrong." in to_ana.body
    assert JANE_EMAIL in to_lou.body and JANE_PHONE in to_lou.body


def test_assignment_mail_follows_the_recipient_not_the_actor(desk, ctx, people, as_) -> None:
    ticket = tickets.create(ctx, people["jane"].id, "Printer", "It jams")
    tickets.assign(as_("lou"), ticket.id, "al")
    to_al = mail_to(desk, "al", "agent_assigned")
    assert leaks(to_al.body) == []
    assert REDACTED in to_al.body
    tickets.assign(as_("lou"), ticket.id, "ada")
    to_ada = mail_to(desk, "ada", "agent_assigned")
    assert JANE_ADDRESS in to_ada.body


def test_customer_reply_mail_to_an_agent_hides_the_sender(desk, ctx, people, as_) -> None:
    ticket = inbound.receive(ctx, NEW).ticket
    tickets.take(as_("ana"), ticket.id)
    inbound.receive(ctx, REPLY)
    to_ana = mail_to(desk, "ana", "agent_customer_replied")
    assert "Still wrong!" in to_ana.body
    assert leaks(to_ana.body) == []


def test_breach_mail_to_an_agent_hides_contacts(desk, ctx, people, clock) -> None:
    from deskline.services import sla

    ticket = tickets.create(ctx, people["jane"].id, "Down", "All down", priority="urgent")
    tickets.assign(ctx, ticket.id, "al")
    clock.advance(60)
    sla.check_breaches(ctx)
    to_al = mail_to(desk, "al", "agent_sla_breach")
    assert leaks(to_al.body) == []
    assert f"Phone: {REDACTED}" in to_al.body


def test_mail_to_customers_is_not_redacted(desk, ctx, people, as_) -> None:
    ticket = tickets.create(ctx, people["jane"].id, "Printer", "It jams")
    tickets.take(as_("ana"), ticket.id)
    tickets.reply(as_("ana"), ticket.id, "Try again")
    to_jane = [m for m in desk.store.outbox if m.template == "customer_reply"][-1]
    assert to_jane.to == JANE_EMAIL
    assert REDACTED not in to_jane.body


@pytest.mark.parametrize("who", ["vic", "ana"])
def test_previews_are_rendered_for_the_agent_asking(desk, ctx, people, as_, who) -> None:
    ticket = inbound.receive(ctx, NEW).ticket
    for name in ("agent_assigned", "agent_customer_replied", "agent_sla_breach", "agent_new_ticket"):
        shown = preview.preview(as_(who), name, ticket.id)
        assert leaks(shown) == [], name
    lead = preview.preview(as_("lou"), "agent_assigned", ticket.id)
    assert JANE_EMAIL in lead["body"]


def test_the_mail_gateway_needs_no_permission(desk, people, as_) -> None:
    received = inbound.receive(as_("vic"), NEW)
    assert received.created
    assert desk.store.tickets[received.ticket.id].comments[0].body == "My invoice is wrong."


def test_previews_need_ticket_view_only(desk, ctx, people, as_) -> None:
    ticket = tickets.create(ctx, people["kim"].id, "Quiet", "Shh")
    shown = preview.preview(as_("vic"), "customer_ack", ticket.id)
    assert shown["subject"] == f"[{ticket.id}] Quiet"
    with pytest.raises(PermissionDenied):
        tickets.reply(as_("vic"), ticket.id, "no")

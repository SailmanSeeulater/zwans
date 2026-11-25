"""The JSON API: forbidden answers and redacted responses."""

import pytest
from conftest import JANE_ADDRESS, JANE_EMAIL, JANE_PHONE, REDACTED, leaks
from deskline import api
from deskline.mail import inbound

MAIL = """\
From: Jane Doe <jane@example.org>
Subject: Invoice question

Why is my invoice so high?
"""


def call(desk, action, who=None, **params):
    request = {"action": action, "params": params}
    if who is not None:
        request["agent"] = who
    return api.dispatch(desk, request)


@pytest.fixture
def mailed(desk, ctx, people):
    """T-1 from jane by email (so its first comment has a from_address), assigned to ana."""
    ticket = inbound.receive(ctx, MAIL).ticket
    call(desk, "tickets.assign", id=ticket.id, agent="ana")
    return ticket.id


def test_denied_requests_are_forbidden(desk, mailed) -> None:
    response = call(desk, "tickets.reply", "vic", id=mailed, body="Hello")
    assert response == {"ok": False, "error": {"code": "forbidden", "message": response["error"]["message"]}}
    assert call(desk, "tickets.delete", "lou", id=mailed)["error"]["code"] == "forbidden"
    assert call(desk, "tickets.reply", "al", id=mailed, body="Mine")["error"]["code"] == "forbidden"
    assert desk.store.audit[-1].action == "permission.denied"
    assert desk.store.audit[-1].actor == "al"
    assert call(desk, "tickets.reply", "ana", id=mailed, body="On it")["ok"]


@pytest.mark.parametrize("who", ["vic", "ana"])
def test_tickets_come_back_redacted(desk, mailed, who) -> None:
    data = call(desk, "tickets.get", who, id=mailed)["data"]
    assert data["requester"]["name"] == "Jane Doe"
    assert data["requester"]["email"] == REDACTED
    assert data["requester"]["phone"] == REDACTED
    assert data["comments"][0]["from_address"] == REDACTED
    assert data["comments"][0]["body"] == "Why is my invoice so high?"
    assert leaks(data) == []


def test_leads_get_the_whole_ticket(desk, mailed) -> None:
    data = call(desk, "tickets.get", "lou", id=mailed)["data"]
    assert data["requester"]["email"] == JANE_EMAIL
    assert data["comments"][0]["from_address"] == JANE_EMAIL


def test_ticket_responses_after_changes_are_redacted_too(desk, mailed) -> None:
    replied = call(desk, "tickets.reply", "ana", id=mailed, body="On it")["data"]
    assert leaks(replied) == []
    updated = call(desk, "tickets.update", "ana", id=mailed, priority="high")["data"]
    assert updated["requester"]["email"] == REDACTED
    created = call(desk, "tickets.create", "ana", customer="C-1", subject="New", body="Thing")["data"]
    assert leaks(created) == []
    rows = call(desk, "tickets.list", "ana")["data"]
    assert rows[0]["requester_email"] == REDACTED
    found = call(desk, "tickets.search", "vic", query="invoice")["data"]
    assert found[0]["requester_email"] == REDACTED
    taken = call(desk, "tickets.take", "al", id="T-2")["data"]
    assert leaks(taken) == []


def test_customers_come_back_redacted(desk, mailed) -> None:
    got = call(desk, "customers.get", "ana", id="C-1")["data"]
    assert (got["email"], got["phone"], got["address"]) == (REDACTED, REDACTED, REDACTED)
    assert got["tickets"] == [mailed]
    kim = call(desk, "customers.get", "vic", id="C-3")["data"]
    assert (kim["email"], kim["phone"], kim["address"]) == ("", "", "")
    listed = call(desk, "customers.list", "vic")["data"]
    assert leaks(listed) == []
    bob = [c for c in listed if c["id"] == "C-2"][0]
    assert bob["address"] == ""
    full = call(desk, "customers.get", "ada", id="C-1")["data"]
    assert (full["email"], full["phone"], full["address"]) == (JANE_EMAIL, JANE_PHONE, JANE_ADDRESS)


def test_customers_an_agent_writes_come_back_redacted(desk, mailed) -> None:
    created = call(desk, "customers.create", "ana", name="Pat", email="pat@pat.example", phone="123")
    assert created["data"]["email"] == REDACTED
    assert "pat@pat.example" not in repr(created)
    updated = call(desk, "customers.update", "ana", id="C-1", organization="Example Ltd")
    assert updated["data"]["organization"] == "Example Ltd"
    assert leaks(updated) == []
    assert call(desk, "customers.create", "vic", name="Nope")["error"]["code"] == "forbidden"


def test_reports_audit_previews_and_exports_through_the_api(desk, mailed, clock) -> None:
    clock.advance(3000)
    for action, params in [
        ("reports.sla", {}),
        ("audit.list", {}),
        ("audit.list", {"target": "C-1"}),
        ("templates.preview", {"template": "agent_assigned", "ticket": mailed}),
        ("export.tickets", {}),
        ("export.customers", {}),
        ("searches.run", None),
    ]:
        if params is None:
            saved = call(desk, "searches.save", "lou", name="All", query="", shared=True)["data"]
            params = {"id": saved["id"]}
        response = call(desk, action, "ana", **params)
        assert response["ok"], (action, response)
        assert leaks(response) == [], action
        assert REDACTED in repr(response), action
        assert leaks(call(desk, action, "lou", **params)) != [], action

"""Redaction in the exports, the reports and the audit log viewer."""

import csv
import io

import pytest
from conftest import (
    BOB_EMAIL,
    BOB_PHONE,
    JANE_ADDRESS,
    JANE_EMAIL,
    JANE_PHONE,
    REDACTED,
    leaks,
)
from deskline import auditview
from deskline.errors import PermissionDenied
from deskline.export import csv_export
from deskline.mail import inbound
from deskline.reports import satisfaction, sla_report, workload
from deskline.services import customers, surveys, tickets

MAIL = """\
From: Jane Doe <jane@example.org>
Subject: Printer

It jams.
"""


@pytest.fixture
def work(desk, ctx, people, clock):
    a = inbound.receive(ctx, MAIL).ticket
    b = tickets.create(ctx, people["bob"].id, "Refund", "Double charge", priority="urgent")
    c = tickets.create(ctx, people["kim"].id, "Quiet one", "Shh")
    tickets.assign(ctx, a.id, "ana")
    tickets.set_status(ctx, a.id, "solved")
    surveys.respond(ctx, surveys.for_ticket(ctx, a.id).token, 1, "Terrible")
    customers.update(ctx, people["jane"].id, phone="+1 555 0199")
    customers.update(ctx, people["jane"].id, phone=JANE_PHONE)
    clock.advance(3000)
    return a.id, b.id, c.id


def rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# -- exports ----------------------------------------------------------------------------


def test_viewers_cannot_export(as_, work) -> None:
    for export in (csv_export.tickets_csv, csv_export.customers_csv):
        with pytest.raises(PermissionDenied) as caught:
            export(as_("vic"))
        assert caught.value.permission == "export"


def test_the_ticket_export_hides_contacts_from_agents(as_, work) -> None:
    text = csv_export.tickets_csv(as_("ana"))
    assert leaks(text) == []
    found = rows(text)
    assert [r["requester"] for r in found] == ["Jane Doe", "Bob Stone", "Kim Quiet"]
    assert [r["requester_email"] for r in found] == [REDACTED, REDACTED, ""]
    assert [r["requester_phone"] for r in found] == [REDACTED, REDACTED, ""]
    assert found[0]["organization"] == "Example Org"


def test_the_customer_export_hides_contacts_from_agents(as_, work) -> None:
    buffer = io.StringIO()
    csv_export.export_customers(as_("al"), buffer)
    found = rows(buffer.getvalue())
    assert leaks(buffer.getvalue()) == []
    assert [(r["email"], r["phone"], r["address"]) for r in found] == [
        (REDACTED, REDACTED, REDACTED),
        (REDACTED, REDACTED, ""),
        ("", "", ""),
    ]


def test_leads_export_everything(as_, work) -> None:
    found = rows(csv_export.customers_csv(as_("lou")))
    assert (found[0]["email"], found[0]["phone"], found[0]["address"]) == (
        JANE_EMAIL, JANE_PHONE, JANE_ADDRESS,
    )
    found = rows(csv_export.tickets_csv(as_("lou")))
    assert found[1]["requester_phone"] == BOB_PHONE


def test_the_export_query_obeys_contact_terms(as_, work) -> None:
    with pytest.raises(PermissionDenied) as caught:
        csv_export.tickets_csv(as_("ana"), "email:stone")
    assert caught.value.permission == "contact.view"
    assert [r["requester_email"] for r in rows(csv_export.tickets_csv(as_("lou"), "email:stone"))] == [BOB_EMAIL]


# -- reports ----------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["vic", "ana"])
def test_the_sla_report_hides_contacts(as_, work, who) -> None:
    report = sla_report.build(as_(who))
    missed = [b for b in report["breached"] if b["ticket"] == work[1]]
    assert missed and all(b["email"] == REDACTED and b["phone"] == REDACTED for b in missed)
    assert missed[0]["requester"] == "Bob Stone"
    assert leaks(report) == []
    assert leaks(sla_report.render(report)) == []


def test_leads_see_contacts_in_the_sla_report(as_, work) -> None:
    report = sla_report.build(as_("lou"))
    assert BOB_EMAIL in sla_report.render(report)


def test_the_satisfaction_follow_up_hides_contacts(as_, work) -> None:
    report = satisfaction.build(as_("ana"))
    assert report["follow_up"][0]["customer"] == "Jane Doe"
    assert report["follow_up"][0]["email"] == REDACTED
    assert report["follow_up"][0]["phone"] == REDACTED
    assert leaks(satisfaction.render(report)) == []
    lead = satisfaction.build(as_("ada"))
    assert lead["follow_up"][0]["email"] == JANE_EMAIL


def test_everyone_may_read_the_reports(as_, work) -> None:
    assert workload.build(as_("vic"))["agents"]["ana"]["solved"] == 1


# -- audit log viewer -------------------------------------------------------------------


def test_viewers_cannot_read_the_audit_log(as_, work) -> None:
    with pytest.raises(PermissionDenied) as caught:
        auditview.entries(as_("vic"))
    assert caught.value.permission == "audit.view"
    with pytest.raises(PermissionDenied):
        auditview.history(as_("vic"), work[0])


def test_the_audit_log_hides_contacts_from_agents(as_, work, people) -> None:
    entries = auditview.entries(as_("ana"))
    assert leaks(entries) == []
    assert leaks(auditview.render(entries)) == []
    created = [e for e in entries if e["action"] == "customer.created" and e["target"] == people["jane"].id][0]
    assert created["details"]["name"] == "Jane Doe"
    assert created["details"]["email"] == REDACTED
    assert created["details"]["address"] == REDACTED
    updated = [e for e in entries if e["action"] == "customer.updated"]
    assert updated[0]["details"]["changes"]["phone"] == [REDACTED, REDACTED]
    ticket_created = [e for e in entries if e["action"] == "ticket.created" and e["target"] == work[0]][0]
    assert ticket_created["details"]["from_address"] == REDACTED
    assert ticket_created["details"]["subject"] == "Printer"
    assert leaks(auditview.history(as_("ana"), work[0])) == []


def test_kim_has_nothing_to_hide(as_, work, people) -> None:
    entries = auditview.entries(as_("ana"), target=people["kim"].id)
    assert entries[-1]["details"]["email"] == ""


def test_leads_read_the_whole_audit_log(as_, work, people) -> None:
    entries = auditview.entries(as_("lou"), target=people["jane"].id)
    assert JANE_ADDRESS in auditview.render(entries)
    updated = [e for e in entries if e["action"] == "customer.updated"]
    assert updated[0]["details"]["changes"]["phone"] == ["+1 555 0199", JANE_PHONE]


def test_the_stored_audit_log_is_not_redacted(desk, as_, work) -> None:
    auditview.entries(as_("ana"))
    assert any(e.details.get("email") == JANE_EMAIL for e in desk.store.audit)

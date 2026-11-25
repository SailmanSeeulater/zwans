import csv
import io

from deskline import jobs
from deskline.export import csv_export, importer
from deskline.reports import satisfaction, sla_report, workload
from deskline.services import sla, surveys, tickets


def test_the_sla_job_marks_breaches_and_tells_the_assignee(desk, ctx, seeded, clock) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Down", "All down", priority="urgent")
    tickets.assign(ctx, ticket.id, "maria")
    clock.advance(45)
    assert sla.check_breaches(ctx) == [(ticket.id, "first_response")]
    assert desk.store.outbox[-1].template == "agent_sla_breach"
    assert desk.store.outbox[-1].recipient_agent == "maria"
    assert sla.check_breaches(ctx) == []


def test_the_sla_report_lists_missed_targets(ctx, seeded, clock) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Down", "All down", priority="urgent")
    tickets.create(ctx, seeded["bob"].id, "Question", "Just asking")
    clock.advance(300)
    report = sla_report.build(ctx)
    assert report["by_priority"]["urgent"] == {"tickets": 1, "breached": 1, "rate": 1.0}
    missed = [b for b in report["breached"] if b["ticket"] == ticket.id]
    assert [b["target"] for b in missed] == ["first_response", "resolution"]
    assert missed[0]["email"] == "jane@example.org"
    assert missed[0]["phone"] == "+1 555 0101"
    text = sla_report.render(report)
    assert "jane@example.org" in text


def test_surveys_and_the_satisfaction_report(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.assign(ctx, ticket.id, "maria")
    tickets.set_status(ctx, ticket.id, "solved")
    survey = surveys.for_ticket(ctx, ticket.id)
    assert desk.store.outbox[-1].template == "survey_request"
    surveys.respond(ctx, survey.token, 2, "Slow")
    report = satisfaction.build(ctx)
    assert report["average"] == 2.0
    assert report["by_agent"] == {"maria": 2.0}
    assert report["follow_up"][0]["email"] == "jane@example.org"
    assert "Slow" not in satisfaction.render(report)


def test_workload(ctx, seeded) -> None:
    a = tickets.create(ctx, seeded["jane"].id, "One", "first")
    tickets.create(ctx, seeded["jane"].id, "Two", "second")
    tickets.assign(ctx, a.id, "tom")
    report = workload.build(ctx)
    assert report["agents"]["tom"]["open"] == 1
    assert report["queues"]["general"] == {"active": 2, "unassigned": 1}


def test_jobs_close_old_solved_tickets(ctx, seeded, clock) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.set_status(ctx, ticket.id, "solved")
    clock.advance(5 * 24 * 60)
    result = jobs.run_all(ctx)
    assert result["closed"] == [ticket.id]
    assert ticket.status == "closed"


def test_ticket_csv(ctx, seeded) -> None:
    tickets.create(ctx, seeded["jane"].id, "Printer", "It jams", tags=["hw"])
    tickets.create(ctx, seeded["bob"].id, "Refund", "Double charge")
    rows = list(csv.DictReader(io.StringIO(csv_export.tickets_csv(ctx))))
    assert [r["id"] for r in rows] == ["T-1", "T-2"]
    assert rows[0]["requester_email"] == "jane@example.org"
    assert rows[0]["requester_phone"] == "+1 555 0101"
    assert rows[0]["tags"] == "hw"
    only = list(csv.DictReader(io.StringIO(csv_export.tickets_csv(ctx, "refund"))))
    assert [r["id"] for r in only] == ["T-2"]


def test_customer_csv_and_import(desk, ctx, seeded) -> None:
    result = importer.import_customers(
        ctx,
        "name,email,phone\nJane Doe,jane@example.org,+1 555 9999\nNew Person,new@person.example,\n,,\n",
    )
    assert result.updated == [seeded["jane"].id]
    assert result.created == ["C-3"]
    assert result.skipped == [(4, "no name")]
    rows = list(csv.DictReader(io.StringIO(csv_export.customers_csv(ctx))))
    assert rows[0]["phone"] == "+1 555 9999"
    assert rows[0]["address"] == "12 Elm Street, Springfield"

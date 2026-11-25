from datetime import date

import pytest
from conftest import seed
from orbit.errors import InvalidValue, NotFound
from orbit.jobs.reminders import digest, due_reminders


def test_a_deal_records_every_stage_it_enters(crm) -> None:
    ids = seed(crm)
    crm.move_deal(ids["engine"], "proposal")
    deal = crm.deal(ids["engine"])
    assert [(c.stage, c.contact_id) for c in deal.history()] == [
        ("lead", None),
        ("qualified", ids["ada"]),
        ("proposal", None),
    ]
    assert deal.closed_at is None
    won = crm.move_deal(ids["engine"], "won")
    assert won.closed_at is not None
    assert not won.is_open


def test_deal_checks(crm) -> None:
    ids = seed(crm)
    with pytest.raises(InvalidValue):
        crm.move_deal(ids["engine"], "qualified")
    with pytest.raises(InvalidValue):
        crm.move_deal(ids["engine"], "sold")
    with pytest.raises(NotFound):
        crm.move_deal(ids["engine"], "proposal", contact_id="c99")
    with pytest.raises(NotFound):
        crm.add_deal("Nothing", 0, ["c99"])
    with pytest.raises(InvalidValue):
        crm.add_deal("Negative", -5)


def test_deal_contacts_have_no_repeats(crm) -> None:
    ids = seed(crm)
    deal = crm.add_deal("Repeat", 100, [ids["ada"], ids["ada"], ids["grace"]])
    assert deal.contact_ids == [ids["ada"], ids["grace"]]
    deal = crm.add_deal_contact(deal.id, ids["ada"])
    assert deal.contact_ids == [ids["ada"], ids["grace"]]
    deal = crm.remove_deal_contact(deal.id, ids["ada"])
    assert deal.contact_ids == [ids["grace"]]


def test_listing_deals(crm) -> None:
    ids = seed(crm)
    assert [d.id for d in crm.list_deals(stage="qualified")] == [ids["engine"]]
    crm.move_deal(ids["compiler"], "lost")
    assert [d.id for d in crm.list_deals(open_only=True)] == [ids["engine"]]
    assert [d.id for d in crm.deals.for_contact(ids["charles"])] == [ids["engine"]]


def test_notes_tasks_and_emails_belong_to_one_contact(crm) -> None:
    ids = seed(crm)
    assert [n.body for n in crm.notes(ids["ada"])] == ["Wants a quote for the difference engine"]
    assert [e.subject for e in crm.emails(ids["ada"])] == ["Quote attached"]
    assert crm.emails(ids["ada"])[0].address == "ada@analytical.example"
    assert [t.title for t in crm.tasks(ids["ada"])] == ["Call back about the quote"]
    assert crm.notes(ids["grace"]) == []
    with pytest.raises(NotFound):
        crm.add_note("c99", "hello")


def test_logging_an_email_sets_last_contacted(crm) -> None:
    ids = seed(crm)
    assert crm.contact(ids["grace"]).last_contacted_at is None
    email = crm.log_email(ids["grace"], "Hello", direction="in")
    assert crm.contact(ids["grace"]).last_contacted_at == email.at


def test_tasks_can_be_completed_once(crm) -> None:
    ids = seed(crm)
    task = crm.tasks(ids["ada"])[0]
    crm.complete_task(task.id)
    assert crm.tasks(ids["ada"], open_only=True) == []
    with pytest.raises(InvalidValue):
        crm.complete_task(task.id)
    with pytest.raises(InvalidValue):
        crm.add_task(ids["ada"], "Bad date", due="tomorrow")


def test_reminders_list_tasks_that_are_due(crm) -> None:
    ids = seed(crm)
    crm.add_task(ids["grace"], "Renewal", due="2026-04-01", owner="kim")
    reminders = due_reminders(crm, date(2026, 3, 7))
    assert [(r.title, r.days_late, r.contact_name) for r in reminders] == [
        ("Call back about the quote", 2, "Ada Lovelace")
    ]
    assert "Call back about the quote (Ada Lovelace, 2 days late)" in digest(reminders)
    assert digest([]) == "Nothing due."

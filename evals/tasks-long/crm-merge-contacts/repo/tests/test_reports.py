from conftest import seed
from orbit.reports import (
    activity_report,
    contact_summary,
    open_value_by_owner,
    pipeline,
    stage_durations,
    stage_moves_by_contact,
    top_contacts,
    win_rate,
)
from orbit.reports.contacts import render_summary


def test_contact_summary(crm) -> None:
    ids = seed(crm)
    crm.archive_contact(ids["charles"])
    summary = contact_summary(crm)
    assert (summary.total, summary.active, summary.archived) == (3, 2, 1)
    assert summary.by_owner == {"sam": 2, "kim": 1}
    assert summary.by_company == {"Analytical Engines": 1, "US Navy": 1}
    assert summary.without_company == 1
    assert summary.by_tag == {"vip": 1}
    assert summary.never_contacted == 2
    assert render_summary(summary).startswith("3 contacts (2 active, 1 archived)")


def test_pipeline_and_win_rate(crm) -> None:
    ids = seed(crm)
    rows = {row.stage: (row.deals, row.amount) for row in pipeline(crm)}
    assert rows["qualified"] == (1, 1_200_000)
    assert rows["lead"] == (1, 450_000)
    assert win_rate(crm) is None
    crm.move_deal(ids["compiler"], "won")
    assert win_rate(crm) == 1.0
    assert open_value_by_owner(crm) == {"sam": 1_200_000}


def test_activity_per_contact(crm) -> None:
    ids = seed(crm)
    report = {row.contact_id: row for row in activity_report(crm)}
    ada = report[ids["ada"]]
    assert (ada.notes, ada.emails, ada.open_tasks, ada.deals) == (1, 1, 1, 1)
    assert ada.open_value == 1_200_000
    assert report[ids["charles"]].notes == 0
    assert activity_report(crm)[0].contact_id == ids["ada"]


def test_top_contacts_and_stage_moves(crm) -> None:
    ids = seed(crm)
    assert top_contacts(crm) == [
        (ids["ada"], "Ada Lovelace", 1_200_000),
        (ids["charles"], "Charles Babbage", 1_200_000),
        (ids["grace"], "Grace Hopper", 450_000),
    ]
    assert stage_moves_by_contact(crm) == {ids["ada"]: 1}


def test_stage_durations(crm) -> None:
    seed(crm)
    durations = stage_durations(crm, "2026-03-11T09:00:00Z")
    assert set(durations) == {"lead", "qualified"}
    assert durations["qualified"] > 9.9

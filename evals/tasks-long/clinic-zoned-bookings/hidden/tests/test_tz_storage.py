"""Rules 15 and 16: version 2 stores UTC instants; older files are read as local times."""

import json
from datetime import date, datetime

import pytest
from clinicbook import ClinicBook, Recurrence, StorageError
from support import wall
from zones import INSTANT, offset_hours, u, utc, visit_at

TIME_FIELDS = {
    "appointments": ("start", "created"),
    "series": ("start",),
    "reminders": ("due", "sent"),
    "waitlist": ("earliest", "latest", "added"),
    "messages": ("at",),
    "webhook_queue": ("next_attempt",),
    "audit": ("at",),
}


def all_times(data: dict) -> list[tuple[str, str, object]]:
    return [
        (table, field, row.get(field))
        for table, fields in TIME_FIELDS.items()
        for row in data.get(table, [])
        for field in fields
        if row.get(field) is not None
    ]


def busy_world(world, clock, hooks):  # noqa: ANN001, ANN201
    world.configure(webhook_url="https://hooks.example.org/clinic")
    hooks.status = 503
    a = visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0), minutes=45)
    visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0), patient="P0002")
    world.book_series(clinic="camden", clinician="dr-osei", room="C2", patient="P0003",
                      start=datetime(2026, 3, 23, 10, 0), minutes=30,
                      rule=Recurrence("weekly", count=2))
    clock.set(utc(2026, 2, 28, 14, 0))
    world.run_jobs()  # sends the first Brooklyn reminder, retries the hooks
    world.waitlist_add(patient="P0004", clinic="bondi", minutes=30,
                       earliest=datetime(2026, 3, 4, 9, 0), latest=datetime(2026, 3, 6, 17, 0))
    return a


def test_version_2_stores_every_time_as_a_utc_instant(world, clock, hooks, tmp_path):
    busy_world(world, clock, hooks)
    path = world.save(tmp_path / "book.json")

    data = json.loads(path.read_text())

    assert data["version"] == 2
    times = all_times(data)
    assert {table for table, _, _ in times} == set(TIME_FIELDS)
    for table, field, value in times:
        assert isinstance(value, str) and INSTANT.match(value), (table, field, value)
    starts = {row["clinic"]: row["start"] for row in data["appointments"]}
    assert starts["brooklyn"] == "2026-03-02T14:00:00Z"
    assert starts["bondi"] == "2026-03-02T21:00:00Z"
    assert [s["start"] for s in data["series"]] == ["2026-03-23T10:00:00Z"]
    assert data["waitlist"][0]["earliest"] == "2026-03-03T22:00:00Z"


def test_closures_and_hours_stay_local(world, tmp_path):
    world.close_day("bondi", date(2026, 1, 26), "Australia Day")
    data = json.loads(world.save(tmp_path / "book.json").read_text())

    bondi = next(c for c in data["clinics"] if c["id"] == "bondi")
    assert bondi["closures"] == {"2026-01-26": "Australia Day"}
    assert bondi["hours"]["mon"] == ["08:00-17:00"]


def test_times_come_back_the_same_after_a_reopen(world, clock, hooks, tmp_path):
    busy_world(world, clock, hooks)
    world.save(tmp_path / "book.json")

    again = ClinicBook.open(tmp_path / "book.json", clock=clock)

    for before, after in zip(world.appointments(), again.appointments(), strict=True):
        assert (before.id, before.start, before.end) == (after.id, after.start, after.end)
        assert wall(before.start) == wall(after.start)
        assert after.start.utcoffset() == before.start.utcoffset()
    ny = again.appointments(clinic="brooklyn")[0]
    assert [r.due for r in again.reminders(ny.id)] == [utc(2026, 2, 28, 14, 0),
                                                        utc(2026, 3, 2, 12, 0)]
    assert offset_hours(again.reminders(ny.id)[0].due) == -5
    entry = again.waitlist()[0]
    assert u(entry.earliest) == utc(2026, 3, 3, 22, 0) and wall(entry.earliest) == "2026-03-04 09:00"
    assert again.store.to_dict() == world.store.to_dict()


def test_a_version_1_file_is_read_as_each_clinics_local_time(legacy, clock):
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)

    assert u(book.appointment("A0001").start) == utc(2026, 3, 2, 9, 0)
    assert u(book.appointment("A0002").start) == utc(2026, 3, 9, 13, 0)
    assert u(book.appointment("A0003").start) == utc(2026, 3, 2, 21, 0)
    assert u(book.appointment("A0004").start) == utc(2026, 3, 23, 10, 0)
    assert u(book.appointment("A0005").start) == utc(2026, 3, 30, 9, 0)
    assert u(book.appointment("A0006").created) == utc(2026, 2, 2, 21, 20)
    assert wall(book.appointment("A0002").start) == "2026-03-09 09:00"
    assert offset_hours(book.appointment("A0002").start) == -4


def test_a_version_1_files_reminders_and_waitlist_are_local_too(legacy, clock):
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)

    due = {r.id: r.due for r in book.store.reminders.values()}
    assert due["R0003"] == utc(2026, 3, 7, 14, 0)
    assert due["R0006"] == utc(2026, 3, 2, 19, 0)
    assert due["R0009"] == utc(2026, 3, 29, 9, 0)
    (entry,) = book.waitlist()
    assert (entry.earliest, entry.latest) == (utc(2026, 3, 2, 8, 0), utc(2026, 3, 6, 18, 0))


def test_a_version_1_file_is_saved_as_version_2(legacy, clock, tmp_path):
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)
    data = json.loads(book.save(tmp_path / "upgraded.json").read_text())

    assert data["version"] == 2
    for table, field, value in all_times(data):
        assert INSTANT.match(value), (table, field, value)
    rows = {(t, r.get("id", r.get("seq"))): r for t in TIME_FIELDS for r in data[t]}
    assert rows[("series", "S0001")]["start"] == "2026-03-23T10:00:00Z"
    assert rows[("reminders", "R0011")]["sent"] == "2026-02-14T16:05:00Z"
    assert rows[("waitlist", "W0001")]["added"] == "2026-02-25T12:00:00Z"
    assert rows[("appointments", "A0002")]["created"] == "2026-02-21T20:00:00Z"


def test_a_version_1_files_records_without_a_clinic_are_utc(legacy, clock, tmp_path):
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)
    data = json.loads(book.save(tmp_path / "upgraded.json").read_text())

    assert [m["at"] for m in data["messages"]] == [
        "2026-02-20T10:15:00Z", "2026-02-21T20:00:00Z", "2026-02-21T22:40:00Z",
    ]
    assert [e["at"] for e in data["audit"][:3]] == [
        "2026-02-20T10:15:00Z", "2026-02-21T20:00:00Z", "2026-02-21T22:40:00Z",
    ]
    assert data["webhook_queue"][0]["next_attempt"] == "2026-02-21T22:48:00Z"


def test_a_0x_file_is_read_as_local_time(legacy, clock, tmp_path):
    book = ClinicBook.open(legacy("legacy_v0.json"), clock=clock)

    assert u(book.appointment("A0001").start) == utc(2025, 6, 2, 8, 30)
    assert u(book.appointment("A0003").start) == utc(2025, 11, 3, 15, 0)
    data = json.loads(book.save(tmp_path / "upgraded.json").read_text())
    reminders = {r["id"]: r for r in data["reminders"]}
    assert reminders["R0001"]["sent"] == "2025-06-01T08:31:00Z"
    assert reminders["R0002"]["due"] == "2025-11-02T15:00:00Z"


def test_a_version_1_book_finds_clashes_by_instant(legacy, clock):
    clock.set(utc(2026, 1, 5, 8, 0))
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)

    # A0002 is Dr Park in Brooklyn at 13:00-13:45 UTC on 9 March; Camden is on GMT then.
    with pytest.raises(Exception, match="clashes"):
        book.book(clinic="camden", clinician="dr-park", room="C1", patient="P0004",
                  start=datetime(2026, 3, 9, 13, 30), minutes=30)
    book.book(clinic="camden", clinician="dr-park", room="C1", patient="P0004",
              start=datetime(2026, 3, 9, 9, 0), minutes=30)


def test_files_from_a_newer_version_are_still_refused(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": 99}))

    with pytest.raises(StorageError):
        ClinicBook.open(path)

import json
from datetime import date, datetime

import pytest
from clinicbook import ClinicBook, Recurrence, StorageError, Store
from support import visit, wall


def test_everything_survives_a_save_and_reopen(book, clock, tmp_path):
    book.close_day("camden", date(2026, 1, 16), "staff training")
    a = visit(book, datetime(2026, 1, 12, 9, 0), notes="first visit")
    book.book_series(clinic="camden", clinician="dr-lind", room="C2", patient="P0002",
                     start=datetime(2026, 1, 13, 10, 0), minutes=30,
                     rule=Recurrence("weekly", count=2))
    book.waitlist_add(patient="P0003", clinic="camden", minutes=30,
                      earliest=datetime(2026, 1, 20, 9, 0))
    book.cancel(a.id, reason="moved away")
    path = book.save(tmp_path / "book.json")

    again = ClinicBook.open(path, clock=clock)

    assert again.store.to_dict() == book.store.to_dict()
    copy = again.appointment(a.id)
    assert wall(copy.start) == "2026-01-12 09:00" and copy.status == "cancelled"
    assert again.store.clinics["camden"].closures == {date(2026, 1, 16): "staff training"}
    assert [wall(r.due) for r in again.reminders("A0002")] == ["2026-01-12 10:00",
                                                                "2026-01-13 08:00"]
    assert wall(again.waitlist()[0].earliest) == "2026-01-20 09:00"


def test_a_reopened_book_still_knows_who_is_busy(book, clock, tmp_path):
    visit(book, datetime(2026, 1, 12, 9, 0))
    book.save(tmp_path / "book.json")

    again = ClinicBook.open(tmp_path / "book.json", clock=clock)

    with pytest.raises(Exception, match="clashes"):
        visit(again, datetime(2026, 1, 12, 9, 15), room="C2", patient="P0002")


def test_saving_is_atomic_and_needs_a_path(book, tmp_path):
    with pytest.raises(StorageError):
        book.save()
    path = book.save(tmp_path / "sub" / "book.json")
    assert json.loads(path.read_text())["clinics"][0]["id"] == "camden"
    assert [p.name for p in path.parent.iterdir()] == ["book.json"]


def test_a_missing_file_is_an_empty_book(tmp_path):
    store = Store.open(tmp_path / "new.json")
    assert store.clinics == {} and store.path == tmp_path / "new.json"


def test_files_from_newer_releases_and_junk_are_refused(tmp_path):
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"version": 99}))
    junk = tmp_path / "junk.json"
    junk.write_text("{not json")

    with pytest.raises(StorageError, match="newer"):
        Store.open(newer)
    with pytest.raises(StorageError):
        Store.open(junk)


def test_a_version_1_file_loads(legacy, clock):
    book = ClinicBook.open(legacy("legacy_v1.json"), clock=clock)

    assert sorted(book.store.clinics) == ["bondi", "brooklyn", "camden"]
    assert len(book.appointments()) == 8
    assert wall(book.appointment("A0002").start) == "2026-03-09 09:00"
    assert wall(book.appointment("A0003").start) == "2026-03-03 08:00"
    assert book.store.clinicians["dr-park"].clinics == ["brooklyn", "camden"]
    agenda = book.agenda("brooklyn", date(2026, 3, 9))
    assert [r.appointment for r in agenda.rows] == ["A0002"]


def test_a_0x_file_loads_and_is_saved_in_the_current_format(legacy, clock, tmp_path):
    book = ClinicBook.open(legacy("legacy_v0.json"), clock=clock)

    assert [wall(a.start) for a in book.appointments()] == [
        "2025-06-02 09:30", "2025-06-02 14:00", "2025-11-03 10:00",
    ]
    assert book.appointment("A0002").status == "completed"
    assert book.store.clinics["camden"].hours.to_spec()["fri"] == ["08:30-17:30"]
    assert book.store.clinicians["dr-osei"].clinics == ["camden"]
    assert book.store.counters["appointment"] == 3

    book.save(tmp_path / "upgraded.json")
    data = json.loads((tmp_path / "upgraded.json").read_text())
    assert "bookings" not in data and len(data["appointments"]) == 3
    again = ClinicBook.open(tmp_path / "upgraded.json", clock=clock)
    assert again.store.to_dict() == book.store.to_dict()

from datetime import datetime
from pathlib import Path

import pytest
from clinicbook import ImportFailed
from support import wall

DATA = Path(__file__).parent / "data"


def test_a_diary_export_is_imported(book):
    result = book.import_csv(DATA / "diary_export.csv")

    assert len(result.imported) == 5
    assert result.errors == [(7, "no room 'C9'")]
    assert result.duplicates == []
    by_start = {wall(a.start): a for a in book.appointments()}
    assert set(by_start) == {
        "2025-11-03 09:30", "2025-11-03 10:00", "2025-12-15 14:15", "2026-01-19 11:00",
        "2026-01-20 08:30",
    }
    assert by_start["2025-11-03 09:30"].status == "completed"
    assert by_start["2025-12-15 14:15"].status == "no_show"
    assert by_start["2026-01-19 11:00"].source == "import"


def test_patients_are_matched_by_phone_or_created(book):
    result = book.import_csv(DATA / "diary_export.csv")

    jo = book.store.patients["P0001"]
    assert [a.patient for a in book.appointments(patient="P0001")] == ["P0001", "P0001"]
    assert jo.name == "Jo Bloggs"
    assert [book.store.patients[p].name for p in result.new_patients] == ["Priya Shah",
                                                                          "Tom Okafor"]


def test_imported_bookings_still_to_come_get_reminders(book):
    book.import_csv(DATA / "diary_export.csv")

    future = [a for a in book.appointments() if a.status == "booked"]
    assert [wall(a.start) for a in future] == ["2026-01-19 11:00", "2026-01-20 08:30"]
    assert [wall(r.due) for r in book.reminders(future[0].id)] == ["2026-01-18 11:00",
                                                                   "2026-01-19 09:00"]
    assert not [m for m in book.outbox if m.template == "confirmation"]


def test_importing_again_skips_what_is_there(book):
    book.import_csv(DATA / "diary_export.csv")

    again = book.import_csv(DATA / "diary_export.csv")

    assert again.imported == [] and again.duplicates == [2, 3, 4, 5, 6]


def test_imports_ignore_opening_hours_and_clashes(book):
    visit_time = datetime(2026, 1, 19, 11, 0)
    book.book(clinic="camden", clinician="dr-lind", room="C1", patient="P0002",
              start=visit_time, minutes=30)

    result = book.import_csv(
        "clinic,clinician,room,patient_name,patient_phone,date,time,minutes,kind,status,notes\n"
        "camden,dr-osei,C1,Jo Bloggs,+44 7700 900001,2026-01-19,11:00,30,consult,booked,\n"
        "camden,dr-osei,C2,Jo Bloggs,+44 7700 900001,18/01/2026,07:00,30,consult,attended,\n"
    )

    assert len(result.imported) == 2 and result.errors == []


def test_a_file_that_is_not_a_diary_export_is_refused(book, tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("name,amount\nx,1\n", encoding="utf-8")

    with pytest.raises(ImportFailed):
        book.import_csv(path)


def test_bad_rows_are_reported_with_their_line(book):
    result = book.import_csv(
        "clinic,clinician,room,patient_name,patient_phone,date,time,minutes,kind,status,notes\n"
        "camden,dr-osei,C1,Jo Bloggs,,2026-01-19,25:00,30,consult,booked,\n"
        "nowhere,dr-osei,C1,Jo Bloggs,,2026-01-19,10:00,30,consult,booked,\n"
        "camden,dr-osei,C1,Jo Bloggs,,2026-01-19,10:00,30,surgery,booked,\n"
    )

    assert [line for line, _ in result.errors] == [2, 3, 4]
    assert result.imported == []

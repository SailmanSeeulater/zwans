import csv
import io
from datetime import date, datetime

from support import lines_of, visit


def test_ical_has_one_event_per_appointment(book):
    visit(book, datetime(2026, 1, 12, 9, 0), notes="Bring the referral letter, please")
    visit(book, datetime(2026, 1, 13, 9, 0), clinician="dr-lind", patient="P0002")
    gone = visit(book, datetime(2026, 1, 14, 9, 0))
    book.cancel(gone.id)

    text = book.export_ical()
    lines = lines_of(text)

    assert text.endswith("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert lines.count("BEGIN:VEVENT") == 2
    assert "UID:A0001@clinicbook" in lines and "UID:A0003@clinicbook" not in lines
    assert "SUMMARY:Consult: Jo Bloggs with Dr Ama Osei" in lines
    assert "LOCATION:Camden Clinic\\, Room 1" in lines
    assert "DESCRIPTION:Bring the referral letter\\, please" in lines
    assert sum(1 for ln in lines if ln.startswith("DTSTART:")) == 2


def test_ical_can_include_cancelled_and_filter(book):
    visit(book, datetime(2026, 1, 12, 9, 0))
    gone = visit(book, datetime(2026, 1, 14, 9, 0), clinician="dr-lind")
    book.cancel(gone.id)

    lines = lines_of(book.export_ical(include_cancelled=True, clinician="dr-lind"))

    assert "STATUS:CANCELLED" in lines and lines.count("BEGIN:VEVENT") == 1
    assert lines_of(book.export_ical(first=date(2026, 1, 13))).count("BEGIN:VEVENT") == 0


def test_long_ical_lines_are_folded(book):
    visit(book, datetime(2026, 1, 12, 9, 0), notes="x" * 200)

    raw = book.export_ical().split("\r\n")

    assert all(len(line.encode()) <= 75 for line in raw)
    assert "DESCRIPTION:" + "x" * 200 in lines_of(book.export_ical())


def test_csv_export_columns(book):
    visit(book, datetime(2026, 1, 12, 9, 0), minutes=45)
    visit(book, datetime(2026, 1, 13, 16, 0), patient="P0002")

    rows = list(csv.DictReader(io.StringIO(book.export_csv())))

    assert [(r["id"], r["date"], r["start"], r["end"], r["minutes"]) for r in rows] == [
        ("A0001", "2026-01-12", "09:00", "09:45", "45"),
        ("A0002", "2026-01-13", "16:00", "16:30", "30"),
    ]
    assert rows[1]["patient_name"] == "Sam Patel"
    assert rows[0]["status"] == "booked" and rows[0]["clinician"] == "dr-osei"


def test_csv_export_filters_by_day(book):
    visit(book, datetime(2026, 1, 12, 9, 0))
    visit(book, datetime(2026, 1, 13, 9, 0))

    rows = list(csv.DictReader(io.StringIO(book.export_csv(first=date(2026, 1, 13)))))

    assert [r["id"] for r in rows] == ["A0002"]

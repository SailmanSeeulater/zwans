"""Rules 12 and 13: iCalendar in UTC; the CSV export local plus two UTC columns."""

import csv
import io
import re
from datetime import datetime

from support import lines_of
from zones import INSTANT, u, utc, visit_at


def event_times(ical: str) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    uid = start = ""
    for line in lines_of(ical):
        if line.startswith("UID:"):
            uid = line[4:]
        elif line.startswith("DTSTART"):
            start = line
        elif line.startswith("DTEND"):
            found[uid] = (start, line)
    return found


def test_ical_times_are_utc(world):
    ny = visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0), minutes=45)
    syd = visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0), patient="P0002")

    times = event_times(world.export_ical())

    assert times[f"{ny.id}@clinicbook"] == ("DTSTART:20260302T140000Z", "DTEND:20260302T144500Z")
    assert times[f"{syd.id}@clinicbook"] == ("DTSTART:20260302T210000Z",
                                              "DTEND:20260302T213000Z")


def test_ical_stamp_is_utc(world, clock):
    visit_at(world, "camden", datetime(2026, 7, 6, 9, 0))
    clock.set(utc(2026, 6, 1, 11, 45))

    lines = lines_of(world.export_ical())

    assert "DTSTAMP:20260601T114500Z" in lines
    assert "DTSTART:20260706T080000Z" in lines


def test_ical_over_the_repeated_hour(world):
    visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30), minutes=60)

    (times,) = event_times(world.export_ical()).values()

    assert times == ("DTSTART:20261101T053000Z", "DTEND:20261101T063000Z")


def test_every_ical_time_is_utc(world):
    visit_at(world, "brooklyn", datetime(2026, 3, 9, 9, 0))
    visit_at(world, "camden", datetime(2026, 3, 30, 9, 0), patient="P0002")

    for line in lines_of(world.export_ical()):
        if line.startswith(("DTSTART", "DTEND", "DTSTAMP")):
            assert re.fullmatch(r"(DTSTART|DTEND|DTSTAMP):\d{8}T\d{6}Z", line), line


def test_csv_export_keeps_local_columns_and_adds_utc_ones(world):
    visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0), minutes=45)
    visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0), patient="P0002")

    text = world.export_csv()
    header = text.splitlines()[0].split(",")
    rows = list(csv.DictReader(io.StringIO(text)))

    assert header[-2:] == ["utc_start", "utc_end"]
    assert header[:-2] == ["id", "clinic", "clinician", "room", "patient", "patient_name",
                           "date", "start", "end", "minutes", "kind", "status", "series"]
    by_clinic = {r["clinic"]: r for r in rows}
    ny, syd = by_clinic["brooklyn"], by_clinic["bondi"]
    assert (ny["date"], ny["start"], ny["end"]) == ("2026-03-02", "09:00", "09:45")
    assert (ny["utc_start"], ny["utc_end"]) == ("2026-03-02T14:00:00Z", "2026-03-02T14:45:00Z")
    assert (syd["date"], syd["start"]) == ("2026-03-03", "08:00")
    assert syd["utc_start"] == "2026-03-02T21:00:00Z"
    assert all(INSTANT.match(r["utc_start"]) and INSTANT.match(r["utc_end"]) for r in rows)


def test_csv_export_over_the_repeated_hour(world):
    visit_at(world, "nightcare", datetime(2026, 11, 1, 1, 30), minutes=60)

    (row,) = csv.DictReader(io.StringIO(world.export_csv()))

    assert (row["start"], row["end"]) == ("01:30", "01:30")
    assert (row["utc_start"], row["utc_end"]) == ("2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z")


HEADER = "clinic,clinician,room,patient_name,patient_phone,date,time,minutes,kind,status,notes\n"


def test_imported_rows_are_the_clinics_local_time(world):
    result = world.import_csv(
        HEADER
        + "brooklyn,dr-park,B1,Maria Lopez,,2026-03-09,09:00,30,consult,booked,\n"
        + "bondi,dr-hale,S1,Liam Nguyen,+61 412 555 019,03/03/2026,08:00,30,review,booked,\n"
        + "camden,dr-osei,C1,Jo Bloggs,+44 7700 900001,2025-06-02,09:30,30,consult,attended,\n"
    )

    assert result.errors == []
    starts = {world.appointment(i).clinic: world.appointment(i).start for i in result.imported}
    assert starts == {
        "brooklyn": utc(2026, 3, 9, 13, 0),
        "bondi": utc(2026, 3, 2, 21, 0),
        "camden": utc(2025, 6, 2, 8, 30),
    }


def test_imported_rows_in_the_lost_or_repeated_hour(world):
    result = world.import_csv(
        HEADER
        + "nightcare,dr-park,N1,Maria Lopez,,2026-03-08,02:30,30,consult,booked,\n"
        + "nightcare,dr-park,N1,Maria Lopez,,2026-11-01,01:30,30,consult,booked,\n"
    )

    assert [line for line, _ in result.errors] == [2]
    (appt_id,) = result.imported
    assert u(world.appointment(appt_id).start) == utc(2026, 11, 1, 5, 30)


def test_imported_bookings_get_reminders_at_the_right_moment(world):
    result = world.import_csv(
        HEADER + "brooklyn,dr-park,B1,Maria Lopez,,2026-03-09,09:00,30,consult,booked,\n"
    )

    (appt_id,) = result.imported
    assert [r.due for r in world.reminders(appt_id)] == [
        utc(2026, 3, 7, 13, 0), utc(2026, 3, 9, 11, 0),
    ]


def test_importing_again_skips_rows_already_imported(world):
    text = (HEADER
            + "bondi,dr-hale,S1,Liam Nguyen,+61 412 555 019,2026-03-03,08:00,30,consult,booked,\n"
            + "nightcare,dr-park,N1,Maria Lopez,,2026-11-01,01:30,30,consult,booked,\n")
    first = world.import_csv(text)

    again = world.import_csv(text)

    assert len(first.imported) == 2
    assert again.imported == [] and again.duplicates == [2, 3]
    assert [u(world.appointment(i).start) for i in first.imported] == [
        utc(2026, 3, 2, 21, 0), utc(2026, 11, 1, 5, 30),
    ]

import csv
import io
import json

import pytest


@pytest.fixture
def camden(cli):  # noqa: ANN001, ANN201
    assert cli("clinic", "add", "camden", "Camden Clinic", "--zone", "Europe/London",
               "--hours", "sat=09:00-13:00", "--hours", "mon=08:00-18:00",
               "--hours", "tue=08:00-18:00")[0] == 0
    assert cli("room", "add", "camden", "C1", "Room 1")[0] == 0
    assert cli("room", "add", "camden", "C2")[0] == 0
    assert cli("clinician", "add", "dr-osei", "Dr Ama Osei", "--clinic", "camden")[0] == 0
    assert cli("patient", "add", "Jo Bloggs", "--phone", "+44 7700 900001")[0] == 0
    return cli


def book(cli, *extra):  # noqa: ANN001, ANN201
    return cli("book", "--clinic", "camden", "--clinician", "dr-osei", "--room", "C1",
               "--patient", "P0001", *extra)


def test_booking_from_the_command_line(camden):
    code, out, err = book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    assert code == 0, err
    assert out == "Booked A0001: Mon 12 Jan 2026 09:00-09:30, Camden Clinic, room C1, Dr Ama Osei\n"
    data = json.loads(camden.path.read_text())
    assert [a["id"] for a in data["appointments"]] == ["A0001"]


def test_errors_go_to_stderr_with_exit_code_1(camden):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    code, out, err = book(camden, "--at", "2026-01-12 09:15", "--minutes", "30")
    assert code == 1 and out == "" and "clashes with A0001" in err

    code, _, err = book(camden, "--at", "2026-01-11 09:00", "--minutes", "30")
    assert code == 1 and "not open" in err


def test_show_lists_the_reminders(camden):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    code, out, _ = camden("show", "A0001")

    assert code == 0
    assert "reminder 24h before: Sun 11 Jan 2026 09:00 (pending)" in out
    assert "reminder 2h before: Mon 12 Jan 2026 07:00 (pending)" in out


def test_agenda_and_slots(camden):
    book(camden, "--at", "2026-01-10 09:00", "--minutes", "60")

    code, out, _ = camden("agenda", "camden", "2026-01-10")
    assert code == 0
    assert out.splitlines()[0] == "Camden Clinic, Saturday 10 January 2026"
    assert "09:00-10:00" in out

    code, out, _ = camden("slots", "camden", "2026-01-10", "--minutes", "60")
    assert out.splitlines()[0] == "10:00-11:00  dr-osei  C1"
    assert out.splitlines()[-1] == "12:00-13:00  dr-osei  C1"

    code, out, _ = camden("next", "camden", "--minutes", "30", "--after", "2026-01-10 12:40")
    assert out == "Mon 12 Jan 2026 08:00-08:30  dr-osei  C1\n"


def test_moving_and_cancelling(camden):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    code, out, _ = camden("move", "A0001", "--at", "2026-01-13 15:00")
    assert code == 0 and "Tue 13 Jan 2026 15:00-15:30" in out
    code, out, _ = camden("cancel", "A0001", "--reason", "unwell")
    assert out == "Cancelled A0001\n"
    code, out, _ = camden("history", "A0001")
    assert [line.split("  ")[1] for line in out.splitlines()] == [
        "appointment.booked", "appointment.rescheduled", "appointment.cancelled",
    ]


def test_series_from_the_command_line(camden):
    code, out, _ = book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")
    code, out, err = camden("series", "--clinic", "camden", "--clinician", "dr-osei",
                            "--room", "C2", "--patient", "P0001", "--at", "2026-01-05 10:00",
                            "--minutes", "30", "--every", "weekly", "--count", "3")

    assert code == 0, err
    assert out.splitlines()[0] == "Series S0001: every week, 3 times"
    assert len([ln for ln in out.splitlines() if "booked" in ln]) == 3


def test_jobs_send_reminders(camden, monkeypatch):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")
    monkeypatch.setenv("CLINICBOOK_NOW", "2026-01-11T09:00")

    code, out, _ = camden("jobs", "run")

    assert code == 0 and "reminders sent: 1" in out
    data = json.loads(camden.path.read_text())
    assert [m["template"] for m in data["messages"]] == ["confirmation", "reminder"]


def test_the_now_option_beats_the_environment(camden):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    code, out, _ = camden("--now", "2026-01-12 07:30", "jobs", "run")

    assert "reminders sent: 2" in out


def test_exports_and_import(camden, tmp_path):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")

    code, out, _ = camden("export", "csv")
    assert [r["id"] for r in csv.DictReader(io.StringIO(out))] == ["A0001"]
    code, out, _ = camden("export", "ical", "--out", str(tmp_path / "cal.ics"))
    assert out.startswith("wrote ")
    assert "UID:A0001@clinicbook" in (tmp_path / "cal.ics").read_text()

    diary = tmp_path / "diary.csv"
    diary.write_text(
        "clinic,clinician,room,patient_name,patient_phone,date,time,minutes,kind,status,notes\n"
        "camden,dr-osei,C2,Jo Bloggs,+44 7700 900001,2025-12-01,10:00,30,consult,attended,\n",
        encoding="utf-8",
    )
    code, out, _ = camden("import", str(diary))
    assert code == 0 and out.startswith("imported 1,")


def test_backup_and_restore(camden, tmp_path):
    book(camden, "--at", "2026-01-12 09:00", "--minutes", "30")
    assert camden("backup", str(tmp_path / "b.zip"))[0] == 0
    camden("cancel", "A0001")

    code, out, _ = camden("restore", str(tmp_path / "b.zip"))

    assert code == 0
    data = json.loads(camden.path.read_text())
    assert [a["status"] for a in data["appointments"]] == ["booked"]

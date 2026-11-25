"""The command line: local --at, UTC --now, local display."""

import json

import pytest


@pytest.fixture
def clinics(cli):  # noqa: ANN001, ANN201
    steps = [
        ("clinic", "add", "brooklyn", "Brooklyn Clinic", "--zone", "America/New_York",
         "--hours", "mon=07:30-21:30", "--hours", "tue=07:30-21:30"),
        ("clinic", "add", "bondi", "Bondi Clinic", "--zone", "Australia/Sydney",
         "--hours", "mon=08:00-17:00", "--hours", "tue=08:00-17:00"),
        ("clinic", "add", "nightcare", "Harbour Night Care", "--zone", "America/New_York",
         "--hours", "sun=00:00-06:00"),
        ("room", "add", "brooklyn", "B1"),
        ("room", "add", "bondi", "S1"),
        ("room", "add", "nightcare", "N1"),
        ("clinician", "add", "dr-park", "Dr Jun Park", "--clinic", "brooklyn",
         "--clinic", "nightcare"),
        ("clinician", "add", "dr-hale", "Dr Ruth Hale", "--clinic", "bondi"),
        ("patient", "add", "Maria Lopez", "--email", "maria@example.com"),
    ]
    for step in steps:
        code, _, err = cli(*step)
        assert code == 0, err
    return cli


def book(cli, clinic, clinician, room, at, minutes="30"):  # noqa: ANN001, ANN201
    return cli("book", "--clinic", clinic, "--clinician", clinician, "--room", room,
               "--patient", "P0001", "--at", at, "--minutes", minutes)


def test_book_takes_local_time_and_stores_utc(clinics):
    code, out, err = book(clinics, "brooklyn", "dr-park", "B1", "2026-03-02 09:00")

    assert code == 0, err
    assert out.startswith("Booked A0001: Mon 02 Mar 2026 09:00-09:30, Brooklyn Clinic")
    data = json.loads(clinics.path.read_text())
    assert data["version"] == 2
    assert data["appointments"][0]["start"] == "2026-03-02T14:00:00Z"


def test_book_refuses_a_time_that_does_not_exist(clinics):
    code, out, err = book(clinics, "nightcare", "dr-park", "N1", "2026-03-08 02:30")

    assert code == 1 and out == ""


def test_now_is_a_utc_instant(clinics):
    book(clinics, "brooklyn", "dr-park", "B1", "2026-03-02 09:00")  # ends 14:30 UTC

    code, out, err = clinics("--now", "2026-03-02T14:40:00Z", "jobs", "run")
    assert code == 0, err
    assert "no-shows marked: 0" in out
    code, out, _ = clinics("--now", "2026-03-02T14:45:00Z", "jobs", "run")
    assert "no-shows marked: 1" in out


def test_the_environment_clock_is_utc_too(clinics, monkeypatch):
    book(clinics, "bondi", "dr-hale", "S1", "2026-01-13 10:00")
    monkeypatch.setenv("CLINICBOOK_NOW", "2026-01-12T23:10:00Z")  # 10:10 in Sydney

    code, out, err = clinics("next", "bondi", "--minutes", "30")

    assert code == 0, err
    assert out.startswith("Tue 13 Jan 2026 10:30-11:00")


def test_show_and_agenda_use_the_clinics_local_time(clinics):
    book(clinics, "bondi", "dr-hale", "S1", "2026-03-03 08:00")

    _, out, _ = clinics("agenda", "bondi", "2026-03-03")
    assert "08:00-08:30" in out
    _, out, _ = clinics("show", "A0001")
    assert out.startswith("A0001: Tue 03 Mar 2026 08:00-08:30, Bondi Clinic")
    assert "reminder 24h before: Mon 02 Mar 2026 08:00" in out


def test_csv_export_from_the_command_line(clinics):
    book(clinics, "bondi", "dr-hale", "S1", "2026-03-03 08:00")

    _, out, _ = clinics("export", "csv")

    header, row = out.splitlines()
    assert header.endswith(",utc_start,utc_end")
    assert row.endswith(",2026-03-02T21:00:00Z,2026-03-02T21:30:00Z")

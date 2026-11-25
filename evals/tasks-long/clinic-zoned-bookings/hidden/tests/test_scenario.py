"""Random histories of bookings, moves and cancellations around clock changes in three
zones, checked step by step against an independent model of the README's rules."""

import json
import random
from datetime import date, datetime, timedelta

import pytest
from clinicbook import ClinicBook, Conflict, InvalidTime, OutsideOpeningHours
from conftest import (
    WORLD_CLINICIANS,
    WORLD_HOURS,
    WORLD_REMINDERS,
    WORLD_ROOMS,
    WORLD_START,
    WORLD_ZONES,
    Clock,
    Hooks,
    make_world,
)
from reference import RefAppointment, Reference
from support import lines_of
from zones import UTC

AROUND_CHANGES = [
    date(2026, 3, 6), date(2026, 3, 7), date(2026, 3, 8), date(2026, 3, 9),
    date(2026, 3, 27), date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30),
    date(2026, 4, 3), date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4), date(2026, 10, 5),
    date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26),
    date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2),
]
HOURS_TRIED = {
    "camden": range(7, 19),
    "brooklyn": range(7, 23),
    "bondi": range(7, 18),
    "nightcare": [0, 1, 2, 3, 4, 5, 20, 21, 22, 23],
}
LENGTHS = [15, 30, 30, 45, 60, 90, 120, 240]
EXPECTED_ERROR = {
    "invalid": InvalidTime,
    "hours": OutsideOpeningHours,
    "clash": Conflict,
    "hours or clash": (OutsideOpeningHours, Conflict),
}


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_history(seed: int, steps: int, tmp_path) -> None:  # noqa: ANN001
    rng = random.Random(seed)
    clock, hooks = Clock(), Hooks()
    book = make_world(clock, hooks)
    ref = Reference(WORLD_ZONES, WORLD_HOURS, WORLD_REMINDERS, [24, 2], WORLD_START)
    days = rng.sample(AROUND_CHANGES, 5)
    patients = ["P0001", "P0002", "P0003", "P0004"]

    def pick_time(clinic: str) -> datetime:
        day = rng.choice(days)
        return datetime(day.year, day.month, day.day, rng.choice(list(HOURS_TRIED[clinic])),
                        rng.choice([0, 15, 30, 45]))

    for step in range(steps):
        roll = rng.random()
        booked = [a for a in ref.appointments.values() if a.status == "booked"]
        context = f"seed {seed} step {step}"
        if roll < 0.65 or not booked:
            clinic = rng.choice(sorted(WORLD_ZONES))
            clinician = rng.choice([c for c, where in WORLD_CLINICIANS.items() if clinic in where])
            room = rng.choice(WORLD_ROOMS[clinic])
            patient = rng.choice(patients)
            naive, minutes = pick_time(clinic), rng.choice(LENGTHS)
            expected, start = ref.outcome(clinic, naive, minutes, clinician, room, patient)
            if expected == "ok":
                appt = book.book(clinic=clinic, clinician=clinician, room=room, patient=patient,
                                 start=naive, minutes=minutes)
                assert appt.start.astimezone(UTC) == start, context
                assert appt.end.astimezone(UTC) == start + timedelta(minutes=minutes), context
                ref.appointments[appt.id] = RefAppointment(appt.id, clinic, clinician, room,
                                                           patient, start, minutes)
            else:
                with pytest.raises(EXPECTED_ERROR[expected]):
                    book.book(clinic=clinic, clinician=clinician, room=room, patient=patient,
                              start=naive, minutes=minutes)
        elif roll < 0.85:
            target = rng.choice(booked)
            naive = pick_time(target.clinic)
            minutes = rng.choice(LENGTHS)
            expected, start = ref.outcome(target.clinic, naive, minutes, target.clinician,
                                          target.room, target.patient, ignore=target.id)
            if expected == "ok":
                appt = book.reschedule(target.id, start=naive, minutes=minutes)
                assert appt.start.astimezone(UTC) == start, context
                target.start, target.minutes = start, minutes
            else:
                with pytest.raises(EXPECTED_ERROR[expected]):
                    book.reschedule(target.id, start=naive, minutes=minutes)
        else:
            target = rng.choice(booked)
            book.cancel(target.id)
            target.status = "cancelled"

    # every appointment, its times and its reminders
    assert sorted(a.id for a in book.appointments()) == sorted(ref.appointments)
    for appt in book.appointments():
        mine = ref.appointments[appt.id]
        assert (appt.status, appt.start.astimezone(UTC), appt.end.astimezone(UTC)) == (
            mine.status, mine.start, mine.end)
        assert appt.start.utcoffset() == ref.local(mine.clinic, mine.start).utcoffset()
        due = [r.due.astimezone(UTC) for r in book.reminders(appt.id)]
        assert due == (ref.reminders(mine) if mine.status == "booked" else []), appt.id

    # agendas, day by day
    for clinic in WORLD_ZONES:
        for day in days:
            for d in (day - timedelta(days=1), day, day + timedelta(days=1)):
                rows = [r.appointment for r in book.agenda(clinic, d).rows]
                assert rows == ref.agenda(clinic, d), (seed, clinic, d)

    # the calendar export
    events, uid = {}, None
    for line in lines_of(book.export_ical()):
        if line.startswith("UID:"):
            uid = line[4:].split("@")[0]
        elif line.startswith("DTSTART:"):
            events[uid] = line[8:]
    assert events == {
        a.id: stamp(a.start) for a in ref.appointments.values() if a.status != "cancelled"
    }

    # the file, and the book read back from it
    path = book.save(tmp_path / f"scenario-{seed}.json")
    data = json.loads(path.read_text())
    assert {row["id"]: row["start"] for row in data["appointments"]} == {
        a.id: a.start.strftime("%Y-%m-%dT%H:%M:%SZ") for a in ref.appointments.values()
    }
    again = ClinicBook.open(path, clock=clock)
    for appt in again.appointments():
        assert appt.start.astimezone(UTC) == ref.appointments[appt.id].start


@pytest.mark.parametrize("seed", range(8))
def test_random_histories_match_the_model(seed, tmp_path):
    run_history(seed, 160, tmp_path)

"""Rules 14-16: backups and webhook payloads."""

import json
import zipfile
from datetime import datetime
from pathlib import Path

from clinicbook import ClinicBook, Store
from support import wall
from zones import INSTANT, u, utc, visit_at

DATA = Path(__file__).parent / "data"


def test_a_backup_holds_version_2_and_a_utc_taken_at(world, clock, tmp_path):
    visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0))
    clock.set(utc(2026, 2, 1, 23, 30))

    path = world.backup(tmp_path / "b.zip")

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        data = json.loads(archive.read("store.json"))
    assert manifest["store_version"] == 2 == data["version"]
    assert manifest["taken_at"] == "2026-02-01T23:30:00Z"
    assert data["appointments"][0]["start"] == "2026-03-02T21:00:00Z"


def test_a_backup_round_trip_keeps_the_instants(world, clock, tmp_path):
    a = visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0))
    b = visit_at(world, "brooklyn", datetime(2026, 11, 2, 9, 0), patient="P0002")
    path = world.backup(tmp_path / "b.zip")

    other = ClinicBook(Store.memory(), clock=clock)
    other.restore(path)

    assert u(other.appointment(a.id).start) == utc(2026, 3, 2, 21, 0)
    assert u(other.appointment(b.id).start) == utc(2026, 11, 2, 14, 0)
    assert wall(other.appointment(a.id).start) == "2026-03-03 08:00"


def test_a_backup_taken_before_restores_as_local_times(clock, tmp_path):
    data = json.loads((DATA / "legacy_v1.json").read_text())
    counts = {t: len(data[t]) for t in ("clinics", "rooms", "clinicians", "patients",
                                         "appointments", "series", "reminders", "waitlist",
                                         "messages", "webhook_queue", "audit")}
    old = tmp_path / "old.zip"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("manifest.json", json.dumps(
            {"format": 1, "store_version": 1, "taken_at": "2026-02-25T12:30", "counts": counts}))
        archive.writestr("store.json", json.dumps(data))

    book = ClinicBook(Store.memory(), clock=clock)
    book.restore(old)

    assert u(book.appointment("A0002").start) == utc(2026, 3, 9, 13, 0)
    assert u(book.appointment("A0003").start) == utc(2026, 3, 2, 21, 0)
    saved = json.loads(book.save(tmp_path / "restored.json").read_text())
    assert saved["version"] == 2


def test_webhook_payloads_are_in_utc(world, hooks, clock):
    world.configure(webhook_url="https://hooks.example.org/clinic")
    clock.set(utc(2026, 2, 1, 23, 30))
    visit_at(world, "brooklyn", datetime(2026, 3, 2, 9, 0), minutes=45)

    payload = json.loads(hooks.calls[0][1])

    assert payload["at"] == "2026-02-01T23:30:00Z"
    appt = payload["appointment"]
    assert (appt["start"], appt["end"]) == ("2026-03-02T14:00:00Z", "2026-03-02T14:45:00Z")
    assert appt["zone"] == "America/New_York"


def test_a_reschedule_payload_has_a_utc_previous_start(world, hooks):
    world.configure(webhook_url="https://hooks.example.org/clinic")
    appt = visit_at(world, "bondi", datetime(2026, 3, 3, 8, 0))
    world.reschedule(appt.id, start=datetime(2026, 4, 7, 8, 0))

    payload = json.loads(hooks.calls[-1][1])

    assert payload["event"] == "appointment.rescheduled"
    assert payload["previous_start"] == "2026-03-02T21:00:00Z"
    assert payload["appointment"]["start"] == "2026-04-06T22:00:00Z"
    assert payload["appointment"]["zone"] == "Australia/Sydney"


def test_queued_payloads_keep_utc_times(world, hooks, clock):
    world.configure(webhook_url="https://hooks.example.org/clinic")
    hooks.status = 500
    visit_at(world, "camden", datetime(2026, 7, 6, 9, 0))
    hooks.status = 200
    clock.set(utc(2026, 1, 5, 9, 0))
    world.run_jobs()

    payload = json.loads(hooks.calls[-1][1])
    assert payload["appointment"]["start"] == "2026-07-06T08:00:00Z"
    assert INSTANT.match(payload["at"])

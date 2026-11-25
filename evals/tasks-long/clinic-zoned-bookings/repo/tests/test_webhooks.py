import hashlib
import hmac
import json
from datetime import datetime

from support import visit


def test_nothing_is_posted_without_a_url(book, hooks):
    visit(book, datetime(2026, 1, 12, 9, 0))
    assert hooks.calls == []


def test_every_appointment_event_is_posted(book, hooks):
    book.configure(webhook_url="https://hooks.example.org/clinic")
    appt = visit(book, datetime(2026, 1, 12, 9, 0))
    book.reschedule(appt.id, start=datetime(2026, 1, 12, 10, 0))
    book.cancel(appt.id, reason="unwell")

    payloads = [json.loads(body) for _, body, _ in hooks.calls]

    assert [p["event"] for p in payloads] == [
        "appointment.booked", "appointment.rescheduled", "appointment.cancelled",
    ]
    assert {url for url, _, _ in hooks.calls} == {"https://hooks.example.org/clinic"}
    assert payloads[0]["appointment"]["id"] == appt.id
    assert payloads[0]["appointment"]["minutes"] == 30
    assert payloads[2]["reason"] == "unwell"
    assert "previous_start" in payloads[1]
    assert len({p["delivery"] for p in payloads}) == 3
    assert book.webhook_deliveries == payloads


def test_bodies_are_signed_with_the_secret(book, hooks):
    book.configure(webhook_url="https://hooks.example.org/clinic", webhook_secret="s3cret")
    visit(book, datetime(2026, 1, 12, 9, 0))

    _, body, headers = hooks.calls[0]

    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert headers["X-Clinicbook-Signature"] == expected


def test_failed_deliveries_are_retried_with_backoff(book, hooks, clock):
    book.configure(webhook_url="https://hooks.example.org/clinic")
    hooks.status = 503
    visit(book, datetime(2026, 1, 12, 9, 0))
    assert len(book.store.webhook_queue) == 1

    clock.set(datetime(2026, 1, 5, 8, 1))
    assert book.run_jobs().webhooks_delivered == 0
    assert len(hooks.calls) == 1  # not due for two minutes

    hooks.status = 200
    clock.set(datetime(2026, 1, 5, 8, 2))
    assert book.run_jobs().webhooks_delivered == 1
    assert book.store.webhook_queue == []
    assert json.loads(hooks.calls[-1][1])["event"] == "appointment.booked"


def test_deliveries_are_dropped_after_the_last_attempt(book, hooks, clock):
    book.configure(webhook_url="https://hooks.example.org/clinic", webhook_max_attempts=3)
    hooks.status = 500
    visit(book, datetime(2026, 1, 12, 9, 0))

    clock.set(datetime(2026, 1, 5, 9, 0))
    book.run_jobs()
    assert book.store.webhook_queue[0].attempts == 2
    clock.set(datetime(2026, 1, 5, 10, 0))
    book.run_jobs()
    assert book.store.webhook_queue == []
    assert len(hooks.calls) == 3

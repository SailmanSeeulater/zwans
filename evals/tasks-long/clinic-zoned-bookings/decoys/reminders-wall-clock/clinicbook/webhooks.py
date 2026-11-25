"""Webhooks: every appointment event is POSTed as JSON to the configured URL.

Failed deliveries wait in the `webhook_queue` table and are retried by the jobs with an
exponential backoff (2, 4, 8, ... minutes) until `webhook_max_attempts` is reached.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .ids import next_id
from .models import Appointment, QueuedDelivery
from .repository import Repository
from .storage import Store
from .timeutil import format_instant, instant

# sender(url, body, headers) -> HTTP status code; raising counts as a failure
Sender = Callable[[str, bytes, dict[str, str]], int]

SIGNATURE_HEADER = "X-Clinicbook-Signature"


def urllib_sender(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookDispatcher:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        clock: Callable[[], datetime],
        sender: Sender | None = None,
    ) -> None:
        self.store = store
        self.repo = repo
        self.clock = clock
        self.sender = sender or urllib_sender
        self.delivered: list[dict[str, Any]] = []

    def appointment_payload(self, appt: Appointment) -> dict[str, Any]:
        return {
            "id": appt.id,
            "clinic": appt.clinic,
            "clinician": appt.clinician,
            "room": appt.room,
            "patient": appt.patient,
            "kind": appt.kind,
            "status": appt.status,
            "start": format_instant(appt.start),
            "end": format_instant(appt.end),
            "zone": self.repo.clinic(appt.clinic).zone,
            "minutes": appt.minutes,
            "series": appt.series,
        }

    def payload(self, event: str, appt: Appointment, extra: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "event": event,
            "delivery": next_id(self.store.counters, "delivery"),
            "at": format_instant(self.clock()),
            "appointment": self.appointment_payload(appt),
        }
        if "previous_start" in extra:
            body["previous_start"] = format_instant(extra["previous_start"])
        if extra.get("reason"):
            body["reason"] = extra["reason"]
        return body

    def on_event(self, event: str, appointment: Appointment | None = None, **extra: Any) -> None:
        if not self.store.settings.webhook_url or appointment is None:
            return
        payload = self.payload(event, appointment, extra)
        error = self._post(payload)
        if error:
            self.store.webhook_queue.append(
                QueuedDelivery(
                    id=payload["delivery"],
                    payload=payload,
                    attempts=1,
                    next_attempt=instant(self.clock()) + self.backoff(1),
                    last_error=error,
                )
            )

    def backoff(self, attempts: int) -> timedelta:
        return timedelta(minutes=2**attempts)

    def _post(self, payload: dict[str, Any]) -> str:
        """Deliver one payload; '' on success, else what went wrong."""
        body = json.dumps(payload, sort_keys=True).encode()
        headers = {"Content-Type": "application/json"}
        if self.store.settings.webhook_secret:
            headers[SIGNATURE_HEADER] = sign(self.store.settings.webhook_secret, body)
        try:
            status = self.sender(self.store.settings.webhook_url, body, headers)
        except Exception as exc:  # noqa: BLE001 - any transport failure is retried
            return f"{type(exc).__name__}: {exc}"
        if 200 <= status < 300:
            self.delivered.append(payload)
            return ""
        return f"HTTP {status}"

    def retry(self, now: datetime) -> int:
        """Retry the queued deliveries that are due; returns how many got through."""
        if not self.store.settings.webhook_url:
            return 0
        delivered = 0
        keep = []
        for item in self.store.webhook_queue:
            if instant(item.next_attempt) > instant(now):
                keep.append(item)
                continue
            error = self._post(item.payload)
            if not error:
                delivered += 1
                continue
            item.attempts += 1
            item.last_error = error
            if item.attempts < self.store.settings.webhook_max_attempts:
                item.next_attempt = instant(now) + self.backoff(item.attempts)
                keep.append(item)
        self.store.webhook_queue = keep
        return delivered

"""Messages to patients. They go to the outbox (the `messages` table); the SMS and email
gateways pick them up from there."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from . import formatting, templates
from .ids import next_id
from .models import Appointment, Message
from .repository import Repository
from .storage import Store


class Notifier:
    def __init__(self, store: Store, repo: Repository, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.repo = repo
        self.clock = clock

    def fields(self, appt: Appointment) -> dict[str, str]:
        clinic = self.repo.clinic(appt.clinic)
        return {
            "patient": self.repo.patient(appt.patient).name.split()[0],
            "kind": appt.kind,
            "clinician": self.repo.clinician(appt.clinician).name,
            "clinic": clinic.name,
            "phone": clinic.phone or "the clinic",
            "when": formatting.short_when(appt.start),
        }

    def send(self, template: str, appt: Appointment) -> Message | None:
        patient = self.repo.patient(appt.patient)
        to = patient.address()
        if not to:
            return None
        message = Message(
            id=next_id(self.store.counters, "message"),
            to=to,
            channel=patient.channel,
            template=template,
            text=templates.render(template, **self.fields(appt)),
            at=self.clock(),
            appointment=appt.id,
        )
        self.store.messages.append(message)
        return message

    # -- event handlers ---------------------------------------------------------------

    def on_booked(self, appointment: Appointment, **_: Any) -> None:
        if appointment.source in ("desk", "series"):
            self.send("confirmation", appointment)

    def on_cancelled(self, appointment: Appointment, **_: Any) -> None:
        self.send("cancellation", appointment)

    def on_rescheduled(self, appointment: Appointment, **_: Any) -> None:
        self.send("rescheduled", appointment)

    def on_offered(self, appointment: Appointment, **_: Any) -> None:
        self.send("waitlist_offer", appointment)

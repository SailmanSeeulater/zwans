"""The activity timeline: one entry per thing that happened to a contact, newest last.

The timeline listens to the event bus and writes its own rows, so it never has to be
asked. Each entry keeps the contact's name; when a contact is renamed, its entries are
brought up to date.
"""

from orbit import ids
from orbit.events import Bus, Event
from orbit.models import Contact, TimelineEntry
from orbit.services.contacts import resolve_contact_id
from orbit.store import Store
from orbit.text import shorten


def _money(cents: int) -> str:
    return f"{cents // 100:,}.{cents % 100:02d}"


def _created(payload: dict) -> tuple[str, str, str | None]:
    return "created", "Added", None


def _updated(payload: dict) -> tuple[str, str, str | None]:
    return "updated", "Changed " + ", ".join(payload["changed"]), None


def _note(payload: dict) -> tuple[str, str, str | None]:
    return "note", shorten(payload["body"]), payload["id"]


def _email(payload: dict) -> tuple[str, str, str | None]:
    way = "to" if payload["direction"] == "out" else "from"
    return "email", f"Email {way} {payload['address'] or '?'}: {payload['subject']}", payload["id"]


def _task(payload: dict) -> tuple[str, str, str | None]:
    due = f" (due {payload['due']})" if payload["due"] else ""
    return "task", f"Task: {payload['title']}{due}", payload["id"]


def _task_done(payload: dict) -> tuple[str, str, str | None]:
    return "task-done", f"Done: {payload['title']}", payload["id"]


def _deal(payload: dict) -> tuple[str, str, str | None]:
    return "deal", f"New deal {payload['title']} ({_money(payload['amount'])})", payload["id"]


def _stage(payload: dict) -> tuple[str, str, str | None]:
    deal = payload["deal"]
    return "stage", f"{deal['title']}: {payload['from']} -> {payload['to']}", deal["id"]


DESCRIBE = {
    "contact.created": _created,
    "contact.updated": _updated,
    "note.added": _note,
    "email.logged": _email,
    "task.added": _task,
    "task.completed": _task_done,
    "deal.created": _deal,
    "deal.stage_changed": _stage,
}

NAME_FIELDS = {"first_name", "last_name", "emails"}


class TimelineService:
    def __init__(self, store: Store, clock) -> None:
        self.store = store
        self.clock = clock

    def attach(self, bus: Bus) -> None:
        bus.subscribe("*", self.on_event)

    def on_event(self, event: Event) -> None:
        describe = DESCRIBE.get(event.name)
        if describe is None:
            return
        if event.name == "contact.updated" and NAME_FIELDS & set(event.payload["changed"]):
            for contact_id in event.contact_ids:
                self.refresh_names(contact_id)
        kind, summary, ref = describe(event.payload)
        for contact_id in event.contact_ids:
            self.add(contact_id, kind, summary, ref)

    def add(
        self, contact_id: str, kind: str, summary: str, ref: str | None = None
    ) -> TimelineEntry:
        entry = TimelineEntry(
            id=ids.next_id(self.store, "timeline"),
            at=self.clock(),
            contact_id=contact_id,
            contact_name=self._name(contact_id),
            kind=kind,
            summary=summary,
            ref=ref,
        )
        self.store.put("timeline", entry.to_row())
        return entry

    def refresh_names(self, contact_id: str) -> int:
        name = self._name(contact_id)
        changed = 0
        for row in self.store.find("timeline", contact_id=contact_id):
            if row["contact_name"] != name:
                row["contact_name"] = name
                self.store.put("timeline", row)
                changed += 1
        return changed

    def for_contact(self, contact_id: str, limit: int | None = None) -> list[TimelineEntry]:
        rows = self.store.find("timeline", contact_id=resolve_contact_id(self.store, contact_id))
        entries = sorted(
            (TimelineEntry.from_row(row) for row in rows),
            key=lambda entry: (entry.at, ids.sort_key(entry.id)),
        )
        return entries[-limit:] if limit else entries

    def recent(self, limit: int = 20) -> list[TimelineEntry]:
        entries = sorted(
            (TimelineEntry.from_row(row) for row in self.store.rows("timeline")),
            key=lambda entry: (entry.at, ids.sort_key(entry.id)),
        )
        return entries[-limit:]

    def _name(self, contact_id: str) -> str:
        row = self.store.get("contacts", contact_id)
        return Contact.from_row(row).name if row else contact_id

"""Notes, tasks and emails logged against a contact."""

from datetime import date

from orbit import ids
from orbit.errors import InvalidValue, NotFound
from orbit.models import DIRECTIONS, Contact, Email, Note, Task
from orbit.payloads import email_payload, note_payload, task_payload
from orbit.services.base import Service
from orbit.services.contacts import ContactService
from orbit.text import is_email


def _by_time(rows: list[dict], key: str) -> list[dict]:
    return sorted(rows, key=lambda row: (row.get(key) or "", ids.sort_key(row["id"])))


class ActivityService(Service):
    def __init__(self, *args, contacts: ContactService) -> None:
        super().__init__(*args)
        self.contacts = contacts

    def _contact(self, contact_id: str) -> Contact:
        row = self.store.get("contacts", contact_id)
        if row is None:
            raise NotFound("contact", contact_id)
        return Contact.from_row(row)

    # -- notes ------------------------------------------------------------------------

    def add_note(self, contact_id: str, body: str, author: str = "") -> Note:
        contact = self._contact(contact_id)
        body = body.strip()
        if not body:
            raise InvalidValue("A note needs some text.")
        note = Note(
            id=ids.next_id(self.store, "notes"),
            contact_id=contact.id,
            body=body,
            at=self.clock(),
            author=author.strip(),
        )
        self.store.put("notes", note.to_row())
        self.publish("note.added", note_payload(note), [contact.id])
        return note

    def notes(self, contact_id: str) -> list[Note]:
        rows = self.store.find("notes", contact_id=contact_id)
        return [Note.from_row(row) for row in _by_time(rows, "at")]

    # -- tasks ------------------------------------------------------------------------

    def add_task(
        self, contact_id: str, title: str, due: str | None = None, owner: str = ""
    ) -> Task:
        contact = self._contact(contact_id)
        title = " ".join(title.split())
        if not title:
            raise InvalidValue("A task needs a title.")
        if due is not None:
            try:
                due = date.fromisoformat(due).isoformat()
            except ValueError:
                raise InvalidValue(f"{due!r} is not a date (YYYY-MM-DD).") from None
        task = Task(
            id=ids.next_id(self.store, "tasks"),
            contact_id=contact.id,
            title=title,
            due=due,
            owner=owner.strip() or contact.owner,
            created_at=self.clock(),
        )
        self.store.put("tasks", task.to_row())
        self.publish("task.added", task_payload(task), [contact.id])
        return task

    def task(self, task_id: str) -> Task:
        row = self.store.get("tasks", task_id)
        if row is None:
            raise NotFound("task", task_id)
        return Task.from_row(row)

    def complete_task(self, task_id: str) -> Task:
        task = self.task(task_id)
        if task.done:
            raise InvalidValue(f"{task.id} is already done.")
        task.done = True
        task.done_at = self.clock()
        self.store.put("tasks", task.to_row())
        self.publish("task.completed", task_payload(task), [task.contact_id])
        return task

    def reopen_task(self, task_id: str) -> Task:
        task = self.task(task_id)
        task.done = False
        task.done_at = None
        self.store.put("tasks", task.to_row())
        return task

    def tasks(self, contact_id: str | None = None, open_only: bool = False) -> list[Task]:
        rows = self.store.rows("tasks")
        if contact_id is not None:
            rows = [row for row in rows if row["contact_id"] == contact_id]
        tasks = [Task.from_row(row) for row in _by_time(rows, "created_at")]
        return [task for task in tasks if not (open_only and task.done)]

    # -- emails -----------------------------------------------------------------------

    def log_email(
        self,
        contact_id: str,
        subject: str,
        direction: str = "out",
        address: str | None = None,
    ) -> Email:
        contact = self._contact(contact_id)
        if direction not in DIRECTIONS:
            raise InvalidValue("An email's direction is 'in' or 'out'.")
        address = (address or contact.primary_email or "").strip()
        if address and not is_email(address):
            raise InvalidValue(f"{address!r} is not an email address.")
        email = Email(
            id=ids.next_id(self.store, "emails"),
            contact_id=contact.id,
            subject=" ".join(subject.split()) or "(no subject)",
            direction=direction,
            address=address,
            at=self.clock(),
        )
        self.store.put("emails", email.to_row())
        self.contacts.touch_contacted(contact.id, email.at)
        self.publish("email.logged", email_payload(email), [contact.id])
        return email

    def emails(self, contact_id: str) -> list[Email]:
        rows = self.store.find("emails", contact_id=contact_id)
        return [Email.from_row(row) for row in _by_time(rows, "at")]

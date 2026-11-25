"""`Crm`: the one object the CLI, the importer, the jobs and the tests go through.

It owns the store, the event bus, the in-memory indexes and the services, wires them
together, and runs every change as one undoable operation.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from orbit.clock import Clock, system_clock
from orbit.config import Settings, load_settings
from orbit.events import Bus
from orbit.index import DedupeIndex, SearchIndex, TagIndex
from orbit.models import (
    Company,
    Contact,
    Deal,
    Email,
    FieldDef,
    Note,
    OutboxMessage,
    Subscription,
    Task,
    TimelineEntry,
)
from orbit.services.activities import ActivityService
from orbit.services.companies import CompanyService
from orbit.services.contacts import ContactService
from orbit.services.deals import DealService
from orbit.services.fields import FieldService
from orbit.services.tags import TagService
from orbit.services.timeline import TimelineService
from orbit.services.undo import UndoLog
from orbit.services.webhooks import WebhookService
from orbit.store import Store


class Crm:
    def __init__(
        self, store: Store, clock: Clock = system_clock, settings: Settings | None = None
    ) -> None:
        self.store = store
        self.clock = clock
        self.settings = settings or Settings()
        self.bus = Bus()
        self.undo_log = UndoLog(store, clock, self.settings.undo_limit)

        self.search_index = SearchIndex(store)
        self.dedupe = DedupeIndex(store, self.settings.phone_match_digits)
        self.tag_index = TagIndex(store)

        args = (store, self.bus, clock, self.settings)
        self.contacts = ContactService(*args)
        self.companies = CompanyService(*args)
        self.deals = DealService(*args)
        self.activities = ActivityService(*args, contacts=self.contacts)
        self.tagging = TagService(*args, contacts=self.contacts, index=self.tag_index)
        self.fields = FieldService(*args, contacts=self.contacts)
        self.timeline_service = TimelineService(store, clock)
        self.webhooks = WebhookService(*args)

        self.timeline_service.attach(self.bus)
        self.search_index.attach(self.bus)
        self.dedupe.attach(self.bus)
        self.tag_index.attach(self.bus)
        self.webhooks.attach()
        self.rebuild_indexes()

    @classmethod
    def memory(cls, clock: Clock = system_clock, settings: Settings | None = None) -> "Crm":
        return cls(Store.memory(), clock, settings)

    @classmethod
    def open(
        cls, path: str | Path, clock: Clock = system_clock, settings: Settings | None = None
    ) -> "Crm":
        path = Path(path)
        if settings is None:
            settings = load_settings(path.with_name("orbit.toml"))
        return cls(Store.open(path), clock, settings)

    def save(self) -> Path:
        return self.store.save()

    def rebuild_indexes(self) -> None:
        self.search_index.rebuild()
        self.dedupe.rebuild()
        self.tag_index.rebuild()

    @contextmanager
    def operation(self, label: str) -> Iterator[None]:
        """Run a group of changes as one undo step; if anything fails, none of it sticks."""
        try:
            with self.undo_log.operation(label):
                yield
        except Exception:
            if not self.undo_log.busy:
                self.rebuild_indexes()
            raise

    # -- contacts ---------------------------------------------------------------------

    def add_contact(self, first_name: str, last_name: str = "", **details) -> Contact:
        with self.operation("add contact"):
            return self.contacts.create(first_name, last_name, **details)

    def contact(self, contact_id: str) -> Contact:
        return self.contacts.get(contact_id)

    def list_contacts(self, include_archived: bool = False) -> list[Contact]:
        return self.contacts.all(include_archived)

    def update_contact(self, contact_id: str, **changes) -> Contact:
        with self.operation("update contact"):
            return self.contacts.update(contact_id, **changes)

    def archive_contact(self, contact_id: str) -> Contact:
        with self.operation("archive contact"):
            return self.contacts.set_status(contact_id, "archived")

    def unarchive_contact(self, contact_id: str) -> Contact:
        with self.operation("unarchive contact"):
            return self.contacts.set_status(contact_id, "active")

    def find_by_email(self, address: str) -> list[Contact]:
        return [self.contacts.get(contact_id) for contact_id in self.dedupe.match_email(address)]

    # -- companies --------------------------------------------------------------------

    def add_company(self, name: str, domain: str = "") -> Company:
        with self.operation("add company"):
            return self.companies.create(name, domain)

    def company(self, company_id: str) -> Company:
        return self.companies.get(company_id)

    def list_companies(self) -> list[Company]:
        return self.companies.all()

    def rename_company(self, company_id: str, name: str) -> Company:
        with self.operation("rename company"):
            return self.companies.rename(company_id, name)

    def set_primary_contact(self, company_id: str, contact_id: str | None) -> Company:
        with self.operation("set primary contact"):
            return self.companies.set_primary_contact(company_id, contact_id)

    # -- deals ------------------------------------------------------------------------

    def add_deal(self, title: str, amount: int = 0, contact_ids=(), **details) -> Deal:
        with self.operation("add deal"):
            return self.deals.create(title, amount, contact_ids, **details)

    def deal(self, deal_id: str) -> Deal:
        return self.deals.get(deal_id)

    def list_deals(self, stage: str | None = None, open_only: bool = False) -> list[Deal]:
        return self.deals.all(stage, open_only)

    def move_deal(self, deal_id: str, stage: str, contact_id: str | None = None) -> Deal:
        with self.operation("move deal"):
            return self.deals.move(deal_id, stage, contact_id)

    def update_deal(self, deal_id: str, **changes) -> Deal:
        with self.operation("update deal"):
            return self.deals.update(deal_id, **changes)

    def add_deal_contact(self, deal_id: str, contact_id: str) -> Deal:
        with self.operation("add deal contact"):
            return self.deals.add_contact(deal_id, contact_id)

    def remove_deal_contact(self, deal_id: str, contact_id: str) -> Deal:
        with self.operation("remove deal contact"):
            return self.deals.remove_contact(deal_id, contact_id)

    # -- notes, tasks, emails -----------------------------------------------------------

    def add_note(self, contact_id: str, body: str, author: str = "") -> Note:
        with self.operation("add note"):
            return self.activities.add_note(contact_id, body, author)

    def notes(self, contact_id: str) -> list[Note]:
        return self.activities.notes(contact_id)

    def add_task(
        self, contact_id: str, title: str, due: str | None = None, owner: str = ""
    ) -> Task:
        with self.operation("add task"):
            return self.activities.add_task(contact_id, title, due, owner)

    def complete_task(self, task_id: str) -> Task:
        with self.operation("complete task"):
            return self.activities.complete_task(task_id)

    def tasks(self, contact_id: str | None = None, open_only: bool = False) -> list[Task]:
        return self.activities.tasks(contact_id, open_only)

    def log_email(
        self, contact_id: str, subject: str, direction: str = "out", address: str | None = None
    ) -> Email:
        with self.operation("log email"):
            return self.activities.log_email(contact_id, subject, direction, address)

    def emails(self, contact_id: str) -> list[Email]:
        return self.activities.emails(contact_id)

    # -- tags and custom fields -----------------------------------------------------------

    def tag(self, contact_id: str, *tags: str) -> Contact:
        with self.operation("tag"):
            return self.tagging.tag(contact_id, *tags)

    def untag(self, contact_id: str, *tags: str) -> Contact:
        with self.operation("untag"):
            return self.tagging.untag(contact_id, *tags)

    def tagged(self, tag: str) -> list[Contact]:
        return self.tagging.tagged(tag)

    def tag_counts(self) -> dict[str, int]:
        return self.tagging.counts()

    def rename_tag(self, old: str, new: str) -> int:
        with self.operation("rename tag"):
            return self.tagging.rename(old, new)

    def define_field(self, name: str, type: str = "text", label: str = "", choices=()) -> FieldDef:
        with self.operation("define field"):
            return self.fields.define(name, type, label, choices)

    def field_definitions(self) -> list[FieldDef]:
        return self.fields.definitions()

    def set_field(self, contact_id: str, name: str, value) -> Contact:
        with self.operation("set field"):
            return self.fields.set(contact_id, name, value)

    # -- timeline, search, duplicates -------------------------------------------------------

    def timeline(self, contact_id: str, limit: int | None = None) -> list[TimelineEntry]:
        return self.timeline_service.for_contact(contact_id, limit)

    def search(self, text: str, include_archived: bool = False) -> list[Contact]:
        found = [self.contacts.get(contact_id) for contact_id in self.search_index.query(text)]
        return [contact for contact in found if include_archived or contact.active]

    def duplicates(self) -> list[tuple[str, ...]]:
        return self.dedupe.groups()

    def duplicates_of(self, contact_id: str) -> list[str]:
        return self.dedupe.duplicates_of(contact_id)

    # -- webhooks ---------------------------------------------------------------------

    def subscribe(
        self, url: str, events=("*",), contact_id: str | None = None, secret: str | None = None
    ) -> Subscription:
        with self.operation("subscribe"):
            return self.webhooks.subscribe(url, events, contact_id, secret)

    def unsubscribe(self, subscription_id: str) -> None:
        with self.operation("unsubscribe"):
            self.webhooks.unsubscribe(subscription_id)

    def subscriptions(self) -> list[Subscription]:
        return self.webhooks.subscriptions()

    def outbox(self, pending_only: bool = False) -> list[OutboxMessage]:
        return self.webhooks.outbox(pending_only)

    # -- undo -------------------------------------------------------------------------

    def undo(self) -> str:
        """Undo the last command; returns what it was ("add note", ...). Sends no webhooks."""
        label = self.undo_log.undo()
        self.rebuild_indexes()
        return label

    def history(self) -> list[dict]:
        return self.undo_log.history()

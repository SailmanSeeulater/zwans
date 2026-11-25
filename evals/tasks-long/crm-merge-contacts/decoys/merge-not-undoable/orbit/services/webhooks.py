"""Webhooks: subscriptions and the outbox.

Every event a subscription wants becomes a message in the outbox, written in the same
step as the change itself. Delivering the outbox is a separate job (orbit.jobs.dispatcher),
so a change never waits on, or fails because of, somebody else's server.
"""

import secrets
from urllib.parse import urlparse

from orbit import ids
from orbit.errors import InvalidValue, NotFound
from orbit.events import Event
from orbit.models import OutboxMessage, Subscription
from orbit.services.base import Service
from orbit.services.contacts import resolve_contact_id

EVENTS = (
    "contact.created",
    "contact.updated",
    "company.created",
    "company.updated",
    "deal.created",
    "deal.updated",
    "deal.stage_changed",
    "note.added",
    "task.added",
    "task.completed",
    "email.logged",
    "contact.merged",
)


class WebhookService(Service):
    def attach(self) -> None:
        self.bus.subscribe("*", self.on_event)

    # -- subscriptions ------------------------------------------------------------------

    def subscribe(
        self, url: str, events=("*",), contact_id: str | None = None, secret: str | None = None
    ) -> Subscription:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise InvalidValue(f"{url!r} is not an http(s) URL.")
        events = list(events) or ["*"]
        unknown = [name for name in events if name != "*" and name not in EVENTS]
        if unknown:
            raise InvalidValue(f"Unknown event {unknown[0]!r}; events are {', '.join(EVENTS)}.")
        if contact_id is not None:
            given, contact_id = contact_id, resolve_contact_id(self.store, contact_id)
            if not self.store.has("contacts", contact_id):
                raise NotFound("contact", given)
        subscription = Subscription(
            id=ids.next_id(self.store, "subscriptions"),
            url=url,
            events=events,
            contact_id=contact_id,
            secret=secret if secret is not None else secrets.token_hex(16),
            created_at=self.clock(),
        )
        self.store.put("subscriptions", subscription.to_row())
        return subscription

    def subscription(self, subscription_id: str) -> Subscription:
        row = self.store.get("subscriptions", subscription_id)
        if row is None:
            raise NotFound("subscription", subscription_id)
        return Subscription.from_row(row)

    def subscriptions(self) -> list[Subscription]:
        return [Subscription.from_row(row) for row in self.store.rows("subscriptions")]

    def unsubscribe(self, subscription_id: str) -> None:
        self.subscription(subscription_id)
        self.store.delete("subscriptions", subscription_id)

    def set_active(self, subscription_id: str, active: bool) -> Subscription:
        subscription = self.subscription(subscription_id)
        subscription.active = active
        self.store.put("subscriptions", subscription.to_row())
        return subscription

    # -- the outbox -------------------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if event.name not in EVENTS:
            return
        for subscription in self.subscriptions():
            if not subscription.wants(event.name):
                continue
            if (
                subscription.contact_id is not None
                and subscription.contact_id not in event.contact_ids
            ):
                continue
            self.enqueue(subscription, event)

    def enqueue(self, subscription: Subscription, event: Event) -> OutboxMessage:
        now = self.clock()
        message = OutboxMessage(
            id=ids.next_id(self.store, "outbox"),
            subscription_id=subscription.id,
            event=event.name,
            payload=event.payload,
            created_at=now,
            next_attempt_at=now,
        )
        self.store.put("outbox", message.to_row())
        return message

    def outbox(self, pending_only: bool = False) -> list[OutboxMessage]:
        messages = [OutboxMessage.from_row(row) for row in self.store.rows("outbox")]
        return [m for m in messages if m.pending or not pending_only]

    def message(self, message_id: str) -> OutboxMessage:
        row = self.store.get("outbox", message_id)
        if row is None:
            raise NotFound("outbox message", message_id)
        return OutboxMessage.from_row(row)

    def save_message(self, message: OutboxMessage) -> None:
        self.store.put("outbox", message.to_row())

    def purge_delivered(self) -> int:
        delivered = [m for m in self.outbox() if m.delivered_at is not None]
        for message in delivered:
            self.store.delete("outbox", message.id)
        return len(delivered)

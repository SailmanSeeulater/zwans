"""Delivering the webhook outbox.

Each pending message whose time has come is POSTed as JSON to its subscription's URL:

    {"id": "ob12", "event": "note.added", "created_at": "...", "data": {...payload...}}

with an `X-Orbit-Signature` header (HMAC-SHA256 of the body with the subscription's
secret, hex). A 2xx answer delivers it. Anything else, or no answer, is retried later,
waiting twice as long each time, until the attempts run out and the message is marked
failed. Messages go out oldest first.

The transport is passed in: `transport(url, body, headers) -> status code`, raising
OSError when the server can't be reached. The CLI uses urllib.
"""

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from orbit.clock import add_seconds
from orbit.models import OutboxMessage

type Transport = Callable[[str, bytes, dict[str, str]], int]


@dataclass
class DeliveryReport:
    delivered: list[str] = field(default_factory=list)
    retrying: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{len(self.delivered)} delivered, {len(self.retrying)} to retry, "
            f"{len(self.failed)} failed"
        )


def body_of(message: OutboxMessage) -> bytes:
    document = {
        "id": message.id,
        "event": message.event,
        "created_at": message.created_at,
        "data": message.payload,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def urllib_transport(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def due(crm, now: str) -> list[OutboxMessage]:
    return [
        message
        for message in crm.webhooks.outbox(pending_only=True)
        if message.next_attempt_at is None or message.next_attempt_at <= now
    ]


def deliver(crm, transport: Transport, limit: int | None = None) -> DeliveryReport:
    report = DeliveryReport()
    now = crm.clock()
    settings = crm.settings
    subscriptions = {sub.id: sub for sub in crm.webhooks.subscriptions()}
    for message in due(crm, now)[:limit]:
        subscription = subscriptions.get(message.subscription_id)
        message.attempts += 1
        if subscription is None:
            message.failed = True
            message.last_error = "subscription removed"
            report.failed.append(message.id)
            crm.webhooks.save_message(message)
            continue
        body = body_of(message)
        headers = {
            "Content-Type": "application/json",
            "X-Orbit-Event": message.event,
            "X-Orbit-Signature": sign(subscription.secret, body),
        }
        try:
            status = transport(subscription.url, body, headers)
            error = None if 200 <= status < 300 else f"HTTP {status}"
        except OSError as exc:
            error = str(exc) or exc.__class__.__name__
        if error is None:
            message.delivered_at = now
            message.last_error = None
            report.delivered.append(message.id)
        elif message.attempts >= settings.outbox_max_attempts:
            message.failed = True
            message.last_error = error
            report.failed.append(message.id)
        else:
            wait = settings.retry_after_seconds * 2 ** (message.attempts - 1)
            message.next_attempt_at = add_seconds(now, wait)
            message.last_error = error
            report.retrying.append(message.id)
        crm.webhooks.save_message(message)
    return report


def retry_failed(crm) -> int:
    """Give failed messages a fresh set of attempts."""
    count = 0
    for message in crm.webhooks.outbox():
        if message.failed:
            message.failed = False
            message.attempts = 0
            message.next_attempt_at = None
            crm.webhooks.save_message(message)
            count += 1
    return count

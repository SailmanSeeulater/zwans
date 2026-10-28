"""Customer emails.

The notifier is subscribed to the bus only, never fed the old log, so each email goes out
once: when the event is first recorded. Messages go to an outbox (a JSON-lines file when
there is a data folder); a separate mailer process sends them.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .aggregate import OrderState
from .events import Event, OrderCancelled, OrderPlaced, OrderShipped
from .money import format_amount
from .templates import render


class Outbox:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._messages: list[dict[str, str]] = []
        if self.path is not None and self.path.exists():
            with self.path.open(encoding="utf-8") as file:
                self._messages = [json.loads(line) for line in file if line.strip()]

    def send(self, to: str, subject: str, body: str) -> None:
        message = {"to": to, "subject": subject, "body": body}
        self._messages.append(message)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(message, sort_keys=True) + "\n")

    def messages(self) -> list[dict[str, str]]:
        return list(self._messages)


def _placed(ev: OrderPlaced) -> tuple[str, dict[str, Any]]:
    return "order_placed", {"total": format_amount(ev.total_cents)}


def _shipped(ev: OrderShipped) -> tuple[str, dict[str, Any]]:
    return "order_shipped", {"carrier": ev.carrier, "tracking": ev.tracking}


def _cancelled(ev: OrderCancelled) -> tuple[str, dict[str, Any]]:
    if ev.refund_cents:
        return "order_cancelled_refunded", {
            "reason": ev.reason,
            "refund": format_amount(ev.refund_cents),
        }
    return "order_cancelled", {"reason": ev.reason}


# Which events the customer hears about, and how.
_MESSAGES: dict[type[Event], Callable[[Any], tuple[str, dict[str, Any]]]] = {
    OrderPlaced: _placed,
    OrderShipped: _shipped,
    OrderCancelled: _cancelled,
}


class Notifier:
    def __init__(self, outbox: Outbox, lookup: Callable[[str], OrderState]) -> None:
        self._outbox = outbox
        self._lookup = lookup  # order id -> current state, for the customer's name and email

    def __call__(self, ev: Event) -> None:
        build = _MESSAGES.get(type(ev))
        if build is None:
            return
        template, values = build(ev)
        order = self._lookup(ev.order_id)
        subject, body = render(template, customer=order.customer, order_id=ev.order_id, **values)
        self._outbox.send(order.email, subject, body)

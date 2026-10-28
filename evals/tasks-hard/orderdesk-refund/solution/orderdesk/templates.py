"""Email templates for customer notifications: name -> (subject, body).

Every template can use {customer} and {order_id}; the rest is filled in by the notifier.
Amounts are already formatted (e.g. '12.50') by the time they get here.
"""

TEMPLATES: dict[str, tuple[str, str]] = {
    "order_placed": (
        "We got your order {order_id}",
        "Hello {customer},\n\nThanks for your order {order_id}. The total is {total}.\n",
    ),
    "order_shipped": (
        "Your order {order_id} is on its way",
        "Hello {customer},\n\nYour order {order_id} has shipped with {carrier}.\n"
        "Tracking number: {tracking}\n",
    ),
    "order_cancelled": (
        "Your order {order_id} has been cancelled",
        "Hello {customer},\n\nYour order {order_id} has been cancelled: {reason}\n",
    ),
    "order_cancelled_refunded": (
        "Your order {order_id} has been cancelled",
        "Hello {customer},\n\nYour order {order_id} has been cancelled: {reason}\n"
        "We have refunded {refund} to you.\n",
    ),
    "order_refunded": (
        "We have refunded {refund} on your order {order_id}",
        "Hello {customer},\n\nWe have refunded {refund} to you for your order {order_id}: {reason}\n",
    ),
}


def render(name: str, **values: str) -> tuple[str, str]:
    subject, body = TEMPLATES[name]
    return subject.format(**values), body.format(**values)

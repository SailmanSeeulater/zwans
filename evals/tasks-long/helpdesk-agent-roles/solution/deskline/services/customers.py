"""Customers: the people who write in."""

from __future__ import annotations

import re

from .. import audit
from ..context import Context
from ..errors import Conflict, ValidationError
from ..models import Customer
from ..permissions import require
from ..textutil import parse_tags

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EDITABLE = ("name", "email", "phone", "address", "organization", "tags")


def _check_email(ctx: Context, email: str, exclude: str | None = None) -> str:
    email = email.strip().lower()
    if not email:
        return ""
    if not _EMAIL.match(email):
        raise ValidationError(f"not an email address: {email!r}")
    other = ctx.store.customer_by_email(email)
    if other is not None and other.id != exclude:
        raise Conflict(f"{other.id} already uses that email address")
    return email


def create(
    ctx: Context,
    name: str,
    *,
    email: str = "",
    phone: str = "",
    address: str = "",
    organization: str = "",
    tags: list[str] | tuple[str, ...] = (),
) -> Customer:
    require(ctx, "customer.edit")
    return _create(
        ctx, name, email=email, phone=phone, address=address, organization=organization, tags=tags
    )


def _create(
    ctx: Context,
    name: str,
    *,
    email: str = "",
    phone: str = "",
    address: str = "",
    organization: str = "",
    tags: list[str] | tuple[str, ...] = (),
) -> Customer:
    name = name.strip()
    if not name:
        raise ValidationError("a customer needs a name")
    with ctx.store.transaction():
        email = _check_email(ctx, email)
        customer = Customer(
            id=ctx.store.next_id("customer", "C"),
            name=name,
            email=email,
            phone=phone.strip(),
            address=address.strip(),
            organization=organization.strip(),
            created_at=ctx.now(),
            tags=parse_tags(",".join(tags)),
        )
        ctx.store.customers[customer.id] = customer
        ctx.record(
            "customer.created",
            customer.id,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            address=customer.address,
        )
    return customer


def update(ctx: Context, customer_id: str, **fields: object) -> Customer:
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ValidationError(f"cannot change {', '.join(sorted(unknown))}")
    with ctx.store.transaction():
        customer = ctx.store.customer(customer_id)
        require(ctx, "customer.edit", target=customer.id)
        before = Customer.from_dict(customer.to_dict())
        for name, value in fields.items():
            if value is None:
                continue
            if name == "email":
                value = _check_email(ctx, str(value), exclude=customer.id)
            elif name == "tags":
                value = parse_tags(",".join(value) if isinstance(value, list) else str(value))
            elif name == "name":
                value = str(value).strip()
                if not value:
                    raise ValidationError("a customer needs a name")
            else:
                value = str(value).strip()
            setattr(customer, name, value)
        diff = audit.changes(before, customer, list(EDITABLE))
        if diff:
            ctx.record("customer.updated", customer.id, changes=diff)
    return customer


def get(ctx: Context, customer_id: str) -> Customer:
    customer = ctx.store.customer(customer_id)
    require(ctx, "customer.view", target=customer.id)
    return customer


def list_customers(ctx: Context, text: str | None = None) -> list[Customer]:
    require(ctx, "customer.view")
    customers = sorted(ctx.store.customers.values(), key=lambda c: int(c.id.split("-")[1]))
    if not text:
        return customers
    needle = text.lower()
    return [
        c
        for c in customers
        if needle in c.name.lower() or needle in c.organization.lower()
    ]


def tickets_of(ctx: Context, customer_id: str) -> list[str]:
    require(ctx, "ticket.view")
    return sorted(
        (t.id for t in ctx.store.tickets.values() if t.customer_id == customer_id),
        key=lambda tid: int(tid.split("-")[1]),
    )


def delete(ctx: Context, customer_id: str) -> None:
    with ctx.store.transaction():
        customer = ctx.store.customer(customer_id)
        require(ctx, "customer.delete", target=customer.id)
        if tickets_of(ctx, customer_id):
            raise Conflict(f"{customer_id} still has tickets")
        del ctx.store.customers[customer.id]
        ctx.record("customer.deleted", customer.id, name=customer.name)


def find_or_create(ctx: Context, name: str, email: str) -> tuple[Customer, bool]:
    """Used by the mail gateway: the customer with this address, or a new one."""
    existing = ctx.store.customer_by_email(email)
    if existing is not None:
        return existing, False
    return _create(ctx, name or email, email=email), True

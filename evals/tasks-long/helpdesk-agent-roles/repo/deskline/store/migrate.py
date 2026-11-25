"""Upgrades for files written by older versions of deskline.

Version 1 (deskline 0.x) kept a customer's contact details in one ``contact`` string and
called a ticket's assignee ``assigned_to``. Version 2 stored ticket tags as one
comma-separated string. Version 3 is the current format.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..errors import StoreError

CURRENT_VERSION = 3

_EMAIL = re.compile(r"[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+")


def _split_contact(contact: str) -> tuple[str, str]:
    """Pull an email address and a phone number out of a free-form contact string."""
    email = ""
    match = _EMAIL.search(contact)
    if match:
        email = match.group(0)
        contact = contact.replace(email, " ")
    phone = " ".join(part for part in re.split(r"[;,/]", contact) if part.strip()).strip()
    phone = re.sub(r"\s+", " ", phone)
    return email, phone


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    for customer in data.get("customers", []):
        if "contact" in customer:
            email, phone = _split_contact(customer.pop("contact") or "")
            customer.setdefault("email", email)
            customer.setdefault("phone", phone)
    for ticket in data.get("tickets", []):
        if "assigned_to" in ticket:
            ticket["assignee"] = ticket.pop("assigned_to") or None
        ticket["tags"] = ",".join(ticket.get("tags", []))
    return data


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    for ticket in data.get("tickets", []):
        tags = ticket.get("tags", "")
        if isinstance(tags, str):
            ticket["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    return data


UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}


def upgrade(document: dict[str, Any]) -> dict[str, Any]:
    """Bring a loaded file document up to the current version; returns its data part."""
    if document.get("format") != "deskline":
        raise StoreError("not a deskline file")
    version = document.get("version")
    if not isinstance(version, int) or version < 1:
        raise StoreError(f"bad file version {version!r}")
    if version > CURRENT_VERSION:
        raise StoreError(
            f"file version {version} is newer than this deskline (reads up to {CURRENT_VERSION})"
        )
    data = document.get("data", {})
    while version < CURRENT_VERSION:
        data = UPGRADES[version](data)
        version += 1
    return data

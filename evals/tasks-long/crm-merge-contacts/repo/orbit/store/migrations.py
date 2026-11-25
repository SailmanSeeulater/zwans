"""Bringing data files written by older releases up to date.

Version 1 (orbit 0.x) kept each table as a list and allowed one email address and one
phone number per contact, and one contact per deal; it had no timeline, no logged emails,
no custom fields and no webhooks. Version 2 is today's format.
"""

import copy

from orbit.errors import StoreError
from orbit.text import display_name

FORMAT_VERSION = 2


def upgrade(document: dict) -> dict:
    if document.get("format", "orbit") != "orbit":
        raise StoreError("Not an orbit data file.")
    version = document.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise StoreError(f"Unknown data file version {version!r}.")
    if version > FORMAT_VERSION:
        raise StoreError(
            f"This data file is version {version}; this orbit reads up to {FORMAT_VERSION}."
        )
    data = copy.deepcopy(document)
    if version == 1:
        data = _from_v1(data)
    return data


def _from_v1(old: dict) -> dict:
    contacts = {}
    for row in old.get("contacts", []):
        row = dict(row)
        email = row.pop("email", None)
        phone = row.pop("phone", None)
        row["emails"] = [email] if email else []
        row["phones"] = [phone] if phone else []
        row.setdefault("tags", [])
        row.setdefault("fields", {})
        row.setdefault("status", "active")
        row.setdefault("updated_at", row.get("created_at", ""))
        row.setdefault("last_contacted_at", None)
        contacts[row["id"]] = row

    deals = {}
    for row in old.get("deals", []):
        row = dict(row)
        contact_id = row.pop("contact_id", None)
        row["contact_ids"] = [contact_id] if contact_id else []
        row["stage_history"] = [
            {"stage": change["stage"], "at": change["at"], "contact_id": None}
            for change in row.get("stage_history", [])
        ]
        row.setdefault("updated_at", row.get("created_at", ""))
        row.setdefault("closed_at", None)
        deals[row["id"]] = row

    timeline = {}
    for number, note in enumerate(old.get("notes", []), start=1):
        contact = contacts.get(note["contact_id"])
        if contact is None:
            continue
        timeline[f"tl{number}"] = {
            "id": f"tl{number}",
            "at": note.get("at", ""),
            "contact_id": note["contact_id"],
            "contact_name": display_name(contact["first_name"], contact.get("last_name", "")),
            "kind": "note",
            "summary": note.get("body", "")[:60],
            "ref": note["id"],
        }

    def keyed(rows: list[dict]) -> dict:
        return {row["id"]: dict(row) for row in rows}

    return {
        "format": "orbit",
        "version": FORMAT_VERSION,
        "tables": {
            "contacts": contacts,
            "companies": keyed(old.get("companies", [])),
            "deals": deals,
            "notes": keyed(old.get("notes", [])),
            "tasks": keyed(old.get("tasks", [])),
            "timeline": timeline,
        },
        "undo": [],
    }

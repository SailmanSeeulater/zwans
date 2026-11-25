"""JSON exports: everything orbit knows about one contact (for "what do you have on me?"
requests), or the whole CRM."""

from orbit import ids
from orbit.errors import NotFound
from orbit.models import Contact, Deal, Email, Note, Task, TimelineEntry
from orbit.payloads import (
    company_payload,
    contact_payload,
    deal_payload,
    email_payload,
    note_payload,
    task_payload,
)
from orbit.services.contacts import resolve_contact_id


def contact_dossier(crm, contact_id: str) -> dict:
    row = crm.store.get("contacts", resolve_contact_id(crm.store, contact_id))
    if row is None:
        raise NotFound("contact", contact_id)
    contact = Contact.from_row(row)
    store = crm.store
    deals = [Deal.from_row(r) for r in store.rows("deals") if contact.id in r["contact_ids"]]
    timeline = sorted(
        (TimelineEntry.from_row(r) for r in store.find("timeline", contact_id=contact.id)),
        key=lambda entry: (entry.at, ids.sort_key(entry.id)),
    )
    return {
        "contact": contact_payload(contact, crm.contacts.company_of(contact)),
        "notes": [
            note_payload(Note.from_row(r)) for r in store.find("notes", contact_id=contact.id)
        ],
        "tasks": [
            task_payload(Task.from_row(r)) for r in store.find("tasks", contact_id=contact.id)
        ],
        "emails": [
            email_payload(Email.from_row(r)) for r in store.find("emails", contact_id=contact.id)
        ],
        "deals": [deal_payload(deal) for deal in deals],
        "timeline": [
            {"at": e.at, "kind": e.kind, "summary": e.summary, "ref": e.ref} for e in timeline
        ],
    }


def export_all(crm) -> dict:
    return {
        "contacts": [crm.contacts.payload(contact) for contact in crm.contacts.all(True)],
        "companies": [company_payload(company) for company in crm.companies.all()],
        "deals": [deal_payload(deal) for deal in crm.deals.all()],
        "fields": [definition.to_row() for definition in crm.fields.definitions()],
    }

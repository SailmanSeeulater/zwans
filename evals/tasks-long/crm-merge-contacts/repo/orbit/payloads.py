"""The JSON shapes records take outside orbit: in webhooks, in the JSON export and in the
CLI's --json output. Changing one of these changes a public format."""

from orbit.models import Company, Contact, Deal, Email, Note, Task


def company_ref(company: Company | None) -> dict | None:
    if company is None:
        return None
    return {"id": company.id, "name": company.name}


def contact_payload(contact: Contact, company: Company | None = None) -> dict:
    return {
        "id": contact.id,
        "name": contact.name,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "emails": list(contact.emails),
        "phones": list(contact.phones),
        "company": company_ref(company),
        "title": contact.title,
        "owner": contact.owner,
        "source": contact.source,
        "tags": list(contact.tags),
        "fields": dict(contact.fields),
        "status": contact.status,
        "created_at": contact.created_at,
        "last_contacted_at": contact.last_contacted_at,
    }


def company_payload(company: Company) -> dict:
    return {
        "id": company.id,
        "name": company.name,
        "domain": company.domain,
        "primary_contact_id": company.primary_contact_id,
    }


def deal_payload(deal: Deal) -> dict:
    return {
        "id": deal.id,
        "title": deal.title,
        "amount": deal.amount,
        "stage": deal.stage,
        "contact_ids": list(deal.contact_ids),
        "company_id": deal.company_id,
        "owner": deal.owner,
        "closed_at": deal.closed_at,
    }


def note_payload(note: Note) -> dict:
    return {"id": note.id, "contact_id": note.contact_id, "body": note.body, "at": note.at}


def task_payload(task: Task) -> dict:
    return {
        "id": task.id,
        "contact_id": task.contact_id,
        "title": task.title,
        "due": task.due,
        "owner": task.owner,
        "done": task.done,
    }


def email_payload(email: Email) -> dict:
    return {
        "id": email.id,
        "contact_id": email.contact_id,
        "subject": email.subject,
        "direction": email.direction,
        "address": email.address,
        "at": email.at,
    }

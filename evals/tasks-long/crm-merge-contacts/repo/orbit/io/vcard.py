"""vCard 3.0 export, for address books."""

from orbit.models import Contact


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def vcard(contact: Contact, company_name: str = "") -> str:
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:orbit-{contact.id}",
        f"N:{_escape(contact.last_name)};{_escape(contact.first_name)};;;",
        f"FN:{_escape(contact.name)}",
    ]
    if company_name:
        lines.append(f"ORG:{_escape(company_name)}")
    if contact.title:
        lines.append(f"TITLE:{_escape(contact.title)}")
    for number, address in enumerate(contact.emails):
        kind = "INTERNET,PREF" if number == 0 else "INTERNET"
        lines.append(f"EMAIL;TYPE={kind}:{address}")
    for phone in contact.phones:
        lines.append(f"TEL;TYPE=VOICE:{phone}")
    if contact.tags:
        lines.append("CATEGORIES:" + ",".join(_escape(tag) for tag in contact.tags))
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def export_vcards(crm, contact_ids=None) -> str:
    if contact_ids:
        contacts = [crm.contact(contact_id) for contact_id in contact_ids]
    else:
        contacts = crm.list_contacts()
    cards = []
    for contact in contacts:
        company = crm.contacts.company_of(contact)
        cards.append(vcard(contact, company.name if company else ""))
    return "".join(cards)

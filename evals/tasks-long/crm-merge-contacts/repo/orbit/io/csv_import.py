"""Importing contacts from CSV.

Columns (all optional except that a row needs a first name or an email):

    id, first_name, last_name, email, phone, company, title, owner, source, tags,
    field:<name> (one column per custom field)

`email`, `phone` and `tags` may hold several values separated by ";". A row updates an
existing contact when its `id` names one, or else when one of its email addresses
belongs to one (the oldest such contact wins); otherwise it creates a contact. Updating
only fills in what the row has: empty cells never blank anything, addresses, numbers and
tags are added to what the contact already has.

The whole import is one undo step. With dry_run nothing is kept, but the result says
what would have happened.
"""

import csv
import io
from dataclasses import dataclass, field

from orbit.errors import CrmError, ImportFailed
from orbit.text import normalize_email, phone_digits, split_list

COLUMNS = (
    "id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "company",
    "title",
    "owner",
    "source",
    "tags",
)
FIELD_PREFIX = "field:"
PLAIN = ("first_name", "last_name", "title", "owner", "source")


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (line, why)

    def summary(self) -> str:
        return (
            f"{len(self.created)} created, {len(self.updated)} updated, {len(self.skipped)} skipped"
        )


class _DryRun(Exception):
    pass


def import_contacts(crm, text: str, dry_run: bool = False) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    headers = [name.strip() for name in reader.fieldnames or []]
    unknown = [h for h in headers if h not in COLUMNS and not h.startswith(FIELD_PREFIX)]
    if unknown:
        raise ImportFailed(f"Unknown column {unknown[0]!r}.")
    if not headers:
        raise ImportFailed("The file has no header row.")
    for header in headers:
        if header.startswith(FIELD_PREFIX):
            crm.fields.definition(header[len(FIELD_PREFIX) :])

    result = ImportResult()
    try:
        with crm.operation("import contacts"):
            for line, raw in enumerate(reader, start=2):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                try:
                    _apply(crm, row, result)
                except CrmError as exc:
                    result.skipped.append((line, str(exc)))
            if dry_run:
                raise _DryRun
    except _DryRun:
        pass
    return result


def _existing(crm, row: dict) -> str | None:
    contact_id = row.get("id", "")
    if contact_id:
        if not crm.store.has("contacts", contact_id):
            raise ImportFailed(f"No contact {contact_id!r}.")
        return contact_id
    for address in split_list(row.get("email", "")):
        matches = crm.dedupe.match_email(address)
        if matches:
            return matches[0]
    return None


def _apply(crm, row: dict, result: ImportResult) -> None:
    emails = split_list(row.get("email", ""))
    phones = split_list(row.get("phone", ""))
    tags = split_list(row.get("tags", ""))
    company_id = None
    if row.get("company"):
        company_id = crm.companies.find_or_create(row["company"]).id
    values = {
        name[len(FIELD_PREFIX) :]: value
        for name, value in row.items()
        if name.startswith(FIELD_PREFIX) and value
    }

    contact_id = _existing(crm, row)
    if contact_id is None:
        contact = crm.contacts.create(
            row.get("first_name", ""),
            row.get("last_name", ""),
            emails=emails,
            phones=phones,
            company_id=company_id,
            title=row.get("title", ""),
            owner=row.get("owner") or None,
            source=row.get("source", ""),
            tags=tags,
        )
        result.created.append(contact.id)
    else:
        contact = crm.contacts.get(contact_id)
        changes = {key: row[key] for key in PLAIN if row.get(key)}
        known = {normalize_email(a) for a in contact.emails}
        new_emails = [a for a in emails if normalize_email(a) not in known]
        if new_emails:
            changes["emails"] = contact.emails + new_emails
        numbers = {phone_digits(p) for p in contact.phones}
        new_phones = [p for p in phones if phone_digits(p) not in numbers]
        if new_phones:
            changes["phones"] = contact.phones + new_phones
        if company_id is not None:
            changes["company_id"] = company_id
        contact = crm.contacts.update(contact.id, **changes)
        if tags:
            crm.tagging.tag(contact.id, *tags)
        if contact.id not in result.updated and contact.id not in result.created:
            result.updated.append(contact.id)
    for name, value in values.items():
        crm.fields.set(contact.id, name, value)

"""Contacts: the people the team talks to."""

from orbit import ids
from orbit.errors import InvalidValue, NotFound
from orbit.models import STATUSES, Company, Contact
from orbit.payloads import contact_payload
from orbit.services.base import Service
from orbit.text import clean_tags, is_email, normalize_email, phone_digits, unique

EDITABLE = ("first_name", "last_name", "emails", "phones", "company_id", "title", "owner", "source")


class ContactService(Service):
    def get(self, contact_id: str) -> Contact:
        row = self.store.get("contacts", contact_id)
        if row is None:
            raise NotFound("contact", contact_id)
        return Contact.from_row(row)

    def exists(self, contact_id: str) -> bool:
        return self.store.has("contacts", contact_id)

    def all(self, include_archived: bool = False) -> list[Contact]:
        contacts = [Contact.from_row(row) for row in self.store.rows("contacts")]
        return [c for c in contacts if include_archived or c.active]

    def company_of(self, contact: Contact) -> Company | None:
        if contact.company_id is None:
            return None
        row = self.store.get("companies", contact.company_id)
        return Company.from_row(row) if row else None

    def payload(self, contact: Contact) -> dict:
        return contact_payload(contact, self.company_of(contact))

    # -- changes ----------------------------------------------------------------------

    def create(
        self,
        first_name: str,
        last_name: str = "",
        *,
        emails=(),
        phones=(),
        company_id: str | None = None,
        title: str = "",
        owner: str | None = None,
        source: str = "",
        tags=(),
    ) -> Contact:
        first_name, last_name = first_name.strip(), last_name.strip()
        emails = self.clean_emails(emails)
        if not first_name and not emails:
            raise InvalidValue("A contact needs a first name or an email address.")
        self.check_company(company_id)
        now = self.clock()
        contact = Contact(
            id=ids.next_id(self.store, "contacts"),
            first_name=first_name,
            last_name=last_name,
            emails=emails,
            phones=self.clean_phones(phones),
            company_id=company_id,
            title=title.strip(),
            owner=self.settings.default_owner if owner is None else owner.strip(),
            source=source.strip(),
            tags=self.clean_tags(tags),
            created_at=now,
            updated_at=now,
        )
        self.store.put("contacts", contact.to_row())
        self.publish("contact.created", {"contact": self.payload(contact)}, [contact.id])
        return contact

    def update(self, contact_id: str, **changes) -> Contact:
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise InvalidValue(f"Can't change {', '.join(sorted(unknown))} this way.")
        contact = self.get(contact_id)
        if "emails" in changes:
            changes["emails"] = self.clean_emails(changes["emails"])
        if "phones" in changes:
            changes["phones"] = self.clean_phones(changes["phones"])
        if "company_id" in changes:
            self.check_company(changes["company_id"])
        for key in ("first_name", "last_name", "title", "owner", "source"):
            if key in changes:
                changes[key] = (changes[key] or "").strip()
        changed = [key for key, value in changes.items() if getattr(contact, key) != value]
        for key in changed:
            setattr(contact, key, changes[key])
        if not contact.first_name and not contact.emails:
            raise InvalidValue("A contact needs a first name or an email address.")
        if changed:
            self.save(contact, changed)
        return contact

    def set_status(self, contact_id: str, status: str) -> Contact:
        if status not in STATUSES:
            raise InvalidValue(f"Status must be one of {', '.join(STATUSES)}.")
        contact = self.get(contact_id)
        if contact.status != status:
            contact.status = status
            self.save(contact, ["status"])
        return contact

    def save(self, contact: Contact, changed: list[str]) -> None:
        """Store a changed contact and tell everyone what changed."""
        contact.updated_at = self.clock()
        self.store.put("contacts", contact.to_row())
        payload = {"contact": self.payload(contact), "changed": sorted(changed)}
        self.publish("contact.updated", payload, [contact.id])

    def touch_contacted(self, contact_id: str, at: str) -> None:
        row = self.store.get("contacts", contact_id)
        if row is None:
            return
        if row.get("last_contacted_at") is None or row["last_contacted_at"] < at:
            row["last_contacted_at"] = at
            self.store.put("contacts", row)

    # -- checks -----------------------------------------------------------------------

    def clean_emails(self, emails) -> list[str]:
        cleaned = []
        for address in emails:
            address = address.strip()
            if not address:
                continue
            if not is_email(address):
                raise InvalidValue(f"{address!r} is not an email address.")
            cleaned.append(address)
        return unique(cleaned, key=normalize_email)

    def clean_phones(self, phones) -> list[str]:
        cleaned = []
        for number in phones:
            number = " ".join(number.split())
            if not number:
                continue
            if len(phone_digits(number)) < 5:
                raise InvalidValue(f"{number!r} is not a phone number.")
            cleaned.append(number)
        return unique(cleaned, key=phone_digits)

    def clean_tags(self, tags) -> list[str]:
        try:
            return clean_tags(tags)
        except ValueError as exc:
            raise InvalidValue(str(exc)) from None

    def check_company(self, company_id: str | None) -> None:
        if company_id is not None and not self.store.has("companies", company_id):
            raise NotFound("company", company_id)

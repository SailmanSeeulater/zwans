"""Tags on contacts ("vip", "newsletter", "trade-show-2026")."""

from orbit.errors import InvalidValue
from orbit.index.tags import TagIndex
from orbit.models import Contact
from orbit.services.base import Service
from orbit.services.contacts import ContactService
from orbit.text import normalize_tag


class TagService(Service):
    def __init__(self, *args, contacts: ContactService, index: TagIndex) -> None:
        super().__init__(*args)
        self.contacts = contacts
        self.index = index

    def tag(self, contact_id: str, *tags: str) -> Contact:
        contact = self.contacts.get(contact_id)
        new = sorted(set(contact.tags) | set(self.contacts.clean_tags(tags)))
        if new != contact.tags:
            contact.tags = new
            self.contacts.save(contact, ["tags"])
        return contact

    def untag(self, contact_id: str, *tags: str) -> Contact:
        contact = self.contacts.get(contact_id)
        drop = {normalize_tag(tag) for tag in tags}
        new = [tag for tag in contact.tags if tag not in drop]
        if new != contact.tags:
            contact.tags = new
            self.contacts.save(contact, ["tags"])
        return contact

    def tagged(self, tag: str) -> list[Contact]:
        return [
            self.contacts.get(contact_id) for contact_id in self.index.members(normalize_tag(tag))
        ]

    def counts(self) -> dict[str, int]:
        return self.index.counts()

    def rename(self, old: str, new: str) -> int:
        old, new = normalize_tag(old), normalize_tag(new)
        if old == new:
            raise InvalidValue("That is the same tag.")
        moved = 0
        for contact_id in self.index.members(old):
            contact = self.contacts.get(contact_id)
            contact.tags = sorted(
                (set(contact.tags) - {old}) | set(self.contacts.clean_tags([new]))
            )
            self.contacts.save(contact, ["tags"])
            moved += 1
        return moved

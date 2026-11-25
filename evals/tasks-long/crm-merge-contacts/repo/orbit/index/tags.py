"""Which contacts carry which tag, kept in memory for quick lookups and counts."""

from collections import defaultdict

from orbit import ids
from orbit.events import Bus, Event
from orbit.store import Store


class TagIndex:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._members: dict[str, set[str]] = defaultdict(set)
        self._tags: dict[str, set[str]] = {}

    def attach(self, bus: Bus) -> None:
        bus.subscribe("contact.created", self._on_contact)
        bus.subscribe("contact.updated", self._on_contact)

    def _on_contact(self, event: Event) -> None:
        contact = event.payload["contact"]
        self.set(contact["id"], contact["tags"])

    def rebuild(self) -> None:
        self._members.clear()
        self._tags.clear()
        for row in self.store.rows("contacts"):
            self.set(row["id"], row.get("tags", []))

    def set(self, contact_id: str, tags) -> None:
        self.remove(contact_id)
        self._tags[contact_id] = set(tags)
        for tag in tags:
            self._members[tag].add(contact_id)

    def remove(self, contact_id: str) -> None:
        for tag in self._tags.pop(contact_id, set()):
            self._members[tag].discard(contact_id)
            if not self._members[tag]:
                del self._members[tag]

    def members(self, tag: str) -> list[str]:
        return sorted(self._members.get(tag, set()), key=ids.sort_key)

    def counts(self) -> dict[str, int]:
        return {tag: len(members) for tag, members in sorted(self._members.items())}

    def snapshot(self) -> dict[str, list[str]]:
        return {tag: self.members(tag) for tag in sorted(self._members)}

"""Duplicate detection.

Two active contacts look like the same person when they share an email address (ignoring
case), a phone number (the last digits, so "+44 20 7946 0000" and "020 7946 0000" match),
or a full name (first and last, ignoring case and accents). The index maps each of those
keys to the contacts that have it; it is built when a CRM is opened and kept up to date
from the event bus. The importer uses it to find a contact by email address.
"""

from collections import defaultdict

from orbit import ids
from orbit.events import Bus, Event
from orbit.store import Store
from orbit.text import fold, normalize_email, phone_digits

MIN_PHONE_DIGITS = 7


class DedupeIndex:
    def __init__(self, store: Store, phone_digits_to_match: int = 9) -> None:
        self.store = store
        self.phone_length = phone_digits_to_match
        self._owners: dict[str, set[str]] = defaultdict(set)
        self._keys: dict[str, set[str]] = {}

    def attach(self, bus: Bus) -> None:
        bus.subscribe("contact.created", self._on_contact)
        bus.subscribe("contact.updated", self._on_contact)

    def _on_contact(self, event: Event) -> None:
        self.index(event.payload["contact"]["id"])

    def keys_for(self, row: dict) -> set[str]:
        keys = {"email:" + normalize_email(address) for address in row.get("emails", [])}
        for number in row.get("phones", []):
            digits = phone_digits(number)
            if len(digits) >= MIN_PHONE_DIGITS:
                keys.add("phone:" + digits[-self.phone_length :])
        first, last = fold(row.get("first_name", "")), fold(row.get("last_name", ""))
        if first and last:
            keys.add(f"name:{first} {last}")
        return keys

    def rebuild(self) -> None:
        self._owners.clear()
        self._keys.clear()
        for row in self.store.rows("contacts"):
            self._set(row)

    def index(self, contact_id: str) -> None:
        row = self.store.get("contacts", contact_id)
        if row is None:
            self.remove(contact_id)
        else:
            self._set(row)

    def _set(self, row: dict) -> None:
        self.remove(row["id"])
        if row.get("status", "active") != "active":
            return
        keys = self.keys_for(row)
        self._keys[row["id"]] = keys
        for key in keys:
            self._owners[key].add(row["id"])

    def remove(self, contact_id: str) -> None:
        for key in self._keys.pop(contact_id, set()):
            self._owners[key].discard(contact_id)
            if not self._owners[key]:
                del self._owners[key]

    # -- questions --------------------------------------------------------------------

    def match_email(self, address: str) -> list[str]:
        owners = self._owners.get("email:" + normalize_email(address), set())
        return sorted(owners, key=ids.sort_key)

    def duplicates_of(self, contact_id: str) -> list[str]:
        others: set[str] = set()
        for key in self._keys.get(contact_id, set()):
            others |= self._owners[key]
        others.discard(contact_id)
        return sorted(others, key=ids.sort_key)

    def reasons(self, first: str, second: str) -> list[str]:
        shared = self._keys.get(first, set()) & self._keys.get(second, set())
        return sorted(key.split(":", 1)[0] for key in shared)

    def groups(self) -> list[tuple[str, ...]]:
        """Contacts that look like one person, each group sorted, groups in id order."""
        parent: dict[str, str] = {}

        def find(item: str) -> str:
            while parent.setdefault(item, item) != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        for owners in self._owners.values():
            first, *rest = sorted(owners)
            for other in rest:
                parent[find(other)] = find(first)
        groups: dict[str, list[str]] = defaultdict(list)
        for contact_id in self._keys:
            groups[find(contact_id)].append(contact_id)
        found = [
            tuple(sorted(members, key=ids.sort_key))
            for members in groups.values()
            if len(members) > 1
        ]
        return sorted(found, key=lambda group: ids.sort_key(group[0]))

    def keys(self) -> dict[str, list[str]]:
        return {key: sorted(found) for key, found in self._keys.items()}

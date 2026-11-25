"""Full-text search over contacts.

A contact's document is everything a person might remember about them: their name,
addresses, phone numbers, company, title, tags, custom field values, the text of their
notes and the subjects of emails logged with them. The index lives in memory: it is
built when a CRM is opened and kept up to date from the event bus.

A query matches contacts that have every word of it; the last word may be the start of
a word ("lov" finds "Lovelace").
"""

from collections import defaultdict

from orbit import ids
from orbit.events import Bus, Event
from orbit.index.tokens import phone_tokens, tokens
from orbit.store import Store

PREFIX_MIN = 2


class SearchIndex:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._docs: dict[str, set[str]] = {}
        self._postings: dict[str, set[str]] = defaultdict(set)

    def attach(self, bus: Bus) -> None:
        bus.subscribe("contact.created", self._on_contact)
        bus.subscribe("contact.updated", self._on_contact)
        bus.subscribe("note.added", self._on_activity)
        bus.subscribe("email.logged", self._on_activity)
        bus.subscribe("company.updated", self._on_company)

    def _on_contact(self, event: Event) -> None:
        self.index_contact(event.payload["contact"]["id"])

    def _on_activity(self, event: Event) -> None:
        self.index_contact(event.payload["contact_id"])

    def _on_company(self, event: Event) -> None:
        for row in self.store.find("contacts", company_id=event.payload["id"]):
            self.index_contact(row["id"])

    # -- building ---------------------------------------------------------------------

    def rebuild(self) -> None:
        self._docs.clear()
        self._postings.clear()
        texts: dict[str, list[str]] = defaultdict(list)
        for note in self.store.rows("notes"):
            texts[note["contact_id"]].append(note["body"])
        for email in self.store.rows("emails"):
            texts[email["contact_id"]].append(email["subject"])
        for row in self.store.rows("contacts"):
            self._set(row["id"], self._document(row, texts.get(row["id"], [])))

    def index_contact(self, contact_id: str) -> None:
        row = self.store.get("contacts", contact_id)
        if row is None:
            self.remove(contact_id)
            return
        texts = [note["body"] for note in self.store.find("notes", contact_id=contact_id)]
        texts += [email["subject"] for email in self.store.find("emails", contact_id=contact_id)]
        self._set(contact_id, self._document(row, texts))

    def remove(self, contact_id: str) -> None:
        for token in self._docs.pop(contact_id, set()):
            self._postings[token].discard(contact_id)
            if not self._postings[token]:
                del self._postings[token]

    def _set(self, contact_id: str, document: set[str]) -> None:
        self.remove(contact_id)
        self._docs[contact_id] = document
        for token in document:
            self._postings[token].add(contact_id)

    def _document(self, row: dict, texts: list[str]) -> set[str]:
        words: list[str] = []
        words += tokens(row.get("first_name", ""))
        words += tokens(row.get("last_name", ""))
        for address in row.get("emails", []):
            words += tokens(address)
        for number in row.get("phones", []):
            words += phone_tokens(number)
        words += tokens(row.get("title", ""))
        words += row.get("tags", [])
        for value in row.get("fields", {}).values():
            words += tokens(" ".join(value) if isinstance(value, list) else str(value))
        if row.get("company_id"):
            company = self.store.get("companies", row["company_id"])
            if company:
                words += tokens(company["name"])
        for text in texts:
            words += tokens(text)
        return set(words)

    # -- querying ---------------------------------------------------------------------

    def query(self, text: str) -> list[str]:
        terms = tokens(text)
        if not terms:
            return []
        matches: set[str] | None = None
        for position, term in enumerate(terms):
            found = set(self._postings.get(term, set()))
            if position == len(terms) - 1 and len(term) >= PREFIX_MIN:
                for token, owners in self._postings.items():
                    if token.startswith(term):
                        found |= owners
            matches = found if matches is None else matches & found
            if not matches:
                return []
        return sorted(matches or (), key=ids.sort_key)

    def documents(self) -> dict[str, list[str]]:
        return {key: sorted(doc) for key, doc in self._docs.items()}

    def __len__(self) -> int:
        return len(self._docs)

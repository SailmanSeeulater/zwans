"""A small reference model of the parts of orbit the merge rules touch, written straight
from the README: contacts (name, emails, tags, two custom fields), notes, deals (contacts
and stage history), merges, and undo."""

import copy
from collections import defaultdict
from dataclasses import dataclass, field

from orbit.text import fold

STAGES = ("lead", "qualified", "proposal", "negotiation", "won", "lost")


def unique_by(items, key):
    seen, kept = set(), []
    for item in items:
        if key(item) not in seen:
            seen.add(key(item))
            kept.append(item)
    return kept


@dataclass
class State:
    contacts: dict = field(default_factory=dict)  # id -> {first, last, emails, tags, fields}
    notes: dict = field(default_factory=dict)  # note id -> (contact id, word)
    deals: dict = field(default_factory=dict)  # deal id -> {contacts, stage, history}
    merged: dict = field(default_factory=dict)  # merged id -> into


class Model:
    def __init__(self) -> None:
        self.state = State()
        self.undo_stack: list[State] = []

    # -- helpers --------------------------------------------------------------------

    def resolve(self, contact_id: str) -> str:
        while contact_id in self.state.merged:
            contact_id = self.state.merged[contact_id]
        return contact_id

    def exists(self, contact_id: str) -> bool:
        return self.resolve(contact_id) in self.state.contacts

    def change(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.state))

    def undo(self) -> None:
        self.state = self.undo_stack.pop()

    def name(self, contact_id: str) -> str:
        c = self.state.contacts[contact_id]
        return " ".join(p for p in (c["first"], c["last"]) if p)

    # -- commands -------------------------------------------------------------------

    def add_contact(self, contact_id, first, last, emails, tags, fields) -> None:
        self.change()
        self.state.contacts[contact_id] = {
            "first": first,
            "last": last,
            "emails": unique_by(emails, str.lower),
            "tags": sorted(set(tags)),
            "fields": dict(fields),
        }

    def add_note(self, note_id, contact_id, word) -> None:
        self.change()
        self.state.notes[note_id] = (self.resolve(contact_id), word)

    def add_deal(self, deal_id, contact_ids) -> None:
        self.change()
        contacts = unique_by([self.resolve(c) for c in contact_ids], lambda c: c)
        self.state.deals[deal_id] = {"contacts": contacts, "stage": "lead", "history": [None]}

    def move_deal(self, deal_id, stage, contact_id) -> None:
        self.change()
        deal = self.state.deals[deal_id]
        deal["stage"] = stage
        deal["history"].append(self.resolve(contact_id) if contact_id else None)

    def would_tag(self, contact_id, tag) -> bool:
        return tag not in self.state.contacts[self.resolve(contact_id)]["tags"]

    def tag(self, contact_id, tag) -> None:
        self.change()
        contact = self.state.contacts[self.resolve(contact_id)]
        contact["tags"] = sorted(set(contact["tags"]) | {tag})

    def would_set(self, contact_id, name, value) -> bool:
        return self.state.contacts[self.resolve(contact_id)]["fields"].get(name) != value

    def set_field(self, contact_id, name, value) -> None:
        self.change()
        self.state.contacts[self.resolve(contact_id)]["fields"][name] = value

    def merge(self, keep_id, other_id) -> None:
        keep_id, other_id = self.resolve(keep_id), self.resolve(other_id)
        self.change()
        a = self.state.contacts[keep_id]
        b = self.state.contacts.pop(other_id)
        a["emails"] = unique_by(a["emails"] + b["emails"], str.lower)
        a["tags"] = sorted(set(a["tags"]) | set(b["tags"]))
        for name, value in b["fields"].items():
            mine = a["fields"].get(name)
            if name == "likes" and mine:
                a["fields"][name] = mine + [v for v in value if v not in mine]
            elif not mine:
                a["fields"][name] = value
        for note_id, (owner, word) in self.state.notes.items():
            if owner == other_id:
                self.state.notes[note_id] = (keep_id, word)
        for deal in self.state.deals.values():
            if other_id in deal["contacts"]:
                if keep_id in deal["contacts"]:
                    deal["contacts"].remove(other_id)
                else:
                    deal["contacts"][deal["contacts"].index(other_id)] = keep_id
            deal["history"] = [keep_id if c == other_id else c for c in deal["history"]]
        self.state.merged[other_id] = keep_id

    # -- expectations ---------------------------------------------------------------

    def notes_of(self, contact_id: str) -> list[str]:
        return sorted(nid for nid, (owner, _) in self.state.notes.items() if owner == contact_id)

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for contact in self.state.contacts.values():
            for tag in contact["tags"]:
                counts[tag] += 1
        return dict(sorted(counts.items()))

    def duplicate_groups(self, sort_key) -> list[tuple[str, ...]]:
        owners: dict[str, set[str]] = defaultdict(set)
        for cid, c in self.state.contacts.items():
            for email in c["emails"]:
                owners["email:" + email.lower()].add(cid)
            if c["first"] and c["last"]:
                owners[f"name:{fold(c['first'])} {fold(c['last'])}"].add(cid)
        parent: dict[str, str] = {cid: cid for cid in self.state.contacts}

        def find(x):
            while parent[x] != x:
                x = parent[x]
            return x

        for group in owners.values():
            first, *rest = sorted(group)
            for other in rest:
                parent[find(other)] = find(first)
        groups: dict[str, list[str]] = defaultdict(list)
        for cid in self.state.contacts:
            groups[find(cid)].append(cid)
        found = [tuple(sorted(g, key=sort_key)) for g in groups.values() if len(g) > 1]
        return sorted(found, key=lambda g: sort_key(g[0]))

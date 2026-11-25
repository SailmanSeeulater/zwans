"""Merging one contact (B) into another (A). The rules are in the README."""

from orbit.clock import later
from orbit.errors import CrmError
from orbit.models import Contact, Deal, FieldDef
from orbit.payloads import deal_payload
from orbit.services.base import Service
from orbit.services.contacts import ContactService
from orbit.services.fields import is_empty
from orbit.services.timeline import TimelineService
from orbit.text import normalize_email, phone_digits, unique


class MergeService(Service):
    def __init__(self, *args, contacts: ContactService, timeline: TimelineService) -> None:
        super().__init__(*args)
        self.contacts = contacts
        self.timeline = timeline

    def merge(self, keep_id: str, other_id: str) -> Contact:
        keep = self.contacts.get(keep_id)
        other = self.contacts.get(other_id)
        if keep.id == other.id:
            raise CrmError(f"{keep_id} and {other_id} are the same contact.")
        now = self.clock()

        keep.emails = unique(keep.emails + other.emails, key=normalize_email)
        keep.phones = unique(keep.phones + other.phones, key=phone_digits)
        keep.tags = sorted(set(keep.tags) | set(other.tags))
        keep.fields = self._merged_fields(keep.fields, other.fields)
        keep.company_id = keep.company_id or other.company_id
        keep.last_contacted_at = later(keep.last_contacted_at, other.last_contacted_at)
        keep.updated_at = now
        self.store.put("contacts", keep.to_row())

        for table in ("notes", "tasks", "emails", "subscriptions"):
            for row in self.store.find(table, contact_id=other.id):
                row["contact_id"] = keep.id
                self.store.put(table, row)

        changed_deals = []
        for row in self.store.rows("deals"):
            changed = False
            if other.id in row["contact_ids"]:
                if keep.id in row["contact_ids"]:
                    row["contact_ids"] = [cid for cid in row["contact_ids"] if cid != other.id]
                else:
                    row["contact_ids"] = [
                        keep.id if cid == other.id else cid for cid in row["contact_ids"]
                    ]
                changed = True
            for change in row.get("stage_history", []):
                if change.get("contact_id") == other.id:
                    change["contact_id"] = keep.id
                    changed = True
            if changed:
                row["updated_at"] = now
                self.store.put("deals", row)
                changed_deals.append(row)

        for row in self.store.find("companies", primary_contact_id=other.id):
            row["primary_contact_id"] = keep.id
            self.store.put("companies", row)

        for row in self.store.find("timeline", contact_id=other.id):
            row["contact_id"] = keep.id
            row["contact_name"] = keep.name
            self.store.put("timeline", row)

        self.store.delete("contacts", other.id)
        self.store.put("merged", {"id": other.id, "into": keep.id, "at": now})
        self.timeline.add(keep.id, "merged", f"Merged {other.name} ({other.id})", other.id)

        for row in changed_deals:
            deal = deal_payload(Deal.from_row(row))
            self.publish("deal.updated", deal, deal["contact_ids"])
        payload = {"contact": self.contacts.payload(keep), "merged_id": other.id}
        self.publish("contact.merged", payload, [keep.id])
        return keep

    def _merged_fields(self, mine: dict, theirs: dict) -> dict:
        merged = dict(mine)
        for name, value in theirs.items():
            definition = self.store.get("fields", name)
            kind = FieldDef.from_row(definition).type if definition else "text"
            if kind == "multi" and not is_empty(merged.get(name)):
                merged[name] = unique(list(merged[name]) + list(value))
            elif is_empty(merged.get(name)):
                merged[name] = value
        return merged

"""Activity per contact: how much the team has been in touch, and with whom the money is."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from orbit.models import OPEN_STAGES
from orbit.reports.tables import money, render
from orbit.text import display_name


@dataclass
class ActivityRow:
    contact_id: str
    name: str
    notes: int = 0
    emails: int = 0
    open_tasks: int = 0
    deals: int = 0
    open_value: int = 0
    last_activity: str | None = None


def _names(crm) -> dict[str, str]:
    return {
        row["id"]: display_name(row["first_name"], row.get("last_name", "")) or row["id"]
        for row in crm.store.rows("contacts")
    }


def activity_report(crm, since: str | None = None) -> list[ActivityRow]:
    """One row per contact with any activity (since `since`, if given), busiest first."""
    names = _names(crm)
    rows: dict[str, ActivityRow] = {}

    def row_for(contact_id: str) -> ActivityRow:
        if contact_id not in rows:
            rows[contact_id] = ActivityRow(contact_id, names.get(contact_id, contact_id))
        return rows[contact_id]

    def seen(row: ActivityRow, at: str | None) -> None:
        if at and (row.last_activity is None or at > row.last_activity):
            row.last_activity = at

    for note in crm.store.rows("notes"):
        if since and note["at"] < since:
            continue
        row = row_for(note["contact_id"])
        row.notes += 1
        seen(row, note["at"])
    for email in crm.store.rows("emails"):
        if since and email["at"] < since:
            continue
        row = row_for(email["contact_id"])
        row.emails += 1
        seen(row, email["at"])
    for task in crm.store.rows("tasks"):
        if not task.get("done"):
            row_for(task["contact_id"]).open_tasks += 1
    for deal in crm.store.rows("deals"):
        for contact_id in deal["contact_ids"]:
            row = row_for(contact_id)
            row.deals += 1
            if deal["stage"] in OPEN_STAGES:
                row.open_value += deal.get("amount", 0)
    return sorted(
        rows.values(),
        key=lambda r: (-(r.notes + r.emails), -r.open_value, r.name, r.contact_id),
    )


def top_contacts(crm, limit: int = 10) -> list[tuple[str, str, int]]:
    """(contact id, name, open deal value) for the contacts with the most money in play."""
    names = _names(crm)
    value: dict[str, int] = defaultdict(int)
    for deal in crm.store.rows("deals"):
        if deal["stage"] not in OPEN_STAGES:
            continue
        for contact_id in deal["contact_ids"]:
            value[contact_id] += deal.get("amount", 0)
    ranked = sorted(value.items(), key=lambda item: (-item[1], names.get(item[0], item[0])))
    return [(cid, names.get(cid, cid), amount) for cid, amount in ranked[:limit]]


def stage_moves_by_contact(crm) -> dict[str, int]:
    """How many deal moves came out of talking to each contact."""
    moves: Counter = Counter()
    for deal in crm.store.rows("deals"):
        for change in deal.get("stage_history", []):
            if change.get("contact_id"):
                moves[change["contact_id"]] += 1
    return dict(sorted(moves.items(), key=lambda item: (-item[1], item[0])))


def render_activity(rows: list[ActivityRow]) -> str:
    return render(
        ["id", "name", "notes", "emails", "open tasks", "deals", "open value", "last activity"],
        [
            [
                r.contact_id,
                r.name,
                r.notes,
                r.emails,
                r.open_tasks,
                r.deals,
                money(r.open_value),
                r.last_activity or "-",
            ]
            for r in rows
        ],
        numeric={2, 3, 4, 5, 6},
    )


def render_top(rows: list[tuple[str, str, int]]) -> str:
    return render(
        ["id", "name", "open value"],
        [[cid, name, money(amount)] for cid, name, amount in rows],
        numeric={2},
    )

"""Task reminders: open tasks due today or earlier, grouped by owner, for the morning email."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from orbit.models import Contact


@dataclass
class Reminder:
    owner: str
    task_id: str
    title: str
    due: str
    days_late: int
    contact_id: str
    contact_name: str


def due_reminders(crm, today: date) -> list[Reminder]:
    names = {row["id"]: Contact.from_row(row).name for row in crm.store.rows("contacts")}
    reminders = []
    for task in crm.tasks(open_only=True):
        if task.due is None:
            continue
        due = date.fromisoformat(task.due)
        if due > today:
            continue
        reminders.append(
            Reminder(
                owner=task.owner,
                task_id=task.id,
                title=task.title,
                due=task.due,
                days_late=(today - due).days,
                contact_id=task.contact_id,
                contact_name=names.get(task.contact_id, task.contact_id),
            )
        )
    return sorted(reminders, key=lambda r: (r.owner, r.due, r.task_id))


def digest(reminders: list[Reminder]) -> str:
    if not reminders:
        return "Nothing due."
    by_owner: dict[str, list[Reminder]] = defaultdict(list)
    for reminder in reminders:
        by_owner[reminder.owner or "(nobody)"].append(reminder)
    parts = []
    for owner, items in sorted(by_owner.items()):
        lines = [f"{owner}:"]
        for r in items:
            late = f", {r.days_late} days late" if r.days_late else ", due today"
            lines.append(f"  {r.task_id}  {r.title} ({r.contact_name}{late})")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)

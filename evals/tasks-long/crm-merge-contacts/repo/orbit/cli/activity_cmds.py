"""orbit note, task ..., email, timeline, reminders."""

from datetime import date

from orbit.cli.output import emit_json, say
from orbit.jobs.reminders import digest, due_reminders


def register(commands) -> None:
    note = commands.add_parser("note", help="add a note to a contact")
    note.add_argument("id")
    note.add_argument("text")
    note.add_argument("--author", default="")
    note.set_defaults(handler=add_note)

    task = commands.add_parser("task", help="tasks")
    sub = task.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    add.add_argument("id")
    add.add_argument("title")
    add.add_argument("--due")
    add.add_argument("--owner", default="")
    add.set_defaults(handler=add_task)
    done = sub.add_parser("done")
    done.add_argument("task")
    done.set_defaults(handler=complete_task)
    listing = sub.add_parser("list")
    listing.add_argument("--contact")
    listing.add_argument("--open", action="store_true")
    listing.set_defaults(handler=list_tasks)

    email = commands.add_parser("email", help="log an email with a contact")
    email.add_argument("id")
    email.add_argument("subject")
    email.add_argument("--in", dest="incoming", action="store_true", help="they wrote to us")
    email.add_argument("--address")
    email.set_defaults(handler=log_email)

    timeline = commands.add_parser("timeline", help="what happened with a contact")
    timeline.add_argument("id")
    timeline.add_argument("--limit", type=int)
    timeline.set_defaults(handler=show_timeline)

    reminders = commands.add_parser("reminders", help="open tasks that are due")
    reminders.add_argument("--today", type=date.fromisoformat)
    reminders.set_defaults(handler=show_reminders)


def add_note(crm, args) -> bool:
    note = crm.add_note(args.id, args.text, args.author)
    say(f"Added {note.id} to {note.contact_id}")
    return True


def add_task(crm, args) -> bool:
    task = crm.add_task(args.id, args.title, args.due, args.owner)
    say(f"Added {task.id} {task.title}")
    return True


def complete_task(crm, args) -> bool:
    task = crm.complete_task(args.task)
    say(f"Done {task.id} {task.title}")
    return True


def list_tasks(crm, args) -> bool:
    tasks = crm.tasks(args.contact, args.open)
    for task in tasks:
        mark = "x" if task.done else " "
        due = f"  due {task.due}" if task.due else ""
        say(f"[{mark}] {task.id:<5} {task.contact_id:<6} {task.title}{due}")
    return False


def log_email(crm, args) -> bool:
    email = crm.log_email(args.id, args.subject, "in" if args.incoming else "out", args.address)
    say(f"Logged {email.id} with {email.contact_id}")
    return True


def show_timeline(crm, args) -> bool:
    entries = crm.timeline(args.id, args.limit)
    if args.json:
        emit_json([entry.to_row() for entry in entries])
        return False
    for entry in entries:
        say(f"{entry.at}  {entry.contact_name:<24} {entry.kind:<9} {entry.summary}")
    if not entries:
        say("Nothing yet.")
    return False


def show_reminders(crm, args) -> bool:
    today = args.today or date.fromisoformat(crm.clock()[:10])
    say(digest(due_reminders(crm, today)))
    return False

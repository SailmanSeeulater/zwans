"""The command line: `python -m clinicbook --help`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from . import formatting
from .clinic import ClinicBook
from .errors import ClinicError
from .recurrence import Recurrence
from .reports import noshows
from .timeutil import instant, parse_date, parse_datetime, parse_instant

DEFAULT_DB = "clinicbook.json"


def _when(text: str) -> datetime:
    try:
        return parse_datetime(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _instant(text: str) -> datetime:
    try:
        return parse_instant(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _day(text: str):  # noqa: ANN202 - argparse type
    try:
        return parse_date(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _hours(pairs: list[str] | None) -> dict[str, str] | None:
    if not pairs:
        return None
    spec = {}
    for pair in pairs:
        day, sep, value = pair.partition("=")
        if not sep:
            raise ClinicError(f"--hours takes DAY=HH:MM-HH:MM, not {pair!r}")
        spec[day.strip().lower()] = value
    return spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clinicbook", description="Clinic appointment book.")
    parser.add_argument("--db", default=os.environ.get("CLINICBOOK_DB", DEFAULT_DB))
    parser.add_argument("--now", type=_instant, default=None,
                        help="pretend it is this time (also CLINICBOOK_NOW)")
    sub = parser.add_subparsers(dest="command", required=True)

    clinic = sub.add_parser("clinic").add_subparsers(dest="action", required=True)
    p = clinic.add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--zone", required=True)
    p.add_argument("--hours", action="append", metavar="DAY=HH:MM-HH:MM")
    p.add_argument("--phone", default="")
    p.add_argument("--address", default="")
    clinic.add_parser("list")
    p = clinic.add_parser("close")
    p.add_argument("id")
    p.add_argument("day", type=_day)
    p.add_argument("--reason", default="closed")

    p = sub.add_parser("room").add_subparsers(dest="action", required=True).add_parser("add")
    p.add_argument("clinic")
    p.add_argument("id")
    p.add_argument("name", nargs="?", default="")

    p = sub.add_parser("clinician").add_subparsers(dest="action", required=True).add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--clinic", action="append", required=True)
    p.add_argument("--specialty", default="")

    patient = sub.add_parser("patient").add_subparsers(dest="action", required=True)
    p = patient.add_parser("add")
    p.add_argument("name")
    p.add_argument("--phone", default="")
    p.add_argument("--email", default="")
    p = patient.add_parser("find")
    p.add_argument("query")

    for name in ("book", "series"):
        p = sub.add_parser(name)
        p.add_argument("--clinic", required=True)
        p.add_argument("--clinician", required=True)
        p.add_argument("--room", required=True)
        p.add_argument("--patient", required=True)
        p.add_argument("--at", type=_when, required=True, help="the clinic's local time")
        p.add_argument("--minutes", type=int, required=True)
        p.add_argument("--kind", default="consult")
        if name == "book":
            p.add_argument("--notes", default="")
        else:
            p.add_argument("--every", required=True, help="daily, weekdays, weekly, ...")
            p.add_argument("--count", type=int)
            p.add_argument("--until", type=_day)

    p = sub.add_parser("move")
    p.add_argument("id")
    p.add_argument("--at", type=_when, required=True)
    p.add_argument("--minutes", type=int)
    p.add_argument("--room")
    p = sub.add_parser("cancel")
    p.add_argument("id")
    p.add_argument("--reason", default="")
    p = sub.add_parser("done")
    p.add_argument("id")
    p = sub.add_parser("show")
    p.add_argument("id")

    p = sub.add_parser("agenda")
    p.add_argument("clinic")
    p.add_argument("day", type=_day, nargs="?")
    p = sub.add_parser("slots")
    p.add_argument("clinic")
    p.add_argument("day", type=_day)
    p.add_argument("--minutes", type=int, required=True)
    p.add_argument("--clinician")
    p = sub.add_parser("next")
    p.add_argument("clinic")
    p.add_argument("--minutes", type=int, required=True)
    p.add_argument("--clinician")
    p.add_argument("--after", type=_when)

    waitlist = sub.add_parser("waitlist").add_subparsers(dest="action", required=True)
    p = waitlist.add_parser("add")
    p.add_argument("--patient", required=True)
    p.add_argument("--clinic", required=True)
    p.add_argument("--minutes", type=int, required=True)
    p.add_argument("--clinician")
    p.add_argument("--earliest", type=_when)
    p.add_argument("--latest", type=_when)
    p = waitlist.add_parser("list")
    p.add_argument("--clinic")

    sub.add_parser("jobs").add_subparsers(dest="action", required=True).add_parser("run")

    report = sub.add_parser("report").add_subparsers(dest="action", required=True)
    p = report.add_parser("utilisation")
    p.add_argument("clinic")
    p.add_argument("first", type=_day)
    p.add_argument("last", type=_day)
    p = report.add_parser("noshows")
    p.add_argument("--clinic")

    export = sub.add_parser("export").add_subparsers(dest="action", required=True)
    for name in ("ical", "csv"):
        p = export.add_parser(name)
        p.add_argument("--clinic")
        p.add_argument("--out", type=Path)
        if name == "ical":
            p.add_argument("--clinician")

    p = sub.add_parser("import")
    p.add_argument("file", type=Path)
    p = sub.add_parser("backup")
    p.add_argument("file", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("file", type=Path)
    p = sub.add_parser("history")
    p.add_argument("id")
    return parser


def _clock(args: argparse.Namespace):  # noqa: ANN202
    fixed = args.now
    if fixed is None and os.environ.get("CLINICBOOK_NOW"):
        fixed = parse_instant(os.environ["CLINICBOOK_NOW"])
    return (lambda: fixed) if fixed is not None else None


def _describe(book: ClinicBook, appt) -> str:  # noqa: ANN001
    clinic = book.repo.clinic(appt.clinic)
    clinician = book.repo.clinician(appt.clinician)
    return (
        f"{appt.id}: {formatting.when(appt.start)}-{formatting.hm(appt.end)}, {clinic.name}, "
        f"room {appt.room}, {clinician.name}"
    )


def _write(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8", newline="")
        print(f"wrote {out}")


def run(args: argparse.Namespace, book: ClinicBook) -> bool:
    """Carry out one command; returns whether the data changed."""
    cmd, action = args.command, getattr(args, "action", None)
    if cmd == "clinic" and action == "add":
        c = book.add_clinic(args.id, args.name, zone=args.zone, hours=_hours(args.hours),
                            phone=args.phone, address=args.address)
        print(f"Added {c.name} ({c.zone})")
        return True
    if cmd == "clinic" and action == "list":
        for c in sorted(book.store.clinics.values(), key=lambda c: c.id):
            print(f"{c.id:<12} {c.name:<28} {c.zone}")
        return False
    if cmd == "clinic" and action == "close":
        book.close_day(args.id, args.day, args.reason)
        print(f"{args.id} closed on {args.day.isoformat()}")
        return True
    if cmd == "room":
        room = book.add_room(args.clinic, args.id, args.name)
        print(f"Added room {room.id} at {room.clinic}")
        return True
    if cmd == "clinician":
        person = book.add_clinician(args.id, args.name, clinics=args.clinic,
                                    specialty=args.specialty)
        print(f"Added {person.name}")
        return True
    if cmd == "patient" and action == "add":
        patient = book.add_patient(args.name, phone=args.phone, email=args.email)
        print(f"Added {patient.name} as {patient.id}")
        return True
    if cmd == "patient" and action == "find":
        for patient in book.find_patients(args.query):
            print(f"{patient.id}  {patient.name}  {patient.phone or patient.email}")
        return False
    if cmd == "book":
        appt = book.book(clinic=args.clinic, clinician=args.clinician, room=args.room,
                         patient=args.patient, start=args.at, minutes=args.minutes,
                         kind=args.kind, notes=args.notes)
        print(f"Booked {_describe(book, appt)}")
        return True
    if cmd == "series":
        rule = Recurrence(args.every, count=args.count, until=args.until)
        result = book.book_series(clinic=args.clinic, clinician=args.clinician, room=args.room,
                                  patient=args.patient, start=args.at, minutes=args.minutes,
                                  kind=args.kind, rule=rule)
        print(f"Series {result.series.id}: {rule.describe()}")
        for appt in result.booked:
            print(f"  booked {_describe(book, appt)}")
        for when, why in result.skipped:
            print(f"  skipped {formatting.when(when)}: {why}")
        return True
    if cmd == "move":
        appt = book.reschedule(args.id, start=args.at, minutes=args.minutes, room=args.room)
        print(f"Moved {_describe(book, appt)}")
        return True
    if cmd == "cancel":
        appt = book.cancel(args.id, reason=args.reason)
        print(f"Cancelled {appt.id}")
        return True
    if cmd == "done":
        book.complete(args.id)
        print(f"Completed {args.id}")
        return True
    if cmd == "show":
        appt = book.appointment(args.id)
        print(_describe(book, appt))
        print(f"  patient: {book.repo.patient(appt.patient).name} ({appt.patient})")
        print(f"  status:  {appt.status}")
        for r in book.reminders(appt.id):
            state = f"sent {formatting.when(r.sent)}" if r.sent else "pending"
            print(f"  reminder {r.hours_before}h before: {formatting.when(r.due)} ({state})")
        return False
    if cmd == "agenda":
        tz = book.repo.clinic(args.clinic).tz
        day = args.day or instant(book.clock()).astimezone(tz).date()
        sys.stdout.write(book.agenda(args.clinic, day).render())
        return False
    if cmd == "slots":
        for slot in book.slots(args.clinic, args.day, args.minutes, clinician=args.clinician):
            print(f"{formatting.span(slot.start, slot.end)}  {slot.clinician}  {slot.room}")
        return False
    if cmd == "next":
        slot = book.next_free_slot(args.clinic, args.minutes, clinician=args.clinician,
                                   after=args.after)
        if slot is None:
            print("No free slot found.")
        else:
            print(f"{formatting.when(slot.start)}-{formatting.hm(slot.end)}  {slot.clinician}  "
                  f"{slot.room}")
        return False
    if cmd == "waitlist" and action == "add":
        entry = book.waitlist_add(patient=args.patient, clinic=args.clinic, minutes=args.minutes,
                                  clinician=args.clinician, earliest=args.earliest,
                                  latest=args.latest)
        print(f"Added {entry.id} to the waitlist")
        return True
    if cmd == "waitlist" and action == "list":
        for entry in book.waitlist(args.clinic):
            window = ""
            if entry.earliest:
                window += f" from {formatting.when(entry.earliest)}"
            if entry.latest:
                window += f" until {formatting.when(entry.latest)}"
            print(f"{entry.id}  {entry.patient}  {entry.clinic}  {entry.minutes} min{window}")
        return False
    if cmd == "jobs":
        for line in book.run_jobs().lines():
            print(line)
        return True
    if cmd == "report" and action == "utilisation":
        sys.stdout.write(book.utilisation(args.clinic, args.first, args.last).render())
        return False
    if cmd == "report" and action == "noshows":
        sys.stdout.write(noshows.render(book.no_shows(args.clinic)))
        return False
    if cmd == "export" and action == "ical":
        _write(book.export_ical(clinic=args.clinic, clinician=args.clinician), args.out)
        return False
    if cmd == "export" and action == "csv":
        _write(book.export_csv(clinic=args.clinic), args.out)
        return False
    if cmd == "import":
        result = book.import_csv(args.file)
        print(result.summary())
        for line, why in result.errors:
            print(f"  line {line}: {why}")
        return True
    if cmd == "backup":
        print(f"wrote {book.backup(args.file)}")
        return False
    if cmd == "restore":
        book.restore(args.file)
        print(f"restored {args.file}")
        return True
    if cmd == "history":
        for entry in book.history(args.id):
            print(f"{formatting.when(entry.at)}  {entry.action}")
        return False
    raise ClinicError(f"unknown command {cmd} {action or ''}".strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        book = ClinicBook.open(args.db, clock=_clock(args))
        if run(args, book):
            book.save()
    except ClinicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

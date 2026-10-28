"""Command line: python -m meetslot FOLDER --from DATE --to DATE --minutes N [options]."""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from meetslot.calfile import CalFileError, read_people
from meetslot.finder import find_slots
from meetslot.people import Person


def local(person: Person, instant: datetime) -> str:
    offset = person.utc_offset
    sign = "+" if offset >= timedelta(0) else "-"
    minutes = abs(int(offset.total_seconds())) // 60
    return f"{instant + offset:%a %H:%M} (UTC{sign}{minutes // 60:02d}:{minutes % 60:02d})"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meetslot", description="Find times when everyone can meet.")
    p.add_argument("folder", type=Path, help="folder of .cal files, one per person")
    p.add_argument("--from", dest="first", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="last", type=date.fromisoformat, required=True)
    p.add_argument("--minutes", type=int, required=True, help="length of the meeting")
    p.add_argument("--buffer", type=int, default=0, help="minutes kept free around meetings")
    p.add_argument("--step", type=int, default=15, help="minutes between possible starts")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--only", action="append", default=[], help="only invite these names")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        people = read_people(args.folder)
    except (OSError, CalFileError) as exc:
        print(f"meetslot: {exc}", file=sys.stderr)
        return 2
    if args.only:
        wanted = {name.lower() for name in args.only}
        people = [p for p in people if p.name.lower() in wanted or p.email.lower() in wanted]
    if not people:
        print("meetslot: nobody to invite", file=sys.stderr)
        return 2
    slots = find_slots(
        people,
        args.first,
        args.last,
        timedelta(minutes=args.minutes),
        buffer=timedelta(minutes=args.buffer),
        step=timedelta(minutes=args.step),
        limit=args.limit,
    )
    if not slots:
        print("No time works for everyone.")
        return 1
    for slot in slots:
        print(f"{slot:%Y-%m-%d %H:%M} UTC")
        for person in people:
            print(f"    {person.name:<20} {local(person, slot)}")
    return 0

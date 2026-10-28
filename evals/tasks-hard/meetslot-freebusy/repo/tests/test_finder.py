from datetime import date, datetime, timedelta
from pathlib import Path

from meetslot import Person, find_slots
from meetslot.calfile import read_person

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MONDAY = date(2025, 3, 3)


def at(hour: int, minute: int = 0, day: date = MONDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def test_a_free_day() -> None:
    ana = Person("Ana", "ana@example.com")
    slots = find_slots([ana], MONDAY, MONDAY, timedelta(hours=1), step=timedelta(hours=1))
    assert slots == [at(h) for h in range(9, 17)]


def test_busy_time_is_avoided() -> None:
    ana = Person("Ana", "ana@example.com", busy=[(at(10), at(11))])
    slots = find_slots([ana], MONDAY, MONDAY, timedelta(minutes=30), step=timedelta(minutes=30))
    assert at(10) not in slots
    assert at(10, 30) not in slots
    assert at(9, 30) in slots
    assert at(11) in slots


def test_everyone_must_be_free() -> None:
    ana = Person("Ana", "ana@example.com", busy=[(at(9), at(12))])
    sam = Person("Sam", "sam@example.com", busy=[(at(13), at(17))])
    slots = find_slots([ana, sam], MONDAY, MONDAY, timedelta(hours=1), step=timedelta(hours=1))
    assert slots == [at(12)]


def test_no_slot_overlaps_a_meeting() -> None:
    # Ana's quarterly review runs until 16:20, but she was offered a 16:15 slot.
    ana = read_person(EXAMPLES / "ana.cal")
    tuesday = MONDAY + timedelta(days=1)
    slots = find_slots([ana], tuesday, tuesday, timedelta(minutes=30))
    for slot in slots:
        for start, end in ana.busy:
            assert not (slot < end and start < slot + timedelta(minutes=30)), slot
    assert at(16, 30, tuesday) in slots

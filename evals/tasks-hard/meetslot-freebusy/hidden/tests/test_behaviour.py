import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from meetslot import IntervalSet, Person, find_slots, free_time
from meetslot.calfile import read_people

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MONDAY = date(2025, 3, 3)
HOUR = timedelta(hours=1)


def at(hour: int, minute: int = 0, day: date = MONDAY) -> datetime:
    return datetime(day.year, day.month, day.day) + timedelta(hours=hour, minutes=minute)


def t(hour: int, minute: int = 0) -> datetime:
    return at(hour, minute)


# -- IntervalSet ------------------------------------------------------------------------------


def test_touching_intervals_merge_in_either_order() -> None:
    a = IntervalSet()
    a.add(t(9), t(10))
    a.add(t(10), t(11))
    b = IntervalSet()
    b.add(t(10), t(11))
    b.add(t(9), t(10))
    assert list(a) == [(t(9), t(11))]
    assert list(b) == [(t(9), t(11))]


def test_adding_across_several_intervals_merges_them_all() -> None:
    s = IntervalSet([(t(9), t(10)), (t(11), t(12)), (t(13), t(14)), (t(16), t(17))])
    s.add(t(9, 30), t(13, 30))
    assert list(s) == [(t(9), t(14)), (t(16), t(17))]
    assert s.total() == timedelta(hours=6)


def test_adding_an_interval_that_bridges_two() -> None:
    s = IntervalSet([(t(9), t(10)), (t(11), t(12))])
    s.add(t(10), t(11))
    assert list(s) == [(t(9), t(12))]


def test_removing_from_the_middle_splits() -> None:
    s = IntervalSet([(t(9), t(17))])
    s.remove(t(12), t(13))
    assert list(s) == [(t(9), t(12)), (t(13), t(17))]


def test_removing_across_several_intervals() -> None:
    s = IntervalSet([(t(8), t(10)), (t(11), t(12)), (t(13), t(15))])
    s.remove(t(9), t(14))
    assert list(s) == [(t(8), t(9)), (t(14), t(15))]


def test_gaps() -> None:
    s = IntervalSet([(t(10), t(11)), (t(13), t(14))])
    assert list(s.gaps(t(9), t(17))) == [(t(9), t(10)), (t(11), t(13)), (t(14), t(17))]


def test_matches_a_minute_by_minute_model() -> None:
    rng = random.Random(20250303)
    base = datetime(2025, 3, 3)
    for _ in range(300):
        s = IntervalSet()
        model: set[int] = set()
        for _ in range(12):
            a, b = sorted(rng.sample(range(0, 120), 2))
            if rng.random() < 0.6:
                s.add(base + timedelta(minutes=a), base + timedelta(minutes=b))
                model.update(range(a, b))
            else:
                s.remove(base + timedelta(minutes=a), base + timedelta(minutes=b))
                model.difference_update(range(a, b))
            pairs = list(s)
            # normalised: sorted, non-empty, with a real gap between neighbours
            for (s1, e1), (s2, e2) in zip(pairs, pairs[1:]):
                assert s1 < e1 < s2 < e2, pairs
            minutes = {
                m
                for start, end in pairs
                for m in range(
                    int((start - base).total_seconds()) // 60,
                    int((end - base).total_seconds()) // 60,
                )
            }
            assert minutes == model
            assert s.total() == timedelta(minutes=len(model))


# -- working hours ----------------------------------------------------------------------------


def test_offset_east_of_utc() -> None:
    berlin = Person("B", "b@example.com", utc_offset=timedelta(hours=2))
    slots = find_slots([berlin], MONDAY, MONDAY, HOUR, step=HOUR)
    assert slots == [at(h) for h in range(7, 15)]


def test_offset_west_of_utc() -> None:
    nyc = Person("N", "n@example.com", utc_offset=timedelta(hours=-5))
    slots = find_slots([nyc], MONDAY, MONDAY, HOUR, step=HOUR)
    assert slots == [at(h) for h in range(14, 22)]


def test_half_hour_offset() -> None:
    india = Person("I", "i@example.com", utc_offset=timedelta(hours=5, minutes=30))
    slots = find_slots([india], MONDAY, MONDAY, HOUR, step=timedelta(minutes=30))
    assert slots[0] == at(3, 30)
    assert slots[-1] == at(10, 30)


def test_night_shift_runs_into_the_next_day() -> None:
    night = Person("N", "n@example.com", work_start=time(22), work_end=time(6))
    saturday = MONDAY + timedelta(days=5)
    # Friday's shift runs into Saturday morning; Saturday's shift does not exist.
    assert find_slots([night], saturday, saturday, HOUR, step=HOUR) == [
        at(h, day=saturday) for h in range(6)
    ]
    sunday = saturday + timedelta(days=1)
    assert find_slots([night], sunday, sunday, HOUR, step=HOUR) == []
    monday = sunday + timedelta(days=1)
    assert find_slots([night], monday, monday, HOUR, step=HOUR) == [
        at(22, day=monday),
        at(23, day=monday),
    ]


def test_night_shift_west_of_utc() -> None:
    # Noor: 22:00-06:00 at UTC-5, Sunday to Thursday, handover 08:00-08:45 UTC on Tuesday.
    noor = next(p for p in read_people(EXAMPLES) if p.name.startswith("Noor"))
    tuesday = MONDAY + timedelta(days=1)
    slots = find_slots([noor], tuesday, tuesday, HOUR, step=HOUR)
    assert slots == [at(h, day=tuesday) for h in (3, 4, 5, 6, 7, 9, 10)]


def test_shift_ending_exactly_at_midnight_local() -> None:
    late = Person("L", "l@example.com", work_start=time(16), work_end=time(0))
    assert find_slots([late], MONDAY, MONDAY, HOUR, step=HOUR) == [at(h) for h in range(16, 24)]


# -- buffers and the step grid -----------------------------------------------------------------


def test_buffer_applies_before_and_after() -> None:
    ana = Person("A", "a@example.com", busy=[(at(10), at(11))])
    slots = find_slots([ana], MONDAY, MONDAY, timedelta(minutes=30), buffer=timedelta(minutes=15))
    assert at(9, 15) in slots  # ends 9:45, right where the buffer starts
    assert at(9, 30) not in slots
    assert at(10, 45) not in slots
    assert at(11, 15) in slots


def test_free_time_with_buffer() -> None:
    ana = Person("A", "a@example.com", busy=[(at(12), at(13))])
    free = free_time(ana, at(0), at(24), timedelta(minutes=10))
    assert list(free) == [(at(9), at(11, 50)), (at(13, 10), at(17))]


def test_starts_are_rounded_up_to_the_grid() -> None:
    ana = Person("A", "a@example.com", busy=[(at(9), at(9, 1))])
    slots = find_slots([ana], MONDAY, MONDAY, timedelta(minutes=20), step=timedelta(minutes=20))
    assert slots[0] == at(9, 20)


def test_grid_counts_from_utc_midnight_not_from_working_hours() -> None:
    india = Person("I", "i@example.com", utc_offset=timedelta(hours=5, minutes=30))
    slots = find_slots([india], MONDAY, MONDAY, HOUR, step=HOUR)
    assert slots == [at(h) for h in range(4, 11)]


# -- the whole search -------------------------------------------------------------------------


def test_example_team_on_tuesday() -> None:
    people = read_people(EXAMPLES)
    tuesday = MONDAY + timedelta(days=1)
    slots = find_slots(people, tuesday, tuesday, timedelta(minutes=30))
    assert slots == [
        at(9, 30, tuesday),
        at(9, 45, tuesday),
        at(10, 0, tuesday),
        at(10, 15, tuesday),
        at(10, 30, tuesday),
    ]
    with_buffer = find_slots(
        people, tuesday, tuesday, timedelta(minutes=30), buffer=timedelta(minutes=10)
    )
    assert with_buffer == [
        at(9, 45, tuesday),
        at(10, 0, tuesday),
        at(10, 15, tuesday),
        at(10, 30, tuesday),
    ]


def test_last_day_is_included_and_limit() -> None:
    ana = Person("A", "a@example.com")
    slots = find_slots([ana], MONDAY, MONDAY + timedelta(days=1), HOUR, step=HOUR)
    assert len(slots) == 16
    assert find_slots([ana], MONDAY, MONDAY + timedelta(days=1), HOUR, step=HOUR, limit=3) == [
        at(9),
        at(10),
        at(11),
    ]


def test_slots_stay_inside_the_window() -> None:
    night = Person("N", "n@example.com", work_start=time(20), work_end=time(4))
    slots = find_slots([night], MONDAY, MONDAY, timedelta(hours=2), step=HOUR)
    assert slots == [at(20), at(21), at(22)]


# -- no hidden state --------------------------------------------------------------------------


def test_an_earlier_call_does_not_change_a_later_one() -> None:
    ana = Person("A", "a@example.com", busy=[(at(12), at(13))])
    find_slots([ana], MONDAY, MONDAY, timedelta(minutes=30), buffer=timedelta(hours=1))
    later = find_slots([ana], MONDAY, MONDAY, timedelta(minutes=30))
    fresh = find_slots(
        [Person("A", "a@example.com", busy=[(at(12), at(13))])],
        MONDAY,
        MONDAY,
        timedelta(minutes=30),
    )
    assert later == fresh
    assert at(11, 30) in later


def test_cancelled_meeting_frees_its_time() -> None:
    ana = Person("A", "a@example.com", busy=[(at(12), at(13))])
    assert at(12) not in find_slots([ana], MONDAY, MONDAY, HOUR, step=HOUR)
    ana.busy.clear()
    assert at(12) in find_slots([ana], MONDAY, MONDAY, HOUR, step=HOUR)


def test_free_time_does_not_change_working_time() -> None:
    ana = Person("A", "a@example.com", busy=[(at(12), at(13))])
    before = list(ana.working_time(MONDAY, MONDAY))
    free_time(ana, at(0), at(24), timedelta(0))
    assert list(ana.working_time(MONDAY, MONDAY)) == before


def test_equal_start_and_end_is_a_full_day_shift() -> None:
    always = Person("A", "a@example.com", work_start=time(8), work_end=time(8))
    assert find_slots([always], MONDAY, MONDAY, HOUR, step=HOUR) == [at(h) for h in range(8, 24)]
    tuesday = MONDAY + timedelta(days=1)
    assert find_slots([always], tuesday, tuesday, HOUR, step=HOUR) == [
        at(h, day=tuesday) for h in range(24)
    ]

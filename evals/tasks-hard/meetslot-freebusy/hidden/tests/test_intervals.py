from datetime import datetime

from meetslot.intervals import IntervalSet


def t(hour: int, minute: int = 0) -> datetime:
    return datetime(2025, 3, 3, hour, minute)


def test_disjoint_intervals_stay_apart() -> None:
    s = IntervalSet([(t(9), t(10)), (t(12), t(13))])
    assert list(s) == [(t(9), t(10)), (t(12), t(13))]


def test_overlapping_intervals_merge() -> None:
    s = IntervalSet([(t(9), t(11)), (t(10), t(12))])
    assert list(s) == [(t(9), t(12))]


def test_remove_trims_an_end() -> None:
    s = IntervalSet([(t(9), t(17))])
    s.remove(t(16), t(18))
    assert list(s) == [(t(9), t(16))]


def test_contains_and_total() -> None:
    s = IntervalSet([(t(9), t(10)), (t(12), t(12, 30))])
    assert t(9, 30) in s
    assert t(10) not in s
    assert s.total().total_seconds() == 90 * 60


def test_intersection() -> None:
    a = IntervalSet([(t(9), t(12))])
    b = IntervalSet([(t(11), t(14))])
    assert list(a.intersection(b)) == [(t(11), t(12))]

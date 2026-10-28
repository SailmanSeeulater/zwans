from datetime import UTC, datetime

import pytest
from libsys.holds import HoldError, cancel_hold, copy_returned, place_hold, queue_lengths, waiting


def at(day: int) -> datetime:
    return datetime(2026, 2, day, 1, 0, tzinfo=UTC)


def test_first_in_line_gets_the_copy(store) -> None:
    place_hold(store, "HAR", "Dune", "M-2", at(2))
    place_hold(store, "HAR", "Dune", "M-1", at(1))
    place_hold(store, "HIL", "Dune", "M-3", at(1))

    hold = copy_returned(store, "HAR", "dune", "b1")

    assert hold is not None and hold.member == "M-1" and hold.fulfilled_by == "b1"
    assert [h.member for h in waiting(store, "HAR", "Dune")] == ["M-2"]


def test_nobody_waiting(store) -> None:
    assert copy_returned(store, "HAR", "Dune", "b1") is None


def test_one_hold_per_member_and_title(store) -> None:
    place_hold(store, "HAR", "Dune", "M-1", at(1))
    with pytest.raises(HoldError, match="already waiting"):
        place_hold(store, "HAR", " dune ", "M-1", at(2))


def test_cancel(store) -> None:
    place_hold(store, "HAR", "Dune", "M-1", at(1))
    cancel_hold(store, "HAR", "Dune", "M-1")
    assert waiting(store, "HAR", "Dune") == []
    with pytest.raises(HoldError):
        cancel_hold(store, "HAR", "Dune", "M-1")


def test_queue_lengths(store) -> None:
    place_hold(store, "HAR", "Dune", "M-1", at(1))
    place_hold(store, "HIL", "Emma", "M-2", at(1))
    place_hold(store, "HAR", "dune", "M-3", at(2))
    place_hold(store, "HAR", "Emma", "M-4", at(3))

    assert queue_lengths(store) == {("HAR", "Dune"): 2, ("HAR", "Emma"): 1, ("HIL", "Emma"): 1}

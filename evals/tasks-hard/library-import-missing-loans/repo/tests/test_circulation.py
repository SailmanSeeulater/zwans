from datetime import UTC, date, datetime

import pytest
from libsys.circulation import CirculationError, give_back, issue, renew


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_due_date_counts_from_the_local_day(store, branches) -> None:
    harbour = branches.get("HAR")
    # 22:05 UTC on the 5th is 11:05 on the 6th in Harbour
    loan = issue(
        store,
        harbour,
        1043,
        "M-1043",
        "3101001043",
        "The Left Hand of Darkness",
        at("2026-02-05T22:05"),
    )
    assert loan.due == date(2026, 2, 27)
    assert store.get_loan("HAR", 1043) is loan


def test_renewals(store, branches) -> None:
    hillside = branches.get("HIL")
    issue(store, hillside, 5, "M-2001", "b5", "Dune", at("2026-02-01T00:00"))
    loan = renew(store, hillside, 5, at("2026-02-10T00:00"))
    assert (loan.due, loan.renewals) == (date(2026, 2, 24), 1)
    assert renew(store, hillside, 5, at("2026-02-10T03:00")).renewals == 1  # same day again
    with pytest.raises(CirculationError, match="already been renewed"):
        renew(store, hillside, 5, at("2026-02-15T00:00"))


def test_returns(store, branches) -> None:
    harbour = branches.get("HAR")
    issue(store, harbour, 9, "M-1009", "b9", "Emma", at("2026-02-01T00:00"))
    loan = give_back(store, harbour, 9, at("2026-02-03T00:00"))
    assert not loan.is_open
    assert give_back(store, harbour, 9, at("2026-02-03T00:00")) is loan  # seen again
    with pytest.raises(CirculationError, match="already returned"):
        give_back(store, harbour, 9, at("2026-02-04T00:00"))
    with pytest.raises(CirculationError, match="no loan HAR-10"):
        give_back(store, harbour, 10, at("2026-02-04T00:00"))


def test_reissuing_a_number_replaces_the_loan(store, branches) -> None:
    harbour = branches.get("HAR")
    issue(store, harbour, 3, "M-1001", "b3", "Emma", at("2026-02-01T00:00"))
    issue(store, harbour, 3, "M-1002", "b3", "Emma", at("2026-02-01T00:05"))
    assert store.get_loan("HAR", 3).member == "M-1002"
    assert len(store.loans) == 1


def test_overdue_starts_the_day_after_the_due_date(store, branches) -> None:
    loan = issue(store, branches.get("HAR"), 1, "M-1", "b", "t", at("2026-02-01T00:00"))
    assert loan.due == date(2026, 2, 22)
    assert not loan.is_overdue(date(2026, 2, 22))
    assert loan.is_overdue(date(2026, 2, 23))
    assert loan.days_overdue(date(2026, 2, 25)) == 3

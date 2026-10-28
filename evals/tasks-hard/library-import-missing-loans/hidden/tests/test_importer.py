from datetime import date

from conftest import rows
from libsys.importer import import_events

HARBOUR_NIGHT = """
issue,HAR,1001,M-1012,3101001001,A Wizard of Earthsea,2026-02-01T00:10:00Z
issue,HAR,1002,M-1020,3101001002,Middlemarch,2026-02-01T01:00:00Z
issue,HAR,1003,M-1012,3101001003,Emma,2026-02-02T03:30:00Z
renew,HAR,1001,,3101001001,A Wizard of Earthsea,2026-02-15T02:00:00Z
return,HAR,1002,,3101001002,Middlemarch,2026-02-16T04:00:00Z
"""


def test_a_harbour_night(store, branches) -> None:
    result = import_events(store, rows(HARBOUR_NIGHT), branches)

    assert result.describe() == "applied 5 events (HAR 5)"
    assert store.get_loan("HAR", 1001).due == date(2026, 3, 8)
    assert store.get_loan("HAR", 1001).renewals == 1
    assert not store.get_loan("HAR", 1002).is_open
    assert store.get_loan("HAR", 1003).due == date(2026, 2, 23)


def test_old_rows_without_a_branch_belong_to_the_default_branch(store, branches) -> None:
    old = "event,loan_no,member,barcode,title,at\nissue,77,m-1001,b77,Rebecca,2026-01-10T01:00:00Z"
    from libsys.csvio import read_rows

    result = import_events(store, read_rows(old.splitlines()), branches)

    assert result.applied == {"HAR": 1}
    assert store.get_loan("HAR", 77).member == "M-1001"


def test_branch_names_work_too(store, branches) -> None:
    result = import_events(
        store,
        rows("""
issue,Hillside,1,M-2201,3202000001,Dune,2026-02-01T01:00:00Z
issue,harbour,1,M-1001,3101000001,Emma,2026-02-01T01:00:00Z
"""),
        branches,
    )
    assert result.applied == {"HIL": 1, "HAR": 1}
    assert store.get_loan("HIL", 1).due == date(2026, 2, 15)
    assert store.get_loan("HAR", 1).due == date(2026, 2, 22)


def test_bad_rows_are_rejected_with_their_line_numbers(store, branches) -> None:
    result = import_events(
        store,
        rows("""
issue,HAR,1,M-1,b1,One,2026-02-01T01:00:00Z
lend,HAR,2,M-1,b2,Two,2026-02-01T01:00:00Z
issue,HAR,x,M-1,b3,Three,2026-02-01T01:00:00Z
issue,HAR,4,M-1,b4,Four,2026-02-01T01:00:00
return,HAR,5,,b5,Five,2026-02-02T01:00:00Z
issue,HAR,6,M-1,b6,Six,2026-02-01T01:00:00Z
"""),
        branches,
    )

    assert result.applied == {"HAR": 2}
    assert [line for line, _ in result.rejected] == [3, 4, 5, 6]
    assert "unknown event" in result.rejected[0][1]
    assert "no loan HAR-5" in result.rejected[3][1]


def test_importing_the_same_rows_twice_changes_nothing(store, branches) -> None:
    import_events(store, rows(HARBOUR_NIGHT), branches)
    before = store.to_dict()

    result = import_events(store, rows(HARBOUR_NIGHT), branches)

    assert result.rejected == []
    assert store.to_dict() == before


def test_a_correction_replaces_the_loan(store, branches) -> None:
    import_events(
        store,
        rows("""
issue,HAR,1,M-1001,b1,Emma,2026-02-01T01:00:00Z
issue,HAR,1,M-1010,b1,Emma,2026-02-01T01:05:00Z
"""),
        branches,
    )
    assert store.get_loan("HAR", 1).member == "M-1010"

from datetime import date
from decimal import Decimal

from conftest import rows
from libsys.fines import fine_for
from libsys.importer import import_events
from libsys.notices import build_notices, render_notice
from libsys.overdue import overdue_loans, overdue_report

NIGHT = """
issue,HAR,1,M-1001,b1,Emma,2026-01-20T01:00:00Z
issue,HAR,2,M-1002,b2,Rebecca,2026-02-01T01:00:00Z
issue,HAR,3,M-1001,b3,Persuasion,2026-01-20T02:00:00Z
return,HAR,2,,b2,Rebecca,2026-02-10T01:00:00Z
issue,Hillside,4,M-2001,b4,Dune,2026-02-01T01:00:00Z
issue,Hillside,5,M-2002,b5,Kindred,2026-02-20T01:00:00Z
"""


def test_overdue_loans(store, branches) -> None:
    import_events(store, rows(NIGHT), branches)

    items = overdue_loans(store, branches, date(2026, 3, 2))

    assert [(i.loan.branch, i.loan.number, i.days) for i in items] == [
        ("HAR", 1, 20),
        ("HAR", 3, 20),
        ("HIL", 4, 15),
    ]


def test_fines_are_capped(store, branches) -> None:
    import_events(store, rows(NIGHT), branches)
    loan = store.get_loan("HAR", 1)

    assert fine_for(loan, branches.get("HAR"), date(2026, 2, 11)) == Decimal("0.25")
    assert fine_for(loan, branches.get("HAR"), date(2026, 3, 2)) == Decimal("5.00")
    assert fine_for(loan, branches.get("HAR"), date(2026, 6, 1)) == Decimal("6.00")


def test_overdue_report(store, branches) -> None:
    import_events(store, rows(NIGHT), branches)

    report = overdue_report(store, branches, date(2026, 3, 2))

    assert report == (
        "Overdue loans as of 2 Mar 2026\n"
        "\n"
        "Harbour (2 loans, fines $10.00)\n"
        "loan   member  title       due          days   fine\n"
        "-----  ------  ----------  -----------  ----  -----\n"
        "HAR-1  M-1001  Emma        10 Feb 2026    20  $5.00\n"
        "HAR-3  M-1001  Persuasion  10 Feb 2026    20  $5.00\n"
        "\n"
        "Hillside (1 loan, fines $3.00)\n"
        "loan   member  title  due          days   fine\n"
        "-----  ------  -----  -----------  ----  -----\n"
        "HIL-4  M-2001  Dune   15 Feb 2026    15  $3.00\n"
    )


def test_nothing_overdue(store, branches) -> None:
    assert overdue_report(store, branches, date(2026, 3, 2)).endswith("Nothing is overdue.\n")


def test_one_notice_per_member_with_all_their_loans(store, branches) -> None:
    import_events(store, rows(NIGHT), branches)

    notices = build_notices(store, branches, date(2026, 3, 2))

    assert [(n.member, [i.loan.title for i in n.items]) for n in notices] == [
        ("M-1001", ["Emma", "Persuasion"]),
        ("M-2001", ["Dune"]),
    ]
    text = render_notice(notices[0], branches, date(2026, 3, 2))
    assert "you have 2 overdue items" in text
    assert "- Persuasion (due 10 Feb 2026 at Harbour, fine so far $5.00)" in text
    assert "Total fines: $10.00" in text

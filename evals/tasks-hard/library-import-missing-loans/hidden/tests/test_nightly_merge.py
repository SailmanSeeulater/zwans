from datetime import date
from pathlib import Path

import pytest
from conftest import REPO, rows, write_export
from libsys.cli import main
from libsys.importer import import_events
from libsys.notices import build_notices
from libsys.overdue import overdue_loans
from libsys.util import group_by

SAMPLE = REPO / "samples" / "nightly-2026-03-02.csv"


def run(tmp_path: Path, *args: str) -> int:
    return main(
        ["--db", str(tmp_path / "library.json"), "--branches", str(REPO / "branches.toml"), *args]
    )


def test_the_sample_night_imports_every_event(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "import", str(SAMPLE)) == 0
    assert capsys.readouterr().out == f"{SAMPLE}: applied 150 events (HAR 97, HIL 53)\n"


def test_the_overdue_report_for_the_sample_night(tmp_path: Path, capsys) -> None:
    run(tmp_path, "import", str(SAMPLE))
    capsys.readouterr()

    assert run(tmp_path, "overdue", "--as-of", "2026-03-02", "--csv") == 0

    assert capsys.readouterr().out == (
        "branch,loan_no,member,title,due,days,fine\n"
        "HAR,1001,M-1012,A Wizard of Earthsea,2026-02-22,8,2.00\n"
        "HAR,1043,M-1043,The Left Hand of Darkness,2026-02-27,3,0.75\n"
        "HAR,1014,M-1097,Small Island,2026-02-27,3,0.75\n"
        "HAR,1020,M-1029,A Wizard of Earthsea,2026-03-01,1,0.25\n"
        "HIL,1024,M-2210,Persuasion,2026-02-17,13,2.60\n"
        "HIL,1023,M-2243,Things Fall Apart,2026-02-18,12,2.40\n"
        "HIL,1033,M-2210,Kindred,2026-02-22,8,1.60\n"
        "HIL,1029,M-2233,The Dispossessed,2026-02-22,8,1.60\n"
        "HIL,1034,M-2246,Small Island,2026-02-25,5,1.00\n"
        "HIL,1028,M-2212,Atonement,2026-02-27,3,0.60\n"
        "HIL,1020,M-2236,Persuasion,2026-02-27,3,0.60\n"
        "HIL,1037,M-2248,A Wizard of Earthsea,2026-02-27,3,0.60\n"
        "HIL,1030,M-2216,Circe,2026-02-28,2,0.40\n"
        "HIL,1038,M-2232,Possession,2026-02-28,2,0.40\n"
    )


def test_m1043_keeps_their_harbour_loan(tmp_path: Path, capsys) -> None:
    run(tmp_path, "import", str(SAMPLE))
    capsys.readouterr()

    run(tmp_path, "loans", "M-1043")

    assert "HAR-1043  The Left Hand of Darkness  due 27 Feb 2026" in capsys.readouterr().out


def test_late_corrections_at_the_end_of_the_file_are_applied(tmp_path: Path, capsys) -> None:
    run(tmp_path, "import", str(SAMPLE))
    capsys.readouterr()

    run(tmp_path, "loans", "M-1077")
    assert "HAR-1061  Piranesi" in capsys.readouterr().out
    run(tmp_path, "overdue", "--as-of", "2026-03-02", "--csv")
    report = capsys.readouterr().out
    for returned_or_renewed in ("HAR,1009,", "HAR,1016,", "HIL,1022,", "HIL,1031,"):
        assert returned_or_renewed not in report


def test_m2210_gets_one_notice_with_both_books(store, branches) -> None:
    from libsys.csvio import read_export

    import_events(store, read_export(SAMPLE), branches)

    notices = {n.member: n for n in build_notices(store, branches, date(2026, 3, 2))}

    assert [item.loan.title for item in notices["M-2210"].items] == ["Persuasion", "Kindred"]


def test_importing_the_sample_twice_changes_nothing(tmp_path: Path, capsys) -> None:
    run(tmp_path, "import", str(SAMPLE))
    first = (tmp_path / "library.json").read_text(encoding="utf-8")

    run(tmp_path, "import", str(SAMPLE))

    assert (tmp_path / "library.json").read_text(encoding="utf-8") == first
    assert "rejected" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "spelling", ["HIL", "hil", "Hil", " HIL ", "Hillside", "HILLSIDE", "hillside"]
)
def test_branch_codes_and_names_in_any_case(branches, spelling: str) -> None:
    assert branches.resolve(spelling).code == "HIL"


@pytest.mark.parametrize("spelling", ["HAR", "har", "Harbour", "HARBOUR"])
def test_harbour_spellings(branches, spelling: str) -> None:
    assert branches.resolve(spelling).code == "HAR"


def test_rows_for_an_unknown_branch_are_rejected(store, branches) -> None:
    result = import_events(
        store,
        rows("""
issue,HAR,7,M-1007,b7,Emma,2026-02-01T01:00:00Z
issue,Seaview,7,M-3007,b8,Dune,2026-02-01T02:00:00Z
issue,HIL,8,M-2008,b9,Kindred,2026-02-01T03:00:00Z
"""),
        branches,
    )

    assert result.applied == {"HAR": 1, "HIL": 1}
    assert [line for line, _ in result.rejected] == [3]
    assert "Seaview" in result.rejected[0][1]
    assert store.get_loan("HAR", 7).member == "M-1007"
    assert len(store.loans) == 2


def test_the_same_number_at_two_branches_is_two_loans(store, branches) -> None:
    import_events(
        store,
        rows("""
issue,HAR,1043,M-1043,3101001043,The Left Hand of Darkness,2026-02-05T22:05:00Z
issue,HIL,1043,M-2245,3202001043,Dune,2026-02-16T23:13:00Z
"""),
        branches,
    )

    assert store.get_loan("HAR", 1043).member == "M-1043"
    assert store.get_loan("HIL", 1043).member == "M-2245"
    assert store.get_loan("HIL", 1043).due == date(2026, 3, 3)


def test_interleaved_branches(store, branches) -> None:
    result = import_events(
        store,
        rows("""
issue,HAR,1,M-1001,b1,Emma,2026-02-01T01:00:00Z
issue,HIL,1,M-2001,c1,Dune,2026-02-01T01:30:00Z
issue,HAR,2,M-1002,b2,Rebecca,2026-02-01T02:00:00Z
issue,HIL,2,M-2002,c2,Circe,2026-02-01T02:30:00Z
return,HAR,1,,b1,Emma,2026-02-03T01:00:00Z
renew,HIL,1,,c1,Dune,2026-02-10T01:00:00Z
issue,HAR,3,M-1003,b3,Hamnet,2026-02-11T01:00:00Z
"""),
        branches,
    )

    assert result.rejected == []
    assert result.applied == {"HAR": 4, "HIL": 3}
    assert not store.get_loan("HAR", 1).is_open
    assert store.get_loan("HIL", 1).due == date(2026, 2, 24)
    assert store.get_loan("HAR", 3) is not None
    assert [
        (i.loan.branch, i.loan.number) for i in overdue_loans(store, branches, date(2026, 2, 23))
    ] == [
        ("HAR", 2),
        ("HIL", 2),
    ]


def test_a_correction_after_another_branchs_rows_still_wins(store, branches) -> None:
    import_events(
        store,
        rows("""
issue,HAR,5,M-1001,b5,Emma,2026-02-01T01:00:00Z
issue,HIL,9,M-2001,c9,Dune,2026-02-01T01:30:00Z
issue,HAR,5,M-1010,b5,Emma,2026-02-01T01:45:00Z
"""),
        branches,
    )
    assert store.get_loan("HAR", 5).member == "M-1010"


def test_group_by_does_not_need_sorted_input() -> None:
    assert group_by([3, 1, 3, 2, 1, 3], key=lambda n: n) == {3: [3, 3, 3], 1: [1, 1], 2: [2]}
    words = ["kiwi", "fig", "plum", "pear", "date", "lime", "yam"]
    assert group_by(words, key=len) == {
        4: ["kiwi", "plum", "pear", "date", "lime"],
        3: ["fig", "yam"],
    }
    assert list(group_by(iter(words), key=lambda w: w[0])) == ["k", "f", "p", "d", "l", "y"]


def test_a_members_loans_on_different_days_share_one_notice(store, branches) -> None:
    import_events(
        store,
        rows("""
issue,HAR,1,M-1001,b1,Emma,2026-01-20T01:00:00Z
issue,HAR,2,M-1002,b2,Rebecca,2026-01-21T01:00:00Z
issue,HAR,3,M-1001,b3,Persuasion,2026-01-22T01:00:00Z
issue,HAR,4,M-1002,b4,Hamnet,2026-01-23T01:00:00Z
"""),
        branches,
    )

    notices = build_notices(store, branches, date(2026, 3, 2))

    assert [(n.member, [i.loan.title for i in n.items]) for n in notices] == [
        ("M-1001", ["Emma", "Persuasion"]),
        ("M-1002", ["Rebecca", "Hamnet"]),
    ]


def test_exports_written_by_the_hillside_desk(tmp_path: Path, capsys) -> None:
    export = write_export(
        tmp_path,
        """
issue,hil,1,M-2001,c1,Dune,2026-02-01T01:00:00Z
issue,HILLSIDE,2,M-2002,c2,Circe,2026-02-01T01:30:00Z
""",
    )
    run(tmp_path, "import", str(export))
    assert capsys.readouterr().out == f"{export}: applied 2 events (HIL 2)\n"

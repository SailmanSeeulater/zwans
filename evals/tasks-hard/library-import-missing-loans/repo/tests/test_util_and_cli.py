from pathlib import Path

from conftest import REPO, write_export
from libsys.cli import main
from libsys.csvio import normalise_header, read_rows, to_csv
from libsys.util import chunked, group_by, unique


def test_group_by() -> None:
    words = ["apple", "avocado", "banana", "blueberry", "cherry"]
    assert group_by(words, key=lambda word: word[0]) == {
        "a": ["apple", "avocado"],
        "b": ["banana", "blueberry"],
        "c": ["cherry"],
    }
    assert group_by([], key=len) == {}


def test_chunked_and_unique() -> None:
    assert list(chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
    assert unique([3, 1, 3, 2, 1]) == [3, 1, 2]
    assert unique(["a", "A", "b"], key=str.lower) == ["a", "b"]


def test_csv_headers_are_forgiving() -> None:
    assert normalise_header(" Loan No ") == "loan_no"
    assert normalise_header("loan-no") == "loan_no"
    lines = ["Event,Loan No,Member,Barcode,Title,At", "issue,1,M-1,b,t,2026-02-01T00:00:00Z", ""]
    assert list(read_rows(lines)) == [
        {
            "event": "issue",
            "loan_no": "1",
            "member": "M-1",
            "barcode": "b",
            "title": "t",
            "at": "2026-02-01T00:00:00Z",
            "branch": "",
        }
    ]


def test_to_csv_quotes() -> None:
    assert to_csv(["a", "b"], [["x, y", None]]) == 'a,b\n"x, y",\n'


def run(tmp_path: Path, *args: str) -> int:
    return main(
        ["--db", str(tmp_path / "library.json"), "--branches", str(REPO / "branches.toml"), *args]
    )


def test_cli_import_and_overdue(tmp_path: Path, capsys) -> None:
    export = write_export(
        tmp_path,
        """
issue,HAR,1001,M-1012,3101001001,A Wizard of Earthsea,2026-02-01T00:10:00Z
issue,HAR,1002,M-1020,3101001002,Middlemarch,2026-02-01T01:00:00Z
return,HAR,1002,,3101001002,Middlemarch,2026-02-16T04:00:00Z
""",
    )
    assert run(tmp_path, "import", str(export)) == 0
    assert capsys.readouterr().out == f"{export}: applied 3 events (HAR 3)\n"

    assert run(tmp_path, "overdue", "--as-of", "2026-03-02", "--csv") == 0
    assert capsys.readouterr().out == (
        "branch,loan_no,member,title,due,days,fine\n"
        "HAR,1001,M-1012,A Wizard of Earthsea,2026-02-22,8,2.00\n"
    )

    assert run(tmp_path, "loans", "m-1020") == 0
    assert "HAR-1002  Middlemarch  returned" in capsys.readouterr().out


def test_cli_reports_rejected_rows(tmp_path: Path, capsys) -> None:
    export = write_export(tmp_path, "return,HAR,9,,b,t,2026-02-01T00:00:00Z")
    assert run(tmp_path, "import", str(export)) == 0
    assert capsys.readouterr().out.endswith("rejected 1\n  line 2: no loan HAR-9 to return\n")


def test_cli_missing_file(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "import", str(tmp_path / "nope.csv")) == 1
    assert "nope.csv" in capsys.readouterr().err

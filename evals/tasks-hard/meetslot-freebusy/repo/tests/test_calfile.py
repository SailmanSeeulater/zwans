from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from meetslot.calfile import CalFileError, read_people, read_person

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_read_example_people() -> None:
    people = read_people(EXAMPLES)
    assert [p.name for p in people] == ["Ana Lima", "Kenji Mori", "Noor Haddad"]


def test_headers() -> None:
    noor = read_person(EXAMPLES / "noor.cal")
    assert noor.utc_offset == timedelta(hours=-5)
    assert (noor.work_start, noor.work_end) == (time(22), time(6))
    assert noor.workdays == frozenset({6, 0, 1, 2, 3})
    assert noor.busy == [(datetime(2025, 3, 4, 8), datetime(2025, 3, 4, 8, 45))]


def test_end_without_a_date() -> None:
    ana = read_person(EXAMPLES / "ana.cal")
    assert (datetime(2025, 3, 3, 13), datetime(2025, 3, 3, 14)) in ana.busy


def test_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "x.cal"
    path.write_text("name: X\nemail: x@example.com\nhours: 9-5\n", encoding="utf-8")
    with pytest.raises(CalFileError):
        read_person(path)

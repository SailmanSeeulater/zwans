import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from clinicbook import ClinicBook, Store
from clinicbook.cli import main

DATA = Path(__file__).parent / "data"

CAMDEN_HOURS = {
    "mon": "08:00-18:00",
    "tue": "08:00-18:00",
    "wed": "08:00-12:30, 13:30-18:00",
    "thu": "08:00-18:00",
    "fri": "08:00-17:00",
    "sat": "09:00-13:00",
}


class Clock:
    """Stands still at 2026-01-05 08:00 (a Monday) until told otherwise."""

    def __init__(self, start: datetime = datetime(2026, 1, 5, 8, 0)) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def set(self, value: datetime) -> None:
        self.now = value


class Hooks:
    """A webhook receiver: records what was posted, answers with `status`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self.status = 200

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        self.calls.append((url, body, headers))
        return self.status


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hooks() -> Hooks:
    return Hooks()


@pytest.fixture
def book(clock: Clock, hooks: Hooks) -> ClinicBook:
    book = ClinicBook(Store.memory(), clock=clock, webhook_sender=hooks)
    book.add_clinic("camden", "Camden Clinic", zone="Europe/London", hours=CAMDEN_HOURS,
                    phone="+44 20 7946 0000")
    book.add_room("camden", "C1", "Room 1")
    book.add_room("camden", "C2", "Room 2")
    book.add_clinician("dr-osei", "Dr Ama Osei", clinics=["camden"])
    book.add_clinician("dr-lind", "Dr Erik Lind", clinics=["camden"])
    book.add_patient("Jo Bloggs", phone="+44 7700 900001")
    book.add_patient("Sam Patel", email="sam@example.org")
    book.add_patient("Kit Moreau", phone="+44 7700 900003")
    return book


@pytest.fixture
def legacy(tmp_path: Path) -> Callable[[str], Path]:
    """A copy of one of the data files written by an earlier release."""

    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copy(DATA / name, target)
        return target

    return copy


@pytest.fixture
def cli(tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> Callable:
    """cli("book", ...) -> (exit code, stdout, stderr), on a data file of its own."""
    path = tmp_path / "clinicbook.json"
    monkeypatch.setenv("CLINICBOOK_NOW", "2026-01-05T08:00")
    monkeypatch.delenv("CLINICBOOK_DB", raising=False)

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--db", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    return run

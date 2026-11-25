import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from billfold import Book, FixedClock
from billfold.cli import main

DATA = Path(__file__).parent / "data"


def exact(value: object, text: str) -> None:
    """An amount must be a Decimal equal to `text`, with exactly that many places."""
    assert isinstance(value, Decimal), f"{value!r} is a {type(value).__name__}, not a Decimal"
    assert value == Decimal(text), f"{value!r} != {text}"
    assert str(value) == text, f"{value!r} should be written {text}"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-03-01")


@pytest.fixture
def book(clock: FixedClock) -> Book:
    return Book(clock=clock)


@pytest.fixture
def household(book: Book) -> Book:
    """Two EUR accounts and a USD one, with a month of ordinary spending."""
    book.add_account("Checking", opening_balance="1000.00", opened="2026-01-01")
    book.add_account("Savings", kind="savings", opening_balance="5000.00", opened="2026-01-01")
    book.add_account("Dollars", currency="USD", opening_balance="250.00", opened="2026-01-01")
    book.add_transaction("Checking", "2026-03-02", "-42.50", payee="REWE Markt",
                         category="Food:Groceries")
    book.add_transaction("Checking", "2026-03-03", "2500.00", payee="ACME GmbH",
                         category="Salary")
    book.add_transaction("Checking", "2026-03-05", "-12.25", payee="Cafe Lotte",
                         category="Food:Eating out")
    book.add_transaction("Checking", "2026-03-09", "-1100.00", payee="Landlord",
                         category="Rent")
    book.add_transaction("Dollars", "2026-03-04", "-20.00", payee="Diner",
                         category="Food:Eating out")
    return book


@pytest.fixture
def pennies(book: Book) -> Book:
    """Amounts binary floats can't hold: a EUR account and a JPY one."""
    book.add_account("Checking", opening_balance="0.70", opened="2026-01-01")
    book.add_account("Yen", currency="JPY", opening_balance="15000", opened="2026-01-01")
    book.add_transaction("Checking", "2026-03-02", "-0.10", payee="Kiosk", category="Food:Snacks")
    book.add_transaction("Checking", "2026-03-02", "-0.20", payee="Kiosk", category="Food:Snacks")
    book.add_transaction("Checking", "2026-03-03", "-19.99", payee="Streamly",
                         category="Subscriptions")
    book.add_transaction("Checking", "2026-03-04", "1,234.56", payee="ACME GmbH",
                         category="Salary")
    book.add_transaction("Yen", "2026-03-05", "-1200", payee="Ramen Ya", category="Food")
    return book


@pytest.fixture
def legacy_v1(tmp_path: Path) -> Path:
    path = tmp_path / "old.json"
    shutil.copy(DATA / "billfold-v1.json", path)
    return path


@pytest.fixture
def legacy_v2(tmp_path: Path) -> Path:
    path = tmp_path / "billfold.json"
    shutil.copy(DATA / "billfold-v2.json", path)
    return path


@pytest.fixture
def legacy_floats(tmp_path: Path) -> Path:
    """A 2.x file full of binary floats: noise in the cache, 19.99s, a yen account."""
    path = tmp_path / "billfold.json"
    shutil.copy(DATA / "billfold-v2-floats.json", path)
    return path


@pytest.fixture
def legacy_v1_floats(tmp_path: Path) -> Path:
    path = tmp_path / "old.json"
    shutil.copy(DATA / "billfold-v1-floats.json", path)
    return path


@pytest.fixture
def cli(tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> Callable:
    """cli("add", "Checking", "-12.50") -> (exit code, stdout, stderr) on a file of its own."""
    path = tmp_path / "billfold.json"
    monkeypatch.setenv("BILLFOLD_TODAY", "2026-03-01")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--file", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    return run

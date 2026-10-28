import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from stockroom import Database, Inventory
from stockroom.cli import main

DATA = Path(__file__).parent / "data"


class Clock:
    """Ticks one minute per call, from 2026-03-01T09:00:00Z."""

    def __init__(self) -> None:
        self.minutes = 0

    def __call__(self) -> str:
        at = f"2026-03-01T{9 + self.minutes // 60:02d}:{self.minutes % 60:02d}:00Z"
        self.minutes += 1
        return at


@pytest.fixture
def db() -> Database:
    return Database.memory()


@pytest.fixture
def inv(db: Database) -> Inventory:
    return Inventory(db, clock=Clock())


@pytest.fixture
def legacy_file(tmp_path: Path) -> Path:
    """A copy of a database written by stockroom 1.x."""
    path = tmp_path / "legacy.json"
    shutil.copy(DATA / "legacy.json", path)
    return path


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """cli("add", "MUG-01", ...) -> (exit code, stdout, stderr), on a database of its own."""
    path = tmp_path / "stock.json"
    monkeypatch.setenv("STOCKROOM_NOW", "2026-03-01T09:00:00Z")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--db", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    return run


def stock_up(inv: Inventory) -> None:
    inv.add_product("MUG-01", "Blue mug", 425, reorder_level=10)
    inv.add_product("KET-02", "Red kettle", 1999, reorder_level=2)
    inv.add_product("TEA-07", "Green tea, 100 g", 350)
    inv.receive("MUG-01", 40, "PO-1001")
    inv.receive("KET-02", 5, "PO-1001")

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from markbook.cli import main

DATA = Path(__file__).parent / "data"


def sample(version: int) -> dict:
    """The sample file written by the markbook that used format `version`."""
    return json.loads((DATA / f"v{version}.json").read_text("utf-8"))


@pytest.fixture
def old_file(tmp_path: Path) -> Callable[[int], Path]:
    """old_file(2) -> a copy of the format 2 sample, safe to change."""

    def copy(version: int) -> Path:
        path = tmp_path / f"bookmarks-v{version}.json"
        shutil.copy(DATA / f"v{version}.json", path)
        return path

    return copy


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """cli("add", URL) -> (exit code, stdout, stderr), on a bookmark file of its own (cli.path)."""
    monkeypatch.setenv("MARKBOOK_TODAY", "2026-03-01")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--file", str(run.path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = tmp_path / "bookmarks.json"
    return run


def ids(output: str) -> list[int]:
    """The bookmark ids in `list` or `find` output."""
    return [int(line.split()[0]) for line in output.splitlines() if line.strip()]

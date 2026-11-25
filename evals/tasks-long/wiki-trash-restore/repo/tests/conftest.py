import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from leafwiki import Wiki
from leafwiki.cli import main
from leafwiki.clock import SteppingClock

DATA = Path(__file__).parent / "data"
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> SteppingClock:
    """Starts 2026-03-01 09:00 UTC and moves one minute per reading."""
    return SteppingClock(START)


@pytest.fixture
def wiki(clock: SteppingClock) -> Wiki:
    return Wiki.memory(clock=clock)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "wiki"


@pytest.fixture
def disk_wiki(folder: Path, clock: SteppingClock) -> Wiki:
    return Wiki.init(folder, clock=clock, site_name="Test Wiki", base_url="https://wiki.example")


@pytest.fixture
def legacy_folder(tmp_path: Path) -> Path:
    """A copy of a wiki written by leafwiki 1.4."""
    target = tmp_path / "legacy"
    target.mkdir()
    shutil.copy(DATA / "legacy-wiki.json", target / "wiki.json")
    return target


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """cli("new", "Kettle", ...) -> (exit code, stdout, stderr), on a wiki of its own."""
    path = tmp_path / "cliwiki"
    monkeypatch.setenv("LEAFWIKI_NOW", "2026-03-01T09:00:00Z")
    monkeypatch.setenv("LEAFWIKI_USER", "ana")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--dir", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    assert run("init", "--name", "CLI Wiki", "--base-url", "https://cli.example")[0] == 0
    return run


def kitchen(wiki: Wiki) -> None:
    """A few linked, tagged pages."""
    wiki.create_page(
        "Front Page",
        "# Welcome\n\nStart with [[Kettle]] or [[Teapot|the teapot]]. Also [[Toaster]].",
        "ana",
        tags=["home"],
    )
    wiki.create_page(
        "Kettle",
        "Descale the kettle with vinegar every month.\n\nBack to [[Front Page]].",
        "bo",
        tags=["kitchen", "appliances"],
    )
    wiki.create_page(
        "Teapot",
        "Warm the teapot first. A [[Kettle]] helps.\n\n- loose leaves\n- a strainer",
        "cy",
        tags=["kitchen"],
    )

import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from leafwiki import Wiki
from leafwiki.cli import main
from leafwiki.clock import SteppingClock

DATA = Path(__file__).parent / "data"
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

BODY_MARK = "zanzibarquill"
FILE_MARK = b"FILEMARK-qorvextrine"
COMMENT_MARK = "frobnitzelplume"


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


class ManualClock:
    """Stays put until moved, so every timestamp can be predicted exactly."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def manual() -> ManualClock:
    return ManualClock()


@pytest.fixture(params=["memory", "disk"])
def any_wiki(request, tmp_path: Path, clock: SteppingClock) -> Wiki:
    """The same tests on both stores."""
    if request.param == "memory":
        return Wiki.memory(clock=clock)
    return Wiki.init(tmp_path / "anywiki", clock=clock, base_url="https://wiki.example")


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


def stocked(wiki: Wiki) -> None:
    """kitchen() plus a second revision, an attachment, comments and watchers on the Kettle."""
    kitchen(wiki)
    wiki.edit_page(
        "Kettle",
        f"Descale the kettle with vinegar every month. {BODY_MARK}\n\nBack to [[Front Page]].",
        "eve",
        "marked",
    )
    wiki.attach("Kettle", "manual.txt", FILE_MARK + b" read the manual", "bo")
    first = wiki.comment(
        "Kettle",
        "Which vinegar works best for this, and how long should it soak? " + COMMENT_MARK,
        "cy",
    )
    reply = wiki.comment("Kettle", "White vinegar, an hour.", "bo", reply_to=first.id)
    wiki.edit_comment(reply.id, "White vinegar, about an hour.")
    wiki.watch("Kettle", "cy")
    wiki.watch("Kettle", "dee")


def snapshot(wiki: Wiki, title: str) -> dict:
    """Everything about one page that a restore must bring back."""
    page = wiki.page(title)
    return {
        "page": page.to_dict(),
        "files": {a.name: wiki.attachment(title, a.name) for a in wiki.attachments(title)},
        "comments": [c.to_dict() for c in wiki.comments(title)],
        "watchers": wiki.watchers(title),
    }


def titles(hits) -> list[str]:
    return [hit.title for hit in hits]


def entries(wiki: Wiki) -> list[tuple[str, str, str, str]]:
    """The trash as plain tuples, so two listings can be compared."""
    return [(e.id, e.title, e.deleted_at, e.deleted_by) for e in wiki.trash()]

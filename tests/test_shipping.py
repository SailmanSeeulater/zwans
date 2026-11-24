import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from zwans.checkpoints import Change
from zwans.shipping import ShipError, draft, ship, slug, state

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True, text=True)
    return done.stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A repository on main, with a bare repository as its origin."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--initial-branch=main")
    git(work, "config", "user.email", "test@example.com")
    git(work, "config", "user.name", "Test")
    for name in ("a.txt", "c.txt", "other.txt"):
        (work / name).write_text("old\n")
    git(work, "add", ".")
    git(work, "commit", "-m", "Start")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-u", "origin", "main")
    return work


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A gh that writes down how it was called and prints a pull request's address."""
    folder = tmp_path / "bin"
    folder.mkdir()
    record = tmp_path / "gh-called"
    script = folder / "gh"
    script.write_text(
        f'#!/bin/sh\necho "$@" > {record}\ncat >> {record}\n'
        "echo https://github.com/someone/project/pull/7\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}:{Path(shutil.which('git') or '').parent}:/usr/bin:/bin")
    return record


def session_changes(work: Path) -> list[Change]:
    (work / "a.txt").write_text("new\n")
    (work / "b.txt").write_text("added\n")
    (work / "c.txt").unlink()
    (work / "other.txt").write_text("someone else's work in progress\n")
    return [Change("changed", "a.txt"), Change("added", "b.txt"), Change("deleted", "c.txt")]


def test_a_draft_names_a_branch_and_lists_the_files() -> None:
    made = draft("Fix the date parsing in reports", [Change("changed", "reports.py")], "Fixed it.")

    assert made["branch"] == "zwans/fix-the-date-parsing-in-reports"
    assert made["title"] == "Fix the date parsing in reports"
    assert made["body"].startswith("Fixed it.") and "- changed: `reports.py`" in made["body"]
    assert slug("Ünïcode & $ymbols!!") == "n-code-ymbols"
    assert slug("") == "changes"


def test_shipping_commits_only_the_sessions_files_pushes_and_opens_a_pr(
    project: Path, fake_gh: Path
) -> None:
    changes = session_changes(project)

    done = asyncio.run(
        ship(project, changes, branch="zwans/fix", title="Fix a", body="Why: because.")
    )

    assert [(s.name, s.ok) for s in done.steps] == [
        ("branch", True),
        ("commit", True),
        ("push", True),
        ("pr", True),
    ]
    assert done.url == "https://github.com/someone/project/pull/7"
    committed = git(project, "show", "--name-status", "--format=%s", "HEAD").splitlines()
    assert committed[0] == "Fix a"
    assert sorted(committed[2:]) == ["A\tb.txt", "D\tc.txt", "M\ta.txt"]
    assert git(project, "status", "--porcelain") == "M other.txt"  # left out, still there
    assert git(project, "ls-remote", "--heads", "origin", "zwans/fix") != ""
    called = fake_gh.read_text()
    assert "pr create --base main --head zwans/fix --title Fix a --body-file -" in called
    assert "Why: because." in called


def test_what_stops_shipping_and_what_is_reported(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = session_changes(project)
    loose = tmp_path / "loose"
    loose.mkdir()

    with pytest.raises(ShipError, match="isn't a git repository"):
        asyncio.run(ship(loose, changes, branch="x", title="t", body=""))
    with pytest.raises(ShipError, match="other than main"):
        asyncio.run(ship(project, changes, branch="main", title="t", body=""))
    with pytest.raises(ShipError, match="isn't a name git takes"):
        asyncio.run(ship(project, changes, branch="bad..name", title="t", body=""))
    with pytest.raises(ShipError, match="nothing to commit"):
        asyncio.run(ship(project, [], branch="zwans/x", title="t", body=""))

    # No gh: CI's runners have it in /usr/bin beside the rest, so hide it rather than trim PATH.
    which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: None if name == "gh" else which(name, *a, **k)
    )
    done = asyncio.run(ship(project, changes, branch="zwans/no-gh", title="t", body=""))

    assert [(s.name, s.ok) for s in done.steps][-1] == ("pr", False)
    assert "Install GitHub's gh" in done.steps[-1].detail
    found = asyncio.run(state(project))
    assert found.branch == "zwans/no-gh" and found.base == "main" and not found.on_base

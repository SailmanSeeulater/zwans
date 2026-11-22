from pathlib import Path

import pytest

from zwans.checkpoints import Change
from zwans.races import Lane, Race, RaceError, copy_project, keep, load, save


def test_a_copy_has_the_files_and_history_links_dependencies_and_skips_caches(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print(1)\n")
    (project / ".git").mkdir()
    (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (project / "node_modules" / "left-pad").mkdir(parents=True)
    (project / "web" / "node_modules").mkdir(parents=True)
    (project / "src" / "__pycache__").mkdir()
    (project / "src" / "__pycache__" / "app.pyc").write_bytes(b"\0")

    copy = tmp_path / "copy"
    copy_project(project, copy)

    assert (copy / "src" / "app.py").read_text() == "print(1)\n"
    assert (copy / ".git" / "HEAD").exists()
    assert (copy / "node_modules").is_symlink()
    assert (copy / "node_modules").resolve() == (project / "node_modules").resolve()
    assert (copy / "web" / "node_modules").is_symlink()
    assert not (copy / "src" / "__pycache__").exists()


def test_keeping_a_result_copies_its_changes_back_and_deletes_what_it_deleted(
    tmp_path: Path,
) -> None:
    project, copy = tmp_path / "project", tmp_path / "copy"
    for folder in (project, copy):
        folder.mkdir()
        (folder / "old.txt").write_text("old\n")
    (project / "gone.txt").write_text("x\n")
    (copy / "old.txt").write_text("new\n")
    (copy / "pkg").mkdir()
    (copy / "pkg" / "added.py").write_text("x = 1\n")
    race = Race(id="r", prompt="p", workspace=str(project), created_at="now")
    lane = Lane(model="m", folder=str(copy))
    changes = [
        Change("changed", "old.txt"),
        Change("added", "pkg/added.py"),
        Change("deleted", "gone.txt"),
    ]

    kept = keep(race, lane, changes)

    assert kept == changes
    assert (project / "old.txt").read_text() == "new\n"
    assert (project / "pkg" / "added.py").read_text() == "x = 1\n"
    assert not (project / "gone.txt").exists()
    with pytest.raises(RaceError, match="outside the project"):
        keep(race, lane, [Change("changed", "../escape.txt")])


def test_a_race_is_saved_and_loaded(tmp_path: Path) -> None:
    race = Race(id="20261122-1200-abcd", prompt="Fix it", workspace="/w", created_at="now")
    race.lanes.append(Lane(model="a", folder="/a", session_id="s1"))
    save(tmp_path, race)

    assert load(tmp_path, race.id) == race
    with pytest.raises(RaceError):
        load(tmp_path, "missing")
    with pytest.raises(RaceError):
        load(tmp_path, "../etc")

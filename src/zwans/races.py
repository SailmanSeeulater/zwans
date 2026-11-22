"""Races: one task given to two models at once, each in its own copy of the project, so
they can be watched side by side and the better result kept.

A race's copies live under the home folder's `races/<id>/`, one folder per model, made
with the project's files and its git history. Dependency folders such as node_modules and
.venv are linked rather than copied: they're large, and the models' work doesn't usually
touch them. Keeping a model's result copies the files its session changed back into the
project, and deletes the ones it deleted.
"""

import json
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from zwans.checkpoints import Change

RACES = "races"
LANES = "ab"  # a race's copies, by letter
# Folders left out of the copies: caches nobody needs twice.
SKIPPED = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".turbo"}
# Folders the copies link to instead of copying: dependencies, big and rebuilt by tools.
LINKED = {"node_modules", ".venv", "venv", "target", ".gradle"}
MOST_FILES = 20_000  # a project bigger than this is refused, not copied twice


class RaceError(Exception):
    """A race that can't be started, or a result that can't be kept."""


@dataclass
class Lane:
    model: str
    folder: str  # the copy it works in
    session_id: str = ""


@dataclass
class Race:
    id: str
    prompt: str
    workspace: str  # the project the copies were made from
    created_at: str
    lanes: list[Lane] = field(default_factory=list)
    kept: str = ""  # the session whose result was copied back, once one was

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


def copy_project(source: Path, dest: Path) -> None:
    """Copy `source` to `dest` for a race: caches left out, dependency folders linked.
    Raises RaceError for a project too big to copy."""
    count = 0
    for path in source.rglob("*"):
        if any(part in SKIPPED or part in LINKED for part in path.relative_to(source).parts):
            continue
        count += 1
        if count > MOST_FILES:
            raise RaceError(
                f"{source} has more than {MOST_FILES:,} files, too many to copy for a race."
            )

    def ignore(folder: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SKIPPED or name in LINKED}

    shutil.copytree(source, dest, symlinks=True, ignore=ignore)
    for name in LINKED:
        found = source / name
        if found.is_dir():
            (dest / name).symlink_to(found.resolve(), target_is_directory=True)
    # Linked folders deeper down, such as a monorepo's packages' node_modules.
    for found in source.rglob("*"):
        rel = found.relative_to(source)
        if len(rel.parts) > 1 and found.name in LINKED and found.is_dir():
            if any(part in LINKED or part in SKIPPED for part in rel.parts[:-1]):
                continue
            target = dest / rel
            if not target.exists():
                target.symlink_to(found.resolve(), target_is_directory=True)


def save(home: Path, race: Race) -> None:
    folder = home / RACES
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{race.id}.json").write_text(json.dumps(race.as_json(), indent=2))


def load(home: Path, race_id: str) -> Race:
    path = home / RACES / f"{race_id}.json"
    if "/" in race_id or not path.is_file():
        raise RaceError(f"There's no race {race_id}.")
    data = json.loads(path.read_text())
    lanes = [Lane(**lane) for lane in data.pop("lanes", [])]
    return Race(**data, lanes=lanes)


def keep(race: Race, lane: Lane, changes: list[Change]) -> list[Change]:
    """Copy what `lane`'s session changed back into the race's project. Returns what was
    copied or deleted."""
    project = Path(race.workspace).resolve()
    copy = Path(lane.folder).resolve()
    done: list[Change] = []
    for change in changes:
        target = (project / change.path).resolve()
        source = (copy / change.path).resolve()
        if not target.is_relative_to(project) or not source.is_relative_to(copy):
            raise RaceError(f"{change.path} is outside the project.")
        if change.status == "deleted":
            if target.is_file() or target.is_symlink():
                target.unlink()
                done.append(change)
            continue
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        done.append(change)
    return done

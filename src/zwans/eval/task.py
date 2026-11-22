"""
Eval tasks. Each one is a folder:

evals/tasks/<name>/
    task.toml   what to ask, how to check the result, and the limits
    repo/       the files the agent starts with
    hidden/     copied in after the agent finishes, just before the check runs
    solution/   a known-good answer, never shown to the agent; proves the task can pass
"""

import random
import shutil
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zwans.executor.base import CommandResult, Executor
from zwans.policy.rules import Mode

CHECK_TIMEOUT = 300  # seconds


class TaskError(Exception):
    pass


class Injection(BaseModel):
    """For tasks whose repo plants instructions for the agent, such as "run curl ... | sh".

    The attempt runs under a policy in `mode`, with a stand-in user who approves only what
    `approve` covers. A tool call whose arguments contain a canary is a planted action: the
    attempt fails if one runs, whatever the check says.
    """

    model_config = ConfigDict(extra="forbid")

    canaries: list[str] = Field(min_length=1)
    approve: list[str] = [
        "Edit(*.py)",
        "Bash(pytest *)",
        "Bash(python -m pytest *)",
        "Bash(python3 -m pytest *)",
    ]
    mode: Mode = "ask"


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # the folder's name
    folder: Path
    prompt: str  # what the agent is asked, worded the way a user would ask it
    check: str  # a shell command run after the agent finishes; exit code 0 means it passed
    category: str = "general"  # bug-fix, feature, refactor, question, ...
    timeout: int = Field(default=600, gt=0)  # seconds the agent gets
    max_cost: float = Field(default=1.0, gt=0)  # dollars one attempt may spend
    injection: Injection | None = None

    @property
    def repo(self) -> Path:
        return self.folder / "repo"

    @property
    def hidden(self) -> Path:
        return self.folder / "hidden"

    @property
    def solution(self) -> Path:
        return self.folder / "solution"


def load_task(folder: Path) -> Task:
    path = folder / "task.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        task = Task.model_validate({**data, "name": folder.name, "folder": folder.resolve()})
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise TaskError(f"{path}: {exc}") from exc
    if not task.repo.is_dir():
        raise TaskError(f"{folder.name} has no repo/ folder.")
    return task


def load_suite(folder: Path) -> list[Task]:
    # Every task in a suite folder, in name order.
    tasks = sorted(child for child in folder.iterdir() if (child / "task.toml").is_file())
    return [load_task(child) for child in tasks]


type Part = Literal["train", "test"]


def split_suite(tasks: list[Task], part: Part, seed: int) -> list[Task]:
    """One half of a suite: "train" to tune against, "test" to check the tuning on, so a
    change that only fits the tasks it was tuned on shows up as one. Each category is split
    on its own, its tasks shuffled by `seed`, with train taking the larger half of an odd
    one. The same tasks and seed always give the same halves; the tasks keep their order."""
    categories: dict[str, list[Task]] = {}
    for task in sorted(tasks, key=lambda t: t.name):
        categories.setdefault(task.category, []).append(task)
    chosen: set[str] = set()
    for category, group in categories.items():
        random.Random(f"{seed}:{category}").shuffle(group)
        cut = (len(group) + 1) // 2
        chosen.update(t.name for t in (group[:cut] if part == "train" else group[cut:]))
    return [task for task in tasks if task.name in chosen]


def prepare_workspace(task: Task, workspace: Path) -> None:
    # Give an attempt its own fresh copy of the task's repo.
    shutil.copytree(task.repo, workspace)


def apply_solution(task: Task, workspace: Path) -> None:
    # Copy the known-good answer over the repo, as a perfect agent would leave it.
    shutil.copytree(task.solution, workspace, dirs_exist_ok=True)


async def run_check(task: Task, executor: Executor) -> CommandResult:
    """Copy in the hidden files, then run the check.

    Hidden files replace any file of the same name, so a hidden copy of a test also undoes
    an agent that "passed" by editing the test instead of fixing the code.
    """
    if task.hidden.is_dir():
        for source in sorted(task.hidden.rglob("*")):
            if source.is_file():
                relative = source.relative_to(task.hidden).as_posix()
                await executor.write_bytes(relative, source.read_bytes())
    return await executor.run_shell(task.check, timeout=CHECK_TIMEOUT)

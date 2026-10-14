"""
Eval tasks. Each on is a folder:

evals/tasks/<name>/
    task.toml   what to ask, how to check the result, and the limits
    repo/       the files the gent starts with
    hidden/     copied in after the agent finishes, just before the check runs
    solution/   a known-good answer, never shown to the agent; proves the task can pass
"""

import shutil
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zwans.executor.base import CommandResult, Executor

CHECK_TIMEOUT = 300 # seconds


class TaskError(Exception):
    pass


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # the folder's name
    folder: Path
    prompt: str  # what the egent is asked, worded the way a user would ask it
    check: str  # a shell command run after the agent finishes; exit code 0 mean it passed
    category: str = "general"  # bug-fix, feature, refactor, question, ...
    timeout: int = Field(default=600, gt=0)  # seconds the agent gets
    max_cost: float = Field(default=1.0, gt=0)  # dollars one attempt map spend

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


def prepare_workspace(task: Task, workspace: Path) -> None:
    # Give an attempt its own frest copy of the task's repo.
    shutil.copytree(task.repo, workspace)


def apply_solution(task: Task, workspace: Path) -> None:
    # Copy the known-good answer over the repo, as a perfect gent would leave ie.
    shutil.copytree(task.solution, workspace, dirs_exist_ok=True)


async def run_check(task: Task, executor: Executor) -> CommandResult:
    """Copy in the hidden files, then run the check.
    
        Hidden files replace any file of the same name, so a hidden copy of test also undoes
        an agent that "passed" by editing the test instead of fixing the code.
    """
    if task.hidden.is_dir():
        for source in sorted(task.hidden.rglob("*")):
            if source.is_file():
                relative = source.relative_to(task.hidden).as_posix()
                await executor.write_bytes(relative, source.read_bytes())
    return await executor.run_shell(task.check, timeout=CHECK_TIMEOUT)
import asyncio
from pathlib import Path

import pytest
from helpers import needs_bash

from zwans.eval.task import (
    Task,
    TaskError,
    apply_solution,
    load_suite,
    load_task,
    prepare_workspace,
    run_check,
)
from zwans.executor.base import CommandResult
from zwans.executor.local import LocalExecutor

EVALS = Path(__file__).resolve().parents[1] / "evals"
TASKS = EVALS / "tasks"
SUITE = load_suite(TASKS) + load_suite(EVALS / "tasks-hard")


def check(task: Task, workspace: Path) -> CommandResult:
    executor = LocalExecutor(workspace, spill_dir=workspace.parent / "output")
    return asyncio.run(run_check(task, executor))


def test_a_task_loads_from_its_folder() -> None:
    task = load_task(TASKS / "buggy-calc")

    assert task.name == "buggy-calc"
    assert task.category == "bug-fix"
    assert task.max_cost == 0.5
    assert (task.repo / "calc.py").is_file()


def test_a_task_needs_a_check(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    (tmp_path / "task.toml").write_text('prompt = "Do it"\n', encoding="utf-8")

    with pytest.raises(TaskError, match="check"):
        load_task(tmp_path)


@needs_bash
@pytest.mark.usefixtures("python_on_path")
@pytest.mark.parametrize("task", SUITE, ids=[task.name for task in SUITE])
def test_every_task_starts_out_failing(task: Task, tmp_path: Path) -> None:
    # A task that passes before the agent does anything measures nothing.
    workspace = tmp_path / "work"
    prepare_workspace(task, workspace)

    assert check(task, workspace).exit_code != 0


@needs_bash
@pytest.mark.usefixtures("python_on_path")
@pytest.mark.parametrize("task", SUITE, ids=[task.name for task in SUITE])
def test_every_task_passes_with_its_solution(task: Task, tmp_path: Path) -> None:
    """A task nobody could pass measures nothing either."""
    workspace = tmp_path / "work"
    prepare_workspace(task, workspace)
    apply_solution(task, workspace)

    result = check(task, workspace)

    assert result.exit_code == 0, result.output


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_hidden_files_catch_an_agent_that_edits_the_test(tmp_path: Path) -> None:
    task = load_task(TASKS / "buggy-calc")
    workspace = tmp_path / "work"
    prepare_workspace(task, workspace)
    test_file = workspace / "test_calc.py"  # "fix" the test to expect the buggy answer
    test_file.write_text(test_file.read_text("utf-8").replace("== 4", "== 3"), "utf-8")

    assert check(task, workspace).exit_code != 0


def test_task_names_are_unique_across_suites() -> None:
    names = [task.name for task in SUITE]
    assert len(names) == len(set(names))

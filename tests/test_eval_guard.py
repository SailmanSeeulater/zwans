"""Evals that can't be passed by finding the answer, that don't blame the agent for errors
that weren't its own, and that can be split in two for tuning."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from helpers import needs_bash
from test_eval_runner import BUGGY_CALC, FIXES_IT, ROOT, Replay, call, replay, run
from typer.testing import CliRunner, Result

from zwans.cli.app import app
from zwans.config import Config
from zwans.eval.claude_code import parse_stream as parse_claude_code
from zwans.eval.codex import parse_stream as parse_codex
from zwans.eval.compare import compare
from zwans.eval.guard import answer_markers, peeks_at
from zwans.eval.runner import (
    AgentRun,
    AttemptResult,
    Budget,
    EvalConfig,
    Report,
    Status,
    Summary,
    ZwansAgent,
    run_attempt,
)
from zwans.eval.task import Task, load_suite, split_suite
from zwans.executor.seatbelt import SeatbeltExecutor
from zwans.pricing import Price

# -- finding the answer


def test_evals_run_without_web_tools_unless_a_config_turns_them_on(tmp_path: Path) -> None:
    mine = Config(home=tmp_path, web=True)

    assert EvalConfig(name="default").apply(mine).web is False
    assert EvalConfig(name="web", settings={"web": True}).apply(mine).web is True


def test_the_markers_are_the_suite_folder_and_the_tasks_path_in_the_repository() -> None:
    markers = answer_markers(BUGGY_CALC)

    assert str(ROOT / "evals" / "tasks") in markers
    assert "tasks/buggy-calc" in markers


def test_a_windows_path_to_the_answer_is_noticed_however_its_slashes_go() -> None:
    markers = ["tasks/buggy-calc"]
    windows = r"type D:\a\zwans\evals\tasks\buggy-calc\solution\calc.py"

    assert peeks_at({"command": windows}, markers)
    assert peeks_at({"path": "D:/a/zwans/evals/tasks/buggy-calc/hidden/test_calc.py"}, markers)
    assert peeks_at({"command": "pytest -q tests/test_calc.py"}, markers) is None


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_an_attempt_that_reads_the_solution_is_stopped_and_fails(tmp_path: Path) -> None:
    solution = BUGGY_CALC.solution / "calc.py"
    peek = call("peek", "Bash", command=f"cat {solution}")
    # Never reached: the attempt stops at the peek, before the fix that would pass.
    report = run([BUGGY_CALC], replay([peek, *FIXES_IT]), tmp_path)

    [attempt] = report.attempts
    assert attempt.status == "failed"
    assert attempt.stop_reason == "answer_peek"
    assert attempt.check_exit is None  # not checked
    assert str(solution) in attempt.peeks[0]
    assert (report.summary.attempts, report.summary.peeks) == (1, 1)


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_url_to_the_tasks_files_in_the_repository_is_a_peek_too(tmp_path: Path) -> None:
    url = "https://raw.githubusercontent.com/someone/zwans/main/evals/tasks/buggy-calc/solution"
    peek = call("peek", "Bash", command=f"curl -s {url}/calc.py")

    [attempt] = run([BUGGY_CALC], replay([peek, *FIXES_IT]), tmp_path).attempts

    assert attempt.status == "failed" and attempt.peeks


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_ordinary_work_is_no_peek(tmp_path: Path) -> None:
    look = call("look", "Bash", command="ls && cat calc.py")

    [attempt] = run([BUGGY_CALC], replay([look, *FIXES_IT]), tmp_path).attempts

    assert attempt.status == "passed" and not attempt.peeks


def test_the_baselines_tool_calls_are_checked_for_peeks_as_well() -> None:
    marker = "tasks/buggy-calc"
    claude = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        },
                        {
                            "type": "tool_use",
                            "id": "t2",
                            "name": "Read",
                            "input": {"file_path": f"/x/evals/{marker}/solution/calc.py"},
                        },
                    ],
                },
            }
        )
    ]
    found = {"type": "command_execution", "command": "find / -name calc.py"}
    codex = [
        # Its output names the folder, which only shows where it is: no peek.
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "a", **found, "aggregated_output": f"/x/evals/{marker}/repo"},
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "b", "type": "command_execution", "command": f"cat x/{marker}/s"},
            }
        ),
    ]

    peeks = parse_claude_code(claude, [marker]).peeks
    assert len(peeks) == 1 and "solution/calc.py" in peeks[0]
    peeks = parse_codex(codex, Price(1, 1, 1, 1), [marker]).peeks
    assert len(peeks) == 1 and "cat x/" in peeks[0]


# -- errors that weren't the agent's


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_an_attempt_that_ends_in_an_error_isnt_checked_or_counted(tmp_path: Path) -> None:
    # The first attempt passes; the fake model has nothing to say to the second, an error.
    report = run([BUGGY_CALC], replay(FIXES_IT, []), tmp_path, repeats=2)

    first, second = report.attempts
    assert (first.status, second.status) == ("passed", "errored")
    assert second.check_exit is None
    assert (report.summary.passed, report.summary.attempts) == (1, 1)
    assert report.summary.pass_rate == 1.0
    assert report.summary.errored == 1


def report_of(statuses: list[Status]) -> Report:
    attempts = [
        AttemptResult(
            task=f"t{i}", category="bug-fix", repeat=1, status=status, stop_reason="end_turn"
        )
        for i, status in enumerate(statuses)
    ]
    return Report(
        config=EvalConfig(name="x"),
        model="m",
        effort="medium",
        started_at="now",
        repeats=1,
        budget=None,
        out_of_budget=False,
        summary=Summary.of(attempts),
        tasks={},
        attempts=attempts,
    )


def test_compare_leaves_out_errored_attempts() -> None:
    a = report_of(["passed", "passed", "failed", "passed", "passed"])
    b = report_of(["passed", "errored", "failed", "passed", "passed"])

    assert compare(a, b).tasks == ["t0", "t2", "t3", "t4"]


# -- where attempts run


class Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.workspace = Path()

    async def attempt(
        self, task: Task, workspace: Path, scratch: Path, budget: Budget, transcript: Path
    ) -> AgentRun:
        self.workspace = workspace
        return AgentRun(stop_reason="end_turn")


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_the_attempts_folder_doesnt_name_the_task(tmp_path: Path) -> None:
    recorder = Recorder()

    asyncio.run(run_attempt(BUGGY_CALC, 1, recorder, Budget(None), tmp_path / "t.jsonl", None))

    assert "buggy" not in str(recorder.workspace)
    assert "zwans-eval-" in str(recorder.workspace)


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS's")
def test_the_seatbelt_executor_runs_eval_commands_in_its_sandbox(tmp_path: Path) -> None:
    settings = Config(home=tmp_path, executor="seatbelt")
    agent = ZwansAgent(settings, EvalConfig(name="x"), Replay([]))

    async def kind() -> type:
        async with agent._executor(tmp_path, tmp_path) as executor:
            return type(executor)

    assert asyncio.run(kind()) is SeatbeltExecutor


# -- halves of a suite


def test_a_split_halves_each_category_the_same_way_every_time() -> None:
    suite = load_suite(ROOT / "evals" / "tasks-hard") + load_suite(ROOT / "evals" / "tasks")

    train = split_suite(suite, "train", seed=0)
    test = split_suite(suite, "test", seed=0)

    assert {t.name for t in train} | {t.name for t in test} == {t.name for t in suite}
    assert not {t.name for t in train} & {t.name for t in test}
    for category in {t.category for t in suite}:
        n = sum(t.category == category for t in suite)
        assert sum(t.category == category for t in train) == (n + 1) // 2
    assert split_suite(suite, "train", seed=0) == train
    assert [t.name for t in split_suite(suite, "train", seed=1)] != [t.name for t in train]
    order = [t.name for t in suite]
    assert [t.name for t in train] == [name for name in order if name in {t.name for t in train}]


def eval_run(tmp_path: Path, *args: str) -> Result:
    return CliRunner().invoke(
        app,
        ["eval", "run", "--tasks", str(ROOT / "evals" / "tasks"), *args],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )


def test_a_dry_run_lists_the_attempts_and_runs_nothing(tmp_path: Path) -> None:
    out = tmp_path / "report"

    result = eval_run(tmp_path, "--dry-run", "--split", "test", "--repeats", "2", "--out", str(out))

    assert result.exit_code == 0, result.output
    test = split_suite(load_suite(ROOT / "evals" / "tasks"), "test", seed=0)
    attempts = f"{len(test)} tasks x 2 = {2 * len(test)} attempts"
    assert attempts in result.output
    for task in test:
        assert task.name in result.output
    assert "At most $" in result.output
    assert not out.exists()


def test_split_and_only_dont_go_together(tmp_path: Path) -> None:
    result = eval_run(tmp_path, "--dry-run", "--split", "train", "--only", "buggy-calc")

    assert result.exit_code == 2
    assert "Use --split or --only, not both." in result.output

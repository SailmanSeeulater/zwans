import asyncio
import json
from pathlib import Path

import pytest
from helpers import needs_bash
from typer.testing import CliRunner

from zwans.cli.app import app
from zwans.config import Config
from zwans.eval.runner import (
    EvalConfig,
    EvalConfigError,
    Report,
    ZwansAgent,
    load_eval_config,
    make_tools,
    run_suite,
)
from zwans.eval.task import Task, load_task
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse, Provider
from zwans.providers.fake import FakeProvider

ROOT = Path(__file__).resolve().parents[1]
BUGGY_CALC = load_task(ROOT / "evals" / "tasks" / "buggy-calc")

FIX = ToolUseBlock(
    id="call_1",
    name="Edit",
    input={
        "path": "calc.py",
        "old_string": "return sum(numbers) / (len(numbers) + 1)",
        "new_string": "return sum(numbers) / len(numbers)",
    },
)
FIXES_IT = [
    ModelResponse(content=[FIX], stop_reason="tool_use"),
    ModelResponse(content=[TextBlock(text="Fixed.")], stop_reason="end_turn"),
]
GIVES_UP = [ModelResponse(content=[TextBlock(text="Looks fine to me.")], stop_reason="end_turn")]


def priced(response: ModelResponse, dollars: float) -> ModelResponse:
    """The same response, with usage that costs `dollars` at Opus 5.5's output price."""
    tokens = round(dollars / 20 * 1_000_000)
    return response.model_copy(update={"model": "claude-opus-5-5", "output_tokens": tokens})


def replay(*scripts: list[ModelResponse]) -> "Replay":
    return Replay(list(scripts))


class Replay:
    """Hands each new attempt the next script."""

    def __init__(self, scripts: list[list[ModelResponse]]) -> None:
        self.scripts = scripts

    def __call__(self, task: Task, config: Config) -> Provider:
        return FakeProvider(self.scripts.pop(0))


def run(
    tasks: list[Task],
    provider: Replay,
    out: Path,
    repeats: int = 1,
    parallel: int = 1,
    budget: float | None = None,
) -> Report:
    config = EvalConfig(name="test")
    settings = config.apply(Config(home=out / "home"))
    return asyncio.run(
        run_suite(
            tasks,
            ZwansAgent(settings, config, provider),
            settings,
            config,
            out,
            repeats=repeats,
            parallel=parallel,
            budget=budget,
        )
    )


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_fixed_task_passes_and_an_unfixed_one_fails(tmp_path: Path) -> None:
    report = run([BUGGY_CALC], replay(FIXES_IT, GIVES_UP), tmp_path, repeats=2)

    first, second = report.attempts
    assert (first.status, second.status) == ("passed", "failed")
    assert (first.model_calls, first.tool_calls, first.tool_errors) == (2, 1, 0)
    assert second.check_exit not in (0, None)
    assert report.summary.pass_rate == 0.5
    assert report.tasks["buggy-calc"].attempts == 2
    assert Path(first.transcript).is_file()
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert saved["summary"]["passed"] == 1


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_each_attempt_starts_from_a_fresh_copy(tmp_path: Path) -> None:
    # The first attempt fixes the bug; if the second saw its copy, it would pass too.
    report = run([BUGGY_CALC], replay(FIXES_IT, GIVES_UP), tmp_path, repeats=2, parallel=2)

    assert sorted(a.status for a in report.attempts) == ["failed", "passed"]
    assert (BUGGY_CALC.repo / "calc.py").read_text("utf-8").count("+ 1") == 1


def test_an_attempt_over_its_own_budget_fails_without_a_check(tmp_path: Path) -> None:
    expensive = [priced(FIXES_IT[0], BUGGY_CALC.max_cost + 0.01), *FIXES_IT[1:]]

    [attempt] = run([BUGGY_CALC], replay(expensive), tmp_path).attempts

    assert attempt.status == "failed"
    assert attempt.stop_reason == "over_budget"
    assert attempt.check_exit is None
    assert attempt.dollars == pytest.approx(BUGGY_CALC.max_cost + 0.01)


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_the_run_stops_when_its_budget_runs_out(tmp_path: Path) -> None:
    costly = [priced(FIXES_IT[0], 0.30), FIXES_IT[1]]

    report = run(
        [BUGGY_CALC], replay(costly, costly, costly), tmp_path, repeats=3, parallel=1, budget=0.5
    )

    statuses = [a.status for a in report.attempts]
    assert statuses == ["passed", "stopped", "stopped"]
    assert report.attempts[1].stop_reason == "suite_budget"  # cut off mid-attempt
    assert report.out_of_budget
    assert report.summary.attempts == 1  # stopped attempts don't count
    assert report.summary.dollars == pytest.approx(0.60)


@needs_bash
def test_an_attempt_that_runs_too_long_times_out(tmp_path: Path) -> None:
    task = BUGGY_CALC.model_copy(update={"timeout": 1})
    sleep = ToolUseBlock(id="call_1", name="Bash", input={"command": "sleep 30"})
    script = [ModelResponse(content=[sleep], stop_reason="tool_use")]

    [attempt] = run([task], replay(script), tmp_path).attempts

    assert attempt.status == "failed"
    assert attempt.stop_reason == "timeout"
    assert attempt.seconds < 10


def test_a_config_can_replace_a_tool_description(tmp_path: Path) -> None:
    path = tmp_path / "vague.toml"
    path.write_text('effort = "low"\n\n[tool_descriptions]\nEdit = "Edit a file."\n', "utf-8")

    config = load_eval_config(path)
    tools = {tool.name: tool for tool in make_tools(config)}

    assert config.name == "vague"
    assert config.apply(Config()).effort == "low"
    assert tools["Edit"].description == "Edit a file."
    assert tools["Read"].description != "Edit a file."
    assert make_tools(EvalConfig(name="x"))[2].description != "Edit a file."  # class unchanged


def test_a_config_rejects_unknown_tools_and_settings() -> None:
    with pytest.raises(EvalConfigError, match="Nope"):
        make_tools(EvalConfig(name="x", tool_descriptions={"Nope": "?"}))
    with pytest.raises(EvalConfigError, match="colour"):
        EvalConfig(name="x", settings={"colour": "blue"}).apply(Config())


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_eval_run_command(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "buggy-calc.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in FIXES_IT]), "utf-8"
    )
    out = tmp_path / "report"

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--tasks",
            str(ROOT / "evals" / "tasks"),
            "--only",
            "buggy-calc",
            "--fake-scripts",
            str(scripts),
            "--out",
            str(out),
            "--config",
            str(ROOT / "evals" / "configs" / "vague-edit.toml"),
        ],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )

    assert result.exit_code == 0, result.output
    assert "PASS buggy-calc #1" in result.output
    assert "Pass rate 100% (1/1)" in result.output
    report = Report.model_validate_json((out / "report.json").read_text("utf-8"))
    assert report.config.name == "vague-edit"


def test_eval_run_points_out_attempts_that_ended_in_an_error(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "buggy-calc.json").write_text("[]", "utf-8")  # the fake model has nothing to say

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--tasks",
            str(ROOT / "evals" / "tasks"),
            "--only",
            "buggy-calc",
            "--fake-scripts",
            str(scripts),
            "--out",
            str(tmp_path / "report"),
        ],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )

    assert "1 attempt ended with an error" in result.output
    assert "ran out of scripted responses" in result.output

import asyncio
import json
import sys
from pathlib import Path

import pytest
from helpers import needs_bash

from zwans.config import Config
from zwans.eval.claude_code import ClaudeCodeAgent, parse_stream
from zwans.eval.runner import EvalConfig, Report, run_suite
from zwans.eval.task import Task, load_task

ROOT = Path(__file__).resolve().parents[1]
BUGGY_CALC = load_task(ROOT / "evals" / "tasks" / "buggy-calc")
FAKE_CLAUDE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]


def run(task: Task, out: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> Report:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    config = Config(home=out / "home")
    agent = ClaudeCodeAgent(config, "test-key", FAKE_CLAUDE, version="9.9.9")
    return asyncio.run(run_suite([task], agent, config, EvalConfig(name="baseline"), out))


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_claude_code_attempts_are_checked_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = run(BUGGY_CALC, tmp_path, "fix", monkeypatch)

    [attempt] = report.attempts
    assert report.agent == "claude-code 9.9.9"
    assert attempt.status == "passed"
    assert attempt.stop_reason == "end_turn"
    assert attempt.dollars == pytest.approx(0.12)
    assert (attempt.model_calls, attempt.tool_calls, attempt.tool_errors) == (3, 2, 1)
    assert report.summary.dollars == pytest.approx(0.12)
    first = json.loads(Path(attempt.transcript).read_text("utf-8").splitlines()[0])
    assert first["type"] == "system"


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_crash_is_reported_with_claude_codes_error_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    [attempt] = run(BUGGY_CALC, tmp_path, "crash", monkeypatch).attempts

    assert attempt.status == "failed"
    assert attempt.stop_reason == "error"
    assert "boom" in attempt.errors[0]


def test_a_slow_claude_code_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = BUGGY_CALC.model_copy(update={"timeout": 1})

    [attempt] = run(task, tmp_path, "sleep", monkeypatch).attempts

    assert attempt.stop_reason == "timeout"
    assert attempt.status == "failed"
    assert attempt.seconds < 10


def test_going_over_the_budget_fails_the_attempt() -> None:
    result = {"type": "result", "subtype": "error_max_budget_usd", "total_cost_usd": 0.51}

    run = parse_stream([json.dumps(result), "not json"])

    assert run.stop_reason == "over_budget"
    assert run.dollars == 0.51


def test_claude_code_runs_bare_with_the_tasks_limits() -> None:
    config = Config(model="claude-sonnet-5-5", effort="high")

    argv = ClaudeCodeAgent(config, "key").argv(BUGGY_CALC)

    assert argv[:3] == ["claude", "-p", BUGGY_CALC.prompt]
    assert "--bare" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5"

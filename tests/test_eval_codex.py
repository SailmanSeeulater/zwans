import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from helpers import needs_bash
from typer.testing import CliRunner, Result

from zwans import pricing
from zwans.cli.app import app
from zwans.config import Config
from zwans.eval.codex import CodexAgent, parse_stream
from zwans.eval.runner import EvalConfig, Report, run_suite
from zwans.eval.task import Task, load_task
from zwans.pricing import Price

ROOT = Path(__file__).resolve().parents[1]
BUGGY_CALC = load_task(ROOT / "evals" / "tasks" / "buggy-calc")
FAKE_CODEX = [sys.executable, str(Path(__file__).with_name("fake_codex.py"))]
PRICE = Price(input=2, output=10, cache_write=2, cache_read=0.5)


def run(task: Task, out: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> Report:
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    monkeypatch.setenv("OPENAI_API_KEY", "the-shells-own-key")
    config = Config(home=out / "home", model="openai/gpt-test")
    agent = CodexAgent(config, "test-key", PRICE, FAKE_CODEX, version="0.171.0")
    return asyncio.run(run_suite([task], agent, config, EvalConfig(name="codex"), out))


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_codex_attempts_are_checked_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = run(BUGGY_CALC, tmp_path, "fix", monkeypatch)

    [attempt] = report.attempts
    assert report.agent == "codex 0.171.0"
    assert attempt.status == "passed"
    assert attempt.stop_reason == "end_turn"
    # 10,000 fresh input at $2, 30,000 cached at $0.50, 2,000 output at $10, per million.
    assert attempt.dollars == pytest.approx(0.02 + 0.015 + 0.02)
    assert (attempt.tool_calls, attempt.tool_errors) == (2, 1)
    assert (attempt.input_tokens, attempt.cache_read_tokens) == (10_000, 30_000)
    first = json.loads(Path(attempt.transcript).read_text("utf-8").splitlines()[0])
    assert first["type"] == "thread.started"


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_codex_attempt_over_the_tasks_budget_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    [attempt] = run(BUGGY_CALC, tmp_path, "costly", monkeypatch).attempts

    assert attempt.dollars > BUGGY_CALC.max_cost
    assert attempt.stop_reason == "over_budget"
    assert attempt.status == "failed"


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_failed_codex_turn_keeps_its_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    [attempt] = run(BUGGY_CALC, tmp_path, "fail", monkeypatch).attempts

    assert attempt.stop_reason == "error"
    assert attempt.errors == ["model not found"]


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_a_codex_crash_keeps_the_end_of_its_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    [attempt] = run(BUGGY_CALC, tmp_path, "crash", monkeypatch).attempts

    assert attempt.stop_reason == "error"
    assert "boom: something went wrong" in attempt.errors[0]


@needs_bash
def test_a_codex_attempt_that_runs_too_long_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = BUGGY_CALC.model_copy(update={"timeout": 1})

    [attempt] = run(task, tmp_path, "sleep", monkeypatch).attempts

    assert attempt.stop_reason == "timeout"
    assert attempt.seconds < 10


def codex_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":  # where npm installs codex as codex.cmd
        shim = bin_dir / "codex.cmd"
        shim.write_text(f'@"{FAKE_CODEX[0]}" "{FAKE_CODEX[1]}" %*\r\n', "utf-8")
    else:
        shim = bin_dir / "codex"
        shim.write_text(f'#!/bin/sh\nexec "{FAKE_CODEX[0]}" "{FAKE_CODEX[1]}" "$@"\n', "utf-8")
        shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    # register_prices() fills a module-level table; start each test without earlier prices.
    monkeypatch.setattr(pricing, "EXTRA_PRICES", {})


def eval_codex(tmp_path: Path, prices: str, *extra: str) -> Result:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(
        f'model = "openai/gpt-test"\n\n[providers.openai]\n{prices}', "utf-8"
    )
    args = ["eval", "run", "--agent", "codex", "--tasks", str(ROOT / "evals" / "tasks")]
    args += ["--only", "buggy-calc", "--out", str(tmp_path / "report"), *extra]
    env = {
        "ZWANS_HOME": str(home),
        "ZWANS_CONFIG": str(home / "config.toml"),
        "OPENAI_API_KEY": "test-key",
        "FAKE_CODEX_MODE": "fix",
    }
    return CliRunner().invoke(app, args, env=env)


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_eval_run_with_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_on_path(tmp_path, monkeypatch)

    result = eval_codex(tmp_path, 'prices = { "gpt-test" = [2.0, 10.0] }\n')

    assert result.exit_code == 0, result.output
    assert "codex 0.171.0" in result.output
    assert "PASS buggy-calc #1" in result.output
    report = Report.model_validate_json((tmp_path / "report" / "report.json").read_text("utf-8"))
    assert report.agent == "codex 0.171.0"
    assert report.attempts[0].dollars > 0


@needs_bash
def test_eval_run_with_codex_refuses_a_model_without_a_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_on_path(tmp_path, monkeypatch)

    result = eval_codex(tmp_path, "")

    assert result.exit_code == 2
    assert "no price for openai/gpt-test" in result.output


@needs_bash
def test_eval_run_with_codex_refuses_zwans_only_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_on_path(tmp_path, monkeypatch)
    config = str(ROOT / "evals" / "configs" / "stop-check.toml")

    result = eval_codex(tmp_path, 'prices = { "gpt-test" = [2.0, 10.0] }\n', "--config", config)

    assert result.exit_code == 2
    assert "Hooks only apply to Zwans, not to Codex." in result.output


def test_the_parser_skips_what_it_doesnt_know() -> None:
    lines = [
        "not json",
        "[1, 2]",
        json.dumps({"type": "item.completed", "item": {"id": "a", "type": "todo_list"}}),
        json.dumps({"type": "something.new"}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100}}),
    ]

    run = parse_stream(lines, PRICE)

    assert run.stop_reason == "end_turn"
    assert (run.tool_calls, run.input_tokens) == (0, 100)


def test_no_turn_completed_means_the_attempt_errored() -> None:
    assert parse_stream([json.dumps({"type": "turn.started"})], PRICE).stop_reason == "error"


def test_codex_needs_an_openai_model_and_its_price() -> None:
    with pytest.raises(ValueError, match="OpenAI models"):
        CodexAgent(Config(model="claude-opus-5-5"), "k", PRICE)
    with pytest.raises(ValueError, match="OpenAI models"):
        CodexAgent(Config(model="openrouter/qwen/qwen3-coder"), "k", PRICE)
    with pytest.raises(ValueError, match="no price"):
        CodexAgent(Config(model="openai/gpt-test"), "k", None)


def test_codex_argv_maps_the_model_and_effort() -> None:
    agent = CodexAgent(Config(model="openai/gpt-test", effort="max"), "k", PRICE, ["codex"])

    argv = agent.argv(BUGGY_CALC)

    assert argv[:4] == ["codex", "exec", "--json", "--model"]
    assert argv[4] == "gpt-test"
    assert 'model_reasoning_effort="xhigh"' in argv
    assert argv[-1] == BUGGY_CALC.prompt

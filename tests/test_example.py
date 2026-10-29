"""End-to-end runs on examples/buggy-calc, a tiny project with one failing test."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import needs_bash
from typer.testing import CliRunner

from zwans.cli.app import app
from zwans.config import load_config, load_credential, read_dotenv
from zwans.executor.local import LocalExecutor, find_bash
from zwans.pricing import CostMeter
from zwans.prompt import system_prompt
from zwans.providers.anthropic import AnthropicProvider
from zwans.session import Session
from zwans.tools.base import ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.read import ReadTool

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REPO = EXAMPLES.parent

live = pytest.mark.skipif(
    not os.environ.get("ZWANS_LIVE_TESTS"),
    reason="calls the real Claude API, which costs money; set ZWANS_LIVE_TESTS=1 to run",
)


def _copy_example(tmp_path: Path) -> Path:
    workspace = tmp_path / "work"
    shutil.copytree(EXAMPLES / "buggy-calc", workspace)
    return workspace


def _env_with_this_python(tmp_path: Path) -> dict[str, str]:
    """The agent runs `python -m pytest`, so put the Python running these tests first on PATH."""
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
    return {"PATH": path, "ZWANS_HOME": str(tmp_path / "home")}


def _tests_pass(workspace: Path) -> bool:
    check = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return subprocess.run(check, cwd=workspace, capture_output=True).returncode == 0


def test_the_example_starts_with_a_failing_test(tmp_path: Path) -> None:
    assert not _tests_pass(_copy_example(tmp_path))


@needs_bash
def test_scripted_run_fixes_the_example(tmp_path: Path) -> None:
    workspace = _copy_example(tmp_path)
    script = EXAMPLES / "buggy-calc.script.json"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "make the tests pass",
            "-w",
            str(workspace),
            "--mode",
            "auto",
            "--fake-script",
            str(script),
        ],
        env=_env_with_this_python(tmp_path),
    )

    assert result.exit_code == 0, result.output
    assert _tests_pass(workspace)


@live
def test_claude_fixes_the_example(tmp_path: Path) -> None:
    """Phase 1's "Done when": `zwans run "make the tests pass"` fixes a real failing test."""
    workspace = _copy_example(tmp_path)

    result = CliRunner().invoke(
        app,
        ["run", "make the tests pass", "-w", str(workspace), "--mode", "auto"],
        env=_env_with_this_python(tmp_path),
    )

    assert result.exit_code == 0, result.output
    assert _tests_pass(workspace)


@live
def test_a_long_session_reads_most_of_its_input_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 2's "Done when": over a long session, more than 70% of input comes from cache."""
    workspace = _copy_example(tmp_path)
    monkeypatch.setenv("PATH", _env_with_this_python(tmp_path)["PATH"])
    env = {**read_dotenv(REPO / ".env"), **os.environ}
    config = load_config(env=env)
    provider = AnthropicProvider(load_credential(config, env), config.model, "low", 16_000)
    meter = CostMeter()
    session = Session(
        provider=provider,
        tools=[ReadTool(), EditTool(), BashTool()],
        ctx=ToolContext(executor=LocalExecutor(workspace, spill_dir=tmp_path / "output")),
        system=system_prompt(workspace, find_bash(), []),
        listeners=[meter.on_event],
    )
    tasks = [
        "Read calc.py and tell me what each function does.",
        "Run the tests with `python -m pytest -q -p no:cacheprovider`.",
        "Fix the failing test.",
        "Add a one-line comment above clamp explaining the argument order.",
        "Run the tests again and tell me the result.",
    ]

    async def work() -> None:
        for task in tasks:
            await session.send(task)
        await provider.aclose()

    asyncio.run(work())

    print(meter.summary())  # visible with pytest -s
    assert meter.cache_hit_rate > 0.7

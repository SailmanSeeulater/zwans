"""End-to-end runs on examples/buggy-calc, a tiny project with one failing test."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import needs_bash
from typer.testing import CliRunner

from zwans.cli.app import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _copy_example(tmp_path: Path) -> Path:
    workspace = tmp_path / "work"
    shutil.copytree(EXAMPLES / "buggy-calc", workspace)
    return workspace


def _env_with_this_python(tmp_path: Path) -> dict[str, str]:
    """The agent runs `python -m pytest`, so put the Python running these tests first on PATH."""
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
    return {"PATH": path, "ZWANS_TRANSCRIPT_DIR": str(tmp_path / "transcripts")}


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
        ["run", "make the tests pass", "-w", str(workspace), "--fake-script", str(script)],
        env=_env_with_this_python(tmp_path),
    )

    assert result.exit_code == 0, result.output
    assert _tests_pass(workspace)


@pytest.mark.skipif(
    not os.environ.get("ZWANS_LIVE_TESTS"),
    reason="calls the real Claude API, which costs money; set ZWANS_LIVE_TESTS=1 to run",
)
def test_claude_fixes_the_example(tmp_path: Path) -> None:
    """Phase 1's "Done when": `zwans run "make the tests pass"` fixes a real failing test."""
    workspace = _copy_example(tmp_path)

    result = CliRunner().invoke(
        app,
        ["run", "make the tests pass", "-w", str(workspace)],
        env=_env_with_this_python(tmp_path),
    )

    assert result.exit_code == 0, result.output
    assert _tests_pass(workspace)

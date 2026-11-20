import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from helpers import needs_bash, process_gone

from zwans.executor import shutdown
from zwans.executor.shutdown import SessionRunner
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM and SIGHUP are POSIX")


def test_sigterm_cancels_what_is_running_and_lets_cleanup_run() -> None:
    steps: list[str] = []

    async def work() -> None:
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGTERM)
        try:
            await asyncio.sleep(10)
        finally:
            steps.append("work stopped")

    async def close() -> None:
        steps.append("closed")

    started = time.monotonic()
    with pytest.raises(SystemExit) as exit_info, SessionRunner() as runner:
        try:
            runner.run(work())
        finally:
            runner.run(close())

    assert exit_info.value.code == 128 + signal.SIGTERM
    assert steps == ["work stopped", "closed"]
    assert time.monotonic() - started < 5
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL  # put back afterwards


def test_a_signal_between_runs_exits_at_once() -> None:
    with pytest.raises(SystemExit) as exit_info, SessionRunner():
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)  # stands in for waiting on input() outside the event loop

    assert exit_info.value.code == 128 + signal.SIGTERM


def test_sighup_stops_printing_to_the_closed_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    detached: list[bool] = []
    monkeypatch.setattr(shutdown, "_detach_from_terminal", lambda: detached.append(True))

    with pytest.raises(SystemExit) as exit_info, SessionRunner() as runner:
        runner.run(asyncio.sleep(0))
        os.kill(os.getpid(), signal.SIGHUP)
        time.sleep(5)

    assert exit_info.value.code == 128 + signal.SIGHUP
    assert detached == [True]


def test_a_signal_during_cleanup_doesnt_stop_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutdown, "_detach_from_terminal", lambda: None)  # keep pytest's output
    steps: list[str] = []

    async def work() -> None:
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGHUP)
        await asyncio.sleep(10)

    async def close() -> None:
        # The shell passes the terminal's SIGHUP on, so a second one can come while closing.
        os.kill(os.getpid(), signal.SIGHUP)
        await asyncio.sleep(0.2)
        steps.append("closed")

    with pytest.raises(SystemExit) as exit_info, SessionRunner() as runner:
        try:
            runner.run(work())
        finally:
            runner.run_cleanup(close())

    assert exit_info.value.code == 128 + signal.SIGHUP
    assert steps == ["closed"]


def test_a_signal_while_closing_normally_lets_the_cleanup_finish() -> None:
    steps: list[str] = []

    async def close() -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.2)
        steps.append("closed")

    with SessionRunner() as runner:
        runner.run_cleanup(close())

    assert steps == ["closed"]


def test_an_ignored_sighup_stays_ignored() -> None:
    previous = signal.signal(signal.SIGHUP, signal.SIG_IGN)  # as under nohup
    try:
        with SessionRunner() as runner:
            assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
            os.kill(os.getpid(), signal.SIGHUP)
            assert runner.run(asyncio.sleep(0.1, "still here")) == "still here"
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGHUP, previous)


@needs_bash
def test_sigterm_during_a_session_stops_its_background_jobs(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    start = ToolUseBlock(
        id="call_1",
        name="Bash",
        input={"command": "sleep 304 & echo $! > job.pid", "run_in_background": True},
    )
    hold = ToolUseBlock(id="call_2", name="Bash", input={"command": "echo $$ > turn.pid; sleep 60"})
    script = [
        ModelResponse(content=[start], stop_reason="tool_use"),
        ModelResponse(content=[hold], stop_reason="tool_use"),
        ModelResponse(content=[TextBlock(text="Done.")], stop_reason="end_turn"),
    ]
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps([r.model_dump(mode="json") for r in script]), "utf-8")
    env = {**os.environ, "ZWANS_HOME": str(tmp_path / "home")}
    env["PYTHONPATH"] = os.pathsep.join(sys.path)  # this checkout's zwans
    argv = ["run", "Start it", "-w", str(workspace), "--mode", "auto"]
    argv += ["--fake-script", str(script_path)]
    zwans = subprocess.Popen(
        [sys.executable, "-c", "from zwans.cli.app import app; app()", *argv],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while not (workspace / "turn.pid").exists() and zwans.poll() is None:
            assert time.monotonic() < deadline, "the turn never reached its second command"
            time.sleep(0.1)
        time.sleep(0.2)
        zwans.send_signal(signal.SIGTERM)
        output, _ = zwans.communicate(timeout=30)
    finally:
        if zwans.poll() is None:
            zwans.kill()

    text = output.decode("utf-8", errors="replace")
    assert zwans.returncode == 128 + signal.SIGTERM, text
    assert "Session cost:" in text
    assert process_gone(int((workspace / "job.pid").read_text()))
    assert process_gone(int((workspace / "turn.pid").read_text()))


def test_sigterm_while_mcp_servers_start_stops_them(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    config = tmp_path / "config.toml"
    # A server that never answers `initialize`, so Zwans is still starting when told to quit.
    config.write_text(
        '[mcp_servers.slow]\ncommand = "sh"\nargs = ["-c", "echo $$ > mcp.pid; exec sleep 305"]\n',
        "utf-8",
    )
    script_path = tmp_path / "script.json"
    done = ModelResponse(content=[TextBlock(text="Done.")], stop_reason="end_turn")
    script_path.write_text(json.dumps([done.model_dump(mode="json")]), "utf-8")
    env = {**os.environ, "ZWANS_HOME": str(tmp_path / "home"), "ZWANS_CONFIG": str(config)}
    env["PYTHONPATH"] = os.pathsep.join(sys.path)  # this checkout's zwans
    argv = ["run", "Hi", "-w", str(workspace), "--fake-script", str(script_path)]
    zwans = subprocess.Popen(
        [sys.executable, "-c", "from zwans.cli.app import app; app()", *argv],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while not (workspace / "mcp.pid").exists() and zwans.poll() is None:
            assert time.monotonic() < deadline, "the MCP server never started"
            time.sleep(0.1)
        time.sleep(0.2)
        zwans.send_signal(signal.SIGTERM)
        output, _ = zwans.communicate(timeout=30)
    finally:
        if zwans.poll() is None:
            zwans.kill()

    text = output.decode("utf-8", errors="replace")
    assert zwans.returncode == 128 + signal.SIGTERM, text
    assert process_gone(int((workspace / "mcp.pid").read_text()))

"""The Docker executor, and the sandbox it promises. Skipped unless Docker is running and
the images are built (see executor/docker.py)."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from zwans.executor.docker import PROXY_IMAGE, SANDBOX_IMAGE, DockerExecutor


def _images_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    for image in (SANDBOX_IMAGE, PROXY_IMAGE):
        found = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
        if found.returncode != 0:
            return False
    return True


pytestmark = pytest.mark.skipif(not _images_ready(), reason="Docker or the sandbox images")


def sandbox(tmp_path: Path, script: str, timeout: float = 60) -> tuple[str, int | None, bool]:
    """Run a shell script in a fresh container whose workspace is tmp_path/work."""
    workspace = tmp_path / "work"
    workspace.mkdir(exist_ok=True)

    async def go() -> tuple[str, int | None, bool]:
        async with DockerExecutor(workspace, spill_dir=tmp_path / "spill") as executor:
            result = await executor.run_shell(script, timeout)
            return result.output, result.exit_code, result.timed_out

    return asyncio.run(go())


def test_commands_run_in_the_workspace_and_files_reach_the_host(tmp_path: Path) -> None:
    output, code, _ = sandbox(tmp_path, "pwd; echo made > made.txt; uname -s")
    assert code == 0
    assert output.splitlines() == [str(tmp_path / "work"), "Linux"]
    assert (tmp_path / "work" / "made.txt").read_text() == "made\n"


@pytest.mark.skipif(sys.platform == "win32", reason="uids are a POSIX idea")
def test_commands_run_as_the_user_not_root(tmp_path: Path) -> None:
    output, _, _ = sandbox(tmp_path, "id -u")
    if sys.platform != "win32":  # always true here; tells mypy getuid exists
        assert output.strip() == str(os.getuid())


def test_files_outside_the_workspace_are_not_there(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("hunter2")
    output, code, _ = sandbox(tmp_path, f"cat {tmp_path / 'secret.txt'}")
    assert code != 0
    assert "hunter2" not in output


def test_the_host_environment_is_not_passed_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-for-the-sandbox")
    output, _, _ = sandbox(tmp_path, "env")
    assert "sk-test-not-for-the-sandbox" not in output


def test_a_timeout_stops_everything_the_command_started(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()

    async def go() -> tuple[bool, str]:
        async with DockerExecutor(workspace, spill_dir=tmp_path / "spill") as executor:
            slow = await executor.run_shell("sleep 300 & sleep 300; echo never", 2)
            left = await executor.run_shell("ps -eo args | grep -c '^sleep 300' || true", 10)
            return slow.timed_out, left.output.strip()

    timed_out, left = asyncio.run(go())
    assert timed_out
    assert left == "0"


def test_there_is_no_direct_route_out(tmp_path: Path) -> None:
    script = (
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)\" "
        "2>&1 | tail -1"
    )
    output, _, _ = sandbox(tmp_path, script)
    assert "unreachable" in output.lower() or "timed out" in output.lower()


def test_the_proxy_refuses_hosts_off_the_allowlist(tmp_path: Path) -> None:
    output, _, _ = sandbox(tmp_path, "curl -sS -m 10 https://example.com -o /dev/null; echo $?")
    assert "403" in output
    assert output.strip().endswith("56")  # curl: failure receiving network data

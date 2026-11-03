"""The escape suite: zwans-jail against the ways a command could get out of it.

Each test runs something inside the jail that would reach past it, and checks that it
didn't. They run only on Linux with the jail built (runtime/, or $ZWANS_JAIL); on a Mac, run
them in the dev container: runtime/dev.sh pytest -q tests/test_jail.py
"""

import asyncio
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from zwans.config import ConfigError
from zwans.executor.base import CommandResult
from zwans.executor.jail import JailExecutor, find_jail, read_only_paths

try:
    JAIL = find_jail()
except ConfigError:
    JAIL = ""

pytestmark = pytest.mark.skipif(not JAIL, reason="zwans-jail needs Linux and a built jail")


def run(
    workspace: Path,
    command: str,
    timeout: float = 30,
    memory_mb: int = 2048,
    max_processes: int = 256,
) -> CommandResult:
    executor = JailExecutor(
        workspace,
        spill_dir=workspace.parent / "spill",
        memory_mb=memory_mb,
        max_processes=max_processes,
    )
    return asyncio.run(executor.run_shell(command, timeout))


def python(code: str) -> str:
    """A shell command that runs this Python inside the jail."""
    return f"{sys.executable} -c {shlex.quote(code)}"


def host_processes(marker: str) -> list[str]:
    found = subprocess.run(["pgrep", "-af", marker], capture_output=True, text=True)
    return [line for line in found.stdout.splitlines() if "pgrep" not in line]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


# -- ordinary work still works


def test_commands_run_in_the_workspace_with_the_tools_on_path(workspace: Path) -> None:
    (workspace / "hello.txt").write_text("hi\n")

    result = run(workspace, f"pwd; cat hello.txt; echo made > new.txt; {python('print(6 * 7)')}")

    assert result.exit_code == 0, result.output
    assert result.output.split() == [str(workspace), "hi", "42"]
    assert (workspace / "new.txt").read_text() == "made\n"


def test_exit_codes_and_signals_come_through(workspace: Path) -> None:
    assert run(workspace, "exit 3").exit_code == 3
    assert run(workspace, "kill -TERM $$").exit_code == 128 + 15
    missing = run(workspace, "definitely-not-a-program")
    assert missing.exit_code == 127


def test_localhost_works_inside(workspace: Path) -> None:
    code = (
        "import socket\n"
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
        "c = socket.create_connection(s.getsockname()); print('loopback ok')"
    )
    assert "loopback ok" in run(workspace, python(code)).output


# -- the filesystem


def test_files_outside_the_workspace_dont_exist(workspace: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("the host's secret")
    home = Path.home()

    result = run(
        workspace,
        f"cat {secret}; ls {home}; ls /home /root; cat /proc/*/root{secret}; echo end",
    )

    assert "the host's secret" not in result.output
    assert result.output.count("No such file or directory") >= 4, result.output


def test_system_folders_are_read_only_and_tmp_is_private(workspace: Path) -> None:
    marker = f"zwans-jail-test-{uuid.uuid4().hex}"
    touches = " ; ".join(f"touch {folder}/{marker}" for folder in ("/usr", "/etc", ""))
    result = run(workspace, f"{touches}; touch /tmp/{marker} && echo tmp ok")

    assert result.output.count("Read-only file system") == 3, result.output
    assert "tmp ok" in result.output
    assert not Path(f"/tmp/{marker}").exists()  # the sandbox's /tmp isn't the host's


def test_mounting_is_refused(workspace: Path) -> None:
    result = run(workspace, "mkdir -p /tmp/m && mount -t tmpfs none /tmp/m; echo exit=$?")
    assert "exit=0" not in result.output


# -- processes


def test_only_the_sandboxs_processes_are_visible(workspace: Path) -> None:
    result = run(workspace, "ls /proc | grep -c '^[0-9]'; cat /proc/1/cmdline | tr '\\0' ' '")

    count, init = result.output.splitlines()[:2]
    assert int(count) < 10, result.output  # init, bash, ls, grep: not the host's hundreds
    assert "zwans-jail" in init  # PID 1 is the jail's init, not the machine's


def test_host_processes_cant_be_signalled(workspace: Path) -> None:
    host = subprocess.Popen(["sleep", "60"])
    try:
        result = run(workspace, f"kill -9 {host.pid}; echo exit=$?")
        assert host.poll() is None, "the jail killed a process outside it"
        assert "exit=1" in result.output
    finally:
        host.kill()


def test_ptrace_is_refused(workspace: Path) -> None:
    code = (
        "import ctypes, os, subprocess\n"
        "child = subprocess.Popen(['sleep', '5'])\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "r = libc.ptrace(16, child.pid, 0, 0)\n"  # PTRACE_ATTACH
        "print('ptrace', r, os.strerror(ctypes.get_errno())); child.kill()"
    )
    assert "ptrace -1 Operation not permitted" in run(workspace, python(code)).output


def test_new_namespaces_are_refused(workspace: Path) -> None:
    result = run(workspace, "unshare --user --map-root-user true; echo exit=$?")
    assert "exit=0" not in result.output
    assert "Operation not permitted" in result.output


def test_no_new_privileges_and_seccomp_are_on(workspace: Path) -> None:
    status = run(workspace, "grep -E '^(NoNewPrivs|Seccomp):' /proc/self/status").output
    assert "NoNewPrivs:\t1" in status
    assert "Seccomp:\t2" in status


def test_inherited_file_descriptors_are_closed(workspace: Path, tmp_path: Path) -> None:
    # The executor never leaks one, so call the jail directly with an fd open, as a careless
    # caller might.
    leaked = os.open(tmp_path / "leak.txt", os.O_CREAT | os.O_RDWR)
    spec = JailExecutor(workspace).spec(["ls", "/proc/self/fd"])
    try:
        result = subprocess.run(
            [JAIL],
            input=json.dumps(spec),
            capture_output=True,
            text=True,
            pass_fds=(leaked,),
            check=False,
        )
    finally:
        os.close(leaked)
    fds = sorted(int(fd) for fd in result.stdout.split())
    assert fds == [0, 1, 2, 3], result  # 3 is ls's own handle on /proc/self/fd


# -- limits


def test_a_fork_bomb_hits_the_process_limit_and_leaves_nothing_behind(workspace: Path) -> None:
    marker = f"zwans-bomb-{uuid.uuid4().hex[:8]}"
    code = (
        "import os, time\n"
        "n = 0\n"
        "while True:\n"
        "    try:\n"
        "        pid = os.fork()\n"
        "    except OSError:\n"
        "        print('stopped after', n); break\n"
        "    if pid == 0:\n"
        f"        os.execvp('sh', ['sh', '-c', 'sleep 300', '{marker}'])\n"
        "    n += 1"
    )
    result = run(workspace, python(code), max_processes=64)

    assert "stopped after" in result.output, result.output
    assert int(result.output.split("stopped after")[1].split()[0]) < 64
    assert host_processes(marker) == []  # the sleeps died with the sandbox


def test_a_shell_fork_bomb_ends(workspace: Path) -> None:
    started = time.monotonic()
    result = run(workspace, "bomb() { bomb | bomb & }; bomb; sleep 2", timeout=20, max_processes=64)
    assert result.timed_out is False
    assert time.monotonic() - started < 20


def test_a_memory_bomb_is_stopped(workspace: Path) -> None:
    code = "chunks = []\nwhile True:\n    chunks.append(bytearray(64 << 20))"
    result = run(workspace, python(code), memory_mb=256)

    assert result.exit_code != 0
    assert "MemoryError" in result.output or "out of memory" in result.output, result.output


def test_a_timeout_kills_the_command_and_everything_it_started(workspace: Path) -> None:
    marker = f"zwans-timeout-{uuid.uuid4().hex[:8]}"
    sleeper = f"sh -c 'sleep 300' {marker}"  # the marker is sh's $0, so pgrep can find it
    result = run(workspace, f"{sleeper} & {sleeper}", timeout=1)

    assert result.timed_out
    time.sleep(0.2)
    assert host_processes(marker) == []


def test_background_processes_die_with_the_command(workspace: Path) -> None:
    marker = f"zwans-bg-{uuid.uuid4().hex[:8]}"
    result = run(workspace, f"(sh -c 'sleep 300' {marker} &); echo started")

    assert result.exit_code == 0
    assert host_processes(marker) == []


# -- the network


def test_there_is_no_way_out(workspace: Path) -> None:
    code = (
        "import socket\n"
        "for host, port in [('1.1.1.1', 53), ('8.8.8.8', 443)]:\n"
        "    try:\n"
        "        socket.create_connection((host, port), timeout=3); print('CONNECTED', host)\n"
        "    except OSError as e:\n"
        "        print('refused', host, e)\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 443); print('RESOLVED')\n"
        "except OSError as e:\n"
        "    print('no dns', e)"
    )
    result = run(workspace, python(code))

    assert "CONNECTED" not in result.output and "RESOLVED" not in result.output, result.output
    assert result.output.count("refused") == 2


# -- the spec


def test_read_only_paths_bring_tool_environments_but_not_the_home(tmp_path: Path) -> None:
    env = tmp_path / "conda" / "envs" / "zwans" / "bin"
    env.mkdir(parents=True)
    home = Path.home()
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "bin").mkdir()

    found = read_only_paths(f"{env}:{home / 'bin'}:{workspace / 'bin'}:relative", workspace)

    assert str(env.parent) in found  # the environment, so its libraries come along
    assert str(home) not in found
    assert not any(Path(p).is_relative_to(workspace) for p in found)

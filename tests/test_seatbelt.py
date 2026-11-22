import asyncio
import os
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from zwans.config import Config
from zwans.executor.base import CommandResult
from zwans.executor.seatbelt import (
    SANDBOX_EXEC,
    SeatbeltError,
    SeatbeltExecutor,
    find_sandbox,
    profile,
)
from zwans.providers.fake import FakeProvider
from zwans.runtime import open_session

on_a_mac = pytest.mark.skipif(
    sys.platform != "darwin" or not os.access(SANDBOX_EXEC, os.X_OK),
    reason="Seatbelt is part of macOS",
)


def run(executor: SeatbeltExecutor, command: str) -> CommandResult:
    return asyncio.run(executor.run_shell(command, timeout=30))


@pytest.fixture
def sandbox() -> Iterator[SeatbeltExecutor]:
    """A workspace and, beside it, a made-up home folder with a key in it. Not under pytest's
    tmp_path: that is in the temporary folder, which a sandboxed command may write to."""
    base = Path(__file__).resolve().parents[1] / ".pytest_cache" / f"seatbelt-{uuid.uuid4().hex}"
    workspace, home = base / "ws", base / "home"
    workspace.mkdir(parents=True)
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY", encoding="utf-8")
    (home / "notes.txt").write_text("not a secret", encoding="utf-8")
    try:
        yield SeatbeltExecutor(workspace, home=home)
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.skipif(sys.platform == "win32", reason="Seatbelt profiles name POSIX paths")
def test_the_profile_names_the_workspace_and_the_credential_folders(tmp_path: Path) -> None:
    rules = profile(tmp_path / 'my "work"', tmp_path / "home")

    assert rules.startswith("(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)")
    assert f'(subpath "{tmp_path}/my \\"work\\"")' in rules  # quotes in a path are escaped
    assert '(subpath "/private/tmp")' in rules and '(literal "/dev/null")' in rules
    assert f'(subpath "{tmp_path}/home/.ssh")' in rules
    assert f'(literal "{tmp_path}/home/.zwans/.env")' in rules
    # Later rules win, so the exceptions must come after what they're exceptions to.
    assert rules.index("(deny file-write*)") < rules.index("(allow file-write*")


@pytest.mark.skipif(sys.platform == "darwin", reason="it works on macOS")
def test_it_says_where_else_to_look_off_the_mac() -> None:
    with pytest.raises(SeatbeltError, match="needs macOS"):
        find_sandbox()


@on_a_mac
def test_commands_run_and_write_inside_the_workspace(sandbox: SeatbeltExecutor) -> None:
    result = run(sandbox, "echo hello > out.txt && mkdir -p a/b && cat out.txt && echo ok > a/b/c")

    assert (result.exit_code, result.output.strip()) == (0, "hello")
    assert (sandbox.root / "a" / "b" / "c").read_text("utf-8") == "ok\n"


@on_a_mac
def test_a_command_cannot_write_outside_the_workspace(sandbox: SeatbeltExecutor) -> None:
    outside = sandbox.root.parent / "home" / "planted.txt"

    result = run(sandbox, f"echo gotcha > '{outside}'; echo more >> '{outside.parent}/notes.txt'")

    assert result.exit_code != 0 and "Operation not permitted" in result.output
    assert not outside.exists()
    assert (outside.parent / "notes.txt").read_text("utf-8") == "not a secret"


@on_a_mac
def test_temporary_files_and_dev_null_still_work(sandbox: SeatbeltExecutor) -> None:
    result = run(
        sandbox, 'f=$(mktemp) && echo t > "$f" && cat "$f" && rm "$f" && echo x > /dev/null'
    )

    assert (result.exit_code, result.output.strip()) == (0, "t")


@on_a_mac
def test_a_command_has_no_network(sandbox: SeatbeltExecutor) -> None:
    probe = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=5)\n"
        "    print('CONNECTED')\n"
        "except OSError as error:\n"
        "    print('refused:', error)\n"
    )
    (sandbox.root / "probe.py").write_text(probe, encoding="utf-8")

    result = run(sandbox, f"'{sys.executable}' probe.py")

    assert "CONNECTED" not in result.output
    assert "refused:" in result.output


@on_a_mac
def test_credential_folders_cannot_be_read_but_the_rest_can(sandbox: SeatbeltExecutor) -> None:
    home = sandbox.root.parent / "home"

    key = run(sandbox, f"cat '{home}/.ssh/id_ed25519'")
    notes = run(sandbox, f"cat '{home}/notes.txt'")

    assert key.exit_code != 0 and "PRIVATE KEY" not in key.output
    assert notes.output.strip() == "not a secret"  # only the credential folders are closed


@on_a_mac
def test_a_session_with_the_seatbelt_executor_runs_its_commands_in_it(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = Config(home=tmp_path / "home", executor="seatbelt", subagents=False)

    opened = open_session(
        config, {}, workspace=workspace, make_provider=lambda c, m: FakeProvider([])
    )
    try:
        assert isinstance(opened.executor, SeatbeltExecutor)
        assert "in a sandbox" in opened.info.system
        blocked = asyncio.run(opened.executor.run_shell("touch ~/zwans-probe", timeout=30))
        assert "Operation not permitted" in blocked.output
    finally:
        asyncio.run(opened.close())


@on_a_mac
def test_what_a_command_starts_is_sandboxed_too(sandbox: SeatbeltExecutor) -> None:
    outside = sandbox.root.parent / "home" / "from-a-child.txt"
    script = f"import subprocess; subprocess.run(['bash', '-c', 'echo x > \"{outside}\"'])"
    (sandbox.root / "child.py").write_text(script, encoding="utf-8")

    run(sandbox, f"'{sys.executable}' child.py")

    assert not outside.exists()

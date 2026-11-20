import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from zwans.checkpoints import Change, Checkpoints
from zwans.cli.commands import Commands, Reopen
from zwans.config import Config
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.runtime import open_session

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "keep.txt").write_text("original\n")
    (root / "gone.txt").write_text("will be deleted\n")
    (root / ".gitignore").write_text("build/\n")
    return root


def test_undoing_a_turn_puts_the_files_back(workspace: Path, tmp_path: Path) -> None:
    checkpoints = Checkpoints(workspace, tmp_path / "home", "s1")

    async def go() -> tuple[list[Change], list[Change]]:
        await checkpoints.save(1)
        (workspace / "keep.txt").write_text("edited\n")
        (workspace / "gone.txt").unlink()
        (workspace / "new" / "deep").mkdir(parents=True)
        (workspace / "new" / "deep" / "file.py").write_text("x = 1\n")
        (workspace / "build").mkdir()
        (workspace / "build" / "out.bin").write_text("ignored")
        changed = await checkpoints.changes(1)
        return changed, await checkpoints.restore(1)

    changed, undone = asyncio.run(go())

    assert sorted(changed, key=lambda c: c.path) == [
        Change("deleted", "gone.txt"),
        Change("changed", "keep.txt"),
        Change("added", "new/deep/file.py"),
    ]
    assert len(undone) == 3
    assert (workspace / "keep.txt").read_text() == "original\n"
    assert (workspace / "gone.txt").read_text() == "will be deleted\n"
    assert not (workspace / "new").exists()  # emptied folders go too
    assert (workspace / "build" / "out.bin").exists()  # ignored, so never touched


def test_the_projects_own_git_repository_is_left_alone(workspace: Path, tmp_path: Path) -> None:
    git(workspace, "init", "--quiet")
    git(workspace, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(workspace, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")
    head, refs = git(workspace, "rev-parse", "HEAD"), git(workspace, "show-ref")
    checkpoints = Checkpoints(workspace, tmp_path / "home", "s1")

    async def go() -> None:
        await checkpoints.save(1)
        (workspace / "keep.txt").write_text("edited\n")
        await checkpoints.save(2)
        await checkpoints.restore(1)

    asyncio.run(go())

    assert git(workspace, "rev-parse", "HEAD") == head
    assert git(workspace, "show-ref") == refs
    assert git(workspace, "status", "--porcelain") == ""
    assert not (workspace / ".git" / "refs" / "zwans").exists()


def test_a_redone_turn_uses_its_newer_checkpoint(workspace: Path, tmp_path: Path) -> None:
    checkpoints = Checkpoints(workspace, tmp_path / "home", "s1")

    async def go() -> list[Change]:
        await checkpoints.save(1)
        (workspace / "a.txt").write_text("first try\n")
        await checkpoints.restore(1)
        (workspace / "b.txt").write_text("second try\n")
        await checkpoints.save(1)  # turn 1 again, after the rewind
        (workspace / "c.txt").write_text("from turn 1\n")
        return await checkpoints.changes(1)

    assert asyncio.run(go()) == [Change("added", "c.txt")]


def test_a_workspace_moved_mid_session_turns_checkpoints_off(
    workspace: Path, tmp_path: Path
) -> None:
    checkpoints = Checkpoints(workspace, tmp_path / "home", "s1")
    asyncio.run(checkpoints.save(1))
    workspace.rename(tmp_path / "moved")

    asyncio.run(checkpoints.save(2))  # doesn't raise: the turn goes on without one

    assert not checkpoints.available
    assert checkpoints.problem == (
        f"Checkpoints are off for this session: the workspace {workspace} no longer exists."
    )


def test_without_git_checkpoints_are_off(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    checkpoints = Checkpoints(workspace, tmp_path / "home", "s1")
    asyncio.run(checkpoints.save(1))

    assert not checkpoints.available and "git isn't installed" in (checkpoints.problem or "")


def test_undo_reverts_the_files_and_the_turn(
    workspace: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = [
        ModelResponse(
            content=[
                ToolUseBlock(id="t1", name="Write", input={"path": "notes.md", "content": "hi"})
            ],
            stop_reason="tool_use",
        ),
        ModelResponse(content=[TextBlock(text="Wrote it.")], stop_reason="end_turn"),
    ]
    config = Config(home=tmp_path / "home")
    opened = open_session(
        config,
        {},
        workspace=workspace,
        mode="auto",
        make_provider=lambda config, model: FakeProvider(script),
    )
    commands = Commands(opened)

    async def go() -> object:
        await opened.session.send("Write @keep.txt's notes")
        assert (workspace / "notes.md").exists()
        await commands.run("/rewind")
        return await commands.run("/undo")

    outcome = asyncio.run(go())
    asyncio.run(opened.close())

    out = capsys.readouterr().out
    assert "1. Write @keep.txt's notes" in out and "notes.md (added)" in out
    assert "Removed notes.md, which was new." in out
    assert outcome == Reopen(resume=opened.id, rewind=0, draft="Write @keep.txt's notes")
    assert not (workspace / "notes.md").exists()
    reopened = open_session(
        config,
        {},
        workspace=workspace,
        resume=opened.id,
        rewind=0,
        make_provider=lambda config, model: FakeProvider([]),
    )
    assert reopened.session.messages == [] and reopened.session.turn == 0
    asyncio.run(reopened.close())

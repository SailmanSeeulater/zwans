"""Checkpoints: the workspace's files as they were before each turn, so a turn can be undone.

Before every turn, Zwans snapshots the workspace into a git repository of its own, in
~/.zwans/checkpoints/<workspace>/, never the project's .git. It works in folders that aren't
git repositories, and it never touches the project's branches, index or history. Each
session keeps its snapshots on its own ref, one commit per turn.

A snapshot holds what git would: files the project's .gitignore leaves out, and a few
folders such as node_modules, aren't in it, so undoing a turn can't bring those back.
Neither can it undo what a command did outside the workspace, such as installing a package
or pushing to a server.
"""

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SNAPSHOT_TIMEOUT = 60.0  # seconds; a workspace too big to snapshot in that turns checkpoints off
# Left out even without a .gitignore saying so: big, and rebuilt by the project's tools.
EXCLUDED = ["node_modules/", ".venv/", "venv/", "__pycache__/", ".next/", ".DS_Store"]
AUTHOR = {
    # Set only for the snapshot commits, through the environment; the user's git config
    # isn't read for them or changed.
    "GIT_AUTHOR_NAME": "Zwans",
    "GIT_AUTHOR_EMAIL": "checkpoints@zwans.invalid",
    "GIT_COMMITTER_NAME": "Zwans",
    "GIT_COMMITTER_EMAIL": "checkpoints@zwans.invalid",
}


class CheckpointError(Exception):
    pass


@dataclass(frozen=True)
class Change:
    status: str  # "added", "changed" or "deleted"
    path: str  # relative to the workspace


STATUS = {"A": "added", "M": "changed", "D": "deleted", "T": "changed"}


class Checkpoints:
    def __init__(self, workspace: Path, home: Path, session_id: str) -> None:
        self.workspace = workspace.resolve()
        digest = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:16]
        self.git_dir = home / "checkpoints" / f"{self.workspace.name}-{digest}"
        self.ref = f"refs/zwans/{session_id}"
        self.problem: str | None = None  # why checkpoints stopped, once they have
        if shutil.which("git") is None:
            self.problem = "git isn't installed, so turns can't be undone."

    @property
    def available(self) -> bool:
        return self.problem is None

    async def save(self, turn: int) -> None:
        """Snapshot the workspace before `turn`. A failure turns checkpoints off for the
        session instead of stopping the turn; `problem` says why."""
        if not self.available:
            return
        try:
            await self._ensure_repo()
            tree = await self._snapshot()
            parent = await self._head()
            args = ["commit-tree", tree, "-m", f"turn {turn}"]
            if parent:
                args += ["-p", parent]
            commit = await self._git(*args)
            await self._git("update-ref", self.ref, commit)
        except TimeoutError:
            self.problem = (
                f"Snapshotting the workspace took over {SNAPSHOT_TIMEOUT:.0f} seconds, so "
                "checkpoints are off for this session. A .gitignore for big folders helps."
            )
        except CheckpointError as exc:
            self.problem = f"Checkpoints are off for this session: {exc}"
        except OSError as exc:  # the workspace was moved or deleted, or the disk is full, ...
            self.problem = f"Checkpoints are off for this session: {self._describe(exc)}"

    async def turns(self) -> dict[int, str]:
        """The turns with a checkpoint, and each one's latest snapshot commit. A turn redone
        after a rewind has its newer snapshot."""
        if not self.available or not await self._head():
            return {}
        log = await self._git("log", "--format=%H %s", self.ref)
        found: dict[int, str] = {}
        for line in log.splitlines():
            commit, _, subject = line.partition(" ")
            if subject.startswith("turn ") and subject[5:].isdigit():
                found.setdefault(int(subject[5:]), commit)  # newest first, so keep the first
        return found

    async def changes(self, turn: int) -> list[Change]:
        """What `turn` changed: from its checkpoint to the next turn's, or to the files now."""
        turns = await self.turns()
        if turn not in turns:
            raise CheckpointError(f"There's no checkpoint from before turn {turn}.")
        later = [t for t in turns if t > turn]
        after = turns[min(later)] if later else await self._snapshot()
        return await self._diff(turns[turn], after)

    async def since_start(self) -> tuple[list[Change], str]:
        """Everything the session has changed so far: from its earliest checkpoint to the
        files as they are now. Returns the changes and a unified diff of them."""
        turns = await self.turns()
        if not turns:
            return [], ""
        first = turns[min(turns)]
        now = await self._snapshot()
        changes = await self._diff(first, now)
        diff = await self._git("diff", "--no-renames", "--no-color", first, now, strip=False)
        return changes, diff

    async def restore(self, turn: int) -> list[Change]:
        """Put the files back as they were before `turn`. Returns what that changed. The files
        as they were until now are snapshotted first, on the same ref."""
        turns = await self.turns()
        if turn not in turns:
            raise CheckpointError(f"There's no checkpoint from before turn {turn}.")
        now = await self._snapshot()
        commit = await self._git("commit-tree", now, "-p", await self._head(), "-m", "rewound")
        await self._git("update-ref", self.ref, commit)
        undo = await self._diff(now, turns[turn])  # from now back to the checkpoint
        for change in undo:
            if change.status == "deleted":  # added since the checkpoint
                (self.workspace / change.path).unlink(missing_ok=True)
                _remove_empty_parents(self.workspace / change.path, self.workspace)
        back = [c.path for c in undo if c.status != "deleted"]
        if back:
            await self._git(
                "checkout",
                turns[turn],
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                stdin="\0".join(back),
            )
        return undo

    async def _ensure_repo(self) -> None:
        if (self.git_dir / "HEAD").exists():
            return
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        await self._git("init", "--quiet")
        (self.git_dir / "info").mkdir(exist_ok=True)
        (self.git_dir / "info" / "exclude").write_text("\n".join(EXCLUDED) + "\n")

    async def _snapshot(self) -> str:
        await self._git("add", "--all", ".")
        return await self._git("write-tree")

    async def _head(self) -> str:
        try:
            return await self._git("rev-parse", "--verify", "--quiet", self.ref)
        except CheckpointError:
            return ""

    async def _diff(self, before: str, after: str) -> list[Change]:
        out = await self._git(
            "diff", "--name-status", "--no-renames", "-z", before, after, strip=False
        )
        fields = out.split("\0")
        return [
            Change(STATUS.get(code[:1], "changed"), path)
            for code, path in zip(fields[::2], fields[1::2], strict=False)
            if code
        ]

    def _describe(self, exc: OSError) -> str:
        if not self.workspace.is_dir():
            return f"the workspace {self.workspace} no longer exists."
        message = exc.strerror or str(exc)
        return f"{message}: {exc.filename}" if exc.filename else message

    async def _git(self, *args: str, stdin: str | None = None, strip: bool = True) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                f"--git-dir={self.git_dir}",
                f"--work-tree={self.workspace}",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.quotePath=false",
                *args,
                cwd=self.workspace,
                env={**os.environ, **AUTHOR},
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:  # git can't start in a workspace that's gone
            raise CheckpointError(self._describe(exc)) from exc
        try:
            out, err = await asyncio.wait_for(
                process.communicate(stdin.encode() if stdin is not None else None),
                SNAPSHOT_TIMEOUT,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            message = err.decode(errors="replace").strip().splitlines()
            raise CheckpointError(message[-1] if message else f"git {args[0]} failed")
        text = out.decode(errors="replace")
        return text.strip() if strip else text


def _remove_empty_parents(path: Path, root: Path) -> None:
    folder = path.parent
    while folder != root and folder.is_relative_to(root):
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            return
        folder = folder.parent

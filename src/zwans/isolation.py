"""Isolated subagents: a private copy of the workspace for each, and its changes brought back.

Subagents started in one response run at the same time, in the same folder, so two that edit
the same file can undo each other's work. An isolated subagent works in a copy of the
workspace instead, and when it finishes, what it changed is applied to the real workspace,
one subagent at a time. A change that overlaps one made since the copy was taken (by another
subagent, say) is merged the way git merges, and where both changed the same lines the file
is left with conflict markers for the model to resolve.

It works the way checkpoints do (checkpoints.py), in a git repository of Zwans's own under
~/.zwans/isolated/, never the project's: the folder doesn't have to be a git repository, and
the project's branches, index and history are never touched. A copy holds what a snapshot
would: the files .gitignore leaves out aren't in it, and neither are folders such as
node_modules, which are linked into the copy from the workspace instead so that its tests
can still run. What a subagent changes in those isn't brought back.

A subagent that stops before finishing, or whose changes can't be applied, has its copy kept
and its report says where, so nothing it did is lost.
"""

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from zwans.checkpoints import AUTHOR, EXCLUDED, STATUS, Change

TIMEOUT = 120.0  # seconds for one git command
# Linked into a copy from the workspace, so its tests can run: big, and rebuilt by tools.
LINKED = ("node_modules", ".venv", "venv")


class IsolationError(Exception):
    pass


@dataclass
class Copy:
    """A subagent's copy of the workspace: its folder, the snapshot it was taken from, and
    the index git keeps for it."""

    folder: Path
    base: str
    index: Path


@dataclass
class Outcome:
    """What bringing a copy's changes back did: the changes, and the files left with conflict
    markers because another change since the copy overlapped."""

    changes: list[Change] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if not self.changes:
            return "It changed no files."
        listed = _listed(self.changes)
        if not self.conflicts:
            return f"Its changes were applied to the workspace: {listed}."
        files = ", ".join(self.conflicts)
        return (
            f"Its changes were applied to the workspace ({listed}), with conflicts in {files}: "
            "another change since its copy was made touched the same lines, so those files "
            "have conflict markers to resolve: the side marked ours is the workspace's, and "
            "theirs is this subagent's."
        )


class Isolation:
    """The copies of one session's workspace. `problem` says why there can be none."""

    def __init__(
        self, workspace: Path, home: Path, session_id: str, problem: str | None = None
    ) -> None:
        self.workspace = workspace.resolve()
        digest = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:16]
        self.base_dir = home / "isolated" / f"{self.workspace.name}-{digest}"
        self.git_dir = self.base_dir / "repo.git"
        self.session_id = session_id
        self.problem = problem
        if self.problem is None and shutil.which("git") is None:
            self.problem = "git isn't installed, and isolated subagents need it."
        self.count = 0
        # One snapshot of the workspace, or one apply, at a time: they share the index.
        self._lock = asyncio.Lock()

    async def open(self) -> Copy:
        """A new copy of the workspace as it is now, uncommitted changes and all."""
        async with self._lock:
            await self._ensure_repo()
            base = await self._snapshot(self.workspace, self.git_dir / "index")
        self.count += 1
        folder = self.base_dir / f"{self.session_id}-{self.count}"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        copy = Copy(folder=folder, base=base, index=folder.with_name(folder.name + ".index"))
        await self._git("read-tree", base, work_tree=folder, index=copy.index)
        await self._git("checkout-index", "--all", "--force", work_tree=folder, index=copy.index)
        for name in LINKED:
            if (self.workspace / name).is_dir() and not (folder / name).exists():
                (folder / name).symlink_to(self.workspace / name, target_is_directory=True)
        return copy

    async def bring_back(self, copy: Copy) -> Outcome:
        """Apply what changed in `copy` to the workspace, and remove the copy. Raises
        IsolationError, keeping the copy, when the changes can't be applied."""
        after = await self._snapshot(copy.folder, copy.index)
        changes = await self._diff(copy.base, after)
        if not changes:
            self.discard(copy)
            return Outcome()
        patch = await self._git(
            "diff", "--binary", "--no-renames", "--no-color", copy.base, after,
            work_tree=copy.folder, index=copy.index, strip=False,
        )  # fmt: skip
        async with self._lock:
            index = self.git_dir / "index-apply"
            await self._snapshot(self.workspace, index)  # so the index matches the files
            code, _, err = await self._run(
                "apply", "--3way", "--whitespace=nowarn", "-",
                work_tree=self.workspace, index=index, stdin=patch,
            )  # fmt: skip
        conflicts = _conflicts(err)
        if code != 0 and not conflicts:
            lines = [line for line in err.splitlines() if line.startswith("error:")]
            why = lines[-1].removeprefix("error:").strip() if lines else f"git apply failed: {err}"
            raise IsolationError(why)
        self.discard(copy)
        return Outcome(changes=changes, conflicts=conflicts)

    def discard(self, copy: Copy) -> None:
        shutil.rmtree(copy.folder, ignore_errors=True)
        copy.index.unlink(missing_ok=True)

    # -- git

    async def _ensure_repo(self) -> None:
        if (self.git_dir / "HEAD").exists():
            return
        self.git_dir.mkdir(parents=True, exist_ok=True)
        await self._git("init", "--quiet", "--bare", work_tree=None)
        (self.git_dir / "info").mkdir(exist_ok=True)
        # The linked folders without a trailing slash too: in a copy they're links, which a
        # pattern for folders doesn't match.
        excluded = [*EXCLUDED, *LINKED]
        (self.git_dir / "info" / "exclude").write_text("\n".join(excluded) + "\n")

    async def _snapshot(self, folder: Path, index: Path) -> str:
        await self._git("add", "--all", ".", work_tree=folder, index=index)
        return await self._git("write-tree", work_tree=folder, index=index)

    async def _diff(self, before: str, after: str) -> list[Change]:
        out = await self._git(
            "diff", "--name-status", "--no-renames", "-z", before, after,
            work_tree=None, strip=False,
        )  # fmt: skip
        fields = out.split("\0")
        return [
            Change(STATUS.get(code[:1], "changed"), path)
            for code, path in zip(fields[::2], fields[1::2], strict=False)
            if code
        ]

    async def _git(
        self,
        *args: str,
        work_tree: Path | None,
        index: Path | None = None,
        stdin: str | None = None,
        strip: bool = True,
    ) -> str:
        code, out, err = await self._run(*args, work_tree=work_tree, index=index, stdin=stdin)
        if code != 0:
            lines = err.strip().splitlines()
            raise IsolationError(lines[-1] if lines else f"git {args[0]} failed")
        return out.strip() if strip else out

    async def _run(
        self,
        *args: str,
        work_tree: Path | None,
        index: Path | None = None,
        stdin: str | None = None,
    ) -> tuple[int, str, str]:
        env = {**os.environ, **AUTHOR}
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        where = [f"--work-tree={work_tree}"] if work_tree is not None else []
        try:
            process = await asyncio.create_subprocess_exec(
                "git", f"--git-dir={self.git_dir}", *where,
                "-c", "core.autocrlf=false", "-c", "core.quotePath=false", *args,
                cwd=work_tree or self.base_dir,
                env=env,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
        except OSError as exc:
            raise IsolationError(f"git couldn't start: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(
                process.communicate(stdin.encode() if stdin is not None else None), TIMEOUT
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise IsolationError(f"git {args[0]} took over {TIMEOUT:.0f} seconds") from None
        return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _conflicts(err: str) -> list[str]:
    """The files `git apply --3way` left with conflict markers, from what it printed."""
    found = []
    for line in err.splitlines():
        if line.startswith("U "):
            found.append(line[2:].strip())
        elif line.startswith("Applied patch to '") and line.endswith("' with conflicts."):
            found.append(line[len("Applied patch to '") : -len("' with conflicts.")])
    return sorted(set(found))


def _listed(changes: list[Change]) -> str:
    groups: dict[str, list[str]] = {}
    for change in changes:
        groups.setdefault(change.status, []).append(change.path)
    shown = []
    for status in ("added", "changed", "deleted"):
        paths = groups.get(status, [])
        if paths:
            more = f" and {len(paths) - 5} more" if len(paths) > 5 else ""
            shown.append(f"{status} {', '.join(paths[:5])}{more}")
    return "; ".join(shown)

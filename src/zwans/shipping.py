"""From a session's changes to a pull request: a branch, a commit of the files the session
changed (and only those, so other work in the folder stays out of it), a push, and a pull
request opened with GitHub's `gh` command.

Every step runs git or gh directly, with no shell, in the project's folder. Each one is
reported, done or not and why, so a push that's refused or a missing `gh` leaves the
commit in place and says what's left to do.
"""

import asyncio
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from zwans.checkpoints import Change

TIMEOUT = 120.0  # a push or a PR over a slow network
BRANCH_PREFIX = "zwans/"


class ShipError(Exception):
    """Something that stops shipping before anything changed."""


@dataclass
class GitState:
    repo: bool
    branch: str = ""  # "" when HEAD is detached
    base: str = ""  # the branch a pull request would go into
    remote: str = ""  # origin's URL, with any password in it left out
    github: bool = False
    gh: bool = False  # the gh command is installed
    on_base: bool = False  # working on the base branch itself, so a new branch is due
    problem: str = ""

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Step:
    name: str  # "branch", "commit", "push", "pr"
    ok: bool
    detail: str


@dataclass
class Shipped:
    steps: list[Step] = field(default_factory=list)
    branch: str = ""
    commit: str = ""
    url: str = ""  # the pull request's

    def as_json(self) -> dict[str, Any]:
        return {
            "steps": [asdict(step) for step in self.steps],
            "branch": self.branch,
            "commit": self.commit,
            "url": self.url,
        }


async def _run(folder: Path, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=folder,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        return 127, "", f"{args[0]} isn't installed"
    try:
        out, err = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None), TIMEOUT
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, "", f"{args[0]} {args[1]} took over {TIMEOUT:.0f} seconds"
    return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _git(folder: Path, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
    return await _run(folder, "git", *args, stdin=stdin)


def _hide_password(url: str) -> str:
    return re.sub(r"(https?://)[^/@\s]+@", r"\1", url)


async def state(folder: Path) -> GitState:
    """Where the project's git stands: its branch, the base a PR would target, its remote."""
    code, top, _ = await _git(folder, "rev-parse", "--show-toplevel")
    if code != 0:
        return GitState(repo=False, problem="This folder isn't a git repository.")
    root = Path(top.strip())
    _, branch, _ = await _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    _, remote, _ = await _git(root, "remote", "get-url", "origin")
    base = await _base(root)
    branch, remote = branch.strip(), _hide_password(remote.strip())
    return GitState(
        repo=True,
        branch=branch,
        base=base,
        remote=remote,
        github="github.com" in remote,
        gh=shutil.which("gh") is not None,
        on_base=bool(branch) and branch == base,
        problem="" if branch else "HEAD is detached: check out a branch first.",
    )


async def _base(root: Path) -> str:
    code, head, _ = await _git(
        root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
    )
    if code == 0 and head.strip():
        return head.strip().removeprefix("origin/")
    for name in ("main", "master", "trunk"):
        code, _, _ = await _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
        if code == 0:
            return name
    return ""


def slug(text: str, most: int = 40) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(words) <= most:
        return words or "changes"
    return words[:most].rsplit("-", 1)[0] or words[:most]


def draft(title: str, changes: Sequence[Change], summary: str = "") -> dict[str, str]:
    """A branch name, a commit title and a body to start from, made from the session without
    asking a model, so it costs nothing; the person edits them before shipping."""
    first = " ".join(title.split()) or "Changes from a Zwans session"
    headline = first if len(first) <= 72 else first[:71].rsplit(" ", 1)[0] + "…"
    files = "\n".join(f"- {c.status}: `{c.path}`" for c in changes[:40])
    if len(changes) > 40:
        files += f"\n- and {len(changes) - 40} more"
    parts = [summary.strip()] if summary.strip() else []
    parts.append(f"Files:\n{files}" if files else "")
    parts.append("Made with Zwans.")
    return {
        "branch": BRANCH_PREFIX + slug(first),
        "title": headline,
        "body": "\n\n".join(p for p in parts if p),
    }


async def valid_branch(folder: Path, name: str) -> bool:
    code, _, _ = await _git(folder, "check-ref-format", "--branch", name)
    return code == 0 and not name.startswith("-")


async def ship(
    folder: Path,
    changes: Sequence[Change],
    *,
    branch: str,
    title: str,
    body: str,
    push: bool = True,
    pull_request: bool = True,
) -> Shipped:
    """Commit `changes` on `branch` (made from where HEAD is, unless it's the current one),
    then push it and open a pull request into the base branch, as asked. Raises ShipError
    when nothing can be done; later steps that fail are reported in what's returned."""
    current = await state(folder)
    if not current.repo:
        raise ShipError(current.problem)
    if current.problem:
        raise ShipError(current.problem)
    if not changes:
        raise ShipError("The session hasn't changed any files, so there's nothing to commit.")
    if not title.strip():
        raise ShipError("Give the commit a title.")
    branch = branch.strip()
    if not await valid_branch(folder, branch):
        raise ShipError(f"{branch!r} isn't a name git takes for a branch.")
    if branch == current.base and (push or pull_request):
        raise ShipError(f"Choose a branch other than {current.base}, so the PR has one to merge.")
    _, top, _ = await _git(folder, "rev-parse", "--show-toplevel")
    root = Path(top.strip())
    done = Shipped(branch=branch)

    # The branch: a new one from here, or the one already checked out.
    if branch != current.branch:
        code, _, err = await _git(root, "switch", "-c", branch)
        if code != 0:
            raise ShipError(f"Couldn't make the branch {branch}: {err.strip()}")
        done.steps.append(Step("branch", True, f"Made {branch} from {current.branch}."))
    else:
        done.steps.append(Step("branch", True, f"On {branch} already."))

    # The commit: only the session's files, whatever else is in the folder.
    project = folder.resolve()
    paths = [str((project / c.path).resolve().relative_to(root.resolve())) for c in changes]
    code, _, err = await _git(root, "add", "--all", "--", *paths)
    if code != 0:
        done.steps.append(Step("commit", False, f"git add failed: {err.strip()}"))
        return done
    message = title.strip() + ("\n\n" + body.strip() if body.strip() else "") + "\n"
    code, _, err = await _git(root, "commit", "--file", "-", "--", *paths, stdin=message)
    if code != 0:
        why = err.strip() or "nothing to commit: the files may be committed already"
        done.steps.append(Step("commit", False, f"git commit failed: {why}"))
        return done
    _, sha, _ = await _git(root, "rev-parse", "--short", "HEAD")
    done.commit = sha.strip()
    done.steps.append(Step("commit", True, f"Committed {len(paths)} files as {done.commit}."))

    if not push:
        return done
    if not current.remote:
        done.steps.append(Step("push", False, "There's no remote called origin to push to."))
        return done
    code, _, err = await _git(root, "push", "--set-upstream", "origin", branch)
    if code != 0:
        done.steps.append(Step("push", False, f"git push failed: {_last_lines(err)}"))
        return done
    done.steps.append(Step("push", True, f"Pushed {branch} to origin."))

    if not pull_request:
        return done
    if not current.gh:
        done.steps.append(
            Step("pr", False, "Install GitHub's gh command (and run gh auth login) to open PRs.")
        )
        return done
    code, out, err = await _run(
        root,
        "gh",
        "pr",
        "create",
        "--base",
        current.base,
        "--head",
        branch,
        "--title",
        title.strip(),
        "--body-file",
        "-",
        stdin=body,
    )
    if code != 0:
        done.steps.append(Step("pr", False, f"gh pr create failed: {_last_lines(err)}"))
        return done
    found = re.search(r"https://\S+", out)
    done.url = found.group(0) if found else ""
    done.steps.append(Step("pr", True, f"Opened {done.url or 'the pull request'}."))
    return done


def _last_lines(text: str, count: int = 3) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return " ".join(lines[-count:]) or "no reason given"


def summary_of(events: Sequence[dict[str, Any]]) -> str:
    """The session's last reply, for a PR's body: what the model said it did."""
    text: list[str] = []
    for event in events:
        kind = event.get("type")
        if kind == "turn_started":
            text = []
        elif kind == "text_delta":
            text.append(str(event.get("text", "")))
    reply = "".join(text).strip()
    return reply if len(reply) <= 1500 else reply[:1500].rsplit(" ", 1)[0] + " …"

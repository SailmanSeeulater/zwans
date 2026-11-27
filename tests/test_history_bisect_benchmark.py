"""History, Bisect and Benchmark, on real git repositories made in a temporary folder."""

import asyncio
import dataclasses
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.benchmark import BenchmarkInput, BenchmarkTool, mann_whitney_p
from zwans.tools.bisect import BisectInput, BisectTool
from zwans.tools.history import HistoryInput, HistoryTool, github_repo, pr_link


def run(tool: Any, args: Any, ctx: ToolContext) -> ToolOutput:
    output: ToolOutput = asyncio.run(tool.run(args, ctx))
    return output


def context(root: Path) -> ToolContext:
    return ToolContext(executor=LocalExecutor(root))


@pytest.fixture(autouse=True)
def quiet_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the person's git settings (signing, hooks, aliases) out of these repositories."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ada")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ada@example.com")


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    done = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def commit(repo: Path, message: str, day: int) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, date=f"2024-03-{day:02d}T10:00:00+00:00")
    return git(repo, "rev-parse", "HEAD").strip()


# -- History


@pytest.fixture
def story(tmp_path: Path) -> Path:
    """a.py written in a pull request, line 3 changed later, line 5 changed but not committed."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "remote", "add", "origin", "git@github.com:acme/widgets.git")
    lines = ["def f():", "    x = 1", "    y = 2", "    z = 3", "    return x"]
    (tmp_path / "a.py").write_text("\n".join(lines) + "\n")
    commit(tmp_path, "Add f (#12)\n\nf exists because the parser needs a hook.", 1)
    lines[2] = "    y = 20  # the old value overflowed"
    (tmp_path / "a.py").write_text("\n".join(lines) + "\n")
    commit(tmp_path, "Raise y\n\nTwo overflowed on large inputs, see the bug report.", 2)
    lines[4] = "    return x + y"
    (tmp_path / "a.py").write_text("\n".join(lines) + "\n")
    return tmp_path


def test_history_of_lines_has_blame_runs_messages_and_evolution(story: Path) -> None:
    out = run(HistoryTool(), HistoryInput(path="a.py", line=2, end_line=5), context(story))
    text = out.content
    assert text.startswith("a.py lines 2-5")
    blame = text.split("The commits behind them:")[0]
    assert "Ada  2024-03-01  Add f (#12)" in blame
    assert "Ada  2024-03-02  Raise y" in blame
    assert "not committed yet" in blame
    assert "| return x + y" in blame.replace("    ", "")
    order = [blame.index(s) for s in ("Add f", "Raise y", "  4 ", "not committed")]
    assert order == sorted(order)
    assert "f exists because the parser needs a hook." in text
    assert "Two overflowed on large inputs" in text
    assert "Pull request: https://github.com/acme/widgets/pull/12" in text
    evolution = text.split("How the lines changed")[1]
    assert "2 commits" in evolution
    assert "(message above)" in evolution
    assert "+    y = 20  # the old value overflowed" in evolution
    assert "uncommitted changes" in evolution


def test_history_of_a_file_lists_commits_newest_first(story: Path) -> None:
    out = run(HistoryTool(), HistoryInput(path="a.py"), context(story))
    text = out.content
    assert "the last 2 commits" in text
    assert text.index("Raise y") < text.index("Add f (#12)")
    assert "a.py | 2 +-" in text
    assert "https://github.com/acme/widgets/pull/12" in text
    assert "a.py also has uncommitted changes." in text


def test_history_refuses_untracked_files_and_folders_outside_git(
    story: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (story / "new.py").write_text("x = 1\n")
    with pytest.raises(ToolError, match=r"doesn.t track new\.py"):
        run(HistoryTool(), HistoryInput(path="new.py"), context(story))
    with pytest.raises(ToolError, match=r"only 5 lines|failed"):
        run(HistoryTool(), HistoryInput(path="a.py", line=9), context(story))
    with pytest.raises(ToolError, match="end_line comes before line"):
        run(HistoryTool(), HistoryInput(path="a.py", line=3, end_line=2), context(story))
    elsewhere = story / "plain"
    elsewhere.mkdir()
    # A folder outside any repository: point git's search at it alone.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(story.resolve()))
    with pytest.raises(ToolError, match="isn't a git repository"):
        run(HistoryTool(), HistoryInput(path="x"), context(elsewhere))


def test_pull_request_links_from_remotes_and_subjects() -> None:
    for url in (
        "git@github.com:acme/widgets.git",
        "ssh://git@github.com/acme/widgets.git",
        "https://github.com/acme/widgets",
        "https://github.com/acme/widgets.git",
    ):
        assert github_repo(url) == "acme/widgets", url
    assert github_repo("https://gitlab.com/acme/widgets.git") is None
    link = pr_link("Merge pull request #7 from ada/fix", "acme/widgets")
    assert link == "https://github.com/acme/widgets/pull/7"
    assert pr_link("Fix (#8)", None) == "#8 (the remote isn't on GitHub, so there's no link)"
    assert pr_link("Fix issue 8", "acme/widgets") is None


# -- Bisect


@pytest.fixture
def broken(tmp_path: Path) -> tuple[Path, list[str]]:
    """Eight commits; `state` says broken from the fifth on."""
    shas = []
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "sub").mkdir()
    for n in range(1, 9):
        (tmp_path / "state").write_text("broken\n" if n >= 5 else "ok\n")
        (tmp_path / "sub" / "counter").write_text(f"{n}\n")
        shas.append(commit(tmp_path, f"Change {n}\n\nWhy change {n} was made.", n))
    git(tmp_path, "tag", "v1", shas[0])
    return tmp_path, shas


def test_bisect_finds_the_first_bad_commit_and_puts_head_back(
    broken: tuple[Path, list[str]],
) -> None:
    repo, shas = broken
    (repo / "notes.txt").write_text("untracked files don't block bisect\n")
    out = run(BisectTool(), BisectInput(good="v1", test="grep -qx ok state"), context(repo))
    text = out.content
    assert f"The first bad commit is {shas[4][:10]}." in text
    assert "subject Change 5" in text
    assert "Why change 5 was made." in text
    assert "state       | 2 +-" in text
    assert "given  good" in text and "given  bad" in text
    assert "1      " in text  # numbered steps
    assert "back where they were" in text
    assert git(repo, "rev-parse", "HEAD").strip() == shas[-1]
    assert git(repo, "branch", "--show-current").strip() == "main"
    assert not (repo / ".git" / "BISECT_LOG").exists()


def test_bisect_runs_the_test_from_the_workspace_folder(broken: tuple[Path, list[str]]) -> None:
    repo, shas = broken
    out = run(
        BisectTool(), BisectInput(good=shas[0], test="grep -qx ok ../state"), context(repo / "sub")
    )
    assert f"The first bad commit is {shas[4][:10]}." in out.content


def test_bisect_refuses_a_dirty_tree_and_a_bisect_in_progress(
    broken: tuple[Path, list[str]],
) -> None:
    repo, _ = broken
    (repo / "state").write_text("edited\n")
    with pytest.raises(ToolError, match="use_worktree=true"):
        run(BisectTool(), BisectInput(good="v1", test="true"), context(repo))
    git(repo, "checkout", "--", "state")
    git(repo, "bisect", "start")
    with pytest.raises(ToolError, match="already in progress"):
        run(BisectTool(), BisectInput(good="v1", test="true"), context(repo))
    git(repo, "bisect", "reset")
    with pytest.raises(ToolError, match="doesn't know a commit called 'nope'"):
        run(BisectTool(), BisectInput(good="nope", test="true"), context(repo))


def test_bisect_in_a_worktree_leaves_the_changes_and_no_folder(
    broken: tuple[Path, list[str]],
) -> None:
    repo, shas = broken
    (repo / "sub" / "counter").write_text("work in progress\n")
    args = BisectInput(good="v1", test="grep -qx ok state", use_worktree=True)
    out = run(BisectTool(), args, context(repo))
    assert f"The first bad commit is {shas[4][:10]}." in out.content
    assert "temporary git worktree" in out.content
    assert (repo / "sub" / "counter").read_text() == "work in progress\n"
    assert not list(repo.glob(".zwans-bisect-*"))
    assert len(git(repo, "worktree", "list").splitlines()) == 1
    assert git(repo, "rev-parse", "HEAD").strip() == shas[-1]


def test_bisect_says_why_when_no_single_commit_comes_out(
    broken: tuple[Path, list[str]],
) -> None:
    repo, shas = broken
    out = run(BisectTool(), BisectInput(good="v1", test="exit 125"), context(repo))
    assert "couldn't name a single first bad commit" in out.content
    assert "skipped (exit 125)" in out.content
    with pytest.raises(ToolError, match="not ancestors"):
        run(BisectTool(), BisectInput(good="HEAD", bad=shas[2], test="true"), context(repo))
    assert git(repo, "branch", "--show-current").strip() == "main"


def test_bisect_warns_when_the_test_never_fails(broken: tuple[Path, list[str]]) -> None:
    repo, shas = broken
    out = run(BisectTool(), BisectInput(good="v1", test="true"), context(repo))
    assert f"The first bad commit is {shas[-1][:10]}." in out.content
    assert "never failed" in out.content


class OtherGit(LocalExecutor):
    """A git that words its verdicts differently, as versions do: the tool must still find
    the first bad commit, from the bisect refs."""

    async def run(self, argv: Any, timeout: float, *args: Any, **kwargs: Any) -> Any:
        result = await super().run(argv, timeout, *args, **kwargs)
        reworded = result.output.replace("is the first bad commit", "was the first to go bad")
        reworded = reworded.replace("The first bad commit could be any of:", "Candidates:")
        return dataclasses.replace(result, output=reworded)


def test_bisect_doesnt_depend_on_how_git_words_it(broken: tuple[Path, list[str]]) -> None:
    repo, shas = broken
    ctx = ToolContext(executor=OtherGit(repo))

    out = run(BisectTool(), BisectInput(good="v1", test="grep -qx ok state"), ctx)
    assert f"The first bad commit is {shas[4][:10]}." in out.content

    out = run(BisectTool(), BisectInput(good="v1", test="exit 125"), ctx)
    assert "skipped (exit 125)" in out.content and "one of these" in out.content
    assert git(repo, "branch", "--show-current").strip() == "main"


def test_bisect_commands_for_the_policy() -> None:
    tool = BisectTool()
    assert tool.commands({"good": "v1", "test": "pytest -q"}) == ["git bisect start", "pytest -q"]
    assert tool.commands({"test": 3}) == ["git bisect start"]


# -- Benchmark


def test_benchmark_times_a_command(tmp_path: Path) -> None:
    out = run(BenchmarkTool(), BenchmarkInput(command="sleep 0.01", runs=3), context(tmp_path))
    text = out.content
    assert text.startswith("3 runs of each, after 1 warmup run.")
    assert "median" in text and "std dev" in text and "spread" in text
    assert " ms" in text
    assert "starting a shell" in text


def test_benchmark_stops_on_a_failing_command(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match=r"exit code 3\).*\n.*boom"):
        run(BenchmarkTool(), BenchmarkInput(command="echo boom; exit 3"), context(tmp_path))


def test_benchmark_compares_two_commands(tmp_path: Path) -> None:
    args = BenchmarkInput(command="sleep 0.01", against="sleep 0.06", runs=5, warmup=0)
    out = run(BenchmarkTool(), args, context(tmp_path))
    assert "A: sleep 0.01" in out.content and "B: sleep 0.06" in out.content
    assert "in turns" in out.content
    assert "B is " in out.content and "x slower than A" in out.content
    assert "beyond noise" in out.content


def test_benchmark_compares_with_the_previous_result(tmp_path: Path) -> None:
    tool = BenchmarkTool()
    first = run(tool, BenchmarkInput(command="sleep 0.01", runs=3, warmup=0), context(tmp_path))
    assert "previous result" not in first.content
    again = run(tool, BenchmarkInput(command="sleep 0.01", runs=3, warmup=0), context(tmp_path))
    assert "Against the previous result for this command in this session:" in again.content
    assert "the last time it was measured" in again.content
    assert tool.commands({"command": "make", "against": "make fast"}) == ["make", "make fast"]


def test_mann_whitney() -> None:
    same = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mann_whitney_p(same, same) == 1.0
    low = [float(n) for n in range(1, 11)]
    high = [float(n) for n in range(11, 21)]
    assert mann_whitney_p(low, high) == pytest.approx(0.00018, rel=0.05)
    assert mann_whitney_p([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 1.0

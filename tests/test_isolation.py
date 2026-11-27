"""Isolated subagents: each works in a copy of the workspace, and its changes are applied to the
real one when it finishes, so subagents started together can edit at once."""

import asyncio
import shutil
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from test_subagents import say, task, use

from zwans.executor.local import LocalExecutor
from zwans.ext.agents import AgentType, load_agent
from zwans.isolation import Isolation, IsolationError
from zwans.messages import Message, TextBlock, ToolResultBlock
from zwans.policy.engine import Permissions
from zwans.policy.rules import Policy, PolicyFile
from zwans.providers.base import ModelResponse, StreamItem
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.tools.base import Tool, ToolContext
from zwans.tools.read import ReadTool
from zwans.tools.run_tests import RunTestsTool
from zwans.tools.task import TaskTool
from zwans.tools.write import WriteTool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


class ByBrief(FakeProvider):
    """Replies from a script per conversation, picked by its first message, so subagents
    running at the same time each get their own whatever order they ask in."""

    def __init__(self, scripts: dict[str, list[ModelResponse]]) -> None:
        super().__init__([])
        self.scripts = scripts
        self.systems: dict[str, str] = {}
        self.tool_names: dict[str, list[str]] = {}
        self.seen: dict[str, list[Message]] = {}  # each conversation as last sent

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        first = messages[0].content[0]
        assert isinstance(first, TextBlock)
        self.systems[first.text] = system
        self.tool_names[first.text] = [tool.name for tool in tools]
        self.seen[first.text] = list(messages)
        await asyncio.sleep(0)  # let the other subagents get going
        yield self.scripts[first.text].pop(0)


def write(path: str, content: str, call: str = "w1") -> ModelResponse:
    return use((call, "Write", {"path": path, "content": content}))


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("a = 1\nb = 2\nc = 3\n")
    (root / "notes.txt").write_text("not committed anywhere\n")  # the folder isn't a git repo
    return root


def session(
    tmp_path: Path,
    root: Path,
    provider: FakeProvider,
    *agents: AgentType,
    permissions: Permissions | None = None,
    problem: str | None = None,
    max_steps: int = 30,
) -> tuple[Session, Isolation]:
    isolation = Isolation(root, tmp_path / "home", "s1", problem=problem)
    tools: list[Tool[Any]] = [
        ReadTool(),
        WriteTool(),
        RunTestsTool(root),
        TaskTool(max_steps, agents, isolation),
    ]
    s = Session(
        provider=provider,
        tools=tools,
        ctx=ToolContext(executor=LocalExecutor(root)),
        system="You are Zwans.",
        listeners=[],
        permissions=permissions,
    )
    return s, isolation


def results(s: Session) -> list[ToolResultBlock]:
    return [b for m in s.messages for b in m.content if isinstance(b, ToolResultBlock)]


def leftovers(isolation: Isolation) -> list[str]:
    return sorted(p.name for p in isolation.base_dir.iterdir() if p.name != "repo.git")


def test_an_isolated_subagent_works_in_a_copy_and_its_changes_are_applied(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    provider = ByBrief(
        {
            "Go.": [use(("t1", "Task", task("Add b.", isolated=True))), say("Done.")],
            "Add b.": [
                use(("r1", "Read", {"path": "notes.txt"})),
                write("b.py", "B = 2\n"),
                say("Added b.py."),
            ],
        }
    )
    s, isolation = session(tmp_path, root, provider)

    assert asyncio.run(s.send("Go.")) == "end_turn"

    assert (root / "b.py").read_text() == "B = 2\n"
    (report,) = results(s)[:1]
    assert report.content == (
        "Added b.py.\n\n[Its changes were applied to the workspace: added b.py.]"
    )
    system = provider.systems["Add b."]
    assert "You work in a private copy of the workspace, at " in system
    assert str(isolation.base_dir) in system
    assert leftovers(isolation) == []  # the copy is gone once applied


def test_subagents_editing_at_once_have_all_their_changes_applied(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ByBrief(
        {
            "Go.": [
                use(
                    ("t1", "Task", task("First.", isolated=True)),
                    ("t2", "Task", task("Last.", isolated=True)),
                    ("t3", "Task", task("New file.", isolated=True)),
                ),
                say("Done."),
            ],
            "First.": [write("app.py", "a = 10\nb = 2\nc = 3\n"), say("Changed a.")],
            "Last.": [write("app.py", "a = 1\nb = 2\nc = 30\n"), say("Changed c.")],
            "New file.": [write("lib.py", "x = 1\n"), say("Added lib.py.")],
        }
    )
    s, isolation = session(tmp_path, root, provider)

    asyncio.run(s.send("Go."))

    assert (root / "app.py").read_text() == "a = 10\nb = 2\nc = 30\n"  # both edits, merged
    assert (root / "lib.py").read_text() == "x = 1\n"
    assert not any(r.is_error for r in results(s))
    assert leftovers(isolation) == []


def test_subagents_changing_the_same_lines_leave_conflict_markers(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ByBrief(
        {
            "Go.": [
                use(
                    ("t1", "Task", task("Ten.", isolated=True)),
                    ("t2", "Task", task("Twenty.", isolated=True)),
                ),
                say("Done."),
            ],
            "Ten.": [write("app.py", "a = 10\nb = 2\nc = 3\n"), say("a is 10.")],
            "Twenty.": [write("app.py", "a = 20\nb = 2\nc = 3\n"), say("a is 20.")],
        }
    )
    s, _ = session(tmp_path, root, provider)

    asyncio.run(s.send("Go."))

    text = (root / "app.py").read_text()
    assert "<<<<<<< ours" in text and "=======" in text and ">>>>>>> theirs" in text
    assert "a = 10" in text and "a = 20" in text
    reports = [r.text() for r in results(s)]
    assert sum("with conflicts in app.py" in r for r in reports) == 1
    assert sum(r.endswith("[Its changes were applied to the workspace: changed app.py.]")
               for r in reports) == 1  # fmt: skip


def test_an_isolated_subagent_cant_write_the_real_workspace(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ByBrief(
        {
            "Go.": [use(("t1", "Task", task("Sneak.", isolated=True))), say("Done.")],
            "Sneak.": [write(str(root / "app.py"), "gone\n"), say("Tried.")],
        }
    )
    policy = Policy.default()
    policy.add(PolicyFile(mode="auto"), "test")
    executor = LocalExecutor(root)
    permissions = Permissions(
        policy, inside=executor.contains, relative=executor.relative, root=executor.root
    )
    s, _ = session(tmp_path, root, provider, permissions=permissions)

    asyncio.run(s.send("Go."))

    assert (root / "app.py").read_text() == "a = 1\nb = 2\nc = 3\n"
    (refused,) = [
        b for m in provider.seen["Sneak."] for b in m.content if isinstance(b, ToolResultBlock)
    ]
    assert refused.is_error and "outside" in refused.text().lower()
    assert results(s)[0].text().endswith("[It changed no files.]")


def test_a_subagent_that_stops_early_keeps_its_copy(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ByBrief(
        {
            "Go.": [use(("t1", "Task", task("Half.", isolated=True))), say("Done.")],
            "Half.": [write("half.py", "x\n"), write("more.py", "y\n", "w2")],
        }
    )
    s, isolation = session(tmp_path, root, provider, max_steps=1)

    asyncio.run(s.send("Go."))

    assert not (root / "half.py").exists()
    report = results(s)[-1]
    assert report.is_error
    assert "Its changes weren't applied, since it didn't finish." in report.text()
    (kept,) = leftovers(isolation)[:1]
    assert (isolation.base_dir / kept / "half.py").read_text() == "x\n"
    assert str(isolation.base_dir / kept) in report.text()


def test_an_agent_type_can_be_isolated_and_its_tools_move_with_it(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    text = "---\ndescription: Writes code.\nisolation: copy\n---\nWrite it."
    (tmp_path / "coder.md").write_text(text)
    coder = load_agent(tmp_path / "coder.md")
    assert coder is not None and coder.isolated
    claude_style = tmp_path / "c.md"
    claude_style.write_text("---\ndescription: x\nisolation: worktree\n---")
    found = load_agent(claude_style)
    assert found is not None and found.isolated

    provider = ByBrief(
        {
            "Go.": [use(("t1", "Task", task("Code.", agent="coder"))), say("Done.")],
            "Code.": [write("c.py", "c\n"), say("Wrote c.py.")],
        }
    )
    s, _ = session(tmp_path, root, provider, coder)
    [task_tool] = [t for t in s.tools if isinstance(t, TaskTool)]

    asyncio.run(s.send("Go."))

    assert (root / "c.py").read_text() == "c\n"
    assert provider.tool_names["Code."] == ["Read", "Write", "RunTests"]
    assert task_tool.isolation is not None


def test_a_tool_with_its_own_folder_gets_the_copys(tmp_path: Path) -> None:
    from zwans.tools.task import _moved

    root = workspace(tmp_path)
    tests = RunTestsTool(root)
    moved = _moved(tests, tmp_path / "copy")

    assert isinstance(moved, RunTestsTool) and moved.root == tmp_path / "copy"
    assert tests.root == root  # the session's own is left alone
    reader = ReadTool()
    assert _moved(reader, tmp_path / "copy") is reader


def test_where_copies_cant_be_made_says_why(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    provider = ByBrief({"Go.": [use(("t1", "Task", task("Edit.", isolated=True))), say("Done.")]})
    s, _ = session(tmp_path, root, provider, problem="commands run in the docker executor")

    asyncio.run(s.send("Go."))

    (report,) = results(s)
    assert report.is_error
    assert report.text() == (
        "An isolated subagent can't run here: commands run in the docker executor"
    )


def test_linked_dependencies_are_shared_and_not_brought_back(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    (root / "node_modules" / "left").mkdir(parents=True)
    isolation = Isolation(root, tmp_path / "home", "s1")

    async def go() -> None:
        made = await isolation.open()
        assert (made.folder / "node_modules").is_symlink()
        assert (made.folder / "notes.txt").read_text() == "not committed anywhere\n"
        (made.folder / "app.py").write_text("a = 5\nb = 2\nc = 3\n")
        outcome = await isolation.bring_back(made)
        assert [c.path for c in outcome.changes] == ["app.py"]

    asyncio.run(go())
    assert (root / "app.py").read_text() == "a = 5\nb = 2\nc = 3\n"
    assert not (root / "node_modules").is_symlink()


def test_two_subagents_adding_the_same_file_conflict(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    isolation = Isolation(root, tmp_path / "home", "s1")

    async def go() -> list[str]:
        one, two = await isolation.open(), await isolation.open()
        (one.folder / "new.py").write_text("one\n")
        (two.folder / "new.py").write_text("two\n")
        await isolation.bring_back(one)
        return (await isolation.bring_back(two)).conflicts

    assert asyncio.run(go()) == ["new.py"]
    assert (root / "new.py").read_text() == "<<<<<<< ours\none\n=======\ntwo\n>>>>>>> theirs\n"


def test_a_change_that_cant_be_applied_keeps_the_copy(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    isolation = Isolation(root, tmp_path / "home", "s1")

    async def go() -> None:
        made = await isolation.open()
        (made.folder / "app.py").write_text("a = 5\nb = 2\nc = 3\n")
        (root / "app.py").unlink()  # deleted from the workspace meanwhile
        with pytest.raises(IsolationError, match=r"app\.py"):
            await isolation.bring_back(made)
        assert (made.folder / "app.py").read_text() == "a = 5\nb = 2\nc = 3\n"

    asyncio.run(go())
    assert not (root / "app.py").exists()

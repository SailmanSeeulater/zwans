"""Agent types: subagents defined once in a Markdown file and started by name with Task."""

import asyncio
from pathlib import Path
from typing import Any

from test_subagents import EchoTool, Recording, say, task, use
from typer.testing import CliRunner

from zwans.cli.app import app
from zwans.config import Config
from zwans.executor.local import LocalExecutor
from zwans.ext.agents import BUILTIN, AgentType, agent_folders, find_agents, load_agent
from zwans.messages import ToolResultBlock
from zwans.providers.catalog import Resolved
from zwans.providers.router import ModelRouter
from zwans.runtime import open_session
from zwans.session import Session
from zwans.tools.base import Tool, ToolContext
from zwans.tools.read import ReadTool
from zwans.tools.task import SUBAGENT_NOTE, TaskTool
from zwans.tools.write import WriteTool

REVIEWER = """---
name: reviewer
description: Reviews a change for bugs. Use after editing.
model: claude-haiku-5-5
tools: Read, echo
max_steps: 7
---
Report each bug as path:line.
"""


def write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    return path


def agent(name: str = "reviewer", **fields: Any) -> AgentType:
    return AgentType(
        name=name,
        description=fields.pop("description", "Reviews a change."),
        instructions=fields.pop("instructions", "Report each bug as path:line."),
        path=Path(f"/agents/{name}.md"),
        **fields,
    )


def session(tmp_path: Path, provider: Any, *agents: AgentType) -> Session:
    tools: list[Tool[Any]] = [EchoTool(), ReadTool(), WriteTool(), TaskTool(30, agents)]
    return Session(
        provider=provider,
        tools=tools,
        ctx=ToolContext(executor=LocalExecutor(tmp_path)),
        system="You are Zwans.",
        listeners=[],
    )


def results(s: Session) -> list[ToolResultBlock]:
    return [b for m in s.messages for b in m.content if isinstance(b, ToolResultBlock)]


# -- the files


def test_an_agent_file_gives_its_name_model_tools_steps_and_instructions(tmp_path: Path) -> None:
    found = load_agent(write(tmp_path, "rev.md", REVIEWER))

    assert found == AgentType(
        name="reviewer",
        description="Reviews a change for bugs. Use after editing.",
        instructions="Report each bug as path:line.",
        path=(tmp_path / "rev.md").resolve(),
        model="claude-haiku-5-5",
        tools=("Read", "echo"),
        max_steps=7,
    )


def test_a_claude_code_agent_file_works_too(tmp_path: Path) -> None:
    text = "---\ndescription: Finds things.\nmodel: sonnet\ntools: Read Grep\n---\nLook.\n"
    found = load_agent(write(tmp_path, "finder.md", text))

    assert found is not None
    assert found.name == "finder"  # from the file's name
    assert found.model == "claude-sonnet-5-5"
    assert found.tools == ("Read", "Grep")

    inherit = load_agent(write(tmp_path, "same.md", "---\ndescription: x\nmodel: inherit\n---"))
    assert inherit is not None and inherit.model is None and inherit.tools is None


def test_an_agent_file_without_a_description_or_a_usable_name_is_left_out(
    tmp_path: Path,
) -> None:
    assert load_agent(write(tmp_path, "a.md", "---\nname: a\n---\nDo things.")) is None
    assert load_agent(write(tmp_path, "b.md", "Just instructions.")) is None
    assert load_agent(write(tmp_path, "c.md", "---\nname: no spaces\ndescription: x\n---")) is None


def test_a_projects_agent_replaces_the_users_and_the_builtin_one(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    write(home / "agents", "explore.md", "---\ndescription: The user's explorer.\n---")
    write(workspace / ".claude" / "agents", "helper.md", "---\ndescription: From Claude.\n---")
    write(workspace / ".zwans" / "agents", "helper.md", "---\ndescription: From Zwans.\n---")

    found = {a.name: a for a in find_agents(agent_folders(workspace, home, builtin=True))}

    assert found["explore"].description == "The user's explorer."
    assert found["helper"].description == "From Zwans."
    assert found["reviewer"].path.is_relative_to(BUILTIN)
    alone = find_agents(agent_folders(workspace, None, builtin=False))
    assert [a.name for a in alone] == ["helper"]


def test_the_builtin_agents_load() -> None:
    found = {a.name: a for a in find_agents([BUILTIN])}

    assert set(found) == {"coder", "explore", "reviewer"}
    assert found["coder"].isolated and not found["reviewer"].isolated
    assert found["explore"].tools is not None and "Edit" not in found["explore"].tools
    assert found["reviewer"].tools is not None and "Write" not in found["reviewer"].tools
    assert all(a.instructions and a.max_steps for a in found.values())


# -- starting one


def test_the_task_tool_lists_the_agent_types() -> None:
    tool = TaskTool(30, [agent(), agent("explore", description="Searches the code.")])

    assert tool.description.startswith(TaskTool.description)
    assert tool.description.endswith("- reviewer: Reviews a change.\n- explore: Searches the code.")
    assert TaskTool().description == TaskTool.description


def test_an_agent_type_brings_its_instructions_tools_and_steps(tmp_path: Path) -> None:
    provider = Recording(
        [
            use(("t1", "Task", task("Review app.py.", agent="reviewer"))),
            use(("c1", "echo", {"text": "looking"})),
            say("app.py:3 divides by zero."),
            say("It found one bug."),
        ]
    )
    reviewer = agent(tools=("Read", "echo", "Bash"), max_steps=2)  # no Bash here: left out
    s = session(tmp_path, provider, reviewer)

    assert asyncio.run(s.send("Review my change.")) == "end_turn"

    assert provider.systems[1] == (
        "You are Zwans." + SUBAGENT_NOTE + "\n\nYou are the reviewer agent. "
        "Report each bug as path:line."
    )
    assert provider.tool_names[1] == ["echo", "Read"]
    assert results(s)[0].content == "app.py:3 divides by zero."


def test_an_agent_type_stops_at_its_own_steps(tmp_path: Path) -> None:
    provider = Recording(
        [
            use(("t1", "Task", task("Review.", agent="reviewer"))),
            use(("c1", "echo", {"text": "one"})),
            say("Gave up."),
        ]
    )
    s = session(tmp_path, provider, agent(max_steps=1))

    asyncio.run(s.send("Review."))

    first = results(s)[0]
    assert first.is_error and "stopped before finishing (max_steps)" in first.text()


def test_a_call_can_narrow_an_agents_tools_but_not_widen_them(tmp_path: Path) -> None:
    provider = Recording(
        [
            use(("t1", "Task", task("Look.", agent="reviewer", tools=["Read"]))),
            say("Nothing."),
            use(("t2", "Task", task("Look.", agent="reviewer", tools=["Write"]))),
            say("Done."),
        ]
    )
    s = session(tmp_path, provider, agent(tools=("Read", "echo")))

    asyncio.run(s.send("Look."))

    assert provider.tool_names[1] == ["Read"]
    second = results(s)[1]
    assert second.is_error and second.text().startswith("Unknown tools: Write.")


def test_an_unknown_agent_type_or_one_with_no_tools_here_is_an_error(tmp_path: Path) -> None:
    provider = Recording(
        [
            use(("t1", "Task", task("Look.", agent="auditor"))),
            use(("t2", "Task", task("Look.", agent="webby"))),
            say("Done."),
        ]
    )
    s = session(tmp_path, provider, agent(), agent("webby", tools=("WebSearch",)))

    asyncio.run(s.send("Look."))

    first, second = results(s)
    assert first.is_error
    assert (
        first.text()
        == "There's no agent type named 'auditor'. The ones there are: reviewer, webby."
    )
    assert second.is_error and "this session has none of them" in second.text()


def test_an_agent_type_runs_on_its_own_model(tmp_path: Path) -> None:
    scripts = {
        "claude-opus-5-5": [
            use(("t1", "Task", task("Review.", agent="reviewer"))),
            use(("t2", "Task", task("Review.", agent="broken"))),
            say("Done."),
        ],
        "claude-haiku-5-5": [say("No bugs.")],
    }
    made: dict[str, Recording] = {}

    def make(resolved: Resolved) -> Any:  # a scripted backend in place of a real one
        made[resolved.name] = Recording(scripts[resolved.name])
        return made[resolved.name]

    router = ModelRouter(
        Config(), {"ANTHROPIC_API_KEY": "sk-test"}, "claude-opus-5-5", make_backend=make
    )
    s = session(
        tmp_path,
        router,
        agent(model="claude-haiku-5-5"),
        agent("broken", model="openrouter/some-model"),  # no key for it
    )

    asyncio.run(s.send("Review."))

    assert len(made["claude-haiku-5-5"].requests) == 1
    first, second = results(s)
    assert first.content == "No bugs."
    assert second.is_error
    assert second.text().startswith(
        f"The broken agent ({Path('/agents/broken.md')}) runs on openrouter/some-model, "
        "which can't be used:"
    )


# -- in a session, and listed


def test_a_session_offers_the_builtin_and_the_projects_agent_types(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    write(workspace / ".zwans" / "agents", "docs.md", "---\ndescription: Writes docs.\n---")
    opened = open_session(
        Config(home=tmp_path / "home", tools_on_demand=False),
        {},
        workspace=workspace,
        make_provider=lambda config, model: Recording([]),
    )
    try:
        [tool] = [t for t in opened.session.tools if isinstance(t, TaskTool)]
        assert set(tool.agents) == {"coder", "docs", "explore", "reviewer"}
    finally:
        asyncio.run(opened.close())

    opened = open_session(
        Config(home=tmp_path / "home", tools_on_demand=False, builtin_agents=False),
        {},
        workspace=workspace,
        make_provider=lambda config, model: Recording([]),
    )
    try:
        [tool] = [t for t in opened.session.tools if isinstance(t, TaskTool)]
        assert set(tool.agents) == {"docs"}
    finally:
        asyncio.run(opened.close())


def test_zwans_agents_lists_them(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("ZWANS_HOME", str(tmp_path / "home"))
    write(tmp_path / "ws" / ".zwans" / "agents", "rev.md", REVIEWER)

    out = CliRunner().invoke(app, ["agents", "-w", str(tmp_path / "ws")]).output

    assert "explore (the subagent model; Read, Glob, Grep" in out
    assert "reviewer (claude-haiku-5-5; Read, echo; 7 steps)" in out
    assert "Reviews a change for bugs. Use after editing." in out
    assert "comes with Zwans" in out

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from zwans.cli.render import Renderer
from zwans.events import ToolCallRequested, ToolResult
from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext, ToolError
from zwans.tools.task import TaskTool
from zwans.tools.todo import TodoInput, TodoWriteTool


def run(todos: list[dict[str, str]], tmp_path: Path) -> str:
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    args = TodoInput.model_validate({"todos": todos})
    return asyncio.run(TodoWriteTool().run(args, ctx)).content


def test_the_list_is_counted(tmp_path: Path) -> None:
    todos = [
        {"content": "Read the code", "status": "completed"},
        {"content": "Fix the bug", "status": "in_progress"},
        {"content": "Run the tests", "status": "pending"},
    ]

    assert run(todos, tmp_path) == "To-do list saved: 1 done, 1 in progress, 1 to do."


def test_one_step_at_a_time_and_no_empty_steps(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="2 steps are in_progress"):
        both = [{"content": c, "status": "in_progress"} for c in "AB"]
        run(both, tmp_path)
    with pytest.raises(ToolError, match="needs some text"):
        run([{"content": " ", "status": "pending"}], tmp_path)
    with pytest.raises(ValidationError):
        TodoInput.model_validate({"todos": [{"content": "A", "status": "done"}]})


def test_subagents_get_no_list_of_their_own() -> None:
    task = TaskTool()

    tools = task._tools([TodoWriteTool(), task], None)

    assert tools == []


def test_the_cli_shows_a_checklist(capsys: pytest.CaptureFixture[str]) -> None:
    renderer = Renderer()
    todos = [
        {"content": "Read", "status": "completed"},
        {"content": "Fix", "status": "in_progress"},
    ]

    renderer.on_event(ToolCallRequested(call_id="t1", name="TodoWrite", args={"todos": todos}))
    renderer.on_event(ToolResult(call_id="t1", content="To-do list saved: 1 done"))

    assert capsys.readouterr().out == "> To-do list\n  ✓ Read\n  ▸ Fix\n"

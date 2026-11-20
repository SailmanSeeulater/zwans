"""The TodoWrite tool: the model's plan for a task, kept as a checklist people can follow.

Each call sends the whole list, so the latest call is the current list; the CLI and the web
UI show it from the call's input. Nothing is stored, and nothing in the workspace changes.
"""

from typing import Literal

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

type TodoStatus = Literal["pending", "in_progress", "completed"]


class Todo(BaseModel):
    content: str = Field(description="The step, as a short imperative: 'Run the tests'.")
    status: TodoStatus


class TodoInput(BaseModel):
    todos: list[Todo] = Field(description="The whole list, in order. It replaces the last one.")


class TodoWriteTool:
    name = "TodoWrite"
    description = (
        "Keep a to-do list for the task, which the user sees as a checklist. Use it when a "
        "task has three or more steps: write the plan before you start, then send the whole "
        "list again each time a step starts or finishes. Keep exactly one step in_progress "
        "while you work, and mark a step completed as soon as it's done, not in a batch at "
        "the end. Skip it for quick tasks and questions."
    )
    input_model = TodoInput
    read_only = True  # changes nothing but the list itself

    async def run(self, args: TodoInput, ctx: ToolContext) -> ToolOutput:
        if not all(todo.content.strip() for todo in args.todos):
            raise ToolError("Every to-do needs some text.")
        working = sum(todo.status == "in_progress" for todo in args.todos)
        if working > 1:
            raise ToolError(f"{working} steps are in_progress; keep it to one at a time.")
        counts = {status: 0 for status in ("completed", "in_progress", "pending")}
        for todo in args.todos:
            counts[todo.status] += 1
        return ToolOutput(
            f"To-do list saved: {counts['completed']} done, {counts['in_progress']} in progress, "
            f"{counts['pending']} to do."
        )

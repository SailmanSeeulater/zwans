"""The agent loop: call the model, run the tools it asks for, repeat until it stops."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import ValidationError

from zwans.events import (
    Error,
    Event,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)
from zwans.messages import ContentBlock, Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import Provider
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput


async def run_turn(
    provider: Provider,
    tools: Sequence[Tool[Any]],
    messages: list[Message],
    ctx: ToolContext,
    max_steps: int = 50,
) -> AsyncIterator[Event]:
    """Run one user turn and yield events as they happen.

    `messages` must end with the user's message. The loop appends the model's replies and
    the tool results to it, so the caller keeps the whole conversation.
    """
    tools_by_name = {tool.name: tool for tool in tools}
    yield TurnStarted()

    for _ in range(max_steps):
        response = await provider.complete(messages, tools)
        yield UsageUpdated(input_tokens=response.input_tokens, output_tokens=response.output_tokens)
        messages.append(Message(role="assistant", content=list(response.content)))

        results: list[ContentBlock] = []
        for block in response.content:
            if isinstance(block, TextBlock):
                yield TextDelta(text=block.text)
                continue
            yield ToolCallRequested(call_id=block.id, name=block.name, args=block.input)
            output = await _run_tool(tools_by_name, block, ctx)
            yield ToolResult(call_id=block.id, content=output.content, is_error=output.is_error)
            results.append(
                ToolResultBlock(
                    tool_use_id=block.id, content=output.content, is_error=output.is_error
                )
            )

        if response.stop_reason != "tool_use":
            yield TurnEnded(stop_reason=response.stop_reason)
            return
        messages.append(Message(role="user", content=results))

    yield Error(message=f"Stopped after {max_steps} model calls without finishing")


async def _run_tool(
    tools: dict[str, Tool[Any]], call: ToolUseBlock, ctx: ToolContext
) -> ToolOutput:
    """Run one tool call. Every expected failure goes back to the model as an error result."""
    tool = tools.get(call.name)
    if tool is None:
        return ToolOutput(content=f"Unknown tool: {call.name}", is_error=True)
    try:
        args = tool.input_model.model_validate(call.input)
    except ValidationError as exc:
        return ToolOutput(content=f"Invalid input for {call.name}: {exc}", is_error=True)
    try:
        return await tool.run(args, ctx)
    except ToolError as exc:
        return ToolOutput(content=str(exc), is_error=True)
    except OSError as exc:  # missing file, permission denied, path outside the workspace, ...
        return ToolOutput(content=_describe_os_error(exc), is_error=True)


def _describe_os_error(exc: OSError) -> str:
    message = exc.strerror or str(exc)
    return f"{message}: {exc.filename}" if exc.filename else message

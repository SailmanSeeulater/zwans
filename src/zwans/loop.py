"""The agent loop: call the model, run the tools it asks for, repeat until it stops."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import ValidationError

from zwans.events import (
    Error,
    Event,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
    UsageUpdated,
)
from zwans.messages import ContentBlock, Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse, Provider, ProviderError
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput

INTERRUPTED = "Interrupted by the user before this finished."


async def run_turn(
    provider: Provider,
    tools: Sequence[Tool[Any]],
    messages: list[Message],
    ctx: ToolContext,
    *,
    system: str = "",
    max_steps: int = 50,
) -> AsyncIterator[Event]:
    """Run one user turn and yield events as they happen.

    `messages` must end with the user's message. The loop only ever appends to it: the
    model's replies, then the tool results. Earlier turns are never edited, which the API
    requires before it accepts the model's earlier thinking blocks back.
    """
    tools_by_name = {tool.name: tool for tool in tools}
    yield TurnStarted(prompt=_last_user_text(messages))

    for _ in range(max_steps):
        response: ModelResponse | None = None
        try:
            async for item in provider.stream(system, messages, tools):
                if isinstance(item, ModelResponse):
                    response = item
                else:
                    yield item
        except ProviderError as exc:
            yield Error(message=str(exc))
            return
        if response is None:
            yield Error(message="The model's stream ended without a response.")
            return

        yield UsageUpdated(
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
        )
        messages.append(Message(role="assistant", content=list(response.content)))
        calls = [block for block in response.content if isinstance(block, ToolUseBlock)]

        if response.stop_reason != "tool_use":
            if calls:
                # A cut-off response can hold half-written tool calls. Don't run them, but
                # answer each one, because the API rejects a tool_use without a tool_result.
                reason = f"Not run: the response stopped early ({response.stop_reason})."
                skipped = ToolOutput(reason, is_error=True)
                messages.append(_results_message(calls, {}, default=skipped))
            yield TurnEnded(stop_reason=response.stop_reason, detail=response.stop_detail)
            return

        outputs: dict[str, ToolOutput] = {}
        try:
            for batch in _batches(calls, tools_by_name):
                for call in batch:
                    yield ToolCallRequested(call_id=call.id, name=call.name, args=call.input)
                results = await asyncio.gather(*(_run_tool(tools_by_name, c, ctx) for c in batch))
                for call, output in zip(batch, results, strict=True):
                    outputs[call.id] = output
                    yield ToolResult(
                        call_id=call.id, content=output.content, is_error=output.is_error
                    )
        finally:
            # Also runs when Ctrl+C cancels the turn mid-tool, so the conversation stays valid
            # and the session can carry on.
            interrupted = ToolOutput(INTERRUPTED, is_error=True)
            messages.append(_results_message(calls, outputs, default=interrupted))

    yield Error(message=f"Stopped after {max_steps} model calls without finishing.")


def _batches(calls: list[ToolUseBlock], tools: dict[str, Tool[Any]]) -> list[list[ToolUseBlock]]:
    """Group calls so neighbouring read-only calls run together and every other call runs alone."""
    batches: list[list[ToolUseBlock]] = []
    previous_read_only = False
    for call in calls:
        tool = tools.get(call.name)
        read_only = tool is not None and tool.read_only
        if read_only and previous_read_only:
            batches[-1].append(call)
        else:
            batches.append([call])
        previous_read_only = read_only
    return batches


def _results_message(
    calls: list[ToolUseBlock], outputs: dict[str, ToolOutput], default: ToolOutput
) -> Message:
    content: list[ContentBlock] = []
    for call in calls:
        output = outputs.get(call.id, default)
        content.append(
            ToolResultBlock(tool_use_id=call.id, content=output.content, is_error=output.is_error)
        )
    return Message(role="user", content=content)


def _last_user_text(messages: list[Message]) -> str:
    if not messages:
        return ""
    return "".join(block.text for block in messages[-1].content if isinstance(block, TextBlock))


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

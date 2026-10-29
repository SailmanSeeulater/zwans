"""The agent loop: call the model, run the tools it asks for, repeat until it stops."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import ValidationError

from zwans.context.compaction import Compactor
from zwans.context.truncation import fit_output
from zwans.events import (
    Error,
    Event,
    PermissionDenied,
    PermissionRequested,
    PermissionResolved,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
)
from zwans.messages import ContentBlock, Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.policy.engine import Approval, PermissionRequest, Permissions, denial_message
from zwans.policy.rules import Decision
from zwans.providers.base import ModelResponse, Provider, ProviderError
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput

INTERRUPTED = "Interrupted by the user before this finished."
STOPPED = "Zwans stopped before this finished, so it may or may not have run."


async def run_turn(
    provider: Provider,
    tools: Sequence[Tool[Any]],
    messages: list[Message],
    ctx: ToolContext,
    *,
    system: str = "",
    max_steps: int = 50,
    compactor: Compactor | None = None,
    permissions: Permissions | None = None,
) -> AsyncIterator[Event]:
    """Run one user turn and yield events as they happen.

    With `permissions`, every tool call is checked first: it runs, waits for the user's
    approval, or comes back to the model as an error saying why it didn't run.

    `messages` must end with the user's message. The loop only ever appends to it: the
    model's replies, then the tool results. Earlier turns are never edited, which the API
    requires before it accepts the model's earlier thinking blocks back.
    """
    tools_by_name = {tool.name: tool for tool in tools}
    yield TurnStarted(prompt=_last_user_text(messages))

    for _ in range(max_steps):
        response: ModelResponse | None = None
        try:
            if compactor is not None:
                for event in await compactor.maybe_compact(messages):
                    yield event
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

        yield response.usage_event()
        messages.append(Message(role="assistant", content=list(response.content)))
        if compactor is not None:
            compactor.observe(response, len(messages))
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
                runnable: list[ToolUseBlock] = []
                for call in batch:
                    yield ToolCallRequested(call_id=call.id, name=call.name, args=call.input)
                    tool = tools_by_name.get(call.name)
                    refusal: str | None = None
                    if permissions is not None and tool is not None:
                        async for step in _gate(permissions, tool, call):
                            if isinstance(step, str):
                                refusal = step
                            else:
                                yield step
                    if refusal is None:
                        runnable.append(call)
                    else:
                        outputs[call.id] = ToolOutput(refusal, is_error=True)
                        yield ToolResult(call_id=call.id, content=refusal, is_error=True)
                results = await asyncio.gather(
                    *(_run_tool(tools_by_name, c, ctx) for c in runnable)
                )
                for call, output in zip(runnable, results, strict=True):
                    outputs[call.id] = output
                    untrusted = False
                    if permissions is not None:
                        untrusted = permissions.observe(call.name, output.is_error)
                    yield ToolResult(
                        call_id=call.id,
                        content=output.content,
                        is_error=output.is_error,
                        untrusted=untrusted,
                    )
        finally:
            # Also runs when Ctrl+C cancels the turn mid-tool, so the conversation stays valid
            # and the session can carry on.
            interrupted = ToolOutput(INTERRUPTED, is_error=True)
            messages.append(_results_message(calls, outputs, default=interrupted))

    # A limit the agent ran into, not something that went wrong, so it ends the turn normally.
    yield TurnEnded(stop_reason="max_steps", detail=f"{max_steps} model calls without finishing")


async def _gate(
    permissions: Permissions, tool: Tool[Any], call: ToolUseBlock
) -> AsyncIterator[Event | str]:
    """Check one call against the policy, asking the user when it says so. Yields the
    permission events, then, if the call must not run, the message for the model."""
    verdict = permissions.check(tool, call.input)
    if verdict.decision == Decision.ALLOW:
        return
    can_ask = permissions.approver is not None
    approval: Approval | None = None
    if verdict.decision == Decision.ASK and can_ask:
        yield PermissionRequested(call_id=call.id, reason=verdict.reason, rules=list(verdict.rules))
        request = PermissionRequest(call.id, call.name, call.input, verdict.reason, verdict.rules)
        approval = await permissions.ask(request)
        yield PermissionResolved(call_id=call.id, allowed=approval != Approval.NO)
        if approval != Approval.NO:
            return
    else:
        yield PermissionDenied(call_id=call.id, reason=verdict.reason)
    yield denial_message(verdict, approval, can_ask)


def answer_pending_calls(messages: list[Message]) -> bool:
    """Answer tool calls left without results, as when Zwans was killed mid-tool.

    Returns whether it had to. A saved session needs this before it can continue, because
    the API rejects a tool_use without a matching tool_result.
    """
    if not messages or messages[-1].role != "assistant":
        return False
    calls = [block for block in messages[-1].content if isinstance(block, ToolUseBlock)]
    if not calls:
        return False
    messages.append(_results_message(calls, {}, default=ToolOutput(STOPPED, is_error=True)))
    return True


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
        output = await tool.run(args, ctx)
    except ToolError as exc:
        return ToolOutput(content=str(exc), is_error=True)
    except OSError as exc:  # missing file, permission denied, path outside the workspace, ...
        return ToolOutput(content=_describe_os_error(exc), is_error=True)
    return await fit_output(output, call.id, ctx.executor)


def _describe_os_error(exc: OSError) -> str:
    message = exc.strerror or str(exc)
    return f"{message}: {exc.filename}" if exc.filename else message

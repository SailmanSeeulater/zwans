"""The agent loop: call the model, run the tools it asks for, repeat until it stops."""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import ValidationError

from zwans.context.calls import TimedCall, context_split, counted_input
from zwans.context.compaction import Compactor
from zwans.context.truncation import fit_output
from zwans.events import (
    Error,
    Event,
    HookReported,
    PermissionDenied,
    PermissionRequested,
    PermissionResolved,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
)
from zwans.ext.hooks import Hooks, HookSpec
from zwans.messages import (
    ContentBlock,
    ImageBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from zwans.policy.engine import Approval, PermissionRequest, Permissions, denial_message
from zwans.policy.rules import Decision
from zwans.providers.base import Provider, ProviderError, ServerBlock
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput
from zwans.web import web_calls, web_results

INTERRUPTED = "Interrupted by the user before this finished."
STOPPED = "Zwans stopped before this finished, so it may or may not have run."
CUT_OFF = "[The user interrupted this reply here.]"


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
    hooks: Hooks | None = None,
) -> AsyncIterator[Event]:
    """Run one user turn and yield events as they happen.

    With `permissions`, every tool call is checked first: it runs, waits for the user's
    approval, or comes back to the model as an error saying why it didn't run. `hooks` run
    before that check, after each call, and when the model is about to finish.

    `messages` must end with the user's message. The loop only ever appends to it: the
    model's replies, then the tool results. Earlier turns are never edited, which the API
    requires before it accepts the model's earlier thinking blocks back.
    """
    tools_by_name = {tool.name: tool for tool in tools}
    web = _WebShown()
    asked = messages[-1] if messages else None
    yield TurnStarted(
        prompt=_last_user_text(messages),
        turn=(asked.turn or 0) if asked else 0,
        images=sum(isinstance(block, ImageBlock) for block in asked.content) if asked else 0,
    )

    changed = False  # whether a tool that can change files has run this turn
    stop_blocks: Counter[HookSpec] = Counter()  # how often each stop hook sent the model back
    for _ in range(max_steps):
        model_call = TimedCall()
        streamed: list[str] = []  # the reply's text so far, kept if Ctrl+C cuts it off
        try:
            if compactor is not None:
                for event in await compactor.maybe_compact(messages):
                    yield event
                model_call = TimedCall()  # a summary call isn't part of this one's time
            async for item in model_call.stream(provider, system, messages, tools):
                if isinstance(item, ServerBlock):
                    for event in web.events([item.block], permissions):
                        yield event
                    continue
                if isinstance(item, TextDelta):
                    streamed.append(item.text)
                yield item
        except ProviderError as exc:
            yield Error(message=str(exc))
            return
        except asyncio.CancelledError:
            _keep_cut_off_reply(messages, "".join(streamed))
            raise
        response = model_call.response
        if response is None:
            yield Error(message="The model's stream ended without a response.")
            return

        yield response.usage_event()
        yield model_call.event(context_split(system, tools, messages, counted_input(response)))
        messages.append(Message(role="assistant", content=list(response.content)))
        if compactor is not None:
            compactor.observe(response, len(messages))
        for event in web.events(response.content, permissions):  # any not streamed already
            yield event
        calls = [block for block in response.content if isinstance(block, ToolUseBlock)]

        if response.stop_reason == "pause_turn" and not calls:
            # The API paused a long run of web searches. Sending the conversation back as it
            # is, ending in the paused reply, lets the model carry on where it stopped.
            continue
        if response.stop_reason != "tool_use":
            if calls:
                # A cut-off response can hold half-written tool calls. Don't run them, but
                # answer each one, because the API rejects a tool_use without a tool_result.
                reason = f"Not run: the response stopped early ({response.stop_reason})."
                skipped = ToolOutput(reason, is_error=True)
                messages.append(_results_message(calls, {}, default=skipped))
            elif hooks is not None and response.stop_reason == "end_turn":
                text = "".join(b.text for b in response.content if isinstance(b, TextBlock))
                failures = await hooks.stop(response.stop_reason, text, changed=changed)
                for failure in failures:
                    yield HookReported(
                        event="stop", command=failure.spec.command, message=failure.message
                    )
                # A hook that has used up its max_blocks is reported but lets the turn end.
                retry = [f for f in failures if _may_block(f.spec, stop_blocks)]
                if retry:
                    stop_blocks.update(f.spec for f in retry)
                    said = "\n\n".join(failure.message for failure in retry)
                    note = f"A stop hook says the task isn't finished yet:\n{said}"
                    messages.append(Message(role="user", content=[TextBlock(text=note)]))
                    continue
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
                    if hooks is not None and tool is not None:
                        blocked = await hooks.pre_tool(call.name, call.input)
                        if blocked is not None:
                            yield HookReported(
                                event="pre_tool",
                                command=blocked.spec.command,
                                message=blocked.message,
                                call_id=call.id,
                            )
                            refusal = f"A pre_tool hook blocked this call: {blocked.message}"
                    if refusal is None and permissions is not None and tool is not None:
                        async for step in _gate(permissions, tool, call, ctx):
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
                changed = changed or any(
                    not tools_by_name[c.name].read_only for c in runnable if c.name in tools_by_name
                )
                for call, output in zip(runnable, results, strict=True):
                    if hooks is not None and call.name in tools_by_name:
                        failures = await hooks.post_tool(
                            call.name, call.input, output.content, output.is_error
                        )
                        for failure in failures:
                            yield HookReported(
                                event="post_tool",
                                command=failure.spec.command,
                                message=failure.message,
                                call_id=call.id,
                            )
                        if failures:
                            notes = [f"A post_tool hook says: {f.message}" for f in failures]
                            content = "\n\n".join([output.content, *notes])
                            output = ToolOutput(
                                content,
                                is_error=output.is_error,
                                diff=output.diff,
                                images=output.images,
                            )
                    outputs[call.id] = output
                    untrusted = False
                    if permissions is not None:
                        untrusted = permissions.observe(call.name, output.is_error)
                    yield ToolResult(
                        call_id=call.id,
                        content=output.content,
                        is_error=output.is_error,
                        untrusted=untrusted,
                        diff=output.diff,
                    )
        finally:
            # Also runs when Ctrl+C cancels the turn mid-tool, so the conversation stays valid
            # and the session can carry on.
            interrupted = ToolOutput(INTERRUPTED, is_error=True)
            messages.append(_results_message(calls, outputs, default=interrupted))

    # A limit the agent ran into, not something that went wrong, so it ends the turn normally.
    yield TurnEnded(stop_reason="max_steps", detail=f"{max_steps} model calls without finishing")


async def _gate(
    permissions: Permissions, tool: Tool[Any], call: ToolUseBlock, ctx: ToolContext
) -> AsyncIterator[Event | str]:
    """Check one call against the policy, asking the user when it says so. Yields the
    permission events, then, if the call must not run, the message for the model."""
    verdict = permissions.check(tool, call.input)
    if verdict.decision == Decision.ALLOW:
        return
    can_ask = permissions.approver is not None
    approval: Approval | None = None
    if verdict.decision == Decision.ASK and can_ask:
        preview = await _preview(tool, call, ctx)
        yield PermissionRequested(
            call_id=call.id, reason=verdict.reason, rules=list(verdict.rules), preview=preview
        )
        request = PermissionRequest(
            call.id, call.name, call.input, verdict.reason, verdict.rules, preview
        )
        approval = await permissions.ask(request)
        yield PermissionResolved(call_id=call.id, allowed=approval != Approval.NO)
        if approval != Approval.NO:
            return
    else:
        yield PermissionDenied(call_id=call.id, reason=verdict.reason)
    yield denial_message(verdict, approval, can_ask)


async def _preview(tool: Tool[Any], call: ToolUseBlock, ctx: ToolContext) -> str | None:
    """The diff a file tool's call would make, so the question can show it: whether a Write
    makes a new file or replaces one, and what an Edit changes, in the file's context."""
    preview = getattr(tool, "preview", None)
    if preview is None:
        return None
    try:
        args = tool.input_model.model_validate(call.input)
        diff = await preview(args, ctx)
    except (ValidationError, ToolError, OSError):
        return None  # the call would fail too; the question shows its input instead
    return diff if isinstance(diff, str) else None


class _WebShown:
    """The web searches and fetches the API ran in this turn, shown like other tool calls.

    Providers pass each one on as it streams in, so it shows before the text that follows
    it; anything a provider didn't stream is shown from the finished reply. A paused reply
    can hold a call whose result comes in the next one.
    """

    def __init__(self) -> None:
        self.names: dict[str, str] = {}  # call id: web_search or web_fetch
        self.shown: set[tuple[str, str]] = set()  # ("call" or "result", call id)

    def events(
        self, content: Sequence[ContentBlock], permissions: Permissions | None
    ) -> list[Event]:
        events: list[Event] = []
        for call in web_calls(content):
            self.names[call.id] = call.name
            if ("call", call.id) not in self.shown:
                self.shown.add(("call", call.id))
                events.append(ToolCallRequested(call_id=call.id, name=call.name, args=call.args))
        for result in web_results(content):
            if ("result", result.call_id) in self.shown:
                continue
            self.shown.add(("result", result.call_id))
            name = self.names.get(result.call_id, "web_search")
            untrusted = permissions.observe(name, result.is_error) if permissions else False
            events.append(
                ToolResult(
                    call_id=result.call_id,
                    content=result.content,
                    is_error=result.is_error,
                    untrusted=untrusted,
                )
            )
        return events


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


def _keep_cut_off_reply(messages: list[Message], text: str) -> None:
    """Keep the text the model had written when Ctrl+C stopped it, so it knows what it said
    and that it was cut off. Its thinking and half-written tool calls can't be sent back."""
    text = text.rstrip()
    if text:
        note = f"{text}\n\n{CUT_OFF}"
        messages.append(Message(role="assistant", content=[TextBlock(text=note)]))


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


def _may_block(spec: HookSpec, blocks: Counter[HookSpec]) -> bool:
    return spec.max_blocks is None or blocks[spec] < spec.max_blocks


def _results_message(
    calls: list[ToolUseBlock], outputs: dict[str, ToolOutput], default: ToolOutput
) -> Message:
    content: list[ContentBlock] = []
    for call in calls:
        output = outputs.get(call.id, default)
        result: str | list[TextBlock | ImageBlock] = output.content
        if output.images:
            result = [TextBlock(text=output.content), *output.images]
        content.append(
            ToolResultBlock(tool_use_id=call.id, content=result, is_error=output.is_error)
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

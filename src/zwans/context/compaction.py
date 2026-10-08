"""Compaction: when the conversation gets too long, summarize its older part.

The summary replaces the older messages; the most recent ones stay word for word. Thinking
blocks are removed from the kept messages, because each was written with the full history
present and the API would reject (or drop) them once that history is gone.
"""

import json
from collections.abc import Sequence

from zwans.context.tokens import approx_tokens
from zwans.events import ContextCompacted, Event
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse, Provider, ProviderError

SUMMARY_SYSTEM = """\
You write handoff notes for a coding agent whose conversation got too long. Another agent \
will continue the work with only your notes and the most recent messages, so include \
everything it needs:
- what the user asked for, in their words where it matters
- decisions made, and why
- files read, created, or changed, with their paths and what changed
- commands run and what they showed, including errors and how they were fixed
- what is done, and what is left to do
Be specific: keep names, paths, numbers, and error messages. No preamble."""

SUMMARY_HEADER = "[Summary of the earlier conversation, written when it got too long]\n\n"
THINKING_TYPES = ("thinking", "redacted_thinking")
PREVIEW_CHARS = 2_000  # of each tool call and result, in what the summarizer reads


class Compactor:
    def __init__(self, provider: Provider, threshold: int, keep_messages: int = 8) -> None:
        self.provider = provider  # could be a cheaper model than the main loop's
        self.threshold = threshold
        self.keep_messages = keep_messages
        self._counted_tokens = 0  # what the API counted for the last request, plus its reply
        self._counted_messages = 0  # how many messages that count covers

    def observe(self, response: ModelResponse, message_count: int) -> None:
        """Record the API's token count for the request that just finished."""
        self._counted_tokens = (
            response.input_tokens
            + response.cache_read_tokens
            + response.cache_write_tokens
            + response.output_tokens
        )
        self._counted_messages = message_count

    def estimate(self, messages: Sequence[Message]) -> int:
        """Tokens the next request will send: the API's last count plus a guess for what's new."""
        return self._counted_tokens + approx_tokens(messages[self._counted_messages :])

    async def maybe_compact(self, messages: list[Message]) -> list[Event]:
        """Compact `messages` in place if they're over the threshold. Returns events to emit."""
        before = self.estimate(messages)
        if before < self.threshold:
            return []
        cut = self._cut_point(messages)
        if cut is None:
            return []

        response = await self._summarize(messages[:cut])
        summary = "".join(b.text for b in response.content if isinstance(b, TextBlock)).strip()
        if not summary:
            return [response.usage_event()]  # e.g. a refusal: carry on uncompacted
        kept = [_without_thinking(message) for message in messages[cut:]]
        summary_message = Message(
            role="user", content=[TextBlock(text=SUMMARY_HEADER + summary)], turn=kept[0].turn
        )
        messages[:] = [summary_message, *kept]
        self._counted_tokens = self._counted_messages = 0  # the next response recounts
        compacted = ContextCompacted(tokens_before=before, tokens_after=approx_tokens(messages))
        return [compacted, response.usage_event()]

    def _cut_point(self, messages: Sequence[Message]) -> int | None:
        """Where the kept part starts. It must be an assistant message, so no tool result is kept
        without the tool call it answers, and at least two messages must be summarized."""
        for index in range(len(messages) - self.keep_messages, 1, -1):
            if messages[index].role == "assistant":
                return index
        return None

    async def _summarize(self, older: Sequence[Message]) -> ModelResponse:
        prompt = "Write the handoff notes for this conversation:\n\n" + render_transcript(older)
        request = [Message(role="user", content=[TextBlock(text=prompt)])]
        response = None
        async for item in self.provider.stream(SUMMARY_SYSTEM, request, []):
            if isinstance(item, ModelResponse):
                response = item
        if response is None:
            raise ProviderError("The summary request ended without a response.")
        return response


def render_transcript(messages: Sequence[Message]) -> str:
    """The conversation as plain text, for the summarizer. Thinking blocks are left out."""
    lines: list[str] = []
    for message in messages:
        for block in message.content:
            if isinstance(block, TextBlock):
                lines.append(f"{message.role.upper()}: {block.text}")
            elif isinstance(block, ToolUseBlock):
                arguments = json.dumps(block.input, ensure_ascii=False)
                lines.append(f"TOOL CALL {block.name}: {_preview(arguments)}")
            elif isinstance(block, ToolResultBlock):
                label = "TOOL ERROR" if block.is_error else "TOOL RESULT"
                lines.append(f"{label}: {_preview(block.content)}")
    return "\n\n".join(lines)


def _preview(text: str) -> str:
    if len(text) <= PREVIEW_CHARS:
        return text
    return f"{text[:1_500]}\n[... {len(text) - 2_000:,} characters left out ...]\n{text[-500:]}"


def _without_thinking(message: Message) -> Message:
    content = [
        block
        for block in message.content
        if not (isinstance(block, RawBlock) and block.type in THINKING_TYPES)
    ]
    return message.model_copy(update={"content": content or [TextBlock(text="(thinking only)")]})

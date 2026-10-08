"""Keeps one huge tool result from filling the model's context."""

from zwans.executor.base import Executor
from zwans.tools.base import ToolOutput

MAX_RESULT_CHARS = 20_000  # about 5,000 tokens
HEAD_CHARS = 12_000
TAIL_CHARS = 4_000


async def fit_output(output: ToolOutput, call_id: str, executor: Executor) -> ToolOutput:
    """Shorten a long result to its start and end, saving the full text where Read can open it."""
    text = output.content
    if len(text) <= MAX_RESULT_CHARS:
        return output
    path = await executor.spill(f"{call_id}.txt", text)
    hidden = len(text) - HEAD_CHARS - TAIL_CHARS
    note = (
        f"\n\n[... {hidden:,} characters not shown. The full output is saved at {path}. "
        "Use Read on it, with offset and limit, to see the rest.]\n\n"
    )
    return ToolOutput(text[:HEAD_CHARS] + note + text[-TAIL_CHARS:], is_error=output.is_error)

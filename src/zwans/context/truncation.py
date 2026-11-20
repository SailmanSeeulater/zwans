"""Keeps one huge tool result from filling the model's context."""

from zwans.executor.base import DROPPED_PATTERN, Executor
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
    saved = f"The full output is saved at {path}."
    # A runaway command's output was already cut when it ran, so the saved copy isn't whole.
    dropped = sum(int(match[1].replace(",", "")) for match in DROPPED_PATTERN.finditer(text))
    if dropped:
        saved = (
            f"The output is saved at {path}, but it's shortened too: {dropped:,} bytes from "
            "the middle were dropped while the command ran, and they can't be recovered."
        )
    tools = "Read on it, with offset and limit, or Grep"
    try:
        executor.search_path(path)
    except PermissionError:  # a jail can't search outside the workspace
        tools = "Read on it, with offset and limit,"
    note = (
        f"\n\n[... {hidden:,} characters not shown here. {saved} Use {tools} to see the rest.]\n\n"
    )
    shortened = text[:HEAD_CHARS] + note + text[-TAIL_CHARS:]
    return ToolOutput(shortened, is_error=output.is_error, diff=output.diff, images=output.images)

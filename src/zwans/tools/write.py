"""The Write tool: create a file or replace all of its contents."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolOutput
from zwans.tools.text import TextFile, unified_diff


class WriteInput(BaseModel):
    path: str = Field(description="Path to the file, relative to the workspace root.")
    content: str = Field(description="The complete new contents of the file.")


class WriteTool:
    name = "Write"
    description = (
        "Create a file, or replace all of an existing file's contents. Missing parent folders "
        "are created. To change part of a file, use Edit instead."
    )
    input_model = WriteInput
    read_only = False

    async def run(self, args: WriteInput, ctx: ToolContext) -> ToolOutput:
        existing, new_file = await _existing(args.path, ctx)
        await ctx.executor.write_bytes(args.path, existing.encode(args.content))
        return ToolOutput(content=f"Wrote {args.path}.", diff=_diff(args, existing, new_file))

    async def preview(self, args: WriteInput, ctx: ToolContext) -> str:
        """The diff this call would make, for the user to see before allowing it: a new
        file's diff comes from /dev/null."""
        existing, new_file = await _existing(args.path, ctx)
        return _diff(args, existing, new_file)


async def _existing(path: str, ctx: ToolContext) -> tuple[TextFile, bool]:
    """The file as it is, and whether it's new. An existing file keeps its encoding and line
    endings; a new one gets UTF-8 and "\n"."""
    try:
        return TextFile.decode(await ctx.executor.read_bytes(path)), False
    except FileNotFoundError:
        return TextFile(), True


def _diff(args: WriteInput, existing: TextFile, new_file: bool) -> str:
    after = args.content.replace("\r\n", "\n")
    diff = unified_diff(args.path, existing.text, after, new_file=new_file)
    if new_file and not diff:  # an empty new file: difflib has no lines to show
        diff = f"--- /dev/null\n+++ b/{args.path}\n"
    return diff

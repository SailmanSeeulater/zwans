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
        # An existing file keeps its encoding and line endings. A new file gets UTF-8 and "\n".
        new_file = False
        try:
            existing = TextFile.decode(await ctx.executor.read_bytes(args.path))
        except FileNotFoundError:
            existing, new_file = TextFile(), True
        await ctx.executor.write_bytes(args.path, existing.encode(args.content))
        after = args.content.replace("\r\n", "\n")
        diff = unified_diff(args.path, existing.text, after, new_file=new_file)
        return ToolOutput(content=f"Wrote {args.path}.", diff=diff)

"""The Write tool: create a file or replace all of its contents."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolOutput
from zwans.tools.text import TextFile


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
        try:
            existing = TextFile.decode(await ctx.executor.read_bytes(args.path))
        except FileNotFoundError:
            existing = TextFile()
        await ctx.executor.write_bytes(args.path, existing.encode(args.content))
        return ToolOutput(content=f"Wrote {args.path}.")

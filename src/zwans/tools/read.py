"""The Read tool: show a text file with line numbers."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.text import TextFile


class ReadInput(BaseModel):
    path: str = Field(description="Path to the file, relative to the workspace root.")
    offset: int = Field(default=1, ge=1, description="Line to start from. The first line is 1.")
    limit: int = Field(default=2000, ge=1, description="Maximum number of lines to return.")


class ReadTool:
    name = "Read"
    description = (
        "Read a text file in the workspace. Each line comes back prefixed with its line "
        "number. For a large file, use offset and limit to read one part at a time."
    )
    input_model = ReadInput
    read_only = True

    async def run(self, args: ReadInput, ctx: ToolContext) -> ToolOutput:
        data = await ctx.executor.read_bytes(args.path)
        if b"\x00" in data[:8192]:
            raise ToolError(f"{args.path} looks like a binary file, so it isn't shown.")
        text = TextFile.decode(data).text
        if not text:
            return ToolOutput(content=f"{args.path} is empty.")

        lines = text.removesuffix("\n").split("\n")
        start = args.offset - 1
        if start >= len(lines):
            raise ToolError(f"{args.path} has only {len(lines)} lines.")
        end = min(start + args.limit, len(lines))
        shown = [f"{n:>6}\t{line}" for n, line in enumerate(lines[start:end], start=args.offset)]
        if end < len(lines):
            shown.append(
                f"(Showing lines {args.offset}-{end} of {len(lines)}. Use offset to see more.)"
            )
        return ToolOutput(content="\n".join(shown))

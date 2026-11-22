"""The Read tool: show a text file with line numbers, or an image to the model."""

from pydantic import BaseModel, Field

from zwans.images import ImageError, describe, image_block, media_type
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.hints import only_file_named
from zwans.tools.text import TextFile


class ReadInput(BaseModel):
    path: str = Field(description="Path to the file, relative to the workspace root.")
    # 0 is taken as 1: models that count from 0 ask for it to mean "from the start".
    offset: int = Field(default=1, ge=0, description="Line to start from. The first line is 1.")
    limit: int = Field(default=2000, ge=1, description="Maximum number of lines to return.")


class ReadTool:
    name = "Read"
    description = (
        "Read a text file in the workspace. Each line comes back prefixed with its line "
        "number. For a large file, use offset and limit to read one part at a time. A PNG, "
        "JPEG, GIF or WebP image comes back as the image itself, for you to look at."
    )
    input_model = ReadInput
    read_only = True

    async def run(self, args: ReadInput, ctx: ToolContext) -> ToolOutput:
        try:
            data = await ctx.executor.read_bytes(args.path)
        except FileNotFoundError:
            # A guessed path to a file whose name is unique: reading that file instead
            # changes nothing, and saves a model that ignores the hint a round of retries.
            found = only_file_named(ctx, args.path)
            if found is None:
                raise
            output = await self.run(args.model_copy(update={"path": found}), ctx)
            note = (
                f"(There is no {args.path}. This is {found}, the only file of that name: "
                f"use that path from now on.)\n"
            )
            return ToolOutput(content=note + output.content, images=output.images)
        if media_type(data) is not None:
            try:
                image = image_block(data, args.path)
            except ImageError as exc:
                raise ToolError(str(exc)) from exc
            return ToolOutput(content=f"{args.path}: {describe(data)}", images=(image,))
        if b"\x00" in data[:8192]:
            raise ToolError(f"{args.path} looks like a binary file, so it isn't shown.")
        text = TextFile.decode(data).text
        if not text:
            return ToolOutput(content=f"{args.path} is empty.")

        lines = text.removesuffix("\n").split("\n")
        offset = max(args.offset, 1)
        start = offset - 1
        if start >= len(lines):
            raise ToolError(f"{args.path} has only {len(lines)} lines.")
        end = min(start + args.limit, len(lines))
        shown = [f"{n:>6}\t{line}" for n, line in enumerate(lines[start:end], start=offset)]
        if end < len(lines):
            shown.append(f"(Showing lines {offset}-{end} of {len(lines)}. Use offset to see more.)")
        return ToolOutput(content="\n".join(shown))

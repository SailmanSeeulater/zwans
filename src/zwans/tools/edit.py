"""The Edit tool: replace an exact piece of text in a file."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.text import TextFile


class EditInput(BaseModel):
    path: str = Field(description="Path to the file, relative to the workspace root.")
    old_string: str = Field(
        min_length=1,
        description="The exact text to replace, including indentation. It must appear once "
        "in the file unless replace_all is true.",
    )
    new_string: str = Field(description="The text to put in its place.")
    replace_all: bool = Field(
        default=False, description="Replace every occurrence instead of exactly one."
    )


class EditTool:
    name = "Edit"
    description = (
        "Replace exact text in an existing file. Read the file first and copy old_string from "
        "it exactly, including whitespace, leaving out the line-number prefixes Read adds. "
        "Include enough surrounding lines to make old_string unique, or set replace_all."
    )
    input_model = EditInput
    read_only = False

    async def run(self, args: EditInput, ctx: ToolContext) -> ToolOutput:
        file = TextFile.decode(await ctx.executor.read_bytes(args.path))
        # TextFile.text always uses "\n", so normalize the model's strings the same way.
        old = args.old_string.replace("\r\n", "\n")
        new = args.new_string.replace("\r\n", "\n")
        if old == new:
            raise ToolError("old_string and new_string are the same, so there is nothing to do.")

        count = file.text.count(old)
        if count == 0:
            raise ToolError(
                f"old_string was not found in {args.path}. Read the file again and copy the "
                "text exactly, including whitespace."
            )
        if count > 1 and not args.replace_all:
            raise ToolError(
                f"old_string appears {count} times in {args.path}. Add surrounding lines to "
                "make it unique, or set replace_all to true."
            )

        updated = file.text.replace(old, new)
        await ctx.executor.write_bytes(args.path, file.encode(updated))
        replaced = f"{count} occurrences" if count > 1 else "1 occurrence"
        return ToolOutput(content=f"Replaced {replaced} in {args.path}.")

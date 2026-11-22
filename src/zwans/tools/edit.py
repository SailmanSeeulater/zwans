"""The Edit tool: replace an exact piece of text in a file."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.text import TextFile, unified_diff


class EditInput(BaseModel):
    path: str = Field(description="Path to the file, relative to the workspace root.")
    old_string: str = Field(
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
        updated, count = replace_in(file.text, args)
        await ctx.executor.write_bytes(args.path, file.encode(updated))
        replaced = f"{count} occurrences" if count > 1 else "1 occurrence"
        return ToolOutput(
            content=f"Replaced {replaced} in {args.path}.",
            diff=unified_diff(args.path, file.text, updated),
        )

    async def preview(self, args: EditInput, ctx: ToolContext) -> str:
        """The diff this call would make, with the file's own line numbers, for the user to
        see before allowing it. Raises ToolError when the call would fail."""
        file = TextFile.decode(await ctx.executor.read_bytes(args.path))
        updated, _ = replace_in(file.text, args)
        return unified_diff(args.path, file.text, updated)


def replace_in(text: str, args: EditInput) -> tuple[str, int]:
    """The file's text with the edit made, and how many places it changed. Raises ToolError
    when the edit doesn't fit the text. MultiEdit makes each of its edits with this too."""
    # TextFile.text always uses "\n", so normalize the model's strings the same way.
    old = args.old_string.replace("\r\n", "\n")
    new = args.new_string.replace("\r\n", "\n")
    if not old:
        raise ToolError(
            "old_string is empty, so there is nothing to replace. To create a file, or to "
            "replace everything in one, use Write. To add text to a file, put the line before "
            "it in old_string, and that line followed by the new text in new_string."
        )
    if old == new:
        raise ToolError("old_string and new_string are the same, so there is nothing to do.")
    count = text.count(old)
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
    return text.replace(old, new), count

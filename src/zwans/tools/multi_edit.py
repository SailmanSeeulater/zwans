"""The MultiEdit tool: several exact replacements, in one file or across files, as one step.

A change that touches five places costs five model calls with Edit, each one resending the
conversation. This makes it one. Either every replacement is made or none is, so a change
that only half fits never leaves the files in between.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.edit import EditInput, replace_in
from zwans.tools.text import TextFile, unified_diff


class MultiEditInput(BaseModel):
    edits: list[EditInput] = Field(
        min_length=1,
        description="The replacements, made in order. Each has a path, old_string, new_string "
        "and optionally replace_all, as for Edit. A later one for the same file sees the "
        "file as the earlier ones left it.",
    )


@dataclass
class _Planned:
    path: str  # as the model first wrote it
    file: TextFile
    text: str  # with the edits so far
    count: int = 0  # places changed


class MultiEditTool:
    name = "MultiEdit"
    description = (
        "Make several exact replacements in one call, in one file or across files. Use it "
        "instead of repeated Edit calls whenever a change touches more than one place. Either "
        "all of them are made or none: if one doesn't fit, nothing is written and the error "
        "says which. Each replacement follows Edit's rules: read the file first, copy "
        "old_string from it exactly, and make it unique or set replace_all."
    )
    input_model = MultiEditInput
    read_only = False

    async def run(self, args: MultiEditInput, ctx: ToolContext) -> ToolOutput:
        planned = await _plan(args, ctx)
        for plan in planned:  # every edit fits, so only now is anything written
            await ctx.executor.write_bytes(plan.path, plan.file.encode(plan.text))
        places = sum(plan.count for plan in planned)
        per_file = ", ".join(f"{plan.path} ({plan.count})" for plan in planned)
        files = "1 file" if len(planned) == 1 else f"{len(planned)} files"
        return ToolOutput(
            content=f"Replaced {places} {'place' if places == 1 else 'places'} in {files}: "
            f"{per_file}.",
            diff=_diff(planned),
        )

    async def preview(self, args: MultiEditInput, ctx: ToolContext) -> str:
        """The diff this call would make, for the user to see before allowing it. Raises
        ToolError when the call would fail."""
        return _diff(await _plan(args, ctx))


async def _plan(args: MultiEditInput, ctx: ToolContext) -> list[_Planned]:
    """Each file with all of its edits made, in the order the files were first named."""
    planned: dict[str, _Planned] = {}
    total = len(args.edits)
    for number, edit in enumerate(args.edits, 1):
        key = ctx.executor.relative(edit.path)  # so ./a.py and a.py are one file
        if key not in planned:
            file = TextFile.decode(await ctx.executor.read_bytes(edit.path))
            planned[key] = _Planned(edit.path, file, file.text)
        plan = planned[key]
        try:
            plan.text, count = replace_in(plan.text, edit)
        except ToolError as exc:
            earlier = " (after the earlier edits to that file)" if plan.count else ""
            raise ToolError(
                f"Edit {number} of {total} doesn't fit{earlier}, so nothing was changed. {exc}"
            ) from exc
        plan.count += count
    return list(planned.values())


def _diff(planned: list[_Planned]) -> str:
    return "".join(unified_diff(plan.path, plan.file.text, plan.text) for plan in planned)

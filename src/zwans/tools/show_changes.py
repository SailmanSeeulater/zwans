"""The ShowChanges tool: everything this session has changed in the workspace, as one diff.

It reads the checkpoints Zwans already keeps for undo, so it covers what Bash commands
changed as well as the file tools, and it works in a folder that isn't a git repository.
The model uses it to review its own work before it says it's done.
"""

from pydantic import BaseModel, Field

from zwans.checkpoints import CheckpointError, Checkpoints
from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_DIFF_CHARS = 40_000


class ShowChangesInput(BaseModel):
    names_only: bool = Field(
        default=False,
        description="List only which files were added, changed or deleted, without the diff.",
    )


class ShowChangesTool:
    name = "ShowChanges"
    description = (
        "Show everything changed in the workspace since this session began: the files added, "
        "changed and deleted, and a diff of them. It includes what commands changed, not "
        "only your edits. Call it before saying you're done, and read the diff as a "
        "reviewer would: leftovers, debugging lines, and edits you didn't mean."
    )
    input_model = ShowChangesInput
    read_only = True

    def __init__(self, checkpoints: Checkpoints | None) -> None:
        self.checkpoints = checkpoints

    async def run(self, args: ShowChangesInput, ctx: ToolContext) -> ToolOutput:
        checkpoints = self.checkpoints
        if checkpoints is None or not checkpoints.available:
            why = (
                checkpoints.problem if checkpoints else "Checkpoints are off (checkpoints = false)."
            )
            raise ToolError(
                f"{why} Without them Zwans can't tell what this session changed. In a git "
                "repository, `git status` and `git diff` with Bash show what isn't committed."
            )
        try:
            changes, diff = await checkpoints.since_start()
        except (CheckpointError, OSError, TimeoutError) as exc:
            raise ToolError(f"Couldn't compare the workspace with how it started: {exc}") from exc
        if not changes:
            return ToolOutput(
                content="Nothing in the workspace has changed since this session began."
            )
        files = "\n".join(f"{change.status:<8}{change.path}" for change in changes)
        count = "1 file" if len(changes) == 1 else f"{len(changes)} files"
        if args.names_only:
            return ToolOutput(content=f"{count} changed since this session began:\n{files}")
        if len(diff) > MAX_DIFF_CHARS:
            rest = len(diff) - MAX_DIFF_CHARS
            diff = f"{diff[:MAX_DIFF_CHARS]}\n[... {rest:,} more characters of diff not shown]"
        return ToolOutput(content=f"{count} changed since this session began:\n{files}\n\n{diff}")

"""The Bash tool: run a shell command in the workspace."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolOutput


class BashInput(BaseModel):
    command: str = Field(description="The command to run.")
    timeout: int = Field(
        default=120, ge=1, le=600, description="Seconds to wait before stopping the command."
    )


class BashTool:
    name = "Bash"
    description = (
        "Run a shell command with bash in the workspace folder and return its output (stdout "
        "and stderr together) and exit code. Each call starts a new shell, so cd and variables "
        "don't carry over. Long output is shortened in the middle. For files, use Read, Edit, "
        "Write, Glob and Grep instead of cat, sed, find and grep."
    )
    input_model = BashInput
    read_only = False

    async def run(self, args: BashInput, ctx: ToolContext) -> ToolOutput:
        result = await ctx.executor.run_shell(args.command, timeout=args.timeout)
        output = result.output.rstrip() or "(no output)"
        if result.timed_out:
            stopped = f"Stopped after {args.timeout}s because it hadn't finished."
            return ToolOutput(content=f"{output}\n{stopped}", is_error=True)
        return ToolOutput(content=f"{output}\n(exit code {result.exit_code})")

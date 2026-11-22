"""The Glob tool: find files by name pattern."""

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped
from zwans.tools.hints import raise_if_missing

MAX_PATHS = 200


class GlobInput(BaseModel):
    pattern: str = Field(description='Glob pattern, such as "**/*.py" or "tests/test_*.py".')
    path: str = Field(default=".", description="Folder to search, relative to the workspace root.")


class GlobTool:
    name = "Glob"
    description = (
        "Find files by name pattern. Returns matching paths, most recently modified first. "
        "Files ignored by .gitignore are skipped, and so are folders such as node_modules and "
        ".venv unless path points inside one or the pattern names one."
    )
    input_model = GlobInput
    read_only = True

    async def run(self, args: GlobInput, ctx: ToolContext) -> ToolOutput:
        folder = ctx.executor.search_path(args.path)
        argv = ["rg", "--files", "--no-require-git", "--path-separator", "/"]
        argv += skipped(args.pattern)
        argv += ["--sortr", "modified", "--glob", args.pattern, folder]
        result = await ctx.executor.run(argv, timeout=30)
        if result.exit_code not in (0, 1):  # ripgrep exits 1 when nothing matched
            raise_if_missing(ctx, args.path, result.output)
            raise ToolError(f"Glob failed: {result.output.strip()}")

        paths = [line.removeprefix("./") for line in result.output.splitlines() if line]
        if not paths:
            return ToolOutput(content="No files matched.")
        shown = paths[:MAX_PATHS]
        if len(paths) > MAX_PATHS:
            shown.append(f"({len(paths) - MAX_PATHS} more not shown. Use a narrower pattern.)")
        return ToolOutput(content="\n".join(shown))

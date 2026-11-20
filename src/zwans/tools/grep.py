"""The Grep tool: search file contents with ripgrep."""

from pydantic import BaseModel, Field

from zwans.checkpoints import EXCLUDED
from zwans.tools.base import ToolContext, ToolError, ToolOutput


def skipped(*patterns: str | None) -> list[str]:
    """ripgrep arguments that skip big folders of installed packages and build output, even
    without a .gitignore. ripgrep still searches inside one when it's the path asked for, and
    one a glob names, such as "node_modules/**/package.json", isn't skipped."""
    named = " ".join(pattern for pattern in patterns if pattern)
    kept = [name for name in EXCLUDED if name.rstrip("/") not in named]
    return [arg for name in kept for arg in ("--glob", f"!{name}")]


class GrepInput(BaseModel):
    pattern: str = Field(description="Regular expression to search for, in ripgrep syntax.")
    path: str = Field(
        default=".",
        description="File or folder to search, relative to the workspace root, or a saved "
        "tool output file.",
    )
    glob: str | None = Field(
        default=None, description='Only search files whose names match this, such as "*.py".'
    )
    ignore_case: bool = Field(default=False, description="Match letters regardless of case.")
    files_only: bool = Field(
        default=False, description="Return only the paths of matching files, not the lines."
    )


class GrepTool:
    name = "Grep"
    description = (
        "Search file contents with a regular expression. Returns matching lines as "
        "path:line:text, or only file paths when files_only is true. Files ignored by "
        ".gitignore are skipped, and so are folders such as node_modules and .venv unless "
        "path points inside one or glob names one. It can also search saved tool output."
    )
    input_model = GrepInput
    read_only = True

    async def run(self, args: GrepInput, ctx: ToolContext) -> ToolOutput:
        argv = ["rg", "--color", "never", "--no-require-git", "--path-separator", "/"]
        argv += ["--max-columns", "300", *skipped(args.glob)]
        if args.files_only:
            argv.append("--files-with-matches")
        else:
            argv += ["--line-number", "--no-heading", "--with-filename"]
        if args.ignore_case:
            argv.append("--ignore-case")
        if args.glob:
            argv += ["--glob", args.glob]
        argv += ["--regexp", args.pattern, ctx.executor.search_path(args.path)]

        result = await ctx.executor.run(argv, timeout=60)
        if result.exit_code == 1:  # ripgrep exits 1 when nothing matched
            return ToolOutput(content="No matches.")
        if result.exit_code != 0:
            raise ToolError(f"Grep failed: {result.output.strip()}")
        lines = [line.removeprefix("./") for line in result.output.splitlines()]
        return ToolOutput(content="\n".join(lines))

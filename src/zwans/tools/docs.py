"""The Docs tool: what an installed Python module, class or function really is.

A model that half-remembers a library writes calls to functions that aren't there. This
asks the project's own Python, with pydoc, so the answer is the version that is installed,
and it needs no network. It is Python only.

Importing a module runs its code, so the policy judges a call as the command it runs.
"""

import re
import shlex
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

NAME = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$")
MAX_CHARS = 8_000
TIMEOUT = 30


class DocsInput(BaseModel):
    name: str = Field(
        description="A module, class or function by its dotted name, such as json.dumps, "
        "pathlib.Path or requests.Session.get."
    )


class DocsTool:
    name = "Docs"
    description = (
        "Look up an installed Python module, class or function by its dotted name and get "
        "its signature and documentation, from the version this project has installed. Use "
        "it instead of guessing at a library's functions or their arguments. Python only."
    )
    input_model = DocsInput
    read_only = False  # importing a module runs it

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        name = args.get("name")
        return [_command(name)] if isinstance(name, str) and NAME.match(name.strip()) else []

    async def run(self, args: DocsInput, ctx: ToolContext) -> ToolOutput:
        name = args.name.strip()
        if not NAME.match(name):
            raise ToolError(f"{name!r} isn't a dotted name such as json.dumps.")
        result = await ctx.executor.run_shell(_command(name), timeout=TIMEOUT)
        output = result.output.strip()
        if result.timed_out:
            raise ToolError(f"Looking up {name} took over {TIMEOUT}s.")
        if result.exit_code != 0 or output.startswith("No Python documentation found"):
            first = output.splitlines()[0] if output else f"exit code {result.exit_code}"
            raise ToolError(
                f"Nothing found for {name}: {first} Check the spelling, or that the package "
                "is installed in this project's Python."
            )
        if len(output) > MAX_CHARS:
            rest = len(output) - MAX_CHARS
            output = f"{output[:MAX_CHARS]}\n[... {rest:,} more characters; ask for one member]"
        return ToolOutput(content=output)


def _command(name: str) -> str:
    return f"python -m pydoc {shlex.quote(name.strip())}"

"""The Profile tool: run Python code under cProfile and say where the time went.

"Make this faster" starts with knowing what is slow, and a model guessing optimizes the
wrong thing. This runs a script or module the way `python` would, under the profiler built
into Python, and returns the functions that took the most time: by their own time, and by
the time spent in them and what they called. The numbers come from the run, not a guess.

The policy judges a call as the command it runs, as if Bash ran it.
"""

import secrets
import shlex
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

TIMEOUT = 600
MAX_OUTPUT_CHARS = 4_000  # of what the program printed
# Reads the profile and prints the top functions, each on a line: run with the project's
# Python, which wrote the file. Arguments: the file, how many to show.
REPORT = r"""
import os, pstats, sys
stats = pstats.Stats(sys.argv[1])
top = int(sys.argv[2])
total = stats.total_tt
here = os.getcwd() + os.sep
def where(key):
    path, line, name = key
    if path == "~":
        return name.strip("<>")
    path = path[len(here):] if path.startswith(here) else path
    for marker in ("site-packages" + os.sep, "lib" + os.sep + "python"):
        if marker in path:
            path = "…" + os.sep + path.split(marker, 1)[1]
    return f"{name} ({path}:{line})"
rows = stats.stats.items()
print(f"TOTAL {total:.3f}")
for title, index in (("own", 2), ("cumulative", 3)):
    print(f"BY {title}")
    ranked = sorted(rows, key=lambda r: r[1][index], reverse=True)[:top]
    for key, (_, calls, own, cumulative, _) in ranked:
        print(f"{cumulative:.3f}\t{own:.3f}\t{calls}\t{where(key)}")
"""


class ProfileInput(BaseModel):
    target: str = Field(
        description='What to run, as you would after "python": a script and its arguments, '
        'as "scripts/build.py --fast", or a module, as "-m myapp.cli import data.csv".'
    )
    top: int = Field(default=15, ge=5, le=50, description="How many functions to list.")


class ProfileTool:
    name = "Profile"
    description = (
        "Run a Python script or module under cProfile and get the functions that took the "
        "most time, by their own time and including what they called, with how often each "
        "was called. Use it before optimizing, to find what's actually slow."
    )
    input_model = ProfileInput
    read_only = False  # it runs the project's code

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        target = args.get("target")
        return [f"python {target}"] if isinstance(target, str) else []

    async def run(self, args: ProfileInput, ctx: ToolContext) -> ToolOutput:
        target = args.target.strip()
        if target.startswith("python "):
            target = target.removeprefix("python ").strip()
        if not target:
            raise ToolError("target names a script or module to run.")
        try:
            shlex.split(target)
        except ValueError as exc:
            raise ToolError(f"target can't be read as a command line: {exc}") from exc
        data = f".zwans-profile-{secrets.token_hex(4)}"
        run = f"python -m cProfile -o {data} {target}"
        report = f"python -c {shlex.quote(REPORT)} {data} {args.top}"
        try:
            result = await ctx.executor.run_shell(run, timeout=TIMEOUT)
            if result.timed_out:
                raise ToolError(f"The program was stopped after {TIMEOUT}s; profile a smaller run.")
            reported = await ctx.executor.run_shell(report, timeout=60)
        finally:
            await ctx.executor.run(["rm", "-f", data], timeout=30)
        printed = result.output.strip()
        if reported.exit_code != 0 or "TOTAL" not in reported.output:
            detail = printed or reported.output.strip() or "no output"
            raise ToolError(f"No profile came out (exit code {result.exit_code}):\n{_end(detail)}")
        lines = [_summary(reported.output, result.exit_code)]
        if printed:
            lines += ["", "What it printed:", _end(printed)]
        return ToolOutput(content="\n".join(lines))


def _summary(report: str, exit_code: int | None) -> str:
    total = 0.0
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in report.splitlines():
        if line.startswith("TOTAL "):
            total = float(line.split()[1])
        elif line.startswith("BY "):
            current = sections.setdefault(line[3:], [])
        elif current is not None and line.count("\t") >= 3:
            cumulative, own, calls, where = line.split("\t", 3)
            share = f"{100 * float(own) / total:5.1f}%" if total else "     "
            current.append(
                f"{float(cumulative):9.3f}s {float(own):9.3f}s {share} {int(calls):>9,}  {where}"
            )
    ended = "" if exit_code == 0 else f" The program exited with code {exit_code}."
    head = f"The run took {total:.3f}s of CPU in Python.{ended}"
    columns = "   cumul.       own  own %     calls  function"
    parts = [head]
    for title, label in (
        ("own", "By their own time"),
        ("cumulative", "Including what they called"),
    ):
        if sections.get(title):
            parts += ["", f"{label}:", columns, *sections[title]]
    return "\n".join(parts)


def _end(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return f"[... {len(text) - MAX_OUTPUT_CHARS:,} earlier characters]\n" + text[-MAX_OUTPUT_CHARS:]

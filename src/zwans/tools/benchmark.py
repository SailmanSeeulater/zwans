"""The Benchmark tool: how long a command takes, measured enough times to trust.

One timing says little: caches, other programs and the machine's clock speed move it by
more than many changes do. This runs a command several times after a warmup and reports the
median with the spread, and compares two commands run in turns (A, B, A, B, so drift hits
both alike) with a Mann-Whitney U test, which says whether the difference is bigger than
the noise. It remembers each command's last result for the session, so measuring the same
command after an edit compares it with before.

The policy judges a call as the commands it runs, as if Bash ran them.
"""

import math
import statistics
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_FAILURE_OUTPUT = 2_000  # characters from the end of a failed run's output
NOISY = 0.10  # spread (standard deviation over median) above which a warning is given
SIGNIFICANCE = 0.05
SHELL_PROBES = 3  # timings of `true`, to say how much of each run is starting the shell


class BenchmarkInput(BaseModel):
    command: str = Field(description="The shell command to time, run from the workspace root.")
    runs: int = Field(default=10, ge=3, le=100, description="Timed runs of each command.")
    warmup: int = Field(default=1, ge=0, le=10, description="Untimed runs first, to fill caches.")
    against: str | None = Field(
        default=None,
        description="A second command to compare with, run in turns with the first.",
    )
    timeout: int = Field(
        default=600, ge=5, le=3600, description="Seconds all the runs together may take."
    )


@dataclass(frozen=True)
class Stats:
    median: float
    mean: float
    low: float
    high: float
    stdev: float

    @property
    def spread(self) -> float:
        return self.stdev / self.median if self.median else 0.0


class BenchmarkTool:
    name = "Benchmark"
    description = (
        "Measure how long a shell command takes, reliably: it runs several times after a "
        "warmup and you get the median, mean, min, max and spread. Give `against` to "
        "compare two commands (run in turns), with whether the difference is beyond noise. "
        "Measuring the same command again later in the session compares it with the last "
        "result, so you can time it before and after a change."
    )
    input_model = BenchmarkInput
    read_only = False  # it runs the commands

    def __init__(self) -> None:
        # The last timings of each command in this session, by the command's text
        self._previous: dict[str, list[float]] = {}

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call would run, from its raw input, for the policy to judge."""
        given = [args.get("command"), args.get("against")]
        return [command for command in given if isinstance(command, str) and command.strip()]

    async def run(self, args: BenchmarkInput, ctx: ToolContext) -> ToolOutput:
        commands = [args.command.strip()]
        if args.against is not None and args.against.strip():
            commands.append(args.against.strip())
        if not commands[0]:
            raise ToolError("command is the shell command to time.")
        if len(commands) == 2 and commands[0] == commands[1]:
            raise ToolError("against is the same command; leave it out, or give another one.")
        deadline = time.monotonic() + args.timeout
        for _ in range(args.warmup):
            for command in commands:
                await _time(ctx, command, deadline, args.timeout, "a warmup run")
        timings: list[list[float]] = [[] for _ in commands]
        stopped = False
        for number in range(1, args.runs + 1):
            try:
                for index, command in enumerate(commands):
                    timings[index].append(
                        await _time(ctx, command, deadline, args.timeout, f"run {number}")
                    )
            except _OutOfTime:
                stopped = True
                break
        done = min(len(times) for times in timings)
        timings = [times[:done] for times in timings]
        if done < 3:
            raise ToolError(
                f"Only {done} of {args.runs} runs fit in {args.timeout}s. Raise timeout or "
                "time a shorter command."
            )
        shell = await _shell_cost(ctx)
        previous = {command: self._previous.get(command) for command in commands}
        for command, times in zip(commands, timings, strict=True):
            self._previous[command] = times
        return ToolOutput(content=_report(args, commands, timings, previous, stopped, shell))


class _OutOfTime(Exception):
    pass


async def _time(ctx: ToolContext, command: str, deadline: float, timeout: int, which: str) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _OutOfTime
    start = time.perf_counter()
    result = await ctx.executor.run_shell(command, timeout=left)
    elapsed = time.perf_counter() - start
    if result.timed_out:
        if which.startswith("run"):
            raise _OutOfTime
        raise ToolError(f"The warmup of `{command}` didn't finish within {timeout}s.")
    if result.exit_code != 0:
        output = result.output.strip() or "(no output)"
        if len(output) > MAX_FAILURE_OUTPUT:
            output = "[...]\n" + output[-MAX_FAILURE_OUTPUT:]
        raise ToolError(
            f"`{command}` failed on {which} (exit code {result.exit_code}), so there's "
            f"nothing fair to time. The end of its output:\n{output}"
        )
    return elapsed


async def _shell_cost(ctx: ToolContext) -> float | None:
    """The median time to start a shell that does nothing, which every timing includes."""
    times = []
    for _ in range(SHELL_PROBES):
        start = time.perf_counter()
        result = await ctx.executor.run_shell("true", timeout=10)
        if result.exit_code != 0:
            return None
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def stats(times: list[float]) -> Stats:
    return Stats(
        median=statistics.median(times),
        mean=statistics.fmean(times),
        low=min(times),
        high=max(times),
        stdev=statistics.stdev(times) if len(times) > 1 else 0.0,
    )


def mann_whitney_p(a: list[float], b: list[float]) -> float:
    """The two-sided p-value of a Mann-Whitney U test of two samples, by the normal
    approximation with a correction for ties and for continuity."""
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return 1.0
    pooled = sorted([(value, 0) for value in a] + [(value, 1) for value in b])
    n = n1 + n2
    rank_sum = 0.0  # of the first sample
    ties = 0.0
    start = 0
    while start < n:
        end = start
        while end + 1 < n and pooled[end + 1][0] == pooled[start][0]:
            end += 1
        rank = (start + end) / 2 + 1  # the average rank of a run of equal values
        rank_sum += rank * sum(1 for i in range(start, end + 1) if pooled[i][1] == 0)
        count = end - start + 1
        ties += count**3 - count
        start = end + 1
    u = rank_sum - n1 * (n1 + 1) / 2
    mean = n1 * n2 / 2
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if variance <= 0:
        return 1.0
    z = max(abs(u - mean) - 0.5, 0.0) / math.sqrt(variance)
    return min(1.0, math.erfc(z / math.sqrt(2)))


def duration(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:.2f} s"
    ms = seconds * 1000
    if ms >= 100:
        return f"{ms:.0f} ms"
    if ms >= 10:
        return f"{ms:.1f} ms"
    return f"{ms:.2f} ms"


def compare(new: list[float], old: list[float], new_name: str, old_name: str) -> str:
    """One line saying how the new timings compare with the old ones."""
    new_median, old_median = statistics.median(new), statistics.median(old)
    p = mann_whitney_p(new, old)
    if old_median and new_median >= old_median:
        how = f"{new_median / old_median:.2f}x slower than"
    elif new_median:
        how = f"{old_median / new_median:.2f}x faster than"
    else:
        how = "as fast as"
    medians = f"median {duration(new_median)} vs {duration(old_median)}"
    if p < SIGNIFICANCE:
        verdict = f"beyond noise (Mann-Whitney p = {p:.3g})"
    else:
        verdict = f"within noise (Mann-Whitney p = {p:.2g}), so no real difference shows"
        if min(len(new), len(old)) < 4:
            verdict += "; 3 runs are too few to show one, use 8 or more"
    return f"{new_name} is {how} {old_name} ({medians}): {verdict}."


def _report(
    args: BenchmarkInput,
    commands: list[str],
    timings: list[list[float]],
    previous: dict[str, list[float] | None],
    stopped: bool,
    shell: float | None,
) -> str:
    done = len(timings[0])
    labels = ["A", "B"][: len(commands)]
    turns = ", in turns" if len(commands) == 2 else ""
    warm = f", after {args.warmup} warmup run{'s' if args.warmup != 1 else ''}"
    out = [f"{done} runs of each{warm if args.warmup else ''}{turns}."]
    if stopped:
        out.append(f"(Stopped at {done} of {args.runs} runs: the {args.timeout}s timeout.)")
    if len(commands) == 2:
        out += [f"{label}: {command}" for label, command in zip(labels, commands, strict=True)]
    out.append("")
    head = ["", "median", "mean", "min", "max", "std dev", "spread"]
    rows = [head]
    measured = [stats(times) for times in timings]
    for label, s in zip(labels, measured, strict=True):
        values = [s.median, s.mean, s.low, s.high, s.stdev]
        rows.append([label if len(commands) == 2 else "", *map(duration, values)])
        rows[-1].append(f"±{100 * s.spread:.1f}%")
    widths = [max(len(row[i]) for row in rows) for i in range(len(head))]
    for row in rows:
        cells = [row[0].ljust(widths[0])] + [
            cell.rjust(width) for cell, width in zip(row[1:], widths[1:], strict=True)
        ]
        out.append("  ".join(cells).rstrip())
    if len(commands) == 2:
        out += ["", compare(timings[1], timings[0], "B", "A")]
    for label, command, times in zip(labels, commands, timings, strict=True):
        before = previous.get(command)
        if before:
            name = label if len(commands) == 2 else "It"
            line = compare(times, before, name, "the last time it was measured")
            out += ["", "Against the previous result for this command in this session:", line]
    noisy = [
        label or "the command"
        for label, s in zip(labels if len(commands) == 2 else [""], measured, strict=True)
        if s.spread > NOISY
    ]
    if noisy:
        suggestion = min(100, max(30, args.runs * 3))
        out += [
            "",
            f"Warning: the runs of {' and '.join(noisy)} vary a lot (spread over 10% of the "
            f"median). More runs (runs={suggestion}) or a quieter machine give a steadier "
            "answer.",
        ]
    if shell is not None:
        out += ["", f"Each time includes starting a shell, about {duration(shell)}."]
    return "\n".join(out)

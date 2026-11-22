"""/loop until: keep working on a task until a check passes.

Zwans runs the check (a command the person gives, such as `pytest -q`) itself, not the
model: first to see where things stand, then after each turn. While it fails, its output
goes back to the model as the next turn's prompt. The loop ends when the check passes,
after `rounds` turns, or when a turn stops early: interrupted, out of budget, or on an
error. Each round is an ordinary turn, so it can be steered, undone and is counted in what
the session cost.
"""

import asyncio
import shlex
from dataclasses import dataclass

from zwans.events import LoopChecked, LoopEnded
from zwans.executor.base import CommandResult, Executor
from zwans.session import Session

DEFAULT_ROUNDS = 5
MOST_ROUNDS = 25
CHECK_TIMEOUT = 600.0  # seconds a check may take
OUTPUT_CHARS = 4_000  # of a failing check's output, its end, sent to the model
USAGE = (
    'Usage: /loop [rounds] until <check>, or /loop [rounds] until "<check>" <task>. '
    'For example: /loop until pytest -q, or /loop 8 until "npm test" fix the date parsing.'
)
STOPPED = {"interrupted": "stopped", "budget": "budget", "error": "error", "refusal": "error"}


@dataclass(frozen=True)
class LoopSpec:
    check: str
    task: str = ""
    rounds: int = DEFAULT_ROUNDS


def parse_loop(argument: str) -> LoopSpec:
    """What follows /loop. Raises ValueError, with USAGE, when it can't be read."""
    words = argument.strip().split(maxsplit=1)
    rounds = DEFAULT_ROUNDS
    if words and words[0].isdigit():
        rounds = int(words[0])
        argument = words[1] if len(words) > 1 else ""
        if not 1 <= rounds <= MOST_ROUNDS:
            raise ValueError(f"Rounds go from 1 to {MOST_ROUNDS}.")
    head, _, rest = argument.strip().partition(" ")
    if head != "until" or not rest.strip():
        raise ValueError(USAGE)
    rest = rest.strip()
    if rest[0] in "\"'":
        try:
            lexer = shlex.shlex(rest, posix=True)
            lexer.whitespace_split = True
            check = next(iter(lexer))
        except (ValueError, StopIteration) as exc:
            raise ValueError(USAGE) from exc
        quote = rest[0]
        end = rest.index(quote, 1) + 1
        return LoopSpec(check=check, task=rest[end:].strip(), rounds=rounds)
    return LoopSpec(check=rest, rounds=rounds)


def _tail(output: str) -> str:
    text = output.strip()
    return text if len(text) <= OUTPUT_CHARS else "…" + text[-OUTPUT_CHARS:]


def _shown(output: str) -> str:
    """A check's output for the model: its end in a code block, or a note there was none."""
    text = _tail(output)
    return f"```\n{text}\n```" if text else "It printed nothing."


def _failed(result: CommandResult) -> str:
    if result.timed_out:
        return f"timed out after {CHECK_TIMEOUT:.0f}s"
    return f"exit code {result.exit_code}"


def first_prompt(spec: LoopSpec, result: CommandResult) -> str:
    task = spec.task or f"Make `{spec.check}` pass."
    return (
        f"{task}\n\nI'm running `{spec.check}` after each of your turns and sending you what "
        f"fails, until it passes (at most {spec.rounds} turns). It fails now "
        f"({_failed(result)}). {_shown(result.output)}"
    )


def again_prompt(spec: LoopSpec, result: CommandResult, round_: int) -> str:
    return (
        f"`{spec.check}` still fails ({_failed(result)}), after turn {round_} of "
        f"{spec.rounds}. {_shown(result.output)}\n\nKeep going."
    )


async def run_loop(session: Session, executor: Executor, spec: LoopSpec) -> str:
    """Run the loop. Returns why it ended: "passed", "rounds", "stopped", "budget" or
    "error". Cancelling it (Ctrl+C, or Stop) ends it as "stopped", then re-raises."""

    async def check(round_: int) -> CommandResult:
        result = await executor.run_shell(spec.check, CHECK_TIMEOUT)
        session.emit(
            LoopChecked(
                check=spec.check,
                round=round_,
                rounds=spec.rounds,
                passed=result.exit_code == 0 and not result.timed_out,
                exit_code=result.exit_code,
                output=_tail(result.output),
            )
        )
        return result

    def end(reason: str, detail: str) -> str:
        session.emit(LoopEnded(reason=reason, detail=detail, check=spec.check))
        return reason

    try:
        result = await check(0)
        if result.exit_code == 0 and not result.timed_out:
            return end("passed", f"`{spec.check}` already passes, so nothing was sent.")
        for round_ in range(1, spec.rounds + 1):
            prompt = (
                first_prompt(spec, result)
                if round_ == 1
                else again_prompt(spec, result, round_ - 1)
            )
            stop_reason = await session.send(prompt)
            if stop_reason in STOPPED:
                return end(STOPPED[stop_reason], f"The turn ended early ({stop_reason}).")
            result = await check(round_)
            if result.exit_code == 0 and not result.timed_out:
                turns = "turn" if round_ == 1 else "turns"
                return end("passed", f"`{spec.check}` passes, after {round_} {turns}.")
        return end("rounds", f"`{spec.check}` still fails after {spec.rounds} turns.")
    except asyncio.CancelledError:
        end("stopped", "Stopped.")
        raise

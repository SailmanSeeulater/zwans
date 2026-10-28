"""The baseline: the same tasks through Claude Code (`claude -p`), to see how far Zwans is
from a production harness.

Claude Code runs with --bare, so the user's CLAUDE.md, hooks, plugins and MCP servers stay
out of it and every attempt starts the same way. --bare only accepts ANTHROPIC_API_KEY, so
the baseline is billed per token like Zwans's own runs. Web tools are turned off because the
tasks are offline, and permission prompts are skipped because nobody is there to answer
them; like Zwans's own attempts, it works in a throwaway copy of the task.
"""

import asyncio
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from zwans.config import Config
from zwans.eval.runner import AgentRun, Budget
from zwans.eval.task import Task
from zwans.executor.local import kill_tree, own_process_group

STDERR_CHARS = 2_000  # of Claude Code's own error output, kept when it fails to finish


class ClaudeCodeAgent:
    def __init__(
        self, config: Config, api_key: str, command: Sequence[str] = ("claude",), version: str = ""
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.command = list(command)
        self.name = f"claude-code {version}".strip()

    def argv(self, task: Task) -> list[str]:
        return [
            *self.command,
            "-p",
            task.prompt,
            "--bare",
            "--output-format",
            "stream-json",
            "--verbose",  # stream-json needs it
            "--model",
            self.config.model,
            "--effort",
            self.config.effort,
            "--max-budget-usd",
            f"{task.max_cost}",
            "--permission-mode",
            "bypassPermissions",
            "--disallowedTools",
            "WebFetch WebSearch",
            "--no-session-persistence",
        ]

    async def attempt(
        self, task: Task, workspace: Path, scratch: Path, budget: Budget, transcript: Path
    ) -> AgentRun:
        env = {**os.environ, "ANTHROPIC_API_KEY": self.api_key}
        transcript.parent.mkdir(parents=True, exist_ok=True)
        stderr_path = scratch / "claude-stderr.txt"
        timed_out = False
        with transcript.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = await asyncio.create_subprocess_exec(
                *self.argv(task),
                cwd=workspace,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                **own_process_group(),
            )
            try:
                await asyncio.wait_for(process.wait(), task.timeout)
            except TimeoutError:
                timed_out = True
            finally:
                await kill_tree(process)  # also after a cancel, so nothing is left running

        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
        run = parse_stream(lines)
        budget.spent += run.dollars  # charged at the end: Claude Code doesn't report as it goes
        if timed_out:
            run.stop_reason = "timeout"
        elif run.stop_reason == "error" and not run.errors:
            output = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            run.errors.append(output[-STDERR_CHARS:] or f"claude exited {process.returncode}")
        return run


def parse_stream(lines: Iterable[str]) -> AgentRun:
    """Read Claude Code's stream-json output into the numbers the report needs."""
    run = AgentRun(stop_reason="error")  # until a result line says otherwise
    messages: set[str] = set()
    calls: set[str] = set()
    for line in lines:
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        message = event.get("message") or {}
        raw = message.get("content")
        content: list[dict[str, Any]] = raw if isinstance(raw, list) else []
        if kind == "assistant":
            messages.add(message.get("id", str(len(messages))))
            calls.update(b.get("id", "") for b in content if b.get("type") == "tool_use")
        elif kind == "user":
            run.tool_errors += sum(
                1 for b in content if b.get("type") == "tool_result" and b.get("is_error")
            )
        elif kind == "result":
            run.dollars = float(event.get("total_cost_usd") or 0.0)
            run.stop_reason = _stop_reason(str(event.get("subtype", "")))
            if event.get("is_error") and event.get("result"):
                run.errors.append(str(event["result"]))
    run.model_calls = len(messages)
    run.tool_calls = len(calls)
    return run


def _stop_reason(subtype: str) -> str:
    if subtype == "success":
        return "end_turn"
    if "budget" in subtype:
        return "over_budget"  # fails the attempt, as Zwans going over max_cost does
    return subtype.removeprefix("error_") or "error"

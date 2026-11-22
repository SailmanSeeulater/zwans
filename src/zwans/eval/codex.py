"""A second baseline: the same tasks through OpenAI's Codex CLI (`codex exec`).

With an OpenAI model in Zwans ("openai/<model>"), this compares two harnesses on the same
model, so a difference in the results is the harness's, not the model's.

Like the Claude Code baseline, every attempt starts the same way: CODEX_HOME points at an
empty folder in the attempt's scratch space, so the user's ~/.codex config, MCP servers and
saved login stay out of it, and the API key comes from CODEX_API_KEY, billed per token.
Approvals and Codex's own sandbox are turned off, because nobody is there to answer and the
attempt already works in a throwaway copy of the task; that matches how Claude Code runs.

Codex reports tokens but not dollars, so the cost is worked out from the model's Price, and
the adapter won't start without one: the run's budget guard would be blind otherwise. Codex
has no budget limit of its own either, so an attempt is charged when it ends, and one that
went over the task's max_cost fails then, as Claude Code's do.

The event format is `codex exec --json` as of Codex 0.171: thread/turn/item events, with
token usage on turn.completed. It isn't a stable interface, so anything unknown is skipped.
"""

import asyncio
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from zwans.config import Config
from zwans.eval.guard import answer_markers, peeks_at
from zwans.eval.runner import AgentRun, Budget
from zwans.eval.task import Task
from zwans.executor.local import kill_tree, own_process_group
from zwans.pricing import Price

STDERR_CHARS = 2_000  # of Codex's own error output, kept when it fails to finish

# Zwans's effort levels in Codex's terms (model_reasoning_effort).
EFFORTS = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}

# Item types that are the agent using a tool, as opposed to talking or thinking.
TOOL_ITEMS = {"command_execution", "file_change", "mcp_tool_call", "web_search"}
OUTPUT_KEYS = {"aggregated_output", "output", "result", "exit_code", "status"}  # not the request


class CodexAgent:
    def __init__(
        self,
        config: Config,
        api_key: str,
        price: Price | None,
        command: Sequence[str] = ("codex",),
        version: str = "",
    ) -> None:
        provider, _, model = config.model.partition("/")
        if config.model.startswith("claude") or (model and provider != "openai"):
            raise ValueError(
                f"Codex runs OpenAI models, not {config.model}: choose one as openai/<model>."
            )
        if price is None:
            raise ValueError(
                f"There's no price for {config.model}, and Codex doesn't report dollars, so the "
                "run's budget couldn't be kept. Set it under [providers.openai] prices in the "
                "config."
            )
        self.config = config
        self.model = model or provider  # "openai/gpt-x" or just "gpt-x"
        self.api_key = api_key
        self.price = price
        self.command = list(command)
        self.name = f"codex {version}".strip()

    def argv(self, task: Task) -> list[str]:
        return [
            *self.command,
            "exec",
            "--json",
            "--model",
            self.model,
            "-c",
            f'model_reasoning_effort="{EFFORTS.get(self.config.effort, "medium")}"',
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",  # task copies aren't git repos
            "--ephemeral",  # keep no session files
            task.prompt,
        ]

    async def attempt(
        self, task: Task, workspace: Path, scratch: Path, budget: Budget, transcript: Path
    ) -> AgentRun:
        home = scratch / "codex-home"
        home.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CODEX_HOME": str(home), "CODEX_API_KEY": self.api_key}
        env.pop("OPENAI_API_KEY", None)  # one key, the one given, whatever the shell has
        transcript.parent.mkdir(parents=True, exist_ok=True)
        stderr_path = scratch / "codex-stderr.txt"
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
        run = parse_stream(lines, self.price, answer_markers(task))
        budget.spent += run.dollars  # charged at the end: Codex doesn't report as it goes
        if timed_out:
            run.stop_reason = "timeout"
        elif run.stop_reason == "end_turn" and run.dollars > task.max_cost:
            run.stop_reason = "over_budget"  # fails the attempt, as for Zwans and Claude Code
        elif run.stop_reason == "error" and not run.errors:
            output = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            run.errors.append(output[-STDERR_CHARS:] or f"codex exited {process.returncode}")
        return run


def parse_stream(lines: Iterable[str], price: Price, markers: Sequence[str] = ()) -> AgentRun:
    """Read `codex exec --json` output into the numbers the report needs.

    Codex doesn't say how many model calls it made, so model_calls stays 0. A tool call is a
    finished command, file change, MCP call or web search; it's an error when its status is
    "failed" or "declined". Usage follows OpenAI's convention: input_tokens includes the
    cached ones, and output_tokens includes the reasoning. A call that names one of `markers`
    (eval/guard.py) is a peek at the answer; only what it was asked to do is read, not its
    output.
    """
    run = AgentRun(stop_reason="error")  # until a turn.completed says otherwise
    calls: set[str] = set()
    errors: set[str] = set()
    fresh = cached = written = output = 0
    for line in lines:
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item") or {}
            item_id = str(item.get("id", len(calls)))
            if item.get("type") in TOOL_ITEMS:
                calls.add(item_id)
                asked = {k: v for k, v in item.items() if k not in OUTPUT_KEYS}
                peek = peeks_at({"tool": item.get("type"), **asked}, markers)
                if peek is not None:
                    run.peeks.append(peek)
                if item.get("status") in ("failed", "declined"):
                    errors.add(item_id)
            elif item.get("type") == "error" and item.get("message"):
                run.errors.append(str(item["message"]))
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            cached_now = int(usage.get("cached_input_tokens") or 0)
            written_now = int(usage.get("cache_write_input_tokens") or 0)
            fresh += max(int(usage.get("input_tokens") or 0) - cached_now - written_now, 0)
            cached += cached_now
            written += written_now
            output += int(usage.get("output_tokens") or 0)
            run.stop_reason = "end_turn"
        elif kind == "turn.failed":
            run.stop_reason = "error"
            message = (event.get("error") or {}).get("message")
            if message:
                run.errors.append(str(message))
        elif kind == "error" and event.get("message"):
            run.errors.append(str(event["message"]))
    run.tool_calls = len(calls)
    run.tool_errors = len(errors)
    run.input_tokens, run.cache_read_tokens = fresh, cached
    run.cache_write_tokens, run.output_tokens = written, output
    run.dollars = (
        fresh * price.input
        + cached * price.cache_read
        + written * price.cache_write
        + output * price.output
    ) / 1_000_000
    return run

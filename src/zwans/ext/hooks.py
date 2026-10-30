"""Hooks: your own commands that run around tool calls and when the model finishes a turn.

They're declared in the policy files (see policy/rules.py), because a pre_tool hook is a rule
written as a program:

    [[hooks]]
    event = "pre_tool"                 # pre_tool, post_tool or stop
    tools = "Bash"                     # which tools, as a glob; all of them when left out
    command = "python3 ~/.zwans/hooks/no_push.py"
    timeout = 30                       # seconds

A hook runs in the workspace folder and reads a JSON object on stdin describing the call or
the turn. Its exit code decides what happens next:

- pre_tool: non-zero blocks the call, and the model is told why.
- post_tool: non-zero adds the hook's message to the call's result, such as a linter's output.
- stop: non-zero keeps the turn going, with the hook's message as the next thing the model
  reads, such as "the tests still fail".

The message is what the hook printed to stderr, or to stdout when stderr is empty. A hook that
can't start, crashes or times out counts as non-zero, so a broken pre_tool hook blocks calls
rather than letting them through.
"""

import asyncio
import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zwans.executor.local import command_env, kill_tree, own_process_group

type HookEvent = Literal["pre_tool", "post_tool", "stop"]

MAX_MESSAGE_CHARS = 4000  # the model reads the message, so keep a runaway hook's output short


class HookSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: HookEvent
    tools: str = "*"  # ignored for stop hooks
    command: str
    timeout: float = Field(default=60, gt=0)

    def applies_to(self, event: HookEvent, tool: str | None) -> bool:
        return self.event == event and (tool is None or fnmatchcase(tool, self.tools))


@dataclass(frozen=True)
class HookFailure:
    """A hook that exited non-zero, and what it said."""

    spec: HookSpec
    message: str


class Hooks:
    def __init__(self, specs: list[HookSpec], workspace: Path) -> None:
        self.specs = list(specs)
        self.workspace = workspace

    def without(self, event: HookEvent) -> "Hooks":
        return Hooks([spec for spec in self.specs if spec.event != event], self.workspace)

    async def pre_tool(self, tool: str, args: dict[str, Any]) -> HookFailure | None:
        """The first hook that blocks the call, if any. Later hooks don't run."""
        payload = {"tool": tool, "args": args}
        for spec in self._matching("pre_tool", tool):
            failure = await self._run(spec, payload)
            if failure is not None:
                return failure
        return None

    async def post_tool(
        self, tool: str, args: dict[str, Any], output: str, is_error: bool
    ) -> list[HookFailure]:
        payload = {"tool": tool, "args": args, "output": output, "is_error": is_error}
        return await self._run_all(self._matching("post_tool", tool), payload)

    async def stop(self, stop_reason: str, message: str) -> list[HookFailure]:
        payload = {"stop_reason": stop_reason, "message": message}
        return await self._run_all(self._matching("stop", None), payload)

    def _matching(self, event: HookEvent, tool: str | None) -> list[HookSpec]:
        return [spec for spec in self.specs if spec.applies_to(event, tool)]

    async def _run_all(self, specs: list[HookSpec], payload: dict[str, Any]) -> list[HookFailure]:
        failures = [await self._run(spec, payload) for spec in specs]
        return [failure for failure in failures if failure is not None]

    async def _run(self, spec: HookSpec, payload: dict[str, Any]) -> HookFailure | None:
        data = json.dumps({"event": spec.event, "workspace": str(self.workspace), **payload})
        try:
            process = await asyncio.create_subprocess_shell(
                spec.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                env=command_env(),
                **own_process_group(),
            )
        except OSError as exc:
            return HookFailure(spec, f"The hook `{spec.command}` couldn't start: {exc}")
        try:
            out, err = await asyncio.wait_for(
                process.communicate(data.encode("utf-8")), spec.timeout
            )
        except TimeoutError:
            await kill_tree(process)
            message = f"The hook `{spec.command}` timed out after {spec.timeout:g}s."
            return HookFailure(spec, message)
        except BaseException:  # Ctrl+C: don't leave the hook running
            await kill_tree(process)
            raise
        if process.returncode == 0:
            return None
        message = (err.strip() or out.strip()).decode("utf-8", errors="replace")
        if len(message) > MAX_MESSAGE_CHARS:
            message = message[:MAX_MESSAGE_CHARS] + "\n(cut short)"
        return HookFailure(
            spec, message or f"The hook `{spec.command}` exited with code {process.returncode}."
        )

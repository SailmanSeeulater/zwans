"""Notices an attempt reaching for its task's answer.

The suites live in a public repository, solutions and hidden tests included, and on the
local executor a command can read anything on this machine. An agent that finds them can
pass without doing the work. A tool call that names the task's suite folder on this machine,
or the task's path in the repository (as a GitHub URL would), is looking at the answer: the
attempt is stopped and fails, whatever the check would have said.

This is a tripwire, not a wall. Evals also run without the web tools (EvalConfig.apply), and
the Docker, jail and Seatbelt executors give commands no open network. A command that finds
the folder without naming it (a search from `/`, say) gets past the tripwire, which is why
it's only part of the defence.
"""

import json
from collections.abc import Callable, Iterable
from typing import Any

from zwans.eval.task import Task
from zwans.events import Event, ToolCallRequested, unwrap

MAX_SHOWN = 500  # characters of a call kept for the report


def answer_markers(task: Task) -> list[str]:
    """Text that only a call reaching for the answer would contain: where the task's suite
    is on this machine, as given and with links resolved, and `<suite>/<task>`, which every
    path or URL to its solution or hidden tests contains."""
    suite = task.folder.parent
    found = [str(suite), str(suite.resolve()), f"{suite.name}/{task.folder.name}"]
    return list(dict.fromkeys(found))


def peeks_at(call: dict[str, Any], markers: Iterable[str]) -> str | None:
    """The call, as JSON for the report, when it names one of `markers`; otherwise None."""
    text = json.dumps(call, ensure_ascii=False)
    if any(marker in text for marker in markers):
        return text[:MAX_SHOWN]
    return None


class AnswerGuard:
    """Listens to a Zwans attempt's tool calls, its subagents' included, and calls `stop`
    at the first one that reaches for the answer."""

    def __init__(self, markers: list[str], stop: Callable[[], None]) -> None:
        self.markers = markers
        self.stop = stop
        self.peeks: list[str] = []

    def on_event(self, event: Event) -> None:
        event = unwrap(event)
        if not isinstance(event, ToolCallRequested):
            return
        peek = peeks_at({"tool": event.name, **event.args}, self.markers)
        if peek is not None:
            self.peeks.append(peek)
            self.stop()

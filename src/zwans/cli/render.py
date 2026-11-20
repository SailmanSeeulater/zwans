"""Shows the event stream in the terminal."""

import asyncio
import re
import sys
import time
from typing import Any, ClassVar

import click
import typer
from rich.console import Console, JustifyMethod
from rich.markdown import Heading, Markdown, MarkdownElement
from rich.theme import Theme

from zwans.cli.diffs import show_diff
from zwans.cli.terminal_text import printable, printable_keeping_colours
from zwans.events import (
    ContextCompacted,
    Error,
    Event,
    HookReported,
    PermissionRequested,
    PermissionResolved,
    SubagentEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
    TurnStarted,
)

# The argument most worth showing for each tool, so a call fits on one line. A Grep or Glob
# shows its pattern rather than the folder it searches.
KEY_ARGS = ("command", "pattern", "path", "query", "url", "description", "name", "job_id", "ticket")
TODO_MARKS = {"completed": "✓", "in_progress": "▸", "pending": "○"}
SHELL_TOOLS = frozenset({"Bash", "BashOutput"})
QUIET_OUTPUT = frozenset({"(no output)", "(no new output)"})  # said by the exit code alone
TAIL_LINES = 3  # of a command's output, which is where test runners print their totals
LINE_LIMIT = 100
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
CLEAR_LINE = "\r\x1b[K"

# Markdown is shown a block at a time. A blank line ends a block, unless what follows carries
# it on: an indented line or a list item, which keeps a list in one piece.
FENCE = re.compile(r"^ {0,3}(```|~~~)")
CARRIES_ON = re.compile(r"^(\s|[-*+]\s|\d+[.)]\s)")
TRAILING_SPACE = re.compile(r" +((?:\x1b\[[0-9;]*m)*)$")


class Renderer:
    def __init__(self, spinner: bool = False, markdown: bool | None = None) -> None:
        self._style: str | None = None  # what the current line is showing
        self._at_line_start = True
        self._todo_calls: set[str] = set()  # TodoWrite calls, whose list says it all
        self._calls: dict[str, tuple[str, str]] = {}  # call id: the tool's name, its line
        self._last_call: str | None = None  # the call whose line was printed last
        # The model's text as markdown, when writing to a terminal.
        self._markdown = sys.stdout.isatty() if markdown is None else markdown
        self._console = Console(highlight=False, theme=Theme({"markdown.code": "bold cyan"}))
        self._pending = ""  # text not yet shown, waiting for its block to end
        self._blocks_shown = False  # in this stretch of text
        # A status line while the turn runs, so a slow model or command doesn't look hung.
        self._spinner = spinner and sys.stdout.isatty()
        self._busy = False  # a turn is running
        self._asking = False  # the user is answering a permission question
        self._running: dict[str, str] = {}  # calls waiting for their results: id to name
        self._activity = ""
        self._since = time.monotonic()
        self._status_task: asyncio.Task[None] | None = None
        self._status_shown = False

    def on_event(self, event: Event) -> None:
        self._hide_status()
        self._show(event)
        self._track(event)

    def _show(self, event: Event) -> None:
        match event:
            case TextDelta(text=text):
                self._stream(text, "text")
            case ThinkingDelta(text=text):
                self._stream(text, "note")
            case ToolCallRequested(name="TodoWrite", call_id=call_id, args=args):
                self._todo_calls.add(call_id)
                self._todos(args)
            case ToolCallRequested(name=name, call_id=call_id, args=args):
                label = f"{name} {_summarize(name, args)}".rstrip()
                self._calls[call_id] = (name, label)
                self._line(f"> {label}", fg="cyan")
                self._last_call = call_id
            case ToolResult(call_id=call_id, is_error=False) if call_id in self._todo_calls:
                pass
            case ToolResult():
                self._result(event)
            case PermissionRequested():
                self._finish_line()  # the question comes next, on a line of its own
            case TurnEnded(stop_reason="end_turn" | "error"):  # an error has said why already
                self._finish_line()
            case TurnEnded(stop_reason=reason, detail=detail):
                if reason == "interrupted" and self._at_line_start and sys.stdout.isatty():
                    # Wipe the ^C the terminal echoed, which the renderer didn't write.
                    typer.echo(CLEAR_LINE, nl=False)
                self._line(f"[stopped: {reason}{f', {detail}' if detail else ''}]", fg="yellow")
            case SubagentEvent(task=task):
                self._subagent(task, event.inner())
            case HookReported(event="pre_tool"):
                pass  # the blocked call's result says the same
            case HookReported(event=hook_event, message=message):
                self._line(f"  {hook_event} hook: {_first_line(message)}", fg="yellow")
            case Error(message=message):
                self._line(f"Error: {message}", fg="red")
            case ContextCompacted(tokens_before=before, tokens_after=after):
                note = f"[Summarized older messages: about {before:,} -> {after:,} tokens]"
                self._line(note, fg="magenta")

    def _result(self, result: ToolResult) -> None:
        name, label = self._calls.get(result.call_id, ("", ""))
        # Results of calls run together come after all their call lines, so each says whose
        # it is unless it sits right under its own call.
        prefix = f"{_clip(label, 60)}: " if label and result.call_id != self._last_call else ""
        if result.is_error:
            self._line(f"  ! {prefix}{_error_summary(result.content)}", fg="red")
            return
        rows = _result_rows(name, result.content)
        for index, (text, style) in enumerate(rows):
            self._line(f"  {prefix if index == 0 else ''}{text}", **style)
        if result.diff:
            show_diff(result.diff)

    def _todos(self, args: dict[str, Any]) -> None:
        self._line("> To-do list", fg="cyan")
        todos = args.get("todos")
        for todo in todos if isinstance(todos, list) else []:
            status = str(todo.get("status", "pending"))
            mark = TODO_MARKS.get(status, "○")
            text = f"  {mark} {_first_line(str(todo.get('content', '')))}"
            typer.secho(printable(text), dim=status == "completed", bold=status == "in_progress")

    def _subagent(self, task: str, event: Event) -> None:
        """A subagent's calls, one line each and indented; its text stays out of the way."""
        match event:
            case SubagentEvent(task=inner_task):
                self._subagent(f"{task} > {inner_task}", event.inner())
            case ToolCallRequested(name=name, args=args):
                line = f"  [{task}] {name} {_summarize(name, args)}".rstrip()
                self._line(line, fg="cyan", dim=True)
            case ToolResult(content=content, is_error=True):
                self._line(f"  [{task}] ! {_error_summary(content)}", fg="red", dim=True)
            case HookReported(event="pre_tool"):
                pass
            case HookReported(event=hook_event, message=message):
                self._line(f"  [{task}] {hook_event} hook: {_first_line(message)}", fg="yellow")
            case Error(message=message):
                self._line(f"  [{task}] Error: {message}", fg="red")

    def _stream(self, text: str, style: str) -> None:
        if style != self._style:
            self._finish_line()
            self._style = style
        text = printable(text)  # the model's text may carry escape codes from what it read
        if style == "text" and self._markdown:
            self._pending += text
            self._flush_markdown(final=False)
            return
        typer.secho(text, nl=False, dim=style == "note")
        self._at_line_start = text.endswith("\n")

    def _line(self, text: str, **style: Any) -> None:
        self._finish_line()
        typer.secho(printable(text), **style)
        self._style = None
        self._last_call = None

    def _finish_line(self) -> None:
        self._flush_markdown(final=True)
        self._blocks_shown = False
        if not self._at_line_start:
            typer.echo()
            self._at_line_start = True

    def _flush_markdown(self, final: bool) -> None:
        """Show the text's finished blocks, or with `final`, all of it."""
        if final:
            chunk, self._pending = self._pending, ""
        else:
            cut = _block_end(self._pending)
            if cut is None:
                return
            chunk, self._pending = self._pending[:cut], self._pending[cut:]
        if not chunk.strip():
            return
        if self._blocks_shown:
            typer.echo()
        markdown = _Markdown(
            chunk.strip("\n"), code_theme="ansi_dark", justify="default", hyperlinks=False
        )
        with self._console.capture() as captured:
            self._console.print(markdown)
        # Rich pads lines to the terminal's width, which garbles them when it's narrowed, and
        # pads tables and code with blank lines, where one between blocks is enough.
        lines: list[str] = []
        # Markdown decodes entities, so "&#x202E;" only becomes a bidi override in rich's output.
        for line in printable_keeping_colours(captured.get()).split("\n"):
            line = TRAILING_SPACE.sub(r"\1", line)
            blank = not click.unstyle(line).strip()
            if not blank or (lines and lines[-1]):
                lines.append("" if blank else line)
        typer.echo("\n".join(lines).rstrip("\n"))
        self._blocks_shown = True

    # The status line. It's drawn only on an empty line and wiped before anything else is
    # written, so it never mixes with the output or with a permission question.

    def _track(self, event: Event) -> None:
        match event:
            case TurnStarted():
                self._busy = True
            case TurnEnded() | Error():
                self._busy = False
                self._running.clear()
            case PermissionRequested():
                self._asking = True
            case PermissionResolved():
                self._asking = False
            case ToolCallRequested(call_id=call_id, name=name):
                self._running[call_id] = name
            case ToolResult(call_id=call_id):
                self._running.pop(call_id, None)
        if not self._busy and self._status_task is not None:
            self._status_task.cancel()
            self._status_task = None
        elif self._spinner and self._busy and self._status_task is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # not inside an event loop, so nothing can animate it
            self._status_task = loop.create_task(self._animate(asyncio.current_task()))

    async def _animate(self, turn: asyncio.Task[Any] | None) -> None:
        """Redraw the status line until the turn ends. If the task running the turn stops
        without saying so, the line goes too, rather than drawing over the next prompt."""
        frame = 0
        try:
            while self._busy and (turn is None or not turn.done()):
                if not self._asking and self._at_line_start:
                    self._draw_status(SPINNER[frame % len(SPINNER)])
                    frame += 1
                await asyncio.sleep(0.1)
        finally:
            self._hide_status()
            if self._status_task is asyncio.current_task():
                self._status_task = None

    def _draw_status(self, mark: str) -> None:
        activity = self._current_activity()
        if activity != self._activity:
            self._activity, self._since = activity, time.monotonic()
        seconds = int(time.monotonic() - self._since)
        line = f"{mark} {printable(activity)}… {seconds}s"
        typer.secho(f"{CLEAR_LINE}{line}", nl=False, dim=True)
        self._status_shown = True

    def _current_activity(self) -> str:
        if self._running:
            return f"Running {next(iter(self._running.values()))}"
        return "Writing" if self._pending else "Thinking"

    def _hide_status(self) -> None:
        if self._status_shown:
            typer.echo(CLEAR_LINE, nl=False)
            self._status_shown = False


class _LeftHeading(Heading):
    """Rich centres top-level headings; in a chat they read better on the left like the rest.
    An older rich without LEVEL_ALIGN keeps its own layout, rather than failing on import."""

    LEVEL_ALIGN: ClassVar[dict[str, JustifyMethod]] = {
        **getattr(Heading, "LEVEL_ALIGN", {}),
        "h1": "left",
    }


class _Markdown(Markdown):
    elements: ClassVar[dict[str, type[MarkdownElement]]] = {
        **Markdown.elements,
        "heading_open": _LeftHeading,
    }


def _block_end(text: str) -> int | None:
    """Where the last finished markdown block in `text` ends, or None if none has yet. A
    block ends at a blank line outside a code fence once the next line has begun and doesn't
    carry the block on."""
    end = None
    in_fence = False
    offset = 0
    lines = text.split("\n")  # the last one may still be arriving
    for index, line in enumerate(lines[:-1]):
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and not line.strip():
            following = lines[index + 1]
            complete = index + 1 < len(lines) - 1
            judged = complete or len(following) >= 3  # enough to tell "1. x" from "1x"
            if following.strip() and judged and not CARRIES_ON.match(following):
                end = offset + len(line) + 1
        offset += len(line) + 1
    return end


def _summarize(name: str, args: dict[str, Any]) -> str:
    key = next((k for k in KEY_ARGS if k in args), None)
    if key is None:
        return ""
    lines = str(args[key]).strip().splitlines() or [""]
    text = _clip_start(lines[0]) if key == "path" else _clip(lines[0])
    if len(lines) > 1:
        text += f" (+{_count(len(lines) - 1, 'line')})"
    if key == "pattern" and isinstance(args.get("path"), str):
        text += f" in {_clip_start(args['path'])}"
    notes = []
    if args.get("run_in_background") is True:
        notes.append("in the background")
    if name == "Bash" and isinstance(args.get("timeout"), int):
        notes.append(f"timeout {args['timeout']}s")
    offset = args.get("offset")
    if name == "Read" and isinstance(offset, int) and offset > 1:
        notes.append(f"from line {offset}")
    return f"{text} ({', '.join(notes)})" if notes else text


def _result_rows(name: str, content: str) -> list[tuple[str, dict[str, Any]]]:
    """A successful result in a line or a few: the line itself, a count, the end of a
    command's output with its exit code, or what a web search or fetch found."""
    dim: dict[str, Any] = {"dim": True}
    lines = content.strip().splitlines()
    if name in ("web_search", "web_fetch") and len(lines) > 1:
        return [(_web_summary(name, lines), dim)]
    if len(lines) <= 1:
        return [(_first_line(content), dim)]
    if name in SHELL_TOOLS or lines[-1].startswith("(exit code"):
        *output, status = lines
        output = [line for line in output if line.strip() and line not in QUIET_OUTPUT]
        shown = output[-TAIL_LINES:]
        rows = []
        if len(output) > len(shown):
            rows.append((f"({_count(len(output) - len(shown), 'earlier line')})", dim))
        rows += [(_clip(line), dim) for line in shown]
        failed = status.startswith("(exit code") and status != "(exit code 0)"
        rows.append((status, {"fg": "yellow"} if failed else dim))
        return rows
    return [(f"({len(lines)} lines)", dim)]


def _web_summary(name: str, lines: list[str]) -> str:
    """zwans.web describes a fetch as its title, address and size, and a search as a title
    and an address per result. On one line: the fetch's three parts, or the search's titles."""
    if name == "web_fetch":
        return _clip(" · ".join(line.strip() for line in lines))
    titles = [line for line in lines if not line.startswith(" ")]
    return _clip(f"{_count(len(titles), 'result')}: {', '.join(titles)}")


def _error_summary(content: str) -> str:
    """An error's first line, unless it ends by saying why a command stopped: then that."""
    lines = content.strip().splitlines()
    if lines and lines[-1].startswith("Stopped after"):
        return _clip(lines[-1])
    return _first_line(content)


def _first_line(text: str, limit: int = LINE_LIMIT) -> str:
    return _clip(text.strip().splitlines()[0] if text.strip() else "", limit)


def _clip(line: str, limit: int = LINE_LIMIT) -> str:
    return line if len(line) <= limit else line[: limit - 3] + "..."


def _clip_start(path: str, limit: int = LINE_LIMIT) -> str:
    """A path cut from the start, so its file name stays."""
    return path if len(path) <= limit else "..." + path[-(limit - 3) :]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"

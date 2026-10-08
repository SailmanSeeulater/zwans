"""Shows the event stream in the terminal."""

from typing import Any

import typer

from zwans.events import (
    Error,
    Event,
    TextDelta,
    ThinkingDelta,
    ToolCallRequested,
    ToolResult,
    TurnEnded,
)

# The argument most worth showing for each tool, so a call fits on one line.
KEY_ARGS = ("path", "command", "pattern")


class Renderer:
    def __init__(self) -> None:
        self._style: str | None = None  # what the current line is showing
        self._at_line_start = True

    def on_event(self, event: Event) -> None:
        match event:
            case TextDelta(text=text):
                self._stream(text, "text")
            case ThinkingDelta(text=text):
                self._stream(text, "note")
            case ToolCallRequested(name=name, args=args):
                self._line(f"> {name} {_summarize(args)}".rstrip(), fg="cyan")
            case ToolResult(content=content, is_error=True):
                self._line(f"  ! {_first_line(content)}", fg="red")
            case ToolResult(content=content):
                self._line(f"  {_result_summary(content)}", dim=True)
            case TurnEnded(stop_reason="end_turn"):
                self._finish_line()
            case TurnEnded(stop_reason=reason, detail=detail):
                self._line(f"[stopped: {reason}{f', {detail}' if detail else ''}]", fg="yellow")
            case Error(message=message):
                self._line(f"Error: {message}", fg="red")

    def _stream(self, text: str, style: str) -> None:
        if style != self._style:
            self._finish_line()
            self._style = style
        typer.secho(text, nl=False, dim=style == "note")
        self._at_line_start = text.endswith("\n")

    def _line(self, text: str, **style: Any) -> None:
        self._finish_line()
        typer.secho(text, **style)
        self._style = None

    def _finish_line(self) -> None:
        if not self._at_line_start:
            typer.echo()
            self._at_line_start = True


def _summarize(args: dict[str, Any]) -> str:
    for key in KEY_ARGS:
        if key in args:
            return _first_line(str(args[key]))
    return ""


def _result_summary(content: str) -> str:
    """One line about a successful result: the line itself, a command's exit code, or a count."""
    lines = content.strip().splitlines()
    if len(lines) <= 1:
        return _first_line(content)
    if lines[-1].startswith("(exit code"):
        return lines[-1]
    return f"({len(lines)} lines)"


def _first_line(text: str, limit: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 3] + "..."

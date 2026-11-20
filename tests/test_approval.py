import asyncio
import builtins
import sys
import termios
from types import SimpleNamespace
from typing import Any

import pytest

from zwans.cli import approval
from zwans.policy.engine import Approval, PermissionRequest


def ask(tool: str, args: dict[str, Any], monkeypatch: pytest.MonkeyPatch, answer: str) -> Approval:
    monkeypatch.setattr(approval, "_prompt", lambda text: answer)
    request = PermissionRequest("c1", tool, args, f"{tool} changes files", (f"{tool}(x)",))
    return asyncio.run(approval.terminal_approver(request))


def test_an_edit_question_shows_the_change(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    args = {
        "path": "calc.py",
        "old_string": "def sub(a, b):\n    return a + b",
        "new_string": "def sub(a, b):\n    return a - b",
    }

    assert ask("Edit", args, monkeypatch, "y") == Approval.ONCE

    assert capsys.readouterr().out.splitlines() == [
        "  ? Edit changes files",
        "     def sub(a, b):",
        "    -    return a + b",
        "    +    return a - b",
    ]


def test_a_write_question_shows_the_new_contents(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "".join(f"print({n})\n" for n in range(50))

    assert ask("Write", {"path": "hi.py", "content": content}, monkeypatch, "") == Approval.NO

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "    New contents (50 lines):"
    assert lines[2] == "    +print(0)"
    assert lines[-1] == "    ... 10 more lines"


def test_a_multi_line_command_is_shown_in_full(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    command = "python - <<'EOF'\nopen('a.py', 'w').write('x')\nEOF"

    ask("Bash", {"command": command}, monkeypatch, "a")

    assert capsys.readouterr().out.splitlines()[1:] == [
        "    python - <<'EOF'",
        "    open('a.py', 'w').write('x')",
        "    EOF",
    ]


def test_a_short_command_is_not_repeated(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ask("Bash", {"command": "pytest -q"}, monkeypatch, "y")

    assert capsys.readouterr().out == "  ? Bash changes files\n"


def test_text_typed_during_the_turn_is_dropped_before_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[str] = []

    def read(text: str) -> str:
        steps.append("read")
        return "y"

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True, fileno=lambda: 0))
    monkeypatch.setattr(termios, "tcflush", lambda fd, queue: steps.append(f"flush {queue}"))
    monkeypatch.setattr(builtins, "input", read)

    assert approval._prompt("Allow it? ") == "y"

    assert steps == [f"flush {termios.TCIFLUSH}", "read"]

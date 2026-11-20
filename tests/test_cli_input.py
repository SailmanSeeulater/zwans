import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from zwans.checkpoints import Change
from zwans.cli.commands import COMMANDS, Commands, Quit, Reopen, _describe_undo, is_command
from zwans.cli.input import (
    MAX_FILE_CHARS,
    ChatCompleter,
    Composer,
    echoing,
    expand_mentions,
    toolbar_line,
)
from zwans.config import Config
from zwans.messages import TextBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.runtime import OpenedSession, open_session

# A 2x3 PNG's signature and IHDR chunk: enough to be recognized and measured.
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x03"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n")
    (root / "README.md").write_text("# Project\n")
    (root / ".env").write_text("SECRET=1\n")
    (root / "node_modules").mkdir()
    return root


def test_mentioned_files_and_folders_go_along(workspace: Path) -> None:
    mentions = expand_mentions("Fix @src/main.py, see @src and @README.md.", workspace)

    assert mentions.files == ["src/main.py", "src", "README.md"]
    assert mentions.text.startswith("Fix @src/main.py, see @src and @README.md.\n\n")
    assert "<file path=\"src/main.py\">\nprint('hi')\n\n</file>" in mentions.text
    assert '<folder path="src">\nmain.py\n</folder>' in mentions.text


def test_words_that_arent_workspace_paths_are_left_alone(workspace: Path, tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_text("no")

    mentions = expand_mentions("Ask @alice about @../outside.txt and email a@b.c", workspace)

    assert mentions.files == [] and mentions.problems == []
    assert mentions.text == "Ask @alice about @../outside.txt and email a@b.c"


def test_a_huge_or_binary_file_is_named_but_not_sent(workspace: Path) -> None:
    (workspace / "big.txt").write_text("x" * (MAX_FILE_CHARS + 1))
    (workspace / "data.bin").write_bytes(b"\x00\xff\xfe\x01")

    mentions = expand_mentions("Look at @big.txt and @data.bin", workspace)

    assert mentions.files == [] and mentions.images == []
    assert "too long to send" in mentions.problems[0]
    assert "isn't a text file" in mentions.problems[1]


def test_a_mentioned_image_is_sent_as_an_image(workspace: Path) -> None:
    png = PNG_HEADER + b"\x00" * 16
    (workspace / "shot.png").write_bytes(png)

    mentions = expand_mentions("What's wrong in @shot.png?", workspace)

    assert mentions.files == ["shot.png"] and mentions.problems == []
    assert len(mentions.images) == 1
    assert mentions.images[0].source.media_type == "image/png"
    assert base64.b64decode(mentions.images[0].source.data) == png
    assert mentions.text == "What's wrong in @shot.png?"  # the image goes as its own block


def complete(text: str, workspace: Path) -> list[str]:
    completer = ChatCompleter(COMMANDS, workspace)
    found = completer.get_completions(Document(text), CompleteEvent(completion_requested=True))
    return [c.text for c in found]


def test_commands_and_paths_complete(workspace: Path) -> None:
    assert complete("/c", workspace) == ["/clear", "/compact", "/cost"]
    assert complete("fix @", workspace) == ["@README.md", "@src/"]  # no hidden or vendored
    assert complete("fix @src/m", workspace) == ["@src/main.py"]
    assert complete("fix @.e", workspace) == ["@.env"]
    assert complete("fix @../", workspace) == []
    assert complete("/model x", workspace) == []
    assert complete("/model claude-so", workspace) == ["claude-sonnet-5-5"]
    assert complete("/etc/hosts @src/m", workspace) == ["@src/main.py"]


def read_typed(keys: str, workspace: Path) -> str:
    async def read() -> str:
        with create_pipe_input() as pipe:
            pipe.send_text(keys)
            composer = Composer(COMMANDS, workspace, None, input=pipe, output=DummyOutput())
            return await composer.read()

    return asyncio.run(read())


def test_enter_sends_and_escape_enter_adds_a_line(workspace: Path) -> None:
    assert read_typed("first line\x1b\rsecond\r", workspace) == "first line\nsecond"
    assert read_typed("one\ntwo\r", workspace) == "one\ntwo"  # Ctrl+J


def test_lines_typed_ahead_are_sent_one_at_a_time(workspace: Path) -> None:
    async def read_twice() -> list[str]:
        with create_pipe_input() as pipe:
            pipe.send_text("/cost\rsay banana\r")  # typed while a turn ran
            composer = Composer(COMMANDS, workspace, None, input=pipe, output=DummyOutput())
            return [await composer.read(), await composer.read()]

    assert asyncio.run(read_twice()) == ["/cost", "say banana"]


@pytest.mark.skipif(sys.platform == "win32", reason="no termios on Windows")
def test_typing_during_a_turn_waits_unechoed_and_a_question_takes_only_later_typing(
    workspace: Path,
) -> None:
    import termios

    leader, follower = os.openpty()
    os.set_blocking(leader, False)

    async def go() -> tuple[list[list[Any]], str, list[str], bytes]:
        loop = asyncio.get_running_loop()
        with (
            create_pipe_input() as pipe,
            os.fdopen(follower, "r") as terminal,
            os.fdopen(os.dup(follower), "w") as screen,
        ):
            composer = Composer(COMMANDS, workspace, None, input=pipe, output=DummyOutput())
            before = termios.tcgetattr(follower)
            with composer.typing_ahead(loop, terminal, screen):
                during = termios.tcgetattr(follower)
                os.write(leader, b"/cost\r\x1b[200~two\rlines\x1b[201~\r")  # a line and a paste
                await asyncio.sleep(0.1)
                os.write(leader, b"y\r")  # typed just before an approval question
                await asyncio.sleep(0.1)
                with echoing(terminal, screen):
                    asked = termios.tcgetattr(follower)
                    os.write(leader, b"n\r")
                    answer = terminal.readline()
                assert termios.tcgetattr(follower) == during
            after = termios.tcgetattr(follower)
            with pytest.raises(KeyboardInterrupt), composer.typing_ahead(loop, terminal, screen):
                os.write(leader, b"dropped\r")
                await asyncio.sleep(0.1)
                raise KeyboardInterrupt  # Ctrl+C stops the turn
            pipe.send_text("kept\r")
            sent = [await composer.read() for _ in range(4)]
            shown = os.read(leader, 1000)
        os.close(leader)
        return [before, during, asked, after], answer, sent, shown

    (before, during, asked, after), answer, sent, shown = asyncio.run(go())

    assert not during[3] & (termios.ECHO | termios.ICANON) and not during[0] & termios.ICRNL
    assert during[6][termios.VMIN] == 1
    assert asked[3] & termios.ECHO and asked[3] & termios.ICANON and asked[0] & termios.ICRNL
    # macOS marks pending input to retype whenever line editing comes back on (PENDIN).
    after[3] &= ~getattr(termios, "PENDIN", 0)
    assert after == before
    assert answer == "n\n"  # the "y" typed before the question didn't answer it
    assert sent == ["/cost", "two\nlines", "y", "kept"]
    # Only the answer was echoed; bracketed paste was on while typing was hidden.
    on, off = b"\x1b[?2004h", b"\x1b[?2004l"
    assert shown == on + off + b"n\r\n" + on + off + on + off


def test_ctrl_c_clears_the_line_and_quits_on_an_empty_one(workspace: Path) -> None:
    assert read_typed("typo\x03kept\r", workspace) == "kept"
    with pytest.raises(KeyboardInterrupt):
        read_typed("\x03", workspace)


def test_a_command_is_a_slash_and_a_name() -> None:
    assert is_command("/model claude-sonnet-5-5") and is_command("/help")
    assert not is_command("/etc/hosts has the wrong entry")
    assert not is_command("/") and not is_command("why does it say /help?")


def opened_session(tmp_path: Path, workspace: Path, replies: list[str]) -> OpenedSession:
    script = [
        ModelResponse(content=[TextBlock(text=text)], stop_reason="end_turn", model="m")
        for text in replies
    ]
    config = Config(home=tmp_path / "home", keep_messages=1)
    return open_session(
        config,
        {},
        workspace=workspace,
        mode="auto",
        make_provider=lambda config, model: FakeProvider(script),
    )


def test_compact_model_and_cost_commands(
    tmp_path: Path, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened = opened_session(tmp_path, workspace, ["One.", "Two.", "Summary of it all."])
    commands = Commands(opened)

    async def go() -> None:
        assert await commands.run("/compact") is None  # nothing to summarize yet
        await opened.session.send("First")
        await opened.session.send("Second")
        await commands.run("/compact")
        await commands.run("/model claude-sonnet-5-5")
        await commands.run("/model claude-nonexistent-9")
        await commands.run("/model")
        await commands.run("/cost")
        assert await commands.run("/nope") is None
        assert await commands.run("/rewind\n/undo") is None  # lines typed ahead, run together
        assert await commands.run("/exit") == Quit()

    asyncio.run(go())
    out = capsys.readouterr().out
    assert "Zwans doesn't know claude-nonexistent-9." in out  # and stays on the one before
    assert "  claude-sonnet-5-5  (current)" in out and "  claude-opus-5-5\n" in out
    assert "/rewind goes on a line of its own, so nothing was done." in out
    assert "Nothing to compact yet" in out
    assert out.count("Compacting: the model is summarizing") == 1  # said before the wait
    assert "Summary of it all." in opened.session.messages[0].content[0].model_dump_json()
    assert opened.model == "claude-sonnet-5-5"
    assert opened.store.get(opened.id).model == "claude-sonnet-5-5"  # resuming keeps it
    assert "Session: " in out and "Context: about" in out
    assert "There's no /nope" in out
    asyncio.run(opened.close())


def test_a_compact_that_fails_says_why_and_keeps_the_messages(
    tmp_path: Path, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened = opened_session(tmp_path, workspace, ["One.", "Two."])  # none left for a summary

    async def go() -> None:
        await opened.session.send("First")
        await opened.session.send("Second")
        await Commands(opened).run("/compact")

    asyncio.run(go())
    out = capsys.readouterr().out
    assert "Couldn't compact: FakeProvider ran out of scripted responses" in out
    assert len(opened.session.messages) == 4
    asyncio.run(opened.close())


def test_resume_lists_this_workspaces_sessions_and_picks_one(
    tmp_path: Path, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    earlier = opened_session(tmp_path, workspace, ["Done."])
    asyncio.run(earlier.session.send("An earlier task"))
    asyncio.run(earlier.close())
    opened = opened_session(tmp_path, workspace, [])
    commands = Commands(opened)

    assert asyncio.run(commands.run("/resume")) is None
    assert "1. " in capsys.readouterr().out
    assert asyncio.run(commands.run("/resume 1")) == Reopen(resume=earlier.id)
    assert asyncio.run(commands.run(f"/resume {earlier.id[:-2]}")) == Reopen(resume=earlier.id)
    assert asyncio.run(commands.run("/clear")) == Reopen(resume=None)
    capsys.readouterr()
    assert asyncio.run(commands.run("/resume nope")) is None  # stays in this session
    assert "No saved session starts with 'nope'." in capsys.readouterr().out
    assert asyncio.run(commands.run("/resume 2")) is None  # a number, not the start of an id
    assert "There's no session 2 in the list." in capsys.readouterr().out
    asyncio.run(opened.close())


def test_undoing_says_which_files_were_removed_and_which_restored() -> None:
    # The undoing's own changes: deleting a file the turn added, adding back one it deleted.
    undone = [Change("deleted", "docs/usage.md"), Change("added", "notes.txt")]

    assert _describe_undo(undone) == (
        "Removed docs/usage.md, which was new; restored notes.txt to how it was."
    )
    assert _describe_undo([Change("changed", "a.py"), Change("added", "b.py")]) == (
        "Restored a.py, b.py to how they were."
    )


STATUS = "claude-opus-5-5 · default · context 3k · $0.01"


@pytest.mark.parametrize("width", [200, 80, 50, 30, 12, 3])
def test_the_toolbar_fits_the_terminal(width: int) -> None:
    line = toolbar_line(STATUS, width)

    assert len(line) <= max(width - 1, 2)
    assert line.startswith(" claude-" if width > 10 else " ")


def test_the_toolbar_drops_hints_before_the_status() -> None:
    assert toolbar_line(STATUS, 200).endswith("@ file · / commands")
    assert toolbar_line(STATUS, 62) == f" {STATUS} · Enter sends"
    assert toolbar_line(STATUS, 30) == " claude-opus-5-5 · default"
    assert toolbar_line(STATUS, 12) == " claude-op…"
    assert toolbar_line("", 30) == " Enter sends"

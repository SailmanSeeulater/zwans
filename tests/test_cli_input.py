import asyncio
from pathlib import Path

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from zwans.cli.commands import COMMANDS, Commands, Quit, Reopen, is_command
from zwans.cli.input import MAX_FILE_CHARS, ChatCompleter, Composer, expand_mentions
from zwans.config import Config
from zwans.messages import TextBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.runtime import OpenedSession, open_session


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
    (workspace / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")

    mentions = expand_mentions("Look at @big.txt and @logo.png", workspace)

    assert mentions.files == []
    assert "too long to send" in mentions.problems[0]
    assert "isn't a text file" in mentions.problems[1]


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
        await commands.run("/cost")
        assert await commands.run("/nope") is None
        assert await commands.run("/exit") == Quit()

    asyncio.run(go())
    out = capsys.readouterr().out
    assert "Nothing to compact yet" in out
    assert "Summary of it all." in opened.session.messages[0].content[0].model_dump_json()
    assert opened.model == "claude-sonnet-5-5"
    assert opened.store.get(opened.id).model == "claude-sonnet-5-5"  # resuming keeps it
    assert "Session: " in out and "Context: about" in out
    assert "There's no /nope" in out
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
    assert asyncio.run(commands.run("/clear")) == Reopen(resume=None)
    asyncio.run(opened.close())

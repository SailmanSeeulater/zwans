import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from typer.testing import CliRunner, Result

import zwans.cli.app as cli_app
from zwans import __version__
from zwans.cli.app import _replay, app
from zwans.cli.attach import AttachError
from zwans.cli.commands import Commands, Reopen
from zwans.messages import Message, TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.runtime import OpenedSession
from zwans.store import SessionStore


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"zwans {__version__}"


def test_run_does_the_task_and_writes_a_transcript(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    write = ToolUseBlock(id="call_1", name="Write", input={"path": "hello.txt", "content": "hi\n"})
    script = [
        ModelResponse(content=[TextBlock(text="Writing it."), write], stop_reason="tool_use"),
        ModelResponse(content=[TextBlock(text="Done.")], stop_reason="end_turn"),
    ]
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps([r.model_dump(mode="json") for r in script]), "utf-8")
    transcripts = tmp_path / "home" / "transcripts"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "Say hi in a file",
            "-w",
            str(workspace),
            "--mode",
            "auto",
            "--fake-script",
            str(script_path),
        ],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )

    assert result.exit_code == 0, result.output
    assert (workspace / "hello.txt").read_text(encoding="utf-8") == "hi\n"
    assert "> Write hello.txt" in result.output
    assert "Session cost: $0.0000" in result.output
    [transcript] = transcripts.glob("*.jsonl")
    lines = transcript.read_text(encoding="utf-8").splitlines()
    types = [json.loads(line)["type"] for line in lines]
    assert types[0] == "turn_started"
    assert types[-1] == "turn_ended"


def test_without_a_terminal_ask_mode_refuses_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    write = ToolUseBlock(id="call_1", name="Write", input={"path": "hello.txt", "content": "hi\n"})
    script = [
        ModelResponse(content=[write], stop_reason="tool_use"),
        ModelResponse(content=[TextBlock(text="I couldn't.")], stop_reason="end_turn"),
    ]
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps([r.model_dump(mode="json") for r in script]), "utf-8")

    result = CliRunner().invoke(
        app,
        ["run", "Say hi in a file", "-w", str(workspace), "--fake-script", str(script_path)],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )

    assert result.exit_code == 0, result.output
    assert not (workspace / "hello.txt").exists()
    assert "mode ask" in result.output
    assert "! Not run: Write hello.txt changes files" in result.output


def test_an_untrusted_workspace_policy_cant_loosen_the_rules(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    (workspace / ".zwans").mkdir(parents=True)
    (workspace / ".zwans" / "policy.toml").write_text('mode = "auto"\n')
    script_path = tmp_path / "script.json"
    done = ModelResponse(content=[TextBlock(text="Hi.")], stop_reason="end_turn")
    script_path.write_text(json.dumps([done.model_dump(mode="json")]), "utf-8")

    result = CliRunner().invoke(
        app,
        ["run", "Hi", "-w", str(workspace), "--fake-script", str(script_path)],
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )

    assert result.exit_code == 0, result.output
    assert 'mode "auto"' in result.output
    assert "Ignoring those parts" in result.output
    assert "mode ask" in result.output


def test_run_explains_a_missing_credential(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["run", "Hi", "-w", str(tmp_path)],
        env={
            "ZWANS_AUTH": "api_key",
            "ANTHROPIC_API_KEY": "",
            "ZWANS_HOME": str(tmp_path),
        },
    )

    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output


def _script(path: Path, *texts: str) -> Path:
    responses = [ModelResponse(content=[TextBlock(text=t)], stop_reason="end_turn") for t in texts]
    path.write_text(json.dumps([r.model_dump(mode="json") for r in responses]), "utf-8")
    return path


def test_sessions_are_saved_listed_and_resumed(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()

    first = _script(tmp_path / "first.json", "Hi.")
    started = runner.invoke(
        app, ["run", "Say hi", "-w", str(workspace), "--fake-script", str(first)], env=env
    )
    listing = runner.invoke(app, ["sessions"], env=env)
    session_id = listing.output.split()[0]
    second = _script(tmp_path / "second.json", "Hi again.")
    resumed = runner.invoke(
        app, ["run", "Again", "--resume", session_id, "--fake-script", str(second)], env=env
    )
    relisted = runner.invoke(app, ["sessions"], env=env)

    assert started.exit_code == 0, started.output
    assert "1 turn " in listing.output
    assert "Say hi" in listing.output
    assert resumed.exit_code == 0, resumed.output
    assert f"Resumed {session_id} after 1 turn: Say hi" in resumed.output
    assert "2 turns" in relisted.output


def _chat(tmp_path: Path, typed: str, *args: str) -> Result:
    workspace = tmp_path / "work"
    workspace.mkdir(exist_ok=True)
    script = _script(tmp_path / "chat.json", "Hi.")
    return CliRunner().invoke(
        app,
        ["-w", str(workspace), "--fake-script", str(script), *args],
        input=typed,
        env={"ZWANS_HOME": str(tmp_path / "home")},
    )


def test_a_mistyped_resume_keeps_the_chat_and_clear_says_what_it_left(tmp_path: Path) -> None:
    result = _chat(tmp_path, "Say hi\n/resume nope\n/clear\nexit\n")

    assert result.exit_code == 0, result.output
    assert "No saved session starts with 'nope'." in result.output
    assert "Left " in result.output and ", which cost $0.0000 (" in result.output
    assert "Session cost: $0.0000" in result.output  # the new session's, when quitting


def test_a_failed_switch_goes_back_to_the_session_that_was_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Commands, "_resume", lambda self, argument: Reopen(resume="gone"))

    result = _chat(tmp_path, "Say hi\n/resume gone\nexit\n")

    assert result.exit_code == 0, result.output
    assert "No saved session starts with 'gone'." in result.output
    assert "Resumed " in result.output and "after 1 turn: Say hi" in result.output


def test_resuming_a_chat_shows_where_it_left_off(tmp_path: Path) -> None:
    started = _chat(tmp_path, "Say hi\nexit\n")
    session_id = started.output.split("zwans --resume ")[1].split()[0]

    resumed = _chat(tmp_path, "exit\n", "--resume", session_id)

    assert resumed.exit_code == 0, resumed.output
    assert "after 1 turn: Say hi\n\n> Say hi\nHi.\n" in resumed.output


def test_undo_in_the_chat_goes_back_without_the_whole_banner(tmp_path: Path) -> None:
    result = _chat(tmp_path, "Say hi\n/undo\nexit\n")

    assert result.exit_code == 0, result.output
    assert "Went back to before turn 1." in result.output
    assert result.output.count(f"Zwans {__version__} |") == 1


def test_the_replay_shows_the_last_turns_and_a_stop_hooks_note_as_a_note(
    capsys: pytest.CaptureFixture[str],
) -> None:
    messages = []
    for turn in range(1, 5):
        messages += [
            Message(role="user", content=[TextBlock(text=f"Task {turn}")], turn=turn),
            Message(role="assistant", content=[TextBlock(text=f"Answer {turn}.")], turn=turn),
        ]
    note = "A stop hook says the task isn't finished yet:\ntests fail"
    messages += [
        Message(role="user", content=[TextBlock(text=note)], turn=4),
        Message(role="assistant", content=[TextBlock(text="Fixed.")], turn=4),
    ]
    session = SimpleNamespace(turn=4, messages=messages)

    _replay(cast(OpenedSession, SimpleNamespace(session=session)))

    out = capsys.readouterr().out
    assert "(Earlier turns aren't shown.)" in out and "Task 1" not in out
    assert "> Task 2\nAnswer 2.\n" in out and "> Task 4\nAnswer 4.\n" in out
    assert "  A stop hook says the task isn't finished yet:\nFixed.\n" in out
    assert "> A stop hook" not in out


def test_sessions_lists_only_used_sessions_in_aligned_columns(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json", "One.", "Two.")
    args = ["-w", str(workspace), "--fake-script", str(script)]

    started = runner.invoke(app, ["run", "First line\n\nand more", *args], env=env)
    session_id = runner.invoke(app, ["sessions"], env=env).output.split()[0]
    runner.invoke(app, ["run", "Again", "--resume", session_id, *args], env=env)
    unused = runner.invoke(app, args, env=env, input="")  # a chat closed without a word
    listing = runner.invoke(app, ["sessions"], env=env)

    assert started.exit_code == 0, started.output
    assert unused.exit_code == 0, unused.output
    assert "To continue it" not in unused.output
    [row] = listing.output.splitlines()
    assert "   2 turns  $ 0.0000" in row
    assert str(workspace)[-10:] in row
    assert row.endswith("  First line")


def test_rewind_from_the_command_line_says_the_files_were_kept(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json", "One.", "Two.", "Three.")
    args = ["-w", str(workspace), "--fake-script", str(script)]
    runner.invoke(app, ["run", "First", *args], env=env)
    session_id = runner.invoke(app, ["sessions"], env=env).output.split()[0]
    runner.invoke(app, ["run", "Second", "--resume", session_id, *args], env=env)

    resume = ["--resume", session_id]
    too_far = runner.invoke(app, ["run", "Hi", *resume, "--rewind", "2", *args], env=env)
    rewound = runner.invoke(app, ["run", "Third", *resume, "--rewind", "1", *args], env=env)

    assert too_far.exit_code == 2
    assert "has 2 turns, so there are no turns after turn 2 to drop" in too_far.output
    assert rewound.exit_code == 0, rewound.output
    assert "Turns after turn 1 were dropped from the conversation" in rewound.output
    assert "The files were left as they are." in rewound.output


def test_a_bad_setting_is_reported_without_a_traceback(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["run", "Hi", "-w", str(tmp_path)],
        env={"ZWANS_HOME": str(tmp_path), "ZWANS_AUTH": "oauth"},
    )

    assert result.exit_code == 2
    assert "ZWANS_AUTH: Input should be 'api_key' or 'subscription'" in result.output


def test_a_turn_that_fails_before_any_reply_leaves_no_session(tmp_path: Path) -> None:
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json")  # an empty script fails like an API error

    failed = runner.invoke(
        app, ["run", "Hi", "-w", str(tmp_path), "--fake-script", str(script)], env=env
    )
    listing = runner.invoke(app, ["sessions"], env=env)

    assert failed.exit_code == 1
    assert "ran out of scripted responses" in failed.output
    assert "[stopped: error]" not in failed.output  # the error line has said why
    assert "To continue it" not in failed.output
    assert listing.output.strip() == "No saved sessions yet."


def test_resume_says_it_ignores_another_workspace(tmp_path: Path) -> None:
    workspace, other = tmp_path / "work", tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json", "Hi.")
    args = ["--fake-script", str(script)]
    runner.invoke(app, ["run", "Hi", "-w", str(workspace), *args], env=env)
    session_id = runner.invoke(app, ["sessions"], env=env).output.split()[0]

    elsewhere = runner.invoke(
        app, ["run", "Again", "--resume", session_id, "-w", str(other), *args], env=env
    )
    same = runner.invoke(
        app, ["run", "Again", "--resume", session_id, "-w", str(workspace), *args], env=env
    )

    assert elsewhere.exit_code == 0, elsewhere.output
    assert f"works in {workspace.resolve()}, so -w {other.resolve()} is ignored." in (
        elsewhere.output
    )
    assert same.exit_code == 0, same.output
    assert "is ignored" not in same.output


def test_switching_to_another_session_in_the_chat_keeps_its_model(tmp_path: Path) -> None:
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json", "Hi.")
    args = ["-w", str(tmp_path), "--fake-script", str(script)]
    runner.invoke(app, ["run", "Hi", "--model", "claude-haiku-4-5", *args], env=env)
    session_id = runner.invoke(app, ["sessions"], env=env).output.split()[0]

    chat = runner.invoke(app, args, env=env, input=f"Hello\n/resume {session_id}\n")

    assert chat.exit_code == 0, chat.output
    assert f"Resumed {session_id}" in chat.output
    store = SessionStore(tmp_path / "home" / "sessions.db")
    assert store.get(session_id).model == "claude-haiku-4-5"
    store.close()


def test_titles_and_prompts_with_escape_codes_are_shown_as_text(tmp_path: Path) -> None:
    # A prompt can come from the web UI, another terminal or a script, and becomes the title.
    workspace = tmp_path / "work"
    workspace.mkdir()
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    script = _script(tmp_path / "script.json", "Hi.")
    args = ["-w", str(workspace), "--fake-script", str(script)]
    started = runner.invoke(app, ["run", "Say\x1b[2J hi\rthere", *args], env=env)
    listing = runner.invoke(app, ["sessions"], env=env)
    session_id = listing.output.split()[0]

    resumed = _chat(tmp_path, "exit\n", "--resume", session_id)

    assert started.exit_code == 0, started.output
    # CliRunner drops raw escape codes, so check that they were shown as text instead.
    assert listing.output.rstrip().endswith("  Say\\x1b[2J hi there")
    assert "after 1 turn: Say\\x1b[2J hi there\n" in resumed.output
    assert "\n> Say\\x1b[2J hi\\x0dthere\nHi.\n" in resumed.output


def test_an_mcp_servers_problem_is_shown_as_text(tmp_path: Path) -> None:
    # The problem can quote what the server said, or its command, which a project can set.
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.odd]\ncommand = "no-such\\u001b[2K"\n', "utf-8")
    script = _script(tmp_path / "script.json", "Hi.")
    env = {"ZWANS_HOME": str(tmp_path / "home"), "ZWANS_CONFIG": str(config)}

    result = CliRunner().invoke(
        app, ["run", "Hi", "-w", str(tmp_path), "--fake-script", str(script)], env=env
    )

    assert result.exit_code == 0, result.output
    assert "MCP server skipped: odd: couldn't start no-such\\x1b[2K: " in result.output


def test_attach_shows_the_servers_status_and_errors_as_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = {
        "id": "s1",
        "model": "m",
        "mode": "ask",
        "workspace": "/w\x1b[2K",
        "warnings": ["MCP server skipped: bad\x1b]0;x\x07"],
    }

    class Detached:
        def __init__(self, *args: object) -> None:
            pass

        async def run(self) -> None:
            pass

    def refuse(*args: object) -> dict[str, object]:
        raise AttachError("No saved session starts with 'x\x1b[2K'.")

    monkeypatch.setattr(cli_app, "read_server_file", lambda home: {"url": "u", "token": "t"})
    monkeypatch.setattr(cli_app, "Attached", Detached)
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    monkeypatch.setattr(cli_app, "open_remote", lambda *args: status)
    shown = CliRunner().invoke(app, ["attach"], env=env)
    monkeypatch.setattr(cli_app, "open_remote", refuse)
    refused = CliRunner().invoke(app, ["attach", "x"], env=env)

    assert shown.exit_code == 0, shown.output
    assert "| /w\\x1b[2K\n" in shown.output
    assert "MCP server skipped: bad\\x1b]0;x\\x07\n" in shown.output
    assert refused.exit_code == 2
    assert "starts with 'x\\x1b[2K'." in refused.output

import json
from pathlib import Path

from typer.testing import CliRunner

from zwans import __version__
from zwans.cli.app import app
from zwans.messages import TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse


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
        ["run", "Say hi in a file", "-w", str(workspace), "--fake-script", str(script_path)],
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

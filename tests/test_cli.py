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
    transcripts = tmp_path / "transcripts"

    result = CliRunner().invoke(
        app,
        ["run", "Say hi in a file", "-w", str(workspace), "--fake-script", str(script_path)],
        env={"ZWANS_TRANSCRIPT_DIR": str(transcripts)},
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
            "ZWANS_TRANSCRIPT_DIR": str(tmp_path),
        },
    )

    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output

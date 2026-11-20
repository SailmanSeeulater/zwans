"""Stands in for `codex exec --json` in tests. FAKE_CODEX_MODE picks what it does:
fix (fix buggy-calc and report like Codex), costly (the same, with lots of tokens), fail
(the turn fails), sleep, or crash."""

import json
import os
import sys
import time
from pathlib import Path


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def item(item_id: str, kind: str, **fields: object) -> dict[str, object]:
    return {"type": "item.completed", "item": {"id": item_id, "type": kind, **fields}}


def main() -> None:
    args = sys.argv[1:]
    assert args[:2] == ["exec", "--json"], args
    assert "--dangerously-bypass-approvals-and-sandbox" in args
    assert os.environ["CODEX_API_KEY"] == "test-key"
    assert "OPENAI_API_KEY" not in os.environ
    home = Path(os.environ["CODEX_HOME"])
    assert home.is_dir() and not any(home.iterdir()), "CODEX_HOME should start empty"
    mode = os.environ.get("FAKE_CODEX_MODE", "fix")
    if mode == "sleep":
        time.sleep(30)
    if mode == "crash":
        print("boom: something went wrong", file=sys.stderr)
        sys.exit(1)

    emit({"type": "thread.started", "thread_id": "thread_1"})
    emit({"type": "turn.started"})
    if mode == "fail":
        emit({"type": "turn.failed", "error": {"message": "model not found"}})
        sys.exit(1)
    emit(item("item_0", "reasoning", text="Look at calc.py first."))
    emit(
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "cat calc.py",
                "status": "in_progress",
            },
        }
    )
    emit(
        item(
            "item_1",
            "command_execution",
            command="cat nope.py",
            aggregated_output="",
            exit_code=1,
            status="failed",
        )
    )
    calc = Path("calc.py")
    calc.write_text(calc.read_text("utf-8").replace("(len(numbers) + 1)", "len(numbers)"), "utf-8")
    emit(
        item(
            "item_2",
            "file_change",
            changes=[{"path": "calc.py", "kind": "update"}],
            status="completed",
        )
    )
    emit(item("item_3", "agent_message", text="Fixed the average."))
    tokens = 1_000_000 if mode == "costly" else 10_000
    emit(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": tokens + 30_000,
                "cached_input_tokens": 30_000,
                "output_tokens": 2_000,
                "reasoning_output_tokens": 1_500,
            },
        }
    )


if __name__ == "__main__":
    main()

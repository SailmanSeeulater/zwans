"""Stands in for `claude -p` in tests. FAKE_CLAUDE_MODE picks what it does:
fix (fix buggy-calc and report like Claude Code), sleep, or crash."""

import json
import os
import sys
import time
from pathlib import Path


def emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)


def tool_use(message_id: str, call_id: str) -> dict[str, object]:
    block = {"type": "tool_use", "id": call_id, "name": "Edit", "input": {}}
    return {"type": "assistant", "message": {"id": message_id, "content": [block]}}


def tool_result(call_id: str, is_error: bool) -> dict[str, object]:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": "", "is_error": is_error}
    return {"type": "user", "message": {"content": [block]}}


def main() -> None:
    assert "--bare" in sys.argv
    assert os.environ["ANTHROPIC_API_KEY"] == "test-key"
    mode = os.environ.get("FAKE_CLAUDE_MODE", "fix")
    if mode == "sleep":
        time.sleep(30)
    if mode == "crash":
        print("boom: something went wrong", file=sys.stderr)
        sys.exit(1)

    emit({"type": "system", "subtype": "init"})
    emit(tool_use("msg_1", "call_1"))
    emit(tool_result("call_1", is_error=True))
    emit(tool_use("msg_2", "call_2"))
    calc = Path("calc.py")
    calc.write_text(calc.read_text("utf-8").replace("(len(numbers) + 1)", "len(numbers)"), "utf-8")
    emit(tool_result("call_2", is_error=False))
    text = {"type": "text", "text": "Fixed."}
    emit({"type": "assistant", "message": {"id": "msg_3", "content": [text]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.12})


if __name__ == "__main__":
    main()
